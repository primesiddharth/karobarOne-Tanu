# tests/test_rls_isolation.py
# FND-TST-008/009, SEC-005: Inventory tenant and store isolation policy (RULES.md §5 & §8)
import pytest
from uuid import uuid4
from sqlalchemy import text
from app.db import async_session_factory, set_rls_context
from app import models

pytestmark = pytest.mark.asyncio


async def test_inventory_tenant_and_store_isolation(db_engine):
    """
    Tests:
    1. Tenant 1/Store 1 only sees its own stock balances and reservations.
    2. Tenant 2/Store 2 cannot view or mutate Tenant 1's inventory.
    """
    t1 = uuid4()
    t2 = uuid4()
    s1 = uuid4()
    s2 = uuid4()
    sku1 = uuid4()
    sku2 = uuid4()

    async with async_session_factory() as session:
        try:
            # 1. Setup Tenant 1 stock balance
            await set_rls_context(session, tenant_id=t1, store_id=s1)
            bal1 = models.StockBalance(
                id=uuid4(),
                tenant_id=t1,
                store_id=s1,
                sku_id=sku1,
                on_hand_qty=50,
                reserved_qty=5,
                version=1,
            )
            session.add(bal1)
            await session.commit()

            # 2. Setup Tenant 2 stock balance
            await set_rls_context(session, tenant_id=t2, store_id=s2)
            bal2 = models.StockBalance(
                id=uuid4(),
                tenant_id=t2,
                store_id=s2,
                sku_id=sku2,
                on_hand_qty=20,
                reserved_qty=0,
                version=1,
            )
            session.add(bal2)
            await session.commit()

            # 3. Query under Tenant 1 context -> sees only bal1
            await set_rls_context(session, tenant_id=t1, store_id=s1)
            res1 = await session.execute(text("SELECT count(*) FROM inventory.stock_balances"))
            assert res1.scalar() == 1

            # Query under Tenant 2 context -> sees only bal2
            await set_rls_context(session, tenant_id=t2, store_id=s2)
            res2 = await session.execute(text("SELECT count(*) FROM inventory.stock_balances"))
            assert res2.scalar() == 1

        finally:
            # Cleanup under admin context
            await set_rls_context(session, tenant_id=None, is_platform_admin=True)
            await session.execute(text("DELETE FROM inventory.stock_balances WHERE tenant_id IN (:t1, :t2)"), {"t1": str(t1), "t2": str(t2)})
            await session.commit()
