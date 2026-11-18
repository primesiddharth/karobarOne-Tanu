# app/commands.py
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional, Tuple
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from libs.platform_contracts.errors import ApiError, ErrorCode
from libs.platform_contracts.tokens import Principal
from . import models, domain, schemas
from .config import settings
from .events import add_event


def check_store_authorization(principal: Principal, store_id: UUID) -> None:
    is_authorized = (
        any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER", "SERVICE") or r.startswith("SERVICE_") for r in principal.roles)
        or (store_id in principal.store_ids)
    )
    if not is_authorized:
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Store access denied", status_code=403)


# ------------------------------------------------------------------------------
# INV-001: Availability
# ------------------------------------------------------------------------------

async def get_inventory_availability_query(
    session: AsyncSession,
    store_id: UUID,
    sku_ids: List[UUID],
    principal: Principal,
) -> List[schemas.SkuAvailabilityDto]:
    check_store_authorization(principal, store_id)

    results = []
    for s_id in sku_ids:
        sku_stmt = select(models.Sku).where(
            models.Sku.store_id == store_id,
            models.Sku.id == s_id,
        )
        sku_res = await session.execute(sku_stmt)
        sku = sku_res.scalars().first()

        bal_stmt = select(models.StockBalance).where(
            models.StockBalance.store_id == store_id,
            models.StockBalance.sku_id == s_id,
        )
        bal_res = await session.execute(bal_stmt)
        bal = bal_res.scalars().first()

        is_tracked = sku.is_tracked if sku else True
        on_hand = bal.on_hand_qty if bal else 0
        reserved = bal.reserved_qty if bal else 0

        avail_qty, is_avail = domain.calculate_availability(is_tracked, on_hand, reserved, requested=1)

        results.append(
            schemas.SkuAvailabilityDto(
                sku_id=s_id,
                is_tracked=is_tracked,
                on_hand_qty=on_hand,
                reserved_qty=reserved,
                available_qty=avail_qty,
                is_available=is_avail,
            )
        )
    return results


# ------------------------------------------------------------------------------
# INV-002: Create Reservation (Group, All-or-nothing, Conditional Atomic Hold)
# ------------------------------------------------------------------------------

async def create_reservation_command(
    session: AsyncSession,
    store_id: UUID,
    checkout_id: UUID,
    lines: List[schemas.ReservationLineRequest],
    principal: Principal,
    ttl_seconds: Optional[int] = None,
) -> Tuple[UUID, List[models.StockReservation]]:
    check_store_authorization(principal, store_id)
    tenant_id = principal.tenant_ids[0] if principal.tenant_ids else uuid4()

    if not lines:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Reservation must include at least one item line", status_code=422)

    ttl = ttl_seconds or settings.DEFAULT_RESERVATION_TTL_SECONDS
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl)
    group_id = uuid4()

    # Sort lines by sku_id to prevent lock acquisition deadlocks across concurrent checkouts
    sorted_lines = sorted(lines, key=lambda l: str(l.sku_id))

    reservations: List[models.StockReservation] = []

    for line in sorted_lines:
        sku_stmt = select(models.Sku).where(
            models.Sku.store_id == store_id,
            models.Sku.id == line.sku_id,
        )
        sku_res = await session.execute(sku_stmt)
        sku = sku_res.scalars().first()

        is_tracked = sku.is_tracked if sku else True

        qty_int = line.qty_units if hasattr(line, "qty_units") else int(Decimal(str(line.quantity)))

        if is_tracked:
            # Atomic conditional hold preventing negative stock (SERVICES.md §8, SM §9 INV-01)
            # UPDATE stock_balances SET reserved = reserved + :q WHERE sku_id = :id AND on_hand - reserved >= :q
            update_query = text(
                "UPDATE inventory.stock_balances "
                "SET reserved_qty = reserved_qty + :qty, "
                "    version = version + 1, "
                "    updated_at = :now "
                "WHERE store_id = :store_id "
                "  AND sku_id = :sku_id "
                "  AND (on_hand_qty - reserved_qty) >= :qty "
                "RETURNING id, on_hand_qty, reserved_qty, tenant_id"
            )
            update_res = await session.execute(
                update_query,
                {"qty": qty_int, "store_id": store_id, "sku_id": line.sku_id, "now": now},
            )
            row = update_res.fetchone()
            if not row:
                raise ApiError(
                    ErrorCode.INSUFFICIENT_INVENTORY,
                    f"Insufficient available stock to reserve SKU {line.sku_id}",
                    status_code=409,
                )
            tenant_id = row.tenant_id

        reservation = models.StockReservation(
            id=uuid4(),
            reservation_group_id=group_id,
            tenant_id=tenant_id,
            store_id=store_id,
            checkout_id=checkout_id,
            sku_id=line.sku_id,
            quantity=qty_int,
            status="ACTIVE",
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )
        session.add(reservation)
        reservations.append(reservation)

        # Append stock movement
        movement = models.StockMovement(
            id=uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            sku_id=line.sku_id,
            movement_type="RESERVE",
            quantity_delta=qty_int,
            reference_type="CHECKOUT",
            reference_id=checkout_id,
            occurred_at=now,
            reason=f"Hold for checkout {checkout_id}",
            created_at=now,
        )
        session.add(movement)

    # Emit inventory.reserved.v1 event
    await add_event(
        session=session,
        event_type="inventory.reserved.v1",
        aggregate_type="reservation_group",
        aggregate_id=group_id,
        tenant_id=tenant_id,
        store_id=store_id,
        topic="inventory.lifecycle",
        payload={
            "reservation_group_id": str(group_id),
            "checkout_id": str(checkout_id),
            "store_id": str(store_id),
            "reservations": [
                {
                    "id": str(r.id),
                    "sku_id": str(r.sku_id),
                    "quantity": r.quantity,
                    "expires_at": r.expires_at.isoformat(),
                }
                for r in reservations
            ],
            "reserved_at": now.isoformat(),
        },
    )

    await session.flush()
    return group_id, reservations


