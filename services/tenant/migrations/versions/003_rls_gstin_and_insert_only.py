"""003_rls_gstin_and_insert_only

Revision ID: 003_tenant
Revises: 002_tenant
Create Date: 2026-11-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '003_tenant'
down_revision = '002_tenant'
branch_labels = None
depends_on = None

TENANT_TABLES = [
    'pan_verifications',
    'guardians',
    'guardian_consents',
    'gstins',
    'gstin_verifications',
    'free_store_entitlements',
]

STORE_TABLES = [
    'stores',
    'store_memberships',
    'seller_identity_snapshots',
    'store_gstin_assignments',
]

INSERT_ONLY_TABLES = [
    'guardian_consents',
    'pan_verifications',
    'gstin_verifications',
    'seller_identity_snapshots',
]


def upgrade() -> None:
    # 1. Create tenant.store_gstin_assignments table (DB Spec §7.2 / App D, AC-008..010)
    op.execute("""
    CREATE TABLE IF NOT EXISTS tenant.store_gstin_assignments (
        id UUID PRIMARY KEY,
        tenant_id UUID NOT NULL REFERENCES tenant.tenants(id) ON DELETE CASCADE,
        store_id UUID NOT NULL REFERENCES tenant.stores(id) ON DELETE CASCADE,
        gstin_id UUID NOT NULL REFERENCES tenant.gstins(id) ON DELETE CASCADE,
        assigned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        released_at TIMESTAMPTZ NULL
    );
    CREATE INDEX IF NOT EXISTS idx_tenant_gstin_assign_tenant ON tenant.store_gstin_assignments (tenant_id);
    CREATE INDEX IF NOT EXISTS idx_tenant_gstin_assign_store ON tenant.store_gstin_assignments (store_id);
    CREATE INDEX IF NOT EXISTS idx_tenant_gstin_assign_gstin ON tenant.store_gstin_assignments (gstin_id);

    -- Partial UNIQUE: same GSTIN cannot actively back two paid stores (AC-008..010)
    CREATE UNIQUE INDEX IF NOT EXISTS uq_active_store_gstin ON tenant.store_gstin_assignments (gstin_id) WHERE released_at IS NULL;
    -- Partial UNIQUE: one store can only hold one active GSTIN assignment
    CREATE UNIQUE INDEX IF NOT EXISTS uq_active_store_assignment ON tenant.store_gstin_assignments (store_id) WHERE released_at IS NULL;

    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tenant_svc') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON tenant.store_gstin_assignments TO tenant_svc;
        END IF;
    END
    $$;
    """)

    # 2. Enable & Force Row Level Security on all tenant and store tables
    all_tables = ['tenants'] + TENANT_TABLES + STORE_TABLES
    for t in all_tables:
        op.execute(f"ALTER TABLE tenant.{t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE tenant.{t} FORCE ROW LEVEL SECURITY;")

        # Migrator role policy: migrator has full access without flags
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tenant_migrator') THEN
                DROP POLICY IF EXISTS migrator_full_access ON tenant.{t};
                CREATE POLICY migrator_full_access ON tenant.{t}
                    TO tenant_migrator
                    USING (true)
                    WITH CHECK (true);
            END IF;
        END
        $$;
        """)

    # 3. Create tenant isolation policy for tenants table (id is the tenant_id)
    op.execute("""
    DO $$
    BEGIN
        DROP POLICY IF EXISTS tenant_isolation_policy ON tenant.tenants;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tenant_svc') THEN
            CREATE POLICY tenant_isolation_policy ON tenant.tenants
                TO tenant_svc
                USING (
                    id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                    OR current_setting('app.is_platform_admin', true) = 'true'
                )
                WITH CHECK (
                    id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                    OR current_setting('app.is_platform_admin', true) = 'true'
                );
        ELSE
            CREATE POLICY tenant_isolation_policy ON tenant.tenants
                USING (
                    id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                    OR current_setting('app.is_platform_admin', true) = 'true'
                )
                WITH CHECK (
                    id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                    OR current_setting('app.is_platform_admin', true) = 'true'
                );
        END IF;
    END
    $$;
    """)

    # 4. Create tenant isolation policy for tenant-owned tables
    for t in TENANT_TABLES:
        op.execute(f"""
        DO $$
        BEGIN
            DROP POLICY IF EXISTS tenant_isolation_policy ON tenant.{t};
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tenant_svc') THEN
                CREATE POLICY tenant_isolation_policy ON tenant.{t}
                    TO tenant_svc
                    USING (
                        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        OR current_setting('app.is_platform_admin', true) = 'true'
                    )
                    WITH CHECK (
                        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        OR current_setting('app.is_platform_admin', true) = 'true'
                    );
            ELSE
                CREATE POLICY tenant_isolation_policy ON tenant.{t}
                    USING (
                        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        OR current_setting('app.is_platform_admin', true) = 'true'
                    )
                    WITH CHECK (
                        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        OR current_setting('app.is_platform_admin', true) = 'true'
                    );
            END IF;
        END
        $$;
        """)

    # 5. Create store isolation policy for store-owned tables (checks tenant_id and store_id if set)
    for t in STORE_TABLES:
        op.execute(f"""
        DO $$
        BEGIN
            DROP POLICY IF EXISTS tenant_isolation_policy ON tenant.{t};
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tenant_svc') THEN
                CREATE POLICY tenant_isolation_policy ON tenant.{t}
                    TO tenant_svc
                    USING (
                        (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                         AND (NULLIF(current_setting('app.store_id', true), '') IS NULL
                              OR store_id = NULLIF(current_setting('app.store_id', true), '')::uuid))
                        OR current_setting('app.is_platform_admin', true) = 'true'
                    )
                    WITH CHECK (
                        (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                         AND (NULLIF(current_setting('app.store_id', true), '') IS NULL
                              OR store_id = NULLIF(current_setting('app.store_id', true), '')::uuid))
                        OR current_setting('app.is_platform_admin', true) = 'true'
                    );
            ELSE
                CREATE POLICY tenant_isolation_policy ON tenant.{t}
                    USING (
                        (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                         AND (NULLIF(current_setting('app.store_id', true), '') IS NULL
                              OR store_id = NULLIF(current_setting('app.store_id', true), '')::uuid))
                        OR current_setting('app.is_platform_admin', true) = 'true'
                    )
                    WITH CHECK (
                        (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                         AND (NULLIF(current_setting('app.store_id', true), '') IS NULL
                              OR store_id = NULLIF(current_setting('app.store_id', true), '')::uuid))
                        OR current_setting('app.is_platform_admin', true) = 'true'
                    );
            END IF;
        END
        $$;
        """)

    # 6. Revoke UPDATE, DELETE on insert-only tables from tenant_svc
    for t in INSERT_ONLY_TABLES:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tenant_svc') THEN
                REVOKE UPDATE, DELETE ON TABLE tenant.{t} FROM tenant_svc;
            END IF;
        END
        $$;
        """)


def downgrade() -> None:
    # Drop policies and RLS
    all_tables = ['tenants'] + TENANT_TABLES + STORE_TABLES
    for t in all_tables:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON tenant.{t};")
        op.execute(f"DROP POLICY IF EXISTS migrator_full_access ON tenant.{t};")
        op.execute(f"ALTER TABLE tenant.{t} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE tenant.{t} DISABLE ROW LEVEL SECURITY;")

    for t in INSERT_ONLY_TABLES:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'tenant_svc') THEN
                GRANT UPDATE, DELETE ON TABLE tenant.{t} TO tenant_svc;
            END IF;
        END
        $$;
        """)

    op.execute("DROP TABLE IF EXISTS tenant.store_gstin_assignments CASCADE;")
