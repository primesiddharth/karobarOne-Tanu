# app/routes.py
# Thin route layer: parse -> authorize -> call command -> return (RULES.md §3 & §6).
import hashlib
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Header, Request, Query, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.platform_contracts.tokens import Principal, verify_token
from libs.platform_contracts.errors import ApiError, ErrorCode
from .config import settings
from .db import get_db_session
from . import domain
from . import models
from . import schemas
from . import commands

router = APIRouter()
security = HTTPBearer(auto_error=False)


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal:
    """Verifies RS256 Bearer JWT and extracts caller Principal."""
    if not credentials:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Missing Bearer token", status_code=401)

    return verify_token(
        token=credentials.credentials,
        public_key=settings.JWT_PUBLIC_KEY,
        issuer=settings.ISSUER,
        audience=settings.AUDIENCE,
    )


async def get_optional_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal | None:
    """Optional JWT principal for endpoints with public and authenticated variations (CAT-002, CAT-003)."""
    if not credentials:
        return None
    try:
        return verify_token(
            token=credentials.credentials,
            public_key=settings.JWT_PUBLIC_KEY,
            issuer=settings.ISSUER,
            audience=settings.AUDIENCE,
        )
    except Exception:
        return None


async def handle_idempotency(
    session: AsyncSession,
    scope: str,
    key: str | None,
    raw_body: dict,
    execute_coroutine,
):
    """Generic idempotency executor per RULES.md §6."""
    if not key:
        return await execute_coroutine()

    request_hash = hashlib.sha256(json.dumps(raw_body, sort_keys=True).encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    query = (
        select(models.IdempotencyKey)
        .where(models.IdempotencyKey.scope == scope, models.IdempotencyKey.key == key)
        .with_for_update()
    )
    res = await session.execute(query)
    stored = res.scalars().first()

    if stored:
        if stored.request_hash != request_hash:
            raise ApiError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Idempotency key reused with different request payload",
                status_code=409,
            )
        return JSONResponse(status_code=stored.response_code, content=stored.response_body)

    result = await execute_coroutine()
    result_data = (
        result
        if isinstance(result, dict)
        else (
            result.model_dump(mode="json")
            if hasattr(result, "model_dump")
            else str(result)
        )
    )

    idem_row = models.IdempotencyKey(
        id=uuid4(),
        scope=scope,
        key=key,
        request_hash=request_hash,
        response_code=200,
        response_body=result_data,
        created_at=now,
        locked_until=now + timedelta(minutes=5),
    )
    session.add(idem_row)
    await session.commit()
    return result


