# app/commands.py
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
import structlog

from libs.platform_contracts.errors import ApiError, ErrorCode
from libs.platform_contracts.tokens import Principal
from . import models, domain, schemas
from .events import add_event
from .db import set_rls_context
from .clients import tenant_client

logger = structlog.get_logger("subscription.commands")


# ------------------------------------------------------------------------------
# SUB-001: List Plans
# ------------------------------------------------------------------------------

async def list_active_plans_command(session: AsyncSession) -> schemas.PlansListResponse:
    """Lists active plan offerings with feature limits (SUB-001)."""
    stmt = (
        select(models.PlanVersion)
        .where(models.PlanVersion.is_active == True)  # noqa: E712
        .order_by(models.PlanVersion.price_amount.asc())
    )
    res = await session.execute(stmt)
    plan_versions = res.scalars().all()

    plan_dtos = []
    for pv in plan_versions:
        ent_stmt = select(models.PlanEntitlement).where(models.PlanEntitlement.plan_version_id == pv.id)
        ent_res = await session.execute(ent_stmt)
        entitlements = ent_res.scalars().all()

        ent_dtos = [
            schemas.PlanEntitlementDto(
                entitlement_code=e.entitlement_code,
                hard_limit=e.hard_limit,
                technical_limit=e.technical_limit,
                value=e.value_json or {},
            )
            for e in entitlements
        ]

        price_paise = int(Decimal(str(pv.price_amount)) * 100)
        plan_dtos.append(
            schemas.PlanDto(
                plan_code=pv.plan_code,
                version_no=pv.version_no,
                price_amount=str(pv.price_amount),
                price_paise=price_paise,
                period_days=pv.period_days,
                commission_rate=float(pv.commission_rate),
                entitlements=ent_dtos,
            )
        )

    return schemas.PlansListResponse(plans=plan_dtos)


# ------------------------------------------------------------------------------
# SUB-002: First Paid Activation Quote
# ------------------------------------------------------------------------------

async def create_activation_quote_command(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    plan_code: str,
    gstin_id: UUID | None = None,
    correlation_id: UUID | None = None,
) -> schemas.ActivationQuoteResponse:
    """Calculates first paid activation quote (SUB-002, AC-042, AC-043)."""
    # 1. Authorization: Principal must be STORE_OWNER for this store or PLATFORM admin
    is_admin = principal.has_role("PLATFORM_STAFF") or principal.has_role("PLATFORM_OWNER")
    if not is_admin:
        if not (principal.has_role("STORE_OWNER") and store_id in principal.store_ids):
            raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Store access denied", status_code=403)

    tenant_id = principal.tenant_ids[0] if principal.tenant_ids else uuid4()
    await set_rls_context(session, tenant_id=tenant_id, store_id=store_id, is_platform_admin=is_admin)

    # 2. Paid commerce activation requires a verified GSTIN (AC-008, AC-009)
    if plan_code.upper() != "PRESENCE":
        if not gstin_id:
            raise ApiError(ErrorCode.GSTIN_REQUIRED, "Paid plan activation requires a verified GSTIN", status_code=422)
        is_gstin_valid = await tenant_client.verify_store_gstin(tenant_id, store_id, gstin_id)
        if not is_gstin_valid:
            raise ApiError(ErrorCode.GSTIN_REQUIRED, "GSTIN could not be verified for store", status_code=422)

    # 3. Fetch plan version
    stmt = (
        select(models.PlanVersion)
        .where(
            models.PlanVersion.plan_code == plan_code.upper(),
            models.PlanVersion.is_active == True,  # noqa: E712
        )
        .order_by(models.PlanVersion.version_no.desc())
    )
    res = await session.execute(stmt)
    plan_version = res.scalars().first()
    if not plan_version:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Plan {plan_code} not found or inactive", status_code=404)

    # 4. Check whether store already has an active or previous paid subscription
    sub_stmt = select(models.Subscription).where(models.Subscription.store_id == store_id)
    sub_res = await session.execute(sub_stmt)
    existing_sub = sub_res.scalars().first()

    is_first_paid = True
    if existing_sub and existing_sub.activation_sequence > 0:
        is_first_paid = False

    plan_price_paise = int(Decimal(str(plan_version.price_amount)) * 100)
    calc = domain.calculate_initial_activation(
        plan_code=plan_code.upper(),
        plan_price_paise=plan_price_paise,
        is_first_paid_activation=is_first_paid,
        gst_rate=Decimal("0.18"),
    )

    quote_id = uuid4()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=24)

    # Emit outbox event
    await add_event(
        session=session,
        event_type="subscription.activation-quote-created.v1",
        aggregate_type="subscription",
        aggregate_id=quote_id,
        payload={
            "quote_id": str(quote_id),
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
            "plan_code": plan_code.upper(),
            "is_first_paid_activation": is_first_paid,
            "period_1_paise": calc["period_1"]["amount_paise"],
            "advance_paise": calc["third_period_advance"]["amount_paise"],
            "setup_fee_paise": calc["setup_fee"]["amount_paise"],
            "total_paise": calc["total"]["amount_paise"],
            "expires_at": expires_at.isoformat(),
        },
        topic="subscription.lifecycle",
        tenant_id=tenant_id,
        store_id=store_id,
        correlation_id=correlation_id,
    )

    return schemas.ActivationQuoteResponse(
        quote_id=quote_id,
        plan_code=plan_code.upper(),
        period_1=schemas.AmountComponentDto(**calc["period_1"]),
        third_period_advance=schemas.AmountComponentDto(**calc["third_period_advance"]),
        setup_fee=schemas.SetupFeeComponentDto(**calc["setup_fee"]),
        gst=schemas.GstComponentDto(**calc["gst"]),
        total=schemas.TotalComponentDto(**calc["total"]),
        expires_at=expires_at,
    )


# ------------------------------------------------------------------------------
# SUB-003: Activate Subscription
# ------------------------------------------------------------------------------

