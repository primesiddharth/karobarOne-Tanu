# tests/test_customer_domain.py
# Pure domain unit tests: normalization, state machines, guards (RULES.md §3 & §1 C9).
import pytest
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import domain


def test_normalize_email_valid_and_cases():
    assert domain.normalize_email("USER@EXAMPLE.COM") == "user@example.com"
    assert domain.normalize_email("  john.doe+tag@test.in  ") == "john.doe+tag@test.in"


def test_normalize_email_invalid_raises_422():
    with pytest.raises(ApiError) as exc_info:
        domain.normalize_email("")
    assert exc_info.value.status_code == 422

    with pytest.raises(ApiError) as exc_info:
        domain.normalize_email("not-an-email")
    assert exc_info.value.status_code == 422


def test_normalize_mobile_e164_valid_formats():
    assert domain.normalize_mobile_e164("9876543210") == "+919876543210"
    assert domain.normalize_mobile_e164("919876543210") == "+919876543210"
    assert domain.normalize_mobile_e164("+919876543210") == "+919876543210"
    assert domain.normalize_mobile_e164("  98765-43210  ") == "+919876543210"


def test_normalize_mobile_e164_invalid_raises_422():
    with pytest.raises(ApiError) as exc_info:
        domain.normalize_mobile_e164("1234567890")  # Does not start with 6-9
    assert exc_info.value.status_code == 422

    with pytest.raises(ApiError) as exc_info:
        domain.normalize_mobile_e164("98765")  # Too short
    assert exc_info.value.status_code == 422

    with pytest.raises(ApiError) as exc_info:
        domain.normalize_mobile_e164("")
    assert exc_info.value.status_code == 422


def test_customer_state_transitions():
    # Valid transitions
    domain.validate_customer_transition("UNCLAIMED", "CLAIMED")
    domain.validate_customer_transition("UNCLAIMED", "BLOCKED")
    domain.validate_customer_transition("CLAIMED", "BLOCKED")
    domain.validate_customer_transition("BLOCKED", "CLAIMED")
    domain.validate_customer_transition("CLAIMED", "ANONYMIZED")

    # Invalid transitions
    with pytest.raises(ApiError) as exc_info:
        domain.validate_customer_transition("CLAIMED", "UNCLAIMED")
    assert exc_info.value.status_code == 409

    with pytest.raises(ApiError) as exc_info:
        domain.validate_customer_transition("ANONYMIZED", "CLAIMED")
    assert exc_info.value.status_code == 409


def test_claim_state_transitions():
    domain.validate_claim_transition("PENDING", "VERIFIED")
    domain.validate_claim_transition("PENDING", "EXPIRED")
    domain.validate_claim_transition("PENDING", "FAILED")

    with pytest.raises(ApiError) as exc_info:
        domain.validate_claim_transition("VERIFIED", "PENDING")
    assert exc_info.value.status_code == 409


def test_validate_privacy_and_address_types():
    assert domain.validate_privacy_request_type("delete") == "DELETE"
    assert domain.validate_privacy_request_type("ACCESS") == "ACCESS"
    with pytest.raises(ApiError):
        domain.validate_privacy_request_type("UNKNOWN")

    assert domain.validate_address_type("shipping") == "SHIPPING"
    assert domain.validate_address_type("BILLING") == "BILLING"
    assert domain.validate_address_type("both") == "BOTH"
    with pytest.raises(ApiError):
        domain.validate_address_type("OFFICE")
