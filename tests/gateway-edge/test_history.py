"""
Tests for GET /v1/history/{session_id}.
"""
from __future__ import annotations

from uuid import uuid4

import pytest


# ── Basic retrieval ────────────────────────────────────────────────────────────

async def test_history_empty_for_fresh_session(client, session_store):
    """New session with no messages returns an empty list."""
    from datetime import datetime, timezone
    from gateway_edge.models import SessionInfo
    sid = uuid4()
    now = datetime.now(timezone.utc)
    session_store[str(sid)] = {
        "session_id": str(sid),
        "created_at": now.isoformat(),
        "last_active": now.isoformat(),
        "message_count": 0,
    }

    r = await client.get(f"/v1/history/{sid}")
    assert r.status_code == 200
    assert r.json() == []


async def test_history_not_found_for_unknown_session(client):
    r = await client.get(f"/v1/history/{uuid4()}")
    assert r.status_code == 404


async def test_history_returns_list_of_messages(client):
    resp = await client.post("/v1/chat", json={"message": "hello"})
    sid = resp.json()["session_id"]

    r = await client.get(f"/v1/history/{sid}")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_history_contains_user_and_assistant_roles(client):
    resp = await client.post("/v1/chat", json={"message": "how are you"})
    sid = resp.json()["session_id"]

    r = await client.get(f"/v1/history/{sid}")
    roles = {m["role"] for m in r.json()}
    assert "user" in roles
    assert "assistant" in roles


async def test_history_message_shape(client):
    resp = await client.post("/v1/chat", json={"message": "shape test"})
    sid = resp.json()["session_id"]

    r = await client.get(f"/v1/history/{sid}")
    for msg in r.json():
        assert "role" in msg
        assert "content" in msg
        assert "timestamp" in msg


async def test_history_preserves_message_content(client, mock_event):
    mock_event.response_content = "Stored reply"
    resp = await client.post("/v1/chat", json={"message": "stored input"})
    sid = resp.json()["session_id"]

    r = await client.get(f"/v1/history/{sid}")
    contents = [m["content"] for m in r.json()]
    assert "stored input" in contents
    assert "Stored reply" in contents


# ── Multiple turns ─────────────────────────────────────────────────────────────

async def test_history_accumulates_across_turns(client):
    resp1 = await client.post("/v1/chat", json={"message": "turn one"})
    sid = resp1.json()["session_id"]
    await client.post("/v1/chat", json={"message": "turn two", "session_id": sid})

    r = await client.get(f"/v1/history/{sid}")
    user_msgs = [m for m in r.json() if m["role"] == "user"]
    assert len(user_msgs) == 2


# ── Limit parameter ────────────────────────────────────────────────────────────

async def test_history_limit_param_restricts_results(client, history_store, session_store):
    """GET /v1/history/{sid}?limit=1 returns at most 1 message."""
    from datetime import datetime, timezone
    from gateway_edge.models import Message
    sid = uuid4()
    now = datetime.now(timezone.utc)
    session_store[str(sid)] = {
        "session_id": str(sid),
        "created_at": now.isoformat(),
        "last_active": now.isoformat(),
        "message_count": 5,
    }
    history_store[str(sid)] = [
        Message(role="user", content=f"msg {i}") for i in range(5)
    ]

    r = await client.get(f"/v1/history/{sid}?limit=1")
    assert len(r.json()) == 1


async def test_history_default_limit_is_fifty(client, history_store, session_store):
    from datetime import datetime, timezone
    from gateway_edge.models import Message
    sid = uuid4()
    now = datetime.now(timezone.utc)
    session_store[str(sid)] = {
        "session_id": str(sid),
        "created_at": now.isoformat(),
        "last_active": now.isoformat(),
        "message_count": 60,
    }
    history_store[str(sid)] = [
        Message(role="user", content=f"msg {i}") for i in range(60)
    ]

    r = await client.get(f"/v1/history/{sid}")
    assert len(r.json()) == 50
