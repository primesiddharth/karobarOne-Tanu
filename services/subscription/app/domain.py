# app/domain.py
"""Pure calculation and state machine transition rules for Subscription & Entitlement Service (SUB).
Source: BTDD §9.3 & §13, State Machine §17 & §18, AC-011, AC-041..075.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from libs.platform_contracts.errors import ApiError, ErrorCode

CALC_POLICY_VERSION = "2026-v1.0"
PERIOD_DURATION_DAYS = 30

ALLOWED_SUBSCRIPTION_TRANSITIONS: dict[str, set[str]] = {
    "FREE_PRESENCE": {"ACTIVE_PERIOD_1", "REACTIVATION_REQUESTED"},
    "ACTIVE_PERIOD_1": {"ACTIVE_PERIOD_2", "PAYMENT_GRACE", "SUBSCRIPTION_EXPIRED", "FREE_PRESENCE"},
    "ACTIVE_PERIOD_2": {"P3_FULLY_PREPAID", "P3_50_PERCENT_DUE", "PAYMENT_GRACE", "SUBSCRIPTION_EXPIRED", "FREE_PRESENCE"},
    "P3_FULLY_PREPAID": {"FREE_PRESENCE"},
    "P3_50_PERCENT_DUE": {"P4_50_PERCENT_DUE", "PAYMENT_GRACE", "SUBSCRIPTION_EXPIRED", "FREE_PRESENCE"},
    "P4_50_PERCENT_DUE": {"STANDARD_RENEWAL", "PAYMENT_GRACE", "SUBSCRIPTION_EXPIRED", "FREE_PRESENCE"},
    "STANDARD_RENEWAL": {"STANDARD_RENEWAL", "PAYMENT_GRACE", "SUBSCRIPTION_EXPIRED", "FREE_PRESENCE"},
    "PAYMENT_GRACE": {
        "ACTIVE_PERIOD_1", "ACTIVE_PERIOD_2", "P3_FULLY_PREPAID", "P3_50_PERCENT_DUE",
        "P4_50_PERCENT_DUE", "STANDARD_RENEWAL", "SUBSCRIPTION_EXPIRED", "FREE_PRESENCE"
    },
    "SUBSCRIPTION_EXPIRED": {
        "ACTIVE_PERIOD_1", "ACTIVE_PERIOD_2", "P3_FULLY_PREPAID", "P3_50_PERCENT_DUE",
        "P4_50_PERCENT_DUE", "STANDARD_RENEWAL", "FREE_PRESENCE"
    },
}


def assert_can_transition(current_state: str, target_state: str) -> None:
    """Guards subscription aggregate transitions per State Machine §17."""
    allowed = ALLOWED_SUBSCRIPTION_TRANSITIONS.get(current_state, set())
    if target_state not in allowed:
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Invalid subscription transition from {current_state} to {target_state}",
        )



def paise_to_decimal_str(paise: int) -> str:
    """Converts integer paise to standard decimal representation (e.g. 199900 -> '1999.00')."""
    val = Decimal(paise) / Decimal(100)
    return f"{val:.2f}"


def decimal_str_to_paise(amount_str: str) -> int:
    """Converts decimal amount string to integer paise."""
    val = Decimal(amount_str)
    return int((val * Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))


def calculate_period_dates(starts_at: datetime) -> tuple[datetime, datetime]:
    """Calculates exact 30 consecutive calendar days billing window [start, start + 30 days).
    Never uses calendar months (AC-041).
    """
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    ends_at = starts_at + timedelta(days=PERIOD_DURATION_DAYS)
    return starts_at, ends_at


def calculate_initial_activation(
    plan_code: str,
    plan_price_paise: int,
    is_first_paid_activation: bool = True,
    gst_rate: Decimal = Decimal("0.18"),
) -> dict[str, Any]:
    """Calculates first paid activation charges:
    - Period 1 fee = S
    - Third-Period Advance A3 = S
    - First-ever setup fee = 0 (AC-042, AC-043)
    - Total collection before GST = 2S
    """
    period_1_fee_paise = plan_price_paise
    advance_paise = plan_price_paise
    setup_fee_paise = 0 if is_first_paid_activation else int(Decimal(plan_price_paise) * Decimal("0.5"))

    total_ex_tax_paise = period_1_fee_paise + advance_paise + setup_fee_paise
    gst_paise = int((Decimal(total_ex_tax_paise) * gst_rate).to_integral_value(rounding=ROUND_HALF_UP))
    total_with_tax_paise = total_ex_tax_paise + gst_paise

    return {
        "policy_version": CALC_POLICY_VERSION,
        "plan_code": plan_code,
        "period_1": {
            "amount_paise": period_1_fee_paise,
            "amount": paise_to_decimal_str(period_1_fee_paise),
        },
        "third_period_advance": {
            "amount_paise": advance_paise,
            "amount": paise_to_decimal_str(advance_paise),
        },
        "setup_fee": {
            "amount_paise": setup_fee_paise,
            "amount": paise_to_decimal_str(setup_fee_paise),
            "is_complimentary": is_first_paid_activation,
        },
        "gst": {
            "rate": float(gst_rate),
            "amount_paise": gst_paise,
            "amount": paise_to_decimal_str(gst_paise),
        },
        "total": {
            "amount_ex_tax_paise": total_ex_tax_paise,
            "amount_paise": total_with_tax_paise,
            "amount": paise_to_decimal_str(total_with_tax_paise),
        },
    }


def calculate_cancellation_period_3(plan_price_paise: int) -> dict[str, Any]:
    """Calculates cancellation charges for Period 3 when notice submitted before P3 start:
    - Additional Period 3 payment = 0 (A3 funds it)
    - Full paid features during Period 3
    - Converts to FREE_PRESENCE after Period 3 (AC-045..048).
    """
    return {
        "paid_through_period": 3,
        "additional_period_3_due": "0.00",
        "additional_period_3_due_paise": 0,
        "advance_consumed_paise": plan_price_paise,
        "end_after_period": 3,
        "subsequent_state": "FREE_PRESENCE",
    }


def calculate_continuation_period(
    period_no: int,
    plan_price_paise: int,
    gst_rate: Decimal = Decimal("0.18"),
) -> dict[str, Any]:
    """Calculates continuation periods (no cancellation notice before P3):
    - P2: full S (AC-044)
    - P3: 0.5S due, 0.5S advance credit (AC-049..051)
    - P4: 0.5S due, 0.5S advance credit (AC-052)
    - P5+: full S standard renewal (AC-053).
    """
    if period_no == 2:
        amount_due_paise = plan_price_paise
        advance_credit_paise = 0
        charge_mode = "FULL"
    elif period_no in (3, 4):
        amount_due_paise = int(Decimal(plan_price_paise) * Decimal("0.5"))
        advance_credit_paise = int(Decimal(plan_price_paise) * Decimal("0.5"))
        charge_mode = "HALF_ADVANCE_CREDIT"
    else:
        amount_due_paise = plan_price_paise
        advance_credit_paise = 0
        charge_mode = "FULL"

    gst_paise = int((Decimal(amount_due_paise) * gst_rate).to_integral_value(rounding=ROUND_HALF_UP))
    total_paise = amount_due_paise + gst_paise

    return {
        "period_no": period_no,
        "charge_mode": charge_mode,
        "amount_due_paise": amount_due_paise,
        "amount_due": paise_to_decimal_str(amount_due_paise),
        "advance_credit_paise": advance_credit_paise,
        "advance_credit": paise_to_decimal_str(advance_credit_paise),
        "gst_paise": gst_paise,
        "gst": paise_to_decimal_str(gst_paise),
        "total_paise": total_paise,
        "total": paise_to_decimal_str(total_paise),
    }


def calculate_delinquency_state(days_overdue: int) -> str:
    """Calculates subscription state for unpaid charges (AC-054..061):
    - Days 1-7: PAYMENT_GRACE
    - Days 8-22: SUBSCRIPTION_EXPIRED
    - Day 23+: FREE_PRESENCE
    """
    if days_overdue <= 7:
        return "PAYMENT_GRACE"
    elif days_overdue <= 22:
        return "SUBSCRIPTION_EXPIRED"
    else:
        return "FREE_PRESENCE"


def calculate_reactivation(
    plan_code: str,
    plan_price_paise: int,
    gst_rate: Decimal = Decimal("0.18"),
) -> dict[str, Any]:
    """Calculates reactivation quote after non-payment Free conversion:
    - New 30-day period S + Reactivation Setup Fee 0.5S
    - Complimentary setup waiver cannot be reused (AC-065..068).
    """
    period_fee_paise = plan_price_paise
    reactivation_setup_paise = int(Decimal(plan_price_paise) * Decimal("0.5"))
    total_ex_tax_paise = period_fee_paise + reactivation_setup_paise
    gst_paise = int((Decimal(total_ex_tax_paise) * gst_rate).to_integral_value(rounding=ROUND_HALF_UP))
    total_with_tax_paise = total_ex_tax_paise + gst_paise

    return {
        "policy_version": CALC_POLICY_VERSION,
        "plan_code": plan_code,
        "period_fee_paise": period_fee_paise,
        "period_fee": paise_to_decimal_str(period_fee_paise),
        "reactivation_setup_paise": reactivation_setup_paise,
        "reactivation_setup": paise_to_decimal_str(reactivation_setup_paise),
        "gst_paise": gst_paise,
        "gst": paise_to_decimal_str(gst_paise),
        "total_paise": total_with_tax_paise,
        "total": paise_to_decimal_str(total_with_tax_paise),
    }


def calculate_upgrade_quote(
    lower_price_paise: int,
    higher_price_paise: int,
    days_remaining: int,
    is_before_p3: bool,
    current_advance_balance_paise: int = 0,
    approved_discount_paise: int = 0,
    gst_rate: Decimal = Decimal("0.18"),
) -> dict[str, Any]:
    """Calculates upgrade quote L -> H with R days remaining (AC-069..075):
    - Prorated subscription difference = (H - L) * R / 30
    - If before P3: advance top up = max(0, H - current_advance_balance)
    - Gross upgrade setup fee = 0.5 * (H - L)
    - Net setup fee = max(0, gross_setup_fee - approved_discount_paise)
    - Total = prorated_diff + advance_top_up + net_setup_fee + GST
    """
    if higher_price_paise <= lower_price_paise:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Target plan price must be higher than current plan")
    if not (0 <= days_remaining <= PERIOD_DURATION_DAYS):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Days remaining must be between 0 and {PERIOD_DURATION_DAYS}")

    diff_paise = higher_price_paise - lower_price_paise
    prorated_diff_paise = int(
        (Decimal(diff_paise) * Decimal(days_remaining) / Decimal(PERIOD_DURATION_DAYS)).to_integral_value(
            rounding=ROUND_HALF_UP
        )
    )

    advance_top_up_paise = max(0, higher_price_paise - current_advance_balance_paise) if is_before_p3 else 0
    gross_setup_fee_paise = int((Decimal(diff_paise) * Decimal("0.5")).to_integral_value(rounding=ROUND_HALF_UP))
    net_setup_fee_paise = max(0, gross_setup_fee_paise - approved_discount_paise)

    total_ex_tax_paise = prorated_diff_paise + advance_top_up_paise + net_setup_fee_paise
    gst_paise = int((Decimal(total_ex_tax_paise) * gst_rate).to_integral_value(rounding=ROUND_HALF_UP))
    total_with_tax_paise = total_ex_tax_paise + gst_paise

    return {
        "policy_version": CALC_POLICY_VERSION,
        "lower_price": paise_to_decimal_str(lower_price_paise),
        "higher_price": paise_to_decimal_str(higher_price_paise),
        "days_remaining": days_remaining,
        "prorated_difference": paise_to_decimal_str(prorated_diff_paise),
        "prorated_difference_paise": prorated_diff_paise,
        "advance_top_up": paise_to_decimal_str(advance_top_up_paise),
        "advance_top_up_paise": advance_top_up_paise,
        "gross_upgrade_setup_fee": paise_to_decimal_str(gross_setup_fee_paise),
        "gross_upgrade_setup_fee_paise": gross_setup_fee_paise,
        "approved_discount": paise_to_decimal_str(approved_discount_paise),
        "approved_discount_paise": approved_discount_paise,
        "net_setup_fee": paise_to_decimal_str(net_setup_fee_paise),
        "net_setup_fee_paise": net_setup_fee_paise,
        "total_before_gst": paise_to_decimal_str(total_ex_tax_paise),
        "total_before_gst_paise": total_ex_tax_paise,
        "gst": paise_to_decimal_str(gst_paise),
        "gst_paise": gst_paise,
        "total": paise_to_decimal_str(total_with_tax_paise),
        "total_paise": total_with_tax_paise,
    }


def build_entitlements_map(plan_code: str, state: str) -> dict[str, Any]:
    """Builds authoritative entitlement capabilities projection for a store."""
    is_free = (plan_code.upper() in ("PRESENCE", "FREE") or state == "FREE_PRESENCE")
    is_expired = (state in ("SUBSCRIPTION_EXPIRED", "FREE_PRESENCE"))

    if is_free:
        return {
            "plan_code": "PRESENCE",
            "state": state,
            "commerce_enabled": False,
            "showcase_limit": 6,
            "max_images_per_item": 1,
            "max_videos_per_item": 0,
            "custom_domain_allowed": False,
            "blog_allowed": False,
        }

    plan_upper = plan_code.upper()
    if plan_upper == "COMMERCE":
        return {
            "plan_code": "COMMERCE",
            "state": state,
            "commerce_enabled": not is_expired,
            "showcase_limit": None,
            "max_images_per_item": 5,
            "max_videos_per_item": 0,
            "custom_domain_allowed": True,
            "blog_allowed": True,
        }
    elif plan_upper == "GROWTH":
        return {
            "plan_code": "GROWTH",
            "state": state,
            "commerce_enabled": not is_expired,
            "showcase_limit": None,
            "max_images_per_item": 10,
            "max_videos_per_item": 1,
            "custom_domain_allowed": True,
            "blog_allowed": True,
        }
    elif plan_upper == "SCALE_AI":
        return {
            "plan_code": "SCALE_AI",
            "state": state,
            "commerce_enabled": not is_expired,
            "showcase_limit": None,
            "max_images_per_item": 50,
            "max_videos_per_item": 5,
            "custom_domain_allowed": True,
            "blog_allowed": True,
        }

    # Fallback to Free presence
    return {
        "plan_code": "PRESENCE",
        "state": state,
        "commerce_enabled": False,
        "showcase_limit": 6,
        "max_images_per_item": 1,
        "max_videos_per_item": 0,
        "custom_domain_allowed": False,
        "blog_allowed": False,
    }
