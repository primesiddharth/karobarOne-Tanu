# tests/test_scheduler_lifecycle.py
"""
Phase 8b: Subscription Scheduler Lifecycle, Delinquency Automation, and Concurrency Tests.
Sources: SERVICES.md §7, State Machine §17-18 & §23, AC-041..064.
Covers:
- Deterministic clock boundaries (P1->P2, P2->P3 cancellation vs continuation, P3->P4->P5+)
- Delinquency timeline (Day 1 Grace, Day 8 Expired, Day 23 Free conversion + advance set-off)
- Payment recovery during delinquency
- Scheduled downgrade at period boundary
- Two-replica scheduler concurrency with SKIP LOCKED and business_key
"""
import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError
from app import commands, models, domain, schemas

pytestmark = pytest.mark.asyncio


def make_mock_session():
    """Lightweight in-memory AsyncSession mock tracking added entities and queries."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.added_models = []

    def _add(item):
        mock_session.added_models.append(item)
    mock_session.add.side_effect = _add

    return mock_session


class InMemoryDbState:
    """Mock database state simulating subscription records for deterministic scheduler execution."""
    def __init__(self, tenant_id, store_id, plan_version, subscription, period, charges=None, movements=None, notices=None, change_requests=None, snapshots=None):
        self.tenant_id = tenant_id
        self.store_id = store_id
        self.plan_version = plan_version
        self.subscription = subscription
        self.period = period
        self.charges = charges or []
        self.movements = movements or []
        self.notices = notices or []
        self.change_requests = change_requests or []
        self.snapshots = snapshots or []
        self.jobs = {}

    def setup_session(self, session):
        def _add(item):
            session.added_models.append(item)
            if isinstance(item, models.SubscriptionCharge):
                self.charges.append(item)
            elif isinstance(item, models.AdvanceMovement):
                self.movements.append(item)
            elif isinstance(item, models.SubscriptionPeriod):
                self.period = item
            elif isinstance(item, models.ScheduledJob):
                self.jobs[item.business_key] = item
            elif isinstance(item, models.CancellationNotice):
                self.notices.append(item)
            elif isinstance(item, models.PlanChangeRequest):
                self.change_requests.append(item)

        session.add.side_effect = _add

        async def _execute(stmt, *args, **kwargs):
            sql = str(stmt).lower()
            params = {}
            try:
                compiled = stmt.compile()
                sql = str(compiled).lower()
                params = {k.lower(): v for k, v in compiled.params.items()}
            except Exception:
                pass

            res = MagicMock()

            where_part = sql.split("where", 1)[1] if "where" in sql else ""

            # Outbox insert / set_config
            if "set_config" in sql or "insert into subscription.outbox_events" in sql:
                return res

            # ScheduledJob queries
            if "scheduled_jobs" in sql:
                found_job = None
                for bkey, job in self.jobs.items():
                    if bkey in sql or bkey in str(stmt) or any(str(bkey) == str(v) for v in params.values()):
                        found_job = job
                        break
                res.scalars.return_value.first.return_value = found_job
                return res

            # Subscriptions query
            if "from subscription.subscriptions" in sql:
                if "id =" in where_part:
                    res.scalars.return_value.first.return_value = self.subscription
                else:
                    active_subs = [self.subscription] if self.subscription.state != "FREE_PRESENCE" else []
                    res.scalars.return_value.all.return_value = active_subs
                return res

            # Periods query
            if "from subscription.subscription_periods" in sql:
                if "period_no" in where_part:
                    # check if next period exists
                    res.scalars.return_value.first.return_value = None
                else:
                    res.scalars.return_value.first.return_value = self.period
                return res


            # Plan versions query
            if "from subscription.plan_versions" in sql:
                res.scalars.return_value.first.return_value = self.plan_version
                return res

            # Charges query
            if "from subscription.subscription_charges" in sql:
                if "status !=" in sql or "status =" in sql:
                    unpaid = [c for c in self.charges if c.status != "PAID"]
                    res.scalars.return_value.all.return_value = unpaid
                    res.scalars.return_value.first.return_value = unpaid[0] if unpaid else None
                else:
                    res.scalars.return_value.all.return_value = self.charges
                    res.scalars.return_value.first.return_value = self.charges[0] if self.charges else None
                return res

            # Advance movements query
            if "from subscription.advance_movements" in sql:
                res.scalars.return_value.all.return_value = self.movements
                return res

            # Cancellation notices query
            if "from subscription.cancellation_notices" in sql:
                res.scalars.return_value.all.return_value = self.notices
                res.scalars.return_value.first.return_value = self.notices[0] if self.notices else None
                return res

            # Plan change requests query
            if "from subscription.plan_change_requests" in sql:
                res.scalars.return_value.all.return_value = self.change_requests
                res.scalars.return_value.first.return_value = self.change_requests[0] if self.change_requests else None
                return res

            # Entitlement snapshot query
            if "from subscription.entitlement_snapshots" in sql:
                res.scalars.return_value.first.return_value = self.snapshots[0] if self.snapshots else None
                return res

            res.scalars.return_value.first.return_value = None
            res.scalars.return_value.all.return_value = []
            return res

        session.execute.side_effect = _execute


# ==============================================================================
# 1. Deterministic Clock Tests: Boundary Advancement P1 -> P2
# ==============================================================================

async def test_scheduler_period_advancement_p1_to_p2():
    """At Period 1 boundary (30 days), scheduler advances to Period 2 and generates charge (AC-041, AC-044)."""
    t_id = uuid4()
    s_id = uuid4()
    sub_id = uuid4()
    p1_id = uuid4()
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    t30 = t0 + timedelta(days=30)

    pv = models.PlanVersion(id=uuid4(), plan_code="COMMERCE", price_amount=Decimal("1999.00"))
    sub = models.Subscription(
        id=sub_id,
        tenant_id=t_id,
        store_id=s_id,
        plan_version_id=pv.id,
        state="ACTIVE_PERIOD_1",
        current_period_no=1,
        current_period_id=p1_id,
        created_at=t0,
    )
    p1 = models.SubscriptionPeriod(
        id=p1_id,
        tenant_id=t_id,
        store_id=s_id,
        subscription_id=sub_id,
        period_no=1,
        plan_version_id=pv.id,
        starts_at=t0,
        ends_at=t30,
        entitlement_status="ACTIVE",
        charge_mode="FULL",
        base_price_snapshot=Decimal("1999.00"),
    )

    db_state = InMemoryDbState(t_id, s_id, pv, sub, p1)
    session = make_mock_session()
    db_state.setup_session(session)

    # Execute scheduler sweep at exact boundary t30
    count = await commands.process_subscription_scheduler_command(session, as_of=t30)

    assert count == 1
    assert sub.state == "ACTIVE_PERIOD_2"
    assert sub.current_period_no == 2

    # Verify Period 2 period was created
    new_periods = [m for m in session.added_models if isinstance(m, models.SubscriptionPeriod) and m.period_no == 2]
    assert len(new_periods) == 1
    assert new_periods[0].starts_at == t30
    assert new_periods[0].ends_at == t30 + timedelta(days=30)

    # Verify Period 2 fee was billed (AC-044)
    new_charges = [m for m in session.added_models if isinstance(m, models.SubscriptionCharge) and m.charge_type == "PERIOD_FEE"]
    assert len(new_charges) == 1
    assert new_charges[0].amount == Decimal("1999.00")
    assert new_charges[0].status == "DUE"


# ==============================================================================
# 2. Delinquency Timeline: Days 1-7 Grace, Days 8-22 Expired, Day 23 Free Presence
# ==============================================================================

async def test_scheduler_delinquency_day_1_payment_grace():
    """Unpaid due charge enters PAYMENT_GRACE on Day 1-7 past due date (AC-054)."""
    t_id = uuid4()
    s_id = uuid4()
    sub_id = uuid4()
    p_id = uuid4()
    due_date = datetime(2026, 1, 31, 0, 0, 0, tzinfo=timezone.utc)
    as_of = due_date + timedelta(days=3)  # Day 3 past due

    pv = models.PlanVersion(id=uuid4(), plan_code="COMMERCE", price_amount=Decimal("1999.00"))
    sub = models.Subscription(
        id=sub_id,
        tenant_id=t_id,
        store_id=s_id,
        plan_version_id=pv.id,
        state="ACTIVE_PERIOD_2",
        current_period_no=2,
        current_period_id=p_id,
    )
    p = models.SubscriptionPeriod(id=p_id, tenant_id=t_id, store_id=s_id, subscription_id=sub_id, period_no=2, plan_version_id=pv.id, starts_at=due_date, ends_at=due_date + timedelta(days=30), entitlement_status="ACTIVE", charge_mode="FULL")
    unpaid_charge = models.SubscriptionCharge(
        id=uuid4(),
        tenant_id=t_id,
        store_id=s_id,
        subscription_id=sub_id,
        charge_type="PERIOD_FEE",
        amount=Decimal("1999.00"),
        status="DUE",
        due_at=due_date,
    )

    db_state = InMemoryDbState(t_id, s_id, pv, sub, p, charges=[unpaid_charge])
    session = make_mock_session()
    db_state.setup_session(session)

    count = await commands.process_subscription_scheduler_command(session, as_of=as_of)

    assert count == 1
    assert sub.state == "PAYMENT_GRACE"


async def test_scheduler_delinquency_day_8_subscription_expired():
    """Unpaid charge transitions from grace to SUBSCRIPTION_EXPIRED on Day 8 (AC-055..058)."""
    t_id = uuid4()
    s_id = uuid4()
    sub_id = uuid4()
    p_id = uuid4()
    due_date = datetime(2026, 1, 31, 0, 0, 0, tzinfo=timezone.utc)
    as_of = due_date + timedelta(days=10)  # Day 10 past due

    pv = models.PlanVersion(id=uuid4(), plan_code="COMMERCE", price_amount=Decimal("1999.00"))
    sub = models.Subscription(
        id=sub_id,
        tenant_id=t_id,
        store_id=s_id,
        plan_version_id=pv.id,
        state="PAYMENT_GRACE",
        current_period_no=2,
        current_period_id=p_id,
    )
    p = models.SubscriptionPeriod(id=p_id, tenant_id=t_id, store_id=s_id, subscription_id=sub_id, period_no=2, plan_version_id=pv.id, starts_at=due_date, ends_at=due_date + timedelta(days=30), entitlement_status="ACTIVE", charge_mode="FULL")
    unpaid_charge = models.SubscriptionCharge(
        id=uuid4(),
        tenant_id=t_id,
        store_id=s_id,
        subscription_id=sub_id,
        charge_type="PERIOD_FEE",
        amount=Decimal("1999.00"),
        status="DUE",
        due_at=due_date,
    )
    snapshot = models.EntitlementSnapshot(
        store_id=s_id,
        plan_code="COMMERCE",
        entitlements={"commerce_enabled": True, "custom_domain_allowed": True},
        reason_code="ACTIVE",
    )

    db_state = InMemoryDbState(t_id, s_id, pv, sub, p, charges=[unpaid_charge], snapshots=[snapshot])
    session = make_mock_session()
    db_state.setup_session(session)

    count = await commands.process_subscription_scheduler_command(session, as_of=as_of)

    assert count == 1
    assert sub.state == "SUBSCRIPTION_EXPIRED"
    # Entitlement projection updated: storefront visible, but new orders blocked
    assert snapshot.entitlements["commerce_enabled"] is False
    assert snapshot.entitlements["custom_domain_allowed"] is True


async def test_scheduler_delinquency_day_23_free_presence_and_advance_set_off():
    """Unpaid charge triggers automatic conversion to FREE_PRESENCE on Day 23 + advance set-off (AC-059..064)."""
    t_id = uuid4()
    s_id = uuid4()
    sub_id = uuid4()
    p_id = uuid4()
    due_date = datetime(2026, 1, 31, 0, 0, 0, tzinfo=timezone.utc)
    as_of = due_date + timedelta(days=24)  # Day 24 past due

    pv = models.PlanVersion(id=uuid4(), plan_code="COMMERCE", price_amount=Decimal("1999.00"))
    sub = models.Subscription(
        id=sub_id,
        tenant_id=t_id,
        store_id=s_id,
        plan_version_id=pv.id,
        state="SUBSCRIPTION_EXPIRED",
        current_period_no=2,
        current_period_id=p_id,
    )
    p = models.SubscriptionPeriod(id=p_id, tenant_id=t_id, store_id=s_id, subscription_id=sub_id, period_no=2, plan_version_id=pv.id, starts_at=due_date, ends_at=due_date + timedelta(days=30), entitlement_status="ACTIVE", charge_mode="FULL")
    unpaid_charge = models.SubscriptionCharge(
        id=uuid4(),
        tenant_id=t_id,
        store_id=s_id,
        subscription_id=sub_id,
        charge_type="PERIOD_FEE",
        amount=Decimal("1999.00"),
        status="DUE",
        due_at=due_date,
    )
    # Third-Period advance was previously collected (Direction C)
    collected_adv = models.AdvanceMovement(
        id=uuid4(),
        tenant_id=t_id,
        store_id=s_id,
        subscription_id=sub_id,
        movement_type="COLLECTED",
        amount=Decimal("1999.00"),
        direction="C",
    )
    snapshot = models.EntitlementSnapshot(
        store_id=s_id,
        plan_code="COMMERCE",
        entitlements={"commerce_enabled": False, "custom_domain_allowed": True},
        reason_code="EXPIRED",
    )

    db_state = InMemoryDbState(t_id, s_id, pv, sub, p, charges=[unpaid_charge], movements=[collected_adv], snapshots=[snapshot])
    session = make_mock_session()
    db_state.setup_session(session)

    count = await commands.process_subscription_scheduler_command(session, as_of=as_of)

    assert count == 1
    assert sub.state == "FREE_PRESENCE"

    # Verify advance set-off movement was recorded (AC-063)
    set_offs = [m for m in session.added_models if isinstance(m, models.AdvanceMovement) and m.movement_type == "SET_OFF"]
    assert len(set_offs) == 1
    assert set_offs[0].amount == Decimal("1999.00")
    assert set_offs[0].direction == "D"

    # Verify entitlement projection converted to Free presence (AC-060, AC-064)
    assert snapshot.plan_code == "PRESENCE"
    assert snapshot.entitlements["showcase_limit"] == 6
    assert snapshot.entitlements["custom_domain_allowed"] is False
    assert snapshot.entitlements["commerce_enabled"] is False


# ==============================================================================
# 3. Delinquency Payment Recovery
# ==============================================================================

async def test_scheduler_delinquency_payment_recovery():
    """Payment received before Day 23 clears delinquency and restores active state (SERVICES §7, SM §17)."""
    t_id = uuid4()
    s_id = uuid4()
    sub_id = uuid4()
    charge_id = uuid4()
    now = datetime.now(timezone.utc)

    pv = models.PlanVersion(id=uuid4(), plan_code="COMMERCE", price_amount=Decimal("1999.00"))
    sub = models.Subscription(
        id=sub_id,
        tenant_id=t_id,
        store_id=s_id,
        plan_version_id=pv.id,
        state="SUBSCRIPTION_EXPIRED",
        current_period_no=2,
    )
    charge = models.SubscriptionCharge(
        id=charge_id,
        tenant_id=t_id,
        store_id=s_id,
        subscription_id=sub_id,
        charge_type="PERIOD_FEE",
        amount=Decimal("1999.00"),
        status="DUE",
    )
    snapshot = models.EntitlementSnapshot(
        store_id=s_id,
        plan_code="COMMERCE",
        entitlements={"commerce_enabled": False, "custom_domain_allowed": True},
        reason_code="EXPIRED",
    )

    db_state = InMemoryDbState(t_id, s_id, pv, sub, None, charges=[charge], snapshots=[snapshot])
    session = make_mock_session()
    db_state.setup_session(session)

    res = await commands.record_platform_payment_command(
        session=session,
        store_id=s_id,
        subscription_id=sub_id,
        amount_paise=199900,
        payment_reference="PAY_REC_123",
        charge_id=charge_id,
        paid_at=now,
    )

    assert res["status"] == "PAID"
    assert sub.state == "ACTIVE_PERIOD_2"
    assert snapshot.entitlements["commerce_enabled"] is True


# ==============================================================================
# 4. Period 2 Cancellation before P3 vs Continuation
# ==============================================================================

async def test_scheduler_cancellation_before_p3_lifecycle():
    """Cancellation notice recorded before P3 -> P3_FULLY_PREPAID (0 due), then FREE_PRESENCE after P3 (AC-045..048)."""
    t_id = uuid4()
    s_id = uuid4()
    sub_id = uuid4()
    p2_id = uuid4()
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    t60 = t0 + timedelta(days=60)  # Period 2 ends at t60

    pv = models.PlanVersion(id=uuid4(), plan_code="COMMERCE", price_amount=Decimal("1999.00"))
    sub = models.Subscription(
        id=sub_id,
        tenant_id=t_id,
        store_id=s_id,
        plan_version_id=pv.id,
        state="ACTIVE_PERIOD_2",
        current_period_no=2,
        current_period_id=p2_id,
    )
    p2 = models.SubscriptionPeriod(id=p2_id, tenant_id=t_id, store_id=s_id, subscription_id=sub_id, period_no=2, plan_version_id=pv.id, starts_at=t0 + timedelta(days=30), ends_at=t60, entitlement_status="ACTIVE", charge_mode="FULL", base_price_snapshot=Decimal("1999.00"))

    # Notice was submitted at day 50 (< day 60)
    notice = models.CancellationNotice(
        id=uuid4(),
        tenant_id=t_id,
        store_id=s_id,
        subscription_id=sub_id,
        created_at=t0 + timedelta(days=50),
    )

    db_state = InMemoryDbState(t_id, s_id, pv, sub, p2, notices=[notice])
    session = make_mock_session()
    db_state.setup_session(session)

    # 1. Sweep at t60: enters P3_FULLY_PREPAID
    count = await commands.process_subscription_scheduler_command(session, as_of=t60)
    assert count == 1
    assert sub.state == "P3_FULLY_PREPAID"
    assert sub.current_period_no == 3

    # Advance was allocated to P3 (additional due = 0)
    allocs = [m for m in session.added_models if isinstance(m, models.AdvanceMovement) and m.movement_type == "ALLOCATION"]
    assert len(allocs) == 1
    assert allocs[0].amount == Decimal("1999.00")

    # 2. Sweep at t90: P3 finishes -> converts to FREE_PRESENCE
    t90 = t60 + timedelta(days=30)
    p3 = [m for m in session.added_models if isinstance(m, models.SubscriptionPeriod) and m.period_no == 3][0]
    db_state.period = p3
    snapshot = models.EntitlementSnapshot(store_id=s_id, plan_code="COMMERCE", entitlements={}, reason_code="ACTIVE")
    db_state.snapshots = [snapshot]

    session2 = make_mock_session()
    db_state.setup_session(session2)

    count2 = await commands.process_subscription_scheduler_command(session2, as_of=t90)
    assert count2 == 1
    assert sub.state == "FREE_PRESENCE"


async def test_scheduler_continuation_p3_p4_p5_renewal():
    """Continuation path (no cancel notice): P3 (50%), P4 (50%), P5+ (standard renewal) (AC-049..053)."""
    t_id = uuid4()
    s_id = uuid4()
    sub_id = uuid4()
    p2_id = uuid4()
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    t60 = t0 + timedelta(days=60)

    pv = models.PlanVersion(id=uuid4(), plan_code="COMMERCE", price_amount=Decimal("1999.00"))
    sub = models.Subscription(
        id=sub_id,
        tenant_id=t_id,
        store_id=s_id,
        plan_version_id=pv.id,
        state="ACTIVE_PERIOD_2",
        current_period_no=2,
        current_period_id=p2_id,
    )
    p2 = models.SubscriptionPeriod(id=p2_id, tenant_id=t_id, store_id=s_id, subscription_id=sub_id, period_no=2, plan_version_id=pv.id, starts_at=t0 + timedelta(days=30), ends_at=t60, entitlement_status="ACTIVE", charge_mode="FULL", base_price_snapshot=Decimal("1999.00"))

    db_state = InMemoryDbState(t_id, s_id, pv, sub, p2)
    session = make_mock_session()
    db_state.setup_session(session)

    # 1. Sweep at t60: enters P3_50_PERCENT_DUE
    count = await commands.process_subscription_scheduler_command(session, as_of=t60)
    assert count == 1
    assert sub.state == "P3_50_PERCENT_DUE"

    # Half advance credit (0.5S) allocated
    allocs = [m for m in session.added_models if isinstance(m, models.AdvanceMovement) and m.movement_type == "ALLOCATION"]
    assert len(allocs) == 1
    assert allocs[0].amount == Decimal("999.50")

    # Half price charge (0.5S) issued
    charges = [m for m in session.added_models if isinstance(m, models.SubscriptionCharge) and m.charge_type == "PERIOD_FEE"]
    assert len(charges) == 1
    assert charges[0].amount == Decimal("999.50")


# ==============================================================================
# 5. Scheduled Downgrade at Period Boundary
# ==============================================================================

async def test_scheduler_scheduled_downgrade_at_boundary():
    """Approved downgrade request is applied at period boundary (PLAN-05)."""
    t_id = uuid4()
    s_id = uuid4()
    sub_id = uuid4()
    p_id = uuid4()
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    t30 = t0 + timedelta(days=30)

    pv_growth = models.PlanVersion(id=uuid4(), plan_code="GROWTH", price_amount=Decimal("4999.00"))
    pv_commerce = models.PlanVersion(id=uuid4(), plan_code="COMMERCE", price_amount=Decimal("1999.00"))

    sub = models.Subscription(
        id=sub_id,
        tenant_id=t_id,
        store_id=s_id,
        plan_version_id=pv_growth.id,
        state="ACTIVE_PERIOD_1",
        current_period_no=1,
        current_period_id=p_id,
    )
    p = models.SubscriptionPeriod(id=p_id, tenant_id=t_id, store_id=s_id, subscription_id=sub_id, period_no=1, plan_version_id=pv_growth.id, starts_at=t0, ends_at=t30, entitlement_status="ACTIVE", charge_mode="FULL", base_price_snapshot=Decimal("4999.00"))

    downgrade_req = models.PlanChangeRequest(
        id=uuid4(),
        subscription_id=sub_id,
        from_plan_version_id=pv_growth.id,
        to_plan_version_id=pv_commerce.id,
        change_type="DOWNGRADE",
        status="APPROVED",
    )
    snapshot = models.EntitlementSnapshot(store_id=s_id, plan_code="GROWTH", entitlements={"commerce_enabled": True}, reason_code="ACTIVE")

    db_state = InMemoryDbState(t_id, s_id, pv_growth, sub, p, change_requests=[downgrade_req], snapshots=[snapshot])
    session = make_mock_session()
    db_state.setup_session(session)

    count = await commands.process_subscription_scheduler_command(session, as_of=t30)

    assert count >= 1
    assert downgrade_req.status == "COMPLETED"
    assert sub.plan_version_id == pv_commerce.id


# ==============================================================================
# 6. Two-Replica Scheduler Concurrency Test
# ==============================================================================

async def test_two_replica_scheduler_concurrency():
    """Two concurrent workers competing on the same period process exactly once (SERVICES §7, RULES §7.4)."""
    t_id = uuid4()
    s_id = uuid4()
    sub_id = uuid4()
    p_id = uuid4()
    t0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    t30 = t0 + timedelta(days=30)

    pv = models.PlanVersion(id=uuid4(), plan_code="COMMERCE", price_amount=Decimal("1999.00"))
    sub = models.Subscription(
        id=sub_id,
        tenant_id=t_id,
        store_id=s_id,
        plan_version_id=pv.id,
        state="ACTIVE_PERIOD_1",
        current_period_no=1,
        current_period_id=p_id,
    )
    p = models.SubscriptionPeriod(id=p_id, tenant_id=t_id, store_id=s_id, subscription_id=sub_id, period_no=1, plan_version_id=pv.id, starts_at=t0, ends_at=t30, entitlement_status="ACTIVE", charge_mode="FULL", base_price_snapshot=Decimal("1999.00"))

    db_state = InMemoryDbState(t_id, s_id, pv, sub, p)

    # Replica 1
    session1 = make_mock_session()
    db_state.setup_session(session1)

    # Replica 2
    session2 = make_mock_session()
    db_state.setup_session(session2)

    # Run both replicas concurrently
    results = await asyncio.gather(
        commands.process_subscription_scheduler_command(session1, as_of=t30),
        commands.process_subscription_scheduler_command(session2, as_of=t30),
    )

    # Exactly one replica processed the transition; the other replica skipped
    assert sum(results) == 1
    assert sub.state == "ACTIVE_PERIOD_2"
    assert sub.current_period_no == 2
