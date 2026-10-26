"""Web chat UI for the shopping agent.

    CATALOG_SOURCE=data/sample_grocery.csv uvicorn shopping_agent.server:app --reload

Then open http://localhost:8000. Each browser tab gets its own session.
"""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .agent import MODEL, ShoppingAgent, ToolError
from .cart import OrderStore
from .catalog import Catalog, load_csv_text, load_json_data, load_source

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="AI Shopping Assistant")
_lock = threading.Lock()
_state: dict = {"catalog": None}
_sessions: dict[str, ShoppingAgent] = {}
_orders = OrderStore(os.environ.get("ORDERS_PATH", "orders.jsonl"))


def _catalog() -> Catalog:
    if _state["catalog"] is None:
        source = os.environ.get("CATALOG_SOURCE", str(Path(__file__).parents[1] / "data" / "sample_grocery.csv"))
        _state["catalog"] = load_source(source)
    return _state["catalog"]


def _agent(session_id: str) -> ShoppingAgent:
    with _lock:
        if session_id not in _sessions:
            _sessions[session_id] = ShoppingAgent(
                _catalog(), model=os.environ.get("SHOPPING_MODEL", MODEL),
                effort=os.environ.get("SHOPPING_EFFORT", "medium"), orders=_orders,
            )
        return _sessions[session_id]


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


class CartItemIn(BaseModel):
    product_id: str
    quantity: int


class SourceIn(BaseModel):
    source: str


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/catalog")
def catalog_info() -> dict:
    cat = _catalog()
    return {"source": cat.source, "count": len(cat), "categories": cat.categories()}


def _set_catalog(catalog: Catalog) -> dict:
    if not len(catalog):
        raise HTTPException(400, "No products found in that source.")
    with _lock:
        _state["catalog"] = catalog
        _sessions.clear()  # carts reference the old catalog
    return {"source": catalog.source, "count": len(catalog), "categories": catalog.categories()}


@app.post("/api/catalog/source")
def set_source(body: SourceIn) -> dict:
    try:
        return _set_catalog(load_source(body.source.strip()))
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/catalog/upload")
async def upload_catalog(file: UploadFile = File(...)) -> dict:
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    name = file.filename or "upload"
    try:
        if name.lower().endswith(".json"):
            import json

            return _set_catalog(load_json_data(json.loads(text), source=name))
        return _set_catalog(load_csv_text(text, source=name))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    session_id = body.session_id or uuid.uuid4().hex
    agent = _agent(session_id)
    steps: list[dict] = []

    def on_event(kind: str, data: dict) -> None:
        if kind == "tool_call":
            steps.append({"tool": data["name"], "input": data["input"]})

    reply = agent.chat(body.message, on_event=on_event)
    order, agent.session.last_order = agent.session.last_order, None
    return {
        "session_id": session_id,
        "reply": reply,
        "steps": steps,
        "cards": agent.session.take_displays(),
        "cart": agent.session.cart_view(images=True),
        "order": order,
    }


@app.get("/api/cart/{session_id}")
def get_cart(session_id: str) -> dict:
    agent = _sessions.get(session_id)
    if not agent:
        raise HTTPException(404, "Unknown session")
    return agent.session.cart_view(images=True)


@app.post("/api/cart/{session_id}/items")
def set_cart_item(session_id: str, body: CartItemIn) -> dict:
    """Add / + / - buttons on product cards change the cart directly, without asking Claude."""
    agent = _agent(session_id)
    try:
        return agent.session.set_quantity_from_ui(body.product_id, body.quantity)
    except (ToolError, KeyError, ValueError) as e:
        raise HTTPException(400, str(e).strip("'\"")) from e
