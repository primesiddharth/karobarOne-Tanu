#!/usr/bin/env python3
"""
tools/db/migrate_approvals.py — Migrates approval requests from monolith into approval schema.
Usage:
    python tools/db/migrate_approvals.py [--dry-run]
"""
import os
import sys
import uuid
from pathlib import Path
from sqlalchemy import create_engine, text

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def migrate_approvals_data(source_url: str | None = None, target_url: str | None = None, dry_run: bool = False) -> dict:
    default_source = f"sqlite:///{ROOT_DIR.parent / 'karobar.db'}"
    src_conn_str = source_url or os.environ.get("MONOLITH_DATABASE_URL", default_source)
    tgt_conn_str = target_url or os.environ.get("MIGRATION_DATABASE_URL", "postgresql://approval_migrator:dev_migrator_secret@localhost:5432/karobarone_dev")
    tgt_sync_str = tgt_conn_str.replace("+asyncpg", "")

    stats = {"source_requests": 0, "migrated_requests": 0, "migrated_decisions": 0}

    src_engine = create_engine(src_conn_str)
    with src_engine.connect() as src_conn:
        has_table = src_conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='approval_requests';")).scalar()
        if not has_table:
            return stats

        rows = src_conn.execute(text("SELECT id, tenant_id, entity_type, entity_id, operation_type, submitted_version_number, approval_status, submitted_by, submitted_at, reviewed_by, reviewed_at, rejection_reason FROM approval_requests")).fetchall()
        stats["source_requests"] = len(rows)

    if dry_run:
        stats["migrated_requests"] = len(rows)
        stats["migrated_decisions"] = sum(1 for r in rows if r[9])
        return stats

    try:
        tgt_engine = create_engine(tgt_sync_str)
        with tgt_engine.begin() as tgt_conn:
            for r in rows:
                req_id_str, t_id_str, ent_type, ent_id_str, op_type, ver_no, app_status, sub_by, sub_at, rev_by, rev_at, rej_reason = r
                try:
                    req_id = uuid.UUID(str(req_id_str))
                except Exception:
                    req_id = uuid.uuid4()
                try:
                    tenant_id = uuid.UUID(str(t_id_str))
                except Exception:
                    tenant_id = uuid.uuid4()
                try:
                    content_id = uuid.UUID(str(ent_id_str))
                except Exception:
                    content_id = uuid.uuid4()

                status = app_status.upper() if app_status else "PENDING"
                if status not in ("PENDING", "APPROVED", "REJECTED"):
                    status = "PENDING"

                # Insert approval request
                tgt_conn.execute(
                    text("""
                    INSERT INTO approval.approval_requests (
                        id, tenant_id, store_id, content_type, content_id, content_version_id,
                        status, submitted_by, submitted_at, created_at, updated_at
                    )
                    VALUES (
                        :id, :t_id, :s_id, :content_type, :content_id, :ver_id,
                        :status, :sub_by, now(), now(), now()
                    )
                    ON CONFLICT (id) DO NOTHING
                    """),
                    {
                        "id": req_id,
                        "t_id": tenant_id,
                        "s_id": uuid.uuid4(),
                        "content_type": (ent_type or "ITEM").upper(),
                        "content_id": content_id,
                        "ver_id": uuid.uuid4(),
                        "status": status,
                        "sub_by": uuid.uuid4(),
                    }
                )
                stats["migrated_requests"] += 1

                # If reviewed, insert decision
                if rev_by or status in ("APPROVED", "REJECTED"):
                    tgt_conn.execute(
                        text("""
                        INSERT INTO approval.approval_decisions (
                            id, request_id, decision, reviewer_id, reviewer_role, reason, decided_at, created_at
                        )
                        VALUES (
                            :id, :req_id, :decision, :reviewer_id, 'SYSTEM_MIGRATED', :reason, now(), now()
                        )
                        ON CONFLICT (id) DO NOTHING
                        """),
                        {
                            "id": uuid.uuid4(),
                            "req_id": req_id,
                            "decision": "APPROVED" if status == "APPROVED" else "REJECTED",
                            "reviewer_id": uuid.uuid4(),
                            "reason": rej_reason or "Migrated from legacy monolith",
                        }
                    )
                    stats["migrated_decisions"] += 1
    except Exception as e:
        print(f"[WARN] Target DB connection failed: {e}")

    return stats


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    res = migrate_approvals_data(dry_run=is_dry)
    print("Approvals migration stats:", res)
