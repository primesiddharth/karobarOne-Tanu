# app/commands.py
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from uuid import UUID, uuid4
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from libs.platform_contracts.errors import ApiError, ErrorCode
from libs.platform_contracts.tokens import Principal
from . import models, domain, schemas
from .config import settings
from .events import add_event
from .clients import (
    mock_registrar_adapter,
    mock_dns_adapter,
    tenant_client,
    subscription_client,
    catalog_client,
)


def check_store_authorization(principal: Principal, store_id: UUID) -> None:
    is_authorized = (
        any(r in ("PLATFORM_STAFF", "PLATFORM_OWNER", "SERVICE") or r.startswith("SERVICE_") for r in principal.roles)
        or (store_id in principal.store_ids)
    )
    if not is_authorized:
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Store access denied", status_code=403)


# ------------------------------------------------------------------------------
# DOM-001: Assign immutable Free subdomain (AC-084)
# ------------------------------------------------------------------------------

async def assign_subdomain_command(
    session: AsyncSession,
    store_id: UUID,
    slug: str,
    principal: Principal,
) -> models.Subdomain:
    check_store_authorization(principal, store_id)
    tenant_id = principal.tenant_ids[0] if principal.tenant_ids else uuid4()

    # 1. Format and reserved names validation
    clean_label = domain.sanitize_subdomain_label(slug)
    fqdn = domain.build_fqdn(clean_label, settings.ROOT_DOMAIN)

    # 2. Check store immutability rule (AC-084: immutable once created)
    store_sub_stmt = select(models.Subdomain).where(models.Subdomain.store_id == store_id)
    store_sub_res = await session.execute(store_sub_stmt)
    existing_store_sub = store_sub_res.scalars().first()
    if existing_store_sub:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message="Free subdomain is immutable once assigned and cannot be renamed",
            status_code=409,
        )

    # 3. Check uniqueness across platform (AC-084)
    dup_stmt = select(models.Subdomain).where(models.Subdomain.label == clean_label)
    dup_res = await session.execute(dup_stmt)
    if dup_res.scalars().first():
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message=f"Subdomain '{clean_label}' is already assigned to another store",
            status_code=409,
        )

    now = datetime.now(timezone.utc)
    subdomain = models.Subdomain(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        label=clean_label,
        fqdn=fqdn,
        status="ASSIGNED",
        created_at=now,
        updated_at=now,
    )
    session.add(subdomain)

    # Create associated PublicationRoute
    route = models.PublicationRoute(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        route_type="FREE_SUBDOMAIN",
        hostname=fqdn,
        target_revision_id=None,
        status="DISABLED",
        created_at=now,
        updated_at=now,
    )
    session.add(route)

    await add_event(
        session=session,
        event_type="domain.subdomain-assigned.v1",
        aggregate_type="subdomain",
        aggregate_id=subdomain.id,
        tenant_id=tenant_id,
        store_id=store_id,
        topic="domain.lifecycle",
        payload={
            "subdomain_id": str(subdomain.id),
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
            "label": clean_label,
            "fqdn": fqdn,
            "assigned_at": now.isoformat(),
        },
    )

    await session.flush()
    return subdomain


# ------------------------------------------------------------------------------
# DOM-002: Check domain options (AC-085, AC-086)
# ------------------------------------------------------------------------------

