# app/config.py
import base64
import hashlib
import json
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
DEV_SERVICE_KEYS = {
    "iam": "dev_secret_key_iam",
    "tenant": "dev_secret_key_tenant",
    "approval": "dev_secret_key_approval",
    "catalog": "dev_secret_key_catalog",
    "domain": "dev_secret_key_domain",
    "customer": "dev_secret_key_customer",
    "subscription": "dev_secret_key_subscription",
    "inventory": "dev_secret_key_inventory",
    "gateway": "dev_secret_key_gateway",
}

DEV_SERVICE_KEY_HASHES: dict[str, str] = {
    hashlib.sha256(raw_key.encode("utf-8")).hexdigest(): svc_name
    for svc_name, raw_key in DEV_SERVICE_KEYS.items()
}

DEFAULT_DEV_IDEMPOTENCY_KEY = base64.urlsafe_b64encode(b"0" * 32).decode("utf-8")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "microservice/.env", "../.env"), extra="ignore")
    ENVIRONMENT: str = "dev"
    SERVICE_NAME: str = "domain"
    DATABASE_URL: str = "postgresql+asyncpg://domain_svc:dev_svc_secret@localhost:5432/karobarone_dev"
    MIGRATION_DATABASE_URL: str = "postgresql+asyncpg://domain_migrator:dev_migrator_secret@localhost:5432/karobarone_dev"
    MY_SERVICE_KEY: str = "dev_secret_key_domain"
    SERVICE_KEY_HASHES: str = "{\"allowed_hash_placeholder\": \"gateway\"}"
    OUTBOX_RELAY_ENABLED: bool = True
    OUTBOX_BATCH_SIZE: int = 50
    OUTBOX_LEASE_SECONDS: int = 30

    # Root domain configuration (BTDD §9.4, RULES.md §5.7)
    ROOT_DOMAIN: str = "karobarone.com"
    EXPECTED_CNAME_TARGET: str = "custom.karobarone.com"

    # Cross-service client URLs (RULES §5.3)
    TENANT_SERVICE_URL: str = "http://localhost:8002"
    SUBSCRIPTION_SERVICE_URL: str = "http://localhost:8007"
    CATALOG_SERVICE_URL: str = "http://localhost:8004"
    APPROVAL_SERVICE_URL: str = "http://localhost:8003"

    # JWT Configuration (for verifying caller tokens issued by IAM - only public key needed)
    JWT_PUBLIC_KEY: str = ""
    ISSUER: str = "karobarone-iam"
    AUDIENCE: str = "karobarone-api"

    # Encryption key for idempotency cached response payload
    IDEMPOTENCY_ENCRYPTION_KEY: str = DEFAULT_DEV_IDEMPOTENCY_KEY

    _parsed_service_key_hashes: dict[str, str] = {}

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if "\\n" in self.JWT_PUBLIC_KEY:
            self.JWT_PUBLIC_KEY = self.JWT_PUBLIC_KEY.replace("\\n", "\n")
        try:
            parsed = json.loads(self.SERVICE_KEY_HASHES)
            if not isinstance(parsed, dict):
                raise ValueError("SERVICE_KEY_HASHES must be a JSON object mapping hash to caller")
            self._parsed_service_key_hashes = parsed
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"SERVICE_KEY_HASHES is invalid JSON: {exc}") from exc

        if self.ENVIRONMENT.lower() not in ("dev", "local", "test"):
            if "dev_svc_secret" in self.DATABASE_URL or "dev_migrator_secret" in self.MIGRATION_DATABASE_URL:
                raise ValueError("DATABASE_URL / MIGRATION_DATABASE_URL contains default dev password in non-dev environment")
            if self.MY_SERVICE_KEY.startswith("dev_secret_key_") or not self.MY_SERVICE_KEY:
                raise ValueError("MY_SERVICE_KEY is using an insecure development default in non-dev environment")
            if self.IDEMPOTENCY_ENCRYPTION_KEY == DEFAULT_DEV_IDEMPOTENCY_KEY:
                raise ValueError("IDEMPOTENCY_ENCRYPTION_KEY is using default placeholder in non-dev environment")
            if not self.JWT_PUBLIC_KEY:
                raise ValueError("JWT_PUBLIC_KEY must be explicitly configured in non-dev environment")

        return self

    def get_caller_service(self, raw_api_key: str | None) -> str | None:
        """Hashes raw_api_key with SHA-256 and maps to registered caller service."""
        if not raw_api_key:
            return None
        key_hash = hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest()
        if key_hash in self._parsed_service_key_hashes:
            return self._parsed_service_key_hashes[key_hash]
        if self.ENVIRONMENT.lower() in ("dev", "local", "test"):
            if key_hash in DEV_SERVICE_KEY_HASHES:
                return DEV_SERVICE_KEY_HASHES[key_hash]
        parsed = json.loads(self.SERVICE_KEY_HASHES)
        return parsed.get(key_hash)


settings = Settings()
