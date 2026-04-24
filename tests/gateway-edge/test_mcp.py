from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

from gateway_edge.config import settings
from gateway_edge.mcp_api import notification_hub
from gateway_edge.models import AuthContext


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


def _agent_context(*, agent_identity_id, system_agent_id, client_id: str) -> AuthContext:
    return AuthContext(
        kind="oidc",
        principal_type="agent",
        agent_identity_id=agent_identity_id,
        system_agent_id=system_agent_id,
        issuer="http://issuer.test/realms/open-talon",
        subject=f"service-account-{client_id}",
        client_id=client_id,
        provider_key="keycloak",
        display_name="Provisioned Agent",
        claims={"azp": client_id, "sub": f"service-account-{client_id}"},
    )


def _patch_oidc_tokens(monkeypatch, token_map: dict[str, AuthContext]) -> None:
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        return token_map.get(token)

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)


async def _jsonrpc(client, *, token: str | None, method: str, params=None, session_id: str | None = None, request_id=1):
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if session_id is not None:
        headers["Mcp-Session-Id"] = session_id
    return await client.post(
        "/v1/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
    )


async def _mcp_initialize(client, *, token: str) -> str:
    response = await _jsonrpc(client, token=token, method="initialize")
    assert response.status_code == 200
    assert response.json()["result"]["protocolVersion"] == "2025-06-18"
    return response.headers["Mcp-Session-Id"]


async def _mcp_tool_call(client, *, token: str, session_id: str, name: str, arguments=None, request_id=2):
    return await _jsonrpc(
        client,
        token=token,
        method="tools/call",
        params={"name": name, "arguments": arguments or {}},
        session_id=session_id,
        request_id=request_id,
    )


async def _mcp_tools_list(client, *, token: str, session_id: str, request_id=3):
    return await _jsonrpc(
        client,
        token=token,
        method="tools/list",
        session_id=session_id,
        request_id=request_id,
    )


async def _mcp_resources_list(client, *, token: str, session_id: str, request_id=4):
    return await _jsonrpc(
        client,
        token=token,
        method="resources/list",
        session_id=session_id,
        request_id=request_id,
    )


async def _mcp_resource_read(client, *, token: str, session_id: str, uri: str, request_id=5):
    return await _jsonrpc(
        client,
        token=token,
        method="resources/read",
        params={"uri": uri},
        session_id=session_id,
        request_id=request_id,
    )


async def _mcp_resource_json(client, *, token: str, session_id: str, uri: str, request_id: int) -> dict[str, object]:
    response = await _mcp_resource_read(
        client,
        token=token,
        session_id=session_id,
        uri=uri,
        request_id=request_id,
    )
    return json.loads(response.json()["result"]["contents"][0]["text"])


async def _mcp_context_snapshot(
    client,
    *,
    token: str,
    scope: str,
    request_id_base: int = 100,
    organization_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, object]:
    session_id = await _mcp_initialize(client, token=token)
    scopes_response = await _mcp_tool_call(
        client,
        token=token,
        session_id=session_id,
        name="session.list_scopes",
        request_id=request_id_base,
    )
    scope_args = {"scope": scope}
    if organization_id is not None:
        scope_args["organization_id"] = organization_id
    if workspace_id is not None:
        scope_args["workspace_id"] = workspace_id
    set_scope_response = await _mcp_tool_call(
        client,
        token=token,
        session_id=session_id,
        name="session.set_scope",
        arguments=scope_args,
        request_id=request_id_base + 1,
    )
    tools_response = await _mcp_tools_list(
        client,
        token=token,
        session_id=session_id,
        request_id=request_id_base + 2,
    )
    resources_response = await _mcp_resources_list(
        client,
        token=token,
        session_id=session_id,
        request_id=request_id_base + 3,
    )
    identity = await _mcp_resource_json(
        client,
        token=token,
        session_id=session_id,
        uri="ot://session/identity",
        request_id=request_id_base + 4,
    )
    permissions = await _mcp_resource_json(
        client,
        token=token,
        session_id=session_id,
        uri="ot://session/permissions",
        request_id=request_id_base + 5,
    )
    scope_payload = await _mcp_resource_json(
        client,
        token=token,
        session_id=session_id,
        uri="ot://session/scope",
        request_id=request_id_base + 6,
    )
    return {
        "session_id": session_id,
        "scopes": scopes_response.json()["result"]["structuredContent"],
        "set_scope": set_scope_response.json()["result"],
        "tool_names": [item["name"] for item in tools_response.json()["result"]["tools"]],
        "resource_uris": [item["uri"] for item in resources_response.json()["result"]["resources"]],
        "identity": identity,
        "permissions": permissions,
        "scope": scope_payload,
    }


