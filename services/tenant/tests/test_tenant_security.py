# tests/test_tenant_security.py
# Security tests: Guardian privilege separation (SEC-TST-005), IDOR tenant isolation,
# PAN/GSTIN log redaction (FND-TST-028), and generic PATCH refusal.
import pytest
import io
import structlog
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import commands
from app import models
from app.main import app
from tools.tests.test_log_redaction import redact_sensitive_values

pytestmark = pytest.mark.asyncio


# -----------------------------------------------------------------------------
# SEC-TST-005: Guardian Privilege Separation
# -----------------------------------------------------------------------------
async def test_guardian_cannot_create_store():
    """Guardian role identity is denied on store creation commands (SEC-TST-005, TEN-R04)."""
    tenant_id = uuid4()
    guardian_principal = Principal(
        sub=uuid4(),
        roles=["GUARDIAN"],
        tenant_ids=[tenant_id],
        store_ids=[],
    )

    mock_session = AsyncMock()

    with pytest.raises(ApiError) as exc_info:
        await commands.create_store_command(
            session=mock_session,
            tenant_id=tenant_id,
            current_principal=guardian_principal,
            store_code="guardian-store",
            display_name="Guardian Store",
            store_mode="FREE_PRESENCE",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert "Guardian role cannot perform store operations" in exc_info.value.message


async def test_guardian_cannot_manage_staff():
    """Guardian role identity cannot assign or revoke store staff (SEC-TST-005)."""
    tenant_id = uuid4()
    store_id = uuid4()
    guardian_principal = Principal(
        sub=uuid4(),
        roles=["GUARDIAN"],
        tenant_ids=[tenant_id],
        store_ids=[],
    )

    mock_session = AsyncMock()
    mock_store = models.Store(id=store_id, tenant_id=tenant_id, store_code="store1", display_name="Store 1")
    mock_session.get.return_value = mock_store

    with pytest.raises(ApiError) as exc_info:
        await commands.assign_store_staff_command(
            session=mock_session,
            store_id=store_id,
            current_principal=guardian_principal,
            target_principal_id=uuid4(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED


# -----------------------------------------------------------------------------
# IDOR & Tenant Boundary Isolation
# -----------------------------------------------------------------------------
async def test_cross_tenant_access_denied():
    """Principal for Tenant A cannot access Tenant B profile (IDOR prevention)."""
    tenant_a = uuid4()
    tenant_b = uuid4()

    principal_a = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_a],
        store_ids=[],
    )

    mock_session = AsyncMock()

    with pytest.raises(ApiError) as exc_info:
        await commands.get_tenant_command(
            session=mock_session,
            tenant_id=tenant_b,
            current_principal=principal_a,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED


# -----------------------------------------------------------------------------
# FND-TST-028: PAN & GSTIN Redaction in Logs
# -----------------------------------------------------------------------------
async def test_pan_and_gstin_redacted_in_logs():
    """PAN and GSTIN values must never enter logs in plaintext (RULES.md §5.10, FND-TST-028)."""
    buffer = io.StringIO()
    structlog.configure(
        processors=[
            redact_sensitive_values,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=buffer),
    )

    logger = structlog.get_logger("tenant_security_test")
    raw_pan = "ABCPD1234F"
    raw_gstin = "27ABCPD1234F1Z5"

    logger.info("tax_registration", pan=raw_pan, gstin=raw_gstin, other="public_info")
    output = buffer.getvalue()

    assert raw_pan not in output, "Plain PAN leaked into logs"
    assert raw_gstin not in output, "Plain GSTIN leaked into logs"
    assert "public_info" in output


# -----------------------------------------------------------------------------
# RULES.md §5.5: No Generic Status Mutation
# -----------------------------------------------------------------------------
async def test_no_generic_status_mutation_routes():
    """Verifies that no PATCH routes exist for generic status mutations."""
    patch_routes = [route.path for route in app.routes if "PATCH" in getattr(route, "methods", set())]
    assert len(patch_routes) == 0, f"Found unauthorized generic PATCH routes: {patch_routes}"
