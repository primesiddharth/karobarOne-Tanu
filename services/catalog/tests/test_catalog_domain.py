# tests/test_catalog_domain.py
# Pure business logic and domain validation tests for Catalog & CMS (RULES.md §5.7, APR-R02).
import pytest
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import domain


def test_parse_price_to_paise():
    """Parses decimal string to integer paise without float errors (RULES.md §5.7)."""
    assert domain.parse_price_to_paise("0.00") == 0
    assert domain.parse_price_to_paise("199.00") == 19900
    assert domain.parse_price_to_paise("0.50") == 50
    assert domain.parse_price_to_paise("100") == 10000
    assert domain.parse_price_to_paise("99.99") == 9999

    # Negative price rejected
    with pytest.raises(ApiError) as exc_info:
        domain.parse_price_to_paise("-10.00")
    assert exc_info.value.status_code == 422

    # More than 2 decimal places rejected
    with pytest.raises(ApiError) as exc_info:
        domain.parse_price_to_paise("10.555")
    assert exc_info.value.status_code == 422

    # Malformed string rejected
    with pytest.raises(ApiError) as exc_info:
        domain.parse_price_to_paise("abc")
    assert exc_info.value.status_code == 422


def test_format_paise_to_decimal_str():
    """Formats integer paise into standard 2-decimal string."""
    assert domain.format_paise_to_decimal_str(0) == "0.00"
    assert domain.format_paise_to_decimal_str(19900) == "199.00"
    assert domain.format_paise_to_decimal_str(50) == "0.50"
    assert domain.format_paise_to_decimal_str(9999) == "99.99"


def test_validate_item_types():
    """Validates permitted item types."""
    for it in ["PHYSICAL_PRODUCT", "DIGITAL_PRODUCT", "APPOINTMENT_SERVICE", "NON_APPOINTMENT_SERVICE"]:
        domain.validate_item_type(it)

    with pytest.raises(ApiError) as exc_info:
        domain.validate_item_type("INVALID_TYPE")
    assert exc_info.value.status_code == 422


def test_media_attachment_entitlement_rules():
    """Tests media boundary evaluations per plan tier."""
    # Free tier: 1 image, 0 video
    domain.validate_media_attachment_entitlement("FREE", 0, 0, "IMAGE")  # OK
    with pytest.raises(ApiError) as exc_info:
        domain.validate_media_attachment_entitlement("FREE", 1, 0, "IMAGE")
    assert exc_info.value.status_code == 403

    with pytest.raises(ApiError) as exc_info:
        domain.validate_media_attachment_entitlement("FREE", 0, 0, "VIDEO")
    assert exc_info.value.status_code == 403

    # Commerce: 5 images, 0 video
    domain.validate_media_attachment_entitlement("COMMERCE", 4, 0, "IMAGE")  # OK
    with pytest.raises(ApiError) as exc_info:
        domain.validate_media_attachment_entitlement("COMMERCE", 5, 0, "IMAGE")
    assert exc_info.value.status_code == 403

    with pytest.raises(ApiError) as exc_info:
        domain.validate_media_attachment_entitlement("COMMERCE", 0, 0, "VIDEO")
    assert exc_info.value.status_code == 403

    # Growth: 10 images, 1 video
    domain.validate_media_attachment_entitlement("GROWTH", 9, 0, "IMAGE")  # OK
    domain.validate_media_attachment_entitlement("GROWTH", 5, 0, "VIDEO")  # OK
    with pytest.raises(ApiError) as exc_info:
        domain.validate_media_attachment_entitlement("GROWTH", 10, 0, "IMAGE")
    assert exc_info.value.status_code == 403

    with pytest.raises(ApiError) as exc_info:
        domain.validate_media_attachment_entitlement("GROWTH", 5, 1, "VIDEO")
    assert exc_info.value.status_code == 403


def test_validate_page_type_and_content_hash():
    """CAT-007 domain tests: page section normalization and deterministic integrity hashing."""
    assert domain.validate_page_type("HERO") == "hero"
    assert domain.validate_page_type(" about ") == "about"

    with pytest.raises(ApiError):
        domain.validate_page_type("")

    with pytest.raises(ApiError):
        domain.validate_page_type("x" * 33)

    hash1 = domain.compute_content_hash({"title": "Karobar", "subtitle": "Bharat"})
    hash2 = domain.compute_content_hash({"subtitle": "Bharat", "title": "Karobar"})
    assert hash1 == hash2
    assert len(hash1) == 64
