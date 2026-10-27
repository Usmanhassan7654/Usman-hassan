"""Cart, budget planner, recipe kits and demo checkout.

All prices and totals are calculated here, never by the AI model.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path

from .catalog import DATA, Catalog, card

# Weekly basics for the budget planner, most important first:
# (what, suitable products with the preferred one first, packs per this many people per week).
# The first CORE basics get their preferred product when it fits; the rest are extras.
BUDGET_STAPLES = [
    ("milk", ["Organic Whole Milk", "2% Reduced Fat Milk", "Oat Milk Original", "Unsweetened Almond Milk"], 2),
    ("eggs", ["Pasture-Raised Eggs", "Large White Eggs"], 3),
    ("bread", ["Whole Wheat Sandwich Bread", "White Sandwich Bread", "Gluten-Free Bread"], 2),
    ("protein", ["Fresh Chicken Breasts", "Chicken Thighs Boneless", "Ground Turkey", "Plant-Based Burger Patties", "Chickpeas"], 2),
    ("rice", ["Jasmine Rice", "Long Grain White Rice", "Brown Rice"], 4),
    ("vegetables", ["Farm Fresh Vegetables Bundle", "Frozen Mixed Vegetables", "Broccoli Crowns", "Carrots"], 2),
    ("fruit", ["Seasonal Fruit Medley", "Gala Apples", "Bananas"], 2),
    ("bananas", ["Bananas"], 2),
    ("pasta", ["Artisan Pasta", "Spaghetti", "Gluten-Free Penne"], 3),
    ("pasta sauce", ["Marinara Sauce", "Crushed Tomatoes"], 3),
    ("yogurt", ["Greek Yogurt Plain", "Strawberry Yogurt Cups"], 3),
    ("onions", ["Yellow Onions"], 4),
    ("tomatoes", ["Roma Tomatoes"], 3),
    ("oats", ["Rolled Oats", "Instant Oatmeal Variety"], 4),
    ("beans", ["Black Beans", "Chickpeas"], 2),
    ("cheese", ["Sharp Cheddar Cheese", "Vegan Cheddar Shreds"], 4),
    ("potatoes", ["Russet Potatoes", "Sweet Potatoes"], 4),
    ("juice", ["Orange Juice No Pulp", "Apple Juice"], 3),
]
CORE = 7


class Shop:
    def __init__(self, catalog: Catalog, orders_path: Path = DATA / "orders.json"):
        self.catalog = catalog
        self.carts: dict[str, dict[str, int]] = {}
        self.orders_path = orders_path

    # ----------------------------------------------------------------- cart

    def cart(self, sid: str) -> dict:
        lines = []
        for pid, qty in self.carts.get(sid, {}).items():
            p = self.catalog.by_id[pid]
            lines.append(card(p, qty))
        total = round(sum(l["line_total"] for l in lines), 2)
        return {"items": lines, "count": sum(l["quantity"] for l in lines), "total": total}

    def set_qty(self, sid: str, pid: str, qty: int) -> dict:
        p = self.catalog.by_id.get(pid)
        if not p:
            raise ValueError(f"Unknown product {pid}.")
        cart = self.carts.setdefault(sid, {})
        qty = max(0, min(int(qty), 50))
        if qty and p["stock"] <= 0:
            raise ValueError(f"{p['name']} is out of stock.")
        if qty > p["stock"]:
            raise ValueError(f"Only {p['stock']} of {p['name']} left.")
        if qty == 0:
            cart.pop(pid, None)
        else:
            cart[pid] = qty
        return self.cart(sid)

    def add(self, sid: str, pid: str, qty: int = 1) -> dict:
        return self.set_qty(sid, pid, self.carts.get(sid, {}).get(pid, 0) + max(1, int(qty)))

    # --------------------------------------------------------------- budget

    def plan_budget(self, budget: float, people: int = 1, days: int = 7, dietary: list[str] | None = None,
                    exclude_allergens: list[str] | None = None, skip: list[str] | None = None) -> dict:
        """Fill a cart with weekly basics without going over the budget.

        Pass 1 covers as many basics as possible with the cheapest suitable product.
        Pass 2 spends what is left upgrading to the preferred product of each basic.
        """
        people, days = max(1, int(people)), max(1, int(days))
        skip_words = {w.lower() for w in skip or []}
        need = {d.lower() for d in dietary or []}
        avoid = set()
        for a in exclude_allergens or []:
            avoid.update({"nuts": ["tree-nuts", "peanuts"], "dairy": ["milk"], "gluten": ["wheat"]}.get(a.lower(), [a.lower()]))
        by_name = {p["name"]: p for p in self.catalog.products}

        def suitable(name: str) -> bool:
            p = by_name.get(name)
            return bool(p) and p["stock"] > 0 and need <= set(p["dietary"]) and not avoid & set(p["allergens"])

        plan, total, left_out = [], 0.0, []
        for rank, (what, names, per) in enumerate(BUDGET_STAPLES):
            options = [by_name[n] for n in names if suitable(n)]
            taken = {x[1]["id"] for x in plan}
            options = [o for o in options if o["id"] not in taken]
            if what in skip_words or not options:
                continue
            qty = max(1, math.ceil(people / per * days / 7))
            cheapest = min(options, key=lambda o: o["price"])
            # Core basics: the preferred product if it still leaves room for the cheapest version of the other core items.
            reserve = sum(min((by_name[n]["price"] for n in names_ if suitable(n)), default=0)
                          for _, names_, _ in BUDGET_STAPLES[rank + 1:CORE])
            first = options[0] if rank < CORE and total + options[0]["price"] * qty + reserve <= budget else cheapest
            pick = first
            while qty and total + pick["price"] * qty > budget:
                qty -= 1
            if qty:
                plan.append([what, pick, qty, options[0]])
                total = round(total + pick["price"] * qty, 2)
            else:
                left_out.append(what)
        for line in plan:  # upgrade where the money allows
            what, current, qty, preferred = line
            extra = (preferred["price"] - current["price"]) * qty
            if preferred is not current and total + extra <= budget:
                line[1] = preferred
                total = round(total + extra, 2)
        items = [card(p, q) for _, p, q, _ in plan]
        return {"kind": "budget", "title": f"Weekly basics for {people} {'person' if people == 1 else 'people'} within ${budget:g}",
                "items": items, "total": round(total, 2), "budget": budget, "remaining": round(budget - total, 2), "left_out": left_out}

    # --------------------------------------------------------------- recipe

    def recipe_kit(self, recipe: str, servings: int, ingredients: list[dict], have_at_home: list[str] | None = None) -> dict:
        """Match each ingredient to a product; skip what the customer already has."""
        home = [h.lower() for h in have_at_home or []]
        items, missing, skipped = [], [], []
        for ing in ingredients:
            name = str(ing.get("name", "")).strip()
            if not name:
                continue
            if any(h in name.lower() or name.lower() in h for h in home):
                skipped.append(name)
                continue
            p = self.catalog.best(str(ing.get("search") or name))
            if not p:
                missing.append(name)
                continue
            item = card(p, max(1, int(ing.get("packs") or 1)))
            item["for"] = name
            items.append(item)
        total = round(sum(i["line_total"] for i in items), 2)
        return {"kind": "recipe", "title": f"{recipe.title()} for {servings}", "items": items, "total": total,
                "missing": missing, "already_have": skipped}

    # ------------------------------------------------------------- checkout

    def checkout(self, sid: str, name: str, address: str, payment: str) -> dict:
        """Demo checkout: records the order; no real payment is taken."""
        cart = self.cart(sid)
        if not cart["items"]:
            raise ValueError("Your cart is empty.")
        if not name.strip() or not address.strip():
            raise ValueError("Please enter your name and delivery address.")
        for line in cart["items"]:
            self.catalog.by_id[line["id"]]["stock"] -= line["quantity"]
        order = {"order_id": "HB-" + uuid.uuid4().hex[:6].upper(), "placed_at": time.strftime("%Y-%m-%d %H:%M"),
                 "name": name.strip(), "address": address.strip(), "payment": payment, "items": cart["items"],
                 "total": cart["total"], "eta": "25 minutes", "demo": True}
        orders = json.loads(self.orders_path.read_text()) if self.orders_path.exists() else []
        orders.append(order)
        self.orders_path.write_text(json.dumps(orders, indent=1))
        self.carts[sid] = {}
        return order
