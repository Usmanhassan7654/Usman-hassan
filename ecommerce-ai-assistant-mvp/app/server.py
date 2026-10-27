"""Web server: the chat page, product pictures and a small JSON API."""

from __future__ import annotations

import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from .agent import Assistant, LLMError  # noqa: E402  (reads the key from .env)
from .catalog import Catalog  # noqa: E402
from .shop import Shop  # noqa: E402

catalog = Catalog()
shop = Shop(catalog)
assistant = Assistant(catalog, shop)

app = FastAPI(title="Ecommerce AI Assistant MVP")
app.mount("/images", StaticFiles(directory=ROOT / "data" / "images"), name="images")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    session_id: str | None = None


class CartIn(BaseModel):
    session_id: str
    items: list[dict]          # [{"product_id": "...", "quantity": 1}]
    mode: str = "add"          # add | set


class CheckoutIn(BaseModel):
    session_id: str
    name: str
    address: str
    payment: str = "card"


@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "app" / "static" / "index.html")


@app.get("/api/info")
def info() -> dict:
    return {"products": len(catalog.products), "search": catalog.mode, "ai_ready": bool(assistant.key)}


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    sid = body.session_id or uuid.uuid4().hex
    try:
        out = assistant.chat(sid, body.message.strip())
    except LLMError as e:
        raise HTTPException(503, str(e)) from e
    return {"session_id": sid, **out}


@app.get("/api/cart/{sid}")
def get_cart(sid: str) -> dict:
    return shop.cart(sid)


@app.post("/api/cart")
def change_cart(body: CartIn) -> dict:
    """Buttons on product cards change the cart directly, without the AI."""
    try:
        for item in body.items:
            if body.mode == "set":
                shop.set_qty(body.session_id, item["product_id"], item.get("quantity", 0))
            else:
                shop.add(body.session_id, item["product_id"], item.get("quantity", 1))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e)) from e
    return shop.cart(body.session_id)


@app.post("/api/checkout")
def checkout(body: CheckoutIn) -> dict:
    try:
        return {"order": shop.checkout(body.session_id, body.name, body.address, body.payment), "cart": shop.cart(body.session_id)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
