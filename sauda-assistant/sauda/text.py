"""Text normalization, pack-size parsing and product classification."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache

from . import taxonomy

_WORD = re.compile(r"[a-z0-9]+|[؀-ۿ]+")


def normalize(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    return " ".join(_WORD.findall(text))


def tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


@lru_cache(maxsize=16384)
def _phrase_pattern(phrase: str) -> re.Pattern | None:
    p = normalize(phrase)
    return re.compile(rf"(?<![a-z0-9]){re.escape(p)}(?:s|es)?(?![a-z0-9])") if p else None


def has_phrase(haystack: str, phrase: str) -> bool:
    """Whole-word phrase match on normalized text; tolerant of simple plurals."""
    pattern = _phrase_pattern(phrase)
    return bool(pattern and pattern.search(haystack))


# ------------------------------------------------------------------ pack sizes

@dataclass(frozen=True)
class Pack:
    amount: float   # in base unit
    unit: str       # g, ml, pc

    def label(self) -> str:
        if self.unit == "g" and self.amount >= 1000:
            return f"{self.amount / 1000:g} kg"
        if self.unit == "ml" and self.amount >= 1000:
            return f"{self.amount / 1000:g} L"
        return f"{self.amount:g} {self.unit}"


_UNITS = {
    "kg": ("g", 1000), "kgs": ("g", 1000), "kilo": ("g", 1000), "g": ("g", 1), "gm": ("g", 1), "gms": ("g", 1), "gram": ("g", 1),
    "grams": ("g", 1), "mg": ("g", 0.001),
    "l": ("ml", 1000), "ltr": ("ml", 1000), "litre": ("ml", 1000), "liter": ("ml", 1000), "litres": ("ml", 1000), "liters": ("ml", 1000),
    "ml": ("ml", 1),
    "pc": ("pc", 1), "pcs": ("pc", 1), "piece": ("pc", 1), "pieces": ("pc", 1), "pack": ("pc", 1), "rolls": ("pc", 1), "roll": ("pc", 1),
    "eggs": ("pc", 1), "bags": ("pc", 1), "tabs": ("pc", 1), "dozen": ("pc", 12), "dz": ("pc", 12),
}
_SIZE = re.compile(r"(?:(\d+)\s*[x×]\s*)?(\d+(?:\.\d+)?)\s*(kg|kgs|kilo|gms|gm|grams|gram|g|mg|ltr|litres|liters|litre|liter|l|ml|pcs|pc|pieces|piece|pack|rolls|roll|eggs|bags|tabs|dozen|dz)\b")


def parse_pack(*texts: str) -> Pack | None:
    for text in texts:
        t = (text or "").lower()
        if re.search(r"\b(1\s*)?dozen\b", t) and not _SIZE.search(t):
            return Pack(12, "pc")
        m = _SIZE.search(t)
        if m:
            multiple = int(m.group(1)) if m.group(1) else 1
            unit, factor = _UNITS[m.group(3)]
            return Pack(round(multiple * float(m.group(2)) * factor, 3), unit)
    return None


def unit_price(price: float, pack: Pack | None) -> str:
    if not pack or pack.amount <= 0:
        return ""
    if pack.unit == "g":
        return f"Rs {price / pack.amount * 1000:,.0f}/kg"
    if pack.unit == "ml":
        return f"Rs {price / pack.amount * 1000:,.0f}/L"
    return f"Rs {price / pack.amount:,.0f}/pc"


def packs_needed(amount: float, unit: str, pack: Pack | None) -> int | None:
    """How many packs cover `amount` of `unit`. None when units don't line up."""
    if not pack or pack.amount <= 0:
        return None
    conv = {"kg": ("g", 1000), "g": ("g", 1), "l": ("ml", 1000), "ml": ("ml", 1), "pc": ("pc", 1), "dozen": ("pc", 12)}
    base, factor = conv.get(unit.lower(), (unit.lower(), 1))
    if base != pack.unit:
        return None
    return max(1, math.ceil(amount * factor / pack.amount - 1e-9))


# ------------------------------------------------------------- classification

@dataclass
class Classification:
    kind: str
    confidence: float
    method: str
    reason: str


def classify(name: str, category: str = "", brand: str = "") -> Classification:
    """Assign a taxonomy kind from product text. Deterministic and explainable.

    Scoring: a keyword hit in the name scores by keyword length (more specific
    phrases win); a feed-category hint adds a bonus. Any `not` word in the name
    vetoes the kind. Ties or weak evidence fall back to "unknown", which is
    never eligible for a need.
    """
    n = normalize(f"{name} {brand}")
    c = normalize(category)
    best: list[tuple[float, str, str]] = []
    for kind in taxonomy.KINDS:
        if any(has_phrase(n, w) for w in kind.not_words):
            continue
        hits = [w for w in kind.keywords if has_phrase(n, w)]
        if not hits:
            continue
        top = max(hits, key=lambda w: len(normalize(w)))
        score = 1.0 + 0.15 * len(normalize(top).split()) + 0.02 * len(normalize(top))
        if kind.categories and any(has_phrase(c, cat) for cat in kind.categories):
            score += 0.6
        best.append((score, kind.id, top))
    if not best:
        return Classification(taxonomy.UNKNOWN, 0.0, "rules", "no keyword matched")
    best.sort(reverse=True)
    score, kid, word = best[0]
    if len(best) > 1 and abs(best[1][0] - score) < 0.05 and best[1][1].split(".")[0] != kid.split(".")[0]:
        return Classification(taxonomy.UNKNOWN, 0.3, "rules", f"ambiguous: {kid} vs {best[1][1]}")
    confidence = min(0.95, 0.55 + 0.1 * score)
    return Classification(kid, round(confidence, 2), "rules", f"matched '{word}'")
