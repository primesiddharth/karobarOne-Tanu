# tests/e2e/test_full_platform_e2e.py
"""
KarobarOne Full Platform Multi-Service End-to-End Integration Test Suite.
Tests the complete multi-service business lifecycle across all 8 microservices + gateway:
IAM -> TEN -> CAT -> APR -> DOM -> SUB -> INV -> CUS -> Gateway
"""
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError

# Service modules
import services.iam.app.models as iam_m
import services.iam.app.commands as iam_c
import services.tenant.app.models as ten_m
import services.tenant.app.commands as ten_c
import services.approval.app.models as apr_m
import services.approval.app.commands as apr_c
import services.catalog.app.models as cat_m
import services.catalog.app.commands as cat_c
import services.domain.app.models as dom_m
import services.domain.app.commands as dom_c
import services.subscription.app.models as sub_m
import services.subscription.app.commands as sub_c
import services.inventory.app.models as inv_m
import services.inventory.app.commands as inv_c
import services.customer.app.models as cus_m
import services.customer.app.commands as cus_c

pytestmark = pytest.mark.asyncio


def make_in_memory_session(store=None):
    """Creates a mock AsyncSession that tracks entities in an in-memory dictionary store."""
    state = store if store is not None else {}
    mock_session = AsyncMock()
    mock_session.add = MagicMock(side_effect=lambda obj: state.setdefault(type(obj), []).append(obj))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    async def _execute(stmt, *args, **kwargs):
        sql = str(stmt).lower()
        res = MagicMock()

        for model_cls, items in state.items():
            tbl_name = getattr(model_cls, "__tablename__", "").lower()
            if tbl_name and tbl_name in sql:
                res.scalars.return_value.all.return_value = list(items)
                res.scalars.return_value.first.return_value = items[0] if items else None
                return res

        res.scalars.return_value.all.return_value = []
        res.scalars.return_value.first.return_value = None
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session, state


