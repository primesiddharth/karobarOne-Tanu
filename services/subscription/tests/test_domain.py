# tests/test_domain.py
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from app import domain


def test_period_duration_is_exact_30_days_ac_041():
    """AC-041: Subscription Billing Period is exactly 30 calendar days."""
    start = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    s, e = domain.calculate_period_dates(start)
    assert s == start
    assert e == start + timedelta(days=30)
    assert (e - s).days == 30
    assert (e - s).total_seconds() == 30 * 86400


def test_first_paid_activation_collects_2s_complimentary_setup_ac_042_043():
    """AC-042 & AC-043: Period 1 fee S + Third-Period Advance S (2S before GST), setup fee = 0."""
    plan_price = 199900  # ₹1,999.00 in paise
    quote = domain.calculate_initial_activation(
        plan_code="COMMERCE",
        plan_price_paise=plan_price,
        is_first_paid_activation=True,
        gst_rate=Decimal("0.18"),
    )

    # Period 1 = S
    assert quote["period_1"]["amount_paise"] == 199900
    assert quote["period_1"]["amount"] == "1999.00"

    # Advance A3 = S
    assert quote["third_period_advance"]["amount_paise"] == 199900
    assert quote["third_period_advance"]["amount"] == "1999.00"

    # Complimentary setup fee = 0
    assert quote["setup_fee"]["amount_paise"] == 0
    assert quote["setup_fee"]["amount"] == "0.00"
    assert quote["setup_fee"]["is_complimentary"] is True

    # Total before GST = 2S = 399800 paise (₹3,998.00)
    assert quote["total"]["amount_ex_tax_paise"] == 399800

    # GST 18% of 3998.00 = 719.64 -> 71964 paise
    assert quote["gst"]["amount_paise"] == 71964
    assert quote["gst"]["amount"] == "719.64"

    # Total with GST = 3998.00 + 719.64 = 4717.64
    assert quote["total"]["amount_paise"] == 471764
    assert quote["total"]["amount"] == "4717.64"


def test_continuation_periods_advance_reimbursement():
    """Continuation: P2 full S, P3 0.5S, P4 0.5S, P5+ full S."""
    plan_price = 199900
    p2 = domain.calculate_continuation_period(2, plan_price)
    assert p2["amount_due_paise"] == 199900
    assert p2["advance_credit_paise"] == 0

    p3 = domain.calculate_continuation_period(3, plan_price)
    assert p3["amount_due_paise"] == 99950  # 0.5 * 199900
    assert p3["advance_credit_paise"] == 99950

    p4 = domain.calculate_continuation_period(4, plan_price)
    assert p4["amount_due_paise"] == 99950
    assert p4["advance_credit_paise"] == 99950

    p5 = domain.calculate_continuation_period(5, plan_price)
    assert p5["amount_due_paise"] == 199900
    assert p5["advance_credit_paise"] == 0


def test_cancellation_before_p3():
    """AC-046..048: Cancellation notice before P3 results in ₹0 additional payment, ends after P3."""
    plan_price = 199900
    c = domain.calculate_cancellation_period_3(plan_price)
    assert c["additional_period_3_due"] == "0.00"
    assert c["additional_period_3_due_paise"] == 0
    assert c["advance_consumed_paise"] == 199900
    assert c["paid_through_period"] == 3
    assert c["end_after_period"] == 3


def test_upgrade_calculation_rules():
    """AC-069..075: Upgrade quote with proration, setup fee, advance top-up."""
    # Upgrade Commerce (₹1,999) to Growth (₹4,999) with 15 days remaining before P3
    lower_paise = 199900
    higher_paise = 499900
    days_rem = 15
    q = domain.calculate_upgrade_quote(
        lower_price_paise=lower_paise,
        higher_price_paise=higher_paise,
        days_remaining=days_rem,
        is_before_p3=True,
        current_advance_balance_paise=lower_paise,
        approved_discount_paise=0,
    )

    diff = higher_paise - lower_paise  # 300000 paise (₹3,000)
    # Prorated diff = 300000 * 15 / 30 = 150000 paise (₹1,500)
    assert q["prorated_difference_paise"] == 150000
    # Advance top up = max(0, 499900 - 199900) = 300000 paise (₹3,000)
    assert q["advance_top_up_paise"] == 300000
    # Gross setup fee = 0.5 * 300000 = 150000 paise (₹1,500)
    assert q["gross_upgrade_setup_fee_paise"] == 150000
    assert q["net_setup_fee_paise"] == 150000

    # Total ex-tax = 150000 + 300000 + 150000 = 600000 paise (₹6,000)
    assert q["total_before_gst_paise"] == 600000
    # GST 18% of 6000 = 1080 -> 108000 paise
    assert q["gst_paise"] == 108000
    # Total = 708000 paise (₹7,080.00)
    assert q["total_paise"] == 708000


def test_entitlement_maps():
    """Entitlements projection mapping."""
    free_ent = domain.build_entitlements_map("PRESENCE", "ACTIVE_PERIOD_1")
    assert free_ent["commerce_enabled"] is False
    assert free_ent["showcase_limit"] == 6
    assert free_ent["custom_domain_allowed"] is False

    comm_ent = domain.build_entitlements_map("COMMERCE", "ACTIVE_PERIOD_1")
    assert comm_ent["commerce_enabled"] is True
    assert comm_ent["max_images_per_item"] == 5
    assert comm_ent["custom_domain_allowed"] is True

    # Delinquent Commerce in SUBSCRIPTION_EXPIRED
    expired_ent = domain.build_entitlements_map("COMMERCE", "SUBSCRIPTION_EXPIRED")
    assert expired_ent["commerce_enabled"] is False  # Orders denied during expired (AC-057/058)
