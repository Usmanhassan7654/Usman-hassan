"""One shared rule for "can this product fill this need?".

Used by search, by selection, by the basket and by presentation, so a
product that fails here can never appear as the answer to a need anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import taxonomy
from .ledger import Need
from .text import has_phrase, normalize

# Reason codes, so "not in catalog", "out of stock" and "doesn't fit" stay distinct.
WRONG_KIND = "wrong_kind"
UNCLASSIFIED = "unclassified"
UNPUBLISHED = "unpublished"
NO_OFFER = "not_sold_at_this_store"
OUT_OF_STOCK = "out_of_stock"
EXCLUDED_TERM = "excluded_term"
EXCLUDED_BRAND = "excluded_brand"
BRAND_MISMATCH = "brand_mismatch"
MISSING_TERM = "missing_required_term"
OVER_PRICE = "over_max_price"


@dataclass
class Verdict:
    ok: bool
    substitute: bool = False
    reasons: tuple[str, ...] = ()


def accepted_kinds(need: Need) -> tuple[set[str], set[str]]:
    primary = {k for k in need.kinds if taxonomy.get(k)}
    subs: set[str] = set()
    if need.allow_substitutes:
        for k in primary:
            subs.update(taxonomy.get(k).subs)
    return primary, subs - primary


def in_stock(row) -> bool:
    return row["stock"] is None or row["stock"] > 0


def check(row, need: Need, quantity: int = 1) -> Verdict:
    """`row` is a product joined with its store offer (see Repo.products_by_*)."""
    primary, subs = accepted_kinds(need)
    reasons: list[str] = []
    kind = row["kind"]
    if kind == taxonomy.UNKNOWN:
        reasons.append(UNCLASSIFIED)
    elif kind not in primary and kind not in subs:
        reasons.append(WRONG_KIND)
    if not row["published"]:
        reasons.append(UNPUBLISHED)
    if not row["has_offer"]:
        reasons.append(NO_OFFER)
    elif not in_stock(row) or (row["stock"] is not None and row["stock"] < quantity):
        reasons.append(OUT_OF_STOCK)

    c = need.constraints
    text = normalize(f"{row['name']} {row['brand'] or ''}")
    brand = normalize(row["brand"] or "")
    if any(has_phrase(text, t) for t in c.exclude_terms):
        reasons.append(EXCLUDED_TERM)
    if any(normalize(b) and (normalize(b) == brand or has_phrase(text, b)) for b in c.exclude_brands):
        reasons.append(EXCLUDED_BRAND)
    if c.brand_required and c.brands and not any(normalize(b) == brand or has_phrase(text, b) for b in c.brands):
        reasons.append(BRAND_MISMATCH)
    if c.must_terms and not all(has_phrase(text, t) for t in c.must_terms):
        reasons.append(MISSING_TERM)
    if c.max_unit_price is not None and row["has_offer"] and row["price"] is not None and row["price"] > c.max_unit_price:
        reasons.append(OVER_PRICE)
    return Verdict(ok=not reasons, substitute=kind in subs and kind not in primary, reasons=tuple(reasons))
