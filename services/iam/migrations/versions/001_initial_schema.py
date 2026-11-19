# migrations/versions/001_initial_schema.py
"""Initial baseline schema for iam"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS iam;")
    op.execute("""
    CREATE TABLE IF NOT EXISTS iam.outbox_events (
        id UUID PRIMARY KEY,
        event_id UUID NOT NULL,
        event_version INTEGER NOT NULL DEFAULT 1,
        event_type VARCHAR(128) NOT NULL,
        aggregate_type VARCHAR(64) NOT NULL,
        aggregate_id UUID NOT NULL,
        tenant_id UUID,
        store_id UUID,
        occurred_at TIMESTAMPTZ NOT NULL,
        correlation_id UUID NOT NULL,
        causation_id UUID,
        producer VARCHAR(64) NOT NULL,
        payload JSONB NOT NULL,
        topic VARCHAR(128) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        locked_until TIMESTAMPTZ,
        published_at TIMESTAMPTZ,
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TIMESTAMPTZ,
        dead BOOLEAN NOT NULL DEFAULT FALSE
    );
    """)

    op.execute("""
    CREATE INDEX IF NOT EXISTS idx_iam_outbox_pending
        ON iam.outbox_events (created_at)
        WHERE published_at IS NULL AND dead = FALSE;
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS iam.processed_events (
        consumer VARCHAR(64) NOT NULL,
        event_id UUID NOT NULL,
        processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (consumer, event_id)
    );
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS iam.idempotency_keys (
        id UUID PRIMARY KEY,
        scope VARCHAR(64) NOT NULL,
        key VARCHAR(128) NOT NULL,
        request_hash VARCHAR(128) NOT NULL,
        response_code INTEGER NOT NULL,
        response_body JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        locked_until TIMESTAMPTZ NOT NULL,
        CONSTRAINT uq_iam_idempotency UNIQUE (scope, key)
    );
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS iam.idempotency_keys;")
    op.execute("DROP TABLE IF EXISTS iam.processed_events;")
    op.execute("DROP TABLE IF EXISTS iam.outbox_events;")
