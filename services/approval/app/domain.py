# app/domain.py
# Pure business logic and state transition rules for Approval & Governance service (RULES.md §5.5, SM §7)
from typing import Set
from libs.platform_contracts.errors import ApiError, ErrorCode


# Valid Subject Types per DB Spec §7.6
VALID_SUBJECT_TYPES: Set[str] = {
    "STORE_CONTENT",
    "ITEM_VERSION",
    "BLOG_VERSION",
    "CUSTOM_CATEGORY",
    "VARIANT",
    "POLICY",
    "BRAND_AUTH",
}

# Valid Takedown Reason Codes per DB Spec §7.6 & SM §7
VALID_TAKEDOWN_REASONS: Set[str] = {
    "ILLEGAL",
    "COUNTERFEIT",
    "UNSAFE",
    "FRAUDULENT",
    "PROHIBITED",
    "OTHER",
}

# Explicit Allowed Transitions Table (RULES.md §5.5, SM §7)
ALLOWED_TRANSITIONS: dict[str, Set[str]] = {
    "PENDING": {"APPROVED", "REJECTED", "TAKEDOWN"},
    "APPROVED": {"UNPUBLISHED", "TAKEDOWN"},
    "REJECTED": set(),
    "TAKEDOWN": set(),
    "UNPUBLISHED": set(),
}


def validate_subject_type(subject_type: str) -> None:
    """Ensures subject_type is recognized by the governance domain."""
    if subject_type not in VALID_SUBJECT_TYPES:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message=f"Unsupported subject type: {subject_type}",
            status_code=422,
        )


def validate_state_transition(current_status: str, target_status: str) -> None:
    """Enforces strictly declared status transition rules without generic mutation (RULES.md §5.5)."""
    allowed = ALLOWED_TRANSITIONS.get(current_status, set())
    if target_status not in allowed:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message=f"Cannot transition approval request from {current_status} to {target_status}",
            status_code=409,
        )


def validate_rejection_reason(reason_text: str | None) -> str:
    """Ensures rejection contains a non-empty reason text (AC-080)."""
    if not reason_text or not reason_text.strip():
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message="Rejection requires a non-empty reason/comment",
            status_code=422,
        )
    return reason_text.strip()


def validate_takedown_reason(reason_code: str, reason_text: str | None) -> tuple[str, str]:
    """Ensures emergency takedown supplies valid code and non-empty explanation (AC-081)."""
    if reason_code not in VALID_TAKEDOWN_REASONS:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message=f"Invalid takedown reason code: {reason_code}",
            status_code=422,
        )
    if not reason_text or not reason_text.strip():
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message="Emergency takedown requires a non-empty explanation",
            status_code=422,
        )
    return reason_code, reason_text.strip()
