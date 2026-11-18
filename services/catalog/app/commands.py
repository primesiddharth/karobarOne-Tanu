# app/commands.py
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from libs.platform_contracts.errors import ApiError, ErrorCode
from libs.platform_contracts.tokens import Principal
from . import models, domain
from .events import add_event
from .clients import approval_client, storage_client, subscription_client


async def _get_or_create_entitlement(session: AsyncSession, store_id: UUID, tenant_id: UUID) -> models.EntitlementProjection:
    """Helper getting local entitlement projection or resolving from Subscription service."""
    ent = await session.get(models.EntitlementProjection, store_id)
    if not ent:
        sub_ent = await subscription_client.get_store_entitlements(store_id)
        plan_code = sub_ent.get("plan_code", "FREE").upper()
        if plan_code == "PRESENCE":
            plan_code = "FREE"
        ent = models.EntitlementProjection(
            store_id=store_id,
            tenant_id=tenant_id,
            plan_tier=plan_code,
            max_items=sub_ent.get("showcase_limit") or 1_000_000,
            max_images_per_item=sub_ent.get("max_images_per_item", 1),
            max_videos_per_item=sub_ent.get("max_videos_per_item", 0),
            blog_enabled=sub_ent.get("blog_allowed", False),
        )
        session.add(ent)
        await session.flush()
    return ent


# ------------------------------------------------------------------------------
# CAT-001: Create catalog item (AC-004, AC-006, AC-007)
# ------------------------------------------------------------------------------

async def create_catalog_item_command(
    session: AsyncSession,
    store_id: UUID,
    principal: Principal,
    item_type: str,
    price_str: str,
    currency_code: str,
    active: bool,
    draft_title: str,
    draft_description: str,
    category_id: UUID | None,
    product_details_input: dict | None = None,
    service_details_input: dict | None = None,
) -> tuple[models.CatalogItem, models.ItemVersion]:
    # Authorization check (RULES.md §5, IDOR protection)
    is_staff = any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
    if not is_staff and principal.store_ids and store_id not in principal.store_ids:
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Store access denied", status_code=403)

    tenant_id = principal.tenant_ids[0] if principal.tenant_ids else uuid4()
    domain.validate_item_type(item_type)
    price_paise = domain.parse_price_to_paise(price_str)

    # Entitlement check (AC-004, AC-006)
    ent = await _get_or_create_entitlement(session, store_id, tenant_id)
    if active:
        count_stmt = select(func.count()).select_from(models.CatalogItem).where(
            models.CatalogItem.store_id == store_id,
            models.CatalogItem.active == True,
        )
        count_res = await session.execute(count_stmt)
        active_count = count_res.scalar_one()
        domain.validate_item_creation_entitlement(ent.plan_tier, active_count)

    item_id = uuid4()
    version_id = uuid4()
    now = datetime.now(timezone.utc)

    # Create CatalogItem
    item = models.CatalogItem(
        id=item_id,
        tenant_id=tenant_id,
        store_id=store_id,
        item_type=item_type,
        price_paise=price_paise,
        currency_code=currency_code,
        active=active,
        draft_version_id=version_id,
        live_version_id=None,  # Controlled fields never start live (AC-079)
        created_at=now,
        updated_at=now,
    )
    session.add(item)

    # Create initial draft version
    version = models.ItemVersion(
        id=version_id,
        item_id=item_id,
        tenant_id=tenant_id,
        store_id=store_id,
        version_no=1,
        title=draft_title,
        description=draft_description,
        category_id=category_id,
        approval_state="DRAFT",
        created_at=now,
    )
    session.add(version)

    # Hybrid product/service details (AC-007)
    if item_type in ("PHYSICAL_PRODUCT", "DIGITAL_PRODUCT"):
        prod_input = product_details_input or {}
        prod = models.ProductDetails(
            id=uuid4(),
            item_id=item_id,
            tenant_id=tenant_id,
            store_id=store_id,
            is_digital=prod_input.get("is_digital", item_type == "DIGITAL_PRODUCT"),
            sku_code=prod_input.get("sku_code"),
        )
        session.add(prod)
    elif item_type in ("APPOINTMENT_SERVICE", "NON_APPOINTMENT_SERVICE"):
        svc_input = service_details_input or {}
        svc = models.ServiceDetails(
            id=uuid4(),
            item_id=item_id,
            tenant_id=tenant_id,
            store_id=store_id,
            is_appointment=svc_input.get("is_appointment", item_type == "APPOINTMENT_SERVICE"),
            duration_minutes=svc_input.get("duration_minutes", 60 if item_type == "APPOINTMENT_SERVICE" else None),
        )
        session.add(svc)

    await add_event(
        session=session,
        event_type="catalog.item-created.v1",
        aggregate_type="catalog_item",
        aggregate_id=item_id,
        tenant_id=tenant_id,
        store_id=store_id,
        topic="catalog.lifecycle",
        payload={
            "item_id": str(item_id),
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
            "item_type": item_type,
            "draft_version_id": str(version_id),
            "price_paise": price_paise,
            "currency_code": currency_code,
            "created_at": now.isoformat(),
        },
    )

    await session.flush()
    return item, version


