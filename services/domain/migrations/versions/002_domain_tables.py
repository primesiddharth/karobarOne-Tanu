"""002_domain_tables

Revision ID: 002_domain
Revises: 001_initial
Create Date: 2026-11-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002_domain'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. domain.subdomains
    op.create_table(
        'subdomains',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('label', sa.String(length=63), nullable=False),
        sa.Column('fqdn', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=24), server_default='ASSIGNED', nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('disabled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('label', name='uq_subdomain_label'),
        sa.UniqueConstraint('fqdn', name='uq_subdomain_fqdn'),
        sa.UniqueConstraint('store_id', name='uq_store_subdomain'),
        sa.CheckConstraint("status IN ('ASSIGNED', 'ACTIVE', 'DISABLED')", name='ck_subdomain_status'),
        schema='domain',
    )
    op.create_index('idx_subdomain_tenant', 'subdomains', ['tenant_id'], schema='domain')
    op.create_index('idx_subdomain_store', 'subdomains', ['store_id'], schema='domain')
    op.create_index('idx_subdomain_label', 'subdomains', ['label'], schema='domain')
    op.create_index('idx_subdomain_fqdn', 'subdomains', ['fqdn'], schema='domain')

    # 2. domain.publication_routes
    op.create_table(
        'publication_routes',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('route_type', sa.String(length=24), nullable=False),
        sa.Column('hostname', sa.String(length=255), nullable=False),
        sa.Column('target_revision_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(length=24), server_default='DISABLED', nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "route_type IN ('FREE_SUBDOMAIN', 'CUSTOM_DOMAIN', 'SYSTEM_PREVIEW')",
            name='ck_publication_route_type',
        ),
        sa.CheckConstraint(
            "status IN ('DISABLED', 'ACTIVE', 'PENDING_DNS', 'SUSPENDED')",
            name='ck_publication_route_status',
        ),
        schema='domain',
    )
    op.create_index('idx_pub_route_tenant', 'publication_routes', ['tenant_id'], schema='domain')
    op.create_index('idx_pub_route_store', 'publication_routes', ['store_id'], schema='domain')
    op.create_index('idx_pub_route_hostname', 'publication_routes', ['hostname'], schema='domain')
    op.create_index('idx_pub_route_status', 'publication_routes', ['status'], schema='domain')

    # 3. domain.domains
    op.create_table(
        'domains',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('domain_name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=32), server_default='PENDING_PURCHASE', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('domain_name', name='uq_custom_domain_name'),
        schema='domain',
    )


def downgrade() -> None:
    op.drop_table('domains', schema='domain')
    op.drop_table('publication_routes', schema='domain')
    op.drop_table('subdomains', schema='domain')
