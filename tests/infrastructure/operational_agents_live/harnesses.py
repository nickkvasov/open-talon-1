from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any

from .helpers import (
    METHODICS_ASSIGNMENT_CREATE_TOOL,
    METHODICS_EXECUTION_GET_TOOL,
    METHODICS_RESOURCE_REQUEST_CREATE_TOOL,
    METHODICS_STEP_EVALUATE_TOOL,
    PROJECT_CREATE_TOOL,
    STEWARD_ORGANIZATION_CREATE_TOOL,
    WORKSPACE_CREATE_TOOL,
)


def _structured_content(
    tool_results: list[dict[str, Any]],
    tool_name: str,
) -> dict[str, Any] | None:
    for tool_result in tool_results:
        if tool_result.get("tool_name") != tool_name:
            continue
        result = tool_result.get("result")
        if not isinstance(result, dict):
            continue
        output_payload = result.get("output_payload")
        if not isinstance(output_payload, dict):
            continue
        structured = output_payload.get("structuredContent")
        if isinstance(structured, dict):
            return structured
    return None


@dataclass
class CuratorTaskHarnessState:
    organization_id: str
    project_slug: str
    project_name: str
    workspace_name: str
    requests: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.requests.append(payload)

    def latest_request(self) -> dict[str, Any] | None:
        with self._lock:
            return self.requests[-1] if self.requests else None

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.record_request(payload)
        context = payload.get("context") if isinstance(payload, dict) else {}
        tool_results = context.get("tool_results") if isinstance(context, dict) else []
        if not isinstance(tool_results, list):
            tool_results = []
        project = _structured_content(tool_results, PROJECT_CREATE_TOOL)
        workspace_detail = _structured_content(
            tool_results,
            WORKSPACE_CREATE_TOOL,
        )
        mcp_scope = {
            "scope": "organization",
            "organization_id": self.organization_id,
        }
        if project is None:
            return {
                "stop_reason": "completed",
                "summary": "Creating the requested project through Curator control-plane MCP.",
                "tool_calls": [
                    {
                        "tool_name": PROJECT_CREATE_TOOL,
                        "arguments": {
                            "_mcp_scope": mcp_scope,
                            "slug": self.project_slug,
                            "name": self.project_name,
                            "description": "Created by the Curator live-system task test.",
                            "metadata": {
                                "system_test": True,
                                "source": "operational_agents_live_system",
                            },
                        },
                        "summary": "Create the requested organization project.",
                    }
                ],
            }
        if workspace_detail is None:
            return {
                "stop_reason": "completed",
                "summary": "Creating the requested workspace through Curator control-plane MCP.",
                "tool_calls": [
                    {
                        "tool_name": WORKSPACE_CREATE_TOOL,
                        "arguments": {
                            "_mcp_scope": mcp_scope,
                            "project_id": project["project_id"],
                            "name": self.workspace_name,
                            "description": "Created by the Curator live-system task test.",
                            "metadata": {
                                "system_test": True,
                                "source": "operational_agents_live_system",
                            },
                        },
                        "summary": "Create the requested workspace in the new project.",
                    }
                ],
            }
        workspace = workspace_detail.get("workspace", workspace_detail)
        return {
            "stop_reason": "completed",
            "message": (
                f"Created project `{project['name']}` and workspace "
                f"`{workspace['name']}` for this organization."
            ),
            "summary": "Curator created the requested project and workspace.",
        }


class CuratorTaskHarnessServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, *, state: CuratorTaskHarnessState):
        super().__init__(server_address, handler_class)
        self.state = state


