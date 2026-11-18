"""001_initial_schema

Revision ID: 001_subscription
Revises: 
Create Date: 2026-11-06 00:00:00.000000

"""
import json
from uuid import uuid4
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001_subscription'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schema creation
    op.execute("CREATE SCHEMA IF NOT EXISTS subscription;")

    # 1. outbox_events
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
        sa.Column('producer', sa.String(64), nullable=False, server_default='subscription'),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('topic', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dead', sa.Boolean(), nullable=False, server_default='false'),
        schema='subscription',
    )
    op.create_index('ix_subscription_outbox_unpublished', 'outbox_events', ['created_at'], schema='subscription',
                    postgresql_where=sa.text('published_at IS NULL'))

    # 2. processed_events
    op.create_table(
        'processed_events',
        sa.Column('event_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('consumer', sa.String(64), primary_key=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        schema='subscription',
    )

    # 3. idempotency_keys
    op.create_table(
        'idempotency_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('scope', sa.String(64), nullable=False),
        sa.Column('key', sa.String(128), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        schema='subscription',
    )
    op.create_index('ix_subscription_idempotency_scope_key', 'idempotency_keys', ['scope', 'key'], unique=True, schema='subscription')

    # 4. plan_versions
    op.create_table(
        'plan_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('plan_code', sa.String(24), nullable=False),
        sa.Column('version_no', sa.Integer(), nullable=False),
        sa.Column('period_days', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('price_amount', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('commission_rate', sa.Numeric(9, 6), nullable=False, server_default='0'),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('plan_code', 'version_no', name='uq_plan_code_version_no'),
        schema='subscription',
    )
    op.create_index('ix_plan_versions_plan_code', 'plan_versions', ['plan_code'], schema='subscription')
    op.create_index('ix_plan_versions_is_active', 'plan_versions', ['is_active'], schema='subscription')

    # 5. plan_entitlements
    op.create_table(
        'plan_entitlements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('plan_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.plan_versions.id'), nullable=False),
        sa.Column('entitlement_code', sa.String(40), nullable=False),
        sa.Column('value_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('hard_limit', sa.Integer(), nullable=True),
        sa.Column('technical_limit', sa.Integer(), nullable=True),
        schema='subscription',
    )
    op.create_index('ix_plan_entitlements_plan_version_id', 'plan_entitlements', ['plan_version_id'], schema='subscription')
    op.create_index('ix_plan_entitlements_code', 'plan_entitlements', ['entitlement_code'], schema='subscription')

    # 6. subscriptions
    op.create_table(
        'subscriptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('plan_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.plan_versions.id'), nullable=False),
        sa.Column('state', sa.String(40), nullable=False),
        sa.Column('activation_sequence', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('first_paid_activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_no', sa.Integer(), nullable=True),
        sa.Column('current_period_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('cancellation_effective_after_period', sa.Integer(), nullable=True),
        sa.Column('version', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('store_id', name='uq_subscription_store_id'),
        schema='subscription',
    )
    op.create_index('ix_subscriptions_tenant_id', 'subscriptions', ['tenant_id'], schema='subscription')
    op.create_index('ix_subscriptions_store_id', 'subscriptions', ['store_id'], schema='subscription')
    op.create_index('ix_subscriptions_state', 'subscriptions', ['state'], schema='subscription')

    # 7. subscription_periods
    op.create_table(
        'subscription_periods',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subscription_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.subscriptions.id'), nullable=False),
        sa.Column('period_no', sa.Integer(), nullable=False),
        sa.Column('plan_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.plan_versions.id'), nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('entitlement_status', sa.String(24), nullable=False),
        sa.Column('charge_mode', sa.String(32), nullable=False),
        sa.Column('base_price_snapshot', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('amount_due_snapshot', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('gst_rate_snapshot', sa.Numeric(9, 6), nullable=False, server_default='0'),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('subscription_id', 'period_no', name='uq_subscription_period_no'),
        schema='subscription',
    )
    op.create_index('ix_subscription_periods_tenant_id', 'subscription_periods', ['tenant_id'], schema='subscription')
    op.create_index('ix_subscription_periods_store_id', 'subscription_periods', ['store_id'], schema='subscription')
    op.create_index('ix_subscription_periods_subscription_id', 'subscription_periods', ['subscription_id'], schema='subscription')

    # 8. subscription_charges
    op.create_table(
        'subscription_charges',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subscription_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.subscriptions.id'), nullable=False),
        sa.Column('period_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('charge_type', sa.String(40), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('tax_amount', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('status', sa.String(24), nullable=False, server_default='DUE'),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('calculation_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('finance_invoice_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        schema='subscription',
    )
    op.create_index('ix_subscription_charges_tenant_id', 'subscription_charges', ['tenant_id'], schema='subscription')
    op.create_index('ix_subscription_charges_store_id', 'subscription_charges', ['store_id'], schema='subscription')
    op.create_index('ix_subscription_charges_subscription_id', 'subscription_charges', ['subscription_id'], schema='subscription')

    # 9. advance_movements (append-only)
    op.create_table(
        'advance_movements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subscription_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.subscriptions.id'), nullable=False),
        sa.Column('movement_type', sa.String(40), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('direction', sa.String(1), nullable=False),
        sa.Column('source_charge_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('effective_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint("direction IN ('C', 'D')", name='ck_advance_direction'),
        schema='subscription',
    )
    op.create_index('ix_advance_movements_tenant_id', 'advance_movements', ['tenant_id'], schema='subscription')
    op.create_index('ix_advance_movements_store_id', 'advance_movements', ['store_id'], schema='subscription')
    op.create_index('ix_advance_movements_subscription_id', 'advance_movements', ['subscription_id'], schema='subscription')

    # 10. cancellation_notices
    op.create_table(
        'cancellation_notices',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subscription_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.subscriptions.id'), nullable=False),
        sa.Column('requested_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('status', sa.String(24), nullable=False, server_default='RECORDED'),
        sa.Column('effective_after_period_no', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        schema='subscription',
    )
    op.create_index('ix_cancellation_notices_subscription_id', 'cancellation_notices', ['subscription_id'], schema='subscription')

    # 11. plan_change_requests
    op.create_table(
        'plan_change_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subscription_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.subscriptions.id'), nullable=False),
        sa.Column('change_type', sa.String(16), nullable=False),
        sa.Column('from_plan_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.plan_versions.id'), nullable=False),
        sa.Column('to_plan_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.plan_versions.id'), nullable=False),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('effective_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(24), nullable=False, server_default='PENDING'),
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.CheckConstraint("change_type IN ('UPGRADE', 'DOWNGRADE')", name='ck_plan_change_type'),
        schema='subscription',
    )
    op.create_index('ix_plan_change_requests_subscription_id', 'plan_change_requests', ['subscription_id'], schema='subscription')

    # 12. upgrade_quotes
    op.create_table(
        'upgrade_quotes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('plan_change_request_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.plan_change_requests.id'), nullable=True),
        sa.Column('subscription_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.subscriptions.id'), nullable=False),
        sa.Column('target_plan_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.plan_versions.id'), nullable=False),
        sa.Column('days_remaining', sa.Integer(), nullable=False),
        sa.Column('prorated_difference', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('advance_top_up', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('gross_setup_fee', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('approved_discount_amount', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('net_setup_fee', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('total_ex_tax', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('tax_amount', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('total_with_tax', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('calculation_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        schema='subscription',
    )
    op.create_index('ix_upgrade_quotes_subscription_id', 'upgrade_quotes', ['subscription_id'], schema='subscription')

    # 13. discount_approvals
    op.create_table(
        'discount_approvals',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('upgrade_quote_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('subscription.upgrade_quotes.id'), nullable=False),
        sa.Column('requested_discount', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('approved_amount', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('approver_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        schema='subscription',
    )
    op.create_index('ix_discount_approvals_quote_id', 'discount_approvals', ['upgrade_quote_id'], schema='subscription')

    # 14. entitlement_snapshots
    op.create_table(
        'entitlement_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subscription_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('plan_code', sa.String(24), nullable=False),
        sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('effective_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('entitlements', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('source_plan_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reason_code', sa.String(40), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        schema='subscription',
    )
    op.create_index('ix_entitlement_snapshots_store_id', 'entitlement_snapshots', ['store_id'], schema='subscription')
    op.create_index('ix_entitlement_snapshots_tenant_id', 'entitlement_snapshots', ['tenant_id'], schema='subscription')

    # 15. Seed initial plan versions and plan entitlements
    # Free Presence, Commerce (₹1,999), Growth (₹4,999), Scale AI (₹9,999)
    presence_id = uuid4()
    commerce_id = uuid4()
    growth_id = uuid4()
    scale_ai_id = uuid4()

    plans_data = [
        {"id": presence_id, "plan_code": "PRESENCE", "version_no": 1, "price_amount": 0, "commission_rate": 0.00},
        {"id": commerce_id, "plan_code": "COMMERCE", "version_no": 1, "price_amount": 1999.00, "commission_rate": 0.040000},
        {"id": growth_id, "plan_code": "GROWTH", "version_no": 1, "price_amount": 4999.00, "commission_rate": 0.020000},
        {"id": scale_ai_id, "plan_code": "SCALE_AI", "version_no": 1, "price_amount": 9999.00, "commission_rate": 0.010000},
    ]

    for p in plans_data:
        op.execute(f"""
        INSERT INTO subscription.plan_versions (id, plan_code, version_no, period_days, price_amount, commission_rate, effective_from, is_active)
        VALUES ('{p['id']}', '{p['plan_code']}', {p['version_no']}, 30, {p['price_amount']}, {p['commission_rate']}, now(), true);
        """)

    entitlements_data = [
        # PRESENCE (Free)
        (presence_id, "SHOWCASE_LIMIT", 6, 6, {"showcase_limit": 6}),
        (presence_id, "MAX_IMAGES_PER_ITEM", 1, 1, {"max_images": 1}),
        (presence_id, "MAX_VIDEOS_PER_ITEM", 0, 0, {"max_videos": 0}),
        (presence_id, "COMMERCE_ENABLED", None, None, {"enabled": False}),
        (presence_id, "CUSTOM_DOMAIN_ALLOWED", None, None, {"enabled": False}),
        (presence_id, "BLOG_ALLOWED", None, None, {"enabled": False}),

        # COMMERCE
        (commerce_id, "SHOWCASE_LIMIT", None, None, {"showcase_limit": None}),
        (commerce_id, "MAX_IMAGES_PER_ITEM", 5, 5, {"max_images": 5}),
        (commerce_id, "MAX_VIDEOS_PER_ITEM", 0, 0, {"max_videos": 0}),
        (commerce_id, "COMMERCE_ENABLED", None, None, {"enabled": True}),
        (commerce_id, "CUSTOM_DOMAIN_ALLOWED", None, None, {"enabled": True}),
        (commerce_id, "BLOG_ALLOWED", None, None, {"enabled": True}),

        # GROWTH
        (growth_id, "SHOWCASE_LIMIT", None, None, {"showcase_limit": None}),
        (growth_id, "MAX_IMAGES_PER_ITEM", 10, 10, {"max_images": 10}),
        (growth_id, "MAX_VIDEOS_PER_ITEM", 1, 1, {"max_videos": 1}),
        (growth_id, "COMMERCE_ENABLED", None, None, {"enabled": True}),
        (growth_id, "CUSTOM_DOMAIN_ALLOWED", None, None, {"enabled": True}),
        (growth_id, "BLOG_ALLOWED", None, None, {"enabled": True}),

        # SCALE_AI
        (scale_ai_id, "SHOWCASE_LIMIT", None, None, {"showcase_limit": None}),
        (scale_ai_id, "MAX_IMAGES_PER_ITEM", 50, 50, {"max_images": 50}),
        (scale_ai_id, "MAX_VIDEOS_PER_ITEM", 5, 5, {"max_videos": 5}),
        (scale_ai_id, "COMMERCE_ENABLED", None, None, {"enabled": True}),
        (scale_ai_id, "CUSTOM_DOMAIN_ALLOWED", None, None, {"enabled": True}),
        (scale_ai_id, "BLOG_ALLOWED", None, None, {"enabled": True}),
    ]

    for plan_v_id, code, hard, tech, val_json in entitlements_data:
        val_str = json.dumps(val_json)
        hard_str = str(hard) if hard is not None else "NULL"
        tech_str = str(tech) if tech is not None else "NULL"
        op.execute(f"""
        INSERT INTO subscription.plan_entitlements (id, plan_version_id, entitlement_code, value_json, hard_limit, technical_limit)
        VALUES ('{uuid4()}', '{plan_v_id}', '{code}', '{val_str}'::jsonb, {hard_str}, {tech_str});
        """)


def downgrade() -> None:
    for t in [
        'entitlement_snapshots', 'discount_approvals', 'upgrade_quotes',
        'plan_change_requests', 'cancellation_notices', 'advance_movements',
        'subscription_charges', 'subscription_periods', 'subscriptions',
        'plan_entitlements', 'plan_versions', 'idempotency_keys',
        'processed_events', 'outbox_events'
    ]:
        op.drop_table(t, schema='subscription')
    op.execute("DROP SCHEMA IF EXISTS subscription CASCADE;")
