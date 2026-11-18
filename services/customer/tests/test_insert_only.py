# tests/test_insert_only.py
# FND-TST-035: Verifies that audit/statutory compliance tables are protected from DELETE by customer_svc (RULES.md §5)
import pytest
from uuid import uuid4
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from app.db import async_session_factory, set_rls_context
from app import models

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("table_name", [
    "privacy_requests",
    "account_claims",
])
async def test_audit_tables_refuse_delete(db_engine, table_name):
    """customer_svc cannot DELETE rows in statutory audit tables (RULES.md §5, CUS-R04)."""
    t1 = uuid4()
    s1 = uuid4()
    c1 = uuid4()
    row_id = uuid4()

    async with async_session_factory() as session:
        try:
            await set_rls_context(session, tenant_id=t1, store_id=s1)
            cust = models.Customer(
                id=c1,
                tenant_id=t1,
                store_id=s1,
                email=f"audit_{c1.hex[:8]}@example.com",
                mobile_e164=f"+91{c1.int % 1000000000 + 6000000000}",
                status="UNCLAIMED",
            )
            session.add(cust)
            await session.commit()

            if table_name == "privacy_requests":
                priv = models.PrivacyRequest(
                    id=row_id,
                    tenant_id=t1,
                    store_id=s1,
                    customer_id=c1,
                    request_type="DELETE",
                    status="COMPLETED",
                )
                session.add(priv)
            else:
                claim = models.AccountClaim(
                    id=row_id,
                    tenant_id=t1,
                    store_id=s1,
                    customer_id=c1,
                    otp_challenge_id=uuid4(),
                    status="PENDING",
                )
                session.add(claim)
            await session.commit()

            # Switch to runtime role customer_svc
            try:
                await session.execute(text("SET ROLE customer_svc;"))
            except Exception:
                pytest.skip("Role customer_svc not provisioned in current test database")

            await set_rls_context(session, tenant_id=t1, store_id=s1)

            # DELETE refused
            with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                await session.execute(text(f"DELETE FROM customer.{table_name} WHERE id = :id"), {"id": str(row_id)})
            assert "permission denied" in str(exc_info.value).lower()

        finally:
            try:
                await session.execute(text("RESET ROLE;"))
            except Exception:
                pass
            await session.rollback()
