# app/commands.py
# Plain transaction functions implementing named business commands (RULES.md §4).
# No abstraction layers, repositories, or unit-of-work classes.
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession
from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from .config import settings
from . import domain
from . import models
from . import clients
from .events import add_event


async def register_principal_command(
    session: AsyncSession,
    email: str,
    password: str,
    mobile_e164: str | None = None,
    correlation_id: UUID | None = None,
) -> dict:
    """Registers a new user principal and credentials; enumeration resistant (OQ-006 & Security §6.1)."""
    norm_email = email.strip().lower()
    corr = correlation_id or uuid4()

    # Check for existing email (enumeration resistance: return generic success if already registered)
    existing = await session.execute(
        select(models.Principal).where(text("lower(email) = lower(:email)")),
        {"email": norm_email}
    )
    existing_principal = existing.scalars().first()
    if existing_principal:
        return {
            "principal_id": existing_principal.id,
            "email": norm_email,
            "status": existing_principal.status,
        }

    principal_id = uuid4()
    now = datetime.now(timezone.utc)
    hashed_pwd = domain.hash_password_argon2(password)

    new_principal = models.Principal(
        id=principal_id,
        principal_type="USER",
        email=norm_email,
        mobile_e164=mobile_e164,
        status="ACTIVE",
        created_at=now,
        updated_at=now,
    )
    session.add(new_principal)

    new_credential = models.Credential(
        id=uuid4(),
        principal_id=principal_id,
        password_hash=hashed_pwd,
        algorithm="argon2id",
        password_version=1,
        failed_attempts=0,
        changed_at=now,
    )
    session.add(new_credential)

    # Emit canonical identity.principal.created.v1 event
    await add_event(
        session=session,
        event_type="identity.principal.created.v1",
        aggregate_type="Principal",
        aggregate_id=principal_id,
        payload={"principal_id": str(principal_id), "email": norm_email, "principal_type": "USER"},
        topic="identity.lifecycle",
        correlation_id=corr,
    )

    # Append-only security audit event
    sec_event = models.SecurityEvent(
        id=uuid4(),
        principal_id=principal_id,
        event_type="PRINCIPAL_REGISTERED",
        result="SUCCESS",
        correlation_id=corr,
        occurred_at=now,
        details={"email": norm_email},
    )
    session.add(sec_event)

    return {
        "principal_id": principal_id,
        "email": norm_email,
        "status": "ACTIVE",
    }


