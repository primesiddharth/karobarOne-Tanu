"""003_rls_and_content_versions

Revision ID: 003_catalog
Revises: 002_catalog
Create Date: 2026-11-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '003_catalog'
down_revision = '002_catalog'
branch_labels = None
depends_on = None

CATALOG_TABLES = [
    'catalog_items',
    'item_versions',
    'store_content_versions',
    'product_details',
    'service_details',
    'item_media',
    'entitlement_projection',
]


def upgrade() -> None:
    # 1. Create catalog.store_content_versions table per DB Spec §7.5 text (CAT-007)
    op.execute("""
    CREATE TABLE IF NOT EXISTS catalog.store_content_versions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id UUID NOT NULL,
        store_id UUID NOT NULL,
        content_section VARCHAR(32) NOT NULL,
        version_no INT NOT NULL,
        content_json JSONB NOT NULL DEFAULT '{}'::jsonb,
        approval_state VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
        content_hash CHAR(64) NOT NULL,
        approved_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_store_content_section_version UNIQUE(store_id, content_section, version_no),
        CONSTRAINT ck_store_content_approval_state CHECK (approval_state IN ('DRAFT', 'PENDING', 'APPROVED_LIVE', 'REJECTED', 'EMERGENCY_TAKEDOWN'))
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_cat_content_tenant ON catalog.store_content_versions (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_cat_content_store ON catalog.store_content_versions (store_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_cat_content_section ON catalog.store_content_versions (content_section);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_cat_content_state ON catalog.store_content_versions (approval_state);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_cat_content_hash ON catalog.store_content_versions (content_hash);")

    # 2. Add tenant_id and store_id to supporting tables for direct RLS enforcement
    op.execute("""
    ALTER TABLE catalog.product_details
        ADD COLUMN IF NOT EXISTS tenant_id UUID,
        ADD COLUMN IF NOT EXISTS store_id UUID;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_product_details_tenant ON catalog.product_details (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_product_details_store ON catalog.product_details (store_id);")

    op.execute("""
    ALTER TABLE catalog.service_details
        ADD COLUMN IF NOT EXISTS tenant_id UUID,
        ADD COLUMN IF NOT EXISTS store_id UUID;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_service_details_tenant ON catalog.service_details (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_service_details_store ON catalog.service_details (store_id);")

    op.execute("""
    ALTER TABLE catalog.item_media
        ADD COLUMN IF NOT EXISTS tenant_id UUID,
        ADD COLUMN IF NOT EXISTS store_id UUID;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_item_media_tenant ON catalog.item_media (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_item_media_store ON catalog.item_media (store_id);")

    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'catalog_svc') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA catalog TO catalog_svc;
        END IF;
    END
    $$;
    """)

    # 3. Enable & Force Row Level Security on all catalog tables
    for t in CATALOG_TABLES:
        op.execute(f"ALTER TABLE catalog.{t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE catalog.{t} FORCE ROW LEVEL SECURITY;")

        # Migrator role policy: migrator has full access without flags
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'catalog_migrator') THEN
                DROP POLICY IF EXISTS migrator_full_access ON catalog.{t};
                CREATE POLICY migrator_full_access ON catalog.{t}
                    TO catalog_migrator
                    USING (true)
                    WITH CHECK (true);
            END IF;
        END
        $$;
        """)

        # Tenant isolation policy (tenant_id + optional store_id)
        op.execute(f"""
        DO $$
        BEGIN
            DROP POLICY IF EXISTS tenant_isolation_policy ON catalog.{t};
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'catalog_svc') THEN
                CREATE POLICY tenant_isolation_policy ON catalog.{t}
                    TO catalog_svc
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
                CREATE POLICY tenant_isolation_policy ON catalog.{t}
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

    # 4. Narrow Public-Read Policies (FOR SELECT only, approved live items only)
    op.execute("""
    DO $$
    BEGIN
        DROP POLICY IF EXISTS public_live_items_select ON catalog.catalog_items;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'catalog_svc') THEN
            CREATE POLICY public_live_items_select ON catalog.catalog_items
                FOR SELECT TO catalog_svc
                USING (
                    active = true
                    AND live_version_id IS NOT NULL
                    AND current_setting('app.public_read', true) = 'true'
                    AND store_id = NULLIF(current_setting('app.store_id', true), '')::uuid
                );
        ELSE
            CREATE POLICY public_live_items_select ON catalog.catalog_items
                FOR SELECT
                USING (
                    active = true
                    AND live_version_id IS NOT NULL
                    AND current_setting('app.public_read', true) = 'true'
                    AND store_id = NULLIF(current_setting('app.store_id', true), '')::uuid
                );
        END IF;

        DROP POLICY IF EXISTS public_live_versions_select ON catalog.item_versions;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'catalog_svc') THEN
            CREATE POLICY public_live_versions_select ON catalog.item_versions
                FOR SELECT TO catalog_svc
                USING (
                    approval_state = 'APPROVED_LIVE'
                    AND current_setting('app.public_read', true) = 'true'
                    AND store_id = NULLIF(current_setting('app.store_id', true), '')::uuid
                );
        ELSE
            CREATE POLICY public_live_versions_select ON catalog.item_versions
                FOR SELECT
                USING (
                    approval_state = 'APPROVED_LIVE'
                    AND current_setting('app.public_read', true) = 'true'
                    AND store_id = NULLIF(current_setting('app.store_id', true), '')::uuid
                );
        END IF;

        DROP POLICY IF EXISTS public_live_media_select ON catalog.item_media;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'catalog_svc') THEN
            CREATE POLICY public_live_media_select ON catalog.item_media
                FOR SELECT TO catalog_svc
                USING (
                    current_setting('app.public_read', true) = 'true'
                    AND store_id = NULLIF(current_setting('app.store_id', true), '')::uuid
                );
        ELSE
            CREATE POLICY public_live_media_select ON catalog.item_media
                FOR SELECT
                USING (
                    current_setting('app.public_read', true) = 'true'
                    AND store_id = NULLIF(current_setting('app.store_id', true), '')::uuid
                );
        END IF;
    END
    $$;
    """)


def downgrade() -> None:
    for t in CATALOG_TABLES:
        op.execute(f"DROP POLICY IF EXISTS public_live_items_select ON catalog.{t};")
        op.execute(f"DROP POLICY IF EXISTS public_live_versions_select ON catalog.{t};")
        op.execute(f"DROP POLICY IF EXISTS public_live_media_select ON catalog.{t};")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON catalog.{t};")
        op.execute(f"DROP POLICY IF EXISTS migrator_full_access ON catalog.{t};")
        op.execute(f"ALTER TABLE catalog.{t} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE catalog.{t} DISABLE ROW LEVEL SECURITY;")

    op.execute("DROP TABLE IF EXISTS catalog.store_content_versions CASCADE;")
