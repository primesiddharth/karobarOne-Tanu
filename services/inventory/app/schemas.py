# app/schemas.py
from datetime import datetime
from decimal import Decimal
from uuid import UUID
from typing import Optional, List, Literal, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class BaseContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------------
# INV-001: Availability
# ------------------------------------------------------------------------------

class SkuAvailabilityDto(BaseContractModel):
    sku_id: UUID
    is_tracked: bool
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    is_available: bool


class InventoryAvailabilityResponse(BaseContractModel):
    store_id: UUID
    lines: List[SkuAvailabilityDto]


# ------------------------------------------------------------------------------
# INV-002: Reservations
# ------------------------------------------------------------------------------

class ReservationLineRequest(BaseContractModel):
    sku_id: UUID
    quantity: str = Field(
        ...,
        pattern=r"^\d+(?:\.\d{1,3})?$",
        description="Quantity to reserve as a decimal string (max 3 decimal places).",
    )

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_positive(cls, v: Any) -> str:
        s = str(v).strip()
        d = Decimal(s)
        if d <= 0:
            raise ValueError("Quantity must be greater than zero")
        return s

    @property
    def qty_units(self) -> int:
        return int(Decimal(self.quantity))


class CreateReservationRequest(BaseContractModel):
    store_id: UUID
    checkout_id: UUID
    lines: List[ReservationLineRequest] = Field(..., min_length=1)
    ttl_seconds: Optional[int] = Field(default=600, ge=30, le=3600)


class ReservationItemDto(BaseContractModel):
    id: UUID
    sku_id: UUID
    quantity: str = Field(..., pattern=r"^\d+(?:\.\d{1,3})?$")
    expires_at: datetime


class CreateReservationResponse(BaseContractModel):
    reservation_group_id: UUID
    reservations: List[ReservationItemDto]


# ------------------------------------------------------------------------------
# INV-003: Consume Reservation
# ------------------------------------------------------------------------------

class ConsumeReservationResponse(BaseContractModel):
    reservation_id: UUID
    status: str
    consumed_at: datetime
    sku_id: UUID
    quantity: int


# ------------------------------------------------------------------------------
# INV-004: Release Reservation
# ------------------------------------------------------------------------------

class ReleaseReservationResponse(BaseContractModel):
    reservation_id: UUID
    status: str
    released_at: datetime
    sku_id: UUID
    quantity: int


# ------------------------------------------------------------------------------
# INV-005: Adjustments
# ------------------------------------------------------------------------------

class CreateAdjustmentRequest(BaseContractModel):
    store_id: UUID
    sku_id: UUID
    adjustment_type: Literal["INCREMENT", "DECREMENT", "SET"]
    quantity: int = Field(..., ge=0)
    reason: Optional[str] = Field(default=None, max_length=255)


class AdjustmentResponse(BaseContractModel):
    adjustment_id: UUID
    sku_id: UUID
    adjustment_type: str
    quantity: int
    new_on_hand_qty: int
    new_available_qty: int


# ------------------------------------------------------------------------------
# INV-006: Store Inventory View
# ------------------------------------------------------------------------------

class InventoryItemDto(BaseContractModel):
    sku_id: UUID
    sku_code: Optional[str] = None
    is_tracked: bool
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    last_movement_at: Optional[datetime] = None


class StoreInventoryResponse(BaseContractModel):
    store_id: UUID
    items: List[InventoryItemDto]
    total_count: int


# ------------------------------------------------------------------------------
# Internal SKU Registration
# ------------------------------------------------------------------------------

class RegisterSkuRequest(BaseContractModel):
    store_id: UUID
    sku_id: UUID
    sku_code: Optional[str] = None
    is_tracked: bool = True
    initial_stock: int = Field(default=0, ge=0)


class RegisterSkuResponse(BaseContractModel):
    sku_id: UUID
    store_id: UUID
    sku_code: Optional[str]
    is_tracked: bool
    on_hand_qty: int
