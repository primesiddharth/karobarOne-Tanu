# app/domain.py
# Pure domain logic: normalization, state machines, guards (RULES.md §3 & §1 C9).
# NO FastAPI, SQLAlchemy, or httpx imports allowed in this module.
import re
from libs.platform_contracts.errors import ApiError, ErrorCode


# ------------------------------------------------------------------------------
# Normalization & Validation (AC-076, SERVICES.md §6)
# ------------------------------------------------------------------------------

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
E164_INDIA_REGEX = re.compile(r"^\+91[6-9]\d{9}$")


def normalize_email(raw_email: str | None) -> str:
    """Normalizes email to trimmed lowercase and validates structure (AC-076)."""
    if not raw_email or not raw_email.strip():
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Email is mandatory", status_code=422)
    email = raw_email.strip().lower()
    if not EMAIL_REGEX.match(email):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Invalid email format", status_code=422)
    return email


def normalize_mobile_e164(raw_mobile: str | None) -> str:
    """Normalizes mobile number to E.164 format (+91XXXXXXXXXX) and validates (AC-076)."""
    if not raw_mobile or not raw_mobile.strip():
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Mobile number is mandatory", status_code=422)
    
    clean = re.sub(r"[\s\-\(\)]", "", raw_mobile.strip())
    
    # Handle standard 10-digit Indian numbers starting with 6-9
    if re.match(r"^[6-9]\d{9}$", clean):
        return f"+91{clean}"
    
    # Handle 12-digit Indian numbers with country code without plus: 91XXXXXXXXXX
    if re.match(r"^91[6-9]\d{9}$", clean):
        return f"+{clean}"
    
    # Handle explicit E.164 format +91XXXXXXXXXX
    if E164_INDIA_REGEX.match(clean):
        return clean
    
    raise ApiError(
        ErrorCode.INVALID_STATE_TRANSITION,
        "Invalid mobile number; must be a valid 10-digit Indian mobile",
        status_code=422,
    )


# ------------------------------------------------------------------------------
# State Machine: Customer Account Claim (SM §8, BTDD §9.7)
# ------------------------------------------------------------------------------

ALLOWED_CUSTOMER_TRANSITIONS: dict[str, set[str]] = {
    "UNCLAIMED": {"CLAIMED", "BLOCKED", "ANONYMIZED"},
    "CLAIMED": {"BLOCKED", "ANONYMIZED"},
    "BLOCKED": {"CLAIMED", "ANONYMIZED"},
    "ANONYMIZED": set(),  # Terminal state for profile deletion
}

ALLOWED_CLAIM_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"VERIFIED", "EXPIRED", "FAILED"},
    "VERIFIED": set(),
    "EXPIRED": set(),
    "FAILED": set(),
}

VALID_PRIVACY_REQUEST_TYPES = {"ACCESS", "CORRECT", "DELETE", "WITHDRAW_CONSENT"}
VALID_ADDRESS_TYPES = {"SHIPPING", "BILLING", "BOTH"}


def validate_customer_transition(current_status: str, target_status: str) -> None:
    """Guards customer lifecycle transitions (RULES.md §5.5, SM §8)."""
    allowed = ALLOWED_CUSTOMER_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Cannot transition customer from {current_status} to {target_status}",
            status_code=409,
        )


def validate_claim_transition(current_status: str, target_status: str) -> None:
    """Guards account claim transitions (SM §8)."""
    allowed = ALLOWED_CLAIM_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Cannot transition claim from {current_status} to {target_status}",
            status_code=409,
        )


def validate_privacy_request_type(request_type: str) -> str:
    """Validates privacy request type per DB Spec §7.7."""
    clean = request_type.strip().upper()
    if clean not in VALID_PRIVACY_REQUEST_TYPES:
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Invalid privacy request type: {request_type}. Must be one of {sorted(VALID_PRIVACY_REQUEST_TYPES)}",
            status_code=422,
        )
    return clean


def validate_address_type(address_type: str) -> str:
    """Validates address type per DB Spec §7.7."""
    clean = address_type.strip().upper()
    if clean not in VALID_ADDRESS_TYPES:
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Invalid address type: {address_type}. Must be one of {sorted(VALID_ADDRESS_TYPES)}",
            status_code=422,
        )
    return clean
