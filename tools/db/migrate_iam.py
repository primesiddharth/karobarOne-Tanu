#!/usr/bin/env python3
"""
migrate_iam.py — Idempotent data migration from monolith into iam schema.
Preserves UUIDs, maps bcrypt hashes, converts superusers to PLATFORM_OWNER.
Usage:
    python tools/db/migrate_iam.py [--source <sqlite_path_or_url>]
"""
import os
import sys
import uuid
from pathlib import Path
from sqlalchemy import create_engine, text

microservice_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(microservice_dir))


def migrate_iam_data(source_url: str | None = None, target_url: str | None = None) -> None:
    # Default to monolith SQLite if present, else environment
    default_source = f"sqlite:///{microservice_dir.parent / 'karobar.db'}"
    src_conn_str = source_url or os.environ.get("MONOLITH_DATABASE_URL", default_source)
    tgt_conn_str = target_url or os.environ.get("MIGRATION_DATABASE_URL", "postgresql://iam_migrator:dev_migrator_secret@localhost:5432/karobarone_dev")

    # Clean asyncpg for sync migration execution
    tgt_sync_str = tgt_conn_str.replace("+asyncpg", "")

    print("=" * 60)
    print("IAM Data Migration: Monolith -> microservice/iam")
    print(f"Source: {src_conn_str}")
    print(f"Target: {tgt_sync_str}")
    print("=" * 60)

    try:
        src_engine = create_engine(src_conn_str)
        with src_engine.connect() as src_conn:
            # Check if users table exists in source
            check_table = src_conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")).scalar()
            if not check_table:
                print("[INFO] Monolith 'users' table not present in source database. 0 rows to migrate.")
                return

            rows = src_conn.execute(text("SELECT id, email, phone_number, password_hash, is_active, is_superuser, created_at, updated_at FROM users")).fetchall()
            source_count = len(rows)
            print(f"[FOUND] {source_count} user rows in source.")
    except Exception as e:
        print(f"[WARN] Could not connect to source database: {e}")
        source_count = 0
        rows = []

    try:
        tgt_engine = create_engine(tgt_sync_str)
        with tgt_engine.begin() as tgt_conn:
            migrated_principals = 0
            migrated_credentials = 0
            migrated_roles = 0

            for r in rows:
                user_id_str, email, phone, pwd_hash, is_active, is_super, cr_at, up_at = r
                try:
                    user_uuid = uuid.UUID(str(user_id_str))
                except ValueError:
                    user_uuid = uuid.uuid4()

                norm_email = email.strip().lower() if email else None
                status = "ACTIVE" if is_active else "DISABLED"

                # 1. Upsert Principal
                tgt_conn.execute(
                    text("""
                        INSERT INTO iam.principals (id, principal_type, email, mobile_e164, status, created_at, updated_at)
                        VALUES (:id, 'USER', :email, :mobile, :status, now(), now())
                        ON CONFLICT (id) DO UPDATE
                        SET email = EXCLUDED.email, status = EXCLUDED.status, updated_at = now();
                    """),
                    {"id": str(user_uuid), "email": norm_email, "mobile": phone, "status": status}
                )
                migrated_principals += 1

                # 2. Upsert Credential (preserve bcrypt for verify-then-rehash)
                if pwd_hash:
                    tgt_conn.execute(
                        text("""
                            INSERT INTO iam.credentials (id, principal_id, password_hash, password_version, algorithm, failed_attempts, changed_at)
                            VALUES (:id, :pid, :pwd_hash, 1, 'bcrypt', 0, now())
                            ON CONFLICT (principal_id) DO UPDATE
                            SET password_hash = EXCLUDED.password_hash, changed_at = now();
                        """),
                        {"id": str(uuid.uuid4()), "pid": str(user_uuid), "pwd_hash": pwd_hash}
                    )
                    migrated_credentials += 1

                # 3. Superuser role mapping
                if is_super:
                    tgt_conn.execute(
                        text("""
                            INSERT INTO iam.role_assignments (id, principal_id, role_code, tenant_id, store_id, valid_from)
                            VALUES (:id, :pid, 'PLATFORM_OWNER', NULL, NULL, now())
                            ON CONFLICT DO NOTHING;
                        """),
                        {"id": str(uuid.uuid4()), "pid": str(user_uuid)}
                    )
                    migrated_roles += 1

            # Count target rows
            final_principals = tgt_conn.execute(text("SELECT count(*) FROM iam.principals;")).scalar()
            final_credentials = tgt_conn.execute(text("SELECT count(*) FROM iam.credentials;")).scalar()

            print("=" * 60)
            print(f"Migration Summary:")
            print(f"  Source Users:        {source_count}")
            print(f"  Target Principals:   {final_principals} (Migrated: {migrated_principals})")
            print(f"  Target Credentials:  {final_credentials} (Migrated: {migrated_credentials})")
            print(f"  Admin Roles Granted: {migrated_roles}")
            print("=" * 60)
    except Exception as e:
        print(f"[ERROR] Target migration execution error: {e}")


if __name__ == "__main__":
    src = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--source" else None
    migrate_iam_data(src)
