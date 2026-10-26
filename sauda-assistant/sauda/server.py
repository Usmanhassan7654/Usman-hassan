"""HTTP API and chat UI.

    SAUDA_DEMO=1 uvicorn sauda.server:app        # seeds a demo store from data/sample_pk_grocery.csv

The store comes from the X-Store-Key header (a publishable key per store),
never from the request body or the model. Admin endpoints need SAUDA_ADMIN_KEY.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import basket as B
from . import ingest
from .db import Repo, Scope

ROOT = Path(__file__).resolve().parent
MAX_MESSAGE_CHARS = 1000
RATE_PER_MINUTE = 20

app = FastAPI(title="Sauda shopping assistant")
_repo: Repo | None = None
_agent = None
_locks: dict[tuple[str, str], threading.Lock] = defaultdict(threading.Lock)
_hits: dict[tuple[str, str], deque] = defaultdict(deque)
metrics = defaultdict(float)


def repo() -> Repo:
    global _repo
    if _repo is None:
        _repo = Repo(os.environ.get("SAUDA_DB", "sauda.db"))
        if os.environ.get("SAUDA_DEMO") == "1":
            seed_demo(_repo)
    return _repo


def agent():
    global _agent
    if _agent is None:
        from . import llm
        from .agent import Agent

        _agent = Agent(repo(), model=llm.build(effort=os.environ.get("SAUDA_EFFORT", "medium")))
    return _agent


def seed_demo(r: Repo) -> Scope:
    scope = r.add_store("demo-mart", "Demo Mart", "demo-khi", "Karachi", api_key="demo-store-key")
    if not r.catalog_stats(scope)["published_products"]:
        ingest.sync(r, scope, str(ROOT.parent / "data" / "sample_pk_grocery.csv"))
    return scope


def store_scope(x_store_key: str = Header(default="")) -> Scope:
    scope = repo().scope_for_key(x_store_key) if x_store_key else None
    if not scope:
        raise HTTPException(401, "Unknown store key.")
    return scope


def admin(x_admin_key: str = Header(default="")) -> None:
    expected = os.environ.get("SAUDA_ADMIN_KEY")
    if not expected or x_admin_key != expected:
        raise HTTPException(403, "Admin key required.")


def _rate_limit(scope: Scope, session_id: str) -> None:
    q, now = _hits[(scope.store_id, session_id)], time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_PER_MINUTE:
        raise HTTPException(429, "Too many messages. Please wait a moment.")
    q.append(now)


# ------------------------------------------------------------------ models

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    session_id: str | None = Field(default=None, max_length=64)


class OpIn(BaseModel):
    op: str
    product_id: str = ""
    quantity: int = 1
    need_id: str = ""


class BasketIn(BaseModel):
    ops: list[OpIn] = Field(min_length=1, max_length=50)
    expected_revision: int
    idempotency_key: str = Field(min_length=8, max_length=64)


class SyncIn(BaseModel):
    source: str
    resume_job: int | None = None


# ------------------------------------------------------------------ routes

@app.get("/")
def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/ready")
def ready() -> JSONResponse:
    checks = {}
    try:
        repo().conn.execute("SELECT 1")
        checks["database"] = True
    except Exception:
        checks["database"] = False
    from . import llm

    checks["model_credentials"] = llm.configured()
    stores = repo().conn.execute("SELECT id, retailer_id, currency FROM stores").fetchall() if checks["database"] else []
    checks["stores_with_catalog"] = sum(1 for s in stores if repo().catalog_stats(Scope(s["retailer_id"], s["id"], s["currency"]))["store_offers"] > 0)
    ok = checks["database"] and checks["model_credentials"] and checks["stores_with_catalog"] > 0
    return JSONResponse({"ready": ok, **checks}, status_code=200 if ok else 503)


@app.get("/metrics")
def get_metrics() -> dict:
    out = dict(metrics)
    if metrics["turns"]:
        out["avg_turn_seconds"] = round(metrics["turn_seconds"] / metrics["turns"], 2)
    return out


@app.get("/api/store")
def store_info(scope: Scope = Depends(store_scope)) -> dict:
    return {"name": repo().store_name(scope), "currency": scope.currency, "catalog": repo().catalog_stats(scope)}


def _session(body: ChatIn) -> str:
    return body.session_id or uuid.uuid4().hex


def _run_turn(scope: Scope, session_id: str, message: str, emit=None) -> dict:
    lock = _locks[(scope.store_id, session_id)]
    if not lock.acquire(timeout=150):
        raise HTTPException(409, "Still working on your previous message.")
    started = time.time()
    try:
        result = agent().handle(scope, session_id, message.strip(), emit)
    except Exception:
        metrics["turn_errors"] += 1
        raise
    finally:
        lock.release()
    metrics["turns"] += 1
    metrics["turn_seconds"] += time.time() - started
    metrics["model_calls"] += result.usage.get("model_calls", 0)
    metrics["input_tokens"] += result.usage.get("input_tokens", 0)
    metrics["output_tokens"] += result.usage.get("output_tokens", 0)
    for name in result.usage.get("models", []):
        metrics[f"turns_by_model:{name}"] += 1
    if result.grounding.get("corrected"):
        metrics["grounding_corrections"] += 1
    if result.grounding.get("issues"):
        metrics["grounding_unresolved"] += 1
    return {"session_id": session_id, "reply": result.reply, "cards": result.cards, "basket": result.basket, "steps": result.steps}


@app.post("/api/chat")
def chat(body: ChatIn, scope: Scope = Depends(store_scope)) -> dict:
    sid = _session(body)
    _rate_limit(scope, sid)
    return _run_turn(scope, sid, body.message)


@app.post("/api/chat/stream")
def chat_stream(body: ChatIn, scope: Scope = Depends(store_scope)) -> StreamingResponse:
    """Server-sent events: `status` while the assistant works, then one `result`.

    The reply is sent once it has passed the grounding check, so the customer
    never sees a figure that later gets corrected.
    """
    sid = _session(body)
    _rate_limit(scope, sid)
    events: queue.Queue = queue.Queue()

    def work():
        try:
            events.put(("result", _run_turn(scope, sid, body.message, emit=lambda e: events.put(("status", e)))))
        except HTTPException as e:
            events.put(("error", {"status": e.status_code, "message": e.detail}))
        except Exception:
            events.put(("error", {"status": 500, "message": "Something went wrong. Please try again."}))
        events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def stream():
        yield f"event: session\ndata: {json.dumps({'session_id': sid})}\n\n"
        while (item := events.get()) is not None:
            kind, data = item
            yield f"event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/session/{session_id}")
def get_session(session_id: str, scope: Scope = Depends(store_scope)) -> dict:
    """Recent conversation text, so a reload shows where the customer left off."""
    _, history, _ = repo().load_session(scope, session_id)
    return {"messages": history[-20:]}


@app.get("/api/basket/{session_id}")
def get_basket(session_id: str, scope: Scope = Depends(store_scope)) -> dict:
    return B.view(repo(), scope, session_id)


@app.post("/api/basket/{session_id}")
def change_basket(session_id: str, body: BasketIn, scope: Scope = Depends(store_scope)) -> JSONResponse:
    """Card buttons change the basket directly, without asking the model."""
    _rate_limit(scope, session_id + ":basket")
    ops = [B.Op(o.op, o.product_id, o.quantity, o.need_id) for o in body.ops]
    try:
        result = B.apply(repo(), scope, session_id, ops, body.expected_revision, body.idempotency_key)
    except B.StaleRevision as e:
        return JSONResponse({"error": "stale_revision", "basket": e.basket}, status_code=409)
    return JSONResponse(result)


@app.post("/api/admin/sync", dependencies=[Depends(admin)])
def admin_sync(body: SyncIn, scope: Scope = Depends(store_scope)) -> dict:
    try:
        return ingest.sync(repo(), scope, body.source, resume_job=body.resume_job)
    except ingest.SourceError as e:
        raise HTTPException(400, str(e)) from e


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception) -> JSONResponse:
    metrics["http_errors"] += 1
    return JSONResponse({"error": "Something went wrong. Please try again."}, status_code=500)
