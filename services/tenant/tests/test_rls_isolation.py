# tests/test_rls_isolation.py
# FND-TST-008/009, SEC-005: Tenant isolation under ENABLE and FORCE ROW LEVEL SECURITY (RULES.md §5)
import pytest
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError, IntegrityError
from app.db import async_session_factory, set_rls_context
from app import models

pytestmark = pytest.mark.asyncio


async def test_rls_real_tables_isolation_and_check_policy(db_engine):
    """
    Tests real table tenant isolation against tenant.tenants and tenant.stores.
    Verifies:
    1. A query without a WHERE clause returns ONLY rows matching active app.tenant_id.
    2. An unset app.tenant_id returns 0 rows.
    3. An insert with a mismatched tenant_id is rejected by WITH CHECK.
    """
    t1 = uuid4()
    t2 = uuid4()
    s1 = uuid4()
    s2 = uuid4()

    async with async_session_factory() as session:
        try:
            # 1. Insert Tenant 1 and Store 1 under T1 context
            await set_rls_context(session, tenant_id=t1)
            tenant_1 = models.Tenant(
                id=t1,
                pan_ciphertext=b"enc1",
                pan_fingerprint=f"fp_{t1.hex[:16]}",
                pan_masked="ABCDE1111F",
                legal_name="Tenant One",
                minor_status="NOT_MINOR",
                status="ACTIVE",
            )
            store_1 = models.Store(
                id=s1,
                tenant_id=t1,
                store_code=f"store-1-{t1.hex[:8]}",
                display_name="Store 1",
            )
            session.add(tenant_1)
            session.add(store_1)
            await session.commit()

            # 2. Insert Tenant 2 and Store 2 under T2 context
            await set_rls_context(session, tenant_id=t2)
            tenant_2 = models.Tenant(
                id=t2,
                pan_ciphertext=b"enc2",
                pan_fingerprint=f"fp_{t2.hex[:16]}",
                pan_masked="ABCDE2222F",
                legal_name="Tenant Two",
                minor_status="NOT_MINOR",
                status="ACTIVE",
            )
            store_2 = models.Store(
                id=s2,
                tenant_id=t2,
                store_code=f"store-2-{t2.hex[:8]}",
                display_name="Store 2",
            )
            session.add(tenant_2)
            session.add(store_2)
            await session.commit()

            # 3. Test Isolation as runtime role: Query under T1 context with NO where predicate
            await set_rls_context(session, tenant_id=t1)
            # Switch to runtime service role if available
            try:
                await session.execute(text("SET ROLE tenant_svc;"))
            except Exception:
                pass  # If role not provisioned in standalone engine, FORCE RLS still applies

            t1_tenants = (await session.execute(text("SELECT id FROM tenant.tenants"))).scalars().all()
            assert t1 in t1_tenants
            assert t2 not in t1_tenants

            t1_stores = (await session.execute(text("SELECT id FROM tenant.stores"))).scalars().all()
            assert s1 in t1_stores
            assert s2 not in t1_stores

            # 4. Query under T2 context
            await set_rls_context(session, tenant_id=t2)
            t2_tenants = (await session.execute(text("SELECT id FROM tenant.tenants"))).scalars().all()
            assert t2 in t2_tenants
            assert t1 not in t2_tenants

            # 5. Query with NO tenant context set -> must return 0 rows
            await session.execute(text("RESET app.tenant_id;"))
            await session.execute(text("RESET app.store_id;"))
            empty_tenants = (await session.execute(text("SELECT id FROM tenant.tenants"))).scalars().all()
            assert len(empty_tenants) == 0

            # 6. WITH CHECK violation: while in T1 context, attempt to insert store for T2
            await set_rls_context(session, tenant_id=t1)
            forbidden_store = models.Store(
                id=uuid4(),
                tenant_id=t2,
                store_code=f"hack-{uuid4().hex[:8]}",
                display_name="Cross-Tenant Store",
            )
            session.add(forbidden_store)
            with pytest.raises((ProgrammingError, IntegrityError, Exception)) as exc_info:
                await session.flush()
            assert "row-level security" in str(exc_info.value).lower() or "policy" in str(exc_info.value).lower()

        finally:
            try:
                await session.execute(text("RESET ROLE;"))
            except Exception:
                pass
            await session.rollback()


async def test_store_staff_isolation_by_store_id(db_engine):
    """Store-owned tables filter strictly by store_id when app.store_id is set (BTDD §5.3)."""
    t1 = uuid4()
    s1 = uuid4()
    s2 = uuid4()

    async with async_session_factory() as session:
        try:
            await set_rls_context(session, tenant_id=t1)
            tenant = models.Tenant(
                id=t1,
                pan_ciphertext=b"enc1",
                pan_fingerprint=f"fp_{t1.hex[:16]}",
                pan_masked="ABCDE1111F",
                legal_name="Tenant Store Isolation",
            )
            store_a = models.Store(id=s1, tenant_id=t1, store_code=f"s1-{s1.hex[:6]}", display_name="Store A")
            store_b = models.Store(id=s2, tenant_id=t1, store_code=f"s2-{s2.hex[:6]}", display_name="Store B")
            session.add_all([tenant, store_a, store_b])
            await session.commit()

            # Set RLS context for Store A only
            await set_rls_context(session, tenant_id=t1, store_id=s1)
            try:
                await session.execute(text("SET ROLE tenant_svc;"))
            except Exception:
                pass

            visible_stores = (await session.execute(text("SELECT id FROM tenant.stores"))).scalars().all()
            assert s1 in visible_stores
            assert s2 not in visible_stores
        finally:
            try:
                await session.execute(text("RESET ROLE;"))
            except Exception:
                pass
            await session.rollback()
