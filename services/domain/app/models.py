# app/models.py
from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    DateTime,
    UniqueConstraint,
    CheckConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# ------------------------------------------------------------------------------
# Foundation Tables (RULES.md §5.4)
# ------------------------------------------------------------------------------

class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = {"schema": "domain"}

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
    producer = Column(String(64), nullable=False, default="domain")
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
    __table_args__ = {"schema": "domain"}

    consumer = Column(String(64), primary_key=True)
    event_id = Column(UUID(as_uuid=True), primary_key=True)
    processed_at = Column(DateTime(timezone=True), nullable=False, default=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_domain_idempotency"),
        {"schema": "domain"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(String(64), nullable=False)
    key = Column(String(128), nullable=False)
    request_hash = Column(String(128), nullable=False)
    response_code = Column(Integer, nullable=False)
    response_body = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    locked_until = Column(DateTime(timezone=True), nullable=False)


# ------------------------------------------------------------------------------
# Domain Tables (SERVICES.md §5, DB Schema §7.4, BTDD §9.4, SM §6)
# ------------------------------------------------------------------------------

class Subdomain(Base):
    __tablename__ = "subdomains"
    __table_args__ = (
        UniqueConstraint("label", name="uq_subdomain_label"),
        UniqueConstraint("fqdn", name="uq_subdomain_fqdn"),
        UniqueConstraint("store_id", name="uq_store_subdomain"),
        CheckConstraint(
            "status IN ('ASSIGNED', 'ACTIVE', 'DISABLED')",
            name="ck_subdomain_status",
        ),
        {"schema": "domain"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    label = Column(String(63), nullable=False, index=True)
    fqdn = Column(String(255), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="ASSIGNED", index=True)

    activated_at = Column(DateTime(timezone=True), nullable=True)
    disabled_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())


class PublicationRoute(Base):
    __tablename__ = "publication_routes"
    __table_args__ = (
        CheckConstraint(
            "route_type IN ('FREE_SUBDOMAIN', 'CUSTOM_DOMAIN', 'SYSTEM_PREVIEW')",
            name="ck_publication_route_type",
        ),
        CheckConstraint(
            "status IN ('DISABLED', 'ACTIVE', 'PENDING_DNS', 'SUSPENDED')",
            name="ck_publication_route_status",
        ),
        {"schema": "domain"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    route_type = Column(String(24), nullable=False)
    hostname = Column(String(255), nullable=False, index=True)
    target_revision_id = Column(UUID(as_uuid=True), nullable=True)
    status = Column(String(24), nullable=False, default="DISABLED", index=True)

    activated_at = Column(DateTime(timezone=True), nullable=True)
    deactivated_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())


class DomainRequest(Base):
    __tablename__ = "domain_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PREFERENCE_SUBMITTED', 'AVAILABILITY_CHECKED', 'SELECTED', 'PURCHASE_PENDING', 'PURCHASED', 'DNS_PENDING', 'DNS_VERIFIED', 'ACTIVE', 'STOPPED_FREE_CONVERSION', 'REJECTED')",
            name="ck_domain_request_status",
        ),
        CheckConstraint(
            "cost_class IN ('STANDARD', 'PREMIUM')",
            name="ck_domain_request_cost_class",
        ),
        {"schema": "domain"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    preferred_domains = Column(JSONB, nullable=False, default=list)
    selected_domain = Column(String(255), nullable=True, index=True)
    cost_class = Column(String(24), nullable=False, default="STANDARD")
    price_paise = Column(Integer, nullable=False, default=0)
    approval_ref = Column(String(128), nullable=True)
    payment_ref = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="PREFERENCE_SUBMITTED", index=True)
    version = Column(Integer, nullable=False, default=1)

    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())


class CustomDomain(Base):
    __tablename__ = "domains"
    __table_args__ = (
        UniqueConstraint("domain_name", name="uq_custom_domain_name"),
        CheckConstraint(
            "cost_class IN ('STANDARD', 'PREMIUM')",
            name="ck_domain_cost_class",
        ),
        CheckConstraint(
            "status IN ('PENDING_PURCHASE', 'PURCHASED', 'DNS_PENDING', 'DNS_VERIFIED', 'ACTIVE', 'STOPPED_FREE_CONVERSION', 'TRANSFER_REVIEW')",
            name="ck_domain_status",
        ),
        {"schema": "domain"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    domain_name = Column(String(255), nullable=False, index=True)
    domain_request_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    registrar_code = Column(String(40), nullable=False, default="MOCK_REGISTRAR")
    registrar_reference = Column(String(128), nullable=True, index=True)
    cost_class = Column(String(24), nullable=False, default="STANDARD")
    purchase_cost = Column(Integer, nullable=False, default=0)
    approval_ref = Column(String(128), nullable=True)
    payment_ref = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, default="PENDING_PURCHASE", index=True)

    transfer_review_notes = Column(String(500), nullable=True)
    transfer_review_opened_at = Column(DateTime(timezone=True), nullable=True)

    registered_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())


class DnsCheck(Base):
    __tablename__ = "dns_checks"
    __table_args__ = (
        CheckConstraint(
            "result IN ('PENDING', 'VERIFIED', 'FAILED')",
            name="ck_dns_check_result",
        ),
        {"schema": "domain"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    domain_request_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    check_type = Column(String(16), nullable=False, default="CNAME")
    expected_value = Column(String(255), nullable=False)
    observed_value = Column(String(255), nullable=True)
    result = Column(String(16), nullable=False, default="PENDING")
    checked_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
