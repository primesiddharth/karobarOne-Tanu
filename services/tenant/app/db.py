# app/db.py
from collections.abc import AsyncGenerator
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text
from .config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    connect_args={"statement_cache_size": 0},
    pool_pre_ping=True,
    echo=False,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yields a transactional AsyncSession dependency for FastAPI routes."""
    async with async_session_factory() as session:
        yield session


async def set_rls_context(
    session: AsyncSession,
    tenant_id: UUID | None,
    store_id: UUID | None = None,
    is_platform_admin: bool = False,
) -> None:
    """Sets PostgreSQL session variables for Row-Level Security enforcement (RULES.md §5.8)."""
    if tenant_id:
        await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)})
    if store_id:
        await session.execute(text("SELECT set_config('app.store_id', :sid, true)"), {"sid": str(store_id)})
    admin_val = "true" if is_platform_admin else "false"
    await session.execute(text("SELECT set_config('app.is_platform_admin', :adm, true)"), {"adm": admin_val})
