"""
Open Talon TUI2.

A simple scrollback-first terminal client intended for reliable mouse selection
and terminal-native link clicking.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import shutil
import sys
import termios
import threading
import tty
import webbrowser
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import websockets
import websockets.exceptions

from open_talon_tui.main import (
    _LLM_PROVIDER_COMMAND_HELP,
    _LLM_PROVIDER_CREATE_USAGE,
    _LLM_PROVIDER_UPDATE_USAGE,
    _DEFAULT_OIDC_CLIENT_ID,
    _DEFAULT_OIDC_ISSUER_URL,
    _URL_PATTERN,
    _build_llm_provider_payload,
    _parse_command_assignments,
    _resolve_llm_provider_target,
    ClientState,
    TokenState,
    discover_oidc,
    fetch_current_user,
    list_profiles,
    load_state,
    load_tokens,
    resolve_startup_profile,
    reset_profile_session_state,
    run_auth_login,
    run_device_login,
    save_state,
    save_tokens,
)


def _render_terminal_links(text: str) -> str:
    if not sys.stdout.isatty():
        return text

    def _wrap(match) -> str:
        url = match.group(0)
        return f"\033]8;;{url}\033\\{url}\033]8;;\033\\"

    return _URL_PATTERN.sub(_wrap, text)


def _format_timestamp(raw_timestamp: str | None) -> str:
    if not raw_timestamp:
        return "--:--"


_INTERACTION_SELECTOR_PATTERN = re.compile(r"@(?:(role|capability):)?([A-Za-z0-9_.-]+)")


def _build_interaction_requests_from_text(text: str) -> list[dict]:
    selectors: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for match in _INTERACTION_SELECTOR_PATTERN.finditer(text):
        selector_type = match.group(1) or "participant"
        selector_value = match.group(2)
        key = (selector_type, selector_value.lower())
        if key in seen:
            continue
        seen.add(key)
        selectors.append({"type": selector_type, "value": selector_value})
    if not selectors:
        return []
    prompt = _INTERACTION_SELECTOR_PATTERN.sub("", text)
    prompt = re.sub(r"\s+", " ", prompt).strip() or text.strip()
    return [
        {
            "title": "Participant Question",
            "questions": [{"prompt": prompt}],
            "selectors": selectors,
        }
    ]
    try:
        normalized = raw_timestamp.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(normalized)
        return timestamp.astimezone().strftime("%H:%M")
    except Exception:
        return "--:--"


def _reset_terminal_mode() -> None:
    if not sys.stdin.isatty() or not hasattr(sys.stdin, "fileno"):
        return
    try:
        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
    except Exception:
        return

    attrs[0] |= getattr(termios, "BRKINT", 0)
    attrs[0] |= getattr(termios, "ICRNL", 0)
    attrs[0] |= getattr(termios, "IXON", 0)
    attrs[0] &= ~getattr(termios, "IGNBRK", 0)
    attrs[0] &= ~getattr(termios, "INLCR", 0)
    attrs[0] &= ~getattr(termios, "IGNCR", 0)
    attrs[1] |= getattr(termios, "OPOST", 0)
    attrs[1] |= getattr(termios, "ONLCR", 0)
    attrs[3] |= termios.ECHO | termios.ICANON | termios.ISIG
    attrs[3] |= getattr(termios, "IEXTEN", 0)
    attrs[6][termios.VMIN] = 1
    attrs[6][termios.VTIME] = 0
    try:
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except Exception:
        return


class ScrollbackTUI2:
    _STATUS_PANEL_HEIGHT = 10
    _USER_VALIDATION_INTERVAL_SECONDS = 60
    _COMMAND_SUGGESTIONS = [
        "/help",
        "/auth login",
        "/auth logout",
        "/account whoami",
        "/account list",
        "/account switch",
        "/llm-provider list",
        "/llm-provider show",
        "/llm-provider create",
        "/llm-provider update",
        "/llm-provider enable",
        "/llm-provider disable",
        "/llm-provider delete",
        "/workspace list",
        "/workspace show",
        "/workspace create",
        "/workspace use",
        "/thread list",
        "/thread show",
        "/thread create",
        "/thread use",
        "/links",
        "/open",
        "/copy",
        "/clear",
        "/quit",
    ]

    def __init__(
        self,
        *,
        gateway: str,
        profile: str,
        oidc_issuer_url: str,
        oidc_client_id: str,
        display_name: str,
        workspace_name: str,
        thread_title: str,
    ) -> None:
        self.gateway = gateway.rstrip("/")
        self.profile = profile
        self.oidc_issuer_url = oidc_issuer_url.rstrip("/")
        self.oidc_client_id = oidc_client_id
        self.workspace_name = workspace_name
        self.default_thread_title = thread_title
        self.state = load_state(profile, display_name, "user")
        self.tokens = load_tokens(profile)
        if self.tokens is None:
            self.state = reset_profile_session_state(
                profile,
                display_name=display_name,
                participant_type="user",
            )
        self.current_user: dict | None = None
        self._fallback_actor_id = str(uuid4())
        self._http_client: httpx.AsyncClient | None = None
        self._ws_task: asyncio.Task | None = None
        self._ws = None
        self._seen_message_ids: set[str] = set()
        self._history_lines: list[str] = []
        self._detected_links: list[str] = []
        self._stop = False
        self._stdout_lock = threading.Lock()
        self._status_initialized = False
        self._status_region_start = self._STATUS_PANEL_HEIGHT + 1
        self._connection_status = "offline"
        self._last_status_lines: tuple[str, ...] = ()
        self._input_history: list[str] = []
        self._history_index: int | None = None
        self._history_saved_buffer = ""
        self._prompt_active = False
        self._prompt_buffer = ""
        self._prompt_cursor = 0
        self._recent_activity: list[str] = []
        self._last_user_validation_at: datetime | None = None
        self._llm_provider_suggestions: list[dict[str, str]] = []

    def _command_suggestions(self, buffer: str) -> list[str]:
        stripped = buffer.lstrip()
        if not stripped.startswith("/"):
            return []
        if not stripped or stripped == "/":
            return list(self._COMMAND_SUGGESTIONS)

        leading_space = buffer[: len(buffer) - len(stripped)]
        if buffer.endswith(" "):
            try:
                parts = shlex.split(stripped)
            except ValueError:
                parts = stripped.split()
            prefix = ""
        else:
            try:
                parts = shlex.split(stripped)
            except ValueError:
                parts = stripped.split()
            prefix = parts.pop() if parts else stripped

        suggestions: list[str] = []
        if not parts:
            suggestions = [
                command
                for command in self._COMMAND_SUGGESTIONS
                if command.startswith(prefix)
            ]
        elif parts[0] == "/account" and len(parts) == 2 and parts[1] == "switch":
            suggestions = [
                f"/account switch {profile}"
                for profile in list_profiles()
                if f"/account switch {profile}".startswith(stripped.rstrip())
            ]
        elif parts[0] == "/open" and len(parts) == 1:
            link_targets = [str(index) for index in range(1, len(self._detected_links) + 1)]
            if self._detected_links:
                link_targets.append("last")
            suggestions = [
                f"/open {target}"
                for target in link_targets
                if f"/open {target}".startswith(stripped.rstrip())
            ]
        elif parts[0] == "/llm-provider" and len(parts) == 2:
            provider_targets: list[str] = []
            for provider in self._llm_provider_suggestions:
                for candidate in (
                    provider["display_name"],
                    provider["engine_id"],
                    provider["provider_id"][:8],
                    provider["provider_id"],
                ):
                    if candidate not in provider_targets:
                        provider_targets.append(candidate)
            if parts[1] in {"show", "update", "delete", "enable", "disable"}:
                suggestions = [
                    f"/llm-provider {parts[1]} {target}"
                    for target in provider_targets
                    if f"/llm-provider {parts[1]} {target}".startswith(stripped.rstrip())
                ]
        return [f"{leading_space}{suggestion}" for suggestion in suggestions]

    @staticmethod
    def _http_status_code(exc: Exception) -> int | None:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code
        response = getattr(exc, "response", None)
        if response is not None:
            return getattr(response, "status_code", None)
        return getattr(exc, "status_code", None)

    def _describe_exception(self, exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            detail = ""
            try:
                body = exc.response.json()
            except Exception:
                body = None
            if isinstance(body, dict):
                for key in ("detail", "message", "error_description", "error"):
                    value = body.get(key)
                    if isinstance(value, str) and value.strip():
                        detail = value.strip()
                        break
            if not detail:
                try:
                    detail = exc.response.text.strip()
                except Exception:
                    detail = ""
            detail = detail[:160]
            if detail:
                return f"{exc.response.status_code} {detail}"
            return f"{exc.response.status_code} {exc.response.reason_phrase}".strip()
        message = str(exc).strip()
        return message or exc.__class__.__name__

    def _handle_runtime_error(
        self,
        exc: Exception,
        *,
        context: str,
        invalidate_auth: bool = True,
    ) -> None:
        status_code = self._http_status_code(exc)
        if invalidate_auth and status_code in {401, 403} and self.tokens is not None:
            self._invalidate_saved_session("authentication expired; run /auth login")
            return
        self._write_system(f"{context}: {self._describe_exception(exc)}")

    @property
    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.tokens is not None:
            headers["Authorization"] = f"Bearer {self.tokens.access_token}"
        return headers

    @property
    def actor_payload(self) -> dict[str, str | None]:
        participant_id = self.state.participant_id or self.state.user_id or self._fallback_actor_id
        return {
            "participant_id": participant_id,
            "participant_type": "user",
            "user_id": self.state.user_id,
            "display_name": self.state.display_name,
        }

    @property
    def _is_authenticated(self) -> bool:
        return self.tokens is not None and self.current_user is not None

    @staticmethod
    def _truncate(text: str, width: int) -> str:
        if width <= 0:
            return ""
        if len(text) <= width:
            return text
        if width == 1:
            return text[:1]
        return text[: width - 1] + "…"

    def _push_recent_activity(self, text: str) -> None:
        normalized = " ".join(text.strip().split())
        if not normalized:
            return
        self._recent_activity.append(normalized)
        self._recent_activity = self._recent_activity[-2:]

    def _status_lines(self, width: int | None = None) -> list[str]:
        terminal_width = width or shutil.get_terminal_size((100, 24)).columns
        total_width = max(terminal_width, 72)
        body_width = total_width - 2
        separator = " │ "
        left_width = max(28, min(42, (body_width - len(separator)) // 2))
        right_width = body_width - len(separator) - left_width

        display_name = self.state.display_name if self._is_authenticated else self.profile
        auth = self.state.display_name if self._is_authenticated else "signed out"
        workspace = self.state.workspace_id[:8] if self._is_authenticated and self.state.workspace_id else "--"
        thread = self.state.thread_id[:8] if self._is_authenticated and self.state.thread_id else "--"
        participant = (
            self.state.participant_id[:8]
            if self._is_authenticated and self.state.participant_id
            else "--"
        )
        gateway_label = self.gateway.replace("http://", "").replace("https://", "")
        recent_one = self._recent_activity[-1] if self._recent_activity else "No recent activity yet"
        recent_two = self._recent_activity[-2] if len(self._recent_activity) > 1 else ""

        rows = [
            (f"Welcome back, {display_name}!", "Tips"),
            (f"Profile: {self.profile}", "Up/Down recalls command history"),
            (f"Auth: {auth}", "Tab fills the first matching slash command"),
            (f"Conn: {self._connection_status} | Links: {len(self._detected_links)}", "/help shows the command list"),
            (f"Workspace: {workspace}", "/workspace list and /thread list are handy starts"),
            (f"Thread: {thread}", "Recent activity"),
            (f"Participant: {participant}", recent_one),
            (f"Gateway: {gateway_label}", recent_two),
        ]

        lines = [f"┌─ {'Open Talon TUI2':<{body_width - 2}} ─┐"]
        for left, right in rows:
            left_text = self._truncate(left, left_width)
            right_text = self._truncate(right, right_width)
            body = f"{left_text:<{left_width}}{separator}{right_text:<{right_width}}"
            lines.append(f"│{body}│")
        lines.append(f"└{'─' * body_width}┘")
        return lines

    def _render_status_panel(self) -> None:
        if not sys.stdout.isatty():
            return
        terminal_size = shutil.get_terminal_size((100, 24))
        terminal_rows = terminal_size.lines
        terminal_cols = terminal_size.columns
        region_start = self._STATUS_PANEL_HEIGHT + 1
        if terminal_rows <= region_start:
            return
        raw_status_lines = tuple(self._status_lines(width=terminal_cols))
        if self._status_initialized and raw_status_lines == self._last_status_lines:
            return
        status_lines = [_render_terminal_links(line) for line in raw_status_lines]
        with self._stdout_lock:
            if not self._status_initialized:
                sys.stdout.write("\033[2J")
                sys.stdout.write(f"\033[{region_start};{terminal_rows}r")
                sys.stdout.write(f"\033[{region_start};1H")
                self._status_initialized = True
                self._status_region_start = region_start
            sys.stdout.write("\033[s")
            sys.stdout.write("\033[H")
            for line in status_lines:
                sys.stdout.write("\033[2K")
                sys.stdout.write(line)
                sys.stdout.write("\n")
            sys.stdout.write("\033[2K")
            sys.stdout.write("\033[u")
            sys.stdout.flush()
        self._last_status_lines = raw_status_lines
        if self._prompt_active:
            self._render_prompt(self._prompt_buffer, self._prompt_cursor)

    def _restore_terminal(self) -> None:
        if not self._status_initialized or not sys.stdout.isatty():
            return
        with self._stdout_lock:
            sys.stdout.write("\033[r")
            terminal_rows = shutil.get_terminal_size((80, 24)).lines
            sys.stdout.write(f"\033[{terminal_rows};1H")
            sys.stdout.flush()
        self._status_initialized = False
        self._last_status_lines = ()

    def _print_line(self, text: str = "") -> None:
        with self._stdout_lock:
            if sys.stdout.isatty():
                sys.stdout.write("\r")
                sys.stdout.write("\033[2K")
            sys.stdout.write(_render_terminal_links(text) + "\n")
            if self._prompt_active:
                self._write_prompt_locked(self._prompt_buffer, self._prompt_cursor)
            sys.stdout.flush()

    def _prompt_label(self) -> str:
        return "▸ "

    def _current_completion(self, buffer: str) -> str | None:
        suggestions = self._command_suggestions(buffer)
        if not suggestions:
            return None
        suggestion = suggestions[0]
        if suggestion == buffer:
            return None
        return suggestion

    def _write_prompt_locked(self, buffer: str, cursor: int) -> None:
        if not sys.stdout.isatty() or not self._status_initialized:
            return
        terminal_cols = shutil.get_terminal_size((100, 24)).columns
        prompt = self._prompt_label()
        suggestion = self._current_completion(buffer)
        suffix = ""
        if suggestion is not None and suggestion.startswith(buffer):
            suffix = suggestion[len(buffer) :]
        sys.stdout.write("\r")
        sys.stdout.write("\033[2K")
        sys.stdout.write("\033[48;5;236m\033[1;37m")
        sys.stdout.write(prompt)
        sys.stdout.write(_render_terminal_links(buffer))
        if suffix:
            sys.stdout.write("\033[2;37m")
            sys.stdout.write(_render_terminal_links(suffix))
            sys.stdout.write("\033[1;37m")
        consumed = len(prompt) + len(buffer) + len(suffix)
        if consumed < terminal_cols:
            sys.stdout.write(" " * (terminal_cols - consumed))
        sys.stdout.write("\033[0m")
        trailing = max(0, terminal_cols - (len(prompt) + cursor))
        if trailing > 0:
            sys.stdout.write(f"\033[{trailing}D")

    def _render_prompt(self, buffer: str, cursor: int) -> None:
        self._prompt_buffer = buffer
        self._prompt_cursor = cursor
        with self._stdout_lock:
            self._write_prompt_locked(buffer, cursor)
            sys.stdout.flush()

    def _supports_tty_prompt(self) -> bool:
        return bool(sys.stdin.isatty() and hasattr(sys.stdin, "fileno"))

    def _remember_input(self, raw: str) -> None:
        if raw:
            self._input_history.append(raw)
        self._history_index = None
        self._history_saved_buffer = ""

    def _history_previous(self, current_buffer: str) -> str:
        if not self._input_history:
            return current_buffer
        if self._history_index is None:
            self._history_saved_buffer = current_buffer
            self._history_index = len(self._input_history) - 1
        elif self._history_index > 0:
            self._history_index -= 1
        return self._input_history[self._history_index]

    def _history_next(self) -> str:
        if self._history_index is None:
            return self._history_saved_buffer
        if self._history_index < len(self._input_history) - 1:
            self._history_index += 1
            return self._input_history[self._history_index]
        self._history_index = None
        return self._history_saved_buffer

    async def _prompt_with_terminal_editor(self) -> str | None:
        fd = sys.stdin.fileno()
        previous = termios.tcgetattr(fd)
        buffer = ""
        cursor = 0
        pending = b""
        self._history_index = None
        self._history_saved_buffer = ""
        self._prompt_active = True
        self._render_prompt(buffer, cursor)
        tty.setcbreak(fd)
        try:
            while True:
                pending += await asyncio.to_thread(os.read, fd, 16)
                if not pending:
                    return None
                while pending:
                    if pending.startswith(b"\x1b"):
                        if len(pending) < 3:
                            break
                        sequence = pending[:3]
                        pending = pending[3:]
                        if sequence == b"\x1b[A":
                            buffer = self._history_previous(buffer)
                            cursor = len(buffer)
                        elif sequence == b"\x1b[B":
                            buffer = self._history_next()
                            cursor = len(buffer)
                        elif sequence == b"\x1b[C":
                            cursor = min(cursor + 1, len(buffer))
                        elif sequence == b"\x1b[D":
                            cursor = max(cursor - 1, 0)
                        self._render_prompt(buffer, cursor)
                        continue

                    byte = pending[0]
                    pending = pending[1:]

                    if byte in {10, 13}:
                        self._prompt_active = False
                        self._prompt_buffer = ""
                        self._prompt_cursor = 0
                        with self._stdout_lock:
                            sys.stdout.write("\r")
                            sys.stdout.write("\033[2K")
                            sys.stdout.flush()
                        return buffer
                    if byte == 3:
                        raise KeyboardInterrupt
                    if byte == 4 and not buffer:
                        self._prompt_active = False
                        return None
                    if byte in {8, 127}:
                        if cursor > 0:
                            buffer = buffer[: cursor - 1] + buffer[cursor:]
                            cursor -= 1
                            self._history_index = None
                    elif byte == 9:
                        suggestion = self._current_completion(buffer)
                        if suggestion is not None:
                            buffer = suggestion
                            cursor = len(buffer)
                    elif 32 <= byte <= 126:
                        character = chr(byte)
                        buffer = buffer[:cursor] + character + buffer[cursor:]
                        cursor += 1
                        self._history_index = None
                    self._render_prompt(buffer, cursor)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, previous)
            self._prompt_active = False

    def _record_line(self, text: str) -> None:
        self._history_lines.append(text)
        links_before = len(self._detected_links)
        for url in _URL_PATTERN.findall(text):
            if url not in self._detected_links:
                self._detected_links.append(url)
        self._print_line(text)
        if len(self._detected_links) != links_before:
            self._render_status_panel()

    def _write_system(self, text: str) -> None:
        self._push_recent_activity(text)
        self._record_line(f"  └ {text}")

    def _sync_http_auth(self) -> None:
        if self._http_client is None:
            return
        self._http_client.headers.clear()
        self._http_client.headers.update(self._auth_headers)

    def _set_connection_status(self, status: str) -> None:
        self._connection_status = status
        self._render_status_panel()

    def _invalidate_saved_session(self, reason: str) -> None:
        self.tokens = None
        self.current_user = None
        self._set_connection_status("offline")
        self.state = reset_profile_session_state(
            self.profile,
            display_name=self.state.display_name,
            participant_type="user",
        )
        save_tokens(self.profile, None)
        self._sync_http_auth()
        self._write_system(reason)

    @staticmethod
    def _token_expiring_soon(tokens: TokenState | None, *, skew_seconds: int = 30) -> bool:
        if tokens is None or not tokens.expires_at:
            return False
        try:
            expires_at = datetime.fromisoformat(tokens.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=skew_seconds)

    async def _refresh_oidc_tokens(self) -> bool:
        if self.tokens is None or not self.tokens.refresh_token:
            return False
        try:
            discovery = await discover_oidc(self.oidc_issuer_url)
            async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
                response = await client.post(
                    discovery["token_endpoint"],
                    data={
                        "grant_type": "refresh_token",
                        "client_id": self.oidc_client_id,
                        "refresh_token": self.tokens.refresh_token,
                    },
                )
            if response.status_code >= 400:
                return False
            body = response.json()
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=body.get("expires_in", 300))
            self.tokens = TokenState(
                access_token=body["access_token"],
                refresh_token=body.get("refresh_token", self.tokens.refresh_token),
                expires_at=expires_at.isoformat(),
                issuer=self.oidc_issuer_url,
                client_id=self.oidc_client_id,
            )
        except Exception:
            return False
        save_tokens(self.profile, self.tokens)
        self._sync_http_auth()
        return True

    async def _ensure_bearer_token(self) -> None:
        if self._token_expiring_soon(self.tokens):
            refreshed = await self._refresh_oidc_tokens()
            if not refreshed:
                self._invalidate_saved_session("token refresh failed; run /auth login")
                return
            await self._validate_current_user_session(force=True)

    async def _validate_current_user_session(self, *, force: bool = False) -> None:
        if self.tokens is None:
            self.current_user = None
            self._last_user_validation_at = None
            return
        if not force and self._last_user_validation_at is not None:
            if self._last_user_validation_at >= datetime.now(timezone.utc) - timedelta(
                seconds=self._USER_VALIDATION_INTERVAL_SECONDS
            ):
                return
        try:
            await self._load_current_user()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                self._invalidate_saved_session("authenticated session is no longer valid; run /auth login")
                return
            raise
        self._last_user_validation_at = datetime.now(timezone.utc)

    async def _load_current_user(self) -> None:
        if self.tokens is None:
            self.current_user = None
            self._last_user_validation_at = None
            return
        try:
            self.current_user = await fetch_current_user(
                gateway=self.gateway,
                access_token=self.tokens.access_token,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                self._invalidate_saved_session("saved login expired; run /auth login")
                return
            raise
        self.state.user_id = self.current_user["user_id"]
        self.state.display_name = self.current_user["display_name"]
        self.state.participant_type = "user"
        self._last_user_validation_at = datetime.now(timezone.utc)
        save_state(self.profile, self.state)

    def _set_current_participant(self, participants: list[dict]) -> None:
        current: dict | None = None
        if self.state.user_id:
            current = next(
                (
                    participant
                    for participant in participants
                    if participant.get("user_id") == self.state.user_id
                ),
                None,
            )
        if current is None and self.state.participant_id:
            current = next(
                (
                    participant
                    for participant in participants
                    if participant.get("participant_id") == self.state.participant_id
                ),
                None,
            )
        if current is not None:
            self.state.participant_id = current.get("participant_id")
            self.state.display_name = current.get("display_name", self.state.display_name)

    @staticmethod
    def _extract_workspace_id(body: dict) -> str:
        workspace = body.get("workspace")
        if isinstance(workspace, dict):
            workspace_id = workspace.get("workspace_id")
            if isinstance(workspace_id, str) and workspace_id:
                return workspace_id
        workspace_id = body.get("workspace_id")
        if isinstance(workspace_id, str) and workspace_id:
            return workspace_id
        raise KeyError("workspace_id")

    @staticmethod
    def _extract_thread_id(body: dict) -> str:
        thread = body.get("thread")
        if isinstance(thread, dict):
            thread_id = thread.get("thread_id")
            if isinstance(thread_id, str) and thread_id:
                return thread_id
        thread_id = body.get("thread_id")
        if isinstance(thread_id, str) and thread_id:
            return thread_id
        raise KeyError("thread_id")

    async def _ensure_context(self) -> None:
        assert self._http_client is not None

        workspace_id = self.state.workspace_id
        if workspace_id:
            response = await self._http_client.get(f"{self.gateway}/v1/workspaces/{workspace_id}")
            if response.status_code != 200:
                self.state.workspace_id = None
            else:
                self._set_current_participant(response.json().get("participants", []))

        if self.state.workspace_id is None:
            response = await self._http_client.post(
                f"{self.gateway}/v1/workspaces",
                json={
                    "name": self.workspace_name,
                    "description": "Workspace created by Open Talon TUI2",
                    "actor": self.actor_payload,
                },
            )
            response.raise_for_status()
            body = response.json()
            self.state.workspace_id = self._extract_workspace_id(body)
            self._set_current_participant(body.get("participants", []))
            save_state(self.profile, self.state)

        thread_id = self.state.thread_id
        if thread_id:
            response = await self._http_client.get(f"{self.gateway}/v1/threads/{thread_id}")
            if response.status_code != 200:
                self.state.thread_id = None
                self.state.last_sequence = 0

        if self.state.thread_id is None:
            await self._create_thread(self.default_thread_title)

        save_state(self.profile, self.state)

    async def _create_thread(self, title: str) -> None:
        assert self._http_client is not None
        assert self.state.workspace_id is not None
        response = await self._http_client.post(
            f"{self.gateway}/v1/workspaces/{self.state.workspace_id}/threads",
            json={"title": title, "actor": self.actor_payload},
        )
        response.raise_for_status()
        body = response.json()
        self.state.thread_id = self._extract_thread_id(body)
        memberships = body.get("memberships", [])
        if memberships:
            self.state.participant_id = memberships[0].get("participant_id", self.state.participant_id)
        self.state.last_sequence = 0
        self._seen_message_ids.clear()
        save_state(self.profile, self.state)

    async def _list_workspaces(self) -> list[dict]:
        assert self._http_client is not None
        response = await self._http_client.get(f"{self.gateway}/v1/workspaces")
        response.raise_for_status()
        return response.json()

    async def _list_threads(self, workspace_id: str) -> list[dict]:
        assert self._http_client is not None
        response = await self._http_client.get(
            f"{self.gateway}/v1/workspaces/{workspace_id}/threads"
        )
        response.raise_for_status()
        return response.json()

    async def _list_llm_providers(self) -> list[dict]:
        assert self._http_client is not None
        response = await self._http_client.get(f"{self.gateway}/v1/llm-providers")
        response.raise_for_status()
        providers = response.json()
        self._llm_provider_suggestions = [
            {
                "provider_id": item["provider_id"],
                "engine_id": item["engine_id"],
                "display_name": item["display_name"],
            }
            for item in providers
        ]
        return providers

    async def _create_llm_provider(self, payload: dict[str, object]) -> dict:
        assert self._http_client is not None
        response = await self._http_client.post(
            f"{self.gateway}/v1/llm-providers",
            json={
                "actor": self.actor_payload,
                **payload,
            },
        )
        response.raise_for_status()
        return response.json()

    async def _update_llm_provider(
        self,
        provider_id: str,
        payload: dict[str, object],
    ) -> dict:
        assert self._http_client is not None
        response = await self._http_client.patch(
            f"{self.gateway}/v1/llm-providers/{provider_id}",
            json={
                "actor": self.actor_payload,
                **payload,
            },
        )
        response.raise_for_status()
        return response.json()

    async def _delete_llm_provider(self, provider_id: str) -> None:
        assert self._http_client is not None
        response = await self._http_client.request(
            "DELETE",
            f"{self.gateway}/v1/llm-providers/{provider_id}",
            json={"actor": self.actor_payload},
        )
        response.raise_for_status()

    def _resolve_workspace_target(self, workspaces: list[dict], target: str) -> dict | None:
        normalized = target.strip()
        if not normalized or normalized == "current":
            for workspace in workspaces:
                if workspace["workspace_id"] == self.state.workspace_id:
                    return workspace
            return None
        for workspace in workspaces:
            if workspace["workspace_id"] == normalized or workspace["workspace_id"].startswith(normalized):
                return workspace
        lowered = normalized.lower()
        for workspace in workspaces:
            if workspace["name"].lower() == lowered:
                return workspace
        return None

    def _resolve_thread_target(self, threads: list[dict], target: str) -> dict | None:
        normalized = target.strip()
        if not normalized or normalized == "current":
            for thread in threads:
                if thread["thread_id"] == self.state.thread_id:
                    return thread
            return None
        for thread in threads:
            if thread["thread_id"] == normalized or thread["thread_id"].startswith(normalized):
                return thread
        lowered = normalized.lower()
        for thread in threads:
            if thread["title"].lower() == lowered:
                return thread
        return None

    async def _handle_llm_provider_command(self, command: str) -> None:
        if not self._is_authenticated:
            self._write_system("sign in first with /auth login")
            return
        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._write_system(_LLM_PROVIDER_COMMAND_HELP)
            return
        action = parts[1].lower()
        target = parts[2].strip() if len(parts) > 2 else ""

        if action == "list":
            providers = await self._list_llm_providers()
            if not providers:
                self._write_system("no llm providers found")
                return
            for provider in providers:
                locality = provider.get("locality") or "unknown"
                enabled = "enabled" if provider.get("enabled", True) else "disabled"
                model = provider.get("default_model") or "auto"
                self._write_system(
                    f"{provider['display_name']} ({provider['engine_id']}) | provider={provider['provider']} | model={model} | locality={locality} | {enabled}"
                )
            return

        if action == "create":
            if not target:
                self._write_system(_LLM_PROVIDER_CREATE_USAGE)
                return
            try:
                payload = _build_llm_provider_payload(
                    _parse_command_assignments(target),
                    partial=False,
                )
            except ValueError as exc:
                self._write_system(str(exc))
                self._write_system(_LLM_PROVIDER_CREATE_USAGE)
                return
            provider = await self._create_llm_provider(payload)
            self._write_system(
                f"created llm provider: {provider['display_name']} ({provider['engine_id']})"
            )
            return

        if action not in {"show", "update", "enable", "disable", "delete"}:
            self._write_system(_LLM_PROVIDER_COMMAND_HELP)
            return

        providers = await self._list_llm_providers()
        provider, remainder = None, ""
        if action == "update":
            target_parts = target.split(maxsplit=1)
            lookup_target = target_parts[0] if target_parts else ""
            remainder = target_parts[1] if len(target_parts) > 1 else ""
            provider = _resolve_llm_provider_target(providers, lookup_target)
            if provider is None:
                self._write_system(f"llm provider not found: {lookup_target or 'current'}")
                return
            if not remainder:
                self._write_system(_LLM_PROVIDER_UPDATE_USAGE)
                return
        else:
            provider = _resolve_llm_provider_target(providers, target)
            if provider is None:
                self._write_system(f"llm provider not found: {target}")
                return

        if action == "show":
            capabilities = ", ".join(provider.get("capabilities", [])) or "none"
            self._write_system(f"name: {provider['display_name']}")
            self._write_system(f"id: {provider['provider_id']}")
            self._write_system(f"engine id: {provider['engine_id']}")
            self._write_system(f"provider: {provider['provider']}")
            self._write_system(
                f"endpoint: {provider.get('endpoint_kind', 'remote')} {provider.get('url') or ''}".rstrip()
            )
            self._write_system(f"default model: {provider.get('default_model') or 'auto'}")
            self._write_system(
                f"locality: {provider.get('locality', 'unknown')} | priority: {provider.get('priority', 100)} | enabled: {provider.get('enabled', True)}"
            )
            self._write_system(f"capabilities: {capabilities}")
            if provider.get("secret_config"):
                self._write_system(
                    "secret config: " + json.dumps(provider["secret_config"], sort_keys=True)
                )
            if provider.get("metadata"):
                self._write_system(
                    "metadata: " + json.dumps(provider["metadata"], sort_keys=True)
                )
            return

        if action == "update":
            try:
                payload = _build_llm_provider_payload(
                    _parse_command_assignments(remainder),
                    partial=True,
                )
            except ValueError as exc:
                self._write_system(str(exc))
                self._write_system(_LLM_PROVIDER_UPDATE_USAGE)
                return
            if not payload:
                self._write_system(_LLM_PROVIDER_UPDATE_USAGE)
                return
            updated = await self._update_llm_provider(provider["provider_id"], payload)
            self._write_system(
                f"updated llm provider: {updated['display_name']} ({updated['engine_id']})"
            )
            return

        if action in {"enable", "disable"}:
            enabled = action == "enable"
            updated = await self._update_llm_provider(
                provider["provider_id"],
                {"enabled": enabled},
            )
            self._write_system(
                f"{action}d llm provider: {updated['display_name']} ({updated['engine_id']})"
            )
            return

        if action == "delete":
            await self._delete_llm_provider(provider["provider_id"])
            self._llm_provider_suggestions = [
                item
                for item in self._llm_provider_suggestions
                if item["provider_id"] != provider["provider_id"]
            ]
            self._write_system(
                f"deleted llm provider: {provider['display_name']} ({provider['engine_id']})"
            )
            return

        self._write_system(_LLM_PROVIDER_COMMAND_HELP)

    async def _load_timeline(self) -> None:
        assert self._http_client is not None
        assert self.state.thread_id is not None
        response = await self._http_client.get(
            f"{self.gateway}/v1/threads/{self.state.thread_id}/timeline"
        )
        response.raise_for_status()
        timeline = response.json()
        self._write_system(
            f"history for workspace {self.state.workspace_id[:8]} thread {self.state.thread_id[:8]}"
        )
        for message in timeline.get("messages", []):
            self._render_message(message)
            self.state.last_sequence = max(self.state.last_sequence, message.get("sequence", 0))
        save_state(self.profile, self.state)

    def _render_message(self, message: dict) -> None:
        message_id = message.get("message_id")
        if message_id and message_id in self._seen_message_ids:
            return
        if message_id:
            self._seen_message_ids.add(message_id)
        actor = message.get("actor", {})
        actor_id = actor.get("id", "")
        prefix = "You" if actor_id == self.state.participant_id else f"Peer {actor_id[:8]}"
        content = message.get("content", "")
        metadata = message.get("metadata", {})
        if isinstance(metadata, dict):
            request_id = metadata.get("interaction_request_id")
            request_status = metadata.get("interaction_request_status")
            aggregate = metadata.get("interaction_aggregate")
            if request_id:
                coverage = ""
                if isinstance(aggregate, dict):
                    coverage = (
                        f" {aggregate.get('answered_count', 0)}/{aggregate.get('target_count', 0)}"
                    )
                prefix = f"{prefix} [request {request_status or 'open'}{coverage}]"
            elif metadata.get("interaction_question_ids"):
                prefix = f"{prefix} [answer]"
        time_mark = _format_timestamp(message.get("created_at") or message.get("updated_at"))
        self._record_line(f"{time_mark} {prefix}: {content}")

    def _handle_event(self, event: dict) -> None:
        sequence = event.get("sequence") or 0
        self.state.last_sequence = max(self.state.last_sequence, sequence)
        save_state(self.profile, self.state)

        if event.get("event_type") == "message.created":
            self._render_message(event.get("payload", {}))

    async def _close_ws(self) -> None:
        if self._ws_task is None:
            return
        task = self._ws_task
        self._ws_task = None
        task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _start_ws(self) -> None:
        if not self._is_authenticated or not self.state.thread_id:
            return
        if self._ws_task is not None:
            self._ws_task.cancel()
        self._set_connection_status("connecting")
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def _ws_loop(self) -> None:
        assert self.state.thread_id is not None
        ws_base = self.gateway.replace("http://", "ws://").replace("https://", "wss://")
        while True:
            await self._ensure_bearer_token()
            await self._validate_current_user_session()
            if not self._is_authenticated:
                return
            query = urlencode({"after_sequence": self.state.last_sequence})
            url = f"{ws_base}/v1/threads/{self.state.thread_id}/ws?{query}"
            headers = list(self._auth_headers.items())
            try:
                async with websockets.connect(url, additional_headers=headers) as ws:
                    self._ws = ws
                    self._set_connection_status("connected")
                    async for raw in ws:
                        self._handle_event(json.loads(raw))
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.ConnectionClosed:
                self._set_connection_status("reconnecting")
            except websockets.exceptions.InvalidStatus as exc:
                status_code = self._http_status_code(exc)
                if status_code in {401, 403}:
                    self._invalidate_saved_session("websocket session expired; run /auth login")
                    return
                self._set_connection_status("reconnecting")
                self._write_system(f"websocket error: {self._describe_exception(exc)}")
            except Exception as exc:
                self._set_connection_status("reconnecting")
                self._write_system(f"websocket error: {self._describe_exception(exc)}")
            finally:
                self._ws = None
            await asyncio.sleep(3)

    async def _activate_profile_session(self) -> None:
        self._set_connection_status("connecting")
        try:
            await self._ensure_bearer_token()
            await self._validate_current_user_session(force=True)
        except Exception as exc:
            self._handle_runtime_error(exc, context="unable to refresh login")
            return
        self._sync_http_auth()
        if self.tokens is None:
            self.current_user = None
            self._set_connection_status("offline")
            self._write_system(f"signed out ({self.profile}); run /auth login")
            return
        try:
            await self._load_current_user()
        except Exception as exc:
            self._handle_runtime_error(exc, context="unable to load current user")
            return
        if self.current_user is None or self.tokens is None:
            self._set_connection_status("offline")
            self._write_system(f"signed out ({self.profile}); run /auth login")
            return
        try:
            await self._ensure_context()
            await self._load_timeline()
        except Exception as exc:
            self._handle_runtime_error(exc, context="unable to load workspace context")
            return
        self._start_ws()
        self._set_connection_status("ready")
        self._write_system(
            f"profile {self.profile} ready as {self.state.display_name} in workspace {self.state.workspace_id[:8]} thread {self.state.thread_id[:8]}"
        )

    async def _login(self) -> None:
        self._write_system("starting device login")
        try:
            self.tokens = await run_device_login(
                issuer_url=self.oidc_issuer_url,
                client_id=self.oidc_client_id,
                write_line=self._print_line,
            )
        except Exception as exc:
            self._write_system(f"login failed: {self._describe_exception(exc)}")
            return
        save_tokens(self.profile, self.tokens)
        await self._activate_profile_session()

    async def _logout(self) -> None:
        await self._close_ws()
        self.tokens = None
        self.current_user = None
        self._set_connection_status("offline")
        self.state = reset_profile_session_state(
            self.profile,
            display_name=self.state.display_name,
            participant_type="user",
        )
        save_tokens(self.profile, None)
        self._sync_http_auth()
        self._write_system(f"signed out profile: {self.profile}")

    async def _switch_profile(self, profile: str) -> None:
        await self._close_ws()
        self.profile = profile
        self.state = load_state(profile, self.state.display_name, "user")
        self.tokens = load_tokens(profile)
        if self.tokens is None:
            self.state = reset_profile_session_state(
                profile,
                display_name=self.state.display_name,
                participant_type="user",
            )
        self.current_user = None
        self._seen_message_ids.clear()
        self._sync_http_auth()
        await self._activate_profile_session()

    async def _send_message(self, text: str) -> None:
        if not self._is_authenticated:
            self._write_system("sign in first with /auth login")
            return
        await self._ensure_bearer_token()
        await self._validate_current_user_session()
        if not self._is_authenticated:
            return
        if not self.state.thread_id:
            self._write_system("thread not ready yet")
            return
        assert self._http_client is not None
        requests = _build_interaction_requests_from_text(text)
        response = await self._http_client.post(
            f"{self.gateway}/v1/threads/{self.state.thread_id}/messages",
            json={
                "actor": self.actor_payload,
                "content": text,
                "visibility": "public",
                "create_task": True,
                "requests": requests,
            },
        )
        response.raise_for_status()

    async def _handle_account_command(self, command: str) -> None:
        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._write_system(
                "account commands: /account login | /account whoami | /account list | /account switch <profile> | /account logout"
            )
            return
        action = parts[1].lower()
        if action == "login":
            await self._login()
            return
        if action == "whoami":
            if self.current_user is None:
                self._write_system(f"profile: {self.profile}")
                self._write_system("not signed in")
                return
            self._write_system(f"profile: {self.profile}")
            self._write_system(f"user: {self.current_user['display_name']}")
            self._write_system(f"user id: {self.current_user['user_id']}")
            if self.current_user.get("email"):
                self._write_system(f"email: {self.current_user['email']}")
            return
        if action == "list":
            self._write_system("profiles:")
            for profile in list_profiles():
                marker = "*" if profile == self.profile else "-"
                self._write_system(f"{marker} {profile}")
            return
        if action == "switch":
            target = parts[2].strip() if len(parts) > 2 else ""
            if not target:
                self._write_system("usage: /account switch <profile>")
                return
            await self._switch_profile(target)
            return
        if action == "logout":
            await self._logout()
            return
        self._write_system(f"unknown account action: {action}")

    async def _handle_workspace_command(self, command: str) -> None:
        if not self._is_authenticated:
            self._write_system("sign in first with /auth login")
            return
        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._write_system(
                "workspace commands: /workspace list | /workspace show | /workspace create <name> | /workspace use <id|name>"
            )
            return
        action = parts[1].lower()
        target = parts[2].strip() if len(parts) > 2 else ""
        workspaces = await self._list_workspaces()
        if action == "list":
            for workspace in workspaces:
                marker = "*" if workspace["workspace_id"] == self.state.workspace_id else "-"
                self._write_system(f"{marker} {workspace['name']} ({workspace['workspace_id'][:8]})")
            return
        if action == "show":
            current = self._resolve_workspace_target(workspaces, "current")
            if current is None:
                self._write_system("current workspace not found")
                return
            self._write_system(f"name: {current['name']}")
            self._write_system(f"id: {current['workspace_id']}")
            return
        if action == "create":
            if not target:
                self._write_system("usage: /workspace create <name>")
                return
            assert self._http_client is not None
            response = await self._http_client.post(
                f"{self.gateway}/v1/workspaces",
                json={
                    "name": target,
                    "description": "Workspace created by Open Talon TUI2",
                    "actor": self.actor_payload,
                },
            )
            response.raise_for_status()
            body = response.json()
            self.state.workspace_id = body["workspace"]["workspace_id"]
            self.state.thread_id = None
            self.state.last_sequence = 0
            self._set_current_participant(body.get("participants", []))
            save_state(self.profile, self.state)
            await self._ensure_context()
            await self._load_timeline()
            self._start_ws()
            self._write_system(f"switched workspace: {target}")
            return
        if action == "use":
            workspace = self._resolve_workspace_target(workspaces, target)
            if workspace is None:
                self._write_system(f"workspace not found: {target or 'current'}")
                return
            await self._close_ws()
            self.state.workspace_id = workspace["workspace_id"]
            self.state.thread_id = None
            self.state.last_sequence = 0
            save_state(self.profile, self.state)
            await self._ensure_context()
            await self._load_timeline()
            self._start_ws()
            self._write_system(f"switched workspace: {workspace['name']}")
            return
        self._write_system(f"unknown workspace action: {action}")

    async def _handle_thread_command(self, command: str) -> None:
        if not self._is_authenticated:
            self._write_system("sign in first with /auth login")
            return
        if not self.state.workspace_id:
            self._write_system("join or create a workspace first")
            return
        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._write_system(
                "thread commands: /thread list | /thread show | /thread create <title> | /thread use <id|title>"
            )
            return
        action = parts[1].lower()
        threads = await self._list_threads(self.state.workspace_id)
        if action == "list":
            for thread in threads:
                marker = "*" if thread["thread_id"] == self.state.thread_id else "-"
                self._write_system(f"{marker} {thread['title']} ({thread['thread_id'][:8]})")
            return
        if action == "show":
            current = self._resolve_thread_target(threads, "current")
            if current is None:
                self._write_system("current thread not found")
                return
            self._write_system(f"title: {current['title']}")
            self._write_system(f"id: {current['thread_id']}")
            return
        if action == "create":
            target = parts[2].strip() if len(parts) > 2 else ""
            if not target:
                self._write_system("usage: /thread create <title>")
                return
            await self._close_ws()
            await self._create_thread(target)
            await self._load_timeline()
            self._start_ws()
            self._write_system(f"created thread: {target}")
            return
        if action == "use":
            target = parts[2].strip() if len(parts) > 2 else ""
            thread = self._resolve_thread_target(threads, target)
            if thread is None:
                self._write_system(f"thread not found: {target or 'current'}")
                return
            await self._close_ws()
            self.state.thread_id = thread["thread_id"]
            self.state.last_sequence = 0
            save_state(self.profile, self.state)
            await self._load_timeline()
            self._start_ws()
            self._write_system(f"switched thread: {thread['title']}")
            return
        self._write_system(f"unknown thread action: {action}")

    def _show_links(self) -> None:
        if not self._detected_links:
            self._write_system("no links detected yet")
            return
        for index, url in enumerate(self._detected_links, start=1):
            self._write_system(f"{index}. {url}")

    def _open_link(self, target: str) -> None:
        normalized = target.strip()
        if not normalized:
            self._write_system("usage: /open <number|last|url>")
            return
        url: str | None = None
        if normalized == "last" and self._detected_links:
            url = self._detected_links[-1]
        elif normalized.isdigit():
            index = int(normalized) - 1
            if 0 <= index < len(self._detected_links):
                url = self._detected_links[index]
        elif normalized.startswith("http://") or normalized.startswith("https://"):
            url = normalized
        if url is None:
            self._write_system(f"link not found: {normalized}")
            return
        try:
            webbrowser.open(url, new=2)
        except Exception as exc:
            self._write_system(f"unable to open link: {self._describe_exception(exc)}")
            return
        self._write_system(f"opened link: {url}")

    def _copy_history(self) -> None:
        try:
            import pyperclip  # type: ignore

            pyperclip.copy("\n".join(self._history_lines))
            self._write_system("copied full timeline")
        except Exception:
            self._write_system("clipboard copy unavailable; use terminal mouse selection")

    async def _handle_command(self, text: str) -> None:
        if text == "/help":
            self._write_system(
                "commands: /auth login | /auth logout | /account whoami | /account list | /account switch <profile> | /llm-provider list | /llm-provider show <id|engine_id|name> | /llm-provider create key=value ... | /llm-provider update <target> field=value ... | /workspace list | /workspace create <name> | /workspace use <id|name> | /thread list | /thread create <title> | /thread use <id|title> | /links | /open <n|last|url> | /copy | /quit"
            )
            return
        if text == "/quit":
            self._stop = True
            return
        if text == "/clear":
            if sys.stdout.isatty():
                self._restore_terminal()
                self._render_status_panel()
            return
        if text == "/copy":
            self._copy_history()
            return
        if text == "/links":
            self._show_links()
            return
        if text.startswith("/open "):
            self._open_link(text[len("/open ") :])
            return
        if text == "/auth login":
            await self._login()
            return
        if text == "/auth logout":
            await self._logout()
            return
        if text == "/account" or text.startswith("/account "):
            await self._handle_account_command(text)
            return
        if text == "/llm-provider" or text.startswith("/llm-provider "):
            await self._handle_llm_provider_command(text)
            return
        if text == "/workspace" or text.startswith("/workspace "):
            await self._handle_workspace_command(text)
            return
        if text == "/thread" or text.startswith("/thread "):
            await self._handle_thread_command(text)
            return
        self._write_system("unsupported command in tui2; use /help")

    async def start(self) -> None:
        self._http_client = httpx.AsyncClient(
            headers=self._auth_headers,
            timeout=10,
            trust_env=False,
        )
        self._render_status_panel()
        self._record_line("Scrollback-first mode. Mouse selection should work normally in your terminal.")
        self._record_line("Type /help for commands. Use Up/Down for history and Tab for command completion.")
        try:
            try:
                await self._activate_profile_session()
            except Exception as exc:
                self._handle_runtime_error(exc, context="startup error", invalidate_auth=False)
            while not self._stop:
                try:
                    if self._supports_tty_prompt():
                        raw = await self._prompt_with_terminal_editor()
                        if raw is None:
                            break
                    else:
                        raw = await asyncio.to_thread(input, f"{self.profile}> ")
                except EOFError:
                    break
                except KeyboardInterrupt:
                    self._print_line("")
                    break
                text = raw.strip()
                if not text:
                    continue
                self._remember_input(raw)
                try:
                    if text.startswith("/"):
                        self._push_recent_activity(text)
                        self._record_line(f"▸ {text}")
                        await self._handle_command(text)
                    else:
                        await self._send_message(text)
                except Exception as exc:
                    self._handle_runtime_error(exc, context="command failed")
        finally:
            self._restore_terminal()
            await self._close_ws()
            if self._http_client is not None:
                await self._http_client.aclose()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open Talon TUI2 scrollback-first terminal client",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--gateway", default="http://127.0.0.1:8000", help="Gateway base URL")
    parser.add_argument("--profile", default=None, help="Named local TUI profile")
    parser.add_argument(
        "--oidc-issuer-url",
        default=os.getenv("OPEN_TALON_OIDC_ISSUER_URL", _DEFAULT_OIDC_ISSUER_URL),
        help="Keycloak OIDC issuer URL for device login",
    )
    parser.add_argument(
        "--oidc-client-id",
        default=os.getenv("OPEN_TALON_OIDC_CLIENT_ID", _DEFAULT_OIDC_CLIENT_ID),
        help="Keycloak OIDC client id for the TUI device-flow login",
    )
    parser.add_argument(
        "--display-name",
        default=os.getenv("USER", "operator"),
        help="Fallback local display label shown before Keycloak identity is loaded",
    )
    parser.add_argument(
        "--workspace-name",
        default="Open Talon Workspace",
        help="Default workspace name when bootstrapping state",
    )
    parser.add_argument(
        "--thread-title",
        default="General",
        help="Default thread title when bootstrapping state",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    _reset_terminal_mode()
    if argv[:2] == ["auth", "login"]:
        parser = _build_parser()
        args = parser.parse_args(argv[2:])
        profile = resolve_startup_profile(args.profile, oidc_enabled=True)
        current_user = asyncio.run(
            run_auth_login(
                gateway=args.gateway,
                profile=profile,
                oidc_issuer_url=args.oidc_issuer_url,
                oidc_client_id=args.oidc_client_id,
                display_name=args.display_name,
            )
        )
        print(f"Signed in profile: {profile}")
        print(f"User: {current_user['display_name']}")
        print(f"User ID: {current_user['user_id']}")
        return

    parser = _build_parser()
    args = parser.parse_args(argv)
    profile = resolve_startup_profile(args.profile, oidc_enabled=True)
    client = ScrollbackTUI2(
        gateway=args.gateway,
        profile=profile,
        oidc_issuer_url=args.oidc_issuer_url,
        oidc_client_id=args.oidc_client_id,
        display_name=args.display_name,
        workspace_name=args.workspace_name,
        thread_title=args.thread_title,
    )
    asyncio.run(client.start())


if __name__ == "__main__":
    main()
