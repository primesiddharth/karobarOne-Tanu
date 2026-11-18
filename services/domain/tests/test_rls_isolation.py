# tests/test_rls_isolation.py
# FND-TST-008/009, SEC-005: Domain tenant isolation & public route resolution policy (RULES.md §5 & §8)
import pytest
from uuid import uuid4
from sqlalchemy import text
from app.db import async_session_factory, set_rls_context
from app import models

pytestmark = pytest.mark.asyncio


async def test_domain_tenant_isolation_and_public_route_lookup(db_engine):
    """
    Tests:
    1. Tenant 1 only sees Tenant 1 subdomains and publication routes.
    2. Narrow public-read policy: when app.public_read = 'true', only ACTIVE routes are visible for storefront resolution.
    """
    t1 = uuid4()
    t2 = uuid4()
    s1 = uuid4()
    s2 = uuid4()
    r_active_id = uuid4()
    r_disabled_id = uuid4()

    async with async_session_factory() as session:
        try:
            # 1. Setup Tenant 1 routes: one ACTIVE, one DISABLED
            await set_rls_context(session, tenant_id=t1)
            route_active = models.PublicationRoute(
                id=r_active_id,
                tenant_id=t1,
                store_id=s1,
                route_type="FREE_SUBDOMAIN",
                hostname=f"store1-{s1.hex[:6]}.karobarone.com",
                status="ACTIVE",
            )
            route_disabled = models.PublicationRoute(
                id=r_disabled_id,
                tenant_id=t1,
                store_id=s1,
                route_type="FREE_SUBDOMAIN",
                hostname=f"old-{s1.hex[:6]}.karobarone.com",
                status="DISABLED",
            )
            session.add_all([route_active, route_disabled])
            await session.commit()

            # 2. Setup Tenant 2 route
            await set_rls_context(session, tenant_id=t2)
            t2_route = models.PublicationRoute(
                id=uuid4(),
                tenant_id=t2,
                store_id=s2,
                route_type="FREE_SUBDOMAIN",
                hostname=f"store2-{s2.hex[:6]}.karobarone.com",
                status="ACTIVE",
            )
            session.add(t2_route)
            await session.commit()

            # 3. Switch to domain_svc role if available
            try:
                await session.execute(text("SET ROLE domain_svc;"))
            except Exception:
                pass

            # 4. Authenticated Tenant 1 query: sees Tenant 1 routes only
            await set_rls_context(session, tenant_id=t1)
            t1_routes = (await session.execute(text("SELECT id FROM domain.publication_routes"))).scalars().all()
            assert r_active_id in t1_routes
            assert r_disabled_id in t1_routes
            assert t2_route.id not in t1_routes

            # 5. Public storefront host resolution: unauthenticated query with app.public_read = 'true'
            await session.execute(text("RESET app.tenant_id;"))
            await session.execute(text("SELECT set_config('app.public_read', 'true', true);"))

            public_routes = (await session.execute(text("SELECT id FROM domain.publication_routes"))).scalars().all()
            # Must see ACTIVE routes
            assert r_active_id in public_routes
            # Must NEVER see DISABLED routes
            assert r_disabled_id not in public_routes

        finally:
            try:
                await session.execute(text("RESET ROLE;"))
            except Exception:
                pass
            await session.rollback()
