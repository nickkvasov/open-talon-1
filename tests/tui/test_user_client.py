from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest


_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_TUI_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../apps/tui")
)
for path in (_CONTRACTS_DIR, _TUI_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import open_talon_tui.main as tui_main
import open_talon_tui.user_client as user_client
from open_talon_tui.main import TokenState


class _FakeResponse:
    def __init__(self, status_code: int, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://test.invalid")
            response = httpx.Response(self.status_code, request=request, json=self._body)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)


class _FakeAsyncClient:
    def __init__(self, responses=None) -> None:
        self.headers = {}
        self.calls: list[dict] = []
        self._responses = list(responses or [])

    async def request(self, method: str, url: str, json=None, params=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "json": json,
                "params": params,
            }
        )
        if not self._responses:
            raise AssertionError(f"unexpected {method} {url}")
        return self._responses.pop(0)

    async def aclose(self) -> None:
        return None


def _token() -> TokenState:
    return TokenState(
        access_token="token",
        refresh_token=None,
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        issuer="http://127.0.0.1:8081/realms/open-talon",
        client_id="open-talon-tui",
    )


def test_user_client_main_dispatches_command_mode(monkeypatch):
    called = {}

    class _FakeClient:
        def __init__(self, **kwargs) -> None:
            called["kwargs"] = kwargs

        async def start(self, *, commands=None) -> int:
            called["commands"] = commands
            return 0

    monkeypatch.setattr(user_client, "UserClient", _FakeClient)

    with pytest.raises(SystemExit) as excinfo:
        user_client.main(["--profile", "alice", "--command", "status"])

    assert excinfo.value.code == 0
    assert called["kwargs"]["profile"] == "alice"
    assert called["commands"] == ["status"]


