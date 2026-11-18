# tests/test_inventory_security.py
import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock
from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import commands, models, schemas

pytestmark = pytest.mark.asyncio


def make_mock_session(execute_results=None):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

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


async def test_cross_store_access_denied_idor():
    """Principal authorized for store_A cannot access inventory of store_B (IDOR prevention)."""
    store_a = uuid4()
    store_b = uuid4()
    principal_a = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[uuid4()],
        store_ids=[store_a],
    )

    session = make_mock_session()

    # 1. Availability query cross-store
    with pytest.raises(ApiError) as exc_info:
        await commands.get_inventory_availability_query(
            session=session,
            store_id=store_b,
            sku_ids=[uuid4()],
            principal=principal_a,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED

    # 2. Reservation creation cross-store
    with pytest.raises(ApiError) as exc_info:
        await commands.create_reservation_command(
            session=session,
            store_id=store_b,
            checkout_id=uuid4(),
            lines=[schemas.ReservationLineRequest(sku_id=uuid4(), quantity=1)],
            principal=principal_a,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED

    # 3. Inventory adjustment cross-store
    with pytest.raises(ApiError) as exc_info:
        await commands.adjust_inventory_command(
            session=session,
            store_id=store_b,
            sku_id=uuid4(),
            adjustment_type="INCREMENT",
            quantity=10,
            principal=principal_a,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED

    # 4. View store inventory cross-store
    with pytest.raises(ApiError) as exc_info:
        await commands.get_store_inventory_query(
            session=session,
            store_id=store_b,
            principal=principal_a,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED


async def test_service_principal_authorized_cross_store():
    """Internal service principal (e.g. SERVICE_COMMERCE) is authorized to create reservations."""
    store_id = uuid4()
    service_principal = Principal(
        sub=uuid4(),
        roles=["SERVICE_COMMERCE", "SERVICE"],
        tenant_ids=[],
        store_ids=[],
    )

    # Calling with empty lines fails with 422, confirming authorization check passed
    session = make_mock_session()
    with pytest.raises(ApiError) as exc_info:
        await commands.create_reservation_command(
            session=session,
            store_id=store_id,
            checkout_id=uuid4(),
            lines=[],
            principal=service_principal,
        )
    assert exc_info.value.status_code == 422
    assert "at least one item line" in exc_info.value.message
