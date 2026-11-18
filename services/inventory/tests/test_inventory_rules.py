# tests/test_inventory_rules.py
# Pure business logic and domain calculation tests for INV (RULES.md §5, State Machine §9).
import pytest
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import domain, models


def test_calculate_availability_non_tracked():
    """Non-tracked SKUs have effectively unlimited availability (INV-R01)."""
    avail, is_avail = domain.calculate_availability(is_tracked=False, on_hand=0, reserved=0, requested=100)
    assert avail == 999999
    assert is_avail is True


def test_calculate_availability_tracked():
    """Tracked SKUs compute available = max(0, on_hand - reserved)."""
    avail, is_avail = domain.calculate_availability(is_tracked=True, on_hand=10, reserved=4, requested=5)
    assert avail == 6
    assert is_avail is True

    # Requested exceeds available
    avail2, is_avail2 = domain.calculate_availability(is_tracked=True, on_hand=10, reserved=4, requested=7)
    assert avail2 == 6
    assert is_avail2 is False


def test_calculate_adjustment_increment():
    """INCREMENT adjustment increases on-hand stock."""
    new_on_hand, delta = domain.calculate_adjustment(on_hand=10, reserved=2, adjustment_type="INCREMENT", quantity=5)
    assert new_on_hand == 15
    assert delta == 5


def test_calculate_adjustment_decrement_valid():
    """DECREMENT adjustment decreases on-hand stock safely."""
    new_on_hand, delta = domain.calculate_adjustment(on_hand=10, reserved=2, adjustment_type="DECREMENT", quantity=4)
    assert new_on_hand == 6
    assert delta == -4


def test_calculate_adjustment_decrement_below_zero_rejected():
    """DECREMENT cannot reduce on-hand below zero (INV-R02: no negative stock)."""
    with pytest.raises(ApiError) as exc_info:
        domain.calculate_adjustment(on_hand=10, reserved=0, adjustment_type="DECREMENT", quantity=15)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INSUFFICIENT_INVENTORY


def test_calculate_adjustment_decrement_below_reserved_rejected():
    """DECREMENT cannot reduce on-hand below currently active reserved holds."""
    with pytest.raises(ApiError) as exc_info:
        domain.calculate_adjustment(on_hand=10, reserved=6, adjustment_type="DECREMENT", quantity=5)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INSUFFICIENT_INVENTORY
    assert "below active reserved stock" in exc_info.value.message


def test_calculate_adjustment_set():
    """SET adjustment directly updates on-hand stock and computes signed delta."""
    new_on_hand, delta = domain.calculate_adjustment(on_hand=10, reserved=2, adjustment_type="SET", quantity=20)
    assert new_on_hand == 20
    assert delta == 10

    # SET below reserved holds -> rejected
    with pytest.raises(ApiError) as exc_info:
        domain.calculate_adjustment(on_hand=10, reserved=5, adjustment_type="SET", quantity=3)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INSUFFICIENT_INVENTORY


def test_low_stock_evaluation():
    """Evaluates low-stock boundary."""
    assert domain.is_low_stock(available_qty=2, threshold=2) is True
    assert domain.is_low_stock(available_qty=1, threshold=2) is True
    assert domain.is_low_stock(available_qty=0, threshold=2) is True
    assert domain.is_low_stock(available_qty=3, threshold=2) is False


def test_stock_balance_model_available_property():
    """Verifies available_qty property on StockBalance model."""
    bal = models.StockBalance(on_hand_qty=50, reserved_qty=12)
    assert bal.available_qty == 38

    bal_oversell_guard = models.StockBalance(on_hand_qty=0, reserved_qty=0)
    assert bal_oversell_guard.available_qty == 0
