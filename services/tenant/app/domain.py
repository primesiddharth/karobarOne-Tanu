# app/domain.py
# Pure business rules: state transition tables, PAN/GSTIN cryptography, age calculations, guards.
# Strictly NO imports of FastAPI, SQLAlchemy, or httpx (RULES.md §3).
import re
import hmac
import hashlib
from datetime import date, datetime, timezone
from uuid import UUID
from cryptography.fernet import Fernet


# ------------------------------------------------------------------------------
# State Transition Tables (State Machine §4 TEN-01..08 & §5)
# ------------------------------------------------------------------------------
ALLOWED_TENANT_STATUS_TRANSITIONS = {
    "PENDING": {"ACTIVE", "SUSPENDED", "TERMINATED"},
    "ACTIVE": {"SUSPENDED", "ARCHIVED", "TERMINATED"},
    "SUSPENDED": {"ACTIVE", "ARCHIVED", "TERMINATED"},
    "ARCHIVED": set(),
    "TERMINATED": set(),
}

ALLOWED_MINOR_STATUS_TRANSITIONS = {
    "NOT_MINOR": set(),
    "GUARDIAN_REQUIRED": {"GUARDIAN_VERIFICATION"},
    "GUARDIAN_VERIFICATION": {"CONSENT_ACCEPTED", "GUARDIAN_REQUIRED"},
    "CONSENT_ACCEPTED": {"MINOR_TENANT_ACTIVE"},
    "MINOR_TENANT_ACTIVE": {"ADULT_REVERIFICATION_REQUIRED"},
    "ADULT_REVERIFICATION_REQUIRED": {"NOT_MINOR"},
}

ALLOWED_STORE_LIFECYCLE_TRANSITIONS = {
    "DRAFT": {"REVIEW", "ACTIVE", "ARCHIVED"},
    "REVIEW": {"ACTIVE", "DRAFT", "ARCHIVED"},
    "ACTIVE": {"PAYMENT_GRACE", "SUBSCRIPTION_EXPIRED", "SUSPENDED", "ARCHIVED"},
    "PAYMENT_GRACE": {"ACTIVE", "SUBSCRIPTION_EXPIRED", "SUSPENDED", "ARCHIVED"},
    "SUBSCRIPTION_EXPIRED": {"ACTIVE", "ARCHIVED"},
    "SUSPENDED": {"ACTIVE", "ARCHIVED", "TERMINATED"},
    "ARCHIVED": set(),
    "TERMINATED": set(),
}


def assert_tenant_minor_transition(current: str, target: str) -> None:
    """Validates aggregate state transition for minor onboarding machine TEN-01..08."""
    allowed = ALLOWED_MINOR_STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(f"Invalid minor status transition from {current} to {target}")


def assert_store_transition(current: str, target: str) -> None:
    """Validates store lifecycle transition per SM §5."""
    allowed = ALLOWED_STORE_LIFECYCLE_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(f"Invalid store lifecycle transition from {current} to {target}")


# ------------------------------------------------------------------------------
# PAN & GSTIN Validation & Cryptography (RULES.md §5.10 & External Integration §11)
# ------------------------------------------------------------------------------
PAN_REGEX = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def validate_pan_format(pan: str) -> str:
    """Normalizes and validates Indian Income Tax Permanent Account Number (PAN)."""
    norm = pan.strip().upper()
    if not PAN_REGEX.match(norm):
        raise ValueError("Invalid PAN format. Must be 10 characters: 5 letters, 4 digits, 1 letter.")
    return norm


def extract_pan_entity_type(pan: str) -> str:
    """Extracts 4th character denoting taxpayer entity type."""
    norm = validate_pan_format(pan)
    code = norm[3]
    entity_map = {
        "P": "INDIVIDUAL",
        "C": "COMPANY",
        "H": "HUF",
        "F": "FIRM",
        "A": "ASSOCIATION_OF_PERSONS",
        "T": "TRUST",
        "B": "BODY_OF_INDIVIDUALS",
        "L": "LOCAL_AUTHORITY",
        "J": "ARTIFICIAL_JURIDICAL_PERSON",
        "G": "GOVERNMENT",
    }
    return entity_map.get(code, "OTHER")


def validate_gstin_format(gstin: str) -> str:
    """Normalizes and validates Goods and Services Tax Identification Number (GSTIN)."""
    norm = gstin.strip().upper()
    if not GSTIN_REGEX.match(norm):
        raise ValueError("Invalid GSTIN format. Must be 15 characters conforming to Indian GST standard.")
    return norm


