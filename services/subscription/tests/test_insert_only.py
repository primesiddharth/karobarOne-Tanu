# tests/test_insert_only.py
# FND-TST-035: Verifies that append-only financial audit tables refuse UPDATE and DELETE from subscription_svc (RULES.md §5)
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from app.db import async_session_factory, set_rls_context
from app import models

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("table_name", [
    "advance_movements",
    "subscription_charges",
])
async def test_financial_audit_tables_refuse_update_and_delete(db_engine, table_name):
    """subscription_svc cannot UPDATE or DELETE rows in financial audit tables (RULES.md §5, BTDD §13)."""
    t1 = uuid4()
    s1 = uuid4()
    sub_id = uuid4()
    row_id = uuid4()
    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        try:
            pv_res = await session.execute(text("SELECT id FROM subscription.plan_versions LIMIT 1"))
            pv_id = pv_res.scalar()
            if not pv_id:
                pytest.skip("No plan_versions seeded in test database")

            await set_rls_context(session, tenant_id=t1, store_id=s1)
            sub = models.Subscription(
                id=sub_id,
                tenant_id=t1,
                store_id=s1,
                plan_version_id=pv_id,
                state="ACTIVE_PERIOD_1",
                activation_sequence=1,
                first_paid_activated_at=now,
                current_period_no=1,
            )
            session.add(sub)
            await session.commit()

            if table_name == "advance_movements":
                adv = models.AdvanceMovement(
                    id=row_id,
                    tenant_id=t1,
                    store_id=s1,
                    subscription_id=sub_id,
                    movement_type="COLLECTED",
                    amount=Decimal("1999.00"),
                    direction="C",
                    effective_at=now,
                )
                session.add(adv)
            else:
                chg = models.SubscriptionCharge(
                    id=row_id,
                    tenant_id=t1,
                    store_id=s1,
                    subscription_id=sub_id,
                    charge_type="PERIOD_FEE",
                    amount=Decimal("1999.00"),
                    status="PAID",
                )
                session.add(chg)
            await session.commit()

            # Switch to runtime role subscription_svc
            try:
                await session.execute(text("SET ROLE subscription_svc;"))
            except Exception:
                pytest.skip("Role subscription_svc not provisioned in current test database")

            await set_rls_context(session, tenant_id=t1, store_id=s1)

            # UPDATE refused
            with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                await session.execute(text(f"UPDATE subscription.{table_name} SET amount = 999 WHERE id = :id"), {"id": str(row_id)})
            assert "permission denied" in str(exc_info.value).lower()

            # DELETE refused
            with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                await session.execute(text(f"DELETE FROM subscription.{table_name} WHERE id = :id"), {"id": str(row_id)})
            assert "permission denied" in str(exc_info.value).lower()

        finally:
            try:
                await session.execute(text("RESET ROLE;"))
            except Exception:
                pass
            await session.rollback()
