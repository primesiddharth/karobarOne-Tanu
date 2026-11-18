# app/commands.py
from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, text
from sqlalchemy.exc import IntegrityError
import structlog

from libs.platform_contracts.errors import ApiError, ErrorCode
from libs.platform_contracts.tokens import Principal
from . import models, domain
from .events import add_event
from .clients import iam_client, tenant_client
from .db import set_rls_context

logger = structlog.get_logger("customer.commands")


async def create_or_resolve_guest_customer_command(
    session: AsyncSession,
    store_id: UUID,
    email: str,
    mobile: str,
    first_name: str | None = None,
    last_name: str | None = None,
    correlation_id: UUID | None = None,
) -> models.Customer:
    """Creates a new UNCLAIMED customer or resolves an existing one in store_id (CUS-001, AC-076, AC-077)."""
    norm_email = domain.normalize_email(email)
    norm_mobile = domain.normalize_mobile_e164(mobile)
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()

    # 1. Resolve store's tenant_id and set RLS context
    tenant_id = await tenant_client.resolve_store_tenant(store_id)
    await set_rls_context(session, tenant_id=tenant_id, store_id=store_id)

    # 2. Check for existing customer in this store with matching email or mobile
    query = select(models.Customer).where(
        models.Customer.store_id == store_id,
        or_(
            models.Customer.email == norm_email,
            models.Customer.mobile_e164 == norm_mobile,
        ),
    )
    res = await session.execute(query)
    existing = res.scalars().all()

    if existing:
        # Check if single exact match (same email AND same mobile)
        exact_matches = [c for c in existing if c.email == norm_email and c.mobile_e164 == norm_mobile]
        if exact_matches:
            # AC-077: Guest checkout resolves existing UNCLAIMED customer
            customer = exact_matches[0]
            customer.last_activity_at = now
            if first_name and not customer.first_name:
                customer.first_name = first_name.strip()
            if last_name and not customer.last_name:
                customer.last_name = last_name.strip()
            await session.flush()
            return customer

        # Conflict: email matches one row or mobile matches another row
        raise ApiError(
            ErrorCode.IDEMPOTENCY_CONFLICT,
            "A customer with this email or mobile already exists in this store",
            status_code=409,
        )

    # 3. Create new UNCLAIMED customer
    customer_id = uuid4()
    new_customer = models.Customer(
        id=customer_id,
        tenant_id=tenant_id,
        store_id=store_id,
        email=norm_email,
        mobile_e164=norm_mobile,
        status="UNCLAIMED",
        first_name=first_name.strip() if first_name else None,
        last_name=last_name.strip() if last_name else None,
        created_at=now,
        updated_at=now,
        last_activity_at=now,
    )
    session.add(new_customer)

    try:
        await session.flush()
    except IntegrityError as exc:
        err_msg = str(exc).lower()
        if "uq_customer_store_email" in err_msg or "uq_customer_store_mobile" in err_msg:
            raise ApiError(
                ErrorCode.IDEMPOTENCY_CONFLICT,
                "A customer with this email or mobile already exists in this store",
                status_code=409,
            ) from exc
        raise

    # 4. Outbox event
    await add_event(
        session=session,
        event_type="customer.unclaimed-created.v1",
        aggregate_type="Customer",
        aggregate_id=customer_id,
        payload={
            "customer_id": str(customer_id),
            "tenant_id": str(tenant_id),
            "store_id": str(store_id),
            "email": norm_email,
            "status": "UNCLAIMED",
        },
        topic="customer.lifecycle",
        tenant_id=tenant_id,
        store_id=store_id,
        correlation_id=corr,
    )

    return new_customer


