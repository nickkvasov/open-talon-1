from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from gateway_edge.config import settings
from gateway_edge.models import (
    AuthContext,
    IamRoleDefinition,
    ParticipantProfile,
    SystemPluginCapabilityDefinition,
    SystemPluginDefinition,
    SystemPluginSyncJob,
    SystemPluginSyncResult,
    WorkspacePluginPrompt,
    WorkspacePluginResource,
    WorkspacePluginTool,
    WorkspaceSystemPlugin,
)


def _oidc_context(*, roles: list[str]) -> AuthContext:
    return AuthContext(
        kind="oidc",
        user_id=uuid4(),
        issuer="http://issuer.test/realms/open-talon",
        subject="subject-123",
        email="plugin-admin@example.com",
        display_name="Plugin Admin",
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


def _grant_workspace_permissions(
    mock_collaboration_service,
    *,
    user_id: UUID,
    organization_id: UUID,
    permissions: list[str],
    name: str,
) -> None:
    now = datetime.now(timezone.utc)
    role = IamRoleDefinition(
        role_id=uuid4(),
        scope="organization",
        subject_kind="human",
        organization_id=organization_id,
        name=name,
        description="Test-only plugin workspace role.",
        permissions=permissions,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    mock_collaboration_service.iam_roles[str(role.role_id)] = role
    mock_collaboration_service.human_role_bindings.setdefault(str(user_id), set()).add(
        str(role.role_id)
    )


def _plugin_definition(plugin_id: UUID, actor_id: UUID) -> SystemPluginDefinition:
    now = datetime.now(timezone.utc)
    return SystemPluginDefinition(
        plugin_id=plugin_id,
        scope="global",
        organization_id=None,
        plugin_key="web_search",
        display_name="Web Search",
        description="Managed web search plugin.",
        backing_protocol="mcp",
        backing_server_id=plugin_id,
        transport_kind="streamable_http",
        config={"url": "http://127.0.0.1:8095/mcp"},
        trust_level="sandboxed",
        enabled=True,
        created_by=actor_id,
        created_at=now,
        updated_by=actor_id,
        updated_at=now,
        metadata={},
    )


async def test_system_plugin_routes_expose_plugin_contract(
    client,
    actor_payload,
    mock_collaboration_service,
):
    plugin_id = uuid4()
    actor_id = UUID(actor_payload["participant_id"])
    captured_payloads = {}

    async def create_system_plugin(payload, *, scope="global", organization_id=None):
        captured_payloads["create"] = payload
        captured_payloads["scope"] = scope
        captured_payloads["organization_id"] = organization_id
        return _plugin_definition(plugin_id, actor_id)

    async def get_system_plugin(requested_plugin_id):
        assert requested_plugin_id == plugin_id
        return _plugin_definition(plugin_id, actor_id)

    async def list_system_plugins(*, scope="global", organization_id=None):
        captured_payloads["list_scope"] = scope
        captured_payloads["list_organization_id"] = organization_id
        return [_plugin_definition(plugin_id, actor_id)]

    async def list_system_plugin_tools(requested_plugin_id):
        assert requested_plugin_id == plugin_id
        return [
            SystemPluginCapabilityDefinition(
                plugin_id=plugin_id,
                plugin_key="web_search",
                kind="tool",
                name="search",
                remote_name="search",
                display_name="Search",
                description="Search the web.",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                capability_hash="abc123",
                metadata={},
            )
        ]

    mock_collaboration_service.create_system_plugin = create_system_plugin
    mock_collaboration_service.get_system_plugin = get_system_plugin
    mock_collaboration_service.list_system_plugins = list_system_plugins
    mock_collaboration_service.list_system_plugin_tools = list_system_plugin_tools

    create_response = await client.post(
        "/v1/system-plugins",
        json={
            "actor": actor_payload,
            "plugin_key": "web_search",
            "display_name": "Web Search",
            "description": "Managed web search plugin.",
            "transport_kind": "streamable_http",
            "config": {"url": "http://127.0.0.1:8095/mcp"},
        },
    )
    list_response = await client.get("/v1/system-plugins")
    tools_response = await client.get(f"/v1/system-plugins/{plugin_id}/tools")

    assert create_response.status_code == 200
    create_body = create_response.json()
    assert create_body["plugin_id"] == str(plugin_id)
    assert create_body["plugin_key"] == "web_search"
    assert create_body["backing_protocol"] == "mcp"
    assert create_body["backing_server_id"] == str(plugin_id)
    assert "server_id" not in create_body
    assert "server_key" not in create_body
    assert captured_payloads["create"].plugin_key == "web_search"

    assert list_response.status_code == 200
    assert list_response.json()[0]["plugin_key"] == "web_search"
    assert "server_key" not in list_response.json()[0]

    assert tools_response.status_code == 200
    tool_body = tools_response.json()[0]
    assert tool_body["kind"] == "tool"
    assert tool_body["plugin_id"] == str(plugin_id)
    assert tool_body["plugin_key"] == "web_search"
    assert tool_body["name"] == "search"
    assert "server_id" not in tool_body


async def test_system_plugin_sync_routes_expose_plugin_contract(
    client,
    actor_payload,
    mock_collaboration_service,
):
    plugin_id = uuid4()
    actor_id = UUID(actor_payload["participant_id"])
    now = datetime.now(timezone.utc)
    captured_payloads = {}

    async def get_system_plugin(requested_plugin_id):
        assert requested_plugin_id == plugin_id
        return _plugin_definition(plugin_id, actor_id)

    async def request_system_plugin_sync(requested_plugin_id, payload):
        assert requested_plugin_id == plugin_id
        captured_payloads["sync"] = payload
        return SystemPluginSyncResult(
            plugin=_plugin_definition(plugin_id, actor_id).model_copy(
                update={"last_sync_status": "queued"}
            ),
            job=SystemPluginSyncJob(
                job_id=uuid4(),
                plugin_id=plugin_id,
                backing_protocol="mcp",
                backing_server_id=plugin_id,
                status="created",
                requested_by=actor_id,
                requested_at=now,
                created_at=now,
                updated_at=now,
                metadata=payload.metadata,
            ),
        )

    async def list_system_plugin_sync_jobs(requested_plugin_id, *, limit=20):
        assert requested_plugin_id == plugin_id
        captured_payloads["sync_limit"] = limit
        return [
            SystemPluginSyncJob(
                job_id=uuid4(),
                plugin_id=plugin_id,
                backing_protocol="mcp",
                backing_server_id=plugin_id,
                status="completed",
                requested_by=actor_id,
                requested_at=now,
                result={"tool_count": 3},
                created_at=now,
                updated_at=now,
                metadata={"source": "route-test"},
            )
        ]

    mock_collaboration_service.get_system_plugin = get_system_plugin
    mock_collaboration_service.request_system_plugin_sync = request_system_plugin_sync
    mock_collaboration_service.list_system_plugin_sync_jobs = list_system_plugin_sync_jobs

    sync_response = await client.post(
        f"/v1/system-plugins/{plugin_id}/sync",
        json={
            "actor": actor_payload,
            "metadata": {"source": "admin-web"},
        },
    )
    jobs_response = await client.get(f"/v1/system-plugins/{plugin_id}/sync-jobs?limit=5")

    assert sync_response.status_code == 200
    sync_body = sync_response.json()
    assert sync_body["plugin"]["plugin_id"] == str(plugin_id)
    assert sync_body["plugin"]["plugin_key"] == "web_search"
    assert sync_body["job"]["plugin_id"] == str(plugin_id)
    assert sync_body["job"]["backing_server_id"] == str(plugin_id)
    assert sync_body["job"]["metadata"] == {"source": "admin-web"}
    assert "server" not in sync_body
    assert "server_id" not in sync_body["job"]
    assert captured_payloads["sync"].metadata == {"source": "admin-web"}

    assert jobs_response.status_code == 200
    job_body = jobs_response.json()[0]
    assert job_body["plugin_id"] == str(plugin_id)
    assert job_body["result"] == {"tool_count": 3}
    assert "server_id" not in job_body
    assert captured_payloads["sync_limit"] == 5


async def test_system_plugin_update_delete_and_org_routes_use_plugin_payloads(
    client,
    actor_payload,
    mock_collaboration_service,
):
    plugin_id = uuid4()
    organization_id = uuid4()
    actor_id = UUID(actor_payload["participant_id"])
    captured_payloads = {}

    def _org_plugin() -> SystemPluginDefinition:
        return _plugin_definition(plugin_id, actor_id).model_copy(
            update={
                "scope": "organization",
                "organization_id": organization_id,
                "plugin_key": "org_web_search",
            }
        )

    async def get_system_plugin(requested_plugin_id):
        assert requested_plugin_id == plugin_id
        return _org_plugin()

    async def update_system_plugin(requested_plugin_id, payload):
        assert requested_plugin_id == plugin_id
        captured_payloads["update"] = payload
        return _org_plugin().model_copy(update={"plugin_key": payload.plugin_key})

    async def delete_system_plugin(requested_plugin_id, payload):
        assert requested_plugin_id == plugin_id
        captured_payloads["delete"] = payload
        return {"deleted": True, "plugin_id": str(requested_plugin_id)}

    async def list_system_plugins(*, scope="global", organization_id=None):
        captured_payloads["list_scope"] = scope
        captured_payloads["list_organization_id"] = organization_id
        return [_org_plugin()]

    mock_collaboration_service.get_system_plugin = get_system_plugin
    mock_collaboration_service.update_system_plugin = update_system_plugin
    mock_collaboration_service.delete_system_plugin = delete_system_plugin
    mock_collaboration_service.list_system_plugins = list_system_plugins

    list_response = await client.get(f"/v1/organizations/{organization_id}/system-plugins")
    update_response = await client.patch(
        f"/v1/organizations/{organization_id}/system-plugins/{plugin_id}",
        json={
            "actor": actor_payload,
            "plugin_key": "org_web_search_v2",
        },
    )
    delete_response = await client.request(
        "DELETE",
        f"/v1/organizations/{organization_id}/system-plugins/{plugin_id}",
        json={"actor": actor_payload},
    )

    assert list_response.status_code == 200
    assert list_response.json()[0]["plugin_key"] == "org_web_search"
    assert "server_key" not in list_response.json()[0]
    assert captured_payloads["list_scope"] == "organization"
    assert captured_payloads["list_organization_id"] == organization_id

    assert update_response.status_code == 200
    assert update_response.json()["plugin_key"] == "org_web_search_v2"
    assert captured_payloads["update"].plugin_key == "org_web_search_v2"
    assert "server_key" not in update_response.json()

    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "plugin_id": str(plugin_id)}
    assert captured_payloads["delete"].actor.participant_id == actor_id


async def test_workspace_system_plugin_routes_expose_plugin_contract(
    client,
    actor_payload,
    mock_collaboration_service,
):
    plugin_id = uuid4()
    workspace_id = uuid4()
    actor_id = UUID(actor_payload["participant_id"])
    captured_payloads = {}

    async def list_workspace_system_plugins(requested_workspace_id):
        assert requested_workspace_id == workspace_id
        return [
            WorkspaceSystemPlugin(
                plugin_id=plugin_id,
                plugin_key="web_search",
                display_name="Web Search",
                description="Managed web search plugin.",
                backing_protocol="mcp",
                backing_server_id=plugin_id,
                transport_kind="streamable_http",
                trust_level="sandboxed",
                plugin_enabled=True,
                enabled=True,
                tools_enabled=True,
                resources_enabled=False,
                prompts_enabled=False,
                sampling_enabled=False,
                name_prefix="web_",
                attached_by=actor_id,
                metadata={},
            )
        ]

    async def list_workspace_plugin_tools(requested_workspace_id):
        assert requested_workspace_id == workspace_id
        return [
            WorkspacePluginTool(
                plugin_id=plugin_id,
                plugin_key="web_search",
                plugin_display_name="Web Search",
                exposed_name="web_search",
                remote_name="search",
                description="Search the web.",
                enabled=True,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                metadata={"workspace_attachment": {"name_prefix": "web_"}},
            )
        ]

    async def list_workspace_plugin_resources(requested_workspace_id):
        assert requested_workspace_id == workspace_id
        return [
            WorkspacePluginResource(
                plugin_id=plugin_id,
                plugin_key="web_search",
                plugin_display_name="Web Search",
                exposed_name="web_recent",
                remote_name="recent",
                uri="ot://web-search/recent",
                description="Recent search state.",
                mime_type="application/json",
                metadata={"workspace_attachment": {"name_prefix": "web_"}},
            )
        ]

    async def list_workspace_plugin_prompts(requested_workspace_id):
        assert requested_workspace_id == workspace_id
        return [
            WorkspacePluginPrompt(
                plugin_id=plugin_id,
                plugin_key="web_search",
                plugin_display_name="Web Search",
                exposed_name="web_summarize",
                remote_name="summarize",
                description="Summarize web-search output.",
                arguments_schema={"type": "object"},
                metadata={"workspace_attachment": {"name_prefix": "web_"}},
            )
        ]

    async def attach_workspace_system_plugin(requested_workspace_id, payload):
        assert requested_workspace_id == workspace_id
        captured_payloads["attach"] = payload
        return (await list_workspace_system_plugins(workspace_id))[0]

    async def update_workspace_system_plugin(requested_workspace_id, requested_plugin_id, payload):
        assert requested_workspace_id == workspace_id
        assert requested_plugin_id == plugin_id
        captured_payloads["update"] = payload
        return (await list_workspace_system_plugins(workspace_id))[0].model_copy(
            update={"enabled": payload.enabled}
        )

    async def delete_workspace_system_plugin(requested_workspace_id, requested_plugin_id, payload):
        assert requested_workspace_id == workspace_id
        assert requested_plugin_id == plugin_id
        captured_payloads["delete"] = payload
        return {"deleted": True, "plugin_id": str(plugin_id)}

    mock_collaboration_service.list_workspace_system_plugins = list_workspace_system_plugins
    mock_collaboration_service.list_workspace_plugin_tools = list_workspace_plugin_tools
    mock_collaboration_service.list_workspace_plugin_resources = list_workspace_plugin_resources
    mock_collaboration_service.list_workspace_plugin_prompts = list_workspace_plugin_prompts
    mock_collaboration_service.attach_workspace_system_plugin = attach_workspace_system_plugin
    mock_collaboration_service.update_workspace_system_plugin = update_workspace_system_plugin
    mock_collaboration_service.delete_workspace_system_plugin = delete_workspace_system_plugin

    list_response = await client.get(f"/v1/workspaces/{workspace_id}/system-plugins")
    tools_response = await client.get(f"/v1/workspaces/{workspace_id}/plugin-capabilities/tools")
    resources_response = await client.get(
        f"/v1/workspaces/{workspace_id}/plugin-capabilities/resources"
    )
    prompts_response = await client.get(
        f"/v1/workspaces/{workspace_id}/plugin-capabilities/prompts"
    )
    attach_response = await client.put(
        f"/v1/workspaces/{workspace_id}/system-plugins/{plugin_id}",
        json={
            "actor": actor_payload,
            "enabled": True,
            "tools_enabled": True,
            "name_prefix": "web_",
            "metadata": {},
        },
    )
    update_response = await client.patch(
        f"/v1/workspaces/{workspace_id}/system-plugins/{plugin_id}",
        json={
            "actor": actor_payload,
            "enabled": False,
        },
    )
    delete_response = await client.request(
        "DELETE",
        f"/v1/workspaces/{workspace_id}/system-plugins/{plugin_id}",
        json={"actor": actor_payload},
    )

    assert list_response.status_code == 200
    attachment_body = list_response.json()[0]
    assert attachment_body["plugin_id"] == str(plugin_id)
    assert attachment_body["plugin_key"] == "web_search"
    assert attachment_body["plugin_enabled"] is True
    assert "server_id" not in attachment_body
    assert "server_key" not in attachment_body

    assert tools_response.status_code == 200
    tool_body = tools_response.json()[0]
    assert tool_body["kind"] == "tool"
    assert tool_body["plugin_display_name"] == "Web Search"
    assert "server_display_name" not in tool_body

    assert resources_response.status_code == 200
    resource_body = resources_response.json()[0]
    assert resource_body["kind"] == "resource"
    assert resource_body["uri"] == "ot://web-search/recent"
    assert "server_display_name" not in resource_body

    assert prompts_response.status_code == 200
    prompt_body = prompts_response.json()[0]
    assert prompt_body["kind"] == "prompt"
    assert prompt_body["arguments_schema"] == {"type": "object"}
    assert "server_display_name" not in prompt_body

    assert attach_response.status_code == 200
    assert captured_payloads["attach"].plugin_id == plugin_id
    assert update_response.status_code == 200
    assert update_response.json()["enabled"] is False
    assert captured_payloads["update"].enabled is False
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True, "plugin_id": str(plugin_id)}
    assert captured_payloads["delete"].actor.participant_id == actor_id


