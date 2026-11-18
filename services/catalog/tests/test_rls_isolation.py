# tests/test_rls_isolation.py
# FND-TST-008/009, SEC-005: Catalog tenant isolation & narrow public-read policy
import pytest
from uuid import uuid4
from sqlalchemy import text
from app.db import async_session_factory, set_rls_context
from app import models

pytestmark = pytest.mark.asyncio


async def test_catalog_items_tenant_isolation_and_narrow_public_read(db_engine):
    """
    Tests:
    1. Tenant 1 cannot access Tenant 2 catalog items.
    2. Narrow public-read policy: when app.public_read = 'true', only approved LIVE items
       are visible; DRAFT and inactive items are never leaked.
    """
    t1 = uuid4()
    t2 = uuid4()
    s1 = uuid4()
    s2 = uuid4()
    item_live_id = uuid4()
    ver_live_id = uuid4()
    item_draft_id = uuid4()
    ver_draft_id = uuid4()

    async with async_session_factory() as session:
        try:
            # 1. Setup Tenant 1 items: one LIVE, one DRAFT
            await set_rls_context(session, tenant_id=t1)

            live_item = models.CatalogItem(
                id=item_live_id,
                tenant_id=t1,
                store_id=s1,
                item_type="PHYSICAL_PRODUCT",
                active=True,
                live_version_id=ver_live_id,
            )
            live_ver = models.ItemVersion(
                id=ver_live_id,
                item_id=item_live_id,
                tenant_id=t1,
                store_id=s1,
                version_no=1,
                title="Live Product",
                approval_state="APPROVED_LIVE",
            )
            draft_item = models.CatalogItem(
                id=item_draft_id,
                tenant_id=t1,
                store_id=s1,
                item_type="PHYSICAL_PRODUCT",
                active=True,
                draft_version_id=ver_draft_id,
            )
            draft_ver = models.ItemVersion(
                id=ver_draft_id,
                item_id=item_draft_id,
                tenant_id=t1,
                store_id=s1,
                version_no=1,
                title="Draft Product",
                approval_state="DRAFT",
            )
            session.add_all([live_item, live_ver, draft_item, draft_ver])
            await session.commit()

            # 2. Setup Tenant 2 item
            await set_rls_context(session, tenant_id=t2)
            t2_item = models.CatalogItem(
                id=uuid4(),
                tenant_id=t2,
                store_id=s2,
                item_type="PHYSICAL_PRODUCT",
                active=True,
            )
            session.add(t2_item)
            await session.commit()

            # 3. Switch to catalog_svc role if available
            try:
                await session.execute(text("SET ROLE catalog_svc;"))
            except Exception:
                pass

            # 4. Authenticated Tenant 1 query: sees Tenant 1 items, does not see Tenant 2 item
            await set_rls_context(session, tenant_id=t1)
            t1_items = (await session.execute(text("SELECT id FROM catalog.catalog_items"))).scalars().all()
            assert item_live_id in t1_items
            assert item_draft_id in t1_items
            assert t2_item.id not in t1_items

            # 5. Narrow public-read policy: unauthenticated user with app.public_read = 'true'
            await session.execute(text("RESET app.tenant_id;"))
            await session.execute(text(f"SELECT set_config('app.public_read', 'true', true);"))
            await session.execute(text(f"SELECT set_config('app.store_id', '{s1}', true);"))

            public_items = (await session.execute(text("SELECT id FROM catalog.catalog_items"))).scalars().all()
            # Must see LIVE item
            assert item_live_id in public_items
            # Must NEVER see DRAFT item
            assert item_draft_id not in public_items
            # Must NEVER see other store's items
            assert t2_item.id not in public_items

        finally:
            try:
                await session.execute(text("RESET ROLE;"))
            except Exception:
                pass
            await session.rollback()
