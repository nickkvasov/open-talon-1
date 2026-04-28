from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import os
from pathlib import Path
import re
import sys

import asyncpg

from core_collab.migrations import apply_pending_migrations


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = "postgresql://admin:password@127.0.0.1:5432/app_db?sslmode=disable"
DEFAULT_MIGRATIONS_DIR = ROOT_DIR / "db" / "migrations"
MIGRATION_NAME = re.compile(r"^[a-z0-9_]+$")


def _database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def _migrations_dir() -> Path:
    configured = os.getenv("DBMATE_MIGRATIONS_DIR")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_MIGRATIONS_DIR


def _timestamp() -> str:
    override = os.getenv("OPEN_TALON_MIGRATION_TIMESTAMP")
    if override:
        if not re.fullmatch(r"\d{14}", override):
            raise SystemExit("OPEN_TALON_MIGRATION_TIMESTAMP must use YYYYMMDDHHMMSS format")
        return override
    return datetime.now().strftime("%Y%m%d%H%M%S")


def create_migration(name: str) -> int:
    if not MIGRATION_NAME.fullmatch(name):
        raise SystemExit("Migration name must use lowercase letters, digits, and underscores only")
    migrations_dir = _migrations_dir()
    migrations_dir.mkdir(parents=True, exist_ok=True)
    path = migrations_dir / f"{_timestamp()}_{name}.sql"
    if path.exists():
        raise SystemExit(f"Migration already exists: {path}")
    path.write_text("-- migrate:up\n\n-- migrate:down\n", encoding="utf-8")
    print(path)
    return 0


async def _connect_pool() -> asyncpg.Pool:
    return await asyncpg.create_pool(_database_url())


async def apply_migrations() -> int:
    pool = await _connect_pool()
    try:
        applied = await apply_pending_migrations(pool, migrations_dir=_migrations_dir())
    finally:
        await pool.close()
    if applied:
        print(f"Applied {len(applied)} migration(s):")
        for version in applied:
            print(f"  {version}")
    else:
        print("No pending migrations.")
    return 0


async def migration_status() -> int:
    migrations_dir = _migrations_dir()
    paths = sorted(migrations_dir.glob("*.sql"))
    pool = await _connect_pool()
    try:
        async with pool.acquire() as conn:
            exists = await conn.fetchval("SELECT to_regclass('public.schema_migrations')")
            rows = (
                await conn.fetch("SELECT version FROM schema_migrations")
                if exists is not None
                else []
            )
    finally:
        await pool.close()
    applied = {row["version"] for row in rows}
    file_versions = [path.stem for path in paths]
    file_version_set = set(file_versions)
    applied_current_count = 0
    pending_count = 0
    for version in file_versions:
        marker = "up" if version in applied else "pending"
        if marker == "pending":
            pending_count += 1
        else:
            applied_current_count += 1
        print(f"{marker:7} {version}")
    recorded_only = sorted(applied - file_version_set)
    print(
        f"Applied: {applied_current_count} Pending: {pending_count} "
        f"Recorded without file: {len(recorded_only)}"
    )
    for version in recorded_only:
        print(f"recorded-only {version}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open Talon SQL migration helper.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="create a timestamped migration file")
    new_parser.add_argument("name")

    subparsers.add_parser("up", help="apply pending migrations with the Python runner")
    subparsers.add_parser("status", help="show applied and pending migrations")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "new":
        return create_migration(args.name)
    if args.command == "up":
        return asyncio.run(apply_migrations())
    if args.command == "status":
        return asyncio.run(migration_status())
    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
