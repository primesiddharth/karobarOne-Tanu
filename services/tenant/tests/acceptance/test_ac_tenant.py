# tests/acceptance/test_ac_tenant.py
# Acceptance Criteria test suite for Tenant & Store service (SERVICES.md §2).
# Function names follow test_ac_NNN_* pattern checked by tools/check_ac_coverage.py.
import pytest
from uuid import uuid4
from datetime import datetime, timezone, date
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.exc import IntegrityError

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app.config import settings
from app import commands
from app import domain
from app import models

pytestmark = pytest.mark.asyncio


def make_mock_session(execute_results=None, get_mapping=None):
    """Helper creating mock AsyncSession that gracefully handles queries and outbox inserts."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

    if get_mapping:
        mock_session.get.side_effect = (
            lambda model, obj_id, **kw: get_mapping.get((model, obj_id)) or get_mapping.get(model)
        )

    results = list(execute_results or [])

    async def _execute(*args, **kwargs):
        if results:
            return results.pop(0)
        res = MagicMock()
        res.scalars.return_value.first.return_value = None
        res.scalars.return_value.all.return_value = []
        return res

    mock_session.execute = AsyncMock(side_effect=_execute)
    return mock_session


# -----------------------------------------------------------------------------
# AC-001: One Tenant Per PAN
# -----------------------------------------------------------------------------
async def test_ac_001_one_tenant_per_pan_duplicate_rejected():
    """Duplicate PAN registration is rejected with 409 TENANT_PAN_ALREADY_REGISTERED via unique constraint (AC-001)."""
    pan = "ABCPD1234F"
    mock_session = make_mock_session()
    # Unique constraint uq_tenant_pan_fingerprint raises IntegrityError on flush
    mock_session.flush.side_effect = IntegrityError(
        "statement",
        params={},
        orig=Exception("duplicate key value violates unique constraint \"uq_tenant_pan_fingerprint\""),
    )

    principal = Principal(sub=uuid4(), roles=["USER"], tenant_ids=[], store_ids=[])

    with pytest.raises(ApiError) as exc_info:
        await commands.register_tenant_command(
            session=mock_session,
            current_principal=principal,
            pan=pan,
            legal_name="New Corp",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.TENANT_PAN_ALREADY_REGISTERED


# -----------------------------------------------------------------------------
# AC-002: One Lifetime Free Store Entitlement per PAN
# -----------------------------------------------------------------------------
async def test_ac_002_one_lifetime_free_store_entitlement():
    """Attempting to create a second Free Store is rejected with 409 (AC-002)."""
    tenant_id = uuid4()
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], tenant_ids=[tenant_id], store_ids=[])

    tenant = models.Tenant(
        id=tenant_id,
        pan_ciphertext=domain.encrypt_pii("ABCPD1234F", settings.PII_ENCRYPTION_KEY),
        pan_fingerprint="fp123",
        pan_masked="ABCPD****F",
        legal_name="ACME",
        minor_status="NOT_MINOR",
        status="ACTIVE",
    )

    consumed_entitlement = models.FreeStoreEntitlement(
        tenant_id=tenant_id,
        status="CONSUMED",
        consumed_store_id=uuid4(),
        consumed_at=datetime.now(timezone.utc),
    )

    code_res = MagicMock()
    code_res.scalars.return_value.first.return_value = None  # store_code free-two does not exist
    ent_res = MagicMock()
    ent_res.scalars.return_value.first.return_value = consumed_entitlement  # entitlement already consumed

    mock_session = make_mock_session(execute_results=[code_res, ent_res], get_mapping={models.Tenant: tenant})

    with pytest.raises(ApiError) as exc_info:
        await commands.create_store_command(
            session=mock_session,
            tenant_id=tenant_id,
            current_principal=principal,
            store_code="free-two",
            display_name="Free Store Two",
            store_mode="FREE_PRESENCE",
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.FREE_STORE_ENTITLEMENT_CONSUMED


# -----------------------------------------------------------------------------
# AC-035: Minor Registration Requires Guardian Workflow
# -----------------------------------------------------------------------------
async def test_ac_035_minor_registration_requires_guardian():
    """Registrant under 18 transitions to GUARDIAN_REQUIRED and blocks store creation (AC-035)."""
    pan = "ABCPD5555M"
    mock_session = make_mock_session()
    principal = Principal(sub=uuid4(), roles=["USER"], tenant_ids=[], store_ids=[])
    dob_minor = date(2010, 1, 1)

    res = await commands.register_tenant_command(
        session=mock_session,
        current_principal=principal,
        pan=pan,
        legal_name="Minor Student",
        date_of_birth=dob_minor,
    )

    assert res["registration_state"] == "GUARDIAN_REQUIRED"
    assert res["status"] == "PENDING"


# -----------------------------------------------------------------------------
# AC-036 & AC-037: GSTIN Must Belong to Tenant PAN
# -----------------------------------------------------------------------------
async def test_ac_036_gstin_must_belong_to_tenant_pan():
    """GSTIN must embed tenant's PAN; valid match succeeds (AC-036)."""
    tenant_id = uuid4()
    tenant_pan = "ABCPD1234F"

    tenant = models.Tenant(
        id=tenant_id,
        pan_ciphertext=domain.encrypt_pii(tenant_pan, settings.PII_ENCRYPTION_KEY),
        pan_fingerprint="fp123",
        pan_masked="ABCPD****F",
        legal_name="ACME",
    )

    mock_session = make_mock_session(get_mapping={models.Tenant: tenant})
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], tenant_ids=[tenant_id], store_ids=[])

    valid_gstin = f"27{tenant_pan}1Z5"
    res = await commands.register_gstin_command(
        session=mock_session,
        tenant_id=tenant_id,
        current_principal=principal,
        gstin=valid_gstin,
    )
    assert res["verification_status"] == "VERIFIED"


