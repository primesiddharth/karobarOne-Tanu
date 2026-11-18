# ==============================================================================
# File: tools/tests/test_foundation_relay.py
# Purpose: Transactional outbox relay & dispatch verification (FND-TST-003, FND-TST-004, FND-TST-006)
# ==============================================================================
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
import httpx
import pytest
from sqlalchemy import text

# Ensure iam service app can be loaded as test context
iam_dir = str(Path(__file__).resolve().parent.parent.parent / "services" / "iam")
if iam_dir not in sys.path:
    sys.path.insert(0, iam_dir)

from app.db import async_session_factory
from app.worker import claim_batch, mark_sent, mark_failed
from app.events import handle_internal_event

from libs.platform_contracts.relay import (
    dispatch_event_to_subscribers,
    get_subscribers_for_event,
)

pytestmark = pytest.mark.asyncio


# ------------------------------------------------------------------------------
# Outbox Relay Unit & Dispatch Tests
# ------------------------------------------------------------------------------

async def test_relay_subscribers_mapping():
    """Verifies that store.created.v1 maps to subscription and domain services."""
    subs = get_subscribers_for_event("store.created.v1")
    assert "subscription" in subs
    assert "domain" in subs


async def test_relay_dispatch_successful_delivery():
    """Simulates tenant relay worker dispatching store.created.v1 to subscribers."""
    event_id = uuid4()
    correlation_id = uuid4()
    store_id = uuid4()
    tenant_id = uuid4()

    event_data = {
        "event_id": event_id,
        "event_type": "store.created.v1",
        "payload": {
            "tenant_id": str(tenant_id),
            "store_id": str(store_id),
            "store_code": "TEST-STORE",
            "store_mode": "PAID_RETAIL",
        },
        "correlation_id": correlation_id,
    }

    delivered_calls = []

    async def mock_post(url, json=None, headers=None, timeout=None):
        delivered_calls.append({"url": url, "json": json, "headers": headers})
        return httpx.Response(200, json={"status": "processed"}, request=httpx.Request("POST", url))

    mock_client = AsyncMock()
    mock_client.post.side_effect = mock_post

    success = await dispatch_event_to_subscribers(
        client=mock_client,
        event_data=event_data,
        service_key="dev_secret_key_tenant",
    )

    assert success is True
    assert len(delivered_calls) == 2
    urls = [call["url"] for call in delivered_calls]
    assert any("subscription" in u or "8007" in u for u in urls)
    assert any("domain" in u or "8005" in u for u in urls)

    for call in delivered_calls:
        assert call["headers"]["X-Service-Key"] == "dev_secret_key_tenant"
        assert call["headers"]["X-Correlation-Id"] == str(correlation_id)
        assert call["json"]["event_type"] == "store.created.v1"
        assert call["json"]["event_id"] == str(event_id)
        assert call["json"]["payload"]["store_id"] == str(store_id)


async def test_relay_dispatch_handles_subscriber_failure():
    """Verifies that if a subscriber fails or returns 500, dispatch returns False so event is retried."""
    event_data = {
        "event_id": uuid4(),
        "event_type": "store.created.v1",
        "payload": {"store_id": str(uuid4())},
    }

    async def mock_post(url, json=None, headers=None, timeout=None):
        if "subscription" in url or "8007" in url:
            return httpx.Response(503, text="Service Unavailable", request=httpx.Request("POST", url))
        return httpx.Response(200, json={"status": "ok"}, request=httpx.Request("POST", url))

    mock_client = AsyncMock()
    mock_client.post.side_effect = mock_post

    success = await dispatch_event_to_subscribers(
        client=mock_client,
        event_data=event_data,
        service_key="dev_secret_key_tenant",
    )
    assert success is False


# ------------------------------------------------------------------------------
# Foundation DB & Relay Concurrency Tests (FND-TST-003, 004, 006)
# ------------------------------------------------------------------------------