async def initiate_claim_challenge_command(
    session: AsyncSession,
    customer_id: UUID,
    channel: str = "EMAIL",
    correlation_id: UUID | None = None,
) -> models.AccountClaim:
    """Initiates an Email OTP claim challenge via IAM (CUS-002, SM §8, AC-078)."""
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()

    # 1. Lookup customer
    customer = await session.get(models.Customer, customer_id)
    if not customer:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Customer {customer_id} not found", status_code=404)

    await set_rls_context(session, tenant_id=customer.tenant_id, store_id=customer.store_id)

    if customer.status == "CLAIMED":
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Customer account is already claimed", status_code=409)
    if customer.status in ("BLOCKED", "ANONYMIZED"):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Cannot claim {customer.status} account", status_code=409)

    # 2. Request OTP from IAM (IAM-004)
    otp_challenge_id = await iam_client.request_otp_challenge(
        email=customer.email,
        purpose="ACCOUNT_CLAIM",
        correlation_id=corr,
    )

    # 3. Record account claim record
    claim_id = uuid4()
    claim = models.AccountClaim(
        id=claim_id,
        tenant_id=customer.tenant_id,
        store_id=customer.store_id,
        customer_id=customer.id,
        otp_challenge_id=otp_challenge_id,
        status="PENDING",
        requested_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(claim)
    await session.flush()

    # 4. Outbox event
    await add_event(
        session=session,
        event_type="customer.claim-challenge-created.v1",
        aggregate_type="AccountClaim",
        aggregate_id=claim_id,
        payload={
            "claim_id": str(claim_id),
            "customer_id": str(customer.id),
            "tenant_id": str(customer.tenant_id),
            "store_id": str(customer.store_id),
            "channel": channel,
            "status": "PENDING",
        },
        topic="customer.lifecycle",
        tenant_id=customer.tenant_id,
        store_id=customer.store_id,
        correlation_id=corr,
    )

    return claim


async def verify_claim_command(
    session: AsyncSession,
    customer_id: UUID,
    challenge_id: UUID,
    otp_code: str,
    password: str | None = None,
    correlation_id: UUID | None = None,
) -> models.Customer:
    """Verifies OTP with IAM, transitions customer to CLAIMED, binds IAM principal (CUS-003, AC-078)."""
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()

    # 1. Lookup customer
    customer = await session.get(models.Customer, customer_id)
    if not customer:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Customer {customer_id} not found", status_code=404)

    await set_rls_context(session, tenant_id=customer.tenant_id, store_id=customer.store_id)

    # 2. Lookup claim record
    claim = await session.get(models.AccountClaim, challenge_id)
    if not claim or claim.customer_id != customer.id:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Claim challenge does not match customer", status_code=400)
    if claim.status != "PENDING":
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Claim challenge is {claim.status}", status_code=409)

    # 3. Verify OTP via IAM (IAM-005)
    is_valid = await iam_client.verify_otp_challenge(
        challenge_id=claim.otp_challenge_id,
        otp_code=otp_code,
        correlation_id=corr,
    )
    if not is_valid:
        claim.status = "FAILED"
        claim.updated_at = now
        await session.flush()
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Invalid or expired OTP code", status_code=400)

    # 4. Resolve or link IAM principal (OQ-040, AC-078)
    principal_id = await iam_client.link_or_create_principal(customer.email, password=password)

    # Transition claim and customer
    domain.validate_claim_transition(claim.status, "VERIFIED")
    domain.validate_customer_transition(customer.status, "CLAIMED")

    claim.status = "VERIFIED"
    claim.verified_at = now
    claim.resulting_principal_id = principal_id
    claim.updated_at = now

    customer.status = "CLAIMED"
    customer.iam_principal_id = principal_id
    customer.claimed_at = now
    customer.updated_at = now
    await session.flush()

    # 5. Outbox event
    await add_event(
        session=session,
        event_type="customer.claimed.v1",
        aggregate_type="Customer",
        aggregate_id=customer.id,
        payload={
            "customer_id": str(customer.id),
            "tenant_id": str(customer.tenant_id),
            "store_id": str(customer.store_id),
            "iam_principal_id": str(principal_id),
            "claimed_at": now.isoformat(),
        },
        topic="customer.lifecycle",
        tenant_id=customer.tenant_id,
        store_id=customer.store_id,
        correlation_id=corr,
    )

    return customer


async def get_customer_command(
    session: AsyncSession,
    customer_id: UUID,
    current_principal: Principal | None = None,
) -> models.Customer:
    """Retrieves customer profile with access verification (CUS-004)."""
    customer = await session.get(models.Customer, customer_id)
    if not customer:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Customer {customer_id} not found", status_code=404)

    is_admin = current_principal and any(r in ("PLATFORM_OWNER", "PLATFORM_STAFF") for r in current_principal.roles)
    await set_rls_context(session, tenant_id=customer.tenant_id, store_id=customer.store_id, is_platform_admin=is_admin)

    return customer


async def update_customer_profile_command(
    session: AsyncSession,
    customer_id: UUID,
    first_name: str | None = None,
    last_name: str | None = None,
    current_principal: Principal | None = None,
    correlation_id: UUID | None = None,
) -> models.Customer:
    """Updates customer profile fields (CUS-005, RULES.md §5.5)."""
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()

    customer = await session.get(models.Customer, customer_id)
    if not customer:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Customer {customer_id} not found", status_code=404)

    is_admin = current_principal and any(r in ("PLATFORM_OWNER", "PLATFORM_STAFF") for r in current_principal.roles)
    await set_rls_context(session, tenant_id=customer.tenant_id, store_id=customer.store_id, is_platform_admin=is_admin)

    if customer.status == "ANONYMIZED":
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Cannot update anonymized profile", status_code=409)

    if first_name is not None:
        customer.first_name = first_name.strip()
    if last_name is not None:
        customer.last_name = last_name.strip()

    customer.updated_at = now
    await session.flush()

    # Outbox event
    await add_event(
        session=session,
        event_type="customer.profile-updated.v1",
        aggregate_type="Customer",
        aggregate_id=customer.id,
        payload={
            "customer_id": str(customer.id),
            "tenant_id": str(customer.tenant_id),
            "store_id": str(customer.store_id),
            "first_name": customer.first_name,
            "last_name": customer.last_name,
        },
        topic="customer.lifecycle",
        tenant_id=customer.tenant_id,
        store_id=customer.store_id,
        correlation_id=corr,
    )

    return customer


async def create_customer_address_command(
    session: AsyncSession,
    customer_id: UUID,
    address_type: str,
    recipient_name: str,
    line1: str,
    line2: str | None,
    city: str,
    state_code: str,
    postal_code: str,
    country_code: str = "IN",
    is_default: bool = False,
    current_principal: Principal | None = None,
    correlation_id: UUID | None = None,
) -> models.CustomerAddress:
    """Adds a shipping or billing address for customer (CUS-006)."""
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()

    customer = await session.get(models.Customer, customer_id)
    if not customer:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Customer {customer_id} not found", status_code=404)

    is_admin = current_principal and any(r in ("PLATFORM_OWNER", "PLATFORM_STAFF") for r in current_principal.roles)
    await set_rls_context(session, tenant_id=customer.tenant_id, store_id=customer.store_id, is_platform_admin=is_admin)

    norm_type = domain.validate_address_type(address_type)

    if is_default:
        # Unset default on previous addresses of this customer
        await session.execute(
            text("UPDATE customer.addresses SET is_default = false WHERE customer_id = :cid"),
            {"cid": str(customer_id)},
        )

    address_id = uuid4()
    address = models.CustomerAddress(
        id=address_id,
        tenant_id=customer.tenant_id,
        store_id=customer.store_id,
        customer_id=customer.id,
        address_type=norm_type,
        recipient_name=recipient_name.strip(),
        line1=line1.strip(),
        line2=line2.strip() if line2 else None,
        city=city.strip(),
        state_code=state_code.strip(),
        postal_code=postal_code.strip(),
        country_code="IN",
        is_default=is_default,
        created_at=now,
        updated_at=now,
    )
    session.add(address)
    await session.flush()

    # Outbox event
    await add_event(
        session=session,
        event_type="customer.address-created.v1",
        aggregate_type="CustomerAddress",
        aggregate_id=address_id,
        payload={
            "address_id": str(address_id),
            "customer_id": str(customer.id),
            "tenant_id": str(customer.tenant_id),
            "store_id": str(customer.store_id),
            "address_type": norm_type,
            "city": city,
            "state_code": state_code,
            "is_default": is_default,
        },
        topic="customer.lifecycle",
        tenant_id=customer.tenant_id,
        store_id=customer.store_id,
        correlation_id=corr,
    )

    return address


async def create_privacy_request_command(
    session: AsyncSession,
    customer_id: UUID,
    request_type: str,
    current_principal: Principal | None = None,
    correlation_id: UUID | None = None,
) -> models.PrivacyRequest:
    """Opens privacy/deletion request while retaining statutory commercial/tax records (CUS-007, CUS-R04)."""
    now = datetime.now(timezone.utc)
    corr = correlation_id or uuid4()

    customer = await session.get(models.Customer, customer_id)
    if not customer:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Customer {customer_id} not found", status_code=404)

    is_admin = current_principal and any(r in ("PLATFORM_OWNER", "PLATFORM_STAFF") for r in current_principal.roles)
    await set_rls_context(session, tenant_id=customer.tenant_id, store_id=customer.store_id, is_platform_admin=is_admin)

    norm_type = domain.validate_privacy_request_type(request_type)

    retention_basis = None
    status = "OPEN"
    completed_at = None

    if norm_type == "DELETE":
        # Anonymize profile fields while statutory commercial/tax records remain intact (CUS-R04, BR-136)
        customer.first_name = "ANONYMIZED"
        customer.last_name = None
        customer.status = "ANONYMIZED"
        customer.updated_at = now

        status = "COMPLETED"
        completed_at = now
        retention_basis = "Statutory retention under GST & commercial tax laws (BR-136, BR-291, CUS-R04)"

    request_id = uuid4()
    priv_req = models.PrivacyRequest(
        id=request_id,
        tenant_id=customer.tenant_id,
        store_id=customer.store_id,
        customer_id=customer.id,
        request_type=norm_type,
        status=status,
        requested_at=now,
        completed_at=completed_at,
        retention_basis=retention_basis,
        created_at=now,
        updated_at=now,
    )
    session.add(priv_req)
    await session.flush()

    # Outbox event
    await add_event(
        session=session,
        event_type="customer.privacy-requested.v1",
        aggregate_type="PrivacyRequest",
        aggregate_id=request_id,
        payload={
            "privacy_request_id": str(request_id),
            "customer_id": str(customer.id),
            "tenant_id": str(customer.tenant_id),
            "store_id": str(customer.store_id),
            "request_type": norm_type,
            "status": status,
        },
        topic="customer.lifecycle",
        tenant_id=customer.tenant_id,
        store_id=customer.store_id,
        correlation_id=corr,
    )

    return priv_req
