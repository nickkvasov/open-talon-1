from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from gateway_edge.config import settings
from gateway_edge.models import (
    AuthContext,
    GeneratedToolManifest,
    ParticipantProfile,
    Thread,
    ToolExecutionBinding,
    ToolGenerationRequest,
    ToolGenerationRequestDetail,
    ToolGenerationRevision,
    Workspace,
)


def _oidc_context(*, roles: list[str], user_id=None) -> AuthContext:
    return AuthContext(
        kind="oidc",
        user_id=user_id or uuid4(),
        issuer="http://issuer.test/realms/open-talon",
        subject="subject-123",
        email="nikolay@example.com",
        display_name="Nikolay",
        roles=roles,
        claims={"sub": "subject-123"},
    )


def _patch_oidc_tokens(monkeypatch, token_map: dict[str, AuthContext]) -> None:
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        return token_map.get(token)

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)


def _seed_tool_generation_request(
    mock_collaboration_service,
    *,
    user_id,
    requested_scope: str = "global",
):
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    participant_id = uuid4()
    request_id = uuid4()
    revision_id = uuid4()
    mock_collaboration_service.workspaces[str(workspace_id)] = Workspace(
        workspace_id=workspace_id,
        organization_id=mock_collaboration_service.default_organization.organization_id,
        name="Tooling",
        created_at=now,
        updated_at=now,
    )
    mock_collaboration_service.participants[str(workspace_id)] = {
        str(participant_id): ParticipantProfile(
            participant_id=participant_id,
            workspace_id=workspace_id,
            participant_type="user",
            user_id=user_id,
            display_name="Nikolay",
            roles=["admin"],
            capabilities=["planning"],
            status="active",
            created_at=now,
            updated_at=now,
        )
    }
    mock_collaboration_service.threads[str(thread_id)] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Tool Request",
        created_at=now,
        updated_at=now,
    )
    detail = ToolGenerationRequestDetail(
        request=ToolGenerationRequest(
            request_id=request_id,
            organization_id=mock_collaboration_service.default_organization.organization_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            requester_participant_id=participant_id,
            target_system_agent_id=uuid4(),
            requested_scope=requested_scope,
            status="pending_approval",
            target_tool_name="repo_stats",
            summary="Repository statistics tool",
            latest_revision_id=revision_id,
            created_at=now,
            updated_at=now,
        ),
        revisions=[
            ToolGenerationRevision(
                revision_id=revision_id,
                request_id=request_id,
                revision_number=1,
                status="pending_approval",
                manifest=GeneratedToolManifest(
                    name="repo_stats",
                    description="Repository statistics tool",
                    build_context_path="/tmp/generated-tools/repo_stats",
                    execution=ToolExecutionBinding(
                        backend_kind="docker",
                        handler_ref="registry.example/repo_stats:latest",
                        execution_profile={"network": "none", "workspace_access": "none"},
                    ),
                    network_access="none",
                    workspace_access="none",
                ),
                image_ref="registry.example/repo_stats:latest",
                image_digest="sha256:abcd",
                created_by=participant_id,
                created_at=now,
                updated_at=now,
            )
        ],
    )
    mock_collaboration_service.tool_generation_requests[str(request_id)] = detail
    return detail


async def test_admin_can_list_tool_generation_requests(
    client,
    mock_collaboration_service,
    monkeypatch,
):
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})
    detail = _seed_tool_generation_request(
        mock_collaboration_service,
        user_id=admin.user_id,
    )

    response = await client.get(
        "/v1/tool-generation/requests",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body[0]["request"]["request_id"] == str(detail.request.request_id)


async def test_non_member_thread_tool_generation_reads_return_404(
    client,
    mock_collaboration_service,
    monkeypatch,
):
    member = _oidc_context(roles=["workspace-user"])
    outsider = _oidc_context(roles=["workspace-user"])
    _patch_oidc_tokens(
        monkeypatch,
        {
            "member-token": member,
            "outsider-token": outsider,
        },
    )
    detail = _seed_tool_generation_request(
        mock_collaboration_service,
        user_id=member.user_id,
    )

    response = await client.get(
        f"/v1/threads/{detail.request.thread_id}/tool-generation/requests",
        headers={"Authorization": "Bearer outsider-token"},
    )

    assert response.status_code == 404


async def test_approve_tool_generation_revision_adds_catalog_tool_only(
    client,
    mock_collaboration_service,
    monkeypatch,
    actor_payload,
):
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})
    detail = _seed_tool_generation_request(
        mock_collaboration_service,
        user_id=admin.user_id,
    )

    response = await client.post(
        f"/v1/tool-generation/revisions/{detail.revisions[0].revision_id}/approve",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "reason": "Validation looks good",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request"]["status"] == "published"
    assert len(mock_collaboration_service.system_tools) == 1
    assert mock_collaboration_service.workspace_tools.get(str(detail.request.workspace_id), {}) == {}


async def test_approve_tool_generation_revision_can_publish_organization_catalog_tool(
    client,
    mock_collaboration_service,
    monkeypatch,
    actor_payload,
):
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})
    detail = _seed_tool_generation_request(
        mock_collaboration_service,
        user_id=admin.user_id,
        requested_scope="organization",
    )

    response = await client.post(
        f"/v1/tool-generation/revisions/{detail.revisions[0].revision_id}/approve",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": actor_payload},
    )

    assert response.status_code == 200
    created_tool = next(iter(mock_collaboration_service.system_tools.values()))
    assert created_tool.scope == "organization"
    assert created_tool.organization_id == detail.request.organization_id


