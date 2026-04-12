from __future__ import annotations

import builtins
import os
import sys

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
import open_talon_tui.tui2 as tui2
from open_talon_tui.main import TokenState


class _DummyStdout:
    def __init__(self, *, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


class _FakeResponse:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "http://test.invalid")
            response = httpx.Response(self.status_code, request=request, json=self._body)
            raise httpx.HTTPStatusError("request failed", request=request, response=response)


class _FakeAsyncClient:
    def __init__(self, *, get_responses=None, post_responses=None) -> None:
        self.headers = {}
        self._get_responses = list(get_responses or [])
        self._post_responses = list(post_responses or [])

    async def get(self, _url: str):
        if not self._get_responses:
            raise AssertionError("unexpected GET")
        return self._get_responses.pop(0)

    async def post(self, _url: str, json=None):
        if not self._post_responses:
            raise AssertionError("unexpected POST")
        return self._post_responses.pop(0)


def test_render_terminal_links_wraps_urls_for_tty(monkeypatch):
    monkeypatch.setattr(tui2.sys, "stdout", _DummyStdout(tty=True))

    rendered = tui2._render_terminal_links("see https://example.com/docs")

    assert "\033]8;;https://example.com/docs\033\\" in rendered
    assert rendered.endswith("\033]8;;\033\\")


def test_open_link_by_index_uses_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    client = tui2.ScrollbackTUI2(
        gateway="http://127.0.0.1:8000",
        profile="alice",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Alice",
        workspace_name="Workspace",
        thread_title="General",
    )
    client._detected_links = ["https://example.com/docs"]
    writes: list[str] = []
    opened: list[str] = []
    monkeypatch.setattr(client, "_write_system", lambda text: writes.append(text))
    monkeypatch.setattr(tui2.webbrowser, "open", lambda url, new=2: opened.append(url))

    client._open_link("1")

    assert opened == ["https://example.com/docs"]
    assert writes == ["opened link: https://example.com/docs"]


