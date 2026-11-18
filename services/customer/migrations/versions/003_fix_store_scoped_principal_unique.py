"""003_fix_store_scoped_principal_unique

Revision ID: 003_customer
Revises: 002_customer
Create Date: 2026-11-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '003_customer'
down_revision = '002_customer'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fix IDOR / multi-store lockout: customer account is store-scoped
    op.drop_index('uq_customer_iam_principal', table_name='customers', schema='customer')
    op.create_index(
        'uq_customer_store_principal',
        'customers',
        ['store_id', 'iam_principal_id'],
        unique=True,
        schema='customer',
        postgresql_where=sa.text('iam_principal_id IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index('uq_customer_store_principal', table_name='customers', schema='customer')
    op.create_index(
        'uq_customer_iam_principal',
        'customers',
        ['iam_principal_id'],
        unique=True,
        schema='customer',
        postgresql_where=sa.text('iam_principal_id IS NOT NULL'),
    )
