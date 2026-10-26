"""Find products for a need.

Candidates come from the catalog by kind (deterministic), are checked by the
shared suitability rule, and the eligible ones are ranked by lexical
relevance to the need's search terms, brand preference and price. Current
product and offer rows are the only source of names, prices and stock.

The outcome says *why* nothing was found, so the assistant can tell the
customer the truth: the store doesn't carry it, it's out of stock, or nothing
matches the constraints.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import suitability as S
from . import taxonomy
from .db import Repo, Scope
from .ledger import Need
from .text import Pack, has_phrase, normalize, packs_needed, unit_price

FOUND = "found"
ONLY_SUBSTITUTES = "only_substitutes"
NONE_ELIGIBLE = "none_eligible"       # the store has this kind, but nothing passes (stock / constraints)
NOT_IN_CATALOG = "not_in_catalog"     # the store's connected catalog has no product of this kind
INVALID_NEED = "invalid_need"


@dataclass
class Candidate:
    product_id: str
    name: str
    brand: str
    size: str
    price: float
    image: str
    kind: str
    substitute: bool
    unit_price: str
    suggested_packs: int | None = None
    stock: int | None = None

    def brief(self) -> dict:
        d = {"product_id": self.product_id, "name": self.name, "price": self.price}
        if self.brand:
            d["brand"] = self.brand
        if self.size:
            d["size"] = self.size
        if self.unit_price:
            d["unit_price"] = self.unit_price
        if self.substitute:
            d["substitute_for_kind"] = True
        if self.suggested_packs:
            d["suggested_packs"] = self.suggested_packs
        if self.stock is not None and self.stock <= 5:
            d["low_stock"] = self.stock
        return d


@dataclass
class Outcome:
    need_id: str
    status: str
    candidates: list[Candidate] = field(default_factory=list)
    rejected: dict[str, int] = field(default_factory=dict)
    message: str = ""

    def brief(self) -> dict:
        d = {"need_id": self.need_id, "status": self.status, "options": [c.brief() for c in self.candidates]}
        if self.rejected:
            d["rejected_counts"] = self.rejected
        if self.message:
            d["message"] = self.message
        return d


def to_candidate(row, substitute: bool = False, suggested: int | None = None) -> Candidate:
    pack = Pack(row["pack_amount"], row["pack_unit"]) if row["pack_amount"] else None
    return Candidate(row["product_id"], row["name"], row["brand"] or "", row["size_text"] or "", float(row["price"]),
                     row["image"] or "", row["kind"], substitute, unit_price(float(row["price"]), pack), suggested, row["stock"])


def suggest_packs(row, need: Need, household: dict) -> int | None:
    """Packs to cover the need's stated quantity, or a household estimate for the period."""
    pack = Pack(row["pack_amount"], row["pack_unit"]) if row["pack_amount"] else None
    q = need.quantity or {}
    if q.get("packs"):
        return int(q["packs"])
    if q.get("amount") and q.get("unit"):
        return packs_needed(float(q["amount"]), str(q["unit"]), pack)
    people, days = household.get("people"), household.get("days")
    kind = taxonomy.get(row["kind"])
    if people and days and kind and kind.norm and pack and pack.unit == kind.unit:
        return packs_needed(kind.norm * people * days / 7, kind.unit, pack)
    return None


def search(repo: Repo, scope: Scope, need: Need, household: dict | None = None, limit: int = 5) -> Outcome:
    household = household or {}
    primary, subs = S.accepted_kinds(need)
    if not primary:
        return Outcome(need.id, INVALID_NEED, message="The need has no valid product kind.")
    rows = repo.products_by_kinds(scope, sorted(primary | subs))
    if not rows:
        return Outcome(need.id, NOT_IN_CATALOG,
                       message=f"The store's connected catalog has no {', '.join(taxonomy.get(k).label for k in primary)}.")

    eligible, rejected = [], Counter()
    for r in rows:
        v = S.check(r, need)
        if v.ok:
            eligible.append((r, v.substitute))
        else:
            for reason in v.reasons:
                rejected[reason] += 1

    lexical = repo.lexical_scores(scope, need.search_terms + [need.label], [r["product_id"] for r, _ in eligible])
    prefer = [normalize(b) for b in need.constraints.brands]

    def value(r) -> float:
        # Price per base unit when sizes are comparable, so a 250 ml pack doesn't look "cheaper" than 1 L.
        return float(r["price"]) / r["pack_amount"] if r["pack_amount"] else float(r["price"])

    units = {r["pack_unit"] for r, _ in eligible}
    comparable = len(units) == 1 and None not in units
    prices = [value(r) if comparable else float(r["price"]) for r, _ in eligible] or [1.0]
    cheapest, dearest = min(prices), max(prices)

    def score(item) -> float:
        r, sub = item
        s = lexical.get(r["product_id"], 0.0)
        text = normalize(f"{r['name']} {r['brand'] or ''}")
        s += sum(1.5 for t in need.search_terms if has_phrase(text, t))
        if prefer and any(p and (p == normalize(r["brand"] or "") or has_phrase(text, p)) for p in prefer):
            s += 4
        if dearest > cheapest:  # mild preference for value
            p = value(r) if comparable else float(r["price"])
            s += 0.8 * (1 - (p - cheapest) / (dearest - cheapest))
        if r["stock"] is not None and r["stock"] <= 5:
            s -= 0.3
        if sub:
            s -= 6  # real matches always rank above substitutes
        return s

    eligible.sort(key=score, reverse=True)
    picked = [to_candidate(r, sub, suggest_packs(r, need, household)) for r, sub in eligible[:limit]]
    if not picked:
        return Outcome(need.id, NONE_ELIGIBLE, rejected=dict(rejected), message=_explain(rejected))
    status = ONLY_SUBSTITUTES if all(c.substitute for c in picked) else FOUND
    return Outcome(need.id, status, picked, dict(rejected))


def _explain(rejected: Counter) -> str:
    labels = {S.OUT_OF_STOCK: "out of stock", S.NO_OFFER: "not sold at this store", S.EXCLUDED_TERM: "excluded by the customer's wording",
              S.EXCLUDED_BRAND: "an excluded brand", S.BRAND_MISMATCH: "not the requested brand", S.MISSING_TERM: "missing a required detail",
              S.OVER_PRICE: "over the price limit", S.UNPUBLISHED: "no longer listed"}
    parts = [f"{n} {labels.get(k, k)}" for k, n in rejected.most_common() if k in labels]
    return "Products of this type exist but none can be offered: " + ", ".join(parts) + "." if parts else ""
