# app/models.py
from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    Index,
    CheckConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ------------------------------------------------------------------------------
# Foundation Tables (RULES.md §5.4)
# ------------------------------------------------------------------------------

class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = {"schema": "customer"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), nullable=False)
    event_version = Column(Integer, nullable=False, default=1)
    event_type = Column(String(128), nullable=False)
    aggregate_type = Column(String(64), nullable=False)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False)
    tenant_id = Column(UUID(as_uuid=True), nullable=True)
    store_id = Column(UUID(as_uuid=True), nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    correlation_id = Column(UUID(as_uuid=True), nullable=False)
    causation_id = Column(UUID(as_uuid=True), nullable=True)
    producer = Column(String(64), nullable=False, default="customer")
    payload = Column(JSONB, nullable=False)
    topic = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    locked_until = Column(DateTime(timezone=True), nullable=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    dead = Column(Boolean, nullable=False, default=False)


class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    __table_args__ = {"schema": "customer"}

    event_id = Column(UUID(as_uuid=True), primary_key=True)
    consumer = Column(String(64), primary_key=True)
    processed_at = Column(DateTime(timezone=True), nullable=False, default=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = {"schema": "customer"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(String(64), nullable=False)
    key = Column(String(128), nullable=False)
    request_hash = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)  # IN_PROGRESS, COMPLETED
    status_code = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)


# ------------------------------------------------------------------------------
# Core Customer Domain Tables (DB Spec §7.7, BTDD §9.7, SM §8)
# ------------------------------------------------------------------------------

class Customer(Base):
    """Store-scoped end-customer profile (DB Spec §7.7, AC-076)."""
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_tenant_id", "tenant_id"),
        Index("ix_customers_store_id", "store_id"),
        Index("uq_customer_store_email", "store_id", "email", unique=True),
        Index("uq_customer_store_mobile", "store_id", "mobile_e164", unique=True),
        Index(
            "uq_customer_store_principal",
            "store_id",
            "iam_principal_id",
            unique=True,
            postgresql_where=text("iam_principal_id IS NOT NULL"),
        ),
        CheckConstraint(
            "status IN ('UNCLAIMED', 'CLAIMED', 'BLOCKED', 'ANONYMIZED')",
            name="ck_customer_status",
        ),
        {"schema": "customer"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    store_id = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    email = Column(String(255), nullable=False)
    mobile_e164 = Column(String(20), nullable=False)
    status = Column(String(24), nullable=False, default="UNCLAIMED")
    iam_principal_id = Column(UUID(as_uuid=True), nullable=True)
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)

    addresses = relationship("CustomerAddress", back_populates="customer", cascade="all, delete-orphan")
    claims = relationship("AccountClaim", back_populates="customer", cascade="all, delete-orphan")
    privacy_requests = relationship("PrivacyRequest", back_populates="customer", cascade="all, delete-orphan")


class CustomerAddress(Base):
    """Customer shipping/billing addresses (DB Spec §7.7)."""
    __tablename__ = "addresses"
    __table_args__ = (
        Index("ix_addresses_tenant_id", "tenant_id"),
        Index("ix_addresses_store_id", "store_id"),
        Index("ix_addresses_customer_id", "customer_id"),
        Index("ix_addresses_city", "city"),
        Index("ix_addresses_state_code", "state_code"),
        Index("ix_addresses_postal_code", "postal_code"),
        CheckConstraint("address_type IN ('SHIPPING', 'BILLING', 'BOTH')", name="ck_address_type"),
        CheckConstraint("country_code = 'IN'", name="ck_country_code_in"),
        {"schema": "customer"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    store_id = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    customer_id = Column(UUID(as_uuid=True), ForeignKey("customer.customers.id", ondelete="CASCADE"), nullable=False)
    address_type = Column(String(16), nullable=False)
    recipient_name = Column(String(200), nullable=False)
    line1 = Column(String(240), nullable=False)
    line2 = Column(String(240), nullable=True)
    city = Column(String(120), nullable=False)
    state_code = Column(String(16), nullable=False)
    postal_code = Column(String(12), nullable=False)
    country_code = Column(String(2), nullable=False, default="IN")
    is_default = Column(Boolean, nullable=False, default=False)

    customer = relationship("Customer", back_populates="addresses")


class AccountClaim(Base):
    """UNCLAIMED -> CLAIMED customer workflow (DB Spec §7.7, SM §8, AC-078)."""
    __tablename__ = "account_claims"
    __table_args__ = (
        Index("ix_account_claims_tenant_id", "tenant_id"),
        Index("ix_account_claims_store_id", "store_id"),
        Index("ix_account_claims_customer_id", "customer_id"),
        Index("ix_account_claims_otp_challenge", "otp_challenge_id"),
        CheckConstraint("status IN ('PENDING', 'VERIFIED', 'EXPIRED', 'FAILED')", name="ck_claim_status"),
        {"schema": "customer"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    store_id = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    customer_id = Column(UUID(as_uuid=True), ForeignKey("customer.customers.id", ondelete="CASCADE"), nullable=False)
    otp_challenge_id = Column(UUID(as_uuid=True), nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    requested_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    verified_at = Column(DateTime(timezone=True), nullable=True)
    resulting_principal_id = Column(UUID(as_uuid=True), nullable=True)

    customer = relationship("Customer", back_populates="claims")


class PrivacyRequest(Base):
    """Data-principal privacy request preserving statutory commercial records (DB Spec §7.7, CUS-R04)."""
    __tablename__ = "privacy_requests"
    __table_args__ = (
        Index("ix_privacy_requests_tenant_id", "tenant_id"),
        Index("ix_privacy_requests_store_id", "store_id"),
        Index("ix_privacy_requests_customer_id", "customer_id"),
        CheckConstraint(
            "request_type IN ('ACCESS', 'CORRECT', 'DELETE', 'WITHDRAW_CONSENT')",
            name="ck_privacy_request_type",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'IN_REVIEW', 'COMPLETED', 'PARTIAL', 'REJECTED_LEGAL_RETENTION')",
            name="ck_privacy_status",
        ),
        {"schema": "customer"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False)
    store_id = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    customer_id = Column(UUID(as_uuid=True), ForeignKey("customer.customers.id", ondelete="CASCADE"), nullable=False)
    request_type = Column(String(24), nullable=False)
    status = Column(String(32), nullable=False, default="OPEN")
    requested_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    retention_basis = Column(Text, nullable=True)

    customer = relationship("Customer", back_populates="privacy_requests")
