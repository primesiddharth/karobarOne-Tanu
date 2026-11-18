# ==============================================================================
# File: conftest.py
# Purpose: Root pytest configuration providing real PostgreSQL testcontainer & DB fixtures (RULES.md §11)
# ==============================================================================
import os
import sys
import re
import pytest
import pytest_asyncio

# Standard Windows asyncpg socket fix
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy.pool import NullPool
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

microservice_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(microservice_dir)

if microservice_dir not in sys.path:
    sys.path.insert(0, microservice_dir)

if root_dir in sys.path:
    sys.path.remove(root_dir)

def pytest_collectstart(collector):
    """Ensures service directory is in sys.path when collecting tests for that service."""
    path_str = str(getattr(collector, "fspath", "") or getattr(collector, "path", ""))
    if "services" in path_str:
        norm = os.path.normpath(path_str)
        parts = norm.split(os.sep)
        if "services" in parts:
            idx = parts.index("services")
            if idx + 1 < len(parts):
                svc_dir = os.sep.join(parts[:idx + 2])
                if svc_dir not in sys.path:
                    sys.path.insert(0, svc_dir)

_container = None


from urllib.parse import urlparse

def get_test_postgres_url() -> str:
    """Returns real PostgreSQL asyncpg URL from environment or starts session-wide testcontainer."""
    global _container
    env_url = os.environ.get("DATABASE_URL")
    if env_url and "postgresql" in env_url:
        parsed = urlparse(env_url)
        hostname = parsed.hostname
        if hostname not in ("localhost", "127.0.0.1", "::1", "host.docker.internal"):
            raise RuntimeError(
                f"conftest.py refuses to run tests against non-local DATABASE_URL: '{hostname}'. "
                "Local/dev database credentials only per RULES.md §10."
            )
        return env_url

    try:
        if _container is None:
            from testcontainers.community.postgres import PostgresContainer
            _container = PostgresContainer("postgres:16-alpine")
            _container.start()
            sync_url = _container.get_connection_url()
            async_url = sync_url.replace("postgresql://", "postgresql+asyncpg://").replace("psycopg2", "asyncpg")
            os.environ["DATABASE_URL"] = async_url
            os.environ["MIGRATION_DATABASE_URL"] = async_url
            return async_url
        sync_url = _container.get_connection_url()
        return sync_url.replace("postgresql://", "postgresql+asyncpg://").replace("psycopg2", "asyncpg")
    except Exception as exc:
        pytest.skip(f"Real PostgreSQL / Docker not available: {exc}. PostgreSQL is required per RULES.md §11.")


@pytest.fixture(scope="session")
def postgres_url():
    """Provides real PostgreSQL database connection URL for tests."""
    url = get_test_postgres_url()
    yield url
    global _container
    if _container is not None:
        _container.stop()
        _container = None


@pytest_asyncio.fixture(scope="function")
async def db_engine(postgres_url, monkeypatch):
    """Configures async engine, creates schema/tables, and wires app.db for PostgreSQL."""
    clean_url = postgres_url.replace("sslmode=", "ssl=")
    clean_url = re.sub(r'[?&]statement_cache_size=[^&]*', '', clean_url)
    engine = create_async_engine(clean_url, poolclass=NullPool, connect_args={"statement_cache_size": 0})

    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS iam;"))
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS tenant;"))
        try:
            from app.models import Base
            await conn.run_sync(Base.metadata.create_all)
        except Exception:
            pass
        for table in [
            "security_events",
            "otp_challenges",
            "refresh_tokens",
            "sessions",
            "role_assignments",
            "credentials",
            "principals",
            "idempotency_keys",
            "processed_events",
            "outbox_events"
        ]:
            try:
                await conn.execute(text(f"DELETE FROM iam.{table};"))
            except Exception:
                pass
        for table in [
            "seller_identity_snapshots",
            "store_memberships",
            "free_store_entitlements",
            "stores",
            "gstin_verifications",
            "gstins",
            "guardian_consents",
            "guardians",
            "pan_verifications",
            "tenants",
            "idempotency_keys",
            "processed_events",
            "outbox_events"
        ]:
            try:
                await conn.execute(text(f"DELETE FROM tenant.{table};"))
            except Exception:
                pass

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)

    try:
        from app.config import settings
        import app.db
        monkeypatch.setattr(settings, "DATABASE_URL", postgres_url)
        monkeypatch.setattr(settings, "MIGRATION_DATABASE_URL", postgres_url)
        monkeypatch.setattr(app.db, "engine", engine)
        monkeypatch.setattr(app.db, "async_session_factory", session_factory)
    except ImportError:
        pass

    for mod_name, mod in list(sys.modules.items()):
        if ("iam.tests" in mod_name or "tenant.tests" in mod_name) and hasattr(mod, "async_session_factory"):
            monkeypatch.setattr(mod, "async_session_factory", session_factory)

    yield engine
    await engine.dispose()
