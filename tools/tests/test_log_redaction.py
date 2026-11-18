# ==============================================================================
# File: tools/tests/test_log_redaction.py
# Purpose: FND-TST-028 Log redaction verification for sensitive data
# ==============================================================================
import io
import structlog
import pytest
from libs.platform_contracts.logging import redact_sensitive_values


def test_sensitive_data_redaction():
    """
    FND-TST-028: Log redaction test.
    Feeds PAN, GSTIN, OTP, passwords, tokens to structlog and verifies they are redacted
    using the canonical platform contracts redaction processor.
    """
    buffer = io.StringIO()

    structlog.configure(
        processors=[
            redact_sensitive_values,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=buffer),
    )

    logger = structlog.get_logger("test_redactor")
    logger.info(
        "user_login_attempt",
        pan="ABCDE1234F",
        gstin="27ABCDE1234F1Z5",
        otp="123456",
        password="MySecretPassword!",
        normal_field="ok_value",
        nested_data={
            "token": "eyJhbGciOi...",
            "secret": "super_secret_val",
            "nested_pan": "ABCDE1234F",
        },
    )

    logged = buffer.getvalue()
    assert "ABCDE1234F" not in logged, "Plain PAN leaked into logs"
    assert "27ABCDE1234F1Z5" not in logged, "Plain GSTIN leaked into logs"
    assert "123456" not in logged, "Plain OTP leaked into logs"
    assert "MySecretPassword!" not in logged, "Plain password leaked into logs"
    assert "super_secret_val" not in logged, "Plain secret leaked into logs"
    assert "ok_value" in logged, "Normal field was improperly stripped"