async def activate_subscription_command(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    plan_code: str,
    quote_id: UUID | None = None,
    gstin_id: UUID | None = None,
    payment_reference: str | None = None,
    correlation_id: UUID | None = None,
) -> schemas.ActivateSubscriptionResponse:
    """Activates paid subscription after verified payment receipt (SUB-003, AC-041, AC-042, AC-043)."""
    is_admin = principal.has_role("PLATFORM_STAFF") or principal.has_role("PLATFORM_OWNER")
    if not is_admin:
        if not (principal.has_role("STORE_OWNER") and store_id in principal.store_ids):
            raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Store access denied", status_code=403)

    tenant_id = principal.tenant_ids[0] if principal.tenant_ids else uuid4()
    await set_rls_context(session, tenant_id=tenant_id, store_id=store_id, is_platform_admin=is_admin)

    # 1. Paid activation requires a verified GSTIN (AC-008)
    if plan_code.upper() != "PRESENCE":
        if not gstin_id:
            raise ApiError(ErrorCode.GSTIN_REQUIRED, "Paid plan activation requires a verified GSTIN", status_code=422)

    # 2. Fetch plan version
    stmt = (
        select(models.PlanVersion)
        .where(
            models.PlanVersion.plan_code == plan_code.upper(),
            models.PlanVersion.is_active == True,  # noqa: E712
        )
        .order_by(models.PlanVersion.version_no.desc())
    )
    res = await session.execute(stmt)
    plan_version = res.scalars().first()
    if not plan_version:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Plan {plan_code} not found", status_code=404)

    now = datetime.now(timezone.utc)
    starts_at, ends_at = domain.calculate_period_dates(now)

    # 3. Retrieve or create Subscription aggregate
    sub_stmt = select(models.Subscription).where(models.Subscription.store_id == store_id)
    sub_res = await session.execute(sub_stmt)
    subscription = sub_res.scalars().first()

    is_first_paid = True
    if subscription:
        if subscription.activation_sequence > 0:
            is_first_paid = False
        subscription.plan_version_id = plan_version.id
        subscription.state = "ACTIVE_PERIOD_1"
        subscription.activation_sequence += 1
        subscription.first_paid_activated_at = subscription.first_paid_activated_at or now
        subscription.current_period_no = 1
        subscription.updated_at = now
    else:
        subscription = models.Subscription(
            id=uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            plan_version_id=plan_version.id,
            state="ACTIVE_PERIOD_1",
            activation_sequence=1,
            first_paid_activated_at=now,
            current_period_no=1,
            version=0,
            created_at=now,
            updated_at=now,
        )
        session.add(subscription)

    plan_price_paise = int(Decimal(str(plan_version.price_amount)) * 100)
    calc = domain.calculate_initial_activation(
        plan_code=plan_code.upper(),
        plan_price_paise=plan_price_paise,
        is_first_paid_activation=is_first_paid,
        gst_rate=Decimal("0.18"),
    )

    # 4. Create SubscriptionPeriod for Period 1
    period_id = uuid4()
    period = models.SubscriptionPeriod(
        id=period_id,
        tenant_id=tenant_id,
        store_id=store_id,
        subscription_id=subscription.id,
        period_no=1,
        plan_version_id=plan_version.id,
        starts_at=starts_at,
        ends_at=ends_at,
        entitlement_status="ACTIVE",
        charge_mode="FULL",
        base_price_snapshot=Decimal(plan_version.price_amount),
        amount_due_snapshot=Decimal(calc["period_1"]["amount"]),
        gst_rate_snapshot=Decimal("0.180000"),
        created_at=now,
        updated_at=now,
    )
    session.add(period)
    subscription.current_period_id = period_id

    # 5. Insert Charges (Period 1 fee + Third-Period Advance)
    charge_p1 = models.SubscriptionCharge(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        subscription_id=subscription.id,
        period_id=period_id,
        charge_type="PERIOD_FEE",
        amount=Decimal(calc["period_1"]["amount"]),
        tax_amount=Decimal(calc["period_1"]["amount"]) * Decimal("0.18"),
        status="PAID",
        due_at=now,
        calculation_snapshot=calc,
        created_at=now,
        updated_at=now,
    )
    session.add(charge_p1)

    charge_a3 = models.SubscriptionCharge(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        subscription_id=subscription.id,
        period_id=period_id,
        charge_type="THIRD_PERIOD_ADVANCE",
        amount=Decimal(calc["third_period_advance"]["amount"]),
        tax_amount=Decimal(calc["third_period_advance"]["amount"]) * Decimal("0.18"),
        status="PAID",
        due_at=now,
        calculation_snapshot=calc,
        created_at=now,
        updated_at=now,
    )
    session.add(charge_a3)

    # 6. Insert AdvanceMovement: Direction 'C' (credit advance balance)
    advance_movement = models.AdvanceMovement(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        subscription_id=subscription.id,
        movement_type="COLLECTED",
        amount=Decimal(calc["third_period_advance"]["amount"]),
        direction="C",
        source_charge_id=charge_a3.id,
        effective_at=now,
        reason="Initial activation collection of Third-Period Advance (AC-042)",
        created_at=now,
        updated_at=now,
    )
    session.add(advance_movement)

    # 7. Upsert EntitlementSnapshot
    ent_map = domain.build_entitlements_map(plan_code.upper(), "ACTIVE_PERIOD_1")
    ent_stmt = select(models.EntitlementSnapshot).where(models.EntitlementSnapshot.store_id == store_id)
    ent_res = await session.execute(ent_stmt)
    snapshot = ent_res.scalars().first()

    if snapshot:
        snapshot.plan_code = plan_code.upper()
        snapshot.subscription_id = subscription.id
        snapshot.effective_from = now
        snapshot.entitlements = ent_map
        snapshot.source_plan_version_id = plan_version.id
        snapshot.reason_code = "ACTIVATION"
        snapshot.updated_at = now
    else:
        snapshot = models.EntitlementSnapshot(
            id=uuid4(),
            tenant_id=tenant_id,
            store_id=store_id,
            subscription_id=subscription.id,
            plan_code=plan_code.upper(),
            effective_from=now,
            entitlements=ent_map,
            source_plan_version_id=plan_version.id,
            reason_code="ACTIVATION",
            created_at=now,
            updated_at=now,
        )
        session.add(snapshot)

    # 8. Outbox events: subscription.activated.v1, subscription.period-started.v1, entitlement.changed.v1
    await add_event(
        session=session,
        event_type="subscription.activated.v1",
        aggregate_type="subscription",
        aggregate_id=subscription.id,
        payload={
            "subscription_id": str(subscription.id),
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
            "plan_code": plan_code.upper(),
            "period_no": 1,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "total_paid": calc["total"]["amount"],
        },
        topic="subscription.lifecycle",
        tenant_id=tenant_id,
        store_id=store_id,
        correlation_id=correlation_id,
    )

    await add_event(
        session=session,
        event_type="subscription.period-started.v1",
        aggregate_type="subscription_period",
        aggregate_id=period_id,
        payload={
            "subscription_id": str(subscription.id),
            "period_id": str(period_id),
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
            "period_no": 1,
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
        },
        topic="subscription.lifecycle",
        tenant_id=tenant_id,
        store_id=store_id,
        correlation_id=correlation_id,
    )

    await add_event(
        session=session,
        event_type="entitlement.changed.v1",
        aggregate_type="store",
        aggregate_id=store_id,
        payload={
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
            "plan_tier": plan_code.upper(),
            "capabilities": ent_map,
        },
        topic="entitlement.changed",
        tenant_id=tenant_id,
        store_id=store_id,
        correlation_id=correlation_id,
    )

    return schemas.ActivateSubscriptionResponse(
        subscription_id=subscription.id,
        store_id=store_id,
        plan_code=plan_code.upper(),
        state="ACTIVE_PERIOD_1",
        current_period_no=1,
        starts_at=starts_at,
        ends_at=ends_at,
        total_paid=calc["total"]["amount"],
    )


# ------------------------------------------------------------------------------
# SUB-004: Store Entitlements Projection
# ------------------------------------------------------------------------------

async def get_store_entitlements_command(
    session: AsyncSession,
    store_id: UUID,
    principal: Principal | None = None,
) -> schemas.EntitlementsResponse:
    """Resolves current authoritative capability projection for a store (SUB-004)."""
    # Look up current entitlement snapshot
    stmt = select(models.EntitlementSnapshot).where(models.EntitlementSnapshot.store_id == store_id)
    res = await session.execute(stmt)
    snapshot = res.scalars().first()

    now = datetime.now(timezone.utc)
    if not snapshot:
        # Generate default Free PRESENCE entitlement
        free_map = domain.build_entitlements_map("PRESENCE", "ACTIVE_PERIOD_1")
        return schemas.EntitlementsResponse(
            store_id=store_id,
            plan_code="PRESENCE",
            state="ACTIVE_PERIOD_1",
            commerce_enabled=False,
            showcase_limit=6,
            max_images_per_item=1,
            max_videos_per_item=0,
            custom_domain_allowed=False,
            blog_allowed=False,
            effective_from=now,
        )

    ent = snapshot.entitlements or {}
    return schemas.EntitlementsResponse(
        store_id=store_id,
        plan_code=snapshot.plan_code,
        state=ent.get("state", "ACTIVE_PERIOD_1"),
        commerce_enabled=bool(ent.get("commerce_enabled", False)),
        showcase_limit=ent.get("showcase_limit"),
        max_images_per_item=int(ent.get("max_images_per_item", 1)),
        max_videos_per_item=int(ent.get("max_videos_per_item", 0)),
        custom_domain_allowed=bool(ent.get("custom_domain_allowed", False)),
        blog_allowed=bool(ent.get("blog_allowed", False)),
        effective_from=snapshot.effective_from,
    )


# ------------------------------------------------------------------------------
# SUB-005: Read Subscription
# ------------------------------------------------------------------------------

