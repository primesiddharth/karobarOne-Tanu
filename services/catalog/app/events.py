# app/events.py
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
import structlog

from . import models

logger = structlog.get_logger("catalog.events")


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
            "INSERT INTO catalog.outbox_events "
            "(id, event_id, event_version, event_type, aggregate_type, aggregate_id, "
            " tenant_id, store_id, occurred_at, correlation_id, causation_id, producer, "
            " payload, topic, created_at, attempts, dead) "
            "VALUES (:id, :event_id, 1, :event_type, :agg_type, :agg_id, "
            " :tenant_id, :store_id, :now, :corr, :caus, 'catalog', "
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
        models.ProcessedEvent.consumer == "catalog",
        models.ProcessedEvent.event_id == UUID(event_id),
    )
    res = await session.execute(stmt)
    if res.scalars().first():
        logger.info("event_already_processed", event_id=event_id, event_type=event_type)
        return

    # Record event in processed_events table
    proc = models.ProcessedEvent(consumer="catalog", event_id=UUID(event_id))
    session.add(proc)

    now = datetime.now(timezone.utc)

    # 2. Process domain events
    if event_type == "content.approved.v1":
        # Atomic promotion to LIVE (RULES.md §5.5, AC-079)
        content_id_str = payload.get("content_id")
        approval_id_str = payload.get("approval_id")
        if content_id_str:
            item_id = UUID(content_id_str)
            item = await session.get(models.CatalogItem, item_id)
            if item:
                # Find version by approval_request_id or draft_version_id
                v_stmt = select(models.ItemVersion).where(
                    models.ItemVersion.item_id == item_id
                )
                if approval_id_str:
                    v_stmt = v_stmt.where(models.ItemVersion.approval_request_id == UUID(approval_id_str))
                else:
                    v_stmt = v_stmt.where(models.ItemVersion.approval_state == "PENDING")

                v_res = await session.execute(v_stmt)
                version = v_res.scalars().first()
                if version:
                    version.approval_state = "APPROVED_LIVE"
                    version.approved_at = now
                    item.live_version_id = version.id
                    item.updated_at = now

                    # Emit storefront snapshot invalidation
                    await add_event(
                        session=session,
                        event_type="storefront.snapshot-invalidated.v1",
                        aggregate_type="catalog_item",
                        aggregate_id=item.id,
                        tenant_id=item.tenant_id,
                        store_id=item.store_id,
                        topic="catalog.lifecycle",
                        payload={"store_id": str(item.store_id), "item_id": str(item.id)},
                    )

    elif event_type == "content.rejected.v1":
        # Keep existing LIVE version, set pending version to REJECTED (AC-080)
        content_id_str = payload.get("content_id")
        approval_id_str = payload.get("approval_id")
        if content_id_str and approval_id_str:
            v_stmt = select(models.ItemVersion).where(
                models.ItemVersion.item_id == UUID(content_id_str),
                models.ItemVersion.approval_request_id == UUID(approval_id_str),
            )
            v_res = await session.execute(v_stmt)
            version = v_res.scalars().first()
            if version:
                version.approval_state = "REJECTED"

    elif event_type == "content.emergency-takedown.v1":
        # Immediately clear live_version_id and mark TAKEDOWN (AC-081)
        content_id_str = payload.get("content_id")
        if content_id_str:
            item_id = UUID(content_id_str)
            item = await session.get(models.CatalogItem, item_id)
            if item:
                item.live_version_id = None
                item.updated_at = now

                # Update live version status if present
                v_stmt = select(models.ItemVersion).where(
                    models.ItemVersion.item_id == item_id,
                    models.ItemVersion.approval_state == "APPROVED_LIVE",
                )
                v_res = await session.execute(v_stmt)
                for ver in v_res.scalars().all():
                    ver.approval_state = "EMERGENCY_TAKEDOWN"

                await add_event(
                    session=session,
                    event_type="storefront.snapshot-invalidated.v1",
                    aggregate_type="catalog_item",
                    aggregate_id=item.id,
                    tenant_id=item.tenant_id,
                    store_id=item.store_id,
                    topic="catalog.lifecycle",
                    payload={"store_id": str(item.store_id), "item_id": str(item.id)},
                )

    elif event_type == "entitlement.changed.v1":
        # Update local entitlement projection
        store_id_str = payload.get("store_id")
        tenant_id_str = payload.get("tenant_id")
        plan_tier = payload.get("plan_tier", "FREE").upper()
        if store_id_str and tenant_id_str:
            store_id = UUID(store_id_str)
            ent = await session.get(models.EntitlementProjection, store_id)
            if not ent:
                ent = models.EntitlementProjection(
                    store_id=store_id,
                    tenant_id=UUID(tenant_id_str),
                    plan_tier=plan_tier,
                )
                session.add(ent)
            ent.plan_tier = plan_tier
            ent.max_items = payload.get("max_items", 6 if plan_tier == "FREE" else 1_000_000)
            ent.max_images_per_item = payload.get("max_images_per_item", 1 if plan_tier == "FREE" else 5)
            ent.max_videos_per_item = payload.get("max_videos_per_item", 0 if plan_tier in ("FREE", "COMMERCE") else 1)
            ent.blog_enabled = payload.get("blog_enabled", plan_tier in ("GROWTH", "SCALE_AI"))
            ent.updated_at = now
