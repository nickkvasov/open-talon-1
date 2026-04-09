"""
Shared pytest fixtures for the Open Talon API Gateway test suite.

Two test layers
---------------
Unit tests (default — no docker needed):
    pytest tests/gateway-edge/ -m "not integration"

Integration tests (requires running infra + gateway):
    pytest tests/gateway-edge/ -m integration

The unit layer patches all IO (Postgres → asyncpg, Valkey → redis, Kafka →
aiokafka) with lightweight in-process fakes so tests run in milliseconds.

Key fixtures
------------
session_store   dict  – in-memory Valkey substitute
history_store   dict  – in-memory Postgres substitute
mock_event      MockEventService – controllable Kafka stand-in
patched         fixture – applies ALL patches; use as fixture dep
client          AsyncClient against the ASGI app (unit tests)
sync_client     TestClient with WebSocket support (unit tests)
"""
from __future__ import annotations

import sys
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

# ── Make the migrated service + contracts importable ─────────────────────────
_GW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/gateway-edge")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
for path in (_GW_DIR, _CONTRACTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

# ── Null lifespan — skips real service connections ────────────────────────────

@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


# ── Mock EventService ─────────────────────────────────────────────────────────

class MockEventService:
    """
    Drop-in replacement for EventService.

    Tests can customise:
      mock_event.response_content  – what wait_for_response returns
      mock_event.stream_tokens     – token list yielded by stream_response
      mock_event.stream_error      – if set, stream_response yields an error event
      mock_event.published         – list of KafkaChatRequest published
    """

    def __init__(self) -> None:
        self.response_content: str = "Mock assistant response"
        self.stream_tokens: list[str] = ["Hello", " world"]
        self.stream_error: str | None = None
        self.published: list = []
        self._registry: dict[str, UUID] = {}

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    def register_response_future(self, correlation_id: UUID) -> None: ...
    def register_stream_queue(self, correlation_id: UUID) -> None: ...

    async def publish_chat_request(self, request) -> None:
        self.published.append(request)
        self._registry[str(request.correlation_id)] = request.session_id

    async def wait_for_response(self, correlation_id: UUID, timeout=None):
        from gateway_edge.models import KafkaChatResponse
        sid = self._registry.get(str(correlation_id), uuid4())
        return KafkaChatResponse(
            correlation_id=correlation_id,
            session_id=sid,
            type="response",
            content=self.response_content,
        )

    async def stream_response(self, correlation_id: UUID) -> AsyncIterator:
        from gateway_edge.models import StreamEvent
        sid = self._registry.get(str(correlation_id), uuid4())
        if self.stream_error:
            yield StreamEvent(type="error", session_id=sid, correlation_id=correlation_id, error=self.stream_error)
            return
        for token in self.stream_tokens:
            yield StreamEvent(type="token", session_id=sid, correlation_id=correlation_id, content=token)
        yield StreamEvent(type="done", session_id=sid, correlation_id=correlation_id, content="")


# ── Simple in-memory stores ───────────────────────────────────────────────────

@pytest.fixture
def session_store() -> dict:
    """Blank in-memory session dict for each test."""
    return {}


@pytest.fixture
def history_store() -> dict:
    """Blank in-memory history dict for each test."""
    return {}


@pytest.fixture
def mock_event() -> MockEventService:
    """Controllable Kafka stand-in for each test."""
    return MockEventService()


# ── Master patch fixture ──────────────────────────────────────────────────────

@pytest.fixture
def patched(monkeypatch, session_store, history_store, mock_event):
    """
    Apply all IO-layer patches.  Depends on session_store, history_store,
    and mock_event so tests can inspect and mutate them.
    """
    from gateway_edge.models import SessionInfo

    # ── Session service ───────────────────────────────────────────────────────
    async def _create_session(sid: UUID) -> SessionInfo:
        now = datetime.now(timezone.utc)
        data = {
            "session_id": str(sid),
            "created_at": now.isoformat(),
            "last_active": now.isoformat(),
            "message_count": 0,
        }
        session_store[str(sid)] = data
        return SessionInfo(**data)

    async def _get_session(sid: UUID) -> SessionInfo | None:
        data = session_store.get(str(sid))
        return SessionInfo(**data) if data else None

    async def _touch_session(sid: UUID, increment_count: bool = False) -> None:
        if str(sid) in session_store:
            session_store[str(sid)]["last_active"] = datetime.now(timezone.utc).isoformat()
            if increment_count:
                session_store[str(sid)]["message_count"] += 1

    async def _delete_session(sid: UUID) -> bool:
        return bool(session_store.pop(str(sid), None))

    monkeypatch.setattr("gateway_edge.services.session.create_session", _create_session)
    monkeypatch.setattr("gateway_edge.services.session.get_session",    _get_session)
    monkeypatch.setattr("gateway_edge.services.session.touch_session",  _touch_session)
    monkeypatch.setattr("gateway_edge.services.session.delete_session", _delete_session)
    monkeypatch.setattr("gateway_edge.services.session.setup_valkey",   AsyncMock())
    monkeypatch.setattr("gateway_edge.services.session.teardown_valkey", AsyncMock())

    # ── History service ───────────────────────────────────────────────────────
    async def _save_message(session_id: UUID, message, correlation_id=None) -> None:
        history_store.setdefault(str(session_id), []).append(message)

    async def _get_history(session_id: UUID, limit: int = 50) -> list:
        return history_store.get(str(session_id), [])[:limit]

    async def _delete_history(session_id: UUID) -> int:
        removed = history_store.pop(str(session_id), [])
        return len(removed)

    monkeypatch.setattr("gateway_edge.services.history.save_message",   _save_message)
    monkeypatch.setattr("gateway_edge.services.history.get_history",    _get_history)
    monkeypatch.setattr("gateway_edge.services.history.delete_history", _delete_history)

    # ── Postgres lifecycle ────────────────────────────────────────────────────
    monkeypatch.setattr("gateway_edge.db.postgres.setup_postgres",   AsyncMock())
    monkeypatch.setattr("gateway_edge.db.postgres.teardown_postgres", AsyncMock())

    # ── EventService singleton ────────────────────────────────────────────────
    monkeypatch.setattr("gateway_edge.services.events.event_service",      mock_event)
    monkeypatch.setattr("gateway_edge.routers.chat.event_svc.event_service", mock_event)

    return {
        "session_store": session_store,
        "history_store": history_store,
        "mock_event":    mock_event,
    }


# ── Async HTTP client (unit tests) ────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(patched) -> AsyncIterator[AsyncClient]:
    """Async HTTPX client against the mocked ASGI gateway_edge."""
    from gateway_edge.main import create_app
    app = create_app()
    app.router.lifespan_context = _null_lifespan
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ── Sync TestClient with WebSocket support (unit tests) ───────────────────────

@pytest.fixture
def sync_client(patched):
    """Synchronous Starlette TestClient — used for WebSocket tests."""
    from starlette.testclient import TestClient
    from gateway_edge.main import create_app
    app = create_app()
    app.router.lifespan_context = _null_lifespan
    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc
