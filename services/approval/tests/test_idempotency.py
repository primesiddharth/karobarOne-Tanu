# tests/test_idempotency.py
import pytest
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from app.db import async_session_factory

pytestmark = pytest.mark.asyncio


async def test_idempotency_unique_constraint(db_engine):
    """Verifies duplicate (scope, key) raises integrity error (RULES.md §5.4, FND-TST-001)."""
    scope = "approval:action"
    key = str(uuid4())
    now = datetime.now(timezone.utc)
    locked_until = now + timedelta(minutes=1)

    async with async_session_factory() as session:
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO approval.idempotency_keys "
                    "(id, scope, key, request_hash, response_code, response_body, created_at, locked_until) "
                    "VALUES (:id, :scope, :key, 'hash1', 200, :body, :now, :locked)"
                ),
                {"id": uuid4(), "scope": scope, "key": key, "body": '{"ok": true}', "now": now, "locked": locked_until}
            )

    with pytest.raises(IntegrityError):
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO approval.idempotency_keys "
                        "(id, scope, key, request_hash, response_code, response_body, created_at, locked_until) "
                        "VALUES (:id, :scope, :key, 'hash2', 200, :body, :now, :locked)"
                    ),
                    {"id": uuid4(), "scope": scope, "key": key, "body": '{"ok": true}', "now": now, "locked": locked_until}
                )
