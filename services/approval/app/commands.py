# app/commands.py
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from libs.platform_contracts.errors import ApiError, ErrorCode
from libs.platform_contracts.tokens import Principal
from . import models, domain
from .events import add_event


# ------------------------------------------------------------------------------
# APR-001: Create review request
# ------------------------------------------------------------------------------

async def create_approval_request_command(
    session: AsyncSession,
    tenant_id: UUID,
    store_id: UUID,
    subject_type: str,
    subject_id: UUID,
    subject_version: str | None,
    priority: int,
    submitted_by: UUID,
) -> models.ApprovalRequest:
    domain.validate_subject_type(subject_type)

    request_id = uuid4()
    now = datetime.now(timezone.utc)

    req = models.ApprovalRequest(
        id=request_id,
        tenant_id=tenant_id,
        store_id=store_id,
        subject_type=subject_type,
        subject_id=subject_id,
        subject_version=subject_version,
        status="PENDING",
        submitted_by=submitted_by,
        submitted_at=now,
        priority=priority,
    )
    session.add(req)

    history = models.ApprovalStateHistory(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        approval_request_id=request_id,
        from_status="NONE",
        to_status="PENDING",
        actor_id=submitted_by,
        reason="Initial submission",
        occurred_at=now,
    )
    session.add(history)

    await add_event(
        session=session,
        event_type="content.submitted.v1",
        aggregate_type="approval_request",
        aggregate_id=request_id,
        tenant_id=tenant_id,
        store_id=store_id,
        topic="approval.lifecycle",
        payload={
            "approval_id": str(request_id),
            "tenant_id": str(tenant_id),
            "store_id": str(store_id),
            "content_type": subject_type,
            "content_id": str(subject_id),
            "content_version_id": subject_version,
            "submitted_by": str(submitted_by),
            "submitted_at": now.isoformat(),
        },
    )

    await session.flush()
    return req


# ------------------------------------------------------------------------------
# APR-002: Review queue query
# ------------------------------------------------------------------------------

async def get_approval_queue_query(
    session: AsyncSession,
    subject_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[models.ApprovalRequest], int]:
    stmt = select(models.ApprovalRequest).where(models.ApprovalRequest.status == "PENDING")
    if subject_type:
        stmt = stmt.where(models.ApprovalRequest.subject_type == subject_type)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_res = await session.execute(count_stmt)
    total = count_res.scalar_one()

    stmt = stmt.order_by(models.ApprovalRequest.priority.desc(), models.ApprovalRequest.submitted_at.asc())
    stmt = stmt.limit(limit).offset(offset)

    result = await session.execute(stmt)
    items = list(result.scalars().all())
    return items, total


# ------------------------------------------------------------------------------
# APR-003: Review detail query
# ------------------------------------------------------------------------------

async def get_approval_detail_query(
    session: AsyncSession,
    approval_id: UUID,
    principal: Principal,
) -> tuple[models.ApprovalRequest, list[models.Takedown]]:
    stmt = (
        select(models.ApprovalRequest)
        .options(selectinload(models.ApprovalRequest.decisions))
        .where(models.ApprovalRequest.id == approval_id)
    )
    res = await session.execute(stmt)
    req = res.scalar_one_or_none()
    if not req:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message="Approval request not found",
            status_code=404,
        )

    # Tenant/store principal isolation check
    is_staff = any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
    if not is_staff:
        if req.store_id not in principal.store_ids and req.tenant_id not in principal.tenant_ids:
            raise ApiError(
                code=ErrorCode.ENTITLEMENT_REQUIRED,
                message="Access forbidden to this approval request",
                status_code=403,
            )

    takedowns_stmt = (
        select(models.Takedown)
        .where(models.Takedown.approval_request_id == approval_id)
        .order_by(models.Takedown.executed_at.desc())
    )
    takedowns_res = await session.execute(takedowns_stmt)
    takedowns = list(takedowns_res.scalars().all())

    return req, takedowns


# ------------------------------------------------------------------------------
# APR-004: Approve immutable version
# ------------------------------------------------------------------------------

async def approve_content_command(
    session: AsyncSession,
    approval_id: UUID,
    principal: Principal,
    expected_version: str | None = None,
    comment: str | None = None,
) -> tuple[models.ApprovalRequest, datetime]:
    # Staff permission check
    is_staff = any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
    if not is_staff:
        raise ApiError(
            code=ErrorCode.ENTITLEMENT_REQUIRED,
            message="Only Platform Staff can approve content",
            status_code=403,
        )

    # Pessimistic row locking for concurrency protection (ROADMAP Phase 4 exit gate)
    stmt = (
        select(models.ApprovalRequest)
        .where(models.ApprovalRequest.id == approval_id)
        .with_for_update()
    )
    res = await session.execute(stmt)
    req = res.scalar_one_or_none()
    if not req:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message="Approval request not found",
            status_code=404,
        )

    # Optimistic version guard if supplied
    if expected_version and req.subject_version and req.subject_version != expected_version:
        raise ApiError(
            code=ErrorCode.STALE_VERSION,
            message=f"Version mismatch: expected {expected_version}, got {req.subject_version}",
            status_code=409,
        )

    domain.validate_state_transition(req.status, "APPROVED")

    now = datetime.now(timezone.utc)
    old_status = req.status
    req.status = "APPROVED"
    req.updated_at = now

    decision = models.ApprovalDecision(
        id=uuid4(),
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        approval_request_id=req.id,
        decision="APPROVE",
        decided_by=principal.id,
        decided_at=now,
        evidence_json={"comment": comment, "expected_version": expected_version} if comment or expected_version else {},
    )
    session.add(decision)

    history = models.ApprovalStateHistory(
        id=uuid4(),
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        approval_request_id=req.id,
        from_status=old_status,
        to_status="APPROVED",
        actor_id=principal.id,
        reason=comment,
        occurred_at=now,
    )
    session.add(history)

    await add_event(
        session=session,
        event_type="content.approved.v1",
        aggregate_type="approval_request",
        aggregate_id=req.id,
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        topic="approval.lifecycle",
        payload={
            "approval_id": str(req.id),
            "tenant_id": str(req.tenant_id),
            "store_id": str(req.store_id),
            "content_type": req.subject_type,
            "content_id": str(req.subject_id),
            "content_version_id": req.subject_version,
            "reviewer_id": str(principal.id),
            "decided_at": now.isoformat(),
            "comment": comment,
        },
    )

    await session.flush()
    return req, now


