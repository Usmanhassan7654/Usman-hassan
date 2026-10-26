"""Live customer-journey evaluation against the real model.

    ANTHROPIC_API_KEY=... python evals/journeys.py            # all journeys
    python evals/journeys.py --only correction --repeat 3      # one journey, 3 runs

Each journey is a multi-turn conversation in a fresh store. After every turn,
checks look at what the customer would see (reply, cards, basket) and at the
authoritative state, not at whether a tool ran. Results go to
evals/reports/<timestamp>.json. Each run spends real API usage.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sauda import ingest  # noqa: E402
from sauda.agent import Agent  # noqa: E402
from sauda.db import Repo  # noqa: E402
from sauda.ledger import Ledger  # noqa: E402

URDU = re.compile(r"[؀-ۿ]")


@dataclass
class Ctx:
    repo: Repo
    scope: object
    session: str
    result: object = None

    def ledger(self) -> Ledger:
        return Ledger.from_dict(self.repo.load_session(self.scope, self.session)[0])

    def kinds_shown(self) -> set[str]:
        ids = [o["product_id"] for c in self.result.cards if c["type"] == "options" for g in c["groups"] for o in g["options"]]
        ids += [l["product_id"] for c in self.result.cards if c["type"] == "plan" for l in c["lines"]]
        return {r["kind"] for r in self.repo.products_by_ids(self.scope, ids).values()}

    def plan_kinds(self) -> dict[str, str]:
        led = self.ledger()
        rows = self.repo.products_by_ids(self.scope, [n.selection["product_id"] for n in led.active_needs() if n.selection])
        return {n.label: rows[n.selection["product_id"]]["kind"] for n in led.active_needs() if n.selection}

    def basket_names(self) -> list[str]:
        return [i["name"] for i in self.result.basket["items"]]


Check = Callable[[Ctx], bool]


@dataclass
class Journey:
    name: str
    turns: list[tuple[str, list[tuple[str, Check]]]]
    tags: list[str] = field(default_factory=list)


def grounded(c: Ctx) -> bool:
    return not c.result.grounding.get("issues")


def no_internal_terms(c: Ctx) -> bool:
    return not re.search(r"\b(ledger|need[_ ]id|n\d+\b|kind|taxonomy|tool|find_products|status code)\b", c.result.reply, re.I)


COMMON: list[tuple[str, Check]] = [("reply is grounded", grounded), ("no internal terms", no_internal_terms)]

JOURNEYS = [
    Journey("milk_is_milk", [
        ("mujhe chai ke liye doodh chahiye", [
            ("only liquid milk shown", lambda c: c.kinds_shown() <= {"dairy.milk"} and bool(c.kinds_shown())),
            ("replies in Roman Urdu or English, not Urdu script", lambda c: not URDU.search(c.result.reply)),
        ]),
    ], ["lesson-2"]),
    Journey("potatoes_not_chips", [
        ("2 kg aloo aur 1 kg pyaz", [
            ("plan has fresh potato and onion only", lambda c: set(c.plan_kinds().values()) == {"produce.potato", "produce.onion"}),
            ("2 packs of potatoes", lambda c: any(l["packs"] == 2 and "Potato" in l["name"] for k in c.result.cards if k["type"] == "plan" for l in k["lines"])),
        ]),
    ], ["lesson-3"]),
    Journey("biryani_masala_not_chaat", [
        ("biryani masala dikhao", [
            ("only biryani masala shown", lambda c: c.kinds_shown() == {"spices.biryani_masala"}),
        ]),
    ], ["lesson-4"]),
    Journey("recipe_plan", [
        ("chicken biryani banana hai 6 logon ke liye", [
            ("chicken, rice and biryani masala planned or asked about", lambda c: {"meat.chicken", "staples.rice", "spices.biryani_masala"} <= set(c.plan_kinds().values())
             or "?" in c.result.reply),
            ("no snacks or sweets in plan", lambda c: not any(k.startswith("snacks.") for k in c.plan_kinds().values())),
            ("basket untouched", lambda c: c.result.basket["items"] == []),
        ]),
    ], ["lesson-8", "lesson-9"]),
    Journey("weekly_budget", [
        ("I need weekly groceries for a family of 4, budget is 8000", [
            ("household recorded", lambda c: c.ledger().household.get("people") == 4),
            ("budget recorded", lambda c: any(b.amount == 8000 for b in c.ledger().budgets)),
            ("no need called budget/week", lambda c: not any(re.search(r"budget|week", n.label, re.I) for n in c.ledger().active_needs())),
            ("plan within budget or overage stated", lambda c: all(not b["over"] for k in c.result.cards if k["type"] == "plan" for b in k["budgets"])
             or re.search(r"over|zyada|exceed", c.result.reply, re.I) is not None),
        ]),
    ], ["lesson-1"]),
    Journey("correction_preserves_others", [
        ("doodh, anday aur chawal chahiye", [("three needs", lambda c: len(c.ledger().active_needs()) >= 3)]),
        ("Olpers nahi, koi aur doodh", [
            ("milk is not Olpers", lambda c: all("Olpers" not in l["name"] for k in c.result.cards if k["type"] == "plan" for l in k["lines"] if "Milk" in l["name"])
             and all("olpers" not in json.dumps(n.selection or {}).lower() for n in c.ledger().active_needs())),
            ("eggs and rice still chosen", lambda c: {"dairy.eggs", "staples.rice"} <= set(c.plan_kinds().values())),
        ]),
    ], ["lesson-6"]),
    Journey("basket_only_on_request", [
        ("doodh aur double roti", [("basket still empty", lambda c: c.result.basket["items"] == [])]),
        ("theek hai, basket mein daal do", [("basket has milk and bread", lambda c: len(c.result.basket["items"]) >= 2)]),
        ("double roti hata do", [
            ("bread removed, milk kept", lambda c: not any("Bread" in n for n in c.basket_names()) and any("Milk" in n for n in c.basket_names())),
        ]),
    ], ["lesson-9"]),
    Journey("honest_missing", [
        ("size 5 diapers chahiye", [
            ("nothing put in the basket", lambda c: c.result.basket["items"] == []),
            ("says it is not available", lambda c: re.search(r"not available|nahi (hai|mil)|don't have|do not have|dastyab nahi|only size 4|size 4", c.result.reply, re.I) is not None),
        ]),
    ], ["lesson-5"]),
    Journey("urdu_script", [
        ("مجھے چینی اور چائے کی پتی چاہیے", [
            ("replies in Urdu script", lambda c: URDU.search(c.result.reply) is not None),
            ("sugar and tea planned", lambda c: {"staples.sugar", "bev.tea"} <= set(c.plan_kinds().values()) or {"staples.sugar", "bev.tea"} <= c.kinds_shown()),
        ]),
    ], ["language"]),
    Journey("compare_value", [
        ("cooking oil mein sab se sasta per litre kaunsa hai?", [
            ("names the 5 L Habib oil as best per litre", lambda c: "Habib" in c.result.reply),
        ]),
    ], ["comparison"]),
]


def run(journey: Journey, model: str, effort: str) -> dict:
    with tempfile.TemporaryDirectory() as d:
        repo = Repo(Path(d) / "eval.db")
        scope = repo.add_store("demo-mart", "Demo Mart", "demo-khi", "Karachi", api_key="k")
        ingest.sync(repo, scope, str(ROOT / "data" / "sample_pk_grocery.csv"))
        agent, ctx = Agent(repo, model=model, effort=effort), Ctx(repo, scope, f"eval-{journey.name}")
        turns = []
        for message, checks in journey.turns:
            started = time.time()
            ctx.result = agent.handle(scope, ctx.session, message)
            outcomes = []
            for label, check in checks + COMMON:
                try:
                    ok = bool(check(ctx))
                except Exception as e:  # a crashing check is a failure, with the reason
                    ok, label = False, f"{label} (check error: {e})"
                outcomes.append({"check": label, "passed": ok})
            turns.append({"message": message, "reply": ctx.result.reply, "seconds": round(time.time() - started, 1),
                          "usage": ctx.result.usage, "grounding": ctx.result.grounding, "checks": outcomes})
        return {"journey": journey.name, "tags": journey.tags, "passed": all(o["passed"] for t in turns for o in t["checks"]), "turns": turns}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--only", help="run journeys whose name contains this")
    p.add_argument("--repeat", type=int, default=1, help="runs per journey (behaviour varies run to run)")
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--effort", default="medium")
    args = p.parse_args()
    selected = [j for j in JOURNEYS if not args.only or args.only in j.name]
    runs = []
    for j in selected:
        for i in range(args.repeat):
            r = run(j, args.model, args.effort)
            runs.append(r)
            mark = "PASS" if r["passed"] else "FAIL"
            print(f"{mark}  {j.name}  (run {i + 1})")
            for t in r["turns"]:
                for o in t["checks"]:
                    if not o["passed"]:
                        print(f"      ✗ {o['check']}  ← \"{t['message']}\"\n        reply: {t['reply'][:200]!r}")
    passed = sum(r["passed"] for r in runs)
    print(f"\n{passed}/{len(runs)} journey runs passed")
    out = ROOT / "evals" / "reports"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"model": args.model, "effort": args.effort, "runs": runs}, indent=1, ensure_ascii=False))
    print(f"Report: {path}")
    return 0 if passed == len(runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