async def login_command(
    session: AsyncSession,
    email: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
    correlation_id: UUID | None = None,
) -> dict:
    """Authenticates principal; supports transparent bcrypt verify-then-rehash to Argon2id (IAM-001)."""
    norm_email = email.strip().lower()
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()

    # Query principal & credential
    query = (
        select(models.Principal, models.Credential)
        .join(models.Credential, models.Credential.principal_id == models.Principal.id)
        .where(text("lower(iam.principals.email) = lower(:email)"))
    )
    result = await session.execute(query, {"email": norm_email})
    row = result.first()

    if not row:
        sec_event = models.SecurityEvent(
            id=uuid4(),
            principal_id=None,
            event_type="LOGIN_ATTEMPT",
            result="FAILURE",
            ip_address=ip_address,
            user_agent=user_agent,
            correlation_id=corr,
            occurred_at=now,
            details={"email": norm_email, "reason": "PRINCIPAL_NOT_FOUND"},
        )
        session.add(sec_event)
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Invalid email or password", status_code=401)

    principal, credential = row

    if credential.locked_until and credential.locked_until > now:
        sec_event = models.SecurityEvent(
            id=uuid4(),
            principal_id=principal.id,
            event_type="LOGIN_ATTEMPT",
            result="LOCKED",
            ip_address=ip_address,
            user_agent=user_agent,
            correlation_id=corr,
            occurred_at=now,
            details={"email": norm_email, "locked_until": credential.locked_until.isoformat()},
        )
        session.add(sec_event)
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Account is temporarily locked due to failed attempts", status_code=401)

    is_valid, needs_rehash = domain.verify_password(password, credential.password_hash, credential.algorithm)

    if not is_valid:
        credential.failed_attempts += 1
        if credential.failed_attempts >= 5:
            credential.locked_until = now + timedelta(minutes=15)
        sec_event = models.SecurityEvent(
            id=uuid4(),
            principal_id=principal.id,
            event_type="LOGIN_ATTEMPT",
            result="FAILURE",
            ip_address=ip_address,
            user_agent=user_agent,
            correlation_id=corr,
            occurred_at=now,
            details={"email": norm_email, "failed_attempts": credential.failed_attempts},
        )
        session.add(sec_event)
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Invalid email or password", status_code=401)

    # Password verified! Reset failed attempts
    credential.failed_attempts = 0
    credential.locked_until = None
    principal.last_login_at = now

    # Transparent re-hash from legacy bcrypt to Argon2id (OQ-008 & Monolith Audit §2.2)
    if needs_rehash or credential.algorithm == "bcrypt":
        credential.password_hash = domain.hash_password_argon2(password)
        credential.algorithm = "argon2id"
        credential.changed_at = now

    # Load active role assignments
    role_query = (
        select(models.RoleAssignment)
        .where(
            models.RoleAssignment.principal_id == principal.id,
            models.RoleAssignment.revoked_at.is_(None),
            (models.RoleAssignment.valid_until.is_(None) | (models.RoleAssignment.valid_until > now)),
        )
    )
    role_rows = (await session.execute(role_query)).scalars().all()
    roles = list({r.role_code for r in role_rows})
    if not roles:
        roles = ["STORE_OWNER"]
    tenant_ids = [r.tenant_id for r in role_rows if r.tenant_id is not None]
    store_ids = [r.store_id for r in role_rows if r.store_id is not None]

    # Create session
    session_id = uuid4()
    session_exp = now + timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS)
    new_session = models.Session(
        id=session_id,
        principal_id=principal.id,
        issued_at=now,
        expires_at=session_exp,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(new_session)

    # Create refresh token (stored as hash in iam.refresh_tokens)
    raw_refresh_token = domain.generate_secure_refresh_token()
    token_hash = domain.hash_token(raw_refresh_token)
    new_refresh = models.RefreshToken(
        id=uuid4(),
        session_id=session_id,
        token_hash=token_hash,
        expires_at=session_exp,
        created_at=now,
    )
    session.add(new_refresh)

    # Issue RS256 access JWT
    access_token = domain.issue_access_jwt(
        principal_id=principal.id,
        session_id=session_id,
        roles=roles,
        tenant_ids=tenant_ids,
        store_ids=store_ids,
        private_key_pem=settings.JWT_PRIVATE_KEY,
        kid=settings.JWT_KID,
        issuer=settings.ISSUER,
        audience=settings.AUDIENCE,
        ttl_seconds=settings.ACCESS_TOKEN_TTL_SECONDS,
    )

    # Audit login success
    sec_event = models.SecurityEvent(
        id=uuid4(),
        principal_id=principal.id,
        event_type="LOGIN_SUCCESS",
        result="SUCCESS",
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=corr,
        occurred_at=now,
        details={"session_id": str(session_id)},
    )
    session.add(sec_event)

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh_token,
        "token_type": "Bearer",
        "expires_in": settings.ACCESS_TOKEN_TTL_SECONDS,
    }


