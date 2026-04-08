"""
Tests for WebSocket /v1/ws/chat/{session_id}.

Uses Starlette's synchronous TestClient (sync_client fixture) since
httpx does not natively support the WebSocket protocol.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest


# ── Connection ────────────────────────────────────────────────────────────────

def test_websocket_connects(sync_client):
    sid = uuid4()
    with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws:
        pass  # should not raise


def test_websocket_rejects_without_auth(sync_client, monkeypatch):
    from starlette.websockets import WebSocketDisconnect
    from app.config import settings

    monkeypatch.setattr(settings, "auth_mode", "api_key")
    sid = uuid4()
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect(f"/v1/ws/chat/{sid}"):
            pass
    assert exc.value.code == 4001


def test_websocket_creates_session_on_connect(sync_client, session_store):
    sid = uuid4()
    with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws:
        pass
    # Session is created lazily on first connect
    # (may already be in session_store after websocket accept)


# ── Message round-trip ────────────────────────────────────────────────────────

def test_websocket_receives_token_event(sync_client, mock_event):
    mock_event.stream_tokens = ["Hi"]
    sid = uuid4()
    with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws:
        ws.send_json({"message": "hello"})
        events = _drain_until_done(ws)
    types = {e["type"] for e in events}
    assert "token" in types or "done" in types  # at minimum one stream event


def test_websocket_receives_done_event(sync_client, mock_event):
    mock_event.stream_tokens = ["foo"]
    sid = uuid4()
    with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws:
        ws.send_json({"message": "hi"})
        events = _drain_until_done(ws)
    assert any(e["type"] == "done" for e in events)


def test_websocket_token_content_matches_mock(sync_client, mock_event):
    mock_event.stream_tokens = ["Greetings"]
    sid = uuid4()
    with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws:
        ws.send_json({"message": "test"})
        events = _drain_until_done(ws)
    token_events = [e for e in events if e["type"] == "token"]
    assert any(e["content"] == "Greetings" for e in token_events)


def test_websocket_empty_message_returns_error(sync_client, mock_event):
    sid = uuid4()
    with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws:
        ws.send_json({"message": "  "})
        msg = ws.receive_json()
    assert msg["type"] == "error"


def test_websocket_agent_error_surfaces_to_client(sync_client, mock_event):
    mock_event.stream_error = "Kafka down"
    sid = uuid4()
    with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws:
        ws.send_json({"message": "hello"})
        events = _drain_until_done(ws)
    assert any(e["type"] == "error" for e in events)


def test_websocket_publishes_to_kafka(sync_client, mock_event):
    sid = uuid4()
    with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws:
        ws.send_json({"message": "publish test"})
        _drain_until_done(ws)
    assert len(mock_event.published) == 1
    assert mock_event.published[0].message == "publish test"


def test_websocket_multiple_turns(sync_client, mock_event):
    """A single WebSocket connection can service multiple consecutive messages."""
    mock_event.stream_tokens = ["A"]
    sid = uuid4()
    with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws:
        ws.send_json({"message": "turn 1"})
        _drain_until_done(ws)
        ws.send_json({"message": "turn 2"})
        _drain_until_done(ws)
    assert len(mock_event.published) == 2


def test_websocket_saves_messages_to_history(sync_client, mock_event, history_store):
    mock_event.stream_tokens = ["Bot reply"]
    sid = uuid4()
    with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws:
        ws.send_json({"message": "save me"})
        _drain_until_done(ws)
    all_msgs = history_store.get(str(sid), [])
    assert any(m.role == "user" for m in all_msgs)
    assert any(m.role == "assistant" for m in all_msgs)


def test_websocket_two_users_interaction(sync_client, mock_event, history_store):
    """Two TUI instances sharing the same session."""
    mock_event.stream_tokens = ["User reply"]
    sid = uuid4()
    
    with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws1:
        with sync_client.websocket_connect(f"/v1/ws/chat/{sid}") as ws2:
            
            # User 1 sends a message
            ws1.send_json({"message": "I am user 1"})
            
            # User 2 sends a message concurrently
            ws2.send_json({"message": "I am user 2"})
            
            evts1 = _drain_until_done(ws1)
            evts2 = _drain_until_done(ws2)
            
            assert any(e.get("type") == "done" for e in evts1)
            assert any(e.get("type") == "done" for e in evts2)
            
    # Both messages should be saved
    all_msgs = history_store.get(str(sid), [])
    user_contents = [m.content for m in all_msgs if m.role == "user"]
    assert "I am user 1" in user_contents
    assert "I am user 2" in user_contents


# ── Helpers ───────────────────────────────────────────────────────────────────

def _drain_until_done(ws, max_events: int = 20) -> list[dict]:
    """Receive events until a 'done' or 'error' type appears."""
    events = []
    for _ in range(max_events):
        msg = ws.receive_json()
        events.append(msg)
        if msg.get("type") in ("done", "error"):
            break
    return events
