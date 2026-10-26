"""The shopping-task ledger: the one authoritative record of what the
customer is trying to buy.

Each need has a stable id ("n1", "n2", ...). Candidates found by search are
bound to the need that asked for them. A selection (product + quantity) is a
proposal, not a basket change. Totals and budget status are always computed
here, never by the model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Constraints:
    brands: list[str] = field(default_factory=list)          # preferred / required brands
    brand_required: bool = False
    exclude_brands: list[str] = field(default_factory=list)
    exclude_terms: list[str] = field(default_factory=list)   # e.g. "flavoured", "powder"
    must_terms: list[str] = field(default_factory=list)      # e.g. "basmati", "boneless"
    max_unit_price: float | None = None


@dataclass
class Need:
    id: str
    label: str                       # customer-facing, e.g. "Milk for chai"
    kinds: list[str]                 # accepted taxonomy kinds
    search_terms: list[str] = field(default_factory=list)
    constraints: Constraints = field(default_factory=Constraints)
    allow_substitutes: bool = False
    quantity: dict | None = None     # {"amount": 2, "unit": "kg"} or {"packs": 2}
    purpose: str = ""                # recipe / plan this need belongs to, e.g. "chicken biryani for 6"
    status: str = "open"             # open | options | chosen | missing | deferred | removed
    candidates: list[str] = field(default_factory=list)   # product ids bound to this need
    selection: dict | None = None    # {"product_id", "quantity", "substitute": bool}
    note: str = ""                   # why missing / what was rejected
    history: list[str] = field(default_factory=list)      # corrections, for the model's context

    def active(self) -> bool:
        return self.status not in ("removed",)


@dataclass
class Budget:
    amount: float
    scope: str = "all"               # "all" or a purpose label
    need_ids: list[str] = field(default_factory=list)  # explicit scope; empty + scope=all means everything


@dataclass
class Ledger:
    needs: list[Need] = field(default_factory=list)
    budgets: list[Budget] = field(default_factory=list)
    household: dict = field(default_factory=dict)   # {"people": 4, "days": 7}
    preferences: dict = field(default_factory=dict) # dietary, brands to avoid, language...
    displayed: list[dict] = field(default_factory=list)  # last cards shown: [{"ref": 1, "product_id", "need_id"}]
    next_id: int = 1
    turn: int = 0
    seen_basket_revision: int = 0   # basket revision the assistant last saw; a newer one means the customer used the buttons

    # ------------------------------------------------------------- needs

    def get(self, need_id: str) -> Need | None:
        return next((n for n in self.needs if n.id == need_id and n.active()), None)

    def new_id(self) -> str:
        nid = f"n{self.next_id}"
        self.next_id += 1
        return nid

    def active_needs(self) -> list[Need]:
        return [n for n in self.needs if n.active()]

    def selected_lines(self, need_ids: list[str] | None = None) -> list[tuple[Need, dict]]:
        out = []
        for n in self.active_needs():
            if n.selection and n.status == "chosen" and (need_ids is None or n.id in need_ids):
                out.append((n, n.selection))
        return out

    # ------------------------------------------------------------ export

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Ledger":
        if not d:
            return cls()
        needs = []
        for n in d.get("needs", []):
            n = dict(n)
            n["constraints"] = Constraints(**n.get("constraints", {}))
            needs.append(Need(**n))
        return cls(needs=needs, budgets=[Budget(**b) for b in d.get("budgets", [])], household=d.get("household", {}),
                   preferences=d.get("preferences", {}), displayed=d.get("displayed", []), next_id=d.get("next_id", 1),
                   turn=d.get("turn", 0), seen_basket_revision=d.get("seen_basket_revision", 0))


def compact_need(n: Need) -> dict[str, Any]:
    """What the model sees about a need: enough to continue, no noise."""
    out: dict[str, Any] = {"id": n.id, "label": n.label, "kinds": n.kinds, "status": n.status}
    if n.purpose:
        out["purpose"] = n.purpose
    if n.quantity:
        out["quantity"] = n.quantity
    c = {k: v for k, v in asdict(n.constraints).items() if v not in ([], None, False)}
    if c:
        out["constraints"] = c
    if n.allow_substitutes:
        out["allow_substitutes"] = True
    if n.selection:
        out["selection"] = n.selection
    if n.note:
        out["note"] = n.note
    if n.history:
        out["changes"] = n.history[-3:]
    return out
