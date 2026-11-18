# tests/acceptance/test_fnd_tst_014_inventory.py
# Acceptance & Concurrency test suite for Inventory Service (SERVICES.md §8, BTDD §9.8, §18.2, FND-TST-014).
import json
import pytest
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import commands, domain, models, schemas
from app.events import handle_internal_event

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
        res.fetchall.return_value = []
        res.fetchone.return_value = None
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session


def get_outbox_events(mock_session):
    """Extracts all outbox events recorded via session.execute."""
    events = []
    for stmt, params in mock_session.executed_calls:
        if params and "event_type" in params:
            p = dict(params)
            if isinstance(p.get("payload"), str):
                p["payload"] = json.loads(p["payload"])
            events.append(p)
    return events


# ==============================================================================
# FND-TST-014: Final-Unit Race Condition & Non-Negative Inventory
# ==============================================================================

async def test_fnd_tst_014_final_unit_race():
    """Two concurrent checkouts attempt to reserve the final tracked SKU: exactly one succeeds (BTDD §18.2)."""
    store_id = uuid4()
    sku_id = uuid4()
    tenant_id = uuid4()

    principal = Principal(
        sub=uuid4(),
        roles=["SERVICE_COMMERCE", "SERVICE"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    # Simulation: 1 unit on hand, 0 reserved
    sku_tracked = models.Sku(id=sku_id, store_id=store_id, is_tracked=True)

    # First checkout reservation attempt: conditional update succeeds
    res_sku1 = MagicMock()
    res_sku1.scalars.return_value.first.return_value = sku_tracked
    res_upd1 = MagicMock()
    res_upd1.fetchone.return_value = MagicMock(id=uuid4(), on_hand_qty=1, reserved_qty=1, tenant_id=tenant_id)

    session1 = make_mock_session([res_sku1, res_upd1])
    group_id1, res1 = await commands.create_reservation_command(
        session=session1,
        store_id=store_id,
        checkout_id=uuid4(),
        lines=[schemas.ReservationLineRequest(sku_id=sku_id, quantity=1)],
        principal=principal,
    )
    assert len(res1) == 1
    assert res1[0].quantity == 1
    assert res1[0].status == "ACTIVE"

    # Second checkout reservation attempt for same SKU: conditional update returns 0 rows
    res_sku2 = MagicMock()
    res_sku2.scalars.return_value.first.return_value = sku_tracked
    res_upd2 = MagicMock()
    res_upd2.fetchone.return_value = None  # 0 rows updated

    session2 = make_mock_session([res_sku2, res_upd2])
    with pytest.raises(ApiError) as exc_info:
        await commands.create_reservation_command(
            session=session2,
            store_id=store_id,
            checkout_id=uuid4(),
            lines=[schemas.ReservationLineRequest(sku_id=sku_id, quantity=1)],
            principal=principal,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INSUFFICIENT_INVENTORY


# ==============================================================================
# Complete Inventory Lifecycle & Append-Only Ledger Sums (INV-01..INV-05)
# ==============================================================================

async def test_inventory_full_lifecycle_and_ledger_integrity():
    """Tests opening stock -> check availability -> reserve -> consume -> adjust -> compensating restore."""
    store_id = uuid4()
    sku_id = uuid4()
    tenant_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )
    service_principal = Principal(
        sub=uuid4(),
        roles=["SERVICE_COMMERCE", "SERVICE"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    # 1. Register SKU with opening stock = 10
    session_reg = make_mock_session()
    sku, bal = await commands.register_sku_command(
        session=session_reg,
        store_id=store_id,
        sku_id=sku_id,
        principal=owner_principal,
        sku_code="TSHIRT-BLK-M",
        is_tracked=True,
        initial_stock=10,
    )
    assert sku.sku_code == "TSHIRT-BLK-M"
    assert bal.on_hand_qty == 10
    assert any(isinstance(m, models.StockMovement) and m.movement_type == "OPENING" and m.quantity_delta == 10 for m in session_reg.added_models)

    # 2. Query availability (INV-001)
    res_sku = MagicMock()
    res_sku.scalars.return_value.first.return_value = sku
    res_bal = MagicMock()
    res_bal.scalars.return_value.first.return_value = bal

    session_avail = make_mock_session([res_sku, res_bal])
    avail_lines = await commands.get_inventory_availability_query(
        session=session_avail,
        store_id=store_id,
        sku_ids=[sku_id],
        principal=owner_principal,
    )
    assert len(avail_lines) == 1
    assert avail_lines[0].available_qty == 10
    assert avail_lines[0].is_available is True

    # 3. Reserve 3 units (INV-002)
    res_sku_hold = MagicMock()
    res_sku_hold.scalars.return_value.first.return_value = sku
    res_upd_hold = MagicMock()
    res_upd_hold.fetchone.return_value = MagicMock(id=bal.id, on_hand_qty=10, reserved_qty=3, tenant_id=tenant_id)

    session_res = make_mock_session([res_sku_hold, res_upd_hold])
    checkout_id = uuid4()
    group_id, res_list = await commands.create_reservation_command(
        session=session_res,
        store_id=store_id,
        checkout_id=checkout_id,
        lines=[schemas.ReservationLineRequest(sku_id=sku_id, quantity=3)],
        principal=service_principal,
        ttl_seconds=600,
    )
    reservation = res_list[0]
    assert reservation.quantity == 3
    assert reservation.status == "ACTIVE"

    events_res = get_outbox_events(session_res)
    assert any(e["event_type"] == "inventory.reserved.v1" for e in events_res)

    # 4. Consume reservation upon order placement (INV-003)
    res_mock_res = MagicMock()
    res_mock_res.scalars.return_value.first.return_value = reservation
    res_sku_cons = MagicMock()
    res_sku_cons.scalars.return_value.first.return_value = sku
    res_upd_cons = MagicMock()
    res_upd_cons.fetchone.return_value = MagicMock(on_hand_qty=7, reserved_qty=0)

    session_cons = make_mock_session([res_mock_res, res_sku_cons, res_upd_cons])
    consumed_res = await commands.consume_reservation_command(
        session=session_cons,
        reservation_id=reservation.id,
        principal=service_principal,
    )
    assert consumed_res.status == "CONSUMED"
    assert consumed_res.consumed_at is not None

    events_cons = get_outbox_events(session_cons)
    assert any(e["event_type"] == "inventory.consumed.v1" for e in events_cons)

    # 5. Manual stock adjustment: SET to 2 units (INV-005, triggers low-stock event)
    bal.on_hand_qty = 7
    bal.reserved_qty = 0
    res_bal_adj = MagicMock()
    res_bal_adj.scalars.return_value.first.return_value = bal

    session_adj = make_mock_session([res_bal_adj])
    adj, new_on_hand, new_avail = await commands.adjust_inventory_command(
        session=session_adj,
        store_id=store_id,
        sku_id=sku_id,
        adjustment_type="SET",
        quantity=2,
        principal=owner_principal,
        reason="Stock recount audit",
    )
    assert new_on_hand == 2
    assert new_avail == 2

    events_adj = get_outbox_events(session_adj)
    event_types_adj = [e["event_type"] for e in events_adj]
    assert "inventory.adjusted.v1" in event_types_adj
    assert "inventory.low-stock.v1" in event_types_adj

    # 6. Compensating restoration: Order cancellation restores 3 units (INV-05)
    bal.on_hand_qty = 2
    res_bal_restore = MagicMock()
    res_bal_restore.scalars.return_value.first.return_value = bal
    res_inbox_none = MagicMock()
    res_inbox_none.scalars.return_value.first.return_value = None

    session_cancel = make_mock_session([res_inbox_none, res_bal_restore])
    event_id = str(uuid4())
    await handle_internal_event(
        session=session_cancel,
        event_id=event_id,
        event_type="order.cancelled.v1",
        payload={
            "store_id": str(store_id),
            "order_id": str(uuid4()),
            "lines": [{"sku_id": str(sku_id), "quantity": 3}],
        },
    )
    assert bal.on_hand_qty == 5

    events_cancel = get_outbox_events(session_cancel)
    restore_event = next(e for e in events_cancel if e["event_type"] == "inventory.restored.v1")
    assert restore_event["payload"]["restored_quantity"] == 3
    assert restore_event["payload"]["new_on_hand_qty"] == 5


# ==============================================================================
# Reservation Expiry Sweep (Scheduler Timeout)
# ==============================================================================

async def test_reservation_expiry_sweep_releases_stock():
    """Scheduler sweeps expired ACTIVE reservations and releases reserved stock atomically."""
    store_id = uuid4()
    sku_id = uuid4()
    tenant_id = uuid4()
    res_id = uuid4()

    mock_row = MagicMock(
        id=res_id,
        store_id=store_id,
        sku_id=sku_id,
        quantity=4,
        tenant_id=tenant_id,
    )

    res_sweep = MagicMock()
    res_sweep.fetchall.return_value = [mock_row]

    session = make_mock_session([res_sweep])
    expired_count = await commands.expire_reservations_command(session)
    assert expired_count == 1

    events = get_outbox_events(session)
    expired_event = next(e for e in events if e["event_type"] == "inventory.expired.v1")
    assert expired_event["payload"]["reservation_id"] == str(res_id)
    assert expired_event["payload"]["quantity"] == 4


# ==============================================================================
# Catalog Event Integration: Automatic Physical SKU Registration
# ==============================================================================

async def test_catalog_item_created_registers_physical_sku():
    """Event catalog.item-created.v1 for PHYSICAL_PRODUCT automatically registers SKU and balance."""
    item_id = uuid4()
    store_id = uuid4()
    tenant_id = uuid4()
    event_id = str(uuid4())

    res_inbox = MagicMock()
    res_inbox.scalars.return_value.first.return_value = None
    res_sku_check = MagicMock()
    res_sku_check.scalars.return_value.first.return_value = None

    session = make_mock_session([res_inbox, res_sku_check])

    await handle_internal_event(
        session=session,
        event_id=event_id,
        event_type="catalog.item-created.v1",
        payload={
            "item_id": str(item_id),
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
            "item_type": "PHYSICAL_PRODUCT",
            "sku_code": "PROD-1234",
        },
    )

    assert any(isinstance(m, models.Sku) and m.id == item_id and m.sku_code == "PROD-1234" for m in session.added_models)
    assert any(isinstance(m, models.StockBalance) and m.sku_id == item_id and m.on_hand_qty == 0 for m in session.added_models)