# ------------------------------------------------------------------------------
# INV-003: Consume Reservation
# ------------------------------------------------------------------------------

async def consume_reservation_command(
    session: AsyncSession,
    reservation_id: UUID,
    principal: Principal,
) -> models.StockReservation:
    res_stmt = select(models.StockReservation).where(models.StockReservation.id == reservation_id)
    res_result = await session.execute(res_stmt)
    reservation = res_result.scalars().first()
    if not reservation:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Reservation {reservation_id} not found", status_code=404)

    check_store_authorization(principal, reservation.store_id)

    # Idempotent response if already consumed
    if reservation.status == "CONSUMED":
        return reservation

    now = datetime.now(timezone.utc)

    if reservation.status != "ACTIVE":
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Cannot consume reservation in state '{reservation.status}'",
            status_code=409,
        )

    if reservation.expires_at <= now:
        # Mark expired and reject consumption
        reservation.status = "EXPIRED"
        reservation.updated_at = now
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Reservation has expired and cannot be consumed", status_code=409)

    # Check if tracked
    sku_stmt = select(models.Sku).where(
        models.Sku.store_id == reservation.store_id,
        models.Sku.id == reservation.sku_id,
    )
    sku_res = await session.execute(sku_stmt)
    sku = sku_res.scalars().first()
    is_tracked = sku.is_tracked if sku else True

    new_on_hand = 0
    new_reserved = 0

    if is_tracked:
        # Atomically convert reserved stock into permanent reduction
        update_query = text(
            "UPDATE inventory.stock_balances "
            "SET on_hand_qty = on_hand_qty - :qty, "
            "    reserved_qty = reserved_qty - :qty, "
            "    version = version + 1, "
            "    last_movement_at = :now, "
            "    updated_at = :now "
            "WHERE store_id = :store_id "
            "  AND sku_id = :sku_id "
            "RETURNING on_hand_qty, reserved_qty"
        )
        update_res = await session.execute(
            update_query,
            {"qty": reservation.quantity, "store_id": reservation.store_id, "sku_id": reservation.sku_id, "now": now},
        )
        row = update_res.fetchone()
        if row:
            new_on_hand = row.on_hand_qty
            new_reserved = row.reserved_qty

    reservation.status = "CONSUMED"
    reservation.consumed_at = now
    reservation.updated_at = now

    movement = models.StockMovement(
        id=uuid4(),
        tenant_id=reservation.tenant_id,
        store_id=reservation.store_id,
        sku_id=reservation.sku_id,
        movement_type="SALE",
        quantity_delta=-reservation.quantity,
        reference_type="RESERVATION",
        reference_id=reservation.id,
        occurred_at=now,
        reason=f"Consumed reservation {reservation.id}",
        created_at=now,
    )
    session.add(movement)

    await add_event(
        session=session,
        event_type="inventory.consumed.v1",
        aggregate_type="reservation",
        aggregate_id=reservation.id,
        tenant_id=reservation.tenant_id,
        store_id=reservation.store_id,
        topic="inventory.lifecycle",
        payload={
            "reservation_id": str(reservation.id),
            "sku_id": str(reservation.sku_id),
            "quantity": reservation.quantity,
            "consumed_at": now.isoformat(),
        },
    )

    if is_tracked and domain.is_low_stock(new_on_hand - new_reserved, settings.LOW_STOCK_THRESHOLD):
        await add_event(
            session=session,
            event_type="inventory.low-stock.v1",
            aggregate_type="stock_balance",
            aggregate_id=reservation.sku_id,
            tenant_id=reservation.tenant_id,
            store_id=reservation.store_id,
            topic="inventory.lifecycle",
            payload={
                "store_id": str(reservation.store_id),
                "sku_id": str(reservation.sku_id),
                "available_qty": new_on_hand - new_reserved,
                "threshold": settings.LOW_STOCK_THRESHOLD,
            },
        )

    await session.flush()
    return reservation


