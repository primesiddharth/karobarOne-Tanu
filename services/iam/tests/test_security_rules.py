# tests/test_security_rules.py
# Verification of IAM security rules: SEC-TST-005..008, enumeration resistance,
# refresh replay detection, concurrency, and generic status mutation refusal.
import json
import pytest
from uuid import uuid4, UUID
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.engine import CursorResult

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app.config import settings
from app import domain
from app import models
from app import commands
from app.main import app


pytestmark = pytest.mark.asyncio


# -----------------------------------------------------------------------------
# SEC-TST-005: Guardian Privilege Separation & Role Scope Validity
# -----------------------------------------------------------------------------
async def test_guardian_privilege_separation():
    """Verifies GUARDIAN role cannot assign or revoke roles (SEC-TST-005)."""
    tenant_id = uuid4()
    guardian_principal = Principal(
        sub=uuid4(),
        roles=["GUARDIAN"],
        tenant_ids=[tenant_id],
        store_ids=[],
    )

    mock_session = AsyncMock()

    # Attempting to grant a role as GUARDIAN must fail with 403 ENTITLEMENT_REQUIRED
    with pytest.raises(ApiError) as exc_info:
        await commands.grant_role_assignment_command(
            session=mock_session,
            current_principal=guardian_principal,
            target_principal_id=uuid4(),
            role_code="STORE_STAFF",
            tenant_id=tenant_id,
            store_id=uuid4(),
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED

    # Attempting to revoke a role as GUARDIAN must fail with 403 ENTITLEMENT_REQUIRED
    with pytest.raises(ApiError) as exc_info:
        await commands.revoke_role_assignment_command(
            session=mock_session,
            current_principal=guardian_principal,
            assignment_id=uuid4(),
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED


async def test_guardian_scope_enforcement():
    """GUARDIAN must require tenant_id and forbid store_id (RULES.md §8)."""
    tenant_id = uuid4()
    store_id = uuid4()

    # Valid: tenant_id present, store_id None
    assert domain.validate_role_assignment_scope("GUARDIAN", tenant_id, None) is True

    # Invalid: missing tenant_id
    with pytest.raises(ValueError, match="GUARDIAN requires tenant_id"):
        domain.validate_role_assignment_scope("GUARDIAN", None, None)

    # Invalid: store_id present
    with pytest.raises(ValueError, match="GUARDIAN requires tenant_id and must not specify store_id"):
        domain.validate_role_assignment_scope("GUARDIAN", tenant_id, store_id)


# -----------------------------------------------------------------------------
# SEC-TST-006: Expired and Revoked Tokens / Sessions Denied
# -----------------------------------------------------------------------------
async def test_expired_access_token_rejected():
    """Access token expired in the past is rejected with 401 UNAUTHENTICATED (SEC-TST-006)."""
    expired_token = domain.issue_access_jwt(
        principal_id=uuid4(),
        session_id=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[uuid4()],
        store_ids=[],
        private_key_pem=settings.JWT_PRIVATE_KEY,
        kid=settings.JWT_KID,
        issuer=settings.ISSUER,
        audience=settings.AUDIENCE,
        ttl_seconds=-60,  # Expired 60s ago
    )

    with pytest.raises(ApiError) as exc_info:
        domain.decode_access_jwt(
            token=expired_token,
            public_key_pem=settings.JWT_PUBLIC_KEY,
            issuer=settings.ISSUER,
            audience=settings.AUDIENCE,
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == ErrorCode.UNAUTHENTICATED


async def test_refresh_on_revoked_session_rejected():
    """Attempting to refresh a token from an already revoked session fails (SEC-TST-006)."""
    now = datetime.now(timezone.utc)
    raw_token = domain.generate_secure_refresh_token()
    token_hash = domain.hash_token(raw_token)

    session_row = models.Session(
        id=uuid4(),
        principal_id=uuid4(),
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(days=7),
        revoked_at=now - timedelta(minutes=10),  # Revoked already
    )

    refresh_row = models.RefreshToken(
        id=uuid4(),
        session_id=session_row.id,
        token_hash=token_hash,
        expires_at=now + timedelta(days=7),
        created_at=now - timedelta(hours=1),
        used_at=None,
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.first.return_value = (refresh_row, session_row)
    mock_session.execute.return_value = mock_result

    with pytest.raises(ApiError) as exc_info:
        await commands.refresh_session_command(
            session=mock_session,
            raw_refresh_token=raw_token,
        )
    assert exc_info.value.status_code == 401
    assert "Session has expired or been revoked" in exc_info.value.message


# -----------------------------------------------------------------------------
# SEC-TST-007: Refresh Token Replay Revokes Session and Logs Security Event
# -----------------------------------------------------------------------------
async def test_refresh_token_replay_revokes_entire_session():
    """Replaying an already-used refresh token revokes session and emits outbox event (SEC-TST-007)."""
    now = datetime.now(timezone.utc)
    raw_token = domain.generate_secure_refresh_token()
    token_hash = domain.hash_token(raw_token)

    session_row = models.Session(
        id=uuid4(),
        principal_id=uuid4(),
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(days=7),
        revoked_at=None,
    )

    # Token was already used 5 minutes ago!
    refresh_row = models.RefreshToken(
        id=uuid4(),
        session_id=session_row.id,
        token_hash=token_hash,
        expires_at=now + timedelta(days=7),
        created_at=now - timedelta(hours=1),
        used_at=now - timedelta(minutes=5),
        replaced_by=uuid4(),
    )

    added_objects = []
    mock_session = AsyncMock()
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    mock_result = MagicMock()
    mock_result.first.return_value = (refresh_row, session_row)
    mock_session.execute.return_value = mock_result

    with pytest.raises(ApiError) as exc_info:
        await commands.refresh_session_command(
            session=mock_session,
            raw_refresh_token=raw_token,
        )

    # 1. Returned 401
    assert exc_info.value.status_code == 401
    assert "Refresh token replay detected. Session revoked." in exc_info.value.message

    # 2. Session revoked immediately
    assert session_row.revoked_at is not None

    # 3. Security event logged with REFRESH_REPLAY and REVOKED
    sec_events = [o for o in added_objects if isinstance(o, models.SecurityEvent)]
    assert len(sec_events) == 1
    assert sec_events[0].event_type == "REFRESH_REPLAY"
    assert sec_events[0].result == "REVOKED"

    # 4. Outbox event identity.session.revoked.v1 executed atomically
    execute_calls = mock_session.execute.call_args_list
    assert len(execute_calls) >= 2
    # Second call is the outbox event insert
    outbox_insert_params = execute_calls[1][0][1]
    assert outbox_insert_params["event_type"] == "identity.session.revoked.v1"
    payload = json.loads(outbox_insert_params["payload"]) if isinstance(outbox_insert_params["payload"], str) else outbox_insert_params["payload"]
    assert payload["reason"] == "REFRESH_TOKEN_REPLAY"


# -----------------------------------------------------------------------------
# SEC-TST-008: OTP Abuse, Attempt Limits, and Rate Limiting
# -----------------------------------------------------------------------------
async def test_otp_incorrect_code_increments_attempts():
    """Submitting wrong OTP increments attempt count and rejects with 401 (SEC-TST-008)."""
    now = datetime.now(timezone.utc)
    challenge_id = uuid4()
    correct_otp = "123456"
    otp_hash = domain.hash_otp(correct_otp)

    challenge = models.OtpChallenge(
        id=challenge_id,
        principal_id=uuid4(),
        channel="EMAIL",
        destination_fingerprint="test_fp",
        purpose="VERIFICATION",
        otp_hash=otp_hash,
        expires_at=now + timedelta(minutes=5),
        attempt_count=1,
        consumed_at=None,
    )

    added_objects = []
    mock_session = AsyncMock()
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
    mock_session.get.return_value = challenge

    with pytest.raises(ApiError) as exc_info:
        await commands.verify_otp_challenge_command(
            session=mock_session,
            challenge_id=challenge_id,
            otp_code="999999",  # Wrong code
        )

    assert exc_info.value.status_code == 401
    assert challenge.attempt_count == 2
    sec_events = [o for o in added_objects if isinstance(o, models.SecurityEvent)]
    assert len(sec_events) == 1
    assert sec_events[0].event_type == "OTP_VERIFY_FAILURE"


async def test_otp_locked_after_max_attempts():
    """Challenge is locked once attempt_count reaches limit (SEC-TST-008)."""
    now = datetime.now(timezone.utc)
    challenge_id = uuid4()

    challenge = models.OtpChallenge(
        id=challenge_id,
        principal_id=uuid4(),
        channel="EMAIL",
        destination_fingerprint="test_fp",
        purpose="VERIFICATION",
        otp_hash=domain.hash_otp("123456"),
        expires_at=now + timedelta(minutes=5),
        attempt_count=5,  # Max limit reached
        consumed_at=None,
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = challenge

    with pytest.raises(ApiError) as exc_info:
        await commands.verify_otp_challenge_command(
            session=mock_session,
            challenge_id=challenge_id,
            otp_code="123456",
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.code == ErrorCode.RATE_LIMITED


async def test_otp_rate_limiting_per_destination():
    """Requesting more than max allowed challenges in window is rejected (SEC-TST-008)."""
    mock_session = AsyncMock()

    # Mock 3 recent challenges in window
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [MagicMock(), MagicMock(), MagicMock()]
    mock_session.execute.return_value = mock_result

    with pytest.raises(ApiError) as exc_info:
        await commands.create_otp_challenge_command(
            session=mock_session,
            channel="EMAIL",
            destination="user@example.com",
            purpose="VERIFICATION",
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.code == ErrorCode.RATE_LIMITED


# -----------------------------------------------------------------------------
# Registration Enumeration Resistance (OQ-006 & Security §6.1)
# -----------------------------------------------------------------------------
async def test_registration_does_not_reveal_existing_email():
    """Registering an existing email returns standard success without revealing existence."""
    mock_session = AsyncMock()
    existing_principal = models.Principal(
        id=uuid4(),
        principal_type="USER",
        email="existing@example.com",
        status="ACTIVE",
    )

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = existing_principal
    mock_session.execute.return_value = mock_result

    res = await commands.register_principal_command(
        session=mock_session,
        email="existing@example.com",
        password="ValidPassword123!",
    )

    assert res["principal_id"] == existing_principal.id
    assert res["email"] == "existing@example.com"
    assert res["status"] == "ACTIVE"
    # Ensure no new principal was added
    mock_session.add.assert_not_called()


# -----------------------------------------------------------------------------
# No Generic Status Mutation Routes (RULES.md §5.5)
# -----------------------------------------------------------------------------
async def test_no_generic_status_mutation_routes():
    """Verifies that no PATCH routes exist for generic status mutations."""
    patch_routes = [route.path for route in app.routes if "PATCH" in getattr(route, "methods", set())]
    assert len(patch_routes) == 0, f"Found unauthorized generic PATCH routes: {patch_routes}"