async def _create_workspace(client, *, token: str, organization_id: str, actor_payload: dict[str, str], name: str) -> str:
    response = await client.post(
        f"/v1/organizations/{organization_id}/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "actor": actor_payload},
    )
    assert response.status_code == 200
    return response.json()["workspace"]["workspace_id"]


async def _create_org_agent(client, *, token: str, organization_id: str, actor_payload: dict[str, str], display_name: str):
    response = await client.post(
        f"/v1/organizations/{organization_id}/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "actor": actor_payload,
            "display_name": display_name,
            "description": f"{display_name} description.",
            "role": "operator",
            "capabilities": ["api"],
            "endpoint": {"kind": "remote", "model": "gpt-5.4"},
            "system_prompt": f"{display_name} prompt.",
        },
    )
    assert response.status_code == 200
    return response.json()


async def _create_org_agent_role(
    client,
    *,
    token: str,
    organization_id: str,
    actor_payload: dict[str, str],
    name: str,
    permissions: list[str],
):
    response = await client.post(
        f"/v1/organizations/{organization_id}/iam/agent-roles",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "actor": actor_payload,
            "name": name,
            "description": f"{name} role",
            "permissions": permissions,
        },
    )
    assert response.status_code == 200
    return response.json()["role_id"]


async def _provision_org_agent_identity(
    client,
    *,
    token: str,
    organization_id: str,
    actor_payload: dict[str, str],
    system_agent_id: str,
    client_id: str,
):
    response = await client.post(
        f"/v1/organizations/{organization_id}/iam/agent-identities",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "actor": actor_payload,
            "system_agent_id": system_agent_id,
            "client_id": client_id,
        },
    )
    assert response.status_code == 200
    return response.json()["identity"]


async def _bind_agent_role(
    client,
    *,
    token: str,
    actor_payload: dict[str, str],
    agent_identity_id: str,
    role_id: str,
):
    response = await client.post(
        f"/v1/iam/agent-identities/{agent_identity_id}/roles/{role_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"actor": actor_payload},
    )
    assert response.status_code == 200


async def _attach_agent_to_workspace(
    client,
    *,
    token: str,
    actor_payload: dict[str, str],
    workspace_id: str,
    agent_id: str,
):
    response = await client.post(
        f"/v1/workspaces/{workspace_id}/agents",
        headers={"Authorization": f"Bearer {token}"},
        json={"actor": actor_payload, "agent_id": agent_id},
    )
    assert response.status_code == 200


async def _create_org_tool(
    client,
    *,
    token: str,
    organization_id: str,
    actor_payload: dict[str, str],
    name: str,
):
    response = await client.post(
        f"/v1/organizations/{organization_id}/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "actor": actor_payload,
            "name": name,
            "description": f"{name} description.",
        },
    )
    assert response.status_code == 200
    return response.json()["tool_id"]


async def _attach_tool_to_workspace(
    client,
    *,
    token: str,
    actor_payload: dict[str, str],
    workspace_id: str,
    tool_id: str,
):
    response = await client.put(
        f"/v1/workspaces/{workspace_id}/tools/{tool_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "actor": actor_payload,
            "enabled": True,
        },
    )
    assert response.status_code == 200


