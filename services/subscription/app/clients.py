# app/clients.py
from uuid import UUID
import httpx
import structlog
from libs.platform_contracts.errors import ApiError, ErrorCode
from .config import settings

logger = structlog.get_logger("subscription.clients")


class TenantServiceClient:
    """Client for cross-service calls to Tenant Service (RULES C7)."""

    def __init__(self, base_url: str | None = None, service_key: str | None = None):
        self.base_url = (base_url or settings.TENANT_SERVICE_URL).rstrip("/")
        self.service_key = service_key or settings.TENANT_SERVICE_KEY

    async def verify_store_gstin(
        self,
        tenant_id: UUID,
        store_id: UUID,
        gstin_id: UUID | None = None,
    ) -> bool:
        """Verifies that the store has a verified GSTIN assigned (AC-008, AC-009)."""
        if not gstin_id:
            # Paid commerce requires a verified GSTIN per AC-008
            return False

        url = f"{self.base_url}/stores/{store_id}"
        headers = {
            "X-Service-Key": self.service_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    # Verified GSTIN must match the requested gstin_id
                    stored_gstin_id = data.get("gstin_id")
                    return bool(stored_gstin_id and str(stored_gstin_id) == str(gstin_id))
                if res.status_code == 404:
                    return False
                logger.error("tenant_verify_gstin_failed", status=res.status_code, response=res.text)
                raise ApiError(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    f"Tenant service returned status {res.status_code}",
                    status_code=503,
                )
        except httpx.RequestError as e:
            logger.error("tenant_connection_error", error=str(e))
            raise ApiError(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                f"Could not reach Tenant service: {str(e)}",
                status_code=503,
            )


tenant_client = TenantServiceClient()
