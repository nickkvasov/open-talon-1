from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import httpx
from open_talon_contracts.models import ExecutionHandle, ExecutionResult, ExecutionSpec

try:  # pragma: no cover - exercised when the optional official MCP SDK is installed.
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
    from mcp.client.streamable_http import streamablehttp_client
except Exception:  # pragma: no cover - local test env may not have the SDK installed yet.
    ClientSession = None
    StdioServerParameters = None
    sse_client = None
    stdio_client = None
    streamablehttp_client = None


@dataclass
class _McpRecord:
    result: ExecutionResult


class McpExecutionBackend:
    kind = "mcp"

    def __init__(self, *, kernel) -> None:
        self._kernel = kernel
        self._records: dict[str, _McpRecord] = {}

    async def submit(self, spec: ExecutionSpec) -> ExecutionHandle:
        server_id = spec.metadata.get("mcp_server_id")
        if not isinstance(server_id, str) or not server_id:
            raise ValueError("MCP execution requires metadata.mcp_server_id")
        server = await self._kernel.get_mcp_server(UUID(server_id))
        if server is None:
            raise KeyError(f"MCP server {server_id} not found")
        if not server.enabled:
            raise ValueError(f"MCP server {server_id} is disabled")
        if server.transport_kind == "stdio" and server.trust_level != "trusted":
            raise ValueError("stdio MCP servers require trust_level='trusted'")
        result = (
            await self._call_sdk_tool(server, spec)
            if ClientSession is not None
            else await self._call_http_tool(server, spec)
        )
        handle = str(uuid4())
        self._records[handle] = _McpRecord(result=result)
        return ExecutionHandle(
            backend_kind=self.kind,
            invocation_id=spec.invocation_id,
            handle=handle,
            metadata={"mcp_server_id": server_id},
        )

    async def poll(self, handle: ExecutionHandle) -> ExecutionResult:
        return self._records[handle.handle].result

    async def cancel(self, handle: ExecutionHandle, reason: str | None = None) -> None:
        _ = reason
        self._records.pop(handle.handle, None)

    async def collect(self, handle: ExecutionHandle) -> ExecutionResult:
        return self._records.pop(handle.handle).result

    async def _call_http_tool(self, server, spec: ExecutionSpec) -> ExecutionResult:
        if server.transport_kind == "stdio":
            raise ValueError("stdio MCP execution requires the official MCP SDK dependency")
        url = str(server.config.get("url") or server.config.get("endpoint") or "")
        if not url:
            raise ValueError("HTTP MCP server config requires url")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-11-25",
        }
        for key, value in dict(server.config.get("headers") or {}).items():
            if isinstance(key, str) and isinstance(value, str):
                headers[key] = value
        timeout = float(spec.profile.get("timeout_seconds") or spec.limits.timeout_seconds or 60)
        async with httpx.AsyncClient(timeout=timeout) as client:
            init = await self._rpc(
                client,
                url,
                headers,
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "open-talon-agent-runtime", "version": "0.1.0"},
                },
            )
            session_id = init.headers.get("MCP-Session-Id")
            call_headers = dict(headers)
            if session_id:
                call_headers["MCP-Session-Id"] = session_id
            call = await self._rpc(
                client,
                url,
                call_headers,
                "tools/call",
                {"name": spec.handler_ref, "arguments": spec.inline_payload},
            )
        payload = self._response_payload(call)
        if "error" in payload:
            return ExecutionResult(
                status="failed",
                output_payload={},
                error=str(payload["error"]),
                metadata={"backend_kind": self.kind},
            )
        return ExecutionResult(
            status="completed",
            output_payload=payload.get("result") if isinstance(payload.get("result"), dict) else payload,
            metadata={"backend_kind": self.kind},
        )

    async def _call_sdk_tool(self, server, spec: ExecutionSpec) -> ExecutionResult:
        assert ClientSession is not None
        headers = {
            key: value
            for key, value in dict(server.config.get("headers") or {}).items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if server.transport_kind == "stdio":
            assert StdioServerParameters is not None and stdio_client is not None
            command = list(server.config.get("command") or [])
            if not command:
                raise ValueError("stdio MCP server config requires command")
            params = StdioServerParameters(
                command=command[0],
                args=command[1:],
                env={
                    key: value
                    for key, value in dict(server.config.get("env") or {}).items()
                    if isinstance(key, str) and isinstance(value, str)
                },
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(spec.handler_ref, spec.inline_payload)
                    return self._sdk_result_to_execution_result(result)
        url = str(server.config.get("url") or server.config.get("endpoint") or "")
        if not url:
            raise ValueError("HTTP MCP server config requires url")
        if server.transport_kind == "sse":
            assert sse_client is not None
            async with sse_client(url, headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(spec.handler_ref, spec.inline_payload)
                    return self._sdk_result_to_execution_result(result)
        assert streamablehttp_client is not None
        async with streamablehttp_client(url, headers=headers) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(spec.handler_ref, spec.inline_payload)
                return self._sdk_result_to_execution_result(result)

    @staticmethod
    def _sdk_result_to_execution_result(result: Any) -> ExecutionResult:
        if hasattr(result, "model_dump"):
            payload = result.model_dump(mode="json")
        elif hasattr(result, "dict"):
            payload = result.dict()
        elif isinstance(result, dict):
            payload = result
        else:
            payload = {"content": str(result)}
        is_error = bool(payload.get("isError") or payload.get("is_error"))
        return ExecutionResult(
            status="failed" if is_error else "completed",
            output_payload=payload,
            error=str(payload.get("error")) if is_error and payload.get("error") else None,
            metadata={"backend_kind": "mcp"},
        )

    async def _rpc(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        method: str,
        params: dict[str, Any],
    ) -> httpx.Response:
        response = await client.post(
            url,
            headers=headers,
            json={"jsonrpc": "2.0", "id": str(uuid4()), "method": method, "params": params},
        )
        response.raise_for_status()
        return response

    @staticmethod
    def _response_payload(response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        if "text/event-stream" not in content_type:
            payload = response.json()
            return payload if isinstance(payload, dict) else {"result": payload}
        data_lines = [
            line.removeprefix("data:").strip()
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        if not data_lines:
            return {}
        return httpx.Response(200, content=data_lines[-1]).json()
