# app/models.py
from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
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
    __table_args__ = {"schema": "inventory"}

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
    producer = Column(String(64), nullable=False, default="inventory")
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
    __table_args__ = {"schema": "inventory"}

    consumer = Column(String(64), primary_key=True)
    event_id = Column(UUID(as_uuid=True), primary_key=True)
    processed_at = Column(DateTime(timezone=True), nullable=False, default=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_inventory_idempotency"),
        {"schema": "inventory"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope = Column(String(64), nullable=False)
    key = Column(String(128), nullable=False)
    request_hash = Column(String(128), nullable=False)
    response_code = Column(Integer, nullable=False)
    response_body = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    locked_until = Column(DateTime(timezone=True), nullable=False)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        UniqueConstraint("business_key", name="uq_inventory_scheduled_business_key"),
        {"schema": "inventory"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type = Column(String(64), nullable=False)
    business_key = Column(String(255), nullable=False)
    status = Column(String(24), nullable=False, default="PENDING")
    scheduled_at = Column(DateTime(timezone=True), nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())


# ------------------------------------------------------------------------------
# Inventory Domain Tables (SERVICES.md §8, DB Schema §7.8, BTDD §9.8, SM §9)
# ------------------------------------------------------------------------------

class Sku(Base):
    __tablename__ = "skus"
    __table_args__ = (
        UniqueConstraint("store_id", "sku_code", name="uq_sku_store_code"),
        {"schema": "inventory"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    sku_code = Column(String(64), nullable=True, index=True)
    is_tracked = Column(Boolean, nullable=False, default=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())


class StockBalance(Base):
    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint("store_id", "sku_id", name="uq_stock_balance_store_sku"),
        CheckConstraint("on_hand_qty >= 0", name="ck_stock_balance_on_hand_positive"),
        CheckConstraint(
            "reserved_qty >= 0 AND reserved_qty <= on_hand_qty",
            name="ck_stock_balance_reserved_bounds",
        ),
        {"schema": "inventory"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    sku_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    on_hand_qty = Column(Integer, nullable=False, default=0)
    reserved_qty = Column(Integer, nullable=False, default=0)
    version = Column(BigInteger, nullable=False, default=0)
    last_movement_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    @property
    def available_qty(self) -> int:
        return max(0, self.on_hand_qty - self.reserved_qty)


class StockReservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_reservation_quantity_positive"),
        CheckConstraint(
            "status IN ('ACTIVE', 'CONSUMED', 'RELEASED', 'EXPIRED')",
            name="ck_reservation_status",
        ),
        {"schema": "inventory"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reservation_group_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    checkout_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    sku_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    quantity = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="ACTIVE", index=True)

    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True), nullable=True)
    released_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint(
            "movement_type IN ('OPENING', 'ADJUSTMENT', 'RESERVE', 'RELEASE', 'SALE', 'CANCEL_RESTORE', 'RETURN_RESTORE', 'EXPIRY')",
            name="ck_stock_movement_type",
        ),
        CheckConstraint("quantity_delta <> 0", name="ck_stock_movement_delta_nonzero"),
        {"schema": "inventory"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    sku_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    movement_type = Column(String(32), nullable=False, index=True)
    quantity_delta = Column(Integer, nullable=False)
    reference_type = Column(String(24), nullable=True, index=True)
    reference_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    occurred_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    reason = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())


class InventoryAdjustment(Base):
    __tablename__ = "inventory_adjustments"
    __table_args__ = (
        CheckConstraint(
            "adjustment_type IN ('INCREMENT', 'DECREMENT', 'SET')",
            name="ck_adjustment_type",
        ),
        {"schema": "inventory"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    sku_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    adjustment_type = Column(String(32), nullable=False)
    quantity = Column(Integer, nullable=False)
    reason = Column(String(255), nullable=True)
    actor_id = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
