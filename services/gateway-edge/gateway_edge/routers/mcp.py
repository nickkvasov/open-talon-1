from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sse_starlette.sse import EventSourceResponse

from gateway_edge.mcp_api import (
    MCP_PROTOCOL_VERSION,
    MCP_SERVER_INFO,
    McpApiContext,
    build_tool_error,
    build_tool_result,
    create_mcp_session,
    dispatch_operation,
    list_resource_definitions,
    list_visible_operations,
    load_mcp_session,
    mcp_capabilities,
    notification_hub,
    publish_scope_change_notifications,
    read_resource,
)
from gateway_edge.models import AuthContext

router = APIRouter(tags=["mcp"])


def _auth_context(request: Request) -> AuthContext:
    auth_context = getattr(request.state, "auth_context", None)
    if not isinstance(auth_context, AuthContext) or auth_context.kind != "oidc":
        raise HTTPException(status_code=401, detail="OIDC authentication is required for MCP")
    return auth_context


def _session_id_from_request(request: Request) -> UUID:
    raw = request.headers.get("Mcp-Session-Id")
    if not raw:
        raise HTTPException(status_code=400, detail="Mcp-Session-Id header is required")
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Mcp-Session-Id header") from exc


def _jsonrpc_error(
    *,
    request_id: Any,
    code: int,
    message: str,
    status_code: int = 200,
    session_id: UUID | None = None,
) -> JSONResponse:
    headers = {"Mcp-Session-Id": str(session_id)} if session_id is not None else {}
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        },
    )


def _jsonrpc_result(
    *,
    request_id: Any,
    result: dict[str, Any],
    session_id: UUID | None = None,
) -> JSONResponse:
    headers = {"Mcp-Session-Id": str(session_id)} if session_id is not None else {}
    return JSONResponse(
        headers=headers,
        content={"jsonrpc": "2.0", "id": request_id, "result": result},
    )

@router.get(
    "/.well-known/oauth-protected-resource",
    include_in_schema=False,
)
@router.get(
    "/.well-known/oauth-protected-resource/v1/mcp",
    include_in_schema=False,
)
async def oauth_protected_resource_metadata(request: Request) -> dict[str, Any]:
    from gateway_edge.config import settings

    resource_server_url = str(request.base_url).rstrip("/") + "/v1/mcp"
    return {
        "resource": resource_server_url,
        "authorization_servers": [settings.oidc_issuer_url],
        "bearer_methods_supported": ["header"],
    }


@router.get("/v1/mcp", include_in_schema=False)
async def stream_mcp_notifications(request: Request):
    auth_context = _auth_context(request)
    session = await load_mcp_session(_session_id_from_request(request), auth_context)

    async def _events():
        queue = await notification_hub.subscribe(session.session_id)
        try:
            while True:
                payload = await queue.get()
                yield {"data": json.dumps(payload)}
        finally:
            notification_hub.unsubscribe(session.session_id, queue)

    request.state.audit_metadata = {
        "mcp_method": "sse.subscribe",
        "mcp_session_id": str(session.session_id),
    }
    return EventSourceResponse(_events())


@router.post("/v1/mcp", include_in_schema=False)
async def handle_mcp(request: Request):
    auth_context = _auth_context(request)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    if not isinstance(method, str):
        return _jsonrpc_error(request_id=request_id, code=-32600, message="Invalid JSON-RPC request")

    request.state.audit_metadata = {
        "mcp_method": method,
        "mcp_name": params.get("name") or params.get("uri"),
    }

    if method == "initialize":
        session = await create_mcp_session(auth_context)
        return _jsonrpc_result(
            request_id=request_id,
            session_id=session.session_id,
            result={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": mcp_capabilities(),
                "serverInfo": MCP_SERVER_INFO,
            },
        )

    if method.startswith("notifications/"):
        session = await load_mcp_session(_session_id_from_request(request), auth_context)
        return Response(status_code=202, headers={"Mcp-Session-Id": str(session.session_id)})

    session = await load_mcp_session(_session_id_from_request(request), auth_context)
    ctx = McpApiContext(request=request, auth_context=auth_context, session=session)

    if method == "ping":
        return _jsonrpc_result(request_id=request_id, session_id=session.session_id, result={})
    if method == "tools/list":
        tools = await list_visible_operations(ctx)
        return _jsonrpc_result(
            request_id=request_id,
            session_id=session.session_id,
            result={"tools": tools},
        )
    if method == "resources/list":
        return _jsonrpc_result(
            request_id=request_id,
            session_id=session.session_id,
            result={"resources": list_resource_definitions()},
        )
    if method == "resources/read":
        uri = params.get("uri")
        if not isinstance(uri, str):
            return _jsonrpc_error(
                request_id=request_id,
                code=-32602,
                message="resources/read requires a string uri",
                session_id=session.session_id,
            )
        try:
            result = await read_resource(ctx, uri)
        except Exception as exc:
            return _jsonrpc_result(
                request_id=request_id,
                session_id=session.session_id,
                result={
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "text/plain",
                            "text": str(exc),
                        }
                    ]
                },
            )
        return _jsonrpc_result(request_id=request_id, session_id=session.session_id, result=result)
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            return _jsonrpc_error(
                request_id=request_id,
                code=-32602,
                message="tools/call requires a string name",
                session_id=session.session_id,
            )
        try:
            result = await dispatch_operation(ctx, name, params.get("arguments"))
        except KeyError as exc:
            return _jsonrpc_error(
                request_id=request_id,
                code=-32602,
                message=str(exc),
                session_id=session.session_id,
            )
        except Exception as exc:
            return _jsonrpc_result(
                request_id=request_id,
                session_id=session.session_id,
                result=build_tool_error(name, exc),
            )
        if ctx.scope_changed:
            await publish_scope_change_notifications(session.session_id)
        return _jsonrpc_result(
            request_id=request_id,
            session_id=ctx.session.session_id,
            result=build_tool_result(name, result),
        )

    return _jsonrpc_error(
        request_id=request_id,
        code=-32601,
        message=f"Unsupported MCP method {method!r}",
        session_id=session.session_id,
    )
