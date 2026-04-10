from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from uuid import UUID

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError

from gateway_edge.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None

_THREAD_CONN_PREFIX = "thread-connection:"
_PRESENCE_PREFIX = "thread-presence:"


def _connection_key(thread_id: UUID, connection_id: str) -> str:
    return f"{_THREAD_CONN_PREFIX}{thread_id}:{connection_id}"


def _presence_key(thread_id: UUID, participant_id: UUID) -> str:
    return f"{_PRESENCE_PREFIX}{thread_id}:{participant_id}"


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
    thread_id: UUID,
    participant_id: UUID,
    connection_id: str,
    status: str = "active",
) -> None:
    redis = await get_redis()
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "thread_id": str(thread_id),
        "participant_id": str(participant_id),
        "connection_id": connection_id,
        "status": status,
        "last_seen_at": now,
    }
    await redis.set(
        _connection_key(thread_id, connection_id),
        json.dumps(payload),
        ex=settings.session_ttl_seconds,
    )
    await redis.set(
        _presence_key(thread_id, participant_id),
        json.dumps(payload),
        ex=settings.session_ttl_seconds,
    )


async def unregister_thread_connection(
    *,
    thread_id: UUID,
    participant_id: UUID,
    connection_id: str,
) -> None:
    redis = await get_redis()
    await redis.delete(_connection_key(thread_id, connection_id))
    await redis.delete(_presence_key(thread_id, participant_id))


async def touch_thread_presence(
    *,
    thread_id: UUID,
    participant_id: UUID,
    connection_id: str | None = None,
    status: str = "active",
) -> None:
    redis = await get_redis()
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "thread_id": str(thread_id),
        "participant_id": str(participant_id),
        "connection_id": connection_id,
        "status": status,
        "last_seen_at": now,
    }
    await redis.set(
        _presence_key(thread_id, participant_id),
        json.dumps(payload),
        ex=settings.session_ttl_seconds,
    )
    if connection_id is not None:
        await redis.set(
            _connection_key(thread_id, connection_id),
            json.dumps(payload),
            ex=settings.session_ttl_seconds,
        )
