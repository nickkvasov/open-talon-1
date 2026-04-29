from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any
from uuid import uuid4

import httpx
import pytest


pytestmark = pytest.mark.integration

_ROOT_DIR = Path(__file__).resolve().parents[2]
_GATEWAY_URL = "http://127.0.0.1:8000"
_KEYCLOAK_BASE_URL = "http://127.0.0.1:8081"
_OPEN_TALON_REALM = "open-talon"
_SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
_WEB_SEARCH_MCP_HEALTH_URL = "http://127.0.0.1:8181/health"
_WEB_SEARCH_MCP_URL = "http://127.0.0.1:8181/mcp"


def _require_live_system_plugins() -> None:
    if os.getenv("OPEN_TALON_RUN_SYSTEM_PLUGINS_LIVE") != "1":
        pytest.skip(
            "Set OPEN_TALON_RUN_SYSTEM_PLUGINS_LIVE=1 and start the local stack with "
            "./open-talon start --web-search to run System Plugin live tests"
        )


def _wait_for(
    description: str,
    predicate,
    *,
    timeout_seconds: float = 120.0,
    interval_seconds: float = 1.0,
):
    deadline = time.monotonic() + timeout_seconds
    last_value = None
    while time.monotonic() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(interval_seconds)
    raise AssertionError(f"Timed out waiting for {description}; last_value={last_value!r}")


def _wait_for_http_ok(url: str, *, description: str) -> None:
    def _healthy() -> bool:
        try:
            response = httpx.get(url, timeout=5.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    _wait_for(description, _healthy, timeout_seconds=120.0, interval_seconds=1.0)


def _wait_for_searxng_container() -> None:
    def _healthy() -> bool:
        for path in ("/healthz", "/"):
            try:
                response = httpx.get(f"{_SEARXNG_BASE_URL}{path}", timeout=5.0)
                if response.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
        return False

    _wait_for("SearXNG container", _healthy, timeout_seconds=120.0, interval_seconds=1.0)


def _master_admin_token() -> str:
    deadline = time.monotonic() + 120.0
    last_detail = "not attempted"
    while time.monotonic() < deadline:
        try:
            response = httpx.post(
                f"{_KEYCLOAK_BASE_URL}/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": "admin",
                    "password": "admin",
                },
                timeout=20.0,
            )
            if response.status_code == 200:
                return str(response.json()["access_token"])
            last_detail = f"{response.status_code} {response.text[:200]}"
        except httpx.HTTPError as exc:
            last_detail = str(exc)
        time.sleep(1.0)
    raise AssertionError(f"Timed out waiting for Keycloak master admin token: {last_detail}")


def _keycloak_client_internal_id(*, admin_token: str, client_id: str) -> str | None:
    response = httpx.get(
        f"{_KEYCLOAK_BASE_URL}/admin/realms/{_OPEN_TALON_REALM}/clients",
        headers={"Authorization": f"Bearer {admin_token}"},
        params={"clientId": client_id},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload:
        return None
    internal_id = payload[0].get("id")
    return str(internal_id) if internal_id else None


def _ensure_password_grant_client(*, admin_token: str, client_id: str) -> None:
    if _keycloak_client_internal_id(admin_token=admin_token, client_id=client_id):
        return
    response = httpx.post(
        f"{_KEYCLOAK_BASE_URL}/admin/realms/{_OPEN_TALON_REALM}/clients",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "clientId": client_id,
            "name": "System Plugin live tests",
            "protocol": "openid-connect",
            "publicClient": True,
            "directAccessGrantsEnabled": True,
            "standardFlowEnabled": False,
            "serviceAccountsEnabled": False,
            "redirectUris": [],
            "webOrigins": [],
        },
        timeout=20.0,
    )
    if response.status_code not in {201, 204, 409}:
        response.raise_for_status()


def _delete_keycloak_client(*, admin_token: str, client_id: str) -> None:
    internal_id = _keycloak_client_internal_id(admin_token=admin_token, client_id=client_id)
    if internal_id is None:
        return
    response = httpx.delete(
        f"{_KEYCLOAK_BASE_URL}/admin/realms/{_OPEN_TALON_REALM}/clients/{internal_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=20.0,
    )
    if response.status_code not in {204, 404}:
        response.raise_for_status()


