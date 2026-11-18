# ==============================================================================
# File: libs/platform_contracts/logging.py
# Purpose: Shared log redaction processor conforming to RULES §10 & FND-TST-028
# ==============================================================================
import re
from typing import Any
import structlog

SENSITIVE_KEYS = {
    "pan",
    "gstin",
    "otp",
    "password",
    "token",
    "secret",
    "authorization",
    "x-service-key",
    "x-api-key",
    "private_key",
    "guardian_id",
}

PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def _redact_value(key: str, val: Any) -> Any:
    """Recursively redacts sensitive values matching sensitive keys or regex patterns."""
    if any(sk in key.lower() for sk in SENSITIVE_KEYS):
        return "[REDACTED]"

    if isinstance(val, dict):
        return {k: _redact_value(k, v) for k, v in val.items()}

    if isinstance(val, list):
        return [_redact_value(key, item) for item in val]

    if isinstance(val, str):
        if PAN_PATTERN.match(val) or GSTIN_PATTERN.match(val):
            return "[REDACTED]"

    return val


def redact_sensitive_values(_, __, event_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Structlog processor that redacts PAN, GSTIN, OTP, passwords, tokens,
    secrets, and authorization headers per RULES §10 and FND-TST-028.
    """
    return {k: _redact_value(k, v) for k, v in event_dict.items()}


def configure_logging(level: str = "INFO") -> None:
    """Configures structlog with standard JSON rendering and sensitive data redaction."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            redact_sensitive_values,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
