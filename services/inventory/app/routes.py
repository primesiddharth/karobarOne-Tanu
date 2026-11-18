# app/routes.py
import hashlib
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from typing import List
from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.platform_contracts.tokens import Principal, verify_token
from libs.platform_contracts.errors import ApiError, ErrorCode
from .config import settings
from .db import get_db_session
from . import models
from . import schemas
from . import commands

router = APIRouter()
security = HTTPBearer(auto_error=False)


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal:
    """Verifies RS256 Bearer JWT and extracts caller Principal."""
    if not credentials:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Missing Bearer token", status_code=401)

    return verify_token(
        token=credentials.credentials,
        public_key=settings.JWT_PUBLIC_KEY,
        issuer=settings.ISSUER,
        audience=settings.AUDIENCE,
    )


async def get_service_or_user_principal(
    x_service_key: str | None = Header(None, alias="X-Service-Key"),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal:
    """Authenticates either internal service via X-Service-Key or user Principal via JWT."""
    if x_service_key:
        caller = settings.get_caller_service(x_service_key)
        if not caller:
            raise ApiError(ErrorCode.FORBIDDEN_CALLER, "Invalid or unauthorized service key", status_code=403)
        return Principal(
            sub=uuid4(),
            roles=[f"SERVICE_{caller.upper()}", "SERVICE"],
            tenant_ids=[],
            store_ids=[],
        )

    if credentials:
        return verify_token(
            token=credentials.credentials,
            public_key=settings.JWT_PUBLIC_KEY,
            issuer=settings.ISSUER,
            audience=settings.AUDIENCE,
        )

    raise ApiError(ErrorCode.UNAUTHENTICATED, "Missing Bearer token or Service Key", status_code=401)


async def handle_idempotency(
    session: AsyncSession,
    scope: str,
    key: str | None,
    raw_body: dict,
    execute_coroutine,
):
    """Generic idempotency executor per RULES.md §6."""
    if not key:
        return await execute_coroutine()

    request_hash = hashlib.sha256(json.dumps(raw_body, sort_keys=True).encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    query = (
        select(models.IdempotencyKey)
        .where(models.IdempotencyKey.scope == scope, models.IdempotencyKey.key == key)
        .with_for_update()
    )
    res = await session.execute(query)
    stored = res.scalars().first()

    if stored:
        if stored.request_hash != request_hash:
            raise ApiError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Idempotency key reused with different request payload",
                status_code=409,
            )
        return JSONResponse(status_code=stored.response_code, content=stored.response_body)

    result = await execute_coroutine()
    result_data = (
        result
        if isinstance(result, dict)
        else (
            result.model_dump(mode="json")
            if hasattr(result, "model_dump")
            else str(result)
        )
    )

    idem_row = models.IdempotencyKey(
        id=uuid4(),
        scope=scope,
        key=key,
        request_hash=request_hash,
        response_code=200,
        response_body=result_data,
        created_at=now,
        locked_until=now + timedelta(minutes=5),
    )
    session.add(idem_row)
    await session.commit()
    return result


@router.get("/status", include_in_schema=False)
@router.get("/inventory/status", include_in_schema=False)
async def get_service_status():
    return {"status": "operational", "service": "inventory"}


# -----------------------------------------------------------------------------
# INV-001: GET /inventory/availability (Read SKU availability)
# -----------------------------------------------------------------------------
@router.get(
    "/inventory/availability",
    response_model=schemas.InventoryAvailabilityResponse,
    operation_id="INV_001",
    summary="Read SKU availability",
)
async def get_inventory_availability(
    store_id: UUID = Query(...),
    sku_ids: List[UUID] = Query(...),
    principal: Principal = Depends(get_service_or_user_principal),
    session: AsyncSession = Depends(get_db_session),
):
    lines = await commands.get_inventory_availability_query(
        session=session,
        store_id=store_id,
        sku_ids=sku_ids,
        principal=principal,
    )
    return schemas.InventoryAvailabilityResponse(
        store_id=store_id,
        lines=lines,
    )


# -----------------------------------------------------------------------------
# INV-002: POST /inventory/reservations (Atomic stock reservation)
# -----------------------------------------------------------------------------
@router.post(
    "/inventory/reservations",
    response_model=schemas.CreateReservationResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="INV_002",
    summary="Atomic stock reservation",
)
async def create_reservation(
    body: schemas.CreateReservationRequest,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        group_id, res_list = await commands.create_reservation_command(
            session=session,
            store_id=body.store_id,
            checkout_id=body.checkout_id,
            lines=body.lines,
            principal=principal,
            ttl_seconds=body.ttl_seconds,
        )
        await session.commit()
        return schemas.CreateReservationResponse(
            reservation_group_id=group_id,
            reservations=[
                schemas.ReservationItemDto(
                    id=r.id,
                    sku_id=r.sku_id,
                    quantity=str(r.quantity),
                    expires_at=r.expires_at,
                )
                for r in res_list
            ],
        )

    return await handle_idempotency(
        session,
        f"INV-002:{body.checkout_id}",
        idempotency_key,
        body.model_dump(mode="json"),
        _action,
    )


# -----------------------------------------------------------------------------
# INV-003: POST /inventory/reservations/{id}/consume (Consume reservation)
# -----------------------------------------------------------------------------
@router.post(
    "/inventory/reservations/{id}/consume",
    response_model=schemas.ConsumeReservationResponse,
    status_code=status.HTTP_200_OK,
    operation_id="INV_003",
    summary="Consume reservation",
)
async def consume_reservation(
    id: UUID,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        reservation = await commands.consume_reservation_command(
            session=session,
            reservation_id=id,
            principal=principal,
        )
        await session.commit()
        return schemas.ConsumeReservationResponse(
            reservation_id=reservation.id,
            status=reservation.status,
            consumed_at=reservation.consumed_at,
            sku_id=reservation.sku_id,
            quantity=reservation.quantity,
        )

    return await handle_idempotency(
        session,
        f"INV-003:{id}",
        idempotency_key,
        {"reservation_id": str(id)},
        _action,
    )


# -----------------------------------------------------------------------------
# INV-004: POST /inventory/reservations/{id}/release (Release reservation)
# -----------------------------------------------------------------------------
@router.post(
    "/inventory/reservations/{id}/release",
    response_model=schemas.ReleaseReservationResponse,
    status_code=status.HTTP_200_OK,
    operation_id="INV_004",
    summary="Release reservation",
)
async def release_reservation(
    id: UUID,
    reason: str | None = None,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        reservation = await commands.release_reservation_command(
            session=session,
            reservation_id=id,
            principal=principal,
            reason=reason,
        )
        await session.commit()
        return schemas.ReleaseReservationResponse(
            reservation_id=reservation.id,
            status=reservation.status,
            released_at=reservation.released_at,
            sku_id=reservation.sku_id,
            quantity=reservation.quantity,
        )

    return await handle_idempotency(
        session,
        f"INV-004:{id}",
        idempotency_key,
        {"reservation_id": str(id), "reason": reason},
        _action,
    )


# -----------------------------------------------------------------------------
# INV-005: POST /inventory/adjustments (Manual stock adjustment)
# -----------------------------------------------------------------------------
@router.post(
    "/inventory/adjustments",
    response_model=schemas.AdjustmentResponse,
    status_code=status.HTTP_200_OK,
    operation_id="INV_005",
    summary="Manual stock adjustment",
)
async def adjust_inventory(
    body: schemas.CreateAdjustmentRequest,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        adjustment, new_on_hand, new_avail = await commands.adjust_inventory_command(
            session=session,
            store_id=body.store_id,
            sku_id=body.sku_id,
            adjustment_type=body.adjustment_type,
            quantity=body.quantity,
            principal=principal,
            reason=body.reason,
        )
        await session.commit()
        return schemas.AdjustmentResponse(
            adjustment_id=adjustment.id,
            sku_id=adjustment.sku_id,
            adjustment_type=adjustment.adjustment_type,
            quantity=adjustment.quantity,
            new_on_hand_qty=new_on_hand,
            new_available_qty=new_avail,
        )

    return await handle_idempotency(
        session,
        f"INV-005:{body.store_id}:{body.sku_id}",
        idempotency_key,
        body.model_dump(mode="json"),
        _action,
    )


# -----------------------------------------------------------------------------
# INV-006: GET /stores/{store_id}/inventory (Inventory view)
# -----------------------------------------------------------------------------
@router.get(
    "/stores/{store_id}/inventory",
    response_model=schemas.StoreInventoryResponse,
    operation_id="INV_006",
    summary="Inventory view",
)
async def get_store_inventory(
    store_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_service_or_user_principal),
    session: AsyncSession = Depends(get_db_session),
):
    items, total_count = await commands.get_store_inventory_query(
        session=session,
        store_id=store_id,
        principal=principal,
        limit=limit,
        offset=offset,
    )
    return schemas.StoreInventoryResponse(
        store_id=store_id,
        items=items,
        total_count=total_count,
    )


# -----------------------------------------------------------------------------
# Internal: POST /internal/skus (Register SKU)
# -----------------------------------------------------------------------------
@router.post(
    "/internal/skus",
    response_model=schemas.RegisterSkuResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
async def register_sku(
    body: schemas.RegisterSkuRequest,
    principal: Principal = Depends(get_service_or_user_principal),
    session: AsyncSession = Depends(get_db_session),
):
    sku, bal = await commands.register_sku_command(
        session=session,
        store_id=body.store_id,
        sku_id=body.sku_id,
        principal=principal,
        sku_code=body.sku_code,
        is_tracked=body.is_tracked,
        initial_stock=body.initial_stock,
    )
    await session.commit()
    return schemas.RegisterSkuResponse(
        sku_id=sku.id,
        store_id=sku.store_id,
        sku_code=sku.sku_code,
        is_tracked=sku.is_tracked,
        on_hand_qty=bal.on_hand_qty,
    )


# -----------------------------------------------------------------------------
# Internal: POST /internal/scheduler/expire-reservations
# -----------------------------------------------------------------------------
@router.post(
    "/internal/scheduler/expire-reservations",
    include_in_schema=False,
)
async def trigger_expire_reservations(
    principal: Principal = Depends(get_service_or_user_principal),
    session: AsyncSession = Depends(get_db_session),
):
    expired = await commands.expire_reservations_command(session)
    await session.commit()
    return {"expired_count": expired}
