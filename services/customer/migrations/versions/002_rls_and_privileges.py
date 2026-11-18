"""002_rls_and_privileges

Revision ID: 002_customer
Revises: 001_customer
Create Date: 2026-11-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '002_customer'
down_revision = '001_customer'
branch_labels = None
depends_on = None

CUSTOMER_RLS_TABLES = [
    'customers',
    'addresses',
    'account_claims',
    'privacy_requests',
]

IMMUTABLE_AUDIT_TABLES = [
    'privacy_requests',
    'account_claims',
]


def upgrade() -> None:
    # 1. Enable & Force Row Level Security on all customer domain tables
    for t in CUSTOMER_RLS_TABLES:
        op.execute(f"ALTER TABLE customer.{t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE customer.{t} FORCE ROW LEVEL SECURITY;")

        # Migrator role policy: migrator has full access without flags
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'customer_migrator') THEN
                DROP POLICY IF EXISTS migrator_full_access ON customer.{t};
                CREATE POLICY migrator_full_access ON customer.{t}
                    TO customer_migrator
                    USING (true)
                    WITH CHECK (true);
            END IF;
        END
        $$;
        """)

        # Tenant & Store isolation policy
        op.execute(f"""
        DO $$
        BEGIN
            DROP POLICY IF EXISTS tenant_isolation_policy ON customer.{t};
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'customer_svc') THEN
                CREATE POLICY tenant_isolation_policy ON customer.{t}
                    TO customer_svc
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
                CREATE POLICY tenant_isolation_policy ON customer.{t}
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

    # 2. Enforce statutory history / audit protection: revoke DELETE on audit tables from customer_svc
    for t in IMMUTABLE_AUDIT_TABLES:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'customer_svc') THEN
                REVOKE DELETE ON customer.{t} FROM customer_svc;
            END IF;
        END
        $$;
        """)


def downgrade() -> None:
    for t in CUSTOMER_RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON customer.{t};")
        op.execute(f"DROP POLICY IF EXISTS migrator_full_access ON customer.{t};")
        op.execute(f"ALTER TABLE customer.{t} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE customer.{t} DISABLE ROW LEVEL SECURITY;")

    for t in IMMUTABLE_AUDIT_TABLES:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'customer_svc') THEN
                GRANT DELETE ON customer.{t} TO customer_svc;
            END IF;
        END
        $$;
        """)
