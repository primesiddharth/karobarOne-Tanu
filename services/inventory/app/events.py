# app/events.py
import json
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select
import structlog

from . import models

logger = structlog.get_logger("inventory.events")


async def add_event(
    session: AsyncSession,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: dict,
    topic: str = "inventory.lifecycle",
    tenant_id: UUID | None = None,
    store_id: UUID | None = None,
    correlation_id: UUID | None = None,
    causation_id: UUID | None = None,
) -> UUID:
    """Inserts outbox event atomically with inventory state (RULES.md §5.4)."""
    event_id = uuid4()
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()
    await session.execute(
        text(
            "INSERT INTO inventory.outbox_events "
            "(id, event_id, event_version, event_type, aggregate_type, aggregate_id, "
            " tenant_id, store_id, occurred_at, correlation_id, causation_id, producer, "
            " payload, topic, created_at, attempts, dead) "
            "VALUES (:id, :event_id, 1, :event_type, :agg_type, :agg_id, "
            " :tenant_id, :store_id, :now, :corr, :caus, 'inventory', "
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
        models.ProcessedEvent.consumer == "inventory",
        models.ProcessedEvent.event_id == UUID(event_id),
    )
    res = await session.execute(stmt)
    if res.scalars().first():
        logger.info("event_already_processed", event_id=event_id, event_type=event_type)
        return

    # Record event in processed_events table
    proc = models.ProcessedEvent(consumer="inventory", event_id=UUID(event_id))
    session.add(proc)

    now = datetime.now(timezone.utc)

    # 2. Process events
    if event_type == "catalog.item-created.v1":
        # Automatically register physical product SKU in inventory
        item_type = payload.get("item_type")
        item_id_str = payload.get("item_id")
        store_id_str = payload.get("store_id")
        tenant_id_str = payload.get("tenant_id")
        if item_type == "PHYSICAL_PRODUCT" and item_id_str and store_id_str:
            sku_id = UUID(item_id_str)
            store_id = UUID(store_id_str)
            tenant_id = UUID(tenant_id_str) if tenant_id_str else uuid4()

            sku_stmt = select(models.Sku).where(models.Sku.id == sku_id)
            sku_res = await session.execute(sku_stmt)
            if not sku_res.scalars().first():
                sku = models.Sku(
                    id=sku_id,
                    tenant_id=tenant_id,
                    store_id=store_id,
                    sku_code=payload.get("sku_code") or str(sku_id)[:8].upper(),
                    is_tracked=True,
                    created_at=now,
                    updated_at=now,
                )
                session.add(sku)

                balance = models.StockBalance(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    store_id=store_id,
                    sku_id=sku_id,
                    on_hand_qty=0,
                    reserved_qty=0,
                    version=0,
                    created_at=now,
                    updated_at=now,
                )
                session.add(balance)

    elif event_type in ("order.cancelled.v1", "refund.completed.v1"):
        # Compensating restoration movement (INV-05)
        store_id_str = payload.get("store_id")
        lines = payload.get("lines", [])
        ref_id_str = payload.get("order_id") or payload.get("refund_id")
        ref_id = UUID(ref_id_str) if ref_id_str else None
        movement_type = "CANCEL_RESTORE" if "cancelled" in event_type else "RETURN_RESTORE"

        if store_id_str and lines:
            store_id = UUID(store_id_str)
            for line in lines:
                sku_id_str = line.get("sku_id")
                qty = int(line.get("quantity", 0))
                if sku_id_str and qty > 0:
                    sku_id = UUID(sku_id_str)
                    bal_stmt = select(models.StockBalance).where(
                        models.StockBalance.store_id == store_id,
                        models.StockBalance.sku_id == sku_id,
                    ).with_for_update()
                    bal_res = await session.execute(bal_stmt)
                    bal = bal_res.scalars().first()
                    if bal:
                        bal.on_hand_qty += qty
                        bal.version += 1
                        bal.last_movement_at = now
                        bal.updated_at = now

                        movement = models.StockMovement(
                            id=uuid4(),
                            tenant_id=bal.tenant_id,
                            store_id=store_id,
                            sku_id=sku_id,
                            movement_type=movement_type,
                            quantity_delta=qty,
                            reference_type="ORDER",
                            reference_id=ref_id,
                            occurred_at=now,
                            reason=f"Compensating restoration from {event_type}",
                            created_at=now,
                        )
                        session.add(movement)

                        await add_event(
                            session=session,
                            event_type="inventory.restored.v1",
                            aggregate_type="stock_balance",
                            aggregate_id=bal.id,
                            tenant_id=bal.tenant_id,
                            store_id=store_id,
                            payload={
                                "store_id": str(store_id),
                                "sku_id": str(sku_id),
                                "restored_quantity": qty,
                                "new_on_hand_qty": bal.on_hand_qty,
                                "reason": movement_type,
                            },
                        )
