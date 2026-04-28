from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import psycopg
import pytest


KEYCLOAK_BASE_URL = "http://127.0.0.1:8081"
OPEN_TALON_REALM = "open-talon"
STEWARD_ORGANIZATION_CREATE_TOOL = "control_plane__organizations.create"
PROJECT_CREATE_TOOL = "control_plane__projects.create"
WORKSPACE_CREATE_TOOL = "control_plane__workspaces.create"
METHODICS_EXECUTION_GET_TOOL = "control_plane__methodics.executions.get"
METHODICS_RESOURCE_REQUEST_CREATE_TOOL = "control_plane__methodics.resource_requests.create"


def postgres_dsn() -> str:
    return os.getenv(
        "POSTGRES_DSN",
        "postgresql://admin:password@127.0.0.1:5432/app_db",
    )


def gateway_url() -> str:
    return os.getenv("OPEN_TALON_GATEWAY_URL", "http://127.0.0.1:8000").rstrip("/")


def human_client_id() -> str:
    return os.getenv("OPEN_TALON_TUI_CLIENT_ID", "open-talon-tui")


def live_actor(*, display_name: str = "Live Admin") -> dict[str, Any]:
    return {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": display_name,
    }


def require_live_operational_agents() -> None:
    if os.getenv("OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE") != "1":
        pytest.skip(
            "Set OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 and start the local stack with ./open-talon start."
        )


def json_request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> dict | list:
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


def form_request(url: str, payload: dict[str, str]) -> dict:
    data = urlencode(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=20.0) as response:  # noqa: S310 - local live-system test
        return json.loads(response.read().decode("utf-8"))


def master_admin_token() -> str:
    deadline = time.monotonic() + 120.0
    last_detail = "not attempted"
    while time.monotonic() < deadline:
        try:
            payload = form_request(
                f"{KEYCLOAK_BASE_URL}/realms/master/protocol/openid-connect/token",
                {
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": "admin",
                    "password": "admin",
                },
            )
            return payload["access_token"]
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_detail = f"{exc.code} {body[:200]}"
        except OSError as exc:
            last_detail = str(exc)
        time.sleep(1.0)
    raise AssertionError(f"Timed out waiting for Keycloak master admin token: {last_detail}")


def keycloak_client_internal_id(*, admin_token: str, client_id: str) -> str | None:
    payload = json_request(
        "GET",
        f"{KEYCLOAK_BASE_URL}/admin/realms/{OPEN_TALON_REALM}/clients?clientId={client_id}",
        token=admin_token,
    )
    if not payload:
        return None
    internal_id = payload[0].get("id")
    return str(internal_id) if internal_id else None


def keycloak_client_representation(*, admin_token: str, client_id: str) -> dict:
    internal_id = keycloak_client_internal_id(admin_token=admin_token, client_id=client_id)
    if internal_id is None:
        raise AssertionError(f"Keycloak client {client_id!r} does not exist")
    payload = json_request(
        "GET",
        f"{KEYCLOAK_BASE_URL}/admin/realms/{OPEN_TALON_REALM}/clients/{internal_id}",
        token=admin_token,
    )
    assert isinstance(payload, dict)
    return payload


def set_direct_access_grants(*, admin_token: str, client_id: str, enabled: bool) -> bool:
    internal_id = keycloak_client_internal_id(admin_token=admin_token, client_id=client_id)
    if internal_id is None:
        raise AssertionError(f"Keycloak client {client_id!r} does not exist")
    representation = keycloak_client_representation(admin_token=admin_token, client_id=client_id)
    original = bool(representation.get("directAccessGrantsEnabled"))
    if original == enabled:
        return original
    representation["directAccessGrantsEnabled"] = enabled
    try:
        json_request(
            "PUT",
            f"{KEYCLOAK_BASE_URL}/admin/realms/{OPEN_TALON_REALM}/clients/{internal_id}",
            token=admin_token,
            payload=representation,
        )
    except HTTPError as exc:
        if exc.code not in {204}:
            raise
    return original


@contextmanager
def direct_access_grants_enabled(*, client_id: str) -> Iterator[None]:
    original = set_direct_access_grants(
        admin_token=master_admin_token(),
        client_id=client_id,
        enabled=True,
    )
    try:
        yield
    finally:
        set_direct_access_grants(
            admin_token=master_admin_token(),
            client_id=client_id,
            enabled=original,
        )


