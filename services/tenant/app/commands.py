# app/commands.py
# Plain transaction functions implementing named business commands for Tenant & Store (RULES.md §4).
# No abstraction layers, repositories, or unit-of-work classes.
from uuid import UUID, uuid4
from datetime import datetime, timezone, date, timedelta
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from .config import settings
from .db import set_rls_context
from . import domain
from . import models
from . import clients
from .events import add_event


# -----------------------------------------------------------------------------
# TEN-001: Register Tenant (AC-001, AC-035, SM §4)
# -----------------------------------------------------------------------------
async def register_tenant_command(
    session: AsyncSession,
    current_principal: Principal,
    pan: str,
    legal_name: str,
    tenant_type: str = "INDIVIDUAL",
    date_of_birth: date | None = None,
    acceptance_refs: list[dict] | None = None,
    correlation_id: UUID | None = None,
) -> dict:
    """Registers PAN-identified tenant; validates PAN format, evaluates minor status, sets Free entitlement."""
    corr = correlation_id or uuid4()
    now = datetime.now(timezone.utc)

    norm_pan = domain.validate_pan_format(pan)
    pan_fp = domain.compute_blind_fingerprint(norm_pan, settings.HMAC_SECRET_KEY)

    # 1. Generate tenant_id and set RLS context before inserting so WITH CHECK passes
    tenant_id = uuid4()
    await set_rls_context(session, tenant_id=tenant_id)

    # 2. Verify PAN with provider adapter (mock STUB)
    verif_res = await clients.verify_pan_with_provider(norm_pan)
    if not verif_res.get("verified"):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, verif_res.get("error", "PAN verification failed"), status_code=400)

    # 3. Evaluate age & minor status (AC-035, TEN-01..03)
    minor_status = domain.evaluate_minor_status(date_of_birth)
    tenant_status = "PENDING" if minor_status == "GUARDIAN_REQUIRED" else "ACTIVE"

    pan_cipher = domain.encrypt_pii(norm_pan, settings.PII_ENCRYPTION_KEY)
    pan_masked = domain.mask_pan(norm_pan)

    new_tenant = models.Tenant(
        id=tenant_id,
        pan_ciphertext=pan_cipher,
        pan_fingerprint=pan_fp,
        pan_masked=pan_masked,
        legal_name=legal_name.strip(),
        date_of_birth=date_of_birth,
        tenant_type=tenant_type,
        minor_status=minor_status,
        status=tenant_status,
        created_at=now,
        updated_at=now,
    )
    session.add(new_tenant)

    # Record PAN verification history
    new_verif = models.PanVerification(
        id=uuid4(),
        tenant_id=tenant_id,
        provider_code=verif_res.get("provider_code", "MOCK_V1"),
        provider_reference=verif_res.get("reference", f"REF-{pan_fp[:16]}"),
        status="VERIFIED",
        verified_name=verif_res.get("registered_name", legal_name),
        verified_at=now,
    )
    session.add(new_verif)

    # Exactly one lifetime Free Store entitlement per tenant PAN (AC-002)
    free_entitlement = models.FreeStoreEntitlement(
        tenant_id=tenant_id,
        status="AVAILABLE",
        created_at=now,
    )
    session.add(free_entitlement)

    # Flush and catch duplicate PAN fingerprint via unique index (ignores RLS, race-safe)
    try:
        await session.flush()
    except IntegrityError as exc:
        if "uq_tenant_pan_fingerprint" in str(exc).lower() or "pan_fingerprint" in str(exc).lower():
            raise ApiError(ErrorCode.TENANT_PAN_ALREADY_REGISTERED, "A tenant is already registered with this PAN", status_code=409) from exc
        raise

    # Outbox events
    await add_event(
        session=session,
        event_type="tenant.registration-started.v1",
        aggregate_type="Tenant",
        aggregate_id=tenant_id,
        payload={"tenant_id": str(tenant_id), "pan_masked": pan_masked, "legal_name": legal_name},
        topic="tenant.lifecycle",
        tenant_id=tenant_id,
        correlation_id=corr,
    )

    if minor_status == "GUARDIAN_REQUIRED":
        await add_event(
            session=session,
            event_type="tenant.guardian-required.v1",
            aggregate_type="Tenant",
            aggregate_id=tenant_id,
            payload={"tenant_id": str(tenant_id), "reason": "AGE_UNDER_18"},
            topic="tenant.lifecycle",
            tenant_id=tenant_id,
            correlation_id=corr,
        )
    else:
        await add_event(
            session=session,
            event_type="tenant.activated.v1",
            aggregate_type="Tenant",
            aggregate_id=tenant_id,
            payload={"tenant_id": str(tenant_id), "status": "ACTIVE"},
            topic="tenant.lifecycle",
            tenant_id=tenant_id,
            correlation_id=corr,
        )

    return {
        "tenant_id": tenant_id,
        "registration_state": minor_status if minor_status != "NOT_MINOR" else "STANDARD_TENANT",
        "status": tenant_status,
        "pan_masked": pan_masked,
        "legal_name": legal_name,
    }


