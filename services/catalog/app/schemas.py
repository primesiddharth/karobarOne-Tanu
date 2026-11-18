# app/schemas.py
from datetime import datetime
from uuid import UUID
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class BaseContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------------
# CAT-001: Create catalog item
# ------------------------------------------------------------------------------

class OperationalInput(BaseContractModel):
    price: str = Field(..., max_length=16)
    currency_code: str = Field("INR", min_length=3, max_length=3)
    active: bool = True


class DraftVersionInput(BaseContractModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=10000)
    category_id: Optional[UUID] = None


class ProductDetailsInput(BaseContractModel):
    is_digital: bool = False
    sku_code: Optional[str] = Field(None, max_length=64)


class ServiceDetailsInput(BaseContractModel):
    is_appointment: bool = False
    duration_minutes: Optional[int] = Field(None, ge=1, le=1440)


class CreateCatalogItemRequest(BaseContractModel):
    item_type: str = Field(..., max_length=32)
    operational: OperationalInput
    draft: DraftVersionInput
    product_details: Optional[ProductDetailsInput] = None
    service_details: Optional[ServiceDetailsInput] = None


class CreateCatalogItemResponse(BaseContractModel):
    item_id: UUID
    draft_version_id: UUID
    approval_state: str = "DRAFT"


# ------------------------------------------------------------------------------
# CAT-002: List catalog items
# ------------------------------------------------------------------------------

class CatalogItemSummary(BaseContractModel):
    id: UUID
    tenant_id: UUID
    store_id: UUID
    item_type: str
    price: str
    currency_code: str
    active: bool
    live_version_id: Optional[UUID] = None
    draft_version_id: Optional[UUID] = None
    title: str
    created_at: datetime


class ListCatalogItemsResponse(BaseContractModel):
    items: List[CatalogItemSummary]
    total: int


# ------------------------------------------------------------------------------
# CAT-003: Read item details
# ------------------------------------------------------------------------------

class MediaItemDetail(BaseContractModel):
    id: UUID
    media_type: str
    url: str
    sort_order: int


class ItemVersionDetail(BaseContractModel):
    id: UUID
    version_no: int
    title: str
    description: str
    category_id: Optional[UUID] = None
    approval_state: str
    approval_request_id: Optional[UUID] = None
    media: List[MediaItemDetail] = Field(default_factory=list)


class CatalogItemDetailResponse(BaseContractModel):
    id: UUID
    tenant_id: UUID
    store_id: UUID
    item_type: str
    price: str
    currency_code: str
    active: bool
    live_version_id: Optional[UUID] = None
    draft_version_id: Optional[UUID] = None
    live_version: Optional[ItemVersionDetail] = None
    draft_version: Optional[ItemVersionDetail] = None
    is_digital: Optional[bool] = None
    sku_code: Optional[str] = None
    is_appointment: Optional[bool] = None
    duration_minutes: Optional[int] = None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------------------
# CAT-004: PATCH operational fields (APR-R02)
# ------------------------------------------------------------------------------

class UpdateOperationalRequest(BaseContractModel):
    price: Optional[str] = Field(None, max_length=16)
    currency_code: Optional[str] = Field(None, min_length=3, max_length=3)
    active: Optional[bool] = None


class UpdateOperationalResponse(BaseContractModel):
    item_id: UUID
    price: str
    currency_code: str
    active: bool
    updated_at: datetime


# ------------------------------------------------------------------------------
# CAT-005: Create controlled version
# ------------------------------------------------------------------------------

class CreateVersionRequest(BaseContractModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=10000)
    category_id: Optional[UUID] = None


class CreateVersionResponse(BaseContractModel):
    version_id: UUID
    item_id: UUID
    version_no: int
    approval_state: str = "DRAFT"
    title: str


# ------------------------------------------------------------------------------
# CAT-006: Submit version for approval
# ------------------------------------------------------------------------------

class SubmitVersionResponse(BaseContractModel):
    item_id: UUID
    version_id: UUID
    approval_id: UUID
    approval_state: str = "PENDING"
    submitted_at: datetime


# ------------------------------------------------------------------------------
# CAT-007: Store page versions (Storefront CMS)
# ------------------------------------------------------------------------------

class CreatePageVersionRequest(BaseContractModel):
    content_json: dict[str, Any] = Field(default_factory=dict)


class CreatePageVersionResponse(BaseContractModel):
    store_id: UUID
    page_type: str
    version_no: int
    status: str = "DRAFT"


# ------------------------------------------------------------------------------
# CAT-008: Media upload intent
# ------------------------------------------------------------------------------

class CreateMediaUploadIntentRequest(BaseContractModel):
    item_version_id: UUID
    filename: str = Field(..., min_length=1, max_length=255)
    media_type: str = Field(..., max_length=16)  # IMAGE | VIDEO


class CreateMediaUploadIntentResponse(BaseContractModel):
    media_id: UUID
    storage_key: str
    upload_url: str
    public_url: str


# ------------------------------------------------------------------------------
# CAT-009: Unpublish item
# ------------------------------------------------------------------------------

class UnpublishItemResponse(BaseContractModel):
    item_id: UUID
    status: str = "UNPUBLISHED"
    unregistered_live_version: Optional[UUID] = None


# ------------------------------------------------------------------------------
# CAT-010: Public storefront snapshot
# ------------------------------------------------------------------------------

class PublicMediaItem(BaseContractModel):
    media_type: str
    url: str
    sort_order: int


class PublicSnapshotItem(BaseContractModel):
    item_id: UUID
    title: str
    description: str
    item_type: str
    price: str
    currency_code: str
    media: List[PublicMediaItem] = Field(default_factory=list)


class PublicSnapshotResponse(BaseContractModel):
    store_id: UUID
    items: List[PublicSnapshotItem]
    snapshot_at: datetime
