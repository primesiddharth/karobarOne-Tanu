# app/domain.py
# Pure business rules: state transition tables, calculations, guards, cryptography.
# Strictly NO imports of FastAPI, SQLAlchemy, or httpx (RULES.md §3).
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta
from uuid import UUID
import argon2
import bcrypt
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.fernet import Fernet

ph = argon2.PasswordHasher()

# ------------------------------------------------------------------------------
# State Transition Tables (State Machine §8 & §21, RULES.md §9)
# ------------------------------------------------------------------------------

ALLOWED_PRINCIPAL_TRANSITIONS = {
    "PENDING_VERIFICATION": {"ACTIVE", "DISABLED"},
    "ACTIVE": {"LOCKED", "DISABLED"},
    "LOCKED": {"ACTIVE", "DISABLED"},
    "DISABLED": set(),
}

ALLOWED_OTP_TRANSITIONS = {
    "OTP_ACTIVE": {"OTP_VERIFIED", "OTP_EXPIRED"},
    "OTP_VERIFIED": set(),
    "OTP_EXPIRED": set(),
}


def assert_principal_transition(current_state: str, target_state: str) -> None:
    """Validates aggregate state transition for Principal."""
    allowed = ALLOWED_PRINCIPAL_TRANSITIONS.get(current_state, set())
    if target_state not in allowed:
        raise ValueError(f"Invalid state transition from {current_state} to {target_state}")


# ------------------------------------------------------------------------------
# Password Hashing & Transparent Migration (Argon2id + legacy bcrypt, OQ-008)
# ------------------------------------------------------------------------------

def hash_password_argon2(password: str) -> str:
    """Hashes plaintext password using Argon2id per RULES.md §8."""
    return ph.hash(password)


def verify_password(plain_password: str, stored_hash: str, algorithm: str) -> tuple[bool, bool]:
    """
    Verifies plain password against stored hash.
    Returns (is_valid, needs_rehash).
    If algorithm is legacy bcrypt, verifies with bcrypt and returns needs_rehash=True.
    """
    if algorithm == "argon2id":
        try:
            ph.verify(stored_hash, plain_password)
            return True, ph.check_needs_rehash(stored_hash)
        except (argon2.exceptions.VerifyMismatchError, argon2.exceptions.VerificationError):
            return False, False

    elif algorithm == "bcrypt":
        try:
            match = bcrypt.checkpw(plain_password.encode("utf-8"), stored_hash.encode("utf-8"))
            return match, True  # Legacy bcrypt verified -> must rehash to Argon2id
        except Exception:
            return False, False

    return False, False


# ------------------------------------------------------------------------------
# Token & OTP Cryptography
# ------------------------------------------------------------------------------

def hash_token(raw_token: str) -> str:
    """Returns SHA-256 one-way hash of refresh token or OTP (char 64)."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def hash_otp(raw_otp: str) -> str:
    """Returns SHA-256 one-way hash of OTP code."""
    return hash_token(raw_otp)


def compute_destination_fingerprint(destination: str, hmac_key: str) -> str:
    """Returns keyed HMAC-SHA256 fingerprint of sensitive contact info (RULES §5.10)."""
    normalized = destination.strip().lower()
    return hmac.new(hmac_key.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_secure_otp(length: int = 6) -> str:
    """Generates cryptographically random numeric OTP code."""
    digits = "0123456789"
    return "".join(secrets.choice(digits) for _ in range(length))


def generate_secure_refresh_token() -> str:
    """Generates cryptographically secure random urlsafe token for session refresh."""
    return secrets.token_urlsafe(48)


# ------------------------------------------------------------------------------
# Asymmetric RS256 JWT Issuance & JWKS (RULES.md §8 & OQ-003)
# ------------------------------------------------------------------------------

def issue_access_jwt(
    principal_id: UUID,
    session_id: UUID,
    roles: list[str],
    tenant_ids: list[UUID],
    store_ids: list[UUID],
    private_key_pem: str,
    kid: str,
    issuer: str,
    audience: str,
    ttl_seconds: int = 900,
) -> str:
    """Issues asymmetric RS256 signed JWT containing canonical claims."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=ttl_seconds)

    payload = {
        "sub": str(principal_id),
        "session_id": str(session_id),
        "roles": roles,
        "tenant_ids": [str(t) for t in tenant_ids],
        "store_ids": [str(s) for s in store_ids],
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": issuer,
        "aud": audience,
    }

    headers = {
        "alg": "RS256",
        "typ": "JWT",
        "kid": kid,
    }

    return jwt.encode(payload, private_key_pem, algorithm="RS256", headers=headers)


