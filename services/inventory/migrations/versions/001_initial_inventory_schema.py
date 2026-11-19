"""initial inventory schema

Revision ID: 001_initial_inventory_schema
Revises: 
Create Date: 2026-11-07 19:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial_inventory_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create schema
    op.execute("CREATE SCHEMA IF NOT EXISTS inventory")

    # 2. Foundation tables
    op.create_table(
        'outbox_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('event_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('event_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('event_type', sa.String(128), nullable=False),
        sa.Column('aggregate_type', sa.String(64), nullable=False),
        sa.Column('aggregate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('correlation_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('causation_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('producer', sa.String(64), nullable=False, server_default='inventory'),
        sa.Column('payload', postgresql.JSONB(), nullable=False),
        sa.Column('topic', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dead', sa.Boolean(), nullable=False, server_default='false'),
        schema='inventory'
    )

    op.create_table(
        'processed_events',
        sa.Column('consumer', sa.String(64), primary_key=True),
        sa.Column('event_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        schema='inventory'
    )

    op.create_table(
        'idempotency_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('scope', sa.String(64), nullable=False),
        sa.Column('key', sa.String(128), nullable=False),
        sa.Column('request_hash', sa.String(128), nullable=False),
        sa.Column('response_code', sa.Integer(), nullable=False),
        sa.Column('response_body', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('scope', 'key', name='uq_inventory_idempotency'),
        schema='inventory'
    )

    op.create_table(
        'scheduled_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('job_type', sa.String(64), nullable=False),
        sa.Column('business_key', sa.String(255), nullable=False),
        sa.Column('status', sa.String(24), nullable=False, server_default='PENDING'),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('business_key', name='uq_inventory_scheduled_business_key'),
        schema='inventory'
    )

    # 3. skus
    op.create_table(
        'skus',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('sku_code', sa.String(64), nullable=True, index=True),
        sa.Column('is_tracked', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('store_id', 'sku_code', name='uq_sku_store_code'),
        schema='inventory'
    )

    # 4. stock_balances
    op.create_table(
        'stock_balances',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('sku_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('on_hand_qty', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reserved_qty', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('version', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('last_movement_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('store_id', 'sku_id', name='uq_stock_balance_store_sku'),
        sa.CheckConstraint('on_hand_qty >= 0', name='ck_stock_balance_on_hand_positive'),
        sa.CheckConstraint('reserved_qty >= 0 AND reserved_qty <= on_hand_qty', name='ck_stock_balance_reserved_bounds'),
        schema='inventory'
    )

    # 5. reservations
    op.create_table(
        'reservations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('reservation_group_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('checkout_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('sku_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='ACTIVE', index=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint('quantity > 0', name='ck_reservation_quantity_positive'),
        sa.CheckConstraint("status IN ('ACTIVE', 'CONSUMED', 'RELEASED', 'EXPIRED')", name='ck_reservation_status'),
        schema='inventory'
    )

    # 6. stock_movements
    op.create_table(
        'stock_movements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('sku_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('movement_type', sa.String(32), nullable=False, index=True),
        sa.Column('quantity_delta', sa.Integer(), nullable=False),
        sa.Column('reference_type', sa.String(24), nullable=True, index=True),
        sa.Column('reference_id', postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint("movement_type IN ('OPENING', 'ADJUSTMENT', 'RESERVE', 'RELEASE', 'SALE', 'CANCEL_RESTORE', 'RETURN_RESTORE', 'EXPIRY')", name='ck_stock_movement_type'),
        sa.CheckConstraint('quantity_delta <> 0', name='ck_stock_movement_delta_nonzero'),
        schema='inventory'
    )

    # 7. inventory_adjustments
    op.create_table(
        'inventory_adjustments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('sku_id', postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column('adjustment_type', sa.String(32), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('reason', sa.String(255), nullable=True),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint("adjustment_type IN ('INCREMENT', 'DECREMENT', 'SET')", name='ck_adjustment_type'),
        schema='inventory'
    )

    # 8. Row Level Security policies
    for tbl in ('skus', 'stock_balances', 'reservations', 'stock_movements', 'inventory_adjustments'):
        op.execute(f"ALTER TABLE inventory.{tbl} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE inventory.{tbl} FORCE ROW LEVEL SECURITY;")

        # Migrator role policy: migrator has full access without flags
        op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'inventory_migrator') THEN
                DROP POLICY IF EXISTS migrator_full_access ON inventory.{tbl};
                CREATE POLICY migrator_full_access ON inventory.{tbl}
                    TO inventory_migrator
                    USING (true)
                    WITH CHECK (true);
            END IF;
        END
        $$;
        """)

        # Tenant isolation policy
        op.execute(f"""
        DO $$
        BEGIN
            DROP POLICY IF EXISTS {tbl}_tenant_store_isolation ON inventory.{tbl};
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'inventory_svc') THEN
                CREATE POLICY {tbl}_tenant_store_isolation ON inventory.{tbl}
                    TO inventory_svc
                    USING (
                        current_setting('app.is_platform_admin', true) = 'true'
                        OR (
                            store_id = NULLIF(current_setting('app.store_id', true), '')::uuid
                            AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        )
                    )
                    WITH CHECK (
                        current_setting('app.is_platform_admin', true) = 'true'
                        OR (
                            store_id = NULLIF(current_setting('app.store_id', true), '')::uuid
                            AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        )
                    );
            ELSE
                CREATE POLICY {tbl}_tenant_store_isolation ON inventory.{tbl}
                    USING (
                        current_setting('app.is_platform_admin', true) = 'true'
                        OR (
                            store_id = NULLIF(current_setting('app.store_id', true), '')::uuid
                            AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        )
                    )
                    WITH CHECK (
                        current_setting('app.is_platform_admin', true) = 'true'
                        OR (
                            store_id = NULLIF(current_setting('app.store_id', true), '')::uuid
                            AND tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                        )
                    );
            END IF;
        END
        $$;
        """)


def downgrade() -> None:
    for tbl in ('skus', 'stock_balances', 'reservations', 'stock_movements', 'inventory_adjustments'):
        op.execute(f"DROP POLICY IF EXISTS migrator_full_access ON inventory.{tbl};")
        op.execute(f"DROP POLICY IF EXISTS {tbl}_tenant_store_isolation ON inventory.{tbl};")
        op.execute(f"ALTER TABLE inventory.{tbl} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE inventory.{tbl} DISABLE ROW LEVEL SECURITY;")

    for tbl in ('inventory_adjustments', 'stock_movements', 'reservations', 'stock_balances', 'skus', 'scheduled_jobs', 'idempotency_keys', 'processed_events', 'outbox_events'):
        op.execute(f"DROP TABLE IF EXISTS inventory.{tbl} CASCADE")
