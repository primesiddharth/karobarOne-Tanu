# app/models.py
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class PlanVersion(Base):
    __tablename__ = "plan_versions"
    __table_args__ = (
        UniqueConstraint("plan_code", "version_no", name="uq_plan_code_version_no"),
        {"schema": "subscription"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_code = Column(String(24), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    period_days = Column(Integer, nullable=False, default=30)
    price_amount = Column(Numeric(18, 2), nullable=False, default=0)
    commission_rate = Column(Numeric(9, 6), nullable=False, default=0)
    effective_from = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    effective_to = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class PlanEntitlement(Base):
    __tablename__ = "plan_entitlements"
    __table_args__ = {"schema": "subscription"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_version_id = Column(UUID(as_uuid=True), ForeignKey("subscription.plan_versions.id"), nullable=False, index=True)
    entitlement_code = Column(String(40), nullable=False, index=True)
    value_json = Column(JSONB, nullable=False, default=dict)
    hard_limit = Column(Integer, nullable=True)
    technical_limit = Column(Integer, nullable=True)


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("store_id", name="uq_subscription_store_id"),
        {"schema": "subscription"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    plan_version_id = Column(UUID(as_uuid=True), ForeignKey("subscription.plan_versions.id"), nullable=False, index=True)
    state = Column(String(40), nullable=False, index=True)
    activation_sequence = Column(Integer, nullable=False, default=0)
    first_paid_activated_at = Column(DateTime(timezone=True), nullable=True)
    current_period_no = Column(Integer, nullable=True)
    current_period_id = Column(UUID(as_uuid=True), nullable=True)
    cancellation_effective_after_period = Column(Integer, nullable=True)
    version = Column(BigInteger, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class SubscriptionPeriod(Base):
    __tablename__ = "subscription_periods"
    __table_args__ = (
        UniqueConstraint("subscription_id", "period_no", name="uq_subscription_period_no"),
        {"schema": "subscription"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscription.subscriptions.id"), nullable=False, index=True)
    period_no = Column(Integer, nullable=False)
    plan_version_id = Column(UUID(as_uuid=True), ForeignKey("subscription.plan_versions.id"), nullable=False, index=True)
    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ends_at = Column(DateTime(timezone=True), nullable=False, index=True)
    entitlement_status = Column(String(24), nullable=False, index=True)
    charge_mode = Column(String(32), nullable=False)
    base_price_snapshot = Column(Numeric(18, 2), nullable=False, default=0)
    amount_due_snapshot = Column(Numeric(18, 2), nullable=False, default=0)
    gst_rate_snapshot = Column(Numeric(9, 6), nullable=False, default=0)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class SubscriptionCharge(Base):
    __tablename__ = "subscription_charges"
    __table_args__ = {"schema": "subscription"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscription.subscriptions.id"), nullable=False, index=True)
    period_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    charge_type = Column(String(40), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    tax_amount = Column(Numeric(18, 2), nullable=False, default=0)
    status = Column(String(24), nullable=False, default="DUE", index=True)
    due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    calculation_snapshot = Column(JSONB, nullable=False, default=dict)
    finance_invoice_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class AdvanceMovement(Base):
    __tablename__ = "advance_movements"
    __table_args__ = {"schema": "subscription"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscription.subscriptions.id"), nullable=False, index=True)
    movement_type = Column(String(40), nullable=False, index=True)
    amount = Column(Numeric(18, 2), nullable=False)
    direction = Column(String(1), nullable=False)  # 'C' or 'D'
    source_charge_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    effective_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class CancellationNotice(Base):
    __tablename__ = "cancellation_notices"
    __table_args__ = {"schema": "subscription"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscription.subscriptions.id"), nullable=False, index=True)
    requested_by = Column(UUID(as_uuid=True), nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    status = Column(String(24), nullable=False, default="RECORDED")
    effective_after_period_no = Column(Integer, nullable=False, default=3)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class PlanChangeRequest(Base):
    __tablename__ = "plan_change_requests"
    __table_args__ = {"schema": "subscription"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscription.subscriptions.id"), nullable=False, index=True)
    change_type = Column(String(16), nullable=False)  # UPGRADE or DOWNGRADE
    from_plan_version_id = Column(UUID(as_uuid=True), ForeignKey("subscription.plan_versions.id"), nullable=False)
    to_plan_version_id = Column(UUID(as_uuid=True), ForeignKey("subscription.plan_versions.id"), nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    effective_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(24), nullable=False, default="PENDING", index=True)
    approved_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class UpgradeQuote(Base):
    __tablename__ = "upgrade_quotes"
    __table_args__ = {"schema": "subscription"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    plan_change_request_id = Column(UUID(as_uuid=True), ForeignKey("subscription.plan_change_requests.id"), nullable=True, index=True)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscription.subscriptions.id"), nullable=False, index=True)
    target_plan_version_id = Column(UUID(as_uuid=True), ForeignKey("subscription.plan_versions.id"), nullable=False)
    days_remaining = Column(Integer, nullable=False)
    prorated_difference = Column(Numeric(18, 2), nullable=False, default=0)
    advance_top_up = Column(Numeric(18, 2), nullable=False, default=0)
    gross_setup_fee = Column(Numeric(18, 2), nullable=False, default=0)
    approved_discount_amount = Column(Numeric(18, 2), nullable=False, default=0)
    net_setup_fee = Column(Numeric(18, 2), nullable=False, default=0)
    total_ex_tax = Column(Numeric(18, 2), nullable=False, default=0)
    tax_amount = Column(Numeric(18, 2), nullable=False, default=0)
    total_with_tax = Column(Numeric(18, 2), nullable=False, default=0)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    calculation_snapshot = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class DiscountApproval(Base):
    __tablename__ = "discount_approvals"
    __table_args__ = {"schema": "subscription"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    upgrade_quote_id = Column(UUID(as_uuid=True), ForeignKey("subscription.upgrade_quotes.id"), nullable=False, index=True)
    requested_discount = Column(Numeric(18, 2), nullable=False, default=0)
    approved_amount = Column(Numeric(18, 2), nullable=False, default=0)
    approver_id = Column(UUID(as_uuid=True), nullable=False)
    reason = Column(Text, nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class EntitlementSnapshot(Base):
    __tablename__ = "entitlement_snapshots"
    __table_args__ = {"schema": "subscription"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    plan_code = Column(String(24), nullable=False, index=True)
    effective_from = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    effective_to = Column(DateTime(timezone=True), nullable=True)
    entitlements = Column(JSONB, nullable=False, default=dict)
    source_plan_version_id = Column(UUID(as_uuid=True), nullable=True)
    reason_code = Column(String(40), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = {"schema": "subscription"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_type = Column(String(128), nullable=False, index=True)
    topic = Column(String(128), nullable=False)
    partition_key = Column(String(128), nullable=False)
    payload = Column(JSONB, nullable=False)
    headers = Column(JSONB, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="PENDING", index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    published_at = Column(DateTime(timezone=True), nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)


class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    __table_args__ = {"schema": "subscription"}

    event_id = Column(UUID(as_uuid=True), primary_key=True)
    consumer_name = Column(String(128), primary_key=True)
    processed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = {"schema": "subscription"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    scope = Column(String(64), nullable=False)
    key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        UniqueConstraint("business_key", name="uq_subscription_scheduled_business_key"),
        {"schema": "subscription"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_type = Column(String(64), nullable=False)
    business_key = Column(String(255), nullable=False)
    status = Column(String(24), nullable=False, default="PENDING")
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

