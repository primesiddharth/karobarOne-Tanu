# app/schemas.py
from datetime import datetime
from uuid import UUID
from typing import Any, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class BaseContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ------------------------------------------------------------------------------
# APR-001: POST /approvals (Create review request)
# ------------------------------------------------------------------------------

class CreateApprovalRequest(BaseContractModel):
    tenant_id: UUID
    store_id: UUID
    subject_type: str = Field(..., max_length=40)
    subject_id: UUID
    subject_version: Optional[str] = Field(None, max_length=64)
    priority: int = Field(0, ge=0, le=10)
    submitted_by: UUID


class ApprovalResponse(BaseContractModel):
    approval_id: UUID
    tenant_id: UUID
    store_id: UUID
    subject_type: str
    subject_id: UUID
    subject_version: Optional[str] = None
    status: str
    priority: int
    submitted_by: UUID
    submitted_at: datetime


# ------------------------------------------------------------------------------
# APR-002: GET /approvals/queue (Review queue)
# ------------------------------------------------------------------------------

class ApprovalQueueItem(BaseContractModel):
    approval_id: UUID
    tenant_id: UUID
    store_id: UUID
    subject_type: str
    subject_id: UUID
    subject_version: Optional[str] = None
    status: str
    priority: int
    submitted_by: UUID
    submitted_at: datetime


class ApprovalQueueResponse(BaseContractModel):
    items: List[ApprovalQueueItem]
    total: int


# ------------------------------------------------------------------------------
# APR-003: GET /approvals/{id} (Review detail)
# ------------------------------------------------------------------------------

class DecisionDetail(BaseContractModel):
    id: UUID
    decision: str
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    decided_by: UUID
    decided_at: datetime
    evidence_json: dict[str, Any] = Field(default_factory=dict)


class TakedownDetail(BaseContractModel):
    id: UUID
    subject_type: str
    subject_id: UUID
    reason_code: str
    reason_text: str
    executed_by: UUID
    executed_at: datetime


class ApprovalDetailResponse(BaseContractModel):
    approval_id: UUID
    tenant_id: UUID
    store_id: UUID
    subject_type: str
    subject_id: UUID
    subject_version: Optional[str] = None
    status: str
    priority: int
    submitted_by: UUID
    submitted_at: datetime
    decisions: List[DecisionDetail] = Field(default_factory=list)
    takedowns: List[TakedownDetail] = Field(default_factory=list)


# ------------------------------------------------------------------------------
# APR-004: POST /approvals/{id}/approve (Approve immutable version)
# ------------------------------------------------------------------------------

class ApproveRequest(BaseContractModel):
    expected_version: Optional[str] = None
    comment: Optional[str] = None


class ApproveResponse(BaseContractModel):
    approval_id: UUID
    state: str = "APPROVED"
    content_version_id: Optional[str] = None
    decided_at: datetime


# ------------------------------------------------------------------------------
# APR-005: POST /approvals/{id}/reject (Reject with reason)
# ------------------------------------------------------------------------------

class RejectRequest(BaseContractModel):
    reason_code: Optional[str] = None
    reason_text: str = Field(..., min_length=1)


class RejectResponse(BaseContractModel):
    approval_id: UUID
    state: str = "REJECTED"
    reason_code: Optional[str] = None
    reason_text: str
    decided_at: datetime


# ------------------------------------------------------------------------------
# APR-006: POST /approvals/{id}/emergency-takedown (Immediate takedown)
# ------------------------------------------------------------------------------

class EmergencyTakedownRequest(BaseContractModel):
    reason_code: str = Field(..., max_length=40)
    reason_text: str = Field(..., min_length=1)


class EmergencyTakedownResponse(BaseContractModel):
    takedown_id: UUID
    approval_id: UUID
    state: str = "TAKEDOWN"
    reason_code: str
    executed_at: datetime
