# tests/acceptance/test_ac_domain.py
# Acceptance Criteria test suite for Domain & Publication service (SERVICES.md §5, ROADMAP Phase 6).
# Function names follow test_ac_NNN_* pattern checked by tools/check_ac_coverage.py.
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError, ErrorCode
from app import commands, domain, models

pytestmark = pytest.mark.asyncio


def make_mock_session(execute_results=None):
    """Helper creating mock AsyncSession that returns queued results and handles outbox inserts."""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()

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


async def test_ac_084_free_subdomain_unique_and_immutable():
    """Free subdomain is immutable and unique across platform (AC-084).

    Given a Free Store already has an assigned subdomain.
    When attempting to rename/change Free subdomain, mutation is rejected; original Free subdomain remains immutable.
    When another store attempts to claim the same slug, it is rejected with 409 INVALID_STATE_TRANSITION.
    """
    store_id = uuid4()
    tenant_id = uuid4()
    owner_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[tenant_id],
        store_ids=[store_id],
    )

    # 1. Successful assignment
    res_sub_none = MagicMock()
    res_sub_none.scalars.return_value.first.return_value = None
    res_dup_none = MagicMock()
    res_dup_none.scalars.return_value.first.return_value = None

    session = make_mock_session([res_sub_none, res_dup_none])
    sub = await commands.assign_subdomain_command(
        session=session,
        store_id=store_id,
        slug="my-art-store",
        principal=owner_principal,
    )
    assert sub.label == "my-art-store"
    assert sub.fqdn == "my-art-store.karobarone.com"
    assert sub.status == "ASSIGNED"
    assert session.add.call_count == 2  # Subdomain + PublicationRoute

    # 2. Re-assignment / Rename attempt on same store -> REJECTED (AC-084: immutable once created)
    res_sub_existing = MagicMock()
    res_sub_existing.scalars.return_value.first.return_value = sub

    session2 = make_mock_session([res_sub_existing])
    with pytest.raises(ApiError) as exc_info:
        await commands.assign_subdomain_command(
            session=session2,
            store_id=store_id,
            slug="new-art-store",
            principal=owner_principal,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION
    assert "immutable once assigned" in exc_info.value.message

    # 3. Duplicate slug for different store -> REJECTED (uniqueness across platform)
    other_store_id = uuid4()
    other_principal = Principal(
        sub=uuid4(),
        roles=["STORE_OWNER"],
        tenant_ids=[uuid4()],
        store_ids=[other_store_id],
    )
    res_other_sub_none = MagicMock()
    res_other_sub_none.scalars.return_value.first.return_value = None
    res_dup_found = MagicMock()
    res_dup_found.scalars.return_value.first.return_value = sub  # Already claimed

    session3 = make_mock_session([res_other_sub_none, res_dup_found])
    with pytest.raises(ApiError) as exc_info:
        await commands.assign_subdomain_command(
            session=session3,
            store_id=other_store_id,
            slug="my-art-store",
            principal=other_principal,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.INVALID_STATE_TRANSITION
    assert "already assigned" in exc_info.value.message


async def test_ac_085_paid_public_launch_requires_custom_domain():
    """Paid public launch requires verified custom domain (AC-085).

    Given a paid store has active subscription but no verified custom domain.
    When attempting paid public launch.
    Then publication is blocked with CUSTOM_DOMAIN_REQUIRED until custom domain/DNS readiness is satisfied.
    """
    # Free tier passes with free subdomain and approved content
    assert domain.validate_publication_gates(
        plan_tier="FREE",
        has_subdomain=True,
        has_verified_custom_domain=False,
        is_content_approved=True,
    ) is True

    # Paid tier without verified custom domain is blocked
    with pytest.raises(ApiError) as exc_info:
        domain.validate_publication_gates(
            plan_tier="COMMERCE_CORE",
            has_subdomain=True,
            has_verified_custom_domain=False,
            is_content_approved=True,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.CUSTOM_DOMAIN_REQUIRED

    # Paid tier with verified custom domain succeeds
    assert domain.validate_publication_gates(
        plan_tier="GROWTH",
        has_subdomain=True,
        has_verified_custom_domain=True,
        is_content_approved=True,
    ) is True


async def test_ac_086_standard_qualifying_domain_cost_included():
    """Standard qualifying domain cost is included according to commercial policy (AC-086).

    Given a tenant selects a standard qualifying domain under active paid service.
    When domain charge treatment is calculated.
    Then standard qualifying domain cost is treated as included in plan policy; no premium surcharge is created.
    """
    treatment_in = domain.classify_domain_cost("mystore.in")
    assert treatment_in["is_premium"] is False
    assert treatment_in["cost_treatment"] == "INCLUDED_IN_PLAN"
    assert treatment_in["additional_payment_required"] is False
    assert treatment_in["approval_required"] is False

    treatment_com = domain.classify_domain_cost("brandname.com")
    assert treatment_com["is_premium"] is False
    assert treatment_com["cost_treatment"] == "INCLUDED_IN_PLAN"
    assert treatment_com["additional_payment_required"] is False


async def test_ac_087_premium_domain_requires_additional_approval_payment():
    """Premium domain requires additional approval and payment (AC-087).

    Given a selected domain is classified premium/non-standard.
    When calculating purchase treatment.
    Then purchase is blocked until explicit approval and required additional payment are satisfied.
    """
    treatment_tech = domain.classify_domain_cost("metaverse.tech")
    assert treatment_tech["is_premium"] is True
    assert treatment_tech["cost_treatment"] == "PREMIUM_SURCHARGE"
    assert treatment_tech["additional_payment_required"] is True
    assert treatment_tech["approval_required"] is True

    treatment_prefix = domain.classify_domain_cost("premium-luxury.in")
    assert treatment_prefix["is_premium"] is True
    assert treatment_prefix["additional_payment_required"] is True


async def test_ac_088_domain_transfer_after_closure_not_automatic():
    """Domain transfer after store closure is not automatic (AC-088).

    Given a store is closed and tenant requests domain transfer.
    When transfer review request is submitted.
    Then transfer is not automatic; a manual review case is opened and outcome remains separate from closure.
    """
    case = domain.initiate_domain_transfer_review(
        store_status="CLOSED",
        domain_name="mybakery.com",
    )
    assert case["automatic_transfer"] is False
    assert case["case_status"] == "MANUAL_REVIEW_OPENED"
    assert case["review_reason"] == "STORE_CLOSURE_POST_REVIEW"
