from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from gateway_edge.config import settings
from gateway_edge.models import AuditEvent, AuthContext


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


def _audit_event(*, workspace_id=None) -> AuditEvent:
    return AuditEvent(
        audit_event_id=uuid4(),
        ledger_offset=1,
        occurred_at=datetime.now(timezone.utc),
        recorded_at=datetime.now(timezone.utc),
        scope_type="workspace" if workspace_id is not None else "global",
        workspace_id=workspace_id,
        thread_id=None,
        actor_type="user",
        actor_id=uuid4(),
        user_id=uuid4(),
        system_agent_id=None,
        source_service="gateway-edge",
        source_component="http-middleware",
        action_category="api",
        action_name="api.request.completed",
        target_type="workspace" if workspace_id is not None else None,
        target_id=workspace_id,
        outcome="success",
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        trace_id=None,
        error_code=None,
        error_class=None,
        error_message_redacted=None,
        payload_mode="metadata_only",
        payload_hash=None,
        payload_ref=None,
        payload_size_bytes=None,
        metadata={},
        chain_partition=f"workspace:{workspace_id}" if workspace_id is not None else "global",
        chain_sequence=1,
        prev_hash="0" * 64,
        event_hash="1" * 64,
    )


async def test_boundary_audit_records_successful_request(client, mock_audit_service):
    response = await client.get("/v1/workspaces")

    assert response.status_code == 200
    assert mock_audit_service.http_records[-1]["path"] == "/v1/workspaces"
    assert mock_audit_service.http_records[-1]["status_code"] == 200
    assert mock_audit_service.http_records[-1]["request_id"] is not None


async def test_boundary_audit_records_unauthorized_request(client, monkeypatch, mock_audit_service):
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "bad-token"
        return None

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)

    response = await client.get(
        "/v1/me",
        headers={"Authorization": "Bearer bad-token"},
    )

    assert response.status_code == 401
    assert mock_audit_service.http_records[-1]["path"] == "/v1/me"
    assert mock_audit_service.http_records[-1]["status_code"] == 401


async def test_boundary_audit_records_forbidden_request(client, monkeypatch, mock_audit_service):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    auth_context = _oidc_context(roles=["workspace-user"])

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    response = await client.get(
        "/v1/admin/api-keys",
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 403
    assert mock_audit_service.http_records[-1]["path"] == "/v1/admin/api-keys"
    assert mock_audit_service.http_records[-1]["status_code"] == 403


async def test_global_audit_list_requires_admin(client, monkeypatch, mock_audit_service):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    auth_context = _oidc_context(roles=["workspace-user"])
    mock_audit_service.events.append(_audit_event())

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    response = await client.get(
        "/v1/audit/events",
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 403


async def test_workspace_admin_can_list_workspace_audit_events(client, monkeypatch, mock_audit_service):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    auth_context = _oidc_context(roles=["workspace-user"])

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    workspace_response = await client.post(
        "/v1/workspaces",
        headers={"Authorization": "Bearer good-token"},
        json={
            "name": "Audit Workspace",
            "actor": {
                "participant_id": str(uuid4()),
                "participant_type": "user",
                "display_name": "Forged",
            },
        },
    )
    assert workspace_response.status_code == 200
    workspace_id = workspace_response.json()["workspace"]["workspace_id"]
    mock_audit_service.events.append(_audit_event(workspace_id=workspace_response.json()["workspace"]["workspace_id"]))

    response = await client.get(
        f"/v1/audit/events?workspace_id={workspace_id}",
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["events"][0]["workspace_id"] == workspace_id


async def test_workspace_audit_export_requires_workspace_admin_or_supervisor(
    client, monkeypatch, mock_collaboration_service
):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    auth_context = _oidc_context(roles=["workspace-user"])

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    workspace_response = await client.post(
        "/v1/workspaces",
        headers={"Authorization": "Bearer good-token"},
        json={
            "name": "Workspace Audit Export",
            "actor": {
                "participant_id": str(uuid4()),
                "participant_type": "user",
                "display_name": "Forged",
            },
        },
    )
    workspace_id = workspace_response.json()["workspace"]["workspace_id"]

    second_context = _oidc_context(roles=["workspace-user"])
    second_participant_id = uuid4()

    from gateway_edge.models import ParticipantProfile

    mock_collaboration_service.participants[str(workspace_id)][str(second_participant_id)] = (
        ParticipantProfile(
            participant_id=second_participant_id,
            workspace_id=workspace_id,
            participant_type="user",
            user_id=second_context.user_id,
            display_name=second_context.display_name or "other-user",
            roles=["user"],
            capabilities=[],
            visibility_scope="workspace",
        )
    )

    async def _validate_second(token: str):
        assert token == "other-token"
        return second_context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate_second)

    response = await client.post(
        "/v1/audit/events/export",
        headers={"Authorization": "Bearer other-token"},
        json={"workspace_id": workspace_id, "limit": 10},
    )

    assert response.status_code == 403


def test_websocket_audit_records_connect(sync_client, mock_audit_service):
    actor = {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Audit User",
    }
    workspace_response = sync_client.post(
        "/v1/workspaces",
        json={"name": "WS Audit", "actor": actor},
    )
    workspace_id = workspace_response.json()["workspace"]["workspace_id"]
    thread_response = sync_client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        json={"title": "WS Audit Thread", "actor": actor},
    )
    thread_id = thread_response.json()["thread"]["thread_id"]

    with sync_client.websocket_connect(
        f"/v1/threads/{thread_id}/ws"
        f"?participant_id={actor['participant_id']}"
        f"&display_name={actor['display_name']}"
        f"&participant_type=user"
    ) as websocket:
        websocket.receive_json()

    action_names = [record["action_name"] for record in mock_audit_service.websocket_records]
    assert "api.websocket.connected" in action_names


def test_websocket_audit_records_missing_identity_failure(sync_client, mock_audit_service):
    actor = {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Audit User",
    }
    workspace_response = sync_client.post(
        "/v1/workspaces",
        json={"name": "WS Audit Failure", "actor": actor},
    )
    workspace_id = workspace_response.json()["workspace"]["workspace_id"]
    thread_response = sync_client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        json={"title": "WS Audit Failure Thread", "actor": actor},
    )
    thread_id = thread_response.json()["thread"]["thread_id"]

    with pytest.raises(Exception) as exc_info:
        with sync_client.websocket_connect(f"/v1/threads/{thread_id}/ws"):
            pass

    assert getattr(exc_info.value, "code", None) == 4002
    action_names = [record["action_name"] for record in mock_audit_service.websocket_records]
    assert "api.websocket.failed" in action_names
