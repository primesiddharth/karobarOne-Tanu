# tests/test_rls_isolation.py
# FND-TST-008/009, SEC-005: Approval tenant isolation & platform staff queue (RULES.md §5 & §8)
import pytest
from uuid import uuid4
from sqlalchemy import text
from app.db import async_session_factory, set_rls_context
from app import models

pytestmark = pytest.mark.asyncio


async def test_approval_requests_rls_and_platform_admin_queue(db_engine):
    """
    Tests approval request isolation:
    1. Tenant 1 only sees Tenant 1 requests.
    2. Platform admin (app.is_platform_admin = 'true') sees requests across all tenants.
    """
    t1 = uuid4()
    t2 = uuid4()
    s1 = uuid4()
    s2 = uuid4()
    r1 = uuid4()
    r2 = uuid4()

    async with async_session_factory() as session:
        try:
            # 1. Insert Request for Tenant 1
            await set_rls_context(session, tenant_id=t1)
            req_1 = models.ApprovalRequest(
                id=r1,
                tenant_id=t1,
                store_id=s1,
                subject_type="CATALOG_ITEM",
                subject_id=uuid4(),
                status="PENDING",
                submitted_by=uuid4(),
            )
            session.add(req_1)
            await session.commit()

            # 2. Insert Request for Tenant 2
            await set_rls_context(session, tenant_id=t2)
            req_2 = models.ApprovalRequest(
                id=r2,
                tenant_id=t2,
                store_id=s2,
                subject_type="CATALOG_ITEM",
                subject_id=uuid4(),
                status="PENDING",
                submitted_by=uuid4(),
            )
            session.add(req_2)
            await session.commit()

            # 3. Query under Tenant 1 context -> sees r1 only
            await set_rls_context(session, tenant_id=t1)
            try:
                await session.execute(text("SET ROLE approval_svc;"))
            except Exception:
                pass

            t1_reqs = (await session.execute(text("SELECT id FROM approval.approval_requests"))).scalars().all()
            assert r1 in t1_reqs
            assert r2 not in t1_reqs

            # 4. Platform Admin queue: app.is_platform_admin = 'true' -> sees both r1 and r2
            await session.execute(text("SELECT set_config('app.is_platform_admin', 'true', true);"))
            admin_reqs = (await session.execute(text("SELECT id FROM approval.approval_requests"))).scalars().all()
            assert r1 in admin_reqs
            assert r2 in admin_reqs

        finally:
            try:
                await session.execute(text("RESET ROLE;"))
            except Exception:
                pass
            await session.rollback()