# -----------------------------------------------------------------------------
# TEN-002: Get Tenant Profile
# -----------------------------------------------------------------------------
async def get_tenant_command(
    session: AsyncSession,
    tenant_id: UUID,
    current_principal: Principal,
) -> models.Tenant:
    """Reads tenant profile; validates caller authorization."""
    if not (current_principal.has_role("PLATFORM_OWNER") or current_principal.has_role("PLATFORM_STAFF") or current_principal.has_tenant(tenant_id)):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Caller is not authorized for this tenant", status_code=403)

    tenant = await session.get(models.Tenant, tenant_id)
    if not tenant:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Tenant not found", status_code=404)
    return tenant


# -----------------------------------------------------------------------------
# TEN-003: Submit Guardian Details (AC-038, TEN-04)
# -----------------------------------------------------------------------------
async def submit_guardian_command(
    session: AsyncSession,
    tenant_id: UUID,
    current_principal: Principal,
    full_name: str,
    relationship_code: str,
    email: str,
    mobile_e164: str,
    correlation_id: UUID | None = None,
) -> dict:
    """Submits guardian profile for a minor tenant (TEN-003, AC-038)."""
    corr = correlation_id or uuid4()
    now = datetime.now(timezone.utc)

    if not (current_principal.has_tenant(tenant_id) or current_principal.has_role("PLATFORM_OWNER") or current_principal.has_role("PLATFORM_STAFF")):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Caller is not authorized for this tenant", status_code=403)

    tenant = await session.get(models.Tenant, tenant_id, with_for_update=True)
    if not tenant:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Tenant not found", status_code=404)

    if tenant.minor_status != "GUARDIAN_REQUIRED":
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Tenant is not in GUARDIAN_REQUIRED state (current: {tenant.minor_status})", status_code=400)

    if relationship_code not in ("PARENT", "LEGAL_GUARDIAN"):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "relationship_code must be PARENT or LEGAL_GUARDIAN", status_code=400)

    guardian_id = uuid4()
    guardian = models.Guardian(
        id=guardian_id,
        tenant_id=tenant_id,
        full_name=full_name.strip(),
        relationship_code=relationship_code,
        email=email.strip().lower(),
        mobile_e164=mobile_e164.strip(),
        verification_status="PENDING",
        active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(guardian)

    tenant.minor_status = "GUARDIAN_VERIFICATION"
    tenant.updated_at = now

    await add_event(
        session=session,
        event_type="guardian.verification-started.v1",
        aggregate_type="Guardian",
        aggregate_id=guardian_id,
        payload={"guardian_id": str(guardian_id), "tenant_id": str(tenant_id), "relationship_code": relationship_code},
        topic="tenant.lifecycle",
        tenant_id=tenant_id,
        correlation_id=corr,
    )

    return {
        "guardian_id": guardian_id,
        "tenant_id": tenant_id,
        "verification_status": "PENDING",
        "minor_status": "GUARDIAN_VERIFICATION",
    }


# -----------------------------------------------------------------------------
# TEN-004: Record Guardian Consent & Activate Minor (AC-039, TEN-05/06)
# -----------------------------------------------------------------------------
async def record_guardian_consent_command(
    session: AsyncSession,
    tenant_id: UUID,
    guardian_id: UUID,
    current_principal: Principal,
    consents: list[dict],
    acceptance_ip: str | None = None,
    correlation_id: UUID | None = None,
) -> dict:
    """Records immutable guardian consents and activates minor tenant (TEN-004, AC-039)."""
    corr = correlation_id or uuid4()
    now = datetime.now(timezone.utc)

    # Caller must have GUARDIAN role for this tenant or be platform admin
    is_admin = current_principal.has_role("PLATFORM_OWNER") or current_principal.has_role("PLATFORM_STAFF")
    is_guardian_for_tenant = current_principal.has_role("GUARDIAN") and current_principal.has_tenant(tenant_id)
    if not (is_admin or is_guardian_for_tenant):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Only GUARDIAN for this tenant can sign legal consents", status_code=403)

    tenant = await session.get(models.Tenant, tenant_id, with_for_update=True)
    if not tenant:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Tenant not found", status_code=404)

    guardian = await session.get(models.Guardian, guardian_id, with_for_update=True)
    if not guardian or guardian.tenant_id != tenant_id:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Guardian not found for this tenant", status_code=404)

    if not consents:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "At least one consent declaration is required", status_code=400)

    # Append immutable consent rows
    for item in consents:
        consent_row = models.GuardianConsent(
            id=uuid4(),
            tenant_id=tenant_id,
            guardian_id=guardian_id,
            consent_type=item.get("consent_type", "TERMS"),
            document_code=item.get("document_code", "DOC_STANDARD_TERMS"),
            document_version=item.get("document_version", "v1.0"),
            document_hash=item.get("document_hash", "hash_placeholder_64char_string_________________________________"),
            accepted_at=now,
            acceptance_ip=acceptance_ip,
        )
        session.add(consent_row)

    guardian.verification_status = "VERIFIED"
    guardian.verified_at = now
    guardian.principal_id = current_principal.sub

    tenant.minor_status = "MINOR_TENANT_ACTIVE"
    tenant.status = "ACTIVE"
    tenant.updated_at = now

    await add_event(
        session=session,
        event_type="guardian.consent.accepted.v1",
        aggregate_type="Guardian",
        aggregate_id=guardian_id,
        payload={"guardian_id": str(guardian_id), "tenant_id": str(tenant_id), "consents_count": len(consents)},
        topic="tenant.lifecycle",
        tenant_id=tenant_id,
        correlation_id=corr,
    )

    await add_event(
        session=session,
        event_type="tenant.activated.v1",
        aggregate_type="Tenant",
        aggregate_id=tenant_id,
        payload={"tenant_id": str(tenant_id), "minor_status": "MINOR_TENANT_ACTIVE"},
        topic="tenant.lifecycle",
        tenant_id=tenant_id,
        correlation_id=corr,
    )

    return {
        "tenant_id": tenant_id,
        "guardian_id": guardian_id,
        "minor_status": "MINOR_TENANT_ACTIVE",
        "status": "ACTIVE",
    }


