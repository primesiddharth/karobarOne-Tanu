# app/events.py
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
import structlog

from . import models

logger = structlog.get_logger("domain.events")


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
            "INSERT INTO domain.outbox_events "
            "(id, event_id, event_version, event_type, aggregate_type, aggregate_id, "
            " tenant_id, store_id, occurred_at, correlation_id, causation_id, producer, "
            " payload, topic, created_at, attempts, dead) "
            "VALUES (:id, :event_id, 1, :event_type, :agg_type, :agg_id, "
            " :tenant_id, :store_id, :now, :corr, :caus, 'domain', "
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
        },
    )
    return event_id


async def handle_internal_event(
    session: AsyncSession,
    event_id: str,
    event_type: str,
    payload: dict,
) -> None:
    """Consumer inbox handler deduplicating via processed_events (RULES.md §5.4)."""
    # 1. Inbox deduplication check
    stmt = select(models.ProcessedEvent).where(
        models.ProcessedEvent.consumer == "domain",
        models.ProcessedEvent.event_id == UUID(event_id),
    )
    res = await session.execute(stmt)
    if res.scalars().first():
        logger.info("event_already_processed", event_id=event_id, event_type=event_type)
        return

    # Record event in processed_events table
    proc = models.ProcessedEvent(consumer="domain", event_id=UUID(event_id))
    session.add(proc)

    now = datetime.now(timezone.utc)

    # 2. Process domain events
    if event_type == "content.approved.v1":
        store_id_str = payload.get("store_id")
        content_version_str = payload.get("content_version_id")
        if store_id_str:
            store_id = UUID(store_id_str)
            r_stmt = select(models.PublicationRoute).where(models.PublicationRoute.store_id == store_id)
            r_res = await session.execute(r_stmt)
            route = r_res.scalars().first()
            if route and content_version_str:
                try:
                    route.target_revision_id = UUID(content_version_str)
                    route.updated_at = now
                except Exception:
                    pass

    elif event_type == "subscription.activated.v1":
        store_id_str = payload.get("store_id")
        logger.info("subscription_activated_inbox", store_id=store_id_str)

    elif event_type == "subscription.converted-to-free.v1":
        # Free conversion: deactivate custom domain, fallback to free subdomain (DOM-09, AC-059)
        store_id_str = payload.get("store_id")
        if store_id_str:
            store_id = UUID(store_id_str)

            # Deactivate custom domain route
            custom_route_stmt = select(models.PublicationRoute).where(
                models.PublicationRoute.store_id == store_id,
                models.PublicationRoute.route_type == "CUSTOM_DOMAIN",
            )
            custom_route_res = await session.execute(custom_route_stmt)
            custom_route = custom_route_res.scalars().first()
            if custom_route:
                custom_route.status = "DISABLED"
                custom_route.deactivated_at = now
                custom_route.updated_at = now

            # Restore free subdomain route
            free_route_stmt = select(models.PublicationRoute).where(
                models.PublicationRoute.store_id == store_id,
                models.PublicationRoute.route_type == "FREE_SUBDOMAIN",
            )
            free_route_res = await session.execute(free_route_stmt)
            free_route = free_route_res.scalars().first()
            if free_route:
                free_route.status = "ACTIVE"
                free_route.activated_at = now
                free_route.updated_at = now

            # Set custom domain status to STOPPED_FREE_CONVERSION
            cd_stmt = select(models.CustomDomain).where(models.CustomDomain.store_id == store_id)
            cd_res = await session.execute(cd_stmt)
            custom_domain = cd_res.scalars().first()
            if custom_domain:
                custom_domain.status = "STOPPED_FREE_CONVERSION"
                custom_domain.updated_at = now

                # Emit domain.stopped.v1
                await add_event(
                    session=session,
                    event_type="domain.stopped.v1",
                    aggregate_type="domain",
                    aggregate_id=custom_domain.id,
                    tenant_id=custom_domain.tenant_id,
                    store_id=store_id,
                    topic="domain.lifecycle",
                    payload={
                        "domain_id": str(custom_domain.id),
                        "store_id": str(store_id),
                        "domain_name": custom_domain.domain_name,
                        "reason": "SUBSCRIPTION_CONVERTED_TO_FREE",
                        "stopped_at": now.isoformat(),
                    },
                )
