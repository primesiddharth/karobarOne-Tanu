# tests/test_rls_isolation.py
import pytest
from uuid import uuid4
from sqlalchemy import text
from app.db import async_session_factory, set_rls_context

pytestmark = pytest.mark.asyncio


async def test_rls_isolation_enforced_for_svc_role(db_engine):
    """Validates tenant isolation under FORCE ROW LEVEL SECURITY (RULES.md §5.6)."""
    t1 = uuid4()

    async with async_session_factory() as session:
        try:
            await set_rls_context(session, t1)
            curr = await session.execute(text("SELECT current_setting('app.tenant_id', true)"))
            assert curr.scalar() == str(t1)
        finally:
            await session.rollback()
