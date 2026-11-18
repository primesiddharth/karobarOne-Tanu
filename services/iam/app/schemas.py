# app/schemas.py
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, EmailStr


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    mobile_e164: str | None = Field(default=None, max_length=20)


class RegisterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal_id: UUID
    email: str
    status: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=16, max_length=256)


class LogoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = "revoked"


class OtpChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str = Field(pattern="^(EMAIL|SMS)$")
    destination: str = Field(min_length=3, max_length=255)
    purpose: str = Field(pattern="^(ACCOUNT_CLAIM|STEP_UP_AUTH|VERIFICATION)$")


class OtpChallengeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    channel: str
    purpose: str
    expires_at: datetime


class OtpVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    otp_code: str = Field(min_length=4, max_length=10)


class OtpVerifyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: UUID
    verified: bool
    purpose: str


class RoleAssignmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal_id: UUID
    role_code: str = Field(pattern="^(PLATFORM_OWNER|PLATFORM_STAFF|GST_STAFF|STORE_OWNER|STORE_STAFF|GUARDIAN|CUSTOMER|SERVICE)$")
    tenant_id: UUID | None = None
    store_id: UUID | None = None
    valid_until: datetime | None = None


class RoleAssignmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    principal_id: UUID
    role_code: str
    tenant_id: UUID | None = None
    store_id: UUID | None = None
    valid_from: datetime
    valid_until: datetime | None = None


class CurrentPrincipalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal_id: UUID
    email: str | None = None
    mobile_e164: str | None = None
    status: str
    roles: list[str] = Field(default_factory=list)
    tenant_ids: list[UUID] = Field(default_factory=list)
    store_ids: list[UUID] = Field(default_factory=list)
    assignments: list[RoleAssignmentResponse] = Field(default_factory=list)


class JwksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    keys: list[dict]
