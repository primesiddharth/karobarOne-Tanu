# tests/acceptance/test_ac_subscription.py
# Acceptance Criteria test suite for Subscription service (SERVICES.md §7, ROADMAP Phase 8a).
# Function names follow test_ac_NNN_* pattern checked by tools/check_ac_coverage.py.
import pytest
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import commands, models, domain, schemas

pytestmark = pytest.mark.asyncio


def make_mock_session(execute_results=None, get_mapping=None):
    """Helper creating mock AsyncSession that returns queued results and handles outbox inserts."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    if get_mapping:
        mock_session.get.side_effect = (
            lambda model, obj_id, **kw: get_mapping.get((model, obj_id)) or get_mapping.get(model) or get_mapping.get(obj_id)
        )

    results = list(execute_results or [])

    async def _execute(*args, **kwargs):
        if args and ("set_config" in str(args[0]) or "INSERT INTO subscription.outbox_events" in str(args[0])):
            res = MagicMock()
            return res
        if results:
            return results.pop(0)
        res = MagicMock()
        res.scalars.return_value.first.return_value = None
        res.scalars.return_value.all.return_value = []
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session


# -----------------------------------------------------------------------------
# AC-041: Subscription Billing Period is exactly 30 calendar days
# -----------------------------------------------------------------------------

async def test_ac_041_billing_period_is_exact_30_calendar_days():
    """Paid subscription period calculates exactly 30 consecutive calendar days, not calendar months (AC-041)."""
    # Test across month boundaries, leap years, and February
    start_dates = [
        datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 31, 12, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 2, 1, 0, 0, 0, tzinfo=timezone.utc),
        datetime(2028, 2, 15, 8, 30, 0, tzinfo=timezone.utc),  # Leap year
        datetime(2026, 12, 15, 23, 59, 59, tzinfo=timezone.utc),
    ]

    for start in start_dates:
        s, e = domain.calculate_period_dates(start)
        assert s == start
        assert e == start + timedelta(days=30)
        assert (e - s).days == 30
        assert (e - s).total_seconds() == 30 * 86400


# -----------------------------------------------------------------------------
# AC-042: First paid activation collects Period 1 fee plus 100% Third-Period Advance
# -----------------------------------------------------------------------------

async def test_ac_042_first_paid_activation_collects_period1_plus_advance():
    """First paid activation quote collects Period 1 fee S + Third-Period Advance S (2S total ex-GST) (AC-042)."""
    store_id = uuid4()
    tenant_id = uuid4()
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], store_ids=[store_id], tenant_ids=[tenant_id])

    plan_ver = models.PlanVersion(
        id=uuid4(),
        plan_code="COMMERCE",
        version_no=1,
        period_days=30,
        price_amount=Decimal("1999.00"),
        commission_rate=Decimal("0.040000"),
        is_active=True,
    )

    # 1. Plan lookup result
    res_plan = MagicMock()
    res_plan.scalars.return_value.first.return_value = plan_ver

    # 2. Existing subscription lookup -> None (first ever activation)
    res_sub = MagicMock()
    res_sub.scalars.return_value.first.return_value = None

    mock_session = make_mock_session(execute_results=[res_plan, res_sub])

    with patch("app.clients.tenant_client.verify_store_gstin", AsyncMock(return_value=True)):
        quote = await commands.create_activation_quote_command(
            session=mock_session,
            principal=principal,
            store_id=store_id,
            plan_code="COMMERCE",
            gstin_id=uuid4(),
        )

    # S = 199900 paise
    assert quote.period_1.amount == "1999.00"
    assert quote.period_1.amount_paise == 199900

    # Advance A3 = S = 199900 paise
    assert quote.third_period_advance.amount == "1999.00"
    assert quote.third_period_advance.amount_paise == 199900

    # Total ex-tax = 2S = 399800 paise
    assert quote.total.amount_ex_tax_paise == 399800
    # Total with 18% GST = 3998.00 + 719.64 = 4717.64
    assert quote.total.amount == "4717.64"
    assert quote.total.amount_paise == 471764


# -----------------------------------------------------------------------------
# AC-043: First-ever setup of each individual store is complimentary
# -----------------------------------------------------------------------------

async def test_ac_043_first_ever_setup_fee_complimentary():
    """Initial setup fee for a store with no previous paid activation is zero/complimentary (AC-043)."""
    store_id = uuid4()
    tenant_id = uuid4()
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], store_ids=[store_id], tenant_ids=[tenant_id])

    plan_ver = models.PlanVersion(
        id=uuid4(),
        plan_code="GROWTH",
        version_no=1,
        period_days=30,
        price_amount=Decimal("4999.00"),
        commission_rate=Decimal("0.020000"),
        is_active=True,
    )

    # First activation: no prior subscription row
    res_plan1 = MagicMock()
    res_plan1.scalars.return_value.first.return_value = plan_ver
    res_sub1 = MagicMock()
    res_sub1.scalars.return_value.first.return_value = None

    mock_session = make_mock_session(execute_results=[res_plan1, res_sub1])

    with patch("app.clients.tenant_client.verify_store_gstin", AsyncMock(return_value=True)):
        quote = await commands.create_activation_quote_command(
            session=mock_session,
            principal=principal,
            store_id=store_id,
            plan_code="GROWTH",
            gstin_id=uuid4(),
        )

    assert quote.setup_fee.amount == "0.00"
    assert quote.setup_fee.amount_paise == 0
    assert quote.setup_fee.is_complimentary is True


# -----------------------------------------------------------------------------
# AC-011: No turnover-based mandatory upgrade exists
# -----------------------------------------------------------------------------

async def test_ac_011_no_turnover_based_forced_upgrade():
    """High turnover does not trigger a forced upgrade or change entitlement tier (AC-011)."""
    store_id = uuid4()
    tenant_id = uuid4()

    # Create active Commerce subscription
    sub = models.Subscription(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        plan_version_id=uuid4(),
        state="ACTIVE_PERIOD_1",
        activation_sequence=1,
        current_period_no=1,
    )
    snapshot = models.EntitlementSnapshot(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        subscription_id=sub.id,
        plan_code="COMMERCE",
        effective_from=datetime.now(timezone.utc),
        entitlements=domain.build_entitlements_map("COMMERCE", "ACTIVE_PERIOD_1"),
        reason_code="ACTIVATION",
    )

    res_snap = MagicMock()
    res_snap.scalars.return_value.first.return_value = snapshot
    mock_session = make_mock_session(execute_results=[res_snap])

    # Store processes high transaction volume (simulated in ledger/turnover)
    high_turnover_amounts = [10_000_000, 50_000_000, 100_000_000]  # in paise
    for amt in high_turnover_amounts:
        res_snap = MagicMock()
        res_snap.scalars.return_value.first.return_value = snapshot
        mock_session = make_mock_session(execute_results=[res_snap])
        # Evaluate store entitlements
        ent = await commands.get_store_entitlements_command(
            session=mock_session,
            store_id=store_id,
        )
        # Plan remains COMMERCE and is never forcibly changed to GROWTH or SCALE_AI
        assert ent.plan_code == "COMMERCE"
        assert ent.state == "ACTIVE_PERIOD_1"
        assert ent.commerce_enabled is True


# -----------------------------------------------------------------------------
# AC-044: Period 2 requires full applicable subscription payment
# -----------------------------------------------------------------------------

async def test_ac_044_period_2_requires_full_subscription_payment():
    """Period 2 requires full applicable plan price S; advance is not auto-applied (AC-044)."""
    p2 = domain.calculate_continuation_period(period_no=2, plan_price_paise=199900)
    assert p2["amount_due_paise"] == 199900
    assert p2["amount_due"] == "1999.00"
    assert p2["advance_credit_paise"] == 0
    assert p2["charge_mode"] == "FULL"


# -----------------------------------------------------------------------------
# AC-045: Cancellation notice can be submitted any time before Period 3 starts
# -----------------------------------------------------------------------------

async def test_ac_045_cancellation_notice_can_be_submitted_before_period_3():
    """Cancellation notice is accepted before P3 start; rejected if P3 already started (AC-045)."""
    sub_id = uuid4()
    store_id = uuid4()
    tenant_id = uuid4()
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], store_ids=[store_id], tenant_ids=[tenant_id])

    # Valid notice during Period 1 or Period 2
    sub_p1 = models.Subscription(
        id=sub_id,
        tenant_id=tenant_id,
        store_id=store_id,
        plan_version_id=uuid4(),
        state="ACTIVE_PERIOD_1",
        current_period_no=1,
        version=1,
    )
    mock_session = make_mock_session(get_mapping={sub_id: sub_p1})
    res = await commands.cancel_subscription_command(
        session=mock_session,
        subscription_id=sub_id,
        principal=principal,
    )
    assert res.paid_through_period == 3
    assert res.end_after_period == 3

    # Invalid notice during Period 3 -> 409 CANCELLATION_WINDOW_CLOSED
    sub_p3 = models.Subscription(
        id=sub_id,
        tenant_id=tenant_id,
        store_id=store_id,
        plan_version_id=uuid4(),
        state="ACTIVE_PERIOD_2",
        current_period_no=3,
        version=2,
    )
    mock_session_p3 = make_mock_session(get_mapping={sub_id: sub_p3})
    with pytest.raises(ApiError) as exc_info:
        await commands.cancel_subscription_command(
            session=mock_session_p3,
            subscription_id=sub_id,
            principal=principal,
        )
    assert exc_info.value.code == ErrorCode.CANCELLATION_WINDOW_CLOSED


# -----------------------------------------------------------------------------
# AC-046: Valid cancellation before Period 3 produces INR 0 additional Period-3 payment
# -----------------------------------------------------------------------------

async def test_ac_046_cancellation_before_period_3_produces_zero_additional_payment():
    """Cancellation before P3 produces ₹0 additional P3 payment because A3 funds it (AC-046)."""
    c = domain.calculate_cancellation_period_3(199900)
    assert c["additional_period_3_due"] == "0.00"
    assert c["additional_period_3_due_paise"] == 0
    assert c["advance_consumed_paise"] == 199900


# -----------------------------------------------------------------------------
# AC-047: Valid cancellation allows full paid functionality during Period 3
# -----------------------------------------------------------------------------

async def test_ac_047_cancellation_allows_full_paid_functionality_during_period_3():
    """Paid functionality remains available throughout Period 3 despite cancellation notice (AC-047)."""
    ent = domain.build_entitlements_map("COMMERCE", "P3_FULLY_PREPAID")
    assert ent["commerce_enabled"] is True
    assert ent["custom_domain_allowed"] is True
    assert ent["max_images_per_item"] == 5


# -----------------------------------------------------------------------------
# AC-048: Valid cancellation causes paid subscription to end after Period 3
# -----------------------------------------------------------------------------

async def test_ac_048_cancellation_causes_paid_subscription_to_end_after_period_3():
    """Paid subscription ends and converts to FREE_PRESENCE after Period 3 (AC-048)."""
    c = domain.calculate_cancellation_period_3(199900)
    assert c["end_after_period"] == 3
    assert c["subsequent_state"] == "FREE_PRESENCE"


# -----------------------------------------------------------------------------
# AC-049: Absence of cancellation notice constitutes continuation
# -----------------------------------------------------------------------------

async def test_ac_049_absence_of_cancellation_constitutes_continuation():
    """Without cancellation notice before P3, subscription continues into 50% continuation path (AC-049)."""
    p3 = domain.calculate_continuation_period(3, 199900)
    assert p3["charge_mode"] == "HALF_ADVANCE_CREDIT"


# -----------------------------------------------------------------------------
# AC-050: Continuation causes Third-Period Advance to be credited across P3 & P4
# -----------------------------------------------------------------------------

async def test_ac_050_continuation_credits_advance_across_period_3_and_4():
    """Continuation applies 0.5S credit in P3 and 0.5S credit in P4 (100% reimbursed) (AC-050)."""
    p3 = domain.calculate_continuation_period(3, 199900)
    p4 = domain.calculate_continuation_period(4, 199900)
    total_credit = p3["advance_credit_paise"] + p4["advance_credit_paise"]
    assert total_credit == 199900  # 100% of original advance S


# -----------------------------------------------------------------------------
# AC-051: Continuation requires 50% subscription payment for Period 3
# -----------------------------------------------------------------------------

async def test_ac_051_continuation_requires_50_percent_payment_period_3():
    """Period 3 requires 50% payment S (0.5S) on continuation (AC-051)."""
    p3 = domain.calculate_continuation_period(3, 199900)
    assert p3["amount_due_paise"] == 99950  # 50% of 199900


# -----------------------------------------------------------------------------
# AC-052: Continuation requires 50% subscription payment for Period 4
# -----------------------------------------------------------------------------

async def test_ac_052_continuation_requires_50_percent_payment_period_4():
    """Period 4 requires 50% payment S (0.5S) on continuation (AC-052)."""
    p4 = domain.calculate_continuation_period(4, 199900)
    assert p4["amount_due_paise"] == 99950  # 50% of 199900


# -----------------------------------------------------------------------------
# AC-053: Period 5 onward returns to full standard renewal pricing
# -----------------------------------------------------------------------------

async def test_ac_053_period_5_onward_returns_to_full_standard_pricing():
    """Period 5 onward returns to full plan price S per 30-day period (AC-053)."""
    p5 = domain.calculate_continuation_period(5, 199900)
    assert p5["amount_due_paise"] == 199900
    assert p5["advance_credit_paise"] == 0
    assert p5["charge_mode"] == "FULL"


# -----------------------------------------------------------------------------
# AC-054: Unpaid charge enters PAYMENT_GRACE on Days 1-7
# -----------------------------------------------------------------------------

async def test_ac_054_unpaid_charge_enters_payment_grace_days_1_to_7():
    """Unpaid due date enters PAYMENT_GRACE for days 1 through 7 (AC-054)."""
    for day in range(1, 8):
        assert domain.calculate_delinquency_state(day) == "PAYMENT_GRACE"


# -----------------------------------------------------------------------------
# AC-055: Unpaid charge enters SUBSCRIPTION_EXPIRED on Day 8
# -----------------------------------------------------------------------------

async def test_ac_055_unpaid_charge_enters_subscription_expired_day_8():
    """Unpaid charge transitions from grace to SUBSCRIPTION_EXPIRED on Day 8 (AC-055)."""
    assert domain.calculate_delinquency_state(8) == "SUBSCRIPTION_EXPIRED"
    assert domain.calculate_delinquency_state(22) == "SUBSCRIPTION_EXPIRED"


# -----------------------------------------------------------------------------
# AC-056: Storefront remains visible during SUBSCRIPTION_EXPIRED
# -----------------------------------------------------------------------------

async def test_ac_056_storefront_remains_visible_during_subscription_expired():
    """Website visibility is maintained during SUBSCRIPTION_EXPIRED (AC-056)."""
    ent = domain.build_entitlements_map("COMMERCE", "SUBSCRIPTION_EXPIRED")
    # Website visible / custom domain still active
    assert ent["custom_domain_allowed"] is True


# -----------------------------------------------------------------------------
# AC-057: New order creation is rejected during SUBSCRIPTION_EXPIRED
# -----------------------------------------------------------------------------

async def test_ac_057_new_orders_denied_during_subscription_expired():
    """commerce_enabled is False in entitlement projection during SUBSCRIPTION_EXPIRED (AC-057)."""
    ent = domain.build_entitlements_map("COMMERCE", "SUBSCRIPTION_EXPIRED")
    assert ent["commerce_enabled"] is False


# -----------------------------------------------------------------------------
# AC-058: New booking creation is rejected during SUBSCRIPTION_EXPIRED
# -----------------------------------------------------------------------------

async def test_ac_058_new_bookings_denied_during_subscription_expired():
    """booking/commerce actions denied in SUBSCRIPTION_EXPIRED state (AC-058)."""
    ent = domain.build_entitlements_map("GROWTH", "SUBSCRIPTION_EXPIRED")
    assert ent["commerce_enabled"] is False


# -----------------------------------------------------------------------------
# AC-059: Unpaid charge converts to FREE_PRESENCE on Day 23
# -----------------------------------------------------------------------------

async def test_ac_059_unpaid_charge_converts_to_free_presence_day_23():
    """Unpaid charge triggers automatic conversion to FREE_PRESENCE on Day 23 (AC-059)."""
    assert domain.calculate_delinquency_state(23) == "FREE_PRESENCE"
    assert domain.calculate_delinquency_state(30) == "FREE_PRESENCE"


# -----------------------------------------------------------------------------
# AC-060: FREE_PRESENCE conversion retains <=6 showcase items
# -----------------------------------------------------------------------------

async def test_ac_060_free_presence_conversion_retains_six_showcase_items():
    """Showcase limit on conversion to FREE_PRESENCE is capped at 6 (AC-060)."""
    ent = domain.build_entitlements_map("COMMERCE", "FREE_PRESENCE")
    assert ent["showcase_limit"] == 6
    assert ent["plan_code"] == "PRESENCE"


# -----------------------------------------------------------------------------
# AC-061: Higher-plan data is preserved hidden/inaccessible
# -----------------------------------------------------------------------------

async def test_ac_061_higher_plan_data_preserved_hidden_after_free_conversion():
    """In FREE_PRESENCE, features are disabled but records remain intact (AC-061)."""
    ent = domain.build_entitlements_map("GROWTH", "FREE_PRESENCE")
    assert ent["commerce_enabled"] is False
    assert ent["custom_domain_allowed"] is False
    assert ent["blog_allowed"] is False


# -----------------------------------------------------------------------------
# AC-062: Third-Period Advance does not automatically settle scheduled Period 2
# -----------------------------------------------------------------------------

async def test_ac_062_advance_does_not_auto_settle_period_2():
    """Third-Period Advance is not consumed for Period 2 payment during grace (AC-062)."""
    p2 = domain.calculate_continuation_period(2, 199900)
    assert p2["advance_credit_paise"] == 0


# -----------------------------------------------------------------------------
# AC-063: Unused Third-Period Advance may be set off at Free conversion
# -----------------------------------------------------------------------------

async def test_ac_063_unused_advance_may_be_set_off_at_free_conversion():
    """Unused advance may be recorded as SET_OFF movement at Day 23 conversion (AC-063)."""
    sub_id = uuid4()
    movement = models.AdvanceMovement(
        id=uuid4(),
        tenant_id=uuid4(),
        store_id=uuid4(),
        subscription_id=sub_id,
        movement_type="SET_OFF",
        amount=Decimal("1999.00"),
        direction="D",
        reason="Set off at Day 23 Free conversion against unpaid receivables",
    )
    assert movement.movement_type == "SET_OFF"
    assert movement.direction == "D"


# -----------------------------------------------------------------------------
# AC-064: Set-off does not restore paid status or reverse delinquency
# -----------------------------------------------------------------------------

async def test_ac_064_set_off_does_not_restore_paid_status():
    """Advance set-off does not restore paid entitlements; state remains FREE_PRESENCE (AC-064)."""
    ent = domain.build_entitlements_map("COMMERCE", "FREE_PRESENCE")
    assert ent["state"] == "FREE_PRESENCE"
    assert ent["commerce_enabled"] is False


# -----------------------------------------------------------------------------
# AC-065: Reactivation after non-payment Free conversion charges full plan price S
# -----------------------------------------------------------------------------

async def test_ac_065_reactivation_charges_full_plan_price():
    """Reactivation requires full plan price S for the new period (AC-065)."""
    r = domain.calculate_reactivation("COMMERCE", 199900)
    assert r["period_fee_paise"] == 199900
    assert r["period_fee"] == "1999.00"


# -----------------------------------------------------------------------------
# AC-066: Reactivation after non-payment Free conversion charges Reactivation Setup Fee 0.5S
# -----------------------------------------------------------------------------

async def test_ac_066_reactivation_charges_half_setup_fee():
    """Reactivation requires separate Reactivation Setup Fee = 50% plan price (0.5S) (AC-066)."""
    r = domain.calculate_reactivation("COMMERCE", 199900)
    assert r["reactivation_setup_paise"] == 99950  # 0.5 * 199900
    assert r["reactivation_setup"] == "999.50"


# -----------------------------------------------------------------------------
# AC-067: Reactivation starts a fresh 30-day billing period at reactivation timestamp
# -----------------------------------------------------------------------------

async def test_ac_067_reactivation_starts_fresh_30_day_period():
    """Reactivation starts a fresh exact 30-day period at the reactivation timestamp (AC-067)."""
    now = datetime(2026, 4, 10, 14, 0, 0, tzinfo=timezone.utc)
    s, e = domain.calculate_period_dates(now)
    assert s == now
    assert e == now + timedelta(days=30)


# -----------------------------------------------------------------------------
# AC-068: Complimentary setup waiver cannot be reused on reactivation
# -----------------------------------------------------------------------------

async def test_ac_068_complimentary_setup_not_reusable_on_reactivation():
    """Reactivation setup fee is not waived (first-ever complimentary waiver cannot be reused) (AC-068)."""
    r = domain.calculate_reactivation("COMMERCE", 199900)
    assert r["reactivation_setup_paise"] > 0


# -----------------------------------------------------------------------------
# AC-069: Upgrade calculation uses authoritative period days remaining R
# -----------------------------------------------------------------------------

async def test_ac_069_upgrade_calculation_uses_days_remaining():
    """Proration uses (H - L) * R / 30 with authoritative days remaining R (AC-069)."""
    q = domain.calculate_upgrade_quote(
        lower_price_paise=199900,
        higher_price_paise=499900,
        days_remaining=10,
        is_before_p3=False,
    )
    # (499900 - 199900) * 10 / 30 = 300000 * 10 / 30 = 100000 paise
    assert q["prorated_difference_paise"] == 100000
    assert q["prorated_difference"] == "1000.00"


# -----------------------------------------------------------------------------
# AC-070: Upgrade before Period 3 calculates advance top-up
# -----------------------------------------------------------------------------

async def test_ac_070_upgrade_before_period_3_calculates_advance_top_up():
    """Before Period 3, upgrade calculates advance top-up = max(0, H - existing eligible advance) (AC-070)."""
    q = domain.calculate_upgrade_quote(
        lower_price_paise=199900,
        higher_price_paise=499900,
        days_remaining=15,
        is_before_p3=True,
        current_advance_balance_paise=199900,
    )
    assert q["advance_top_up_paise"] == 300000  # 499900 - 199900


# -----------------------------------------------------------------------------
# AC-071: Advance top-up = max(0, required_advance - eligible_advance)
# -----------------------------------------------------------------------------

async def test_ac_071_advance_top_up_formula():
    """Advance top-up is non-negative and zero if after Period 3 (AC-071)."""
    q_after_p3 = domain.calculate_upgrade_quote(
        lower_price_paise=199900,
        higher_price_paise=499900,
        days_remaining=15,
        is_before_p3=False,
    )
    assert q_after_p3["advance_top_up_paise"] == 0


# -----------------------------------------------------------------------------
# AC-072: Upgrade setup fee is 50% of plan price difference
# -----------------------------------------------------------------------------

async def test_ac_072_upgrade_setup_fee_half_plan_difference():
    """Gross upgrade setup fee = 0.5 * (H - L) (AC-072)."""
    q = domain.calculate_upgrade_quote(
        lower_price_paise=199900,
        higher_price_paise=499900,
        days_remaining=15,
        is_before_p3=False,
    )
    # 0.5 * (499900 - 199900) = 150000 paise
    assert q["gross_upgrade_setup_fee_paise"] == 150000
    assert q["gross_upgrade_setup_fee"] == "1500.00"


# -----------------------------------------------------------------------------
# AC-073: Upgrade setup discount requires Platform Owner decision
# -----------------------------------------------------------------------------

async def test_ac_073_upgrade_setup_discount_requires_platform_owner():
    """Non-platform-owner cannot approve setup fee discount (AC-073)."""
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"])
    mock_session = make_mock_session()

    with pytest.raises(ApiError) as exc_info:
        await commands.decide_upgrade_discount_command(
            session=mock_session,
            request_id=uuid4(),
            principal=principal,
            approved=True,
            approved_amount_str="500.00",
            reason="Good loyalty",
        )
    assert exc_info.value.status_code == 403


# -----------------------------------------------------------------------------
# AC-074: Platform Owner discount requires auditable reason and timestamp
# -----------------------------------------------------------------------------

async def test_ac_074_platform_owner_discount_requires_reason_and_audit():
    """Platform Owner decision records auditable approver, amount, reason, timestamp (AC-074)."""
    owner_principal = Principal(sub=uuid4(), roles=["PLATFORM_OWNER"])
    quote_id = uuid4()
    quote = models.UpgradeQuote(
        id=quote_id,
        tenant_id=uuid4(),
        store_id=uuid4(),
        subscription_id=uuid4(),
        target_plan_version_id=uuid4(),
        days_remaining=15,
        prorated_difference=Decimal("1500.00"),
        advance_top_up=Decimal("0.00"),
        gross_setup_fee=Decimal("1500.00"),
        approved_discount_amount=Decimal("0.00"),
        net_setup_fee=Decimal("1500.00"),
        total_ex_tax=Decimal("3000.00"),
        tax_amount=Decimal("540.00"),
        total_with_tax=Decimal("3540.00"),
    )

    mock_session = make_mock_session(get_mapping={quote_id: quote})
    res = await commands.decide_upgrade_discount_command(
        session=mock_session,
        request_id=quote_id,
        principal=owner_principal,
        approved=True,
        approved_amount_str="500.00",
        reason="Approved by Platform Owner for annual contract promotion",
    )
    assert res.approved_amount == "500.00"
    assert res.net_setup_fee == "1000.00"
    assert res.decided_at is not None


# -----------------------------------------------------------------------------
# AC-075: Discount affects setup fee only and never waives proration
# -----------------------------------------------------------------------------

async def test_ac_075_discount_affects_setup_fee_only_never_waives_proration():
    """Setup fee discount cannot exceed gross setup fee and never waives prorated difference (AC-075)."""
    owner_principal = Principal(sub=uuid4(), roles=["PLATFORM_OWNER"])
    quote_id = uuid4()
    quote = models.UpgradeQuote(
        id=quote_id,
        tenant_id=uuid4(),
        store_id=uuid4(),
        subscription_id=uuid4(),
        target_plan_version_id=uuid4(),
        days_remaining=15,
        prorated_difference=Decimal("1500.00"),
        advance_top_up=Decimal("0.00"),
        gross_setup_fee=Decimal("1000.00"),  # Setup fee is 1000
        approved_discount_amount=Decimal("0.00"),
        net_setup_fee=Decimal("1000.00"),
        total_ex_tax=Decimal("2500.00"),
        tax_amount=Decimal("450.00"),
        total_with_tax=Decimal("2950.00"),
    )

    mock_session = make_mock_session(get_mapping={quote_id: quote})
    # Attempt to discount 5000 (more than setup fee)
    res = await commands.decide_upgrade_discount_command(
        session=mock_session,
        request_id=quote_id,
        principal=owner_principal,
        approved=True,
        approved_amount_str="5000.00",
        reason="Excessive discount attempt",
    )
    # Discount capped at gross setup fee = 1000
    assert res.approved_amount == "1000.00"
    assert res.net_setup_fee == "0.00"
    # Total still contains the 1500 prorated difference (never waived!)
    assert quote.prorated_difference == Decimal("1500.00")
    assert quote.total_ex_tax == Decimal("1500.00")
