# app/routes.py
# Thin route layer: parse -> authorize -> call command -> return (RULES.md §3 & §6).
import hashlib
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.platform_contracts.tokens import Principal, verify_token
from libs.platform_contracts.errors import ApiError, ErrorCode
from .config import settings
from .db import get_db_session
from . import models, schemas, commands, events

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


async def get_optional_principal_or_service(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal | None:
    """Returns authenticated Principal or None if called with a valid internal service key."""
    service_key = request.headers.get("X-Service-Key")
    if service_key and (service_key == settings.MY_SERVICE_KEY or settings.get_caller_service(service_key)):
        return None  # Authorized internal caller

    if not credentials:
        return None
    try:
        return verify_token(
            token=credentials.credentials,
            public_key=settings.JWT_PUBLIC_KEY,
            issuer=settings.ISSUER,
            audience=settings.AUDIENCE,
        )
    except Exception:
        return None


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
        response_data = json.loads(stored.response_body) if stored.response_body else {}
        return JSONResponse(status_code=stored.status_code or 200, content=response_data)

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
        status="COMPLETED",
        status_code=200,
        response_body=json.dumps(result_data),
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    session.add(idem_row)
    await session.commit()
    return result


# -----------------------------------------------------------------------------
# SUB-001: GET /plans
# -----------------------------------------------------------------------------
@router.get(
    "/plans",
    response_model=schemas.PlansListResponse,
    status_code=status.HTTP_200_OK,
    operation_id="SUB_001",
    summary="List current plan offerings",
)
async def list_plans(
    session: AsyncSession = Depends(get_db_session),
):
    """Lists available commercial plan versions and their limits (SUB-001)."""
    return await commands.list_active_plans_command(session)


# -----------------------------------------------------------------------------
# SUB-002: POST /stores/{store_id}/subscriptions/activation-quote
# -----------------------------------------------------------------------------
@router.post(
    "/stores/{store_id}/subscriptions/activation-quote",
    response_model=schemas.ActivationQuoteResponse,
    status_code=status.HTTP_200_OK,
    operation_id="SUB_002",
    summary="Calculate first activation",
)
async def create_activation_quote(
    store_id: UUID,
    body: schemas.ActivationQuoteRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Calculates first paid activation quote (SUB-002, AC-042, AC-043)."""
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        quote = await commands.create_activation_quote_command(
            session=session,
            principal=principal,
            store_id=store_id,
            plan_code=body.plan_code,
            gstin_id=body.gstin_id,
            correlation_id=corr,
        )
        await session.commit()
        return quote

    return await handle_idempotency(
        session=session,
        scope=f"activation_quote:{store_id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# SUB-003: POST /stores/{store_id}/subscriptions/activate
# -----------------------------------------------------------------------------
@router.post(
    "/stores/{store_id}/subscriptions/activate",
    response_model=schemas.ActivateSubscriptionResponse,
    status_code=status.HTTP_200_OK,
    operation_id="SUB_003",
    summary="Activate paid subscription after payment",
)
async def activate_subscription(
    store_id: UUID,
    body: schemas.ActivateSubscriptionRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Activates paid subscription after payment confirmation (SUB-003, AC-041, AC-042, AC-043)."""
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        activated = await commands.activate_subscription_command(
            session=session,
            principal=principal,
            store_id=store_id,
            plan_code=body.plan_code,
            quote_id=body.quote_id,
            gstin_id=body.gstin_id,
            payment_reference=body.payment_reference,
            correlation_id=corr,
        )
        await session.commit()
        return activated

    return await handle_idempotency(
        session=session,
        scope=f"activate_subscription:{store_id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# SUB-004: GET /stores/{store_id}/entitlements
# -----------------------------------------------------------------------------
@router.get(
    "/stores/{store_id}/entitlements",
    response_model=schemas.EntitlementsResponse,
    status_code=status.HTTP_200_OK,
    operation_id="SUB_004",
    summary="Resolve current capabilities",
)
async def get_store_entitlements(
    store_id: UUID,
    principal: Principal | None = Depends(get_optional_principal_or_service),
    session: AsyncSession = Depends(get_db_session),
):
    """Resolves authoritative entitlement capabilities for a store (SUB-004)."""
    return await commands.get_store_entitlements_command(
        session=session,
        store_id=store_id,
        principal=principal,
    )


# -----------------------------------------------------------------------------
# SUB-005: GET /subscriptions/{subscription_id}
# -----------------------------------------------------------------------------
@router.get(
    "/subscriptions/{subscription_id}",
    response_model=schemas.SubscriptionDetailResponse,
    status_code=status.HTTP_200_OK,
    operation_id="SUB_005",
    summary="Read subscription lifecycle",
)
async def get_subscription(
    subscription_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Reads subscription aggregate, period status, and advance balance (SUB-005)."""
    return await commands.get_subscription_detail_command(
        session=session,
        subscription_id=subscription_id,
        principal=principal,
    )


# -----------------------------------------------------------------------------
# SUB-006: POST /subscriptions/{id}/cancel
# -----------------------------------------------------------------------------
@router.post(
    "/subscriptions/{id}/cancel",
    response_model=schemas.CancelSubscriptionResponse,
    status_code=status.HTTP_200_OK,
    operation_id="SUB_006",
    summary="Record initial cancellation notice",
)
async def cancel_subscription(
    id: UUID,
    body: schemas.CancelSubscriptionRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Records cancellation notice before Period 3 (SUB-006, AC-045..048)."""
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        res = await commands.cancel_subscription_command(
            session=session,
            subscription_id=id,
            principal=principal,
            reason=body.reason,
            expected_version=body.expected_version,
            correlation_id=corr,
        )
        await session.commit()
        return res

    return await handle_idempotency(
        session=session,
        scope=f"cancel_subscription:{id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# SUB-007: POST /subscriptions/{id}/upgrade-quote
# -----------------------------------------------------------------------------
@router.post(
    "/subscriptions/{id}/upgrade-quote",
    response_model=schemas.UpgradeQuoteResponse,
    status_code=status.HTTP_200_OK,
    operation_id="SUB_007",
    summary="Calculate upgrade",
)
async def create_upgrade_quote(
    id: UUID,
    body: schemas.UpgradeQuoteRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Calculates immutable upgrade quote (SUB-007, AC-069..075)."""
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        res = await commands.create_upgrade_quote_command(
            session=session,
            subscription_id=id,
            principal=principal,
            target_plan_code=body.target_plan_code,
            effective=body.effective,
            correlation_id=corr,
        )
        await session.commit()
        return res

    return await handle_idempotency(
        session=session,
        scope=f"upgrade_quote:{id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# SUB-008: POST /subscriptions/{id}/upgrade
# -----------------------------------------------------------------------------
@router.post(
    "/subscriptions/{id}/upgrade",
    response_model=schemas.ApplyUpgradeResponse,
    status_code=status.HTTP_200_OK,
    operation_id="SUB_008",
    summary="Apply approved/paid upgrade",
)
async def apply_upgrade(
    id: UUID,
    body: schemas.ApplyUpgradeRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Applies approved/paid upgrade (SUB-008)."""
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        res = await commands.apply_upgrade_command(
            session=session,
            subscription_id=id,
            quote_id=body.quote_id,
            principal=principal,
            correlation_id=corr,
        )
        await session.commit()
        return res

    return await handle_idempotency(
        session=session,
        scope=f"apply_upgrade:{id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# SUB-009: POST /subscriptions/{id}/downgrade
# -----------------------------------------------------------------------------
@router.post(
    "/subscriptions/{id}/downgrade",
    response_model=schemas.DowngradeResponse,
    status_code=status.HTTP_200_OK,
    operation_id="SUB_009",
    summary="Request future downgrade",
)
async def request_downgrade(
    id: UUID,
    body: schemas.DowngradeRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Requests future billing boundary downgrade (SUB-009, SM PLAN-05)."""
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        res = await commands.request_downgrade_command(
            session=session,
            subscription_id=id,
            target_plan_code=body.target_plan_code,
            principal=principal,
            reason=body.reason,
            correlation_id=corr,
        )
        await session.commit()
        return res

    return await handle_idempotency(
        session=session,
        scope=f"downgrade_request:{id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# SUB-010: POST /subscriptions/{id}/reactivate
# -----------------------------------------------------------------------------
@router.post(
    "/subscriptions/{id}/reactivate",
    response_model=schemas.ReactivateSubscriptionResponse,
    status_code=status.HTTP_200_OK,
    operation_id="SUB_010",
    summary="Reactivate after Free conversion",
)
async def reactivate_subscription(
    id: UUID,
    body: schemas.ReactivateSubscriptionRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Reactivates subscription after non-payment Free conversion (SUB-010, AC-065..068)."""
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        res = await commands.reactivate_subscription_command(
            session=session,
            subscription_id=id,
            target_plan_code=body.target_plan_code,
            principal=principal,
            gstin_id=body.gstin_id,
            correlation_id=corr,
        )
        await session.commit()
        return res

    return await handle_idempotency(
        session=session,
        scope=f"reactivate_subscription:{id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# SUB-011: POST /admin/upgrade-discounts/{request_id}/decision
# -----------------------------------------------------------------------------
@router.post(
    "/admin/upgrade-discounts/{request_id}/decision",
    response_model=schemas.DiscountDecisionResponse,
    status_code=status.HTTP_200_OK,
    operation_id="SUB_011",
    summary="Approve/reject setup-fee discount",
)
async def decide_upgrade_discount(
    request_id: UUID,
    body: schemas.DiscountDecisionRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Platform Owner decision on upgrade setup discount (SUB-011, AC-072..075)."""
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        res = await commands.decide_upgrade_discount_command(
            session=session,
            request_id=request_id,
            principal=principal,
            approved=body.approved,
            approved_amount_str=body.approved_amount,
            reason=body.reason,
            correlation_id=corr,
        )
        await session.commit()
        return res

    return await handle_idempotency(
        session=session,
        scope=f"discount_decision:{request_id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# STUB: POST /internal/dev/platform-payments (SERVICES.md §7, STUBS.md item 12)
# -----------------------------------------------------------------------------
@router.post(
    "/internal/dev/platform-payments",
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def record_platform_payment_dev_stub(
    body: schemas.DevPlatformPaymentRequest,
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    session: AsyncSession = Depends(get_db_session),
):
    """Dev-only platform payment recorder stub (SERVICES.md §7, STUBS.md item 12)."""
    if settings.ENVIRONMENT == "prod":
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND, "Dev payment endpoint disabled in production", status_code=404)

    corr = UUID(x_correlation_id) if x_correlation_id else None
    res = await commands.record_platform_payment_command(
        session=session,
        store_id=body.store_id,
        subscription_id=body.subscription_id,
        amount_paise=body.amount_paise,
        payment_reference=body.payment_reference,
        charge_id=body.charge_id,
        correlation_id=corr,
    )
    await session.commit()
    return res

