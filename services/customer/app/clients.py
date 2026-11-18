# app/clients.py
# External & cross-service clients with stubs marked per RULES.md §13 & docs/STUBS.md
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
import httpx
import structlog
from libs.platform_contracts.errors import ApiError, ErrorCode
from .config import settings

logger = structlog.get_logger("customer.clients")


class IamClient:
    """Client for synchronous calls to IAM service (IAM-004 & IAM-005) per RULES.md §5.3."""

    def __init__(self, base_url: str | None = None, service_key: str | None = None):
        self.base_url = (base_url or settings.IAM_SERVICE_URL).rstrip("/")
        self.service_key = service_key or settings.IAM_SERVICE_KEY

    async def request_otp_challenge(
        self,
        email: str,
        purpose: str = "ACCOUNT_CLAIM",
        correlation_id: UUID | None = None,
    ) -> UUID:
        """Invokes POST /auth/otp/challenges (IAM-004)."""
        url = f"{self.base_url}/auth/otp/challenges"
        headers = {
            "X-Service-Key": self.service_key,
            "Content-Type": "application/json",
        }
        if correlation_id:
            headers["X-Correlation-Id"] = str(correlation_id)

        payload = {
            "channel": "EMAIL",
            "destination": email,
            "purpose": purpose,
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code in (200, 201):
                    data = res.json()
                    return UUID(data["challenge_id"])

                logger.error("iam_otp_challenge_failed", status=res.status_code, response=res.text)
                if res.status_code == 429:
                    raise ApiError(ErrorCode.RATE_LIMITED, "Too many OTP requests. Please wait.", status_code=429)
                raise ApiError(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    f"IAM service returned error status {res.status_code}",
                    status_code=503,
                )
        except httpx.RequestError as e:
            logger.error("iam_connection_error", error=str(e))
            raise ApiError(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                f"Could not reach IAM service: {str(e)}",
                status_code=503,
            )

    async def verify_otp_challenge(
        self,
        challenge_id: UUID,
        otp_code: str,
        correlation_id: UUID | None = None,
    ) -> bool:
        """Invokes POST /auth/otp/challenges/{id}/verify (IAM-005)."""
        url = f"{self.base_url}/auth/otp/challenges/{challenge_id}/verify"
        headers = {
            "X-Service-Key": self.service_key,
            "Content-Type": "application/json",
        }
        if correlation_id:
            headers["X-Correlation-Id"] = str(correlation_id)

        payload = {
            "otp_code": otp_code,
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    return bool(data.get("verified", False))

                logger.warning("iam_otp_verify_failed", status=res.status_code, response=res.text)
                if res.status_code in (400, 401, 404, 422):
                    return False
                if res.status_code == 429:
                    raise ApiError(ErrorCode.RATE_LIMITED, "Too many failed attempts. OTP locked.", status_code=429)
                raise ApiError(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    f"IAM service returned error status {res.status_code}",
                    status_code=503,
                )
        except httpx.RequestError as e:
            logger.error("iam_connection_error", error=str(e))
            raise ApiError(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                f"Could not reach IAM service: {str(e)}",
                status_code=503,
            )

    async def link_or_create_principal(self, email: str, password: str | None = None) -> UUID:
        """Resolves or provisions an IAM principal for a claimed customer (OQ-040, AC-078).
        # STUB(iam, OQ-040): In clean-room test/dev, generates deterministic principal UUID based on email.
        """
        return uuid5(NAMESPACE_URL, f"karobarone:customer:principal:{email.lower().strip()}")


class TenantClient:
    """Client for resolving store tenant information."""

    def __init__(self, base_url: str | None = None, service_key: str | None = None):
        self.base_url = (base_url or settings.TENANT_SERVICE_URL).rstrip("/")
        self.service_key = service_key or settings.TENANT_SERVICE_KEY

    async def resolve_store_tenant(self, store_id: UUID) -> UUID:
        """Resolves the owning tenant_id for a store_id."""
        url = f"{self.base_url}/stores/{store_id}"
        headers = {"X-Service-Key": self.service_key}
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    return UUID(data["tenant_id"])
                if res.status_code == 404:
                    raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Store {store_id} not found", status_code=404)
                logger.error("tenant_resolve_store_failed", status=res.status_code, response=res.text)
                raise ApiError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"Tenant service returned status {res.status_code}", status_code=503)
        except httpx.RequestError as e:
            logger.error("tenant_connection_error", error=str(e))
            raise ApiError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"Could not reach Tenant service: {str(e)}", status_code=503)


iam_client = IamClient()
tenant_client = TenantClient()