async def get_subscription_detail_command(
    session: AsyncSession,
    subscription_id: UUID,
    principal: Principal,
) -> schemas.SubscriptionDetailResponse:
    """Reads subscription aggregate, period details, and advance balance (SUB-005)."""
    sub = await session.get(models.Subscription, subscription_id)
    if not sub:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    is_admin = principal.has_role("PLATFORM_STAFF") or principal.has_role("PLATFORM_OWNER")
    if not is_admin and sub.store_id not in principal.store_ids and not principal.has_tenant(sub.tenant_id):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    plan_ver = await session.get(models.PlanVersion, sub.plan_version_id)
    plan_code = plan_ver.plan_code if plan_ver else "PRESENCE"

    current_period_dto = None
    if sub.current_period_id:
        p = await session.get(models.SubscriptionPeriod, sub.current_period_id)
        if p:
            current_period_dto = schemas.SubscriptionPeriodDto(
                period_no=p.period_no,
                starts_at=p.starts_at,
                ends_at=p.ends_at,
                entitlement_status=p.entitlement_status,
                charge_mode=p.charge_mode,
                amount_due=str(p.amount_due_snapshot),
            )

    # Compute advance ledger balance: sum('C') - sum('D')
    adv_stmt = select(models.AdvanceMovement).where(models.AdvanceMovement.subscription_id == subscription_id)
    adv_res = await session.execute(adv_stmt)
    movements = adv_res.scalars().all()

    bal = Decimal(0)
    for m in movements:
        if m.direction == "C":
            bal += Decimal(str(m.amount))
        elif m.direction == "D":
            bal -= Decimal(str(m.amount))

    return schemas.SubscriptionDetailResponse(
        subscription_id=sub.id,
        store_id=sub.store_id,
        tenant_id=sub.tenant_id,
        plan_code=plan_code,
        state=sub.state,
        activation_sequence=sub.activation_sequence,
        first_paid_activated_at=sub.first_paid_activated_at,
        current_period_no=sub.current_period_no,
        current_period=current_period_dto,
        advance_balance=f"{bal:.2f}",
        created_at=sub.created_at,
        updated_at=sub.updated_at,
    )


# ------------------------------------------------------------------------------
# SUB-006: Cancellation Notice
# ------------------------------------------------------------------------------

async def cancel_subscription_command(
    session: AsyncSession,
    subscription_id: UUID,
    principal: Principal,
    reason: str | None = None,
    expected_version: int | None = None,
    correlation_id: UUID | None = None,
) -> schemas.CancelSubscriptionResponse:
    """Records cancellation notice before Period 3 (SUB-006, AC-045..048)."""
    sub = await session.get(models.Subscription, subscription_id)
    if not sub:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    is_admin = principal.has_role("PLATFORM_STAFF") or principal.has_role("PLATFORM_OWNER")
    if not is_admin and sub.store_id not in principal.store_ids and not principal.has_tenant(sub.tenant_id):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    if expected_version is not None and sub.version != expected_version:
        raise ApiError(ErrorCode.STALE_VERSION, "Subscription version mismatch", status_code=409)

    # Notice must be recorded strictly before Period 3 starts (AC-045)
    current_period = sub.current_period_no or 1
    if current_period >= 3:
        raise ApiError(
            ErrorCode.CANCELLATION_WINDOW_CLOSED,
            "Cancellation window closed: notice must be recorded strictly before Period 3 starts",
            status_code=409,
        )

    now = datetime.now(timezone.utc)
    sub.cancellation_effective_after_period = 3
    sub.version += 1
    sub.updated_at = now

    notice = models.CancellationNotice(
        id=uuid4(),
        tenant_id=sub.tenant_id,
        store_id=sub.store_id,
        subscription_id=sub.id,
        requested_by=principal.sub,
        submitted_at=now,
        status="RECORDED",
        effective_after_period_no=3,
        reason=reason,
        created_at=now,
    )
    session.add(notice)

    calc = domain.calculate_cancellation_period_3(199900)

    await add_event(
        session=session,
        event_type="subscription.cancellation-notice-recorded.v1",
        aggregate_type="subscription",
        aggregate_id=sub.id,
        payload={
            "subscription_id": str(sub.id),
            "store_id": str(sub.store_id),
            "tenant_id": str(sub.tenant_id),
            "notice_recorded_at": now.isoformat(),
            "effective_after_period_no": 3,
            "paid_through_period": 3,
            "additional_period_3_due": "0.00",
        },
        topic="subscription.lifecycle",
        tenant_id=sub.tenant_id,
        store_id=sub.store_id,
        correlation_id=correlation_id,
    )

    return schemas.CancelSubscriptionResponse(
        subscription_id=sub.id,
        notice_recorded_at=now,
        paid_through_period=3,
        additional_period_3_due="0.00",
        end_after_period=3,
    )


# ------------------------------------------------------------------------------
# SUB-007: Upgrade Quote
# ------------------------------------------------------------------------------

async def create_upgrade_quote_command(
    session: AsyncSession,
    subscription_id: UUID,
    principal: Principal,
    target_plan_code: str,
    effective: str = "IMMEDIATE",
    correlation_id: UUID | None = None,
) -> schemas.UpgradeQuoteResponse:
    """Calculates immutable upgrade quote (SUB-007, AC-069..075)."""
    sub = await session.get(models.Subscription, subscription_id)
    if not sub:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    is_admin = principal.has_role("PLATFORM_STAFF") or principal.has_role("PLATFORM_OWNER")
    if not is_admin and sub.store_id not in principal.store_ids and not principal.has_tenant(sub.tenant_id):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    current_pv = await session.get(models.PlanVersion, sub.plan_version_id)
    target_stmt = select(models.PlanVersion).where(
        models.PlanVersion.plan_code == target_plan_code.upper(),
        models.PlanVersion.is_active == True,
    ).order_by(models.PlanVersion.version_no.desc())
    target_res = await session.execute(target_stmt)
    target_pv = target_res.scalars().first()

    if not target_pv or not current_pv:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Target plan not found", status_code=404)

    lower_paise = int(Decimal(str(current_pv.price_amount)) * 100)
    higher_paise = int(Decimal(str(target_pv.price_amount)) * 100)
    if higher_paise <= lower_paise:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Target plan price must be higher than current plan", status_code=400)

    # Calculate authoritative days remaining R
    now = datetime.now(timezone.utc)
    days_rem = 15  # default/fallback
    if sub.current_period_id:
        p = await session.get(models.SubscriptionPeriod, sub.current_period_id)
        if p and p.ends_at:
            delta = (p.ends_at - now).total_seconds() / 86400.0
            days_rem = max(0, min(30, int(delta)))

    is_before_p3 = (sub.current_period_no or 1) < 3

    # Advance balance
    adv_stmt = select(models.AdvanceMovement).where(models.AdvanceMovement.subscription_id == subscription_id)
    adv_res = await session.execute(adv_stmt)
    movements = adv_res.scalars().all()
    adv_bal = Decimal(0)
    for m in movements:
        adv_bal += Decimal(str(m.amount)) if m.direction == "C" else -Decimal(str(m.amount))
    adv_bal_paise = int(adv_bal * 100)

    calc = domain.calculate_upgrade_quote(
        lower_price_paise=lower_paise,
        higher_price_paise=higher_paise,
        days_remaining=days_rem,
        is_before_p3=is_before_p3,
        current_advance_balance_paise=adv_bal_paise,
        approved_discount_paise=0,
    )

    quote_id = uuid4()
    expires_at = now + timedelta(hours=24)

    quote = models.UpgradeQuote(
        id=quote_id,
        tenant_id=sub.tenant_id,
        store_id=sub.store_id,
        subscription_id=sub.id,
        target_plan_version_id=target_pv.id,
        days_remaining=days_rem,
        prorated_difference=Decimal(calc["prorated_difference"]),
        advance_top_up=Decimal(calc["advance_top_up"]),
        gross_setup_fee=Decimal(calc["gross_upgrade_setup_fee"]),
        approved_discount_amount=Decimal(0),
        net_setup_fee=Decimal(calc["net_setup_fee"]),
        total_ex_tax=Decimal(calc["total_before_gst"]),
        tax_amount=Decimal(calc["gst"]),
        total_with_tax=Decimal(calc["total"]),
        expires_at=expires_at,
        calculation_snapshot=calc,
        created_at=now,
        updated_at=now,
    )
    session.add(quote)

    await add_event(
        session=session,
        event_type="subscription.upgrade-quote-created.v1",
        aggregate_type="upgrade_quote",
        aggregate_id=quote_id,
        payload={
            "quote_id": str(quote_id),
            "subscription_id": str(sub.id),
            "store_id": str(sub.store_id),
            "tenant_id": str(sub.tenant_id),
            "target_plan_code": target_plan_code.upper(),
            "total_with_tax": calc["total"],
        },
        topic="subscription.lifecycle",
        tenant_id=sub.tenant_id,
        store_id=sub.store_id,
        correlation_id=correlation_id,
    )

    return schemas.UpgradeQuoteResponse(
        quote_id=quote_id,
        lower_price=calc["lower_price"],
        higher_price=calc["higher_price"],
        days_remaining=days_rem,
        prorated_difference=calc["prorated_difference"],
        advance_top_up=calc["advance_top_up"],
        gross_upgrade_setup_fee=calc["gross_upgrade_setup_fee"],
        approved_discount=calc["approved_discount"],
        net_setup_fee=calc["net_setup_fee"],
        total_before_gst=calc["total_before_gst"],
        total_with_tax=calc["total"],
    )


