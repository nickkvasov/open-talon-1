from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from open_talon_contracts.models import (
    ExecutionHandle,
    ExecutionResult,
    ExecutionSpec,
    plugin_metadata_enables_asset_persistence,
)

from ..secrets import SecretResolver, build_default_secret_resolver, secret_references_from_config

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


class ExternalOperationPendingApproval(Exception):
    def __init__(self, operation_request_id: UUID | None) -> None:
        self.operation_request_id = operation_request_id
        super().__init__("External operation requires approval")


class McpExecutionBackend:
    kind = "mcp"

    def __init__(self, *, kernel, secret_resolver: SecretResolver | None = None) -> None:
        self._kernel = kernel
        self._secret_resolver = secret_resolver or build_default_secret_resolver()
        self._records: dict[str, _McpRecord] = {}
        self._token_cache: dict[UUID, tuple[str, datetime]] = {}

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
        try:
            headers = await self._headers_for_server(server, spec)
        except ExternalOperationPendingApproval as pending:
            return self._pending_external_approval_result(pending)
        arguments, scope_args = self._split_scope_arguments(spec.inline_payload)
        self._validate_asset_persistence_arguments(spec, arguments)
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
            if scope_args is not None:
                scoped = await self._rpc(
                    client,
                    url,
                    call_headers,
                    "tools/call",
                    {"name": "session.set_scope", "arguments": scope_args},
                )
                scoped_payload = self._response_payload(scoped)
                if "error" in scoped_payload:
                    return ExecutionResult(
                        status="failed",
                        output_payload={},
                        error=str(scoped_payload["error"]),
                        metadata={"backend_kind": self.kind},
                    )
            call = await self._rpc(
                client,
                url,
                call_headers,
                "tools/call",
                {"name": spec.handler_ref, "arguments": arguments},
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
        try:
            headers = await self._headers_for_server(
                server,
                spec,
                include_protocol_headers=False,
            )
        except ExternalOperationPendingApproval as pending:
            return self._pending_external_approval_result(pending)
        arguments, scope_args = self._split_scope_arguments(spec.inline_payload)
        self._validate_asset_persistence_arguments(spec, arguments)
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
                    if scope_args is not None:
                        await session.call_tool("session.set_scope", scope_args)
                    result = await session.call_tool(spec.handler_ref, arguments)
                    return self._sdk_result_to_execution_result(result)
        url = str(server.config.get("url") or server.config.get("endpoint") or "")
        if not url:
            raise ValueError("HTTP MCP server config requires url")
        if server.transport_kind == "sse":
            assert sse_client is not None
            async with sse_client(url, headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    if scope_args is not None:
                        await session.call_tool("session.set_scope", scope_args)
                    result = await session.call_tool(spec.handler_ref, arguments)
                    return self._sdk_result_to_execution_result(result)
        assert streamablehttp_client is not None
        async with streamablehttp_client(url, headers=headers) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                if scope_args is not None:
                    await session.call_tool("session.set_scope", scope_args)
                result = await session.call_tool(spec.handler_ref, arguments)
                return self._sdk_result_to_execution_result(result)

    async def _headers_for_server(
        self,
        server,
        spec: ExecutionSpec,
        *,
        include_protocol_headers: bool = True,
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        if include_protocol_headers:
            headers.update(
                {
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                    "MCP-Protocol-Version": "2025-11-25",
                }
            )
        for key, value in dict(server.config.get("headers") or {}).items():
            if isinstance(key, str) and isinstance(value, str):
                headers[key] = value
        auth_config = server.config.get("auth")
        if not isinstance(auth_config, dict):
            return headers
        auth_kind = auth_config.get("kind")
        if auth_kind == "external_identity":
            headers.update(await self._external_identity_headers(server, spec, auth_config))
            return headers
        if auth_kind != "open_talon_agent_identity":
            return headers
        token = await self._agent_identity_token(spec)
        headers["Authorization"] = f"Bearer {token}"
        return headers

    @staticmethod
    def _pending_external_approval_result(
        pending: ExternalOperationPendingApproval,
    ) -> ExecutionResult:
        return ExecutionResult(
            status="pending_approval",
            output_payload={
                "status": "pending_approval",
                "operation_request_id": (
                    str(pending.operation_request_id)
                    if pending.operation_request_id is not None
                    else None
                ),
            },
            error="External operation requires approval",
            metadata={
                "backend_kind": "mcp",
                "external_operation_pending_approval": True,
                "operation_request_id": (
                    str(pending.operation_request_id)
                    if pending.operation_request_id is not None
                    else None
                ),
            },
        )

    async def _external_identity_headers(
        self,
        server,
        spec: ExecutionSpec,
        auth_config: dict[str, Any],
    ) -> dict[str, str]:
        raw_workspace_id = spec.metadata.get("workspace_id")
        if not isinstance(raw_workspace_id, str) or not raw_workspace_id:
            raise ValueError("MCP external_identity auth requires metadata.workspace_id")
        raw_system_agent_id = spec.metadata.get("system_agent_id")
        if not isinstance(raw_system_agent_id, str) or not raw_system_agent_id:
            raise ValueError("MCP external_identity auth requires metadata.system_agent_id")
        operation_key = (
            auth_config.get("operation_key")
            or spec.metadata.get("external_operation_key")
            or spec.metadata.get("mcp_tool_name")
            or spec.handler_ref
        )
        if not isinstance(operation_key, str) or not operation_key:
            raise ValueError("MCP external_identity auth requires an operation key")
        risk_level = (
            auth_config.get("risk_level")
            or spec.metadata.get("external_operation_risk_level")
            or spec.metadata.get("external_operation_risk")
            or "low"
        )
        if not isinstance(risk_level, str) or not risk_level:
            risk_level = "low"
        system_id = None
        raw_system_id = auth_config.get("external_system_id") or auth_config.get("system_id")
        if isinstance(raw_system_id, str) and raw_system_id:
            system_id = UUID(raw_system_id)
        system_key = auth_config.get("external_system_key") or auth_config.get("system_key")
        if not isinstance(system_key, str):
            system_key = None
        thread_id = self._metadata_uuid(spec, "thread_id")
        tool_call_id = self._metadata_uuid(spec, "tool_call_id")
        resolution = await self._kernel.resolve_external_identity_for_operation(
            workspace_id=UUID(raw_workspace_id),
            system_agent_id=UUID(raw_system_agent_id),
            system_id=system_id,
            system_key=system_key,
            operation_key=operation_key,
            risk_level=risk_level,
            source="mcp",
            thread_id=thread_id,
            tool_call_id=tool_call_id,
            request_metadata={
                "mcp_server_id": str(server.server_id),
                "mcp_server_key": server.server_key,
                "mcp_tool_name": spec.metadata.get("mcp_tool_name") or spec.handler_ref,
                "argument_keys": (
                    sorted(spec.inline_payload.keys())
                    if isinstance(spec.inline_payload, dict)
                    else []
                ),
            },
        )
        if not resolution.approved:
            raise ExternalOperationPendingApproval(
                resolution.operation_request.operation_request_id
                if resolution.operation_request is not None
                else None
            )
        credential_config = (
            resolution.account.credential_ref
            if resolution.account is not None
            else resolution.system.secret_config
        )
        return await self._credential_headers(
            credential_config,
            auth_config=auth_config,
            label=f"external system {resolution.system.system_id}",
        )

    async def _credential_headers(
        self,
        credential_config: dict[str, Any],
        *,
        auth_config: dict[str, Any],
        label: str,
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        configured_headers = credential_config.get("headers")
        if isinstance(configured_headers, dict):
            for key, value in configured_headers.items():
                if isinstance(key, str):
                    resolved = await self._resolve_secret_value(
                        value,
                        label=f"{label} header {key}",
                        required=False,
                    )
                    if resolved:
                        headers[key] = resolved
        token_value = await self._resolve_secret_value(
            credential_config.get("bearer_token") or credential_config.get("token"),
            label=f"{label} bearer token",
            required=False,
        )
        if token_value:
            header_name = str(auth_config.get("header_name") or "Authorization")
            scheme = str(auth_config.get("scheme") or "Bearer")
            headers[header_name] = (
                token_value if not scheme else f"{scheme} {token_value}"
            )
        api_key = await self._resolve_secret_value(
            credential_config.get("api_key"),
            label=f"{label} API key",
            required=False,
        )
        if api_key:
            header_name = str(auth_config.get("header_name") or "X-API-Key")
            headers[header_name] = api_key
        return headers

    async def _resolve_secret_value(
        self,
        value: Any,
        *,
        label: str,
        required: bool = True,
    ) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            raw = value.get("value")
            if isinstance(raw, str):
                return raw
            references = secret_references_from_config(value)
            if references:
                return await self._secret_resolver.resolve(
                    references,
                    label=label,
                    required=required,
                )
        if required:
            raise ValueError(f"Unable to resolve {label}")
        return None

    @staticmethod
    def _metadata_uuid(spec: ExecutionSpec, key: str) -> UUID | None:
        raw = spec.metadata.get(key)
        if isinstance(raw, UUID):
            return raw
        if isinstance(raw, str) and raw:
            return UUID(raw)
        return None

    async def _agent_identity_token(self, spec: ExecutionSpec) -> str:
        raw_agent_id = spec.metadata.get("system_agent_id")
        if not isinstance(raw_agent_id, str) or not raw_agent_id:
            raise ValueError("MCP open_talon_agent_identity auth requires metadata.system_agent_id")
        system_agent_id = UUID(raw_agent_id)
        cached = self._token_cache.get(system_agent_id)
        now = datetime.now(UTC)
        if cached is not None and cached[1] > now + timedelta(seconds=30):
            return cached[0]
        if not hasattr(self._kernel, "get_active_agent_identity_for_system_agent"):
            raise ValueError("Kernel cannot resolve active agent identities")
        identity = await self._kernel.get_active_agent_identity_for_system_agent(system_agent_id)
        if identity is None:
            raise KeyError(f"Active machine identity for system agent {system_agent_id} not found")
        client_secret = await self._secret_resolver.resolve(
            secret_references_from_config(identity.secret_ref),
            label=f"agent identity {identity.agent_identity_id} client secret",
        )
        token_endpoint = identity.metadata.get("token_endpoint")
        if not isinstance(token_endpoint, str) or not token_endpoint:
            token_endpoint = f"{identity.issuer.rstrip('/')}/protocol/openid-connect/token"
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.post(
                token_endpoint,
                data={
                    "grant_type": "client_credentials",
                    "client_id": identity.client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            payload = response.json()
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("OIDC token endpoint did not return access_token")
        expires_in = payload.get("expires_in")
        ttl_seconds = expires_in if isinstance(expires_in, int) and expires_in > 0 else 60
        self._token_cache[system_agent_id] = (token, now + timedelta(seconds=ttl_seconds))
        return token

    @staticmethod
    def _split_scope_arguments(payload: Any) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if not isinstance(payload, dict):
            return {}, None
        arguments = dict(payload)
        scope_args = arguments.pop("_mcp_scope", None)
        if scope_args is None:
            return arguments, None
        if not isinstance(scope_args, dict):
            raise ValueError("_mcp_scope must be an object when provided")
        return arguments, scope_args

    @staticmethod
    def _validate_asset_persistence_arguments(spec: ExecutionSpec, arguments: dict[str, Any]) -> None:
        requested = bool(arguments.get("persist_asset") or arguments.get("persist_assets"))
        if not requested:
            return
        metadata = spec.metadata.get("mcp_workspace_attachment_metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        if not plugin_metadata_enables_asset_persistence(metadata):
            raise ValueError(
                "MCP tool requested asset persistence, but the workspace plugin attachment does not enable it"
            )

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
