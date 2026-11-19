# app/models.py
# Authoritative models for tenant schema per DB Schema Spec §7.2 and SERVICES.md §2.
# Strict schema isolation: all tables live in schema "tenant".
from datetime import datetime, timezone, date
from uuid import UUID, uuid4
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import (
    DateTime, Date, UniqueConstraint, CheckConstraint, String,
    Boolean, ForeignKey, Index, LargeBinary, text
)


class Base(DeclarativeBase):
    pass


# -----------------------------------------------------------------------------
# Foundation Tables (RULES.md §5.4 & §6)
# -----------------------------------------------------------------------------
class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = {"schema": "tenant"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_version: Mapped[int] = mapped_column(default=1, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    store_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    causation_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    producer: Mapped[str] = mapped_column(String(64), nullable=False, default="tenant")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead: Mapped[bool] = mapped_column(default=False, nullable=False)


class ProcessedEvent(Base):
    __tablename__ = "processed_events"
    __table_args__ = {"schema": "tenant"}

    consumer: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_tenant_idempotency"),
        {"schema": "tenant"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    response_code: Mapped[int] = mapped_column(nullable=False)
    response_body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    locked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# -----------------------------------------------------------------------------
# Tenant Core Aggregate (DB Schema §7.2, SM §4, RULES.md §5.10)
# -----------------------------------------------------------------------------
class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("pan_fingerprint", name="uq_tenant_pan_fingerprint"),
        CheckConstraint("tenant_type IN ('INDIVIDUAL', 'BUSINESS', 'OTHER')", name="chk_tenant_type"),
        CheckConstraint(
            "minor_status IN ('NOT_MINOR', 'GUARDIAN_REQUIRED', 'GUARDIAN_VERIFICATION', 'CONSENT_ACCEPTED', 'MINOR_TENANT_ACTIVE', 'ADULT_REVERIFICATION_REQUIRED')",
            name="chk_tenant_minor_status",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'SUSPENDED', 'TERMINATED', 'ARCHIVED')",
            name="chk_tenant_status",
        ),
        {"schema": "tenant"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    pan_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    pan_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    pan_masked: Mapped[str] = mapped_column(String(16), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    tenant_type: Mapped[str] = mapped_column(String(24), nullable=False, default="INDIVIDUAL")
    minor_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NOT_MINOR", index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="PENDING", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    pan_verifications: Mapped[list["PanVerification"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    guardians: Mapped[list["Guardian"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    guardian_consents: Mapped[list["GuardianConsent"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    gstins: Mapped[list["Gstin"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    stores: Mapped[list["Store"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    free_store_entitlement: Mapped["FreeStoreEntitlement | None"] = relationship(back_populates="tenant", uselist=False, cascade="all, delete-orphan")


class PanVerification(Base):
    __tablename__ = "pan_verifications"
    __table_args__ = {"schema": "tenant"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_code: Mapped[str] = mapped_column(String(32), default="MOCK_V1", nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    verified_name: Mapped[str] = mapped_column(String(200), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="pan_verifications")


# -----------------------------------------------------------------------------
# Guardian & Minor Compliance Aggregate (DB Schema §7.2, SM §4, AC-035..040)
# -----------------------------------------------------------------------------
class Guardian(Base):
    __tablename__ = "guardians"
    __table_args__ = (
        CheckConstraint("relationship_code IN ('PARENT', 'LEGAL_GUARDIAN')", name="chk_guardian_relationship"),
        CheckConstraint("verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')", name="chk_guardian_verification_status"),
        {"schema": "tenant"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    principal_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    relationship_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    mobile_e164: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    verification_status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="guardians")
    consents: Mapped[list["GuardianConsent"]] = relationship(back_populates="guardian", cascade="all, delete-orphan")


class GuardianConsent(Base):
    __tablename__ = "guardian_consents"
    __table_args__ = {"schema": "tenant"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    guardian_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.guardians.id", ondelete="CASCADE"), nullable=False, index=True)
    consent_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    document_code: Mapped[str] = mapped_column(String(64), nullable=False)
    document_version: Mapped[str] = mapped_column(String(32), nullable=False)
    document_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    acceptance_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="guardian_consents")
    guardian: Mapped["Guardian"] = relationship(back_populates="consents")


# -----------------------------------------------------------------------------
# GSTIN Aggregate (DB Schema §7.2, AC-008..010, AC-036/037)
# -----------------------------------------------------------------------------
class Gstin(Base):
    __tablename__ = "gstins"
    __table_args__ = (
        UniqueConstraint("gstin_fingerprint", name="uq_tenant_gstin_fingerprint"),
        CheckConstraint("verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')", name="chk_gstin_verification_status"),
        {"schema": "tenant"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    gstin_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    gstin_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    gstin_masked: Mapped[str] = mapped_column(String(20), nullable=False)
    state_code: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False, index=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="gstins")
    verifications: Mapped[list["GstinVerification"]] = relationship(back_populates="gstin", cascade="all, delete-orphan")


class GstinVerification(Base):
    __tablename__ = "gstin_verifications"
    __table_args__ = {"schema": "tenant"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    gstin_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.gstins.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_code: Mapped[str] = mapped_column(String(32), default="MOCK_V1", nullable=False)
    provider_reference: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    verified_pan_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    gstin: Mapped["Gstin"] = relationship(back_populates="verifications")


# -----------------------------------------------------------------------------
# Store & Free Entitlement Aggregate (DB Schema §7.2, SM §5, AC-002)
# -----------------------------------------------------------------------------
class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (
        UniqueConstraint("store_code", name="uq_tenant_store_code"),
        CheckConstraint("store_mode IN ('FREE_PRESENCE', 'PAID_COMMERCE')", name="chk_store_mode"),
        CheckConstraint(
            "lifecycle_status IN ('DRAFT', 'REVIEW', 'ACTIVE', 'PAYMENT_GRACE', 'SUBSCRIPTION_EXPIRED', 'SUSPENDED', 'ARCHIVED', 'TERMINATED')",
            name="chk_store_lifecycle_status",
        ),
        # Partial unique index: One active paid store per GSTIN (AC-008/009)
        Index("uq_active_store_gstin_store", "gstin_id", unique=True, postgresql_where=text("gstin_id IS NOT NULL AND archived_at IS NULL")),
        {"schema": "tenant"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    store_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    store_mode: Mapped[str] = mapped_column(String(24), default="FREE_PRESENCE", nullable=False, index=True)
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False, index=True)
    gstin_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.gstins.id", ondelete="SET NULL"), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata", nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="stores")
    memberships: Mapped[list["StoreMembership"]] = relationship(back_populates="store", cascade="all, delete-orphan")


class FreeStoreEntitlement(Base):
    __tablename__ = "free_store_entitlements"
    __table_args__ = (
        CheckConstraint("status IN ('AVAILABLE', 'CONSUMED')", name="chk_free_store_entitlement_status"),
        Index("uq_free_entitlement_consumed_store", "consumed_store_id", unique=True, postgresql_where=text("consumed_store_id IS NOT NULL")),
        {"schema": "tenant"},
    )

    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.tenants.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="AVAILABLE", nullable=False)
    consumed_store_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.stores.id", ondelete="SET NULL"), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="free_store_entitlement")


class StoreMembership(Base):
    __tablename__ = "store_memberships"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="chk_membership_status"),
        {"schema": "tenant"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    store_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.stores.id", ondelete="CASCADE"), nullable=False, index=True)
    principal_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    role_code: Mapped[str] = mapped_column(String(40), default="STORE_STAFF", nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False, index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    store: Mapped["Store"] = relationship(back_populates="memberships")


class SellerIdentitySnapshot(Base):
    __tablename__ = "seller_identity_snapshots"
    __table_args__ = {"schema": "tenant"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    store_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.stores.id", ondelete="CASCADE"), nullable=False, index=True)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    pan_masked: Mapped[str] = mapped_column(String(16), nullable=False)
    gstin_masked: Mapped[str | None] = mapped_column(String(20), nullable=True)
    snapshotted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class StoreGstinAssignment(Base):
    __tablename__ = "store_gstin_assignments"
    __table_args__ = (
        # Partial UNIQUE on gstin_id: same GSTIN cannot actively back two paid stores (AC-008..010)
        Index("uq_active_store_gstin_assignment", "gstin_id", unique=True, postgresql_where=text("released_at IS NULL")),
        # Partial UNIQUE on store_id: one store can only hold one active GSTIN assignment at once
        Index("uq_active_store_assignment", "store_id", unique=True, postgresql_where=text("released_at IS NULL")),
        {"schema": "tenant"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    store_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.stores.id", ondelete="CASCADE"), nullable=False, index=True)
    gstin_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("tenant.gstins.id", ondelete="CASCADE"), nullable=False, index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
