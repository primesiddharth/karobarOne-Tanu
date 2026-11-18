# tests/test_rls_isolation.py
# FND-TST-008/009, SEC-005: Subscription tenant & store isolation, migrator bypass, and platform admin access
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import text
from app.db import async_session_factory, set_rls_context
from app import models

pytestmark = pytest.mark.asyncio


async def test_subscription_tenant_and_store_isolation(db_engine):
    """
    Tests:
    1. Tenant 1 / Store 1 cannot see or access Tenant 2 / Store 2 subscriptions.
    2. Platform admin can access across stores when app.is_platform_admin = 'true'.
    3. Migrator role has full access without flags (FORCE RLS bypass via policy).
    """
    t1 = uuid4()
    t2 = uuid4()
    s1 = uuid4()
    s2 = uuid4()
    sub1_id = uuid4()
    sub2_id = uuid4()
    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        try:
            # Look up a plan version to bind
            pv_res = await session.execute(text("SELECT id FROM subscription.plan_versions LIMIT 1"))
            pv_id = pv_res.scalar()
            if not pv_id:
                pytest.skip("No plan_versions seeded in test database")

            # 1. Insert seed data as migrator/super
            await set_rls_context(session, tenant_id=t1, store_id=s1)
            sub1 = models.Subscription(
                id=sub1_id,
                tenant_id=t1,
                store_id=s1,
                plan_version_id=pv_id,
                state="ACTIVE_PERIOD_1",
                activation_sequence=1,
                first_paid_activated_at=now,
                current_period_no=1,
            )
            session.add(sub1)

            sub2 = models.Subscription(
                id=sub2_id,
                tenant_id=t2,
                store_id=s2,
                plan_version_id=pv_id,
                state="ACTIVE_PERIOD_1",
                activation_sequence=1,
                first_paid_activated_at=now,
                current_period_no=1,
            )
            session.add(sub2)
            await session.commit()

            # 2. Switch to runtime role subscription_svc
            try:
                await session.execute(text("SET ROLE subscription_svc;"))
            except Exception:
                pytest.skip("Role subscription_svc not provisioned in current test database")

            # 3. Query under Tenant 1 context -> must only see sub1
            await set_rls_context(session, tenant_id=t1, store_id=s1)
            res1 = (await session.execute(text("SELECT id FROM subscription.subscriptions WHERE id = :id"), {"id": str(sub1_id)})).fetchall()
            assert len(res1) == 1

            res2 = (await session.execute(text("SELECT id FROM subscription.subscriptions WHERE id = :id"), {"id": str(sub2_id)})).fetchall()
            assert len(res2) == 0  # Tenant 2 subscription invisible

            # 4. Query under Platform Admin context -> sees both
            await set_rls_context(session, tenant_id=None, store_id=None, is_platform_admin=True)
            res_admin = (await session.execute(text("SELECT id FROM subscription.subscriptions WHERE id IN (:s1, :s2)"),
                                              {"s1": str(sub1_id), "s2": str(sub2_id)})).fetchall()
            assert len(res_admin) == 2

            # 5. Switch to subscription_migrator -> verifies migrator bypass policy works with FORCE RLS
            await session.execute(text("RESET ROLE;"))
            try:
                await session.execute(text("SET ROLE subscription_migrator;"))
            except Exception:
                pytest.skip("Role subscription_migrator not provisioned in current test database")

            res_migrator = (await session.execute(text("SELECT id FROM subscription.subscriptions WHERE id IN (:s1, :s2)"),
                                                  {"s1": str(sub1_id), "s2": str(sub2_id)})).fetchall()
            assert len(res_migrator) == 2

        finally:
            try:
                await session.execute(text("RESET ROLE;"))
            except Exception:
                pass
            await session.rollback()
