# app/clients.py
# External & cross-service clients with stubs marked per RULES.md §13 & docs/STUBS.md
from uuid import UUID, uuid4
from typing import Dict, Any, List, Optional
import httpx
import structlog
from libs.platform_contracts.errors import ApiError, ErrorCode
from .config import settings
from . import schemas

logger = structlog.get_logger("domain.clients")


# ==============================================================================
# In-process Mock Adapters (RULES.md §13, STUBS.md)
# ==============================================================================

class MockRegistrarAdapter:
    """Mock Registrar Provider Adapter.
    Simulates domain availability check, purchase, and reference lookup.
    """

    def __init__(self):
        # In-memory lookup registry for simulating timeout-then-lookup idempotent recovery
        self._purchases_by_ref: Dict[str, Dict[str, Any]] = {}

    def check_availability(self, domain_names: List[str]) -> List[schemas.DomainOptionDto]:
        """Checks availability and determines cost classification."""
        results = []
        for raw_name in domain_names:
            name = raw_name.lower().strip()
            # Unavailable simulation: names starting with 'taken' or 'unavailable'
            is_available = not (name.startswith("taken") or name.startswith("unavailable"))

            # Cost classification rule:
            # Standard: .com, .in, .co.in, .org without 'premium' in name and length > 4 chars
            # Premium: .ai, .io, length <= 4, or containing 'premium'
            tld = name.split(".")[-1] if "." in name else ""
            sld = name.split(".")[0] if "." in name else name

            if "premium" in name or tld in ("ai", "io") or len(sld) <= 4:
                cost_class = "PREMIUM"
                price_paise = 499900  # ₹4,999.00
            else:
                cost_class = "STANDARD"
                price_paise = 0  # Included in paid plan per AC-086

            results.append(
                schemas.DomainOptionDto(
                    domain_name=name,
                    is_available=is_available,
                    cost_class=cost_class,
                    price_paise=price_paise,
                )
            )
        return results

    def purchase_domain(self, domain_name: str, request_reference: str) -> Dict[str, Any]:
        """Simulates domain purchase with registrar reference."""
        # Check if already purchased under this request reference (idempotency)
        if request_reference in self._purchases_by_ref:
            return self._purchases_by_ref[request_reference]

        # Simulation: if domain contains 'timeout', raise ConnectTimeout for testing timeout-then-lookup
        if "sim-timeout" in domain_name and request_reference not in self._purchases_by_ref:
            # Record backend state before raising simulated network timeout
            reg_ref = f"REG-MOCK-{uuid4().hex[:10].upper()}"
            self._purchases_by_ref[request_reference] = {
                "registrar_reference": reg_ref,
                "domain_name": domain_name,
                "status": "PURCHASED",
            }
            raise httpx.ConnectTimeout("Simulated registrar connection timeout")

        reg_ref = f"REG-MOCK-{uuid4().hex[:10].upper()}"
        record = {
            "registrar_reference": reg_ref,
            "domain_name": domain_name,
            "status": "PURCHASED",
        }
        self._purchases_by_ref[request_reference] = record
        return record

    def lookup_purchase(self, request_reference: str) -> Optional[Dict[str, Any]]:
        """Queries registrar by request reference to avoid blind re-purchases after ambiguous timeouts."""
        return self._purchases_by_ref.get(request_reference)


class MockDnsAdapter:
    """Mock DNS Provider Adapter."""

    def verify_records(self, domain_name: str, expected_target: str) -> bool:
        """Verifies CNAME or A records for domain."""
        name = domain_name.lower().strip()
        # Simulated DNS failure if name starts with 'unconfigured' or 'dns-fail'
        if name.startswith("unconfigured") or name.startswith("dns-fail"):
            return False
        return True


# ==============================================================================
# Cross-Service HTTP Clients (Fail Closed per RULES.md §5.3)
# ==============================================================================

class TenantServiceClient:
    """Synchronous client to Tenant Service (TEN-009)."""

    def __init__(self, base_url: str | None = None, service_key: str | None = None):
        self.base_url = (base_url or settings.TENANT_SERVICE_URL).rstrip("/")
        self.service_key = service_key or settings.MY_SERVICE_KEY

    async def get_store_compliance(self, store_id: UUID) -> Dict[str, Any]:
        """Fetches store details to verify lifecycle_status, store_mode, and gstin_id.
        Fails closed with 503 DEPENDENCY_UNAVAILABLE if Tenant service is unreachable.
        """
        url = f"{self.base_url}/stores/{store_id}"
        headers = {
            "X-Service-Key": self.service_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    return res.json()
                if res.status_code == 404:
                    raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Store {store_id} not found", status_code=404)
                logger.error("tenant_store_lookup_failed", status=res.status_code, response=res.text)
                raise ApiError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"Tenant service returned status {res.status_code}", status_code=503)
        except httpx.RequestError as e:
            logger.error("tenant_service_unreachable", error=str(e))
            raise ApiError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"Could not reach Tenant service: {str(e)}", status_code=503)


class SubscriptionServiceClient:
    """Synchronous client to Subscription Service."""

    def __init__(self, base_url: str | None = None, service_key: str | None = None):
        self.base_url = (base_url or settings.SUBSCRIPTION_SERVICE_URL).rstrip("/")
        self.service_key = service_key or settings.MY_SERVICE_KEY

    async def get_store_subscription_status(self, store_id: UUID) -> Dict[str, Any]:
        """Queries subscription details for store.
        Fails closed with 503 DEPENDENCY_UNAVAILABLE if Subscription service is unreachable.
        """
        url = f"{self.base_url}/stores/{store_id}/subscription"
        headers = {
            "X-Service-Key": self.service_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    return res.json()
                if res.status_code == 404:
                    # No active subscription found
                    return {"state": "NONE", "is_active": False}
                logger.error("subscription_lookup_failed", status=res.status_code, response=res.text)
                raise ApiError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"Subscription service returned status {res.status_code}", status_code=503)
        except httpx.RequestError as e:
            logger.error("subscription_service_unreachable", error=str(e))
            raise ApiError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"Could not reach Subscription service: {str(e)}", status_code=503)


class CatalogServiceClient:
    """Synchronous client to Catalog Service."""

    def __init__(self, base_url: str | None = None, service_key: str | None = None):
        self.base_url = (base_url or settings.CATALOG_SERVICE_URL).rstrip("/")
        self.service_key = service_key or settings.MY_SERVICE_KEY

    async def verify_store_content_approved(self, store_id: UUID) -> bool:
        """Verifies store has approved content eligible for public serving (CAT-010).
        Fails closed with 503 DEPENDENCY_UNAVAILABLE if Catalog service is unreachable.
        """
        url = f"{self.base_url}/public/stores/{store_id}/snapshot"
        headers = {
            "X-Service-Key": self.service_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    # Must contain approved items or published pages
                    items = data.get("items", [])
                    return len(items) > 0 or data.get("is_published", False)
                if res.status_code == 404:
                    return False
                logger.error("catalog_snapshot_failed", status=res.status_code, response=res.text)
                raise ApiError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"Catalog service returned status {res.status_code}", status_code=503)
        except httpx.RequestError as e:
            logger.error("catalog_service_unreachable", error=str(e))
            raise ApiError(ErrorCode.DEPENDENCY_UNAVAILABLE, f"Could not reach Catalog service: {str(e)}", status_code=503)


mock_registrar_adapter = MockRegistrarAdapter()
mock_dns_adapter = MockDnsAdapter()
tenant_client = TenantServiceClient()
subscription_client = SubscriptionServiceClient()
catalog_client = CatalogServiceClient()
