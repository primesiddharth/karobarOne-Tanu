# app/routes.py
# Thin route layer: parse -> authorize -> call command -> return (RULES.md §3 & §6).
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
from . import domain
from . import models
from . import schemas
from . import commands

router = APIRouter()
security = HTTPBearer(auto_error=False)


async def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal:
    """Verifies RS256 Bearer JWT and extracts caller Principal (RULES §8)."""
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
    """Authenticates either internal service via X-Service-Key or caller Principal via JWT."""
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
    raise ApiError(ErrorCode.UNAUTHENTICATED, "Authentication required (service key or bearer token)", status_code=401)


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
            raise ApiError(ErrorCode.IDEMPOTENCY_CONFLICT, "Idempotency key reused with different request payload", status_code=409)
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


import hashlib


# -----------------------------------------------------------------------------
# TEN-001: POST /tenants/register
# -----------------------------------------------------------------------------
@router.post("/tenants/register", response_model=schemas.RegisterTenantResponse, status_code=status.HTTP_201_CREATED)
async def register_tenant(
    body: schemas.RegisterTenantRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Registers PAN-identified tenant; evaluates age & sets Free Store entitlement."""
    async def _action():
        async with session.begin():
            return await commands.register_tenant_command(
                session=session,
                current_principal=principal,
                pan=body.pan,
                legal_name=body.legal_name,
                tenant_type=body.tenant_type,
                date_of_birth=body.date_of_birth,
                acceptance_refs=body.acceptance_refs,
            )

    return await handle_idempotency(session, "tenant:register", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# TEN-002: GET /tenants/{tenant_id}
# -----------------------------------------------------------------------------
@router.get("/tenants/{tenant_id}", response_model=schemas.TenantResponse)
async def get_tenant(
    tenant_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Reads tenant profile and minor status."""
    tenant = await commands.get_tenant_command(session, tenant_id, principal)
    return schemas.TenantResponse(
        id=tenant.id,
        pan_masked=tenant.pan_masked,
        legal_name=tenant.legal_name,
        tenant_type=tenant.tenant_type,
        minor_status=tenant.minor_status,
        status=tenant.status,
        date_of_birth=tenant.date_of_birth,
        created_at=tenant.created_at,
    )


# -----------------------------------------------------------------------------
# TEN-003: POST /tenants/{tenant_id}/guardians
# -----------------------------------------------------------------------------
@router.post("/tenants/{tenant_id}/guardians", response_model=schemas.SubmitGuardianResponse, status_code=status.HTTP_201_CREATED)
async def submit_guardian(
    tenant_id: UUID,
    body: schemas.SubmitGuardianRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Submits Guardian details for minor tenant."""
    async def _action():
        async with session.begin():
            return await commands.submit_guardian_command(
                session=session,
                tenant_id=tenant_id,
                current_principal=principal,
                full_name=body.full_name,
                relationship_code=body.relationship_code,
                email=body.email,
                mobile_e164=body.mobile_e164,
            )

    return await handle_idempotency(session, f"tenant:{tenant_id}:guardian", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# TEN-004: POST /tenants/{tenant_id}/guardians/{guardian_id}/consents
# -----------------------------------------------------------------------------
@router.post("/tenants/{tenant_id}/guardians/{guardian_id}/consents", response_model=schemas.RecordGuardianConsentResponse)
async def record_guardian_consent(
    tenant_id: UUID,
    guardian_id: UUID,
    body: schemas.RecordGuardianConsentRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Guardian accepts mandatory legal declarations, activating minor tenant."""
    client_ip = body.acceptance_ip or request.client.host if request.client else None

    async def _action():
        async with session.begin():
            return await commands.record_guardian_consent_command(
                session=session,
                tenant_id=tenant_id,
                guardian_id=guardian_id,
                current_principal=principal,
                consents=[c.model_dump(mode="json") for c in body.consents],
                acceptance_ip=client_ip,
            )

    return await handle_idempotency(session, f"guardian:{guardian_id}:consents", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# TEN-005: POST /tenants/{tenant_id}/adult-reverification
# -----------------------------------------------------------------------------
@router.post("/tenants/{tenant_id}/adult-reverification", response_model=schemas.AdultReverificationResponse)
async def adult_reverification(
    tenant_id: UUID,
    body: schemas.AdultReverificationRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Turns-18 adult reverification with fresh terms acceptance."""
    async def _action():
        async with session.begin():
            return await commands.adult_reverification_command(
                session=session,
                tenant_id=tenant_id,
                current_principal=principal,
                acceptance_refs=body.acceptance_refs,
            )

    return await handle_idempotency(session, f"tenant:{tenant_id}:adult-reverification", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# TEN-006: POST /tenants/{tenant_id}/gstins
# -----------------------------------------------------------------------------
@router.post("/tenants/{tenant_id}/gstins", response_model=schemas.GstinResponse, status_code=status.HTTP_201_CREATED)
async def register_gstin(
    tenant_id: UUID,
    body: schemas.RegisterGstinRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Registers and verifies GSTIN against tenant PAN."""
    async def _action():
        async with session.begin():
            return await commands.register_gstin_command(
                session=session,
                tenant_id=tenant_id,
                current_principal=principal,
                gstin=body.gstin,
            )

    return await handle_idempotency(session, f"tenant:{tenant_id}:gstin", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# TEN-007: GET /tenants/{tenant_id}/gstins
# -----------------------------------------------------------------------------
@router.get("/tenants/{tenant_id}/gstins", response_model=list[schemas.GstinResponse])
async def list_gstins(
    tenant_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Lists registered GSTINs for tenant."""
    rows = await commands.list_gstins_command(session, tenant_id, principal)
    return [
        schemas.GstinResponse(
            id=r.id,
            tenant_id=r.tenant_id,
            gstin_masked=r.gstin_masked,
            state_code=r.state_code,
            verification_status=r.verification_status,
        )
        for r in rows
    ]


# -----------------------------------------------------------------------------
# TEN-008: POST /stores
# -----------------------------------------------------------------------------
@router.post("/stores", response_model=schemas.StoreResponse, status_code=status.HTTP_201_CREATED)
async def create_store(
    body: schemas.CreateStoreRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Creates Free Store shell or Paid Store."""
    tenant_id = principal.tenant_ids[0] if principal.tenant_ids else body.tenant_id
    if not tenant_id:
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Principal has no associated tenant", status_code=403)

    async def _action():
        async with session.begin():
            return await commands.create_store_command(
                session=session,
                tenant_id=tenant_id,
                current_principal=principal,
                store_code=body.store_code,
                display_name=body.display_name,
                store_mode=body.store_mode,
                gstin_id=body.gstin_id,
            )

    res = await handle_idempotency(session, f"tenant:{tenant_id}:store", idempotency_key, body.model_dump(mode="json"), _action)
    if isinstance(res, JSONResponse):
        return res
    store_obj = await session.get(models.Store, res["store_id"])
    return schemas.StoreResponse(
        id=store_obj.id,
        tenant_id=store_obj.tenant_id,
        store_code=store_obj.store_code,
        display_name=store_obj.display_name,
        store_mode=store_obj.store_mode,
        lifecycle_status=store_obj.lifecycle_status,
        gstin_id=store_obj.gstin_id,
        timezone=store_obj.timezone,
        currency_code=store_obj.currency_code,
        created_at=store_obj.created_at,
    )


# -----------------------------------------------------------------------------
# TEN-009: GET /stores/{store_id}
# -----------------------------------------------------------------------------
@router.get("/stores/{store_id}", response_model=schemas.StoreResponse)
async def get_store(
    store_id: UUID,
    principal: Principal = Depends(get_service_or_user_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Reads store details and mode."""
    store = await commands.get_store_command(session, store_id, principal)
    return schemas.StoreResponse(
        id=store.id,
        tenant_id=store.tenant_id,
        store_code=store.store_code,
        display_name=store.display_name,
        store_mode=store.store_mode,
        lifecycle_status=store.lifecycle_status,
        gstin_id=store.gstin_id,
        timezone=store.timezone,
        currency_code=store.currency_code,
        created_at=store.created_at,
    )


# -----------------------------------------------------------------------------
# TEN-010: POST /stores/{store_id}/staff
# -----------------------------------------------------------------------------
@router.post("/stores/{store_id}/staff", response_model=schemas.AssignStaffResponse, status_code=status.HTTP_201_CREATED)
async def assign_store_staff(
    store_id: UUID,
    body: schemas.AssignStaffRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Assigns staff to store."""
    async def _action():
        async with session.begin():
            return await commands.assign_store_staff_command(
                session=session,
                store_id=store_id,
                current_principal=principal,
                target_principal_id=body.principal_id,
                role_code=body.role_code,
            )

    return await handle_idempotency(session, f"store:{store_id}:staff", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# TEN-011: DELETE /stores/{store_id}/staff/{assignment_id}
# -----------------------------------------------------------------------------
@router.delete("/stores/{store_id}/staff/{assignment_id}")
async def revoke_store_staff(
    store_id: UUID,
    assignment_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Revokes store staff assignment."""
    async with session.begin():
        return await commands.revoke_store_staff_command(
            session=session,
            store_id=store_id,
            assignment_id=assignment_id,
            current_principal=principal,
        )


# -----------------------------------------------------------------------------
# Internal: POST /internal/gstins/{id}/bind
# -----------------------------------------------------------------------------
@router.post("/internal/gstins/{gstin_id}/bind")
async def bind_gstin(
    gstin_id: UUID,
    body: schemas.BindGstinRequest,
    x_service_key: str | None = Header(None, alias="X-Service-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Internal service endpoint: atomically binds GSTIN to store (called by SUB)."""
    caller = settings.get_caller_service(x_service_key)
    if not caller:
        raise ApiError(ErrorCode.FORBIDDEN_CALLER, "Invalid or missing X-Service-Key", status_code=403)

    async with session.begin():
        return await commands.bind_gstin_to_store_command(
            session=session,
            gstin_id=gstin_id,
            store_id=body.store_id,
        )


# -----------------------------------------------------------------------------
# Internal Scheduler: POST /internal/scheduler/turns-18
# -----------------------------------------------------------------------------
@router.post("/internal/scheduler/turns-18")
async def trigger_turns_18_job(
    x_service_key: str | None = Header(None, alias="X-Service-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Internal scheduler endpoint: evaluates minor tenants reaching 18 years."""
    caller = settings.get_caller_service(x_service_key)
    if not caller:
        raise ApiError(ErrorCode.FORBIDDEN_CALLER, "Invalid or missing X-Service-Key", status_code=403)

    async with session.begin():
        transitioned = await commands.run_turns_18_scheduler_task(session)
        return {"status": "success", "transitioned_tenants": [str(t) for t in transitioned]}
