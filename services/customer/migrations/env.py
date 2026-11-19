# migrations/env.py
import asyncio
import os
import sys
import re
from pathlib import Path
from logging.config import fileConfig
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context

service_dir = str(Path(__file__).resolve().parent.parent)
if service_dir not in sys.path:
    sys.path.insert(0, service_dir)

from app.config import settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def do_run_migrations(connection):
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS customer;"))
    context.configure(
        connection=connection,
        target_metadata=None,
        version_table="customer_alembic_version",
        version_table_schema="customer",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    url = settings.MIGRATION_DATABASE_URL.replace("sslmode=", "ssl=")
    url = re.sub(r'[?&]statement_cache_size=[^&]*', '', url)
    engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
        await connection.commit()
    await engine.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    context.configure(url=settings.MIGRATION_DATABASE_URL)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
