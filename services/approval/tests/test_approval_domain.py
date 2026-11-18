# tests/test_approval_domain.py
# Pure business logic and state machine transition tests for APR (RULES.md §5.5, State Machine §7).
import pytest
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import domain


def test_subject_type_validation():
    """Validates subject_type conforms to supported domain types."""
    valid_types = [
        "STORE_CONTENT",
        "ITEM_VERSION",
        "BLOG_VERSION",
        "CUSTOM_CATEGORY",
        "VARIANT",
        "POLICY",
        "BRAND_AUTH",
    ]
    for st in valid_types:
        domain.validate_subject_type(st)  # Must not raise

    with pytest.raises(ApiError) as exc_info:
        domain.validate_subject_type("UNSUPPORTED_TYPE")
    assert exc_info.value.status_code == 422


def test_allowed_state_transitions():
    """Verifies all permitted state machine transitions succeed."""
    # APR-02: PENDING -> APPROVED
    domain.validate_state_transition("PENDING", "APPROVED")

    # APR-03: PENDING -> REJECTED
    domain.validate_state_transition("PENDING", "REJECTED")

    # APR-06: PENDING -> TAKEDOWN
    domain.validate_state_transition("PENDING", "TAKEDOWN")

    # APR-06: APPROVED -> TAKEDOWN
    domain.validate_state_transition("APPROVED", "TAKEDOWN")

    # APR-05: APPROVED -> UNPUBLISHED
    domain.validate_state_transition("APPROVED", "UNPUBLISHED")


def test_invalid_transitions_for_every_status():
    """Verifies that invalid transitions are strictly rejected with 409 INVALID_STATE_TRANSITION (Phase 4 exit gate)."""
    # From PENDING: cannot jump directly to UNPUBLISHED
    with pytest.raises(ApiError) as exc_info:
        domain.validate_state_transition("PENDING", "UNPUBLISHED")
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION
    assert exc_info.value.status_code == 409

    # From APPROVED: cannot transition to APPROVED (already approved) or REJECTED
    with pytest.raises(ApiError) as exc_info:
        domain.validate_state_transition("APPROVED", "APPROVED")
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION

    with pytest.raises(ApiError) as exc_info:
        domain.validate_state_transition("APPROVED", "REJECTED")
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION

    with pytest.raises(ApiError) as exc_info:
        domain.validate_state_transition("APPROVED", "PENDING")
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION

    # From REJECTED: immutable terminal state for that request; cannot transition to APPROVED, REJECTED, TAKEDOWN, UNPUBLISHED
    terminal_rejected_targets = ["APPROVED", "REJECTED", "TAKEDOWN", "UNPUBLISHED", "PENDING"]
    for target in terminal_rejected_targets:
        with pytest.raises(ApiError) as exc_info:
            domain.validate_state_transition("REJECTED", target)
        assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION
        assert exc_info.value.status_code == 409

    # From TAKEDOWN: terminal state; cannot transition to APPROVED, REJECTED, PENDING
    terminal_takedown_targets = ["APPROVED", "REJECTED", "PENDING", "UNPUBLISHED"]
    for target in terminal_takedown_targets:
        with pytest.raises(ApiError) as exc_info:
            domain.validate_state_transition("TAKEDOWN", target)
        assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION
        assert exc_info.value.status_code == 409

    # From UNPUBLISHED: cannot transition directly to APPROVED or REJECTED
    for target in ["APPROVED", "REJECTED", "PENDING", "TAKEDOWN"]:
        with pytest.raises(ApiError) as exc_info:
            domain.validate_state_transition("UNPUBLISHED", target)
        assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION


def test_rejection_reason_validation():
    """Verifies that empty, whitespace, or missing rejection reasons are rejected (AC-080)."""
    assert domain.validate_rejection_reason("Content violates guideline 4.2") == "Content violates guideline 4.2"
    assert domain.validate_rejection_reason("  Trimmed explanation  ") == "Trimmed explanation"

    with pytest.raises(ApiError) as exc_info:
        domain.validate_rejection_reason("")
    assert exc_info.value.status_code == 422

    with pytest.raises(ApiError) as exc_info:
        domain.validate_rejection_reason("     ")
    assert exc_info.value.status_code == 422

    with pytest.raises(ApiError) as exc_info:
        domain.validate_rejection_reason(None)
    assert exc_info.value.status_code == 422


def test_takedown_reason_validation():
    """Verifies takedown reasons conform to statutory/governance vocabulary (AC-081)."""
    for code in ["ILLEGAL", "COUNTERFEIT", "UNSAFE", "FRAUDULENT", "PROHIBITED", "OTHER"]:
        c, t = domain.validate_takedown_reason(code, "Law enforcement request")
        assert c == code
        assert t == "Law enforcement request"

    with pytest.raises(ApiError) as exc_info:
        domain.validate_takedown_reason("UNKNOWN_CODE", "explanation")
    assert exc_info.value.status_code == 422

    with pytest.raises(ApiError) as exc_info:
        domain.validate_takedown_reason("ILLEGAL", "")
    assert exc_info.value.status_code == 422
