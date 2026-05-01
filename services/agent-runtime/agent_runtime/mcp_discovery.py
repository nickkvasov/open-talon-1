from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import uuid4

import httpx
from open_talon_contracts.models import (
    McpPromptDefinition,
    McpResourceDefinition,
    McpServerDefinition,
    McpToolDefinition,
)

from .secrets import SecretResolver, build_default_secret_resolver, secret_references_from_config


@dataclass(frozen=True)
class McpCapabilityDiscoveryResult:
    tools: list[McpToolDefinition] = field(default_factory=list)
    resources: list[McpResourceDefinition] = field(default_factory=list)
    prompts: list[McpPromptDefinition] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


async def discover_mcp_capabilities(
    server: McpServerDefinition,
    *,
    timeout_seconds: float = 30.0,
    secret_resolver: SecretResolver | None = None,
) -> McpCapabilityDiscoveryResult:
    if server.transport_kind == "stdio":
        raise ValueError("System Plugin sync v1 supports HTTP MCP servers; stdio requires seeded capabilities")
    url = str(server.config.get("url") or server.config.get("endpoint") or "").strip()
    if not url:
        raise ValueError("HTTP MCP server config requires url")
    resolver = secret_resolver or build_default_secret_resolver()
    headers = await _headers_for_server(server, resolver)
    async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=False) as client:
        init = await _rpc(
            client,
            url,
            headers,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "open-talon-mcp-sync-worker", "version": "0.1.0"},
            },
        )
        payload = _response_payload(init)
        if "error" in payload:
            raise ValueError(f"MCP initialize failed: {payload['error']}")
        call_headers = dict(headers)
        session_id = init.headers.get("MCP-Session-Id")
        if session_id:
            call_headers["MCP-Session-Id"] = session_id
        tools = await _list_paginated(client, url, call_headers, "tools/list", "tools")
        resources = await _list_optional(client, url, call_headers, "resources/list", "resources")
        prompts = await _list_optional(client, url, call_headers, "prompts/list", "prompts")
    discovered_at = datetime.now(UTC)
    return McpCapabilityDiscoveryResult(
        tools=[_tool_from_mcp(server, item, discovered_at) for item in tools],
        resources=[_resource_from_mcp(server, item, discovered_at) for item in resources],
        prompts=[_prompt_from_mcp(server, item, discovered_at) for item in prompts],
        metadata={
            "protocol": "mcp",
            "transport_kind": server.transport_kind,
            "discovered_at": discovered_at.isoformat(),
        },
    )


async def _headers_for_server(
    server: McpServerDefinition,
    secret_resolver: SecretResolver,
) -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-11-25",
    }
    for key, value in dict(server.config.get("headers") or {}).items():
        if isinstance(key, str) and isinstance(value, str):
            headers[key] = value
    auth_config = server.config.get("auth")
    if isinstance(auth_config, dict) and auth_config.get("kind") in {
        "open_talon_agent_identity",
        "external_identity",
    }:
        raise ValueError(
            "System Plugin sync cannot use execution-scoped MCP auth because no workspace participant is executing the sync"
        )
    for key, value in dict(server.secret_config.get("headers") or {}).items():
        if not isinstance(key, str):
            continue
        secret = await _resolve_secret_value(value, secret_resolver, label=f"MCP header {key}")
        if secret:
            headers[key] = secret
    bearer = await _resolve_secret_value(
        server.secret_config.get("bearer_token") or server.secret_config.get("token"),
        secret_resolver,
        label=f"MCP server {server.server_id} bearer token",
        required=False,
    )
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return headers


