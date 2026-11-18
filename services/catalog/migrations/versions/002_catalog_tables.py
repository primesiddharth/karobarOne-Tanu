"""002_catalog_tables

Revision ID: 002_catalog
Revises: 001_initial
Create Date: 2026-11-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002_catalog'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. catalog.catalog_items
    op.create_table(
        'catalog_items',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('item_type', sa.String(length=32), nullable=False),
        sa.Column('price_paise', sa.BigInteger(), server_default='0', nullable=False),
        sa.Column('currency_code', sa.String(length=3), server_default='INR', nullable=False),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('live_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('draft_version_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "item_type IN ('PHYSICAL_PRODUCT', 'DIGITAL_PRODUCT', 'APPOINTMENT_SERVICE', 'NON_APPOINTMENT_SERVICE')",
            name='ck_catalog_item_type',
        ),
        schema='catalog',
    )
    op.create_index('idx_catalog_item_tenant', 'catalog_items', ['tenant_id'], schema='catalog')
    op.create_index('idx_catalog_item_store', 'catalog_items', ['store_id'], schema='catalog')
    op.create_index('idx_catalog_item_type', 'catalog_items', ['item_type'], schema='catalog')
    op.create_index('idx_catalog_item_active', 'catalog_items', ['active'], schema='catalog')

    # 2. catalog.item_versions
    op.create_table(
        'item_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('catalog.catalog_items.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('version_no', sa.Integer(), server_default='1', nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), server_default='', nullable=False),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('approval_state', sa.String(length=32), server_default='DRAFT', nullable=False),
        sa.Column('approval_request_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "approval_state IN ('DRAFT', 'PENDING', 'APPROVED_LIVE', 'REJECTED', 'UNPUBLISHED', 'EMERGENCY_TAKEDOWN')",
            name='ck_item_version_approval_state',
        ),
        schema='catalog',
    )
    op.create_index('idx_item_version_item', 'item_versions', ['item_id'], schema='catalog')
    op.create_index('idx_item_version_tenant', 'item_versions', ['tenant_id'], schema='catalog')
    op.create_index('idx_item_version_store', 'item_versions', ['store_id'], schema='catalog')
    op.create_index('idx_item_version_approval_state', 'item_versions', ['approval_state'], schema='catalog')

    # 3. catalog.product_details
    op.create_table(
        'product_details',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('catalog.catalog_items.id', ondelete='CASCADE'),
            nullable=False,
            unique=True,
        ),
        sa.Column('is_digital', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('sku_code', sa.String(length=64), nullable=True),
        schema='catalog',
    )

    # 4. catalog.service_details
    op.create_table(
        'service_details',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'item_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('catalog.catalog_items.id', ondelete='CASCADE'),
            nullable=False,
            unique=True,
        ),
        sa.Column('is_appointment', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=True),
        schema='catalog',
    )

    # 5. catalog.item_media
    op.create_table(
        'item_media',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'item_version_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('catalog.item_versions.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('media_type', sa.String(length=16), nullable=False),
        sa.Column('storage_key', sa.String(length=512), nullable=False),
        sa.Column('url', sa.String(length=1024), nullable=False),
        sa.Column('sort_order', sa.SmallInteger(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("media_type IN ('IMAGE', 'VIDEO')", name='ck_item_media_type'),
        schema='catalog',
    )
    op.create_index('idx_item_media_version', 'item_media', ['item_version_id'], schema='catalog')

    # 6. catalog.entitlement_projection
    op.create_table(
        'entitlement_projection',
        sa.Column('store_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('plan_tier', sa.String(length=32), server_default='FREE', nullable=False),
        sa.Column('max_items', sa.Integer(), server_default='6', nullable=False),
        sa.Column('max_images_per_item', sa.Integer(), server_default='1', nullable=False),
        sa.Column('max_videos_per_item', sa.Integer(), server_default='0', nullable=False),
        sa.Column('blog_enabled', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        schema='catalog',
    )
    op.create_index('idx_entitlement_proj_tenant', 'entitlement_projection', ['tenant_id'], schema='catalog')


def downgrade() -> None:
    op.drop_table('entitlement_projection', schema='catalog')
    op.drop_table('item_media', schema='catalog')
    op.drop_table('service_details', schema='catalog')
    op.drop_table('product_details', schema='catalog')
    op.drop_table('item_versions', schema='catalog')
    op.drop_table('catalog_items', schema='catalog')