async def test_admin_can_attach_tinker_and_start_fibonacci_tool_request(
    client,
    monkeypatch,
    actor_payload,
):
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    workspace_resp = await client.post(
        "/v1/workspaces",
        headers={"Authorization": "Bearer admin-token"},
        json={"name": "Tooling Lab", "actor": actor_payload},
    )
    assert workspace_resp.status_code == 200
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    thread_resp = await client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        headers={"Authorization": "Bearer admin-token"},
        json={"title": "Fibonacci Tool Request", "actor": actor_payload},
    )
    assert thread_resp.status_code == 200
    thread_id = thread_resp.json()["thread"]["thread_id"]

    agent_resp = await client.post(
        "/v1/agents",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "display_name": "Tinker",
            "description": "Builds tools on demand and submits them for approval.",
            "role": "tool generation agent",
            "capabilities": [
                "tool_generation",
                "tool_validation",
                "tool_catalog",
                "tool_authoring",
            ],
            "endpoint": {"kind": "local", "model": "gemma4:latest"},
            "system_prompt": "Build tools carefully, prefer reuse, and justify trust levels.",
            "definition": {"tool_generation_agent": True},
            "metadata": {"tool_generation_agent": True},
        },
    )
    assert agent_resp.status_code == 200
    tinker_agent_id = agent_resp.json()["agent_id"]

    attach_resp = await client.post(
        f"/v1/workspaces/{workspace_id}/agents",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": actor_payload, "agent_id": tinker_agent_id},
    )
    assert attach_resp.status_code == 200
    assert attach_resp.json()["display_name"] == "Tinker"

    message_resp = await client.post(
        f"/v1/threads/{thread_id}/messages",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "content": "Tinker, please create a Fibonacci calculator tool.",
            "visibility": "workspace",
            "target_system_agent_id": tinker_agent_id,
            "metadata": {"target_tool_name": "fibonacci_calculator"},
        },
    )
    assert message_resp.status_code == 200
    message = message_resp.json()
    assert message["metadata"]["target_system_agent_id"] == tinker_agent_id
    assert "tool_generation_request_id" in message["metadata"]
    assert message["metadata"]["tool_generation_request_status"] == "submitted"

    requests_resp = await client.get(
        f"/v1/threads/{thread_id}/tool-generation/requests",
        headers={"Authorization": "Bearer admin-token"},
    )
    assert requests_resp.status_code == 200
    requests = requests_resp.json()
    assert len(requests) == 1
    assert requests[0]["request"]["target_tool_name"] == "fibonacci_calculator"
    assert requests[0]["request"]["status"] == "submitted"
    assert requests[0]["request"]["requested_scope"] == "global"
    assert requests[0]["request"]["target_system_agent_id"] == tinker_agent_id


async def test_admin_can_request_organization_scoped_tinker_tool(
    client,
    monkeypatch,
    actor_payload,
):
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    workspace_resp = await client.post(
        "/v1/workspaces",
        headers={"Authorization": "Bearer admin-token"},
        json={"name": "Org Tooling Lab", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    thread_resp = await client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        headers={"Authorization": "Bearer admin-token"},
        json={"title": "Org Fibonacci Tool Request", "actor": actor_payload},
    )
    thread_id = thread_resp.json()["thread"]["thread_id"]

    agent_resp = await client.post(
        "/v1/agents",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "display_name": "Tinker",
            "description": "Builds tools on demand and submits them for approval.",
            "role": "tool generation agent",
            "capabilities": ["tool_generation"],
            "endpoint": {"kind": "local", "model": "gemma4:latest"},
            "system_prompt": "Build tools carefully.",
            "definition": {"tool_generation_agent": True},
            "metadata": {"tool_generation_agent": True},
        },
    )
    tinker_agent_id = agent_resp.json()["agent_id"]

    await client.post(
        f"/v1/workspaces/{workspace_id}/agents",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": actor_payload, "agent_id": tinker_agent_id},
    )

    message_resp = await client.post(
        f"/v1/threads/{thread_id}/messages",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "content": "Tinker, please create a Fibonacci calculator tool for this organization.",
            "visibility": "workspace",
            "target_system_agent_id": tinker_agent_id,
            "target_tool_scope": "organization",
            "metadata": {"target_tool_name": "fibonacci_calculator"},
        },
    )

    assert message_resp.status_code == 200
    requests_resp = await client.get(
        f"/v1/threads/{thread_id}/tool-generation/requests",
        headers={"Authorization": "Bearer admin-token"},
    )
    request = requests_resp.json()[0]["request"]
    assert request["requested_scope"] == "organization"
    assert request["organization_id"] == workspace_resp.json()["workspace"]["organization_id"]