# ------------------------------------------------------------------------------
# APR-005: Reject content with reason (AC-080)
# ------------------------------------------------------------------------------

async def reject_content_command(
    session: AsyncSession,
    approval_id: UUID,
    principal: Principal,
    reason_code: str | None,
    reason_text: str,
) -> tuple[models.ApprovalRequest, datetime, str]:
    # Staff permission check
    is_staff = any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
    if not is_staff:
        raise ApiError(
            code=ErrorCode.ENTITLEMENT_REQUIRED,
            message="Only Platform Staff can reject content",
            status_code=403,
        )

    # Validate rejection explanation (AC-080)
    validated_reason = domain.validate_rejection_reason(reason_text)

    stmt = (
        select(models.ApprovalRequest)
        .where(models.ApprovalRequest.id == approval_id)
        .with_for_update()
    )
    res = await session.execute(stmt)
    req = res.scalar_one_or_none()
    if not req:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message="Approval request not found",
            status_code=404,
        )

    domain.validate_state_transition(req.status, "REJECTED")

    now = datetime.now(timezone.utc)
    old_status = req.status
    req.status = "REJECTED"
    req.updated_at = now

    decision = models.ApprovalDecision(
        id=uuid4(),
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        approval_request_id=req.id,
        decision="REJECT",
        reason_code=reason_code,
        reason_text=validated_reason,
        decided_by=principal.id,
        decided_at=now,
        evidence_json={},
    )
    session.add(decision)

    history = models.ApprovalStateHistory(
        id=uuid4(),
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        approval_request_id=req.id,
        from_status=old_status,
        to_status="REJECTED",
        actor_id=principal.id,
        reason=validated_reason,
        occurred_at=now,
    )
    session.add(history)

    await add_event(
        session=session,
        event_type="content.rejected.v1",
        aggregate_type="approval_request",
        aggregate_id=req.id,
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        topic="approval.lifecycle",
        payload={
            "approval_id": str(req.id),
            "tenant_id": str(req.tenant_id),
            "store_id": str(req.store_id),
            "content_type": req.subject_type,
            "content_id": str(req.subject_id),
            "content_version_id": req.subject_version,
            "reviewer_id": str(principal.id),
            "decided_at": now.isoformat(),
            "reason_code": reason_code,
            "reason_text": validated_reason,
        },
    )

    await session.flush()
    return req, now, validated_reason


# ------------------------------------------------------------------------------
# APR-006: Emergency takedown (AC-081)
# ------------------------------------------------------------------------------

async def emergency_takedown_command(
    session: AsyncSession,
    approval_id: UUID,
    principal: Principal,
    reason_code: str,
    reason_text: str,
) -> tuple[models.Takedown, datetime]:
    # Staff permission check
    is_staff = any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
    if not is_staff:
        raise ApiError(
            code=ErrorCode.ENTITLEMENT_REQUIRED,
            message="Only Platform Staff can perform emergency takedown",
            status_code=403,
        )

    validated_code, validated_reason = domain.validate_takedown_reason(reason_code, reason_text)

    stmt = (
        select(models.ApprovalRequest)
        .where(models.ApprovalRequest.id == approval_id)
        .with_for_update()
    )
    res = await session.execute(stmt)
    req = res.scalar_one_or_none()
    if not req:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message="Approval request not found",
            status_code=404,
        )

    domain.validate_state_transition(req.status, "TAKEDOWN")

    now = datetime.now(timezone.utc)
    old_status = req.status
    req.status = "TAKEDOWN"
    req.updated_at = now

    takedown = models.Takedown(
        id=uuid4(),
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        approval_request_id=req.id,
        subject_type=req.subject_type,
        subject_id=req.subject_id,
        reason_code=validated_code,
        reason_text=validated_reason,
        executed_by=principal.id,
        executed_at=now,
    )
    session.add(takedown)

    history = models.ApprovalStateHistory(
        id=uuid4(),
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        approval_request_id=req.id,
        from_status=old_status,
        to_status="TAKEDOWN",
        actor_id=principal.id,
        reason=validated_reason,
        occurred_at=now,
    )
    session.add(history)

    await add_event(
        session=session,
        event_type="content.emergency-takedown.v1",
        aggregate_type="approval_request",
        aggregate_id=req.id,
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        topic="approval.lifecycle",
        payload={
            "approval_id": str(req.id),
            "tenant_id": str(req.tenant_id),
            "store_id": str(req.store_id),
            "content_type": req.subject_type,
            "content_id": str(req.subject_id),
            "reason_code": validated_code,
            "reason_text": validated_reason,
            "executed_by": str(principal.id),
            "executed_at": now.isoformat(),
        },
    )

    await session.flush()
    return takedown, now