# ------------------------------------------------------------------------------
# CAT-002: List catalog items
# ------------------------------------------------------------------------------

async def list_catalog_items_query(
    session: AsyncSession,
    store_id: UUID,
    limit: int = 50,
    offset: int = 0,
    active_only: bool = False,
) -> tuple[list[dict], int]:
    stmt = select(models.CatalogItem).where(models.CatalogItem.store_id == store_id)
    if active_only:
        stmt = stmt.where(models.CatalogItem.active == True)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_res = await session.execute(count_stmt)
    total = count_res.scalar_one()

    stmt = stmt.order_by(models.CatalogItem.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    items = list(result.scalars().all())

    summaries = []
    for it in items:
        # Fetch title from draft or live version
        v_stmt = select(models.ItemVersion.title).where(
            models.ItemVersion.id == (it.draft_version_id or it.live_version_id)
        )
        v_res = await session.execute(v_stmt)
        title = v_res.scalar_one_or_none() or "Untitled"

        summaries.append({
            "id": it.id,
            "tenant_id": it.tenant_id,
            "store_id": it.store_id,
            "item_type": it.item_type,
            "price": domain.format_paise_to_decimal_str(it.price_paise),
            "currency_code": it.currency_code,
            "active": it.active,
            "live_version_id": it.live_version_id,
            "draft_version_id": it.draft_version_id,
            "title": title,
            "created_at": it.created_at,
        })

    return summaries, total


# ------------------------------------------------------------------------------
# CAT-003: Read item details
# ------------------------------------------------------------------------------

async def get_catalog_item_detail_query(
    session: AsyncSession,
    item_id: UUID,
    principal: Principal | None = None,
    is_staff: bool = False,
) -> dict:
    stmt = (
        select(models.CatalogItem)
        .options(
            selectinload(models.CatalogItem.product_details),
            selectinload(models.CatalogItem.service_details),
        )
        .where(models.CatalogItem.id == item_id)
    )
    res = await session.execute(stmt)
    item = res.scalar_one_or_none()
    if not item:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Catalog item not found", status_code=404)

    can_view_draft = is_staff
    if principal:
        if any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles):
            can_view_draft = True
        elif item.store_id in principal.store_ids and any(r in ("STORE_OWNER", "STORE_STAFF") for r in principal.roles):
            can_view_draft = True

    if not item.live_version_id and not can_view_draft:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Catalog item not found", status_code=404)

    live_ver = None
    if item.live_version_id:
        lv_stmt = (
            select(models.ItemVersion)
            .options(selectinload(models.ItemVersion.media))
            .where(models.ItemVersion.id == item.live_version_id)
        )
        lv_res = await session.execute(lv_stmt)
        live_ver = lv_res.scalar_one_or_none()

    draft_ver = None
    if can_view_draft and item.draft_version_id:
        dv_stmt = (
            select(models.ItemVersion)
            .options(selectinload(models.ItemVersion.media))
            .where(models.ItemVersion.id == item.draft_version_id)
        )
        dv_res = await session.execute(dv_stmt)
        draft_ver = dv_res.scalar_one_or_none()

    def _format_ver(v: models.ItemVersion | None):
        if not v:
            return None
        return {
            "id": v.id,
            "version_no": v.version_no,
            "title": v.title,
            "description": v.description,
            "category_id": v.category_id,
            "approval_state": v.approval_state,
            "approval_request_id": v.approval_request_id,
            "media": [
                {
                    "id": m.id,
                    "media_type": m.media_type,
                    "url": m.url,
                    "sort_order": m.sort_order,
                }
                for m in v.media
            ],
        }

    return {
        "id": item.id,
        "tenant_id": item.tenant_id,
        "store_id": item.store_id,
        "item_type": item.item_type,
        "price": domain.format_paise_to_decimal_str(item.price_paise),
        "currency_code": item.currency_code,
        "active": item.active,
        "live_version_id": item.live_version_id,
        "draft_version_id": item.draft_version_id if is_staff else None,
        "live_version": _format_ver(live_ver),
        "draft_version": _format_ver(draft_ver),
        "is_digital": item.product_details.is_digital if item.product_details else None,
        "sku_code": item.product_details.sku_code if item.product_details else None,
        "is_appointment": item.service_details.is_appointment if item.service_details else None,
        "duration_minutes": item.service_details.duration_minutes if item.service_details else None,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


# ------------------------------------------------------------------------------
# CAT-004: PATCH operational fields (APR-R02: No approval required)
# ------------------------------------------------------------------------------

async def update_operational_command(
    session: AsyncSession,
    item_id: UUID,
    principal: Principal,
    price_str: str | None = None,
    currency_code: str | None = None,
    active: bool | None = None,
) -> tuple[models.CatalogItem, datetime]:
    item = await session.get(models.CatalogItem, item_id)
    if not item:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Catalog item not found", status_code=404)

    is_staff = any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
    if not is_staff and item.store_id not in principal.store_ids:
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Store access denied", status_code=403)

    now = datetime.now(timezone.utc)
    updated = False

    if price_str is not None:
        item.price_paise = domain.parse_price_to_paise(price_str)
        updated = True

    if currency_code is not None:
        item.currency_code = currency_code
        updated = True

    if active is not None and active != item.active:
        if active:
            # Check entitlement if activating
            ent = await _get_or_create_entitlement(session, item.store_id, item.tenant_id)
            count_stmt = select(func.count()).select_from(models.CatalogItem).where(
                models.CatalogItem.store_id == item.store_id,
                models.CatalogItem.active == True,
            )
            count_res = await session.execute(count_stmt)
            active_count = count_res.scalar_one()
            domain.validate_item_creation_entitlement(ent.plan_tier, active_count)

        item.active = active
        updated = True

    if updated:
        item.updated_at = now
        await add_event(
            session=session,
            event_type="catalog.item-operational-changed.v1",
            aggregate_type="catalog_item",
            aggregate_id=item.id,
            tenant_id=item.tenant_id,
            store_id=item.store_id,
            topic="catalog.lifecycle",
            payload={
                "item_id": str(item.id),
                "store_id": str(item.store_id),
                "price_paise": item.price_paise,
                "currency_code": item.currency_code,
                "active": item.active,
                "updated_at": now.isoformat(),
            },
        )
        if item.live_version_id:
            await add_event(
                session=session,
                event_type="storefront.snapshot-invalidated.v1",
                aggregate_type="catalog_item",
                aggregate_id=item.id,
                tenant_id=item.tenant_id,
                store_id=item.store_id,
                topic="catalog.lifecycle",
                payload={"store_id": str(item.store_id), "item_id": str(item.id)},
            )

    await session.flush()
    return item, now


# ------------------------------------------------------------------------------
# CAT-005: Create controlled version (DRAFT)
# ------------------------------------------------------------------------------

async def create_version_command(
    session: AsyncSession,
    item_id: UUID,
    principal: Principal,
    title: str,
    description: str,
    category_id: UUID | None = None,
) -> models.ItemVersion:
    item = await session.get(models.CatalogItem, item_id)
    if not item:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Catalog item not found", status_code=404)

    is_staff = any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
    if not is_staff and item.store_id not in principal.store_ids:
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Store access denied", status_code=403)

    # Next version number
    max_stmt = select(func.max(models.ItemVersion.version_no)).where(models.ItemVersion.item_id == item_id)
    max_res = await session.execute(max_stmt)
    cur_max = max_res.scalar_one() or 0
    next_ver = cur_max + 1

    now = datetime.now(timezone.utc)
    version = models.ItemVersion(
        id=uuid4(),
        item_id=item.id,
        tenant_id=item.tenant_id,
        store_id=item.store_id,
        version_no=next_ver,
        title=title,
        description=description,
        category_id=category_id,
        approval_state="DRAFT",
        created_at=now,
    )
    session.add(version)
    item.draft_version_id = version.id
    item.updated_at = now

    await add_event(
        session=session,
        event_type="catalog.version-created.v1",
        aggregate_type="catalog_item",
        aggregate_id=item.id,
        tenant_id=item.tenant_id,
        store_id=item.store_id,
        topic="catalog.lifecycle",
        payload={
            "item_id": str(item.id),
            "version_id": str(version.id),
            "version_no": next_ver,
            "created_at": now.isoformat(),
        },
    )

    await session.flush()
    return version


# ------------------------------------------------------------------------------
# CAT-006: Submit version for approval (calls APR-001 synchronously per RULES C7)
# ------------------------------------------------------------------------------

async def submit_version_command(
    session: AsyncSession,
    item_id: UUID,
    version_id: UUID,
    principal: Principal,
    apr_client: approval_client.__class__ = approval_client,
) -> tuple[models.ItemVersion, UUID, datetime]:
    item = await session.get(models.CatalogItem, item_id)
    if not item:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Catalog item not found", status_code=404)

    version = await session.get(models.ItemVersion, version_id)
    if not version or version.item_id != item_id:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Version not found for this item", status_code=404)

    is_staff = any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
    if not is_staff and item.store_id not in principal.store_ids:
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Store access denied", status_code=403)

    if version.approval_state not in ("DRAFT", "REJECTED"):
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Cannot submit version in state {version.approval_state}",
            status_code=409,
        )

    # Synchronous call to APR-001 (RULES.md C7)
    approval_id = await apr_client.submit_for_approval(
        tenant_id=item.tenant_id,
        store_id=item.store_id,
        subject_type="ITEM_VERSION",
        subject_id=item.id,
        subject_version=str(version.version_no),
        submitted_by=principal.id,
        priority=0,
    )

    now = datetime.now(timezone.utc)
    version.approval_state = "PENDING"
    version.approval_request_id = approval_id
    version.submitted_at = now
    item.updated_at = now

    await session.flush()
    return version, approval_id, now


