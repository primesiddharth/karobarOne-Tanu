# tests/test_approval_security.py
# Security and isolation tests for Approval & Governance service (RULES.md §5 & §6).
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app.main import app
from app import commands
from app import models

pytestmark = pytest.mark.asyncio


async def test_non_staff_role_cannot_approve_reject_or_takedown():
    """Tenants, store owners, and non-staff actors cannot execute review decisions (403 ENTITLEMENT_REQUIRED)."""
    store_owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[uuid4()],
        store_ids=[uuid4()],
    )

    req_id = uuid4()
    mock_session = AsyncMock()

    # 1. Non-staff cannot approve
    with pytest.raises(ApiError) as exc_info:
        await commands.approve_content_command(
            session=mock_session,
            approval_id=req_id,
            principal=store_owner_principal,
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert exc_info.value.status_code == 403

    # 2. Non-staff cannot reject
    with pytest.raises(ApiError) as exc_info:
        await commands.reject_content_command(
            session=mock_session,
            approval_id=req_id,
            principal=store_owner_principal,
            reason_code=None,
            reason_text="Reject",
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert exc_info.value.status_code == 403

    # 3. Non-staff cannot emergency takedown
    with pytest.raises(ApiError) as exc_info:
        await commands.emergency_takedown_command(
            session=mock_session,
            approval_id=req_id,
            principal=store_owner_principal,
            reason_code="ILLEGAL",
            reason_text="Illegal",
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert exc_info.value.status_code == 403


async def test_cross_store_idor_prevented():
    """Store owner cannot inspect approval requests belonging to another store."""
    my_store_id = uuid4()
    other_store_id = uuid4()

    principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[uuid4()],
        store_ids=[my_store_id],
    )

    other_req = models.ApprovalRequest(
        id=uuid4(),
        tenant_id=uuid4(),
        store_id=other_store_id,  # Belongs to another store
        subject_type="STORE_CONTENT",
        subject_id=uuid4(),
        subject_version="v1",
        status="PENDING",
        submitted_by=uuid4(),
        submitted_at=datetime.now(timezone.utc),
        priority=0,
    )
    other_req.decisions = []

    mock_session = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = other_req
    mock_session.execute.return_value = res

    with pytest.raises(ApiError) as exc_info:
        await commands.get_approval_detail_query(
            session=mock_session,
            approval_id=other_req.id,
            principal=principal,
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert exc_info.value.status_code == 403


async def test_no_generic_status_mutation_routes():
    """Verifies absence of generic status PATCH or PUT routes across the service (RULES.md §5.5)."""
    forbidden_methods = {"PATCH", "PUT"}
    for route in app.routes:
        if hasattr(route, "methods"):
            if forbidden_methods.intersection(route.methods):
                # Ensure path is not a generic status mutator
                assert "status" not in route.path.lower(), f"Forbidden generic status mutation route found: {route.path}"