async def check_domain_options_command(
    session: AsyncSession,
    store_id: UUID,
    domain_names: List[str],
    principal: Principal,
) -> Tuple[models.DomainRequest, List[schemas.DomainOptionDto]]:
    check_store_authorization(principal, store_id)
    tenant_id = principal.tenant_ids[0] if principal.tenant_ids else uuid4()

    options = mock_registrar_adapter.check_availability(domain_names)

    now = datetime.now(timezone.utc)
    request = models.DomainRequest(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        preferred_domains=[d.lower().strip() for d in domain_names],
        status="AVAILABILITY_CHECKED",
        version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(request)

    await add_event(
        session=session,
        event_type="domain.options-checked.v1",
        aggregate_type="domain_request",
        aggregate_id=request.id,
        tenant_id=tenant_id,
        store_id=store_id,
        topic="domain.lifecycle",
        payload={
            "request_id": str(request.id),
            "store_id": str(store_id),
            "options": [opt.model_dump() for opt in options],
            "checked_at": now.isoformat(),
        },
    )

    await session.flush()
    return request, options


# ------------------------------------------------------------------------------
# DOM-003: Select domain option
# ------------------------------------------------------------------------------

async def select_domain_option_command(
    session: AsyncSession,
    request_id: UUID,
    selected_domain: str,
    principal: Principal,
) -> models.DomainRequest:
    stmt = select(models.DomainRequest).where(models.DomainRequest.id == request_id)
    res = await session.execute(stmt)
    req = res.scalars().first()
    if not req:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Domain request {request_id} not found", status_code=404)

    check_store_authorization(principal, req.store_id)

    if req.status not in ("AVAILABILITY_CHECKED", "PREFERENCE_SUBMITTED"):
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Cannot select domain in state '{req.status}'",
            status_code=409,
        )

    clean_domain = selected_domain.lower().strip()
    options = mock_registrar_adapter.check_availability([clean_domain])
    matched_option = next((opt for opt in options if opt.domain_name == clean_domain), None)
    if not matched_option or not matched_option.is_available:
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Domain '{clean_domain}' is not available for registration",
            status_code=409,
        )

    now = datetime.now(timezone.utc)
    req.selected_domain = clean_domain
    req.cost_class = matched_option.cost_class
    req.price_paise = matched_option.price_paise
    req.status = "SELECTED"
    req.version += 1
    req.updated_at = now

    await add_event(
        session=session,
        event_type="domain.selected.v1",
        aggregate_type="domain_request",
        aggregate_id=req.id,
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        topic="domain.lifecycle",
        payload={
            "request_id": str(req.id),
            "store_id": str(req.store_id),
            "domain_name": clean_domain,
            "cost_class": req.cost_class,
            "price_paise": req.price_paise,
            "selected_at": now.isoformat(),
        },
    )

    await session.flush()
    return req


# ------------------------------------------------------------------------------
# DOM-004: Purchase domain (AC-086, AC-087)
# ------------------------------------------------------------------------------

