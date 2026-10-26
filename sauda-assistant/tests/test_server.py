import importlib

import pytest
from fastapi.testclient import TestClient

from conftest import FakeClient, resp, text

H = {"X-Store-Key": "demo-store-key"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SAUDA_DB", str(tmp_path / "api.db"))
    monkeypatch.setenv("SAUDA_DEMO", "1")
    from sauda import server
    importlib.reload(server)
    from sauda.agent import Agent
    server._agent = Agent(server.repo(), client=FakeClient([resp(text("Hello! What do you need?")), resp(text("Sure."))]))
    return TestClient(server.app)


def test_store_key_is_required(client):
    assert client.get("/api/store").status_code == 401
    assert client.get("/api/store", headers={"X-Store-Key": "wrong"}).status_code == 401
    info = client.get("/api/store", headers=H).json()
    assert info["catalog"]["published_products"] == 143 and info["currency"] == "PKR"


def test_basket_api_revisions_and_idempotency(client):
    ok = client.post("/api/basket/s1", headers=H, json={"ops": [{"op": "add", "product_id": "demo-mart:MLK-001", "quantity": 1}],
                                                     "expected_revision": 0, "idempotency_key": "key-00000001"})
    assert ok.status_code == 200 and ok.json()["basket"]["revision"] == 1
    again = client.post("/api/basket/s1", headers=H, json={"ops": [{"op": "add", "product_id": "demo-mart:MLK-001", "quantity": 1}],
                                                        "expected_revision": 0, "idempotency_key": "key-00000001"})
    assert again.json()["duplicate"] and again.json()["basket"]["items"][0]["quantity"] == 1
    stale = client.post("/api/basket/s1", headers=H, json={"ops": [{"op": "remove", "product_id": "demo-mart:MLK-001"}],
                                                        "expected_revision": 0, "idempotency_key": "key-00000002"})
    assert stale.status_code == 409 and stale.json()["basket"]["revision"] == 1


def test_chat_persists_conversation_and_streams(client):
    r = client.post("/api/chat", headers=H, json={"message": "salam"}).json()
    sid = r["session_id"]
    assert r["reply"] == "Hello! What do you need?"
    assert client.get(f"/api/session/{sid}", headers=H).json()["messages"][0] == {"role": "user", "content": "salam"}
    with client.stream("POST", "/api/chat/stream", headers=H, json={"message": "ok", "session_id": sid}) as s:
        body = "".join(s.iter_text())
    assert "event: session" in body and "event: result" in body and '"reply": "Sure."' in body


def test_input_limits_and_health(client):
    assert client.post("/api/chat", headers=H, json={"message": "x" * 1001}).status_code == 422
    assert client.get("/health").json() == {"ok": True}
    assert "ready" in client.get("/ready").json()
    assert client.post("/api/admin/sync", headers=H, json={"source": "x"}).status_code == 403
