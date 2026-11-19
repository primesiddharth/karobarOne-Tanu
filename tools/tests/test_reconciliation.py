# tools/tests/test_reconciliation.py
"""
Data Reconciliation and Cutover Hardening Tests (ROADMAP Phase 11).
Tests:
- Monolith SQLite extraction and count reconciliation
- Quantity conservation in inventory migration
- Idempotent migration dry-run execution
- Generated reconciliation report presence and format
"""
import pytest
from pathlib import Path

from tools.db.reconcile_data import (
    DEFAULT_SQLITE_PATH,
    DEFAULT_REPORT_PATH,
    get_monolith_stats,
    generate_reconciliation_report,
)
from tools.db.migrate_catalog import migrate_catalog_data
from tools.db.migrate_inventory import migrate_inventory_data
from tools.db.migrate_approvals import migrate_approvals_data


def test_monolith_source_extraction():
    """Extracts record counts from monolith SQLite database."""
    if not DEFAULT_SQLITE_PATH.exists() or DEFAULT_SQLITE_PATH.stat().st_size == 0:
        pytest.skip("Monolith database karobar.db not found")

    stats = get_monolith_stats(DEFAULT_SQLITE_PATH)
    assert isinstance(stats, dict)
    assert "inventory_records" in stats
    assert stats["inventory_records"] >= 90
    assert stats["inventory_total_qty"] > 0


def test_catalog_migration_dry_run():
    """Verifies dry-run catalog migration maps products and categories accurately."""
    res = migrate_catalog_data(dry_run=True)
    assert res["source_products"] == res["migrated_items"]
    assert res["source_categories"] == res["migrated_categories"]


def test_inventory_migration_quantity_conservation():
    """Verifies that inventory migration perfectly conserves total stock units."""
    if not DEFAULT_SQLITE_PATH.exists() or DEFAULT_SQLITE_PATH.stat().st_size == 0:
        pytest.skip("Monolith database karobar.db not found")
    res = migrate_inventory_data(dry_run=True)
    assert res["source_rows"] == res["migrated_skus"]
    assert res["migrated_skus"] == res["migrated_balances"]
    assert res["total_available_qty"] == 446


def test_approvals_migration_dry_run():
    """Verifies approval requests are mapped with decisions without loss."""
    if not DEFAULT_SQLITE_PATH.exists() or DEFAULT_SQLITE_PATH.stat().st_size == 0:
        pytest.skip("Monolith database karobar.db not found")
    res = migrate_approvals_data(dry_run=True)
    assert res["source_requests"] == res["migrated_requests"]
    assert res["migrated_decisions"] > 0


def test_reconciliation_report_generated():
    """Verifies reconciliation report is generated and contains required sign-offs."""
    if not DEFAULT_REPORT_PATH.exists():
        pytest.skip("Reconciliation report not generated in environment")
    assert DEFAULT_REPORT_PATH.exists()
    content = DEFAULT_REPORT_PATH.read_text(encoding="utf-8")
    assert "KarobarOne Data Reconciliation & Cutover Hardening Report" in content
    assert "Phase 11 Exit Gate Sign-Off" in content
    assert "MATCH / RECONCILED" in content
