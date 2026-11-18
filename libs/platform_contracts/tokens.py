# ==============================================================================
# File: libs/platform_contracts/tokens.py
# Purpose: Asymmetric JWT verification and Principal claims extraction (RULES §8, Security §6)
# ==============================================================================
from typing import Any
from uuid import UUID
import jwt
from pydantic import BaseModel, ConfigDict, Field
from .errors import ApiError, ErrorCode

ALLOWED_ALGORITHMS = ["RS256", "EdDSA"]


class Principal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Principal identifier (user or service UUID)
    sub: UUID
    # Session identifier (None for machine service tokens)
    session_id: UUID | None = None
    # Authorization hints per RULES §8
    roles: list[str] = Field(default_factory=list)
    tenant_ids: list[UUID] = Field(default_factory=list)
    store_ids: list[UUID] = Field(default_factory=list)
    iat: int | None = None
    exp: int | None = None
    iss: str | None = None
    aud: str | None = None
    kid: str | None = None

    @property
    def id(self) -> UUID:
        """Alias returning sub as id."""
        return self.sub

    def has_role(self, role: str) -> bool:
        """Checks if principal has the requested role."""
        return role in self.roles

    def has_tenant(self, tenant_id: UUID) -> bool:
        """Checks if principal is authorized for the given tenant ID."""
        return tenant_id in self.tenant_ids


def verify_token(
    token: str,
    public_key: str,
    issuer: str = "karobarone-iam",
    audience: str = "karobarone-api",
) -> Principal:
    """Verifies an asymmetric JWT enforcing RS256/EdDSA and extracts the Principal."""
    try:
        # Enforce allow-listed asymmetric algorithms before signature verification
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg")
        if not alg or alg not in ALLOWED_ALGORITHMS:
            raise ApiError(ErrorCode.UNAUTHENTICATED, "Invalid token", status_code=401)

        payload = jwt.decode(
            token,
            public_key,
            algorithms=ALLOWED_ALGORITHMS,
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )

        session_id_val = payload.get("session_id")
        return Principal(
            sub=UUID(str(payload["sub"])),
            session_id=UUID(str(session_id_val)) if session_id_val else None,
            roles=list(payload.get("roles", [])),
            tenant_ids=[UUID(str(t)) for t in payload.get("tenant_ids", [])],
            store_ids=[UUID(str(s)) for s in payload.get("store_ids", [])],
            iat=payload.get("iat"),
            exp=payload.get("exp"),
            iss=payload.get("iss"),
            aud=payload.get("aud"),
            kid=unverified_header.get("kid"),
        )
    except ApiError:
        raise
    except jwt.ExpiredSignatureError as e:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Token has expired", status_code=401) from e
    except (jwt.InvalidTokenError, ValueError, KeyError) as e:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Invalid token", status_code=401) from e
