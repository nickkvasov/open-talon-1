"""
Tests for /v1/admin/api-keys (create, list, revoke).
The underlying Valkey storage is replaced with an in-memory dict via monkeypatch.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


# ── POST /v1/admin/api-keys ────────────────────────────────────────────────────

async def test_create_api_key_returns_200(client, _mock_api_key_backend):
    resp = await client.post("/v1/admin/api-keys", json={"label": "my-key"})
    assert resp.status_code == 200


async def test_create_api_key_returns_raw_key(client, _mock_api_key_backend):
    resp = await client.post("/v1/admin/api-keys", json={"label": "my-key"})
    body = resp.json()
    assert "raw_key" in body
    assert isinstance(body["raw_key"], str)
    assert len(body["raw_key"]) > 0


async def test_create_api_key_response_shape(client, _mock_api_key_backend):
    resp = await client.post("/v1/admin/api-keys", json={"label": "test-key"})
    body = resp.json()
    assert "key_id" in body
    assert "label" in body
    assert "created_at" in body


async def test_create_api_key_stores_label(client, _mock_api_key_backend):
    resp = await client.post("/v1/admin/api-keys", json={"label": "prod-bot"})
    assert resp.json()["label"] == "prod-bot"


async def test_create_api_key_with_ttl(client, _mock_api_key_backend):
    resp = await client.post(
        "/v1/admin/api-keys",
        json={"label": "ephemeral", "ttl_seconds": 3600},
    )
    assert resp.status_code == 200


async def test_create_two_keys_have_distinct_ids(client, _mock_api_key_backend):
    r1 = await client.post("/v1/admin/api-keys", json={"label": "a"})
    r2 = await client.post("/v1/admin/api-keys", json={"label": "b"})
    assert r1.json()["key_id"] != r2.json()["key_id"]


async def test_created_key_raw_not_exposed_on_second_request(client, _mock_api_key_backend):
    """raw_key must only appear at creation time — list endpoint must omit it."""
    await client.post("/v1/admin/api-keys", json={"label": "once"})
    r = await client.get("/v1/admin/api-keys")
    for key in r.json():
        assert key.get("raw_key") is None


# ── GET /v1/admin/api-keys ─────────────────────────────────────────────────────

async def test_list_api_keys_returns_list(client, _mock_api_key_backend):
    r = await client.get("/v1/admin/api-keys")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_list_api_keys_contains_created_key(client, _mock_api_key_backend):
    await client.post("/v1/admin/api-keys", json={"label": "listed-key"})
    r = await client.get("/v1/admin/api-keys")
    labels = [k["label"] for k in r.json()]
    assert "listed-key" in labels


async def test_list_api_keys_grows_on_creation(client, _mock_api_key_backend):
    r0 = await client.get("/v1/admin/api-keys")
    count0 = len(r0.json())
    await client.post("/v1/admin/api-keys", json={"label": "new"})
    r1 = await client.get("/v1/admin/api-keys")
    assert len(r1.json()) == count0 + 1


# ── DELETE /v1/admin/api-keys/{key_id} ────────────────────────────────────────

async def test_revoke_api_key_returns_deleted_true(client, _mock_api_key_backend):
    r_create = await client.post("/v1/admin/api-keys", json={"label": "to-delete"})
    key_id = r_create.json()["key_id"]

    r_del = await client.delete(f"/v1/admin/api-keys/{key_id}")
    assert r_del.status_code == 200
    assert r_del.json()["deleted"] is True


async def test_revoke_unknown_key_returns_deleted_false(client, _mock_api_key_backend):
    r = await client.delete(f"/v1/admin/api-keys/{uuid4()}")
    assert r.status_code == 200
    assert r.json()["deleted"] is False


async def test_revoke_removes_key_from_list(client, _mock_api_key_backend):
    r_create = await client.post("/v1/admin/api-keys", json={"label": "gone"})
    key_id = r_create.json()["key_id"]

    await client.delete(f"/v1/admin/api-keys/{key_id}")
    r_list = await client.get("/v1/admin/api-keys")
    key_ids = [k["key_id"] for k in r_list.json()]
    assert key_id not in key_ids


# ── Fixture: in-memory API key backend ───────────────────────────────────────

@pytest.fixture
def _mock_api_key_backend(monkeypatch):
    """Replace Valkey-backed api_key functions with in-memory equivalents."""
    from gateway_edge.models import ApiKeyInfo
    import secrets, hashlib
    from uuid import uuid4
    _store: dict[str, dict] = {}

    async def _create(payload):
        key_id = str(uuid4())
        raw_key = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        _store[key_id] = {
            "key_id": key_id,
            "label": payload.label,
            "key_hash": hashlib.sha256(raw_key.encode()).hexdigest(),
            "created_at": now,
            "expires_at": None,
        }
        return ApiKeyInfo(key_id=key_id, label=payload.label, created_at=now, raw_key=raw_key)

    async def _list():
        return [
            ApiKeyInfo(
                key_id=v["key_id"],
                label=v["label"],
                created_at=v["created_at"],
            )
            for v in _store.values()
        ]

    async def _revoke(key_id: str) -> bool:
        return bool(_store.pop(key_id, None))

    monkeypatch.setattr("gateway_edge.auth.api_key.create_api_key", _create)
    monkeypatch.setattr("gateway_edge.auth.api_key.list_api_keys",  _list)
    monkeypatch.setattr("gateway_edge.auth.api_key.revoke_api_key", _revoke)
    monkeypatch.setattr("gateway_edge.routers.admin.create_api_key", _create)
    monkeypatch.setattr("gateway_edge.routers.admin.list_api_keys",  _list)
    monkeypatch.setattr("gateway_edge.routers.admin.revoke_api_key", _revoke)
    return _store
