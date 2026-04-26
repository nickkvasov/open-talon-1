from __future__ import annotations

import json
import os
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest


pytestmark = pytest.mark.integration


def _require_live_operational_agents() -> None:
    if os.getenv("OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE") != "1":
        pytest.skip(
            "Set OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 and start the local stack with ./open-talon start."
        )


def _json_request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> dict:
    data = None
    request_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=request_headers, method=method)
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - local live-system test
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def _form_request(url: str, payload: dict[str, str]) -> dict:
    data = urlencode(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=20.0) as response:  # noqa: S310 - local live-system test
        return json.loads(response.read().decode("utf-8"))


def _admin_token() -> str:
    issuer = os.getenv(
        "OPEN_TALON_OIDC_ISSUER_URL",
        "http://127.0.0.1:8081/realms/open-talon",
    ).rstrip("/")
    payload = _form_request(
        f"{issuer}/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": os.getenv("OPEN_TALON_TUI_CLIENT_ID", "open-talon-tui"),
            "username": os.getenv("OPEN_TALON_LIVE_ADMIN_USERNAME", "admin"),
            "password": os.getenv("OPEN_TALON_LIVE_ADMIN_PASSWORD", "admin123"),
        },
    )
    return payload["access_token"]


def _mcp_call(
    gateway: str,
    token: str,
    *,
    method: str,
    params: dict | None = None,
    session_id: str | None = None,
    request_id: str = "test",
) -> tuple[dict, str | None]:
    headers: dict[str, str] = {}
    if session_id is not None:
        headers["Mcp-Session-Id"] = session_id
    payload = _json_request(
        "POST",
        f"{gateway}/v1/mcp",
        token=token,
        payload={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
        headers=headers,
    )
    return payload, session_id


def test_operational_agents_bootstrap_on_live_system():
    _require_live_operational_agents()
    gateway = os.getenv("OPEN_TALON_GATEWAY_URL", "http://127.0.0.1:8000").rstrip("/")
    token = _admin_token()

    deadline = time.time() + 60
    system_base = None
    while time.time() < deadline:
        organizations = _json_request("GET", f"{gateway}/v1/organizations", token=token)
        system_base = next(
            (item for item in organizations if item["slug"] == "system-base"),
            None,
        )
        if system_base is not None:
            break
        time.sleep(2)
    assert system_base is not None

    projects = _json_request(
        "GET",
        f"{gateway}/v1/organizations/{system_base['organization_id']}/projects",
        token=token,
    )
    administration = next(item for item in projects if item["slug"] == "administration")
    workspaces = _json_request(
        "GET",
        f"{gateway}/v1/organizations/{system_base['organization_id']}/workspaces?project_id={administration['project_id']}",
        token=token,
    )
    assert any(workspace["name"] == "System Operations" for workspace in workspaces)

    suffix = uuid4().hex[:10]
    actor = {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Live Admin",
    }
    organization = _json_request(
        "POST",
        f"{gateway}/v1/organizations",
        token=token,
        payload={
            "actor": actor,
            "slug": f"operational-live-{suffix}",
            "name": f"Operational Live {suffix}",
        },
    )
    org_projects = _json_request(
        "GET",
        f"{gateway}/v1/organizations/{organization['organization_id']}/projects",
        token=token,
    )
    org_admin = next(item for item in org_projects if item["slug"] == "administration")
    org_workspaces = _json_request(
        "GET",
        f"{gateway}/v1/organizations/{organization['organization_id']}/workspaces?project_id={org_admin['project_id']}",
        token=token,
    )
    org_operations = next(
        workspace for workspace in org_workspaces if workspace["name"] == "Organization Operations"
    )
    agents = _json_request(
        "GET",
        f"{gateway}/v1/organizations/{organization['organization_id']}/agents",
        token=token,
    )
    curator = next(agent for agent in agents if agent["agent_key"] == "curator")
    assert curator["role"] == "organization curator"

    # urllib helper returns only JSON bodies; initialize directly so the MCP session
    # header is available for subsequent tool calls.
    request = Request(
        f"{gateway}/v1/mcp",
        data=json.dumps(
            {"jsonrpc": "2.0", "id": "init2", "method": "initialize", "params": {}}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urlopen(request, timeout=20.0) as response:  # noqa: S310 - local live-system test
        session_id = response.headers["Mcp-Session-Id"]
        payload = json.loads(response.read().decode("utf-8"))
    assert payload["result"]["protocolVersion"]
    set_scope, _ = _mcp_call(
        gateway,
        token,
        method="tools/call",
        session_id=session_id,
        params={
            "name": "session.set_scope",
            "arguments": {"scope": "workspace", "workspace_id": org_operations["workspace_id"]},
        },
    )
    assert set_scope["result"]["isError"] is False
    tools, _ = _mcp_call(gateway, token, method="tools/list", session_id=session_id)
    tool_names = {item["name"] for item in tools["result"]["tools"]}
    assert "threads.messages.create" in tool_names
