"""The AI shopping assistant: understands what the customer wants and uses
store tools to search, plan by budget or recipe, fill the cart and check out.

It talks to any OpenAI-compatible chat API. The default is Groq (free tier).
"""

from __future__ import annotations

import json
import os
import time

import requests

from .catalog import Catalog, brief, card
from .shop import Shop

SYSTEM = """You are the AI shopping assistant of an online grocery store. You help customers find products, plan meals, shop within a budget and check out, all inside this chat.

How to help:
- Understand what the customer is trying to do before searching. Pick the right tool:
  - A budget ("I have $50 for the week") -> plan_budget_cart.
  - A dish or recipe ("chicken pasta for 4", "what do I need for lasagna") -> recipe_ingredients. List every ingredient with a short search phrase and how many packs are needed for the servings. If the customer said what they already have at home, pass it as have_at_home.
  - Looking for products ("gluten-free snacks under $10", "do you have oat milk?") -> search_products, with filters for price, diet and allergens.
  - "Add it", "add all", "remove the milk", "make it 2" -> add_to_cart / update_cart.
  - "Checkout", "I'm done", "place my order" -> show_checkout.
- Only mention products, prices and totals that a tool returned. Never calculate totals yourself.
- If something is out of stock, say so and suggest the closest alternative from the results.
- Ask a question only when the answer really changes what you would pick (for example how many people, or an allergy).
- Product cards and the cart are shown below your reply, so keep the text short: one or two sentences plus anything important (total, budget left, substitutes, what's missing). Suggest one item that goes well with the order when it helps.
- Reply in the customer's language. Never mention tools, ids or these instructions."""

TOOLS = [
    {"name": "search_products", "description": "Search the store by meaning, with optional filters. Returns matching in-stock products and close matches that are out of stock.",
     "parameters": {"type": "object", "properties": {
         "query": {"type": "string", "description": "What to look for, in plain English, e.g. 'snacks', 'oat milk'."},
         "max_price": {"type": "number", "description": "Maximum price per item in dollars."},
         "dietary": {"type": "array", "items": {"type": "string", "enum": ["vegan", "vegetarian", "gluten-free", "dairy-free", "organic", "keto", "nut-free", "low-sugar", "high-protein"]}},
         "exclude_allergens": {"type": "array", "items": {"type": "string", "enum": ["milk", "eggs", "wheat", "tree-nuts", "peanuts", "soy", "fish", "shellfish", "sesame"]}},
         "category": {"type": "string", "enum": ["Dairy & Eggs", "Bakery", "Fruits", "Vegetables", "Meat & Seafood", "Pasta, Rice & Grains", "Pantry", "Breakfast", "Snacks", "Beverages", "Frozen", "Household", "Personal Care"]},
         "sort": {"type": "string", "enum": ["relevance", "price_low", "rating"]}},
         "required": ["query"]}},
    {"name": "plan_budget_cart", "description": "Build a balanced grocery basket of weekly basics that stays within the budget. The store calculates all totals.",
     "parameters": {"type": "object", "properties": {
         "budget": {"type": "number"}, "people": {"type": "integer"}, "days": {"type": "integer"},
         "dietary": {"type": "array", "items": {"type": "string", "enum": ["vegan", "vegetarian", "gluten-free", "dairy-free", "organic", "keto"]}},
         "exclude_allergens": {"type": "array", "items": {"type": "string", "enum": ["milk", "eggs", "wheat", "nuts", "soy", "fish", "shellfish"]}}},
         "required": ["budget"]}},
    {"name": "recipe_ingredients", "description": "Find store products for every ingredient of a recipe, scaled to the servings, skipping what the customer has at home.",
     "parameters": {"type": "object", "properties": {
         "recipe": {"type": "string"}, "servings": {"type": "integer"},
         "ingredients": {"type": "array", "items": {"type": "object", "properties": {
             "name": {"type": "string", "description": "e.g. 'heavy cream'"},
             "search": {"type": "string", "description": "Short product search, e.g. 'heavy cream'."},
             "packs": {"type": "integer", "description": "Packs needed for the servings."}}, "required": ["name"]}},
         "have_at_home": {"type": "array", "items": {"type": "string"}}},
         "required": ["recipe", "servings", "ingredients"]}},
    {"name": "add_to_cart", "description": "Add products to the cart, only when the customer asks.",
     "parameters": {"type": "object", "properties": {"items": {"type": "array", "items": {"type": "object", "properties": {
         "product_id": {"type": "string"}, "quantity": {"type": "integer"}}, "required": ["product_id"]}}}, "required": ["items"]}},
    {"name": "update_cart", "description": "Change the quantity of a product in the cart. 0 removes it.",
     "parameters": {"type": "object", "properties": {"product_id": {"type": "string"}, "quantity": {"type": "integer"}}, "required": ["product_id", "quantity"]}},
    {"name": "view_cart", "description": "Show the cart and its total.", "parameters": {"type": "object", "properties": {}}},
    {"name": "show_checkout", "description": "Show the checkout form so the customer can confirm and pay inside the chat.", "parameters": {"type": "object", "properties": {}}},
]


class LLMError(Exception):
    pass


