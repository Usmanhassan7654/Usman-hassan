"""Web server.

    /            the customer chat
    /manager     the manager dashboard (password from MANAGER_PASSWORD in .env)

Every /manager/api/... call checks the manager's login cookie on the server, so
chat users can't reach the dashboard's functions even if they guess the address.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from .agent import Assistant, LLMError  # noqa: E402  (reads the key from .env)
from .catalog import Catalog  # noqa: E402
from .products import ALLERGENS, DIETARY, ProductError, ProductStore, image_url, to_csv_text, write_csv  # noqa: E402
from .shop import Shop  # noqa: E402

catalog = Catalog()
shop = Shop(catalog)
assistant = Assistant(catalog, shop)
store = ProductStore(catalog)

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
        with store.lock:
            order = shop.checkout(body.session_id, body.name, body.address, body.payment)
            write_csv(catalog.products, store.path)  # save the new stock levels for the manager
        return {"order": order, "cart": shop.cart(body.session_id)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ====================================================================== manager dashboard

SESSION_HOURS = 12
_secret = (os.environ.get("MANAGER_SECRET") or secrets.token_hex(32)).encode()
_failed: dict[str, deque] = defaultdict(deque)


def _token(issued: int) -> str:
    sig = hmac.new(_secret, f"manager:{issued}".encode(), hashlib.sha256).hexdigest()
    return f"{issued}.{sig}"


def manager(request: Request) -> None:
    """Allow the request only with a valid, unexpired manager login cookie."""
    token = request.cookies.get("manager_session", "")
    issued, _, _sig = token.partition(".")
    if not issued.isdigit() or not hmac.compare_digest(token, _token(int(issued))) or time.time() - int(issued) > SESSION_HOURS * 3600:
        raise HTTPException(401, "Please log in to the manager dashboard.")


class LoginIn(BaseModel):
    password: str


@app.get("/manager")
def manager_page() -> FileResponse:
    return FileResponse(ROOT / "app" / "static" / "manager.html")


@app.get("/manager/api/session")
def manager_session(request: Request) -> dict:
    try:
        manager(request)
        logged_in = True
    except HTTPException:
        logged_in = False
    return {"configured": bool(os.environ.get("MANAGER_PASSWORD")), "logged_in": logged_in}


@app.post("/manager/api/login")
def manager_login(body: LoginIn, request: Request, response: Response) -> dict:
    password = os.environ.get("MANAGER_PASSWORD", "")
    if not password:
        raise HTTPException(503, "Set MANAGER_PASSWORD in the .env file to use the dashboard.")
    ip = request.client.host if request.client else "?"
    attempts = _failed[ip]
    while attempts and time.time() - attempts[0] > 300:
        attempts.popleft()
    if len(attempts) >= 5:
        raise HTTPException(429, "Too many wrong passwords. Try again in 5 minutes.")
    if not hmac.compare_digest(body.password.encode(), password.encode()):
        attempts.append(time.time())
        raise HTTPException(401, "Wrong password.")
    attempts.clear()
    response.set_cookie("manager_session", _token(int(time.time())), max_age=SESSION_HOURS * 3600, httponly=True, samesite="strict")
    return {"ok": True}


@app.post("/manager/api/logout")
def manager_logout(response: Response) -> dict:
    response.delete_cookie("manager_session")
    return {"ok": True}


def _product_out(p: dict) -> dict:
    return {**p, "image_url": image_url(p)}


@app.get("/manager/api/overview", dependencies=[Depends(manager)])
def manager_overview() -> dict:
    return store.overview(shop.orders_path)


@app.get("/manager/api/options", dependencies=[Depends(manager)])
def manager_options() -> dict:
    return {"categories": sorted({p["category"] for p in catalog.products}), "dietary": DIETARY, "allergens": ALLERGENS}


@app.get("/manager/api/products", dependencies=[Depends(manager)])
def manager_products() -> list[dict]:
    return [_product_out(p) for p in catalog.products]


@app.post("/manager/api/products", dependencies=[Depends(manager)])
def manager_add(body: dict) -> dict:
    try:
        p, warnings = store.add(body)
    except ProductError as e:
        raise HTTPException(400, str(e)) from e
    return {"product": _product_out(p), "warnings": warnings}


@app.put("/manager/api/products/{pid}", dependencies=[Depends(manager)])
def manager_update(pid: str, body: dict) -> dict:
    try:
        p, warnings = store.update(pid, body)
    except ProductError as e:
        raise HTTPException(400, str(e)) from e
    return {"product": _product_out(p), "warnings": warnings}


@app.delete("/manager/api/products/{pid}", dependencies=[Depends(manager)])
def manager_delete(pid: str) -> dict:
    try:
        store.delete(pid)
    except ProductError as e:
        raise HTTPException(404, str(e)) from e
    return {"ok": True}


@app.post("/manager/api/products/{pid}/image", dependencies=[Depends(manager)])
async def manager_image(pid: str, file: UploadFile = File(...)) -> dict:
    data = await file.read()
    try:
        if pid not in catalog.by_id:
            raise ProductError(f"No product {pid}.")
        name = store.save_image(pid, file.filename or "upload", data)
        p, _ = store.update(pid, {"image": name})
    except ProductError as e:
        raise HTTPException(400, str(e)) from e
    return {"product": _product_out(p)}


@app.get("/manager/api/export.csv", dependencies=[Depends(manager)])
def manager_export() -> PlainTextResponse:
    return PlainTextResponse(to_csv_text(catalog.products), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="products.csv"'})


async def _csv_text(file: UploadFile) -> str:
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "The CSV is too big (max 5 MB).")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


@app.post("/manager/api/import/preview", dependencies=[Depends(manager)])
async def manager_import_preview(file: UploadFile = File(...)) -> dict:
    try:
        preview = store.import_preview(await _csv_text(file))
    except ProductError as e:
        raise HTTPException(400, str(e)) from e
    return {k: preview[k] for k in ("added", "updated", "errors", "warnings")}


@app.post("/manager/api/import/commit", dependencies=[Depends(manager)])
async def manager_import_commit(file: UploadFile = File(...)) -> dict:
    try:
        return store.import_commit(await _csv_text(file))
    except ProductError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/manager/api/orders", dependencies=[Depends(manager)])
def manager_orders() -> list[dict]:
    orders = json.loads(shop.orders_path.read_text()) if shop.orders_path.exists() else []
    return list(reversed(orders))[:200]