async def test_workspace_system_plugin_asset_persistence_requires_publish_permission(
    client,
    actor_payload,
    mock_collaboration_service,
    monkeypatch,
):
    owner_context = _oidc_context(roles=["workspace-user"])
    outsider_context = _oidc_context(roles=["workspace-user"])
    _patch_oidc_tokens(
        monkeypatch,
        {
            "owner-token": owner_context,
            "outsider-token": outsider_context,
        },
    )

    workspace_response = await client.post(
        "/v1/workspaces",
        headers={"Authorization": "Bearer owner-token"},
        json={"name": "Plugin Permissions", "actor": actor_payload},
    )
    assert workspace_response.status_code == 200
    workspace_id = UUID(workspace_response.json()["workspace"]["workspace_id"])
    organization_id = UUID(workspace_response.json()["workspace"]["organization_id"])
    plugin_id = uuid4()
    attach_calls: list[object] = []

    _grant_workspace_permissions(
        mock_collaboration_service,
        user_id=owner_context.user_id,
        organization_id=organization_id,
        permissions=["workspace.mcp_servers.write"],
        name="plugin-attacher",
    )

    async def attach_workspace_system_plugin(requested_workspace_id, payload):
        assert requested_workspace_id == workspace_id
        attach_calls.append(payload)
        return WorkspaceSystemPlugin(
            plugin_id=plugin_id,
            plugin_key="web_search",
            display_name="Web Search",
            description="Managed web search plugin.",
            backing_server_id=plugin_id,
            attached_by=payload.actor.participant_id,
            metadata=payload.metadata,
        )

    mock_collaboration_service.attach_workspace_system_plugin = attach_workspace_system_plugin

    denied_response = await client.put(
        f"/v1/workspaces/{workspace_id}/system-plugins/{plugin_id}",
        headers={"Authorization": "Bearer owner-token"},
        json={
            "actor": actor_payload,
            "enabled": True,
            "tools_enabled": True,
            "metadata": {"asset_persistence": {"enabled": True}},
        },
    )
    assert denied_response.status_code == 403
    assert "workspace.assets.publish" in denied_response.json()["detail"]
    assert attach_calls == []

    outsider_response = await client.get(
        f"/v1/workspaces/{workspace_id}/system-plugins",
        headers={"Authorization": "Bearer outsider-token"},
    )
    assert outsider_response.status_code == 404

    _grant_workspace_permissions(
        mock_collaboration_service,
        user_id=owner_context.user_id,
        organization_id=organization_id,
        permissions=["workspace.assets.publish"],
        name="plugin-asset-publisher",
    )
    allowed_response = await client.put(
        f"/v1/workspaces/{workspace_id}/system-plugins/{plugin_id}",
        headers={"Authorization": "Bearer owner-token"},
        json={
            "actor": actor_payload,
            "enabled": True,
            "tools_enabled": True,
            "metadata": {"asset_persistence": {"enabled": True}},
        },
    )

    assert allowed_response.status_code == 200
    assert allowed_response.json()["metadata"] == {"asset_persistence": {"enabled": True}}
    assert len(attach_calls) == 1