# ------------------------------------------------------------------------------
# SUB-008: Apply Upgrade
# ------------------------------------------------------------------------------

async def apply_upgrade_command(
    session: AsyncSession,
    subscription_id: UUID,
    quote_id: UUID,
    principal: Principal,
    correlation_id: UUID | None = None,
) -> schemas.ApplyUpgradeResponse:
    """Applies approved/paid upgrade (SUB-008)."""
    sub = await session.get(models.Subscription, subscription_id)
    if not sub:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    is_admin = principal.has_role("PLATFORM_STAFF") or principal.has_role("PLATFORM_OWNER")
    if not is_admin and sub.store_id not in principal.store_ids and not principal.has_tenant(sub.tenant_id):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    quote = await session.get(models.UpgradeQuote, quote_id)
    if not quote or quote.subscription_id != subscription_id:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Upgrade quote not found for subscription", status_code=404)

    target_pv = await session.get(models.PlanVersion, quote.target_plan_version_id)
    if not target_pv:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Target plan version not found", status_code=404)

    now = datetime.now(timezone.utc)
    sub.plan_version_id = target_pv.id
    sub.version += 1
    sub.updated_at = now

    # Update entitlement snapshot immediately
    ent_map = domain.build_entitlements_map(target_pv.plan_code, sub.state)
    ent_stmt = select(models.EntitlementSnapshot).where(models.EntitlementSnapshot.store_id == sub.store_id)
    ent_res = await session.execute(ent_stmt)
    snapshot = ent_res.scalars().first()
    if snapshot:
        snapshot.plan_code = target_pv.plan_code
        snapshot.entitlements = ent_map
        snapshot.source_plan_version_id = target_pv.id
        snapshot.reason_code = "UPGRADE"
        snapshot.updated_at = now

    await add_event(
        session=session,
        event_type="subscription.upgraded.v1",
        aggregate_type="subscription",
        aggregate_id=sub.id,
        payload={
            "subscription_id": str(sub.id),
            "store_id": str(sub.store_id),
            "tenant_id": str(sub.tenant_id),
            "target_plan_code": target_pv.plan_code,
            "effective_at": now.isoformat(),
        },
        topic="subscription.lifecycle",
        tenant_id=sub.tenant_id,
        store_id=sub.store_id,
        correlation_id=correlation_id,
    )

    await add_event(
        session=session,
        event_type="entitlement.changed.v1",
        aggregate_type="store",
        aggregate_id=sub.store_id,
        payload={
            "store_id": str(sub.store_id),
            "tenant_id": str(sub.tenant_id),
            "plan_tier": target_pv.plan_code,
            "capabilities": ent_map,
        },
        topic="entitlement.changed",
        tenant_id=sub.tenant_id,
        store_id=sub.store_id,
        correlation_id=correlation_id,
    )

    return schemas.ApplyUpgradeResponse(
        subscription_id=sub.id,
        plan_code=target_pv.plan_code,
        state=sub.state,
        effective_at=now,
    )


# ------------------------------------------------------------------------------
# SUB-009: Request Downgrade
# ------------------------------------------------------------------------------

async def request_downgrade_command(
    session: AsyncSession,
    subscription_id: UUID,
    target_plan_code: str,
    principal: Principal,
    reason: str | None = None,
    correlation_id: UUID | None = None,
) -> schemas.DowngradeResponse:
    """Requests future billing boundary downgrade (SUB-009, SM PLAN-05)."""
    sub = await session.get(models.Subscription, subscription_id)
    if not sub:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    is_admin = principal.has_role("PLATFORM_STAFF") or principal.has_role("PLATFORM_OWNER")
    if not is_admin and sub.store_id not in principal.store_ids and not principal.has_tenant(sub.tenant_id):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    target_stmt = select(models.PlanVersion).where(
        models.PlanVersion.plan_code == target_plan_code.upper(),
        models.PlanVersion.is_active == True,
    ).order_by(models.PlanVersion.version_no.desc())
    target_res = await session.execute(target_stmt)
    target_pv = target_res.scalars().first()
    if not target_pv:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Target plan not found", status_code=404)

    now = datetime.now(timezone.utc)
    req_id = uuid4()
    req = models.PlanChangeRequest(
        id=req_id,
        tenant_id=sub.tenant_id,
        store_id=sub.store_id,
        subscription_id=sub.id,
        change_type="DOWNGRADE",
        from_plan_version_id=sub.plan_version_id,
        to_plan_version_id=target_pv.id,
        requested_at=now,
        status="PENDING",
        created_at=now,
        updated_at=now,
    )
    session.add(req)

    await add_event(
        session=session,
        event_type="subscription.downgrade-requested.v1",
        aggregate_type="plan_change_request",
        aggregate_id=req_id,
        payload={
            "request_id": str(req_id),
            "subscription_id": str(sub.id),
            "store_id": str(sub.store_id),
            "target_plan_code": target_plan_code.upper(),
        },
        topic="subscription.lifecycle",
        tenant_id=sub.tenant_id,
        store_id=sub.store_id,
        correlation_id=correlation_id,
    )

    return schemas.DowngradeResponse(
        request_id=req_id,
        subscription_id=sub.id,
        from_plan="COMMERCE",
        to_plan=target_plan_code.upper(),
        status="PENDING",
        effective_at=None,
    )


# ------------------------------------------------------------------------------
# SUB-010: Reactivate Subscription
# ------------------------------------------------------------------------------

