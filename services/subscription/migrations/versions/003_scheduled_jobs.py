"""003_scheduled_jobs

Revision ID: 003_subscription
Revises: 002_subscription
Create Date: 2026-11-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '003_subscription'
down_revision = '002_subscription'
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        sa.UniqueConstraint('business_key', name='uq_subscription_scheduled_business_key'),
        schema='subscription'
    )

    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'subscription_svc') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON subscription.scheduled_jobs TO subscription_svc;
        END IF;
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'subscription_migrator') THEN
            GRANT ALL ON subscription.scheduled_jobs TO subscription_migrator;
        END IF;
    END
    $$;
    """)


def downgrade() -> None:
    op.drop_table('scheduled_jobs', schema='subscription')