# ------------------------------------------------------------------------------
# CAT-008: Media upload intent (AC-005, AC-012, AC-013, AC-014)
# ------------------------------------------------------------------------------

async def create_media_upload_intent_command(
    session: AsyncSession,
    store_id: UUID,
    item_version_id: UUID,
    filename: str,
    media_type: str,
    principal: Principal,
    s3_client: storage_client.__class__ = storage_client,
) -> tuple[models.ItemMedia, str]:
    version = await session.get(models.ItemVersion, item_version_id)
    if not version or version.store_id != store_id:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Version not found for this store", status_code=404)

    is_staff = any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
    if not is_staff and store_id not in principal.store_ids:
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Store access denied", status_code=403)

    # Entitlement check for media counts
    ent = await _get_or_create_entitlement(session, store_id, version.tenant_id)

    img_count_stmt = select(func.count()).select_from(models.ItemMedia).where(
        models.ItemMedia.item_version_id == item_version_id,
        models.ItemMedia.media_type == "IMAGE",
    )
    img_res = await session.execute(img_count_stmt)
    img_count = img_res.scalar_one()

    vid_count_stmt = select(func.count()).select_from(models.ItemMedia).where(
        models.ItemMedia.item_version_id == item_version_id,
        models.ItemMedia.media_type == "VIDEO",
    )
    vid_res = await session.execute(vid_count_stmt)
    vid_count = vid_res.scalar_one()

    domain.validate_media_attachment_entitlement(ent.plan_tier, img_count, vid_count, media_type.upper())

    # Generate non-guessable storage key and pre-signed upload URL
    storage_key, upload_url, cdn_url = s3_client.generate_upload_intent(store_id, filename, media_type)

    now = datetime.now(timezone.utc)
    media = models.ItemMedia(
        id=uuid4(),
        item_version_id=item_version_id,
        tenant_id=version.tenant_id,
        store_id=store_id,
        media_type=media_type.upper(),
        storage_key=storage_key,
        url=cdn_url,
        sort_order=img_count + vid_count,
        created_at=now,
    )
    session.add(media)

    await add_event(
        session=session,
        event_type="catalog.media-uploaded.v1",
        aggregate_type="item_media",
        aggregate_id=media.id,
        tenant_id=version.tenant_id,
        store_id=store_id,
        topic="catalog.lifecycle",
        payload={
            "media_id": str(media.id),
            "item_version_id": str(item_version_id),
            "media_type": media.media_type,
            "storage_key": storage_key,
            "created_at": now.isoformat(),
        },
    )

    await session.flush()
    return media, upload_url


