from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from typing import Any

from .helpers import PROJECT_CREATE_TOOL, STEWARD_ORGANIZATION_CREATE_TOOL, WORKSPACE_CREATE_TOOL


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
