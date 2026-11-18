# app/domain.py
# Pure business rules for inventory calculations per RULES.md §6 & State Machine §9.
from libs.platform_contracts.errors import ApiError, ErrorCode


def calculate_availability(is_tracked: bool, on_hand: int, reserved: int, requested: int = 1) -> tuple[int, bool]:
    """Calculates available quantity and availability boolean for SKU.
    Non-tracked products are effectively unlimited by default (INV-R01).
    """
    if not is_tracked:
        return 999999, True
    available = max(0, on_hand - reserved)
    return available, available >= requested


def calculate_adjustment(
    on_hand: int,
    reserved: int,
    adjustment_type: str,
    quantity: int,
) -> tuple[int, int]:
    """Computes the new on_hand quantity and signed delta for an adjustment.
    Ensures on_hand cannot be adjusted below current reserved holds or negative.
    """
    if adjustment_type == "INCREMENT":
        if quantity < 0:
            raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Increment quantity must be non-negative", status_code=422)
        new_on_hand = on_hand + quantity
        delta = quantity

    elif adjustment_type == "DECREMENT":
        if quantity < 0:
            raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Decrement quantity must be non-negative", status_code=422)
        new_on_hand = on_hand - quantity
        if new_on_hand < 0:
            raise ApiError(
                ErrorCode.INSUFFICIENT_INVENTORY,
                f"Decrement of {quantity} exceeds current on-hand stock {on_hand}",
                status_code=409,
            )
        if new_on_hand < reserved:
            raise ApiError(
                ErrorCode.INSUFFICIENT_INVENTORY,
                f"Decrement leaves on-hand ({new_on_hand}) below active reserved stock ({reserved})",
                status_code=409,
            )
        delta = -quantity

    elif adjustment_type == "SET":
        if quantity < 0:
            raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Set quantity cannot be negative", status_code=422)
        new_on_hand = quantity
        if new_on_hand < reserved:
            raise ApiError(
                ErrorCode.INSUFFICIENT_INVENTORY,
                f"Setting on-hand to {quantity} is below active reserved stock ({reserved})",
                status_code=409,
            )
        delta = quantity - on_hand

    else:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Unknown adjustment_type: {adjustment_type}", status_code=422)

    return new_on_hand, delta


def is_low_stock(available_qty: int, threshold: int = 2) -> bool:
    """Returns True if stock falls to or below configured threshold."""
    return available_qty <= threshold
