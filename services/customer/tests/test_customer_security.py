# tests/test_customer_security.py
# Security tests: Cross-store IDOR prevention and customer role scope (RULES.md §6).
import pytest
from uuid import uuid4
from libs.platform_contracts.tokens import Principal
from libs.platform_contracts.errors import ApiError
from app import models
from app.routes import verify_customer_access


def test_customer_can_access_own_profile():
    principal_id = uuid4()
    cust = models.Customer(
        id=uuid4(),
        tenant_id=uuid4(),
        store_id=uuid4(),
        email="me@example.com",
        mobile_e164="+919876543210",
        status="CLAIMED",
        iam_principal_id=principal_id,
    )
    principal = Principal(sub=principal_id, roles=["CUSTOMER"], tenant_ids=[], store_ids=[])
    # Should not raise
    verify_customer_access(cust, principal)


def test_cross_customer_idor_prevented():
    cust = models.Customer(
        id=uuid4(),
        tenant_id=uuid4(),
        store_id=uuid4(),
        email="victim@example.com",
        mobile_e164="+919876543210",
        status="CLAIMED",
        iam_principal_id=uuid4(),
    )
    attacker_principal = Principal(sub=uuid4(), roles=["CUSTOMER"], tenant_ids=[], store_ids=[])
    with pytest.raises(ApiError) as exc_info:
        verify_customer_access(cust, attacker_principal)
    assert exc_info.value.status_code == 403


def test_cross_store_staff_idor_prevented():
    store_a = uuid4()
    store_b = uuid4()

    cust = models.Customer(
        id=uuid4(),
        tenant_id=uuid4(),
        store_id=store_a,
        email="customer_a@example.com",
        mobile_e164="+919876543210",
        status="UNCLAIMED",
    )
    staff_store_b = Principal(sub=uuid4(), roles=["STORE_STAFF"], tenant_ids=[uuid4()], store_ids=[store_b])

    with pytest.raises(ApiError) as exc_info:
        verify_customer_access(cust, staff_store_b)
    assert exc_info.value.status_code == 403


def test_assigned_store_staff_can_access_store_customer():
    store_a = uuid4()
    cust = models.Customer(
        id=uuid4(),
        tenant_id=uuid4(),
        store_id=store_a,
        email="customer_a@example.com",
        mobile_e164="+919876543210",
        status="UNCLAIMED",
    )
    staff_store_a = Principal(sub=uuid4(), roles=["STORE_STAFF"], tenant_ids=[uuid4()], store_ids=[store_a])
    verify_customer_access(cust, staff_store_a)


def test_platform_staff_can_access_any_store_customer():
    cust = models.Customer(
        id=uuid4(),
        tenant_id=uuid4(),
        store_id=uuid4(),
        email="customer@example.com",
        mobile_e164="+919876543210",
        status="UNCLAIMED",
    )
    admin_principal = Principal(sub=uuid4(), roles=["PLATFORM_OWNER"], tenant_ids=[], store_ids=[])
    verify_customer_access(cust, admin_principal)
