"""Cards shown under the assistant's reply, built from the ledger, the catalog
and the basket (never from the model's text), so cards, quantities and totals
always agree with the store's state.
"""

from __future__ import annotations

from . import basket as B
from . import retrieval as R
from . import suitability as S
from .tools import Turn, budget_status, plan_lines


def build(turn: Turn) -> list[dict]:
    blocks = list(turn.cards)
    types = {b["type"] for b in blocks}
    if turn.selections_changed and "plan" not in types and turn.ledger.selected_lines():
        blocks.append({"type": "plan"})
    if turn.basket_changes and "basket" not in types:
        blocks.append({"type": "basket"})

    basket = B.view(turn.repo, turn.scope, turn.session_id)
    in_basket = {i["product_id"]: i["quantity"] for i in basket["items"]}
    out, seen, displayed, ref = [], set(), [], 1
    for b in blocks:
        key = (b["type"], tuple(b.get("need_ids", ())), tuple(b.get("product_ids", ())))
        if key in seen:
            continue
        seen.add(key)
        if b["type"] == "options":
            groups = []
            for nid in b["need_ids"]:
                need = turn.ledger.get(nid)
                if not need:
                    continue
                rows = turn.repo.products_by_ids(turn.scope, need.candidates)
                options = []
                for pid in need.candidates:
                    row = rows.get(pid)
                    if not row:
                        continue
                    v = S.check(row, need)
                    if not v.ok:  # stock or data changed since search
                        continue
                    c = R.to_candidate(row, v.substitute, R.suggest_packs(row, need, turn.ledger.household))
                    options.append({"ref": ref, **_card(c), "in_basket": in_basket.get(pid, 0),
                                    "chosen": bool(need.selection and need.selection["product_id"] == pid), "need_id": need.id})
                    displayed.append({"ref": ref, "product_id": pid, "need_id": need.id, "name": row["name"]})
                    ref += 1
                if options:
                    groups.append({"need_id": need.id, "label": need.label, "options": options})
            if groups:
                out.append({"type": "options", "groups": groups})
        elif b["type"] == "plan":
            lines = plan_lines(turn)
            for l in lines:
                l["in_basket"] = in_basket.get(l["product_id"], 0)
            missing = [{"need_id": n.id, "label": n.label, "note": n.note} for n in turn.ledger.active_needs() if n.status == "missing"]
            out.append({"type": "plan", "lines": lines, "total": round(sum(l["line_total"] for l in lines), 2),
                        "budgets": budget_status(turn), "missing": missing, "currency": turn.scope.currency})
        elif b["type"] == "comparison":
            rows = turn.repo.products_by_ids(turn.scope, b["product_ids"])
            items = []
            for pid in b["product_ids"]:
                if pid in rows:
                    c = R.to_candidate(rows[pid])
                    items.append({"ref": ref, **_card(c), "in_stock": S.in_stock(rows[pid]), "in_basket": in_basket.get(pid, 0)})
                    displayed.append({"ref": ref, "product_id": pid, "need_id": "", "name": c.name})
                    ref += 1
            out.append({"type": "comparison", "items": items})
        elif b["type"] == "basket":
            out.append({"type": "basket", "basket": basket})
    if displayed:
        turn.ledger.displayed = displayed
    return out


def _card(c: R.Candidate) -> dict:
    return {"product_id": c.product_id, "name": c.name, "brand": c.brand, "size": c.size, "price": c.price,
            "unit_price": c.unit_price, "image": c.image, "substitute": c.substitute, "suggested_packs": c.suggested_packs,
            "low_stock": c.stock if c.stock is not None and c.stock <= 5 else None}