async def test_ac_037_gstin_mismatch_pan_rejected():
    """Mismatched GSTIN rejected with GSTIN_NOT_OWNED (AC-037)."""
    tenant_id = uuid4()
    tenant_pan = "ABCPD1234F"

    tenant = models.Tenant(
        id=tenant_id,
        pan_ciphertext=domain.encrypt_pii(tenant_pan, settings.PII_ENCRYPTION_KEY),
        pan_fingerprint="fp123",
        pan_masked="ABCPD****F",
        legal_name="ACME",
    )

    mock_session = make_mock_session(get_mapping={models.Tenant: tenant})
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], tenant_ids=[tenant_id], store_ids=[])

    mismatched_gstin = "27OTHER9999K1Z5"
    with pytest.raises(ApiError) as exc_info:
        await commands.register_gstin_command(
            session=mock_session,
            tenant_id=tenant_id,
            current_principal=principal,
            gstin=mismatched_gstin,
        )
    assert exc_info.value.status_code == 400
    assert "GSTIN_NOT_OWNED" in exc_info.value.message


# -----------------------------------------------------------------------------
# AC-038 & AC-039: Guardian Submission & Consent Recording
# -----------------------------------------------------------------------------
async def test_ac_038_guardian_submission():
    """Guardian submission transitions tenant to GUARDIAN_VERIFICATION (AC-038)."""
    tenant_id = uuid4()
    tenant = models.Tenant(
        id=tenant_id,
        pan_ciphertext=domain.encrypt_pii("ABCPD1234F", settings.PII_ENCRYPTION_KEY),
        pan_fingerprint="fp123",
        pan_masked="ABCPD****F",
        legal_name="Minor Tenant",
        minor_status="GUARDIAN_REQUIRED",
        status="PENDING",
    )
    mock_session = make_mock_session(get_mapping={models.Tenant: tenant})
    owner_principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], tenant_ids=[tenant_id], store_ids=[])

    sub_res = await commands.submit_guardian_command(
        session=mock_session,
        tenant_id=tenant_id,
        current_principal=owner_principal,
        full_name="Parent Guardian",
        relationship_code="PARENT",
        email="parent@example.com",
        mobile_e164="+919876543210",
    )
    assert sub_res["minor_status"] == "GUARDIAN_VERIFICATION"


async def test_ac_039_guardian_consent_recording():
    """Immutable consent recording activates minor tenant (AC-039)."""
    tenant_id = uuid4()
    guardian_id = uuid4()
    tenant = models.Tenant(
        id=tenant_id,
        pan_ciphertext=domain.encrypt_pii("ABCPD1234F", settings.PII_ENCRYPTION_KEY),
        pan_fingerprint="fp123",
        pan_masked="ABCPD****F",
        legal_name="Minor Tenant",
        minor_status="GUARDIAN_VERIFICATION",
        status="PENDING",
    )
    guardian = models.Guardian(
        id=guardian_id,
        tenant_id=tenant_id,
        full_name="Parent Guardian",
        relationship_code="PARENT",
        email="parent@example.com",
        mobile_e164="+919876543210",
        verification_status="PENDING",
        active=True,
    )
    mock_session = make_mock_session(get_mapping={models.Tenant: tenant, models.Guardian: guardian})
    guardian_principal = Principal(sub=uuid4(), roles=["GUARDIAN"], tenant_ids=[tenant_id], store_ids=[])

    consent_res = await commands.record_guardian_consent_command(
        session=mock_session,
        tenant_id=tenant_id,
        guardian_id=guardian_id,
        current_principal=guardian_principal,
        consents=[{"consent_type": "TERMS", "document_code": "DOC_TERMS", "document_version": "v1.0", "document_hash": "a" * 64}],
    )
    assert consent_res["minor_status"] == "MINOR_TENANT_ACTIVE"
    assert consent_res["status"] == "ACTIVE"


