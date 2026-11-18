# app/schemas.py
# Request and response schemas for Tenant & Store endpoints (RULES.md §6).
# Strict schema validation: extra="forbid".
from datetime import datetime, date
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class RegisterTenantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pan: str = Field(..., description="Indian Income Tax PAN (10 characters: 5 letters, 4 digits, 1 letter)")
    legal_name: str = Field(..., min_length=2, max_length=200)
    tenant_type: str = Field(default="INDIVIDUAL", description="INDIVIDUAL, BUSINESS, or OTHER")
    date_of_birth: date | None = Field(default=None, description="Required for minor check")
    acceptance_refs: list[dict] | None = Field(default=None)


class RegisterTenantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    registration_state: str
    status: str
    pan_masked: str
    legal_name: str


class TenantResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    pan_masked: str
    legal_name: str
    tenant_type: str
    minor_status: str
    status: str
    date_of_birth: date | None = None
    created_at: datetime


class SubmitGuardianRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(..., min_length=2, max_length=200)
    relationship_code: str = Field(..., description="PARENT or LEGAL_GUARDIAN")
    email: str = Field(..., min_length=5, max_length=255)
    mobile_e164: str = Field(..., min_length=10, max_length=20)


class SubmitGuardianResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guardian_id: UUID
    tenant_id: UUID
    verification_status: str
    minor_status: str


class ConsentItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_type: str = Field(default="TERMS")
    document_code: str = Field(default="DOC_STANDARD_TERMS")
    document_version: str = Field(default="v1.0")
    document_hash: str = Field(..., min_length=10, max_length=64)


class RecordGuardianConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consents: list[ConsentItem]
    acceptance_ip: str | None = Field(default=None)


class RecordGuardianConsentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    guardian_id: UUID
    minor_status: str
    status: str


class AdultReverificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acceptance_refs: list[dict] | None = Field(default=None)


class AdultReverificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    minor_status: str
    status: str


class RegisterGstinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gstin: str = Field(..., min_length=15, max_length=15, description="15-character GSTIN")


class GstinResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    gstin_masked: str
    state_code: str
    verification_status: str


class CreateStoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_code: str = Field(..., min_length=3, max_length=32)
    display_name: str = Field(..., min_length=2, max_length=200)
    store_mode: str = Field(default="FREE_PRESENCE", description="FREE_PRESENCE or PAID_COMMERCE")
    gstin_id: UUID | None = Field(default=None, description="Required for PAID_COMMERCE")
    tenant_id: UUID | None = Field(default=None, description="Tenant ID when not present in token claims")


class StoreResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    store_code: str
    display_name: str
    store_mode: str
    lifecycle_status: str
    gstin_id: UUID | None = None
    timezone: str
    currency_code: str
    created_at: datetime


class AssignStaffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: UUID
    role_code: str = Field(default="STORE_STAFF")


class AssignStaffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignment_id: UUID
    store_id: UUID
    principal_id: UUID
    status: str


class BindGstinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_id: UUID
