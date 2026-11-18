# tests/test_domain_rules.py
from uuid import uuid4
import pytest
import bcrypt
from app import domain
from app.config import settings


def test_argon2id_password_hashing():
    """Argon2id produces non-empty hash, verifies, and rejects bad password (RULES §8)."""
    pwd = "CorrectHorseBatteryStaple123!"
    hashed = domain.hash_password_argon2(pwd)
    assert hashed.startswith("$argon2id$")

    is_valid, needs_rehash = domain.verify_password(pwd, hashed, "argon2id")
    assert is_valid is True
    assert needs_rehash is False

    is_bad_valid, _ = domain.verify_password("WrongPassword!", hashed, "argon2id")
    assert is_bad_valid is False


def test_legacy_bcrypt_verify_then_rehash():
    """Legacy bcrypt hashes verify successfully and signal needs_rehash=True (OQ-008)."""
    pwd = "MonolithLegacyPassword123!"
    bcrypt_hash = bcrypt.hashpw(pwd.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    is_valid, needs_rehash = domain.verify_password(pwd, bcrypt_hash, "bcrypt")
    assert is_valid is True
    assert needs_rehash is True

    # Bad password with bcrypt algorithm
    is_bad_valid, _ = domain.verify_password("WrongPassword!", bcrypt_hash, "bcrypt")
    assert is_bad_valid is False


def test_token_and_otp_hashing():
    """Hashes tokens and OTPs with SHA-256 and computes keyed destination fingerprints."""
    raw_token = domain.generate_secure_refresh_token()
    h = domain.hash_token(raw_token)
    assert len(h) == 64
    assert h == domain.hash_token(raw_token)

    otp = domain.generate_secure_otp(6)
    assert len(otp) == 6
    assert otp.isdigit()

    fp1 = domain.compute_destination_fingerprint("User@Example.com", "secret-key")
    fp2 = domain.compute_destination_fingerprint("user@example.com ", "secret-key")
    assert fp1 == fp2  # Normalization verified
    assert len(fp1) == 64


def test_asymmetric_jwt_issuance_and_claims():
    """Issues RS256 token containing all required claims (RULES §8, OQ-003)."""
    pid = uuid4()
    sid = uuid4()
    tid = uuid4()
    stid = uuid4()

    token = domain.issue_access_jwt(
        principal_id=pid,
        session_id=sid,
        roles=["STORE_OWNER"],
        tenant_ids=[tid],
        store_ids=[stid],
        private_key_pem=settings.JWT_PRIVATE_KEY,
        kid=settings.JWT_KID,
        issuer=settings.ISSUER,
        audience=settings.AUDIENCE,
        ttl_seconds=300,
    )

    from libs.platform_contracts.tokens import verify_token
    principal = verify_token(token, settings.JWT_PUBLIC_KEY, issuer=settings.ISSUER, audience=settings.AUDIENCE)
    assert principal.sub == pid
    assert principal.session_id == sid
    assert principal.roles == ["STORE_OWNER"]
    assert principal.tenant_ids == [tid]
    assert principal.store_ids == [stid]
    assert principal.kid == settings.JWT_KID


def test_role_assignment_scope_validation():
    """Enforces role scope check matrix; tenant_id IS NULL never implies admin (RULES §8)."""
    # 1. Platform roles must have NULL tenant and NULL store
    domain.validate_role_assignment_scope("PLATFORM_OWNER", None, None)
    domain.validate_role_assignment_scope("PLATFORM_STAFF", None, None)
    domain.validate_role_assignment_scope("GST_STAFF", None, None)

    with pytest.raises(ValueError, match="Platform role"):
        domain.validate_role_assignment_scope("PLATFORM_OWNER", uuid4(), None)

    # 2. STORE_OWNER requires tenant_id and NULL store_id
    domain.validate_role_assignment_scope("STORE_OWNER", uuid4(), None)
    with pytest.raises(ValueError, match="STORE_OWNER requires tenant_id"):
        domain.validate_role_assignment_scope("STORE_OWNER", None, None)

    # 3. STORE_STAFF requires both tenant_id and store_id
    domain.validate_role_assignment_scope("STORE_STAFF", uuid4(), uuid4())
    with pytest.raises(ValueError, match="STORE_STAFF requires both"):
        domain.validate_role_assignment_scope("STORE_STAFF", uuid4(), None)

    # 4. GUARDIAN requires tenant_id and NULL store_id
    domain.validate_role_assignment_scope("GUARDIAN", uuid4(), None)
    with pytest.raises(ValueError, match="GUARDIAN requires tenant_id"):
        domain.validate_role_assignment_scope("GUARDIAN", None, None)

    # 5. CUSTOMER requires store_id
    domain.validate_role_assignment_scope("CUSTOMER", None, uuid4())
    with pytest.raises(ValueError, match="CUSTOMER role requires store_id"):
        domain.validate_role_assignment_scope("CUSTOMER", None, None)

    # 6. PUBLIC is unassignable
    with pytest.raises(ValueError, match="Unrecognized or unassignable"):
        domain.validate_role_assignment_scope("PUBLIC", None, None)


def test_idempotency_payload_encryption():
    """Encrypts and decrypts sensitive token responses in idempotency keys (OQ-038)."""
    data = '{"access_token": "secret_jwt", "refresh_token": "secret_refresh"}'
    encrypted = domain.encrypt_idempotency_payload(data, settings.IDEMPOTENCY_ENCRYPTION_KEY)
    assert "secret_jwt" not in encrypted
    assert "secret_refresh" not in encrypted

    decrypted = domain.decrypt_idempotency_payload(encrypted, settings.IDEMPOTENCY_ENCRYPTION_KEY)
    assert decrypted == data