async def reactivate_subscription_command(
    session: AsyncSession,
    subscription_id: UUID,
    target_plan_code: str,
    principal: Principal,
    gstin_id: UUID | None = None,
    correlation_id: UUID | None = None,
) -> schemas.ReactivateSubscriptionResponse:
    """Reactivates paid subscription after non-payment Free conversion (SUB-010, AC-065..068)."""
    sub = await session.get(models.Subscription, subscription_id)
    if not sub:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    is_admin = principal.has_role("PLATFORM_STAFF") or principal.has_role("PLATFORM_OWNER")
    if not is_admin and sub.store_id not in principal.store_ids and not principal.has_tenant(sub.tenant_id):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Subscription not found", status_code=404)

    # Must be in Free Presence state following non-payment or cancellation
    if sub.state != "FREE_PRESENCE":
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Reactivation only allowed from FREE_PRESENCE state", status_code=409)

    target_stmt = select(models.PlanVersion).where(
        models.PlanVersion.plan_code == target_plan_code.upper(),
        models.PlanVersion.is_active == True,
    ).order_by(models.PlanVersion.version_no.desc())
    target_res = await session.execute(target_stmt)
    target_pv = target_res.scalars().first()
    if not target_pv:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Target plan not found", status_code=404)

    now = datetime.now(timezone.utc)
    starts_at, ends_at = domain.calculate_period_dates(now)

    plan_price_paise = int(Decimal(str(target_pv.price_amount)) * 100)
    calc = domain.calculate_reactivation(
        plan_code=target_plan_code.upper(),
        plan_price_paise=plan_price_paise,
    )

    sub.plan_version_id = target_pv.id
    sub.state = "ACTIVE_PERIOD_1"
    sub.activation_sequence += 1
    sub.current_period_no = 1
    sub.version += 1
    sub.updated_at = now

    # Create fresh period
    period = models.SubscriptionPeriod(
        id=uuid4(),
        tenant_id=sub.tenant_id,
        store_id=sub.store_id,
        subscription_id=sub.id,
        period_no=1,
        plan_version_id=target_pv.id,
        starts_at=starts_at,
        ends_at=ends_at,
        entitlement_status="ACTIVE",
        charge_mode="FULL",
        base_price_snapshot=Decimal(calc["period_fee"]),
        amount_due_snapshot=Decimal(calc["total"]),
        gst_rate_snapshot=Decimal("0.180000"),
        created_at=now,
        updated_at=now,
    )
    session.add(period)
    sub.current_period_id = period.id

    # Update entitlement snapshot
    ent_map = domain.build_entitlements_map(target_plan_code.upper(), "ACTIVE_PERIOD_1")
    ent_stmt = select(models.EntitlementSnapshot).where(models.EntitlementSnapshot.store_id == sub.store_id)
    ent_res = await session.execute(ent_stmt)
    snapshot = ent_res.scalars().first()
    if snapshot:
        snapshot.plan_code = target_plan_code.upper()
        snapshot.entitlements = ent_map
        snapshot.reason_code = "REACTIVATION"
        snapshot.updated_at = now

    await add_event(
        session=session,
        event_type="subscription.reactivated.v1",
        aggregate_type="subscription",
        aggregate_id=sub.id,
        payload={
            "subscription_id": str(sub.id),
            "store_id": str(sub.store_id),
            "target_plan_code": target_plan_code.upper(),
            "starts_at": starts_at.isoformat(),
            "ends_at": ends_at.isoformat(),
            "total_paid": calc["total"],
        },
        topic="subscription.lifecycle",
        tenant_id=sub.tenant_id,
        store_id=sub.store_id,
        correlation_id=correlation_id,
    )

    return schemas.ReactivateSubscriptionResponse(
        subscription_id=sub.id,
        plan_code=target_plan_code.upper(),
        state="ACTIVE_PERIOD_1",
        period_fee=calc["period_fee"],
        reactivation_setup_fee=calc["reactivation_setup"],
        total=calc["total"],
        starts_at=starts_at,
        ends_at=ends_at,
    )


# ------------------------------------------------------------------------------
# SUB-011: Upgrade Setup Discount Decision
# ------------------------------------------------------------------------------

async def decide_upgrade_discount_command(
    session: AsyncSession,
    request_id: UUID,
    principal: Principal,
    approved: bool,
    approved_amount_str: str,
    reason: str,
    correlation_id: UUID | None = None,
) -> schemas.DiscountDecisionResponse:
    """Platform Owner decision approving or rejecting upgrade setup fee discount (SUB-011, AC-072..075)."""
    # Strict Platform Owner permission check
    if not principal.has_role("PLATFORM_OWNER"):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Only PLATFORM_OWNER can decide upgrade setup discounts", status_code=403)

    quote = await session.get(models.UpgradeQuote, request_id)
    if not quote:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Upgrade quote not found", status_code=404)

    now = datetime.now(timezone.utc)
    appr_amt = Decimal(approved_amount_str) if approved else Decimal(0)

    # Discount can only apply against gross setup fee (never waives proration) (AC-075)
    gross_setup = Decimal(str(quote.gross_setup_fee))
    appr_amt = min(appr_amt, gross_setup)
    net_setup = max(Decimal(0), gross_setup - appr_amt)

    quote.approved_discount_amount = appr_amt
    quote.net_setup_fee = net_setup
    quote.total_ex_tax = quote.prorated_difference + quote.advance_top_up + net_setup
    quote.tax_amount = quote.total_ex_tax * Decimal("0.18")
    quote.total_with_tax = quote.total_ex_tax + quote.tax_amount
    quote.updated_at = now

    audit = models.DiscountApproval(
        id=uuid4(),
        tenant_id=quote.tenant_id,
        store_id=quote.store_id,
        upgrade_quote_id=quote.id,
        requested_discount=Decimal(approved_amount_str),
        approved_amount=appr_amt,
        approver_id=principal.sub,
        reason=reason,
        decided_at=now,
        created_at=now,
    )
    session.add(audit)

    await add_event(
        session=session,
        event_type="subscription.upgrade-discount-decided.v1",
        aggregate_type="upgrade_quote",
        aggregate_id=quote.id,
        payload={
            "quote_id": str(quote.id),
            "approved": approved,
            "approved_amount": str(appr_amt),
            "approver_id": str(principal.sub),
            "reason": reason,
        },
        topic="subscription.lifecycle",
        tenant_id=quote.tenant_id,
        store_id=quote.store_id,
        correlation_id=correlation_id,
    )

    return schemas.DiscountDecisionResponse(
        quote_id=quote.id,
        requested_discount=approved_amount_str,
        approved_amount=f"{appr_amt:.2f}",
        net_setup_fee=f"{net_setup:.2f}",
        total_with_tax=f"{quote.total_with_tax:.2f}",
        decided_at=now,
    )


# ------------------------------------------------------------------------------
# Dev / Internal Stub: Record Platform Payment (STUBS.md line 12, SERVICES.md §7)
# ------------------------------------------------------------------------------

async def record_platform_payment_command(
    session: AsyncSession,
    store_id: UUID,
    subscription_id: UUID,
    amount_paise: int,
    payment_reference: str,
    charge_id: UUID | None = None,
    paid_at: datetime | None = None,
    correlation_id: UUID | None = None,
) -> dict:
    """STUB dev-only platform payment recorder (SERVICES.md §7, STUBS.md item 12).
    Simulates finance.platform-payment-recorded.v1 from FIN.
    Settles pending charge, clears delinquency if in grace/expired, restores active state.
    """
    now = paid_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # 1. Fetch subscription
    sub_stmt = select(models.Subscription).where(models.Subscription.id == subscription_id)
    sub_res = await session.execute(sub_stmt)
    subscription = sub_res.scalars().first()
    if not subscription or subscription.store_id != store_id:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND, "Subscription not found for store", status_code=404)

    # 2. Fetch charge
    if charge_id:
        chg_stmt = select(models.SubscriptionCharge).where(models.SubscriptionCharge.id == charge_id)
    else:
        chg_stmt = (
            select(models.SubscriptionCharge)
            .where(
                models.SubscriptionCharge.subscription_id == subscription_id,
                models.SubscriptionCharge.status != "PAID",
            )
            .order_by(models.SubscriptionCharge.created_at.asc())
        )
    chg_res = await session.execute(chg_stmt)
    charge = chg_res.scalars().first()
    if not charge:
        raise ApiError(ErrorCode.RESOURCE_NOT_FOUND, "No unpaid charge found for subscription", status_code=404)

    # Settle charge
    charge.status = "PAID"
    charge.updated_at = now

    # 3. If in delinquency (PAYMENT_GRACE or SUBSCRIPTION_EXPIRED), recover active state!
    if subscription.state in ("PAYMENT_GRACE", "SUBSCRIPTION_EXPIRED"):
        p_no = subscription.current_period_no
        if p_no == 1:
            target_state = "ACTIVE_PERIOD_1"
        elif p_no == 2:
            target_state = "ACTIVE_PERIOD_2"
        elif p_no == 3:
            target_state = "P3_50_PERCENT_DUE"
        elif p_no == 4:
            target_state = "P4_50_PERCENT_DUE"
        else:
            target_state = "STANDARD_RENEWAL"

        subscription.state = target_state
        subscription.updated_at = now

        pv_stmt = select(models.PlanVersion).where(models.PlanVersion.id == subscription.plan_version_id)
        pv_res = await session.execute(pv_stmt)
        pv = pv_res.scalars().first()
        plan_code = pv.plan_code if pv else "COMMERCE"

        ent_map = domain.build_entitlements_map(plan_code, target_state)
        ent_stmt = select(models.EntitlementSnapshot).where(models.EntitlementSnapshot.store_id == store_id)
        ent_res = await session.execute(ent_stmt)
        snapshot = ent_res.scalars().first()
        if snapshot:
            snapshot.plan_code = ent_map["plan_code"]
            snapshot.entitlements = ent_map
            snapshot.effective_from = now
            snapshot.reason_code = "PAYMENT_RECOVERY"
            snapshot.updated_at = now

        await add_event(
            session=session,
            event_type="entitlement.changed.v1",
            aggregate_type="subscription",
            aggregate_id=subscription.id,
            payload={
                "tenant_id": str(subscription.tenant_id),
                "store_id": str(store_id),
                "plan_code": ent_map["plan_code"],
                "state": target_state,
                "capabilities": ent_map,
                "changed_at": now.isoformat(),
            },
            topic="entitlement.changed",
            tenant_id=subscription.tenant_id,
            store_id=store_id,
            correlation_id=correlation_id,
        )

    return {
        "subscription_id": str(subscription.id),
        "charge_id": str(charge.id),
        "status": charge.status,
        "subscription_state": subscription.state,
    }