class CuratorTaskHarnessHandler(BaseHTTPRequestHandler):
    server: CuratorTaskHarnessServer

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        body = json.dumps(self.server.state.handle(payload)).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@dataclass
class ConductorTaskHarnessState:
    requests: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.requests.append(payload)

    def latest_request(self) -> dict[str, Any] | None:
        with self._lock:
            return self.requests[-1] if self.requests else None

    def request_count(self) -> int:
        with self._lock:
            return len(self.requests)

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.record_request(payload)
        context = payload.get("context") if isinstance(payload, dict) else {}
        if not isinstance(context, dict):
            context = {}
        task = context.get("task") if isinstance(context, dict) else {}
        task_metadata = task.get("metadata") if isinstance(task, dict) else {}
        if not isinstance(task_metadata, dict):
            task_metadata = {}
        workspace = context.get("workspace") if isinstance(context, dict) else {}
        workspace_id = workspace.get("workspace_id") if isinstance(workspace, dict) else None
        mcp_scope = {
            "scope": "workspace",
            "workspace_id": workspace_id,
        }
        execution_id = task_metadata.get("methodic_execution_id")
        step_execution_id = task_metadata.get("methodic_execution_step_id")
        tool_results = context.get("tool_results")
        if not isinstance(tool_results, list):
            tool_results = []
        execution_detail = _structured_content(
            tool_results,
            METHODICS_EXECUTION_GET_TOOL,
        )
        resource_request = _structured_content(
            tool_results,
            METHODICS_RESOURCE_REQUEST_CREATE_TOOL,
        )
        if execution_detail is None:
            return {
                "stop_reason": "completed",
                "summary": "Inspecting the active methodics execution through Conductor MCP.",
                "tool_calls": [
                    {
                        "tool_name": METHODICS_EXECUTION_GET_TOOL,
                        "arguments": {
                            "_mcp_scope": mcp_scope,
                            "execution_id": execution_id,
                        },
                        "summary": "Read the active methodics execution snapshot.",
                    }
                ],
            }
        if resource_request is None:
            return {
                "stop_reason": "completed",
                "summary": "Requesting a human-gated resource for the active methodics step.",
                "tool_calls": [
                    {
                        "tool_name": METHODICS_RESOURCE_REQUEST_CREATE_TOOL,
                        "arguments": {
                            "_mcp_scope": mcp_scope,
                            "execution_id": execution_id,
                            "step_execution_id": step_execution_id,
                            "resource_kind": "tool",
                            "action": "attach",
                            "title": "Attach evidence checklist tool",
                            "description": "Needed to collect and verify step evidence.",
                            "required_permission": "workspace.tools.write",
                            "payload": {
                                "tool_name": "evidence-checklist",
                                "reason": "Conductor live test resource proposal.",
                            },
                            "metadata": {"system_test": True},
                        },
                        "summary": "Create a pending methodics resource request.",
                    }
                ],
            }
        return {
            "stop_reason": "completed",
            "message": "Methodics execution inspected and resource request proposed.",
            "summary": "Conductor inspected the execution and proposed the needed resource.",
        }


