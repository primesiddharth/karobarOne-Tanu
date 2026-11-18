# tests/test_catalog_security.py
# Security, tenant isolation, and operational separation tests for Catalog service (RULES.md §5, APR-R02).
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app.main import app
from app import commands
from app import models

pytestmark = pytest.mark.asyncio


async def test_cross_store_idor_prevented():
    """Store owner of store A cannot create or modify items in store B (403 ENTITLEMENT_REQUIRED)."""
    store_a = uuid4()
    store_b = uuid4()

    owner_a = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[uuid4()],
        store_ids=[store_a],
    )

    mock_session = AsyncMock()

    # Attempting to create item in store_b
    with pytest.raises(ApiError) as exc_info:
        await commands.create_catalog_item_command(
            session=mock_session,
            store_id=store_b,
            principal=owner_a,
            item_type="PHYSICAL_PRODUCT",
            price_str="100.00",
            currency_code="INR",
            active=True,
            draft_title="IDOR Test",
            draft_description="",
            category_id=None,
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert exc_info.value.status_code == 403


async def test_operational_update_does_not_require_approval():
    """Operational fields (price, active) change immediately without approval (APR-R02)."""
    store_id = uuid4()
    item_id = uuid4()
    live_version_id = uuid4()

    owner = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[uuid4()],
        store_ids=[store_id],
    )

    item = models.CatalogItem(
        id=item_id,
        tenant_id=uuid4(),
        store_id=store_id,
        item_type="PHYSICAL_PRODUCT",
        price_paise=10000,
        currency_code="INR",
        active=True,
        live_version_id=live_version_id,
        draft_version_id=None,
    )

    mock_session = AsyncMock()
    mock_session.get.return_value = item

    updated_item, updated_at = await commands.update_operational_command(
        session=mock_session,
        item_id=item_id,
        principal=owner,
        price_str="250.00",
        active=False,
    )

    assert updated_item.price_paise == 25000
    assert updated_item.active is False
    assert updated_item.live_version_id == live_version_id  # Live version remains untouched!


async def test_no_generic_status_mutation_routes():
    """Verifies absence of generic status PATCH or PUT routes across the service (RULES.md §5.5)."""
    forbidden_methods = {"PATCH", "PUT"}
    for route in app.routes:
        if hasattr(route, "methods"):
            if forbidden_methods.intersection(route.methods):
                # Ensure path is not a generic status mutator
                assert "status" not in route.path.lower(), f"Forbidden generic status mutation route found: {route.path}"