# ------------------------------------------------------------------------------
# Phase 8b: Autonomous Subscription Background Scheduler (SERVICES.md §7)
# ------------------------------------------------------------------------------

async def _claim_job_lock(
    session: AsyncSession,
    job_type: str,
    business_key: str,
    now: datetime,
    lease_seconds: int,
) -> bool:
    """Attempts to acquire a job lock via scheduled_jobs using SKIP LOCKED."""
    stmt = (
        select(models.ScheduledJob)
        .where(models.ScheduledJob.business_key == business_key)
        .with_for_update(skip_locked=True)
    )
    res = await session.execute(stmt)
    existing = res.scalars().first()

    if existing:
        if existing.status == "COMPLETED":
            return False
        if existing.locked_until and existing.locked_until > now:
            return False
        existing.status = "PROCESSING"
        existing.locked_until = now + timedelta(seconds=lease_seconds)
        existing.attempts += 1
        existing.updated_at = now
        return True

    try:
        new_job = models.ScheduledJob(
            id=uuid4(),
            job_type=job_type,
            business_key=business_key,
            status="PROCESSING",
            scheduled_at=now,
            locked_until=now + timedelta(seconds=lease_seconds),
            attempts=1,
            created_at=now,
            updated_at=now,
        )
        session.add(new_job)
        await session.flush()
        return True
    except Exception:
        return False


async def _complete_job(session: AsyncSession, business_key: str, now: datetime) -> None:
    stmt = select(models.ScheduledJob).where(models.ScheduledJob.business_key == business_key)
    res = await session.execute(stmt)
    job = res.scalars().first()
    if job:
        job.status = "COMPLETED"
        job.locked_until = None
        job.completed_at = now
        job.updated_at = now


async def _update_entitlement_snapshot(
    session: AsyncSession,
    subscription: models.Subscription,
    ent_map: dict,
    now: datetime,
    reason_code: str,
) -> None:
    ent_stmt = select(models.EntitlementSnapshot).where(models.EntitlementSnapshot.store_id == subscription.store_id)
    ent_res = await session.execute(ent_stmt)
    snapshot = ent_res.scalars().first()
    if snapshot:
        snapshot.plan_code = ent_map["plan_code"]
        snapshot.entitlements = ent_map
        snapshot.effective_from = now
        snapshot.reason_code = reason_code
        snapshot.updated_at = now


