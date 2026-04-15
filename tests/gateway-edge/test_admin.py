"""
Tests for /v1/admin/api-keys (create, list, revoke).
The underlying Valkey storage is replaced with an in-memory dict via monkeypatch.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from gateway_edge.config import settings
from gateway_edge.models import AuthContext


def _oidc_context(*, roles: list[str]) -> AuthContext:
    return AuthContext(
        kind="oidc",
        user_id=uuid4(),
        issuer="http://issuer.test/realms/open-talon",
        subject="subject-123",
        email="nikolay@example.com",
        display_name="Nikolay",
        roles=roles,
        claims={"sub": "subject-123"},
    )


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


async def test_runtime_overview_returns_runtime_queue_and_token_totals(
    client,
    mock_collaboration_service,
):
    async def fake_overview():
        workspace_id = uuid4()
        return {
            "tasks": {"pending": 2, "claimed": 1},
            "run_steps": {"pending": 3, "claimed": 1},
            "tool_calls": {"pending": 4, "claimed": 2},
            "failed_last_24h": {"tasks": 1, "run_steps": 2, "tool_calls": 3},
            "oldest_pending_age_seconds": {"run_steps": 45, "tool_calls": 90},
            "token_totals": {
                "global_total_tokens": 144,
                "by_workspace": [
                    {"workspace_id": workspace_id, "total_tokens": 120}
                ],
            },
        }

    mock_collaboration_service.get_runtime_overview = fake_overview

    response = await client.get("/v1/admin/runtime/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["tasks"] == {"pending": 2, "claimed": 1}
    assert body["failed_last_24h"] == {"tasks": 1, "run_steps": 2, "tool_calls": 3}
    assert body["token_totals"]["global_total_tokens"] == 144
    assert body["token_totals"]["by_workspace"][0]["total_tokens"] == 120


async def test_runtime_overview_requires_admin_role_in_oidc_mode(client, monkeypatch):
    auth_context = _oidc_context(roles=["workspace-user"])
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    response = await client.get(
        "/v1/admin/runtime/overview",
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


async def test_runtime_overview_allows_admin_role_in_oidc_mode(client, monkeypatch):
    auth_context = _oidc_context(roles=["admin"])
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    response = await client.get(
        "/v1/admin/runtime/overview",
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200


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