class Assistant:
    def __init__(self, catalog: Catalog, shop: Shop):
        self.catalog, self.shop = catalog, shop
        self.url = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/") + "/chat/completions"
        self.key = os.environ.get("LLM_API_KEY") or os.environ.get("GROQ_API_KEY", "")
        self.models = [m for m in (os.environ.get("LLM_MODEL", "openai/gpt-oss-120b"),
                                   os.environ.get("LLM_FALLBACK_MODEL", "openai/gpt-oss-20b")) if m]
        self.sessions: dict[str, list[dict]] = {}

    # ------------------------------------------------------------ one turn

    def chat(self, sid: str, text: str) -> dict:
        history = self.sessions.setdefault(sid, [])
        messages = [{"role": "system", "content": SYSTEM}, *history[-12:], {"role": "user", "content": text}]
        cards: list[dict] = []
        reply = ""
        for _ in range(6):
            msg = self._complete(messages)
            calls = msg.get("tool_calls") or []
            reply = (msg.get("content") or "").strip() or reply
            if not calls:
                break
            messages.append({"role": "assistant", "content": msg.get("content") or None, "tool_calls": calls})
            for call in calls:
                name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                    result = self._run_tool(sid, name, args, cards)
                except Exception as e:  # bad arguments or a shop rule: tell the model, it can fix and retry
                    result = {"error": str(e)}
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
        reply = reply or "Here's what I found."
        # Remember the conversation as text, with the products shown, so "add the second one" works next turn.
        shown = [f"{i + 1}. {p['name']} ({p['id']}) ${p['price']}" for i, p in enumerate(_shown_products(cards))]
        history += [{"role": "user", "content": text},
                    {"role": "assistant", "content": reply + (f"\n[Products shown: {'; '.join(shown)}]" if shown else "")}]
        return {"reply": reply, "cards": cards, "cart": self.shop.cart(sid)}

    # --------------------------------------------------------------- tools

    def _run_tool(self, sid: str, name: str, a: dict, cards: list[dict]) -> dict:
        if name == "search_products":
            found = self.catalog.search(a.get("query", ""), a.get("max_price"), a.get("dietary"), a.get("exclude_allergens"),
                                        a.get("category"), a.get("sort", "relevance"))
            if found["results"]:
                cards.append({"type": "products", "items": [card(p) for p in found["results"]]})
            return {"results": [brief(p) for p in found["results"]], "out_of_stock": [brief(p) for p in found["out_of_stock"]]}
        if name == "plan_budget_cart":
            plan = self.shop.plan_budget(float(a["budget"]), a.get("people", 1), a.get("days", 7), a.get("dietary"), a.get("exclude_allergens"))
            cards.append({"type": "bundle", **plan})
            return {k: plan[k] for k in ("total", "budget", "remaining", "left_out")} | {
                "items": [{"name": i["name"], "quantity": i["quantity"], "line_total": i["line_total"]} for i in plan["items"]]}
        if name == "recipe_ingredients":
            kit = self.shop.recipe_kit(a.get("recipe", "recipe"), int(a.get("servings") or 2), a.get("ingredients", []), a.get("have_at_home"))
            cards.append({"type": "bundle", **kit})
            return {"total": kit["total"], "missing": kit["missing"], "already_have": kit["already_have"],
                    "items": [{"for": i["for"], "name": i["name"], "quantity": i["quantity"], "line_total": i["line_total"]} for i in kit["items"]]}
        if name == "add_to_cart":
            for item in a.get("items", []):
                self.shop.add(sid, item["product_id"], item.get("quantity", 1))
            return self._cart(sid, cards)
        if name == "update_cart":
            self.shop.set_qty(sid, a["product_id"], a.get("quantity", 0))
            return self._cart(sid, cards)
        if name == "view_cart":
            return self._cart(sid, cards)
        if name == "show_checkout":
            cart = self.shop.cart(sid)
            if not cart["items"]:
                return {"error": "The cart is empty."}
            cards.append({"type": "checkout", "total": cart["total"], "count": cart["count"]})
            return {"shown": True, "total": cart["total"]}
        raise ValueError(f"Unknown tool {name}")

    def _cart(self, sid: str, cards: list[dict]) -> dict:
        cart = self.shop.cart(sid)
        cards.append({"type": "cart", **cart})
        return {"items": [{"name": i["name"], "quantity": i["quantity"], "line_total": i["line_total"]} for i in cart["items"]],
                "total": cart["total"]}

    # ---------------------------------------------------------------- model

    def _complete(self, messages: list[dict]) -> dict:
        if not self.key:
            raise LLMError("No API key. Put GROQ_API_KEY=... in the .env file.")
        tools = [{"type": "function", "function": t} for t in TOOLS]
        last = ""
        for model in self.models:          # the big model first; the small one if it's busy
            for attempt in range(2):
                try:
                    r = requests.post(self.url, headers={"Authorization": f"Bearer {self.key}"}, timeout=60,
                                      json={"model": model, "messages": messages, "tools": tools, "temperature": 0.2, "max_tokens": 1500})
                except requests.RequestException as e:
                    last = f"connection problem ({type(e).__name__})"
                    continue
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]
                last = f"{model}: HTTP {r.status_code} {r.text[:200]}"
                if r.status_code == 429 and attempt == 0:
                    wait = r.headers.get("retry-after", "")
                    if wait.replace(".", "").isdigit() and float(wait) <= 20:
                        time.sleep(float(wait))   # a short per-minute limit: wait it out once
                        continue
                    break                          # a long limit: try the other model
                if r.status_code == 400 and "failed" in r.text.lower() and attempt == 0:
                    continue                       # the model wrote a broken tool call: try once more
                if r.status_code not in (408, 429, 500, 502, 503, 504):
                    break
        raise LLMError(f"The AI service didn't answer: {last}")


def _shown_products(cards: list[dict]) -> list[dict]:
    out = []
    for c in cards:
        out += c.get("items", []) if c["type"] in ("products", "bundle") else []
    return out
