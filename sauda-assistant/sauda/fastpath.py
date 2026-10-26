"""Handle clear, simple messages without calling a model.

Two cases:

1. A plain product list: "doodh aur double roti", "2 kg aloo, 1 kg pyaz",
   "eggs, bread and milk", "چینی اور چائے". Every item must be recognised
   with confidence (a known product word, an optional quantity, an optional
   brand of that product, filler words); anything else - a recipe, a budget,
   a question, a correction, an unknown word - goes to the model.
2. A yes to "Shall I add these to your basket?": "haan", "ji daal do", "yes".

The reply is written from what the tools returned, so its figures are exact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import retrieval as R
from . import taxonomy
from .ledger import Need
from .text import classify, has_phrase, normalize, tokens
from .tools import Turn, plan_summary, update_basket, update_needs

FILLER = set("""
mujhe muje mjhe hamein humein hume chahiye chahye chaiye chahiyay chahie chaheye chiye chahiay chahta chahti lena leni lene hai hain he
bhi b plz please pls ek aik kuch thora thoda thori thodi zara de do dedo dein dijiye dijye dikhao dikha send bhejo bhej mangwa mangwana
i need want would like to get some me the a an of also for my
""".split()) | {"مجھے", "چاہیے", "بھی", "اور", "کچھ", "دے", "دو", "دیں"}
JOINERS = re.compile(r"\s*(?:,|،|\+|&|\n|;|\band\b|\baur\b|\bor\b|\bphir\b|اور)\s*", re.I)
# Words that mean the message is more than a product list: let the model handle it.
NOT_A_LIST = re.compile(
    r"\?|\b(budget|rs|rupe+s?|rupay|hazar|hazaar|thousand|recipe|banana|banani|bana|pakana|cook|logon|log|people|persons?|family|ghar|"
    r"week|weekly|hafte|hafta|month|mahine|mahina|din|days?|nahi|nahin|nai|not|no|instead|change|badal|badlo|hata|hatao|remove|replace|"
    r"cancel|add|daal|dal|daalo|basket|cart|tokri|sasta|saste|cheap|cheapest|best|acha|achha|compare|konsa|kaunsa|kon|which|what|kya|"
    r"how|kaise|kitna|kitne|price|qeemat|offer|discount|hello|hi|salam|assalam|thanks|shukriya|biryani|karahi|nihari|korma|pulao|"
    r"halwa|kheer|party|dawat|breakfast|nashta|lunch|dinner|khana)\b|بجٹ|ترکیب|لوگ|ہفت|نہیں|سستا|کیا|کونسا|ٹوکری",
    re.I)
YES = re.compile(r"^\s*(haan|han|haa|ha|ji|jee|g|yes|yep|yeah|ok|okay|theek hai|thik hai|theek|thik|sure|done|ہاں|جی|ٹھیک ہے)?[\s,!.]*"
                 r"(haan|ji|yes|ok|okay|theek hai|thik hai|sab|all|daal do|dal do|daal dein|add karo|add kar do|add kardo|add|daal|kar do|ڈال دو|ڈال دیں)?"
                 r"[\s,!.]*(sab|all|everything|sara|saara)?[\s,!.]*(daal do|dal do|add karo|add kar do|add|daal dein|kar do|please|plz|ڈال دو)?[\s,!.]*$", re.I)
UNITS = {"kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "g": "g", "gm": "g", "gram": "g", "grams": "g", "l": "l", "litre": "l",
         "liter": "l", "litres": "l", "liters": "l", "ltr": "l", "ml": "ml", "dozen": "dozen", "darjan": "dozen", "darjen": "dozen",
         "pack": "packs", "packs": "packs", "packet": "packs", "packets": "packs", "pc": "pc", "pcs": "pc", "piece": "pc", "pieces": "pc",
         "کلو": "kg", "درجن": "dozen", "لیٹر": "l"}
QTY = re.compile(r"(\d+(?:\.\d+)?)\s*(" + "|".join(sorted(map(re.escape, UNITS), key=len, reverse=True)) + r")\b|(\d+(?:\.\d+)?)", re.I)
URDU = re.compile(r"[؀-ۿ]")
ROMAN_URDU = re.compile(r"\b(aur|mujhe|chahiye|chahye|chaiye|bhi|ka|ke|ki|do|dedo|doodh|anday|anda|aata|atta|cheeni|chawal|pyaz|aloo|tamatar|"
                        r"double roti|dahi|makhan|chai|daal|ghee|tel|namak|haan|ji|daal do|kar do|sabun|sabzi|gosht|murghi)\b", re.I)


@dataclass
class Item:
    label: str
    kind: str
    quantity: dict | None
    brands: list[str]


def language(text: str) -> str:
    if URDU.search(text):
        return "ur"
    return "roman" if ROMAN_URDU.search(text) else "en"


def parse_list(turn: Turn, text: str) -> list[Item] | None:
    """The items of a plain product list, or None if the message is anything more."""
    if len(text) > 300 or NOT_A_LIST.search(text):
        return None
    items = []
    for part in JOINERS.split(text):
        part = part.strip(" .!")
        if not part:
            continue
        quantity = None
        m = QTY.search(part)
        if m:
            amount = float(m.group(1) or m.group(3))
            unit = UNITS.get((m.group(2) or "").lower(), "") if m.group(2) else ""
            quantity = {"packs": int(amount)} if unit in ("", "packs") and amount.is_integer() else (
                {"amount": amount, "unit": unit} if unit else None)
            if quantity is None:
                return None
            part = (part[:m.start()] + " " + part[m.end():]).strip()
        words = [w for w in tokens(part) if w not in FILLER]
        if not words:
            continue
        if len(words) > 4:
            return None
        phrase = " ".join(words)
        kind = classify(phrase).kind
        if kind == taxonomy.UNKNOWN or kind in taxonomy.BROAD:
            return None  # broad kinds need the item's English name matched; leave them to the model
        k = taxonomy.get(kind)
        brands = _brands(turn, kind)
        explained = set()
        for kw in k.keywords:
            if has_phrase(normalize(phrase), kw):
                explained.update(tokens(kw))
                explained.update(t + "s" for t in tokens(kw))
        found_brands = [b for b in brands if has_phrase(normalize(phrase), b)]
        for b in found_brands:
            explained.update(tokens(b))
        if any(w not in explained and w.rstrip("s") not in explained for w in words):
            return None  # a word we can't account for: not confident
        items.append(Item(label=_label(kind, phrase), kind=kind, quantity=quantity, brands=found_brands))
    return items or None


def try_handle(turn: Turn, text: str) -> str | None:
    """A reply when the message can be handled without a model, else None (nothing changed)."""
    L = turn.ledger
    if L.preferences.get("_awaiting") == "add_plan" and YES.match(text) and text.strip():
        L.preferences.pop("_awaiting", None)
        lines = L.selected_lines()
        if not lines:
            return None
        result = update_basket(turn, {"from_plan": True})
        return _basket_reply(result, language(text) if language(text) != "en" else L.preferences.get("_lang", "en"))
    items = parse_list(turn, text)
    if not items:
        return None
    # Dry run: a product that only has substitutes needs explaining, so leave those to the model.
    for it in items:
        probe = Need("probe", it.label, [it.kind], constraints=_constraints(it))
        if R.search(turn.repo, turn.scope, probe, L.household, limit=1).status == R.ONLY_SUBSTITUTES:
            return None
    specs = [{"label": it.label, "kinds": [it.kind], **({"quantity": it.quantity} if it.quantity else {}),
              **({"constraints": {"brands": it.brands}} if it.brands else {})} for it in items]
    out = update_needs(turn, {"needs": specs})
    lang = language(text)
    L.preferences["_lang"] = lang
    reply = _list_reply(turn, out, lang)
    if L.selected_lines():
        L.preferences["_awaiting"] = "add_plan"
    return reply


# ------------------------------------------------------------------ replies

def _list_reply(turn: Turn, out: dict, lang: str) -> str:
    found = [r for r in out["results"] if r.get("proposed")]
    missing = [r["label"] for r in out["results"] if not r.get("proposed")]
    lines = [f"• {r['proposed']['packs']} × {r['proposed']['name']}: Rs {r['proposed']['line_total']:,.0f}" for r in found]
    total = plan_summary(turn)["plan_total"]
    words = {
        "en": ("Here's what I found:", "Total for your list: Rs {t:,.0f}.", "Not available right now: {m}.", "Shall I add these to your basket?",
               "Sorry, none of these are available right now: {m}."),
        "roman": ("Ye mil gaya:", "Aap ki list ka total: Rs {t:,.0f}.", "Abhi dastyab nahi: {m}.", "Basket mein daal doon?",
                  "Maazrat, ye abhi dastyab nahi: {m}."),
        "ur": ("یہ مل گیا:", "آپ کی فہرست کا کل: Rs {t:,.0f}", "ابھی دستیاب نہیں: {m}", "کیا میں یہ ٹوکری میں ڈال دوں؟",
               "معذرت، یہ ابھی دستیاب نہیں: {m}"),
    }[lang]
    if not found:
        return words[4].format(m=", ".join(missing))
    parts = [words[0], *lines, words[1].format(t=total)]
    if missing:
        parts.append(words[2].format(m=", ".join(missing)))
    parts.append(words[3])
    return "\n".join(parts)


def _basket_reply(result: dict, lang: str) -> str:
    b = result["basket"]
    n = sum(c["to"] - c["from"] for c in result["changes"] if c.get("to", 0) > c.get("from", 0))
    if not result["changes"]:
        return {"en": "Those items are already in your basket.", "roman": "Ye sab pehle se basket mein hain.",
                "ur": "یہ سب پہلے سے ٹوکری میں ہیں۔"}[lang]
    extra = "" if not result["errors"] else {"en": " Some items couldn't be added: ", "roman": " Kuch cheezen add nahi ho sakin: ",
                                             "ur": " کچھ چیزیں شامل نہیں ہو سکیں: "}[lang] + "; ".join(result["errors"])
    return {"en": f"Done, I added {n} item(s) to your basket. Basket total: Rs {b['total']:,.0f}.",
            "roman": f"Ho gaya, {n} cheezen basket mein daal di hain. Basket ka total: Rs {b['total']:,.0f}.",
            "ur": f"ہو گیا، {n} چیزیں ٹوکری میں ڈال دی گئی ہیں۔ ٹوکری کا کل: Rs {b['total']:,.0f}"}[lang] + extra


# ------------------------------------------------------------------ helpers

def _brands(turn: Turn, kind: str) -> list[str]:
    cache = getattr(turn, "_brand_cache", None)
    if cache is None:
        cache = turn._brand_cache = {}
    if kind not in cache:
        cache[kind] = sorted({r["brand"] for r in turn.repo.products_by_kinds(turn.scope, [kind]) if r["brand"] and r["brand"] != "Fresh"},
                             key=len, reverse=True)
    return cache[kind]


def _label(kind: str, phrase: str) -> str:
    return taxonomy.get(kind).label.split(" (")[0].split(" /")[0]


def _constraints(it: Item):
    from .ledger import Constraints

    return Constraints(brands=it.brands)
