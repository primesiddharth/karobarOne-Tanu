# ==============================================================================
# File: microservice/tools/tests/test_config_validation.py
# Purpose: Verify startup config validation, prod secrets enforcement, and key parsing
# ==============================================================================
import hashlib
import pytest
from pydantic import ValidationError

from services.iam.app.config import Settings as IamSettings
from services.tenant.app.config import Settings as TenantSettings
from services.approval.app.config import Settings as ApprovalSettings
from services.catalog.app.config import Settings as CatalogSettings
from services.domain.app.config import Settings as DomainSettings
from services.customer.app.config import Settings as CustomerSettings


@pytest.mark.parametrize("SettingsClass", [
    IamSettings,
    TenantSettings,
    ApprovalSettings,
    CatalogSettings,
    DomainSettings,
    CustomerSettings,
])
def test_prod_rejects_default_secrets(SettingsClass):
    """In non-dev/local/test environments, default dev credentials and placeholders must be rejected."""
    with pytest.raises((ValidationError, ValueError)):
        SettingsClass(
            ENVIRONMENT="prod",
            # Defaults are kept for passwords / keys, should fail validation
        )


@pytest.mark.parametrize("SettingsClass", [
    IamSettings,
    TenantSettings,
    ApprovalSettings,
    CatalogSettings,
    DomainSettings,
    CustomerSettings,
])
def test_invalid_service_key_hashes_json_rejected(SettingsClass):
    """SERVICE_KEY_HASHES must be valid JSON object or fail at startup."""
    with pytest.raises((ValidationError, ValueError)):
        SettingsClass(
            ENVIRONMENT="dev",
            SERVICE_KEY_HASHES="not_valid_json{["
        )

    with pytest.raises((ValidationError, ValueError)):
        SettingsClass(
            ENVIRONMENT="dev",
            SERVICE_KEY_HASHES="[\"list\", \"not\", \"dict\"]"
        )


def test_caller_service_lookup_and_no_broad_except():
    """Verify that get_caller_service maps valid hashed key to caller, and returns None for invalid."""
    raw_key = "my_super_secret_test_key"
    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    settings = TenantSettings(
        ENVIRONMENT="dev",
        SERVICE_KEY_HASHES=f'{{"{key_hash}": "test-caller"}}'
    )

    assert settings.get_caller_service(raw_key) == "test-caller"
    assert settings.get_caller_service("wrong_key") is None
    assert settings.get_caller_service(None) is None


def test_iam_requires_private_key_in_prod():
    """IAM must require JWT_PRIVATE_KEY in production."""
    with pytest.raises((ValidationError, ValueError)):
        IamSettings(
            ENVIRONMENT="prod",
            DATABASE_URL="postgresql+asyncpg://iam_svc:real_secret@db.prod:5432/karobarone",
            MIGRATION_DATABASE_URL="postgresql+asyncpg://iam_migrator:real_secret@db.prod:5432/karobarone",
            MY_SERVICE_KEY="real_prod_service_key_1234567890",
            IDEMPOTENCY_ENCRYPTION_KEY="custom_encryption_key_32bytes_len",
            SERVICE_KEY_HASHES="{}",
            JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----",
            JWT_PRIVATE_KEY="",  # Missing private key in IAM
        )


def test_tenant_only_requires_public_key_in_prod():
    """Other services (e.g. Tenant) require only JWT_PUBLIC_KEY, not private key."""
    # TenantSettings does not even have JWT_PRIVATE_KEY attribute
    assert not hasattr(TenantSettings, "JWT_PRIVATE_KEY")

    # With non-default config, TenantSettings succeeds in prod without private key
    settings = TenantSettings(
        ENVIRONMENT="prod",
        DATABASE_URL="postgresql+asyncpg://tenant_svc:real_secret@db.prod:5432/karobarone",
        MIGRATION_DATABASE_URL="postgresql+asyncpg://tenant_migrator:real_secret@db.prod:5432/karobarone",
        MY_SERVICE_KEY="real_prod_service_key_1234567890",
        IDEMPOTENCY_ENCRYPTION_KEY="custom_encryption_key_32bytes_len",
        SERVICE_KEY_HASHES="{}",
        JWT_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...\n-----END PUBLIC KEY-----",
        HMAC_SECRET_KEY="custom_hmac_secret_key_prod_32b",
        PII_ENCRYPTION_KEY="custom_pii_encryption_key_prod_32b",
    )
    assert settings.ENVIRONMENT == "prod"
