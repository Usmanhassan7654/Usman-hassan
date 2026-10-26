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

from . import basket as B
from . import llm, presenter, taxonomy
from .db import ConcurrentUpdate, Repo, Scope
from .ledger import Ledger, compact_need
from .tools import TOOLS, ToolError, Turn, budget_status, execute, plan_lines

HISTORY_TURNS = 12          # recent text turns kept verbatim; the ledger carries everything older
MAX_STEPS = 12              # model calls per customer message
TURN_DEADLINE_S = 120

SYSTEM = """You are the shopping assistant for {store}, an online supermarket in Pakistan. Customers write English, Roman Urdu, Urdu or a mix, with typos. Help them get their shopping done.

Workflow
1. Call update_needs once with every product the customer needs. A recipe becomes its ingredients; "weekly groceries for 4" becomes staples plus household {{people: 4, days: 7}}; a budget is a budget, not a product. It searches the store and proposes a product for each need, with alternatives.
2. Then reply. Use choose_products only to switch a pick, find_products only to search again (e.g. prefer "cheapest" for a budget), and show type "options" only when the customer must choose between very different products.
3. Change the basket (update_basket) only when the customer asks, e.g. "add karo", "daal do", "remove the oil".

Rules
- A need is filled only by products of its kind: chocolate spread or milk powder is not milk, chips are not potatoes, chaat masala is not biryani masala. Offer a related product only as a clearly labelled substitute.
- Corrections ("Olpers nahi", "basmati wala"): update only that need, by its id.
- If a result is not_in_catalog or none_eligible, say briefly that the store doesn't have it or it's unavailable, and offer the closest alternative if there is one.
- Ask a question only when the answer changes what you would buy; at most two.
- Use only prices and totals that tools returned or that appear in the store state; never add them up yourself. Write money as "Rs 1,250". Household quantities are estimates.
- Cards with the plan and basket appear under your reply, so don't repeat every line; mention the total, the budget, substitutions and anything missing.
- Reply in the customer's language and script (Roman Urdu for Roman Urdu, Urdu script for Urdu), warm and brief. Never mention tools, ids, kinds or other internal terms.

Kind ids: {kinds}
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
    """`model` is any llm.ChatModel (Groq, Gemini, Claude or a fallback chain).

    For tests, `client` accepts an Anthropic-style client and wraps it in the Claude adapter.
    """

    def __init__(self, repo: Repo, model: llm.ChatModel | None = None, client: Any | None = None, effort: str = "medium"):
        self.repo = repo
        if client is not None:
            model = llm.AnthropicModel(effort=effort, client=client)
        self.model = model or llm.build(effort=effort)
        self._system_cache: dict[str, str] = {}

    @property
    def client(self):  # tests swap the scripted client between turns
        return self.model.client

    @client.setter
    def client(self, client) -> None:
        self.model = llm.AnthropicModel(effort=getattr(self.model, "effort", "medium"), client=client)

    def system_prompt(self, scope: Scope) -> str:
        if scope.store_id not in self._system_cache:
            self._system_cache[scope.store_id] = SYSTEM.format(store=self.repo.store_name(scope), kinds=", ".join(k.id for k in taxonomy.KINDS))
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
        messages.append({"role": "state", "content": self.state_message(turn)})
        usage = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "model_calls": 0, "models": [], "errors": []}

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
            try:
                reply = self.model.complete(self.system_prompt(turn.scope), messages, TOOLS)
            except llm.LLMError as e:
                usage["errors"].append(str(e))
                return final_text or "Sorry, I'm having trouble reaching my assistant service right now. Please try again in a minute."
            _add_usage(usage, reply)
            messages.append({"role": "assistant", "content": reply.text, "tool_calls": reply.tool_calls, "raw": reply.raw})
            if reply.stop == "refusal":
                return "Sorry, I can't help with that. Is there something from the store I can find for you?"
            if reply.text:
                final_text = reply.text
            if reply.stop == "pause":
                continue
            if reply.stop != "tool_use":
                break
            for call in reply.tool_calls:
                emit({"type": "status", "text": _status_label(call["name"], call["args"], turn)})
                try:
                    if "__invalid_arguments__" in call["args"]:
                        raise ToolError("The arguments were not valid JSON. Send them again as a JSON object.")
                    output = execute(turn, call["name"], dict(call["args"]))
                    messages.append({"role": "tool", "id": call["id"], "name": call["name"],
                                     "content": json.dumps(output, ensure_ascii=False)})
                except (ToolError, B.BasketError, TypeError, ValueError, KeyError) as e:
                    messages.append({"role": "tool", "id": call["id"], "name": call["name"], "content": f"Error: {e}", "is_error": True})
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


def _add_usage(usage: dict, reply: llm.Reply) -> None:
    usage["model_calls"] += 1
    for k in ("input_tokens", "output_tokens", "cached_tokens"):
        usage[k] += reply.usage.get(k, 0)
    if reply.model and reply.model not in usage["models"]:
        usage["models"].append(reply.model)


def _status_label(name: str, args: dict, turn: Turn) -> str:
    if name == "find_products":
        labels = [turn.ledger.get(i).label for i in args.get("need_ids", []) if turn.ledger.get(i)]
        return "Looking for " + ", ".join(labels[:4]) + ("…" if len(labels) > 4 else "") if labels else "Searching the store"
    return {"update_needs": "Understanding your list", "choose_products": "Picking the best options", "show": "Preparing products",
            "update_basket": "Updating your basket", "browse_catalog": "Browsing the store"}.get(name, "Working on it")