async def refresh_session_command(
    session: AsyncSession,
    raw_refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
    correlation_id: UUID | None = None,
) -> dict:
    """Rotates refresh token; detecting replay revokes the entire session (IAM-002, SEC-TST-007)."""
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()
    presented_hash = domain.hash_token(raw_refresh_token)

    # Look up refresh token with row lock
    query = (
        select(models.RefreshToken, models.Session)
        .join(models.Session, models.Session.id == models.RefreshToken.session_id)
        .where(models.RefreshToken.token_hash == presented_hash)
        .with_for_update()
    )
    result = await session.execute(query)
    row = result.first()

    if not row:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Invalid or unrecognized refresh token", status_code=401)

    refresh_token_row, session_row = row

    # SEC-TST-007: Check for token reuse / replay
    if refresh_token_row.used_at is not None:
        # REFRESH TOKEN REPLAY DETECTED! Immediately revoke the whole session
        session_row.revoked_at = now
        sec_event = models.SecurityEvent(
            id=uuid4(),
            principal_id=session_row.principal_id,
            event_type="REFRESH_REPLAY",
            result="REVOKED",
            ip_address=ip_address,
            user_agent=user_agent,
            correlation_id=corr,
            occurred_at=now,
            details={"session_id": str(session_row.id), "token_id": str(refresh_token_row.id)},
        )
        session.add(sec_event)
        await add_event(
            session=session,
            event_type="identity.session.revoked.v1",
            aggregate_type="Session",
            aggregate_id=session_row.id,
            payload={"session_id": str(session_row.id), "reason": "REFRESH_TOKEN_REPLAY"},
            topic="identity.lifecycle",
            correlation_id=corr,
        )
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Refresh token replay detected. Session revoked.", status_code=401)

    # Check if session was already revoked or expired
    if session_row.revoked_at is not None or refresh_token_row.expires_at < now:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Session has expired or been revoked", status_code=401)

    # Load active roles
    role_query = (
        select(models.RoleAssignment)
        .where(
            models.RoleAssignment.principal_id == session_row.principal_id,
            models.RoleAssignment.revoked_at.is_(None),
            (models.RoleAssignment.valid_until.is_(None) | (models.RoleAssignment.valid_until > now)),
        )
    )
    role_rows = (await session.execute(role_query)).scalars().all()
    roles = list({r.role_code for r in role_rows})
    if not roles:
        roles = ["STORE_OWNER"]
    tenant_ids = [r.tenant_id for r in role_rows if r.tenant_id is not None]
    store_ids = [r.store_id for r in role_rows if r.store_id is not None]

    # Generate new refresh token and rotate
    new_raw_refresh = domain.generate_secure_refresh_token()
    new_token_hash = domain.hash_token(new_raw_refresh)
    new_exp = now + timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS)

    new_refresh_row = models.RefreshToken(
        id=uuid4(),
        session_id=session_row.id,
        token_hash=new_token_hash,
        expires_at=new_exp,
        created_at=now,
    )
    session.add(new_refresh_row)

    # Mark current token used and linked to replacement
    refresh_token_row.used_at = now
    refresh_token_row.replaced_by = new_refresh_row.id

    # Issue new access JWT
    access_token = domain.issue_access_jwt(
        principal_id=session_row.principal_id,
        session_id=session_row.id,
        roles=roles,
        tenant_ids=tenant_ids,
        store_ids=store_ids,
        private_key_pem=settings.JWT_PRIVATE_KEY,
        kid=settings.JWT_KID,
        issuer=settings.ISSUER,
        audience=settings.AUDIENCE,
        ttl_seconds=settings.ACCESS_TOKEN_TTL_SECONDS,
    )

    sec_event = models.SecurityEvent(
        id=uuid4(),
        principal_id=session_row.principal_id,
        event_type="REFRESH_SUCCESS",
        result="SUCCESS",
        ip_address=ip_address,
        user_agent=user_agent,
        correlation_id=corr,
        occurred_at=now,
        details={"session_id": str(session_row.id)},
    )
    session.add(sec_event)

    return {
        "access_token": access_token,
        "refresh_token": new_raw_refresh,
        "token_type": "Bearer",
        "expires_in": settings.ACCESS_TOKEN_TTL_SECONDS,
    }


async def logout_command(
    session: AsyncSession,
    principal_id: UUID,
    session_id: UUID | None,
    correlation_id: UUID | None = None,
) -> dict:
    """Revokes active session (IAM-003)."""
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()

    if session_id:
        sess = await session.get(models.Session, session_id)
        if sess and sess.principal_id == principal_id and sess.revoked_at is None:
            sess.revoked_at = now
            await add_event(
                session=session,
                event_type="identity.session.revoked.v1",
                aggregate_type="Session",
                aggregate_id=session_id,
                payload={"session_id": str(session_id), "principal_id": str(principal_id)},
                topic="identity.lifecycle",
                correlation_id=corr,
            )
            sec_event = models.SecurityEvent(
                id=uuid4(),
                principal_id=principal_id,
                event_type="LOGOUT",
                result="SUCCESS",
                correlation_id=corr,
                occurred_at=now,
                details={"session_id": str(session_id)},
            )
            session.add(sec_event)

    return {"status": "revoked"}