async def test_mcp_requires_oidc_even_when_api_key_auth_is_enabled(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "any")

    async def _allow_api_key(raw_key: str) -> bool:
        return raw_key == "good-key"

    async def _deny_oidc(token: str):
        _ = token
        return None

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_api_key", _allow_api_key)
    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _deny_oidc)

    response = await client.post(
        "/v1/mcp",
        headers={"X-API-Key": "good-key"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing OIDC Bearer token"
    assert "resource_metadata=" in response.headers["WWW-Authenticate"]
    assert "/.well-known/oauth-protected-resource/v1/mcp" in response.headers["WWW-Authenticate"]


async def test_mcp_scope_change_emits_notifications_and_filters_operations(
    client,
    actor_payload,
    monkeypatch,
):
    organization_id = "11111111-1111-1111-1111-111111111111"
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    workspace_id = await _create_workspace(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="MCP Organization Workspace",
    )

    reader_agent = await _create_org_agent(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        display_name="Reader Agent",
    )
    manager_agent = await _create_org_agent(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        display_name="Manager Agent",
    )

    reader_role_id = await _create_org_agent_role(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="mcp-reader",
        permissions=["organization.read", "workspace.list", "workspace.read"],
    )
    manager_role_id = await _create_org_agent_role(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="mcp-manager",
        permissions=["organization.read", "organization.members.read", "workspace.list", "workspace.read"],
    )

    reader_identity = await _provision_org_agent_identity(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        system_agent_id=reader_agent["agent_id"],
        client_id="mcp-reader-client",
    )
    manager_identity = await _provision_org_agent_identity(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        system_agent_id=manager_agent["agent_id"],
        client_id="mcp-manager-client",
    )

    await _bind_agent_role(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        agent_identity_id=reader_identity["agent_identity_id"],
        role_id=reader_role_id,
    )
    await _bind_agent_role(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        agent_identity_id=manager_identity["agent_identity_id"],
        role_id=manager_role_id,
    )
    await _attach_agent_to_workspace(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        workspace_id=workspace_id,
        agent_id=reader_agent["agent_id"],
    )
    await _attach_agent_to_workspace(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        workspace_id=workspace_id,
        agent_id=manager_agent["agent_id"],
    )

    reader_context = _agent_context(
        agent_identity_id=reader_identity["agent_identity_id"],
        system_agent_id=reader_identity["system_agent_id"],
        client_id=reader_identity["client_id"],
    )
    manager_context = _agent_context(
        agent_identity_id=manager_identity["agent_identity_id"],
        system_agent_id=manager_identity["system_agent_id"],
        client_id=manager_identity["client_id"],
    )
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": admin,
            "reader-token": reader_context,
            "manager-token": manager_context,
        },
    )

    reader_session_id = await _mcp_initialize(client, token="reader-token")
    manager_session_id = await _mcp_initialize(client, token="manager-token")
    manager_queue = await notification_hub.subscribe(UUID(manager_session_id))
    try:
        reader_scope_response = await _mcp_tool_call(
            client,
            token="reader-token",
            session_id=reader_session_id,
            name="session.set_scope",
            arguments={"scope": "organization", "organization_id": organization_id},
        )
        manager_scope_response = await _mcp_tool_call(
            client,
            token="manager-token",
            session_id=manager_session_id,
            name="session.set_scope",
            arguments={"scope": "organization", "organization_id": organization_id},
        )

        assert reader_scope_response.status_code == 200
        assert manager_scope_response.status_code == 200
        assert reader_scope_response.json()["result"]["isError"] is False
        assert manager_scope_response.json()["result"]["isError"] is False

        first_event = await asyncio.wait_for(manager_queue.get(), timeout=1)
        second_event = await asyncio.wait_for(manager_queue.get(), timeout=1)
        assert {first_event["method"], second_event["method"]} == {
            "notifications/tools/list_changed",
            "notifications/resources/list_changed",
        }
    finally:
        notification_hub.unsubscribe(UUID(manager_session_id), manager_queue)

    reader_tools_response = await _mcp_tools_list(
        client,
        token="reader-token",
        session_id=reader_session_id,
    )
    manager_tools_response = await _mcp_tools_list(
        client,
        token="manager-token",
        session_id=manager_session_id,
    )

    reader_tool_names = {
        item["name"] for item in reader_tools_response.json()["result"]["tools"]
    }
    manager_tool_names = {
        item["name"] for item in manager_tools_response.json()["result"]["tools"]
    }

    assert "organizations.members.list" not in reader_tool_names
    assert "iam.agent_identities.list" not in reader_tool_names
    assert "iam.agent_identities.list" in manager_tool_names

    denied_direct_call = await _mcp_tool_call(
        client,
        token="reader-token",
        session_id=reader_session_id,
        name="iam.agent_identities.list",
    )

    assert denied_direct_call.status_code == 200
    assert denied_direct_call.json()["result"]["isError"] is True
    assert "not available" in denied_direct_call.json()["result"]["content"][0]["text"]


