"""002_approval_tables

Revision ID: 002_approval
Revises: 001_initial
Create Date: 2026-11-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002_approval'
down_revision = '001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. approval.approval_requests
    op.create_table(
        'approval_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('subject_type', sa.String(length=40), nullable=False),
        sa.Column('subject_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subject_version', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=24), server_default='PENDING', nullable=False),
        sa.Column('submitted_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('priority', sa.SmallInteger(), server_default='0', nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'TAKEDOWN', 'UNPUBLISHED')",
            name='ck_approval_request_status',
        ),
        schema='approval',
    )
    op.create_index('idx_approval_req_tenant', 'approval_requests', ['tenant_id'], schema='approval')
    op.create_index('idx_approval_req_store', 'approval_requests', ['store_id'], schema='approval')
    op.create_index('idx_approval_req_subject_type', 'approval_requests', ['subject_type'], schema='approval')
    op.create_index('idx_approval_req_subject_id', 'approval_requests', ['subject_id'], schema='approval')
    op.create_index('idx_approval_req_status', 'approval_requests', ['status'], schema='approval')
    op.create_index('idx_approval_req_submitted_by', 'approval_requests', ['submitted_by'], schema='approval')
    op.create_index('idx_approval_req_priority', 'approval_requests', ['priority'], schema='approval')

    # 2. approval.approval_decisions
    op.create_table(
        'approval_decisions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column(
            'approval_request_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('approval.approval_requests.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('decision', sa.String(length=20), nullable=False),
        sa.Column('reason_code', sa.String(length=40), nullable=True),
        sa.Column('reason_text', sa.Text(), nullable=True),
        sa.Column('decided_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('evidence_json', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False),
        sa.CheckConstraint(
            "decision IN ('APPROVE', 'REJECT', 'UNPUBLISH')",
            name='ck_approval_decision_type',
        ),
        schema='approval',
    )
    op.create_index('idx_approval_dec_tenant', 'approval_decisions', ['tenant_id'], schema='approval')
    op.create_index('idx_approval_dec_store', 'approval_decisions', ['store_id'], schema='approval')
    op.create_index('idx_approval_dec_req_id', 'approval_decisions', ['approval_request_id'], schema='approval')
    op.create_index('idx_approval_dec_decided_by', 'approval_decisions', ['decided_by'], schema='approval')
    op.create_index('idx_approval_dec_reason_code', 'approval_decisions', ['reason_code'], schema='approval')

    # 3. approval.takedowns
    op.create_table(
        'takedowns',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('store_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column(
            'approval_request_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('approval.approval_requests.id', ondelete='SET NULL'),
            nullable=True,
        ),
        sa.Column('subject_type', sa.String(length=40), nullable=False),
        sa.Column('subject_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reason_code', sa.String(length=40), nullable=False),
        sa.Column('reason_text', sa.Text(), nullable=False),
        sa.Column('executed_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('executed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('restored_at', sa.DateTime(timezone=True), nullable=True),
        schema='approval',
    )
    op.create_index('idx_takedown_tenant', 'takedowns', ['tenant_id'], schema='approval')
    op.create_index('idx_takedown_store', 'takedowns', ['store_id'], schema='approval')
    op.create_index('idx_takedown_req_id', 'takedowns', ['approval_request_id'], schema='approval')
    op.create_index('idx_takedown_subject', 'takedowns', ['subject_type', 'subject_id'], schema='approval')
    op.create_index('idx_takedown_executed_by', 'takedowns', ['executed_by'], schema='approval')

    # 4. approval.approval_state_history
    op.create_table(
        'approval_state_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            'approval_request_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('approval.approval_requests.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('from_status', sa.String(length=24), nullable=False),
        sa.Column('to_status', sa.String(length=24), nullable=False),
        sa.Column('actor_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        schema='approval',
    )
    op.create_index('idx_approval_history_req_id', 'approval_state_history', ['approval_request_id'], schema='approval')


def downgrade() -> None:
    op.drop_table('approval_state_history', schema='approval')
    op.drop_table('takedowns', schema='approval')
    op.drop_table('approval_decisions', schema='approval')
    op.drop_table('approval_requests', schema='approval')
