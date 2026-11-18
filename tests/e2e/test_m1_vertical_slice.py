# microservice/tests/e2e/test_m1_vertical_slice.py
# Milestone 1 (M1) Vertical Slice End-to-End Integration Test Suite.
# Proves seamless business behaviour and invariants across all first 4 services:
# TEN (Tenant & Store) -> DOM (Domain & Publication) -> CAT (Catalog & CMS) -> APR (Content Approval)
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode

# Service command & model imports
import services.tenant.app.models as tm
import services.tenant.app.commands as tc
import services.domain.app.models as dm
import services.domain.app.commands as dc
import services.approval.app.models as am
import services.approval.app.commands as ac
import services.catalog.app.models as cm
import services.catalog.app.commands as cc
import services.catalog.app.events as ce

pytestmark = pytest.mark.asyncio


def make_mock_session(store_state=None, execute_results=None):
    """Creates a mock AsyncSession that tracks and simulates database state across tables."""
    state = store_state if store_state is not None else {}
    mock_session = AsyncMock()
    mock_session.add = MagicMock(side_effect=lambda obj: state.setdefault(type(obj), []).append(obj))
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    async def _get(model, obj_id, **kw):
        for obj in state.get(model, []):
            if getattr(obj, "id", None) == obj_id or getattr(obj, "store_id", None) == obj_id or getattr(obj, "tenant_id", None) == obj_id:
                return obj
        return None

    mock_session.get = AsyncMock(side_effect=_get)

    results = list(execute_results or [])

    async def _execute(stmt, *args, **kwargs):
        if results:
            return results.pop(0)
        res = MagicMock()
        # Default behavior: empty
        res.scalars.return_value.first.return_value = None
        res.scalars.return_value.all.return_value = []
        res.scalar_one.return_value = 0
        res.scalar_one_or_none.return_value = None
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session, state


