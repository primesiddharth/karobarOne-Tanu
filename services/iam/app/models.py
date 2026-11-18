# app/models.py
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import DateTime, UniqueConstraint, CheckConstraint, String, Integer, Boolean, ForeignKey, Index, text


class Base(DeclarativeBase):
    pass


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = {"schema": "iam"}

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
    producer: Mapped[str] = mapped_column(String(64), nullable=False, default="iam")
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
    __table_args__ = {"schema": "iam"}

    consumer: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_iam_idempotency"),
        {"schema": "iam"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    response_code: Mapped[int] = mapped_column(nullable=False)
    response_body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    locked_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Principal(Base):
    __tablename__ = "principals"
    __table_args__ = (
        Index("idx_iam_principals_lower_email", text("lower(email)"), unique=True, postgresql_where=text("email IS NOT NULL")),
        Index("idx_iam_principals_mobile", "mobile_e164", unique=True, postgresql_where=text("mobile_e164 IS NOT NULL")),
        CheckConstraint("principal_type IN ('USER', 'SERVICE')", name="chk_principal_type"),
        CheckConstraint("status IN ('ACTIVE', 'LOCKED', 'DISABLED', 'PENDING_VERIFICATION')", name="chk_principal_status"),
        {"schema": "iam"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    principal_type: Mapped[str] = mapped_column(String(24), default="USER", nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mobile_e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="ACTIVE", nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mobile_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    credentials: Mapped[list["Credential"]] = relationship(back_populates="principal", cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship(back_populates="principal", cascade="all, delete-orphan")
    role_assignments: Mapped[list["RoleAssignment"]] = relationship(back_populates="principal", cascade="all, delete-orphan")


class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = (
        CheckConstraint("algorithm IN ('argon2id', 'bcrypt')", name="chk_credential_algorithm"),
        {"schema": "iam"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    principal_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("iam.principals.id", ondelete="CASCADE"), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    algorithm: Mapped[str] = mapped_column(String(24), default="argon2id", nullable=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    must_rotate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    principal: Mapped["Principal"] = relationship(back_populates="credentials")


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = {"schema": "iam"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    principal_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("iam.principals.id", ondelete="CASCADE"), nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    principal: Mapped["Principal"] = relationship(back_populates="sessions")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_iam_refresh_token_hash"),
        {"schema": "iam"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("iam.sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    replaced_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("iam.refresh_tokens.id"), nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    session: Mapped["Session"] = relationship(back_populates="refresh_tokens")


class RoleAssignment(Base):
    __tablename__ = "role_assignments"
    __table_args__ = (
        CheckConstraint(
            """
            (role_code IN ('PLATFORM_OWNER', 'PLATFORM_STAFF', 'GST_STAFF') AND tenant_id IS NULL AND store_id IS NULL)
            OR (role_code = 'STORE_OWNER' AND tenant_id IS NOT NULL AND store_id IS NULL)
            OR (role_code = 'STORE_STAFF' AND tenant_id IS NOT NULL AND store_id IS NOT NULL)
            OR (role_code = 'GUARDIAN' AND tenant_id IS NOT NULL AND store_id IS NULL)
            OR (role_code = 'CUSTOMER' AND store_id IS NOT NULL)
            OR (role_code = 'SERVICE' AND tenant_id IS NULL AND store_id IS NULL)
            """,
            name="chk_role_scope_validity",
        ),
        {"schema": "iam"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    principal_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("iam.principals.id", ondelete="CASCADE"), nullable=False, index=True)
    role_code: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    tenant_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    store_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    principal: Mapped["Principal"] = relationship(back_populates="role_assignments")


class OtpChallenge(Base):
    __tablename__ = "otp_challenges"
    __table_args__ = (
        CheckConstraint("channel IN ('EMAIL', 'SMS')", name="chk_otp_channel"),
        CheckConstraint("purpose IN ('ACCOUNT_CLAIM', 'STEP_UP_AUTH', 'VERIFICATION')", name="chk_otp_purpose"),
        {"schema": "iam"},
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    principal_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("iam.principals.id", ondelete="CASCADE"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    destination_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    otp_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = {"schema": "iam"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    principal_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("iam.principals.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(24), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    correlation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
