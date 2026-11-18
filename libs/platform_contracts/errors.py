# ==============================================================================
# File: libs/platform_contracts/errors.py
# Purpose: Canonical registered error codes and standard error envelope (Contract Appendix C)
# ==============================================================================
from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from fastapi import Request
from fastapi.responses import JSONResponse


class ErrorCode(str, Enum):
    # Contract Appendix C Standard Registry (exact 25 error codes)
    INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
    TENANT_PAN_ALREADY_REGISTERED = "TENANT_PAN_ALREADY_REGISTERED"
    FREE_STORE_ENTITLEMENT_CONSUMED = "FREE_STORE_ENTITLEMENT_CONSUMED"
    GSTIN_REQUIRED = "GSTIN_REQUIRED"
    GSTIN_NOT_OWNED = "GSTIN_NOT_OWNED"
    GSTIN_ALREADY_USED = "GSTIN_ALREADY_USED"
    GUARDIAN_REQUIRED = "GUARDIAN_REQUIRED"
    ENTITLEMENT_REQUIRED = "ENTITLEMENT_REQUIRED"
    COMMERCE_SUSPENDED = "COMMERCE_SUSPENDED"
    SUBSCRIPTION_EXPIRED = "SUBSCRIPTION_EXPIRED"
    CROSS_STORE_CHECKOUT_NOT_ALLOWED = "CROSS_STORE_CHECKOUT_NOT_ALLOWED"
    MIXED_CHECKOUT_NOT_ALLOWED = "MIXED_CHECKOUT_NOT_ALLOWED"
    INSUFFICIENT_INVENTORY = "INSUFFICIENT_INVENTORY"
    CAPACITY_UNAVAILABLE = "CAPACITY_UNAVAILABLE"
    PAYMENT_NOT_CONFIRMED = "PAYMENT_NOT_CONFIRMED"
    UPI_NOT_SUPPORTED = "UPI_NOT_SUPPORTED"
    CUSTOM_DOMAIN_REQUIRED = "CUSTOM_DOMAIN_REQUIRED"
    CONTENT_APPROVAL_REQUIRED = "CONTENT_APPROVAL_REQUIRED"
    CANCELLATION_WINDOW_CLOSED = "CANCELLATION_WINDOW_CLOSED"
    UPGRADE_APPROVAL_REQUIRED = "UPGRADE_APPROVAL_REQUIRED"
    REFUND_NOT_ALLOWED = "REFUND_NOT_ALLOWED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    STALE_VERSION = "STALE_VERSION"
    RATE_LIMITED = "RATE_LIMITED"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"

    # Pending OQ-025 resolution for internal service-to-service auth
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN_CALLER = "FORBIDDEN_CALLER"


# Default HTTP status code mapping per Contract Appendix C
DEFAULT_STATUS_MAP: dict[ErrorCode, int] = {
    ErrorCode.INVALID_STATE_TRANSITION: 409,
    ErrorCode.TENANT_PAN_ALREADY_REGISTERED: 409,
    ErrorCode.FREE_STORE_ENTITLEMENT_CONSUMED: 409,
    ErrorCode.GSTIN_REQUIRED: 422,
    ErrorCode.GSTIN_NOT_OWNED: 409,
    ErrorCode.GSTIN_ALREADY_USED: 409,
    ErrorCode.GUARDIAN_REQUIRED: 409,
    ErrorCode.ENTITLEMENT_REQUIRED: 403,
    ErrorCode.COMMERCE_SUSPENDED: 403,
    ErrorCode.SUBSCRIPTION_EXPIRED: 403,
    ErrorCode.CROSS_STORE_CHECKOUT_NOT_ALLOWED: 409,
    ErrorCode.MIXED_CHECKOUT_NOT_ALLOWED: 409,
    ErrorCode.INSUFFICIENT_INVENTORY: 409,
    ErrorCode.CAPACITY_UNAVAILABLE: 409,
    ErrorCode.PAYMENT_NOT_CONFIRMED: 409,
    ErrorCode.UPI_NOT_SUPPORTED: 422,
    ErrorCode.CUSTOM_DOMAIN_REQUIRED: 409,
    ErrorCode.CONTENT_APPROVAL_REQUIRED: 409,
    ErrorCode.CANCELLATION_WINDOW_CLOSED: 409,
    ErrorCode.UPGRADE_APPROVAL_REQUIRED: 409,
    ErrorCode.REFUND_NOT_ALLOWED: 409,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.STALE_VERSION: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
    ErrorCode.UNAUTHENTICATED: 401,
    ErrorCode.FORBIDDEN_CALLER: 403,
}


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: ErrorDetail


class ApiError(Exception):
    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Constructs an API error, verifying that code exists in registered ErrorCode enum."""
        if isinstance(code, str):
            try:
                self.code = ErrorCode(code)
            except ValueError:
                raise ValueError(f"Unregistered error code '{code}' not allowed by contract")
        else:
            self.code = code

        self.message = message
        self.status_code = status_code or DEFAULT_STATUS_MAP.get(self.code, 400)
        self.details = details or {}
        super().__init__(self.message)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """FastAPI exception handler converting ApiError into Contract §6 standard JSON envelope."""
    request_id = getattr(request.state, "request_id", "req-unknown")
    payload = {
        "error": {
            "code": exc.code.value,
            "message": exc.message,
            "details": exc.details,
            "request_id": request_id,
        }
    }
    return JSONResponse(status_code=exc.status_code, content=payload)