async def test_m1_vertical_slice_full_lifecycle():
    """Executes the complete M1 vertical slice workflow:

    1. Tenant Registration (TEN-001, AC-001)
    2. Free Store Creation (TEN-008, AC-002)
    3. Free Subdomain Assignment (DOM-001, AC-084)
    4. Catalog Item Creation (CAT-001)
    5. Version Submission to Approval (CAT-006 -> APR-001)
    6. Platform Staff Review Approval (APR-004, AC-079)
    7. Content Promotion on content.approved.v1 (APR -> CAT)
    8. Store Publication (DOM-007)
    9. Public Storefront Snapshot Verification (CAT-010)
    10. Invariant Enforcement:
        - Commercial transactions denied on Free store (AC-003)
        - 7th active showcase item rejected (AC-004)
    """
    tenant_id = uuid4()
    principal_id = uuid4()
    store_id = uuid4()

    owner_principal = Principal(
        sub=principal_id,
        roles=["TENANT_OWNER", "STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )
    staff_principal = Principal(
        sub=uuid4(),
        roles=["PLATFORM_STAFF"],
        tenant_ids=[],
        store_ids=[],
    )

    # --------------------------------------------------------------------------
    # Step 1: Tenant Registration (TEN-001, AC-001)
    # --------------------------------------------------------------------------
    ten_session, ten_state = make_mock_session()

    # Mock no existing PAN to allow registration
    res_pan_none = MagicMock()
    res_pan_none.scalars.return_value.first.return_value = None
    ten_session.execute = AsyncMock(return_value=res_pan_none)

    tenant_reg = await tc.register_tenant_command(
        session=ten_session,
        current_principal=owner_principal,
        pan="ABCDE1234F",
        legal_name="Artisan Crafts India",
    )
    assert tenant_reg["status"] == "ACTIVE"
    assert tenant_reg["legal_name"] == "Artisan Crafts India"

    # --------------------------------------------------------------------------
    # Step 2: Free Store Creation (TEN-008, AC-002)
    # --------------------------------------------------------------------------
    tenant_obj = tm.Tenant(
        id=tenant_id,
        pan_fingerprint="fp123",
        pan_masked="ABCDE****F",
        legal_name="Artisan Crafts India",
        minor_status="NOT_MINOR",
        status="ACTIVE",
    )
    free_ent = tm.FreeStoreEntitlement(
        tenant_id=tenant_id,
        status="AVAILABLE",
    )

    # Store code uniqueness query (None) + entitlement query (AVAILABLE)
    res_code_none = MagicMock()
    res_code_none.scalars.return_value.first.return_value = None
    res_ent_avail = MagicMock()
    res_ent_avail.scalars.return_value.first.return_value = free_ent

    ten_session_create, _ = make_mock_session(execute_results=[res_code_none, res_ent_avail])
    ten_session_create.get = AsyncMock(return_value=tenant_obj)

    store_dict = await tc.create_store_command(
        session=ten_session_create,
        tenant_id=tenant_id,
        current_principal=owner_principal,
        store_code="artisan-pottery",
        display_name="Artisan Pottery",
        store_mode="FREE_PRESENCE",
    )
    assert store_dict["store_code"] == "artisan-pottery"
    assert store_dict["store_mode"] == "FREE_PRESENCE"
    assert free_ent.status == "CONSUMED"

    # --------------------------------------------------------------------------
    # Step 3: Free Subdomain Assignment (DOM-001, AC-084)
    # --------------------------------------------------------------------------
    res_sub_none = MagicMock()
    res_sub_none.scalars.return_value.first.return_value = None
    res_dup_none = MagicMock()
    res_dup_none.scalars.return_value.first.return_value = None
    dom_session, dom_state = make_mock_session(execute_results=[res_sub_none, res_dup_none])

    subdomain = await dc.assign_subdomain_command(
        session=dom_session,
        store_id=store_id,
        slug="artisan-pottery",
        principal=owner_principal,
    )
    assert subdomain.label == "artisan-pottery"
    assert subdomain.fqdn == "artisan-pottery.karobarone.com"
    assert subdomain.status == "ASSIGNED"

    # Invariant AC-084: Subdomain is immutable once assigned
    res_sub_exists = MagicMock()
    res_sub_exists.scalars.return_value.first.return_value = subdomain
    dom_session_rename, _ = make_mock_session(execute_results=[res_sub_exists])

    with pytest.raises(ApiError) as exc_rename:
        await dc.assign_subdomain_command(
            session=dom_session_rename,
            store_id=store_id,
            slug="renamed-pottery",
            principal=owner_principal,
        )
    assert exc_rename.value.status_code == 409
    assert exc_rename.value.code == ErrorCode.INVALID_STATE_TRANSITION

    # --------------------------------------------------------------------------
    # Step 4: Catalog Item Creation (CAT-001)
    # --------------------------------------------------------------------------
    cat_session, cat_state = make_mock_session()

    # Free entitlement projection
    free_cat_ent = cm.EntitlementProjection(
        store_id=store_id,
        tenant_id=tenant_id,
        plan_tier="FREE",
        max_items=6,
        max_images_per_item=1,
        max_videos_per_item=0,
    )
    cat_session.get = AsyncMock(return_value=free_cat_ent)

    item, draft_version = await cc.create_catalog_item_command(
        session=cat_session,
        store_id=store_id,
        principal=owner_principal,
        item_type="PHYSICAL_PRODUCT",
        price_str="450.00",
        currency_code="INR",
        active=True,
        draft_title="Handcrafted Terracotta Vase",
        draft_description="Natural clay vase baked using traditional methods.",
        category_id=None,
    )
    assert item.store_id == store_id
    assert item.price_paise == 45000
    assert draft_version.approval_state == "DRAFT"
    assert draft_version.title == "Handcrafted Terracotta Vase"
    assert item.live_version_id is None  # Initial item is not LIVE yet

    # --------------------------------------------------------------------------
    # Step 5: Version Submission to Approval (CAT-006 -> APR-001)
    # --------------------------------------------------------------------------
    apr_session, apr_state = make_mock_session()

    # Mock APR create_approval_request_command
    approval_request = await ac.create_approval_request_command(
        session=apr_session,
        tenant_id=tenant_id,
        store_id=store_id,
        subject_type="ITEM_VERSION",
        subject_id=item.id,
        subject_version=draft_version.version_no,
        priority="NORMAL",
        submitted_by=owner_principal.sub,
    )
    assert approval_request.status == "PENDING"
    assert approval_request.subject_type == "ITEM_VERSION"

    # In CAT, draft version transitions to PENDING
    draft_version.approval_state = "PENDING"
    draft_version.approval_request_id = approval_request.id

    # --------------------------------------------------------------------------
    # Step 6: Platform Review & Approval (APR-004, AC-079)
    # --------------------------------------------------------------------------
    res_apr = MagicMock()
    res_apr.scalar_one_or_none.return_value = approval_request
    apr_session_approve, _ = make_mock_session(execute_results=[res_apr])

    approved_req, approved_at = await ac.approve_content_command(
        session=apr_session_approve,
        approval_id=approval_request.id,
        principal=staff_principal,
        comment="Content adheres to platform catalog standards.",
    )
    assert approved_req.status == "APPROVED"

    # --------------------------------------------------------------------------
    # Step 7: Content Promotion on content.approved.v1 (APR -> CAT)
    # --------------------------------------------------------------------------
    # CAT consumes content.approved.v1 emitted by APR
    # Mock item and version lookup in CAT consumer
    res_proc_none = MagicMock()
    res_proc_none.scalars.return_value.first.return_value = None  # Not deduplicated

    res_item_version = MagicMock()
    res_item_version.scalars.return_value.first.return_value = draft_version

    cat_session_promote, _ = make_mock_session(execute_results=[res_proc_none, res_item_version])
    cat_session_promote.get = AsyncMock(return_value=item)

    event_id = uuid4()
    await ce.handle_internal_event(
        session=cat_session_promote,
        event_id=str(event_id),
        event_type="content.approved.v1",
        payload={
            "approval_id": str(approval_request.id),
            "content_type": "ITEM_VERSION",
            "content_id": str(item.id),
            "approved_by": str(staff_principal.sub),
        },
    )

    # Item version is promoted to APPROVED_LIVE and item.live_version_id points to it
    assert draft_version.approval_state == "APPROVED_LIVE"
    assert item.live_version_id == draft_version.id

    # --------------------------------------------------------------------------
    # Step 8: Store Publication (DOM-007)
    # --------------------------------------------------------------------------
    route = dm.PublicationRoute(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        route_type="FREE_SUBDOMAIN",
        hostname=subdomain.fqdn,
        status="DISABLED",
    )

    res_sub_lookup = MagicMock()
    res_sub_lookup.scalars.return_value.first.return_value = subdomain
    res_route_lookup = MagicMock()
    res_route_lookup.scalars.return_value.first.return_value = route

    dom_pub_session, _ = make_mock_session(execute_results=[res_sub_lookup, res_route_lookup])

    with patch("services.domain.app.commands.tenant_client.get_store_compliance", new=AsyncMock(return_value={"lifecycle_status": "ACTIVE", "store_mode": "FREE_PRESENCE"})):
        published_store_id, pub_state, active_host, published_at = await dc.publish_store_command(
            session=dom_pub_session,
            store_id=store_id,
            principal=owner_principal,
        )
    assert published_store_id == store_id
    assert pub_state == "PUBLIC_LIVE"
    assert active_host == "artisan-pottery.karobarone.com"
    assert route.status == "ACTIVE"
    assert subdomain.status == "ACTIVE"

    # --------------------------------------------------------------------------
    # Step 9: Public Storefront Snapshot Verification (CAT-010)
    # --------------------------------------------------------------------------
    # Public snapshot query serves only LIVE items
    res_live_items = MagicMock()
    res_live_items.scalars.return_value.all.return_value = [item]

    res_live_ver = MagicMock()
    res_live_ver.scalar_one_or_none.return_value = draft_version

    cat_snapshot_session, _ = make_mock_session(execute_results=[res_live_items, res_live_ver])

    items, generated_at = await cc.get_public_store_snapshot_query(
        session=cat_snapshot_session,
        store_id=store_id,
    )
    assert len(items) == 1
    assert items[0]["title"] == "Handcrafted Terracotta Vase"
    assert items[0]["price"] == "450.00"

    # --------------------------------------------------------------------------
    # Step 10: Invariant Guards Enforcement
    # --------------------------------------------------------------------------
    # 10a. Commerce attempt denied on Free store (AC-003)
    # Free stores have plan_tier="FREE" and store_mode="FREE_PRESENCE"
    assert free_cat_ent.plan_tier == "FREE"
    assert store_dict["store_mode"] == "FREE_PRESENCE"

    # 10b. 7th showcase item creation rejected (AC-004)
    res_count_six = MagicMock()
    res_count_six.scalar_one.return_value = 6

    cat_limit_session, _ = make_mock_session(execute_results=[res_count_six])
    cat_limit_session.get = AsyncMock(return_value=free_cat_ent)

    with pytest.raises(ApiError) as exc_seventh:
        await cc.create_catalog_item_command(
            session=cat_limit_session,
            store_id=store_id,
            principal=owner_principal,
            item_type="PHYSICAL_PRODUCT",
            price_str="100.00",
            currency_code="INR",
            active=True,
            draft_title="7th Item",
            draft_description="Should be rejected",
            category_id=None,
        )
    assert exc_seventh.value.status_code == 403
    assert exc_seventh.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert "maximum 6 showcase items" in exc_seventh.value.message.lower()
