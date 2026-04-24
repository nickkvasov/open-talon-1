from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any


@dataclass(frozen=True)
class FullFeaturedMcpServerState:
    tool_calls: list[dict[str, Any]]
    resource_reads: list[str]
    prompt_reads: list[dict[str, Any]]


class FullFeaturedMcpServer(AbstractContextManager["FullFeaturedMcpServer"]):
    """Small MCP-like Streamable HTTP server for external MCP integration tests.

    It intentionally supports the three major MCP capability families so tests can
    assert Open Talon keeps external MCP tools, resources, and prompts separate
    from Open Talon tool catalog records.
    """

    def __init__(self) -> None:
        self._server: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None
        self.state = FullFeaturedMcpServerState(
            tool_calls=[],
            resource_reads=[],
            prompt_reads=[],
        )

    @property
    def url(self) -> str:
        if self._server is None:
            raise RuntimeError("Server is not running")
        host, port = self._server.server_address
        return f"http://{host}:{port}/mcp"

    def __enter__(self) -> "FullFeaturedMcpServer":
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FullFeaturedMcpTest/1.0"

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("content-length") or "0")
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                method = payload.get("method")
                params = payload.get("params") or {}
                response = {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "result": owner._result_for(method, params),
                }
                body = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("MCP-Session-Id", "test-mcp-session")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:
                _ = format, args

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _result_for(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return {
                "protocolVersion": "2025-11-25",
                "serverInfo": {"name": "full-featured-test-mcp", "version": "1.0.0"},
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"listChanged": True, "subscribe": False},
                    "prompts": {"listChanged": True},
                    "logging": {},
                },
            }
        if method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "echo",
                        "title": "Echo",
                        "description": "Echoes input text and records the call.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    },
                    {
                        "name": "summarize",
                        "description": "Returns a short summary for supplied text.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"body": {"type": "string"}},
                            "required": ["body"],
                        },
                    },
                ]
            }
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = dict(params.get("arguments") or {})
            self.state.tool_calls.append({"name": name, "arguments": arguments})
            if name == "echo":
                text = str(arguments.get("text") or "")
                return {
                    "content": [{"type": "text", "text": f"echo:{text}"}],
                    "structuredContent": {"echo": text},
                    "isError": False,
                }
            if name == "summarize":
                body = str(arguments.get("body") or "")
                return {
                    "content": [{"type": "text", "text": body[:24]}],
                    "structuredContent": {"summary": body[:24]},
                    "isError": False,
                }
            return {"content": [{"type": "text", "text": "unknown tool"}], "isError": True}
        if method == "resources/list":
            return {
                "resources": [
                    {
                        "uri": "docs://open-talon/mcp",
                        "name": "Open Talon MCP Integration",
                        "description": "Test documentation resource.",
                        "mimeType": "text/markdown",
                    }
                ]
            }
        if method == "resources/read":
            uri = str(params.get("uri") or "")
            self.state.resource_reads.append(uri)
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/markdown",
                        "text": "# MCP Integration\nExternal MCP resources are references.",
                    }
                ]
            }
        if method == "prompts/list":
            return {
                "prompts": [
                    {
                        "name": "incident_triage",
                        "description": "Suggests an incident triage shape.",
                        "arguments": [
                            {
                                "name": "service",
                                "description": "Service name",
                                "required": True,
                            }
                        ],
                    }
                ]
            }
        if method == "prompts/get":
            name = str(params.get("name") or "")
            arguments = dict(params.get("arguments") or {})
            self.state.prompt_reads.append({"name": name, "arguments": arguments})
            return {
                "description": "Incident triage prompt",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": f"Triage {arguments.get('service', 'service')}",
                        },
                    }
                ],
            }
        return {}
