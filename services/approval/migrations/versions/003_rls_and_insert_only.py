"""003_rls_and_insert_only

Revision ID: 003_approval
Revises: 002_approval
Create Date: 2026-11-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '003_approval'
down_revision = '002_approval'
branch_labels = None
depends_on = None

APPROVAL_TABLES = [
    'approval_requests',
    'approval_decisions',
    'takedowns',
    'approval_state_history',
]


def upgrade() -> None:
    # 1. Add tenant_id and store_id to approval_state_history if not present
    op.execute("""
    ALTER TABLE approval.approval_state_history
        ADD COLUMN IF NOT EXISTS tenant_id UUID,
        ADD COLUMN IF NOT EXISTS store_id UUID;
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_approval_history_tenant ON approval.approval_state_history (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_approval_history_store ON approval.approval_state_history (store_id);")

    # 2. Enable & Force Row Level Security on all approval tables
    for t in APPROVAL_TABLES:
        op.execute(f"ALTER TABLE approval.{t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE approval.{t} FORCE ROW LEVEL SECURITY;")

        # Migrator role policy: migrator has full access without flags
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'approval_migrator') THEN
                DROP POLICY IF EXISTS migrator_full_access ON approval.{t};
                CREATE POLICY migrator_full_access ON approval.{t}
                    TO approval_migrator
                    USING (true)
                    WITH CHECK (true);
            END IF;
        END
        $$;
        """)

        # Tenant isolation policy with platform admin queue support (app.is_platform_admin)
        op.execute(f"""
        DO $$
        BEGIN
            DROP POLICY IF EXISTS tenant_isolation_policy ON approval.{t};
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'approval_svc') THEN
                CREATE POLICY tenant_isolation_policy ON approval.{t}
                    TO approval_svc
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
                CREATE POLICY tenant_isolation_policy ON approval.{t}
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

    # 3. Revoke UPDATE, DELETE on insert-only tables from approval_svc
    # approval_state_history and approval_decisions are append-only.
    # takedowns has mutable restored_at, so revoke only DELETE.
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'approval_svc') THEN
            REVOKE UPDATE, DELETE ON TABLE approval.approval_state_history FROM approval_svc;
            REVOKE UPDATE, DELETE ON TABLE approval.approval_decisions FROM approval_svc;
            REVOKE DELETE ON TABLE approval.takedowns FROM approval_svc;
        END IF;
    END
    $$;
    """)


def downgrade() -> None:
    for t in APPROVAL_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON approval.{t};")
        op.execute(f"DROP POLICY IF EXISTS migrator_full_access ON approval.{t};")
        op.execute(f"ALTER TABLE approval.{t} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE approval.{t} DISABLE ROW LEVEL SECURITY;")

    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'approval_svc') THEN
            GRANT UPDATE, DELETE ON TABLE approval.approval_state_history TO approval_svc;
            GRANT UPDATE, DELETE ON TABLE approval.approval_decisions TO approval_svc;
            GRANT DELETE ON TABLE approval.takedowns TO approval_svc;
        END IF;
    END
    $$;
    """)
