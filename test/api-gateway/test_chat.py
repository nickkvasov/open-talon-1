"""
Tests for POST /v1/chat (synchronous) and POST /v1/chat/stream (SSE).
WebSocket tests live in test_websocket.py.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest


# ── POST /v1/chat — new session ────────────────────────────────────────────────

async def test_chat_creates_new_session_when_none_given(client):
    resp = await client.post("/v1/chat", json={"message": "Hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert body["session_id"] is not None


async def test_chat_returns_assistant_message(client):
    resp = await client.post("/v1/chat", json={"message": "Hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"]["role"] == "assistant"
    assert isinstance(body["message"]["content"], str)
    assert len(body["message"]["content"]) > 0


async def test_chat_returns_correlation_id(client):
    resp = await client.post("/v1/chat", json={"message": "Hi"})
    assert resp.status_code == 200
    assert "correlation_id" in resp.json()


async def test_chat_returns_latency_ms(client):
    resp = await client.post("/v1/chat", json={"message": "Hi"})
    body = resp.json()
    assert "latency_ms" in body
    assert isinstance(body["latency_ms"], int)
    assert body["latency_ms"] >= 0


async def test_chat_publishes_to_kafka(client, mock_event):
    await client.post("/v1/chat", json={"message": "test publish"})
    assert len(mock_event.published) == 1
    published = mock_event.published[0]
    assert published.message == "test publish"


async def test_chat_uses_mock_response_content(client, mock_event):
    mock_event.response_content = "Custom mock reply"
    resp = await client.post("/v1/chat", json={"message": "anything"})
    assert resp.json()["message"]["content"] == "Custom mock reply"


# ── POST /v1/chat — existing session ──────────────────────────────────────────

async def test_chat_resumes_existing_session(client, session_store):
    # First message — creates session
    r1 = await client.post("/v1/chat", json={"message": "First"})
    sid = r1.json()["session_id"]
    assert sid in session_store

    # Second message — same session
    r2 = await client.post("/v1/chat", json={"message": "Second", "session_id": sid})
    assert r2.status_code == 200
    assert r2.json()["session_id"] == sid


async def test_chat_unknown_session_returns_404(client):
    fake_id = str(uuid4())
    resp = await client.post("/v1/chat", json={"message": "Hi", "session_id": fake_id})
    assert resp.status_code == 404


async def test_chat_saves_user_and_assistant_to_history(client, history_store):
    resp = await client.post("/v1/chat", json={"message": "testing history"})
    sid = resp.json()["session_id"]
    messages = history_store.get(sid, [])
    roles = [m.role for m in messages]
    assert "user" in roles
    assert "assistant" in roles


async def test_chat_increments_session_message_count(client, session_store):
    resp = await client.post("/v1/chat", json={"message": "count me"})
    sid = resp.json()["session_id"]
    assert session_store[sid]["message_count"] == 1


# ── POST /v1/chat — Kafka timeout ─────────────────────────────────────────────

async def test_chat_returns_504_on_timeout(client, mock_event, monkeypatch):
    async def _timeout(correlation_id, timeout=None):
        raise TimeoutError

    monkeypatch.setattr(mock_event, "wait_for_response", _timeout)
    resp = await client.post("/v1/chat", json={"message": "agent is down"})
    assert resp.status_code == 504


# ── POST /v1/chat/stream — SSE ────────────────────────────────────────────────

async def test_chat_stream_returns_200(client):
    resp = await client.post("/v1/chat/stream", json={"message": "stream me"})
    assert resp.status_code == 200


async def test_chat_stream_content_type_is_sse(client):
    resp = await client.post("/v1/chat/stream", json={"message": "stream"})
    assert "text/event-stream" in resp.headers.get("content-type", "")


async def test_chat_stream_emits_token_and_done_events(client, mock_event):
    mock_event.stream_tokens = ["foo", " bar"]
    resp = await client.post("/v1/chat/stream", json={"message": "stream"})
    events = _parse_sse(resp.text)
    types = [e["type"] for e in events]
    assert "token" in types
    assert "done" in types


async def test_chat_stream_tokens_contain_content(client, mock_event):
    mock_event.stream_tokens = ["Alpha", " Beta"]
    resp = await client.post("/v1/chat/stream", json={"message": "stream"})
    events = _parse_sse(resp.text)
    tokens = [e["content"] for e in events if e["type"] == "token"]
    assert "Alpha" in tokens
    assert " Beta" in tokens


async def test_chat_stream_error_event_on_agent_error(client, mock_event):
    mock_event.stream_error = "Agent exploded"
    resp = await client.post("/v1/chat/stream", json={"message": "oops"})
    events = _parse_sse(resp.text)
    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert errors[0]["error"] == "Agent exploded"


async def test_chat_stream_saves_accumulated_content_to_history(client, mock_event, history_store):
    mock_event.stream_tokens = ["Hello", " there"]
    resp = await client.post("/v1/chat/stream", json={"message": "stream history"})
    sid = None
    for evt in _parse_sse(resp.text):
        if "session_id" in evt:
            sid = evt["session_id"]
            break
    # History may use session_id from any response event; just verify assistant saved
    all_msgs = [m for msgs in history_store.values() for m in msgs]
    assistant_msgs = [m for m in all_msgs if m.role == "assistant"]
    assert any("Hello there" in m.content for m in assistant_msgs)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_sse(text: str) -> list[dict]:
    """Parse SSE body into a list of data dicts."""
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            raw = line[6:].strip()
            if raw:
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
    return events
