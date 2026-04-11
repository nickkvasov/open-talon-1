from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import uuid4

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
from open_talon_tui.main import CollaborationApp, ClientState, TokenState


def test_profile_state_and_tokens_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    alice_state = ClientState(
        participant_id=str(uuid4()),
        user_id=str(uuid4()),
        display_name="Alice",
        participant_type="user",
    )
    bob_state = ClientState(
        participant_id=str(uuid4()),
        user_id=str(uuid4()),
        display_name="Bob",
        participant_type="user",
    )
    alice_tokens = TokenState(
        access_token="alice-token",
        refresh_token="alice-refresh",
        expires_at=None,
        issuer="http://issuer.test",
        client_id="open-talon-tui",
    )
    bob_tokens = TokenState(
        access_token="bob-token",
        refresh_token="bob-refresh",
        expires_at=None,
        issuer="http://issuer.test",
        client_id="open-talon-tui",
    )

    tui_main.save_state("alice", alice_state)
    tui_main.save_state("bob", bob_state)
    tui_main.save_tokens("alice", alice_tokens)
    tui_main.save_tokens("bob", bob_tokens)

    assert tui_main.load_state("alice", "ignored", "user").display_name == "Alice"
    assert tui_main.load_state("bob", "ignored", "user").display_name == "Bob"
    assert tui_main.load_tokens("alice").access_token == "alice-token"
    assert tui_main.load_tokens("bob").access_token == "bob-token"


def test_legacy_tokens_are_invalidated_and_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    token_file = legacy_dir / "tokens.json"
    token_file.write_text(
        """{
  "access_token": "legacy-token",
  "refresh_token": "legacy-refresh",
  "expires_at": null,
  "issuer": "http://issuer.test",
  "client_id": "open-talon-tui"
}"""
    )

    assert tui_main.load_tokens("legacy") is None
    assert not token_file.exists()


def test_reset_profile_session_state_clears_cached_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    state = tui_main.reset_profile_session_state(
        "legacy",
        display_name="operator",
        participant_type="user",
    )

    assert state.participant_id is None
    assert state.user_id is None
    assert state.workspace_id is None
    assert state.thread_id is None
    assert state.last_sequence == 0
    assert state.display_name == "operator"


def test_oidc_startup_without_valid_tokens_resets_stale_profile_state(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    legacy_dir = tmp_path / "test-profile"
    legacy_dir.mkdir()
    (legacy_dir / "state.json").write_text(
        """{
  "participant_id": "7192c9da-bd44-4013-b545-a5d12e813e14",
  "user_id": null,
  "display_name": "Nikolay",
  "participant_type": "user",
  "workspace_id": "bc4d03ba-737c-41ff-af85-bdfeeae36bbf",
  "thread_id": "5184083c-8f3b-4502-853c-cd842a318175",
  "last_sequence": 17
}"""
    )

    app = CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="test-profile",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="operator",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )

    assert app.tokens is None
    assert app.state.participant_id is None
    assert app.state.workspace_id is None
    assert app.state.thread_id is None
    assert app.state.display_name == "operator"


def test_list_profiles_prunes_legacy_profile_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    legacy_dir = tmp_path / "test-profile"
    legacy_dir.mkdir()
    (legacy_dir / "state.json").write_text(
        """{
  "participant_id": "7192c9da-bd44-4013-b545-a5d12e813e14",
  "user_id": null,
  "display_name": "Nikolay",
  "participant_type": "user",
  "workspace_id": "bc4d03ba-737c-41ff-af85-bdfeeae36bbf",
  "thread_id": "5184083c-8f3b-4502-853c-cd842a318175",
  "last_sequence": 17
}"""
    )

    profiles = tui_main.list_profiles()

    assert profiles == []
    assert not legacy_dir.exists()


@pytest.mark.asyncio
async def test_account_list_command_shows_profiles(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    tui_main.save_state(
        "alice",
        ClientState(participant_id=None, user_id=None, display_name="Alice", participant_type="user"),
    )
    tui_main.save_state(
        "bob",
        ClientState(participant_id=None, user_id=None, display_name="Bob", participant_type="user"),
    )

    app = CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="alice",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Alice",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )
    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))

    await app._handle_account_command("/account list")

    assert ("profiles:", "dim") in writes
    assert any(content.endswith("alice") for content, _ in writes)
    assert any(content.endswith("bob") for content, _ in writes)


@pytest.mark.asyncio
async def test_auth_logout_alias_clears_profile_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    tui_main.save_state(
        "alice",
        ClientState(participant_id=None, user_id=str(uuid4()), display_name="Alice", participant_type="user"),
    )
    tui_main.save_tokens(
        "alice",
        TokenState(
            access_token="alice-token",
            refresh_token="alice-refresh",
            expires_at=None,
            issuer="http://issuer.test",
            client_id="open-talon-tui",
        ),
    )

    app = CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="alice",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Alice",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )
    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))
    monkeypatch.setattr(app, "_update_context_info", lambda: None)

    await app._handle_auth_command("/auth logout")

    assert app.tokens is None
    assert tui_main.load_tokens("alice") is None
    assert ("signed out profile: alice", "yellow") in writes


