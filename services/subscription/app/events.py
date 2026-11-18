# app/events.py
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
import structlog
import json

from . import models, domain

logger = structlog.get_logger("subscription.events")


async def add_event(
    session: AsyncSession,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict,
    topic: str = "subscription.lifecycle",
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
            "INSERT INTO subscription.outbox_events "
            "(id, event_id, event_version, event_type, aggregate_type, aggregate_id, "
            " tenant_id, store_id, occurred_at, correlation_id, causation_id, producer, "
            " payload, topic, created_at, attempts, dead) "
            "VALUES (:id, :event_id, 1, :event_type, :agg_type, :agg_id, "
            " :tenant_id, :store_id, :now, :corr, :caus, 'subscription', "
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
            "payload": json.dumps(payload),
            "topic": topic,
        },
    )
    logger.info(
        "outbox_event_added",
        event_id=str(event_id),
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        tenant_id=str(tenant_id) if tenant_id else None,
        store_id=str(store_id) if store_id else None,
    )
    return event_id


async def is_event_processed(session: AsyncSession, event_id: UUID, consumer: str = "subscription") -> bool:
    """Inbox deduplication check (RULES.md §5.4)."""
    res = await session.execute(
        select(models.ProcessedEvent).where(
            models.ProcessedEvent.event_id == event_id,
            models.ProcessedEvent.consumer == consumer,
        )
    )
    return res.scalars().first() is not None


async def mark_event_processed(session: AsyncSession, event_id: UUID, consumer: str = "subscription") -> None:
    """Records inbox deduplication entry."""
    session.add(models.ProcessedEvent(event_id=event_id, consumer=consumer))


async def handle_internal_event(
    session: AsyncSession,
    event_id: str | None,
    event_type: str | None,
    payload: dict,
) -> None:
    """Consumes incoming cross-service events with inbox deduplication (RULES.md §5.4)."""
    if not event_id or not event_type:
        logger.warning("received_event_missing_id_or_type", event_id=event_id, event_type=event_type)
        return

    parsed_id = UUID(event_id)
    if await is_event_processed(session, parsed_id):
        logger.info("event_already_processed", event_id=str(parsed_id))
        return

    logger.info("handling_internal_event", event_type=event_type, event_id=str(parsed_id))

    if event_type == "store.created.v1":
        # Create Free PRESENCE entitlement snapshot for new store
        store_id_str = payload.get("store_id")
        tenant_id_str = payload.get("tenant_id")
        if store_id_str and tenant_id_str:
            store_id = UUID(store_id_str)
            tenant_id = UUID(tenant_id_str)
            existing = await session.execute(
                select(models.EntitlementSnapshot).where(models.EntitlementSnapshot.store_id == store_id)
            )
            if not existing.scalars().first():
                now = datetime.now(timezone.utc)
                free_map = domain.build_entitlements_map("PRESENCE", "ACTIVE_PERIOD_1")
                snapshot = models.EntitlementSnapshot(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    store_id=store_id,
                    subscription_id=None,
                    plan_code="PRESENCE",
                    effective_from=now,
                    entitlements=free_map,
                    reason_code="STORE_CREATION_FREE",
                )
                session.add(snapshot)
                logger.info("free_entitlement_snapshot_created", store_id=str(store_id), tenant_id=str(tenant_id))

    await mark_event_processed(session, parsed_id)
