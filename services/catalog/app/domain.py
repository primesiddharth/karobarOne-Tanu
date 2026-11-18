# app/domain.py
# Pure business logic and entitlement rules for Catalog & CMS service (RULES.md §5, SERVICES.md §4, State Machine §5)
import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Set
from libs.platform_contracts.errors import ApiError, ErrorCode

VALID_PAGE_TYPES: Set[str] = {
    "hero", "about", "usp", "contact", "policy", "marquee", "home", "terms", "privacy", "custom"
}

VALID_ITEM_TYPES: Set[str] = {
    "PHYSICAL_PRODUCT",
    "DIGITAL_PRODUCT",
    "APPOINTMENT_SERVICE",
    "NON_APPOINTMENT_SERVICE",
}

VALID_MEDIA_TYPES: Set[str] = {"IMAGE", "VIDEO"}

# Entitlement Limits per Plan Tier (SERVICES.md §4, AC-004..007, AC-012..014)
PLAN_MEDIA_LIMITS: dict[str, dict[str, int]] = {
    "FREE": {"max_images": 1, "max_videos": 0, "max_items": 6},
    "COMMERCE": {"max_images": 5, "max_videos": 0, "max_items": 1_000_000},
    "GROWTH": {"max_images": 10, "max_videos": 1, "max_items": 1_000_000},
    "SCALE_AI": {"max_images": 50, "max_videos": 5, "max_items": 1_000_000},
}


def parse_price_to_paise(price_str: str) -> int:
    """Parses decimal string to integer paise without float conversions (RULES.md §5.7)."""
    try:
        dec = Decimal(price_str)
        if dec < 0:
            raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Price cannot be negative", status_code=422)
        # Check precision: max 2 decimal places
        if dec.as_tuple().exponent < -2:
            raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Price cannot have more than 2 decimal places", status_code=422)
        return int(dec * 100)
    except (InvalidOperation, ValueError, TypeError):
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Invalid price format: {price_str}", status_code=422)


def format_paise_to_decimal_str(paise: int) -> str:
    """Formats integer paise into a standard decimal string (RULES.md §5.7)."""
    dec = Decimal(paise) / Decimal(100)
    return f"{dec:.2f}"


def validate_item_type(item_type: str) -> None:
    """Ensures item_type is one of the four supported statutory types."""
    if item_type not in VALID_ITEM_TYPES:
        raise ApiError(
            code=ErrorCode.INVALID_STATE_TRANSITION,
            message=f"Unsupported item type: {item_type}",
            status_code=422,
        )


def validate_item_creation_entitlement(
    plan_tier: str,
    current_active_item_count: int,
) -> None:
    """Enforces item count limit: Free <= 6 combined showcase items (AC-004, AC-006)."""
    limits = PLAN_MEDIA_LIMITS.get(plan_tier.upper(), PLAN_MEDIA_LIMITS["FREE"])
    max_items = limits["max_items"]

    if current_active_item_count >= max_items:
        raise ApiError(
            code=ErrorCode.ENTITLEMENT_REQUIRED,
            message=f"Store plan ({plan_tier}) allows maximum {max_items} showcase items",
            status_code=403,
        )


def validate_media_attachment_entitlement(
    plan_tier: str,
    current_image_count: int,
    current_video_count: int,
    media_type: str,
) -> None:
    """Enforces media boundaries per plan tier (AC-005, AC-012, AC-013, AC-014)."""
    if media_type not in VALID_MEDIA_TYPES:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, f"Invalid media type: {media_type}", status_code=422)

    limits = PLAN_MEDIA_LIMITS.get(plan_tier.upper(), PLAN_MEDIA_LIMITS["FREE"])
    max_images = limits["max_images"]
    max_videos = limits["max_videos"]

    if media_type == "IMAGE":
        if current_image_count >= max_images:
            raise ApiError(
                code=ErrorCode.ENTITLEMENT_REQUIRED,
                message=f"Plan {plan_tier} allows maximum {max_images} image(s) per item",
                status_code=403,
            )
    elif media_type == "VIDEO":
        if current_video_count >= max_videos:
            raise ApiError(
                code=ErrorCode.ENTITLEMENT_REQUIRED,
                message=f"Plan {plan_tier} allows maximum {max_videos} video(s) per item",
                status_code=403,
            )


def validate_page_type(page_type: str) -> str:
    """Validates and normalizes page_type/content_section (DB Spec §7.5)."""
    norm = page_type.strip().lower()
    if not norm or len(norm) > 32:
        raise ApiError(ErrorCode.INVALID_STATE_TRANSITION, "Invalid page_type length", status_code=422)
    return norm


def compute_content_hash(content_json: dict) -> str:
    """Computes SHA-256 integrity hash of page content."""
    serialized = json.dumps(content_json, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
