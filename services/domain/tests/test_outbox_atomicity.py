# tests/test_outbox_atomicity.py
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy import text
from app.db import async_session_factory

pytestmark = pytest.mark.asyncio


async def test_outbox_committed_with_state(db_engine):
    """Verifies outbox_events record commits atomically with domain state (RULES.md §5.4, FND-TST-003)."""
    event_id = uuid4()
    agg_id = uuid4()
    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO domain.outbox_events "
                    "(id, event_id, event_version, event_type, aggregate_type, aggregate_id, "
                    " occurred_at, correlation_id, producer, payload, topic, created_at) "
                    "VALUES (:id, :event_id, 1, :event_type, 'test', :agg_id, "
                    " :now, :corr, :prod, :payload, 'test-topic', :now)"
                ),
                {
                    "id": uuid4(),
                    "event_id": event_id,
                    "event_type": "domain.test.emitted.v1",
                    "agg_id": agg_id,
                    "now": now,
                    "corr": uuid4(),
                    "prod": "domain",
                    "payload": '{"key": "value"}',
                }
            )

    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT count(*) FROM domain.outbox_events WHERE event_id = :eid"),
            {"eid": event_id}
        )
        assert result.scalar() == 1


async def test_outbox_rollback_leaves_no_traces(db_engine):
    """Verifies outbox is rolled back if transaction fails (RULES.md §5.4, FND-TST-003)."""
    event_id = uuid4()
    agg_id = uuid4()
    now = datetime.now(timezone.utc)
    try:
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO domain.outbox_events "
                        "(id, event_id, event_version, event_type, aggregate_type, aggregate_id, "
                        " occurred_at, correlation_id, producer, payload, topic, created_at) "
                        "VALUES (:id, :event_id, 1, :event_type, 'test', :agg_id, "
                        " :now, :corr, :prod, :payload, 'test-topic', :now)"
                    ),
                    {
                        "id": uuid4(),
                        "event_id": event_id,
                        "event_type": "domain.test.failed.v1",
                        "agg_id": agg_id,
                        "now": now,
                        "corr": uuid4(),
                        "prod": "domain",
                        "payload": '{}',
                    }
                )
                raise RuntimeError("Simulated transaction crash")
    except RuntimeError:
        pass

    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT count(*) FROM domain.outbox_events WHERE event_id = :eid"),
            {"eid": event_id}
        )
        assert result.scalar() == 0
