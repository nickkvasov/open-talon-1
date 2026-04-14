from __future__ import annotations

from uuid import uuid4

from gateway_edge.models import AuthContext
from gateway_edge.config import settings


def _oidc_context() -> AuthContext:
    return AuthContext(
        kind="oidc",
        user_id=uuid4(),
        issuer="http://issuer.test/realms/open-talon",
        subject="subject-123",
        email="nikolay@example.com",
        display_name="Nikolay",
        roles=["admin"],
        claims={"sub": "subject-123"},
    )


async def test_oidc_mode_returns_me_identity(client, monkeypatch):
    auth_context = _oidc_context()
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    response = await client.get(
        "/v1/me",
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == str(auth_context.user_id)
    assert response.json()["display_name"] == "Nikolay"


async def test_oidc_create_workspace_ignores_forged_actor_identity(client, monkeypatch):
    auth_context = _oidc_context()
    forged_actor = {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Forged",
    }
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    response = await client.post(
        "/v1/workspaces",
        headers={"Authorization": "Bearer good-token"},
        json={"name": "OIDC Workspace", "actor": forged_actor},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["participants"][0]["participant_id"] != forged_actor["participant_id"]
    assert body["participants"][0]["user_id"] == str(auth_context.user_id)
    assert body["participants"][0]["display_name"] == auth_context.display_name
    assert body["workspace"]["owner_user_id"] == str(auth_context.user_id)
    assert body["participants"][0]["roles"] == ["admin"]


def test_oidc_websocket_uses_authenticated_user_without_query_identity(sync_client, monkeypatch):
    auth_context = _oidc_context()
    forged_actor = {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Forged",
    }
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)
    monkeypatch.setattr("gateway_edge.routers.collaboration.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.routers.collaboration.sync_oidc_auth_context", _sync)

    workspace_resp = sync_client.post(
        "/v1/workspaces",
        headers={"Authorization": "Bearer good-token"},
        json={"name": "Realtime", "actor": forged_actor},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]
    thread_resp = sync_client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        headers={"Authorization": "Bearer good-token"},
        json={"title": "Presence", "actor": forged_actor},
    )
    thread_id = thread_resp.json()["thread"]["thread_id"]
    expected_participant_id = thread_resp.json()["memberships"][0]["participant_id"]

    with sync_client.websocket_connect(
        f"/v1/threads/{thread_id}/ws?after_sequence=0",
        headers={"Authorization": "Bearer good-token"},
    ) as websocket:
        event = websocket.receive_json()

    assert event["event_type"] == "presence.updated"
    assert event["payload"]["participant_id"] == expected_participant_id