def validate_gstin_pan_match(gstin: str, pan: str) -> None:
    """
    Enforces statutory ownership: GSTIN characters 3..12 must equal the tenant PAN (AC-036/037).
    """
    norm_gstin = validate_gstin_format(gstin)
    norm_pan = validate_pan_format(pan)
    embedded_pan = norm_gstin[2:12]
    if embedded_pan != norm_pan:
        raise ValueError(f"GSTIN {norm_gstin} does not belong to tenant PAN {norm_pan} (GSTIN_NOT_OWNED)")


def compute_blind_fingerprint(value: str, hmac_key: str) -> str:
    """Keyed HMAC-SHA256 blind index for database uniqueness without exposing plaintext."""
    norm = value.strip().upper()
    return hmac.new(hmac_key.encode("utf-8"), norm.encode("utf-8"), hashlib.sha256).hexdigest()


def mask_pan(pan: str) -> str:
    """Masks PAN for safe logging and display: ABCDE****F."""
    norm = validate_pan_format(pan)
    return f"{norm[:5]}****{norm[-1]}"


def mask_gstin(gstin: str) -> str:
    """Masks GSTIN for safe display: 27ABCDE****1Z5."""
    norm = validate_gstin_format(gstin)
    return f"{norm[:7]}****{norm[-3:]}"


def encrypt_pii(plaintext: str, encryption_key_b64: str) -> bytes:
    """Encrypts sensitive plaintext (PAN or GSTIN) using Fernet (AES-128-CBC + HMAC-SHA256)."""
    f = Fernet(encryption_key_b64.encode("utf-8"))
    return f.encrypt(plaintext.strip().upper().encode("utf-8"))


def decrypt_pii(ciphertext_bytes: bytes, encryption_key_b64: str) -> str:
    """Decrypts ciphertext back to uppercase plaintext."""
    f = Fernet(encryption_key_b64.encode("utf-8"))
    return f.decrypt(ciphertext_bytes).decode("utf-8")


# ------------------------------------------------------------------------------
# Age & Minor Verification Logic (State Machine §4, AC-035..040)
# ------------------------------------------------------------------------------
def calculate_age(dob: date, reference_date: date | None = None) -> int:
    """Calculates age in completed years as of reference date."""
    ref = reference_date or date.today()
    years = ref.year - dob.year
    if (ref.month, ref.day) < (dob.month, dob.day):
        years -= 1
    return years


def evaluate_minor_status(dob: date | None, reference_date: date | None = None) -> str:
    """
    Evaluates age on registration:
    - If no DOB provided -> default to NOT_MINOR
    - If age >= 18 -> NOT_MINOR (STANDARD_TENANT)
    - If age < 18 -> GUARDIAN_REQUIRED (AC-035)
    """
    if not dob:
        return "NOT_MINOR"
    age = calculate_age(dob, reference_date)
    return "GUARDIAN_REQUIRED" if age < 18 else "NOT_MINOR"


def should_transition_turns_18(dob: date, current_status: str, reference_date: date | None = None) -> bool:
    """
    Determines whether an active minor tenant has reached age 18 (AC-040).
    Only applies to tenants in MINOR_TENANT_ACTIVE.
    """
    if current_status != "MINOR_TENANT_ACTIVE":
        return False
    age = calculate_age(dob, reference_date)
    return age >= 18


# ------------------------------------------------------------------------------
# Free Store Entitlement Guard (AC-002, SM §5)
# ------------------------------------------------------------------------------
def check_free_store_entitlement(status: str) -> None:
    """Enforces one lifetime Free Store entitlement per tenant PAN (AC-002)."""
    if status != "AVAILABLE":
        raise ValueError("Free store entitlement already consumed (FREE_STORE_ENTITLEMENT_CONSUMED)")


# ------------------------------------------------------------------------------
# Idempotency Encryption Helper (RULES.md §5.10 & OQ-038)
# ------------------------------------------------------------------------------
def encrypt_idempotency_payload(payload_json: str, encryption_key_b64: str) -> str:
    f = Fernet(encryption_key_b64.encode("utf-8"))
    return f.encrypt(payload_json.encode("utf-8")).decode("utf-8")


def decrypt_idempotency_payload(encrypted_str: str, encryption_key_b64: str) -> str:
    f = Fernet(encryption_key_b64.encode("utf-8"))
    return f.decrypt(encrypted_str.encode("utf-8")).decode("utf-8")
