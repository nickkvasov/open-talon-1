from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from uuid import UUID

import redis.asyncio as aioredis

from app.config import settings
from app.models import SessionInfo

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None

_KEY_PREFIX = "session:"


def _key(session_id: UUID) -> str:
    return f"{_KEY_PREFIX}{session_id}"


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        raise RuntimeError("Redis/Valkey client is not initialised")
    return _redis


async def setup_valkey() -> None:
    global _redis
    t0 = time.monotonic()
    _redis = aioredis.from_url(
        settings.valkey_url,
        decode_responses=True,
        socket_connect_timeout=5,
    )
    await _redis.ping()
    logger.info("Valkey ready (%.0f ms)", (time.monotonic() - t0) * 1000)


async def teardown_valkey() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
        logger.info("Valkey connection closed")


async def create_session(session_id: UUID) -> SessionInfo:
    r = await get_redis()
    now = datetime.now(timezone.utc)
    data = {
        "session_id": str(session_id),
        "created_at": now.isoformat(),
        "last_active": now.isoformat(),
        "message_count": 0,
    }
    await r.setex(
        _key(session_id),
        settings.session_ttl_seconds,
        json.dumps(data),
    )
    return SessionInfo(**data)


async def get_session(session_id: UUID) -> SessionInfo | None:
    r = await get_redis()
    raw = await r.get(_key(session_id))
    if raw is None:
        return None
    return SessionInfo(**json.loads(raw))


async def touch_session(session_id: UUID, increment_count: bool = False) -> None:
    """Refresh TTL and optionally bump message_count."""
    r = await get_redis()
    raw = await r.get(_key(session_id))
    if raw is None:
        return
    data = json.loads(raw)
    data["last_active"] = datetime.now(timezone.utc).isoformat()
    if increment_count:
        data["message_count"] = data.get("message_count", 0) + 1
    await r.setex(
        _key(session_id),
        settings.session_ttl_seconds,
        json.dumps(data),
    )


async def delete_session(session_id: UUID) -> bool:
    r = await get_redis()
    deleted = await r.delete(_key(session_id))
    return bool(deleted)
