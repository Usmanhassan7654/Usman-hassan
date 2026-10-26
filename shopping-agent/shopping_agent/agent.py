"""The shopping agent: Claude + tools over a catalog, a cart and checkout.

The customer describes what they need in plain language ("stuff for a pasta
dinner for 4 under $25", "we're out of breakfast things"). Claude works out
the intent, searches the catalog, picks products, fills the cart, and walks
the customer through checkout. Orders are only placed after the customer has
explicitly confirmed a checkout summary in a later turn.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

import anthropic

from .cart import Cart, OrderStore
from .catalog import Catalog

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You are a friendly, efficient personal shopping assistant for an online store.
Your job is to take the customer from a vague need to a placed order with as little effort on their side as possible.

How to work:
- Understand the real intent behind a request. "Breakfast for the week for two" means turning it into a concrete shopping list (eggs, bread, milk, fruit, ...) with sensible quantities. "Ingredients for chicken biryani" means the recipe's ingredients. "We're out of cleaning stuff" means the usual household cleaning basics.
- Search the catalog for every item yourself; try alternative words if a search comes back empty (e.g. "ground beef" vs "mince"). Never invent products, prices or ids: only use what the tools return.
- Choose good-value, in-stock products that match the customer's stated preferences (budget, dietary needs, brands, household size). Remember preferences with save_preferences as soon as the customer mentions them.
- Act, don't interrogate. For clear requests, add the items to the cart straight away and tell the customer what you picked and why in a short list. Ask a question only when the answer really changes what you'd buy (e.g. allergy, a choice between very different options), and ask at most one or two questions at a time.
- Keep the customer within budget. If the cart would exceed it, pick cheaper alternatives or say what you left out.
- If something is unavailable, suggest the closest substitute and say so.
- After filling the cart, show a brief cart summary with the total and ask if they want changes or are ready to check out.
- Checkout: collect the customer's name, delivery address, preferred delivery slot and payment method (cash on delivery or card on delivery). Then call prepare_checkout and show the summary it returns. Only call place_order after the customer has clearly said yes to that summary in their next message.
- Keep replies short and scannable: bullet lists with item, quantity and price. Use the store's currency.
- The chat shows products as cards with a picture, price and Add / quantity buttons. Items you add to the cart appear as cards automatically. When the customer should choose between options, or asks to see products, call show_products with those ids instead of listing them in text. The customer can also change quantities with the buttons; you'll be told about those changes in their next message.

Store catalog overview:
{catalog_summary}
"""

