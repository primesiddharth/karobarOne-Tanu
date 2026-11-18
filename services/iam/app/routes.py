# app/routes.py
# Thin route layer: parse -> authorize -> call command -> return (RULES.md §3 & §6).
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from libs.platform_contracts.tokens import Principal, verify_token
from libs.platform_contracts.errors import ApiError, ErrorCode
from .config import settings
from .db import get_db_session
from . import domain
from . import models
from . import schemas
from . import commands

router = APIRouter()
security = HTTPBearer(auto_error=False)


async def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session: AsyncSession = Depends(get_db_session),
) -> Principal:
    """Verifies RS256 Bearer JWT and confirms active session state (RULES §8, SDD-004)."""
    if not credentials:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Missing Bearer token", status_code=401)

    principal = verify_token(
        token=credentials.credentials,
        public_key=settings.JWT_PUBLIC_KEY,
        issuer=settings.ISSUER,
        audience=settings.AUDIENCE,
    )

    # SDD-004: Validate session has not been revoked on sensitive routes
    if principal.session_id:
        sess = await session.get(models.Session, principal.session_id)
        if not sess or sess.revoked_at is not None or sess.expires_at < datetime.now(timezone.utc):
            raise ApiError(ErrorCode.UNAUTHENTICATED, "Session has expired or was revoked", status_code=401)

    return principal


async def handle_idempotency(
    session: AsyncSession,
    scope: str,
    key: str | None,
    raw_body: dict,
    execute_coroutine,
    encrypt_response: bool = False,
):
    """Generic idempotency executor per RULES.md §6 & OQ-038."""
    if not key:
        return await execute_coroutine()

    request_hash = domain.hash_token(json.dumps(raw_body, sort_keys=True))
    now = datetime.now(timezone.utc)

    # Check for existing idempotency key
    query = (
        select(models.IdempotencyKey)
        .where(models.IdempotencyKey.scope == scope, models.IdempotencyKey.key == key)
        .with_for_update()
    )
    res = await session.execute(query)
    stored = res.scalars().first()

    if stored:
        if stored.request_hash != request_hash:
            raise ApiError(ErrorCode.IDEMPOTENCY_CONFLICT, "Idempotency key reused with different request payload", status_code=409)

        stored_body = stored.response_body
        if isinstance(stored_body, dict) and "_encrypted" in stored_body:
            decrypted_json = domain.decrypt_idempotency_payload(stored_body["_encrypted"], settings.IDEMPOTENCY_ENCRYPTION_KEY)
            return JSONResponse(status_code=stored.response_code, content=json.loads(decrypted_json))
        return JSONResponse(status_code=stored.response_code, content=stored_body)

    # Execute business command
    result = await execute_coroutine()
    result_data = result if isinstance(result, dict) else (result.model_dump(mode="json") if hasattr(result, "model_dump") else str(result))

    # Encrypt response payload if sensitive (OQ-038)
    if encrypt_response:
        persisted_body = {
            "_encrypted": domain.encrypt_idempotency_payload(json.dumps(result_data), settings.IDEMPOTENCY_ENCRYPTION_KEY)
        }
    else:
        persisted_body = result_data

    idem_row = models.IdempotencyKey(
        id=uuid4(),
        scope=scope,
        key=key,
        request_hash=request_hash,
        response_code=200,
        response_body=persisted_body,
        created_at=now,
        locked_until=now + timedelta(hours=24),
    )
    session.add(idem_row)
    await session.commit()
    return result_data


# ------------------------------------------------------------------------------
# Authentication Routes
# ------------------------------------------------------------------------------

