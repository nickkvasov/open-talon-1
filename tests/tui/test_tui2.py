from __future__ import annotations

import asyncio
import builtins
import os
import sys
from datetime import datetime, timedelta, timezone

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
        self.buffer = ""

    def isatty(self) -> bool:
        return self._tty

    def write(self, value: str) -> int:
        self.buffer += value
        return len(value)

    def flush(self) -> None:
        return None


class _DummyStdin:
    def __init__(self, *, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty

    def fileno(self) -> int:
        return 0


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

    async def get(self, _url: str, params=None):
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


def test_tui2_main_resets_terminal_before_startup_profile(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(tui2, "_reset_terminal_mode", lambda: calls.append("reset"))
    monkeypatch.setattr(
        tui2,
        "resolve_startup_profile",
        lambda explicit_profile, oidc_enabled=True: calls.append("profile") or "admin",
    )

    class _FakeClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        async def start(self) -> None:
            calls.append("start")

    monkeypatch.setattr(tui2, "ScrollbackTUI2", _FakeClient)

    def _run(coro) -> None:
        calls.append("run")
        coro.close()

    monkeypatch.setattr(tui2.asyncio, "run", _run)

    tui2.main(["--profile", "admin"])

    assert calls[:2] == ["reset", "profile"]


def test_tui2_status_lines_reflect_current_context(tmp_path, monkeypatch):
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
    client.current_user = {"user_id": "user-123", "display_name": "Alice Example"}
    client.tokens = TokenState(
        access_token="token",
        refresh_token=None,
        expires_at=None,
        issuer="http://127.0.0.1:8081/realms/open-talon",
        client_id="open-talon-tui",
    )
    client.state.organization_id = "org-1234"
    client.state.workspace_id = "workspace-1234"
    client.state.thread_id = "thread-5678"
    client.state.participant_id = "participant-9012"
    client.state.display_name = "Alice Example"
    client._detected_links = ["https://example.com/docs", "https://example.com/guide"]
    client._connection_status = "connected"
    client._recent_activity = ["history loaded", "profile ready"]

    lines = client._status_lines()

    assert lines[0].startswith("┌─ Open Talon TUI2")
    assert any("Profile: alice" in line for line in lines)
    assert any("Auth: Alice Example" in line for line in lines)
    assert any("Conn: connected | Links: 2" in line for line in lines)
    assert any("Organization: org-1234" in line for line in lines)
    assert any("Workspace: workspac" in line for line in lines)
    assert any("Thread: thread-5" in line for line in lines)
    assert any("Participant: particip" in line for line in lines)
    assert any("Recent activity" in line for line in lines)
    assert any("profile ready" in line for line in lines)


def test_tui2_render_status_panel_writes_fixed_header(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    stdout = _DummyStdout(tty=True)
    monkeypatch.setattr(tui2.sys, "stdout", stdout)

    client = tui2.ScrollbackTUI2(
        gateway="http://127.0.0.1:8000",
        profile="alice",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Alice",
        workspace_name="Workspace",
        thread_title="General",
    )

    client._render_status_panel()

    assert "Open Talon TUI2" in stdout.buffer
    assert "Profile: alice" in stdout.buffer
    assert "\033[H" in stdout.buffer
    assert "\033[11;24r" in stdout.buffer
    assert client._status_initialized is True


def test_tui2_render_status_panel_skips_unchanged_redraw(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    stdout = _DummyStdout(tty=True)
    monkeypatch.setattr(tui2.sys, "stdout", stdout)

    client = tui2.ScrollbackTUI2(
        gateway="http://127.0.0.1:8000",
        profile="alice",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Alice",
        workspace_name="Workspace",
        thread_title="General",
    )

    client._render_status_panel()
    stdout.buffer = ""
    client._render_status_panel()

    assert stdout.buffer == ""


def test_tui2_restore_terminal_resets_scroll_region(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    stdout = _DummyStdout(tty=True)
    monkeypatch.setattr(tui2.sys, "stdout", stdout)

    client = tui2.ScrollbackTUI2(
        gateway="http://127.0.0.1:8000",
        profile="alice",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Alice",
        workspace_name="Workspace",
        thread_title="General",
    )
    client._render_status_panel()

    stdout.buffer = ""
    client._restore_terminal()

    assert "\033[r" in stdout.buffer
    assert client._status_initialized is False


def test_tui2_set_connection_status_updates_header_state(tmp_path, monkeypatch):
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
    calls: list[str] = []
    monkeypatch.setattr(client, "_render_status_panel", lambda: calls.append("render"))

    client._set_connection_status("reconnecting")

    assert client._connection_status == "reconnecting"
    assert calls == ["render"]


def test_tui2_parse_tool_request_scope_supports_organization_flag():
    scope, text = tui2.ScrollbackTUI2._parse_tool_request_scope(
        "--scope organization Build Fibonacci tool"
    )

    assert scope == "organization"
    assert text == "Build Fibonacci tool"


def test_tui2_history_navigation_tracks_saved_buffer(tmp_path, monkeypatch):
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
    client._remember_input("/workspace list")
    client._remember_input("/thread list")

    previous = client._history_previous("/wo")
    oldest = client._history_previous(previous)
    forward = client._history_next()
    restored = client._history_next()

    assert previous == "/thread list"
    assert oldest == "/workspace list"
    assert forward == "/thread list"
    assert restored == "/wo"


def test_tui2_current_completion_returns_first_fill_candidate(tmp_path, monkeypatch):
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

    completion = client._current_completion("/wo")

    assert completion == "/workspace list"


def test_tui2_write_system_formats_nested_result(tmp_path, monkeypatch):
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
    lines: list[str] = []
    monkeypatch.setattr(client, "_record_line", lambda text: lines.append(text))

    client._write_system("status dialog dismissed")

    assert lines == ["  └ status dialog dismissed"]
    assert client._recent_activity == ["status dialog dismissed"]


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


def test_tui2_command_suggestions_cover_supported_commands(tmp_path, monkeypatch):
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

    suggestions = client._command_suggestions("/wo")

    assert "/workspace list" in suggestions
    assert "/workspace show" in suggestions
    assert "/workspace create" in suggestions
    assert "/workspace use" in suggestions
    assert "/llm-provider list" in client._command_suggestions("/llm")


def test_tui2_command_suggestions_include_profiles_and_links(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    tui_main.save_state(
        "bob",
        tui_main.ClientState(
            participant_id=None,
            user_id=None,
            display_name="Bob",
            participant_type="user",
        ),
    )

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

    account_suggestions = client._command_suggestions("/account switch ")
    open_suggestions = client._command_suggestions("/open ")

    assert "/account switch bob" in account_suggestions
    assert "/open 1" in open_suggestions
    assert "/open last" in open_suggestions


@pytest.mark.asyncio
async def test_tui2_llm_provider_show_displays_provider(tmp_path, monkeypatch):
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
    client.tokens = TokenState(
        access_token="token",
        refresh_token=None,
        expires_at=None,
        issuer="http://127.0.0.1:8081/realms/open-talon",
        client_id="open-talon-tui",
    )
    client.current_user = {"user_id": "user-123", "display_name": "Alice Example"}
    writes: list[str] = []
    provider = {
        "provider_id": "provider-1234",
        "engine_id": "openai-responses",
        "display_name": "OpenAI Responses",
        "description": "OpenAI Responses API",
        "provider": "openai",
        "endpoint_kind": "remote",
        "url": "https://api.openai.com/v1/responses",
        "default_model": "gpt-5.4-mini",
        "capabilities": ["text", "reasoning"],
        "locality": "cloud",
        "priority": 100,
        "enabled": True,
        "secret_config": {"openbao": {"path": "open-talon/llm/openai", "field": "api_key"}},
        "metadata": {"team": "platform"},
    }

    async def fake_list_llm_providers():
        client._llm_provider_suggestions = [
            {
                "provider_id": provider["provider_id"],
                "engine_id": provider["engine_id"],
                "display_name": provider["display_name"],
            }
        ]
        return [provider]

    monkeypatch.setattr(client, "_list_llm_providers", fake_list_llm_providers)
    monkeypatch.setattr(client, "_write_system", lambda text: writes.append(text))

    await client._handle_llm_provider_command("/llm-provider show openai-responses")

    assert "name: OpenAI Responses" in writes
    assert "engine id: openai-responses" in writes
    assert any("secret config:" in line for line in writes)


@pytest.mark.asyncio
async def test_tui2_llm_provider_create_parses_key_value_payload(tmp_path, monkeypatch):
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
    client.tokens = TokenState(
        access_token="token",
        refresh_token=None,
        expires_at=None,
        issuer="http://127.0.0.1:8081/realms/open-talon",
        client_id="open-talon-tui",
    )
    client.current_user = {"user_id": "user-123", "display_name": "Alice Example"}
    writes: list[str] = []
    captured: dict[str, object] = {}

    async def fake_create_llm_provider(payload: dict[str, object]):
        captured.update(payload)
        return {
            "provider_id": "provider-5678",
            "engine_id": payload["engine_id"],
            "display_name": payload["display_name"],
        }

    monkeypatch.setattr(client, "_create_llm_provider", fake_create_llm_provider)
    monkeypatch.setattr(client, "_write_system", lambda text: writes.append(text))

    await client._handle_llm_provider_command(
        "/llm-provider create "
        'engine_id=groq-llama display_name="Groq Llama" provider=groq '
        'description="Groq chat endpoint" url=https://api.groq.com/openai/v1/responses '
        "capabilities=text,fast locality=cloud priority=80 enabled=true"
    )

    assert captured["engine_id"] == "groq-llama"
    assert captured["display_name"] == "Groq Llama"
    assert captured["capabilities"] == ["text", "fast"]
    assert captured["priority"] == 80
    assert captured["enabled"] is True
    assert "created llm provider: Groq Llama (groq-llama)" in writes


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
async def test_tui2_refresh_revalidates_authenticated_user(tmp_path, monkeypatch):
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
        refresh_token="refresh-token",
        expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        issuer="http://127.0.0.1:8081/realms/open-talon",
        client_id="open-talon-tui",
    )
    validations: list[bool] = []

    async def _refresh_oidc_tokens() -> bool:
        client.tokens = TokenState(
            access_token="fresh-token",
            refresh_token="refresh-token",
            expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            issuer="http://127.0.0.1:8081/realms/open-talon",
            client_id="open-talon-tui",
        )
        return True

    async def _validate_current_user_session(*, force: bool = False) -> None:
        validations.append(force)

    monkeypatch.setattr(client, "_refresh_oidc_tokens", _refresh_oidc_tokens)
    monkeypatch.setattr(client, "_validate_current_user_session", _validate_current_user_session)

    await client._ensure_bearer_token()

    assert validations == [True]


@pytest.mark.asyncio
async def test_tui2_periodic_user_validation_invalidates_session(tmp_path, monkeypatch):
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
        access_token="token",
        refresh_token="refresh-token",
        expires_at=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
        issuer="http://127.0.0.1:8081/realms/open-talon",
        client_id="open-talon-tui",
    )
    client.current_user = {"user_id": "user-123", "display_name": "Admin"}
    writes: list[str] = []
    monkeypatch.setattr(client, "_write_system", lambda text: writes.append(text))

    request = httpx.Request("GET", "http://127.0.0.1:8000/v1/me")
    response = httpx.Response(401, request=request, json={"detail": "OIDC authentication required"})

    async def _load_current_user() -> None:
        raise httpx.HTTPStatusError("401 unauthorized", request=request, response=response)

    monkeypatch.setattr(client, "_load_current_user", _load_current_user)

    await client._validate_current_user_session(force=True)

    assert client.tokens is None
    assert client.current_user is None
    assert any("authenticated session is no longer valid; run /auth login" in line for line in writes)


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
        get_responses=[
            _FakeResponse(
                200,
                [
                    {
                        "organization_id": "org-123",
                        "slug": "default",
                        "name": "Default Org",
                    }
                ],
            )
        ],
        post_responses=[
            _FakeResponse(
                200,
                {
                    "workspace": {
                        "workspace_id": "workspace-123",
                        "organization_id": "org-123",
                        "name": "Workspace",
                    },
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
    assert client.state.organization_id == "org-123"


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


@pytest.mark.asyncio
async def test_tui2_start_adds_prompt_entries_to_input_history(tmp_path, monkeypatch):
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

    async def _activate_profile_session() -> None:
        return None

    async def _handle_command(_text: str) -> None:
        client._stop = True

    commands = iter(["/help"])

    def _input(_prompt: str = "") -> str:
        try:
            return next(commands)
        except StopIteration as exc:  # pragma: no cover - defensive
            raise EOFError from exc

    monkeypatch.setattr(client, "_activate_profile_session", _activate_profile_session)
    monkeypatch.setattr(client, "_handle_command", _handle_command)
    monkeypatch.setattr(client, "_supports_tty_prompt", lambda: False)
    monkeypatch.setattr(builtins, "input", _input)

    await client.start()

    assert client._input_history == ["/help"]


def test_build_interaction_requests_from_text_parses_selectors():
    requests = tui2._build_interaction_requests_from_text(
        "@role:reviewer @capability:backend What blocks delivery?"
    )

    assert len(requests) == 1
    assert requests[0]["questions"][0]["prompt"] == "What blocks delivery?"
    assert requests[0]["selectors"] == [
        {"type": "role", "value": "reviewer"},
        {"type": "capability", "value": "backend"},
    ]


@pytest.mark.asyncio
async def test_send_message_includes_parsed_interaction_requests(monkeypatch):
    client = tui2.ScrollbackTUI2(
        gateway="http://127.0.0.1:8000",
        profile="admin",
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Admin",
        workspace_name="Workspace",
        thread_title="General",
    )
    client.state.thread_id = "thread-123"
    client.state.workspace_id = "workspace-123"
    client.state.participant_id = "participant-123"
    client.current_user = {"user_id": "user-123", "display_name": "Admin"}
    client.tokens = TokenState(
        access_token="token",
        refresh_token=None,
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        issuer="http://127.0.0.1:8081/realms/open-talon",
        client_id="open-talon-tui",
    )

    captured = {}

    class _CapturingClient(_FakeAsyncClient):
        async def post(self, url: str, json=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse(200, {})

    client._http_client = _CapturingClient()
    monkeypatch.setattr(client, "_ensure_bearer_token", lambda: asyncio.sleep(0))
    monkeypatch.setattr(client, "_validate_current_user_session", lambda: asyncio.sleep(0))

    await client._send_message("@role:reviewer Need feedback")

    assert captured["json"]["requests"][0]["selectors"] == [{"type": "role", "value": "reviewer"}]


def test_render_message_marks_interaction_request_progress(tmp_path, monkeypatch):
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
    lines: list[str] = []
    monkeypatch.setattr(client, "_record_line", lambda line: lines.append(line))

    client._render_message(
        {
            "message_id": "msg-1",
            "actor": {"id": "peer-123"},
            "content": "Need blockers from reviewers.",
            "created_at": "2026-04-18T08:00:00Z",
            "metadata": {
                "interaction_request_id": "request-1",
                "interaction_request_status": "open",
                "interaction_aggregate": {"answered_count": 2, "target_count": 3},
            },
        }
    )

    assert len(lines) == 1
    assert "[request open 2/3]" in lines[0]
    assert "Need blockers from reviewers." in lines[0]


def test_render_message_marks_interaction_answers(tmp_path, monkeypatch):
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
    lines: list[str] = []
    monkeypatch.setattr(client, "_record_line", lambda line: lines.append(line))

    client._render_message(
        {
            "message_id": "msg-2",
            "actor": {"id": "peer-456"},
            "content": "Backend is blocked on review.",
            "created_at": "2026-04-18T08:01:00Z",
            "metadata": {
                "interaction_question_ids": ["question-1"],
            },
        }
    )

    assert len(lines) == 1
    assert "[answer]" in lines[0]
    assert "Backend is blocked on review." in lines[0]


def test_handle_event_marks_publication_review_events(tmp_path, monkeypatch):
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
    client.state.participant_id = "participant-1"
    lines: list[str] = []
    monkeypatch.setattr(client, "_write_system", lambda line: lines.append(line))

    client._handle_event({"event_type": "message.publication_review_pending", "sequence": 1})
    client._handle_event({"event_type": "message.publication_flagged", "sequence": 2})
    client._handle_event({"event_type": "message.publication_suppressed", "sequence": 3})

    assert lines == [
        "message pending publication review",
        "message flagged for topic drift",
        "message suppressed by publication review",
    ]
