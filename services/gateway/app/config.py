# app/config.py
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "dev"
    PORT: int = 8000
    SERVICE_NAME: str = "gateway"

    # Upstream service base URLs (fall back to localhost ports in dev)
    UPSTREAM_MONOLITH_URL: str = "http://localhost:8000"
    UPSTREAM_IAM_URL: str = "http://localhost:8001"
    UPSTREAM_TENANT_URL: str = "http://localhost:8002"
    UPSTREAM_APPROVAL_URL: str = "http://localhost:8003"
    UPSTREAM_CATALOG_URL: str = "http://localhost:8004"
    UPSTREAM_DOMAIN_URL: str = "http://localhost:8005"
    UPSTREAM_CUSTOMER_URL: str = "http://localhost:8006"
    UPSTREAM_SUBSCRIPTION_URL: str = "http://localhost:8007"
    UPSTREAM_INVENTORY_URL: str = "http://localhost:8008"

    ROUTES_FILE_PATH: str = str(Path(__file__).parent / "routes.yaml")
    GATEWAY_CLIENT_TIMEOUT_SEC: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
