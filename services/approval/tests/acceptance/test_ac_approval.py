# tests/acceptance/test_ac_approval.py
# Acceptance Criteria test suite for Approval & Governance service (SERVICES.md §3, ROADMAP.md Phase 4).
# Function names follow test_ac_NNN_* pattern checked by tools/check_ac_coverage.py.
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app.config import settings
from app import commands
from app import domain
from app import models

pytestmark = pytest.mark.asyncio


def make_mock_session(execute_results=None, get_mapping=None):
    """Helper creating mock AsyncSession that returns queued results and handles outbox inserts."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    if get_mapping:
        mock_session.get.side_effect = (
            lambda model, obj_id, **kw: get_mapping.get((model, obj_id)) or get_mapping.get(model)
        )

    results = list(execute_results or [])

    async def _execute(*args, **kwargs):
        if results:
            return results.pop(0)
        res = MagicMock()
        res.scalars.return_value.first.return_value = None
        res.scalars.return_value.all.return_value = []
        res.scalar_one_or_none.return_value = None
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session


async def test_ac_079_controlled_content_cannot_go_live_without_approval():
    """Controlled content cannot go LIVE without approval (AC-079, APR-R03, APR-01..02).

    Given a controlled content submission in PENDING state,
    it remains unapproved and not LIVE until an authorized reviewer approves it.
    """
    tenant_id = uuid4()
    store_id = uuid4()
    item_id = uuid4()
    version_id = "v1.0"
    submitter_id = uuid4()
    reviewer_id = uuid4()

    staff_principal = Principal(
        sub=reviewer_id,
        roles=["PLATFORM_STAFF"],
        tenant_ids=[],
        store_ids=[],
    )

    # 1. Create approval submission
    mock_session = make_mock_session()
    req = await commands.create_approval_request_command(
        session=mock_session,
        tenant_id=tenant_id,
        store_id=store_id,
        subject_type="ITEM_VERSION",
        subject_id=item_id,
        subject_version=version_id,
        priority=1,
        submitted_by=submitter_id,
    )
    assert req.status == "PENDING"
    assert req.subject_id == item_id
    assert req.subject_version == version_id

    # Verify outbox event 'content.submitted.v1' emitted
    assert mock_session.execute.call_count >= 1
    call_args = mock_session.execute.call_args_list[0][0][1]
    assert call_args["event_type"] == "content.submitted.v1"
    assert call_args["payload"]["content_id"] == str(item_id)

    # 2. Before approval, status remains PENDING and cannot go live without approve command
    assert req.status == "PENDING"

    # 3. Authorized reviewer approves the version
    req_res = MagicMock()
    req_res.scalar_one_or_none.return_value = req
    approve_session = make_mock_session(execute_results=[req_res])

    approved_req, decided_at = await commands.approve_content_command(
        session=approve_session,
        approval_id=req.id,
        principal=staff_principal,
        expected_version=version_id,
        comment="Approved by reviewer",
    )
    assert approved_req.status == "APPROVED"
    assert approved_req.updated_at == decided_at

    # Verify outbox event 'content.approved.v1' emitted
    approve_call_args = approve_session.execute.call_args_list[1][0][1]
    assert approve_call_args["event_type"] == "content.approved.v1"
    assert approve_call_args["payload"]["approval_id"] == str(req.id)
    assert approve_call_args["payload"]["reviewer_id"] == str(reviewer_id)


async def test_ac_080_rejected_content_records_reason():
    """Rejected content must record reason and evidence without becoming LIVE (AC-080, APR-R04, APR-03).

    Given a PENDING approval request,
    when a reviewer attempts to reject without a reason, the command is blocked;
    when rejected with valid reason, reason and decision are persisted and content.rejected.v1 emitted.
    """
    req_id = uuid4()
    reviewer_id = uuid4()
    staff_principal = Principal(
        sub=reviewer_id,
        roles=["PLATFORM_STAFF"],
        tenant_ids=[],
        store_ids=[],
    )

    pending_req = models.ApprovalRequest(
        id=req_id,
        tenant_id=uuid4(),
        store_id=uuid4(),
        subject_type="STORE_CONTENT",
        subject_id=uuid4(),
        subject_version="v2.0",
        status="PENDING",
        submitted_by=uuid4(),
        submitted_at=datetime.now(timezone.utc),
        priority=0,
    )

    # 1. Reject without reason is rejected with 422
    mock_session = make_mock_session()
    with pytest.raises(ApiError) as exc_info:
        await commands.reject_content_command(
            session=mock_session,
            approval_id=req_id,
            principal=staff_principal,
            reason_code="POLICY_VIOLATION",
            reason_text="",  # Empty reason forbidden
        )
    assert exc_info.value.status_code == 422
    assert "non-empty reason" in exc_info.value.message

    # 2. Reject with valid reason succeeds
    req_res = MagicMock()
    req_res.scalar_one_or_none.return_value = pending_req
    valid_session = make_mock_session(execute_results=[req_res])

    rejected_req, decided_at, reason = await commands.reject_content_command(
        session=valid_session,
        approval_id=req_id,
        principal=staff_principal,
        reason_code="PROHIBITED_CLAIMS",
        reason_text="Misleading health claims detected in storefront description",
    )
    assert rejected_req.status == "REJECTED"
    assert reason == "Misleading health claims detected in storefront description"

    # Verify outbox event 'content.rejected.v1' emitted
    reject_call_args = valid_session.execute.call_args_list[1][0][1]
    assert reject_call_args["event_type"] == "content.rejected.v1"
    assert reject_call_args["payload"]["reason_code"] == "PROHIBITED_CLAIMS"
    assert reject_call_args["payload"]["reason_text"] == "Misleading health claims detected in storefront description"


async def test_ac_081_platform_staff_can_emergency_unpublish_content():
    """Platform Staff can emergency-unpublish suspicious or prohibited content (AC-081, APR-06).

    Given suspicious content that is LIVE or PENDING,
    when authorized Platform Staff executes emergency takedown,
    a takedown record is created with mandatory reason, status becomes TAKEDOWN, and content.emergency-takedown.v1 is emitted.
    """
    req_id = uuid4()
    reviewer_id = uuid4()
    staff_principal = Principal(
        sub=reviewer_id,
        roles=["PLATFORM_OWNER"],
        tenant_ids=[],
        store_ids=[],
    )

    live_req = models.ApprovalRequest(
        id=req_id,
        tenant_id=uuid4(),
        store_id=uuid4(),
        subject_type="ITEM_VERSION",
        subject_id=uuid4(),
        subject_version="v3.1",
        status="APPROVED",  # Currently approved/live
        submitted_by=uuid4(),
        submitted_at=datetime.now(timezone.utc),
        priority=0,
    )

    # 1. Takedown with invalid reason code is blocked
    mock_session = make_mock_session()
    with pytest.raises(ApiError) as exc_info:
        await commands.emergency_takedown_command(
            session=mock_session,
            approval_id=req_id,
            principal=staff_principal,
            reason_code="INVALID_REASON",
            reason_text="Some explanation",
        )
    assert exc_info.value.status_code == 422
    assert "Invalid takedown reason code" in exc_info.value.message

    # 2. Takedown with empty explanation is blocked
    with pytest.raises(ApiError) as exc_info:
        await commands.emergency_takedown_command(
            session=mock_session,
            approval_id=req_id,
            principal=staff_principal,
            reason_code="COUNTERFEIT",
            reason_text="   ",
        )
    assert exc_info.value.status_code == 422

    # 3. Authorized staff executes valid takedown
    req_res = MagicMock()
    req_res.scalar_one_or_none.return_value = live_req
    valid_session = make_mock_session(execute_results=[req_res])

    takedown, executed_at = await commands.emergency_takedown_command(
        session=valid_session,
        approval_id=req_id,
        principal=staff_principal,
        reason_code="COUNTERFEIT",
        reason_text="Notified by brand owner of counterfeit goods listing",
    )
    assert live_req.status == "TAKEDOWN"
    assert takedown.reason_code == "COUNTERFEIT"
    assert takedown.executed_by == reviewer_id

    # Verify outbox event 'content.emergency-takedown.v1' emitted
    takedown_call_args = valid_session.execute.call_args_list[1][0][1]
    assert takedown_call_args["event_type"] == "content.emergency-takedown.v1"
    assert takedown_call_args["payload"]["reason_code"] == "COUNTERFEIT"
    assert takedown_call_args["payload"]["executed_by"] == str(reviewer_id)
