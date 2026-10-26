"""The shopping agent: one Claude conversation per customer session, with
tools that act on the authoritative ledger and basket.

Each turn the model gets the recent conversation (text only), the customer's
message, and a fresh system message with the authoritative shopping state.
Within a turn, history is append-only so thinking stays valid. After the
model answers, a grounding check verifies every amount of money and every
"added to your basket" claim against what actually happened; if something
doesn't match, the model gets one chance to correct its reply.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import anthropic

from . import basket as B
from . import presenter, taxonomy
from .db import ConcurrentUpdate, Repo, Scope
from .ledger import Ledger, compact_need
from .tools import TOOLS, ToolError, Turn, budget_status, execute, plan_lines

MODEL = "claude-opus-5-5"
HISTORY_TURNS = 12          # recent text turns kept verbatim; the ledger carries everything older
MAX_STEPS = 12              # model calls per customer message
TURN_DEADLINE_S = 120

SYSTEM = """You are the shopping assistant for {store}, an online supermarket in Pakistan. Customers write in English, Roman Urdu, Urdu or a mix, often with misspellings. Your job is to understand what they are trying to get done and help them finish it: find the right products, choose between them, plan within budget, and fill their basket.

How you work
- Understand the goal before searching. Turn what the customer says into needs with update_needs, then search them all with one find_products call. A request like "biryani for 6" becomes its ingredients; "weekly groceries for 4" becomes a staple list with household {{people: 4, days: 7}}; "my budget is 5000" is a budget, not a product.
- Each need names the taxonomy kinds that truly satisfy it. Matching a word in a product name is not enough: chocolate spread or nutrition powder is not milk, potato chips are not potatoes, chaat masala is not biryani masala. If only a related product exists, say so and offer it as a clearly labelled substitute (allow_substitutes), never silently.
- When the customer corrects something ("not Olpers", "make the rice basmati", "remove the oil"), change only that need by its id. Everything else stays as it was.
- Ask a question only when the answer changes what you would buy (household size for a weekly plan, an allergy, two very different options). Ask at most two at a time, and still show what you can.
- Help the customer decide. For each need, pick a sensible default (choose_products) and explain any real trade-off in a few words: price per kg, brand, size. Show options (show type "options") only when they genuinely need to choose. Don't repeat products from earlier turns unless they asked.
- A plan is a proposal. The basket only changes when the customer asks ("add them", "haan daal do", "make it 2"); then call update_basket and report only the changes it returns. Customers can also use the buttons on product cards; the state message tells you when the basket changed that way.
- Be honest about gaps. find_products tells you whether the store doesn't carry something (not_in_catalog), has it but not available or not matching (none_eligible), or only has substitutes. Say which, briefly, and offer the closest alternative when there is one.
- Quantities from find_products (suggested_packs) for a household are rough estimates. Call them estimates; never claim they are nutritionally sufficient.

Facts and numbers
- Only state prices, totals, sizes and stock that a tool returned in this turn or that appear in the state message. Never compute totals yourself; use plan_total, line_total and the budget figures the tools give you. Write money as "Rs 1,250".
- Product cards are shown automatically under your reply for the plan and the basket. Don't re-list every line in text; mention what matters (total, budget left, substitutions, what's missing).

Style
- Reply in the customer's language and script: Roman Urdu if they write Roman Urdu, Urdu script if they write Urdu, English otherwise. Match their tone.
- Be warm and brief: a sentence or two plus a short list when useful. No internal terms (ledger, need id, kind, tool names, status codes).
- Refer to displayed options by their number or name the way the customer did ("option 2", "the cheaper one").