def admin_token(*, client_id: str) -> str:
    issuer = os.getenv(
        "OPEN_TALON_OIDC_ISSUER_URL",
        "http://127.0.0.1:8081/realms/open-talon",
    ).rstrip("/")
    payload = form_request(
        f"{issuer}/protocol/openid-connect/token",
        {
            "grant_type": "password",
            "client_id": client_id,
            "username": os.getenv("OPEN_TALON_LIVE_ADMIN_USERNAME", "admin"),
            "password": os.getenv("OPEN_TALON_LIVE_ADMIN_PASSWORD", "admin123"),
        },
    )
    return payload["access_token"]


def mcp_call(
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
    payload = json_request(
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


def initialize_mcp_session(gateway: str, token: str) -> tuple[str, dict[str, Any]]:
    request = Request(
        f"{gateway}/v1/mcp",
        data=json.dumps(
            {"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {}}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urlopen(request, timeout=20.0) as response:  # noqa: S310 - local live-system test
        session_id = response.headers["Mcp-Session-Id"]
        payload = json.loads(response.read().decode("utf-8"))
    return session_id, payload


def wait_for(
    description: str,
    predicate: Callable[[], Any],
    *,
    timeout_seconds: float = 120.0,
    interval_seconds: float = 1.0,
) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last_value = None
    while time.monotonic() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(interval_seconds)
    raise AssertionError(f"Timed out waiting for {description}; last_value={last_value!r}")


def tool_call_rows(
    *,
    thread_id: str,
    system_agent_id: str,
    tool_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    placeholders = ", ".join(["%s"] * len(tool_names))
    with psycopg.connect(postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    tool_name,
                    status,
                    result,
                    metadata
                FROM tool_calls
                WHERE thread_id = %s
                  AND system_agent_id = %s
                  AND tool_name IN ({placeholders})
                ORDER BY created_at ASC
                """,
                (thread_id, system_agent_id, *tool_names),
            )
            rows = cur.fetchall()
    return [
        {
            "tool_name": tool_name,
            "status": status,
            "result": result,
            "metadata": metadata,
        }
        for tool_name, status, result, metadata in rows
    ]


def steward_created_resource_rows(
    *,
    organization_slug: str,
    project_slug: str,
    workspace_name: str,
) -> dict[str, Any] | None:
    with psycopg.connect(postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    organization.organization_id,
                    organization.created_by,
                    project.project_id,
                    project.created_by,
                    project.creator_system_agent_id,
                    workspace.workspace_id,
                    workspace.created_by,
                    workspace.creator_user_id,
                    workspace.creator_system_agent_id,
                    workspace.metadata
                FROM organizations AS organization
                JOIN projects AS project
                  ON project.organization_id = organization.organization_id
                 AND project.slug = %s
                JOIN workspaces AS workspace
                  ON workspace.project_id = project.project_id
                 AND workspace.name = %s
                WHERE organization.slug = %s
                """,
                (project_slug, workspace_name, organization_slug),
            )
            row = cur.fetchone()
    if row is None:
        return None
    (
        organization_id,
        organization_created_by,
        project_id,
        project_created_by,
        project_creator_system_agent_id,
        workspace_id,
        workspace_created_by,
        workspace_creator_user_id,
        workspace_creator_system_agent_id,
        workspace_metadata,
    ) = row
    return {
        "organization_id": str(organization_id),
        "organization_created_by": str(organization_created_by),
        "project_id": str(project_id),
        "project_created_by": str(project_created_by),
        "project_creator_system_agent_id": (
            str(project_creator_system_agent_id)
            if project_creator_system_agent_id is not None
            else None
        ),
        "workspace_id": str(workspace_id),
        "workspace_created_by": str(workspace_created_by),
        "workspace_creator_user_id": (
            str(workspace_creator_user_id) if workspace_creator_user_id is not None else None
        ),
        "workspace_creator_system_agent_id": (
            str(workspace_creator_system_agent_id)
            if workspace_creator_system_agent_id is not None
            else None
        ),
        "workspace_metadata": workspace_metadata,
    }