async def process_subscription_scheduler_command(
    session: AsyncSession,
    as_of: datetime | None = None,
    lease_seconds: int = 30,
) -> int:
    """Autonomous background scheduler command for subscription lifecycle (Phase 8b, SERVICES.md §7).
    Executes:
    1. Period advancement at boundary (P1 -> P2 -> P3 -> P4 -> P5+)
    2. Cancellation notice check before P3 (P3_FULLY_PREPAID vs P3_50_PERCENT_DUE)
    3. Scheduled downgrade execution at period boundary
    4. Delinquency transitions for unpaid charges:
       - Days 1-7: PAYMENT_GRACE (subscription.grace-entered.v1)
       - Days 8-22: SUBSCRIPTION_EXPIRED (subscription.expired.v1, entitlement.changed.v1)
       - Day 23+: FREE_PRESENCE conversion (subscription.converted-to-free.v1, entitlement.changed.v1, SET_OFF advance)
    Uses scheduled_jobs with FOR UPDATE SKIP LOCKED and business_key = f"{sub_id}:{period_no}:{transition}".
    Returns total processed transitions count.
    """
    now = as_of or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    await set_rls_context(session, tenant_id=None, store_id=None, is_platform_admin=True)

    processed_count = 0

    stmt = (
        select(models.Subscription)
        .where(models.Subscription.state != "FREE_PRESENCE")
        .order_by(models.Subscription.created_at.asc())
    )
    sub_res = await session.execute(stmt)
    subscriptions = sub_res.scalars().all()

    for sub in subscriptions:
        period = None
        if sub.current_period_id:
            p_stmt = select(models.SubscriptionPeriod).where(models.SubscriptionPeriod.id == sub.current_period_id)
            p_res = await session.execute(p_stmt)
            period = p_res.scalars().first()

        if not period:
            continue

        pv_stmt = select(models.PlanVersion).where(models.PlanVersion.id == sub.plan_version_id)
        pv_res = await session.execute(pv_stmt)
        plan_version = pv_res.scalars().first()
        plan_price_paise = int(Decimal(str(plan_version.price_amount)) * 100) if plan_version else 199900

        # ------------------------------------------------------------------
        # PART A: Check for Unpaid Delinquency on pending charges
        # ------------------------------------------------------------------
        chg_stmt = (
            select(models.SubscriptionCharge)
            .where(
                models.SubscriptionCharge.subscription_id == sub.id,
                models.SubscriptionCharge.status != "PAID",
                models.SubscriptionCharge.due_at <= now,
            )
            .order_by(models.SubscriptionCharge.due_at.asc())
        )
        chg_res = await session.execute(chg_stmt)
        overdue_charges = chg_res.scalars().all()

        if overdue_charges:
            oldest_due = overdue_charges[0].due_at
            days_overdue = (now.date() - oldest_due.date()).days
            if days_overdue >= 1:
                delinquency_target = domain.calculate_delinquency_state(days_overdue)

                # DAY 23+: FREE_PRESENCE CONVERSION (AC-059..064)
                if delinquency_target == "FREE_PRESENCE" and sub.state != "FREE_PRESENCE":
                    bkey = f"{sub.id}:{sub.current_period_no}:DAY_23_FREE"
                    if await _claim_job_lock(session, "DAY_23_FREE", bkey, now, lease_seconds):
                        sub.state = "FREE_PRESENCE"
                        sub.updated_at = now

                        adv_stmt = select(models.AdvanceMovement).where(models.AdvanceMovement.subscription_id == sub.id)
                        adv_res = await session.execute(adv_stmt)
                        movements = adv_res.scalars().all()
                        adv_bal = sum(m.amount if m.direction == "C" else -m.amount for m in movements)
                        if adv_bal > 0:
                            set_off = models.AdvanceMovement(
                                id=uuid4(),
                                tenant_id=sub.tenant_id,
                                store_id=sub.store_id,
                                subscription_id=sub.id,
                                movement_type="SET_OFF",
                                amount=adv_bal,
                                direction="D",
                                effective_at=now,
                                reason="Day 23 non-payment conversion set-off (AC-063)",
                                created_at=now,
                                updated_at=now,
                            )
                            session.add(set_off)

                        ent_map = domain.build_entitlements_map("PRESENCE", "FREE_PRESENCE")
                        await _update_entitlement_snapshot(session, sub, ent_map, now, "DELINQUENCY_CONVERSION")

                        await add_event(
                            session=session,
                            event_type="subscription.converted-to-free.v1",
                            aggregate_type="subscription",
                            aggregate_id=sub.id,
                            payload={
                                "subscription_id": str(sub.id),
                                "store_id": str(sub.store_id),
                                "reason": "UNPAID_DELINQUENCY_DAY_23",
                                "converted_at": now.isoformat(),
                            },
                            topic="subscription.lifecycle",
                            tenant_id=sub.tenant_id,
                            store_id=sub.store_id,
                        )
                        await add_event(
                            session=session,
                            event_type="entitlement.changed.v1",
                            aggregate_type="subscription",
                            aggregate_id=sub.id,
                            payload={
                                "tenant_id": str(sub.tenant_id),
                                "store_id": str(sub.store_id),
                                "plan_code": "PRESENCE",
                                "state": "FREE_PRESENCE",
                                "capabilities": ent_map,
                                "changed_at": now.isoformat(),
                            },
                            topic="entitlement.changed",
                            tenant_id=sub.tenant_id,
                            store_id=sub.store_id,
                        )
                        await _complete_job(session, bkey, now)
                        processed_count += 1
                        continue

                # DAY 8-22: SUBSCRIPTION_EXPIRED (AC-055..058)
                elif delinquency_target == "SUBSCRIPTION_EXPIRED" and sub.state not in ("SUBSCRIPTION_EXPIRED", "FREE_PRESENCE"):
                    bkey = f"{sub.id}:{sub.current_period_no}:DAY_8_EXPIRED"
                    if await _claim_job_lock(session, "DAY_8_EXPIRED", bkey, now, lease_seconds):
                        sub.state = "SUBSCRIPTION_EXPIRED"
                        sub.updated_at = now

                        ent_map = domain.build_entitlements_map(plan_version.plan_code, "SUBSCRIPTION_EXPIRED")
                        await _update_entitlement_snapshot(session, sub, ent_map, now, "SUBSCRIPTION_EXPIRED")

                        await add_event(
                            session=session,
                            event_type="subscription.expired.v1",
                            aggregate_type="subscription",
                            aggregate_id=sub.id,
                            payload={
                                "subscription_id": str(sub.id),
                                "store_id": str(sub.store_id),
                                "days_overdue": days_overdue,
                                "expired_at": now.isoformat(),
                            },
                            topic="subscription.lifecycle",
                            tenant_id=sub.tenant_id,
                            store_id=sub.store_id,
                        )
                        await add_event(
                            session=session,
                            event_type="entitlement.changed.v1",
                            aggregate_type="subscription",
                            aggregate_id=sub.id,
                            payload={
                                "tenant_id": str(sub.tenant_id),
                                "store_id": str(sub.store_id),
                                "plan_code": plan_version.plan_code,
                                "state": "SUBSCRIPTION_EXPIRED",
                                "capabilities": ent_map,
                                "changed_at": now.isoformat(),
                            },
                            topic="entitlement.changed",
                            tenant_id=sub.tenant_id,
                            store_id=sub.store_id,
                        )
                        await _complete_job(session, bkey, now)
                        processed_count += 1

                # DAY 1-7: PAYMENT_GRACE (AC-054)
                elif delinquency_target == "PAYMENT_GRACE" and sub.state not in ("PAYMENT_GRACE", "SUBSCRIPTION_EXPIRED", "FREE_PRESENCE"):
                    bkey = f"{sub.id}:{sub.current_period_no}:DAY_1_GRACE"
                    if await _claim_job_lock(session, "DAY_1_GRACE", bkey, now, lease_seconds):
                        sub.state = "PAYMENT_GRACE"
                        sub.updated_at = now

                        await add_event(
                            session=session,
                            event_type="subscription.grace-entered.v1",
                            aggregate_type="subscription",
                            aggregate_id=sub.id,
                            payload={
                                "subscription_id": str(sub.id),
                                "store_id": str(sub.store_id),
                                "grace_started_at": now.isoformat(),
                            },
                            topic="subscription.lifecycle",
                            tenant_id=sub.tenant_id,
                            store_id=sub.store_id,
                        )
                        await _complete_job(session, bkey, now)
                        processed_count += 1

        # ------------------------------------------------------------------
        # PART B: Period Boundary Advancement (when current period has ended)
        # ------------------------------------------------------------------
        if period.ends_at <= now:
            # P3_FULLY_PREPAID ends -> converts directly to FREE_PRESENCE (AC-048)
            if sub.state == "P3_FULLY_PREPAID":
                bkey = f"{sub.id}:{sub.current_period_no}:P3_PREPAID_END"
                if await _claim_job_lock(session, "P3_PREPAID_END", bkey, now, lease_seconds):
                    sub.state = "FREE_PRESENCE"
                    sub.updated_at = now
                    ent_map = domain.build_entitlements_map("PRESENCE", "FREE_PRESENCE")
                    await _update_entitlement_snapshot(session, sub, ent_map, now, "PREPAID_P3_COMPLETED")

                    await add_event(
                        session=session,
                        event_type="subscription.converted-to-free.v1",
                        aggregate_type="subscription",
                        aggregate_id=sub.id,
                        payload={
                            "subscription_id": str(sub.id),
                            "store_id": str(sub.store_id),
                            "reason": "P3_FULLY_PREPAID_COMPLETED",
                            "converted_at": now.isoformat(),
                        },
                        topic="subscription.lifecycle",
                        tenant_id=sub.tenant_id,
                        store_id=sub.store_id,
                    )
                    await add_event(
                        session=session,
                        event_type="entitlement.changed.v1",
                        aggregate_type="subscription",
                        aggregate_id=sub.id,
                        payload={
                            "tenant_id": str(sub.tenant_id),
                            "store_id": str(sub.store_id),
                            "plan_code": "PRESENCE",
                            "state": "FREE_PRESENCE",
                            "capabilities": ent_map,
                            "changed_at": now.isoformat(),
                        },
                        topic="entitlement.changed",
                        tenant_id=sub.tenant_id,
                        store_id=sub.store_id,
                    )
                    await _complete_job(session, bkey, now)
                    processed_count += 1
                    continue

            # Check for approved scheduled downgrade (PLAN-05)
            d_stmt = (
                select(models.PlanChangeRequest)
                .where(
                    models.PlanChangeRequest.subscription_id == sub.id,
                    models.PlanChangeRequest.change_type == "DOWNGRADE",
                    models.PlanChangeRequest.status == "APPROVED",
                )
            )
            d_res = await session.execute(d_stmt)
            downgrade_req = d_res.scalars().first()
            if downgrade_req:
                bkey = f"{sub.id}:{sub.current_period_no}:DOWNGRADE"
                if await _claim_job_lock(session, "DOWNGRADE", bkey, now, lease_seconds):
                    sub.plan_version_id = downgrade_req.to_plan_version_id
                    downgrade_req.status = "COMPLETED"
                    downgrade_req.effective_at = now
                    sub.updated_at = now

                    new_pv_stmt = select(models.PlanVersion).where(models.PlanVersion.id == sub.plan_version_id)
                    new_pv_res = await session.execute(new_pv_stmt)
                    new_pv = new_pv_res.scalars().first()
                    plan_code = new_pv.plan_code if new_pv else "COMMERCE"

                    ent_map = domain.build_entitlements_map(plan_code, sub.state)
                    await _update_entitlement_snapshot(session, sub, ent_map, now, "SCHEDULED_DOWNGRADE")

                    await add_event(
                        session=session,
                        event_type="subscription.downgraded.v1",
                        aggregate_type="subscription",
                        aggregate_id=sub.id,
                        payload={
                            "subscription_id": str(sub.id),
                            "store_id": str(sub.store_id),
                            "to_plan_version_id": str(sub.plan_version_id),
                            "effective_at": now.isoformat(),
                        },
                        topic="subscription.lifecycle",
                        tenant_id=sub.tenant_id,
                        store_id=sub.store_id,
                    )
                    await add_event(
                        session=session,
                        event_type="entitlement.changed.v1",
                        aggregate_type="subscription",
                        aggregate_id=sub.id,
                        payload={
                            "tenant_id": str(sub.tenant_id),
                            "store_id": str(sub.store_id),
                            "plan_code": plan_code,
                            "state": sub.state,
                            "capabilities": ent_map,
                            "changed_at": now.isoformat(),
                        },
                        topic="entitlement.changed",
                        tenant_id=sub.tenant_id,
                        store_id=sub.store_id,
                    )
                    await _complete_job(session, bkey, now)
                    processed_count += 1

            # Advance to next period
            next_period_no = sub.current_period_no + 1
            bkey = f"{sub.id}:{next_period_no}:ADVANCE"

            p_exist_stmt = select(models.SubscriptionPeriod).where(
                models.SubscriptionPeriod.subscription_id == sub.id,
                models.SubscriptionPeriod.period_no == next_period_no,
            )
            p_exist_res = await session.execute(p_exist_stmt)
            if p_exist_res.scalars().first():
                continue

            if await _claim_job_lock(session, "ADVANCE", bkey, now, lease_seconds):
                next_start = period.ends_at
                next_end = next_start + timedelta(days=domain.PERIOD_DURATION_DAYS)

                if next_period_no == 2:
                    target_state = "ACTIVE_PERIOD_2"
                    calc = domain.calculate_continuation_period(2, plan_price_paise)
                    charge = models.SubscriptionCharge(
                        id=uuid4(),
                        tenant_id=sub.tenant_id,
                        store_id=sub.store_id,
                        subscription_id=sub.id,
                        charge_type="PERIOD_FEE",
                        amount=Decimal(calc["amount_due"]),
                        tax_amount=Decimal(calc["gst"]),
                        status="DUE",
                        due_at=next_start,
                        calculation_snapshot=calc,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(charge)

                    await add_event(
                        session=session,
                        event_type="subscription.payment-due.v1",
                        aggregate_type="subscription",
                        aggregate_id=sub.id,
                        payload={
                            "subscription_id": str(sub.id),
                            "store_id": str(sub.store_id),
                            "charge_id": str(charge.id),
                            "amount_due": calc["amount_due"],
                            "due_date": next_start.isoformat(),
                        },
                        topic="subscription.lifecycle",
                        tenant_id=sub.tenant_id,
                        store_id=sub.store_id,
                    )

                elif next_period_no == 3:
                    cn_stmt = (
                        select(models.CancellationNotice)
                        .where(
                            models.CancellationNotice.subscription_id == sub.id,
                            models.CancellationNotice.created_at < next_start,
                        )
                    )
                    cn_res = await session.execute(cn_stmt)
                    cancellation_notice = cn_res.scalars().first()

                    if cancellation_notice:
                        target_state = "P3_FULLY_PREPAID"
                        calc = domain.calculate_cancellation_period_3(plan_price_paise)
                        adv_alloc = models.AdvanceMovement(
                            id=uuid4(),
                            tenant_id=sub.tenant_id,
                            store_id=sub.store_id,
                            subscription_id=sub.id,
                            movement_type="ALLOCATION",
                            amount=Decimal(plan_version.price_amount),
                            direction="D",
                            effective_at=now,
                            reason="Period 3 fully prepaid by Third-Period Advance (AC-046)",
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(adv_alloc)
                    else:
                        target_state = "P3_50_PERCENT_DUE"
                        calc = domain.calculate_continuation_period(3, plan_price_paise)
                        adv_alloc = models.AdvanceMovement(
                            id=uuid4(),
                            tenant_id=sub.tenant_id,
                            store_id=sub.store_id,
                            subscription_id=sub.id,
                            movement_type="ALLOCATION",
                            amount=Decimal(calc["advance_credit"]),
                            direction="D",
                            effective_at=now,
                            reason="Period 3 50% advance credit (AC-050)",
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(adv_alloc)

                        charge = models.SubscriptionCharge(
                            id=uuid4(),
                            tenant_id=sub.tenant_id,
                            store_id=sub.store_id,
                            subscription_id=sub.id,
                            charge_type="PERIOD_FEE",
                            amount=Decimal(calc["amount_due"]),
                            tax_amount=Decimal(calc["gst"]),
                            status="DUE",
                            due_at=next_start,
                            calculation_snapshot=calc,
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(charge)

                        await add_event(
                            session=session,
                            event_type="subscription.payment-due.v1",
                            aggregate_type="subscription",
                            aggregate_id=sub.id,
                            payload={
                                "subscription_id": str(sub.id),
                                "store_id": str(sub.store_id),
                                "charge_id": str(charge.id),
                                "amount_due": calc["amount_due"],
                                "due_date": next_start.isoformat(),
                            },
                            topic="subscription.lifecycle",
                            tenant_id=sub.tenant_id,
                            store_id=sub.store_id,
                        )

                elif next_period_no == 4:
                    target_state = "P4_50_PERCENT_DUE"
                    calc = domain.calculate_continuation_period(4, plan_price_paise)
                    adv_alloc = models.AdvanceMovement(
                        id=uuid4(),
                        tenant_id=sub.tenant_id,
                        store_id=sub.store_id,
                        subscription_id=sub.id,
                        movement_type="ALLOCATION",
                        amount=Decimal(calc["advance_credit"]),
                        direction="D",
                        effective_at=now,
                        reason="Period 4 50% remaining advance credit (AC-052)",
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(adv_alloc)

                    charge = models.SubscriptionCharge(
                        id=uuid4(),
                        tenant_id=sub.tenant_id,
                        store_id=sub.store_id,
                        subscription_id=sub.id,
                        charge_type="PERIOD_FEE",
                        amount=Decimal(calc["amount_due"]),
                        tax_amount=Decimal(calc["gst"]),
                        status="DUE",
                        due_at=next_start,
                        calculation_snapshot=calc,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(charge)

                    await add_event(
                        session=session,
                        event_type="subscription.payment-due.v1",
                        aggregate_type="subscription",
                        aggregate_id=sub.id,
                        payload={
                            "subscription_id": str(sub.id),
                            "store_id": str(sub.store_id),
                            "charge_id": str(charge.id),
                            "amount_due": calc["amount_due"],
                            "due_date": next_start.isoformat(),
                        },
                        topic="subscription.lifecycle",
                        tenant_id=sub.tenant_id,
                        store_id=sub.store_id,
                    )

                else:
                    target_state = "STANDARD_RENEWAL"
                    calc = domain.calculate_continuation_period(next_period_no, plan_price_paise)
                    charge = models.SubscriptionCharge(
                        id=uuid4(),
                        tenant_id=sub.tenant_id,
                        store_id=sub.store_id,
                        subscription_id=sub.id,
                        charge_type="PERIOD_FEE",
                        amount=Decimal(calc["amount_due"]),
                        tax_amount=Decimal(calc["gst"]),
                        status="DUE",
                        due_at=next_start,
                        calculation_snapshot=calc,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(charge)

                    await add_event(
                        session=session,
                        event_type="subscription.payment-due.v1",
                        aggregate_type="subscription",
                        aggregate_id=sub.id,
                        payload={
                            "subscription_id": str(sub.id),
                            "store_id": str(sub.store_id),
                            "charge_id": str(charge.id),
                            "amount_due": calc["amount_due"],
                            "due_date": next_start.isoformat(),
                        },
                        topic="subscription.lifecycle",
                        tenant_id=sub.tenant_id,
                        store_id=sub.store_id,
                    )

                new_period = models.SubscriptionPeriod(
                    id=uuid4(),
                    tenant_id=sub.tenant_id,
                    store_id=sub.store_id,
                    subscription_id=sub.id,
                    period_no=next_period_no,
                    plan_version_id=sub.plan_version_id,
                    starts_at=next_start,
                    ends_at=next_end,
                    entitlement_status="ACTIVE",
                    charge_mode="FULL" if next_period_no not in (3, 4) else "HALF_ADVANCE_CREDIT",
                    base_price_snapshot=Decimal(plan_version.price_amount),
                    amount_due_snapshot=Decimal(calc["amount_due"]) if "amount_due" in calc else Decimal(0),
                    gst_rate_snapshot=Decimal("0.180000"),
                    created_at=now,
                    updated_at=now,
                )
                session.add(new_period)

                sub.current_period_no = next_period_no
                sub.current_period_id = new_period.id
                sub.state = target_state
                sub.updated_at = now

                await add_event(
                    session=session,
                    event_type="subscription.period-started.v1",
                    aggregate_type="subscription",
                    aggregate_id=sub.id,
                    payload={
                        "subscription_id": str(sub.id),
                        "store_id": str(sub.store_id),
                        "period_no": next_period_no,
                        "starts_at": next_start.isoformat(),
                        "ends_at": next_end.isoformat(),
                        "state": target_state,
                    },
                    topic="subscription.lifecycle",
                    tenant_id=sub.tenant_id,
                    store_id=sub.store_id,
                )

                await _complete_job(session, bkey, now)
                processed_count += 1

    return processed_count