def decode_access_jwt(
    token: str,
    public_key_pem: str,
    issuer: str = "karobarone-iam",
    audience: str = "karobarone-api",
):
    """Verifies and decodes asymmetric RS256 JWT using platform token contract."""
    from libs.platform_contracts.tokens import verify_token
    return verify_token(token=token, public_key=public_key_pem, issuer=issuer, audience=audience)


def public_key_pem_to_jwk(public_key_pem: str, kid: str) -> dict:
    """Converts RSA public key PEM to standard JWK dictionary."""
    pub_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    if not isinstance(pub_key, rsa.RSAPublicKey):
        raise ValueError("Key is not an RSA public key")

    pub_numbers = pub_key.public_numbers()

    def to_b64u(val: int) -> str:
        b = val.to_bytes((val.bit_length() + 7) // 8, byteorder="big")
        return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")

    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": to_b64u(pub_numbers.n),
        "e": to_b64u(pub_numbers.e),
    }


# ------------------------------------------------------------------------------
# Scope & Role Assignment Validation (Security §6.3, RULES §8)
# ------------------------------------------------------------------------------

PLATFORM_ROLES = {"PLATFORM_OWNER", "PLATFORM_STAFF", "GST_STAFF"}


def validate_role_assignment_scope(
    role_code: str,
    tenant_id: UUID | None,
    store_id: UUID | None,
) -> None:
    """
    Validates scope rules:
    - Platform roles require tenant_id IS NULL and store_id IS NULL.
    - tenant_id IS NULL never grants admin access.
    - Store owner requires tenant_id and store_id IS NULL.
    - Store staff requires both tenant_id and store_id.
    - Guardian requires tenant_id and store_id IS NULL.
    - Customer requires store_id.
    - Service requires tenant_id IS NULL and store_id IS NULL.
    """
    if role_code in PLATFORM_ROLES:
        if tenant_id is not None or store_id is not None:
            raise ValueError(f"Platform role '{role_code}' must not have tenant_id or store_id scope")

    elif role_code == "STORE_OWNER":
        if tenant_id is None or store_id is not None:
            raise ValueError("STORE_OWNER requires tenant_id and must not specify store_id")

    elif role_code == "STORE_STAFF":
        if tenant_id is None or store_id is None:
            raise ValueError("STORE_STAFF requires both tenant_id and store_id")

    elif role_code == "GUARDIAN":
        if tenant_id is None or store_id is not None:
            raise ValueError("GUARDIAN requires tenant_id and must not specify store_id")

    elif role_code == "CUSTOMER":
        if store_id is None:
            raise ValueError("CUSTOMER role requires store_id scope")

    elif role_code == "SERVICE":
        if tenant_id is not None or store_id is not None:
            raise ValueError("SERVICE role must not have tenant_id or store_id scope")

    else:
        raise ValueError(f"Unrecognized or unassignable role code: '{role_code}'")

    return True


def assert_platform_admin_mfa(roles: list[str], mfa_completed: bool = True) -> None:
    """Enforces MFA security hook for privileged platform administration (SDD-001)."""
    if any(r in PLATFORM_ROLES for r in roles) and not mfa_completed:
        raise ValueError("Platform administration requires multi-factor authentication (MFA)")


# ------------------------------------------------------------------------------
# Idempotency Payload Encryption (RULES §5.10 & OQ-038)
# ------------------------------------------------------------------------------

def encrypt_idempotency_payload(payload_json: str, encryption_key_b64: str) -> str:
    """Encrypts response body before storing in idempotency_keys to protect tokens."""
    f = Fernet(encryption_key_b64.encode("utf-8"))
    return f.encrypt(payload_json.encode("utf-8")).decode("utf-8")


def decrypt_idempotency_payload(encrypted_str: str, encryption_key_b64: str) -> str:
    """Decrypts response body retrieved from idempotency_keys."""
    f = Fernet(encryption_key_b64.encode("utf-8"))
    return f.decrypt(encrypted_str.encode("utf-8")).decode("utf-8")
