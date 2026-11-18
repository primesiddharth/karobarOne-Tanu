"""001_initial_schema

Revision ID: 001_customer
Revises: 
Create Date: 2026-11-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001_customer'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schema creation
    op.execute("CREATE SCHEMA IF NOT EXISTS customer;")

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
        sa.Column('producer', sa.String(64), nullable=False, server_default='customer'),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('topic', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dead', sa.Boolean(), nullable=False, server_default='false'),
        schema='customer',
    )
    op.create_index('ix_customer_outbox_unpublished', 'outbox_events', ['created_at'], schema='customer',
                    postgresql_where=sa.text('published_at IS NULL'))

    # 2. processed_events
    op.create_table(
        'processed_events',
        sa.Column('event_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('consumer', sa.String(64), primary_key=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        schema='customer',
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
        schema='customer',
    )
    op.create_index('ix_customer_idempotency_scope_key', 'idempotency_keys', ['scope', 'key'], unique=True, schema='customer')

    # 4. customers
    op.create_table(
        'customers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('mobile_e164', sa.String(20), nullable=False),
        sa.Column('status', sa.String(24), nullable=False, server_default='UNCLAIMED'),
        sa.Column('iam_principal_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('first_name', sa.String(100), nullable=True),
        sa.Column('last_name', sa.String(100), nullable=True),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_activity_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('UNCLAIMED', 'CLAIMED', 'BLOCKED', 'ANONYMIZED')", name='ck_customer_status'),
        schema='customer',
    )
    op.create_index('ix_customers_tenant_id', 'customers', ['tenant_id'], schema='customer')
    op.create_index('ix_customers_store_id', 'customers', ['store_id'], schema='customer')
    op.create_index('uq_customer_store_email', 'customers', ['store_id', 'email'], unique=True, schema='customer')
    op.create_index('uq_customer_store_mobile', 'customers', ['store_id', 'mobile_e164'], unique=True, schema='customer')
    op.create_index('uq_customer_iam_principal', 'customers', ['iam_principal_id'], unique=True, schema='customer',
                    postgresql_where=sa.text('iam_principal_id IS NOT NULL'))

    # 5. addresses
    op.create_table(
        'addresses',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('customer.customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('address_type', sa.String(16), nullable=False),
        sa.Column('recipient_name', sa.String(200), nullable=False),
        sa.Column('line1', sa.String(240), nullable=False),
        sa.Column('line2', sa.String(240), nullable=True),
        sa.Column('city', sa.String(120), nullable=False),
        sa.Column('state_code', sa.String(16), nullable=False),
        sa.Column('postal_code', sa.String(12), nullable=False),
        sa.Column('country_code', sa.String(2), nullable=False, server_default='IN'),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.CheckConstraint("address_type IN ('SHIPPING', 'BILLING', 'BOTH')", name='ck_address_type'),
        sa.CheckConstraint("country_code = 'IN'", name='ck_country_code_in'),
        schema='customer',
    )
    op.create_index('ix_addresses_tenant_id', 'addresses', ['tenant_id'], schema='customer')
    op.create_index('ix_addresses_store_id', 'addresses', ['store_id'], schema='customer')
    op.create_index('ix_addresses_customer_id', 'addresses', ['customer_id'], schema='customer')
    op.create_index('ix_addresses_city', 'addresses', ['city'], schema='customer')
    op.create_index('ix_addresses_state_code', 'addresses', ['state_code'], schema='customer')
    op.create_index('ix_addresses_postal_code', 'addresses', ['postal_code'], schema='customer')

    # 6. account_claims
    op.create_table(
        'account_claims',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('customer.customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('otp_challenge_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='PENDING'),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resulting_principal_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint("status IN ('PENDING', 'VERIFIED', 'EXPIRED', 'FAILED')", name='ck_claim_status'),
        schema='customer',
    )
    op.create_index('ix_account_claims_tenant_id', 'account_claims', ['tenant_id'], schema='customer')
    op.create_index('ix_account_claims_store_id', 'account_claims', ['store_id'], schema='customer')
    op.create_index('ix_account_claims_customer_id', 'account_claims', ['customer_id'], schema='customer')
    op.create_index('ix_account_claims_otp_challenge', 'account_claims', ['otp_challenge_id'], schema='customer')

    # 7. privacy_requests
    op.create_table(
        'privacy_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('customer_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('customer.customers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('request_type', sa.String(24), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='OPEN'),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retention_basis', sa.Text(), nullable=True),
        sa.CheckConstraint("request_type IN ('ACCESS', 'CORRECT', 'DELETE', 'WITHDRAW_CONSENT')", name='ck_privacy_request_type'),
        sa.CheckConstraint("status IN ('OPEN', 'IN_REVIEW', 'COMPLETED', 'PARTIAL', 'REJECTED_LEGAL_RETENTION')", name='ck_privacy_status'),
        schema='customer',
    )
    op.create_index('ix_privacy_requests_tenant_id', 'privacy_requests', ['tenant_id'], schema='customer')
    op.create_index('ix_privacy_requests_store_id', 'privacy_requests', ['store_id'], schema='customer')
    op.create_index('ix_privacy_requests_customer_id', 'privacy_requests', ['customer_id'], schema='customer')


def downgrade() -> None:
    op.drop_table('privacy_requests', schema='customer')
    op.drop_table('account_claims', schema='customer')
    op.drop_table('addresses', schema='customer')
    op.drop_table('customers', schema='customer')
    op.drop_table('idempotency_keys', schema='customer')
    op.drop_table('processed_events', schema='customer')
    op.drop_table('outbox_events', schema='customer')
