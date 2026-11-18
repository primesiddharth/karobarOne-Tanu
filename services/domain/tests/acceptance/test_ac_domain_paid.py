# tests/acceptance/test_ac_domain_paid.py
# Acceptance Criteria test suite for Phase 9: Domain & Publication (Paid Part)
# Covers: AC-059, AC-085, AC-086, AC-087, AC-088, publish gates, timeout recovery, and event contracts.
import pytest
from uuid import UUID, uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import httpx

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import commands, domain, models, schemas
from app.events import handle_internal_event
from app.clients import mock_registrar_adapter

pytestmark = pytest.mark.asyncio


def make_mock_session(execute_results=None):
    """Helper creating mock AsyncSession tracking added models and executed outbox inserts."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.added_models = []

    def _add(item):
        mock_session.added_models.append(item)
    mock_session.add.side_effect = _add

    results = list(execute_results or [])
    mock_session.executed_calls = []

    async def _execute(statement, params=None, *args, **kwargs):
        mock_session.executed_calls.append((statement, params))
        if results:
            return results.pop(0)
        res = MagicMock()
        res.scalars.return_value.first.return_value = None
        res.scalars.return_value.all.return_value = []
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session


def get_outbox_events(mock_session):
    """Extracts all outbox events recorded via session.execute."""
    events = []
    for stmt, params in mock_session.executed_calls:
        if params and "event_type" in params:
            events.append(params)
    return events


# ==============================================================================
# AC-085: Options Checked & Selected (DOM-002, DOM-003)
# ==============================================================================

async def test_ac_085_domain_options_checked_and_selected():
    """DOM-002 checks options and DOM-003 selects domain, emitting events."""
    store_id = uuid4()
    tenant_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    # 1. Check options (DOM-002)
    session1 = make_mock_session()
    domain_names = ["mybrand.com", "mybrand.ai", "takenbrand.com"]
    req, options = await commands.check_domain_options_command(
        session=session1,
        store_id=store_id,
        domain_names=domain_names,
        principal=owner_principal,
    )
    assert req.store_id == store_id
    assert req.status == "AVAILABILITY_CHECKED"
    assert len(options) == 3

    # Verify classification: .com is standard/0; .ai is premium/499900; taken is unavailable
    opt_com = next(o for o in options if o.domain_name == "mybrand.com")
    opt_ai = next(o for o in options if o.domain_name == "mybrand.ai")
    opt_taken = next(o for o in options if o.domain_name == "takenbrand.com")

    assert opt_com.is_available is True
    assert opt_com.cost_class == "STANDARD"
    assert opt_com.price_paise == 0

    assert opt_ai.is_available is True
    assert opt_ai.cost_class == "PREMIUM"
    assert opt_ai.price_paise == 499900

    assert opt_taken.is_available is False

    events1 = get_outbox_events(session1)
    assert any(e["event_type"] == "domain.options-checked.v1" for e in events1)

    # 2. Select unavailable option -> fails 409
    res_req = MagicMock()
    res_req.scalars.return_value.first.return_value = req
    session_fail = make_mock_session([res_req])
    with pytest.raises(ApiError) as exc_info:
        await commands.select_domain_option_command(
            session=session_fail,
            request_id=req.id,
            selected_domain="takenbrand.com",
            principal=owner_principal,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION

    # 3. Select valid option (DOM-003) -> succeeds
    res_req_ok = MagicMock()
    res_req_ok.scalars.return_value.first.return_value = req
    session2 = make_mock_session([res_req_ok])
    updated_req = await commands.select_domain_option_command(
        session=session2,
        request_id=req.id,
        selected_domain="mybrand.com",
        principal=owner_principal,
    )
    assert updated_req.selected_domain == "mybrand.com"
    assert updated_req.cost_class == "STANDARD"
    assert updated_req.price_paise == 0
    assert updated_req.status == "SELECTED"

    events2 = get_outbox_events(session2)
    assert any(e["event_type"] == "domain.selected.v1" for e in events2)


# ==============================================================================
# AC-086: Standard Domain Purchase Included (DOM-004)
# ==============================================================================

async def test_ac_086_standard_domain_purchase_included_and_idempotent():
    """Standard qualifying domain cost is included; purchase succeeds without extra approval/payment refs."""
    store_id = uuid4()
    tenant_id = uuid4()
    req_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    req = models.DomainRequest(
        id=req_id,
        tenant_id=tenant_id,
        store_id=store_id,
        preferred_domains=["standardstore.com"],
        selected_domain="standardstore.com",
        cost_class="STANDARD",
        price_paise=0,
        status="SELECTED",
        version=2,
    )

    # 1. Purchase succeeds without approval_ref / payment_ref
    res_req = MagicMock()
    res_req.scalars.return_value.first.return_value = req
    res_existing_name = MagicMock()
    res_existing_name.scalars.return_value.first.return_value = None

    session = make_mock_session([res_req, res_existing_name])
    custom_domain = await commands.purchase_domain_command(
        session=session,
        request_id=req_id,
        principal=owner_principal,
    )
    assert custom_domain.domain_name == "standardstore.com"
    assert custom_domain.cost_class == "STANDARD"
    assert custom_domain.purchase_cost == 0
    assert custom_domain.status == "PURCHASED"
    assert custom_domain.registrar_reference.startswith("REG-MOCK-")
    assert req.status == "PURCHASED"

    events = get_outbox_events(session)
    assert any(e["event_type"] == "domain.purchased.v1" for e in events)

    # 2. Idempotent re-purchase returns existing custom domain
    res_req_purchased = MagicMock()
    res_req_purchased.scalars.return_value.first.return_value = req
    res_existing_cd = MagicMock()
    res_existing_cd.scalars.return_value.first.return_value = custom_domain

    session_idem = make_mock_session([res_req_purchased, res_existing_cd])
    cd_repeat = await commands.purchase_domain_command(
        session=session_idem,
        request_id=req_id,
        principal=owner_principal,
    )
    assert cd_repeat.id == custom_domain.id


# ==============================================================================
# AC-087: Premium Domain Purchase Rules (DOM-004)
# ==============================================================================

async def test_ac_087_premium_domain_purchase_requires_approval_and_payment():
    """Premium domain requires both approval_ref and payment_ref; fails closed if either missing."""
    store_id = uuid4()
    tenant_id = uuid4()
    req_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    req = models.DomainRequest(
        id=req_id,
        tenant_id=tenant_id,
        store_id=store_id,
        preferred_domains=["luxury.ai"],
        selected_domain="luxury.ai",
        cost_class="PREMIUM",
        price_paise=499900,
        status="SELECTED",
        version=2,
    )

    # 1. Missing approval_ref -> 409 UPGRADE_APPROVAL_REQUIRED
    res_req1 = MagicMock()
    res_req1.scalars.return_value.first.return_value = req
    session1 = make_mock_session([res_req1])
    with pytest.raises(ApiError) as exc_info:
        await commands.purchase_domain_command(
            session=session1,
            request_id=req_id,
            principal=owner_principal,
            approval_ref=None,
            payment_ref="PAY-12345",
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.UPGRADE_APPROVAL_REQUIRED

    # 2. Missing payment_ref -> 409 PAYMENT_NOT_CONFIRMED
    res_req2 = MagicMock()
    res_req2.scalars.return_value.first.return_value = req
    session2 = make_mock_session([res_req2])
    with pytest.raises(ApiError) as exc_info:
        await commands.purchase_domain_command(
            session=session2,
            request_id=req_id,
            principal=owner_principal,
            approval_ref="APR-PREM-001",
            payment_ref=None,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.PAYMENT_NOT_CONFIRMED

    # 3. Both provided -> purchase succeeds
    res_req3 = MagicMock()
    res_req3.scalars.return_value.first.return_value = req
    res_dup_none = MagicMock()
    res_dup_none.scalars.return_value.first.return_value = None

    session3 = make_mock_session([res_req3, res_dup_none])
    cd = await commands.purchase_domain_command(
        session=session3,
        request_id=req_id,
        principal=owner_principal,
        approval_ref="APR-PREM-001",
        payment_ref="PAY-12345",
    )
    assert cd.domain_name == "luxury.ai"
    assert cd.cost_class == "PREMIUM"
    assert cd.purchase_cost == 499900
    assert cd.approval_ref == "APR-PREM-001"
    assert cd.payment_ref == "PAY-12345"
    assert cd.status == "PURCHASED"


# ==============================================================================
# Registrar Timeout-Then-Lookup Idempotent Recovery
# ==============================================================================

async def test_ac_registrar_timeout_then_lookup_recovery():
    """Registrar ambiguous timeout recovers by looking up purchase reference instead of blind re-ordering."""
    store_id = uuid4()
    tenant_id = uuid4()
    req_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    # Domain with 'sim-timeout' will trigger ConnectTimeout in mock_registrar_adapter
    req = models.DomainRequest(
        id=req_id,
        tenant_id=tenant_id,
        store_id=store_id,
        preferred_domains=["sim-timeout-shop.com"],
        selected_domain="sim-timeout-shop.com",
        cost_class="STANDARD",
        price_paise=0,
        status="SELECTED",
        version=2,
    )

    res_req = MagicMock()
    res_req.scalars.return_value.first.return_value = req
    res_dup_none = MagicMock()
    res_dup_none.scalars.return_value.first.return_value = None

    session = make_mock_session([res_req, res_dup_none])
    cd = await commands.purchase_domain_command(
        session=session,
        request_id=req_id,
        principal=owner_principal,
    )
    # Recovered via lookup_purchase
    assert cd.domain_name == "sim-timeout-shop.com"
    assert cd.status == "PURCHASED"
    assert cd.registrar_reference.startswith("REG-MOCK-")


# ==============================================================================
# Domain Name Unique Constraint Across Platform
# ==============================================================================

async def test_ac_custom_domain_unique_constraint():
    """Attempting to purchase a domain name already registered by another store raises 409 INVALID_STATE_TRANSITION."""
    store_id = uuid4()
    tenant_id = uuid4()
    req_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    req = models.DomainRequest(
        id=req_id,
        tenant_id=tenant_id,
        store_id=store_id,
        preferred_domains=["taken-by-other.com"],
        selected_domain="taken-by-other.com",
        cost_class="STANDARD",
        price_paise=0,
        status="SELECTED",
        version=2,
    )

    existing_domain = models.CustomDomain(
        id=uuid4(),
        tenant_id=uuid4(),
        store_id=uuid4(),
        domain_name="taken-by-other.com",
        status="ACTIVE",
    )

    res_req = MagicMock()
    res_req.scalars.return_value.first.return_value = req
    res_dup_found = MagicMock()
    res_dup_found.scalars.return_value.first.return_value = existing_domain

    session = make_mock_session([res_req, res_dup_found])
    with pytest.raises(ApiError) as exc_info:
        await commands.purchase_domain_command(
            session=session,
            request_id=req_id,
            principal=owner_principal,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION
    assert "already registered" in exc_info.value.message


# ==============================================================================
# DOM-006: DNS Record Verification (CNAME)
# ==============================================================================

async def test_ac_087_dns_verification_cname():
    """DOM-006 checks DNS records; verifies and logs DnsCheck."""
    store_id = uuid4()
    tenant_id = uuid4()
    req_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    req = models.DomainRequest(
        id=req_id,
        tenant_id=tenant_id,
        store_id=store_id,
        selected_domain="configured-store.com",
        status="PURCHASED",
    )
    custom_domain = models.CustomDomain(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        domain_name="configured-store.com",
        domain_request_id=req_id,
        status="PURCHASED",
    )

    # 1. Successful DNS verification
    res_req = MagicMock()
    res_req.scalars.return_value.first.return_value = req
    res_cd = MagicMock()
    res_cd.scalars.return_value.first.return_value = custom_domain

    session = make_mock_session([res_req, res_cd])
    cd, is_verified = await commands.verify_dns_command(
        session=session,
        request_id=req_id,
        principal=owner_principal,
    )
    assert is_verified is True
    assert cd.status == "DNS_VERIFIED"
    assert req.status == "DNS_VERIFIED"
    assert any(isinstance(m, models.DnsCheck) and m.result == "VERIFIED" for m in session.added_models)

    events = get_outbox_events(session)
    assert any(e["event_type"] == "domain.dns-verified.v1" for e in events)

    # 2. Unconfigured DNS verification -> FAILED
    req_fail = models.DomainRequest(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        selected_domain="unconfigured-store.com",
        status="PURCHASED",
    )
    cd_fail = models.CustomDomain(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        domain_name="unconfigured-store.com",
        domain_request_id=req_fail.id,
        status="PURCHASED",
    )
    res_req_f = MagicMock()
    res_req_f.scalars.return_value.first.return_value = req_fail
    res_cd_f = MagicMock()
    res_cd_f.scalars.return_value.first.return_value = cd_fail

    session_fail = make_mock_session([res_req_f, res_cd_f])
    cd_res, is_verified_fail = await commands.verify_dns_command(
        session=session_fail,
        request_id=req_fail.id,
        principal=owner_principal,
    )
    assert is_verified_fail is False
    assert cd_res.status == "PURCHASED"  # unchanged
    assert any(isinstance(m, models.DnsCheck) and m.result == "FAILED" for m in session_fail.added_models)


# ==============================================================================
# Paid Publish Gates (DOM-007) Failing Closed with Exact Error Codes
# ==============================================================================

async def test_ac_085_paid_publish_gates_exhaustive(monkeypatch):
    """Paid store publish must evaluate all gates and fail closed with exact registered error codes."""
    store_id = uuid4()
    tenant_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    # Baseline valid custom domain in DB
    cd_verified = models.CustomDomain(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        domain_name="verifiedbrand.com",
        status="DNS_VERIFIED",
    )

    # --- Gate 1: Tenant service down -> 503 DEPENDENCY_UNAVAILABLE
    monkeypatch.setattr(
        commands.tenant_client,
        "get_store_compliance",
        AsyncMock(side_effect=ApiError(ErrorCode.DEPENDENCY_UNAVAILABLE, "Tenant service down", 503)),
    )
    session = make_mock_session()
    with pytest.raises(ApiError) as exc:
        await commands.publish_store_command(session, store_id, owner_principal)
    assert exc.value.status_code == 503
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE

    # --- Gate 2: Store commerce suspended -> 403 COMMERCE_SUSPENDED
    monkeypatch.setattr(
        commands.tenant_client,
        "get_store_compliance",
        AsyncMock(return_value={"lifecycle_status": "SUSPENDED", "store_mode": "DIRECT_PAID_SETUP"}),
    )
    with pytest.raises(ApiError) as exc:
        await commands.publish_store_command(session, store_id, owner_principal)
    assert exc.value.status_code == 403
    assert exc.value.code == ErrorCode.COMMERCE_SUSPENDED

    # From here on, tenant returns active paid store with GSTIN
    valid_compliance = {
        "lifecycle_status": "ACTIVE",
        "store_mode": "DIRECT_PAID_SETUP",
        "gstin_id": "GSTIN-12345",
        "gstin_status": "VERIFIED",
    }
    monkeypatch.setattr(commands.tenant_client, "get_store_compliance", AsyncMock(return_value=valid_compliance))

    # --- Gate 3: Subscription service down -> 503 DEPENDENCY_UNAVAILABLE
    monkeypatch.setattr(
        commands.subscription_client,
        "get_store_subscription_status",
        AsyncMock(side_effect=ApiError(ErrorCode.DEPENDENCY_UNAVAILABLE, "Subscription service down", 503)),
    )
    with pytest.raises(ApiError) as exc:
        await commands.publish_store_command(session, store_id, owner_principal)
    assert exc.value.status_code == 503
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE

    # --- Gate 4: Subscription expired/inactive -> 403 SUBSCRIPTION_EXPIRED
    monkeypatch.setattr(
        commands.subscription_client,
        "get_store_subscription_status",
        AsyncMock(return_value={"state": "EXPIRED", "is_active": False}),
    )
    with pytest.raises(ApiError) as exc:
        await commands.publish_store_command(session, store_id, owner_principal)
    assert exc.value.status_code == 403
    assert exc.value.code == ErrorCode.SUBSCRIPTION_EXPIRED

    # --- Gate 5: Subscription free plan unentitled -> 403 ENTITLEMENT_REQUIRED
    monkeypatch.setattr(
        commands.subscription_client,
        "get_store_subscription_status",
        AsyncMock(return_value={"state": "ACTIVE", "is_active": True, "plan_id": "FREE_PLAN"}),
    )
    with pytest.raises(ApiError) as exc:
        await commands.publish_store_command(session, store_id, owner_principal)
    assert exc.value.status_code == 403
    assert exc.value.code == ErrorCode.ENTITLEMENT_REQUIRED

    # Valid active paid subscription
    valid_sub = {"state": "ACTIVE", "is_active": True, "plan_id": "GROWTH"}
    monkeypatch.setattr(commands.subscription_client, "get_store_subscription_status", AsyncMock(return_value=valid_sub))

    # --- Gate 6: Missing or unverified GSTIN -> 422 GSTIN_REQUIRED
    monkeypatch.setattr(
        commands.tenant_client,
        "get_store_compliance",
        AsyncMock(return_value={"lifecycle_status": "ACTIVE", "store_mode": "DIRECT_PAID_SETUP", "gstin_id": None}),
    )
    with pytest.raises(ApiError) as exc:
        await commands.publish_store_command(session, store_id, owner_principal)
    assert exc.value.status_code == 422
    assert exc.value.code == ErrorCode.GSTIN_REQUIRED

    # Restore valid compliance with GSTIN
    monkeypatch.setattr(commands.tenant_client, "get_store_compliance", AsyncMock(return_value=valid_compliance))

    # --- Gate 7: Custom domain missing or not DNS verified -> 409 CUSTOM_DOMAIN_REQUIRED
    res_no_cd = MagicMock()
    res_no_cd.scalars.return_value.first.return_value = None
    session_no_cd = make_mock_session([res_no_cd])
    with pytest.raises(ApiError) as exc:
        await commands.publish_store_command(session_no_cd, store_id, owner_principal)
    assert exc.value.status_code == 409
    assert exc.value.code == ErrorCode.CUSTOM_DOMAIN_REQUIRED

    # Custom domain present but status != DNS_VERIFIED
    cd_pending = models.CustomDomain(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        domain_name="pendingbrand.com",
        status="PURCHASED",
    )
    res_pending_cd = MagicMock()
    res_pending_cd.scalars.return_value.first.return_value = cd_pending
    session_pending_cd = make_mock_session([res_pending_cd])
    with pytest.raises(ApiError) as exc:
        await commands.publish_store_command(session_pending_cd, store_id, owner_principal)
    assert exc.value.status_code == 409
    assert exc.value.code == ErrorCode.CUSTOM_DOMAIN_REQUIRED

    # --- Gate 8: Catalog service down -> 503 DEPENDENCY_UNAVAILABLE
    monkeypatch.setattr(
        commands.catalog_client,
        "verify_store_content_approved",
        AsyncMock(side_effect=ApiError(ErrorCode.DEPENDENCY_UNAVAILABLE, "Catalog service down", 503)),
    )
    res_cd = MagicMock()
    res_cd.scalars.return_value.first.return_value = cd_verified
    session_cat_down = make_mock_session([res_cd])
    with pytest.raises(ApiError) as exc:
        await commands.publish_store_command(session_cat_down, store_id, owner_principal)
    assert exc.value.status_code == 503
    assert exc.value.code == ErrorCode.DEPENDENCY_UNAVAILABLE

    # --- Gate 9: Catalog content not approved -> 409 CONTENT_APPROVAL_REQUIRED
    monkeypatch.setattr(commands.catalog_client, "verify_store_content_approved", AsyncMock(return_value=False))
    res_cd2 = MagicMock()
    res_cd2.scalars.return_value.first.return_value = cd_verified
    session_not_app = make_mock_session([res_cd2])
    with pytest.raises(ApiError) as exc:
        await commands.publish_store_command(session_not_app, store_id, owner_principal)
    assert exc.value.status_code == 409
    assert exc.value.code == ErrorCode.CONTENT_APPROVAL_REQUIRED

    # Valid catalog approved
    monkeypatch.setattr(commands.catalog_client, "verify_store_content_approved", AsyncMock(return_value=True))

    # --- Gate 10: Stale version -> 409 STALE_VERSION
    res_cd3 = MagicMock()
    res_cd3.scalars.return_value.first.return_value = cd_verified
    session_stale = make_mock_session([res_cd3])
    with pytest.raises(ApiError) as exc:
        await commands.publish_store_command(session_stale, store_id, owner_principal, expected_version=0)
    assert exc.value.status_code == 409
    assert exc.value.code == ErrorCode.STALE_VERSION


# ==============================================================================
# Paid Publish Success: Emits domain.activated.v1 and NOT domain.route.activated.v1
# ==============================================================================

async def test_ac_paid_publish_success_event_contract(monkeypatch):
    """Paid publish switches route, marks custom domain ACTIVE, emits domain.activated.v1 and store.published.v1."""
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
        AsyncMock(return_value={
            "lifecycle_status": "ACTIVE",
            "store_mode": "DIRECT_PAID_SETUP",
            "gstin_id": "GSTIN-99999",
            "gstin_status": "VERIFIED",
        }),
    )
    monkeypatch.setattr(
        commands.subscription_client,
        "get_store_subscription_status",
        AsyncMock(return_value={"state": "ACTIVE", "is_active": True, "plan_id": "GROWTH"}),
    )
    monkeypatch.setattr(commands.catalog_client, "verify_store_content_approved", AsyncMock(return_value=True))

    custom_domain = models.CustomDomain(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        domain_name="coolshop.com",
        status="DNS_VERIFIED",
    )
    free_route = models.PublicationRoute(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        route_type="FREE_SUBDOMAIN",
        hostname="coolshop.karobarone.com",
        status="ACTIVE",
    )

    res_cd = MagicMock()
    res_cd.scalars.return_value.first.return_value = custom_domain
    res_free_route = MagicMock()
    res_free_route.scalars.return_value.first.return_value = free_route
    res_cust_route_none = MagicMock()
    res_cust_route_none.scalars.return_value.first.return_value = None

    session = make_mock_session([res_cd, res_free_route, res_cust_route_none])
    s_id, state, active_host, published_at = await commands.publish_store_command(
        session=session,
        store_id=store_id,
        principal=owner_principal,
    )

    assert s_id == store_id
    assert state == "PUBLIC_LIVE"
    assert active_host == "coolshop.com"
    assert custom_domain.status == "ACTIVE"
    assert free_route.status == "DISABLED"

    # Verify event contract: domain.activated.v1 is emitted, domain.route.activated.v1 is NOT
    events = get_outbox_events(session)
    event_types = [e["event_type"] for e in events]
    assert "domain.activated.v1" in event_types
    assert "store.published.v1" in event_types
    assert "domain.route.activated.v1" not in event_types


# ==============================================================================
# AC-059: subscription.converted-to-free.v1 Consumer Route Flip
# ==============================================================================

async def test_ac_059_subscription_converted_to_free_consumer():
    """Event subscription.converted-to-free.v1 deactivates custom domain, restores Free subdomain, and emits domain.stopped.v1."""
    store_id = uuid4()
    tenant_id = uuid4()

    custom_route = models.PublicationRoute(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        route_type="CUSTOM_DOMAIN",
        hostname="brand.com",
        status="ACTIVE",
    )
    free_route = models.PublicationRoute(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        route_type="FREE_SUBDOMAIN",
        hostname="brand.karobarone.com",
        status="DISABLED",
    )
    custom_domain = models.CustomDomain(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        domain_name="brand.com",
        status="ACTIVE",
    )

    # Inbox check: event not processed yet
    res_inbox_none = MagicMock()
    res_inbox_none.scalars.return_value.first.return_value = None
    res_c_route = MagicMock()
    res_c_route.scalars.return_value.first.return_value = custom_route
    res_f_route = MagicMock()
    res_f_route.scalars.return_value.first.return_value = free_route
    res_cd = MagicMock()
    res_cd.scalars.return_value.first.return_value = custom_domain

    session = make_mock_session([res_inbox_none, res_c_route, res_f_route, res_cd])
    event_id = str(uuid4())

    await handle_internal_event(
        session=session,
        event_id=event_id,
        event_type="subscription.converted-to-free.v1",
        payload={"store_id": str(store_id)},
    )

    # Route flip assertions
    assert custom_route.status == "DISABLED"
    assert free_route.status == "ACTIVE"
    assert custom_domain.status == "STOPPED_FREE_CONVERSION"

    # Outbox event domain.stopped.v1 emitted
    events = get_outbox_events(session)
    stopped_event = next(e for e in events if e["event_type"] == "domain.stopped.v1")
    assert stopped_event["payload"]["store_id"] == str(store_id)
    assert stopped_event["payload"]["domain_name"] == "brand.com"
    assert stopped_event["payload"]["reason"] == "SUBSCRIPTION_CONVERTED_TO_FREE"


# ==============================================================================
# Event Consumer: subscription.activated.v1 & Inbox Deduplication
# ==============================================================================

async def test_ac_subscription_activated_and_inbox_deduplication():
    """Event subscription.activated.v1 is processed and recorded in processed_events; duplicates are dropped."""
    session = make_mock_session()
    event_id = str(uuid4())

    await handle_internal_event(
        session=session,
        event_id=event_id,
        event_type="subscription.activated.v1",
        payload={"store_id": str(uuid4()), "plan_id": "COMMERCE_CORE"},
    )
    assert any(isinstance(m, models.ProcessedEvent) and m.event_id == UUID(event_id) for m in session.added_models)

    # Replaying same event ID -> no-op due to inbox deduplication
    existing_proc = models.ProcessedEvent(consumer="domain", event_id=UUID(event_id))
    res_dup = MagicMock()
    res_dup.scalars.return_value.first.return_value = existing_proc
    session_dup = make_mock_session([res_dup])

    await handle_internal_event(
        session=session_dup,
        event_id=event_id,
        event_type="subscription.activated.v1",
        payload={"store_id": str(uuid4())},
    )
    assert len(session_dup.added_models) == 0


# ==============================================================================
# AC-088: Post-Closure Domain Transfer Review (DOM-008)
# ==============================================================================

async def test_ac_088_domain_transfer_review_post_closure():
    """DOM-008 opens a transfer review case without performing automatic transfer."""
    store_id = uuid4()
    tenant_id = uuid4()
    domain_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    custom_domain = models.CustomDomain(
        id=domain_id,
        tenant_id=tenant_id,
        store_id=store_id,
        domain_name="closedshop.com",
        status="STOPPED_FREE_CONVERSION",
    )

    res_cd = MagicMock()
    res_cd.scalars.return_value.first.return_value = custom_domain
    session = make_mock_session([res_cd])

    domain_obj = await commands.open_transfer_review_command(
        session=session,
        domain_id=domain_id,
        principal=owner_principal,
        notes="Store closed; owner requests transfer to external registrar",
    )

    assert domain_obj.status == "TRANSFER_REVIEW"
    assert domain_obj.transfer_review_notes == "Store closed; owner requests transfer to external registrar"
    assert domain_obj.transfer_review_opened_at is not None

    events = get_outbox_events(session)
    review_event = next(e for e in events if e["event_type"] == "domain.transfer-review-opened.v1")
    assert review_event["payload"]["domain_id"] == str(domain_id)
    assert review_event["payload"]["notes"] == "Store closed; owner requests transfer to external registrar"


# ==============================================================================
# DOM-005: Read Domain Status for Paid Store
# ==============================================================================

async def test_ac_domain_status_query_paid():
    """DOM-005 returns both free subdomain and custom domain status with cost_class."""
    store_id = uuid4()
    tenant_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    sub = models.Subdomain(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        label="mybrand",
        fqdn="mybrand.karobarone.com",
        status="ASSIGNED",
    )
    custom_domain = models.CustomDomain(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        domain_name="mybrand.com",
        status="ACTIVE",
        cost_class="STANDARD",
        registrar_reference="REG-MOCK-TEST1234",
    )
    active_route = models.PublicationRoute(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        route_type="CUSTOM_DOMAIN",
        hostname="mybrand.com",
        status="ACTIVE",
    )

    res_sub = MagicMock()
    res_sub.scalars.return_value.first.return_value = sub
    res_cd = MagicMock()
    res_cd.scalars.return_value.first.return_value = custom_domain
    res_route = MagicMock()
    res_route.scalars.return_value.first.return_value = active_route

    session = make_mock_session([res_sub, res_cd, res_route])
    status_resp = await commands.get_domain_status_query(
        session=session,
        store_id=store_id,
        principal=owner_principal,
    )

    assert status_resp["store_id"] == store_id
    assert status_resp["publication_status"] == "PUBLIC_LIVE"
    assert status_resp["active_host"] == "mybrand.com"
    assert status_resp["free_subdomain"]["label"] == "mybrand"
    assert status_resp["custom_domain"]["domain_name"] == "mybrand.com"
    assert status_resp["custom_domain"]["cost_class"] == "STANDARD"
    assert status_resp["custom_domain"]["registrar_reference"] == "REG-MOCK-TEST1234"
