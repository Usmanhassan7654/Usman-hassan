"""AI shopping assistant: turns plain-language needs into a filled cart and a placed order."""

from .agent import ShoppingAgent, ShoppingSession
from .cart import Cart, OrderStore
from .catalog import Catalog, Product, load_source

__all__ = ["ShoppingAgent", "ShoppingSession", "Cart", "OrderStore", "Catalog", "Product", "load_source"]