async def create_otp_challenge_command(
    session: AsyncSession,
    channel: str,
    destination: str,
    purpose: str,
    principal_id: UUID | None = None,
    correlation_id: UUID | None = None,
) -> dict:
    """Creates hashed OTP challenge; enforces database-backed rate limit (IAM-004, SEC-TST-008)."""
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()
    fingerprint = domain.compute_destination_fingerprint(destination, settings.HMAC_SECRET_KEY)

    # Database-backed rate limiting per contact window
    window_start = now - timedelta(seconds=settings.OTP_RATE_LIMIT_SECONDS)
    rate_query = (
        select(models.OtpChallenge)
        .where(
            models.OtpChallenge.destination_fingerprint == fingerprint,
            models.OtpChallenge.created_at >= window_start,
        )
    )
    recent_challenges = (await session.execute(rate_query)).scalars().all()
    if len(recent_challenges) >= settings.OTP_MAX_CHALLENGES_PER_WINDOW:
        raise ApiError(ErrorCode.RATE_LIMITED, "Too many OTP challenges requested. Please wait before retrying.", status_code=429)

    challenge_id = uuid4()
    otp_code = domain.generate_secure_otp(length=6)
    otp_hash = domain.hash_otp(otp_code)
    exp = now + timedelta(seconds=settings.OTP_TTL_SECONDS)

    new_challenge = models.OtpChallenge(
        id=challenge_id,
        principal_id=principal_id,
        channel=channel,
        destination_fingerprint=fingerprint,
        purpose=purpose,
        otp_hash=otp_hash,
        expires_at=exp,
        attempt_count=0,
        created_at=now,
    )
    session.add(new_challenge)

    # Dispatch notification through stub (plain OTP never emitted to logs or event tables)
    await clients.send_otp_notification(destination=destination, otp_code=otp_code, purpose=purpose)

    sec_event = models.SecurityEvent(
        id=uuid4(),
        principal_id=principal_id,
        event_type="OTP_CHALLENGE_CREATED",
        result="SUCCESS",
        correlation_id=corr,
        occurred_at=now,
        details={"challenge_id": str(challenge_id), "channel": channel, "purpose": purpose},
    )
    session.add(sec_event)

    return {
        "challenge_id": challenge_id,
        "channel": channel,
        "purpose": purpose,
        "expires_at": exp,
    }


async def verify_otp_challenge_command(
    session: AsyncSession,
    challenge_id: UUID,
    otp_code: str,
    correlation_id: UUID | None = None,
) -> dict:
    """Verifies OTP challenge; enforces attempt caps and single-use semantics (IAM-005, SEC-TST-008)."""
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()

    challenge = await session.get(models.OtpChallenge, challenge_id, with_for_update=True)
    if not challenge:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Invalid challenge identifier", status_code=404)

    if challenge.consumed_at is not None:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "OTP challenge has already been verified", status_code=409)

    if challenge.expires_at < now:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "OTP challenge has expired", status_code=409)

    if challenge.attempt_count >= settings.OTP_ATTEMPT_LIMIT:
        raise ApiError(ErrorCode.RATE_LIMITED, "Maximum verification attempts exceeded for this challenge", status_code=429)

    challenge.attempt_count += 1
    submitted_hash = domain.hash_otp(otp_code)

    if challenge.otp_hash != submitted_hash:
        sec_event = models.SecurityEvent(
            id=uuid4(),
            principal_id=challenge.principal_id,
            event_type="OTP_VERIFY_FAILURE",
            result="FAILURE",
            correlation_id=corr,
            occurred_at=now,
            details={"challenge_id": str(challenge_id), "attempts": challenge.attempt_count},
        )
        session.add(sec_event)
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Incorrect OTP code", status_code=401)

    # Success: mark challenge consumed (single-use)
    challenge.consumed_at = now

    await add_event(
        session=session,
        event_type="identity.otp.verified.v1",
        aggregate_type="OtpChallenge",
        aggregate_id=challenge_id,
        payload={"challenge_id": str(challenge_id), "purpose": challenge.purpose},
        topic="identity.lifecycle",
        correlation_id=corr,
    )

    sec_event = models.SecurityEvent(
        id=uuid4(),
        principal_id=challenge.principal_id,
        event_type="OTP_VERIFY_SUCCESS",
        result="SUCCESS",
        correlation_id=corr,
        occurred_at=now,
        details={"challenge_id": str(challenge_id), "purpose": challenge.purpose},
    )
    session.add(sec_event)

    return {
        "challenge_id": challenge_id,
        "verified": True,
        "purpose": challenge.purpose,
    }


