from __future__ import annotations

import json
import threading
from typing import Any, Callable
from urllib.error import HTTPError
from uuid import uuid4

import psycopg
import pytest

from .harnesses import (
    ConductorFullLoopHarnessState,
    ConductorTaskHarnessHandler,
    ConductorTaskHarnessServer,
    ConductorTaskHarnessState,
)
from .helpers import (
    METHODICS_ASSIGNMENT_CREATE_TOOL,
    METHODICS_EXECUTION_GET_TOOL,
    METHODICS_RESOURCE_REQUEST_CREATE_TOOL,
    METHODICS_STEP_EVALUATE_TOOL,
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


def _methodics_loop_harness() -> dict[str, Any]:
    return {
        "version": 1,
        "summary": "Live Conductor full execution loop harness.",
        "methodology": {
            "ontology": "Workspace requirements, readiness evidence, assignments, and DoD checks.",
            "principles": [
                "Assign every active step before verification.",
                "Advance only after evidence satisfies the step definition of done.",
            ],
        },
        "methodics": [
            {
                "name": "Evidence-backed launch loop",
                "goal": "Complete a two-step methodics execution with a rework loop.",
                "steps": [
                    {
                        "instruction": "Collect requirements evidence for launch.",
                        "expected_artifacts": ["requirements evidence note"],
                        "verification": ["Requirements evidence includes measurable acceptance criteria."],
                    },
                    {
                        "instruction": "Verify readiness and produce final report.",
                        "expected_artifacts": ["readiness verification report"],
                        "verification": ["Readiness report satisfies the final definition of done."],
                    },
                ],
                "success_criteria": ["Final execution report confirms all steps passed."],
            }
        ],
        "execution_rules": [
            {
                "name": "dod-before-advance",
                "instruction": "Record DoD checks before progressing to the next step.",
                "priority": "critical",
                "scope": "validation",
            }
        ],
        "metadata": {"system_test": True, "full_loop": True},
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


def _methodic_execution_summary(*, execution_id: str) -> dict[str, Any] | None:
    with psycopg.connect(postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    execution.status,
                    execution.current_step_execution_id::text,
                    execution.metadata,
                    step.step_execution_id::text,
                    step.step_index,
                    step.status,
                    step.evidence_refs,
                    assignment.assignment_id::text,
                    assignment.assignment_kind,
                    assignment.status,
                    assignment.title,
                    assignment.metadata,
                    ch.check_id::text,
                    ch.status,
                    ch.reason,
                    ch.metadata
                FROM methodic_executions AS execution
                LEFT JOIN methodic_execution_steps AS step
                  ON step.execution_id = execution.execution_id
                LEFT JOIN methodic_execution_assignments AS assignment
                  ON assignment.execution_id = execution.execution_id
                LEFT JOIN methodic_execution_checks AS ch
                  ON ch.execution_id = execution.execution_id
                WHERE execution.execution_id = %s
                ORDER BY step.step_index ASC, assignment.created_at ASC, ch.created_at ASC
                """,
                (execution_id,),
            )
            rows = cur.fetchall()
    if not rows:
        return None
    status, current_step_execution_id, metadata = rows[0][0], rows[0][1], rows[0][2] or {}
    steps: dict[str, dict[str, Any]] = {}
    assignments: dict[str, dict[str, Any]] = {}
    checks: dict[str, dict[str, Any]] = {}
    for row in rows:
        (
            _status,
            _current_step_execution_id,
            _metadata,
            step_execution_id,
            step_index,
            step_status,
            evidence_refs,
            assignment_id,
            assignment_kind,
            assignment_status,
            assignment_title,
            assignment_metadata,
            check_id,
            check_status,
            check_reason,
            check_metadata,
        ) = row
        if step_execution_id is not None:
            steps[step_execution_id] = {
                "step_execution_id": step_execution_id,
                "step_index": step_index,
                "status": step_status,
                "evidence_refs": evidence_refs or [],
            }
        if assignment_id is not None:
            assignments[assignment_id] = {
                "assignment_id": assignment_id,
                "assignment_kind": assignment_kind,
                "status": assignment_status,
                "title": assignment_title,
                "metadata": assignment_metadata or {},
            }
        if check_id is not None:
            checks[check_id] = {
                "check_id": check_id,
                "status": check_status,
                "reason": check_reason,
                "metadata": check_metadata or {},
            }
    return {
        "status": status,
        "current_step_execution_id": current_step_execution_id,
        "metadata": metadata,
        "steps": list(steps.values()),
        "assignments": list(assignments.values()),
        "checks": list(checks.values()),
    }


def _final_report_message(*, thread_id: str) -> dict[str, Any] | None:
    with psycopg.connect(postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    message_id::text,
                    content,
                    metadata
                FROM timeline_messages
                WHERE thread_id = %s
                  AND metadata->>'methodics_final_report' = 'true'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (thread_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    message_id, content, metadata = row
    return {"message_id": message_id, "content": content, "metadata": metadata or {}}


def test_conductor_live_completes_full_methodics_execution_loop():
    require_live_operational_agents()
    gateway = gateway_url()
    client_id = human_client_id()
    actor = live_actor(display_name="Conductor Full Loop Admin")
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
                    "slug": f"conductor-loop-{suffix}",
                    "name": f"Conductor Loop {suffix}",
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
                    "name": f"Conductor Full Loop {suffix}",
                    "description": "Live Conductor full methodics execution workspace.",
                    "actor": actor,
                    "harness": _methodics_loop_harness(),
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

            harness_state = ConductorFullLoopHarnessState()
            server = ConductorTaskHarnessServer(
                ("127.0.0.1", 0),
                ConductorTaskHarnessHandler,
                state=harness_state,
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            harness_url = f"http://127.0.0.1:{server.server_address[1]}/conductor-loop"

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
            assert conductor_participant["metadata"]["task_routing"]["normal_message_fanout"] is False

            execution_detail = json_request(
                "POST",
                f"{gateway}/v1/workspaces/{workspace_id}/methodics/executions",
                token=token,
                payload={
                    "actor": workspace_actor,
                    "target_goal": "Run the full live methodics loop.",
                    "methodic_indexes": [0],
                    "metadata": {"system_test": True, "full_loop": True},
                },
            )
            execution = execution_detail["execution"]
            execution_id = str(execution["execution_id"])
            thread_id = str(execution["thread_id"])
            assert execution["status"] == "running"
            assert len(execution_detail["steps"]) == 2
            assert execution_detail["steps"][0]["status"] == "active"
            assert execution_detail["steps"][1]["status"] == "pending"

            completed = wait_for(
                "completed Conductor full methodics execution loop",
                lambda: (
                    summary
                    if (summary := _methodic_execution_summary(execution_id=execution_id))
                    and summary["status"] == "completed"
                    and len(summary["checks"]) >= 3
                    else None
                ),
                timeout_seconds=240.0,
                interval_seconds=2.0,
            )

            assert completed["current_step_execution_id"] is None
            step_statuses = {
                item["step_index"]: item["status"] for item in completed["steps"]
            }
            assert step_statuses == {0: "passed", 1: "passed"}
            outcomes = [check["metadata"].get("outcome") for check in completed["checks"]]
            assert outcomes.count("rework") == 1
            assert outcomes.count("passed") >= 2
            assignment_titles = {assignment["title"] for assignment in completed["assignments"]}
            assert "Collect launch requirements evidence" in assignment_titles
            assert "Produce readiness verification report" in assignment_titles
            assignment_kinds = [assignment["assignment_kind"] for assignment in completed["assignments"]]
            assert assignment_kinds.count("manual") >= 2
            assert assignment_kinds.count("agent_task") >= 3
            assert "Final execution report" in completed["metadata"]["final_report"]

            report = wait_for(
                "Conductor final execution report message",
                lambda: _final_report_message(thread_id=thread_id),
                timeout_seconds=60.0,
                interval_seconds=1.0,
            )
            assert "all methodics steps passed after one rework loop" in report["content"]

            task_rows = _conductor_task_rows(
                workspace_id=workspace_id,
                conductor_id=conductor_id,
            )
            task_kinds = [row["metadata"].get("task_kind") for row in task_rows]
            assert "methodics_execution_start" in task_kinds
            assert task_kinds.count("methodics_step_coordinate") >= 2

            assert wait_for(
                "Conductor full-loop deterministic harness requests",
                lambda: harness_state.request_count() >= 9,
                timeout_seconds=60.0,
                interval_seconds=1.0,
            )

            def completed_tool_calls() -> list[dict[str, Any]] | None:
                rows = tool_call_rows(
                    thread_id=thread_id,
                    system_agent_id=conductor_id,
                    tool_names=(
                        METHODICS_EXECUTION_GET_TOOL,
                        METHODICS_ASSIGNMENT_CREATE_TOOL,
                        METHODICS_STEP_EVALUATE_TOOL,
                    ),
                )
                by_name: dict[str, list[dict[str, Any]]] = {}
                for row in rows:
                    by_name.setdefault(row["tool_name"], []).append(row)
                expected = {
                    METHODICS_EXECUTION_GET_TOOL,
                    METHODICS_ASSIGNMENT_CREATE_TOOL,
                    METHODICS_STEP_EVALUATE_TOOL,
                }
                if expected <= set(by_name) and all(
                    any(row["status"] == "completed" for row in by_name[tool_name])
                    for tool_name in expected
                ):
                    return rows
                return None

            tool_calls = wait_for(
                "Conductor full-loop MCP tool calls",
                completed_tool_calls,
                timeout_seconds=60.0,
                interval_seconds=1.0,
            )
            assert all(
                row["metadata"].get("tool_source") == "agent_internal_mcp_server"
                for row in tool_calls
            )
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
                "methodics.assignments.create",
                "methodics.steps.evaluate",
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
            assert execution_get["result"]["structuredContent"]["execution"]["status"] == "running"
            assert (
                execution_get["result"]["structuredContent"]["execution"]["current_step_execution_id"]
                == first_step["step_execution_id"]
            )
            assert execution_get["result"]["structuredContent"]["steps"][0]["status"] == "active"
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