TOOLS: list[dict] = [
    {
        "name": "search_products",
        "description": (
            "Search the store catalog. Use short product-style queries (e.g. 'whole milk', "
            "'basmati rice', 'dish soap'). Call it once per distinct item on the shopping list. "
            "Returns matching in-stock products with id, name, price, unit, category and tags."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for."},
                "category": {"type": "string", "description": "Optional category filter (substring match)."},
                "max_price": {"type": "number", "description": "Optional maximum unit price."},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional required tags, e.g. ['vegan'], ['gluten-free'], ['organic'].",
                },
                "sort": {"type": "string", "enum": ["relevance", "price_asc", "price_desc"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "show_products",
        "description": (
            "Show products to the customer as cards with picture, price and Add buttons, e.g. a few "
            "options to choose from. Items you add to the cart are shown automatically; don't repeat them here."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 12},
                "title": {"type": "string", "description": "Short heading, e.g. 'Pick a cooking oil'."},
            },
            "required": ["product_ids"],
        },
    },
    {
        "name": "get_product_details",
        "description": "Get the full details (description, stock, link) of one product by id.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}},
            "required": ["product_id"],
        },
    },
    {
        "name": "list_categories",
        "description": "List all catalog categories with how many products each has.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_to_cart",
        "description": "Add one or more products to the cart. Returns the updated cart.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "product_id": {"type": "string"},
                            "quantity": {"type": "integer", "minimum": 1},
                            "note": {"type": "string", "description": "Why it was added, e.g. 'for biryani'."},
                        },
                        "required": ["product_id", "quantity"],
                    },
                    "minItems": 1,
                }
            },
            "required": ["items"],
        },
    },
    {
        "name": "update_cart_item",
        "description": "Change the quantity of a product already in the cart. Quantity 0 removes it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "product_id": {"type": "string"},
                "quantity": {"type": "integer", "minimum": 0},
            },
            "required": ["product_id", "quantity"],
        },
    },
    {
        "name": "remove_from_cart",
        "description": "Remove a product from the cart.",
        "input_schema": {
            "type": "object",
            "properties": {"product_id": {"type": "string"}},
            "required": ["product_id"],
        },
    },
    {
        "name": "view_cart",
        "description": "Show the current cart, item count, total, and remaining budget if one is set.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_preferences",
        "description": (
            "Remember customer preferences for this session: budget, dietary needs, "
            "household size, favourite or avoided brands, anything else relevant."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "budget": {"type": "number", "description": "Total spending limit for this order."},
                "dietary": {"type": "array", "items": {"type": "string"}},
                "household_size": {"type": "integer", "minimum": 1},
                "notes": {"type": "string"},
            },
        },
    },
    {
        "name": "prepare_checkout",
        "description": (
            "Validate the cart and delivery details and produce an order summary for the customer "
            "to confirm. Does NOT place the order."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string"},
                "delivery_address": {"type": "string"},
                "delivery_slot": {"type": "string", "description": "e.g. 'tomorrow 9-11am'."},
                "payment_method": {"type": "string", "enum": ["cash_on_delivery", "card_on_delivery"]},
                "phone": {"type": "string"},
            },
            "required": ["customer_name", "delivery_address", "payment_method"],
        },
    },
    {
        "name": "place_order",
        "description": (
            "Place the order prepared by prepare_checkout. Only call this after the customer has "
            "explicitly confirmed the checkout summary in a message after you showed it."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


class ToolError(Exception):
    pass


@dataclass
class ShoppingSession:
    catalog: Catalog
    orders: OrderStore = field(default_factory=OrderStore)
    cart: Cart = field(default_factory=Cart)
    preferences: dict[str, Any] = field(default_factory=dict)
    pending_checkout: dict | None = None
    pending_checkout_turn: int = -1
    turn: int = 0
    last_order: dict | None = None
    # Product cards to show in the chat for the current turn: [{"title", "product_ids"}].
    displays: list[dict] = field(default_factory=list)
    # Cart changes the customer made with the buttons, reported to Claude on the next message.
    ui_changes: list[str] = field(default_factory=list)

    # ----------------------------------------------------------- tool impls

    def execute(self, name: str, args: dict) -> dict:
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            raise ToolError(f"Unknown tool: {name}")
        return handler(**args)

    def tool_search_products(self, query: str, category: str | None = None, max_price: float | None = None,
                             tags: list[str] | None = None, sort: str = "relevance", limit: int = 8) -> dict:
        results = self.catalog.search(query, category=category, max_price=max_price, tags=tags,
                                      sort=sort, limit=max(1, min(int(limit), 20)))
        if not results and (category or tags or max_price is not None):
            # Retry without filters so the agent can see near misses.
            loose = self.catalog.search(query, limit=5)
            return {
                "results": [],
                "note": "No match with those filters. Closest products without filters:",
                "unfiltered_results": [p.to_dict(compact=True) for p in loose],
            }
        return {"results": [p.to_dict(compact=True) for p in results]}

    def tool_get_product_details(self, product_id: str) -> dict:
        product = self.catalog.get(product_id)
        if not product:
            raise ToolError(f"No product with id '{product_id}'.")
        return product.to_dict()

    def tool_list_categories(self) -> dict:
        counts: dict[str, int] = {}
        for p in self.catalog.products.values():
            counts[p.category or "Uncategorized"] = counts.get(p.category or "Uncategorized", 0) + 1
        return {"categories": counts}

    def tool_add_to_cart(self, items: list[dict]) -> dict:
        added, errors, added_ids = [], [], []
        for item in items:
            pid = str(item.get("product_id", ""))
            product = self.catalog.get(pid)
            if not product:
                errors.append(f"No product with id '{pid}'.")
                continue
            try:
                self.cart.add(product, int(item.get("quantity", 1)), item.get("note", ""))
                added.append(f"{item.get('quantity', 1)} x {product.name}")
                added_ids.append(product.id)
            except ValueError as e:
                errors.append(str(e))
        if added_ids:
            self._display("Added to your cart", added_ids)
        self._invalidate_checkout()
        return {"added": added, "errors": errors, "cart": self.cart_view()}

    def tool_show_products(self, product_ids: list[str], title: str = "") -> dict:
        found = [pid for pid in product_ids if self.catalog.get(str(pid))]
        missing = [pid for pid in product_ids if not self.catalog.get(str(pid))]
        if not found:
            raise ToolError("None of those product ids exist.")
        self._display(title or "Products", [str(pid) for pid in found])
        return {"shown": len(found), **({"unknown_ids": missing} if missing else {})}

    def tool_update_cart_item(self, product_id: str, quantity: int) -> dict:
        try:
            self.cart.set_quantity(product_id, int(quantity))
        except (KeyError, ValueError) as e:
            raise ToolError(str(e).strip("'\"")) from e
        self._invalidate_checkout()
        return {"cart": self.cart_view()}

    def tool_remove_from_cart(self, product_id: str) -> dict:
        try:
            self.cart.remove(product_id)
        except KeyError as e:
            raise ToolError(str(e).strip("'\"")) from e
        self._invalidate_checkout()
        return {"cart": self.cart_view()}

    def tool_view_cart(self) -> dict:
        return {"cart": self.cart_view()}

    def tool_save_preferences(self, **prefs) -> dict:
        self.preferences.update({k: v for k, v in prefs.items() if v not in (None, "", [])})
        return {"preferences": self.preferences, "cart": self.cart_view()}

    def tool_prepare_checkout(self, customer_name: str, delivery_address: str, payment_method: str,
                              delivery_slot: str = "", phone: str = "") -> dict:
        if not self.cart.lines:
            raise ToolError("The cart is empty.")
        if not customer_name.strip() or not delivery_address.strip():
            raise ToolError("Customer name and delivery address are required.")
        for line in self.cart.lines.values():
            if not line.product.in_stock:
                raise ToolError(f"'{line.product.name}' is now out of stock; replace or remove it.")
        self.pending_checkout = {
            "customer_name": customer_name.strip(),
            "delivery_address": delivery_address.strip(),
            "delivery_slot": delivery_slot.strip() or "earliest available",
            "payment_method": payment_method,
            "phone": phone.strip(),
        }
        self.pending_checkout_turn = self.turn
        return {
            "summary": {"customer": self.pending_checkout, **self.cart_view()},
            "next_step": "Show this summary and ask the customer to confirm. Wait for their reply before place_order.",
        }

    def tool_place_order(self) -> dict:
        if not self.pending_checkout:
            raise ToolError("No checkout prepared. Call prepare_checkout first.")
        if self.pending_checkout_turn >= self.turn:
            raise ToolError("The customer has not confirmed the summary yet. Show it and wait for their reply.")
        order = self.orders.place(self.cart, self.pending_checkout, self.catalog)
        self.last_order = order
        self.pending_checkout = None
        return {"order": order}

    # ------------------------------------------------------ customer buttons

    def set_quantity_from_ui(self, product_id: str, quantity: int) -> dict:
        """Apply an Add / + / - click from a product card, without a Claude round trip."""
        product = self.catalog.get(product_id)
        if not product:
            raise ToolError(f"No product with id '{product_id}'.")
        quantity = max(0, int(quantity))
        current = self.cart.lines[product_id].quantity if product_id in self.cart.lines else 0
        if quantity == current:
            return self.cart_view(images=True)
        if current == 0:
            self.cart.add(product, quantity)
        else:
            self.cart.set_quantity(product_id, quantity)
        self.ui_changes.append(f"{product.name} ({product_id}): {current} -> {quantity}")
        self._invalidate_checkout()
        return self.cart_view(images=True)

    def take_displays(self) -> list[dict]:
        """Product cards for this turn, with the details the UI needs."""
        groups = []
        for d in self.displays:
            products = []
            for pid in dict.fromkeys(d["product_ids"]):
                product = self.catalog.get(pid)
                if product:
                    card = product.to_dict()
                    card["in_cart"] = self.cart.lines[pid].quantity if pid in self.cart.lines else 0
                    products.append(card)
            if products:
                groups.append({"title": d["title"], "products": products})
        self.displays = []
        return groups

    # -------------------------------------------------------------- helpers

    def _display(self, title: str, product_ids: list[str]) -> None:
        # Repeated adds in one turn go into one "Added to your cart" group.
        for d in self.displays:
            if d["title"] == title:
                d["product_ids"].extend(product_ids)
                return
        self.displays.append({"title": title, "product_ids": list(product_ids)})

    def _invalidate_checkout(self) -> None:
        self.pending_checkout = None

    def cart_view(self, images: bool = False) -> dict:
        view = self.cart.to_dict()
        if not images:
            for item in view["items"]:
                item.pop("image", None)
        budget = self.preferences.get("budget")
        if budget:
            view["budget"] = budget
            view["remaining_budget"] = round(float(budget) - view["total"], 2)
            view["over_budget"] = view["total"] > float(budget)
        return view


EventCallback = Callable[[str, dict], None]


class ShoppingAgent:
    """Runs the Claude tool-use loop for one customer conversation."""

    def __init__(self, catalog: Catalog, client: Any | None = None, model: str = MODEL,
                 effort: str = "medium", orders: OrderStore | None = None, max_steps: int = 40):
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_steps = max_steps
        self.session = ShoppingSession(catalog=catalog, orders=orders or OrderStore())
        self.system = SYSTEM_PROMPT.format(catalog_summary=catalog.summary())
        self.messages: list[dict] = []

    def _create(self):
        return self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=self.system,
            tools=TOOLS,
            messages=self.messages,
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            # On a safety decline, re-run on Anthropic's recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def chat(self, user_text: str, on_event: EventCallback | None = None) -> str:
        emit = on_event or (lambda kind, data: None)
        self.session.turn += 1
        if self.session.ui_changes:
            note = "; ".join(self.session.ui_changes)
            user_text = f"[The customer changed the cart with the buttons: {note}]\n\n{user_text}"
            self.session.ui_changes = []
        self.messages.append({"role": "user", "content": user_text})
        text_parts: list[str] = []

        for _ in range(self.max_steps):
            response = self._create()
            self.messages.append({"role": "assistant", "content": response.content})

            for block in response.content:
                if block.type == "text" and block.text.strip():
                    text_parts.append(block.text)

            if response.stop_reason == "refusal":
                return "Sorry, I can't help with that request. Is there something else you'd like to shop for?"
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                break

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                emit("tool_call", {"name": block.name, "input": block.input})
                try:
                    output = self.session.execute(block.name, dict(block.input or {}))
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": json.dumps(output)})
                    emit("tool_result", {"name": block.name, "output": output})
                except (ToolError, TypeError, ValueError) as e:
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"Error: {e}", "is_error": True})
                    emit("tool_error", {"name": block.name, "error": str(e)})
            # All tool results go back in a single user message.
            self.messages.append({"role": "user", "content": results})
        else:
            text_parts.append("(I hit my step limit for this turn. Tell me how you'd like to continue.)")

        return "\n\n".join(text_parts).strip()
