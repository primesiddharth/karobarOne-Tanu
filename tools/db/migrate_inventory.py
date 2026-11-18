#!/usr/bin/env python3
"""
tools/db/migrate_inventory.py — Migrates inventory rows from monolith into inventory schema.
Usage:
    python tools/db/migrate_inventory.py [--dry-run]
"""
import os
import sys
import uuid
from pathlib import Path
from sqlalchemy import create_engine, text

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def migrate_inventory_data(source_url: str | None = None, target_url: str | None = None, dry_run: bool = False) -> dict:
    default_source = f"sqlite:///{ROOT_DIR.parent / 'karobar.db'}"
    src_conn_str = source_url or os.environ.get("MONOLITH_DATABASE_URL", default_source)
    tgt_conn_str = target_url or os.environ.get("MIGRATION_DATABASE_URL", "postgresql://inventory_migrator:dev_migrator_secret@localhost:5432/karobarone_dev")
    tgt_sync_str = tgt_conn_str.replace("+asyncpg", "")

    stats = {"source_rows": 0, "migrated_skus": 0, "migrated_balances": 0, "total_available_qty": 0}

    src_engine = create_engine(src_conn_str)
    with src_engine.connect() as src_conn:
        has_table = src_conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='inventory';")).scalar()
        if not has_table:
            return stats

        rows = src_conn.execute(text("SELECT id, variant_id, available_quantity, reserved_quantity, reorder_level, track_inventory FROM inventory")).fetchall()
        stats["source_rows"] = len(rows)
        for r in rows:
            stats["total_available_qty"] += int(r[2] or 0)

    if dry_run:
        stats["migrated_skus"] = len(rows)
        stats["migrated_balances"] = len(rows)
        return stats

    try:
        tgt_engine = create_engine(tgt_sync_str)
        with tgt_engine.begin() as tgt_conn:
            for r in rows:
                inv_id, var_id, avail_qty, res_qty, reorder, track = r
                try:
                    sku_id = uuid.UUID(str(inv_id))
                except Exception:
                    sku_id = uuid.uuid4()

                t_id = uuid.uuid4()
                s_id = uuid.uuid4()
                sku_code = f"SKU-{str(sku_id)[:8]}"

                # Insert SKU
                tgt_conn.execute(
                    text("""
                    INSERT INTO inventory.skus (id, tenant_id, store_id, sku_code, is_tracked, created_at, updated_at)
                    VALUES (:id, :t_id, :s_id, :sku_code, :is_tracked, now(), now())
                    ON CONFLICT (id) DO NOTHING
                    """),
                    {"id": sku_id, "t_id": t_id, "s_id": s_id, "sku_code": sku_code, "is_tracked": bool(track)}
                )
                stats["migrated_skus"] += 1

                # Insert Stock Balance
                tgt_conn.execute(
                    text("""
                    INSERT INTO inventory.stock_balances (sku_id, store_id, on_hand, reserved, reorder_threshold, updated_at)
                    VALUES (:id, :s_id, :on_hand, :reserved, :reorder, now())
                    ON CONFLICT (sku_id) DO UPDATE SET on_hand = EXCLUDED.on_hand, reserved = EXCLUDED.reserved
                    """),
                    {"id": sku_id, "s_id": s_id, "on_hand": int(avail_qty or 0), "reserved": int(res_qty or 0), "reorder": int(reorder or 0)}
                )
                stats["migrated_balances"] += 1
    except Exception as e:
        print(f"[WARN] Target DB connection failed: {e}")

    return stats


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    res = migrate_inventory_data(dry_run=is_dry)
    print("Inventory migration stats:", res)