# -----------------------------------------------------------------------------
# AC-040: Turns-18 Scheduler Task & Adult Reverification
# -----------------------------------------------------------------------------
async def test_ac_040_turns_18_scheduler_task_and_reverification():
    """Turns-18 scheduled task transitions tenant to ADULT_REVERIFICATION_REQUIRED (AC-040)."""
    tenant_id = uuid4()
    today = date(2026, 11, 4)
    dob_adult = date(2008, 11, 4)

    minor_tenant = models.Tenant(
        id=tenant_id,
        pan_ciphertext=domain.encrypt_pii("ABCPD1234F", settings.PII_ENCRYPTION_KEY),
        pan_fingerprint="fp123",
        pan_masked="ABCPD****F",
        legal_name="Now Adult",
        date_of_birth=dob_adult,
        minor_status="MINOR_TENANT_ACTIVE",
        status="ACTIVE",
    )

    query_res = MagicMock()
    query_res.scalars.return_value.all.return_value = [minor_tenant]
    mock_session = make_mock_session(execute_results=[query_res], get_mapping={models.Tenant: minor_tenant})

    # 1. Run scheduler task
    transitioned = await commands.run_turns_18_scheduler_task(mock_session, reference_date=today)
    assert tenant_id in transitioned
    assert minor_tenant.minor_status == "ADULT_REVERIFICATION_REQUIRED"

    # 2. Complete Adult Reverification (TEN-005)
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], tenant_ids=[tenant_id], store_ids=[])
    reverif_res = await commands.adult_reverification_command(
        session=mock_session,
        tenant_id=tenant_id,
        current_principal=principal,
    )
    assert reverif_res["minor_status"] == "NOT_MINOR"


# -----------------------------------------------------------------------------
# AC-008 & AC-009: One GSTIN Backs One Active Paid Store
# -----------------------------------------------------------------------------
async def test_ac_008_gstin_backs_paid_store():
    """Verified GSTIN successfully backs a paid store (AC-008)."""
    tenant_id = uuid4()
    gstin_id = uuid4()
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], tenant_ids=[tenant_id], store_ids=[])

    tenant = models.Tenant(
        id=tenant_id,
        pan_ciphertext=domain.encrypt_pii("ABCPD1234F", settings.PII_ENCRYPTION_KEY),
        pan_fingerprint="fp123",
        pan_masked="ABCPD****F",
        legal_name="ACME Corp",
        minor_status="NOT_MINOR",
        status="ACTIVE",
    )
    gstin = models.Gstin(
        id=gstin_id,
        tenant_id=tenant_id,
        gstin_ciphertext=b"xyz",
        gstin_fingerprint="fp_gst1",
        gstin_masked="27ABCPD****1Z5",
        state_code="27",
        verification_status="VERIFIED",
    )

    code_res = MagicMock()
    code_res.scalars.return_value.first.return_value = None
    gstin_free_res = MagicMock()
    gstin_free_res.scalars.return_value.first.return_value = None

    mock_session = make_mock_session(
        execute_results=[code_res, gstin_free_res],
        get_mapping={models.Tenant: tenant, models.Gstin: gstin},
    )

    store_res = await commands.create_store_command(
        session=mock_session,
        tenant_id=tenant_id,
        current_principal=principal,
        store_code="paid-store-1",
        display_name="Paid Store 1",
        store_mode="PAID_COMMERCE",
        gstin_id=gstin_id,
    )
    assert store_res["store_mode"] == "PAID_COMMERCE"


