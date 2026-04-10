from __future__ import annotations

from pathlib import Path

import asyncpg

_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "db" / "migrations"


async def apply_pending_migrations(pool: asyncpg.Pool) -> None:
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

        for migration_path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
            version = migration_path.stem
            if version in applied_versions:
                continue
            sql = migration_path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    """
                    INSERT INTO schema_migrations (version)
                    VALUES ($1)
                    """,
                    version,
                )