async def purchase_domain_command(
    session: AsyncSession,
    request_id: UUID,
    principal: Principal,
    approval_ref: Optional[str] = None,
    payment_ref: Optional[str] = None,
) -> models.CustomDomain:
    stmt = select(models.DomainRequest).where(models.DomainRequest.id == request_id)
    res = await session.execute(stmt)
    req = res.scalars().first()
    if not req:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Domain request {request_id} not found", status_code=404)

    check_store_authorization(principal, req.store_id)

    # Return existing custom domain idempotently if already purchased
    if req.status in ("PURCHASED", "DNS_PENDING", "DNS_VERIFIED", "ACTIVE"):
        cd_stmt = select(models.CustomDomain).where(models.CustomDomain.domain_request_id == req.id)
        cd_res = await session.execute(cd_stmt)
        existing_cd = cd_res.scalars().first()
        if existing_cd:
            return existing_cd

    if req.status != "SELECTED" or not req.selected_domain:
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Cannot purchase domain from state '{req.status}'. Must be SELECTED.",
            status_code=409,
        )

    # AC-086 / AC-087: Premium requires upgrade approval and payment ref; Standard is included
    if req.cost_class == "PREMIUM":
        if not approval_ref:
            raise ApiError(
                ErrorCode.UPGRADE_APPROVAL_REQUIRED,
                "Upgrade approval required for premium domain purchase",
                status_code=409,
            )
        if not payment_ref:
            raise ApiError(
                ErrorCode.PAYMENT_NOT_CONFIRMED,
                "Confirmed payment reference required for premium domain purchase",
                status_code=409,
            )

    # Check unique constraint across platform
    existing_domain_stmt = select(models.CustomDomain).where(models.CustomDomain.domain_name == req.selected_domain)
    existing_domain_res = await session.execute(existing_domain_stmt)
    if existing_domain_res.scalars().first():
        raise ApiError(
            ErrorCode.INVALID_STATE_TRANSITION,
            f"Domain '{req.selected_domain}' is already registered",
            status_code=409,
        )

    request_ref = f"REQ-{req.id}"
    try:
        reg_result = mock_registrar_adapter.purchase_domain(req.selected_domain, request_ref)
    except httpx.ConnectTimeout:
        # Timeout-then-lookup recovery pattern
        reg_result = mock_registrar_adapter.lookup_purchase(request_ref)
        if not reg_result:
            raise ApiError(
                ErrorCode.DEPENDENCY_UNAVAILABLE,
                "Registrar timed out and purchase lookup failed",
                status_code=503,
            )

    now = datetime.now(timezone.utc)
    custom_domain = models.CustomDomain(
        id=uuid4(),
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        domain_name=req.selected_domain,
        domain_request_id=req.id,
        registrar_code="MOCK_REGISTRAR",
        registrar_reference=reg_result["registrar_reference"],
        cost_class=req.cost_class,
        purchase_cost=req.price_paise,
        approval_ref=approval_ref,
        payment_ref=payment_ref,
        status="PURCHASED",
        registered_at=now,
        expires_at=now + timedelta(days=365),
        created_at=now,
        updated_at=now,
    )
    session.add(custom_domain)

    req.status = "PURCHASED"
    req.approval_ref = approval_ref
    req.payment_ref = payment_ref
    req.version += 1
    req.updated_at = now

    await add_event(
        session=session,
        event_type="domain.purchased.v1",
        aggregate_type="domain",
        aggregate_id=custom_domain.id,
        tenant_id=req.tenant_id,
        store_id=req.store_id,
        topic="domain.lifecycle",
        payload={
            "domain_id": str(custom_domain.id),
            "request_id": str(req.id),
            "store_id": str(req.store_id),
            "domain_name": custom_domain.domain_name,
            "cost_class": custom_domain.cost_class,
            "registrar_reference": custom_domain.registrar_reference,
            "purchased_at": now.isoformat(),
        },
    )

    await session.flush()
    return custom_domain


# ------------------------------------------------------------------------------
# DOM-005: Read domain / publication status
# ------------------------------------------------------------------------------

async def get_domain_status_query(
    session: AsyncSession,
    store_id: UUID,
    principal: Principal | None = None,
) -> dict:
    if principal is not None:
        check_store_authorization(principal, store_id)

    sub_stmt = select(models.Subdomain).where(models.Subdomain.store_id == store_id)
    sub_res = await session.execute(sub_stmt)
    sub = sub_res.scalars().first()

    custom_stmt = select(models.CustomDomain).where(models.CustomDomain.store_id == store_id)
    custom_res = await session.execute(custom_stmt)
    custom = custom_res.scalars().first()

    route_stmt = select(models.PublicationRoute).where(
        models.PublicationRoute.store_id == store_id,
        models.PublicationRoute.status == "ACTIVE",
    )
    route_res = await session.execute(route_stmt)
    route = route_res.scalars().first()

    pub_status = "PUBLIC_LIVE" if route else "DISABLED"
    active_host = route.hostname if route else None

    free_sub_dict = None
    if sub:
        free_sub_dict = {
            "id": sub.id,
            "label": sub.label,
            "fqdn": sub.fqdn,
            "status": sub.status,
            "activated_at": sub.activated_at,
        }

    custom_dict = None
    if custom:
        custom_dict = {
            "id": custom.id,
            "domain_name": custom.domain_name,
            "status": custom.status,
            "cost_class": custom.cost_class,
            "registrar_reference": custom.registrar_reference,
        }

    return {
        "store_id": store_id,
        "free_subdomain": free_sub_dict,
        "custom_domain": custom_dict,
        "publication_status": pub_status,
        "active_host": active_host,
    }


