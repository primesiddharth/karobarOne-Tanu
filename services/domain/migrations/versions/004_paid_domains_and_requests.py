"""004_paid_domains_and_requests

Revision ID: 004_domain
Revises: 003_domain
Create Date: 2026-11-07 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '004_domain'
down_revision = '003_domain'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create domain.domain_requests
    op.create_table(
        'domain_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('preferred_domains', postgresql.JSONB(), nullable=False),
        sa.Column('selected_domain', sa.String(255), nullable=True),
        sa.Column('cost_class', sa.String(24), nullable=False, server_default='STANDARD'),
        sa.Column('price_paise', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('approval_ref', sa.String(128), nullable=True),
        sa.Column('payment_ref', sa.String(128), nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='PREFERENCE_SUBMITTED'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('PREFERENCE_SUBMITTED', 'AVAILABILITY_CHECKED', 'SELECTED', 'PURCHASE_PENDING', 'PURCHASED', 'DNS_PENDING', 'DNS_VERIFIED', 'ACTIVE', 'STOPPED_FREE_CONVERSION', 'REJECTED')",
            name='ck_domain_request_status',
        ),
        sa.CheckConstraint(
            "cost_class IN ('STANDARD', 'PREMIUM')",
            name='ck_domain_request_cost_class',
        ),
        schema='domain',
    )
    op.create_index('ix_domain_requests_tenant_id', 'domain_requests', ['tenant_id'], schema='domain')
    op.create_index('ix_domain_requests_store_id', 'domain_requests', ['store_id'], schema='domain')
    op.create_index('ix_domain_requests_selected_domain', 'domain_requests', ['selected_domain'], schema='domain')
    op.create_index('ix_domain_requests_status', 'domain_requests', ['status'], schema='domain')

    # 2. Add columns to domain.domains
    op.add_column('domains', sa.Column('domain_request_id', postgresql.UUID(as_uuid=True), nullable=True), schema='domain')
    op.add_column('domains', sa.Column('registrar_code', sa.String(40), nullable=False, server_default='MOCK_REGISTRAR'), schema='domain')
    op.add_column('domains', sa.Column('registrar_reference', sa.String(128), nullable=True), schema='domain')
    op.add_column('domains', sa.Column('cost_class', sa.String(24), nullable=False, server_default='STANDARD'), schema='domain')
    op.add_column('domains', sa.Column('purchase_cost', sa.Integer(), nullable=False, server_default='0'), schema='domain')
    op.add_column('domains', sa.Column('approval_ref', sa.String(128), nullable=True), schema='domain')
    op.add_column('domains', sa.Column('payment_ref', sa.String(128), nullable=True), schema='domain')
    op.add_column('domains', sa.Column('transfer_review_notes', sa.String(500), nullable=True), schema='domain')
    op.add_column('domains', sa.Column('transfer_review_opened_at', sa.DateTime(timezone=True), nullable=True), schema='domain')
    op.add_column('domains', sa.Column('registered_at', sa.DateTime(timezone=True), nullable=True), schema='domain')
    op.add_column('domains', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True), schema='domain')
    op.add_column('domains', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), schema='domain')
    op.create_index('ix_domains_domain_request_id', 'domains', ['domain_request_id'], schema='domain')
    op.create_index('ix_domains_registrar_reference', 'domains', ['registrar_reference'], schema='domain')

    # 3. Create domain.dns_checks
    op.create_table(
        'dns_checks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('domain_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('domain_request_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('check_type', sa.String(16), nullable=False, server_default='CNAME'),
        sa.Column('expected_value', sa.String(255), nullable=False),
        sa.Column('observed_value', sa.String(255), nullable=True),
        sa.Column('result', sa.String(16), nullable=False, server_default='PENDING'),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "result IN ('PENDING', 'VERIFIED', 'FAILED')",
            name='ck_dns_check_result',
        ),
        schema='domain',
    )
    op.create_index('ix_dns_checks_domain_id', 'dns_checks', ['domain_id'], schema='domain')
    op.create_index('ix_dns_checks_store_id', 'dns_checks', ['store_id'], schema='domain')

    # 4. RLS for newly created tables
    for t in ['domain_requests', 'dns_checks']:
        op.execute(f"ALTER TABLE domain.{t} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE domain.{t} FORCE ROW LEVEL SECURITY;")

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

        op.execute(f"""
            CREATE POLICY {t}_tenant_isolation ON domain.{t}
            FOR ALL
            TO domain_svc
            USING (
                (store_id = NULLIF(current_setting('app.store_id', true), '')::uuid)
                OR (current_setting('app.is_platform_admin', true) = 'true')
            )
            WITH CHECK (
                (store_id = NULLIF(current_setting('app.store_id', true), '')::uuid)
                OR (current_setting('app.is_platform_admin', true) = 'true')
            );
        """)


def downgrade() -> None:
    for t in ['domain_requests', 'dns_checks']:
        op.execute(f"DROP POLICY IF EXISTS migrator_full_access ON domain.{t};")
        op.execute(f"DROP POLICY IF EXISTS {t}_tenant_isolation ON domain.{t};")
        op.execute(f"ALTER TABLE domain.{t} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE domain.{t} DISABLE ROW LEVEL SECURITY;")

    op.drop_table('dns_checks', schema='domain')
    op.drop_table('domain_requests', schema='domain')
    op.drop_column('domains', 'updated_at', schema='domain')
    op.drop_column('domains', 'expires_at', schema='domain')
    op.drop_column('domains', 'registered_at', schema='domain')
    op.drop_column('domains', 'transfer_review_opened_at', schema='domain')
    op.drop_column('domains', 'transfer_review_notes', schema='domain')
    op.drop_column('domains', 'payment_ref', schema='domain')
    op.drop_column('domains', 'approval_ref', schema='domain')
    op.drop_column('domains', 'purchase_cost', schema='domain')
    op.drop_column('domains', 'cost_class', schema='domain')
    op.drop_column('domains', 'registrar_reference', schema='domain')
    op.drop_column('domains', 'registrar_code', schema='domain')
    op.drop_column('domains', 'domain_request_id', schema='domain')