async def test_mcp_agent_git_and_catalog_tools_require_matching_permissions(
    client,
    actor_payload,
    monkeypatch,
):
    organization_id = "11111111-1111-1111-1111-111111111111"
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    reader_agent = await _create_org_agent(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        display_name="Catalog Reader Agent",
    )
    author_agent = await _create_org_agent(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        display_name="Catalog Author Agent",
    )
    reader_role_id = await _create_org_agent_role(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="agent-git-reader",
        permissions=["organization.read"],
    )
    author_role_id = await _create_org_agent_role(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="agent-git-author",
        permissions=["organization.read", "agent_catalog.write", "git_registry.write"],
    )
    reader_identity = await _provision_org_agent_identity(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        system_agent_id=reader_agent["agent_id"],
        client_id="agent-git-reader-client",
    )
    author_identity = await _provision_org_agent_identity(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        system_agent_id=author_agent["agent_id"],
        client_id="agent-git-author-client",
    )
    await _bind_agent_role(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        agent_identity_id=reader_identity["agent_identity_id"],
        role_id=reader_role_id,
    )
    await _bind_agent_role(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        agent_identity_id=author_identity["agent_identity_id"],
        role_id=author_role_id,
    )

    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": admin,
            "reader-token": _agent_context(
                agent_identity_id=reader_identity["agent_identity_id"],
                system_agent_id=reader_identity["system_agent_id"],
                client_id=reader_identity["client_id"],
            ),
            "author-token": _agent_context(
                agent_identity_id=author_identity["agent_identity_id"],
                system_agent_id=author_identity["system_agent_id"],
                client_id=author_identity["client_id"],
            ),
        },
    )

    reader_session_id = await _mcp_initialize(client, token="reader-token")
    author_session_id = await _mcp_initialize(client, token="author-token")
    for token, session_id in [
        ("reader-token", reader_session_id),
        ("author-token", author_session_id),
    ]:
        response = await _mcp_tool_call(
            client,
            token=token,
            session_id=session_id,
            name="session.set_scope",
            arguments={"scope": "organization", "organization_id": organization_id},
        )
        assert response.status_code == 200
        assert response.json()["result"]["isError"] is False

    reader_tools_response = await _mcp_tools_list(
        client,
        token="reader-token",
        session_id=reader_session_id,
    )
    author_tools_response = await _mcp_tools_list(
        client,
        token="author-token",
        session_id=author_session_id,
    )
    reader_tool_names = {
        item["name"] for item in reader_tools_response.json()["result"]["tools"]
    }
    author_tool_names = {
        item["name"] for item in author_tools_response.json()["result"]["tools"]
    }

    expected_author_tools = {
        "agent_catalog.bundle.validate",
        "agent_catalog.bundle.publish",
        "agent_git.repo.ensure",
        "agent_git.worktree.create",
        "agent_git.file.read",
        "agent_git.file.write",
        "agent_git.file.delete",
        "agent_git.diff.preview",
        "agent_git.commit.push",
        "agent_git.worktree.discard",
    }
    assert expected_author_tools <= author_tool_names
    assert expected_author_tools.isdisjoint(reader_tool_names)

    denied_call = await _mcp_tool_call(
        client,
        token="reader-token",
        session_id=reader_session_id,
        name="agent_catalog.bundle.validate",
        arguments={"repository_id": str(uuid4()), "bundle_path": "agents/admin"},
    )
    assert denied_call.status_code == 200
    assert denied_call.json()["result"]["isError"] is True
    assert "not available" in denied_call.json()["result"]["content"][0]["text"]


