from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID


_THREAD_CONN_PREFIX = "thread-connection:"
_PRESENCE_PREFIX = "thread-presence:"
_WORKSPACE_PRESENCE_PREFIX = "workspace-presence:"


class RedisPresenceStore(Protocol):
    async def set(self, key: str, value: str, ex: int | None = None) -> None: ...

    async def delete(self, key: str) -> None: ...

    async def get(self, key: str) -> str | None: ...

    def scan_iter(self, match: str) -> AsyncIterator[str]: ...


def connection_key(thread_id: UUID, connection_id: str) -> str:
    return f"{_THREAD_CONN_PREFIX}{thread_id}:{connection_id}"


def presence_key(thread_id: UUID, participant_id: UUID) -> str:
    return f"{_PRESENCE_PREFIX}{thread_id}:{participant_id}"


def workspace_presence_key(workspace_id: UUID, participant_id: UUID) -> str:
    return f"{_WORKSPACE_PRESENCE_PREFIX}{workspace_id}:{participant_id}"


class ThreadPresenceDirectory:
    """Tracks per-thread connection and participant presence state in Valkey."""

    def __init__(self, redis: RedisPresenceStore, *, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    async def register_thread_connection(
        self,
        *,
        workspace_id: UUID | None = None,
        thread_id: UUID,
        participant_id: UUID,
        connection_id: str,
        status: str = "active",
    ) -> None:
        payload = self._presence_payload(
            workspace_id=workspace_id,
            thread_id=thread_id,
            participant_id=participant_id,
            connection_id=connection_id,
            status=status,
        )
        await self._write_payload(connection_key(thread_id, connection_id), payload)
        await self._write_payload(presence_key(thread_id, participant_id), payload)
        if workspace_id is not None:
            await self._write_payload(workspace_presence_key(workspace_id, participant_id), payload)

    async def unregister_thread_connection(
        self,
        *,
        workspace_id: UUID | None = None,
        thread_id: UUID,
        participant_id: UUID,
        connection_id: str,
    ) -> dict[str, str] | None:
        await self._redis.delete(connection_key(thread_id, connection_id))
        remaining_connections = await self._list_participant_connections(
            thread_id=thread_id,
            participant_id=participant_id,
        )
        if remaining_connections:
            replacement = remaining_connections[0]
            await self._write_payload(presence_key(thread_id, participant_id), replacement)
            if workspace_id is not None:
                workspace_replacement = await self._first_workspace_connection(
                    workspace_id=workspace_id,
                    participant_id=participant_id,
                )
                if workspace_replacement is not None:
                    await self._write_payload(
                        workspace_presence_key(workspace_id, participant_id),
                        workspace_replacement,
                    )
            return replacement
        await self._redis.delete(presence_key(thread_id, participant_id))
        if workspace_id is not None:
            workspace_replacement = await self._first_workspace_connection(
                workspace_id=workspace_id,
                participant_id=participant_id,
            )
            if workspace_replacement is not None:
                await self._write_payload(
                    workspace_presence_key(workspace_id, participant_id),
                    workspace_replacement,
                )
            else:
                await self._redis.delete(workspace_presence_key(workspace_id, participant_id))
        return None

    async def touch_thread_presence(
        self,
        *,
        workspace_id: UUID | None = None,
        thread_id: UUID,
        participant_id: UUID,
        connection_id: str | None = None,
        status: str = "active",
    ) -> None:
        payload = self._presence_payload(
            workspace_id=workspace_id,
            thread_id=thread_id,
            participant_id=participant_id,
            connection_id=connection_id,
            status=status,
        )
        await self._write_payload(presence_key(thread_id, participant_id), payload)
        if workspace_id is not None:
            await self._write_payload(workspace_presence_key(workspace_id, participant_id), payload)
        if connection_id is not None:
            await self._write_payload(connection_key(thread_id, connection_id), payload)

    async def get_workspace_participant_presence(
        self,
        *,
        workspace_id: UUID,
        participant_id: UUID,
    ) -> dict[str, str] | None:
        raw = await self._redis.get(workspace_presence_key(workspace_id, participant_id))
        if raw is None:
            return None
        return json.loads(raw)

    async def _write_payload(self, key: str, payload: dict[str, str | None]) -> None:
        await self._redis.set(
            key,
            json.dumps(payload),
            ex=self._ttl_seconds,
        )

    def _presence_payload(
        self,
        *,
        workspace_id: UUID | None,
        thread_id: UUID,
        participant_id: UUID,
        connection_id: str | None,
        status: str,
    ) -> dict[str, str | None]:
        return {
            "workspace_id": str(workspace_id) if workspace_id is not None else None,
            "thread_id": str(thread_id),
            "participant_id": str(participant_id),
            "connection_id": connection_id,
            "status": status,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }

    async def _list_participant_connections(
        self,
        *,
        thread_id: UUID,
        participant_id: UUID,
    ) -> list[dict[str, str]]:
        pattern = connection_key(thread_id, "*")
        payloads: list[dict[str, str]] = []

        if hasattr(self._redis, "scan_iter"):
            async for key in self._redis.scan_iter(match=pattern):
                raw = await self._redis.get(key)
                if raw is None:
                    continue
                payload = json.loads(raw)
                if payload.get("participant_id") == str(participant_id):
                    payloads.append(payload)
            return payloads

        values = getattr(self._redis, "values", None)
        if isinstance(values, dict):
            connection_prefix = connection_key(thread_id, "")
            for key, raw in values.items():
                if not key.startswith(connection_prefix):
                    continue
                payload = json.loads(raw)
                if payload.get("participant_id") == str(participant_id):
                    payloads.append(payload)
        return payloads

    async def _first_workspace_connection(
        self,
        *,
        workspace_id: UUID,
        participant_id: UUID,
    ) -> dict[str, str] | None:
        pattern = connection_key("*", "*")

        if hasattr(self._redis, "scan_iter"):
            async for key in self._redis.scan_iter(match=pattern):
                raw = await self._redis.get(key)
                if raw is None:
                    continue
                payload = json.loads(raw)
                if payload.get("participant_id") == str(participant_id) and payload.get(
                    "workspace_id"
                ) == str(workspace_id):
                    return payload
            return None

        values = getattr(self._redis, "values", None)
        if isinstance(values, dict):
            for key, raw in values.items():
                if not key.startswith(_THREAD_CONN_PREFIX):
                    continue
                payload = json.loads(raw)
                if payload.get("participant_id") == str(participant_id) and payload.get(
                    "workspace_id"
                ) == str(workspace_id):
                    return payload
        return None
