# tests/test_rls_isolation.py
# FND-TST-008/009, SEC-005: Customer tenant & store isolation, migrator bypass, and platform admin access
import pytest
from uuid import uuid4
from sqlalchemy import text
from app.db import async_session_factory, set_rls_context
from app import models

pytestmark = pytest.mark.asyncio


async def test_customer_tenant_and_store_isolation(db_engine):
    """
    Tests:
    1. Tenant 1 / Store 1 cannot see or access Tenant 2 / Store 2 customers.
    2. Platform admin can access across stores when app.is_platform_admin = 'true'.
    3. Migrator role has full access without flags (FORCE RLS bypass via policy).
    """
    t1 = uuid4()
    t2 = uuid4()
    s1 = uuid4()
    s2 = uuid4()
    c1_id = uuid4()
    c2_id = uuid4()

    async with async_session_factory() as session:
        try:
            # 1. Insert seed data as migrator/super
            await set_rls_context(session, tenant_id=t1, store_id=s1)
            cust1 = models.Customer(
                id=c1_id,
                tenant_id=t1,
                store_id=s1,
                email="cust1@example.com",
                mobile_e164="+919876543210",
                status="UNCLAIMED",
            )
            session.add(cust1)

            cust2 = models.Customer(
                id=c2_id,
                tenant_id=t2,
                store_id=s2,
                email="cust2@example.com",
                mobile_e164="+919876543211",
                status="UNCLAIMED",
            )
            session.add(cust2)
            await session.commit()

            # 2. Switch to runtime role customer_svc
            try:
                await session.execute(text("SET ROLE customer_svc;"))
            except Exception:
                pytest.skip("Role customer_svc not provisioned in current test database")

            # 3. Query under Tenant 1 context -> must only see cust1
            await set_rls_context(session, tenant_id=t1, store_id=s1)
            res1 = (await session.execute(text("SELECT id FROM customer.customers WHERE id = :id"), {"id": str(c1_id)})).fetchall()
            assert len(res1) == 1

            res2 = (await session.execute(text("SELECT id FROM customer.customers WHERE id = :id"), {"id": str(c2_id)})).fetchall()
            assert len(res2) == 0  # Tenant 2 customer invisible

            # 4. Query under Platform Admin context -> sees both
            await set_rls_context(session, tenant_id=None, store_id=None, is_platform_admin=True)
            res_admin = (await session.execute(text("SELECT id FROM customer.customers WHERE id IN (:c1, :c2)"),
                                              {"c1": str(c1_id), "c2": str(c2_id)})).fetchall()
            assert len(res_admin) == 2

            # 5. Switch to customer_migrator -> verifies migrator bypass policy works with FORCE RLS
            await session.execute(text("RESET ROLE;"))
            try:
                await session.execute(text("SET ROLE customer_migrator;"))
            except Exception:
                pytest.skip("Role customer_migrator not provisioned in current test database")

            res_migrator = (await session.execute(text("SELECT id FROM customer.customers WHERE id IN (:c1, :c2)"),
                                                  {"c1": str(c1_id), "c2": str(c2_id)})).fetchall()
            assert len(res_migrator) == 2

        finally:
            try:
                await session.execute(text("RESET ROLE;"))
            except Exception:
                pass
            await session.rollback()
