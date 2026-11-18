# app/routes.py
# Thin route layer: parse -> authorize -> call command -> return (RULES.md §3 & §6).
import hashlib
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
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


# -----------------------------------------------------------------------------
# APR-001: POST /approvals (Create review request)
# -----------------------------------------------------------------------------
@router.post("/approvals", response_model=schemas.ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def create_approval(
    body: schemas.CreateApprovalRequest,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        async with session.begin():
            req = await commands.create_approval_request_command(
                session=session,
                tenant_id=body.tenant_id,
                store_id=body.store_id,
                subject_type=body.subject_type,
                subject_id=body.subject_id,
                subject_version=body.subject_version,
                priority=body.priority,
                submitted_by=body.submitted_by,
            )
            return schemas.ApprovalResponse(
                approval_id=req.id,
                tenant_id=req.tenant_id,
                store_id=req.store_id,
                subject_type=req.subject_type,
                subject_id=req.subject_id,
                subject_version=req.subject_version,
                status=req.status,
                priority=req.priority,
                submitted_by=req.submitted_by,
                submitted_at=req.submitted_at,
            )

    return await handle_idempotency(session, "APR-001", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# APR-002: GET /approvals/queue (Review queue)
# -----------------------------------------------------------------------------
@router.get("/approvals/queue", response_model=schemas.ApprovalQueueResponse)
async def get_approval_queue(
    subject_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    is_staff = any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
    if not is_staff:
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Staff privilege required", status_code=403)

    items, total = await commands.get_approval_queue_query(
        session=session,
        subject_type=subject_type,
        limit=limit,
        offset=offset,
    )
    return schemas.ApprovalQueueResponse(
        items=[
            schemas.ApprovalQueueItem(
                approval_id=it.id,
                tenant_id=it.tenant_id,
                store_id=it.store_id,
                subject_type=it.subject_type,
                subject_id=it.subject_id,
                subject_version=it.subject_version,
                status=it.status,
                priority=it.priority,
                submitted_by=it.submitted_by,
                submitted_at=it.submitted_at,
            )
            for it in items
        ],
        total=total,
    )


# -----------------------------------------------------------------------------
# APR-003: GET /approvals/{id} (Review detail)
# -----------------------------------------------------------------------------
@router.get("/approvals/{id}", response_model=schemas.ApprovalDetailResponse)
async def get_approval_detail(
    id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    req, takedowns = await commands.get_approval_detail_query(
        session=session,
        approval_id=id,
        principal=principal,
    )
    return schemas.ApprovalDetailResponse(
        approval_id=req.id,
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        subject_type=req.subject_type,
        subject_id=req.subject_id,
        subject_version=req.subject_version,
        status=req.status,
        priority=req.priority,
        submitted_by=req.submitted_by,
        submitted_at=req.submitted_at,
        decisions=[
            schemas.DecisionDetail(
                id=d.id,
                decision=d.decision,
                reason_code=d.reason_code,
                reason_text=d.reason_text,
                decided_by=d.decided_by,
                decided_at=d.decided_at,
                evidence_json=d.evidence_json or {},
            )
            for d in req.decisions
        ],
        takedowns=[
            schemas.TakedownDetail(
                id=t.id,
                subject_type=t.subject_type,
                subject_id=t.subject_id,
                reason_code=t.reason_code,
                reason_text=t.reason_text,
                executed_by=t.executed_by,
                executed_at=t.executed_at,
            )
            for t in takedowns
        ],
    )


# -----------------------------------------------------------------------------
# APR-004: POST /approvals/{id}/approve (Approve immutable version)
# -----------------------------------------------------------------------------
@router.post("/approvals/{id}/approve", response_model=schemas.ApproveResponse)
async def approve_content(
    id: UUID,
    body: schemas.ApproveRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        async with session.begin():
            req, decided_at = await commands.approve_content_command(
                session=session,
                approval_id=id,
                principal=principal,
                expected_version=body.expected_version,
                comment=body.comment,
            )
            return schemas.ApproveResponse(
                approval_id=req.id,
                state="APPROVED",
                content_version_id=req.subject_version,
                decided_at=decided_at,
            )

    return await handle_idempotency(session, f"APR-004:{id}", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# APR-005: POST /approvals/{id}/reject (Reject with reason)
# -----------------------------------------------------------------------------
@router.post("/approvals/{id}/reject", response_model=schemas.RejectResponse)
async def reject_content(
    id: UUID,
    body: schemas.RejectRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        async with session.begin():
            req, decided_at, reason = await commands.reject_content_command(
                session=session,
                approval_id=id,
                principal=principal,
                reason_code=body.reason_code,
                reason_text=body.reason_text,
            )
            return schemas.RejectResponse(
                approval_id=req.id,
                state="REJECTED",
                reason_code=body.reason_code,
                reason_text=reason,
                decided_at=decided_at,
            )

    return await handle_idempotency(session, f"APR-005:{id}", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# APR-006: POST /approvals/{id}/emergency-takedown (Immediate takedown)
# -----------------------------------------------------------------------------
@router.post("/approvals/{id}/emergency-takedown", response_model=schemas.EmergencyTakedownResponse)
async def emergency_takedown(
    id: UUID,
    body: schemas.EmergencyTakedownRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        async with session.begin():
            takedown, executed_at = await commands.emergency_takedown_command(
                session=session,
                approval_id=id,
                principal=principal,
                reason_code=body.reason_code,
                reason_text=body.reason_text,
            )
            return schemas.EmergencyTakedownResponse(
                takedown_id=takedown.id,
                approval_id=id,
                state="TAKEDOWN",
                reason_code=takedown.reason_code,
                executed_at=executed_at,
            )

    return await handle_idempotency(session, f"APR-006:{id}", idempotency_key, body.model_dump(mode="json"), _action)
