# app/schemas.py
from datetime import datetime
from uuid import UUID
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


class BaseContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------------
# DOM-001: POST /stores/{store_id}/subdomain
# ------------------------------------------------------------------------------

class AssignSubdomainRequest(BaseContractModel):
    slug: str = Field(..., min_length=3, max_length=63)


class AssignSubdomainResponse(BaseContractModel):
    subdomain_id: UUID
    store_id: UUID
    label: str
    fqdn: str
    status: str = "ASSIGNED"


# ------------------------------------------------------------------------------
# DOM-002: POST /stores/{store_id}/domains/options
# ------------------------------------------------------------------------------

class CheckDomainOptionsRequest(BaseContractModel):
    domain_names: List[str] = Field(..., min_length=1, max_length=10)


class DomainOptionDto(BaseContractModel):
    domain_name: str
    is_available: bool
    cost_class: str
    price_paise: int


class CheckDomainOptionsResponse(BaseContractModel):
    request_id: UUID
    store_id: UUID
    status: str
    options: List[DomainOptionDto]


# ------------------------------------------------------------------------------
# DOM-003: POST /domain-requests/{id}/select
# ------------------------------------------------------------------------------

class SelectDomainOptionRequest(BaseContractModel):
    domain_name: str


class SelectDomainOptionResponse(BaseContractModel):
    request_id: UUID
    store_id: UUID
    selected_domain: str
    cost_class: str
    price_paise: int
    status: str


# ------------------------------------------------------------------------------
# DOM-004: POST /domain-requests/{id}/purchase
# ------------------------------------------------------------------------------

class PurchaseDomainRequest(BaseContractModel):
    approval_ref: Optional[str] = None
    payment_ref: Optional[str] = None


class PurchaseDomainResponse(BaseContractModel):
    domain_id: UUID
    request_id: UUID
    store_id: UUID
    domain_name: str
    cost_class: str
    status: str
    registrar_reference: str


# ------------------------------------------------------------------------------
# DOM-005: GET /stores/{store_id}/domain-status
# ------------------------------------------------------------------------------

class SubdomainDetail(BaseContractModel):
    id: UUID
    label: str
    fqdn: str
    status: str
    activated_at: Optional[datetime] = None


class CustomDomainDetail(BaseContractModel):
    id: UUID
    domain_name: str
    status: str
    cost_class: Optional[str] = None
    registrar_reference: Optional[str] = None


class DomainStatusResponse(BaseContractModel):
    store_id: UUID
    free_subdomain: Optional[SubdomainDetail] = None
    custom_domain: Optional[CustomDomainDetail] = None
    publication_status: str
    active_host: Optional[str] = None


# ------------------------------------------------------------------------------
# DOM-006: POST /domain-requests/{id}/verify-dns
# ------------------------------------------------------------------------------

class VerifyDnsRequest(BaseContractModel):
    check_type: str = "CNAME"


class VerifyDnsResponse(BaseContractModel):
    domain_id: UUID
    domain_name: str
    status: str
    is_verified: bool
    details: Dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------------------
# DOM-007: POST /stores/{store_id}/publish
# ------------------------------------------------------------------------------

class PublishStoreRequest(BaseContractModel):
    expected_version: Optional[int] = None


class PublishStoreResponse(BaseContractModel):
    store_id: UUID
    publication_state: str = "PUBLIC_LIVE"
    active_host: str
    published_at: datetime


# ------------------------------------------------------------------------------
# DOM-008: POST /domains/{id}/transfer-review
# ------------------------------------------------------------------------------

class TransferReviewRequest(BaseContractModel):
    notes: Optional[str] = None


class TransferReviewResponse(BaseContractModel):
    domain_id: UUID
    domain_name: str
    status: str = "TRANSFER_REVIEW"
    notes: Optional[str] = None
    opened_at: datetime


# ------------------------------------------------------------------------------
# Internal Route Resolution
# ------------------------------------------------------------------------------

class ResolveRouteResponse(BaseContractModel):
    hostname: str
    store_id: UUID
    tenant_id: UUID
    route_type: str
    status: str