async def test_mcp_workspace_scope_requires_attachment(
    client,
    actor_payload,
    monkeypatch,
):
    organization_id = "11111111-1111-1111-1111-111111111111"
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    workspace_id = await _create_workspace(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="MCP Workspace Scope",
    )

    attached_agent = await _create_org_agent(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        display_name="Attached Agent",
    )
    unattached_agent = await _create_org_agent(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        display_name="Unattached Agent",
    )

    role_id = await _create_org_agent_role(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="mcp-workspace-reader",
        permissions=["organization.read", "workspace.list", "workspace.read"],
    )

    attached_identity = await _provision_org_agent_identity(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        system_agent_id=attached_agent["agent_id"],
        client_id="attached-workspace-client",
    )
    unattached_identity = await _provision_org_agent_identity(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        system_agent_id=unattached_agent["agent_id"],
        client_id="unattached-workspace-client",
    )

    await _bind_agent_role(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        agent_identity_id=attached_identity["agent_identity_id"],
        role_id=role_id,
    )
    await _bind_agent_role(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        agent_identity_id=unattached_identity["agent_identity_id"],
        role_id=role_id,
    )
    await _attach_agent_to_workspace(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        workspace_id=workspace_id,
        agent_id=attached_agent["agent_id"],
    )

    attached_context = _agent_context(
        agent_identity_id=attached_identity["agent_identity_id"],
        system_agent_id=attached_identity["system_agent_id"],
        client_id=attached_identity["client_id"],
    )
    unattached_context = _agent_context(
        agent_identity_id=unattached_identity["agent_identity_id"],
        system_agent_id=unattached_identity["system_agent_id"],
        client_id=unattached_identity["client_id"],
    )
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": admin,
            "attached-token": attached_context,
            "unattached-token": unattached_context,
        },
    )

    attached_session_id = await _mcp_initialize(client, token="attached-token")
    unattached_session_id = await _mcp_initialize(client, token="unattached-token")

    attached_scope = await _mcp_tool_call(
        client,
        token="attached-token",
        session_id=attached_session_id,
        name="session.set_scope",
        arguments={"scope": "workspace", "workspace_id": workspace_id},
    )
    unattached_scope = await _mcp_tool_call(
        client,
        token="unattached-token",
        session_id=unattached_session_id,
        name="session.set_scope",
        arguments={"scope": "workspace", "workspace_id": workspace_id},
    )

    assert attached_scope.json()["result"]["isError"] is False
    assert unattached_scope.json()["result"]["isError"] is True
    assert "not available" in unattached_scope.json()["result"]["content"][0]["text"]

    attached_tools = await _mcp_tools_list(
        client,
        token="attached-token",
        session_id=attached_session_id,
    )
    attached_tool_names = {item["name"] for item in attached_tools.json()["result"]["tools"]}
    assert "threads.list" in attached_tool_names

    hidden_call = await _mcp_tool_call(
        client,
        token="unattached-token",
        session_id=unattached_session_id,
        name="threads.list",
    )

    assert hidden_call.status_code == 200
    assert hidden_call.json()["result"]["isError"] is True
    assert "not available" in hidden_call.json()["result"]["content"][0]["text"]


