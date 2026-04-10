from __future__ import annotations

import asyncio
import logging
import time

import asyncpg

from gateway_edge.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        raise RuntimeError("Postgres pool is not initialised")
    return _pool


async def setup_postgres() -> None:
    global _pool
    t0 = time.monotonic()
    deadline = time.monotonic() + settings.postgres_startup_timeout_seconds
    attempt = 1
    while True:
        try:
            _pool = await asyncpg.create_pool(
                dsn=settings.postgres_dsn,
                min_size=settings.postgres_min_pool,
                max_size=settings.postgres_max_pool,
            )
            break
        except OSError as exc:
            if time.monotonic() >= deadline:
                logger.error("Postgres failed to start after %s attempts", attempt)
                raise
            logger.warning(
                "Postgres startup attempt %s failed: %s; retrying in %.1fs",
                attempt,
                exc,
                settings.postgres_startup_retry_interval_seconds,
            )
            attempt += 1
            await asyncio.sleep(settings.postgres_startup_retry_interval_seconds)
    logger.info("Postgres pool ready (%.0f ms)", (time.monotonic() - t0) * 1000)


async def teardown_postgres() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Postgres pool closed")
