# migrations/versions/002_iam_tables.py
"""Create IAM domain tables (principals, credentials, sessions, refresh_tokens, role_assignments, otp_challenges, security_events)"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    # 1. iam.principals
    op.execute("""
    CREATE TABLE IF NOT EXISTS iam.principals (
        id UUID PRIMARY KEY,
        principal_type VARCHAR(24) NOT NULL DEFAULT 'USER',
        email VARCHAR(255) NULL,
        mobile_e164 VARCHAR(20) NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'ACTIVE',
        email_verified_at TIMESTAMPTZ NULL,
        mobile_verified_at TIMESTAMPTZ NULL,
        last_login_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT chk_principal_type CHECK (principal_type IN ('USER', 'SERVICE')),
        CONSTRAINT chk_principal_status CHECK (status IN ('ACTIVE', 'LOCKED', 'DISABLED', 'PENDING_VERIFICATION'))
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_iam_principals_lower_email
        ON iam.principals (lower(email)) WHERE email IS NOT NULL;
    CREATE UNIQUE INDEX IF NOT EXISTS idx_iam_principals_mobile
        ON iam.principals (mobile_e164) WHERE mobile_e164 IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_iam_principals_status
        ON iam.principals (status);
    """)

    # 2. iam.credentials
    op.execute("""
    CREATE TABLE IF NOT EXISTS iam.credentials (
        id UUID PRIMARY KEY,
        principal_id UUID NOT NULL UNIQUE REFERENCES iam.principals(id) ON DELETE CASCADE,
        password_hash VARCHAR(255) NOT NULL,
        password_version INTEGER NOT NULL DEFAULT 1,
        algorithm VARCHAR(24) NOT NULL DEFAULT 'argon2id',
        failed_attempts INTEGER NOT NULL DEFAULT 0,
        locked_until TIMESTAMPTZ NULL,
        must_rotate BOOLEAN NOT NULL DEFAULT FALSE,
        changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT chk_credential_algorithm CHECK (algorithm IN ('argon2id', 'bcrypt'))
    );
    """)

    # 3. iam.sessions
    op.execute("""
    CREATE TABLE IF NOT EXISTS iam.sessions (
        id UUID PRIMARY KEY,
        principal_id UUID NOT NULL REFERENCES iam.principals(id) ON DELETE CASCADE,
        issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL,
        revoked_at TIMESTAMPTZ NULL,
        ip_address VARCHAR(45) NULL,
        user_agent VARCHAR(512) NULL
    );
    CREATE INDEX IF NOT EXISTS idx_iam_sessions_principal
        ON iam.sessions (principal_id);
    CREATE INDEX IF NOT EXISTS idx_iam_sessions_revoked
        ON iam.sessions (revoked_at);
    """)

    # 4. iam.refresh_tokens (with reuse history per BTDD §9.1 and review)
    op.execute("""
    CREATE TABLE IF NOT EXISTS iam.refresh_tokens (
        id UUID PRIMARY KEY,
        session_id UUID NOT NULL REFERENCES iam.sessions(id) ON DELETE CASCADE,
        token_hash VARCHAR(64) NOT NULL UNIQUE,
        replaced_by UUID NULL REFERENCES iam.refresh_tokens(id),
        used_at TIMESTAMPTZ NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    CREATE INDEX IF NOT EXISTS idx_iam_refresh_tokens_session
        ON iam.refresh_tokens (session_id);
    CREATE INDEX IF NOT EXISTS idx_iam_refresh_tokens_used
        ON iam.refresh_tokens (used_at);
    """)

    # 5. iam.role_assignments (with strict scope validity check)
    op.execute("""
    CREATE TABLE IF NOT EXISTS iam.role_assignments (
        id UUID PRIMARY KEY,
        principal_id UUID NOT NULL REFERENCES iam.principals(id) ON DELETE CASCADE,
        role_code VARCHAR(40) NOT NULL,
        tenant_id UUID NULL,
        store_id UUID NULL,
        valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
        valid_until TIMESTAMPTZ NULL,
        granted_by UUID NULL,
        revoked_at TIMESTAMPTZ NULL,
        CONSTRAINT chk_role_scope_validity CHECK (
            (role_code IN ('PLATFORM_OWNER', 'PLATFORM_STAFF', 'GST_STAFF') AND tenant_id IS NULL AND store_id IS NULL)
            OR (role_code = 'STORE_OWNER' AND tenant_id IS NOT NULL AND store_id IS NULL)
            OR (role_code = 'STORE_STAFF' AND tenant_id IS NOT NULL AND store_id IS NOT NULL)
            OR (role_code = 'GUARDIAN' AND tenant_id IS NOT NULL AND store_id IS NULL)
            OR (role_code = 'CUSTOMER' AND store_id IS NOT NULL)
            OR (role_code = 'SERVICE' AND tenant_id IS NULL AND store_id IS NULL)
        )
    );
    CREATE INDEX IF NOT EXISTS idx_iam_role_assignments_principal
        ON iam.role_assignments (principal_id);
    CREATE INDEX IF NOT EXISTS idx_iam_role_assignments_role_code
        ON iam.role_assignments (role_code);
    CREATE INDEX IF NOT EXISTS idx_iam_role_assignments_tenant
        ON iam.role_assignments (tenant_id) WHERE tenant_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_iam_role_assignments_store
        ON iam.role_assignments (store_id) WHERE store_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_iam_role_assignments_active
        ON iam.role_assignments (revoked_at) WHERE revoked_at IS NULL;
    """)

    # 6. iam.otp_challenges
    op.execute("""
    CREATE TABLE IF NOT EXISTS iam.otp_challenges (
        id UUID PRIMARY KEY,
        principal_id UUID NULL REFERENCES iam.principals(id) ON DELETE CASCADE,
        channel VARCHAR(16) NOT NULL,
        destination_fingerprint VARCHAR(64) NOT NULL,
        purpose VARCHAR(32) NOT NULL,
        otp_hash VARCHAR(64) NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        consumed_at TIMESTAMPTZ NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT chk_otp_channel CHECK (channel IN ('EMAIL', 'SMS')),
        CONSTRAINT chk_otp_purpose CHECK (purpose IN ('ACCOUNT_CLAIM', 'STEP_UP_AUTH', 'VERIFICATION'))
    );
    CREATE INDEX IF NOT EXISTS idx_iam_otp_fingerprint
        ON iam.otp_challenges (destination_fingerprint);
    CREATE INDEX IF NOT EXISTS idx_iam_otp_expires
        ON iam.otp_challenges (expires_at);
    CREATE INDEX IF NOT EXISTS idx_iam_otp_consumed
        ON iam.otp_challenges (consumed_at);
    """)

    # 7. iam.security_events (append-only)
    op.execute("""
    CREATE TABLE IF NOT EXISTS iam.security_events (
        id UUID PRIMARY KEY,
        principal_id UUID NULL REFERENCES iam.principals(id) ON DELETE SET NULL,
        event_type VARCHAR(64) NOT NULL,
        result VARCHAR(24) NOT NULL,
        ip_address VARCHAR(45) NULL,
        user_agent VARCHAR(512) NULL,
        correlation_id UUID NOT NULL,
        occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        details JSONB NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_iam_sec_events_principal
        ON iam.security_events (principal_id);
    CREATE INDEX IF NOT EXISTS idx_iam_sec_events_type
        ON iam.security_events (event_type);
    CREATE INDEX IF NOT EXISTS idx_iam_sec_events_occurred
        ON iam.security_events (occurred_at);
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS iam.security_events;")
    op.execute("DROP TABLE IF EXISTS iam.otp_challenges;")
    op.execute("DROP TABLE IF EXISTS iam.role_assignments;")
    op.execute("DROP TABLE IF EXISTS iam.refresh_tokens;")
    op.execute("DROP TABLE IF EXISTS iam.sessions;")
    op.execute("DROP TABLE IF EXISTS iam.credentials;")
    op.execute("DROP TABLE IF EXISTS iam.principals;")
