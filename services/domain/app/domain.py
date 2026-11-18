# app/domain.py
# Pure business logic and validation rules for Domain & Publication service (SERVICES.md §5, State Machine §6, AC-084).
import re
from typing import Set
from libs.platform_contracts.errors import ApiError, ErrorCode

# Subdomain slug regex: 3 to 63 lowercase alphanumeric characters, hyphens allowed internally
SUBDOMAIN_REGEX = re.compile(r"^[a-z0-9]([a-z0-9-]{1,61}[a-z0-9])?$")

# Reserved and system subdomains prohibited from tenant registration
RESERVED_SUBDOMAINS: Set[str] = {
    "admin",
    "api",
    "app",
    "auth",
    "billing",
    "cdn",
    "dashboard",
    "gateway",
    "help",
    "karobarone",
    "mail",
    "root",
    "static",
    "status",
    "support",
    "www",
}


def sanitize_subdomain_label(raw_slug: str) -> str:
    """Validates and normalizes subdomain slug to lowercase format."""
    if not raw_slug or not raw_slug.strip():
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message="Subdomain slug is required",
            status_code=422,
        )

    slug = raw_slug.strip().lower()

    if len(slug) < 3 or len(slug) > 63:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message=f"Subdomain label length must be between 3 and 63 characters (got {len(slug)})",
            status_code=422,
        )

    if not SUBDOMAIN_REGEX.match(slug):
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message="Subdomain must contain only lowercase letters, numbers, and internal hyphens",
            status_code=422,
        )

    if slug in RESERVED_SUBDOMAINS:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message=f"Subdomain '{slug}' is reserved by the platform",
            status_code=409,
        )

    return slug


def build_fqdn(slug: str, root_domain: str = "karobarone.com") -> str:
    """Constructs fully-qualified domain name (FQDN)."""
    return f"{slug}.{root_domain.lower()}"


def validate_publication_gates(
    plan_tier: str,
    has_subdomain: bool,
    has_verified_custom_domain: bool = False,
    is_content_approved: bool = True,
) -> bool:
    """Validates publication readiness gates per plan tier (AC-084, AC-085)."""
    if plan_tier.upper() != "FREE" and not has_verified_custom_domain:
        raise ApiError(
            code=ErrorCode.CUSTOM_DOMAIN_REQUIRED,
            message="Paid public launch requires a verified custom domain",
            status_code=409,
        )

    if not has_subdomain:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message="Cannot publish store without an assigned subdomain",
            status_code=409,
        )

    if not is_content_approved:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message="Publication requires approved content revision",
            status_code=409,
        )

    return True


STANDARD_TLDS = {".in", ".co.in", ".com"}


def classify_domain_cost(domain_name: str) -> dict:
    """Classifies domain as standard (included) or premium (surcharge) (AC-086, AC-087)."""
    clean_domain = domain_name.strip().lower()
    is_standard = any(clean_domain.endswith(tld) for tld in STANDARD_TLDS) and not clean_domain.startswith("premium-")

    if is_standard:
        return {
            "domain_name": clean_domain,
            "is_premium": False,
            "cost_treatment": "INCLUDED_IN_PLAN",
            "additional_payment_required": False,
            "approval_required": False,
        }
    else:
        return {
            "domain_name": clean_domain,
            "is_premium": True,
            "cost_treatment": "PREMIUM_SURCHARGE",
            "additional_payment_required": True,
            "approval_required": True,
        }


def initiate_domain_transfer_review(store_status: str, domain_name: str) -> dict:
    """Creates a manual transfer review case on store closure (AC-088). Transfer is never automatic."""
    return {
        "domain_name": domain_name.strip().lower(),
        "store_status": store_status,
        "case_status": "MANUAL_REVIEW_OPENED",
        "automatic_transfer": False,
        "review_reason": "STORE_CLOSURE_POST_REVIEW",
    }

