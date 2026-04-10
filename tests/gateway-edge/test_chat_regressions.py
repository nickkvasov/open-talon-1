from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


async def test_get_session_returns_not_found_instead_of_internal_error(patched, monkeypatch):
    from gateway_edge.config import settings
    from gateway_edge.main import create_app
    from gateway_edge.routers import chat as chat_router

    monkeypatch.setattr(settings, "auth_mode", "none")
    monkeypatch.setattr(chat_router.session_svc, "get_session", AsyncMock(return_value=None))
    app = create_app()
    app.router.lifespan_context = _null_lifespan

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        resp = await client.get(f"/v1/sessions/{uuid4()}")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_history_queries_latest_messages_first(monkeypatch):
    from gateway_edge.services import history as history_svc

    captured: dict[str, object] = {}
    session_id = uuid4()

    class FakeConn:
        async def fetch(self, query, *args):
            captured["query"] = query
            captured["args"] = args
            now = datetime.now(timezone.utc)
            return [
                {"role": "assistant", "content": "latest", "created_at": now},
                {
                    "role": "user",
                    "content": "older",
                    "created_at": now - timedelta(seconds=1),
                },
            ]

    class FakeAcquire:
        async def __aenter__(self):
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    async def fake_get_pool():
        return FakePool()

    monkeypatch.setattr(history_svc, "get_pool", fake_get_pool)

    await history_svc.get_history(session_id, limit=20)

    query = str(captured["query"])
    assert "ORDER BY created_at DESC" in query


@pytest.mark.asyncio
async def test_build_kafka_request_uses_latest_context_window(monkeypatch):
    from gateway_edge.routers import chat
    from gateway_edge.models import Message

    session_id = uuid4()
    now = datetime.now(timezone.utc)
    expected = [
        Message(role="user", content="recent-1", timestamp=now),
        Message(role="assistant", content="recent-2", timestamp=now),
    ]

    async def fake_get_history(requested_session_id, limit=50):
        assert requested_session_id == session_id
        assert limit == 20
        return expected

    monkeypatch.setattr(chat.history_svc, "get_history", fake_get_history)

    request = await chat._build_kafka_request(session_id, "next turn")

    assert request.history == expected
