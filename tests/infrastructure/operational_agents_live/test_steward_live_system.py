from __future__ import annotations

import threading
from typing import Any
from uuid import uuid4

import pytest

from .harnesses import (
    StewardTaskHarnessHandler,
    StewardTaskHarnessServer,
    StewardTaskHarnessState,
)
from .helpers import (
    PROJECT_CREATE_TOOL,
    STEWARD_ORGANIZATION_CREATE_TOOL,
    WORKSPACE_CREATE_TOOL,
    admin_token,
    direct_access_grants_enabled,
    gateway_url,
    human_client_id,
    json_request,
    live_actor,
    require_live_operational_agents,
    steward_created_resource_rows,
    tool_call_rows,
    wait_for,
)


pytestmark = pytest.mark.integration


def test_steward_task_creates_organization_project_and_workspace_on_live_system():
    require_live_operational_agents()
    gateway = gateway_url()
    client_id = human_client_id()
    actor = live_actor()
    server: StewardTaskHarnessServer | None = None
    server_thread: threading.Thread | None = None
    original_steward_endpoint: dict[str, Any] | None = None
    steward_id: str | None = None
    system_base_id: str | None = None
    admin_user_id: str | None = None
    added_system_base_membership = False

    with direct_access_grants_enabled(client_id=client_id):
        try:
            token = admin_token(client_id=client_id)
            me = json_request("GET", f"{gateway}/v1/me", token=token)
            admin_user_id = str(me["user_id"])
            organizations = json_request("GET", f"{gateway}/v1/organizations", token=token)
            system_base = next(item for item in organizations if item["slug"] == "system-base")
            system_base_id = str(system_base["organization_id"])
            system_members = json_request(
                "GET",
                f"{gateway}/v1/organizations/{system_base_id}/members",
                token=token,
            )
            if not any(member["user_id"] == admin_user_id for member in system_members):
                json_request(
                    "POST",
                    f"{gateway}/v1/organizations/{system_base_id}/members",
                    token=token,
                    payload={
                        "actor": actor,
                        "user_id": admin_user_id,
                        "role": "owner",
                        "metadata": {"system_test": True},
                    },
                )
                added_system_base_membership = True
            system_projects = json_request(
                "GET",
                f"{gateway}/v1/organizations/{system_base_id}/projects",
                token=token,
            )
            system_admin = next(
                item for item in system_projects if item["slug"] == "administration"
            )
            system_workspaces = json_request(
                "GET",
                f"{gateway}/v1/organizations/{system_base_id}/workspaces?project_id={system_admin['project_id']}",
                token=token,
            )
            system_operations = next(
                workspace
                for workspace in system_workspaces
                if workspace["name"] == "System Operations"
            )
            agents = json_request("GET", f"{gateway}/v1/agents", token=token)
            steward = next(agent for agent in agents if agent["agent_key"] == "steward")
            steward_id = str(steward["agent_id"])
            original_steward_endpoint = steward["endpoint"]

            def steward_identity() -> dict[str, Any] | None:
                identities = json_request(
                    "GET",
                    f"{gateway}/v1/iam/agent-identities",
                    token=token,
                )
                return next(
                    (
                        identity
                        for identity in identities
                        if identity["system_agent_id"] == steward_id
                        and identity["status"] == "active"
                    ),
                    None,
                )

            assert wait_for(
                "Steward machine identity bootstrap",
                steward_identity,
                timeout_seconds=60.0,
                interval_seconds=1.0,
            )

            json_request(
                "PATCH",
                f"{gateway}/v1/workspaces/{system_operations['workspace_id']}/participants/{actor['participant_id']}/role",
                token=token,
                payload={
                    "actor": actor,
                    "role": "admin",
                    "description": "Live system-level operational-agent task test administrator.",
                    "capabilities": ["live-system-test"],
                },
            )

            suffix = uuid4().hex[:10]
            organization_slug = f"steward-created-{suffix}"
            organization_name = f"Steward Created Organization {suffix}"
            project_slug = f"steward-project-{suffix}"
            project_name = f"Steward Created Project {suffix}"
            workspace_name = f"Steward Created Workspace {suffix}"
            harness_state = StewardTaskHarnessState(
                steward_id=steward_id,
                organization_slug=organization_slug,
                organization_name=organization_name,
                project_slug=project_slug,
                project_name=project_name,
                workspace_name=workspace_name,
            )
            server = StewardTaskHarnessServer(
                ("127.0.0.1", 0),
                StewardTaskHarnessHandler,
                state=harness_state,
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            harness_url = f"http://127.0.0.1:{server.server_address[1]}/steward"

            json_request(
                "PATCH",
                f"{gateway}/v1/agents/{steward_id}",
                token=token,
                payload={
                    "actor": actor,
                    "endpoint": {
                        "kind": "remote",
                        "url": harness_url,
                        "model": steward["endpoint"].get("model"),
                        "provider": "system-test-harness",
                    },
                    "metadata": {"system_test_harness": True},
                },
            )

            thread_detail = json_request(
                "POST",
                f"{gateway}/v1/workspaces/{system_operations['workspace_id']}/threads",
                token=token,
                payload={
                    "title": "Steward Organization Project Workspace Task",
                    "actor": actor,
                },
            )
            thread_id = str(thread_detail["thread"]["thread_id"])
            json_request(
                "POST",
                f"{gateway}/v1/threads/{thread_id}/messages",
                token=token,
                payload={
                    "actor": actor,
                    "content": (
                        f"Steward, create organization `{organization_name}` with slug "
                        f"`{organization_slug}`, then create project `{project_name}` with "
                        f"slug `{project_slug}`, then create workspace `{workspace_name}`."
                    ),
                    "visibility": "workspace",
                    "target_system_agent_id": steward_id,
                    "task_instructions": [
                        "Use only your private Open Talon control-plane MCP tools.",
                        "Create exactly one organization, one project, and one workspace.",
                        "You must be recorded as creator on all three created resources.",
                    ],
                    "metadata": {"system_test": True},
                },
            )

            assert wait_for(
                "Steward harness request",
                harness_state.latest_request,
                timeout_seconds=120.0,
                interval_seconds=1.0,
            )

            def final_steward_message() -> dict[str, Any] | None:
                timeline = json_request(
                    "GET",
                    f"{gateway}/v1/threads/{thread_id}/timeline",
                    token=token,
                )
                for message in reversed(timeline["messages"]):
                    actor_ref = message.get("actor") or {}
                    content = str(message.get("content") or "")
                    if (
                        actor_ref.get("type") == "agent"
                        and organization_name in content
                        and project_name in content
                        and workspace_name in content
                    ):
                        return message
                return None

            assert wait_for(
                "Steward final organization/project/workspace message",
                final_steward_message,
                timeout_seconds=180.0,
                interval_seconds=2.0,
            )

            organizations_after = json_request("GET", f"{gateway}/v1/organizations", token=token)
            created_organization = next(
                item for item in organizations_after if item["slug"] == organization_slug
            )
            assert created_organization["created_by"] == steward_id

            projects_after = json_request(
                "GET",
                f"{gateway}/v1/organizations/{created_organization['organization_id']}/projects",
                token=token,
            )
            created_project = next(item for item in projects_after if item["slug"] == project_slug)
            assert created_project["created_by"] == steward_id
            assert created_project["creator_system_agent_id"] == steward_id

            workspaces_after = json_request(
                "GET",
                f"{gateway}/v1/organizations/{created_organization['organization_id']}/workspaces?project_id={created_project['project_id']}",
                token=token,
            )
            created_workspace = next(
                workspace for workspace in workspaces_after if workspace["name"] == workspace_name
            )
            assert created_workspace["created_by"] == steward_id
            assert created_workspace["creator_user_id"] is None
            assert created_workspace["creator_system_agent_id"] == steward_id
            assert created_workspace["metadata"]["created_by"] == steward_id
            assert created_workspace["metadata"]["creator_system_agent_id"] == steward_id

            creator_rows = steward_created_resource_rows(
                organization_slug=organization_slug,
                project_slug=project_slug,
                workspace_name=workspace_name,
            )
            assert creator_rows == {
                "organization_id": created_organization["organization_id"],
                "organization_created_by": steward_id,
                "project_id": created_project["project_id"],
                "project_created_by": steward_id,
                "project_creator_system_agent_id": steward_id,
                "workspace_id": created_workspace["workspace_id"],
                "workspace_created_by": steward_id,
                "workspace_creator_user_id": None,
                "workspace_creator_system_agent_id": steward_id,
                "workspace_metadata": created_workspace["metadata"],
            }

            expected_tools = {
                STEWARD_ORGANIZATION_CREATE_TOOL,
                PROJECT_CREATE_TOOL,
                WORKSPACE_CREATE_TOOL,
            }

            def completed_tool_calls() -> list[dict[str, Any]] | None:
                rows = tool_call_rows(
                    thread_id=thread_id,
                    system_agent_id=steward_id,
                    tool_names=tuple(sorted(expected_tools)),
                )
                by_name = {row["tool_name"]: row for row in rows}
                if expected_tools <= set(by_name) and all(
                    row["status"] == "completed" for row in by_name.values()
                ):
                    return rows
                return None

            tool_calls = wait_for(
                "Steward organization/project/workspace MCP tool calls",
                completed_tool_calls,
                timeout_seconds=60.0,
                interval_seconds=1.0,
            )
            assert {row["tool_name"] for row in tool_calls} == expected_tools
            assert all(
                row["metadata"].get("tool_source") == "agent_internal_mcp_server"
                for row in tool_calls
            )
            remote_names = {row["metadata"].get("mcp_tool_name") for row in tool_calls}
            assert remote_names == {
                "organizations.create",
                "projects.create",
                "workspaces.create",
            }
        finally:
            if original_steward_endpoint is not None and steward_id is not None:
                try:
                    json_request(
                        "PATCH",
                        f"{gateway}/v1/agents/{steward_id}",
                        token=admin_token(client_id=client_id),
                        payload={
                            "actor": actor,
                            "endpoint": original_steward_endpoint,
                            "metadata": {"system_test_harness": False},
                        },
                    )
                except Exception:
                    pass
            if server is not None:
                server.shutdown()
                server.server_close()
            if server_thread is not None:
                server_thread.join(timeout=5.0)
            if (
                added_system_base_membership
                and system_base_id is not None
                and admin_user_id is not None
            ):
                try:
                    json_request(
                        "DELETE",
                        f"{gateway}/v1/organizations/{system_base_id}/members/{admin_user_id}",
                        token=admin_token(client_id=client_id),
                        payload={"actor": actor},
                    )
                except Exception:
                    pass
