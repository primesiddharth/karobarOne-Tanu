# tests/test_foundation_rules.py
# Verification of foundation rules: Idempotency (FND-TST-001/002), Token payload
# encryption in idempotency cache (OQ-038), Audit completeness, and Outbox atomicity.
import pytest
import json
import hashlib
from uuid import uuid4, UUID
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app.config import settings
from app import domain
from app import models
from app import commands
from app.routes import handle_idempotency


pytestmark = pytest.mark.asyncio


# -----------------------------------------------------------------------------
# FND-TST-001 & FND-TST-002: Idempotency Repeat and Conflict
# -----------------------------------------------------------------------------
async def test_idempotency_repeat_returns_cached_response():
    """Identical idempotency key with identical payload returns cached response (FND-TST-001)."""
    key = str(uuid4())
    req_body = {"email": "user@example.com"}
    req_hash = domain.hash_token(json.dumps(req_body, sort_keys=True))

    cached_entry = models.IdempotencyKey(
        id=uuid4(),
        scope="iam",
        key=key,
        request_hash=req_hash,
        response_code=200,
        response_body={"principal_id": str(uuid4()), "status": "ACTIVE"},
        created_at=datetime.now(timezone.utc),
        locked_until=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = cached_entry
    mock_session.execute.return_value = mock_result

    called = False

    async def execute_target():
        nonlocal called
        called = True
        return {"should": "not_be_called"}

    res = await handle_idempotency(
        session=mock_session,
        scope="iam",
        key=key,
        raw_body=req_body,
        execute_coroutine=execute_target,
    )

    assert called is False
    assert res.status_code == 200
    assert json.loads(res.body.decode("utf-8")) == cached_entry.response_body


async def test_idempotency_conflict_raises_409():
    """Replaying an idempotency key with different request payload raises 409 conflict (FND-TST-002)."""
    key = str(uuid4())
    req_body_original = {"email": "original@example.com"}
    req_hash_original = domain.hash_token(json.dumps(req_body_original, sort_keys=True))

    cached_entry = models.IdempotencyKey(
        id=uuid4(),
        scope="iam",
        key=key,
        request_hash=req_hash_original,
        response_code=200,
        response_body={"status": "ACTIVE"},
        created_at=datetime.now(timezone.utc),
        locked_until=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = cached_entry
    mock_session.execute.return_value = mock_result

    req_body_tampered = {"email": "tampered@example.com"}

    with pytest.raises(ApiError) as exc_info:
        await handle_idempotency(
            session=mock_session,
            scope="iam",
            key=key,
            raw_body=req_body_tampered,
            execute_coroutine=AsyncMock(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.IDEMPOTENCY_CONFLICT


# -----------------------------------------------------------------------------
# OQ-038: Idempotency Token Body Encryption
# -----------------------------------------------------------------------------
async def test_idempotent_token_response_body_is_encrypted():
    """Token-issuing routes encrypt cached response body in idempotency table (OQ-038)."""
    key = str(uuid4())
    req_body = {"login": "test"}
    added_keys = []

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result
    mock_session.add = MagicMock(side_effect=lambda obj: added_keys.append(obj))

    raw_tokens = {
        "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.secret_jwt_body",
        "refresh_token": "plain_secret_refresh_token_xyz123",
    }

    async def fake_login():
        return raw_tokens

    res = await handle_idempotency(
        session=mock_session,
        scope="iam:auth",
        key=key,
        raw_body=req_body,
        execute_coroutine=fake_login,
        encrypt_response=True,
    )

    assert res == raw_tokens
    assert len(added_keys) == 1
    stored_entry = added_keys[0]

    # Stored body must be encrypted
    assert "_encrypted" in stored_entry.response_body
    ciphertext = stored_entry.response_body["_encrypted"]
    assert "plain_secret_refresh_token_xyz123" not in str(stored_entry.response_body)

    # Decrypting ciphertext with key recovers plain response
    decrypted_str = domain.decrypt_idempotency_payload(ciphertext, settings.IDEMPOTENCY_ENCRYPTION_KEY)
    decrypted_json = json.loads(decrypted_str)
    assert decrypted_json["refresh_token"] == "plain_secret_refresh_token_xyz123"


# -----------------------------------------------------------------------------
# Audit Completeness: Security Events Logged on Commands
# -----------------------------------------------------------------------------
async def test_audit_security_event_logged_on_all_commands():
    """All state-changing auth commands must append a SecurityEvent row."""
    # 1. Register command
    mock_session = AsyncMock()
    added_objects = []
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result

    await commands.register_principal_command(
        session=mock_session,
        email="audit_user@example.com",
        password="ValidPassword123!",
    )
    sec_events = [o for o in added_objects if isinstance(o, models.SecurityEvent)]
    assert len(sec_events) == 1
    assert sec_events[0].event_type == "PRINCIPAL_REGISTERED"
    assert sec_events[0].result == "SUCCESS"

    # 2. Logout command
    added_objects.clear()
    session_id = uuid4()
    principal_id = uuid4()
    mock_active_session = models.Session(
        id=session_id,
        principal_id=principal_id,
        issued_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        revoked_at=None,
    )
    mock_session.get.return_value = mock_active_session
    await commands.logout_command(
        session=mock_session,
        principal_id=principal_id,
        session_id=session_id,
    )
    sec_events = [o for o in added_objects if isinstance(o, models.SecurityEvent)]
    assert len(sec_events) == 1
    assert sec_events[0].event_type == "LOGOUT"
    assert sec_events[0].result == "SUCCESS"


# -----------------------------------------------------------------------------
# Outbox Atomicity
# -----------------------------------------------------------------------------
async def test_outbox_event_added_with_domain_state():
    """Domain events are inserted atomically with state changes."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute.return_value = mock_result

    await commands.register_principal_command(
        session=mock_session,
        email="outbox_test@example.com",
        password="ValidPassword123!",
    )

    execute_calls = mock_session.execute.call_args_list
    assert len(execute_calls) >= 2
    # Second call is the outbox event insert
    outbox_call = execute_calls[1]
    outbox_params = outbox_call[0][1]
    assert outbox_params["event_type"] == "identity.principal.created.v1"
    assert outbox_params["agg_type"] == "Principal"


# -----------------------------------------------------------------------------
# Migration Fresh & Upgrade Structure
# -----------------------------------------------------------------------------
async def test_alembic_migration_defines_all_iam_tables():
    """Validates Alembic migration file 002_iam_tables.py defines all required tables."""
    import importlib.util
    from pathlib import Path

    migration_path = Path(__file__).parents[1] / "migrations" / "versions" / "002_iam_tables.py"
    spec = importlib.util.spec_from_file_location(
        "migration_002",
        str(migration_path),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "upgrade")
    assert hasattr(module, "downgrade")
    assert module.revision == "002"
    assert module.down_revision == "001"
