# app/clients.py
# HTTP calls to other services + STUBS per RULES.md §13 & docs/STUBS.md
import structlog

logger = structlog.get_logger("iam.clients")


async def send_otp_notification(destination: str, otp_code: str, purpose: str = "login") -> None:
    """
    STUB(iam, OQ-007): OTP/email delivery -> logs to structlog + local Mailpit.
    Replaced when NTF service is built.
    Per RULES.md §5.10 & §8: plain OTP codes are NEVER emitted to logs.
    """
    # RULES.md §5.10 & §8: Never log PII destination, plain OTP codes, or secrets.
    logger.info("otp_notification_dispatched", purpose=purpose)