async def test_fnd_tst_003_duplicate_delivery_processed_once(db_engine):
    """FND-TST-003: Duplicate event delivery processed exactly once via inbox deduplication."""
    event_id = uuid4()
    event_type = "tenant.created.v1"
    payload = {"tenant_id": str(uuid4()), "legal_name": "Test Org"}

    # First delivery
    async with async_session_factory() as session:
        async with session.begin():
            await handle_internal_event(session, str(event_id), event_type, payload)

    # Verify event was recorded in processed_events
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT count(*) FROM iam.processed_events WHERE event_id = :eid"),
            {"eid": str(event_id)}
        )
        assert result.scalar() == 1

    # Second delivery with the same event_id (duplicate delivery)
    async with async_session_factory() as session:
        async with session.begin():
            await handle_internal_event(session, str(event_id), event_type, payload)

    # Ensure processed count remains exactly 1
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT count(*) FROM iam.processed_events WHERE event_id = :eid"),
            {"eid": str(event_id)}
        )
        assert result.scalar() == 1


async def test_fnd_tst_004_two_relay_replicas_never_double_send(db_engine):
    """FND-TST-004: Two relay worker replicas running concurrently never double-claim outbox rows."""
    now = datetime.now(timezone.utc)
    event_ids = [uuid4() for _ in range(10)]

    # Seed 10 pending events into outbox
    async with async_session_factory() as session:
        async with session.begin():
            for eid in event_ids:
                await session.execute(
                    text(
                        "INSERT INTO iam.outbox_events "
                        "(id, event_id, event_version, event_type, aggregate_type, aggregate_id, "
                        " occurred_at, correlation_id, producer, payload, topic, created_at, locked_until) "
                        "VALUES (:id, :eid, 1, 'test.event', 'agg', :aid, "
                        " :now, :cid, 'iam', '{}', 'test-topic', :now, NULL)"
                    ),
                    {
                        "id": str(uuid4()),
                        "eid": str(eid),
                        "aid": str(uuid4()),
                        "cid": str(uuid4()),
                        "now": now,
                    }
                )

    # Worker 1 claims a batch of 5 items
    async with async_session_factory() as session:
        async with session.begin():
            rows_1 = await claim_batch(session, batch_size=5, lease_seconds=60)
            claimed_worker_1 = [str(r["id"]) for r in rows_1]

    # Worker 2 claims the next available batch of 5 items
    async with async_session_factory() as session:
        async with session.begin():
            rows_2 = await claim_batch(session, batch_size=5, lease_seconds=60)
            claimed_worker_2 = [str(r["id"]) for r in rows_2]

    # Guarantees:
    assert len(claimed_worker_1) == 5
    assert len(claimed_worker_2) == 5
    assert len(claimed_worker_1) + len(claimed_worker_2) == 10
    overlap = set(claimed_worker_1).intersection(set(claimed_worker_2))
    assert len(overlap) == 0


async def test_fnd_tst_006_crash_after_commit_still_delivers(db_engine):
    """FND-TST-006: Crash after DB commit recovers on next poll cycle and finishes delivery."""
    event_id = uuid4()
    row_id = uuid4()
    now = datetime.now(timezone.utc)

    # Commit event to outbox
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO iam.outbox_events "
                    "(id, event_id, event_version, event_type, aggregate_type, aggregate_id, "
                    " occurred_at, correlation_id, producer, payload, topic, created_at, locked_until) "
                    "VALUES (:id, :eid, 1, 'crash.test', 'agg', :aid, "
                    " :now, :cid, 'iam', '{}', 'test-topic', :now, NULL)"
                ),
                {
                    "id": str(row_id),
                    "eid": str(event_id),
                    "aid": str(uuid4()),
                    "cid": str(uuid4()),
                    "now": now,
                }
            )

    # Worker 1 claims the row, simulates crash
    async with async_session_factory() as session:
        async with session.begin():
            claimed = await claim_batch(session, batch_size=1, lease_seconds=1)
            assert len(claimed) == 1
            assert str(claimed[0]["id"]) == str(row_id)

    # Expire the lease to simulate time passing after crash
    expired_time = now - timedelta(seconds=10)
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text("UPDATE iam.outbox_events SET locked_until = :exp WHERE id = :id"),
                {"exp": expired_time, "id": str(row_id)}
            )

    # Worker 2 on next polling loop claims the recovered row and successfully completes delivery
    async with async_session_factory() as session:
        async with session.begin():
            recovered_rows = await claim_batch(session, batch_size=1, lease_seconds=30)
            assert len(recovered_rows) == 1
            assert str(recovered_rows[0]["id"]) == str(row_id)
            await mark_sent(session, str(row_id))

    # Verify outbox event is marked published
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT published_at FROM iam.outbox_events WHERE id = :id"),
            {"id": str(row_id)}
        )
        published_at = result.scalar()
        assert published_at is not None