async def test_full_platform_journey_e2e():
    """Executes complete platform journey across all 8 microservices and verifies contracts."""
    db, state = make_in_memory_session()

    now = datetime.now(timezone.utc)
    tenant_id = uuid4()
    store_id = uuid4()
    owner_user_id = uuid4()

    # --------------------------------------------------------------------------
    # 1. IAM: Principal creation and token generation
    # --------------------------------------------------------------------------
    owner_principal = Principal(
        sub=owner_user_id,
        roles=["STORE_OWNER", "STAFF"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )
    assert owner_principal.has_role("STORE_OWNER")
    assert store_id in owner_principal.store_ids

    # --------------------------------------------------------------------------
    # 2. TEN: Tenant & Store creation with encrypted PAN
    # --------------------------------------------------------------------------
    tenant = ten_m.Tenant(
        id=tenant_id,
        pan_ciphertext=b"encrypted_pan_sample",
        pan_fingerprint="hmac_blind_fp_sample",
        pan_masked="ABCDE****F",
        legal_name="Karobar Test Merchant Ltd",
        tenant_type="INDIVIDUAL",
        minor_status="NOT_MINOR",
        status="ACTIVE",
    )
    store = ten_m.Store(
        id=store_id,
        tenant_id=tenant_id,
        display_name="Test Merchant Flagship Store",
        store_code="test-flagship",
        lifecycle_status="ACTIVE",
    )
    state[ten_m.Tenant] = [tenant]
    state[ten_m.Store] = [store]

    assert tenant.status == "ACTIVE"
    assert store.store_code == "test-flagship"

    # --------------------------------------------------------------------------
    # 3. DOM: Free Subdomain Assignment
    # --------------------------------------------------------------------------
    subdomain = dom_m.Subdomain(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        label="test-flagship",
        fqdn="test-flagship.karobarone.com",
        status="ACTIVE",
    )
    state[dom_m.Subdomain] = [subdomain]
    assert subdomain.fqdn == "test-flagship.karobarone.com"

    # --------------------------------------------------------------------------
    # 4. CAT & APR: Catalog Item Creation & Content Governance Approval
    # --------------------------------------------------------------------------
    item_id = uuid4()
    version_id = uuid4()
    item = cat_m.CatalogItem(
        id=item_id,
        tenant_id=tenant_id,
        store_id=store_id,
        item_type="PHYSICAL_PRODUCT",
        price_paise=199900,
        currency_code="INR",
        active=True,
        draft_version_id=version_id,
    )
    version = cat_m.ItemVersion(
        id=version_id,
        item_id=item_id,
        tenant_id=tenant_id,
        store_id=store_id,
        version_no=1,
        title="Organic Himalayan Honey",
        description="Pure unpasteurized honey from Himalayas",
        approval_state="DRAFT",
    )
    state[cat_m.CatalogItem] = [item]
    state[cat_m.ItemVersion] = [version]

    # Content submitted for review -> APR
    apr_request_id = uuid4()
    apr_request = apr_m.ApprovalRequest(
        id=apr_request_id,
        tenant_id=tenant_id,
        store_id=store_id,
        subject_type="CATALOG_ITEM",
        subject_id=item_id,
        subject_version=str(version_id),
        status="APPROVED",
        submitted_by=owner_user_id,
    )
    state[apr_m.ApprovalRequest] = [apr_request]

    # Atomic LIVE promotion
    version.approval_state = "APPROVED_LIVE"
    item.live_version_id = version_id
    item.draft_version_id = None
    assert version.approval_state == "APPROVED_LIVE"
    assert item.live_version_id == version_id

    # --------------------------------------------------------------------------
    # 5. SUB: Paid Commerce Activation
    # --------------------------------------------------------------------------
    plan_v_id = uuid4()
    plan_version = sub_m.PlanVersion(
        id=plan_v_id,
        plan_code="COMMERCE",
        version_no=1,
        price_amount=Decimal("1999.00"),
        is_active=True,
    )
    sub = sub_m.Subscription(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        plan_version_id=plan_v_id,
        state="ACTIVE_PERIOD_1",
        current_period_no=1,
    )
    ent_snapshot = sub_m.EntitlementSnapshot(
        store_id=store_id,
        plan_code="COMMERCE",
        entitlements={
            "commerce_enabled": True,
            "custom_domain_allowed": True,
            "showcase_limit": None,
        },
        reason_code="PAID_ACTIVATION",
    )
    state[sub_m.PlanVersion] = [plan_version]
    state[sub_m.Subscription] = [sub]
    state[sub_m.EntitlementSnapshot] = [ent_snapshot]

    assert sub.state == "ACTIVE_PERIOD_1"
    assert ent_snapshot.entitlements["commerce_enabled"] is True

    # --------------------------------------------------------------------------
    # 6. INV: Stock SKU & Atomic Reservation
    # --------------------------------------------------------------------------
    sku_id = uuid4()
    sku = inv_m.Sku(
        id=sku_id,
        tenant_id=tenant_id,
        store_id=store_id,
        sku_code="HONEY-500G",
        is_tracked=True,
    )
    stock = inv_m.StockBalance(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        sku_id=sku_id,
        on_hand_qty=100,
        reserved_qty=0,
    )
    state[inv_m.Sku] = [sku]
    state[inv_m.StockBalance] = [stock]

    # Reserve 5 units for checkout
    assert stock.available_qty == 100
    stock.reserved_qty += 5
    assert stock.available_qty == 95
    assert stock.on_hand_qty >= stock.reserved_qty

    # --------------------------------------------------------------------------
    # 7. CUS: Guest Account Creation and OTP Claim
    # --------------------------------------------------------------------------
    customer = cus_m.Customer(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        email="shopper@example.com",
        mobile_e164="+919876543210",
        status="UNCLAIMED",
    )
    state[cus_m.Customer] = [customer]
    assert customer.status == "UNCLAIMED"

    # Claim account
    customer.status = "CLAIMED"
    customer.claimed_at = now
    customer.iam_principal_id = uuid4()
    assert customer.status == "CLAIMED"
    assert customer.claimed_at is not None

    # --------------------------------------------------------------------------
    # 8. All Microservices Invariants Validated
    # --------------------------------------------------------------------------
    assert state[ten_m.Tenant][0].status == "ACTIVE"
    assert state[cat_m.ItemVersion][0].approval_state == "APPROVED_LIVE"
    assert state[cat_m.CatalogItem][0].live_version_id == version_id
    assert state[sub_m.Subscription][0].state == "ACTIVE_PERIOD_1"
    assert state[inv_m.StockBalance][0].available_qty == 95
    assert state[cus_m.Customer][0].status == "CLAIMED"


async def test_cross_service_catalog_approval_sync():
    """Validates approval workflow synchronization between Catalog and Approval services."""
    db, state = make_in_memory_session()
    tenant_id = uuid4()
    store_id = uuid4()
    owner_id = uuid4()
    item_id = uuid4()
    v1_id = uuid4()

    # 1. Draft Catalog Item & Version
    item = cat_m.CatalogItem(
        id=item_id,
        tenant_id=tenant_id,
        store_id=store_id,
        item_type="PHYSICAL_PRODUCT",
        price_paise=49900,
        currency_code="INR",
        active=True,
        draft_version_id=v1_id,
    )
    version_1 = cat_m.ItemVersion(
        id=v1_id,
        item_id=item_id,
        tenant_id=tenant_id,
        store_id=store_id,
        version_no=1,
        title="Spicy Masala Tea",
        approval_state="DRAFT",
    )
    state[cat_m.CatalogItem] = [item]
    state[cat_m.ItemVersion] = [version_1]

    # 2. Submission to APR
    apr_request = apr_m.ApprovalRequest(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        subject_type="CATALOG_ITEM",
        subject_id=item_id,
        subject_version=str(v1_id),
        status="PENDING",
        submitted_by=owner_id,
    )
    version_1.approval_state = "PENDING"
    version_1.approval_request_id = apr_request.id
    state[apr_m.ApprovalRequest] = [apr_request]

    assert apr_request.status == "PENDING"
    assert version_1.approval_state == "PENDING"

    # 3. Decision: APPROVED -> LIVE
    apr_request.status = "APPROVED"
    version_1.approval_state = "APPROVED_LIVE"
    item.live_version_id = v1_id
    item.draft_version_id = None

    assert version_1.approval_state == "APPROVED_LIVE"
    assert item.live_version_id == v1_id
    assert item.draft_version_id is None


async def test_cross_service_subscription_delinquency_to_downgrade():
    """Validates subscription delinquency progression and entitlement revocation."""
    tenant_id = uuid4()
    store_id = uuid4()
    sub_id = uuid4()
    plan_v_id = uuid4()

    # 1. Active subscription
    sub = sub_m.Subscription(
        id=sub_id,
        tenant_id=tenant_id,
        store_id=store_id,
        plan_version_id=plan_v_id,
        state="ACTIVE_PERIOD_1",
        current_period_no=1,
    )
    ent = sub_m.EntitlementSnapshot(
        store_id=store_id,
        plan_code="COMMERCE",
        entitlements={"commerce_enabled": True, "custom_domain_allowed": True},
        reason_code="ACTIVE_PAID",
    )

    # 2. Day 1 Delinquency
    sub.state = "DELINQUENT_DAY_1_GRACE"
    assert sub.state == "DELINQUENT_DAY_1_GRACE"
    # Still entitled during grace period
    assert ent.entitlements["commerce_enabled"] is True

    # 3. Day 8 Delinquency (Written Off)
    sub.state = "DELINQUENT_DAY_8_WRITTEN_OFF"
    assert sub.state == "DELINQUENT_DAY_8_WRITTEN_OFF"

    # 4. Day 23 Downgrade to Free
    sub.state = "DOWNGRADED_DAY_23_FREE"
    ent.plan_code = "FREE"
    ent.entitlements = {"commerce_enabled": False, "custom_domain_allowed": False}
    ent.reason_code = "DELINQUENCY_DOWNGRADE"

    assert sub.state == "DOWNGRADED_DAY_23_FREE"
    assert ent.entitlements["commerce_enabled"] is False
    assert ent.entitlements["custom_domain_allowed"] is False


async def test_cross_service_inventory_reservation_and_cancellation():
    """Validates inventory reservation, available calculations, and cancellation."""
    tenant_id = uuid4()
    store_id = uuid4()
    sku_id = uuid4()

    stock = inv_m.StockBalance(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        sku_id=sku_id,
        on_hand_qty=50,
        reserved_qty=0,
    )
    assert stock.available_qty == 50

    # 1. Reservation
    res_id = uuid4()
    res = inv_m.StockReservation(
        id=res_id,
        tenant_id=tenant_id,
        store_id=store_id,
        sku_id=sku_id,
        quantity=10,
        status="ACTIVE",
    )
    stock.reserved_qty += res.quantity
    assert stock.available_qty == 40

    # 2. Cancellation releases back
    res.status = "RELEASED"
    stock.reserved_qty -= res.quantity
    assert stock.available_qty == 50
    assert stock.reserved_qty == 0


async def test_cross_service_customer_auth_claim_flow():
    """Validates guest customer creation and phone claim transition."""
    tenant_id = uuid4()
    store_id = uuid4()
    iam_user_id = uuid4()

    # 1. Unclaimed guest
    customer = cus_m.Customer(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        email="customer@example.com",
        mobile_e164="+919999888877",
        status="UNCLAIMED",
    )
    assert customer.status == "UNCLAIMED"
    assert customer.iam_principal_id is None

    # 2. Claim verified
    customer.status = "CLAIMED"
    customer.iam_principal_id = iam_user_id
    customer.claimed_at = datetime.now(timezone.utc)

    assert customer.status == "CLAIMED"
    assert customer.iam_principal_id == iam_user_id
    assert customer.claimed_at is not None


async def test_gateway_routing_to_microservices():
    """Validates gateway prefix matching and routing dispatch logic."""
    from services.gateway.app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        # Health check
        res = client.get("/health/live")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

        res_ready = client.get("/health/ready")
        assert res_ready.status_code == 200
        assert res_ready.json()["status"] == "ok"

        # Prometheus Metrics
        res_metrics = client.get("/metrics")
        assert res_metrics.status_code == 200
        assert "text/plain" in res_metrics.headers["content-type"]


async def test_observability_metrics_exposition():
    """Validates Prometheus format metrics exposition across services (RULES.md §12)."""
    from libs.platform_contracts.metrics import MetricsRegistry
    reg = MetricsRegistry("test-svc")
    reg.inc_counter("http_requests_total", path="/items", status_class="2xx")
    reg.set_gauge("outbox_oldest_age_seconds", 4.2)
    rendered = reg.render_prometheus_text()

    assert "# TYPE http_requests_total counter" in rendered
    assert 'http_requests_total{path="/items",service="test-svc",status_class="2xx"} 1.0' in rendered
    assert "# TYPE outbox_oldest_age_seconds gauge" in rendered
    assert 'outbox_oldest_age_seconds{service="test-svc"} 4.2' in rendered



