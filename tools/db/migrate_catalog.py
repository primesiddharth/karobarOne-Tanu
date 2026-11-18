#!/usr/bin/env python3
"""
tools/db/migrate_catalog.py — Migrates products, services, and categories from monolith to catalog schema.
Usage:
    python tools/db/migrate_catalog.py [--dry-run]
"""
import os
import sys
import uuid
from pathlib import Path
from sqlalchemy import create_engine, text

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def migrate_catalog_data(source_url: str | None = None, target_url: str | None = None, dry_run: bool = False) -> dict:
    default_source = f"sqlite:///{ROOT_DIR.parent / 'karobar.db'}"
    src_conn_str = source_url or os.environ.get("MONOLITH_DATABASE_URL", default_source)
    tgt_conn_str = target_url or os.environ.get("MIGRATION_DATABASE_URL", "postgresql://catalog_migrator:dev_migrator_secret@localhost:5432/karobarone_dev")
    tgt_sync_str = tgt_conn_str.replace("+asyncpg", "")

    stats = {"source_products": 0, "source_categories": 0, "migrated_items": 0, "migrated_categories": 0}

    src_engine = create_engine(src_conn_str)
    with src_engine.connect() as src_conn:
        # Check products
        has_products = src_conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='products';")).scalar()
        products = []
        if has_products:
            products = src_conn.execute(text("SELECT id, tenant_id, store_id, product_name, product_slug, short_description, long_description, status, category_id, created_at, updated_at FROM products")).fetchall()
            stats["source_products"] = len(products)

        # Check categories
        has_categories = src_conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='categories';")).scalar()
        categories = []
        if has_categories:
            categories = src_conn.execute(text("SELECT id, category_name, category_slug FROM categories")).fetchall()
            stats["source_categories"] = len(categories)

    if dry_run:
        stats["migrated_items"] = len(products)
        stats["migrated_categories"] = len(categories)
        return stats

    try:
        tgt_engine = create_engine(tgt_sync_str)
        with tgt_engine.begin() as tgt_conn:
            for cat in categories:
                cat_id_str, cat_name, cat_slug = cat
                try:
                    c_id = uuid.UUID(str(cat_id_str))
                except Exception:
                    c_id = uuid.uuid4()

                tgt_conn.execute(
                    text("""
                    INSERT INTO catalog.categories (id, store_id, name, slug, is_active, created_at, updated_at)
                    VALUES (:id, :store_id, :name, :slug, true, now(), now())
                    ON CONFLICT (id) DO NOTHING
                    """),
                    {"id": c_id, "store_id": uuid.uuid4(), "name": cat_name, "slug": cat_slug or f"cat-{str(c_id)[:6]}"}
                )
                stats["migrated_categories"] += 1

            for p in products:
                p_id_str, t_id_str, s_id_str, name, slug, short_desc, long_desc, status_str, cat_id_str, cr_at, up_at = p
                try:
                    item_id = uuid.UUID(str(p_id_str))
                except Exception:
                    item_id = uuid.uuid4()
                try:
                    tenant_id = uuid.UUID(str(t_id_str))
                except Exception:
                    tenant_id = uuid.uuid4()
                try:
                    store_id = uuid.UUID(str(s_id_str))
                except Exception:
                    store_id = uuid.uuid4()

                status = "LIVE" if status_str and "publish" in status_str.lower() else "DRAFT"

                tgt_conn.execute(
                    text("""
                    INSERT INTO catalog.catalog_items (id, tenant_id, store_id, item_type, title, slug, status, created_at, updated_at)
                    VALUES (:id, :tenant_id, :store_id, 'PHYSICAL_PRODUCT', :title, :slug, :status, now(), now())
                    ON CONFLICT (id) DO NOTHING
                    """),
                    {"id": item_id, "tenant_id": tenant_id, "store_id": store_id, "title": name or "Unnamed Product", "slug": slug or f"item-{str(item_id)[:8]}", "status": status}
                )
                stats["migrated_items"] += 1
    except Exception as e:
        print(f"[WARN] Target DB connection failed: {e}")

    return stats


if __name__ == "__main__":
    is_dry = "--dry-run" in sys.argv
    res = migrate_catalog_data(dry_run=is_dry)
    print("Catalog migration stats:", res)
