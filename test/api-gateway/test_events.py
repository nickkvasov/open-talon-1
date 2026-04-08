"""
Unit tests for EventService internals.

All Kafka connections are mocked — no broker is needed.
Tests exercise the future/queue correlation logic and the echo agent.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models import KafkaChatRequest, KafkaChatResponse, StreamEvent
from app.services.events import EventService


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def svc() -> EventService:
    """A fresh EventService instance — Kafka connections not started."""
    return EventService()


@pytest.fixture
def started_svc(svc):
    """EventService with mocked Kafka connections already 'started'."""
    mock_producer = AsyncMock()
    mock_consumer = AsyncMock()
    svc._producer = mock_producer
    svc._consumer = mock_consumer
    return svc


# ── _dispatch — REST future path ──────────────────────────────────────────────

async def test_dispatch_resolves_pending_future(svc):
    corr = uuid4()
    sid = uuid4()
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    svc._pending[str(corr)] = future

    response_data = {
        "correlation_id": str(corr),
        "session_id": str(sid),
        "type": "response",
        "role": "assistant",
        "content": "Hello from agent",
    }
    await svc._dispatch(response_data)

    assert future.done()
    result = future.result()
    assert result.content == "Hello from agent"


async def test_dispatch_ignores_unknown_correlation_id(svc):
    data = {
        "correlation_id": str(uuid4()),
        "session_id": str(uuid4()),
        "type": "response",
        "content": "orphan",
    }
    # Should not raise
    await svc._dispatch(data)


async def test_dispatch_drops_malformed_message(svc):
    await svc._dispatch({"garbage": "data"})  # missing required fields, should not raise


async def test_dispatch_does_not_double_set_done_future(svc):
    corr = uuid4()
    sid = uuid4()
    loop = asyncio.get_event_loop()
    future = loop.create_future()
    svc._pending[str(corr)] = future

    data = {
        "correlation_id": str(corr),
        "session_id": str(sid),
        "type": "response",
        "content": "first",
    }
    await svc._dispatch(data)
    await svc._dispatch(data)  # second dispatch must not raise InvalidStateError


# ── _dispatch — streaming queue path ─────────────────────────────────────────

async def test_dispatch_routes_stream_token_to_queue(svc):
    corr = uuid4()
    sid = uuid4()
    queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
    svc._streams[str(corr)] = queue

    await svc._dispatch({
        "correlation_id": str(corr),
        "session_id": str(sid),
        "type": "stream_token",
        "content": "partial",
    })

    evt = queue.get_nowait()
    assert evt.type == "token"
    assert evt.content == "partial"


async def test_dispatch_routes_stream_done_to_queue(svc):
    corr = uuid4()
    sid = uuid4()
    queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
    svc._streams[str(corr)] = queue

    await svc._dispatch({
        "correlation_id": str(corr),
        "session_id": str(sid),
        "type": "stream_done",
        "content": "final",
    })

    evt = queue.get_nowait()
    assert evt.type == "done"


async def test_dispatch_routes_error_to_queue(svc):
    corr = uuid4()
    sid = uuid4()
    queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
    svc._streams[str(corr)] = queue

    await svc._dispatch({
        "correlation_id": str(corr),
        "session_id": str(sid),
        "type": "error",
        "error": "Something broke",
    })

    evt = queue.get_nowait()
    assert evt.type == "error"
    assert evt.error == "Something broke"


# ── wait_for_response ─────────────────────────────────────────────────────────

async def test_wait_for_response_returns_result(svc):
    corr = uuid4()
    sid = uuid4()

    async def _deliver():
        await asyncio.sleep(0.01)
        await svc._dispatch({
            "correlation_id": str(corr),
            "session_id": str(sid),
            "type": "response",
            "content": "delivered",
        })

    asyncio.create_task(_deliver())
    result = await svc.wait_for_response(corr, timeout=2.0)
    assert result.content == "delivered"


async def test_wait_for_response_timeout_raises(svc):
    corr = uuid4()
    with pytest.raises((TimeoutError, asyncio.TimeoutError)):
        await svc.wait_for_response(corr, timeout=0.05)


async def test_wait_for_response_cleans_up_pending_on_success(svc):
    corr = uuid4()
    sid = uuid4()

    async def _deliver():
        await asyncio.sleep(0.01)
        await svc._dispatch({
            "correlation_id": str(corr),
            "session_id": str(sid),
            "type": "response",
            "content": "ok",
        })

    asyncio.create_task(_deliver())
    await svc.wait_for_response(corr, timeout=2.0)
    assert str(corr) not in svc._pending


async def test_wait_for_response_cleans_up_pending_on_timeout(svc):
    corr = uuid4()
    try:
        await svc.wait_for_response(corr, timeout=0.05)
    except (TimeoutError, asyncio.TimeoutError):
        pass
    assert str(corr) not in svc._pending


# ── stream_response ───────────────────────────────────────────────────────────

async def test_stream_response_yields_token_then_done(svc):
    corr = uuid4()
    sid = uuid4()

    async def _send_events():
        await asyncio.sleep(0.01)
        await svc._dispatch({"correlation_id": str(corr), "session_id": str(sid), "type": "stream_token", "content": "tok"})
        await svc._dispatch({"correlation_id": str(corr), "session_id": str(sid), "type": "stream_done",  "content": ""})

    asyncio.create_task(_send_events())

    events = []
    async for evt in svc.stream_response(corr):
        events.append(evt)

    assert events[0].type == "token"
    assert events[-1].type == "done"


async def test_stream_response_yields_error_and_stops(svc):
    corr = uuid4()
    sid = uuid4()

    async def _send_event():
        await asyncio.sleep(0.01)
        await svc._dispatch({"correlation_id": str(corr), "session_id": str(sid), "type": "error", "error": "boom"})

    asyncio.create_task(_send_event())

    events = []
    async for evt in svc.stream_response(corr):
        events.append(evt)

    assert len(events) == 1
    assert events[0].type == "error"


async def test_stream_response_cleans_up_queue(svc):
    corr = uuid4()
    sid = uuid4()

    async def _finish():
        await asyncio.sleep(0.01)
        await svc._dispatch({"correlation_id": str(corr), "session_id": str(sid), "type": "stream_done", "content": ""})

    asyncio.create_task(_finish())
    async for _ in svc.stream_response(corr):
        pass

    assert str(corr) not in svc._streams


# ── publish_chat_request ──────────────────────────────────────────────────────

async def test_publish_raises_if_not_started(svc):
    req = KafkaChatRequest(session_id=uuid4(), message="hi")
    with pytest.raises(RuntimeError, match="not started"):
        await svc.publish_chat_request(req)


async def test_publish_sends_to_correct_topic(started_svc):
    from app.config import settings
    req = KafkaChatRequest(session_id=uuid4(), message="pub test")
    await started_svc.publish_chat_request(req)
    started_svc._producer.send_and_wait.assert_called_once()
    call_args = started_svc._producer.send_and_wait.call_args
    assert call_args[0][0] == settings.kafka_request_topic


async def test_publish_serializes_message_field(started_svc):
    req = KafkaChatRequest(session_id=uuid4(), message="the content")
    await started_svc.publish_chat_request(req)
    payload = started_svc._producer.send_and_wait.call_args[1]["value"]
    assert payload["message"] == "the content"
