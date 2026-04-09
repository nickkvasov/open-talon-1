"""
Tests for session management endpoints:
  GET    /v1/sessions/{session_id}
  DELETE /v1/sessions/{session_id}
"""
from __future__ import annotations

from uuid import uuid4

import pytest


# ── GET /v1/sessions/{session_id} ─────────────────────────────────────────────

async def test_get_session_of_existing_session(client):
    # Create a session via chat
    resp = await client.post("/v1/chat", json={"message": "hi"})
    sid = resp.json()["session_id"]

    r = await client.get(f"/v1/sessions/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == sid


async def test_get_session_returns_correct_fields(client):
    resp = await client.post("/v1/chat", json={"message": "hi"})
    sid = resp.json()["session_id"]

    r = await client.get(f"/v1/sessions/{sid}")
    body = r.json()
    assert "session_id" in body
    assert "created_at" in body
    assert "last_active" in body
    assert "message_count" in body


async def test_get_session_message_count_increments(client):
    resp1 = await client.post("/v1/chat", json={"message": "first"})
    sid = resp1.json()["session_id"]
    await client.post("/v1/chat", json={"message": "second", "session_id": sid})

    r = await client.get(f"/v1/sessions/{sid}")
    assert r.json()["message_count"] == 2


async def test_get_session_unknown_returns_404(client):
    r = await client.get(f"/v1/sessions/{uuid4()}")
    assert r.status_code == 404


# ── DELETE /v1/sessions/{session_id} ──────────────────────────────────────────

async def test_delete_session_returns_deleted_true(client):
    resp = await client.post("/v1/chat", json={"message": "delete me"})
    sid = resp.json()["session_id"]

    r = await client.delete(f"/v1/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    assert r.json()["session_id"] == sid


async def test_delete_session_removes_it_from_store(client, session_store):
    resp = await client.post("/v1/chat", json={"message": "bye"})
    sid = resp.json()["session_id"]

    await client.delete(f"/v1/sessions/{sid}")
    assert sid not in session_store


async def test_delete_session_clears_history(client, history_store):
    resp = await client.post("/v1/chat", json={"message": "remember me"})
    sid = resp.json()["session_id"]
    assert history_store.get(sid)  # history was written

    await client.delete(f"/v1/sessions/{sid}")
    assert not history_store.get(sid)


async def test_delete_session_unknown_returns_404(client):
    r = await client.delete(f"/v1/sessions/{uuid4()}")
    assert r.status_code == 404


async def test_deleted_session_cannot_be_fetched(client):
    resp = await client.post("/v1/chat", json={"message": "bye"})
    sid = resp.json()["session_id"]

    await client.delete(f"/v1/sessions/{sid}")
    r = await client.get(f"/v1/sessions/{sid}")
    assert r.status_code == 404
