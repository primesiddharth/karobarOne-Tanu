"""002_tenant_tables

Revision ID: 002_tenant
Revises: 001_initial
Create Date: 2026-11-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002_tenant'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. tenant.tenants
    op.create_table(
        'tenants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('pan_ciphertext', sa.LargeBinary(), nullable=False),
        sa.Column('pan_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('pan_masked', sa.String(length=16), nullable=False),
        sa.Column('legal_name', sa.String(length=200), nullable=False),
        sa.Column('date_of_birth', sa.Date(), nullable=True),
        sa.Column('tenant_type', sa.String(length=24), server_default='INDIVIDUAL', nullable=False),
        sa.Column('minor_status', sa.String(length=32), server_default='NOT_MINOR', nullable=False),
        sa.Column('status', sa.String(length=24), server_default='PENDING', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('pan_fingerprint', name='uq_tenant_pan_fingerprint'),
        sa.CheckConstraint("tenant_type IN ('INDIVIDUAL', 'BUSINESS', 'OTHER')", name='chk_tenant_type'),
        sa.CheckConstraint(
            "minor_status IN ('NOT_MINOR', 'GUARDIAN_REQUIRED', 'GUARDIAN_VERIFICATION', 'CONSENT_ACCEPTED', 'MINOR_TENANT_ACTIVE', 'ADULT_REVERIFICATION_REQUIRED')",
            name='chk_tenant_minor_status'
        ),
        sa.CheckConstraint("status IN ('PENDING', 'ACTIVE', 'SUSPENDED', 'TERMINATED', 'ARCHIVED')", name='chk_tenant_status'),
        schema='tenant'
    )
    op.create_index('idx_tenant_pan_fingerprint', 'tenants', ['pan_fingerprint'], schema='tenant')
    op.create_index('idx_tenant_legal_name', 'tenants', ['legal_name'], schema='tenant')
    op.create_index('idx_tenant_minor_status', 'tenants', ['minor_status'], schema='tenant')
    op.create_index('idx_tenant_status', 'tenants', ['status'], schema='tenant')

    # 2. tenant.pan_verifications
    op.create_table(
        'pan_verifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider_code', sa.String(length=32), server_default='MOCK_V1', nullable=False),
        sa.Column('provider_reference', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('verified_name', sa.String(length=200), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        schema='tenant'
    )
    op.create_index('idx_pan_verif_tenant', 'pan_verifications', ['tenant_id'], schema='tenant')

    # 3. tenant.guardians
    op.create_table(
        'guardians',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('principal_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('full_name', sa.String(length=200), nullable=False),
        sa.Column('relationship_code', sa.String(length=40), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('mobile_e164', sa.String(length=20), nullable=False),
        sa.Column('verification_status', sa.String(length=24), server_default='PENDING', nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("relationship_code IN ('PARENT', 'LEGAL_GUARDIAN')", name='chk_guardian_relationship'),
        sa.CheckConstraint("verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')", name='chk_guardian_verification_status'),
        schema='tenant'
    )
    op.create_index('idx_guardian_tenant', 'guardians', ['tenant_id'], schema='tenant')
    op.create_index('idx_guardian_email', 'guardians', ['email'], schema='tenant')

    # 4. tenant.guardian_consents
    op.create_table(
        'guardian_consents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('guardian_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.guardians.id', ondelete='CASCADE'), nullable=False),
        sa.Column('consent_type', sa.String(length=40), nullable=False),
        sa.Column('document_code', sa.String(length=64), nullable=False),
        sa.Column('document_version', sa.String(length=32), nullable=False),
        sa.Column('document_hash', sa.String(length=64), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('acceptance_ip', sa.String(length=45), nullable=True),
        schema='tenant'
    )
    op.create_index('idx_consent_tenant', 'guardian_consents', ['tenant_id'], schema='tenant')
    op.create_index('idx_consent_guardian', 'guardian_consents', ['guardian_id'], schema='tenant')

    # 5. tenant.gstins
    op.create_table(
        'gstins',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('gstin_ciphertext', sa.LargeBinary(), nullable=False),
        sa.Column('gstin_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('gstin_masked', sa.String(length=20), nullable=False),
        sa.Column('state_code', sa.String(length=2), nullable=False),
        sa.Column('legal_name', sa.String(length=200), nullable=True),
        sa.Column('verification_status', sa.String(length=24), server_default='PENDING', nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.UniqueConstraint('gstin_fingerprint', name='uq_tenant_gstin_fingerprint'),
        sa.CheckConstraint("verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')", name='chk_gstin_verification_status'),
        schema='tenant'
    )
    op.create_index('idx_gstin_tenant', 'gstins', ['tenant_id'], schema='tenant')

    # 6. tenant.gstin_verifications
    op.create_table(
        'gstin_verifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('gstin_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.gstins.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider_code', sa.String(length=32), server_default='MOCK_V1', nullable=False),
        sa.Column('provider_reference', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('verified_pan_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        schema='tenant'
    )
    op.create_index('idx_gstin_verif_gstin', 'gstin_verifications', ['gstin_id'], schema='tenant')

    # 7. tenant.stores
    op.create_table(
        'stores',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('store_code', sa.String(length=32), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=False),
        sa.Column('store_mode', sa.String(length=24), server_default='FREE_PRESENCE', nullable=False),
        sa.Column('lifecycle_status', sa.String(length=32), server_default='DRAFT', nullable=False),
        sa.Column('gstin_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.gstins.id', ondelete='SET NULL'), nullable=True),
        sa.Column('timezone', sa.String(length=64), server_default='Asia/Kolkata', nullable=False),
        sa.Column('currency_code', sa.String(length=3), server_default='INR', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('store_code', name='uq_tenant_store_code'),
        sa.CheckConstraint("store_mode IN ('FREE_PRESENCE', 'PAID_COMMERCE')", name='chk_store_mode'),
        sa.CheckConstraint(
            "lifecycle_status IN ('DRAFT', 'REVIEW', 'ACTIVE', 'PAYMENT_GRACE', 'SUBSCRIPTION_EXPIRED', 'SUSPENDED', 'ARCHIVED', 'TERMINATED')",
            name='chk_store_lifecycle_status'
        ),
        schema='tenant'
    )
    op.create_index('idx_store_tenant', 'stores', ['tenant_id'], schema='tenant')
    op.create_index(
        'uq_active_store_gstin_store',
        'stores',
        ['gstin_id'],
        unique=True,
        schema='tenant',
        postgresql_where=sa.text('gstin_id IS NOT NULL AND archived_at IS NULL')
    )

    # 8. tenant.free_store_entitlements
    op.create_table(
        'free_store_entitlements',
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.tenants.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('status', sa.String(length=16), server_default='AVAILABLE', nullable=False),
        sa.Column('consumed_store_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.stores.id', ondelete='SET NULL'), nullable=True),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('AVAILABLE', 'CONSUMED')", name='chk_free_store_entitlement_status'),
        schema='tenant'
    )
    op.create_index(
        'uq_free_entitlement_consumed_store',
        'free_store_entitlements',
        ['consumed_store_id'],
        unique=True,
        schema='tenant',
        postgresql_where=sa.text('consumed_store_id IS NOT NULL')
    )

    # 9. tenant.store_memberships
    op.create_table(
        'store_memberships',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.stores.id', ondelete='CASCADE'), nullable=False),
        sa.Column('principal_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role_code', sa.String(length=40), server_default='STORE_STAFF', nullable=False),
        sa.Column('status', sa.String(length=24), server_default='ACTIVE', nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name='chk_membership_status'),
        schema='tenant'
    )
    op.create_index('idx_membership_store', 'store_memberships', ['store_id'], schema='tenant')
    op.create_index('idx_membership_principal', 'store_memberships', ['principal_id'], schema='tenant')

    # 10. tenant.seller_identity_snapshots
    op.create_table(
        'seller_identity_snapshots',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenant.stores.id', ondelete='CASCADE'), nullable=False),
        sa.Column('legal_name', sa.String(length=200), nullable=False),
        sa.Column('pan_masked', sa.String(length=16), nullable=False),
        sa.Column('gstin_masked', sa.String(length=20), nullable=True),
        sa.Column('snapshotted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        schema='tenant'
    )
    op.create_index('idx_snapshot_store', 'seller_identity_snapshots', ['store_id'], schema='tenant')


def downgrade() -> None:
    op.drop_table('seller_identity_snapshots', schema='tenant')
    op.drop_table('store_memberships', schema='tenant')
    op.drop_table('free_store_entitlements', schema='tenant')
    op.drop_table('stores', schema='tenant')
    op.drop_table('gstin_verifications', schema='tenant')
    op.drop_table('gstins', schema='tenant')
    op.drop_table('guardian_consents', schema='tenant')
    op.drop_table('guardians', schema='tenant')
    op.drop_table('pan_verifications', schema='tenant')
    op.drop_table('tenants', schema='tenant')
