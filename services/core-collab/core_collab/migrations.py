from __future__ import annotations

import re
from pathlib import Path

import asyncpg

_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"
_MIGRATE_UP = re.compile(r"(?m)^\s*--\s*migrate:up\s*$")
_MIGRATE_DOWN = re.compile(r"(?m)^\s*--\s*migrate:down\s*$")


def _migration_up_sql(sql: str) -> str:
    up_match = _MIGRATE_UP.search(sql)
    if up_match is None:
        return sql
    down_match = _MIGRATE_DOWN.search(sql, up_match.end())
    end = down_match.start() if down_match is not None else len(sql)
    return sql[up_match.end() : end].strip()


async def apply_pending_migrations(
    pool: asyncpg.Pool,
    *,
    migrations_dir: Path | None = None,
) -> list[str]:
    applied_now: list[str] = []
    source_dir = migrations_dir or _MIGRATIONS_DIR
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        applied_rows = await conn.fetch("SELECT version FROM schema_migrations")
        applied_versions = {row["version"] for row in applied_rows}

        for migration_path in sorted(source_dir.glob("*.sql")):
            version = migration_path.stem
            if version in applied_versions:
                continue
            sql = _migration_up_sql(migration_path.read_text(encoding="utf-8"))
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    """
                    INSERT INTO schema_migrations (version)
                    VALUES ($1)
                    """,
                    version,
                )
            applied_now.append(version)
    return applied_now