# ------------------------------------------------------------------------------
# CAT-009: Unpublish item (Soft unpublish)
# ------------------------------------------------------------------------------

async def unpublish_item_command(
    session: AsyncSession,
    item_id: UUID,
    principal: Principal,
) -> tuple[models.CatalogItem, UUID | None]:
    item = await session.get(models.CatalogItem, item_id)
    if not item:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Catalog item not found", status_code=404)

    is_staff = any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
    if not is_staff and item.store_id not in principal.store_ids:
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Store access denied", status_code=403)

    old_live = item.live_version_id
    item.live_version_id = None
    now = datetime.now(timezone.utc)
    item.updated_at = now

    await add_event(
        session=session,
        event_type="catalog.item-unpublished.v1",
        aggregate_type="catalog_item",
        aggregate_id=item.id,
        tenant_id=item.tenant_id,
        store_id=item.store_id,
        topic="catalog.lifecycle",
        payload={
            "item_id": str(item.id),
            "store_id": str(item.store_id),
            "unregistered_live_version": str(old_live) if old_live else None,
            "occurred_at": now.isoformat(),
        },
    )
    await add_event(
        session=session,
        event_type="storefront.snapshot-invalidated.v1",
        aggregate_type="catalog_item",
        aggregate_id=item.id,
        tenant_id=item.tenant_id,
        store_id=item.store_id,
        topic="catalog.lifecycle",
        payload={"store_id": str(item.store_id), "item_id": str(item.id)},
    )

    await session.flush()
    return item, old_live


