# app/routes.py
# Thin route layer: parse -> authorize -> call command -> return (RULES.md §3 & §6).
import hashlib
import json
from uuid import UUID, uuid4
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.platform_contracts.tokens import Principal, verify_token
from libs.platform_contracts.errors import ApiError, ErrorCode
from .config import settings
from .db import get_db_session
from . import models
from . import schemas
from . import commands

router = APIRouter()
security = HTTPBearer(auto_error=False)


async def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal:
    """Verifies RS256 Bearer JWT and extracts caller Principal."""
    if not credentials:
        raise ApiError(ErrorCode.UNAUTHENTICATED, "Missing Bearer token", status_code=401)

    return verify_token(
        token=credentials.credentials,
        public_key=settings.JWT_PUBLIC_KEY,
        issuer=settings.ISSUER,
        audience=settings.AUDIENCE,
    )


async def get_service_or_user_principal(
    x_service_key: str | None = Header(None, alias="X-Service-Key"),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal:
    """Authenticates either internal service via X-Service-Key or user Principal via JWT."""
    if x_service_key:
        caller = settings.get_caller_service(x_service_key)
        if not caller:
            raise ApiError(ErrorCode.FORBIDDEN_CALLER, "Invalid or unauthorized service key", status_code=403)
        return Principal(
            sub=uuid4(),
            roles=[f"SERVICE_{caller.upper()}", "SERVICE"],
            tenant_ids=[],
            store_ids=[],
        )

    if credentials:
        return verify_token(
            token=credentials.credentials,
            public_key=settings.JWT_PUBLIC_KEY,
            issuer=settings.ISSUER,
            audience=settings.AUDIENCE,
        )

    raise ApiError(ErrorCode.UNAUTHENTICATED, "Missing Bearer token or Service Key", status_code=401)


async def handle_idempotency(
    session: AsyncSession,
    scope: str,
    key: str | None,
    raw_body: dict,
    execute_coroutine,
):
    """Generic idempotency executor per RULES.md §6."""
    if not key:
        return await execute_coroutine()

    request_hash = hashlib.sha256(json.dumps(raw_body, sort_keys=True).encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    query = (
        select(models.IdempotencyKey)
        .where(models.IdempotencyKey.scope == scope, models.IdempotencyKey.key == key)
        .with_for_update()
    )
    res = await session.execute(query)
    stored = res.scalars().first()

    if stored:
        if stored.request_hash != request_hash:
            raise ApiError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "Idempotency key reused with different request payload",
                status_code=409,
            )
        return JSONResponse(status_code=stored.response_code, content=stored.response_body)

    result = await execute_coroutine()
    result_data = (
        result
        if isinstance(result, dict)
        else (
            result.model_dump(mode="json")
            if hasattr(result, "model_dump")
            else str(result)
        )
    )

    idem_row = models.IdempotencyKey(
        id=uuid4(),
        scope=scope,
        key=key,
        request_hash=request_hash,
        response_code=200,
        response_body=result_data,
        created_at=now,
        locked_until=now + timedelta(minutes=5),
    )
    session.add(idem_row)
    await session.commit()
    return result


@router.get("/status")
@router.get("/domains/status")
async def get_service_status():
    return {"status": "operational", "service": "domain"}


# -----------------------------------------------------------------------------
# DOM-001: POST /stores/{store_id}/subdomain (Assign immutable Free subdomain)
# -----------------------------------------------------------------------------
@router.post(
    "/stores/{store_id}/subdomain",
    response_model=schemas.AssignSubdomainResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assign_subdomain(
    store_id: UUID,
    body: schemas.AssignSubdomainRequest,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        subdomain = await commands.assign_subdomain_command(
            session=session,
            store_id=store_id,
            slug=body.slug,
            principal=principal,
        )
        await session.commit()
        return schemas.AssignSubdomainResponse(
            subdomain_id=subdomain.id,
            store_id=subdomain.store_id,
            label=subdomain.label,
            fqdn=subdomain.fqdn,
            status=subdomain.status,
        )

    return await handle_idempotency(
        session,
        f"DOM-001:{store_id}",
        idempotency_key,
        body.model_dump(mode="json"),
        _action,
    )


# -----------------------------------------------------------------------------
# DOM-002: POST /stores/{store_id}/domains/options
# -----------------------------------------------------------------------------
@router.post(
    "/stores/{store_id}/domains/options",
    response_model=schemas.CheckDomainOptionsResponse,
    status_code=status.HTTP_200_OK,
)
async def check_domain_options(
    store_id: UUID,
    body: schemas.CheckDomainOptionsRequest,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        req, options = await commands.check_domain_options_command(
            session=session,
            store_id=store_id,
            domain_names=body.domain_names,
            principal=principal,
        )
        await session.commit()
        return schemas.CheckDomainOptionsResponse(
            request_id=req.id,
            store_id=req.store_id,
            status=req.status,
            options=options,
        )

    return await handle_idempotency(
        session,
        f"DOM-002:{store_id}",
        idempotency_key,
        body.model_dump(mode="json"),
        _action,
    )


# -----------------------------------------------------------------------------
# DOM-003: POST /domain-requests/{id}/select
# -----------------------------------------------------------------------------
@router.post(
    "/domain-requests/{id}/select",
    response_model=schemas.SelectDomainOptionResponse,
    status_code=status.HTTP_200_OK,
)
async def select_domain_option(
    id: UUID,
    body: schemas.SelectDomainOptionRequest,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    async def _action():
        req = await commands.select_domain_option_command(
            session=session,
            request_id=id,
            selected_domain=body.domain_name,
            principal=principal,
        )
        await session.commit()
        return schemas.SelectDomainOptionResponse(
            request_id=req.id,
            store_id=req.store_id,
            selected_domain=req.selected_domain,
            cost_class=req.cost_class,
            price_paise=req.price_paise,
            status=req.status,
        )

    return await handle_idempotency(
        session,
        f"DOM-003:{id}",
        idempotency_key,
        body.model_dump(mode="json"),
        _action,
    )


# -----------------------------------------------------------------------------
# DOM-004: POST /domain-requests/{id}/purchase
# -----------------------------------------------------------------------------
@router.post(
    "/domain-requests/{id}/purchase",
    response_model=schemas.PurchaseDomainResponse,
    status_code=status.HTTP_201_CREATED,
)
async def purchase_domain(
    id: UUID,
    body: schemas.PurchaseDomainRequest | None = None,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    approval_ref = body.approval_ref if body else None
    payment_ref = body.payment_ref if body else None
    raw_body = body.model_dump(mode="json") if body else {}

    async def _action():
        custom_domain = await commands.purchase_domain_command(
            session=session,
            request_id=id,
            principal=principal,
            approval_ref=approval_ref,
            payment_ref=payment_ref,
        )
        await session.commit()
        return schemas.PurchaseDomainResponse(
            domain_id=custom_domain.id,
            request_id=id,
            store_id=custom_domain.store_id,
            domain_name=custom_domain.domain_name,
            cost_class=custom_domain.cost_class,
            status=custom_domain.status,
            registrar_reference=custom_domain.registrar_reference,
        )

    return await handle_idempotency(
        session,
        f"DOM-004:{id}",
        idempotency_key,
        raw_body,
        _action,
    )


# -----------------------------------------------------------------------------
# DOM-005: GET /stores/{store_id}/domain-status
# -----------------------------------------------------------------------------
@router.get(
    "/stores/{store_id}/domain-status",
    response_model=schemas.DomainStatusResponse,
)
async def get_domain_status(
    store_id: UUID,
    principal: Principal = Depends(get_service_or_user_principal),
    session: AsyncSession = Depends(get_db_session),
):
    status_dict = await commands.get_domain_status_query(
        session=session,
        store_id=store_id,
        principal=principal,
    )
    return schemas.DomainStatusResponse(**status_dict)


# -----------------------------------------------------------------------------
# DOM-006: POST /domain-requests/{id}/verify-dns
# -----------------------------------------------------------------------------
@router.post(
    "/domain-requests/{id}/verify-dns",
    response_model=schemas.VerifyDnsResponse,
    status_code=status.HTTP_200_OK,
)
async def verify_dns(
    id: UUID,
    body: schemas.VerifyDnsRequest | None = None,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    check_type = body.check_type if body else "CNAME"
    raw_body = body.model_dump(mode="json") if body else {}

    async def _action():
        custom_domain, is_verified = await commands.verify_dns_command(
            session=session,
            request_id=id,
            principal=principal,
            check_type=check_type,
        )
        await session.commit()
        return schemas.VerifyDnsResponse(
            domain_id=custom_domain.id,
            domain_name=custom_domain.domain_name,
            status=custom_domain.status,
            is_verified=is_verified,
            details={"check_type": check_type, "expected_target": settings.EXPECTED_CNAME_TARGET},
        )

    return await handle_idempotency(
        session,
        f"DOM-006:{id}",
        idempotency_key,
        raw_body,
        _action,
    )


# -----------------------------------------------------------------------------
# DOM-007: POST /stores/{store_id}/publish (Activate Free or Paid store route)
# -----------------------------------------------------------------------------
@router.post(
    "/stores/{store_id}/publish",
    response_model=schemas.PublishStoreResponse,
)
async def publish_store(
    store_id: UUID,
    body: schemas.PublishStoreRequest | None = None,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    expected_version = body.expected_version if body else None
    raw_body = body.model_dump(mode="json") if body else {}

    async def _action():
        s_id, state, active_host, published_at = await commands.publish_store_command(
            session=session,
            store_id=store_id,
            principal=principal,
            expected_version=expected_version,
        )
        await session.commit()
        return schemas.PublishStoreResponse(
            store_id=s_id,
            publication_state=state,
            active_host=active_host,
            published_at=published_at,
        )

    return await handle_idempotency(
        session,
        f"DOM-007:{store_id}",
        idempotency_key,
        raw_body,
        _action,
    )


# -----------------------------------------------------------------------------
# DOM-008: POST /domains/{id}/transfer-review
# -----------------------------------------------------------------------------
@router.post(
    "/domains/{id}/transfer-review",
    response_model=schemas.TransferReviewResponse,
    status_code=status.HTTP_200_OK,
)
async def open_transfer_review(
    id: UUID,
    body: schemas.TransferReviewRequest | None = None,
    principal: Principal = Depends(get_service_or_user_principal),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db_session),
):
    notes = body.notes if body else None
    raw_body = body.model_dump(mode="json") if body else {}

    async def _action():
        domain_obj = await commands.open_transfer_review_command(
            session=session,
            domain_id=id,
            principal=principal,
            notes=notes,
        )
        await session.commit()
        return schemas.TransferReviewResponse(
            domain_id=domain_obj.id,
            domain_name=domain_obj.domain_name,
            status=domain_obj.status,
            notes=domain_obj.transfer_review_notes,
            opened_at=domain_obj.transfer_review_opened_at,
        )

    return await handle_idempotency(
        session,
        f"DOM-008:{id}",
        idempotency_key,
        raw_body,
        _action,
    )


# -----------------------------------------------------------------------------
# Internal: GET /internal/routes/resolve (Storefront proxy route lookup)
# -----------------------------------------------------------------------------
@router.get(
    "/internal/routes/resolve",
    response_model=schemas.ResolveRouteResponse,
)
async def resolve_route(
    hostname: str = Query(..., min_length=3),
    principal: Principal = Depends(get_service_or_user_principal),
    session: AsyncSession = Depends(get_db_session),
):
    route = await commands.resolve_route_query(session, hostname)
    return schemas.ResolveRouteResponse(
        hostname=route.hostname,
        store_id=route.store_id,
        tenant_id=route.tenant_id,
        route_type=route.route_type,
        status=route.status,
    )
