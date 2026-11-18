# app/schemas.py
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


# ------------------------------------------------------------------------------
# CUS-001: Guest Customer
# ------------------------------------------------------------------------------

class GuestCustomerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=255)
    mobile: str = Field(min_length=10, max_length=20)
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)


class CustomerResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    tenant_id: UUID
    store_id: UUID
    email: str
    mobile_e164: str
    status: str
    iam_principal_id: UUID | None = None
    first_name: str | None = None
    last_name: str | None = None
    claimed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ------------------------------------------------------------------------------
# CUS-002: Claim Challenge
# ------------------------------------------------------------------------------

class ClaimChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str = Field(default="EMAIL", pattern="^(EMAIL|SMS)$")


class ClaimChallengeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    customer_id: UUID
    channel: str
    status: str


# ------------------------------------------------------------------------------
# CUS-003: Claim Verify
# ------------------------------------------------------------------------------

class ClaimVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    otp_code: str = Field(min_length=4, max_length=10)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class ClaimVerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: UUID
    status: str
    iam_principal_id: UUID
    claimed_at: datetime


# ------------------------------------------------------------------------------
# CUS-005: Profile Update
# ------------------------------------------------------------------------------

class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)


# ------------------------------------------------------------------------------
# CUS-006: Addresses
# ------------------------------------------------------------------------------

class CreateAddressRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address_type: str = Field(pattern="^(SHIPPING|BILLING|BOTH)$")
    recipient_name: str = Field(min_length=1, max_length=200)
    line1: str = Field(min_length=1, max_length=240)
    line2: str | None = Field(default=None, max_length=240)
    city: str = Field(min_length=1, max_length=120)
    state_code: str = Field(min_length=2, max_length=16)
    postal_code: str = Field(min_length=4, max_length=12)
    country_code: str = Field(default="IN", max_length=2)
    is_default: bool = False


class AddressResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    customer_id: UUID
    address_type: str
    recipient_name: str
    line1: str
    line2: str | None = None
    city: str
    state_code: str
    postal_code: str
    country_code: str
    is_default: bool
    created_at: datetime


# ------------------------------------------------------------------------------
# CUS-007: Privacy Requests
# ------------------------------------------------------------------------------

class PrivacyRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_type: str = Field(pattern="^(ACCESS|CORRECT|DELETE|WITHDRAW_CONSENT)$")


class PrivacyRequestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    customer_id: UUID
    request_type: str
    status: str
    requested_at: datetime
    completed_at: datetime | None = None
    retention_basis: str | None = None
