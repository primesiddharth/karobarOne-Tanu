"""002_rls_and_privileges

Revision ID: 002_subscription
Revises: 001_subscription
Create Date: 2026-11-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '002_subscription'
down_revision = '001_subscription'
branch_labels = None
depends_on = None

SUBSCRIPTION_RLS_TABLES = [
    'subscriptions',
    'subscription_periods',
    'subscription_charges',
    'advance_movements',
    'cancellation_notices',
    'plan_change_requests',
    'upgrade_quotes',
    'discount_approvals',
    'entitlement_snapshots',
]

IMMUTABLE_FINANCIAL_TABLES = [
    'advance_movements',
    'subscription_charges',
    'cancellation_notices',
    'discount_approvals',
]


def upgrade() -> None:
    # 1. Enable & Force Row Level Security on all subscription tenant/store tables
    for t in SUBSCRIPTION_RLS_TABLES:
        op.execute(f"ALTER TABLE subscription.{t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE subscription.{t} FORCE ROW LEVEL SECURITY;")

        # Migrator role policy: migrator has full access without flags
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'subscription_migrator') THEN
                DROP POLICY IF EXISTS migrator_full_access ON subscription.{t};
                CREATE POLICY migrator_full_access ON subscription.{t}
                    TO subscription_migrator
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
            DROP POLICY IF EXISTS tenant_isolation_policy ON subscription.{t};
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'subscription_svc') THEN
                CREATE POLICY tenant_isolation_policy ON subscription.{t}
                    TO subscription_svc
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
                CREATE POLICY tenant_isolation_policy ON subscription.{t}
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

    # Narrow public read policy for entitlement_snapshots (fast storefront verification)
    op.execute("""
    DO $$
    BEGIN
        DROP POLICY IF EXISTS narrow_public_read_policy ON subscription.entitlement_snapshots;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'subscription_svc') THEN
            CREATE POLICY narrow_public_read_policy ON subscription.entitlement_snapshots
                FOR SELECT
                TO subscription_svc
                USING (current_setting('app.public_read', true) = 'true');
        END IF;
    END
    $$;
    """)

    # 2. Enforce statutory financial / audit protection: revoke UPDATE and DELETE on financial tables from subscription_svc
    for t in IMMUTABLE_FINANCIAL_TABLES:
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'subscription_svc') THEN
                REVOKE UPDATE, DELETE ON subscription.{t} FROM subscription_svc;
            END IF;
        END
        $$;
        """)


def downgrade() -> None:
    for t in SUBSCRIPTION_RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS migrator_full_access ON subscription.{t};")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_policy ON subscription.{t};")
        op.execute(f"ALTER TABLE subscription.{t} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE subscription.{t} DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS narrow_public_read_policy ON subscription.entitlement_snapshots;")
