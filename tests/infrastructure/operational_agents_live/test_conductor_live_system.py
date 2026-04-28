from __future__ import annotations

import json
import threading
from typing import Any, Callable
from urllib.error import HTTPError
from uuid import uuid4

import psycopg
import pytest

from .harnesses import (
    ConductorTaskHarnessHandler,
    ConductorTaskHarnessServer,
    ConductorTaskHarnessState,
)
from .helpers import (
    METHODICS_EXECUTION_GET_TOOL,
    METHODICS_RESOURCE_REQUEST_CREATE_TOOL,
    admin_token,
    direct_access_grants_enabled,
    gateway_url,
    human_client_id,
    initialize_mcp_session,
    json_request,
    live_actor,
    mcp_call,
    postgres_dsn,
    require_live_operational_agents,
    tool_call_rows,
    wait_for,
)


pytestmark = pytest.mark.integration


def _actor_from_participant(participant: dict[str, Any]) -> dict[str, Any]:
    actor = {
        "participant_id": participant["participant_id"],
        "participant_type": participant["participant_type"],
        "display_name": participant["display_name"],
    }
    for key in ("user_id", "description", "roles", "capabilities", "visibility_scope"):
        if participant.get(key) is not None:
            actor[key] = participant[key]
    return actor


def _expect_http_error(status_code: int, call: Callable[[], Any]) -> dict[str, Any]:
    with pytest.raises(HTTPError) as exc_info:
        call()
    assert exc_info.value.code == status_code
    body = exc_info.value.read().decode("utf-8", errors="replace")
    return json.loads(body) if body else {}


def _methodics_harness() -> dict[str, Any]:
    return {
        "version": 1,
        "summary": "Live Conductor test harness.",
        "methodology": {
            "ontology": "Workspace evidence, assignments, and verification checks.",
            "principles": ["Advance only when definition-of-done evidence exists."],
        },
        "methodics": [
            {
                "name": "Evidence-backed kickoff",
                "goal": "Coordinate a small workspace methodic with explicit evidence.",
                "steps": [
                    {
                        "instruction": "Collect the kickoff evidence checklist.",
                        "recommended_tool_patterns": ["evidence-checklist"],
                        "expected_artifacts": ["kickoff evidence checklist"],
                        "verification": ["Checklist request is visible as workspace evidence."],
                    }
                ],
                "success_criteria": ["The kickoff outcome has an accepted evidence record."],
            }
        ],
        "execution_rules": [
            {
                "name": "human-gated-resources",
                "instruction": (
                    "Propose resource attachment and wait for authorized human approval."
                ),
                "priority": "critical",
                "scope": "communication",
            }
        ],
        "metadata": {"system_test": True},
    }


def _conductor_participants(
    *,
    workspace_id: str,
    conductor_id: str,
) -> list[dict[str, Any]]:
    with psycopg.connect(postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    participant_id::text,
                    metadata,
                    status
                FROM participants
                WHERE workspace_id = %s
                  AND system_agent_id = %s
                ORDER BY created_at ASC
                """,
                (workspace_id, conductor_id),
            )
            rows = cur.fetchall()
    return [
        {"participant_id": participant_id, "metadata": metadata or {}, "status": status}
        for participant_id, metadata, status in rows
    ]


def _conductor_task_rows(
    *,
    workspace_id: str,
    conductor_id: str,
) -> list[dict[str, Any]]:
    with psycopg.connect(postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    task_id::text,
                    status,
                    metadata
                FROM tasks
                WHERE workspace_id = %s
                  AND metadata->>'target_system_agent_id' = %s
                ORDER BY created_at ASC
                """,
                (workspace_id, conductor_id),
            )
            rows = cur.fetchall()
    return [
        {"task_id": task_id, "status": status, "metadata": metadata or {}}
        for task_id, status, metadata in rows
    ]


def _resource_request_row(
    *,
    execution_id: str,
    title: str,
) -> dict[str, Any] | None:
    with psycopg.connect(postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    resource_request_id::text,
                    status,
                    title,
                    requested_by_system_agent_id::text
                FROM methodic_resource_requests
                WHERE execution_id = %s
                  AND title = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (execution_id, title),
            )
            row = cur.fetchone()
    if row is None:
        return None
    resource_request_id, status, title, requested_by_system_agent_id = row
    return {
        "resource_request_id": resource_request_id,
        "status": status,
        "title": title,
        "requested_by_system_agent_id": requested_by_system_agent_id,
    }


