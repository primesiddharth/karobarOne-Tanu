# tests/test_approval_concurrency.py
# Concurrency tests for Approval & Governance service (ROADMAP Phase 4 exit gate).
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import commands
from app import models

pytestmark = pytest.mark.asyncio


async def test_concurrent_approve_race_only_one_reviewer_wins():
    """Concurrent approve race: two reviewers attempt to approve the same pending version.

    The first caller transitions status to APPROVED.
    The second caller finds status is no longer PENDING and is rejected with 409 INVALID_STATE_TRANSITION.
    """
    req_id = uuid4()
    version_id = "v1.0"

    reviewer_a = Principal(
        sub=uuid4(),
        roles=["PLATFORM_STAFF"],
        tenant_ids=[],
        store_ids=[],
    )
    reviewer_b = Principal(
        sub=uuid4(),
        roles=["PLATFORM_STAFF"],
        tenant_ids=[],
        store_ids=[],
    )

    # Initial state: PENDING
    req = models.ApprovalRequest(
        id=req_id,
        tenant_id=uuid4(),
        store_id=uuid4(),
        subject_type="ITEM_VERSION",
        subject_id=uuid4(),
        subject_version=version_id,
        status="PENDING",
        submitted_by=uuid4(),
        submitted_at=datetime.now(timezone.utc),
        priority=0,
    )

    # First reviewer execution (wins lock)
    mock_session_a = AsyncMock()
    mock_session_a.add = MagicMock()
    res_a = MagicMock()
    res_a.scalar_one_or_none.return_value = req
    mock_session_a.execute.return_value = res_a

    approved_req, decided_at = await commands.approve_content_command(
        session=mock_session_a,
        approval_id=req_id,
        principal=reviewer_a,
        expected_version=version_id,
        comment="Reviewer A approval",
    )
    assert approved_req.status == "APPROVED"

    # Second reviewer execution (req.status is now APPROVED)
    mock_session_b = AsyncMock()
    mock_session_b.add = MagicMock()
    res_b = MagicMock()
    res_b.scalar_one_or_none.return_value = req  # Now status is APPROVED
    mock_session_b.execute.return_value = res_b

    with pytest.raises(ApiError) as exc_info:
        await commands.approve_content_command(
            session=mock_session_b,
            approval_id=req_id,
            principal=reviewer_b,
            expected_version=version_id,
            comment="Reviewer B concurrent approval attempt",
        )
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION
    assert exc_info.value.status_code == 409
    assert "Cannot transition approval request from APPROVED to APPROVED" in exc_info.value.message


async def test_approve_stale_version_rejected():
    """Approving with an outdated expected_version fails with 409 STALE_VERSION."""
    req_id = uuid4()
    reviewer = Principal(
        sub=uuid4(),
        roles=["PLATFORM_STAFF"],
        tenant_ids=[],
        store_ids=[],
    )

    req = models.ApprovalRequest(
        id=req_id,
        tenant_id=uuid4(),
        store_id=uuid4(),
        subject_type="ITEM_VERSION",
        subject_id=uuid4(),
        subject_version="v2.0",  # Actual version is v2.0
        status="PENDING",
        submitted_by=uuid4(),
        submitted_at=datetime.now(timezone.utc),
        priority=0,
    )

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = req
    mock_session.execute.return_value = res

    with pytest.raises(ApiError) as exc_info:
        await commands.approve_content_command(
            session=mock_session,
            approval_id=req_id,
            principal=reviewer,
            expected_version="v1.0",  # Reviewer expected v1.0
        )
    assert exc_info.value.code == ErrorCode.STALE_VERSION
    assert exc_info.value.status_code == 409