async def _resolve_secret_value(
    value: Any,
    resolver: SecretResolver,
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
            return await resolver.resolve(references, label=label, required=required)
    if required:
        raise ValueError(f"Unable to resolve {label}")
    return None


async def _list_optional(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    method: str,
    key: str,
) -> list[dict[str, Any]]:
    try:
        return await _list_paginated(client, url, headers, method, key)
    except ValueError as exc:
        if "-32601" in str(exc) or "Method not found" in str(exc):
            return []
        raise


async def _list_paginated(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    method: str,
    key: str,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor
        response = await _rpc(client, url, headers, method, params)
        payload = _response_payload(response)
        if "error" in payload:
            raise ValueError(f"MCP {method} failed: {payload['error']}")
        result = payload.get("result")
        if not isinstance(result, dict):
            return items
        raw_items = result.get(key)
        if isinstance(raw_items, list):
            items.extend([item for item in raw_items if isinstance(item, dict)])
        next_cursor = result.get("nextCursor") or result.get("next_cursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            return items
        cursor = next_cursor


async def _rpc(
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
    payload = httpx.Response(200, content=data_lines[-1]).json()
    return payload if isinstance(payload, dict) else {"result": payload}


def _tool_from_mcp(
    server: McpServerDefinition,
    item: dict[str, Any],
    discovered_at: datetime,
) -> McpToolDefinition:
    name = str(item.get("name") or item.get("tool_name") or "").strip()
    if not name:
        raise ValueError(f"MCP tool entry for server {server.server_id} is missing name")
    input_schema = _object_or_empty(item.get("inputSchema") or item.get("input_schema"))
    output_schema = _object_or_empty(item.get("outputSchema") or item.get("output_schema"))
    payload = {
        "kind": "tool",
        "name": name,
        "description": item.get("description") or "",
        "input_schema": input_schema,
        "output_schema": output_schema,
    }
    return McpToolDefinition(
        server_id=server.server_id,
        tool_name=name,
        display_name=_optional_str(item.get("title") or item.get("displayName")),
        description=str(item.get("description") or ""),
        input_schema=input_schema,
        output_schema=output_schema,
        capability_hash=_hash_payload(payload),
        discovered_at=discovered_at,
        metadata={"source": "mcp_discovery", "raw": item},
    )


def _resource_from_mcp(
    server: McpServerDefinition,
    item: dict[str, Any],
    discovered_at: datetime,
) -> McpResourceDefinition:
    uri = str(item.get("uri") or "").strip()
    if not uri:
        raise ValueError(f"MCP resource entry for server {server.server_id} is missing uri")
    name = str(item.get("name") or uri)
    payload = {
        "kind": "resource",
        "uri": uri,
        "name": name,
        "description": item.get("description") or "",
        "mime_type": item.get("mimeType") or item.get("mime_type"),
    }
    return McpResourceDefinition(
        server_id=server.server_id,
        uri=uri,
        name=name,
        description=str(item.get("description") or ""),
        mime_type=_optional_str(item.get("mimeType") or item.get("mime_type")),
        capability_hash=_hash_payload(payload),
        discovered_at=discovered_at,
        metadata={"source": "mcp_discovery", "raw": item},
    )


def _prompt_from_mcp(
    server: McpServerDefinition,
    item: dict[str, Any],
    discovered_at: datetime,
) -> McpPromptDefinition:
    name = str(item.get("name") or item.get("prompt_name") or "").strip()
    if not name:
        raise ValueError(f"MCP prompt entry for server {server.server_id} is missing name")
    arguments_schema = _prompt_arguments_schema(item.get("arguments"))
    payload = {
        "kind": "prompt",
        "name": name,
        "description": item.get("description") or "",
        "arguments_schema": arguments_schema,
    }
    return McpPromptDefinition(
        server_id=server.server_id,
        prompt_name=name,
        description=str(item.get("description") or ""),
        arguments_schema=arguments_schema,
        capability_hash=_hash_payload(payload),
        discovered_at=discovered_at,
        metadata={"source": "mcp_discovery", "raw": item},
    )


def _prompt_arguments_schema(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, list):
        return {"type": "object", "properties": {}, "additionalProperties": False}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for item in arguments:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        properties[name] = {
            "type": "string",
            "description": str(item.get("description") or ""),
        }
        if item.get("required"):
            required.append(name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _object_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _hash_payload(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
