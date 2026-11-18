# tests/test_insert_only.py
# FND-TST-035: Verifies that audit/history/consent tables are insert-only for the runtime role (RULES.md §5)
import pytest
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from app.db import async_session_factory, set_rls_context
from app import models

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("table_name", [
    "guardian_consents",
    "pan_verifications",
    "gstin_verifications",
    "seller_identity_snapshots",
])
async def test_insert_only_tables_refuse_update_and_delete(db_engine, table_name):
    """Runtime role tenant_svc cannot UPDATE or DELETE rows in immutable tables (RULES.md §5)."""
    t1 = uuid4()
    row_id = uuid4()

    async with async_session_factory() as session:
        try:
            # 1. Insert seed row under tenant context as migrator/super
            await set_rls_context(session, tenant_id=t1)
            tenant = models.Tenant(
                id=t1,
                pan_ciphertext=b"enc",
                pan_fingerprint=f"fp_{t1.hex[:16]}",
                pan_masked="ABCDE1111F",
                legal_name="Tenant Insert-Only",
            )
            session.add(tenant)
            await session.commit()

            # Insert verification row
            verif = models.PanVerification(
                id=row_id,
                tenant_id=t1,
                provider_code="MOCK",
                provider_reference="REF1",
                status="VERIFIED",
                verified_name="Tenant One",
                verified_at=datetime.now(timezone.utc),
            )
            session.add(verif)
            await session.commit()

            # 2. Switch to runtime role tenant_svc
            try:
                await session.execute(text("SET ROLE tenant_svc;"))
            except Exception:
                pytest.skip("Role tenant_svc not provisioned in current test database")

            await set_rls_context(session, tenant_id=t1)

            # 3. Attempt UPDATE on table -> must raise permission denied
            with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                await session.execute(text(f"UPDATE tenant.{table_name} SET provider_code = 'HACKED' WHERE id = :id"), {"id": str(row_id)})
            assert "permission denied" in str(exc_info.value).lower()

            # 4. Attempt DELETE on table -> must raise permission denied
            with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                await session.execute(text(f"DELETE FROM tenant.{table_name} WHERE id = :id"), {"id": str(row_id)})
            assert "permission denied" in str(exc_info.value).lower()

        finally:
            try:
                await session.execute(text("RESET ROLE;"))
            except Exception:
                pass
            await session.rollback()