@dataclass
class ConductorFullLoopHarnessState:
    requests: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.requests.append(payload)

    def request_count(self) -> int:
        with self._lock:
            return len(self.requests)

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.record_request(payload)
        context = payload.get("context") if isinstance(payload, dict) else {}
        if not isinstance(context, dict):
            context = {}
        task = context.get("task") if isinstance(context, dict) else {}
        task_metadata = task.get("metadata") if isinstance(task, dict) else {}
        if not isinstance(task_metadata, dict):
            task_metadata = {}
        workspace = context.get("workspace") if isinstance(context, dict) else {}
        workspace_id = workspace.get("workspace_id") if isinstance(workspace, dict) else None
        execution_id = task_metadata.get("methodic_execution_id")
        mcp_scope = {"scope": "workspace", "workspace_id": workspace_id}
        tool_results = context.get("tool_results")
        if not isinstance(tool_results, list):
            tool_results = []

        # Let each DoD evaluation end the current task. Rework/progression creates the
        # next targeted Conductor task, which proves the execution loop across tasks.
        if _structured_content(tool_results, METHODICS_STEP_EVALUATE_TOOL) is not None:
            return {
                "stop_reason": "completed",
                "message": "Conductor recorded the step DoD evaluation.",
                "summary": "Conductor completed this methodics coordination turn.",
            }

        execution_detail = (
            _structured_content(tool_results, METHODICS_ASSIGNMENT_CREATE_TOOL)
            or _structured_content(tool_results, METHODICS_EXECUTION_GET_TOOL)
        )
        if execution_detail is None:
            return {
                "stop_reason": "completed",
                "summary": "Reading methodics execution state before coordinating the active step.",
                "tool_calls": [
                    {
                        "tool_name": METHODICS_EXECUTION_GET_TOOL,
                        "arguments": {
                            "_mcp_scope": mcp_scope,
                            "execution_id": execution_id,
                        },
                        "summary": "Read the active methodics execution.",
                    }
                ],
            }

        execution = execution_detail.get("execution", {})
        if execution.get("status") == "completed":
            return {
                "stop_reason": "completed",
                "message": "Methodics execution is complete.",
                "summary": "Conductor observed a completed methodics execution.",
            }

        current_step_id = execution.get("current_step_execution_id")
        steps = execution_detail.get("steps") or []
        assignments = execution_detail.get("assignments") or []
        checks = execution_detail.get("checks") or []
        current_step = next(
            (
                step
                for step in steps
                if step.get("step_execution_id") == current_step_id
            ),
            None,
        )
        if current_step is None:
            return {
                "stop_reason": "blocked_dependency",
                "message": "No active methodics step was available to coordinate.",
                "summary": "Conductor could not identify the current methodics step.",
            }

        step_execution_id = current_step["step_execution_id"]
        step_index = int(current_step.get("step_index", 0))
        manual_assignment_exists = any(
            assignment.get("assignment_kind") == "manual"
            and assignment.get("step_execution_id") == step_execution_id
            for assignment in assignments
        )
        step_outcomes = [
            check.get("metadata", {}).get("outcome")
            for check in checks
            if check.get("step_execution_id") == step_execution_id
        ]

        if step_index == 0 and not manual_assignment_exists:
            return {
                "stop_reason": "completed",
                "summary": "Assigning the first methodics step to the workspace owner.",
                "tool_calls": [
                    {
                        "tool_name": METHODICS_ASSIGNMENT_CREATE_TOOL,
                        "arguments": {
                            "_mcp_scope": mcp_scope,
                            "execution_id": execution_id,
                            "step_execution_id": step_execution_id,
                            "assignment_kind": "manual",
                            "title": "Collect launch requirements evidence",
                            "instructions": (
                                "Create the requirements evidence note before DoD verification."
                            ),
                            "metadata": {
                                "system_test": True,
                                "loop_phase": "first_assignment",
                            },
                        },
                        "summary": "Create the first step assignment.",
                    }
                ],
            }
        if step_index == 0 and "rework" not in step_outcomes:
            return {
                "stop_reason": "completed",
                "summary": "Recording first-step DoD failure and requesting rework.",
                "tool_calls": [
                    {
                        "tool_name": METHODICS_STEP_EVALUATE_TOOL,
                        "arguments": {
                            "_mcp_scope": mcp_scope,
                            "execution_id": execution_id,
                            "step_execution_id": step_execution_id,
                            "outcome": "rework",
                            "reason": "Requirements evidence lacks acceptance criteria.",
                            "confidence": 0.42,
                            "evidence_refs": [
                                {
                                    "kind": "artifact",
                                    "id": "requirements-draft",
                                    "summary": "Draft lacks measurable acceptance criteria.",
                                }
                            ],
                            "rework_instructions": (
                                "Add measurable acceptance criteria and cite the updated artifact."
                            ),
                            "metadata": {
                                "system_test": True,
                                "loop_phase": "first_rework",
                            },
                        },
                        "summary": "Fail the first DoD check and request rework.",
                    }
                ],
            }
        if step_index == 0 and "passed" not in step_outcomes:
            return {
                "stop_reason": "completed",
                "summary": "Passing first-step DoD after rework evidence is available.",
                "tool_calls": [
                    {
                        "tool_name": METHODICS_STEP_EVALUATE_TOOL,
                        "arguments": {
                            "_mcp_scope": mcp_scope,
                            "execution_id": execution_id,
                            "step_execution_id": step_execution_id,
                            "outcome": "passed",
                            "reason": "Updated requirements evidence includes acceptance criteria.",
                            "confidence": 0.93,
                            "evidence_refs": [
                                {
                                    "kind": "artifact",
                                    "id": "requirements-evidence-v2",
                                    "summary": "Accepted requirements evidence.",
                                }
                            ],
                            "metadata": {
                                "system_test": True,
                                "loop_phase": "first_pass",
                            },
                        },
                        "summary": "Pass the first methodics step.",
                    }
                ],
            }
        if step_index == 1 and not manual_assignment_exists:
            return {
                "stop_reason": "completed",
                "summary": "Assigning the final readiness verification step.",
                "tool_calls": [
                    {
                        "tool_name": METHODICS_ASSIGNMENT_CREATE_TOOL,
                        "arguments": {
                            "_mcp_scope": mcp_scope,
                            "execution_id": execution_id,
                            "step_execution_id": step_execution_id,
                            "assignment_kind": "manual",
                            "title": "Produce readiness verification report",
                            "instructions": "Create readiness evidence for final DoD evaluation.",
                            "metadata": {
                                "system_test": True,
                                "loop_phase": "second_assignment",
                            },
                        },
                        "summary": "Create the final step assignment.",
                    }
                ],
            }
        return {
            "stop_reason": "completed",
            "summary": "Passing final methodics step and publishing the execution report.",
            "tool_calls": [
                {
                    "tool_name": METHODICS_STEP_EVALUATE_TOOL,
                    "arguments": {
                        "_mcp_scope": mcp_scope,
                        "execution_id": execution_id,
                        "step_execution_id": step_execution_id,
                        "outcome": "passed",
                        "reason": "Readiness report satisfies the final definition of done.",
                        "confidence": 0.96,
                        "evidence_refs": [
                            {
                                "kind": "artifact",
                                "id": "readiness-report",
                                "summary": "Final readiness evidence accepted.",
                            }
                        ],
                        "final_report": (
                            "Final execution report: requirements evidence and readiness "
                            "verification completed; all methodics steps passed after one rework loop."
                        ),
                        "metadata": {
                            "system_test": True,
                            "loop_phase": "final_pass",
                        },
                    },
                    "summary": "Pass the final methodics step and complete execution.",
                }
            ],
        }


class ConductorTaskHarnessServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, *, state: ConductorTaskHarnessState):
        super().__init__(server_address, handler_class)
        self.state = state


class ConductorTaskHarnessHandler(BaseHTTPRequestHandler):
    server: ConductorTaskHarnessServer

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        body = json.dumps(self.server.state.handle(payload)).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@dataclass
class MethodologistTaskHarnessState:
    context_pack_id: str
    source_id: str
    requests: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.requests.append(payload)

    def latest_request(self) -> dict[str, Any] | None:
        with self._lock:
            return self.requests[-1] if self.requests else None

    def saw_retriever_evidence(self) -> bool:
        payload = self.latest_request()
        if payload is None:
            return False
        serialized = json.dumps(payload, sort_keys=True)
        return all(
            marker in serialized
            for marker in (
                self.context_pack_id,
                f"source={self.source_id}",
                "chunk=0",
                "chunk=1",
                "retrieval_context_pack_id",
            )
        )

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.record_request(payload)
        if not self.saw_retriever_evidence():
            return {
                "stop_reason": "blocked_dependency",
                "message": "Retriever context-pack evidence was not visible to Methodologist.",
                "summary": "Methodologist live harness did not receive cited Retriever evidence.",
            }
        message = f"""
## Source Scope
Source-backed claims use Retriever context pack `{self.context_pack_id}` with citations [1] and [2].
The cited source is a bounded live-test methodology handbook excerpt from `source={self.source_id}`.

## Target Goal
Create a repeatable workspace approach for evidence-backed incident learning.

## Methodology Basis
Source-backed claim: the methodology basis is evidence-first diagnosis, shared interpretation, and explicit verification criteria [1].
Source-backed claim: the approach treats artifacts, decisions, and review records as the observable objects of work [2].

## Methodics
1. Source-backed methodic: collect cited evidence, record the decision context, and name the verification criteria before assigning implementation work [1].
2. Source-backed methodic: review produced artifacts against the stated criteria and capture gaps as follow-up work [2].

## Methods And Tools
Source-backed methods: evidence checklist, decision log, artifact review, and gap register [1][2].
Inferred/ideated items: use Open Talon Retriever context packs for evidence packets, workspace tasks for assignments, and Conductor for optional execution tracking.

## Actors
Source-backed actors: facilitator, contributor, and reviewer [2].
Inferred/ideated actors: Methodologist drafts the workspace template; Conductor can coordinate methodics execution only when attached and explicitly started.

## Workspace Template
Project: Evidence-backed incident learning.
Workspace: Incident Learning Methodics.
WorkspaceHarness.methodology: ontology is evidence, decisions, artifacts, actors, and verification criteria.
WorkspaceHarness.methodics: collect evidence, synthesize decision context, assign implementation, verify artifacts, and capture gaps.
WorkspaceHarness.execution_rules: require citations for source-derived claims and mark inferred tools explicitly.

## Evidence And Gaps
Source-backed claims are labeled above and cite [1] or [2].
Inferred/ideated items are labeled separately and are Open Talon implementation recommendations, not source claims.
Gap: the context pack is intentionally small, so the template should be revisited after more source pages are ingested.

## Next Actions
Create the workspace harness draft, attach needed retrieval corpora, and ask a human owner whether to attach Conductor for active execution.
""".strip()
        return {
            "stop_reason": "completed",
            "message": message,
            "summary": "Methodologist produced cited methodology extraction and workspace template.",
            "metadata": {
                "methodologist_live_test": True,
                "retrieval_context_pack_id": self.context_pack_id,
            },
        }


class MethodologistTaskHarnessServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address,
        handler_class,
        *,
        state: MethodologistTaskHarnessState,
    ):
        super().__init__(server_address, handler_class)
        self.state = state


class MethodologistTaskHarnessHandler(BaseHTTPRequestHandler):
    server: MethodologistTaskHarnessServer

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        body = json.dumps(self.server.state.handle(payload)).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@dataclass
class StewardTaskHarnessState:
    steward_id: str
    organization_slug: str
    organization_name: str
    project_slug: str
    project_name: str
    workspace_name: str
    requests: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.requests.append(payload)

    def latest_request(self) -> dict[str, Any] | None:
        with self._lock:
            return self.requests[-1] if self.requests else None

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.record_request(payload)
        context = payload.get("context") if isinstance(payload, dict) else {}
        tool_results = context.get("tool_results") if isinstance(context, dict) else []
        if not isinstance(tool_results, list):
            tool_results = []
        organization = _structured_content(
            tool_results,
            STEWARD_ORGANIZATION_CREATE_TOOL,
        )
        project = _structured_content(tool_results, PROJECT_CREATE_TOOL)
        workspace_detail = _structured_content(
            tool_results,
            WORKSPACE_CREATE_TOOL,
        )
        if organization is None:
            return {
                "stop_reason": "completed",
                "summary": "Creating the requested organization through Steward control-plane MCP.",
                "tool_calls": [
                    {
                        "tool_name": STEWARD_ORGANIZATION_CREATE_TOOL,
                        "arguments": {
                            "_mcp_scope": {"scope": "global"},
                            "slug": self.organization_slug,
                            "name": self.organization_name,
                            "description": "Created by the Steward live-system task test.",
                            "metadata": {
                                "system_test": True,
                                "source": "operational_agents_live_system",
                                "creator_system_agent_id": self.steward_id,
                            },
                        },
                        "summary": "Create the requested organization.",
                    }
                ],
            }
        organization_scope = {
            "scope": "organization",
            "organization_id": organization["organization_id"],
        }
        if project is None:
            return {
                "stop_reason": "completed",
                "summary": "Creating the requested project through Steward control-plane MCP.",
                "tool_calls": [
                    {
                        "tool_name": PROJECT_CREATE_TOOL,
                        "arguments": {
                            "_mcp_scope": organization_scope,
                            "slug": self.project_slug,
                            "name": self.project_name,
                            "description": "Created by the Steward live-system task test.",
                            "metadata": {
                                "system_test": True,
                                "source": "operational_agents_live_system",
                                "creator_system_agent_id": self.steward_id,
                            },
                        },
                        "summary": "Create the requested organization project.",
                    }
                ],
            }
        if workspace_detail is None:
            return {
                "stop_reason": "completed",
                "summary": "Creating the requested workspace through Steward control-plane MCP.",
                "tool_calls": [
                    {
                        "tool_name": WORKSPACE_CREATE_TOOL,
                        "arguments": {
                            "_mcp_scope": organization_scope,
                            "project_id": project["project_id"],
                            "name": self.workspace_name,
                            "description": "Created by the Steward live-system task test.",
                            "metadata": {
                                "system_test": True,
                                "source": "operational_agents_live_system",
                                "created_by": self.steward_id,
                                "creator_system_agent_id": self.steward_id,
                            },
                        },
                        "summary": "Create the requested workspace in the new project.",
                    }
                ],
            }
        workspace = workspace_detail.get("workspace", workspace_detail)
        return {
            "stop_reason": "completed",
            "message": (
                f"Created organization `{organization['name']}`, project "
                f"`{project['name']}`, and workspace `{workspace['name']}`."
            ),
            "summary": "Steward created the requested organization, project, and workspace.",
        }


class StewardTaskHarnessServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, *, state: StewardTaskHarnessState):
        super().__init__(server_address, handler_class)
        self.state = state


class StewardTaskHarnessHandler(BaseHTTPRequestHandler):
    server: StewardTaskHarnessServer

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        body = json.dumps(self.server.state.handle(payload)).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return
