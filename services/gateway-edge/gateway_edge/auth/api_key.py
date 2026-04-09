"""
API-key auth backend.

Keys are stored in Valkey as a hash under  ``apikey:{key_id}``  with fields:
  label, key_hash, created_at, expires_at (optional)

The raw key is returned once at creation time and never stored in plaintext.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from uuid import uuid4

import redis.asyncio as aioredis

from gateway_edge.models import ApiKeyCreate, ApiKeyInfo
from gateway_edge.services.session import get_redis

logger = logging.getLogger(__name__)

_PREFIX = "apikey:"
_INDEX = "apikeys:index"  # Set of key_ids for listing


def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _redis_key(key_id: str) -> str:
    return f"{_PREFIX}{key_id}"


async def create_api_key(payload: ApiKeyCreate) -> ApiKeyInfo:
    r: aioredis.Redis = await get_redis()
    key_id = str(uuid4())
    raw_key = secrets.token_urlsafe(32)
    key_hash = _hash_key(raw_key)
    now = datetime.now(timezone.utc)

    data: dict[str, str] = {
        "key_id": key_id,
        "label": payload.label,
        "key_hash": key_hash,
        "created_at": now.isoformat(),
        "expires_at": "",
    }

    pipe = r.pipeline()
    pipe.hset(_redis_key(key_id), mapping=data)
    pipe.sadd(_INDEX, key_id)
    if payload.ttl_seconds:
        pipe.expire(_redis_key(key_id), payload.ttl_seconds)
    await pipe.execute()

    return ApiKeyInfo(
        key_id=key_id,
        label=payload.label,
        created_at=now,
        expires_at=None,
        raw_key=raw_key,
    )


async def validate_api_key(raw_key: str) -> bool:
    """Return True if the key exists and is not expired."""
    r: aioredis.Redis = await get_redis()
    key_hash = _hash_key(raw_key)
    # Scan all keys — acceptable for expected key volume (<10k)
    all_ids: set[str] = await r.smembers(_INDEX)  # type: ignore[assignment]
    for key_id in all_ids:
        stored_hash = await r.hget(_redis_key(key_id), "key_hash")
        if stored_hash == key_hash:
            return True
    return False


async def revoke_api_key(key_id: str) -> bool:
    r: aioredis.Redis = await get_redis()
    deleted = await r.delete(_redis_key(key_id))
    await r.srem(_INDEX, key_id)
    return bool(deleted)


async def list_api_keys() -> list[ApiKeyInfo]:
    r: aioredis.Redis = await get_redis()
    all_ids: set[str] = await r.smembers(_INDEX)  # type: ignore[assignment]
    keys: list[ApiKeyInfo] = []
    for key_id in all_ids:
        data = await r.hgetall(_redis_key(key_id))
        if not data:
            continue
        keys.append(
            ApiKeyInfo(
                key_id=data["key_id"],
                label=data["label"],
                created_at=datetime.fromisoformat(data["created_at"]),
                expires_at=(
                    datetime.fromisoformat(data["expires_at"])
                    if data.get("expires_at")
                    else None
                ),
            )
        )
    return keys
