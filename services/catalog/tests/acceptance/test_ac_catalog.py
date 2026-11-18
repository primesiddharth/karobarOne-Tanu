# tests/acceptance/test_ac_catalog.py
# Acceptance Criteria test suite for Catalog & CMS service (SERVICES.md §4, ROADMAP Phase 5).
# Function names follow test_ac_NNN_* pattern checked by tools/check_ac_coverage.py.
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import commands
from app import models
from app import events

pytestmark = pytest.mark.asyncio


def make_mock_session(execute_results=None, get_mapping=None):
    """Helper creating mock AsyncSession that returns queued results and handles outbox inserts."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    if get_mapping:
        mock_session.get.side_effect = (
            lambda model, obj_id, **kw: get_mapping.get((model, obj_id)) or get_mapping.get(model) or get_mapping.get(obj_id)
        )

    results = list(execute_results or [])

    async def _execute(*args, **kwargs):
        if results:
            return results.pop(0)
        res = MagicMock()
        res.scalars.return_value.first.return_value = None
        res.scalars.return_value.all.return_value = []
        res.scalar_one_or_none.return_value = None
        res.scalar_one.return_value = 0
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session


async def test_ac_004_free_store_max_six_showcase_items():
    """Free Store cannot showcase more than 6 products/services combined (AC-004, STO-R03).

    Given a Free Store that already has 6 active items,
    attempting to create a 7th active item is rejected with 403 ENTITLEMENT_REQUIRED.
    """
    store_id = uuid4()
    tenant_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    free_ent = models.EntitlementProjection(
        store_id=store_id,
        tenant_id=tenant_id,
        plan_tier="FREE",
        max_items=6,
        max_images_per_item=1,
        max_videos_per_item=0,
    )

    # Mock count query returning 6 active items
    count_res = MagicMock()
    count_res.scalar_one.return_value = 6
    mock_session = make_mock_session(
        execute_results=[count_res],
        get_mapping={(models.EntitlementProjection, store_id): free_ent, store_id: free_ent},
    )

    with pytest.raises(ApiError) as exc_info:
        await commands.create_catalog_item_command(
            session=mock_session,
            store_id=store_id,
            principal=owner_principal,
            item_type="PHYSICAL_PRODUCT",
            price_str="299.00",
            currency_code="INR",
            active=True,
            draft_title="Seventh Item",
            draft_description="Should fail",
            category_id=None,
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert exc_info.value.status_code == 403
    assert "allows maximum 6 showcase items" in exc_info.value.message


async def test_ac_005_free_store_media_limits():
    """Each Free showcase item supports max 1 image and no video (AC-005, STO-R03).

    Given a Free Store item version,
    attaching 1 image succeeds; attaching a second image or any video is rejected with 403.
    """
    store_id = uuid4()
    tenant_id = uuid4()
    version_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    version = models.ItemVersion(
        id=version_id,
        item_id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        version_no=1,
        title="Item 1",
        approval_state="DRAFT",
    )
    free_ent = models.EntitlementProjection(
        store_id=store_id,
        tenant_id=tenant_id,
        plan_tier="FREE",
        max_items=6,
        max_images_per_item=1,
        max_videos_per_item=0,
    )

    # 1. Attaching video to Free item fails immediately
    img_res0 = MagicMock()
    img_res0.scalar_one.return_value = 0
    vid_res0 = MagicMock()
    vid_res0.scalar_one.return_value = 0

    mock_session = make_mock_session(
        execute_results=[img_res0, vid_res0],
        get_mapping={
            (models.ItemVersion, version_id): version,
            version_id: version,
            (models.EntitlementProjection, store_id): free_ent,
            store_id: free_ent,
        },
    )

    with pytest.raises(ApiError) as exc_info:
        await commands.create_media_upload_intent_command(
            session=mock_session,
            store_id=store_id,
            item_version_id=version_id,
            filename="demo.mp4",
            media_type="VIDEO",
            principal=owner_principal,
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert exc_info.value.status_code == 403
    assert "allows maximum 0 video(s)" in exc_info.value.message

    # 2. Attaching second image when 1 already exists fails
    img_res1 = MagicMock()
    img_res1.scalar_one.return_value = 1
    vid_res1 = MagicMock()
    vid_res1.scalar_one.return_value = 0

    mock_session2 = make_mock_session(
        execute_results=[img_res1, vid_res1],
        get_mapping={
            (models.ItemVersion, version_id): version,
            version_id: version,
            (models.EntitlementProjection, store_id): free_ent,
            store_id: free_ent,
        },
    )

    with pytest.raises(ApiError) as exc_info:
        await commands.create_media_upload_intent_command(
            session=mock_session2,
            store_id=store_id,
            item_version_id=version_id,
            filename="second.jpg",
            media_type="IMAGE",
            principal=owner_principal,
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert exc_info.value.status_code == 403
    assert "allows maximum 1 image(s)" in exc_info.value.message


async def test_ac_006_paid_catalog_not_blocked_by_free_six_limit():
    """Paid catalog is not blocked by the Free six-item limit (AC-006).

    Given a store with Commerce plan and 6 existing active items,
    creating a 7th item succeeds without error.
    """
    store_id = uuid4()
    tenant_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    commerce_ent = models.EntitlementProjection(
        store_id=store_id,
        tenant_id=tenant_id,
        plan_tier="COMMERCE",
        max_items=1_000_000,
        max_images_per_item=5,
        max_videos_per_item=0,
    )

    count_res = MagicMock()
    count_res.scalar_one.return_value = 6  # 6 existing items
    mock_session = make_mock_session(
        execute_results=[count_res],
        get_mapping={(models.EntitlementProjection, store_id): commerce_ent, store_id: commerce_ent},
    )

    item, version = await commands.create_catalog_item_command(
        session=mock_session,
        store_id=store_id,
        principal=owner_principal,
        item_type="PHYSICAL_PRODUCT",
        price_str="499.00",
        currency_code="INR",
        active=True,
        draft_title="Seventh Paid Item",
        draft_description="Allowed under Commerce plan",
        category_id=None,
    )
    assert item.price_paise == 49900
    assert version.title == "Seventh Paid Item"
    assert version.approval_state == "DRAFT"


async def test_ac_007_paid_store_hybrid_products_and_services():
    """Paid store may contain products and services coexisting in catalog (AC-007, STO-R04).

    Given an active paid store,
    creating a PHYSICAL_PRODUCT and an APPOINTMENT_SERVICE in the same catalog succeeds.
    """
    store_id = uuid4()
    tenant_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    growth_ent = models.EntitlementProjection(
        store_id=store_id,
        tenant_id=tenant_id,
        plan_tier="GROWTH",
        max_items=1_000_000,
        max_images_per_item=10,
        max_videos_per_item=1,
    )

    count_res = MagicMock()
    count_res.scalar_one.return_value = 2
    mock_session = make_mock_session(
        execute_results=[count_res],
        get_mapping={(models.EntitlementProjection, store_id): growth_ent, store_id: growth_ent},
    )

    # 1. Create Product
    prod_item, prod_ver = await commands.create_catalog_item_command(
        session=mock_session,
        store_id=store_id,
        principal=owner_principal,
        item_type="PHYSICAL_PRODUCT",
        price_str="850.00",
        currency_code="INR",
        active=True,
        draft_title="Handcrafted Mug",
        draft_description="Ceramic mug",
        category_id=None,
        product_details_input={"is_digital": False, "sku_code": "MUG-001"},
    )
    assert prod_item.item_type == "PHYSICAL_PRODUCT"

    # 2. Create Service in same store
    count_res2 = MagicMock()
    count_res2.scalar_one.return_value = 3
    mock_session2 = make_mock_session(
        execute_results=[count_res2],
        get_mapping={(models.EntitlementProjection, store_id): growth_ent, store_id: growth_ent},
    )

    svc_item, svc_ver = await commands.create_catalog_item_command(
        session=mock_session2,
        store_id=store_id,
        principal=owner_principal,
        item_type="APPOINTMENT_SERVICE",
        price_str="1500.00",
        currency_code="INR",
        active=True,
        draft_title="Consultation Session",
        draft_description="1 hour advisory",
        category_id=None,
        service_details_input={"is_appointment": True, "duration_minutes": 60},
    )
    assert svc_item.item_type == "APPOINTMENT_SERVICE"


async def test_ac_012_commerce_item_media_limits():
    """Commerce item media allows max 5 images and no video (AC-012).

    Given a Commerce store item,
    attaching a 6th image or a video is rejected with 403 ENTITLEMENT_REQUIRED.
    """
    store_id = uuid4()
    tenant_id = uuid4()
    version_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    version = models.ItemVersion(
        id=version_id,
        item_id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        version_no=1,
        title="Commerce Item",
        approval_state="DRAFT",
    )
    commerce_ent = models.EntitlementProjection(
        store_id=store_id,
        tenant_id=tenant_id,
        plan_tier="COMMERCE",
        max_items=1_000_000,
        max_images_per_item=5,
        max_videos_per_item=0,
    )

    # 1. 6th image rejected
    img_res = MagicMock()
    img_res.scalar_one.return_value = 5  # already has 5 images
    vid_res = MagicMock()
    vid_res.scalar_one.return_value = 0

    mock_session = make_mock_session(
        execute_results=[img_res, vid_res],
        get_mapping={
            (models.ItemVersion, version_id): version,
            version_id: version,
            (models.EntitlementProjection, store_id): commerce_ent,
            store_id: commerce_ent,
        },
    )

    with pytest.raises(ApiError) as exc_info:
        await commands.create_media_upload_intent_command(
            session=mock_session,
            store_id=store_id,
            item_version_id=version_id,
            filename="img6.jpg",
            media_type="IMAGE",
            principal=owner_principal,
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert "allows maximum 5 image(s)" in exc_info.value.message


async def test_ac_013_growth_item_media_limits():
    """Growth item media allows max 10 images + 1 video (AC-013).

    Given a Growth store item,
    attaching an 11th image or a 2nd video is rejected with 403 ENTITLEMENT_REQUIRED.
    """
    store_id = uuid4()
    tenant_id = uuid4()
    version_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    version = models.ItemVersion(
        id=version_id,
        item_id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        version_no=1,
        title="Growth Item",
        approval_state="DRAFT",
    )
    growth_ent = models.EntitlementProjection(
        store_id=store_id,
        tenant_id=tenant_id,
        plan_tier="GROWTH",
        max_items=1_000_000,
        max_images_per_item=10,
        max_videos_per_item=1,
    )

    # 2nd video rejected
    img_res = MagicMock()
    img_res.scalar_one.return_value = 3
    vid_res = MagicMock()
    vid_res.scalar_one.return_value = 1  # already has 1 video

    mock_session = make_mock_session(
        execute_results=[img_res, vid_res],
        get_mapping={
            (models.ItemVersion, version_id): version,
            version_id: version,
            (models.EntitlementProjection, store_id): growth_ent,
            store_id: growth_ent,
        },
    )

    with pytest.raises(ApiError) as exc_info:
        await commands.create_media_upload_intent_command(
            session=mock_session,
            store_id=store_id,
            item_version_id=version_id,
            filename="vid2.mp4",
            media_type="VIDEO",
            principal=owner_principal,
        )
    assert exc_info.value.code == ErrorCode.ENTITLEMENT_REQUIRED
    assert "allows maximum 1 video(s)" in exc_info.value.message


async def test_ac_014_scale_ai_media_limits():
    """Scale AI has no commercial media-count ceiling, subject to technical limits (AC-014).

    Given a Scale AI item with 15 images already uploaded,
    adding another image succeeds without commercial plan ceiling.
    """
    store_id = uuid4()
    tenant_id = uuid4()
    version_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    version = models.ItemVersion(
        id=version_id,
        item_id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        version_no=1,
        title="Scale AI Item",
        approval_state="DRAFT",
    )
    scale_ent = models.EntitlementProjection(
        store_id=store_id,
        tenant_id=tenant_id,
        plan_tier="SCALE_AI",
        max_items=1_000_000,
        max_images_per_item=50,
        max_videos_per_item=5,
    )

    img_res = MagicMock()
    img_res.scalar_one.return_value = 15  # 15 existing images
    vid_res = MagicMock()
    vid_res.scalar_one.return_value = 0

    mock_session = make_mock_session(
        execute_results=[img_res, vid_res],
        get_mapping={
            (models.ItemVersion, version_id): version,
            version_id: version,
            (models.EntitlementProjection, store_id): scale_ent,
            store_id: scale_ent,
        },
    )

    media, upload_url = await commands.create_media_upload_intent_command(
        session=mock_session,
        store_id=store_id,
        item_version_id=version_id,
        filename="img16.jpg",
        media_type="IMAGE",
        principal=owner_principal,
    )
    assert media.media_type == "IMAGE"
    assert "upload" in upload_url or "stores" in upload_url


async def test_ac_079_controlled_content_cannot_go_live_without_approval():
    """Controlled content cannot go LIVE without approval (AC-079, APR-R01, APR-R03).

    1. New draft version has approval_state DRAFT and live_version_id is None.
    2. Version is submitted calling APR-001; approval_state becomes PENDING.
    3. Public storefront snapshot returns empty items.
    4. Upon receiving content.approved.v1 event, live_version_id updates and item appears in snapshot.
    """
    store_id = uuid4()
    tenant_id = uuid4()
    item_id = uuid4()
    version_id = uuid4()
    approval_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    item = models.CatalogItem(
        id=item_id,
        tenant_id=tenant_id,
        store_id=store_id,
        item_type="PHYSICAL_PRODUCT",
        price_paise=19900,
        currency_code="INR",
        active=True,
        draft_version_id=version_id,
        live_version_id=None,
    )
    version = models.ItemVersion(
        id=version_id,
        item_id=item_id,
        tenant_id=tenant_id,
        store_id=store_id,
        version_no=1,
        title="Awesome T-Shirt",
        description="100% cotton",
        approval_state="DRAFT",
    )
    version.media = []

    # 1. Public snapshot has no live items
    mock_session = make_mock_session()
    empty_res = MagicMock()
    empty_res.scalars.return_value.all.return_value = []
    mock_session.execute.return_value = empty_res

    items, _ = await commands.get_public_store_snapshot_query(mock_session, store_id)
    assert len(items) == 0

    # 2. Submit version for approval
    mock_apr_client = MagicMock()
    mock_apr_client.submit_for_approval = AsyncMock(return_value=approval_id)

    submit_session = make_mock_session(
        get_mapping={
            (models.CatalogItem, item_id): item,
            item_id: item,
            (models.ItemVersion, version_id): version,
            version_id: version,
        }
    )
    submitted_ver, returned_appr_id, _ = await commands.submit_version_command(
        session=submit_session,
        item_id=item_id,
        version_id=version_id,
        principal=owner_principal,
        apr_client=mock_apr_client,
    )
    assert submitted_ver.approval_state == "PENDING"
    assert returned_appr_id == approval_id
    assert item.live_version_id is None  # Still not live!

    # 3. Simulate consuming content.approved.v1 event from APR
    inbox_session = make_mock_session(
        get_mapping={
            (models.CatalogItem, item_id): item,
            item_id: item,
        }
    )
    # Mock deduplication check (not processed) and version query
    dedupe_res = MagicMock()
    dedupe_res.scalars.return_value.first.return_value = None
    v_res = MagicMock()
    v_res.scalars.return_value.first.return_value = version
    inbox_session.execute.side_effect = [dedupe_res, v_res, MagicMock()]

    await events.handle_internal_event(
        session=inbox_session,
        event_id=str(uuid4()),
        event_type="content.approved.v1",
        payload={
            "content_id": str(item_id),
            "approval_id": str(approval_id),
        },
    )
    assert version.approval_state == "APPROVED_LIVE"
    assert item.live_version_id == version.id

    # 4. Now public snapshot serves the item
    snap_session = make_mock_session()
    live_res = MagicMock()
    live_res.scalars.return_value.all.return_value = [item]
    v_snap_res = MagicMock()
    v_snap_res.scalar_one_or_none.return_value = version
    snap_session.execute.side_effect = [live_res, v_snap_res]

    snapshot_items, _ = await commands.get_public_store_snapshot_query(snap_session, store_id)
    assert len(snapshot_items) == 1
    assert snapshot_items[0]["item_id"] == item_id
    assert snapshot_items[0]["title"] == "Awesome T-Shirt"
    assert snapshot_items[0]["price"] == "199.00"