# ------------------------------------------------------------------------------
# CAT-010: Public storefront snapshot (LIVE-only projection)
# ------------------------------------------------------------------------------

async def get_public_store_snapshot_query(
    session: AsyncSession,
    store_id: UUID,
) -> tuple[list[dict], datetime]:
    """Reads approved LIVE-only projection; drafts and rejected items are completely unreachable (AC-079, CAT-010)."""
    stmt = (
        select(models.CatalogItem)
        .where(
            models.CatalogItem.store_id == store_id,
            models.CatalogItem.active == True,
            models.CatalogItem.live_version_id.isnot(None),  # Must be LIVE
        )
        .order_by(models.CatalogItem.created_at.asc())
    )
    res = await session.execute(stmt)
    live_items = list(res.scalars().all())

    now = datetime.now(timezone.utc)
    snapshot_items = []

    for item in live_items:
        v_stmt = (
            select(models.ItemVersion)
            .options(selectinload(models.ItemVersion.media))
            .where(models.ItemVersion.id == item.live_version_id)
        )
        v_res = await session.execute(v_stmt)
        ver = v_res.scalar_one_or_none()
        if not ver:
            continue

        media_list = [
            {
                "media_type": m.media_type,
                "url": m.url,
                "sort_order": m.sort_order,
            }
            for m in ver.media
        ]

        snapshot_items.append({
            "item_id": item.id,
            "title": ver.title,
            "description": ver.description,
            "item_type": item.item_type,
            "price": domain.format_paise_to_decimal_str(item.price_paise),
            "currency_code": item.currency_code,
            "media": media_list,
        })

    return snapshot_items, now


# ------------------------------------------------------------------------------
# CAT-007: Create page content version (DB Spec §7.5, SERVICES.md §4)
# ------------------------------------------------------------------------------
async def create_page_version_command(
    session: AsyncSession,
    store_id: UUID,
    page_type: str,
    content_json: dict,
    principal: Principal,
    correlation_id: UUID | None = None,
) -> dict:
    """CAT-007: Creates a new draft page content version (DB Spec §7.5)."""
    if not (principal.has_role("STORE_OWNER") or principal.has_role("STORE_STAFF") or principal.has_role("PLATFORM_OWNER")):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden", status_code=403)
    if not principal.has_store(store_id):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Principal has no access to this store", status_code=403)

    norm_section = domain.validate_page_type(page_type)
    content_hash = domain.compute_content_hash(content_json)
    now = datetime.now(timezone.utc)

    ver_stmt = (
        select(func.coalesce(func.max(models.StoreContentVersion.version_no), 0))
        .where(
            models.StoreContentVersion.store_id == store_id,
            models.StoreContentVersion.content_section == norm_section,
        )
    )
    res = await session.execute(ver_stmt)
    next_version = res.scalar_one() + 1

    tenant_id = principal.tenant_ids[0] if principal.tenant_ids else store_id

    page_ver = models.StoreContentVersion(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        content_section=norm_section,
        version_no=next_version,
        content_json=content_json,
        approval_state="DRAFT",
        content_hash=content_hash,
        created_at=now,
        updated_at=now,
    )
    session.add(page_ver)

    # TODO(OQ-024): gap event catalog.page-version-created.v1 is in SOURCE_GAPS.json, omit publish per RULES.md §1 C8

    await session.flush()
    return {
        "store_id": store_id,
        "page_type": norm_section,
        "version_no": next_version,
        "status": "DRAFT",
    }