@router.post("/auth/register", response_model=schemas.RegisterResponse, operation_id="registerPrincipal")
async def register(
    req: schemas.RegisterRequest,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Registers a new user principal and credentials; enumeration resistant (OQ-006)."""
    corr_id = UUID(getattr(request.state, "request_id", str(uuid4())))

    async def _action():
        return await commands.register_principal_command(
            session=session,
            email=req.email,
            password=req.password,
            mobile_e164=req.mobile_e164,
            correlation_id=corr_id,
        )

    res = await handle_idempotency(session, "iam:register", idempotency_key, req.model_dump(), _action)
    await session.commit()
    return res


@router.post("/auth/login", response_model=schemas.TokenResponse, operation_id="loginPrincipal")
async def login(
    req: schemas.LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
):
    """Authenticates principal; supports transparent bcrypt verify-then-rehash to Argon2id (IAM-001)."""
    corr_id = UUID(getattr(request.state, "request_id", str(uuid4())))
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    tokens = await commands.login_command(
        session=session,
        email=req.email,
        password=req.password,
        ip_address=client_ip,
        user_agent=user_agent,
        correlation_id=corr_id,
    )
    await session.commit()
    return tokens


@router.post("/auth/refresh", response_model=schemas.TokenResponse, operation_id="refreshSession")
async def refresh_session(
    req: schemas.RefreshRequest,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Rotates refresh token; detecting replay revokes the entire session (IAM-002, SEC-TST-007)."""
    corr_id = UUID(getattr(request.state, "request_id", str(uuid4())))
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    async def _action():
        return await commands.refresh_session_command(
            session=session,
            raw_refresh_token=req.refresh_token,
            ip_address=client_ip,
            user_agent=user_agent,
            correlation_id=corr_id,
        )

    tokens = await handle_idempotency(
        session=session,
        scope="iam:refresh",
        key=idempotency_key,
        raw_body=req.model_dump(),
        execute_coroutine=_action,
        encrypt_response=True,  # OQ-038: encrypt token response in idempotency_keys
    )
    await session.commit()
    return tokens


@router.post("/auth/logout", response_model=schemas.LogoutResponse, operation_id="logoutSession")
async def logout(
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Revokes active authenticated session (IAM-003)."""
    corr_id = UUID(getattr(request.state, "request_id", str(uuid4())))
    res = await commands.logout_command(
        session=session,
        principal_id=principal.sub,
        session_id=principal.session_id,
        correlation_id=corr_id,
    )
    await session.commit()
    return res


# ------------------------------------------------------------------------------
# OTP Challenge Routes (IAM-004, IAM-005)
# ------------------------------------------------------------------------------

@router.post("/auth/otp/challenges", response_model=schemas.OtpChallengeResponse, operation_id="createOtpChallenge")
async def create_otp_challenge(
    req: schemas.OtpChallengeRequest,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Creates hashed OTP challenge; enforces attempt caps and sliding rate limits (IAM-004)."""
    corr_id = UUID(getattr(request.state, "request_id", str(uuid4())))

    async def _action():
        return await commands.create_otp_challenge_command(
            session=session,
            channel=req.channel,
            destination=req.destination,
            purpose=req.purpose,
            correlation_id=corr_id,
        )

    res = await handle_idempotency(session, "iam:otp_challenge", idempotency_key, req.model_dump(), _action)
    await session.commit()
    return res


@router.post("/auth/otp/challenges/{challenge_id}/verify", response_model=schemas.OtpVerifyResponse, operation_id="verifyOtpChallenge")
async def verify_otp_challenge(
    challenge_id: UUID,
    req: schemas.OtpVerifyRequest,
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Verifies OTP challenge; single-use semantics (IAM-005)."""
    corr_id = UUID(getattr(request.state, "request_id", str(uuid4())))

    async def _action():
        return await commands.verify_otp_challenge_command(
            session=session,
            challenge_id=challenge_id,
            otp_code=req.otp_code,
            correlation_id=corr_id,
        )

    res = await handle_idempotency(session, f"iam:otp_verify:{challenge_id}", idempotency_key, req.model_dump(), _action)
    await session.commit()
    return res


# ------------------------------------------------------------------------------
# Principal Identity & Profile Routes (IAM-006)
# ------------------------------------------------------------------------------

@router.get("/me", response_model=schemas.CurrentPrincipalResponse, operation_id="getCurrentPrincipal")
async def get_me(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_db_session),
):
    """Returns authenticated principal profile and active scoped role assignments (IAM-006)."""
    user_record = await session.get(models.Principal, principal.sub)
    if not user_record:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Principal not found", status_code=404)

    now = datetime.now(timezone.utc)
    role_query = (
        select(models.RoleAssignment)
        .where(
            models.RoleAssignment.principal_id == principal.sub,
            models.RoleAssignment.revoked_at.is_(None),
            (models.RoleAssignment.valid_until.is_(None) | (models.RoleAssignment.valid_until > now)),
        )
    )
    role_rows = (await session.execute(role_query)).scalars().all()

    assignments = [
        schemas.RoleAssignmentResponse(
            id=r.id,
            principal_id=r.principal_id,
            role_code=r.role_code,
            tenant_id=r.tenant_id,
            store_id=r.store_id,
            valid_from=r.valid_from,
            valid_until=r.valid_until,
        )
        for r in role_rows
    ]

    return schemas.CurrentPrincipalResponse(
        principal_id=user_record.id,
        email=user_record.email,
        mobile_e164=user_record.mobile_e164,
        status=user_record.status,
        roles=principal.roles,
        tenant_ids=principal.tenant_ids,
        store_ids=principal.store_ids,
        assignments=assignments,
    )


# ------------------------------------------------------------------------------
# Administrative Role Assignment Routes (IAM-007, IAM-008)
# ------------------------------------------------------------------------------

@router.post("/admin/role-assignments", response_model=schemas.RoleAssignmentResponse, operation_id="grantRoleAssignment")
async def grant_role_assignment(
    req: schemas.RoleAssignmentCreateRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Grants scoped role assignment enforcing role check constraints and platform MFA (IAM-007)."""
    corr_id = UUID(getattr(request.state, "request_id", str(uuid4())))

    async def _action():
        assigned = await commands.grant_role_assignment_command(
            session=session,
            current_principal=principal,
            target_principal_id=req.principal_id,
            role_code=req.role_code,
            tenant_id=req.tenant_id,
            store_id=req.store_id,
            valid_until=req.valid_until,
            correlation_id=corr_id,
        )
        return schemas.RoleAssignmentResponse(
            id=assigned.id,
            principal_id=assigned.principal_id,
            role_code=assigned.role_code,
            tenant_id=assigned.tenant_id,
            store_id=assigned.store_id,
            valid_from=assigned.valid_from,
            valid_until=assigned.valid_until,
        )

    res = await handle_idempotency(session, "iam:role_grant", idempotency_key, req.model_dump(), _action)
    await session.commit()
    return res


@router.delete("/admin/role-assignments/{assignment_id}", operation_id="revokeRoleAssignment")
async def revoke_role_assignment(
    assignment_id: UUID,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    """Revokes active role assignment (IAM-008)."""
    corr_id = UUID(getattr(request.state, "request_id", str(uuid4())))

    async def _action():
        return await commands.revoke_role_assignment_command(
            session=session,
            current_principal=principal,
            assignment_id=assignment_id,
            correlation_id=corr_id,
        )

    res = await handle_idempotency(session, f"iam:role_revoke:{assignment_id}", idempotency_key, {"id": str(assignment_id)}, _action)
    await session.commit()
    return res


# ------------------------------------------------------------------------------
# Public JWKS Key Distribution Route
# ------------------------------------------------------------------------------

@router.get("/.well-known/jwks.json", response_model=schemas.JwksResponse, operation_id="getJwks")
async def get_jwks():
    """Exposes current and previous public RSA keys in standard JWKS format (RULES §8)."""
    current_jwk = domain.public_key_pem_to_jwk(settings.JWT_PUBLIC_KEY, settings.JWT_KID)
    keys = [current_jwk]

    if settings.JWT_PREVIOUS_PUBLIC_KEY:
        prev_jwk = domain.public_key_pem_to_jwk(settings.JWT_PREVIOUS_PUBLIC_KEY, f"{settings.JWT_KID}-prev")
        keys.append(prev_jwk)

    return schemas.JwksResponse(keys=keys)
