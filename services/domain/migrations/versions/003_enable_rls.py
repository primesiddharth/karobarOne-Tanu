"""003_enable_rls

Revision ID: 003_domain
Revises: 002_domain
Create Date: 2026-11-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '003_domain'
down_revision = '002_domain'
branch_labels = None
depends_on = None

DOMAIN_TABLES = [
    'subdomains',
    'publication_routes',
    'domains',
]


def upgrade() -> None:
    # 1. Enable & Force Row Level Security on all domain tables
    for t in DOMAIN_TABLES:
        op.execute(f"ALTER TABLE domain.{t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE domain.{t} FORCE ROW LEVEL SECURITY;")

        # Migrator role policy: migrator has full access without flags
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'domain_migrator') THEN
                DROP POLICY IF EXISTS migrator_full_access ON domain.{t};
                CREATE POLICY migrator_full_access ON domain.{t}
                    TO domain_migrator
                    USING (true)
                    WITH CHECK (true);
            END IF;
        END
        $$;
        """)

        # Tenant isolation policy (tenant_id + store_id)
        op.execute(f"""
        DO $$
        BEGIN
            DROP POLICY IF EXISTS tenant_isolation_policy ON domain.{t};
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'domain_svc') THEN
                CREATE POLICY tenant_isolation_policy ON domain.{t}
                    TO domain_svc
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
                CREATE POLICY tenant_isolation_policy ON domain.{t}
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

    # 2. Narrow Public-Read Policy on publication_routes (FOR SELECT only, active routes only)
    op.execute("""
    DO $$
    BEGIN
        DROP POLICY IF EXISTS public_live_routes_select ON domain.publication_routes;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'domain_svc') THEN
            CREATE POLICY public_live_routes_select ON domain.publication_routes
                FOR SELECT TO domain_svc
                USING (
                    status = 'ACTIVE'
                    AND current_setting('app.public_read', true) = 'true'
                );
        ELSE
            CREATE POLICY public_live_routes_select ON domain.publication_routes
                FOR SELECT
                USING (
                    status = 'ACTIVE'
                    AND current_setting('app.public_read', true) = 'true'
                );
        END IF;
    END
    $$;
    """)


def downgrade() -> None:
    for t in DOMAIN_TABLES:
        op.execute(f"DROP POLICY IF EXISTS public_live_routes_select ON domain.{t};")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON domain.{t};")
        op.execute(f"DROP POLICY IF EXISTS migrator_full_access ON domain.{t};")
        op.execute(f"ALTER TABLE domain.{t} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE domain.{t} DISABLE ROW LEVEL SECURITY;")
