# app/schemas.py
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


# ------------------------------------------------------------------------------
# SUB-001: Plans & Entitlements
# ------------------------------------------------------------------------------

class PlanEntitlementDto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entitlement_code: str
    hard_limit: int | None = None
    technical_limit: int | None = None
    value: dict[str, Any] = Field(default_factory=dict)


class PlanDto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_code: str
    version_no: int
    price_amount: str
    price_paise: int
    period_days: int
    commission_rate: float
    entitlements: list[PlanEntitlementDto] = Field(default_factory=list)


class PlansListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plans: list[PlanDto]


# ------------------------------------------------------------------------------
# SUB-002: First Paid Activation Quote
# ------------------------------------------------------------------------------

class ActivationQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_code: str = Field(min_length=2, max_length=24)
    gstin_id: UUID


class AmountComponentDto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: str
    amount_paise: int


class SetupFeeComponentDto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: str
    amount_paise: int
    is_complimentary: bool


class GstComponentDto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate: float
    amount: str
    amount_paise: int


class TotalComponentDto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: str
    amount_paise: int
    amount_ex_tax_paise: int


class ActivationQuoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: UUID
    plan_code: str
    period_1: AmountComponentDto
    third_period_advance: AmountComponentDto
    setup_fee: SetupFeeComponentDto
    gst: GstComponentDto
    total: TotalComponentDto
    expires_at: datetime


# ------------------------------------------------------------------------------
# SUB-003: Activate Subscription
# ------------------------------------------------------------------------------

class ActivateSubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_code: str = Field(min_length=2, max_length=24)
    quote_id: UUID | None = None
    gstin_id: UUID | None = None
    payment_reference: str | None = None


class ActivateSubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_id: UUID
    store_id: UUID
    plan_code: str
    state: str
    current_period_no: int
    starts_at: datetime
    ends_at: datetime
    total_paid: str


# ------------------------------------------------------------------------------
# SUB-004: Store Entitlements Projection
# ------------------------------------------------------------------------------

class EntitlementsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_id: UUID
    plan_code: str
    state: str
    commerce_enabled: bool
    showcase_limit: int | None = None
    max_images_per_item: int
    max_videos_per_item: int
    custom_domain_allowed: bool
    blog_allowed: bool
    effective_from: datetime


# ------------------------------------------------------------------------------
# SUB-005: Subscription Detail
# ------------------------------------------------------------------------------

class SubscriptionPeriodDto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period_no: int
    starts_at: datetime
    ends_at: datetime
    entitlement_status: str
    charge_mode: str
    amount_due: str


class SubscriptionDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_id: UUID
    store_id: UUID
    tenant_id: UUID
    plan_code: str
    state: str
    activation_sequence: int
    first_paid_activated_at: datetime | None = None
    current_period_no: int | None = None
    current_period: SubscriptionPeriodDto | None = None
    advance_balance: str
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------------------
# SUB-006: Cancellation Notice
# ------------------------------------------------------------------------------

class CancelSubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = None
    expected_version: int = Field(..., ge=0)


class CancelSubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_id: UUID
    notice_recorded_at: datetime
    paid_through_period: int
    additional_period_3_due: str
    end_after_period: int


# ------------------------------------------------------------------------------
# SUB-007: Upgrade Quote
# ------------------------------------------------------------------------------

class UpgradeQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_plan_code: Literal["COMMERCE", "GROWTH", "SCALE_AI"]
    effective: Literal["IMMEDIATE"] = "IMMEDIATE"


class UpgradeQuoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: UUID
    lower_price: str
    higher_price: str
    days_remaining: int
    prorated_difference: str
    advance_top_up: str
    gross_upgrade_setup_fee: str
    approved_discount: str
    net_setup_fee: str
    total_before_gst: str
    total_with_tax: str


# ------------------------------------------------------------------------------
# SUB-008: Apply Upgrade
# ------------------------------------------------------------------------------

class ApplyUpgradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: UUID


class ApplyUpgradeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_id: UUID
    plan_code: str
    state: str
    effective_at: datetime


# ------------------------------------------------------------------------------
# SUB-009: Downgrade Request
# ------------------------------------------------------------------------------

class DowngradeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_plan_code: str
    reason: str | None = None


class DowngradeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    subscription_id: UUID
    from_plan: str
    to_plan: str
    status: str
    effective_at: datetime | None = None


# ------------------------------------------------------------------------------
# SUB-010: Reactivate Subscription
# ------------------------------------------------------------------------------

class ReactivateSubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_plan_code: str
    gstin_id: UUID | None = None


class ReactivateSubscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_id: UUID
    plan_code: str
    state: str
    period_fee: str
    reactivation_setup_fee: str
    total: str
    starts_at: datetime
    ends_at: datetime


# ------------------------------------------------------------------------------
# SUB-011: Upgrade Discount Decision
# ------------------------------------------------------------------------------

class DiscountDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    approved_amount: str = "0.00"
    reason: str


class DiscountDecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quote_id: UUID
    requested_discount: str
    approved_amount: str
    net_setup_fee: str
    total_with_tax: str
    decided_at: datetime


# ------------------------------------------------------------------------------
# Dev Stub: Platform Payment
# ------------------------------------------------------------------------------

class DevPlatformPaymentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_id: UUID
    subscription_id: UUID
    charge_id: UUID | None = None
    amount_paise: int
    payment_reference: str = Field(min_length=1, max_length=128)