def test_tui2_auth_login_cli_triggers_shared_auth_workflow(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    called: dict[str, str] = {}

    async def _fake_run_auth_login(**kwargs):
        called.update(kwargs)
        return {
            "user_id": "user-123",
            "display_name": "Alice Example",
        }

    monkeypatch.setattr(tui2, "run_auth_login", _fake_run_auth_login)

    tui2.main(
        [
            "auth",
            "login",
            "--gateway",
            "http://127.0.0.1:8000",
            "--profile",
            "alice",
            "--oidc-issuer-url",
            "http://127.0.0.1:8081/realms/open-talon",
            "--oidc-client-id",
            "open-talon-tui",
            "--display-name",
            "Alice",
        ]
    )

    output = capsys.readouterr().out
    assert called["profile"] == "alice"
    assert called["gateway"] == "http://127.0.0.1:8000"
    assert "Signed in profile: alice" in output
    assert "User: Alice Example" in output


@pytest.mark.asyncio
async def test_tui2_invalid_saved_token_falls_back_to_signed_out(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    tui_main.save_tokens(
        "admin",
        TokenState(
            access_token="expired-token",
            refresh_token="expired-refresh",
            expires_at="2000-01-01T00:00:00+00:00",
            issuer="http://127.0.0.1:8081/realms/open-talon",
            client_id="open-talon-tui",
        ),
    )

    client = tui2.ScrollbackTUI2(
        gateway="http://127.0.0.1:8000",
        profile="admin",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Admin",
        workspace_name="Workspace",
        thread_title="General",
    )
    writes: list[str] = []
    monkeypatch.setattr(client, "_write_system", lambda text: writes.append(text))

    async def _refresh_oidc_tokens() -> bool:
        return False

    monkeypatch.setattr(client, "_refresh_oidc_tokens", _refresh_oidc_tokens)

    await client._activate_profile_session()

    assert client.tokens is None
    assert client.current_user is None
    assert any("token refresh failed; run /auth login" in line for line in writes)
    assert any("signed out (admin); run /auth login" in line for line in writes)


@pytest.mark.asyncio
async def test_tui2_create_thread_accepts_thread_detail_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    client = tui2.ScrollbackTUI2(
        gateway="http://127.0.0.1:8000",
        profile="admin",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Admin",
        workspace_name="Workspace",
        thread_title="General",
    )
    client.state.workspace_id = "workspace-123"
    client._http_client = _FakeAsyncClient(
        post_responses=[
            _FakeResponse(
                200,
                {
                    "thread": {"thread_id": "thread-456", "title": "General"},
                    "memberships": [{"participant_id": "participant-789"}],
                },
            )
        ]
    )

    await client._create_thread("General")

    assert client.state.thread_id == "thread-456"
    assert client.state.participant_id == "participant-789"
    assert client.state.last_sequence == 0


@pytest.mark.asyncio
async def test_tui2_ensure_context_accepts_workspace_detail_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    client = tui2.ScrollbackTUI2(
        gateway="http://127.0.0.1:8000",
        profile="admin",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Admin",
        workspace_name="Workspace",
        thread_title="General",
    )
    client.state.user_id = "user-123"
    client._http_client = _FakeAsyncClient(
        post_responses=[
            _FakeResponse(
                200,
                {
                    "workspace": {"workspace_id": "workspace-123", "name": "Workspace"},
                    "participants": [{"participant_id": "participant-111", "user_id": "user-123"}],
                },
            ),
            _FakeResponse(
                200,
                {
                    "thread": {"thread_id": "thread-456", "title": "General"},
                    "memberships": [{"participant_id": "participant-111"}],
                },
            ),
        ]
    )

    await client._ensure_context()

    assert client.state.workspace_id == "workspace-123"
    assert client.state.thread_id == "thread-456"
    assert client.state.participant_id == "participant-111"


@pytest.mark.asyncio
async def test_tui2_start_survives_startup_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    client = tui2.ScrollbackTUI2(
        gateway="http://127.0.0.1:8000",
        profile="admin",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Admin",
        workspace_name="Workspace",
        thread_title="General",
    )
    writes: list[str] = []
    monkeypatch.setattr(client, "_write_system", lambda text: writes.append(text))

    async def _activate_profile_session() -> None:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(client, "_activate_profile_session", _activate_profile_session)
    monkeypatch.setattr(builtins, "input", lambda _prompt="": (_ for _ in ()).throw(EOFError))

    await client.start()

    assert any("startup error: connection refused" in line for line in writes)


@pytest.mark.asyncio
async def test_tui2_start_survives_failing_command_and_invalidates_auth(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    client = tui2.ScrollbackTUI2(
        gateway="http://127.0.0.1:8000",
        profile="admin",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Admin",
        workspace_name="Workspace",
        thread_title="General",
    )
    client.tokens = TokenState(
        access_token="stale-token",
        refresh_token="stale-refresh",
        expires_at=None,
        issuer="http://127.0.0.1:8081/realms/open-talon",
        client_id="open-talon-tui",
    )
    writes: list[str] = []
    monkeypatch.setattr(client, "_write_system", lambda text: writes.append(text))

    async def _activate_profile_session() -> None:
        return None

    commands = iter(["/workspace list"])

    def _input(_prompt: str = "") -> str:
        try:
            return next(commands)
        except StopIteration as exc:  # pragma: no cover - defensive
            raise EOFError from exc

    request = httpx.Request("GET", "http://127.0.0.1:8000/v1/workspaces")
    response = httpx.Response(401, request=request, json={"detail": "OIDC authentication required"})

    async def _handle_command(_text: str) -> None:
        client._stop = True
        raise httpx.HTTPStatusError("401 unauthorized", request=request, response=response)

    monkeypatch.setattr(client, "_activate_profile_session", _activate_profile_session)
    monkeypatch.setattr(client, "_handle_command", _handle_command)
    monkeypatch.setattr(builtins, "input", _input)

    await client.start()

    assert client.tokens is None
    assert any("authentication expired; run /auth login" in line for line in writes)
