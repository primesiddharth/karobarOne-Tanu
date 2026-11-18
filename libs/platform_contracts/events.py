# ==============================================================================
# File: libs/platform_contracts/events.py
# Purpose: Canonical wire event envelope (Contract Specification §10.1)
# ==============================================================================
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Globally unique immutable event identifier (stable across delivery retries)
    event_id: UUID = Field(default_factory=uuid4)
    # Verbatim event type name from Contract Appendix B (e.g. tenant.activated.v1)
    event_type: str
    # Schema version matching Appendix B
    event_version: int = 1
    # Aggregate root type and identifier
    aggregate_type: str
    aggregate_id: UUID
    # Tenant and store scope (None only for global platform events)
    tenant_id: UUID | None = None
    store_id: UUID | None = None
    # UTC timestamp when business fact committed
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # End-to-end tracing and correlation
    correlation_id: UUID = Field(default_factory=uuid4)
    causation_id: UUID | None = None
    # Stable producing service name
    producer: str
    # Event-specific payload matching canonical schema
    payload: dict[str, Any] = Field(default_factory=dict)
