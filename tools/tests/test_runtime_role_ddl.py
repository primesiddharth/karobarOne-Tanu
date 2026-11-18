# tools/tests/test_runtime_role_ddl.py
# FND-TST-022: Verifies that runtime service roles (<schema>_svc) cannot execute DDL commands (RULES.md §5)
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("schema", ["iam", "tenant", "approval", "catalog", "domain", "customer", "subscription", "inventory"])
async def test_runtime_role_cannot_run_ddl(postgres_url, schema):
    """Runtime role (<schema>_svc) must be refused on CREATE, ALTER, and DROP (RULES.md §5)."""
    # Construct connection URL for runtime role
    clean_url = postgresurl_for_role(postgres_url, f"{schema}_svc", "dev_svc_secret")
    engine = create_async_engine(clean_url)

    try:
        async with engine.connect() as conn:
            # 1. Attempt CREATE TABLE
            with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                await conn.execute(text(f"CREATE TABLE {schema}.__test_forbidden_ddl (id int);"))
            assert "permission denied" in str(exc_info.value).lower() or "must be owner" in str(exc_info.value).lower()

            # 2. Attempt ALTER TABLE
            with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                await conn.execute(text(f"ALTER TABLE {schema}.outbox_events ADD COLUMN __forbidden int;"))
            assert "permission denied" in str(exc_info.value).lower() or "must be owner" in str(exc_info.value).lower()

            # 3. Attempt DROP TABLE
            with pytest.raises((ProgrammingError, DBAPIError)) as exc_info:
                await conn.execute(text(f"DROP TABLE {schema}.outbox_events;"))
            assert "permission denied" in str(exc_info.value).lower() or "must be owner" in str(exc_info.value).lower()
    finally:
        await engine.dispose()


def postgresurl_for_role(base_url: str, username: str, password: str) -> str:
    """Helper to rewrite asyncpg connection URL with specific user credentials."""
    import re
    # Replace username:password in URL
    return re.sub(r'://([^:]+):([^@]+)@', f'://{username}:{password}@', base_url)