async def grant_role_assignment_command(
    session: AsyncSession,
    current_principal: Principal,
    target_principal_id: UUID,
    role_code: str,
    tenant_id: UUID | None = None,
    store_id: UUID | None = None,
    valid_until: datetime | None = None,
    correlation_id: UUID | None = None,
) -> models.RoleAssignment:
    """Grants scoped role assignment enforcing role check constraints and platform MFA (IAM-007)."""
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()

    # Privilege check: only platform staff/owner can grant roles
    if not (current_principal.has_role("PLATFORM_OWNER") or current_principal.has_role("PLATFORM_STAFF")):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Only platform administrators can assign roles", status_code=403)

    # Enforce platform admin MFA hook
    domain.assert_platform_admin_mfa(current_principal.roles)

    # Enforce scope check constraints
    try:
        domain.validate_role_assignment_scope(role_code, tenant_id, store_id)
    except ValueError as e:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, str(e), status_code=400)

    # Ensure target principal exists
    target = await session.get(models.Principal, target_principal_id)
    if not target:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Target principal does not exist", status_code=404)

    assignment_id = uuid4()
    assignment = models.RoleAssignment(
        id=assignment_id,
        principal_id=target_principal_id,
        role_code=role_code,
        tenant_id=tenant_id,
        store_id=store_id,
        valid_from=now,
        valid_until=valid_until,
        granted_by=current_principal.sub,
        revoked_at=None,
    )
    session.add(assignment)

    await add_event(
        session=session,
        event_type="identity.role-assigned.v1",
        aggregate_type="RoleAssignment",
        aggregate_id=assignment_id,
        payload={
            "assignment_id": str(assignment_id),
            "principal_id": str(target_principal_id),
            "role_code": role_code,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "store_id": str(store_id) if store_id else None,
        },
        topic="identity.lifecycle",
        correlation_id=corr,
    )

    sec_event = models.SecurityEvent(
        id=uuid4(),
        principal_id=current_principal.sub,
        event_type="ROLE_ASSIGNED",
        result="SUCCESS",
        correlation_id=corr,
        occurred_at=now,
        details={"assignment_id": str(assignment_id), "target_principal_id": str(target_principal_id), "role_code": role_code},
    )
    session.add(sec_event)

    return assignment


async def revoke_role_assignment_command(
    session: AsyncSession,
    current_principal: Principal,
    assignment_id: UUID,
    correlation_id: UUID | None = None,
) -> dict:
    """Revokes active role assignment (IAM-008)."""
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()

    if not (current_principal.has_role("PLATFORM_OWNER") or current_principal.has_role("PLATFORM_STAFF")):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Only platform administrators can revoke roles", status_code=403)

    assignment = await session.get(models.RoleAssignment, assignment_id, with_for_update=True)
    if not assignment or assignment.revoked_at is not None:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Role assignment not found or already revoked", status_code=404)

    assignment.revoked_at = now

    await add_event(
        session=session,
        event_type="identity.role-revoked.v1",
        aggregate_type="RoleAssignment",
        aggregate_id=assignment_id,
        payload={"assignment_id": str(assignment_id), "principal_id": str(assignment.principal_id), "role_code": assignment.role_code},
        topic="identity.lifecycle",
        correlation_id=corr,
    )

    sec_event = models.SecurityEvent(
        id=uuid4(),
        principal_id=current_principal.sub,
        event_type="ROLE_REVOKED",
        result="SUCCESS",
        correlation_id=corr,
        occurred_at=now,
        details={"assignment_id": str(assignment_id), "target_principal_id": str(assignment.principal_id)},
    )
    session.add(sec_event)

    return {"status": "revoked", "assignment_id": str(assignment_id)}
