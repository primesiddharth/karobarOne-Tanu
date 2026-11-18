# tests/test_inbox_unknown_events.py
import pytest
import hashlib
import json
from uuid import uuid4
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from app.main import app
from app.config import settings
from app.db import async_session_factory

pytestmark = pytest.mark.asyncio


async def test_unknown_event_type_returns_200_and_not_recorded(monkeypatch, db_engine):
    """Unknown events must return 200 and NOT be recorded in processed_events."""
    valid_key = "service_key"
    key_hash = hashlib.sha256(valid_key.encode()).hexdigest()
    monkeypatch.setattr(settings, "SERVICE_KEY_HASHES", json.dumps({key_hash: "producer_svc"}))

    event_id = uuid4()
    payload = {
        "event_id": str(event_id),
        "event_type": "unrecognized.domain.event",
        "payload": {"data": 123}
    }

    transport = ASGITransport(app=app)
    headers = {"X-Service-Key": valid_key}
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.post("/internal/events", headers=headers, json=payload)
    assert res.status_code == 200

    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT count(*) FROM approval.processed_events WHERE event_id = :eid"),
            {"eid": event_id}
        )
        assert result.scalar() == 0