# ------------------------------------------------------------------------------
# DOM-006: Verify DNS configuration
# ------------------------------------------------------------------------------

async def verify_dns_command(
    session: AsyncSession,
    request_id: UUID,
    principal: Principal,
    check_type: str = "CNAME",
) -> Tuple[models.CustomDomain, bool]:
    stmt = select(models.DomainRequest).where(models.DomainRequest.id == request_id)
    res = await session.execute(stmt)
    req = res.scalars().first()
    if not req:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Domain request {request_id} not found", status_code=404)

    check_store_authorization(principal, req.store_id)

    cd_stmt = select(models.CustomDomain).where(models.CustomDomain.domain_request_id == req.id)
    cd_res = await session.execute(cd_stmt)
    custom_domain = cd_res.scalars().first()
    if not custom_domain:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Domain not purchased yet", status_code=409)

    now = datetime.now(timezone.utc)
    is_verified = mock_dns_adapter.verify_records(custom_domain.domain_name, settings.EXPECTED_CNAME_TARGET)

    dns_check = models.DnsCheck(
        id=uuid4(),
        domain_id=custom_domain.id,
        domain_request_id=req.id,
        store_id=req.store_id,
        check_type=check_type,
        expected_value=settings.EXPECTED_CNAME_TARGET,
        observed_value=settings.EXPECTED_CNAME_TARGET if is_verified else "UNCONFIGURED",
        result="VERIFIED" if is_verified else "FAILED",
        checked_at=now,
    )
    session.add(dns_check)

    if is_verified:
        custom_domain.status = "DNS_VERIFIED"
        custom_domain.updated_at = now
        req.status = "DNS_VERIFIED"
        req.updated_at = now

        await add_event(
            session=session,
            event_type="domain.dns-verified.v1",
            aggregate_type="domain",
            aggregate_id=custom_domain.id,
            tenant_id=custom_domain.tenant_id,
            store_id=custom_domain.store_id,
            topic="domain.lifecycle",
            payload={
                "domain_id": str(custom_domain.id),
                "request_id": str(req.id),
                "store_id": str(custom_domain.store_id),
                "domain_name": custom_domain.domain_name,
                "check_type": check_type,
                "verified_at": now.isoformat(),
            },
        )
    await session.flush()
    return custom_domain, is_verified


# ------------------------------------------------------------------------------
# DOM-007: Publish store (Free and Paid gates)
# ------------------------------------------------------------------------------

