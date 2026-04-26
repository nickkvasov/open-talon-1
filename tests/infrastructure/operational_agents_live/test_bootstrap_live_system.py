from __future__ import annotations

import time
from uuid import uuid4

import pytest

from .helpers import (
    admin_token,
    direct_access_grants_enabled,
    gateway_url,
    human_client_id,
    initialize_mcp_session,
    json_request,
    live_actor,
    mcp_call,
    require_live_operational_agents,
)


pytestmark = pytest.mark.integration


def test_operational_agents_bootstrap_on_live_system():
    require_live_operational_agents()
    gateway = gateway_url()
    client_id = human_client_id()

    with direct_access_grants_enabled(client_id=client_id):
        token = admin_token(client_id=client_id)
        deadline = time.time() + 60
        system_base = None
        while time.time() < deadline:
            organizations = json_request("GET", f"{gateway}/v1/organizations", token=token)
            system_base = next(
                (item for item in organizations if item["slug"] == "system-base"),
                None,
            )
            if system_base is not None:
                break
            time.sleep(2)
        assert system_base is not None

        projects = json_request(
            "GET",
            f"{gateway}/v1/organizations/{system_base['organization_id']}/projects",
            token=token,
        )
        administration = next(item for item in projects if item["slug"] == "administration")
        workspaces = json_request(
            "GET",
            f"{gateway}/v1/organizations/{system_base['organization_id']}/workspaces?project_id={administration['project_id']}",
            token=token,
        )
        assert any(workspace["name"] == "System Operations" for workspace in workspaces)

        suffix = uuid4().hex[:10]
        actor = live_actor()
        organization = json_request(
            "POST",
            f"{gateway}/v1/organizations",
            token=token,
            payload={
                "actor": actor,
                "slug": f"operational-live-{suffix}",
                "name": f"Operational Live {suffix}",
            },
        )
        org_projects = json_request(
            "GET",
            f"{gateway}/v1/organizations/{organization['organization_id']}/projects",
            token=token,
        )
        org_admin = next(item for item in org_projects if item["slug"] == "administration")
        org_workspaces = json_request(
            "GET",
            f"{gateway}/v1/organizations/{organization['organization_id']}/workspaces?project_id={org_admin['project_id']}",
            token=token,
        )
        org_operations = next(
            workspace
            for workspace in org_workspaces
            if workspace["name"] == "Organization Operations"
        )
        agents = json_request(
            "GET",
            f"{gateway}/v1/organizations/{organization['organization_id']}/agents",
            token=token,
        )
        curator = next(agent for agent in agents if agent["agent_key"] == "curator")
        assert curator["role"] == "organization operations curator"
        json_request(
            "PATCH",
            f"{gateway}/v1/workspaces/{org_operations['workspace_id']}/participants/{actor['participant_id']}/role",
            token=token,
            payload={
                "actor": actor,
                "role": "admin",
                "description": "Live operational-agent test administrator.",
                "capabilities": ["live-system-test"],
            },
        )

        session_id, payload = initialize_mcp_session(gateway, token)
        assert payload["result"]["protocolVersion"]
        set_scope, _ = mcp_call(
            gateway,
            token,
            method="tools/call",
            session_id=session_id,
            params={
                "name": "session.set_scope",
                "arguments": {"scope": "workspace", "workspace_id": org_operations["workspace_id"]},
            },
        )
        assert set_scope["result"]["isError"] is False
        tools, _ = mcp_call(gateway, token, method="tools/list", session_id=session_id)
        tool_names = {item["name"] for item in tools["result"]["tools"]}
        assert "threads.messages.create" in tool_names
