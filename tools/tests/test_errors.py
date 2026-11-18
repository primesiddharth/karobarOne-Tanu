# ==============================================================================
# File: microservice/tools/tests/test_errors.py
# Purpose: Verify ErrorCode alignment with Contract Appendix C and ApiError behavior
# ==============================================================================
import pytest
from libs.platform_contracts.errors import ApiError, ErrorCode, DEFAULT_STATUS_MAP


def test_registered_error_codes():
    """Validates that key registered error codes exist with proper default status."""
    assert ErrorCode.INVALID_STATE_TRANSITION.value == "INVALID_STATE_TRANSITION"
    assert DEFAULT_STATUS_MAP[ErrorCode.INVALID_STATE_TRANSITION] == 409
    assert DEFAULT_STATUS_MAP[ErrorCode.GSTIN_REQUIRED] == 422
    assert DEFAULT_STATUS_MAP[ErrorCode.UPI_NOT_SUPPORTED] == 422
    assert DEFAULT_STATUS_MAP[ErrorCode.DEPENDENCY_UNAVAILABLE] == 503
    assert DEFAULT_STATUS_MAP[ErrorCode.UNAUTHENTICATED] == 401


def test_api_error_initialization():
    """Asserts that ApiError initializes with default status code and details."""
    err = ApiError(ErrorCode.IDEMPOTENCY_CONFLICT, "Conflict detected", details={"key": "k1"})
    assert err.code == "IDEMPOTENCY_CONFLICT"
    assert err.status_code == 409
    assert err.details == {"key": "k1"}


def test_unregistered_error_code_rejected():
    """Asserts that attempting to instantiate an unregistered error code raises ValueError."""
    with pytest.raises(ValueError):
        ApiError("INVENTED_NON_CONTRACT_ERROR", "Should fail")