def test_conductor_live_executes_methodics_start_and_resource_gate():
    require_live_operational_agents()
    gateway = gateway_url()
    client_id = human_client_id()
    actor = live_actor(display_name="Conductor Live Admin")
    server: ConductorTaskHarnessServer | None = None
    server_thread: threading.Thread | None = None
    original_conductor_endpoint: dict[str, Any] | None = None
    conductor_id: str | None = None
    token: str | None = None

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
                    "slug": f"conductor-live-{suffix}",
                    "name": f"Conductor Live {suffix}",
                    "metadata": {"system_test": True},
                },
            )
            organization_id = str(organization["organization_id"])
            me = json_request("GET", f"{gateway}/v1/me", token=token)
            organization_members = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/members",
                token=token,
            )
            if not any(member["user_id"] == me["user_id"] for member in organization_members):
                json_request(
                    "POST",
                    f"{gateway}/v1/organizations/{organization_id}/members",
                    token=token,
                    payload={
                        "actor": actor,
                        "user_id": me["user_id"],
                        "role": "owner",
                        "metadata": {"system_test": True},
                    },
                )
            workspace_detail = json_request(
                "POST",
                f"{gateway}/v1/organizations/{organization_id}/workspaces",
                token=token,
                payload={
                    "name": f"Conductor Methodics {suffix}",
                    "description": "Live Conductor methodics execution workspace.",
                    "actor": actor,
                    "harness": _methodics_harness(),
                    "metadata": {"system_test": True},
                },
            )
            workspace_id = str(workspace_detail["workspace"]["workspace_id"])
            workspace_actor = _actor_from_participant(
                next(
                    participant
                    for participant in workspace_detail["participants"]
                    if participant["participant_type"] == "user"
                )
            )
            agents = json_request("GET", f"{gateway}/v1/agents", token=token)
            conductor = next(agent for agent in agents if agent["agent_key"] == "conductor")
            conductor_id = str(conductor["agent_id"])
            original_conductor_endpoint = conductor["endpoint"]

            assert _conductor_participants(
                workspace_id=workspace_id,
                conductor_id=conductor_id,
            ) == []

            error_body = _expect_http_error(
                409,
                lambda: json_request(
                    "POST",
                    f"{gateway}/v1/workspaces/{workspace_id}/methodics/executions",
                    token=token,
                    payload={
                        "actor": workspace_actor,
                        "target_goal": "Run the live methodics kickoff.",
                        "methodic_indexes": [0],
                        "metadata": {"system_test": True},
                    },
                ),
            )
            assert "Conductor must be attached" in error_body["detail"]

            def conductor_identity() -> dict[str, Any] | None:
                identities = json_request("GET", f"{gateway}/v1/iam/agent-identities", token=token)
                return next(
                    (
                        identity
                        for identity in identities
                        if identity["system_agent_id"] == conductor_id
                        and identity["status"] == "active"
                    ),
                    None,
                )

            assert wait_for(
                "Conductor machine identity bootstrap",
                conductor_identity,
                timeout_seconds=60.0,
                interval_seconds=1.0,
            )

            harness_state = ConductorTaskHarnessState()
            server = ConductorTaskHarnessServer(
                ("127.0.0.1", 0),
                ConductorTaskHarnessHandler,
                state=harness_state,
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            harness_url = f"http://127.0.0.1:{server.server_address[1]}/conductor"

            json_request(
                "PATCH",
                f"{gateway}/v1/agents/{conductor_id}",
                token=token,
                payload={
                    "actor": actor,
                    "endpoint": {
                        "kind": "remote",
                        "url": harness_url,
                        "model": conductor["endpoint"].get("model"),
                        "provider": "system-test-harness",
                    },
                    "metadata": {"system_test_harness": True},
                },
            )

            conductor_participant = json_request(
                "POST",
                f"{gateway}/v1/workspaces/{workspace_id}/agents",
                token=token,
                payload={"actor": workspace_actor, "agent_id": conductor_id},
            )
            routing = conductor_participant["metadata"]["task_routing"]
            assert routing["normal_message_fanout"] is False
            assert routing["accepted_task_kinds"] == [
                "methodics_execution_start",
                "methodics_step_coordinate",
                "methodics_step_verify",
                "methodics_resource_review",
            ]

            execution_detail = json_request(
                "POST",
                f"{gateway}/v1/workspaces/{workspace_id}/methodics/executions",
                token=token,
                payload={
                    "actor": workspace_actor,
                    "target_goal": "Run the live methodics kickoff.",
                    "methodic_indexes": [0],
                    "metadata": {"system_test": True},
                },
            )
            execution = execution_detail["execution"]
            execution_id = str(execution["execution_id"])
            thread_id = str(execution["thread_id"])
            first_step = execution_detail["steps"][0]
            assert execution["status"] == "running"
            assert execution["conductor_system_agent_id"] == conductor_id
            assert execution["methodics_snapshot"][0]["name"] == "Evidence-backed kickoff"
            assert first_step["status"] == "active"
            assert first_step["definition_of_done"] == [
                "Checklist request is visible as workspace evidence.",
                "The kickoff outcome has an accepted evidence record.",
            ]

            def methodics_start_task() -> dict[str, Any] | None:
                for row in _conductor_task_rows(
                    workspace_id=workspace_id,
                    conductor_id=conductor_id,
                ):
                    metadata = row["metadata"]
                    if metadata.get("methodic_execution_id") == execution_id:
                        return row
                return None

            task_row = wait_for(
                "Conductor methodics start task",
                methodics_start_task,
                timeout_seconds=30.0,
                interval_seconds=1.0,
            )
            assert task_row["metadata"]["task_kind"] == "methodics_execution_start"

            resource_request = wait_for(
                "Conductor-created methodics resource request",
                lambda: _resource_request_row(
                    execution_id=execution_id,
                    title="Attach evidence checklist tool",
                ),
                timeout_seconds=180.0,
                interval_seconds=2.0,
            )
            assert resource_request["status"] == "pending"
            assert resource_request["requested_by_system_agent_id"] == conductor_id
            assert wait_for(
                "Conductor deterministic harness completion",
                lambda: harness_state.request_count() >= 3,
                timeout_seconds=60.0,
                interval_seconds=1.0,
            )

            def completed_tool_calls() -> list[dict[str, Any]] | None:
                rows = tool_call_rows(
                    thread_id=thread_id,
                    system_agent_id=conductor_id,
                    tool_names=(
                        METHODICS_EXECUTION_GET_TOOL,
                        METHODICS_RESOURCE_REQUEST_CREATE_TOOL,
                    ),
                )
                by_name = {row["tool_name"]: row for row in rows}
                if {
                    METHODICS_EXECUTION_GET_TOOL,
                    METHODICS_RESOURCE_REQUEST_CREATE_TOOL,
                } <= set(by_name) and all(row["status"] == "completed" for row in by_name.values()):
                    return rows
                return None

            tool_calls = wait_for(
                "Conductor methodics MCP tool calls",
                completed_tool_calls,
                timeout_seconds=60.0,
                interval_seconds=1.0,
            )
            assert all(
                row["metadata"].get("tool_source") == "agent_internal_mcp_server"
                for row in tool_calls
            )

            approved = json_request(
                "POST",
                (
                    f"{gateway}/v1/workspaces/{workspace_id}/methodics/resource-requests/"
                    f"{resource_request['resource_request_id']}/approve"
                ),
                token=token,
                payload={
                    "actor": workspace_actor,
                    "reason": "Approved by live test administrator.",
                    "metadata": {"system_test": True},
                },
            )
            assert approved["status"] == "approved"

            manual_request = json_request(
                "POST",
                (
                    f"{gateway}/v1/workspaces/{workspace_id}/methodics/executions/"
                    f"{execution_id}/resource-requests"
                ),
                token=token,
                payload={
                    "actor": workspace_actor,
                    "step_execution_id": first_step["step_execution_id"],
                    "resource_kind": "user",
                    "action": "invite",
                    "title": "Invite methodics reviewer",
                    "description": "Manual live-test resource request.",
                    "required_permission": "workspace.participants.write",
                    "payload": {"collaboration_role": "reviewer"},
                    "metadata": {"system_test": True},
                },
            )
            assert manual_request["status"] == "pending"
            rejected = json_request(
                "POST",
                (
                    f"{gateway}/v1/workspaces/{workspace_id}/methodics/resource-requests/"
                    f"{manual_request['resource_request_id']}/reject"
                ),
                token=token,
                payload={
                    "actor": workspace_actor,
                    "reason": "Rejected by live test administrator.",
                    "metadata": {"system_test": True},
                },
            )
            assert rejected["status"] == "rejected"

            session_id, initialize_payload = initialize_mcp_session(gateway, token)
            assert initialize_payload["result"]["protocolVersion"]
            set_scope, _ = mcp_call(
                gateway,
                token,
                method="tools/call",
                session_id=session_id,
                params={
                    "name": "session.set_scope",
                    "arguments": {"scope": "workspace", "workspace_id": workspace_id},
                },
            )
            assert set_scope["result"]["isError"] is False
            tools, _ = mcp_call(gateway, token, method="tools/list", session_id=session_id)
            tool_names = {item["name"] for item in tools["result"]["tools"]}
            assert {
                "methodics.executions.list",
                "methodics.executions.get",
                "methodics.executions.cancel",
                "methodics.resource_requests.approve",
                "methodics.resource_requests.create",
                "methodics.resource_requests.reject",
            } <= tool_names

            executions_list, _ = mcp_call(
                gateway,
                token,
                method="tools/call",
                session_id=session_id,
                params={"name": "methodics.executions.list", "arguments": {}},
                request_id="methodics-list",
            )
            assert executions_list["result"]["isError"] is False
            assert any(
                item["execution_id"] == execution_id
                for item in executions_list["result"]["structuredContent"]
            )

            execution_get, _ = mcp_call(
                gateway,
                token,
                method="tools/call",
                session_id=session_id,
                params={
                    "name": "methodics.executions.get",
                    "arguments": {"execution_id": execution_id},
                },
                request_id="methodics-get",
            )
            assert execution_get["result"]["isError"] is False
            resource_statuses = {
                item["title"]: item["status"]
                for item in execution_get["result"]["structuredContent"]["resource_requests"]
            }
            assert resource_statuses["Attach evidence checklist tool"] == "approved"
            assert resource_statuses["Invite methodics reviewer"] == "rejected"

            before_normal_message_task_ids = {
                row["task_id"]
                for row in _conductor_task_rows(
                    workspace_id=workspace_id,
                    conductor_id=conductor_id,
                )
            }
            thread_detail = json_request(
                "POST",
                f"{gateway}/v1/workspaces/{workspace_id}/threads",
                token=token,
                payload={"title": "Normal Workspace Discussion", "actor": workspace_actor},
            )
            json_request(
                "POST",
                f"{gateway}/v1/threads/{thread_detail['thread']['thread_id']}/messages",
                token=token,
                payload={
                    "actor": workspace_actor,
                    "content": "This ordinary workspace note must not fan out to Conductor.",
                    "visibility": "workspace",
                    "create_task": True,
                    "metadata": {"system_test": True},
                },
            )
            after_normal_message_task_ids = {
                row["task_id"]
                for row in _conductor_task_rows(
                    workspace_id=workspace_id,
                    conductor_id=conductor_id,
                )
            }
            assert after_normal_message_task_ids == before_normal_message_task_ids

            cancelled, _ = mcp_call(
                gateway,
                token,
                method="tools/call",
                session_id=session_id,
                params={
                    "name": "methodics.executions.cancel",
                    "arguments": {
                        "execution_id": execution_id,
                        "reason": "Live test complete.",
                        "metadata": {"system_test": True},
                    },
                },
                request_id="methodics-cancel",
            )
            assert cancelled["result"]["isError"] is False
            assert cancelled["result"]["structuredContent"]["execution"]["status"] == "cancelled"
        finally:
            if (
                original_conductor_endpoint is not None
                and conductor_id is not None
                and token is not None
            ):
                try:
                    json_request(
                        "PATCH",
                        f"{gateway}/v1/agents/{conductor_id}",
                        token=token,
                        payload={
                            "actor": actor,
                            "endpoint": original_conductor_endpoint,
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