# ------------------------------------------------------------------------------
# INV-004: Release Reservation
# ------------------------------------------------------------------------------

async def release_reservation_command(
    session: AsyncSession,
    reservation_id: UUID,
    principal: Principal,
    reason: Optional[str] = None,
) -> models.StockReservation:
    res_stmt = select(models.StockReservation).where(models.StockReservation.id == reservation_id)
    res_result = await session.execute(res_stmt)
    reservation = res_result.scalars().first()
    if not reservation:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Reservation {reservation_id} not found", status_code=404)

    check_store_authorization(principal, reservation.store_id)

    # Idempotent response if already released
    if reservation.status == "RELEASED":
        return reservation

    if reservation.status != "ACTIVE":
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Cannot release reservation in state '{reservation.status}'",
            status_code=409,
        )

    now = datetime.now(timezone.utc)

    # Check if tracked
    sku_stmt = select(models.Sku).where(
        models.Sku.store_id == reservation.store_id,
        models.Sku.id == reservation.sku_id,
    )
    sku_res = await session.execute(sku_stmt)
    sku = sku_res.scalars().first()
    is_tracked = sku.is_tracked if sku else True

    if is_tracked:
        update_query = text(
            "UPDATE inventory.stock_balances "
            "SET reserved_qty = GREATEST(0, reserved_qty - :qty), "
            "    version = version + 1, "
            "    updated_at = :now "
            "WHERE store_id = :store_id "
            "  AND sku_id = :sku_id"
        )
        await session.execute(
            update_query,
            {"qty": reservation.quantity, "store_id": reservation.store_id, "sku_id": reservation.sku_id, "now": now},
        )

    reservation.status = "RELEASED"
    reservation.released_at = now
    reservation.updated_at = now

    movement = models.StockMovement(
        id=uuid4(),
        tenant_id=reservation.tenant_id,
        store_id=reservation.store_id,
        sku_id=reservation.sku_id,
        movement_type="RELEASE",
        quantity_delta=reservation.quantity,
        reference_type="RESERVATION",
        reference_id=reservation.id,
        occurred_at=now,
        reason=reason or f"Released reservation {reservation.id}",
        created_at=now,
    )
    session.add(movement)

    await add_event(
        session=session,
        event_type="inventory.released.v1",
        aggregate_type="reservation",
        aggregate_id=reservation.id,
        tenant_id=reservation.tenant_id,
        store_id=reservation.store_id,
        topic="inventory.lifecycle",
        payload={
            "reservation_id": str(reservation.id),
            "sku_id": str(reservation.sku_id),
            "quantity": reservation.quantity,
            "released_at": now.isoformat(),
            "reason": reason,
        },
    )

    await session.flush()
    return reservation


# ------------------------------------------------------------------------------
# INV-005: Adjustments
# ------------------------------------------------------------------------------