Product kinds (id: label)
{kinds}
"""

_MONEY = re.compile(
    r"(?:rs\.?|pkr|₨|rupees?|روپے)\s*([0-9][0-9,]*(?:\.[0-9]+)?)|([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:/-|rs\b\.?|pkr\b|rupees?\b|روپے)",
    re.IGNORECASE)
_BASKET_CLAIM = re.compile(
    r"((?:i(?:'ve| have)? )?added|add kar (?:diya|di|diye|dia)|daal (?:diya|di|diye|dia)|dal (?:diya|di|diye|dia)|shamil kar (?:diya|di|diye))"
    r"[^.\n!?]{0,50}(basket|cart|tokri|ٹوکری)|(basket|cart|tokri)[^.\n!?]{0,30}(added|add kar (?:diya|di|diye)|daal (?:diya|di|diye))|ٹوکری میں شامل",
    re.IGNORECASE)


@dataclass
class Result:
    reply: str
    cards: list[dict]
    basket: dict
    steps: list[str] = field(default_factory=list)
    grounding: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)


class Agent:
    def __init__(self, repo: Repo, client: Any | None = None, model: str = MODEL, effort: str = "medium"):
        self.repo = repo
        self.client = client or anthropic.Anthropic(max_retries=2, timeout=60)
        self.model = model
        self.effort = effort
        self._system_cache: dict[str, str] = {}

    def system_prompt(self, scope: Scope) -> str:
        if scope.store_id not in self._system_cache:
            self._system_cache[scope.store_id] = SYSTEM.format(store=self.repo.store_name(scope), kinds=taxonomy.catalog_prompt())
        return self._system_cache[scope.store_id]

    # ------------------------------------------------------------------ turn

    def handle(self, scope: Scope, session_id: str, text: str, emit: Callable[[dict], None] | None = None) -> Result:
        emit = emit or (lambda e: None)
        started = time.monotonic()
        raw_ledger, history, version = self.repo.load_session(scope, session_id)
        ledger = Ledger.from_dict(raw_ledger)
        ledger.turn += 1
        turn = Turn(self.repo, scope, session_id, ledger)

        messages: list[dict] = _recent(history)
        messages.append({"role": "user", "content": text})
        messages.append({"role": "system", "content": self.state_message(turn)})
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0, "model_calls": 0}

        reply = self._run(turn, messages, emit, started, usage)
        grounding = check_grounding(reply, turn, text)
        if grounding["issues"] and time.monotonic() - started < TURN_DEADLINE_S - 20:
            emit({"type": "status", "text": "Double-checking the details"})
            messages.append({"role": "user", "content": "[Store check, not from the customer] Your reply has problems: "
                             + "; ".join(grounding["issues"])
                             + ". Rewrite the reply for the customer using only figures and changes the tools reported. Do not mention this check."})
            reply = self._run(turn, messages, emit, started, usage)
            second = check_grounding(reply, turn, text)
            grounding = {"issues": second["issues"], "corrected": grounding["issues"]}

        cards = presenter.build(turn)
        basket = B.view(self.repo, scope, session_id)
        ledger.seen_basket_revision = basket["revision"]
        history = history + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        try:
            self.repo.save_session(scope, session_id, ledger.to_dict(), history[-4 * HISTORY_TURNS:], version)
        except ConcurrentUpdate:
            # Another message from this session finished first; its ledger wins and this reply is still shown.
            grounding.setdefault("issues", []).append("session saved concurrently; this turn's plan changes were not stored")
        return Result(reply, cards, basket, turn.steps, grounding, usage)

    def _run(self, turn: Turn, messages: list[dict], emit, started: float, usage: dict) -> str:
        final_text = ""
        for _ in range(MAX_STEPS):
            if time.monotonic() - started > TURN_DEADLINE_S:
                return final_text or "Sorry, that took too long on my side. Could you send that again?"
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=[{"type": "text", "text": self.system_prompt(turn.scope), "cache_control": {"type": "ephemeral"}}],
                tools=TOOLS,
                messages=messages,
                output_config={"effort": self.effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            _add_usage(usage, response)
            messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "refusal":
                return "Sorry, I can't help with that. Is there something from the store I can find for you?"
            texts = [b.text for b in response.content if getattr(b, "type", "") == "text" and b.text.strip()]
            if texts:
                final_text = "\n\n".join(texts).strip()
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                break
            results = []
            for block in response.content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                emit({"type": "status", "text": _status_label(block.name, block.input, turn)})
                try:
                    output = execute(turn, block.name, dict(block.input or {}))
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output, ensure_ascii=False)})
                except (ToolError, B.BasketError, TypeError, ValueError, KeyError) as e:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {e}", "is_error": True})
            messages.append({"role": "user", "content": results})
        return final_text or "Sorry, something went wrong on my side. Could you say that again?"

    # ----------------------------------------------------------------- state

    def state_message(self, turn: Turn) -> str:
        L = turn.ledger
        basket = B.view(self.repo, turn.scope, turn.session_id)
        lines = plan_lines(turn)
        turn.money(basket["total"], *[i["line_total"] for i in basket["items"]], *[i["unit_price"] for i in basket["items"]],
                   *[l["line_total"] for l in lines], *[l["unit_price"] for l in lines], sum(l["line_total"] for l in lines))
        state: dict[str, Any] = {
            "needs": [compact_need(n) for n in L.active_needs()],
            "plan_total": round(sum(l["line_total"] for l in lines), 2),
            "budgets": budget_status(turn),
            "household": L.household or None,
            "preferences": L.preferences or None,
            "basket": {"items": [{"name": i["name"], "product_id": i["product_id"], "quantity": i["quantity"], "line_total": i["line_total"],
                                  **({"issue": i["issue"]} if i.get("issue") else {})} for i in basket["items"]],
                       "total": basket["total"]},
            "displayed_last_turn": [{"ref": d["ref"], "name": d["name"], "product_id": d["product_id"], "need_id": d["need_id"]}
                                    for d in L.displayed],
        }
        if basket["revision"] != L.seen_basket_revision and L.turn > 1:
            state["note"] = "The customer changed the basket with the card buttons since your last reply."
        if basket["problems"]:
            state["basket_problems"] = basket["problems"]
        state = {k: v for k, v in state.items() if v not in (None, [], {})}
        return "Authoritative shopping state (from the store, not the customer):\n" + json.dumps(state, ensure_ascii=False)


# ---------------------------------------------------------------- grounding

def check_grounding(reply: str, turn: Turn, customer_text: str) -> dict:
    issues = []
    allowed = set(turn.amounts)
    for m in re.finditer(r"[0-9][0-9,]*(?:\.[0-9]+)?", customer_text):
        allowed.add(round(float(m.group(0).replace(",", "")), 2))
    vals = sorted(allowed)
    bad = []
    for m in _MONEY.finditer(reply):
        amount = float((m.group(1) or m.group(2)).replace(",", ""))
        if any(abs(amount - a) <= 1 for a in vals):
            continue
        if any(abs(amount - abs(a - b)) <= 1 for i, a in enumerate(vals) for b in vals[i + 1:]):
            continue  # a difference of two reported figures, e.g. a saving
        bad.append(m.group(0).strip())
    if bad:
        issues.append(f"these amounts were not reported by the store: {', '.join(sorted(set(bad)))}")
    if _BASKET_CLAIM.search(reply) and not turn.basket_changes:
        issues.append("it says items were added to the basket, but the basket did not change this turn")
    return {"issues": issues}


# ------------------------------------------------------------------ helpers

def _recent(history: list[dict]) -> list[dict]:
    msgs = history[-2 * HISTORY_TURNS:]
    while msgs and msgs[0]["role"] != "user":
        msgs = msgs[1:]
    return [dict(m) for m in msgs]


def _add_usage(usage: dict, response) -> None:
    u = getattr(response, "usage", None)
    usage["model_calls"] += 1
    if u is None:
        return
    for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
        usage[k] += getattr(u, k, 0) or 0


def _status_label(name: str, args: dict, turn: Turn) -> str:
    if name == "find_products":
        labels = [turn.ledger.get(i).label for i in args.get("need_ids", []) if turn.ledger.get(i)]
        return "Looking for " + ", ".join(labels[:4]) + ("…" if len(labels) > 4 else "") if labels else "Searching the store"
    return {"update_needs": "Understanding your list", "choose_products": "Picking the best options", "show": "Preparing products",
            "update_basket": "Updating your basket", "browse_catalog": "Browsing the store"}.get(name, "Working on it")