# -----------------------------------------------------------------------------
# TEN-005: Adult Reverification (AC-040, TEN-08)
# -----------------------------------------------------------------------------
async def adult_reverification_command(
    session: AsyncSession,
    tenant_id: UUID,
    current_principal: Principal,
    acceptance_refs: list[dict] | None = None,
    correlation_id: UUID | None = None,
) -> dict:
    """Completes adult reverification for a minor turning 18; retains guardian audit history (TEN-005, AC-040)."""
    corr = correlation_id or uuid4()
    now = datetime.now(timezone.utc)

    if not (current_principal.has_tenant(tenant_id) or current_principal.has_role("PLATFORM_OWNER") or not current_principal.tenant_ids):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Caller is not authorized for this tenant", status_code=403)

    tenant = await session.get(models.Tenant, tenant_id, with_for_update=True)
    if not tenant:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Tenant not found", status_code=404)

    if tenant.minor_status != "ADULT_REVERIFICATION_REQUIRED":
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Tenant is not awaiting adult reverification (current: {tenant.minor_status})", status_code=400)

    # Transition to STANDARD_TENANT (NOT_MINOR)
    tenant.minor_status = "NOT_MINOR"
    tenant.updated_at = now

    await add_event(
        session=session,
        event_type="tenant.adult-reverified.v1",
        aggregate_type="Tenant",
        aggregate_id=tenant_id,
        payload={"tenant_id": str(tenant_id), "minor_status": "NOT_MINOR"},
        topic="tenant.lifecycle",
        tenant_id=tenant_id,
        correlation_id=corr,
    )

    return {
        "tenant_id": tenant_id,
        "minor_status": "NOT_MINOR",
        "status": tenant.status,
    }


