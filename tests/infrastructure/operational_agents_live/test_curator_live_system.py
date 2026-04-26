from __future__ import annotations

import threading
from typing import Any
from uuid import uuid4

import pytest

from .harnesses import (
    CuratorTaskHarnessHandler,
    CuratorTaskHarnessServer,
    CuratorTaskHarnessState,
)
from .helpers import (
    PROJECT_CREATE_TOOL,
    WORKSPACE_CREATE_TOOL,
    admin_token,
    direct_access_grants_enabled,
    gateway_url,
    human_client_id,
    json_request,
    live_actor,
    require_live_operational_agents,
    tool_call_rows,
    wait_for,
)


pytestmark = pytest.mark.integration


def test_curator_task_creates_project_and_workspace_on_live_system():
    require_live_operational_agents()
    gateway = gateway_url()
    client_id = human_client_id()
    server: CuratorTaskHarnessServer | None = None
    server_thread: threading.Thread | None = None
    original_curator_endpoint: dict[str, Any] | None = None
    curator_id: str | None = None
    organization_id: str | None = None
    actor = live_actor()

    with direct_access_grants_enabled(client_id=client_id):
        try:
            token = admin_token(client_id=client_id)
            suffix = uuid4().hex[:10]
            organization = json_request(
                "POST",
                f"{gateway}/v1/organizations",
                token=token,
                payload={
                    "actor": actor,
                    "slug": f"operational-task-{suffix}",
                    "name": f"Operational Task {suffix}",
                    "metadata": {"system_test": True},
                },
            )
            organization_id = str(organization["organization_id"])
            org_projects = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/projects",
                token=token,
            )
            org_admin = next(item for item in org_projects if item["slug"] == "administration")
            org_workspaces = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/workspaces?project_id={org_admin['project_id']}",
                token=token,
            )
            org_operations = next(
                workspace
                for workspace in org_workspaces
                if workspace["name"] == "Organization Operations"
            )
            agents = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/agents",
                token=token,
            )
            curator = next(agent for agent in agents if agent["agent_key"] == "curator")
            curator_id = str(curator["agent_id"])
            original_curator_endpoint = curator["endpoint"]

            def curator_identity() -> dict[str, Any] | None:
                identities = json_request(
                    "GET",
                    f"{gateway}/v1/organizations/{organization_id}/iam/agent-identities",
                    token=token,
                )
                return next(
                    (
                        identity
                        for identity in identities
                        if identity["system_agent_id"] == curator_id
                        and identity["status"] == "active"
                    ),
                    None,
                )

            assert wait_for(
                "Curator machine identity bootstrap",
                curator_identity,
                timeout_seconds=60.0,
                interval_seconds=1.0,
            )

            json_request(
                "PATCH",
                f"{gateway}/v1/workspaces/{org_operations['workspace_id']}/participants/{actor['participant_id']}/role",
                token=token,
                payload={
                    "actor": actor,
                    "role": "admin",
                    "description": "Live operational-agent task test administrator.",
                    "capabilities": ["live-system-test"],
                },
            )

            project_slug = f"curator-created-{suffix}"
            project_name = f"Curator Created Project {suffix}"
            workspace_name = f"Curator Created Workspace {suffix}"
            harness_state = CuratorTaskHarnessState(
                organization_id=organization_id,
                project_slug=project_slug,
                project_name=project_name,
                workspace_name=workspace_name,
            )
            server = CuratorTaskHarnessServer(
                ("127.0.0.1", 0),
                CuratorTaskHarnessHandler,
                state=harness_state,
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            harness_url = f"http://127.0.0.1:{server.server_address[1]}/curator"

            json_request(
                "PATCH",
                f"{gateway}/v1/organizations/{organization_id}/agents/{curator_id}",
                token=token,
                payload={
                    "actor": actor,
                    "endpoint": {
                        "kind": "remote",
                        "url": harness_url,
                        "model": curator["endpoint"].get("model"),
                        "provider": "system-test-harness",
                    },
                    "metadata": {"system_test_harness": True},
                },
            )

            thread_detail = json_request(
                "POST",
                f"{gateway}/v1/workspaces/{org_operations['workspace_id']}/threads",
                token=token,
                payload={
                    "title": "Curator Project And Workspace Task",
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
                        f"Curator, create project `{project_name}` with slug `{project_slug}`, "
                        f"then create workspace `{workspace_name}` inside that project."
                    ),
                    "visibility": "workspace",
                    "target_system_agent_id": curator_id,
                    "task_instructions": [
                        "Use only your private Open Talon control-plane MCP tools.",
                        "Create exactly one project and exactly one workspace for this task instance.",
                    ],
                    "metadata": {"system_test": True},
                },
            )

            assert wait_for(
                "Curator harness request",
                harness_state.latest_request,
                timeout_seconds=120.0,
                interval_seconds=1.0,
            )

            def final_curator_message() -> dict[str, Any] | None:
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
                        and project_name in content
                        and workspace_name in content
                    ):
                        return message
                return None

            assert wait_for(
                "Curator final project/workspace message",
                final_curator_message,
                timeout_seconds=180.0,
                interval_seconds=2.0,
            )

            projects_after = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/projects",
                token=token,
            )
            created_project = next(item for item in projects_after if item["slug"] == project_slug)
            workspaces_after = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/workspaces?project_id={created_project['project_id']}",
                token=token,
            )
            assert any(workspace["name"] == workspace_name for workspace in workspaces_after)

            def completed_tool_calls() -> list[dict[str, Any]] | None:
                rows = tool_call_rows(
                    thread_id=thread_id,
                    system_agent_id=curator_id,
                    tool_names=(
                        PROJECT_CREATE_TOOL,
                        WORKSPACE_CREATE_TOOL,
                    ),
                )
                by_name = {row["tool_name"]: row for row in rows}
                if {PROJECT_CREATE_TOOL, WORKSPACE_CREATE_TOOL} <= set(by_name) and all(
                    row["status"] == "completed" for row in by_name.values()
                ):
                    return rows
                return None

            tool_calls = wait_for(
                "Curator project/workspace MCP tool calls",
                completed_tool_calls,
                timeout_seconds=60.0,
                interval_seconds=1.0,
            )
            assert {row["tool_name"] for row in tool_calls} == {
                PROJECT_CREATE_TOOL,
                WORKSPACE_CREATE_TOOL,
            }
            assert all(
                row["metadata"].get("tool_source") == "agent_internal_mcp_server"
                for row in tool_calls
            )
        finally:
            if (
                original_curator_endpoint is not None
                and curator_id is not None
                and organization_id is not None
            ):
                try:
                    json_request(
                        "PATCH",
                        f"{gateway}/v1/organizations/{organization_id}/agents/{curator_id}",
                        token=admin_token(client_id=client_id),
                        payload={
                            "actor": actor,
                            "endpoint": original_curator_endpoint,
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
