# tests/test_service_auth.py
import pytest
import hashlib
import json
from uuid import UUID
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.config import settings

pytestmark = pytest.mark.asyncio


async def test_unauthenticated_request_rejected():
    """Rejects internal calls without service key with 401 UNAUTHENTICATED and valid error envelope."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/internal/events", json={"test": 1})
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "UNAUTHENTICATED"
    assert "request_id" in data["error"]
    assert "X-Request-Id" in res.headers
    UUID(res.headers["X-Request-Id"])


async def test_forbidden_caller_rejected():
    """Rejects service keys not belonging to registered caller with 403 FORBIDDEN_CALLER."""
    transport = ASGITransport(app=app)
    headers = {"X-Service-Key": "unregistered_bogus_key"}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/internal/events", headers=headers, json={"test": 1})
    assert res.status_code == 403
    data = res.json()
    assert data["error"]["code"] == "FORBIDDEN_CALLER"
    assert "request_id" in data["error"]
    assert "X-Request-Id" in res.headers


async def test_authorized_caller_accepted(monkeypatch, db_engine):
    """Accepts internal events from registered caller in SERVICE_KEY_HASHES."""
    valid_key = "super_secret_gateway_key"
    key_hash = hashlib.sha256(valid_key.encode()).hexdigest()
    monkeypatch.setattr(settings, "SERVICE_KEY_HASHES", json.dumps({key_hash: "gateway"}))

    transport = ASGITransport(app=app)
    headers = {"X-Service-Key": valid_key}
    payload = {
        "event_id": "00000000-0000-0000-0000-000000000001",
        "event_type": "unknown.unhandled.event",
        "payload": {}
    }
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/internal/events", headers=headers, json=payload)
    assert res.status_code == 200