@pytest.mark.asyncio
async def test_user_client_send_command_posts_workspace_message_and_updates_state(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    client = user_client.UserClient(
        gateway="http://127.0.0.1:8000",
        profile="alice",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Alice",
        output_format="text",
    )
    client.tokens = _token()
    client.current_user = {"user_id": "user-123", "display_name": "Alice Example"}
    client.state.thread_id = "thread-123"
    client.state.participant_id = "participant-123"
    fake_http = _FakeAsyncClient(
        responses=[
            _FakeResponse(
                200,
                {
                    "message_id": "msg-1",
                    "workspace_id": "workspace-123",
                    "thread_id": "thread-123",
                    "actor": {"id": "participant-456"},
                    "content": "@role:reviewer Need feedback",
                    "created_at": "2026-04-19T10:00:00Z",
                    "updated_at": "2026-04-19T10:00:00Z",
                    "sequence": 4,
                    "metadata": {},
                },
            )
        ]
    )
    client._http_client = fake_http
    emitted = []
    monkeypatch.setattr(client, "_emit", lambda **payload: emitted.append(payload))
    monkeypatch.setattr(client, "_ensure_bearer_token", lambda: __import__("asyncio").sleep(0))

    await client.handle_command("send @role:reviewer Need feedback")

    assert fake_http.calls[0]["method"] == "POST"
    assert fake_http.calls[0]["url"].endswith("/v1/threads/thread-123/messages")
    assert fake_http.calls[0]["json"]["visibility"] == "workspace"
    assert fake_http.calls[0]["json"]["create_task"] is True
    assert fake_http.calls[0]["json"]["requests"][0]["selectors"] == [
        {"type": "role", "value": "reviewer"}
    ]
    assert client.state.workspace_id == "workspace-123"
    assert client.state.thread_id == "thread-123"
    assert client.state.participant_id == "participant-456"
    assert emitted[0]["command"] == "send"


@pytest.mark.asyncio
async def test_user_client_workspace_use_accepts_direct_uuid_without_visibility(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    client = user_client.UserClient(
        gateway="http://127.0.0.1:8000",
        profile="bob",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Bob",
        output_format="text",
    )
    client.tokens = _token()
    client.current_user = {"user_id": "user-456", "display_name": "Bob Example"}
    fake_http = _FakeAsyncClient(responses=[_FakeResponse(200, [])])
    client._http_client = fake_http
    emitted = []
    monkeypatch.setattr(client, "_emit", lambda **payload: emitted.append(payload))
    monkeypatch.setattr(client, "_ensure_bearer_token", lambda: __import__("asyncio").sleep(0))
    workspace_id = str(uuid4())

    await client.handle_command(f"workspace use {workspace_id}")

    assert client.state.workspace_id == workspace_id
    assert emitted[0]["command"] == "workspace.use"
    assert "selected workspace id" in emitted[0]["message"]


@pytest.mark.asyncio
async def test_user_client_role_use_calls_participant_role_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    client = user_client.UserClient(
        gateway="http://127.0.0.1:8000",
        profile="frontend",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Frontend",
        output_format="text",
    )
    client.tokens = _token()
    client.current_user = {"user_id": "user-789", "display_name": "Frontend Example"}
    client.state.workspace_id = "workspace-123"
    client.state.participant_id = "participant-123"
    fake_http = _FakeAsyncClient(
        responses=[
            _FakeResponse(
                200,
                {
                    "participant_id": "participant-123",
                    "roles": ["frontend_engineer"],
                    "capabilities": ["ui", "delivery"],
                },
            )
        ]
    )
    client._http_client = fake_http
    emitted = []
    monkeypatch.setattr(client, "_emit", lambda **payload: emitted.append(payload))
    monkeypatch.setattr(client, "_ensure_bearer_token", lambda: __import__("asyncio").sleep(0))

    await client.handle_command("role use frontend_engineer :: Owns UI delivery :: ui,delivery")

    assert fake_http.calls[0]["method"] == "PATCH"
    assert fake_http.calls[0]["url"].endswith(
        "/v1/workspaces/workspace-123/participants/participant-123/role"
    )
    assert fake_http.calls[0]["json"]["role"] == "frontend_engineer"
    assert fake_http.calls[0]["json"]["description"] == "Owns UI delivery"
    assert fake_http.calls[0]["json"]["capabilities"] == ["ui", "delivery"]
    assert emitted[0]["command"] == "role.use"


@pytest.mark.asyncio
async def test_user_client_request_answer_resolves_current_open_request(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    client = user_client.UserClient(
        gateway="http://127.0.0.1:8000",
        profile="lead",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Lead",
        output_format="text",
    )
    client.tokens = _token()
    client.current_user = {"user_id": "user-111", "display_name": "Lead Example"}
    client.state.thread_id = "thread-555"
    client.state.participant_id = "participant-111"
    fake_http = _FakeAsyncClient(
        responses=[
            _FakeResponse(
                200,
                [
                    {
                        "request": {
                            "request_id": "request-123",
                            "title": "Lead priority",
                            "status": "open",
                        },
                        "questions": [],
                        "targets": [],
                        "answers": [],
                    }
                ],
            ),
            _FakeResponse(
                200,
                {
                    "request": {"request_id": "request-123", "status": "completed"},
                    "answers": [{"participant_id": "participant-111"}],
                },
            ),
        ]
    )
    client._http_client = fake_http
    emitted = []
    monkeypatch.setattr(client, "_emit", lambda **payload: emitted.append(payload))
    monkeypatch.setattr(client, "_ensure_bearer_token", lambda: __import__("asyncio").sleep(0))

    await client.handle_command("request answer current :: Escalate the frontend blocker today.")

    assert fake_http.calls[0]["method"] == "GET"
    assert fake_http.calls[0]["url"].endswith("/v1/threads/thread-555/requests")
    assert fake_http.calls[1]["method"] == "POST"
    assert fake_http.calls[1]["url"].endswith("/v1/requests/request-123/answers")
    assert fake_http.calls[1]["json"]["content"] == "Escalate the frontend blocker today."
    assert emitted[0]["command"] == "request.answer"


@pytest.mark.asyncio
async def test_user_client_log_renders_thread_scoped_communication_log(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    client = user_client.UserClient(
        gateway="http://127.0.0.1:8000",
        profile="backend",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Backend",
        output_format="text",
    )
    client.tokens = _token()
    client.current_user = {"user_id": "user-222", "display_name": "Backend Example"}
    client.state.workspace_id = "workspace-abc"
    client.state.thread_id = "thread-xyz"
    fake_http = _FakeAsyncClient(
        responses=[
            _FakeResponse(
                200,
                {
                    "entries": [
                        {
                            "kind": "interaction_request",
                            "actor_display_name": "Standup Coordinator Agent",
                            "content": "What are you working on today?",
                            "created_at": "2026-04-19T10:00:00Z",
                        },
                        {
                            "kind": "interaction_answer",
                            "actor_display_name": "Backend Example",
                            "content": "I own the mitigation.",
                            "created_at": "2026-04-19T10:01:00Z",
                        },
                    ],
                    "total_count": 2,
                },
            )
        ]
    )
    client._http_client = fake_http
    emitted = []
    monkeypatch.setattr(client, "_emit", lambda **payload: emitted.append(payload))
    monkeypatch.setattr(client, "_ensure_bearer_token", lambda: __import__("asyncio").sleep(0))

    await client.handle_command("log 10")

    assert fake_http.calls[0]["params"] == {"limit": 10, "thread_id": "thread-xyz"}
    assert emitted[0]["command"] == "log"
    assert "interaction_request Standup Coordinator Agent" in emitted[0]["data"][0]
    assert "interaction_answer Backend Example" in emitted[0]["data"][1]
