from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any
from uuid import uuid4

import httpx
import pytest


pytestmark = pytest.mark.integration

_ROOT_DIR = Path(__file__).resolve().parents[2]
_GATEWAY_URL = "http://127.0.0.1:8000"
_KEYCLOAK_BASE_URL = "http://127.0.0.1:8081"
_OPEN_TALON_REALM = "open-talon"


def _wait_for(
    description: str,
    predicate,
    *,
    timeout_seconds: float = 120.0,
    interval_seconds: float = 1.0,
):
    deadline = time.monotonic() + timeout_seconds
    last_value = None
    while time.monotonic() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(interval_seconds)
    raise AssertionError(f"Timed out waiting for {description}; last_value={last_value!r}")


def _wait_for_gateway() -> None:
    def _healthy() -> bool:
        try:
            response = httpx.get(f"{_GATEWAY_URL}/health", timeout=5.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    _wait_for("gateway health", _healthy, timeout_seconds=120.0, interval_seconds=1.0)


def _wait_for_keycloak() -> None:
    def _healthy() -> bool:
        try:
            response = httpx.get(
                f"{_KEYCLOAK_BASE_URL}/realms/{_OPEN_TALON_REALM}/.well-known/openid-configuration",
                timeout=5.0,
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    _wait_for("Keycloak discovery", _healthy, timeout_seconds=120.0, interval_seconds=1.0)


def _master_admin_token() -> str:
    response = httpx.post(
        f"{_KEYCLOAK_BASE_URL}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": "admin",
            "password": "admin",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def _keycloak_client_internal_id(*, admin_token: str, client_id: str) -> str | None:
    response = httpx.get(
        f"{_KEYCLOAK_BASE_URL}/admin/realms/{_OPEN_TALON_REALM}/clients",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"clientId": client_id},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload:
        return None
    internal_id = payload[0].get("id")
    return str(internal_id) if internal_id else None


def _ensure_password_grant_client(*, admin_token: str, client_id: str) -> None:
    if _keycloak_client_internal_id(admin_token=admin_token, client_id=client_id):
        return
    response = httpx.post(
        f"{_KEYCLOAK_BASE_URL}/admin/realms/{_OPEN_TALON_REALM}/clients",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "clientId": client_id,
            "name": "MCP live system tests",
            "protocol": "openid-connect",
            "publicClient": True,
            "directAccessGrantsEnabled": True,
            "standardFlowEnabled": False,
            "serviceAccountsEnabled": False,
            "redirectUris": [],
            "webOrigins": [],
        },
        timeout=20.0,
    )
    if response.status_code not in {201, 204, 409}:
        response.raise_for_status()


def _delete_keycloak_client(*, admin_token: str, client_id: str) -> None:
    internal_id = _keycloak_client_internal_id(admin_token=admin_token, client_id=client_id)
    if internal_id is None:
        return
    response = httpx.delete(
        f"{_KEYCLOAK_BASE_URL}/admin/realms/{_OPEN_TALON_REALM}/clients/{internal_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=20.0,
    )
    if response.status_code not in {204, 404}:
        response.raise_for_status()


def _password_grant_token(*, client_id: str, username: str, password: str) -> str:
    response = httpx.post(
        f"{_KEYCLOAK_BASE_URL}/realms/{_OPEN_TALON_REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "username": username,
            "password": password,
            "scope": "openid profile email",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def _client_credentials_token(*, client_id: str, client_secret: str) -> str:
    response = httpx.post(
        f"{_KEYCLOAK_BASE_URL}/realms/{_OPEN_TALON_REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def _actor_payload(*, display_name: str) -> dict[str, Any]:
    return {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": display_name,
    }


def _workspace_actor_from_participant(participant: dict[str, Any]) -> dict[str, Any]:
    return {
        "participant_id": participant["participant_id"],
        "participant_type": participant["participant_type"],
        "user_id": participant.get("user_id"),
        "display_name": participant["display_name"],
    }


def _json_request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: str | None = None,
    json_body: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> dict[str, Any] | list[Any]:
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, path, headers=headers, json=json_body)
    if response.status_code != expected_status:
        raise AssertionError(
            f"{method} {path} returned {response.status_code}: {response.text}"
        )
    return response.json()


def _mcp_request(
    client: httpx.Client,
    *,
    token: str,
    method: str,
    params: dict[str, Any] | None = None,
    session_id: str | None = None,
    request_id: int = 1,
    expected_status: int = 200,
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"}
    if session_id is not None:
        headers["Mcp-Session-Id"] = session_id
    response = client.post(
        "/v1/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
    )
    if response.status_code != expected_status:
        raise AssertionError(
            f"MCP {method} returned {response.status_code}: {response.text}"
        )
    return response


@dataclass
class _LiveMcpSystem:
    gateway_url: str
    human_client_id: str
    admin_token: str


@dataclass
class _LiveWorkspaceContext:
    organization_id: str
    workspace_id: str
    workspace_actor: dict[str, Any]


@dataclass
class _LiveProvisionedAgent:
    organization_id: str
    workspace_id: str
    workspace_actor: dict[str, Any]
    agent_identity_id: str
    system_agent_id: str
    machine_token: str


@pytest.fixture(scope="module")
def live_open_talon_mcp_system():
    human_client_id = f"mcp-system-tests-{uuid4().hex[:8]}"
    env = os.environ.copy()
    env.update(
        {
            "AUTH_MODE": "oidc",
            "OIDC_AUDIENCE": human_client_id,
        }
    )
    subprocess.run(
        ["./open-talon", "stop"],
        cwd=_ROOT_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["./open-talon", "start"],
        cwd=_ROOT_DIR,
        env=env,
        check=True,
    )
    _wait_for_keycloak()
    _wait_for_gateway()
    admin_token = _master_admin_token()
    _ensure_password_grant_client(admin_token=admin_token, client_id=human_client_id)
    human_access_token = _password_grant_token(
        client_id=human_client_id,
        username="admin",
        password="admin123",
    )
    me_response = httpx.get(
        f"{_GATEWAY_URL}/v1/me",
        headers={"Authorization": f"Bearer {human_access_token}"},
        timeout=20.0,
    )
    if me_response.status_code != 200:
        raise AssertionError(
            f"Human OIDC login failed against the live gateway: {me_response.status_code} {me_response.text}"
        )
    try:
        yield _LiveMcpSystem(
            gateway_url=_GATEWAY_URL,
            human_client_id=human_client_id,
            admin_token=human_access_token,
        )
    finally:
        try:
            _delete_keycloak_client(admin_token=_master_admin_token(), client_id=human_client_id)
        finally:
            subprocess.run(
                ["./open-talon", "stop"],
                cwd=_ROOT_DIR,
                env=env,
                check=False,
            )


def _provision_workspace_agent(
    client: httpx.Client,
    *,
    system: _LiveMcpSystem,
    permissions: list[str],
    workspace_context: _LiveWorkspaceContext | None = None,
) -> _LiveProvisionedAgent:
    admin_actor = _actor_payload(display_name="MCP Live Admin")
    workspace = workspace_context or _create_workspace_context(
        client,
        system=system,
        admin_actor=admin_actor,
    )
    suffix = uuid4().hex[:8]

    agent = _json_request(
        client,
        "POST",
        f"/v1/organizations/{workspace.organization_id}/agents",
        token=system.admin_token,
        json_body={
            "actor": admin_actor,
            "display_name": f"MCP Agent {suffix}",
            "description": "Live MCP agent.",
            "role": "mcp operator",
            "capabilities": ["mcp", "api"],
            "endpoint": {"kind": "remote", "model": "gpt-5.4"},
            "system_prompt": "Use Open Talon system APIs carefully.",
            "metadata": {"system_test": True},
        },
    )
    agent_id = str(agent["agent_id"])

    role = _json_request(
        client,
        "POST",
        f"/v1/organizations/{workspace.organization_id}/iam/agent-roles",
        token=system.admin_token,
        json_body={
            "actor": admin_actor,
            "name": f"mcp-live-role-{suffix}",
            "description": "Live MCP role.",
            "permissions": permissions,
        },
    )
    role_id = str(role["role_id"])

    provisioned = _json_request(
        client,
        "POST",
        f"/v1/organizations/{workspace.organization_id}/iam/agent-identities",
        token=system.admin_token,
        json_body={
            "actor": admin_actor,
            "system_agent_id": agent_id,
            "client_id": f"mcp-live-client-{suffix}",
        },
    )
    identity = provisioned["identity"]

    _json_request(
        client,
        "POST",
        f"/v1/iam/agent-identities/{identity['agent_identity_id']}/roles/{role_id}",
        token=system.admin_token,
        json_body={"actor": admin_actor},
    )
    _json_request(
        client,
        "POST",
        f"/v1/workspaces/{workspace.workspace_id}/agents",
        token=system.admin_token,
        json_body={
            "actor": workspace.workspace_actor,
            "agent_id": agent_id,
        },
    )

    machine_token = _client_credentials_token(
        client_id=str(identity["client_id"]),
        client_secret=str(provisioned["client_secret"]),
    )
    return _LiveProvisionedAgent(
        organization_id=workspace.organization_id,
        workspace_id=workspace.workspace_id,
        workspace_actor=workspace.workspace_actor,
        agent_identity_id=str(identity["agent_identity_id"]),
        system_agent_id=str(identity["system_agent_id"]),
        machine_token=machine_token,
    )


def _create_workspace_context(
    client: httpx.Client,
    *,
    system: _LiveMcpSystem,
    admin_actor: dict[str, Any] | None = None,
) -> _LiveWorkspaceContext:
    actor = admin_actor or _actor_payload(display_name="MCP Live Admin")
    suffix = uuid4().hex[:8]
    organization = _json_request(
        client,
        "POST",
        "/v1/organizations",
        token=system.admin_token,
        json_body={
            "actor": actor,
            "slug": f"mcp-live-{suffix}",
            "name": f"MCP Live {suffix}",
            "description": "Live MCP system test organization.",
            "metadata": {"system_test": True},
        },
    )
    organization_id = str(organization["organization_id"])

    workspace_detail = _json_request(
        client,
        "POST",
        f"/v1/organizations/{organization_id}/workspaces",
        token=system.admin_token,
        json_body={
            "name": f"MCP Workspace {suffix}",
            "description": "Live MCP system test workspace.",
            "actor": actor,
            "metadata": {"system_test": True},
        },
    )
    workspace_id = str(workspace_detail["workspace"]["workspace_id"])
    workspace_actor = _workspace_actor_from_participant(workspace_detail["participants"][0])
    return _LiveWorkspaceContext(
        organization_id=organization_id,
        workspace_id=workspace_id,
        workspace_actor=workspace_actor,
    )


def _mcp_resource_json(
    client: httpx.Client,
    *,
    token: str,
    session_id: str,
    uri: str,
    request_id: int,
) -> dict[str, Any]:
    response = _mcp_request(
        client,
        token=token,
        session_id=session_id,
        method="resources/read",
        params={"uri": uri},
        request_id=request_id,
    )
    return json.loads(response.json()["result"]["contents"][0]["text"])


def _mcp_context_snapshot(
    client: httpx.Client,
    *,
    token: str,
    scope: str,
    request_id_base: int = 100,
    organization_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    initialize = _mcp_request(
        client,
        token=token,
        method="initialize",
        request_id=request_id_base,
    )
    session_id = initialize.headers["Mcp-Session-Id"]
    scopes = _mcp_request(
        client,
        token=token,
        session_id=session_id,
        method="tools/call",
        params={"name": "session.list_scopes", "arguments": {}},
        request_id=request_id_base + 1,
    ).json()["result"]["structuredContent"]

    scope_args: dict[str, Any] = {"scope": scope}
    if organization_id is not None:
        scope_args["organization_id"] = organization_id
    if workspace_id is not None:
        scope_args["workspace_id"] = workspace_id
    set_scope = _mcp_request(
        client,
        token=token,
        session_id=session_id,
        method="tools/call",
        params={"name": "session.set_scope", "arguments": scope_args},
        request_id=request_id_base + 2,
    ).json()["result"]
    tools = _mcp_request(
        client,
        token=token,
        session_id=session_id,
        method="tools/list",
        request_id=request_id_base + 3,
    ).json()["result"]["tools"]
    resources = _mcp_request(
        client,
        token=token,
        session_id=session_id,
        method="resources/list",
        request_id=request_id_base + 4,
    ).json()["result"]["resources"]
    identity = _mcp_resource_json(
        client,
        token=token,
        session_id=session_id,
        uri="ot://session/identity",
        request_id=request_id_base + 5,
    )
    permissions = _mcp_resource_json(
        client,
        token=token,
        session_id=session_id,
        uri="ot://session/permissions",
        request_id=request_id_base + 6,
    )
    scope_payload = _mcp_resource_json(
        client,
        token=token,
        session_id=session_id,
        uri="ot://session/scope",
        request_id=request_id_base + 7,
    )
    return {
        "session_id": session_id,
        "scopes": scopes,
        "set_scope": set_scope,
        "tool_names": [item["name"] for item in tools],
        "resource_uris": [item["uri"] for item in resources],
        "identity": identity,
        "permissions": permissions,
        "scope": scope_payload,
    }


def test_mcp_machine_identity_can_create_thread_message_and_memory_on_live_system(
    live_open_talon_mcp_system: _LiveMcpSystem,
):
    with httpx.Client(base_url=live_open_talon_mcp_system.gateway_url, timeout=30.0) as client:
        provisioned = _provision_workspace_agent(
            client,
            system=live_open_talon_mcp_system,
            permissions=["organization.read", "workspace.list", "workspace.read"],
        )

        initialize = _mcp_request(
            client,
            token=provisioned.machine_token,
            method="initialize",
        )
        session_id = initialize.headers["Mcp-Session-Id"]

        scopes = _mcp_request(
            client,
            token=provisioned.machine_token,
            session_id=session_id,
            method="tools/call",
            params={"name": "session.list_scopes", "arguments": {}},
            request_id=2,
        ).json()["result"]["structuredContent"]
        assert any(
            item["kind"] == "workspace" and item["id"] == provisioned.workspace_id
            for item in scopes
        )

        set_scope = _mcp_request(
            client,
            token=provisioned.machine_token,
            session_id=session_id,
            method="tools/call",
            params={
                "name": "session.set_scope",
                "arguments": {"scope": "workspace", "workspace_id": provisioned.workspace_id},
            },
            request_id=3,
        ).json()["result"]
        assert set_scope["isError"] is False

        permissions_resource = _mcp_request(
            client,
            token=provisioned.machine_token,
            session_id=session_id,
            method="resources/read",
            params={"uri": "ot://session/permissions"},
            request_id=4,
        ).json()["result"]["contents"][0]["text"]
        assert '"workspace_id"' in permissions_resource
        assert '"workspace.read"' in permissions_resource

        create_thread = _mcp_request(
            client,
            token=provisioned.machine_token,
            session_id=session_id,
            method="tools/call",
            params={"name": "threads.create", "arguments": {"title": "Live MCP Thread"}},
            request_id=5,
        ).json()["result"]
        assert create_thread["isError"] is False
        thread_id = str(create_thread["structuredContent"]["thread"]["thread_id"])

        create_message = _mcp_request(
            client,
            token=provisioned.machine_token,
            session_id=session_id,
            method="tools/call",
            params={
                "name": "threads.messages.create",
                "arguments": {
                    "thread_id": thread_id,
                    "content": "Live MCP message",
                    "visibility": "public",
                    "create_task": False,
                },
            },
            request_id=6,
        ).json()["result"]
        assert create_message["isError"] is False
        assert create_message["structuredContent"]["content"] == "Live MCP message"

        create_memory = _mcp_request(
            client,
            token=provisioned.machine_token,
            session_id=session_id,
            method="tools/call",
            params={
                "name": "memory.workspace.create",
                "arguments": {
                    "entry_type": "decision",
                    "content": "Live MCP memory",
                    "summary": "MCP summary",
                },
            },
            request_id=7,
        ).json()["result"]
        assert create_memory["isError"] is False
        assert create_memory["structuredContent"]["summary"] == "MCP summary"

        timeline = _json_request(
            client,
            "GET",
            f"/v1/threads/{thread_id}/timeline",
            token=live_open_talon_mcp_system.admin_token,
        )
        assert timeline["messages"][-1]["content"] == "Live MCP message"

        workspace_memory = _json_request(
            client,
            "GET",
            f"/v1/workspaces/{provisioned.workspace_id}/memory",
            token=live_open_talon_mcp_system.admin_token,
        )
        assert any(entry["content"] == "Live MCP memory" for entry in workspace_memory)


def test_mcp_live_system_keeps_workspace_tool_catalog_entries_out_of_operation_list(
    live_open_talon_mcp_system: _LiveMcpSystem,
):
    with httpx.Client(base_url=live_open_talon_mcp_system.gateway_url, timeout=30.0) as client:
        provisioned = _provision_workspace_agent(
            client,
            system=live_open_talon_mcp_system,
            permissions=["organization.read", "workspace.list", "workspace.read"],
        )
        admin_actor = _actor_payload(display_name="MCP Live Admin")
        tool_name = f"live_catalog_tool_{uuid4().hex[:8]}"

        organization_tool = _json_request(
            client,
            "POST",
            f"/v1/organizations/{provisioned.organization_id}/tools",
            token=live_open_talon_mcp_system.admin_token,
            json_body={
                "actor": admin_actor,
                "name": tool_name,
                "description": "Live catalog tool that must stay outside MCP operations.",
                "metadata": {"system_test": True},
            },
        )
        _json_request(
            client,
            "PUT",
            f"/v1/workspaces/{provisioned.workspace_id}/tools/{organization_tool['tool_id']}",
            token=live_open_talon_mcp_system.admin_token,
            json_body={
                "actor": provisioned.workspace_actor,
                "enabled": True,
            },
        )

        workspace_detail = _json_request(
            client,
            "GET",
            f"/v1/workspaces/{provisioned.workspace_id}",
            token=live_open_talon_mcp_system.admin_token,
        )
        assert any(tool["name"] == tool_name for tool in workspace_detail["tools"])

        initialize = _mcp_request(
            client,
            token=provisioned.machine_token,
            method="initialize",
        )
        session_id = initialize.headers["Mcp-Session-Id"]
        _mcp_request(
            client,
            token=provisioned.machine_token,
            session_id=session_id,
            method="tools/call",
            params={
                "name": "session.set_scope",
                "arguments": {"scope": "workspace", "workspace_id": provisioned.workspace_id},
            },
            request_id=2,
        )
        visible_operations = _mcp_request(
            client,
            token=provisioned.machine_token,
            session_id=session_id,
            method="tools/list",
            request_id=3,
        ).json()["result"]["tools"]
        operation_names = {item["name"] for item in visible_operations}

        assert "threads.list" in operation_names
        assert tool_name not in operation_names


def test_mcp_live_system_compares_context_between_agents_with_different_permissions(
    live_open_talon_mcp_system: _LiveMcpSystem,
):
    with httpx.Client(base_url=live_open_talon_mcp_system.gateway_url, timeout=30.0) as client:
        workspace_context = _create_workspace_context(
            client,
            system=live_open_talon_mcp_system,
        )
        reader = _provision_workspace_agent(
            client,
            system=live_open_talon_mcp_system,
            permissions=["organization.read", "workspace.list", "workspace.read"],
            workspace_context=workspace_context,
        )
        manager = _provision_workspace_agent(
            client,
            system=live_open_talon_mcp_system,
            permissions=[
                "organization.read",
                "organization.members.read",
                "workspace.list",
                "workspace.read",
            ],
            workspace_context=workspace_context,
        )

        reader_org_snapshot = _mcp_context_snapshot(
            client,
            token=reader.machine_token,
            scope="organization",
            organization_id=workspace_context.organization_id,
            request_id_base=100,
        )
        manager_org_snapshot = _mcp_context_snapshot(
            client,
            token=manager.machine_token,
            scope="organization",
            organization_id=workspace_context.organization_id,
            request_id_base=200,
        )
        reader_workspace_snapshot = _mcp_context_snapshot(
            client,
            token=reader.machine_token,
            scope="workspace",
            workspace_id=workspace_context.workspace_id,
            request_id_base=300,
        )
        manager_workspace_snapshot = _mcp_context_snapshot(
            client,
            token=manager.machine_token,
            scope="workspace",
            workspace_id=workspace_context.workspace_id,
            request_id_base=400,
        )

        assert reader_org_snapshot["resource_uris"] == manager_org_snapshot["resource_uris"]
        assert (
            reader_org_snapshot["identity"]["agent_identity_id"]
            == reader.agent_identity_id
        )
        assert (
            manager_org_snapshot["identity"]["agent_identity_id"]
            == manager.agent_identity_id
        )
        assert (
            reader_org_snapshot["identity"]["agent_identity_id"]
            != manager_org_snapshot["identity"]["agent_identity_id"]
        )
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
        assert set(reader_org_snapshot["tool_names"]).issubset(
            set(manager_org_snapshot["tool_names"])
        )

        assert reader_workspace_snapshot["tool_names"] == manager_workspace_snapshot["tool_names"]
        assert "iam.agent_identities.list" not in reader_workspace_snapshot["tool_names"]
        assert "iam.agent_identities.list" not in manager_workspace_snapshot["tool_names"]
        assert reader_workspace_snapshot["permissions"]["workspace_participant_id"]
        assert manager_workspace_snapshot["permissions"]["workspace_participant_id"]
        assert reader_workspace_snapshot["scope"] == {
            "scope": "workspace",
            "workspace_id": workspace_context.workspace_id,
        }
        assert manager_workspace_snapshot["scope"] == {
            "scope": "workspace",
            "workspace_id": workspace_context.workspace_id,
        }
