# tests/test_insert_only.py
# FND-TST-035: Verifies that approval audit/history tables are insert-only for approval_svc
import pytest
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from app.db import async_session_factory, set_rls_context
from app import models

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("table_name", [
    "approval_state_history",
    "approval_decisions",
])
async def test_approval_history_refuses_update_and_delete(db_engine, table_name):
    """approval_svc cannot UPDATE or DELETE rows in immutable approval history tables."""
    t1 = uuid4()
    s1 = uuid4()
    r1 = uuid4()
    h1 = uuid4()

    async with async_session_factory() as session:
        try:
            await set_rls_context(session, tenant_id=t1)
            req = models.ApprovalRequest(
                id=r1,
                tenant_id=t1,
                store_id=s1,
                subject_type="CATALOG_ITEM",
                subject_id=uuid4(),
                status="PENDING",
                submitted_by=uuid4(),
            )
            session.add(req)
            await session.commit()

            history = models.ApprovalStateHistory(
                id=h1,
                tenant_id=t1,
                store_id=s1,
                approval_request_id=r1,
                from_status="NONE",
                to_status="PENDING",
                actor_id=uuid4(),
                reason="Initial",
            )
            session.add(history)
            await session.commit()

            try:
                await session.execute(text("SET ROLE approval_svc;"))
            except Exception:
                pytest.skip("Role approval_svc not provisioned in current test database")

            await set_rls_context(session, tenant_id=t1)

            # UPDATE refused
            with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                await session.execute(text(f"UPDATE approval.{table_name} SET reason = 'HACK' WHERE id = :id"), {"id": str(h1)})
            assert "permission denied" in str(exc_info.value).lower()

            # DELETE refused
            with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                await session.execute(text(f"DELETE FROM approval.{table_name} WHERE id = :id"), {"id": str(h1)})
            assert "permission denied" in str(exc_info.value).lower()

        finally:
            try:
                await session.execute(text("RESET ROLE;"))
            except Exception:
                pass
            await session.rollback()
