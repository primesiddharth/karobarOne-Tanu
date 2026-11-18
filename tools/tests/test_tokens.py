from datetime import datetime, timezone, timedelta
from uuid import uuid4
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from libs.platform_contracts.tokens import Principal, verify_token
from libs.platform_contracts.errors import ApiError, ErrorCode


@pytest.fixture(scope="module")
def rsa_key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_pem, public_pem


def test_valid_asymmetric_token(rsa_key_pair):
    private_pem, public_pem = rsa_key_pair
    sub_id = uuid4()
    session_id = uuid4()
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(sub_id),
        "session_id": str(session_id),
        "roles": ["STORE_OWNER"],
        "tenant_ids": [str(uuid4())],
        "store_ids": [str(uuid4())],
        "iss": "karobarone-iam",
        "aud": "karobarone-api",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    }

    token = jwt.encode(payload, private_pem, algorithm="RS256")
    principal = verify_token(token, public_pem)

    assert principal.sub == sub_id
    assert principal.session_id == session_id
    assert "STORE_OWNER" in principal.roles
    assert len(principal.tenant_ids) == 1
    assert len(principal.store_ids) == 1


def test_reject_none_algorithm(rsa_key_pair):
    _, public_pem = rsa_key_pair
    token = jwt.encode({"sub": str(uuid4())}, key="", algorithm="none")
    with pytest.raises(ApiError) as exc:
        verify_token(token, public_pem)
    assert exc.value.code == ErrorCode.UNAUTHENTICATED.value


def test_reject_symmetric_hs256(rsa_key_pair):
    _, public_pem = rsa_key_pair
    token = jwt.encode({"sub": str(uuid4())}, "some-secret-key", algorithm="HS256")
    with pytest.raises(ApiError) as exc:
        verify_token(token, public_pem)
    assert exc.value.code == ErrorCode.UNAUTHENTICATED.value


def test_reject_expired_token(rsa_key_pair):
    private_pem, public_pem = rsa_key_pair
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid4()),
        "session_id": str(uuid4()),
        "iss": "karobarone-iam",
        "aud": "karobarone-api",
        "iat": int((now - timedelta(hours=2)).timestamp()),
        "exp": int((now - timedelta(hours=1)).timestamp()),
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")
    with pytest.raises(ApiError) as exc:
        verify_token(token, public_pem)
    assert exc.value.code == ErrorCode.UNAUTHENTICATED.value
