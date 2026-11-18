# tests/acceptance/test_ac_customer.py
# Acceptance Criteria test suite for Customer service (SERVICES.md §6, ROADMAP Phase 7).
# Function names follow test_ac_NNN_* pattern checked by tools/check_ac_coverage.py.
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import commands
from app import models
from app import domain

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def mock_tenant_resolution():
    with patch("app.commands.tenant_client.resolve_store_tenant", AsyncMock(side_effect=lambda sid: uuid4())):
        yield


def make_mock_session(execute_results=None, get_mapping=None):
    """Helper creating mock AsyncSession that returns queued results and handles outbox inserts."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    if get_mapping:
        mock_session.get.side_effect = (
            lambda model, obj_id, **kw: get_mapping.get((model, obj_id)) or get_mapping.get(model) or get_mapping.get(obj_id)
        )

    results = list(execute_results or [])

    async def _execute(*args, **kwargs):
        if args and ("set_config" in str(args[0]) or "INSERT INTO customer.outbox_events" in str(args[0])):
            res = MagicMock()
            return res
        if results:
            return results.pop(0)
        res = MagicMock()
        res.scalars.return_value.first.return_value = None
        res.scalars.return_value.all.return_value = []
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session


# -----------------------------------------------------------------------------
# AC-076: Customer email/mobile are mandatory and unique within store
# -----------------------------------------------------------------------------

async def test_ac_076_customer_email_mobile_mandatory():
    """Omitting email or mobile raises 422 INVALID_REQUEST (AC-076)."""
    store_id = uuid4()
    mock_session = make_mock_session()

    with pytest.raises(ApiError) as exc_info:
        await commands.create_or_resolve_guest_customer_command(
            session=mock_session,
            store_id=store_id,
            email="",
            mobile="9876543210",
        )
    assert exc_info.value.status_code == 422
    assert "email is mandatory" in exc_info.value.message.lower()

    with pytest.raises(ApiError) as exc_info:
        await commands.create_or_resolve_guest_customer_command(
            session=mock_session,
            store_id=store_id,
            email="valid@example.com",
            mobile="",
        )
    assert exc_info.value.status_code == 422
    assert "mobile number is mandatory" in exc_info.value.message.lower()


async def test_ac_076_duplicate_email_or_mobile_in_same_store_rejected():
    """Duplicate email or duplicate mobile with conflicting data in the same store raises 409 (AC-076)."""
    store_id = uuid4()
    t1 = uuid4()

    existing_customer = models.Customer(
        id=uuid4(),
        tenant_id=t1,
        store_id=store_id,
        email="customer1@example.com",
        mobile_e164="+919876543210",
        status="UNCLAIMED",
    )

    # 1. Existing row found with same email but DIFFERENT mobile
    dup_res = MagicMock()
    dup_res.scalars.return_value.all.return_value = [existing_customer]
    mock_session = make_mock_session(execute_results=[dup_res])

    with pytest.raises(ApiError) as exc_info:
        await commands.create_or_resolve_guest_customer_command(
            session=mock_session,
            store_id=store_id,
            email="customer1@example.com",
            mobile="9876543211",  # Different mobile
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.IDEMPOTENCY_CONFLICT


async def test_ac_076_same_email_mobile_allowed_in_different_stores():
    """Same email and mobile can be registered independently across different stores (AC-076)."""
    store1 = uuid4()
    store2 = uuid4()
    email = "shopper@example.com"
    mobile = "9876543210"

    # Store 1 creates customer
    mock_session_s1 = make_mock_session()
    c1 = await commands.create_or_resolve_guest_customer_command(
        session=mock_session_s1,
        store_id=store1,
        email=email,
        mobile=mobile,
    )
    assert c1.store_id == store1
    assert c1.email == email
    assert c1.mobile_e164 == "+919876543210"

    # Store 2 creates independent customer with same email & mobile without conflict
    mock_session_s2 = make_mock_session()
    c2 = await commands.create_or_resolve_guest_customer_command(
        session=mock_session_s2,
        store_id=store2,
        email=email,
        mobile=mobile,
    )
    assert c2.store_id == store2
    assert c2.email == email
    assert c2.mobile_e164 == "+919876543210"
    assert c1.id != c2.id


# -----------------------------------------------------------------------------
# AC-077: Guest checkout creates UNCLAIMED customer
# -----------------------------------------------------------------------------

async def test_ac_077_guest_checkout_creates_unclaimed_customer():
    """Guest begins checkout in store with mandatory data; UNCLAIMED profile created (AC-077)."""
    store_id = uuid4()
    mock_session = make_mock_session()

    cust = await commands.create_or_resolve_guest_customer_command(
        session=mock_session,
        store_id=store_id,
        email="guest@example.com",
        mobile="9812345678",
        first_name="Ravi",
        last_name="Kumar",
    )

    assert cust.status == "UNCLAIMED"
    assert cust.store_id == store_id
    assert cust.email == "guest@example.com"
    assert cust.mobile_e164 == "+919812345678"
    assert cust.first_name == "Ravi"
    assert cust.last_name == "Kumar"
    assert cust.claimed_at is None
    assert cust.iam_principal_id is None


async def test_ac_077_guest_checkout_resolves_existing_unclaimed_customer():
    """Returning guest checkout with matching email and mobile resolves existing UNCLAIMED record (AC-077)."""
    store_id = uuid4()
    existing_id = uuid4()
    existing_cust = models.Customer(
        id=existing_id,
        tenant_id=uuid4(),
        store_id=store_id,
        email="returning@example.com",
        mobile_e164="+919876500000",
        status="UNCLAIMED",
        first_name="Anita",
    )

    dup_res = MagicMock()
    dup_res.scalars.return_value.all.return_value = [existing_cust]
    mock_session = make_mock_session(execute_results=[dup_res])

    resolved = await commands.create_or_resolve_guest_customer_command(
        session=mock_session,
        store_id=store_id,
        email="returning@example.com",
        mobile="9876500000",
        last_name="Sharma",
    )

    assert resolved.id == existing_id
    assert resolved.status == "UNCLAIMED"
    assert resolved.last_name == "Sharma"  # Updated missing field


# -----------------------------------------------------------------------------
# AC-078: Email OTP is used to claim UNCLAIMED account
# -----------------------------------------------------------------------------

async def test_ac_078_email_otp_claims_unclaimed_account():
    """Valid non-expired Email OTP moves account to CLAIMED and binds IAM principal (AC-078)."""
    customer_id = uuid4()
    t1 = uuid4()
    s1 = uuid4()
    otp_challenge_id = uuid4()
    claim_id = uuid4()

    customer = models.Customer(
        id=customer_id,
        tenant_id=t1,
        store_id=s1,
        email="claim_me@example.com",
        mobile_e164="+919876543210",
        status="UNCLAIMED",
    )
    claim = models.AccountClaim(
        id=claim_id,
        tenant_id=t1,
        store_id=s1,
        customer_id=customer_id,
        otp_challenge_id=otp_challenge_id,
        status="PENDING",
    )

    get_map = {
        (models.Customer, customer_id): customer,
        (models.AccountClaim, claim_id): claim,
    }
    mock_session = make_mock_session(get_mapping=get_map)

    # Mock IAM client verifying the OTP
    with patch("app.clients.iam_client.verify_otp_challenge", new=AsyncMock(return_value=True)):
        claimed_customer = await commands.verify_claim_command(
            session=mock_session,
            customer_id=customer_id,
            challenge_id=claim_id,
            otp_code="123456",
        )

    assert claimed_customer.status == "CLAIMED"
    assert claimed_customer.iam_principal_id is not None
    assert claimed_customer.claimed_at is not None
    assert claim.status == "VERIFIED"
    assert claim.verified_at is not None


async def test_ac_078_invalid_otp_never_claims():
    """Invalid or expired OTP does not claim account and raises 400 (AC-078)."""
    customer_id = uuid4()
    claim_id = uuid4()

    customer = models.Customer(
        id=customer_id,
        tenant_id=uuid4(),
        store_id=uuid4(),
        email="fail_claim@example.com",
        mobile_e164="+919876543210",
        status="UNCLAIMED",
    )
    claim = models.AccountClaim(
        id=claim_id,
        tenant_id=customer.tenant_id,
        store_id=customer.store_id,
        customer_id=customer_id,
        otp_challenge_id=uuid4(),
        status="PENDING",
    )

    get_map = {
        (models.Customer, customer_id): customer,
        (models.AccountClaim, claim_id): claim,
    }
    mock_session = make_mock_session(get_mapping=get_map)

    with patch("app.clients.iam_client.verify_otp_challenge", new=AsyncMock(return_value=False)):
        with pytest.raises(ApiError) as exc_info:
            await commands.verify_claim_command(
                session=mock_session,
                customer_id=customer_id,
                challenge_id=claim_id,
                otp_code="wrong_code",
            )

    assert exc_info.value.status_code == 400
    assert customer.status == "UNCLAIMED"
    assert claim.status == "FAILED"
