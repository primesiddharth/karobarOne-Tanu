# tests/test_tenant_domain.py
# Pure unit tests for Tenant domain rules: PAN/GSTIN validation, PII encryption,
# blind indexing, age calculations, turns-18 boundaries, and entitlement guards.
import pytest
from datetime import date, timedelta
from uuid import uuid4
from app.config import settings
from app import domain


def test_pan_validation_and_masking():
    """Validates PAN format, entity extraction, and safe masking (RULES.md §5.10)."""
    valid_indiv_pan = "ABCPD1234F"
    assert domain.validate_pan_format(valid_indiv_pan) == "ABCPD1234F"
    assert domain.extract_pan_entity_type(valid_indiv_pan) == "INDIVIDUAL"
    assert domain.mask_pan(valid_indiv_pan) == "ABCPD****F"

    valid_company_pan = "AAACT1234G"
    assert domain.extract_pan_entity_type(valid_company_pan) == "COMPANY"

    with pytest.raises(ValueError, match="Invalid PAN format"):
        domain.validate_pan_format("INVALID123")


def test_gstin_validation_and_pan_match():
    """Validates GSTIN format and statutory match with tenant PAN (AC-036/037)."""
    tenant_pan = "ABCDE1234F"
    valid_gstin = "27ABCDE1234F1Z5"

    assert domain.validate_gstin_format(valid_gstin) == "27ABCDE1234F1Z5"
    assert domain.mask_gstin(valid_gstin) == "27ABCDE****1Z5"

    # Must match tenant PAN
    domain.validate_gstin_pan_match(valid_gstin, tenant_pan)

    # Mismatched PAN raises GSTIN_NOT_OWNED error
    mismatched_gstin = "27XYZAB9999K1Z5"
    with pytest.raises(ValueError, match="GSTIN_NOT_OWNED"):
        domain.validate_gstin_pan_match(mismatched_gstin, tenant_pan)


def test_blind_indexing_determinism():
    """HMAC-SHA256 blind indexing produces identical hash for identical PAN/GSTIN."""
    pan1 = "ABCDE1234F"
    pan2 = "abcde1234f"  # lowercase input
    fp1 = domain.compute_blind_fingerprint(pan1, settings.HMAC_SECRET_KEY)
    fp2 = domain.compute_blind_fingerprint(pan2, settings.HMAC_SECRET_KEY)

    assert fp1 == fp2
    assert len(fp1) == 64


def test_pii_encryption_and_decryption():
    """Fernet (AES-128-CBC + HMAC-SHA256) encrypts PAN/GSTIN and decrypts to original uppercase plaintext."""
    pan = "ABCDE1234F"
    ciphertext = domain.encrypt_pii(pan, settings.PII_ENCRYPTION_KEY)
    assert ciphertext != pan.encode("utf-8")
    assert b"ABCDE1234F" not in ciphertext

    decrypted = domain.decrypt_pii(ciphertext, settings.PII_ENCRYPTION_KEY)
    assert decrypted == pan


def test_age_calculation_and_minor_status():
    """Calculates age and flags GUARDIAN_REQUIRED for registrants under 18 (AC-035)."""
    today = date(2026, 11, 4)

    # 17 years old -> GUARDIAN_REQUIRED
    dob_minor = date(2009, 11, 5)  # Turns 17 tomorrow, currently 16 (or 17)
    assert domain.calculate_age(dob_minor, today) == 16
    assert domain.evaluate_minor_status(dob_minor, today) == "GUARDIAN_REQUIRED"

    # 18 years old -> NOT_MINOR
    dob_adult = date(2008, 11, 4)  # Exactly 18 today
    assert domain.calculate_age(dob_adult, today) == 18
    assert domain.evaluate_minor_status(dob_adult, today) == "NOT_MINOR"


def test_turns_18_boundary_conditions():
    """Boundary test for turns-18 detection (AC-040)."""
    reference_date = date(2026, 11, 4)

    # Day before 18th birthday: still 17 -> False
    dob_day_before = date(2008, 11, 5)
    assert domain.should_transition_turns_18(dob_day_before, "MINOR_TENANT_ACTIVE", reference_date) is False

    # Exact 18th birthday: turns 18 today -> True
    dob_exact = date(2008, 11, 4)
    assert domain.should_transition_turns_18(dob_exact, "MINOR_TENANT_ACTIVE", reference_date) is True

    # Day after 18th birthday: already 18 -> True
    dob_day_after = date(2008, 11, 3)
    assert domain.should_transition_turns_18(dob_day_after, "MINOR_TENANT_ACTIVE", reference_date) is True

    # If tenant is NOT in MINOR_TENANT_ACTIVE state, should not transition
    assert domain.should_transition_turns_18(dob_exact, "NOT_MINOR", reference_date) is False


def test_free_store_entitlement_guard():
    """AVAILABLE entitlement passes; CONSUMED raises error (AC-002)."""
    domain.check_free_store_entitlement("AVAILABLE")

    with pytest.raises(ValueError, match="FREE_STORE_ENTITLEMENT_CONSUMED"):
        domain.check_free_store_entitlement("CONSUMED")