async def test_mcp_threads_create_and_message_create_round_trip(
    client,
    actor_payload,
    monkeypatch,
):
    organization_id = "11111111-1111-1111-1111-111111111111"
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    workspace_id = await _create_workspace(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="MCP Thread Workspace",
    )
    agent = await _create_org_agent(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        display_name="Thread Agent",
    )
    role_id = await _create_org_agent_role(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="mcp-thread-agent",
        permissions=["organization.read", "workspace.list", "workspace.read"],
    )
    identity = await _provision_org_agent_identity(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        system_agent_id=agent["agent_id"],
        client_id="thread-agent-client",
    )
    await _bind_agent_role(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        agent_identity_id=identity["agent_identity_id"],
        role_id=role_id,
    )
    await _attach_agent_to_workspace(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        workspace_id=workspace_id,
        agent_id=agent["agent_id"],
    )

    agent_context = _agent_context(
        agent_identity_id=identity["agent_identity_id"],
        system_agent_id=identity["system_agent_id"],
        client_id=identity["client_id"],
    )
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": admin,
            "agent-token": agent_context,
        },
    )

    session_id = await _mcp_initialize(client, token="agent-token")
    set_scope_response = await _mcp_tool_call(
        client,
        token="agent-token",
        session_id=session_id,
        name="session.set_scope",
        arguments={"scope": "workspace", "workspace_id": workspace_id},
    )
    assert set_scope_response.json()["result"]["isError"] is False

    create_thread_response = await _mcp_tool_call(
        client,
        token="agent-token",
        session_id=session_id,
        name="threads.create",
        arguments={"title": "MCP Thread"},
    )
    assert create_thread_response.status_code == 200
    assert create_thread_response.json()["result"]["isError"] is False
    thread_id = create_thread_response.json()["result"]["structuredContent"]["thread"]["thread_id"]

    create_message_response = await _mcp_tool_call(
        client,
        token="agent-token",
        session_id=session_id,
        name="threads.messages.create",
        arguments={
            "thread_id": thread_id,
            "content": "Created through MCP",
            "visibility": "public",
            "create_task": False,
        },
    )

    assert create_message_response.status_code == 200
    assert create_message_response.json()["result"]["isError"] is False
    message = create_message_response.json()["result"]["structuredContent"]
    assert message["thread_id"] == thread_id
    assert message["content"] == "Created through MCP"

    timeline_response = await _mcp_tool_call(
        client,
        token="agent-token",
        session_id=session_id,
        name="threads.timeline.get",
        arguments={"thread_id": thread_id},
    )

    assert timeline_response.status_code == 200
    assert timeline_response.json()["result"]["isError"] is False
    assert timeline_response.json()["result"]["structuredContent"]["messages"][0]["content"] == "Created through MCP"


async def test_mcp_resources_reflect_active_scope_and_permissions(
    client,
    actor_payload,
    monkeypatch,
):
    organization_id = "11111111-1111-1111-1111-111111111111"
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    workspace_id = await _create_workspace(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="MCP Resource Workspace",
    )
    agent = await _create_org_agent(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        display_name="Resource Agent",
    )
    role_id = await _create_org_agent_role(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="mcp-resource-agent",
        permissions=["organization.read", "workspace.list", "workspace.read"],
    )
    identity = await _provision_org_agent_identity(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        system_agent_id=agent["agent_id"],
        client_id="resource-agent-client",
    )
    await _bind_agent_role(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        agent_identity_id=identity["agent_identity_id"],
        role_id=role_id,
    )
    await _attach_agent_to_workspace(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        workspace_id=workspace_id,
        agent_id=agent["agent_id"],
    )

    agent_context = _agent_context(
        agent_identity_id=identity["agent_identity_id"],
        system_agent_id=identity["system_agent_id"],
        client_id=identity["client_id"],
    )
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": admin,
            "agent-token": agent_context,
        },
    )

    session_id = await _mcp_initialize(client, token="agent-token")
    resources_list_response = await _mcp_resources_list(
        client,
        token="agent-token",
        session_id=session_id,
    )
    assert resources_list_response.status_code == 200
    assert {item["uri"] for item in resources_list_response.json()["result"]["resources"]} == {
        "ot://session/identity",
        "ot://session/permissions",
        "ot://session/scope",
    }

    set_scope_response = await _mcp_tool_call(
        client,
        token="agent-token",
        session_id=session_id,
        name="session.set_scope",
        arguments={"scope": "workspace", "workspace_id": workspace_id},
    )
    assert set_scope_response.json()["result"]["isError"] is False

    identity_response = await _mcp_resource_read(
        client,
        token="agent-token",
        session_id=session_id,
        uri="ot://session/identity",
        request_id=6,
    )
    permissions_response = await _mcp_resource_read(
        client,
        token="agent-token",
        session_id=session_id,
        uri="ot://session/permissions",
        request_id=7,
    )
    scope_response = await _mcp_resource_read(
        client,
        token="agent-token",
        session_id=session_id,
        uri="ot://session/scope",
        request_id=8,
    )

    identity_text = identity_response.json()["result"]["contents"][0]["text"]
    permissions_text = permissions_response.json()["result"]["contents"][0]["text"]
    scope_text = scope_response.json()["result"]["contents"][0]["text"]

    assert '"principal_type": "agent"' in identity_text
    assert f'"workspace_id": "{workspace_id}"' in identity_text
    assert '"workspace_permissions": []' in permissions_text
    assert '"identity_permissions": ["organization.read", "workspace.list", "workspace.read"]' in permissions_text
    assert '"workspace_participant_id": "' in permissions_text
    assert f'"workspace_id": "{workspace_id}"' in scope_text