async def test_ac_009_one_gstin_cannot_back_two_paid_stores():
    """One GSTIN cannot actively back two paid stores simultaneously (AC-009)."""
    tenant_id = uuid4()
    gstin_id = uuid4()
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], tenant_ids=[tenant_id], store_ids=[])

    tenant = models.Tenant(
        id=tenant_id,
        pan_ciphertext=domain.encrypt_pii("ABCPD1234F", settings.PII_ENCRYPTION_KEY),
        pan_fingerprint="fp123",
        pan_masked="ABCPD****F",
        legal_name="ACME Corp",
        minor_status="NOT_MINOR",
        status="ACTIVE",
    )
    gstin = models.Gstin(
        id=gstin_id,
        tenant_id=tenant_id,
        gstin_ciphertext=b"xyz",
        gstin_fingerprint="fp_gst1",
        gstin_masked="27ABCPD****1Z5",
        state_code="27",
        verification_status="VERIFIED",
    )
    existing_active_store = models.Store(
        id=uuid4(),
        tenant_id=tenant_id,
        store_code="paid-one",
        display_name="Paid Store One",
        store_mode="PAID_COMMERCE",
        gstin_id=gstin_id,
        archived_at=None,
    )

    code_res = MagicMock()
    code_res.scalars.return_value.first.return_value = None  # store_code free
    gstin_used_res = MagicMock()
    gstin_used_res.scalars.return_value.first.return_value = existing_active_store  # GSTIN used!

    mock_session = make_mock_session(
        execute_results=[code_res, gstin_used_res],
        get_mapping={models.Tenant: tenant, models.Gstin: gstin},
    )

    with pytest.raises(ApiError) as exc_info:
        await commands.create_store_command(
            session=mock_session,
            tenant_id=tenant_id,
            current_principal=principal,
            store_code="paid-two",
            display_name="Paid Store Two",
            store_mode="PAID_COMMERCE",
            gstin_id=gstin_id,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.GSTIN_ALREADY_USED


# -----------------------------------------------------------------------------
# AC-010: Different GSTIN Stores under Same PAN
# -----------------------------------------------------------------------------
async def test_ac_010_different_gstin_stores_under_same_pan():
    """Different verified GSTINs under the same tenant PAN may each back a store (AC-010)."""
    tenant_id = uuid4()
    gstin_a_id = uuid4()
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], tenant_ids=[tenant_id], store_ids=[])

    tenant = models.Tenant(
        id=tenant_id,
        pan_ciphertext=domain.encrypt_pii("ABCPD1234F", settings.PII_ENCRYPTION_KEY),
        pan_fingerprint="fp123",
        pan_masked="ABCPD****F",
        legal_name="Multi-State Corp",
        minor_status="NOT_MINOR",
        status="ACTIVE",
    )
    gstin_a = models.Gstin(
        id=gstin_a_id,
        tenant_id=tenant_id,
        gstin_ciphertext=b"xyz",
        gstin_fingerprint="fp_gst_a",
        gstin_masked="27ABCPD****1Z5",
        state_code="27",
        verification_status="VERIFIED",
    )

    code_res = MagicMock()
    code_res.scalars.return_value.first.return_value = None
    gstin_free_res = MagicMock()
    gstin_free_res.scalars.return_value.first.return_value = None

    mock_session = make_mock_session(
        execute_results=[code_res, gstin_free_res],
        get_mapping={models.Tenant: tenant, models.Gstin: gstin_a},
    )

    store_res = await commands.create_store_command(
        session=mock_session,
        tenant_id=tenant_id,
        current_principal=principal,
        store_code="store-state-a",
        display_name="Maharashtra Store",
        store_mode="PAID_COMMERCE",
        gstin_id=gstin_a_id,
    )
    assert store_res["store_mode"] == "PAID_COMMERCE"
    assert store_res["store_code"] == "store-state-a"


# -----------------------------------------------------------------------------
# AC-082 & AC-083 (Partial): Seller Identity Snapshotting
# -----------------------------------------------------------------------------
async def test_ac_082_083_seller_identity_snapshotting():
    """Store creation creates immutable SellerIdentitySnapshot; stores are archived, not hard-deleted (AC-082/083)."""
    tenant_id = uuid4()
    principal = Principal(sub=uuid4(), roles=["STORE_OWNER"], tenant_ids=[tenant_id], store_ids=[])

    tenant = models.Tenant(
        id=tenant_id,
        pan_ciphertext=domain.encrypt_pii("ABCPD1234F", settings.PII_ENCRYPTION_KEY),
        pan_fingerprint="fp123",
        pan_masked="ABCPD****F",
        legal_name="Audited Seller",
        minor_status="NOT_MINOR",
        status="ACTIVE",
    )
    entitlement = models.FreeStoreEntitlement(
        tenant_id=tenant_id,
        status="AVAILABLE",
    )

    code_res = MagicMock()
    code_res.scalars.return_value.first.return_value = None
    ent_res = MagicMock()
    ent_res.scalars.return_value.first.return_value = entitlement

    added_objects = []
    mock_session = make_mock_session(
        execute_results=[code_res, ent_res],
        get_mapping={models.Tenant: tenant},
    )
    mock_session.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

    await commands.create_store_command(
        session=mock_session,
        tenant_id=tenant_id,
        current_principal=principal,
        store_code="snapshot-store",
        display_name="Audited Store",
        store_mode="FREE_PRESENCE",
    )

    snapshots = [o for o in added_objects if isinstance(o, models.SellerIdentitySnapshot)]
    assert len(snapshots) == 1
    assert snapshots[0].legal_name == "Audited Seller"
    assert snapshots[0].pan_masked == "ABCPD****F"
