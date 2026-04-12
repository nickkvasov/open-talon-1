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
import sys
import threading
import webbrowser
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import websockets
import websockets.exceptions

from open_talon_tui.main import (
    _DEFAULT_OIDC_CLIENT_ID,
    _DEFAULT_OIDC_ISSUER_URL,
    _URL_PATTERN,
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
    try:
        normalized = raw_timestamp.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(normalized)
        return timestamp.astimezone().strftime("%H:%M")
    except Exception:
        return "--:--"


class ScrollbackTUI2:
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

    def _print_line(self, text: str = "") -> None:
        with self._stdout_lock:
            sys.stdout.write(_render_terminal_links(text) + "\n")
            sys.stdout.flush()

    def _record_line(self, text: str) -> None:
        self._history_lines.append(text)
        for url in _URL_PATTERN.findall(text):
            if url not in self._detected_links:
                self._detected_links.append(url)
        self._print_line(text)

    def _write_system(self, text: str) -> None:
        self._record_line(f"-- {text} --")

    def _sync_http_auth(self) -> None:
        if self._http_client is None:
            return
        self._http_client.headers.clear()
        self._http_client.headers.update(self._auth_headers)

    def _invalidate_saved_session(self, reason: str) -> None:
        self.tokens = None
        self.current_user = None
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

    async def _load_current_user(self) -> None:
        if self.tokens is None:
            self.current_user = None
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
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def _ws_loop(self) -> None:
        assert self.state.thread_id is not None
        ws_base = self.gateway.replace("http://", "ws://").replace("https://", "wss://")
        while True:
            await self._ensure_bearer_token()
            if not self._is_authenticated:
                return
            query = urlencode({"after_sequence": self.state.last_sequence})
            url = f"{ws_base}/v1/threads/{self.state.thread_id}/ws?{query}"
            headers = list(self._auth_headers.items())
            try:
                async with websockets.connect(url, additional_headers=headers) as ws:
                    self._ws = ws
                    async for raw in ws:
                        self._handle_event(json.loads(raw))
            except asyncio.CancelledError:
                raise
            except websockets.exceptions.ConnectionClosed:
                pass
            except websockets.exceptions.InvalidStatus as exc:
                status_code = self._http_status_code(exc)
                if status_code in {401, 403}:
                    self._invalidate_saved_session("websocket session expired; run /auth login")
                    return
                self._write_system(f"websocket error: {self._describe_exception(exc)}")
            except Exception as exc:
                self._write_system(f"websocket error: {self._describe_exception(exc)}")
            finally:
                self._ws = None
            await asyncio.sleep(3)

    async def _activate_profile_session(self) -> None:
        try:
            await self._ensure_bearer_token()
        except Exception as exc:
            self._handle_runtime_error(exc, context="unable to refresh login")
            return
        self._sync_http_auth()
        if self.tokens is None:
            self.current_user = None
            self._write_system(f"signed out ({self.profile}); run /auth login")
            return
        try:
            await self._load_current_user()
        except Exception as exc:
            self._handle_runtime_error(exc, context="unable to load current user")
            return
        if self.current_user is None or self.tokens is None:
            self._write_system(f"signed out ({self.profile}); run /auth login")
            return
        try:
            await self._ensure_context()
            await self._load_timeline()
        except Exception as exc:
            self._handle_runtime_error(exc, context="unable to load workspace context")
            return
        self._start_ws()
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
        if not self.state.thread_id:
            self._write_system("thread not ready yet")
            return
        assert self._http_client is not None
        response = await self._http_client.post(
            f"{self.gateway}/v1/threads/{self.state.thread_id}/messages",
            json={
                "actor": self.actor_payload,
                "content": text,
                "visibility": "public",
                "create_task": True,
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
                "commands: /auth login | /auth logout | /account whoami | /account list | /account switch <profile> | /workspace list | /workspace create <name> | /workspace use <id|name> | /thread list | /thread create <title> | /thread use <id|title> | /links | /open <n|last|url> | /copy | /quit"
            )
            return
        if text == "/quit":
            self._stop = True
            return
        if text == "/clear":
            if sys.stdout.isatty():
                sys.stdout.write("\033[2J\033[H")
                sys.stdout.flush()
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
        self._print_line("Open Talon TUI2")
        self._print_line("Scrollback-first mode. Mouse selection should work normally in your terminal.")
        self._print_line("Type /help for commands.")
        try:
            try:
                await self._activate_profile_session()
            except Exception as exc:
                self._handle_runtime_error(exc, context="startup error", invalidate_auth=False)
            while not self._stop:
                try:
                    raw = await asyncio.to_thread(input, f"{self.profile}> ")
                except EOFError:
                    break
                except KeyboardInterrupt:
                    self._print_line("")
                    break
                text = raw.strip()
                if not text:
                    continue
                try:
                    if text.startswith("/"):
                        await self._handle_command(text)
                    else:
                        await self._send_message(text)
                except Exception as exc:
                    self._handle_runtime_error(exc, context="command failed")
        finally:
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