async def test_mcp_does_not_import_workspace_tool_catalog_entries_as_operations(
    client,
    actor_payload,
    monkeypatch,
):
    organization_id = "11111111-1111-1111-1111-111111111111"
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    workspace_id = await _create_workspace(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="MCP Catalog Isolation Workspace",
    )
    system_tool_id = await _create_org_tool(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="workspace_catalog_probe",
    )
    await _attach_tool_to_workspace(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        workspace_id=workspace_id,
        tool_id=system_tool_id,
    )

    agent = await _create_org_agent(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        display_name="Catalog Isolation Agent",
    )
    role_id = await _create_org_agent_role(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="mcp-catalog-isolation-agent",
        permissions=["organization.read", "workspace.list", "workspace.read"],
    )
    identity = await _provision_org_agent_identity(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        system_agent_id=agent["agent_id"],
        client_id="catalog-isolation-agent-client",
    )
    await _bind_agent_role(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        agent_identity_id=identity["agent_identity_id"],
        role_id=role_id,
    )
    await _attach_agent_to_workspace(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        workspace_id=workspace_id,
        agent_id=agent["agent_id"],
    )

    agent_context = _agent_context(
        agent_identity_id=identity["agent_identity_id"],
        system_agent_id=identity["system_agent_id"],
        client_id=identity["client_id"],
    )
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": admin,
            "agent-token": agent_context,
        },
    )

    session_id = await _mcp_initialize(client, token="agent-token")
    set_scope_response = await _mcp_tool_call(
        client,
        token="agent-token",
        session_id=session_id,
        name="session.set_scope",
        arguments={"scope": "workspace", "workspace_id": workspace_id},
    )
    assert set_scope_response.json()["result"]["isError"] is False

    tools_response = await _mcp_tools_list(
        client,
        token="agent-token",
        session_id=session_id,
    )
    tool_names = {item["name"] for item in tools_response.json()["result"]["tools"]}

    assert "threads.list" in tool_names
    assert "workspace_catalog_probe" not in tool_names


