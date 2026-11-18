# app/models.py
from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    SmallInteger,
    Boolean,
    DateTime,
    Text,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    func,
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
    __table_args__ = {"schema": "catalog"}

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
    producer = Column(String(64), nullable=False, default="catalog")
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
    __table_args__ = {"schema": "catalog"}

    consumer = Column(String(64), primary_key=True)
    event_id = Column(UUID(as_uuid=True), primary_key=True)
    processed_at = Column(DateTime(timezone=True), nullable=False, default=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_catalog_idempotency"),
        {"schema": "catalog"},
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
# Domain Tables (SERVICES.md §4, DB Schema §7.5, BTDD §9.5 & §14)
# ------------------------------------------------------------------------------

class CatalogItem(Base):
    __tablename__ = "catalog_items"
    __table_args__ = (
        CheckConstraint(
            "item_type IN ('PHYSICAL_PRODUCT', 'DIGITAL_PRODUCT', 'APPOINTMENT_SERVICE', 'NON_APPOINTMENT_SERVICE')",
            name="ck_catalog_item_type",
        ),
        {"schema": "catalog"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    item_type = Column(String(32), nullable=False, index=True)

    # Operational fields (APR-R02: change without approval)
    price_paise = Column(BigInteger, nullable=False, default=0)
    currency_code = Column(String(3), nullable=False, default="INR")
    active = Column(Boolean, nullable=False, default=True, index=True)

    # Version references
    live_version_id = Column(UUID(as_uuid=True), nullable=True)
    draft_version_id = Column(UUID(as_uuid=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    # Relationships
    versions = relationship("ItemVersion", back_populates="item", cascade="all, delete-orphan", foreign_keys="ItemVersion.item_id")
    product_details = relationship("ProductDetails", back_populates="item", uselist=False, cascade="all, delete-orphan")
    service_details = relationship("ServiceDetails", back_populates="item", uselist=False, cascade="all, delete-orphan")


class ItemVersion(Base):
    __tablename__ = "item_versions"
    __table_args__ = (
        CheckConstraint(
            "approval_state IN ('DRAFT', 'PENDING', 'APPROVED_LIVE', 'REJECTED', 'UNPUBLISHED', 'EMERGENCY_TAKEDOWN')",
            name="ck_item_version_approval_state",
        ),
        {"schema": "catalog"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.catalog_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    version_no = Column(Integer, nullable=False, default=1)

    # Controlled fields (require APR approval)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    category_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    approval_state = Column(String(32), nullable=False, default="DRAFT", index=True)
    approval_request_id = Column(UUID(as_uuid=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    item = relationship("CatalogItem", back_populates="versions", foreign_keys=[item_id])
    media = relationship("ItemMedia", back_populates="version", cascade="all, delete-orphan")


class ProductDetails(Base):
    __tablename__ = "product_details"
    __table_args__ = {"schema": "catalog"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.catalog_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    is_digital = Column(Boolean, nullable=False, default=False)
    sku_code = Column(String(64), nullable=True)

    item = relationship("CatalogItem", back_populates="product_details")


class ServiceDetails(Base):
    __tablename__ = "service_details"
    __table_args__ = {"schema": "catalog"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.catalog_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    is_appointment = Column(Boolean, nullable=False, default=False)
    duration_minutes = Column(Integer, nullable=True)

    item = relationship("CatalogItem", back_populates="service_details")


class ItemMedia(Base):
    __tablename__ = "item_media"
    __table_args__ = (
        CheckConstraint("media_type IN ('IMAGE', 'VIDEO')", name="ck_item_media_type"),
        {"schema": "catalog"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("catalog.item_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    media_type = Column(String(16), nullable=False)
    storage_key = Column(String(512), nullable=False)
    url = Column(String(1024), nullable=False)
    sort_order = Column(SmallInteger, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    version = relationship("ItemVersion", back_populates="media")


class StoreContentVersion(Base):
    """
    catalog.store_content_versions per DB Schema Spec §7.5 text (BR-075; BR-210..216).
    Versioned Hero/About/USP/Contact/Policy/Marquee/page content.
    """
    __tablename__ = "store_content_versions"
    __table_args__ = (
        UniqueConstraint("store_id", "content_section", "version_no", name="uq_store_content_section_version"),
        CheckConstraint(
            "approval_state IN ('DRAFT', 'PENDING', 'APPROVED_LIVE', 'REJECTED', 'EMERGENCY_TAKEDOWN')",
            name="ck_store_content_approval_state",
        ),
        {"schema": "catalog"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    content_section = Column(String(32), nullable=False, index=True)
    version_no = Column(Integer, nullable=False)
    content_json = Column(JSONB, nullable=False, default=dict)
    approval_state = Column(String(32), nullable=False, default="DRAFT", index=True)
    content_hash = Column(String(64), nullable=False, index=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())


class EntitlementProjection(Base):
    __tablename__ = "entitlement_projection"
    __table_args__ = {"schema": "catalog"}

    store_id = Column(UUID(as_uuid=True), primary_key=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    plan_tier = Column(String(32), nullable=False, default="FREE")

    max_items = Column(Integer, nullable=False, default=6)
    max_images_per_item = Column(Integer, nullable=False, default=1)
    max_videos_per_item = Column(Integer, nullable=False, default=0)
    blog_enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
