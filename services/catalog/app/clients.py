# app/clients.py
# External & cross-service clients with stubs marked per RULES.md §13 & docs/STUBS.md
from uuid import UUID, uuid4
import httpx
import structlog
from libs.platform_contracts.errors import ApiError, ErrorCode
from .config import settings

logger = structlog.get_logger("catalog.clients")


class ApprovalServiceClient:
    """Client for synchronous calls to Approval & Governance service (APR-001) per RULES C7."""

    def __init__(self, base_url: str | None = None, service_key: str | None = None):
        self.base_url = (base_url or settings.APPROVAL_SERVICE_URL).rstrip("/")
        self.service_key = service_key or settings.APPROVAL_SERVICE_KEY

    async def submit_for_approval(
        self,
        tenant_id: UUID,
        store_id: UUID,
        subject_type: str,
        subject_id: UUID,
        subject_version: str | None,
        submitted_by: UUID,
        priority: int = 0,
    ) -> UUID:
        """Invokes POST /approvals (APR-001) synchronously."""
        url = f"{self.base_url}/approvals"
        headers = {
            "X-Service-Key": self.service_key,
            "Content-Type": "application/json",
        }
        payload = {
            "tenant_id": str(tenant_id),
            "store_id": str(store_id),
            "subject_type": subject_type,
            "subject_id": str(subject_id),
            "subject_version": subject_version,
            "submitted_by": str(submitted_by),
            "priority": priority,
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json=payload, headers=headers)
                if res.status_code in (200, 201):
                    data = res.json()
                    return UUID(data["approval_id"])

                logger.error("apr_submission_failed", status=res.status_code, response=res.text)
                raise ApiError(
                    ErrorCode.DEPENDENCY_UNAVAILABLE,
                    f"Approval service returned error status {res.status_code}",
                    status_code=503,
                )
        except httpx.RequestError as e:
            logger.error("apr_connection_error", error=str(e))
            raise ApiError(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                f"Could not reach Approval service: {str(e)}",
                status_code=503,
            )


class StorageClient:
    """Object storage adapter for generating non-guessable private upload URLs (BTDD §14).
    # STUB(catalog, OQ-013): Local MinIO emulator; replaced by cloud S3/R2 vendor in production.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        bucket: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
    ):
        self.endpoint = (endpoint or settings.S3_ENDPOINT).rstrip("/")
        self.bucket = bucket or settings.S3_BUCKET
        self.access_key = access_key or settings.S3_ACCESS_KEY
        self.secret_key = secret_key or settings.S3_SECRET_KEY
        self.region = region or settings.S3_REGION

    def generate_upload_intent(
        self,
        store_id: UUID,
        filename: str,
        media_type: str,
    ) -> tuple[str, str, str]:
        """Generates a non-guessable object key and pre-signed upload URL (15 min expiry per spec).

        Returns (storage_key, upload_url, public_or_cdn_url).
        """
        ext = filename.split(".")[-1].lower() if "." in filename else "bin"
        random_suffix = uuid4().hex
        storage_key = f"stores/{store_id}/media/{random_suffix}.{ext}"

        # S3-compatible pre-signed upload URL (MinIO locally)
        upload_url = f"{self.endpoint}/{self.bucket}/{storage_key}"
        try:
            import boto3
            s3 = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
            )
            upload_url = s3.generate_presigned_url(
                "put_object",
                Params={"Bucket": self.bucket, "Key": storage_key},
                ExpiresIn=900,
            )
        except Exception:
            pass

        cdn_url = f"{self.endpoint}/{self.bucket}/{storage_key}"
        return storage_key, upload_url, cdn_url

    async def verify_object_exists(self, storage_key: str) -> bool:
        """Verifies object exists in storage via HEAD request (SERVICES.md §4 CAT Rule 7)."""
        url = f"{self.endpoint}/{self.bucket}/{storage_key}"
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.head(url)
                return res.status_code == 200
        except Exception:
            return False


# Default client instances
approval_client = ApprovalServiceClient()
storage_client = StorageClient()



class SubscriptionServiceClient:
    """Client for synchronous calls to Subscription Service (SUB-004) per RULES C7."""

    def __init__(self, base_url: str | None = None, service_key: str | None = None):
        self.base_url = (base_url or settings.SUBSCRIPTION_SERVICE_URL).rstrip("/")
        self.service_key = service_key or settings.SUBSCRIPTION_SERVICE_KEY

    async def get_store_entitlements(self, store_id: UUID) -> dict:
        """Invokes GET /api/v1/stores/{store_id}/entitlements (SUB-004)."""
        url = f"{self.base_url}/api/v1/stores/{store_id}/entitlements"
        headers = {
            "X-Service-Key": self.service_key,
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(url, headers=headers)
                if res.status_code == 200:
                    return res.json()
        except Exception:
            pass
        # Fallback to Free presence
        return {
            "plan_code": "PRESENCE",
            "state": "ACTIVE_PERIOD_1",
            "commerce_enabled": False,
            "showcase_limit": 6,
            "max_images_per_item": 1,
            "max_videos_per_item": 0,
            "custom_domain_allowed": False,
            "blog_allowed": False,
        }


subscription_client = SubscriptionServiceClient()
