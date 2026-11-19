#!/usr/bin/env python3
"""
tools/db/reset_dev_db.py — Guarded database reset for migration testing.

Safety Rules:
- Defaults strictly to 'karobarone_migration_test'.
- Explicitly refuses to touch 'karobarone_dev' or production/staging databases without explicit bypass.
- Uses the appropriate migrator role for each schema and preserves permissions defined by bootstrap.sql.
"""

import sys
import argparse
import asyncio
import asyncpg

ALLOWED_TEST_DATABASES = {"karobarone_migration_test"}

SERVICES = [
    "iam",
    "tenant",
    "approval",
    "catalog",
    "domain",
    "customer",
    "subscription",
    "inventory",
]

DEV_MIGRATOR_SECRET = "dev_migrator_secret"
DEV_SVC_SECRET = "dev_svc_secret"


async def ensure_database_exists(db_name: str, host: str, port: int, admin_user: str, admin_pass: str):
    """Ensures target database exists, connecting via the admin user."""
    conn = None
    try:
        conn = await asyncpg.connect(
            user=admin_user,
            password=admin_pass,
            database="postgres",
            host=host,
            port=port,
        )
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )
        if not exists:
            print(f"[*] Database '{db_name}' does not exist. Creating...")
            await conn.execute(f'CREATE DATABASE "{db_name}"')
            print(f"[+] Database '{db_name}' created.")
        else:
            print(f"[*] Database '{db_name}' already exists.")

        # Ensure migrator & svc roles have appropriate privileges on db_name
        for s in SERVICES:
            migrator_role = f"{s}_migrator"
            svc_role = f"{s}_svc"
            await conn.execute(f'GRANT CREATE, CONNECT ON DATABASE "{db_name}" TO {migrator_role}')
            await conn.execute(f'GRANT CONNECT ON DATABASE "{db_name}" TO {svc_role}')
    except Exception as e:
        print(f"[!] Warning connecting to admin postgres DB: {e}")
    finally:
        if conn:
            await conn.close()


async def reset_schema_for_service(
    service: str,
    db_name: str,
    host: str,
    port: int,
    admin_user: str,
    admin_pass: str,
):
    migrator_role = f"{service}_migrator"
    svc_role = f"{service}_svc"

    # Try connecting as admin first to drop/create schema with proper authorization
    conn = None
    try:
        conn = await asyncpg.connect(
            user=admin_user,
            password=admin_pass,
            database=db_name,
            host=host,
            port=port,
        )
    except Exception:
        # Fallback to connecting as the migrator role itself
        conn = await asyncpg.connect(
            user=migrator_role,
            password=DEV_MIGRATOR_SECRET,
            database=db_name,
            host=host,
            port=port,
        )

    try:
        print(f"[*] Resetting schema '{service}' on database '{db_name}'...")
        # 1. Drop existing schema & objects cascade
        await conn.execute(f'DROP SCHEMA IF EXISTS "{service}" CASCADE;')

        # 2. Recreate schema owned by Migrator
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{service}" AUTHORIZATION {migrator_role};')

        # 3. Grant usage on schema to runtime service role
        await conn.execute(f'GRANT USAGE ON SCHEMA "{service}" TO {svc_role};')

        # 4. Default table & sequence privileges matching bootstrap.sql
        await conn.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE {migrator_role} IN SCHEMA "{service}" '
            f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {svc_role};'
        )
        await conn.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE {migrator_role} IN SCHEMA "{service}" '
            f'GRANT USAGE, SELECT ON SEQUENCES TO {svc_role};'
        )

        # 5. Revoke public
        await conn.execute(f'REVOKE ALL ON SCHEMA "{service}" FROM PUBLIC;')

        print(f"[+] Schema '{service}' reset cleanly.")
    finally:
        await conn.close()


async def main():
    parser = argparse.ArgumentParser(description="Guarded database reset for migration testing.")
    parser.add_argument(
        "--database",
        default="karobarone_migration_test",
        help="Target database name (default: karobarone_migration_test)",
    )
    parser.add_argument("--host", default="localhost", help="PostgreSQL host")
    parser.add_argument("--port", type=int, default=5432, help="PostgreSQL port")
    parser.add_argument("--admin-user", default="postgres", help="PostgreSQL admin user")
    parser.add_argument("--admin-pass", default="postgres", help="PostgreSQL admin password")
    parser.add_argument(
        "--allow-dev",
        action="store_true",
        help="Explicitly permit resetting karobarone_dev (DANGEROUS)",
    )

    args = parser.parse_args()

    # Safety Guard
    if args.database not in ALLOWED_TEST_DATABASES:
        if args.database == "karobarone_dev" and not args.allow_dev:
            print(
                f"[FATAL] Refusing to reset '{args.database}'. "
                "Safety guard prevented execution on dev database! Use --database karobarone_migration_test.",
                file=sys.stderr,
            )
            sys.exit(1)
        elif args.database != "karobarone_dev":
            print(
                f"[FATAL] Refusing to reset unrecognized database '{args.database}'. "
                f"Allowed test databases: {ALLOWED_TEST_DATABASES}",
                file=sys.stderr,
            )
            sys.exit(1)

    print(f"=== Starting Guarded Database Reset on '{args.database}' ===")

    # Step 1: Ensure database exists
    await ensure_database_exists(
        db_name=args.database,
        host=args.host,
        port=args.port,
        admin_user=args.admin_user,
        admin_pass=args.admin_pass,
    )

    # Step 2: Reset each service schema
    for service in SERVICES:
        await reset_schema_for_service(
            service=service,
            db_name=args.database,
            host=args.host,
            port=args.port,
            admin_user=args.admin_user,
            admin_pass=args.admin_pass,
        )

    print(f"=== Successfully reset all 8 schemas in '{args.database}' to clean zero ===")


if __name__ == "__main__":
    asyncio.run(main())
