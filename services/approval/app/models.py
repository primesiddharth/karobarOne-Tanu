# app/models.py
from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
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
    __table_args__ = {"schema": "approval"}

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
    producer = Column(String(64), nullable=False, default="approval")
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
    __table_args__ = {"schema": "approval"}

    consumer = Column(String(64), primary_key=True)
    event_id = Column(UUID(as_uuid=True), primary_key=True)
    processed_at = Column(DateTime(timezone=True), nullable=False, default=func.now())


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_approval_idempotency"),
        {"schema": "approval"},
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
# Domain Tables (SERVICES.md §3, DB Schema §7.6, BTDD §9.6)
# ------------------------------------------------------------------------------

class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'TAKEDOWN', 'UNPUBLISHED')",
            name="ck_approval_request_status",
        ),
        {"schema": "approval"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    subject_type = Column(String(40), nullable=False, index=True)
    subject_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    subject_version = Column(String(64), nullable=True)

    status = Column(String(24), nullable=False, default="PENDING", index=True)
    submitted_by = Column(UUID(as_uuid=True), nullable=False, index=True)
    submitted_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    priority = Column(SmallInteger, nullable=False, default=0, index=True)

    # Relationships
    decisions = relationship("ApprovalDecision", back_populates="request", cascade="all, delete-orphan")
    history = relationship("ApprovalStateHistory", back_populates="request", cascade="all, delete-orphan")


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('APPROVE', 'REJECT', 'UNPUBLISH')",
            name="ck_approval_decision_type",
        ),
        {"schema": "approval"},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    approval_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("approval.approval_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    decision = Column(String(20), nullable=False)
    reason_code = Column(String(40), nullable=True, index=True)
    reason_text = Column(Text, nullable=True)
    decided_by = Column(UUID(as_uuid=True), nullable=False, index=True)
    decided_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    evidence_json = Column(JSONB, nullable=False, default=dict)

    request = relationship("ApprovalRequest", back_populates="decisions")


class Takedown(Base):
    __tablename__ = "takedowns"
    __table_args__ = {"schema": "approval"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())

    approval_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("approval.approval_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    subject_type = Column(String(40), nullable=False, index=True)
    subject_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    reason_code = Column(String(40), nullable=False, index=True)
    reason_text = Column(Text, nullable=False)
    executed_by = Column(UUID(as_uuid=True), nullable=False, index=True)
    executed_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    restored_at = Column(DateTime(timezone=True), nullable=True)


class ApprovalStateHistory(Base):
    __tablename__ = "approval_state_history"
    __table_args__ = {"schema": "approval"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    approval_request_id = Column(
        UUID(as_uuid=True),
        ForeignKey("approval.approval_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status = Column(String(24), nullable=False)
    to_status = Column(String(24), nullable=False)
    actor_id = Column(UUID(as_uuid=True), nullable=False)
    reason = Column(Text, nullable=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False, default=func.now())

    request = relationship("ApprovalRequest", back_populates="history")