# -----------------------------------------------------------------------------
# CAT-001: POST /stores/{store_id}/items
# -----------------------------------------------------------------------------
@router.post("/stores/{store_id}/items", response_model=schemas.CreateCatalogItemResponse, status_code=status.HTTP_201_CREATED)
async def create_catalog_item(
    store_id: UUID,
    body: schemas.CreateCatalogItemRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        async with session.begin():
            item, version = await commands.create_catalog_item_command(
                session=session,
                store_id=store_id,
                principal=principal,
                item_type=body.item_type,
                price_str=body.operational.price,
                currency_code=body.operational.currency_code,
                active=body.operational.active,
                draft_title=body.draft.title,
                draft_description=body.draft.description,
                category_id=body.draft.category_id,
                product_details_input=body.product_details.model_dump() if body.product_details else None,
                service_details_input=body.service_details.model_dump() if body.service_details else None,
            )
            return schemas.CreateCatalogItemResponse(
                item_id=item.id,
                draft_version_id=version.id,
                approval_state=version.approval_state,
            )

    return await handle_idempotency(session, f"CAT-001:{store_id}", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# CAT-002: GET /stores/{store_id}/items
# -----------------------------------------------------------------------------
@router.get("/stores/{store_id}/items", response_model=schemas.ListCatalogItemsResponse)
async def list_catalog_items(
    store_id: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    principal: Principal | None = Depends(get_optional_principal),
    session: AsyncSession = Depends(get_db_session),
):
    is_staff = bool(
        principal
        and (
            any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER") for r in principal.roles)
            or (store_id in principal.store_ids and any(r in ("STORE_OWNER", "STORE_STAFF") for r in principal.roles))
        )
    )
    items, total = await commands.list_catalog_items_query(
        session=session,
        store_id=store_id,
        limit=limit,
        offset=offset,
        active_only=not is_staff,
    )
    return schemas.ListCatalogItemsResponse(
        items=[schemas.CatalogItemSummary(**it) for it in items],
        total=total,
    )


# -----------------------------------------------------------------------------
# CAT-003: GET /items/{item_id}
# -----------------------------------------------------------------------------
@router.get("/items/{item_id}", response_model=schemas.CatalogItemDetailResponse)
async def get_catalog_item(
    item_id: UUID,
    principal: Principal | None = Depends(get_optional_principal),
    session: AsyncSession = Depends(get_db_session),
):
    data = await commands.get_catalog_item_detail_query(session, item_id, principal=principal)
    return schemas.CatalogItemDetailResponse(**data)


# -----------------------------------------------------------------------------
# CAT-004: PATCH /items/{item_id}/operational (APR-R02)
# -----------------------------------------------------------------------------
@router.patch("/items/{item_id}/operational", response_model=schemas.UpdateOperationalResponse)
async def update_operational(
    item_id: UUID,
    body: schemas.UpdateOperationalRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        async with session.begin():
            item, updated_at = await commands.update_operational_command(
                session=session,
                item_id=item_id,
                principal=principal,
                price_str=body.price,
                currency_code=body.currency_code,
                active=body.active,
            )
            return schemas.UpdateOperationalResponse(
                item_id=item.id,
                price=domain.format_paise_to_decimal_str(item.price_paise),
                currency_code=item.currency_code,
                active=item.active,
                updated_at=updated_at,
            )

    return await handle_idempotency(session, f"CAT-004:{item_id}", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# CAT-005: POST /items/{item_id}/versions
# -----------------------------------------------------------------------------
@router.post("/items/{item_id}/versions", response_model=schemas.CreateVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_version(
    item_id: UUID,
    body: schemas.CreateVersionRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        async with session.begin():
            version = await commands.create_version_command(
                session=session,
                item_id=item_id,
                principal=principal,
                title=body.title,
                description=body.description,
                category_id=body.category_id,
            )
            return schemas.CreateVersionResponse(
                version_id=version.id,
                item_id=item_id,
                version_no=version.version_no,
                approval_state=version.approval_state,
                title=version.title,
            )

    return await handle_idempotency(session, f"CAT-005:{item_id}", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# CAT-006: POST /items/{item_id}/versions/{version_id}/submit
# -----------------------------------------------------------------------------
@router.post("/items/{item_id}/versions/{version_id}/submit", response_model=schemas.SubmitVersionResponse)
async def submit_version(
    item_id: UUID,
    version_id: UUID,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        async with session.begin():
            version, approval_id, submitted_at = await commands.submit_version_command(
                session=session,
                item_id=item_id,
                version_id=version_id,
                principal=principal,
            )
            return schemas.SubmitVersionResponse(
                item_id=item_id,
                version_id=version.id,
                approval_id=approval_id,
                approval_state=version.approval_state,
                submitted_at=submitted_at,
            )

    return await handle_idempotency(session, f"CAT-006:{item_id}:{version_id}", idempotency_key, {}, _action)


# -----------------------------------------------------------------------------
# CAT-007: POST /stores/{store_id}/pages/{page_type}/versions
# -----------------------------------------------------------------------------
@router.post(
    "/stores/{store_id}/pages/{page_type}/versions",
    response_model=schemas.CreatePageVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_page_version(
    store_id: UUID,
    page_type: str,
    body: schemas.CreatePageVersionRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        async with session.begin():
            res = await commands.create_page_version_command(
                session=session,
                store_id=store_id,
                page_type=page_type,
                content_json=body.content_json,
                principal=principal,
            )
            return schemas.CreatePageVersionResponse(
                store_id=res["store_id"],
                page_type=res["page_type"],
                version_no=res["version_no"],
                status=res["status"],
            )

    return await handle_idempotency(
        session, f"CAT-007:{store_id}:{page_type}", idempotency_key, body.model_dump(mode="json"), _action
    )


# -----------------------------------------------------------------------------
# CAT-008: POST /stores/{store_id}/media/upload-intents
# -----------------------------------------------------------------------------
@router.post("/stores/{store_id}/media/upload-intents", response_model=schemas.CreateMediaUploadIntentResponse)
async def create_media_upload_intent(
    store_id: UUID,
    body: schemas.CreateMediaUploadIntentRequest,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        async with session.begin():
            media, upload_url = await commands.create_media_upload_intent_command(
                session=session,
                store_id=store_id,
                item_version_id=body.item_version_id,
                filename=body.filename,
                media_type=body.media_type,
                principal=principal,
            )
            return schemas.CreateMediaUploadIntentResponse(
                media_id=media.id,
                storage_key=media.storage_key,
                upload_url=upload_url,
                public_url=media.url,
            )

    return await handle_idempotency(session, f"CAT-008:{store_id}", idempotency_key, body.model_dump(mode="json"), _action)


# -----------------------------------------------------------------------------
# CAT-009: POST /items/{item_id}/unpublish
# -----------------------------------------------------------------------------
@router.post("/items/{item_id}/unpublish", response_model=schemas.UnpublishItemResponse)
async def unpublish_item(
    item_id: UUID,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        async with session.begin():
            item, old_live = await commands.unpublish_item_command(
                session=session,
                item_id=item_id,
                principal=principal,
            )
            return schemas.UnpublishItemResponse(
                item_id=item.id,
                status="UNPUBLISHED",
                unregistered_live_version=old_live,
            )

    return await handle_idempotency(session, f"CAT-009:{item_id}", idempotency_key, {}, _action)


# -----------------------------------------------------------------------------
# CAT-010: GET /public/stores/{store_id}/snapshot (PUBLIC read-model)
# -----------------------------------------------------------------------------
@router.get("/public/stores/{store_id}/snapshot", response_model=schemas.PublicSnapshotResponse)
async def get_public_store_snapshot(
    store_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    items, snap_at = await commands.get_public_store_snapshot_query(session, store_id)
    return schemas.PublicSnapshotResponse(
        store_id=store_id,
        items=[
            schemas.PublicSnapshotItem(
                item_id=it["item_id"],
                title=it["title"],
                description=it["description"],
                item_type=it["item_type"],
                price=it["price"],
                currency_code=it["currency_code"],
                media=[schemas.PublicMediaItem(**m) for m in it["media"]],
            )
            for it in items
        ],
        snapshot_at=snap_at,
    )