# -----------------------------------------------------------------------------
# TEN-006: Register & Verify GSTIN (AC-008..010, AC-036/037)
# -----------------------------------------------------------------------------
async def register_gstin_command(
    session: AsyncSession,
    tenant_id: UUID,
    current_principal: Principal,
    gstin: str,
    correlation_id: UUID | None = None,
) -> dict:
    """Registers and verifies GSTIN; verifies GSTIN characters 3..12 match tenant PAN (AC-036/037)."""
    corr = correlation_id or uuid4()
    now = datetime.now(timezone.utc)

    if not (current_principal.has_tenant(tenant_id) or current_principal.has_role("PLATFORM_OWNER") or not current_principal.tenant_ids):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Caller is not authorized for this tenant", status_code=403)

    tenant = await session.get(models.Tenant, tenant_id)
    if not tenant:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Tenant not found", status_code=404)

    norm_gstin = domain.validate_gstin_format(gstin)
    tenant_pan = domain.decrypt_pii(tenant.pan_ciphertext, settings.PII_ENCRYPTION_KEY)

    # Statutory match check (AC-036/037): GSTIN must match tenant PAN
    try:
        domain.validate_gstin_pan_match(norm_gstin, tenant_pan)
    except ValueError as e:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, str(e), status_code=400)

    gstin_fp = domain.compute_blind_fingerprint(norm_gstin, settings.HMAC_SECRET_KEY)

    # Check for duplicate GSTIN registration
    dup_query = select(models.Gstin).where(models.Gstin.gstin_fingerprint == gstin_fp)
    if (await session.execute(dup_query)).scalars().first():
        raise ApiError(ErrorCode.GSTIN_ALREADY_USED, "GSTIN already registered", status_code=409)

    # Verify GSTIN via provider adapter
    verif_res = await clients.verify_gstin_with_provider(norm_gstin, tenant_pan)
    if not verif_res.get("verified"):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, verif_res.get("error", "GSTIN verification failed"), status_code=400)

    gstin_id = uuid4()
    gstin_cipher = domain.encrypt_pii(norm_gstin, settings.PII_ENCRYPTION_KEY)
    gstin_masked = domain.mask_gstin(norm_gstin)

    new_gstin = models.Gstin(
        id=gstin_id,
        tenant_id=tenant_id,
        gstin_ciphertext=gstin_cipher,
        gstin_fingerprint=gstin_fp,
        gstin_masked=gstin_masked,
        state_code=verif_res.get("state_code", norm_gstin[:2]),
        legal_name=verif_res.get("legal_name"),
        verification_status="VERIFIED",
        verified_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(new_gstin)

    new_verif = models.GstinVerification(
        id=uuid4(),
        gstin_id=gstin_id,
        provider_code=verif_res.get("provider_code", "MOCK_V1"),
        provider_reference=verif_res.get("reference", f"REF-{gstin_fp[:16]}"),
        status="VERIFIED",
        verified_pan_fingerprint=tenant.pan_fingerprint,
        verified_at=now,
    )
    session.add(new_verif)

    await add_event(
        session=session,
        event_type="gstin.verified.v1",
        aggregate_type="Gstin",
        aggregate_id=gstin_id,
        payload={"gstin_id": str(gstin_id), "tenant_id": str(tenant_id), "state_code": new_gstin.state_code},
        topic="tenant.lifecycle",
        tenant_id=tenant_id,
        correlation_id=corr,
    )

    return {
        "gstin_id": gstin_id,
        "tenant_id": tenant_id,
        "gstin_masked": gstin_masked,
        "state_code": new_gstin.state_code,
        "verification_status": "VERIFIED",
    }


# -----------------------------------------------------------------------------
# TEN-007: List GSTINs
# -----------------------------------------------------------------------------
async def list_gstins_command(
    session: AsyncSession,
    tenant_id: UUID,
    current_principal: Principal,
) -> list[models.Gstin]:
    """Lists registered GSTINs for tenant."""
    if not (current_principal.has_tenant(tenant_id) or current_principal.has_role("PLATFORM_OWNER") or current_principal.has_role("PLATFORM_STAFF")):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Caller is not authorized for this tenant", status_code=403)

    query = select(models.Gstin).where(models.Gstin.tenant_id == tenant_id)
    return (await session.execute(query)).scalars().all()


# -----------------------------------------------------------------------------
# TEN-008: Create Store (AC-002, AC-008..010, SEC-TST-005)
# -----------------------------------------------------------------------------
async def create_store_command(
    session: AsyncSession,
    tenant_id: UUID,
    current_principal: Principal,
    store_code: str,
    display_name: str,
    store_mode: str = "FREE_PRESENCE",
    gstin_id: UUID | None = None,
    correlation_id: UUID | None = None,
) -> dict:
    """Creates Free Store shell (atomically consumes lifetime entitlement) or Paid Store (validates unused GSTIN)."""
    corr = correlation_id or uuid4()
    now = datetime.now(timezone.utc)

    # SEC-TST-005: Guardian privilege separation (Guardian has zero store rights)
    if current_principal.has_role("GUARDIAN") and not (current_principal.has_role("PLATFORM_OWNER") or current_principal.has_role("STORE_OWNER")):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Guardian role cannot perform store operations", status_code=403)

    if not (current_principal.has_tenant(tenant_id) or current_principal.has_role("PLATFORM_OWNER") or not current_principal.tenant_ids):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Caller is not authorized for this tenant", status_code=403)

    tenant = await session.get(models.Tenant, tenant_id)
    if not tenant:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Tenant not found", status_code=404)

    # Minor check: minor cannot create stores until active with guardian consent
    if tenant.minor_status in ("GUARDIAN_REQUIRED", "GUARDIAN_VERIFICATION"):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Minor tenant cannot create stores until guardian consent is completed", status_code=403)

    norm_code = store_code.strip().lower()

    # Check store code uniqueness
    code_query = select(models.Store).where(models.Store.store_code == norm_code)
    if (await session.execute(code_query)).scalars().first():
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Store code '{norm_code}' already exists", status_code=409)

    store_id = uuid4()

    # FREE_PRESENCE mode: check availability
    entitlement = None
    if store_mode == "FREE_PRESENCE":
        entitlement_query = (
            select(models.FreeStoreEntitlement)
            .where(models.FreeStoreEntitlement.tenant_id == tenant_id)
            .with_for_update()
        )
        ent_res = await session.execute(entitlement_query)
        entitlement = ent_res.scalars().first()

        if not entitlement or entitlement.status != "AVAILABLE":
            raise ApiError(ErrorCode.FREE_STORE_ENTITLEMENT_CONSUMED, "Free store entitlement already consumed (FREE_STORE_ENTITLEMENT_CONSUMED)", status_code=409)

    # PAID_COMMERCE mode: requires valid, unused GSTIN (AC-008..010)
    elif store_mode == "PAID_COMMERCE":
        if not gstin_id:
            raise ApiError(ErrorCode.GSTIN_REQUIRED, "Paid store creation requires a valid gstin_id", status_code=400)

        gstin = await session.get(models.Gstin, gstin_id)
        if not gstin or gstin.tenant_id != tenant_id or gstin.verification_status != "VERIFIED":
            raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Specified GSTIN is invalid or not verified for this tenant", status_code=400)

        # Check that this GSTIN is not actively used by another non-archived store (AC-008/009)
        gstin_used_query = (
            select(models.Store)
            .where(models.Store.gstin_id == gstin_id, models.Store.archived_at.is_(None))
        )
        if (await session.execute(gstin_used_query)).scalars().first():
            raise ApiError(ErrorCode.GSTIN_ALREADY_USED, "GSTIN is already actively backing another store (GSTIN_ALREADY_USED)", status_code=409)

    # 1. Insert store first to satisfy FK references
    new_store = models.Store(
        id=store_id,
        tenant_id=tenant_id,
        store_code=norm_code,
        display_name=display_name.strip(),
        store_mode=store_mode,
        lifecycle_status="ACTIVE",
        gstin_id=gstin_id if store_mode == "PAID_COMMERCE" else None,
        created_at=now,
        updated_at=now,
    )
    session.add(new_store)
    await session.flush()

    # 2. Update entitlement now that store exists
    if store_mode == "FREE_PRESENCE" and entitlement:
        entitlement.status = "CONSUMED"
        entitlement.consumed_store_id = store_id
        entitlement.consumed_at = now

        await add_event(
            session=session,
            event_type="store.free-entitlement-consumed.v1",
            aggregate_type="FreeStoreEntitlement",
            aggregate_id=tenant_id,
            payload={"tenant_id": str(tenant_id), "store_id": str(store_id)},
            topic="tenant.lifecycle",
            tenant_id=tenant_id,
            store_id=store_id,
            correlation_id=corr,
        )

    # Seller identity snapshot (AC-082/083)
    gstin_masked_val = None
    if gstin_id:
        g = await session.get(models.Gstin, gstin_id)
        gstin_masked_val = g.gstin_masked if g else None

    snapshot = models.SellerIdentitySnapshot(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        legal_name=tenant.legal_name,
        pan_masked=tenant.pan_masked,
        gstin_masked=gstin_masked_val,
        snapshotted_at=now,
    )
    session.add(snapshot)

    # Store owner membership
    owner_membership = models.StoreMembership(
        id=uuid4(),
        tenant_id=tenant_id,
        store_id=store_id,
        principal_id=current_principal.sub,
        role_code="STORE_OWNER",
        status="ACTIVE",
        assigned_at=now,
    )
    session.add(owner_membership)

    await add_event(
        session=session,
        event_type="store.created.v1",
        aggregate_type="Store",
        aggregate_id=store_id,
        payload={
            "store_id": str(store_id),
            "tenant_id": str(tenant_id),
            "store_code": norm_code,
            "store_mode": store_mode,
        },
        topic="tenant.lifecycle",
        tenant_id=tenant_id,
        store_id=store_id,
        correlation_id=corr,
    )

    return {
        "store_id": store_id,
        "tenant_id": tenant_id,
        "store_code": norm_code,
        "display_name": display_name,
        "store_mode": store_mode,
        "lifecycle_status": "ACTIVE",
    }


# -----------------------------------------------------------------------------
# TEN-009: Get Store
# -----------------------------------------------------------------------------
async def get_store_command(
    session: AsyncSession,
    store_id: UUID,
    current_principal: Principal,
) -> models.Store:
    """Reads store details; verifies caller authorization."""
    store = await session.get(models.Store, store_id)
    if not store:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Store not found", status_code=404)

    if not (
        current_principal.has_role("PLATFORM_OWNER")
        or current_principal.has_role("PLATFORM_STAFF")
        or current_principal.has_role("SERVICE")
        or current_principal.has_tenant(store.tenant_id)
        or (store_id in current_principal.store_ids)
    ):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Caller is not authorized for this store", status_code=403)

    return store


# -----------------------------------------------------------------------------
# TEN-010: Assign Store Staff
# -----------------------------------------------------------------------------
async def assign_store_staff_command(
    session: AsyncSession,
    store_id: UUID,
    current_principal: Principal,
    target_principal_id: UUID,
    role_code: str = "STORE_STAFF",
    correlation_id: UUID | None = None,
) -> dict:
    """Assigns staff membership to a store."""
    corr = correlation_id or uuid4()
    now = datetime.now(timezone.utc)

    store = await session.get(models.Store, store_id)
    if not store:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Store not found", status_code=404)

    # SEC-TST-005 & TEN-R04: Guardian has zero store operational permissions
    if current_principal.has_role("GUARDIAN") and not current_principal.has_role("PLATFORM_OWNER"):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Guardian role cannot manage store staff", status_code=403)

    if not (current_principal.has_role("STORE_OWNER") or current_principal.has_role("PLATFORM_OWNER")) or not current_principal.has_tenant(store.tenant_id):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Caller is not store owner", status_code=403)

    assignment_id = uuid4()
    membership = models.StoreMembership(
        id=assignment_id,
        tenant_id=store.tenant_id,
        store_id=store_id,
        principal_id=target_principal_id,
        role_code=role_code,
        status="ACTIVE",
        assigned_at=now,
    )
    session.add(membership)

    await add_event(
        session=session,
        event_type="store.staff-assigned.v1",
        aggregate_type="StoreMembership",
        aggregate_id=assignment_id,
        payload={"assignment_id": str(assignment_id), "store_id": str(store_id), "principal_id": str(target_principal_id)},
        topic="tenant.lifecycle",
        tenant_id=store.tenant_id,
        store_id=store_id,
        correlation_id=corr,
    )

    return {"assignment_id": assignment_id, "store_id": store_id, "principal_id": target_principal_id, "status": "ACTIVE"}


# -----------------------------------------------------------------------------
# TEN-011: Revoke Store Staff
# -----------------------------------------------------------------------------
async def revoke_store_staff_command(
    session: AsyncSession,
    store_id: UUID,
    assignment_id: UUID,
    current_principal: Principal,
    correlation_id: UUID | None = None,
) -> dict:
    """Revokes store staff assignment."""
    corr = correlation_id or uuid4()
    now = datetime.now(timezone.utc)

    membership = await session.get(models.StoreMembership, assignment_id, with_for_update=True)
    if not membership or membership.store_id != store_id or membership.status != "ACTIVE":
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Active membership not found", status_code=404)

    # SEC-TST-005 & TEN-R04: Guardian has zero store operational permissions
    if current_principal.has_role("GUARDIAN") and not current_principal.has_role("PLATFORM_OWNER"):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Guardian role cannot manage store staff", status_code=403)

    if not (current_principal.has_role("STORE_OWNER") or current_principal.has_role("PLATFORM_OWNER")) or not current_principal.has_tenant(membership.tenant_id):
        raise ApiError(ErrorCode.ENTITLEMENT_REQUIRED, "Forbidden: Caller is not store owner", status_code=403)

    membership.status = "REVOKED"
    membership.revoked_at = now

    # TODO(OQ-042): gap event store.staff-revoked.v1 is not in Event Registry; omit publish per RULES.md §1 C8

    return {"assignment_id": assignment_id, "status": "REVOKED"}


# -----------------------------------------------------------------------------
# Internal: Bind GSTIN to Store (OQ-023 / SUB activation)
# -----------------------------------------------------------------------------
async def bind_gstin_to_store_command(
    session: AsyncSession,
    gstin_id: UUID,
    store_id: UUID,
    correlation_id: UUID | None = None,
) -> dict:
    """Internal service command: atomically binds verified GSTIN to store (called by SUB)."""
    store = await session.get(models.Store, store_id, with_for_update=True)
    if not store:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Store not found", status_code=404)

    gstin = await session.get(models.Gstin, gstin_id)
    if not gstin or gstin.tenant_id != store.tenant_id or gstin.verification_status != "VERIFIED":
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "GSTIN is invalid or not verified for this store's tenant", status_code=400)

    # Check for another active store using this GSTIN
    dup_query = (
        select(models.Store)
        .where(models.Store.gstin_id == gstin_id, models.Store.id != store_id, models.Store.archived_at.is_(None))
    )
    if (await session.execute(dup_query)).scalars().first():
        raise ApiError(ErrorCode.GSTIN_ALREADY_USED, "GSTIN is already bound to another active store", status_code=409)

    # Record store_gstin_assignment
    now = datetime.now(timezone.utc)
    assignment = models.StoreGstinAssignment(
        id=uuid4(),
        tenant_id=store.tenant_id,
        store_id=store.id,
        gstin_id=gstin.id,
        assigned_at=now,
    )
    session.add(assignment)

    store.gstin_id = gstin_id
    store.updated_at = now

    try:
        await session.flush()
    except IntegrityError as exc:
        if "uq_active_store_gstin" in str(exc).lower() or "uq_active_store_assignment" in str(exc).lower():
            raise ApiError(ErrorCode.GSTIN_ALREADY_USED, "GSTIN or store already has an active assignment", status_code=409) from exc
        raise

    return {"status": "bound", "store_id": store_id, "gstin_id": gstin_id}