async def adjust_inventory_command(
    session: AsyncSession,
    store_id: UUID,
    sku_id: UUID,
    adjustment_type: str,
    quantity: int,
    principal: Principal,
    reason: Optional[str] = None,
) -> Tuple[models.InventoryAdjustment, int, int]:
    check_store_authorization(principal, store_id)
    tenant_id = principal.tenant_ids[0] if principal.tenant_ids else uuid4()

    now = datetime.now(timezone.utc)

    bal_stmt = select(models.StockBalance).where(
        models.StockBalance.store_id == store_id,
        models.StockBalance.sku_id == sku_id,
    ).with_for_update()
    bal_res = await session.execute(bal_stmt)
    bal = bal_res.scalars().first()

    if not bal:
        if adjustment_type == "DECREMENT" and quantity > 0:
            raise ApiError(ErrorCode.INSUFFICIENT_INVENTORY, "Cannot decrement non-existent stock balance", status_code=409)
        bal = models.StockBalance(
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
        session.add(bal)

    new_on_hand, delta = domain.calculate_adjustment(
        on_hand=bal.on_hand_qty,
        reserved=bal.reserved_qty,
        adjustment_type=adjustment_type,
        quantity=quantity,
    )

    bal.on_hand_qty = new_on_hand
    bal.version += 1
    bal.last_movement_at = now
    bal.updated_at = now

    adjustment = models.InventoryAdjustment(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        sku_id=sku_id,
        adjustment_type=adjustment_type,
        quantity=quantity,
        reason=reason,
        actor_id=principal.sub,
        created_at=now,
    )
    session.add(adjustment)

    if delta != 0:
        movement = models.StockMovement(
            id=uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            sku_id=sku_id,
            movement_type="ADJUSTMENT",
            quantity_delta=delta,
            reference_type="ADMIN",
            reference_id=adjustment.id,
            occurred_at=now,
            reason=reason or f"Inventory {adjustment_type} adjustment",
            created_at=now,
        )
        session.add(movement)

    await add_event(
        session=session,
        event_type="inventory.adjusted.v1",
        aggregate_type="inventory_adjustment",
        aggregate_id=adjustment.id,
        tenant_id=tenant_id,
        store_id=store_id,
        topic="inventory.lifecycle",
        payload={
            "adjustment_id": str(adjustment.id),
            "store_id": str(store_id),
            "sku_id": str(sku_id),
            "adjustment_type": adjustment_type,
            "quantity": quantity,
            "delta": delta,
            "new_on_hand_qty": new_on_hand,
            "adjusted_at": now.isoformat(),
        },
    )

    available = bal.available_qty
    if domain.is_low_stock(available, settings.LOW_STOCK_THRESHOLD):
        await add_event(
            session=session,
            event_type="inventory.low-stock.v1",
            aggregate_type="stock_balance",
            aggregate_id=sku_id,
            tenant_id=tenant_id,
            store_id=store_id,
            topic="inventory.lifecycle",
            payload={
                "store_id": str(store_id),
                "sku_id": str(sku_id),
                "available_qty": available,
                "threshold": settings.LOW_STOCK_THRESHOLD,
            },
        )

    await session.flush()
    return adjustment, new_on_hand, available


# ------------------------------------------------------------------------------
# INV-006: Store Inventory View
# ------------------------------------------------------------------------------

async def get_store_inventory_query(
    session: AsyncSession,
    store_id: UUID,
    principal: Principal,
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[schemas.InventoryItemDto], int]:
    check_store_authorization(principal, store_id)

    # Fetch all SKUs for store
    sku_stmt = select(models.Sku).where(models.Sku.store_id == store_id).offset(offset).limit(limit)
    sku_res = await session.execute(sku_stmt)
    skus = sku_res.scalars().all()

    items = []
    for s in skus:
        bal_stmt = select(models.StockBalance).where(
            models.StockBalance.store_id == store_id,
            models.StockBalance.sku_id == s.id,
        )
        bal_res = await session.execute(bal_stmt)
        bal = bal_res.scalars().first()

        on_hand = bal.on_hand_qty if bal else 0
        reserved = bal.reserved_qty if bal else 0
        avail = max(0, on_hand - reserved) if s.is_tracked else 999999

        items.append(
            schemas.InventoryItemDto(
                sku_id=s.id,
                sku_code=s.sku_code,
                is_tracked=s.is_tracked,
                on_hand_qty=on_hand,
                reserved_qty=reserved,
                available_qty=avail,
                last_movement_at=bal.last_movement_at if bal else None,
            )
        )

    total_count = len(items)
    return items, total_count


# ------------------------------------------------------------------------------
# Internal: Register SKU
# ------------------------------------------------------------------------------

async def register_sku_command(
    session: AsyncSession,
    store_id: UUID,
    sku_id: UUID,
    principal: Principal,
    sku_code: Optional[str] = None,
    is_tracked: bool = True,
    initial_stock: int = 0,
) -> Tuple[models.Sku, models.StockBalance]:
    check_store_authorization(principal, store_id)
    tenant_id = principal.tenant_ids[0] if principal.tenant_ids else uuid4()
    now = datetime.now(timezone.utc)

    sku_stmt = select(models.Sku).where(models.Sku.store_id == store_id, models.Sku.id == sku_id)
    sku_res = await session.execute(sku_stmt)
    sku = sku_res.scalars().first()
    if not sku:
        sku = models.Sku(
            id=sku_id,
            tenant_id=tenant_id,
            store_id=store_id,
            sku_code=sku_code or str(sku_id)[:8].upper(),
            is_tracked=is_tracked,
            created_at=now,
            updated_at=now,
        )
        session.add(sku)

    bal_stmt = select(models.StockBalance).where(models.StockBalance.store_id == store_id, models.StockBalance.sku_id == sku_id)
    bal_res = await session.execute(bal_stmt)
    bal = bal_res.scalars().first()
    if not bal:
        bal = models.StockBalance(
            id=uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            sku_id=sku_id,
            on_hand_qty=initial_stock,
            reserved_qty=0,
            version=0,
            created_at=now,
            updated_at=now,
        )
        session.add(bal)
        if initial_stock > 0:
            movement = models.StockMovement(
                id=uuid4(),
                tenant_id=tenant_id,
                store_id=store_id,
                sku_id=sku_id,
                movement_type="OPENING",
                quantity_delta=initial_stock,
                reference_type="ADMIN",
                reference_id=sku_id,
                occurred_at=now,
                reason="Initial SKU opening stock",
                created_at=now,
            )
            session.add(movement)

    await session.flush()
    return sku, bal


# ------------------------------------------------------------------------------
# Internal / Scheduler: Expire Reservations
# ------------------------------------------------------------------------------

async def expire_reservations_command(
    session: AsyncSession,
) -> int:
    """Sweeps active reservations that reached expires_at, releasing reserved stock atomically."""
    now = datetime.now(timezone.utc)
    query = text(
        "SELECT id, store_id, sku_id, quantity, tenant_id FROM inventory.reservations "
        "WHERE status = 'ACTIVE' AND expires_at <= :now "
        "FOR UPDATE SKIP LOCKED"
    )
    res = await session.execute(query, {"now": now})
    rows = res.fetchall()

    expired_count = 0
    for r in rows:
        # Release reserved qty
        upd_bal = text(
            "UPDATE inventory.stock_balances "
            "SET reserved_qty = GREATEST(0, reserved_qty - :qty), "
            "    version = version + 1, "
            "    updated_at = :now "
            "WHERE store_id = :store_id AND sku_id = :sku_id"
        )
        await session.execute(upd_bal, {"qty": r.quantity, "store_id": r.store_id, "sku_id": r.sku_id, "now": now})

        upd_res = text(
            "UPDATE inventory.reservations "
            "SET status = 'EXPIRED', released_at = :now, updated_at = :now "
            "WHERE id = :id"
        )
        await session.execute(upd_res, {"id": r.id, "now": now})

        # Append stock movement
        movement = models.StockMovement(
            id=uuid4(),
            tenant_id=r.tenant_id,
            store_id=r.store_id,
            sku_id=r.sku_id,
            movement_type="EXPIRY",
            quantity_delta=r.quantity,
            reference_type="RESERVATION",
            reference_id=r.id,
            occurred_at=now,
            reason="Reservation expired by scheduler timeout",
            created_at=now,
        )
        session.add(movement)

        await add_event(
            session=session,
            event_type="inventory.expired.v1",
            aggregate_type="reservation",
            aggregate_id=r.id,
            tenant_id=r.tenant_id,
            store_id=r.store_id,
            topic="inventory.lifecycle",
            payload={
                "reservation_id": str(r.id),
                "sku_id": str(r.sku_id),
                "quantity": r.quantity,
                "expired_at": now.isoformat(),
            },
        )
        expired_count += 1

    await session.flush()
    return expired_count
