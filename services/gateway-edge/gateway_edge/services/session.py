from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from uuid import UUID

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError

_PRESENCE_DIRECTORY_DIR = Path(__file__).resolve().parents[4] / "services" / "presence-directory"
if _PRESENCE_DIRECTORY_DIR.is_dir():
    import sys

    presence_path = str(_PRESENCE_DIRECTORY_DIR)
    if presence_path not in sys.path:
        sys.path.insert(0, presence_path)

from presence_directory import ThreadPresenceDirectory, connection_key, presence_key

from gateway_edge.config import settings
from gateway_edge.db.postgres import get_pool
from gateway_edge.models import SessionInfo

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


def _presence_key(thread_id: UUID, participant_id: UUID) -> str:
    return presence_key(thread_id, participant_id)


def _connection_key(thread_id: UUID, connection_id: str) -> str:
    return connection_key(thread_id, connection_id)


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        raise RuntimeError("Redis/Valkey client is not initialised")
    return _redis


async def setup_valkey() -> None:
    global _redis
    t0 = time.monotonic()
    deadline = time.monotonic() + settings.valkey_startup_timeout_seconds
    attempt = 1
    while True:
        try:
            _redis = aioredis.from_url(
                settings.valkey_url,
                decode_responses=True,
                socket_connect_timeout=5,
            )
            await _redis.ping()
            break
        except (OSError, RedisConnectionError) as exc:
            if _redis:
                await _redis.aclose()
                _redis = None
            if time.monotonic() >= deadline:
                logger.error("Valkey failed to start after %s attempts", attempt)
                raise
            logger.warning(
                "Valkey startup attempt %s failed: %s; retrying in %.1fs",
                attempt,
                exc,
                settings.valkey_startup_retry_interval_seconds,
            )
            attempt += 1
            await asyncio.sleep(settings.valkey_startup_retry_interval_seconds)
    logger.info("Valkey ready (%.0f ms)", (time.monotonic() - t0) * 1000)


async def teardown_valkey() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        logger.info("Valkey connection closed")


async def register_thread_connection(
    *,
    workspace_id: UUID | None = None,
    thread_id: UUID,
    participant_id: UUID,
    connection_id: str,
    status: str = "active",
) -> None:
    directory = ThreadPresenceDirectory(
        await get_redis(),
        ttl_seconds=settings.session_ttl_seconds,
    )
    await directory.register_thread_connection(
        workspace_id=workspace_id,
        thread_id=thread_id,
        participant_id=participant_id,
        connection_id=connection_id,
        status=status,
    )


async def unregister_thread_connection(
    *,
    workspace_id: UUID | None = None,
    thread_id: UUID,
    participant_id: UUID,
    connection_id: str,
) -> dict[str, str] | None:
    directory = ThreadPresenceDirectory(
        await get_redis(),
        ttl_seconds=settings.session_ttl_seconds,
    )
    return await directory.unregister_thread_connection(
        workspace_id=workspace_id,
        thread_id=thread_id,
        participant_id=participant_id,
        connection_id=connection_id,
    )


async def touch_thread_presence(
    *,
    workspace_id: UUID | None = None,
    thread_id: UUID,
    participant_id: UUID,
    connection_id: str | None = None,
    status: str = "active",
) -> None:
    directory = ThreadPresenceDirectory(
        await get_redis(),
        ttl_seconds=settings.session_ttl_seconds,
    )
    await directory.touch_thread_presence(
        workspace_id=workspace_id,
        thread_id=thread_id,
        participant_id=participant_id,
        connection_id=connection_id,
        status=status,
    )


async def get_workspace_participant_presence(
    *,
    workspace_id: UUID,
    participant_id: UUID,
) -> dict[str, str] | None:
    directory = ThreadPresenceDirectory(
        await get_redis(),
        ttl_seconds=settings.session_ttl_seconds,
    )
    return await directory.get_workspace_participant_presence(
        workspace_id=workspace_id,
        participant_id=participant_id,
    )


async def create_session(session_id: UUID) -> SessionInfo:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO chat_sessions (session_id)
            VALUES ($1)
            ON CONFLICT (session_id) DO UPDATE
                SET last_active = NOW()
            RETURNING session_id, created_at, last_active, message_count
            """,
            session_id,
        )
    assert row is not None
    return SessionInfo(**dict(row))


async def get_session(session_id: UUID) -> SessionInfo | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT session_id, created_at, last_active, message_count
            FROM chat_sessions
            WHERE session_id = $1
            """,
            session_id,
        )
    if row is None:
        return None
    return SessionInfo(**dict(row))


async def touch_session(session_id: UUID, *, increment_count: bool = False) -> SessionInfo | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE chat_sessions
            SET last_active = NOW(),
                message_count = message_count + $2::int
            WHERE session_id = $1
            RETURNING session_id, created_at, last_active, message_count
            """,
            session_id,
            1 if increment_count else 0,
        )
    if row is None:
        return None
    return SessionInfo(**dict(row))


async def delete_session(session_id: UUID) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM chat_sessions WHERE session_id = $1",
            session_id,
        )
    return result.endswith("1")
