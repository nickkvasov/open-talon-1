from __future__ import annotations

import os
import sys


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


class _DummyStdout:
    def __init__(self, *, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


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
