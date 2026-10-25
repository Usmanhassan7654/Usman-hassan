"""Shopping cart and checkout."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import Catalog, Product


@dataclass
class CartLine:
    product: Product
    quantity: int
    note: str = ""

    @property
    def subtotal(self) -> float:
        return round(self.product.price * self.quantity, 2)


@dataclass
class Cart:
    lines: dict[str, CartLine] = field(default_factory=dict)

    def add(self, product: Product, quantity: int = 1, note: str = "") -> CartLine:
        if quantity < 1:
            raise ValueError("Quantity must be at least 1.")
        if not product.in_stock:
            raise ValueError(f"'{product.name}' is out of stock.")
        line = self.lines.get(product.id)
        new_qty = quantity + (line.quantity if line else 0)
        if product.stock is not None and new_qty > product.stock:
            raise ValueError(f"Only {product.stock} of '{product.name}' in stock.")
        if line:
            line.quantity = new_qty
            line.note = note or line.note
        else:
            line = self.lines[product.id] = CartLine(product, quantity, note)
        return line

    def set_quantity(self, product_id: str, quantity: int) -> None:
        if product_id not in self.lines:
            raise KeyError(f"Product {product_id} is not in the cart.")
        if quantity <= 0:
            del self.lines[product_id]
            return
        stock = self.lines[product_id].product.stock
        if stock is not None and quantity > stock:
            raise ValueError(f"Only {stock} in stock.")
        self.lines[product_id].quantity = quantity

    def remove(self, product_id: str) -> None:
        if self.lines.pop(product_id, None) is None:
            raise KeyError(f"Product {product_id} is not in the cart.")

    def clear(self) -> None:
        self.lines.clear()

    @property
    def total(self) -> float:
        return round(sum(line.subtotal for line in self.lines.values()), 2)

    @property
    def item_count(self) -> int:
        return sum(line.quantity for line in self.lines.values())

    def to_dict(self) -> dict:
        currency = next((l.product.currency for l in self.lines.values()), "USD")
        return {
            "items": [
                {
                    "product_id": pid,
                    "name": line.product.name,
                    "unit": line.product.unit,
                    "unit_price": line.product.price,
                    "quantity": line.quantity,
                    "subtotal": line.subtotal,
                    **({"note": line.note} if line.note else {}),
                }
                for pid, line in self.lines.items()
            ],
            "item_count": self.item_count,
            "total": self.total,
            "currency": currency,
        }


class OrderStore:
    """Places orders. The default implementation writes them to a JSONL file.

    Swap `place` for a call to your store's checkout / order API (Shopify
    Admin API, WooCommerce REST, Stripe Checkout, ...) to go live.
    """

    def __init__(self, path: str | Path = "orders.jsonl"):
        self.path = Path(path)

    def place(self, cart: Cart, customer: dict, catalog: Catalog | None = None) -> dict:
        if not cart.lines:
            raise ValueError("Cart is empty.")
        order = {
            "order_id": "ORD-" + uuid.uuid4().hex[:8].upper(),
            "placed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "customer": customer,
            **cart.to_dict(),
            "status": "confirmed",
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(order) + "\n")
        # Reserve stock in the in-memory catalog.
        for line in cart.lines.values():
            if line.product.stock is not None:
                line.product.stock -= line.quantity
        cart.clear()
        return order
