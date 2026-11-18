# app/routes.py
# Thin route layer: parse -> authorize -> call command -> return (RULES.md §3 & §6).
import hashlib
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Header, status
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


async def get_optional_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal | None:
    """Optional JWT principal for endpoints supporting both public and authenticated callers."""
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


def verify_customer_access(customer: models.Customer, principal: Principal) -> None:
    """Enforces role-based and IDOR access boundaries for customer records (RULES.md §6)."""
    # 1. Platform staff
    if any(r in ("PLATFORM_OWNER", "PLATFORM_STAFF") for r in principal.roles):
        return
    # 2. Store staff assigned to store
    if any(r in ("STORE_OWNER", "STORE_STAFF") for r in principal.roles):
        if str(customer.store_id) in [str(sid) for sid in principal.store_ids]:
            return
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Store staff not assigned to this store", status_code=403)
    # 3. Customer owning the profile
    if "CUSTOMER" in principal.roles:
        if customer.iam_principal_id and customer.iam_principal_id == principal.sub:
            return
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Customer does not own this profile", status_code=403)
    # Default forbid
    raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Insufficient permissions to access this customer profile", status_code=403)


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
# CUS-001: POST /stores/{store_id}/customers/guest
# -----------------------------------------------------------------------------
@router.post(
    "/stores/{store_id}/customers/guest",
    response_model=schemas.CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="CUS_001",
    summary="Create/resolve UNCLAIMED customer",
)
async def create_guest_customer(
    store_id: UUID,
    body: schemas.GuestCustomerRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    session: AsyncSession = Depends(get_db_session),
):
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        cust = await commands.create_or_resolve_guest_customer_command(
            session=session,
            store_id=store_id,
            email=body.email,
            mobile=body.mobile,
            first_name=body.first_name,
            last_name=body.last_name,
            correlation_id=corr,
        )
        await session.commit()
        return schemas.CustomerResponse(
            id=cust.id,
            tenant_id=cust.tenant_id,
            store_id=cust.store_id,
            email=cust.email,
            mobile_e164=cust.mobile_e164,
            status=cust.status,
            iam_principal_id=cust.iam_principal_id,
            first_name=cust.first_name,
            last_name=cust.last_name,
            claimed_at=cust.claimed_at,
            created_at=cust.created_at,
            updated_at=cust.updated_at,
        )

    return await handle_idempotency(
        session=session,
        scope=f"guest_cust:{store_id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# CUS-002: POST /customers/{id}/claim/challenge
# -----------------------------------------------------------------------------
@router.post(
    "/customers/{id}/claim/challenge",
    response_model=schemas.ClaimChallengeResponse,
    status_code=status.HTTP_200_OK,
    operation_id="CUS_002",
    summary="Start Email OTP claim",
)
async def initiate_claim_challenge(
    id: UUID,
    body: schemas.ClaimChallengeRequest = schemas.ClaimChallengeRequest(),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    session: AsyncSession = Depends(get_db_session),
):
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        claim = await commands.initiate_claim_challenge_command(
            session=session,
            customer_id=id,
            channel=body.channel,
            correlation_id=corr,
        )
        await session.commit()
        return schemas.ClaimChallengeResponse(
            challenge_id=claim.id,
            customer_id=claim.customer_id,
            channel=body.channel,
            status=claim.status,
        )

    return await handle_idempotency(
        session=session,
        scope=f"claim_challenge:{id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# CUS-003: POST /customers/{id}/claim/verify
# -----------------------------------------------------------------------------
@router.post(
    "/customers/{id}/claim/verify",
    response_model=schemas.ClaimVerifyResponse,
    status_code=status.HTTP_200_OK,
    operation_id="CUS_003",
    summary="Verify OTP and claim",
)
async def verify_claim(
    id: UUID,
    body: schemas.ClaimVerifyRequest,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    session: AsyncSession = Depends(get_db_session),
):
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        cust = await commands.verify_claim_command(
            session=session,
            customer_id=id,
            challenge_id=body.challenge_id,
            otp_code=body.otp_code,
            password=body.password,
            correlation_id=corr,
        )
        await session.commit()
        return schemas.ClaimVerifyResponse(
            customer_id=cust.id,
            status=cust.status,
            iam_principal_id=cust.iam_principal_id,
            claimed_at=cust.claimed_at,
        )

    return await handle_idempotency(
        session=session,
        scope=f"claim_verify:{id}",
        key=idempotency_key,
        raw_body={"challenge_id": str(body.challenge_id), "otp_code": body.otp_code},
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# CUS-004: GET /customers/{id}
# -----------------------------------------------------------------------------
@router.get(
    "/customers/{id}",
    response_model=schemas.CustomerResponse,
    status_code=status.HTTP_200_OK,
    operation_id="CUS_004",
    summary="Read customer",
)
async def get_customer(
    id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    cust = await commands.get_customer_command(
        session=session,
        customer_id=id,
        current_principal=principal,
    )
    verify_customer_access(cust, principal)
    return schemas.CustomerResponse(
        id=cust.id,
        tenant_id=cust.tenant_id,
        store_id=cust.store_id,
        email=cust.email,
        mobile_e164=cust.mobile_e164,
        status=cust.status,
        iam_principal_id=cust.iam_principal_id,
        first_name=cust.first_name,
        last_name=cust.last_name,
        claimed_at=cust.claimed_at,
        created_at=cust.created_at,
        updated_at=cust.updated_at,
    )


# -----------------------------------------------------------------------------
# CUS-005: PATCH /customers/{id}
# -----------------------------------------------------------------------------
@router.patch(
    "/customers/{id}",
    response_model=schemas.CustomerResponse,
    status_code=status.HTTP_200_OK,
    operation_id="CUS_005",
    summary="Update profile fields",
)
async def update_customer_profile(
    id: UUID,
    body: schemas.UpdateProfileRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    session: AsyncSession = Depends(get_db_session),
):
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        cust = await commands.get_customer_command(
            session=session,
            customer_id=id,
            current_principal=principal,
        )
        verify_customer_access(cust, principal)
        updated = await commands.update_customer_profile_command(
            session=session,
            customer_id=id,
            first_name=body.first_name,
            last_name=body.last_name,
            current_principal=principal,
            correlation_id=corr,
        )
        await session.commit()
        return schemas.CustomerResponse(
            id=updated.id,
            tenant_id=updated.tenant_id,
            store_id=updated.store_id,
            email=updated.email,
            mobile_e164=updated.mobile_e164,
            status=updated.status,
            iam_principal_id=updated.iam_principal_id,
            first_name=updated.first_name,
            last_name=updated.last_name,
            claimed_at=updated.claimed_at,
            created_at=updated.created_at,
            updated_at=updated.updated_at,
        )

    return await handle_idempotency(
        session=session,
        scope=f"update_customer:{id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# CUS-006: POST /customers/{id}/addresses
# -----------------------------------------------------------------------------
@router.post(
    "/customers/{id}/addresses",
    response_model=schemas.AddressResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="CUS_006",
    summary="Create address",
)
async def create_customer_address(
    id: UUID,
    body: schemas.CreateAddressRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    session: AsyncSession = Depends(get_db_session),
):
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        cust = await commands.get_customer_command(
            session=session,
            customer_id=id,
            current_principal=principal,
        )
        verify_customer_access(cust, principal)
        addr = await commands.create_customer_address_command(
            session=session,
            customer_id=id,
            address_type=body.address_type,
            recipient_name=body.recipient_name,
            line1=body.line1,
            line2=body.line2,
            city=body.city,
            state_code=body.state_code,
            postal_code=body.postal_code,
            country_code=body.country_code,
            is_default=body.is_default,
            current_principal=principal,
            correlation_id=corr,
        )
        await session.commit()
        return schemas.AddressResponse(
            id=addr.id,
            customer_id=addr.customer_id,
            address_type=addr.address_type,
            recipient_name=addr.recipient_name,
            line1=addr.line1,
            line2=addr.line2,
            city=addr.city,
            state_code=addr.state_code,
            postal_code=addr.postal_code,
            country_code=addr.country_code,
            is_default=addr.is_default,
            created_at=addr.created_at,
        )

    return await handle_idempotency(
        session=session,
        scope=f"create_address:{id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )


# -----------------------------------------------------------------------------
# CUS-007: POST /customers/{id}/privacy-requests
# -----------------------------------------------------------------------------
@router.post(
    "/customers/{id}/privacy-requests",
    response_model=schemas.PrivacyRequestResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="CUS_007",
    summary="Open privacy request",
)
async def create_privacy_request(
    id: UUID,
    body: schemas.PrivacyRequestInput,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    session: AsyncSession = Depends(get_db_session),
):
    corr = UUID(x_correlation_id) if x_correlation_id else None

    async def _action():
        cust = await commands.get_customer_command(
            session=session,
            customer_id=id,
            current_principal=principal,
        )
        verify_customer_access(cust, principal)
        priv_req = await commands.create_privacy_request_command(
            session=session,
            customer_id=id,
            request_type=body.request_type,
            current_principal=principal,
            correlation_id=corr,
        )
        await session.commit()
        return schemas.PrivacyRequestResponse(
            id=priv_req.id,
            customer_id=priv_req.customer_id,
            request_type=priv_req.request_type,
            status=priv_req.status,
            requested_at=priv_req.requested_at,
            completed_at=priv_req.completed_at,
            retention_basis=priv_req.retention_basis,
        )

    return await handle_idempotency(
        session=session,
        scope=f"privacy_request:{id}",
        key=idempotency_key,
        raw_body=body.model_dump(mode="json"),
        execute_coroutine=_action,
    )