# -----------------------------------------------------------------------------
# Turns-18 Scheduler Task (AC-040, TEN-07)
# -----------------------------------------------------------------------------
async def run_turns_18_scheduler_task(
    session: AsyncSession,
    reference_date: date | None = None,
    correlation_id: UUID | None = None,
) -> list[UUID]:
    """
    Evaluates all minor tenants in MINOR_TENANT_ACTIVE.
    If DOB indicates age >= 18, transitions minor_status to ADULT_REVERIFICATION_REQUIRED (AC-040).
    """
    ref = reference_date or date.today()
    corr = correlation_id or uuid4()
    now = datetime.now(timezone.utc)

    # Query active minor tenants
    query = (
        select(models.Tenant)
        .where(
            models.Tenant.minor_status == "MINOR_TENANT_ACTIVE",
            models.Tenant.date_of_birth.is_not(None),
        )
        .with_for_update()
    )
    res = await session.execute(query)
    minor_tenants = res.scalars().all()

    transitioned_ids = []
    for tenant in minor_tenants:
        if domain.should_transition_turns_18(tenant.date_of_birth, tenant.minor_status, ref):
            tenant.minor_status = "ADULT_REVERIFICATION_REQUIRED"
            tenant.updated_at = now
            transitioned_ids.append(tenant.id)

            # TODO(OQ-043): invented event tenant.adult-reverification-required.v1 is not in Event Registry; omit publish

    return transitioned_ids
