# tests/test_domain_security.py
# Security, tenant isolation, and invariant tests for DOM (RULES.md §5, SECURITY_LAYER.md).
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app.main import app
from app import commands

pytestmark = pytest.mark.asyncio


def make_mock_session(execute_results=None):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    results = list(execute_results or [])

    async def _execute(*args, **kwargs):
        if results:
            return results.pop(0)
        res = MagicMock()
        res.scalars.return_value.first.return_value = None
        res.scalars.return_value.all.return_value = []
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session


async def test_cross_store_idor_prevented():
    """Store owner of store A cannot assign subdomain or publish store B (403 ENTITLEMENT_REQUIRED)."""
    store_a = uuid4()
    store_b = uuid4()

    owner_a = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[uuid4()],
        store_ids=[store_a],
    )

    mock_session = AsyncMock()

    # Attempt subdomain assignment on store_b
    with pytest.raises(ApiError) as exc_info:
        await commands.assign_subdomain_command(
            session=mock_session,
            store_id=store_b,
            slug="store-b-label",
            principal=owner_a,
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert exc_info.value.status_code == 403

    # Attempt store publish on store_b
    with pytest.raises(ApiError) as exc_info:
        await commands.publish_store_command(
            session=mock_session,
            store_id=store_b,
            principal=owner_a,
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert exc_info.value.status_code == 403

    # Attempt domain status query on store_b
    with pytest.raises(ApiError) as exc_info:
        await commands.get_domain_status_query(
            session=mock_session,
            store_id=store_b,
            principal=owner_a,
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert exc_info.value.status_code == 403


async def test_staff_and_service_cross_store_access():
    """Platform staff and service callers can operate across stores."""
    store_id = uuid4()
    staff_principal = Principal(
        sub=uuid4(),
        roles=["PLATFORM_STAFF"],
        tenant_ids=[],
        store_ids=[],
    )
    service_principal = Principal(
        sub=uuid4(),
        roles=["SERVICE", "SERVICE_GATEWAY"],
        tenant_ids=[],
        store_ids=[],
    )

    mock_session = make_mock_session()

    # Subdomain command authorization passes without 403
    sub1 = await commands.assign_subdomain_command(
        session=mock_session,
        store_id=store_id,
        slug="staff-created",
        principal=staff_principal,
    )
    assert sub1.label == "staff-created"

    mock_session2 = make_mock_session()
    sub2 = await commands.assign_subdomain_command(
        session=mock_session2,
        store_id=store_id,
        slug="service-created",
        principal=service_principal,
    )
    assert sub2.label == "service-created"


async def test_no_generic_status_mutation_routes():
    """Verifies absence of generic status PATCH or PUT routes across DOM (RULES.md §5.5)."""
    forbidden_methods = {"PATCH", "PUT"}
    for route in app.routes:
        if hasattr(route, "methods"):
            if forbidden_methods.intersection(route.methods):
                assert "status" not in route.path.lower(), f"Forbidden generic status mutation route found: {route.path}"
