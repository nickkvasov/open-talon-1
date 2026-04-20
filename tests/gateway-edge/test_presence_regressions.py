from __future__ import annotations

import json
from uuid import uuid4

import pytest


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def get(self, key: str) -> str | None:
        return self.values.get(key)


@pytest.mark.asyncio
async def test_unregistering_one_connection_keeps_participant_present_if_another_connection_exists(
    monkeypatch,
):
    from gateway_edge.services import session as session_svc

    redis = FakeRedis()
    thread_id = uuid4()
    participant_id = uuid4()

    async def fake_get_redis():
        return redis

    monkeypatch.setattr(session_svc, "get_redis", fake_get_redis)

    await session_svc.register_thread_connection(
        thread_id=thread_id,
        participant_id=participant_id,
        connection_id="conn-a",
    )
    await session_svc.register_thread_connection(
        thread_id=thread_id,
        participant_id=participant_id,
        connection_id="conn-b",
    )

    await session_svc.unregister_thread_connection(
        thread_id=thread_id,
        participant_id=participant_id,
        connection_id="conn-a",
    )

    presence_payload = await redis.get(
        session_svc._presence_key(thread_id, participant_id)  # noqa: SLF001
    )

    assert presence_payload is not None
    assert json.loads(presence_payload)["connection_id"] == "conn-b"


@pytest.mark.asyncio
async def test_workspace_presence_keeps_latest_connection_across_threads(monkeypatch):
    from gateway_edge.services import session as session_svc

    redis = FakeRedis()
    workspace_id = uuid4()
    first_thread_id = uuid4()
    second_thread_id = uuid4()
    participant_id = uuid4()

    async def fake_get_redis():
        return redis

    monkeypatch.setattr(session_svc, "get_redis", fake_get_redis)

    await session_svc.register_thread_connection(
        workspace_id=workspace_id,
        thread_id=first_thread_id,
        participant_id=participant_id,
        connection_id="conn-a",
    )
    await session_svc.register_thread_connection(
        workspace_id=workspace_id,
        thread_id=second_thread_id,
        participant_id=participant_id,
        connection_id="conn-b",
    )

    await session_svc.unregister_thread_connection(
        workspace_id=workspace_id,
        thread_id=first_thread_id,
        participant_id=participant_id,
        connection_id="conn-a",
    )

    presence_payload = await session_svc.get_workspace_participant_presence(
        workspace_id=workspace_id,
        participant_id=participant_id,
    )

    assert presence_payload is not None
    assert presence_payload["connection_id"] == "conn-b"
    assert presence_payload["thread_id"] == str(second_thread_id)
