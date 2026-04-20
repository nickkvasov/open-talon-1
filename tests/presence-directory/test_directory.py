from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4


_PRESENCE_DIRECTORY_DIR = (
    Path(__file__).resolve().parents[2] / "services" / "presence-directory"
)
presence_path = str(_PRESENCE_DIRECTORY_DIR)
if presence_path not in sys.path:
    sys.path.insert(0, presence_path)

from presence_directory import (  # noqa: E402
    ThreadPresenceDirectory,
    presence_key,
    workspace_presence_key,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


async def test_unregistering_one_connection_keeps_latest_participant_presence() -> None:
    redis = FakeRedis()
    directory = ThreadPresenceDirectory(redis, ttl_seconds=60)
    thread_id = uuid4()
    participant_id = uuid4()

    await directory.register_thread_connection(
        thread_id=thread_id,
        participant_id=participant_id,
        connection_id="conn-a",
    )
    await directory.register_thread_connection(
        thread_id=thread_id,
        participant_id=participant_id,
        connection_id="conn-b",
    )

    replacement = await directory.unregister_thread_connection(
        thread_id=thread_id,
        participant_id=participant_id,
        connection_id="conn-a",
    )

    assert replacement is not None
    assert replacement["connection_id"] == "conn-b"
    payload = json.loads(redis.values[presence_key(thread_id, participant_id)])
    assert payload["connection_id"] == "conn-b"


async def test_touch_presence_updates_presence_without_connection() -> None:
    redis = FakeRedis()
    directory = ThreadPresenceDirectory(redis, ttl_seconds=60)
    thread_id = uuid4()
    participant_id = uuid4()

    await directory.touch_thread_presence(
        thread_id=thread_id,
        participant_id=participant_id,
        status="idle",
    )

    payload = json.loads(redis.values[presence_key(thread_id, participant_id)])
    assert payload["status"] == "idle"
    assert payload["connection_id"] is None


async def test_workspace_presence_stays_active_while_another_thread_connection_exists() -> None:
    redis = FakeRedis()
    directory = ThreadPresenceDirectory(redis, ttl_seconds=60)
    workspace_id = uuid4()
    first_thread_id = uuid4()
    second_thread_id = uuid4()
    participant_id = uuid4()

    await directory.register_thread_connection(
        workspace_id=workspace_id,
        thread_id=first_thread_id,
        participant_id=participant_id,
        connection_id="conn-a",
    )
    await directory.register_thread_connection(
        workspace_id=workspace_id,
        thread_id=second_thread_id,
        participant_id=participant_id,
        connection_id="conn-b",
    )

    await directory.unregister_thread_connection(
        workspace_id=workspace_id,
        thread_id=first_thread_id,
        participant_id=participant_id,
        connection_id="conn-a",
    )

    payload = json.loads(redis.values[workspace_presence_key(workspace_id, participant_id)])
    assert payload["connection_id"] == "conn-b"
    assert payload["thread_id"] == str(second_thread_id)


async def test_workspace_presence_is_removed_after_last_connection_closes() -> None:
    redis = FakeRedis()
    directory = ThreadPresenceDirectory(redis, ttl_seconds=60)
    workspace_id = uuid4()
    thread_id = uuid4()
    participant_id = uuid4()

    await directory.register_thread_connection(
        workspace_id=workspace_id,
        thread_id=thread_id,
        participant_id=participant_id,
        connection_id="conn-a",
    )

    await directory.unregister_thread_connection(
        workspace_id=workspace_id,
        thread_id=thread_id,
        participant_id=participant_id,
        connection_id="conn-a",
    )

    assert workspace_presence_key(workspace_id, participant_id) not in redis.values
