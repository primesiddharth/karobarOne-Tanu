# app/events.py
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def add_event(
    session: AsyncSession,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict,
    topic: str = "default.events",
    tenant_id: UUID | None = None,
    store_id: UUID | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
) -> UUID:
    """Inserts outbox event atomically with domain state (RULES.md §5.4)."""
    event_id = uuid4()
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()
    await session.execute(
        text(
            "INSERT INTO tenant.outbox_events "
            "(id, event_id, event_version, event_type, aggregate_type, aggregate_id, "
            " tenant_id, store_id, occurred_at, correlation_id, causation_id, producer, "
            " payload, topic, created_at, attempts, dead) "
            "VALUES (:id, :event_id, 1, :event_type, :agg_type, :agg_id, "
            " :tenant_id, :store_id, :now, :corr, :caus, 'tenant', "
            " :payload, :topic, :now, 0, false)"
        ),
        {
            "id": uuid4(),
            "event_id": event_id,
            "event_type": event_type,
            "agg_type": aggregate_type,
            "agg_id": aggregate_id,
            "tenant_id": tenant_id,
            "store_id": store_id,
            "now": now,
            "corr": corr,
            "caus": causation_id,
            "payload": json.dumps(payload) if isinstance(payload, dict) else payload,
            "topic": topic,
        }
    )
    return event_id


async def handle_internal_event(session: AsyncSession, event_id: str | None, event_type: str | None, payload: dict) -> None:
    """Dispatches received events to consumers or ignores unknown events per OQ-026."""
    if not event_type or not event_id:
        return

    # Inbox deduplication check (FND-TST-003)
    res = await session.execute(
        text("SELECT 1 FROM tenant.processed_events WHERE consumer = 'tenant' AND event_id = :eid"),
        {"eid": event_id}
    )
    if res.scalar() is not None:
        return

    # Dispatch recognized events. Unknown events are ignored and NOT recorded.
    if event_type.startswith("tenant.") or event_type.startswith("tenant."):
        await session.execute(
            text("INSERT INTO tenant.processed_events (consumer, event_id, processed_at) VALUES ('tenant', :eid, :now)"),
            {"eid": event_id, "now": datetime.now(timezone.utc)}
        )