def test_resolve_startup_profile_requires_explicit_choice_for_oidc(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    tui_main.save_state(
        "default",
        ClientState(participant_id=None, user_id=None, display_name="Default", participant_type="user"),
    )

    prompted: list[str] = []

    def _prompt(message: str) -> str:
        prompted.append(message)
        return "alice"

    profile = tui_main.resolve_startup_profile(
        None,
        oidc_enabled=True,
        prompt=_prompt,
    )

    assert profile == "alice"
    assert prompted == ["Profile number or new name: "]


def test_resolve_startup_profile_reuses_single_existing_profile_without_oidc(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)
    tui_main.save_state(
        "default",
        ClientState(participant_id=None, user_id=None, display_name="Default", participant_type="user"),
    )

    profile = tui_main.resolve_startup_profile(
        None,
        oidc_enabled=False,
    )

    assert profile == "default"


def test_resolve_startup_profile_fails_for_oidc_when_no_profile_is_provided(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    def _prompt(_: str) -> str:
        return ""

    with pytest.raises(SystemExit):
        tui_main.resolve_startup_profile(
            None,
            oidc_enabled=True,
            prompt=_prompt,
        )


def test_human_tui_requires_keycloak_oidc():
    with pytest.raises(RuntimeError, match="Keycloak OIDC"):
        CollaborationApp(
            gateway="http://127.0.0.1:8000",
            profile="alice",
            api_key=None,
            openbao_token=None,
            oidc_issuer_url=None,
            oidc_client_id=None,
            display_name="Alice",
            workspace_name="Workspace",
            thread_title="General",
            participant_type="user",
        )


def test_human_tui_rejects_api_key_auth():
    with pytest.raises(RuntimeError, match="cannot use API key or OpenBao auth"):
        CollaborationApp(
            gateway="http://127.0.0.1:8000",
            profile="alice",
            api_key="dev-key",
            openbao_token=None,
            oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
            oidc_client_id="open-talon-tui",
            display_name="Alice",
            workspace_name="Workspace",
            thread_title="General",
            participant_type="user",
        )


@pytest.mark.asyncio
async def test_initialize_allows_signed_out_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    app = CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="alice",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Alice",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )
    writes: list[tuple[str, str]] = []
    statuses: list[tuple[str, str]] = []
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))
    monkeypatch.setattr(app, "_update_status", lambda state, label: statuses.append((state, label)))
    monkeypatch.setattr(app, "_update_context_info", lambda: None)

    async def _fail_load_current_user() -> None:
        raise AssertionError("signed-out startup should not load current user")

    monkeypatch.setattr(app, "_load_current_user", _fail_load_current_user)
    monkeypatch.setattr(app, "_ensure_context", _fail_load_current_user)
    monkeypatch.setattr(app, "_load_timeline", _fail_load_current_user)
    monkeypatch.setattr(app, "_connect_ws", lambda: (_ for _ in ()).throw(AssertionError("signed-out startup should not open websocket")))

    await CollaborationApp._initialize.__wrapped__(app)

    assert app.current_user is None
    assert ("wait", "Signed out") in statuses
    assert ("sign in with /auth login", "yellow") in writes


@pytest.mark.asyncio
async def test_workspace_command_is_blocked_when_signed_out(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    app = CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="alice",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Alice",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )
    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))
    monkeypatch.setattr(app, "_update_status", lambda *_args, **_kwargs: None)

    async def _fail_workspace_command(_command: str) -> None:
        raise AssertionError("workspace command should be blocked when signed out")

    monkeypatch.setattr(app, "_handle_workspace_command", _fail_workspace_command)

    class _Input:
        def clear(self) -> None:
            return None

    class _Event:
        value = "/workspace list"
        input = _Input()

    await app.on_submit(_Event())

    assert ("sign in first with /auth login", "yellow") in writes


@pytest.mark.asyncio
async def test_submit_requeues_input_focus(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    app = CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="alice",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Alice",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )
    callbacks: list[object] = []
    monkeypatch.setattr(app, "call_after_refresh", lambda callback: callbacks.append(callback))
    monkeypatch.setattr(app, "_show_links", lambda: None)

    class _Input:
        def clear(self) -> None:
            return None

    class _Event:
        value = "/links"
        input = _Input()

    await app.on_submit(_Event())

    assert callbacks


def test_auth_login_cli_triggers_shared_auth_workflow(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    called: dict[str, str] = {}

    async def _fake_run_auth_login(**kwargs):
        called.update(kwargs)
        return {
            "user_id": "user-123",
            "display_name": "Alice Example",
        }

    monkeypatch.setattr(tui_main, "run_auth_login", _fake_run_auth_login)

    tui_main.main(
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
    assert called["oidc_issuer_url"] == "http://127.0.0.1:8081/realms/open-talon"
    assert called["oidc_client_id"] == "open-talon-tui"
    assert "Signed in profile: alice" in output
    assert "User: Alice Example" in output


def test_timeline_link_detection_tracks_links_in_plain_log_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(tui_main, "_PROFILES_DIR", tmp_path)

    app = CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="alice",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Alice",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )

    class _FakeRichLog:
        def __init__(self) -> None:
            self.lines: list[str] = []

        def write(self, line: str) -> None:
            self.lines.append(line)

    def _fake_query_one(selector: str, _expected_type):
        if selector == "#timeline":
            return timeline
        raise AssertionError(f"unexpected selector: {selector}")

    timeline = _FakeRichLog()
    monkeypatch.setattr(app, "query_one", _fake_query_one)

    app._append_timeline_line("see https://example.com/docs for details")

    assert "see https://example.com/docs for details" in timeline.lines
    assert "https://example.com/docs" in app._detected_links
