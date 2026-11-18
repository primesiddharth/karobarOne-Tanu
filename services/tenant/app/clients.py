# app/clients.py
# External provider adapters: PAN & GSTIN verifiers conforming to Integration Spec §11.
import structlog
from . import domain

logger = structlog.get_logger("tenant.clients")


async def verify_pan_with_provider(pan: str) -> dict:
    """
    STUB(tenant, OQ-023): Mock PAN verification adapter.
    Validates synthetic PAN and returns verified identity payload.
    """
    norm_pan = domain.validate_pan_format(pan)
    logger.info("pan_verification_requested", pan_masked=domain.mask_pan(norm_pan))

    # Reject synthetic PANs ending with 'X' for negative testing
    if norm_pan.endswith("X"):
        return {
            "verified": False,
            "provider_code": "MOCK_V1",
            "reference": f"REF-PAN-{norm_pan}",
            "error": "PAN not found with provider",
        }

    return {
        "verified": True,
        "provider_code": "MOCK_V1",
        "reference": f"REF-PAN-{norm_pan}",
        "registered_name": "VERIFIED LEGAL ENTITY",
        "entity_type": domain.extract_pan_entity_type(norm_pan),
    }


async def verify_gstin_with_provider(gstin: str, tenant_pan: str) -> dict:
    """
    STUB(tenant, OQ-023): Mock GSTIN verification adapter.
    Enforces statutory match: GSTIN characters 3..12 must equal tenant PAN (AC-036/037).
    """
    norm_gstin = domain.validate_gstin_format(gstin)
    norm_pan = domain.validate_pan_format(tenant_pan)
    logger.info("gstin_verification_requested", gstin_masked=domain.mask_gstin(norm_gstin))

    # Statutory PAN-GSTIN match check
    domain.validate_gstin_pan_match(norm_gstin, norm_pan)

    # Reject synthetic GSTINs ending with 'X' for negative testing
    if norm_gstin.endswith("X"):
        return {
            "verified": False,
            "provider_code": "MOCK_V1",
            "reference": f"REF-GST-{norm_gstin}",
            "error": "GSTIN inactive or cancelled by tax authority",
        }

    return {
        "verified": True,
        "provider_code": "MOCK_V1",
        "reference": f"REF-GST-{norm_gstin}",
        "state_code": norm_gstin[:2],
        "legal_name": "VERIFIED GSTIN HOLDER",
    }
