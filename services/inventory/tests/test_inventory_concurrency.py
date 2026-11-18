# tests/test_inventory_concurrency.py
import pytest
from uuid import uuid4
from datetime import datetime, timezone, timedelta
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
    mock_session.added_models = []

    def _add(item):
        mock_session.added_models.append(item)
    mock_session.add.side_effect = _add

    results = list(execute_results or [])
    mock_session.executed_calls = []

    async def _execute(statement, params=None, *args, **kwargs):
        mock_session.executed_calls.append((statement, params))
        if results:
            return results.pop(0)
        res = MagicMock()
        res.scalars.return_value.first.return_value = None
        res.scalars.return_value.all.return_value = []
        res.fetchone.return_value = None
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session


async def test_all_or_nothing_reservation_failure():
    """If any line item in a multi-item checkout lacks inventory, the entire reservation fails (INV-01, AC-015..018)."""
    store_id = uuid4()
    checkout_id = uuid4()
    sku1 = uuid4()
    sku2 = uuid4()

    principal = Principal(
        sub=uuid4(),
        roles=["SERVICE_COMMERCE", "SERVICE"],
        tenant_ids=[uuid4()],
        store_ids=[store_id],
    )

    # SKU 1 is tracked and has stock
    # SKU 2 is tracked and DOES NOT have stock
    res_sku1 = MagicMock()
    res_sku1.scalars.return_value.first.return_value = models.Sku(id=sku1, store_id=store_id, is_tracked=True)

    # First update succeeds
    res_upd1 = MagicMock()
    res_upd1.fetchone.return_value = MagicMock(id=uuid4(), on_hand_qty=5, reserved_qty=2, tenant_id=uuid4())

    res_sku2 = MagicMock()
    res_sku2.scalars.return_value.first.return_value = models.Sku(id=sku2, store_id=store_id, is_tracked=True)

    # Second update fails (0 rows returned)
    res_upd2 = MagicMock()
    res_upd2.fetchone.return_value = None

    session = make_mock_session([res_sku1, res_upd1, res_sku2, res_upd2])

    with pytest.raises(ApiError) as exc_info:
        await commands.create_reservation_command(
            session=session,
            store_id=store_id,
            checkout_id=checkout_id,
            lines=[
                schemas.ReservationLineRequest(sku_id=sku1, quantity=2),
                schemas.ReservationLineRequest(sku_id=sku2, quantity=10),
            ],
            principal=principal,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INSUFFICIENT_INVENTORY


async def test_consume_expired_reservation_rejected():
    """Attempting to consume an expired reservation fails with 409 INVALID_STATE_TRANSITION."""
    store_id = uuid4()
    res_id = uuid4()
    principal = Principal(
        sub=uuid4(),
        roles=["SERVICE_COMMERCE", "SERVICE"],
        tenant_ids=[uuid4()],
        store_ids=[store_id],
    )

    now = datetime.now(timezone.utc)
    # Reservation expired 5 minutes ago
    expired_reservation = models.StockReservation(
        id=res_id,
        reservation_group_id=uuid4(),
        tenant_id=uuid4(),
        store_id=store_id,
        checkout_id=uuid4(),
        sku_id=uuid4(),
        quantity=2,
        status="ACTIVE",
        expires_at=now - timedelta(minutes=5),
    )

    res_mock = MagicMock()
    res_mock.scalars.return_value.first.return_value = expired_reservation

    session = make_mock_session([res_mock])

    with pytest.raises(ApiError) as exc_info:
        await commands.consume_reservation_command(
            session=session,
            reservation_id=res_id,
            principal=principal,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION
    assert "expired" in exc_info.value.message
    assert expired_reservation.status == "EXPIRED"


async def test_consume_already_consumed_idempotent():
    """Calling consume on an already CONSUMED reservation returns the reservation idempotently."""
    store_id = uuid4()
    res_id = uuid4()
    principal = Principal(
        sub=uuid4(),
        roles=["SERVICE_COMMERCE", "SERVICE"],
        tenant_ids=[uuid4()],
        store_ids=[store_id],
    )

    consumed_res = models.StockReservation(
        id=res_id,
        reservation_group_id=uuid4(),
        tenant_id=uuid4(),
        store_id=store_id,
        checkout_id=uuid4(),
        sku_id=uuid4(),
        quantity=1,
        status="CONSUMED",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    res_mock = MagicMock()
    res_mock.scalars.return_value.first.return_value = consumed_res
    session = make_mock_session([res_mock])

    result = await commands.consume_reservation_command(
        session=session,
        reservation_id=res_id,
        principal=principal,
    )
    assert result.id == res_id
    assert result.status == "CONSUMED"


async def test_release_already_released_idempotent():
    """Calling release on an already RELEASED reservation returns the reservation idempotently."""
    store_id = uuid4()
    res_id = uuid4()
    principal = Principal(
        sub=uuid4(),
        roles=["SERVICE_COMMERCE", "SERVICE"],
        tenant_ids=[uuid4()],
        store_ids=[store_id],
    )

    released_res = models.StockReservation(
        id=res_id,
        reservation_group_id=uuid4(),
        tenant_id=uuid4(),
        store_id=store_id,
        checkout_id=uuid4(),
        sku_id=uuid4(),
        quantity=1,
        status="RELEASED",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    res_mock = MagicMock()
    res_mock.scalars.return_value.first.return_value = released_res
    session = make_mock_session([res_mock])

    result = await commands.release_reservation_command(
        session=session,
        reservation_id=res_id,
        principal=principal,
    )
    assert result.id == res_id
    assert result.status == "RELEASED"
