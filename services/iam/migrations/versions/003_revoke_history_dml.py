# migrations/versions/003_revoke_history_dml.py
"""Revoke UPDATE and DELETE on immutable audit table iam.security_events from runtime role iam_svc"""
from alembic import op

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    # RULES.md §5: Audit/security_events table is insert-only. Runtime role has no UPDATE/DELETE on it.
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'iam_svc') THEN
            REVOKE UPDATE, DELETE ON TABLE iam.security_events FROM iam_svc;
        END IF;
    END
    $$;
    """)


def downgrade():
    op.execute("""
    DO $$
    BEGIN
        IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'iam_svc') THEN
            GRANT UPDATE, DELETE ON TABLE iam.security_events TO iam_svc;
        END IF;
    END
    $$;
    """)
