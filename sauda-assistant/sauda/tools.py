"""The agent's tools. Each one validates its input, acts on the ledger or the
basket through application code, and returns compact facts.

A Turn collects what happened during one customer message: which cards to
show, whether the basket changed, and every amount of money the tools
reported, so the reply can be checked against them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import basket as B
from . import retrieval as R
from . import suitability as S
from . import taxonomy
from .db import Repo, Scope
from .ledger import Budget, Constraints, Ledger, Need, compact_need

MAX_NEEDS_PER_SEARCH = 12


class ToolError(Exception):
    pass


@dataclass
class Turn:
    repo: Repo
    scope: Scope
    session_id: str
    ledger: Ledger
    cards: list[dict] = field(default_factory=list)       # presentation blocks for this turn
    amounts: set[float] = field(default_factory=set)      # every money figure the tools reported
    basket_changes: list[dict] = field(default_factory=list)
    selections_changed: bool = False
    steps: list[str] = field(default_factory=list)

    def money(self, *values) -> None:
        for v in values:
            if v is not None:
                self.amounts.add(round(float(v), 2))


# ------------------------------------------------------------------ schemas

_CONSTRAINTS = {
    "type": "object",
    "properties": {
        "brands": {"type": "array", "items": {"type": "string"}, "description": "Preferred brands."},
        "brand_required": {"type": "boolean", "description": "Only if the customer insists."},
        "exclude_brands": {"type": "array", "items": {"type": "string"}},
        "exclude_terms": {"type": "array", "items": {"type": "string"}, "description": "e.g. ['flavoured']"},
        "must_terms": {"type": "array", "items": {"type": "string"}, "description": "e.g. ['basmati']"},
        "max_unit_price": {"type": "number"},
    },
}

TOOLS: list[dict] = [
    {
        "name": "update_needs",
        "description": (
            "Record or correct the shopping list, household, budget and preferences, then search the store: returns, per need, a "
            "proposed product with packs and line total, a few alternatives, and the plan total. To correct a need, pass its id "
            "with only the changed fields. Budget/week/household words are not products."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "needs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Existing need id to change; omit for a new need."},
                            "label": {"type": "string", "description": "Short English name, e.g. 'Milk'."},
                            "kinds": {"type": "array", "items": {"type": "string"}, "description": "Kind ids from the list in the instructions."},
                            "search_terms": {"type": "array", "items": {"type": "string"}, "description": "English words, e.g. ['basmati']."},
                            "quantity": {"type": "object", "description": "amount+unit (kg, g, l, ml, pc, dozen) or packs.",
                                         "properties": {"amount": {"type": "number"}, "unit": {"type": "string"}, "packs": {"type": "integer"}}},
                            "purpose": {"type": "string", "description": "e.g. 'biryani for 6'"},
                            "constraints": _CONSTRAINTS,
                            "allow_substitutes": {"type": "boolean", "description": "Allow a related product, clearly labelled."},
                            "action": {"type": "string", "enum": ["upsert", "remove", "defer"]},
                        },
                    },
                },
                "household": {"type": "object", "properties": {"people": {"type": "integer"}, "days": {"type": "integer"}}},
                "budget": {"type": "object", "description": "Omit need_ids for the whole order; amount 0 clears it.",
                           "properties": {"amount": {"type": "number"}, "need_ids": {"type": "array", "items": {"type": "string"}},
                                          "label": {"type": "string"}}},
                "preferences": {"type": "object",
                                "properties": {"avoid_brands": {"type": "array", "items": {"type": "string"}},
                                               "preferred_brands": {"type": "array", "items": {"type": "string"}},
                                               "diet": {"type": "string"}, "notes": {"type": "string"}}},
                "start_over": {"type": "boolean", "description": "Clear the list and budgets (not the basket)."},
            },
        },
    },
    {
        "name": "find_products",
        "description": "Search again for needs, e.g. prefer 'cheapest' to fit a budget. update_needs already searches new or changed needs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "need_ids": {"type": "array", "items": {"type": "string"}},
                "prefer": {"type": "string", "enum": ["relevance", "cheapest"], "description": "Use 'cheapest' when fitting a budget."},
            },
            "required": ["need_ids"],
        },
    },
    {
        "name": "choose_products",
        "description": "Switch the proposed product or packs for needs (a plan, not the basket). Returns line totals, plan total and budget.",
        "input_schema": {
            "type": "object",
            "properties": {
                "choices": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"need_id": {"type": "string"}, "product_id": {"type": "string"},
                                                            "packs": {"type": "integer", "minimum": 1}},
                              "required": ["need_id", "product_id"]},
                },
                "clear_need_ids": {"type": "array", "items": {"type": "string"}, "description": "Drop the current choice for these needs."},
            },
        },
    },
    {
        "name": "show",
        "description": "Cards under your reply: 'options' (numbered choices for needs), 'plan', 'comparison' (2-4 product_ids) or 'basket'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["options", "plan", "comparison", "basket"]},
                "need_ids": {"type": "array", "items": {"type": "string"}},
                "product_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["type"],
        },
    },
    {
        "name": "update_basket",
        "description": "Change the basket, only when the customer asks. from_plan=true adds the planned lines. Report only the changes returned.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ops": {"type": "array", "items": {"type": "object", "properties": {
                    "op": {"type": "string", "enum": ["add", "set", "remove"]}, "product_id": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 0}, "need_id": {"type": "string"}}, "required": ["op", "product_id"]}},
                "from_plan": {"type": "boolean"},
                "need_ids": {"type": "array", "items": {"type": "string"}},
                "clear": {"type": "boolean"},
            },
        },
    },
    {
        "name": "browse_catalog",
        "description": "List what the store carries by kind and/or words, 10 per page.",
        "input_schema": {
            "type": "object",
            "properties": {"kind": {"type": "string"}, "query": {"type": "string"}, "page": {"type": "integer", "minimum": 1}},
        },
    },
]


# --------------------------------------------------------------- executors

def execute(turn: Turn, name: str, args: dict) -> dict:
    fn = HANDLERS.get(name)
    if not fn:
        raise ToolError(f"Unknown tool {name}.")
    if not isinstance(args, dict):
        raise ToolError("Arguments must be an object.")
    return fn(turn, args)


def _strs(v) -> list[str]:
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def update_needs(turn: Turn, a: dict) -> dict:
    L, notes, errors, touched = turn.ledger, [], [], []
    if a.get("start_over"):
        for n in L.active_needs():
            n.status = "removed"
        L.budgets, L.household = [], {}
        notes.append("Cleared the shopping task.")
    if isinstance(a.get("household"), dict):
        h = {k: int(v) for k, v in a["household"].items() if k in ("people", "days") and isinstance(v, (int, float)) and 0 < v <= 60}
        L.household.update(h)
    if isinstance(a.get("preferences"), dict):
        L.preferences.update(a["preferences"])

    for spec in a.get("needs") or []:
        if not isinstance(spec, dict):
            continue
        action = spec.get("action", "upsert")
        nid = spec.get("id")
        need = L.get(nid) if nid else None
        if nid and not need:
            errors.append(f"No active need {nid}.")
            continue
        if action in ("remove", "defer"):
            if need:
                need.status = "removed" if action == "remove" else "deferred"
                need.history.append(action + "d")
                turn.selections_changed = True
            continue
        kinds = [k for k in _strs(spec.get("kinds")) if taxonomy.get(k)]
        bad = [k for k in _strs(spec.get("kinds")) if not taxonomy.get(k)]
        if not kinds and (bad or not need):
            inferred = infer_kind(str(spec.get("label", "")), _strs(spec.get("search_terms")))
            if inferred:
                kinds = [inferred]
            elif bad:
                errors.append(f"Unknown kinds {bad} for '{spec.get('label', '')}'; closest valid: "
                              f"{sorted({c for k in bad for c in taxonomy.closest(k)})}. Not a product? Use budget/household/purpose.")
                continue
        if not need:
            if not kinds or not spec.get("label"):
                errors.append(f"Couldn't tell what product '{spec.get('label', '')}' is; give a kind id, or skip it if it isn't a product.")
                continue
            need = Need(id=L.new_id(), label=str(spec["label"]), kinds=kinds)
            L.needs.append(need)
            touched.append(need)
        else:
            change = []
            if kinds and kinds != need.kinds:
                change.append(f"kinds {need.kinds}->{kinds}")
                need.kinds = kinds
            if spec.get("label") and spec["label"] != need.label:
                change.append(f"label '{need.label}'->'{spec['label']}'")
                need.label = str(spec["label"])
            if change:
                need.history.append("; ".join(change))
        if "search_terms" in spec:
            need.search_terms = _strs(spec["search_terms"])
        if isinstance(spec.get("quantity"), dict):
            need.quantity = {k: v for k, v in spec["quantity"].items() if k in ("amount", "unit", "packs") and v not in (None, "")} or None
        if spec.get("purpose"):
            need.purpose = str(spec["purpose"])
        if isinstance(spec.get("constraints"), dict):
            c = {**need.constraints.__dict__}
            for k, v in spec["constraints"].items():
                if k in c:
                    c[k] = (_strs(v) if isinstance(c[k], list) else v)
            if c != need.constraints.__dict__:
                need.history.append("constraints updated")
            need.constraints = Constraints(**c)
        if "allow_substitutes" in spec:
            need.allow_substitutes = bool(spec["allow_substitutes"])
        if need.status in ("deferred", "missing"):
            need.status = "open"
        if need not in touched and any(k in spec for k in ("kinds", "search_terms", "constraints", "quantity", "allow_substitutes", "label")):
            touched.append(need)
        _revalidate(turn, need)

    b = a.get("budget")
    if isinstance(b, dict) and isinstance(b.get("amount"), (int, float)):
        ids = [i for i in _strs(b.get("need_ids")) if L.get(i)]
        label = str(b.get("label") or ("whole order" if not ids else ", ".join(L.get(i).label for i in ids)))
        L.budgets = [x for x in L.budgets if sorted(x.need_ids) != sorted(ids)]
        if b["amount"] > 0:
            L.budgets.append(Budget(amount=float(b["amount"]), scope=label, need_ids=ids))
        turn.money(b["amount"])
    turn.steps.append("updated the shopping list")
    results = [_search_and_propose(turn, n) for n in touched if n.active()]
    if a.get("household") or L.household:  # quantities may depend on the household: refresh auto-picked packs
        for n in L.active_needs():
            if n not in touched and n.selection and n.selection.get("auto"):
                _search_and_propose(turn, n, keep_choice=True)
    out = {"results": results, "plan_total": plan_summary(turn)["plan_total"], "budgets": budget_status(turn)}
    if L.household:
        out["household"] = L.household
    other = [{"id": n.id, "label": n.label, "status": n.status} for n in L.active_needs() if n not in touched]
    if other:
        out["other_needs"] = other
    if errors:
        out["errors"] = errors
    if notes:
        out["notes"] = notes
    return out


def infer_kind(label: str, terms: list[str]) -> str | None:
    """Kind from the need's own words, for models that don't name one. None if unclear."""
    from .text import classify

    for text in [" ".join([label] + terms), label] + terms:
        k = classify(text).kind
        if k != taxonomy.UNKNOWN:
            return k
    return None


def _search_and_propose(turn: Turn, need: Need, keep_choice: bool = False) -> dict:
    """Search one need, bind its candidates, and propose the top real match if nothing is chosen yet."""
    L = turn.ledger
    out = R.search(turn.repo, turn.scope, need, L.household, limit=4)
    need.candidates = [c.product_id for c in out.candidates]
    real = [c for c in out.candidates if not c.substitute]
    if keep_choice and need.selection:
        top = next((c for c in out.candidates if c.product_id == need.selection["product_id"]), None)
        if top and top.suggested_packs:
            need.selection["packs"] = top.suggested_packs
    elif real and (not need.selection or need.selection.get("auto")):
        top = real[0]
        need.selection = {"product_id": top.product_id, "packs": top.suggested_packs or 1, "substitute": False, "auto": True}
        need.status, need.note = "chosen", ""
        turn.selections_changed = True
    elif out.candidates:
        need.status, need.note = ("chosen" if need.selection else "options"), ""
    else:
        need.status, need.note = "missing", out.status + (f": {out.message}" if out.message else "")
    r: dict[str, Any] = {"need_id": need.id, "label": need.label, "status": out.status}
    if need.selection:
        row = turn.repo.products_by_ids(turn.scope, [need.selection["product_id"]]).get(need.selection["product_id"])
        if row:
            line = round(float(row["price"]) * need.selection["packs"], 2)
            r["proposed"] = {"product_id": row["product_id"], "name": row["name"], "size": row["size_text"] or "",
                             "price": float(row["price"]), "packs": need.selection["packs"], "line_total": line}
            turn.money(row["price"], line)
    alts = [c for c in out.candidates if not need.selection or c.product_id != need.selection["product_id"]][:3]
    if alts:
        r["alternatives"] = [{k: v for k, v in c.brief().items() if k in ("product_id", "name", "price", "size", "unit_price", "substitute_for_kind")}
                             for c in alts]
        for c in alts:
            turn.money(c.price, c.price * (c.suggested_packs or 1))
    if out.message:
        r["message"] = out.message
    return r


def _revalidate(turn: Turn, need: Need) -> None:
    """After a correction, drop candidates/selection that no longer fit; keep the rest."""
    ids = need.candidates + ([need.selection["product_id"]] if need.selection else [])
    rows = turn.repo.products_by_ids(turn.scope, ids)
    need.candidates = [i for i in need.candidates if i in rows and S.check(rows[i], need).ok]
    if need.selection:
        row = rows.get(need.selection["product_id"])
        if not row or not S.check(row, need, need.selection["packs"]).ok:
            need.history.append(f"dropped choice {need.selection['product_id']} (no longer fits)")
            need.selection = None
            need.status = "open"
            turn.selections_changed = True


def find_products(turn: Turn, a: dict) -> dict:
    L = turn.ledger
    ids = _strs(a.get("need_ids"))
    results, unknown = [], [i for i in ids if not L.get(i)]
    todo = [i for i in ids if L.get(i)]
    for nid in todo[:MAX_NEEDS_PER_SEARCH]:
        need = L.get(nid)
        out = R.search(turn.repo, turn.scope, need, L.household, limit=4)
        if a.get("prefer") == "cheapest":
            out.candidates.sort(key=lambda c: (c.substitute, c.price * (c.suggested_packs or 1)))
        need.candidates = [c.product_id for c in out.candidates]
        if out.candidates:
            need.status = "options" if need.status != "chosen" else "chosen"
            need.note = ""
        else:
            need.status, need.note = "missing", out.status + (f": {out.message}" if out.message else "")
        for c in out.candidates:
            turn.money(c.price, c.price * (c.suggested_packs or 1))
        results.append(out.brief())
    turn.steps.append("searched " + ", ".join(L.get(i).label for i in todo[:MAX_NEEDS_PER_SEARCH]))
    reply: dict[str, Any] = {"results": results}
    if unknown:
        reply["unknown_need_ids"] = unknown
    if len(todo) > MAX_NEEDS_PER_SEARCH:
        reply["not_searched_yet"] = todo[MAX_NEEDS_PER_SEARCH:]
    return reply


def choose_products(turn: Turn, a: dict) -> dict:
    L, errors = turn.ledger, []
    for nid in _strs(a.get("clear_need_ids")):
        need = L.get(nid)
        if need and need.selection:
            need.selection, need.status = None, "options" if need.candidates else "open"
            turn.selections_changed = True
    choices = [c for c in a.get("choices") or [] if isinstance(c, dict)]
    rows = turn.repo.products_by_ids(turn.scope, [str(c.get("product_id", "")) for c in choices])
    for c in choices:
        need, pid = L.get(str(c.get("need_id", ""))), str(c.get("product_id", ""))
        if not need:
            errors.append(f"No active need {c.get('need_id')}.")
            continue
        row = rows.get(pid)
        if not row:
            errors.append(f"{pid} is not in this store's catalog.")
            continue
        packs = c.get("packs") or R.suggest_packs(row, need, L.household) or 1
        packs = max(1, min(int(packs), B.MAX_QTY))
        v = S.check(row, need, packs)
        if not v.ok:
            errors.append(f"{row['name']} can't be used for '{need.label}': {', '.join(v.reasons)}.")
            continue
        need.selection = {"product_id": pid, "packs": packs, "substitute": v.substitute}
        need.status = "chosen"
        if pid not in need.candidates:
            need.candidates.append(pid)
        turn.selections_changed = True
    plan = plan_summary(turn)
    turn.steps.append("updated the plan")
    return {**plan, "errors": errors}


def show(turn: Turn, a: dict) -> dict:
    kind = a.get("type")
    L = turn.ledger
    if kind == "options":
        needs = [L.get(i) for i in _strs(a.get("need_ids"))] or [n for n in L.active_needs() if n.status == "options"]
        needs = [n for n in needs if n and n.candidates]
        if not needs:
            raise ToolError("None of those needs has options to show. Run find_products first.")
        turn.cards.append({"type": "options", "need_ids": [n.id for n in needs]})
        return {"shown": [n.id for n in needs]}
    if kind == "plan":
        if not L.selected_lines():
            raise ToolError("Nothing has been chosen yet.")
        turn.cards.append({"type": "plan"})
        return {"shown": "plan"}
    if kind == "comparison":
        ids = _strs(a.get("product_ids"))[:4]
        rows = turn.repo.products_by_ids(turn.scope, ids)
        if len(rows) < 2:
            raise ToolError("Give at least two product ids from this store.")
        turn.cards.append({"type": "comparison", "product_ids": [i for i in ids if i in rows]})
        facts = [R.to_candidate(rows[i]).brief() | {"in_stock": S.in_stock(rows[i])} for i in ids if i in rows]
        for f in facts:
            turn.money(f["price"])
        return {"comparison": facts}
    if kind == "basket":
        turn.cards.append({"type": "basket"})
        return {"shown": "basket"}
    raise ToolError("type must be options, plan, comparison or basket.")


def update_basket(turn: Turn, a: dict) -> dict:
    L = turn.ledger
    ops: list[B.Op] = []
    if a.get("clear"):
        ops.append(B.Op("clear"))
    if a.get("from_plan"):
        only = set(_strs(a.get("need_ids")))
        for need, sel in L.selected_lines():
            if not only or need.id in only:
                ops.append(B.Op("set", sel["product_id"], sel["packs"], need.id))
    for o in a.get("ops") or []:
        if isinstance(o, dict) and o.get("op") in ("add", "set", "remove") and o.get("product_id"):
            ops.append(B.Op(o["op"], str(o["product_id"]), int(o.get("quantity", 1) or 0), str(o.get("need_id", ""))))
    if not ops:
        raise ToolError("Nothing to change.")
    _, revision = turn.repo.load_basket(turn.scope, turn.session_id)
    result = B.apply(turn.repo, turn.scope, turn.session_id, ops, expected_revision=revision)
    turn.basket_changes.extend(result["changes"])
    basket = result["basket"]
    turn.money(basket["total"], *[i["line_total"] for i in basket["items"]], *[i["unit_price"] for i in basket["items"]])
    if result["changes"]:
        turn.cards.append({"type": "basket"})
    turn.steps.append("updated the basket")
    return {"changes": result["changes"], "errors": result["errors"],
            "basket": {"items": [{k: i[k] for k in ("product_id", "name", "quantity", "line_total")} for i in basket["items"]],
                       "total": basket["total"], "item_count": basket["item_count"]}}


def browse_catalog(turn: Turn, a: dict) -> dict:
    kind = a.get("kind") or None
    if kind and not taxonomy.get(kind) and not any(k.id.startswith(kind + ".") for k in taxonomy.KINDS):
        raise ToolError(f"Unknown kind {kind}; closest: {taxonomy.closest(kind)}")
    page = max(1, int(a.get("page") or 1))
    rows, total = turn.repo.browse(turn.scope, kind, a.get("query"), page, 10)
    items = [R.to_candidate(r).brief() | ({"out_of_stock": True} if not S.in_stock(r) else {}) for r in rows]
    for i in items:
        turn.money(i["price"])
    turn.steps.append("browsed the catalog")
    return {"page": page, "total": total, "pages": (total + 9) // 10, "items": items}


HANDLERS = {"update_needs": update_needs, "find_products": find_products, "choose_products": choose_products,
            "show": show, "update_basket": update_basket, "browse_catalog": browse_catalog}


# --------------------------------------------------------------- summaries

def plan_lines(turn: Turn) -> list[dict]:
    L = turn.ledger
    lines = L.selected_lines()
    rows = turn.repo.products_by_ids(turn.scope, [s["product_id"] for _, s in lines])
    out = []
    for need, sel in lines:
        row = rows.get(sel["product_id"])
        if not row or not row["has_offer"]:
            continue
        price = float(row["price"])
        out.append({"need_id": need.id, "need": need.label, "product_id": row["product_id"], "name": row["name"],
                    "size": row["size_text"] or "", "image": row["image"] or "", "unit_price": price, "packs": sel["packs"],
                    "line_total": round(price * sel["packs"], 2), "substitute": sel.get("substitute", False),
                    "purpose": need.purpose})
    return out


def budget_status(turn: Turn) -> list[dict]:
    lines = plan_lines(turn)
    out = []
    for b in turn.ledger.budgets:
        spent = round(sum(l["line_total"] for l in lines if not b.need_ids or l["need_id"] in b.need_ids), 2)
        remaining = round(b.amount - spent, 2)
        turn.money(b.amount, spent, remaining, abs(remaining))
        out.append({"scope": b.scope, "budget": b.amount, "planned": spent, "remaining": remaining, "over": remaining < 0})
    return out


def plan_summary(turn: Turn) -> dict:
    lines = plan_lines(turn)
    total = round(sum(l["line_total"] for l in lines), 2)
    turn.money(total, *[l["line_total"] for l in lines], *[l["unit_price"] for l in lines])
    open_needs = [compact_need(n) for n in turn.ledger.active_needs() if n.status in ("open", "options", "missing")]
    return {"plan": [{k: l[k] for k in ("need_id", "name", "unit_price", "packs", "line_total", "substitute")} for l in lines],
            "plan_total": total, "budgets": budget_status(turn), "still_open": open_needs}
