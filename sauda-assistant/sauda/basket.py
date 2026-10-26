"""Server-authoritative basket.

Every change carries the revision the client last saw and an idempotency
key. A stale revision is rejected with the current basket (the client
re-renders from it, so browser and server can't drift); a repeated key
returns the original result instead of applying twice. Prices and
availability are re-read from the catalog every time the basket is viewed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from . import suitability as S
from .db import Repo, Scope

MAX_QTY = 50


class BasketError(Exception):
    pass


class StaleRevision(BasketError):
    def __init__(self, basket: dict):
        super().__init__("The basket changed since you last saw it.")
        self.basket = basket


@dataclass
class Op:
    op: str            # add | set | remove | clear
    product_id: str = ""
    quantity: int = 1
    need_id: str = ""


def view(repo: Repo, scope: Scope, session_id: str) -> dict:
    lines, revision = repo.load_basket(scope, session_id)
    products = repo.products_by_ids(scope, [l["product_id"] for l in lines])
    items, total, problems = [], 0.0, []
    for l in lines:
        row = products.get(l["product_id"])
        if not row or not row["published"] or not row["has_offer"]:
            problems.append({"product_id": l["product_id"], "name": l.get("name", ""), "issue": "no longer available"})
            continue
        available = S.in_stock(row) and (row["stock"] is None or row["stock"] >= l["quantity"])
        price = float(row["price"])
        item = {"product_id": row["product_id"], "name": row["name"], "brand": row["brand"] or "", "size": row["size_text"] or "",
                "image": row["image"] or "", "unit_price": price, "quantity": l["quantity"], "line_total": round(price * l["quantity"], 2),
                "need_id": l.get("need_id", "")}
        if not available:
            item["issue"] = "out of stock" if not S.in_stock(row) else f"only {row['stock']} left"
            problems.append({"product_id": row["product_id"], "name": row["name"], "issue": item["issue"]})
        else:
            total += item["line_total"]
        items.append(item)
    return {"revision": revision, "items": items, "item_count": sum(i["quantity"] for i in items if "issue" not in i),
            "total": round(total, 2), "currency": scope.currency, "problems": problems}


def apply(repo: Repo, scope: Scope, session_id: str, ops: list[Op], expected_revision: int | None,
          idempotency_key: str | None = None) -> dict:
    """Apply ops atomically. Returns {"basket": view, "changes": [...], "errors": [...]}."""
    key = idempotency_key or uuid.uuid4().hex
    with repo.tx() as c:
        prior = repo.find_op(c, scope, session_id, key)
        if prior is not None:
            return {**prior, "duplicate": True, "basket": view(repo, scope, session_id)}
        lines, revision = repo.load_basket(scope, session_id)
        if expected_revision is not None and expected_revision != revision:
            raise StaleRevision(view(repo, scope, session_id))
        by_id = {l["product_id"]: l for l in lines}
        products = repo.products_by_ids(scope, [o.product_id for o in ops if o.product_id])
        changes, errors = [], []
        for o in ops:
            if o.op == "clear":
                if by_id:
                    changes.append({"op": "clear"})
                by_id.clear()
                continue
            row = products.get(o.product_id)
            if row is None:
                errors.append(f"Unknown product {o.product_id}.")
                continue
            current = by_id.get(o.product_id, {}).get("quantity", 0)
            target = {"add": current + max(1, o.quantity), "set": max(0, o.quantity), "remove": 0}.get(o.op)
            if target is None:
                errors.append(f"Unknown operation {o.op}.")
                continue
            target = min(target, MAX_QTY)
            if target > 0:
                if not row["published"] or not row["has_offer"]:
                    errors.append(f"{row['name']} is not sold at this store.")
                    continue
                if not S.in_stock(row) or (row["stock"] is not None and row["stock"] < target):
                    errors.append(f"{row['name']}: only {row['stock'] or 0} in stock.")
                    continue
                by_id[o.product_id] = {"product_id": o.product_id, "quantity": target, "name": row["name"],
                                       "need_id": o.need_id or by_id.get(o.product_id, {}).get("need_id", "")}
            elif o.product_id in by_id:
                del by_id[o.product_id]
            if target != current:
                changes.append({"product_id": o.product_id, "name": row["name"], "from": current, "to": target})
        new_revision = revision + 1 if changes else revision
        if changes:
            repo.save_basket(c, scope, session_id, list(by_id.values()), new_revision)
        result = {"changes": changes, "errors": errors}
        repo.record_op(c, scope, session_id, key, result)
    return {**result, "basket": view(repo, scope, session_id)}