async def test_mcp_compares_submitted_context_between_agents_with_different_permissions(
    client,
    actor_payload,
    monkeypatch,
):
    organization_id = "11111111-1111-1111-1111-111111111111"
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    workspace_id = await _create_workspace(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="MCP Context Comparison Workspace",
    )
    reader_agent = await _create_org_agent(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        display_name="Context Reader Agent",
    )
    manager_agent = await _create_org_agent(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        display_name="Context Manager Agent",
    )

    reader_role_id = await _create_org_agent_role(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="mcp-context-reader",
        permissions=["organization.read", "workspace.list", "workspace.read"],
    )
    manager_role_id = await _create_org_agent_role(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        name="mcp-context-manager",
        permissions=["organization.read", "organization.members.read", "workspace.list", "workspace.read"],
    )

    reader_identity = await _provision_org_agent_identity(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        system_agent_id=reader_agent["agent_id"],
        client_id="mcp-context-reader-client",
    )
    manager_identity = await _provision_org_agent_identity(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor_payload=actor_payload,
        system_agent_id=manager_agent["agent_id"],
        client_id="mcp-context-manager-client",
    )

    await _bind_agent_role(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        agent_identity_id=reader_identity["agent_identity_id"],
        role_id=reader_role_id,
    )
    await _bind_agent_role(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        agent_identity_id=manager_identity["agent_identity_id"],
        role_id=manager_role_id,
    )
    await _attach_agent_to_workspace(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        workspace_id=workspace_id,
        agent_id=reader_agent["agent_id"],
    )
    await _attach_agent_to_workspace(
        client,
        token="admin-token",
        actor_payload=actor_payload,
        workspace_id=workspace_id,
        agent_id=manager_agent["agent_id"],
    )

    reader_context = _agent_context(
        agent_identity_id=reader_identity["agent_identity_id"],
        system_agent_id=reader_identity["system_agent_id"],
        client_id=reader_identity["client_id"],
    )
    manager_context = _agent_context(
        agent_identity_id=manager_identity["agent_identity_id"],
        system_agent_id=manager_identity["system_agent_id"],
        client_id=manager_identity["client_id"],
    )
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": admin,
            "reader-token": reader_context,
            "manager-token": manager_context,
        },
    )

    reader_org_snapshot = await _mcp_context_snapshot(
        client,
        token="reader-token",
        scope="organization",
        organization_id=organization_id,
        request_id_base=200,
    )
    manager_org_snapshot = await _mcp_context_snapshot(
        client,
        token="manager-token",
        scope="organization",
        organization_id=organization_id,
        request_id_base=300,
    )
    reader_workspace_snapshot = await _mcp_context_snapshot(
        client,
        token="reader-token",
        scope="workspace",
        workspace_id=workspace_id,
        request_id_base=400,
    )
    manager_workspace_snapshot = await _mcp_context_snapshot(
        client,
        token="manager-token",
        scope="workspace",
        workspace_id=workspace_id,
        request_id_base=500,
    )

    assert reader_org_snapshot["resource_uris"] == manager_org_snapshot["resource_uris"]
    assert reader_org_snapshot["identity"]["agent_identity_id"] != manager_org_snapshot["identity"]["agent_identity_id"]
    assert reader_org_snapshot["permissions"]["identity_permissions"] == [
        "organization.read",
        "workspace.list",
        "workspace.read",
    ]
    assert manager_org_snapshot["permissions"]["identity_permissions"] == [
        "organization.members.read",
        "organization.read",
        "workspace.list",
        "workspace.read",
    ]
    assert "iam.agent_identities.list" not in reader_org_snapshot["tool_names"]
    assert "iam.agent_identities.list" in manager_org_snapshot["tool_names"]
    assert set(reader_org_snapshot["tool_names"]).issubset(set(manager_org_snapshot["tool_names"]))

    assert reader_workspace_snapshot["tool_names"] == manager_workspace_snapshot["tool_names"]
    assert "iam.agent_identities.list" not in reader_workspace_snapshot["tool_names"]
    assert "iam.agent_identities.list" not in manager_workspace_snapshot["tool_names"]
    assert reader_workspace_snapshot["permissions"]["identity_permissions"] == [
        "organization.read",
        "workspace.list",
        "workspace.read",
    ]
    assert manager_workspace_snapshot["permissions"]["identity_permissions"] == [
        "organization.members.read",
        "organization.read",
        "workspace.list",
        "workspace.read",
    ]
    assert reader_workspace_snapshot["permissions"]["workspace_participant_id"]
    assert manager_workspace_snapshot["permissions"]["workspace_participant_id"]
    assert reader_workspace_snapshot["scope"] == {
        "scope": "workspace",
        "workspace_id": workspace_id,
    }
    assert manager_workspace_snapshot["scope"] == {
        "scope": "workspace",
        "workspace_id": workspace_id,
    }
