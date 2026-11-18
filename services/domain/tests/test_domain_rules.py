# tests/test_domain_rules.py
# Pure business logic and domain rules tests for DOM (RULES.md §5, State Machine §6).
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import domain, commands, models


def make_mock_session(execute_results=None):
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()

    results = list(execute_results or [])

    async def _execute(*args, **kwargs):
        if results:
            return results.pop(0)
        res = MagicMock()
        res.scalars.return_value.first.return_value = None
        res.scalars.return_value.all.return_value = []
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session


def test_subdomain_label_validation():
    """Validates slug formatting and length boundaries."""
    assert domain.sanitize_subdomain_label("my-store") == "my-store"
    assert domain.sanitize_subdomain_label("STORE123") == "store123"  # Normalized to lower
    assert domain.sanitize_subdomain_label("  craft-shop  ") == "craft-shop"

    # Too short (< 3)
    with pytest.raises(ApiError) as exc_info:
        domain.sanitize_subdomain_label("ab")
    assert exc_info.value.status_code == 422

    # Too long (> 63)
    with pytest.raises(ApiError) as exc_info:
        domain.sanitize_subdomain_label("a" * 64)
    assert exc_info.value.status_code == 422

    # Invalid characters
    for invalid in ["store_name", "store.name", "store!name", "-leading-hyphen", "trailing-hyphen-"]:
        with pytest.raises(ApiError) as exc_info:
            domain.sanitize_subdomain_label(invalid)
        assert exc_info.value.status_code == 422


def test_reserved_subdomain_rejections():
    """Verifies reserved system subdomains are rejected with 409."""
    for reserved in ["admin", "api", "app", "auth", "billing", "dashboard", "gateway", "karobarone", "root", "www"]:
        with pytest.raises(ApiError) as exc_info:
            domain.sanitize_subdomain_label(reserved)
        assert exc_info.value.status_code == 409
        assert "reserved" in exc_info.value.message


def test_build_fqdn():
    """Builds standard FQDN with configured root domain."""
    assert domain.build_fqdn("my-store", "karobarone.com") == "my-store.karobarone.com"
    assert domain.build_fqdn("shop", "TEST.COM") == "shop.test.com"


@pytest.mark.asyncio
async def test_publish_store_without_subdomain_rejected(monkeypatch):
    """Publish command without an assigned subdomain fails with 409 INVALID_STATE_TRANSITION."""
    store_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[uuid4()],
        store_ids=[store_id],
    )

    mock_session = make_mock_session()
    monkeypatch.setattr(
        commands.tenant_client,
        "get_store_compliance",
        AsyncMock(return_value={"lifecycle_status": "ACTIVE", "store_mode": "FREE_PRESENCE"}),
    )

    with pytest.raises(ApiError) as exc_info:
        await commands.publish_store_command(
            session=mock_session,
            store_id=store_id,
            principal=owner_principal,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION
    assert "without an assigned subdomain" in exc_info.value.message


@pytest.mark.asyncio
async def test_publish_store_success(monkeypatch):
    """Publish command activates subdomain and publication route."""
    store_id = uuid4()
    tenant_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    monkeypatch.setattr(
        commands.tenant_client,
        "get_store_compliance",
        AsyncMock(return_value={"lifecycle_status": "ACTIVE", "store_mode": "FREE_PRESENCE"}),
    )

    sub = models.Subdomain(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        label="my-bakery",
        fqdn="my-bakery.karobarone.com",
        status="ASSIGNED",
    )
    route = models.PublicationRoute(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        route_type="FREE_SUBDOMAIN",
        hostname="my-bakery.karobarone.com",
        status="DISABLED",
    )

    res_sub = MagicMock()
    res_sub.scalars.return_value.first.return_value = sub
    res_route = MagicMock()
    res_route.scalars.return_value.first.return_value = route

    mock_session = make_mock_session([res_sub, res_route])

    s_id, state, active_host, published_at = await commands.publish_store_command(
        session=mock_session,
        store_id=store_id,
        principal=owner_principal,
    )

    assert s_id == store_id
    assert state == "PUBLIC_LIVE"
    assert active_host == "my-bakery.karobarone.com"
    assert sub.status == "ACTIVE"
    assert route.status == "ACTIVE"


@pytest.mark.asyncio
async def test_resolve_route_query():
    """Route resolution query maps active host to publication route."""
    store_id = uuid4()
    tenant_id = uuid4()
    route = models.PublicationRoute(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        route_type="FREE_SUBDOMAIN",
        hostname="active-store.karobarone.com",
        status="ACTIVE",
    )

    res_route = MagicMock()
    res_route.scalars.return_value.first.return_value = route
    mock_session = make_mock_session([res_route])

    resolved = await commands.resolve_route_query(
        session=mock_session,
        hostname="ACTIVE-STORE.KAROBARONE.COM ",  # Test case-insensitivity and trim
    )
    assert resolved.store_id == store_id
    assert resolved.hostname == "active-store.karobarone.com"

    # Unknown or inactive host raises 404
    mock_session_none = make_mock_session()

    with pytest.raises(ApiError) as exc_info:
        await commands.resolve_route_query(
            session=mock_session_none,
            hostname="unknown-store.karobarone.com",
        )
    assert exc_info.value.status_code == 404
