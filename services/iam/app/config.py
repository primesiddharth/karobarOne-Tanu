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
DEFAULT_DEV_HMAC_KEY = "dev_hmac_fingerprint_secret_key_32bytes!"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "microservice/.env", "../.env"), extra="ignore")
    ENVIRONMENT: str = "dev"
    SERVICE_NAME: str = "iam"
    DATABASE_URL: str = "postgresql+asyncpg://iam_svc:dev_svc_secret@localhost:5432/karobarone_dev"
    MIGRATION_DATABASE_URL: str = "postgresql+asyncpg://iam_migrator:dev_migrator_secret@localhost:5432/karobarone_dev"
    MY_SERVICE_KEY: str = "dev_secret_key_iam"
    SERVICE_KEY_HASHES: str = "{\"allowed_hash_placeholder\": \"gateway\"}"
    OUTBOX_RELAY_ENABLED: bool = True
    OUTBOX_BATCH_SIZE: int = 50
    OUTBOX_LEASE_SECONDS: int = 30

    # JWT Configuration (RULES.md §8 & OQ-003)
    JWT_KID: str = "key-dev-static-2026"
    JWT_PRIVATE_KEY: str = ""
    JWT_PUBLIC_KEY: str = ""
    JWT_PREVIOUS_PUBLIC_KEY: str | None = None
    ACCESS_TOKEN_TTL_SECONDS: int = 900       # 15 minutes
    REFRESH_TOKEN_TTL_SECONDS: int = 604800   # 7 days
    ISSUER: str = "karobarone-iam"
    AUDIENCE: str = "karobarone-api"

    # OTP & Security Configuration (OQ-007)
    OTP_TTL_SECONDS: int = 300                # 5 minutes
    OTP_ATTEMPT_LIMIT: int = 5                # Max 5 attempts
    OTP_RATE_LIMIT_SECONDS: int = 900         # 15 minute sliding window
    OTP_MAX_CHALLENGES_PER_WINDOW: int = 3    # Max 3 challenges per window
    HMAC_SECRET_KEY: str = DEFAULT_DEV_HMAC_KEY

    # Idempotency encryption (OQ-038)
    IDEMPOTENCY_ENCRYPTION_KEY: str = DEFAULT_DEV_IDEMPOTENCY_KEY

    _parsed_service_key_hashes: dict[str, str] = {}

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if "\\n" in self.JWT_PRIVATE_KEY:
            self.JWT_PRIVATE_KEY = self.JWT_PRIVATE_KEY.replace("\\n", "\n")
        if "\\n" in self.JWT_PUBLIC_KEY:
            self.JWT_PUBLIC_KEY = self.JWT_PUBLIC_KEY.replace("\\n", "\n")

        # 1. Parse and validate SERVICE_KEY_HASHES
        try:
            parsed = json.loads(self.SERVICE_KEY_HASHES)
            if not isinstance(parsed, dict):
                raise ValueError("SERVICE_KEY_HASHES must be a JSON object mapping hash to caller")
            self._parsed_service_key_hashes = parsed
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"SERVICE_KEY_HASHES is invalid JSON: {exc}") from exc

        # 2. Refuse default secrets in non-dev environments (staging, prod, etc.)
        if self.ENVIRONMENT.lower() not in ("dev", "local", "test"):
            if "dev_svc_secret" in self.DATABASE_URL or "dev_migrator_secret" in self.MIGRATION_DATABASE_URL:
                raise ValueError("DATABASE_URL / MIGRATION_DATABASE_URL contains default dev password in non-dev environment")
            if self.MY_SERVICE_KEY.startswith("dev_secret_key_") or not self.MY_SERVICE_KEY:
                raise ValueError("MY_SERVICE_KEY is using an insecure development default in non-dev environment")
            if self.HMAC_SECRET_KEY == DEFAULT_DEV_HMAC_KEY:
                raise ValueError("HMAC_SECRET_KEY is using default dev key in non-dev environment")
            if self.IDEMPOTENCY_ENCRYPTION_KEY == DEFAULT_DEV_IDEMPOTENCY_KEY:
                raise ValueError("IDEMPOTENCY_ENCRYPTION_KEY is using default placeholder in non-dev environment")
            if not self.JWT_PRIVATE_KEY or not self.JWT_PUBLIC_KEY or self.JWT_KID == "key-dev-default":
                raise ValueError("IAM requires non-default JWT_PRIVATE_KEY, JWT_PUBLIC_KEY, and JWT_KID in non-dev environment")

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