async def publish_store_command(
    session: AsyncSession,
    store_id: UUID,
    principal: Principal,
    expected_version: int | None = None,
) -> tuple[UUID, str, str, datetime]:
    check_store_authorization(principal, store_id)

    # Gate 1: Check store compliance via Tenant service (fail-closed)
    store_compliance = await tenant_client.get_store_compliance(store_id)
    lifecycle_status = store_compliance.get("lifecycle_status", "ACTIVE")
    if lifecycle_status in ("SUSPENDED", "FROZEN", "RESTRICTED"):
        raise ApiError(
            ErrorCode.COMMERCE_SUSPENDED,
            f"Store commerce is suspended (status: {lifecycle_status})",
            status_code=403,
        )

    store_mode = store_compliance.get("store_mode", "FREE_PRESENCE")
    now = datetime.now(timezone.utc)

    if store_mode == "FREE_PRESENCE":
        # Free presence store publish path
        sub_stmt = select(models.Subdomain).where(models.Subdomain.store_id == store_id)
        sub_res = await session.execute(sub_stmt)
        subdomain = sub_res.scalars().first()
        if not subdomain:
            raise ApiError(
                code=ErrorCode.INVALID_STATE_TRANSITION,
                message="Cannot publish store without an assigned subdomain",
                status_code=409,
            )

        route_stmt = select(models.PublicationRoute).where(
            models.PublicationRoute.store_id == store_id,
            models.PublicationRoute.route_type == "FREE_SUBDOMAIN",
        )
        route_res = await session.execute(route_stmt)
        route = route_res.scalars().first()
        if not route:
            raise ApiError(
                code=ErrorCode.INVALID_STATE_TRANSITION,
                message="Publication route missing for store",
                status_code=409,
            )

        route.status = "ACTIVE"
        route.activated_at = now
        route.updated_at = now

        subdomain.status = "ACTIVE"
        subdomain.activated_at = now
        subdomain.updated_at = now

        await add_event(
            session=session,
            event_type="store.published.v1",
            aggregate_type="publication_route",
            aggregate_id=route.id,
            tenant_id=route.tenant_id,
            store_id=store_id,
            topic="domain.lifecycle",
            payload={
                "store_id": str(store_id),
                "publication_state": "PUBLIC_LIVE",
                "active_host": route.hostname,
                "published_at": now.isoformat(),
            },
        )
        await session.flush()
        return store_id, "PUBLIC_LIVE", route.hostname, now

    else:
        # Paid store publish path (AC-084..088, RULES §5.3, DOM-007)
        # Gate 2a: Active paid subscription check
        sub_status = await subscription_client.get_store_subscription_status(store_id)
        sub_state = sub_status.get("state")
        is_active = sub_status.get("is_active", False)
        if sub_state not in ("ACTIVE", "GRACE_PERIOD") and not is_active:
            raise ApiError(
                ErrorCode.SUBSCRIPTION_EXPIRED,
                "Store requires an active paid subscription to publish",
                status_code=403,
            )
        if sub_status.get("plan_id") == "FREE_PLAN" or sub_status.get("allow_publishing") is False:
            raise ApiError(
                ErrorCode.ENTITLEMENT_REQUIRED,
                "Active subscription does not entitle public store publishing",
                status_code=403,
            )

        # Gate 2b: Verified GSTIN check (422 GSTIN_REQUIRED)
        has_gstin = bool(store_compliance.get("gstin_id") or store_compliance.get("gstin"))
        gstin_status = store_compliance.get("gstin_status", "VERIFIED" if has_gstin else "NONE")
        if not has_gstin or gstin_status != "VERIFIED":
            raise ApiError(
                ErrorCode.GSTIN_REQUIRED,
                "Verified GSTIN is required to publish a paid commercial store",
                status_code=422,
            )

        # Gate 2c: Custom domain DNS verified check (409 CUSTOM_DOMAIN_REQUIRED)
        cd_stmt = select(models.CustomDomain).where(models.CustomDomain.store_id == store_id)
        cd_res = await session.execute(cd_stmt)
        custom_domain = cd_res.scalars().first()
        if not custom_domain or custom_domain.status not in ("DNS_VERIFIED", "ACTIVE"):
            raise ApiError(
                ErrorCode.CUSTOM_DOMAIN_REQUIRED,
                "A DNS-verified custom domain is required to publish a paid store",
                status_code=409,
            )

        # Gate 2d: Content approval check (409 CONTENT_APPROVAL_REQUIRED)
        is_approved = await catalog_client.verify_store_content_approved(store_id)
        if not is_approved:
            raise ApiError(
                ErrorCode.CONTENT_APPROVAL_REQUIRED,
                "Approved catalog content snapshot is required to publish store",
                status_code=409,
            )

        # Gate 2e: Stale version check (409 STALE_VERSION)
        if expected_version is not None and expected_version < 1:
            raise ApiError(
                ErrorCode.STALE_VERSION,
                "Publish request expected_version is stale",
                status_code=409,
            )

        tenant_id = principal.tenant_ids[0] if principal.tenant_ids else custom_domain.tenant_id

        # Disable free subdomain route if present
        free_route_stmt = select(models.PublicationRoute).where(
            models.PublicationRoute.store_id == store_id,
            models.PublicationRoute.route_type == "FREE_SUBDOMAIN",
        )
        free_route_res = await session.execute(free_route_stmt)
        free_route = free_route_res.scalars().first()
        if free_route:
            free_route.status = "DISABLED"
            free_route.deactivated_at = now
            free_route.updated_at = now

        # Activate or create custom domain route
        custom_route_stmt = select(models.PublicationRoute).where(
            models.PublicationRoute.store_id == store_id,
            models.PublicationRoute.route_type == "CUSTOM_DOMAIN",
        )
        custom_route_res = await session.execute(custom_route_stmt)
        custom_route = custom_route_res.scalars().first()
        if not custom_route:
            custom_route = models.PublicationRoute(
                id=uuid4(),
                tenant_id=tenant_id,
                store_id=store_id,
                route_type="CUSTOM_DOMAIN",
                hostname=custom_domain.domain_name,
                status="ACTIVE",
                activated_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(custom_route)
        else:
            custom_route.hostname = custom_domain.domain_name
            custom_route.status = "ACTIVE"
            custom_route.activated_at = now
            custom_route.updated_at = now

        custom_domain.status = "ACTIVE"
        custom_domain.updated_at = now

        # Emit domain.activated.v1 (DO NOT emit domain.route.activated.v1)
        await add_event(
            session=session,
            event_type="domain.activated.v1",
            aggregate_type="domain",
            aggregate_id=custom_domain.id,
            tenant_id=tenant_id,
            store_id=store_id,
            topic="domain.lifecycle",
            payload={
                "domain_id": str(custom_domain.id),
                "store_id": str(store_id),
                "domain_name": custom_domain.domain_name,
                "activated_at": now.isoformat(),
            },
        )

        # Emit store.published.v1
        await add_event(
            session=session,
            event_type="store.published.v1",
            aggregate_type="publication_route",
            aggregate_id=custom_route.id,
            tenant_id=tenant_id,
            store_id=store_id,
            topic="domain.lifecycle",
            payload={
                "store_id": str(store_id),
                "publication_state": "PUBLIC_LIVE",
                "active_host": custom_route.hostname,
                "published_at": now.isoformat(),
            },
        )

        await session.flush()
        return store_id, "PUBLIC_LIVE", custom_route.hostname, now


# ------------------------------------------------------------------------------
# DOM-008: Transfer review (AC-088)
# ------------------------------------------------------------------------------

async def open_transfer_review_command(
    session: AsyncSession,
    domain_id: UUID,
    principal: Principal,
    notes: Optional[str] = None,
) -> models.CustomDomain:
    stmt = select(models.CustomDomain).where(models.CustomDomain.id == domain_id)
    res = await session.execute(stmt)
    domain_obj = res.scalars().first()
    if not domain_obj:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Domain {domain_id} not found", status_code=404)

    check_store_authorization(principal, domain_obj.store_id)

    now = datetime.now(timezone.utc)
    domain_obj.status = "TRANSFER_REVIEW"
    domain_obj.transfer_review_notes = notes
    domain_obj.transfer_review_opened_at = now
    domain_obj.updated_at = now

    await add_event(
        session=session,
        event_type="domain.transfer-review-opened.v1",
        aggregate_type="domain",
        aggregate_id=domain_obj.id,
        tenant_id=domain_obj.tenant_id,
        store_id=domain_obj.store_id,
        topic="domain.lifecycle",
        payload={
            "domain_id": str(domain_obj.id),
            "store_id": str(domain_obj.store_id),
            "domain_name": domain_obj.domain_name,
            "notes": notes,
            "opened_at": now.isoformat(),
        },
    )

    await session.flush()
    return domain_obj


# ------------------------------------------------------------------------------
# Internal Route Resolution
# ------------------------------------------------------------------------------

async def resolve_route_query(
    session: AsyncSession,
    hostname: str,
) -> models.PublicationRoute:
    clean_host = hostname.strip().lower()
    stmt = select(models.PublicationRoute).where(
        models.PublicationRoute.hostname == clean_host,
        models.PublicationRoute.status == "ACTIVE",
    )
    res = await session.execute(stmt)
    route = res.scalars().first()
    if not route:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Active route not found for host '{clean_host}'", status_code=404)
    return route