def _password_grant_token(*, client_id: str, username: str, password: str) -> str:
    response = httpx.post(
        f"{_KEYCLOAK_BASE_URL}/realms/{_OPEN_TALON_REALM}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": client_id,
            "username": username,
            "password": password,
            "scope": "openid profile email",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def _actor_payload(*, display_name: str = "System Plugin Live Admin") -> dict[str, Any]:
    return {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": display_name,
    }


def _json_request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: str,
    json_body: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> dict[str, Any] | list[Any]:
    response = client.request(
        method,
        path,
        headers={"Authorization": f"Bearer {token}"},
        json=json_body,
    )
    if response.status_code != expected_status:
        raise AssertionError(
            f"{method} {path} returned {response.status_code}: {response.text}"
        )
    return response.json()


def _web_search_mcp_rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = httpx.post(
        _WEB_SEARCH_MCP_URL,
        json={"jsonrpc": "2.0", "id": "live-test", "method": method, "params": params or {}},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise AssertionError(f"web-search MCP {method} failed: {payload['error']}")
    return payload["result"]


class _FixturePageHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"""
        <!doctype html>
        <html>
          <head><title>Open Talon Fixture</title></head>
          <body>
            <main>
              <h1>System Plugins</h1>
              <p>Crawl4AI extracts deterministic local fixture content.</p>
            </main>
          </body>
        </html>
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002
        return


class _LocalFixtureServer:
    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FixturePageHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/fixture"
        return self

    def __exit__(self, exc_type, exc, tb):
        self.server.shutdown()
        self.thread.join(timeout=5.0)
        self.server.server_close()
        return False


@dataclass
class _LiveSystemPluginSystem:
    gateway_url: str
    human_client_id: str
    admin_token: str


@pytest.fixture(scope="module")
def live_system_plugins_system():
    _require_live_system_plugins()
    human_client_id = f"system-plugins-live-{uuid4().hex[:8]}"
    env = os.environ.copy()
    env.update(
        {
            "AUTH_MODE": "oidc",
            "OIDC_AUDIENCE": human_client_id,
        }
    )
    subprocess.run(
        ["./open-talon", "stop"],
        cwd=_ROOT_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["./open-talon", "start", "--web-search"],
        cwd=_ROOT_DIR,
        env=env,
        check=True,
    )
    _wait_for_http_ok(
        f"{_KEYCLOAK_BASE_URL}/realms/{_OPEN_TALON_REALM}/.well-known/openid-configuration",
        description="Keycloak discovery",
    )
    _wait_for_searxng_container()
    _wait_for_http_ok(f"{_GATEWAY_URL}/health", description="gateway health")
    _wait_for_http_ok(_WEB_SEARCH_MCP_HEALTH_URL, description="web-search MCP health")
    admin_token = _master_admin_token()
    _ensure_password_grant_client(admin_token=admin_token, client_id=human_client_id)
    human_access_token = _password_grant_token(
        client_id=human_client_id,
        username="admin",
        password="admin123",
    )
    me_response = httpx.get(
        f"{_GATEWAY_URL}/v1/me",
        headers={"Authorization": f"Bearer {human_access_token}"},
        timeout=20.0,
    )
    if me_response.status_code != 200:
        raise AssertionError(
            f"Human OIDC login failed against the live gateway: {me_response.status_code} {me_response.text}"
        )
    try:
        yield _LiveSystemPluginSystem(
            gateway_url=_GATEWAY_URL,
            human_client_id=human_client_id,
            admin_token=human_access_token,
        )
    finally:
        try:
            _delete_keycloak_client(admin_token=_master_admin_token(), client_id=human_client_id)
        finally:
            subprocess.run(
                ["./open-talon", "stop"],
                cwd=_ROOT_DIR,
                env=env,
                check=False,
            )


def test_live_web_search_mcp_service_lists_tools_and_reports_searxng_container(
    live_system_plugins_system: _LiveSystemPluginSystem,
):
    health_response = httpx.get(_WEB_SEARCH_MCP_HEALTH_URL, timeout=20.0)
    health_response.raise_for_status()
    assert health_response.json()["searxng_base_url"] == _SEARXNG_BASE_URL

    initialized = _web_search_mcp_rpc("initialize")
    tools = _web_search_mcp_rpc("tools/list")["tools"]

    assert initialized["serverInfo"]["name"] == "open-talon-web-search-mcp"
    assert initialized["capabilities"]["tools"]["listChanged"] is False
    assert {tool["name"] for tool in tools} == {"search", "fetch", "search_and_fetch"}
    assert next(tool for tool in tools if tool["name"] == "fetch")["description"].endswith(
        "Crawl4AI."
    )


def test_live_web_search_mcp_fetch_extracts_local_fixture_without_internet(
    live_system_plugins_system: _LiveSystemPluginSystem,
):
    with _LocalFixtureServer() as fixture:
        result = _web_search_mcp_rpc(
            "tools/call",
            {
                "name": "fetch",
                "arguments": {
                    "url": fixture.url,
                    "max_chars": 4000,
                    "persist_asset": True,
                },
            },
        )

    payload = result["structuredContent"]
    assert payload["url"].startswith(fixture.url)
    assert "System Plugins" in payload["markdown"]
    assert "deterministic local fixture content" in payload["markdown"]
    assert payload["asset_candidate"]["content_type"] == "text/markdown"
    assert payload["metadata"]["extractor"] in {"crawl4ai", "httpx_html_parser"}


def test_live_seeded_web_search_plugin_syncs_and_attaches_to_workspace(
    live_system_plugins_system: _LiveSystemPluginSystem,
):
    actor = _actor_payload()
    suffix = uuid4().hex[:8]
    with httpx.Client(
        base_url=live_system_plugins_system.gateway_url,
        timeout=60.0,
    ) as client:
        plugins = _json_request(
            client,
            "GET",
            "/v1/system-plugins",
            token=live_system_plugins_system.admin_token,
        )
        assert isinstance(plugins, list)
        plugin = next(item for item in plugins if item["plugin_key"] == "web_search")
        plugin_id = plugin["plugin_id"]
        assert plugin["backing_protocol"] == "mcp"
        assert plugin["backing_server_id"] == plugin_id
        assert "server_id" not in plugin
        assert "server_key" not in plugin

        sync_result = _json_request(
            client,
            "POST",
            f"/v1/system-plugins/{plugin_id}/sync",
            token=live_system_plugins_system.admin_token,
            json_body={
                "actor": actor,
                "metadata": {"source": "system-plugin-live-test"},
            },
        )
        assert sync_result["plugin"]["plugin_id"] == plugin_id
        assert sync_result["job"]["plugin_id"] == plugin_id

        def _discovered_tools() -> list[dict[str, Any]] | None:
            response = client.get(
                f"/v1/system-plugins/{plugin_id}/tools",
                headers={"Authorization": f"Bearer {live_system_plugins_system.admin_token}"},
            )
            if response.status_code != 200:
                return None
            tools = response.json()
            names = {tool["name"] for tool in tools}
            if {"search", "fetch", "search_and_fetch"}.issubset(names):
                return tools
            return None

        tools = _wait_for(
            "web_search plugin capability discovery",
            _discovered_tools,
            timeout_seconds=120.0,
            interval_seconds=2.0,
        )
        assert all("server_id" not in tool for tool in tools)

        organization = _json_request(
            client,
            "POST",
            "/v1/organizations",
            token=live_system_plugins_system.admin_token,
            json_body={
                "actor": actor,
                "slug": f"system-plugin-live-{suffix}",
                "name": f"System Plugin Live {suffix}",
                "description": "Live System Plugin test organization.",
                "metadata": {"source": "system-plugin-live-test"},
            },
        )
        organization_id = str(organization["organization_id"])
        workspace = _json_request(
            client,
            "POST",
            f"/v1/organizations/{organization_id}/workspaces",
            token=live_system_plugins_system.admin_token,
            json_body={
                "actor": actor,
                "name": f"Plugin Workspace {suffix}",
                "description": "Live System Plugin attachment workspace.",
                "metadata": {"source": "system-plugin-live-test"},
            },
        )
        workspace_id = str(workspace["workspace"]["workspace_id"])

        attachment = _json_request(
            client,
            "PUT",
            f"/v1/workspaces/{workspace_id}/system-plugins/{plugin_id}",
            token=live_system_plugins_system.admin_token,
            json_body={
                "actor": actor,
                "enabled": True,
                "tools_enabled": True,
                "resources_enabled": False,
                "prompts_enabled": False,
                "name_prefix": "web_",
                "tool_allowlist": ["search", "fetch", "search_and_fetch"],
                "metadata": {
                    "persist_assets": False,
                    "asset_candidate_output": "disabled",
                },
            },
        )
        assert attachment["plugin_id"] == plugin_id
        assert attachment["plugin_key"] == "web_search"
        assert "server_id" not in attachment
        assert "server_key" not in attachment

        workspace_tools = _json_request(
            client,
            "GET",
            f"/v1/workspaces/{workspace_id}/plugin-capabilities/tools",
            token=live_system_plugins_system.admin_token,
        )
        exposed_names = {tool["exposed_name"] for tool in workspace_tools}
        assert {"web_search", "web_fetch", "web_search_and_fetch"}.issubset(exposed_names)
        assert all(tool["plugin_key"] == "web_search" for tool in workspace_tools)
        assert all("server_id" not in tool for tool in workspace_tools)
