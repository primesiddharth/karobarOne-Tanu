# tools/tests/test_rls_completeness.py
# FND-TST-008/009 / SEC-005: Audit database metadata to ensure all tenant-owned tables enforce RLS
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

# Explicitly documented exclusion list per architectural mandate
EXCLUDED_TABLES = {
    "outbox_events": "Outbox relay worker reads across tenants to poll and dispatch unpublished events (RULES.md §7.4)",
    "processed_events": "Inbox deduplication consumer processes events arriving from multiple producers across schemas (RULES.md §7.4)",
    "idempotency_keys": "Idempotent request check occurs before tenant context is authenticated/resolved (RULES.md §6)",
    "role_assignments": "Holds global platform roles (e.g. PLATFORM_OWNER, PLATFORM_STAFF, GST_STAFF) where tenant_id is NULL (RULES.md §8)",
}


async def test_all_tenant_id_tables_have_enabled_and_forced_rls(postgres_url):
    """
    Verifies that EVERY table across all service schemas containing a 'tenant_id' column
    has BOTH relrowsecurity=true (ENABLE) and relforcerowsecurity=true (FORCE) in pg_class,
    unless explicitly present in EXCLUDED_TABLES with a documented reason.
    """
    engine = create_async_engine(postgres_url.replace("sslmode=", "ssl="))
    async with engine.connect() as conn:
        # Find all user tables with a tenant_id column
        query = text("""
            SELECT
                c.table_schema,
                c.table_name,
                cl.relrowsecurity AS rls_enabled,
                cl.relforcerowsecurity AS rls_forced
            FROM information_schema.columns c
            JOIN pg_class cl ON cl.relname = c.table_name
            JOIN pg_namespace n ON n.oid = cl.relnamespace AND n.nspname = c.table_schema
            WHERE c.column_name = 'tenant_id'
              AND c.table_schema IN ('iam', 'tenant', 'approval', 'catalog', 'domain', 'customer', 'subscription', 'inventory')
              AND cl.relkind = 'r'
            ORDER BY c.table_schema, c.table_name;
        """)
        rows = (await conn.execute(query)).fetchall()
        assert rows, (
            "No tables found with a 'tenant_id' column across schemas. "
            "Database migrations must be applied before running RLS completeness audit."
        )

        missing_rls = []
        for schema, table, rls_enabled, rls_forced in rows:
            if table in EXCLUDED_TABLES:
                continue

            if not rls_enabled or not rls_forced:
                missing_rls.append(
                    f"{schema}.{table} (enabled={rls_enabled}, forced={rls_forced})"
                )

        assert not missing_rls, (
            f"The following tables with a tenant_id column lack ENABLE or FORCE ROW LEVEL SECURITY:\n"
            + "\n".join(missing_rls)
            + f"\nIf an exclusion is legitimate, add it to EXCLUDED_TABLES with an architectural justification."
        )
    await engine.dispose()
