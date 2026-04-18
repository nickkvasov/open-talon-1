"""
Open Talon scriptable user client.

A line-oriented, per-profile terminal client intended for software development
agents that need to drive human-user collaboration flows end to end.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx

from open_talon_tui.main import (
    _DEFAULT_OIDC_CLIENT_ID,
    _DEFAULT_OIDC_ISSUER_URL,
    TokenState,
    discover_oidc,
    fetch_current_user,
    load_state,
    load_tokens,
    reset_profile_session_state,
    resolve_startup_profile,
    run_auth_login,
    save_state,
    save_tokens,
)

_INTERACTION_SELECTOR_PATTERN = re.compile(r"@(?:(role|capability):)?([A-Za-z0-9_.-]+)")


def _format_timestamp(raw_timestamp: str | None) -> str:
    if not raw_timestamp:
        return "--:--"
    try:
        normalized = raw_timestamp.replace("Z", "+00:00")
        timestamp = datetime.fromisoformat(normalized)
        return timestamp.astimezone().strftime("%H:%M")
    except Exception:
        return "--:--"


def _build_interaction_requests_from_text(text: str) -> list[dict[str, Any]]:
    selectors: list[dict[str, str]] = []
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


class UserClient:
    def __init__(
        self,
        *,
        gateway: str,
        profile: str,
        oidc_issuer_url: str,
        oidc_client_id: str,
        display_name: str,
        output_format: str,
    ) -> None:
        self.gateway = gateway.rstrip("/")
        self.profile = profile
        self.oidc_issuer_url = oidc_issuer_url.rstrip("/")
        self.oidc_client_id = oidc_client_id
        self.output_format = output_format
        self.state = load_state(profile, display_name, "user")
        self.tokens = load_tokens(profile)
        if self.tokens is None:
            self.state = reset_profile_session_state(
                profile,
                display_name=display_name,
                participant_type="user",
            )
        self.current_user: dict[str, Any] | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._fallback_actor_id = str(uuid4())
        self._exit_requested = False

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
    def _auth_headers(self) -> dict[str, str]:
        if self.tokens is None:
            return {}
        return {"Authorization": f"Bearer {self.tokens.access_token}"}

    @property
    def _is_authenticated(self) -> bool:
        return self.tokens is not None and self.current_user is not None

    def _emit(self, *, command: str, data: Any | None = None, message: str | None = None) -> None:
        if self.output_format == "json":
            print(
                json.dumps(
                    {
                        "ok": True,
                        "command": command,
                        "message": message,
                        "data": data,
                    },
                    sort_keys=True,
                )
            )
            return
        if message:
            print(message)
        if isinstance(data, list):
            for item in data:
                print(item)
        elif isinstance(data, dict):
            for key, value in data.items():
                print(f"{key}: {value}")
        elif data is not None:
            print(data)

    def _emit_error(self, *, command: str, message: str) -> None:
        if self.output_format == "json":
            print(
                json.dumps(
                    {
                        "ok": False,
                        "command": command,
                        "error": message,
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"error: {message}")

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
        self._emit(command="session.invalidate", message=reason)

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
        save_tokens(self.profile, self.tokens)
        self._sync_http_auth()
        return True

    async def _ensure_bearer_token(self) -> None:
        if self._token_expiring_soon(self.tokens):
            if not await self._refresh_oidc_tokens():
                self._invalidate_saved_session("token refresh failed; run `auth login`")
                raise RuntimeError("authentication required")

    async def _load_current_user(self) -> None:
        if self.tokens is None:
            self.current_user = None
            return
        self.current_user = await fetch_current_user(
            gateway=self.gateway,
            access_token=self.tokens.access_token,
        )
        self.state.user_id = self.current_user["user_id"]
        self.state.display_name = self.current_user["display_name"]
        self.state.participant_type = "user"
        save_state(self.profile, self.state)

    async def _activate_profile_session(self) -> None:
        self._sync_http_auth()
        if self.tokens is None:
            return
        await self._ensure_bearer_token()
        try:
            await self._load_current_user()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {401, 403}:
                self._invalidate_saved_session("saved login expired; run `auth login`")
                return
            raise

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        if self._http_client is None:
            raise RuntimeError("client not started")
        await self._ensure_bearer_token()
        self._sync_http_auth()
        response = await self._http_client.request(
            method,
            f"{self.gateway}{path}",
            json=json_body,
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def _set_current_participant(self, participants: list[dict[str, Any]]) -> None:
        current: dict[str, Any] | None = None
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
            save_state(self.profile, self.state)

    def _update_state_from_message(self, message: dict[str, Any]) -> None:
        actor = message.get("actor", {})
        if actor.get("id"):
            self.state.participant_id = actor["id"]
        if message.get("workspace_id"):
            self.state.workspace_id = message["workspace_id"]
        if message.get("thread_id"):
            self.state.thread_id = message["thread_id"]
        sequence = message.get("sequence")
        if isinstance(sequence, int):
            self.state.last_sequence = max(self.state.last_sequence, sequence)
        save_state(self.profile, self.state)

    def _render_message(self, message: dict[str, Any]) -> str:
        actor = message.get("actor", {})
        actor_id = actor.get("id", "")
        prefix = "You" if actor_id == self.state.participant_id else f"Peer {str(actor_id)[:8]}"
        metadata = message.get("metadata", {})
        if isinstance(metadata, dict):
            request_status = metadata.get("interaction_request_status")
            aggregate = metadata.get("interaction_aggregate")
            if metadata.get("interaction_request_id"):
                coverage = ""
                if isinstance(aggregate, dict):
                    coverage = (
                        f" {aggregate.get('answered_count', 0)}/{aggregate.get('target_count', 0)}"
                    )
                prefix = f"{prefix} [request {request_status or 'open'}{coverage}]"
            elif metadata.get("interaction_question_ids"):
                prefix = f"{prefix} [answer]"
        return f"{_format_timestamp(message.get('created_at') or message.get('updated_at'))} {prefix}: {message.get('content', '')}"

    def _resolve_workspace_target(
        self,
        workspaces: list[dict[str, Any]],
        target: str,
    ) -> dict[str, Any] | None:
        normalized = target.strip()
        if not normalized or normalized == "current":
            return next(
                (workspace for workspace in workspaces if workspace["workspace_id"] == self.state.workspace_id),
                None,
            )
        for workspace in workspaces:
            workspace_id = workspace["workspace_id"]
            if workspace_id == normalized or workspace_id.startswith(normalized):
                return workspace
        lowered = normalized.lower()
        for workspace in workspaces:
            if workspace["name"].lower() == lowered:
                return workspace
        return None

    def _resolve_thread_target(
        self,
        threads: list[dict[str, Any]],
        target: str,
    ) -> dict[str, Any] | None:
        normalized = target.strip()
        if not normalized or normalized == "current":
            return next(
                (thread for thread in threads if thread["thread_id"] == self.state.thread_id),
                None,
            )
        for thread in threads:
            thread_id = thread["thread_id"]
            if thread_id == normalized or thread_id.startswith(normalized):
                return thread
        lowered = normalized.lower()
        for thread in threads:
            if thread["title"].lower() == lowered:
                return thread
        return None

    def _resolve_request_target(
        self,
        details: list[dict[str, Any]],
        target: str,
    ) -> dict[str, Any] | None:
        normalized = target.strip()
        if not normalized or normalized == "current":
            open_requests = [detail for detail in details if detail["request"]["status"] == "open"]
            return open_requests[0] if len(open_requests) == 1 else None
        for detail in details:
            request_id = detail["request"]["request_id"]
            if request_id == normalized or request_id.startswith(normalized):
                return detail
        lowered = normalized.lower()
        for detail in details:
            if detail["request"]["title"].lower() == lowered:
                return detail
        return None

    @staticmethod
    def _looks_like_uuid(value: str) -> bool:
        try:
            UUID(value)
        except ValueError:
            return False
        return True

    async def _list_workspaces(self) -> list[dict[str, Any]]:
        body = await self._request("GET", "/v1/workspaces")
        assert isinstance(body, list)
        return body

    async def _workspace_detail(self, workspace_id: str) -> dict[str, Any]:
        body = await self._request("GET", f"/v1/workspaces/{workspace_id}")
        assert isinstance(body, dict)
        self._set_current_participant(body.get("participants", []))
        return body

    async def _list_threads(self, workspace_id: str) -> list[dict[str, Any]]:
        body = await self._request("GET", f"/v1/workspaces/{workspace_id}/threads")
        assert isinstance(body, list)
        return body

    async def _list_interaction_requests(self, thread_id: str) -> list[dict[str, Any]]:
        body = await self._request("GET", f"/v1/threads/{thread_id}/requests")
        assert isinstance(body, list)
        return body

    async def _timeline(self, thread_id: str) -> dict[str, Any]:
        body = await self._request("GET", f"/v1/threads/{thread_id}/timeline")
        assert isinstance(body, dict)
        messages = body.get("messages", [])
        if messages:
            last_sequence = max(
                (message.get("sequence", 0) for message in messages if isinstance(message.get("sequence"), int)),
                default=self.state.last_sequence,
            )
            self.state.last_sequence = max(self.state.last_sequence, last_sequence)
            save_state(self.profile, self.state)
        return body

    async def _communication_log(self, workspace_id: str, *, limit: int) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if self.state.thread_id:
            params["thread_id"] = self.state.thread_id
        body = await self._request(
            "GET",
            f"/v1/workspaces/{workspace_id}/communication-log",
            params=params,
        )
        assert isinstance(body, dict)
        return body

    async def _post_message(self, content: str) -> dict[str, Any]:
        if not self.state.thread_id:
            raise RuntimeError("select a thread first with `thread use` or `thread create`")
        body = await self._request(
            "POST",
            f"/v1/threads/{self.state.thread_id}/messages",
            json_body={
                "actor": self.actor_payload,
                "content": content,
                "visibility": "workspace",
                "create_task": True,
                "requests": _build_interaction_requests_from_text(content),
            },
        )
        assert isinstance(body, dict)
        self._update_state_from_message(body)
        return body

    async def _answer_interaction_request(self, request_id: str, content: str) -> dict[str, Any]:
        body = await self._request(
            "POST",
            f"/v1/requests/{request_id}/answers",
            json_body={
                "actor": self.actor_payload,
                "content": content,
            },
        )
        assert isinstance(body, dict)
        return body

    async def _assume_role(
        self,
        *,
        role: str,
        description: str | None,
        capabilities: list[str],
    ) -> dict[str, Any]:
        if not self.state.workspace_id:
            raise RuntimeError("select a workspace first with `workspace use` or `workspace create`")
        participant_id = self.state.participant_id or self.state.user_id or self._fallback_actor_id
        body = await self._request(
            "PATCH",
            f"/v1/workspaces/{self.state.workspace_id}/participants/{participant_id}/role",
            json_body={
                "actor": self.actor_payload,
                "role": role,
                "description": description,
                "capabilities": capabilities,
            },
        )
        assert isinstance(body, dict)
        self.state.participant_id = body.get("participant_id", self.state.participant_id)
        save_state(self.profile, self.state)
        return body

    async def handle_command(self, raw: str) -> None:
        text = raw.strip()
        if not text:
            return
        normalized = text[1:] if text.startswith("/") else text
        command_name = normalized.split(maxsplit=1)[0].lower()
        known_commands = {
            "help",
            "status",
            "auth",
            "workspace",
            "thread",
            "role",
            "send",
            "timeline",
            "request",
            "log",
            "quit",
        }
        if command_name not in known_commands and not text.startswith("/"):
            message = await self._post_message(text)
            self._emit(command="send", message=self._render_message(message), data=message)
            return

        if command_name == "help":
            self._emit(
                command="help",
                data=[
                    "help",
                    "status",
                    "auth login",
                    "auth logout",
                    "workspace list|show|create <name>|use <id|name>|clear",
                    "thread list|show|create <title>|use <id|title>|clear",
                    "role list|use <role> [:: <description> :: <cap1,cap2>]",
                    "send <text>",
                    "timeline [limit]",
                    "request list [open|all]",
                    "request show <id|title|current>",
                    "request answer <id|title|current> :: <text>",
                    "log [limit]",
                    "quit",
                ],
            )
            return

        if command_name == "quit":
            self._exit_requested = True
            self._emit(command="quit", message=f"profile {self.profile} exiting")
            return

        if command_name == "status":
            self._emit(
                command="status",
                data={
                    "profile": self.profile,
                    "authenticated": self._is_authenticated,
                    "display_name": self.state.display_name,
                    "user_id": self.state.user_id,
                    "participant_id": self.state.participant_id,
                    "workspace_id": self.state.workspace_id,
                    "thread_id": self.state.thread_id,
                },
            )
            return

        if normalized.startswith("auth "):
            action = normalized.split(maxsplit=1)[1].strip().lower()
            if action == "login":
                current_user = await run_auth_login(
                    gateway=self.gateway,
                    profile=self.profile,
                    oidc_issuer_url=self.oidc_issuer_url,
                    oidc_client_id=self.oidc_client_id,
                    display_name=self.state.display_name,
                    write_line=lambda line: self._emit(command="auth.login", message=str(line)),
                )
                self.tokens = load_tokens(self.profile)
                await self._activate_profile_session()
                self._emit(command="auth.login", data=current_user, message=f"signed in profile: {self.profile}")
                return
            if action == "logout":
                self.tokens = None
                self.current_user = None
                self.state = reset_profile_session_state(
                    self.profile,
                    display_name=self.state.display_name,
                    participant_type="user",
                )
                save_tokens(self.profile, None)
                self._sync_http_auth()
                self._emit(command="auth.logout", message=f"signed out profile: {self.profile}")
                return
            raise ValueError("supported auth commands: `auth login`, `auth logout`")

        if not self._is_authenticated:
            raise RuntimeError("sign in first with `auth login`")

        if normalized.startswith("workspace "):
            remainder = normalized.split(maxsplit=1)[1].strip()
            if remainder == "list":
                workspaces = await self._list_workspaces()
                self._emit(
                    command="workspace.list",
                    data=[
                        f"{'*' if item['workspace_id'] == self.state.workspace_id else '-'} {item['name']} ({item['workspace_id'][:8]})"
                        for item in workspaces
                    ],
                )
                return
            if remainder == "show":
                if not self.state.workspace_id:
                    raise RuntimeError("no workspace selected")
                detail = await self._workspace_detail(self.state.workspace_id)
                self._emit(
                    command="workspace.show",
                    data={
                        "workspace_id": detail["workspace"]["workspace_id"],
                        "name": detail["workspace"]["name"],
                        "participants": len(detail.get("participants", [])),
                        "role_definitions": [item["name"] for item in detail.get("role_definitions", [])],
                    },
                )
                return
            if remainder == "clear":
                self.state.workspace_id = None
                self.state.thread_id = None
                save_state(self.profile, self.state)
                self._emit(command="workspace.clear", message="cleared current workspace and thread")
                return
            if remainder.startswith("create "):
                name = remainder[len("create ") :].strip()
                if not name:
                    raise ValueError("usage: `workspace create <name>`")
                body = await self._request(
                    "POST",
                    "/v1/workspaces",
                    json_body={
                        "name": name,
                        "description": "Workspace created by the Open Talon user client",
                        "actor": self.actor_payload,
                    },
                )
                assert isinstance(body, dict)
                self.state.workspace_id = body["workspace"]["workspace_id"]
                self.state.thread_id = None
                self._set_current_participant(body.get("participants", []))
                save_state(self.profile, self.state)
                self._emit(command="workspace.create", data=body["workspace"], message=f"selected workspace {name}")
                return
            if remainder.startswith("use "):
                target = remainder[len("use ") :].strip()
                if not target:
                    raise ValueError("usage: `workspace use <id|name>`")
                workspaces = await self._list_workspaces()
                selected = self._resolve_workspace_target(workspaces, target)
                if selected is not None:
                    self.state.workspace_id = selected["workspace_id"]
                    self.state.thread_id = None
                    detail = await self._workspace_detail(self.state.workspace_id)
                    self._set_current_participant(detail.get("participants", []))
                    save_state(self.profile, self.state)
                    self._emit(
                        command="workspace.use",
                        data=selected,
                        message=f"selected workspace {selected['name']}",
                    )
                    return
                if self._looks_like_uuid(target):
                    self.state.workspace_id = target
                    self.state.thread_id = None
                    save_state(self.profile, self.state)
                    self._emit(
                        command="workspace.use",
                        message=f"selected workspace id {target}; access will be confirmed by the next workspace action",
                    )
                    return
                raise KeyError(f"workspace not found: {target}")
            raise ValueError("supported workspace commands: list, show, create, use, clear")

        if normalized.startswith("thread "):
            remainder = normalized.split(maxsplit=1)[1].strip()
            if remainder == "list":
                if not self.state.workspace_id:
                    raise RuntimeError("select a workspace first")
                threads = await self._list_threads(self.state.workspace_id)
                self._emit(
                    command="thread.list",
                    data=[
                        f"{'*' if item['thread_id'] == self.state.thread_id else '-'} {item['title']} ({item['thread_id'][:8]})"
                        for item in threads
                    ],
                )
                return
            if remainder == "show":
                if not self.state.thread_id:
                    raise RuntimeError("no thread selected")
                body = await self._request("GET", f"/v1/threads/{self.state.thread_id}")
                assert isinstance(body, dict)
                memberships = body.get("memberships", [])
                if memberships:
                    self.state.participant_id = memberships[0].get("participant_id", self.state.participant_id)
                    save_state(self.profile, self.state)
                self._emit(
                    command="thread.show",
                    data={
                        "thread_id": body["thread"]["thread_id"],
                        "title": body["thread"]["title"],
                        "memberships": len(memberships),
                    },
                )
                return
            if remainder == "clear":
                self.state.thread_id = None
                save_state(self.profile, self.state)
                self._emit(command="thread.clear", message="cleared current thread")
                return
            if remainder.startswith("create "):
                if not self.state.workspace_id:
                    raise RuntimeError("select a workspace first")
                title = remainder[len("create ") :].strip()
                if not title:
                    raise ValueError("usage: `thread create <title>`")
                body = await self._request(
                    "POST",
                    f"/v1/workspaces/{self.state.workspace_id}/threads",
                    json_body={
                        "title": title,
                        "actor": self.actor_payload,
                    },
                )
                assert isinstance(body, dict)
                self.state.thread_id = body["thread"]["thread_id"]
                memberships = body.get("memberships", [])
                if memberships:
                    self.state.participant_id = memberships[0].get("participant_id", self.state.participant_id)
                save_state(self.profile, self.state)
                self._emit(command="thread.create", data=body["thread"], message=f"selected thread {title}")
                return
            if remainder.startswith("use "):
                target = remainder[len("use ") :].strip()
                if not target:
                    raise ValueError("usage: `thread use <id|title>`")
                if self.state.workspace_id:
                    try:
                        threads = await self._list_threads(self.state.workspace_id)
                    except Exception:
                        threads = []
                    selected = self._resolve_thread_target(threads, target)
                    if selected is not None:
                        self.state.thread_id = selected["thread_id"]
                        save_state(self.profile, self.state)
                        self._emit(command="thread.use", data=selected, message=f"selected thread {selected['title']}")
                        return
                if self._looks_like_uuid(target):
                    self.state.thread_id = target
                    save_state(self.profile, self.state)
                    self._emit(
                        command="thread.use",
                        message=f"selected thread id {target}; membership will be established on the first message if needed",
                    )
                    return
                raise KeyError(f"thread not found: {target}")
            raise ValueError("supported thread commands: list, show, create, use, clear")

        if normalized.startswith("role "):
            remainder = normalized.split(maxsplit=1)[1].strip()
            if remainder == "list":
                if not self.state.workspace_id:
                    raise RuntimeError("select a workspace first")
                detail = await self._workspace_detail(self.state.workspace_id)
                self._emit(
                    command="role.list",
                    data=[
                        f"{item['name']}: {item['definition']}"
                        for item in detail.get("role_definitions", [])
                    ],
                )
                return
            if remainder.startswith("use "):
                payload = remainder[len("use ") :]
                segments = [segment.strip() for segment in payload.split("::")]
                role = segments[0]
                if not role:
                    raise ValueError("usage: `role use <role> [:: <description> :: <cap1,cap2>]`")
                description = segments[1] if len(segments) > 1 and segments[1] else None
                capabilities = (
                    [item.strip() for item in segments[2].split(",") if item.strip()]
                    if len(segments) > 2 and segments[2]
                    else []
                )
                participant = await self._assume_role(
                    role=role,
                    description=description,
                    capabilities=capabilities,
                )
                self._emit(
                    command="role.use",
                    data={
                        "participant_id": participant["participant_id"],
                        "roles": participant.get("roles", []),
                        "capabilities": participant.get("capabilities", []),
                    },
                    message=f"current role set to {role}",
                )
                return
            raise ValueError("supported role commands: list, use")

        if normalized.startswith("send "):
            message = await self._post_message(normalized[len("send ") :].strip())
            self._emit(command="send", message=self._render_message(message), data=message)
            return

        if command_name == "timeline":
            limit = 50
            parts = shlex.split(normalized)
            if len(parts) > 1:
                limit = int(parts[1])
            if not self.state.thread_id:
                raise RuntimeError("select a thread first")
            timeline = await self._timeline(self.state.thread_id)
            messages = timeline.get("messages", [])[-limit:]
            self._emit(
                command="timeline",
                data=[self._render_message(message) for message in messages],
            )
            return

        if normalized.startswith("request "):
            remainder = normalized.split(maxsplit=1)[1].strip()
            if remainder.startswith("list"):
                if not self.state.thread_id:
                    raise RuntimeError("select a thread first")
                mode = "all"
                parts = shlex.split(remainder)
                if len(parts) > 1:
                    mode = parts[1].lower()
                details = await self._list_interaction_requests(self.state.thread_id)
                if mode == "open":
                    details = [detail for detail in details if detail["request"]["status"] == "open"]
                lines = []
                for detail in details:
                    aggregate = detail["request"].get("metadata", {}).get("aggregate", {})
                    coverage = ""
                    if isinstance(aggregate, dict):
                        coverage = f" {aggregate.get('answered_count', 0)}/{aggregate.get('target_count', 0)}"
                    lines.append(
                        f"{detail['request']['status']} {detail['request']['title']} ({detail['request']['request_id'][:8]}){coverage}"
                    )
                self._emit(command="request.list", data=lines)
                return
            if remainder.startswith("show "):
                target = remainder[len("show ") :].strip()
                details = await self._list_interaction_requests(self.state.thread_id) if self.state.thread_id else []
                detail = self._resolve_request_target(details, target)
                if detail is None:
                    if self._looks_like_uuid(target):
                        body = await self._request("GET", f"/v1/requests/{target}")
                        assert isinstance(body, dict)
                        detail = body
                    else:
                        raise KeyError(f"request not found: {target}")
                self._emit(
                    command="request.show",
                    data={
                        "request_id": detail["request"]["request_id"],
                        "title": detail["request"]["title"],
                        "status": detail["request"]["status"],
                        "questions": [question["prompt"] for question in detail.get("questions", [])],
                        "targets": [
                            {
                                "participant_id": target_item.get("participant_id"),
                                "selector_type": target_item.get("selector_type"),
                                "selector_value": target_item.get("selector_value"),
                                "status": target_item.get("status"),
                            }
                            for target_item in detail.get("targets", [])
                        ],
                        "answers": [
                            {
                                "participant_id": answer.get("participant_id"),
                                "message_id": answer.get("message_id"),
                            }
                            for answer in detail.get("answers", [])
                        ],
                    },
                )
                return
            if remainder.startswith("answer "):
                target_and_content = remainder[len("answer ") :]
                target_part, separator, content = target_and_content.partition("::")
                if not separator or not content.strip():
                    raise ValueError("usage: `request answer <id|title|current> :: <text>`")
                target = target_part.strip()
                details = await self._list_interaction_requests(self.state.thread_id) if self.state.thread_id else []
                detail = self._resolve_request_target(details, target)
                request_id = detail["request"]["request_id"] if detail is not None else target
                result = await self._answer_interaction_request(request_id, content.strip())
                self._emit(
                    command="request.answer",
                    data=result,
                    message=f"answered request {request_id}",
                )
                return
            raise ValueError("supported request commands: list, show, answer")

        if command_name == "log":
            parts = shlex.split(normalized)
            limit = 50
            if len(parts) > 1:
                limit = int(parts[1])
            if not self.state.workspace_id:
                raise RuntimeError("select a workspace first")
            page = await self._communication_log(self.state.workspace_id, limit=limit)
            entries = page.get("entries", [])
            self._emit(
                command="log",
                data=[
                    f"{_format_timestamp(entry.get('created_at') or entry.get('updated_at'))} {entry.get('kind')} {entry.get('actor_display_name')}: {entry.get('content', '')}"
                    for entry in entries
                ],
            )
            return

        raise ValueError(f"unsupported command: {text}")

    async def run_commands(self, commands: list[str]) -> int:
        assert self._http_client is not None
        for command in commands:
            try:
                await self.handle_command(command)
            except Exception as exc:
                self._emit_error(command=command, message=str(exc))
                return 1
            if self._exit_requested:
                break
        return 0

    async def repl(self) -> int:
        assert self._http_client is not None
        self._emit(
            command="startup",
            message=(
                "Open Talon user client. One instance maps to one user profile. "
                "Use `help` for commands."
            ),
        )
        while not self._exit_requested:
            try:
                raw = await asyncio.to_thread(input, f"{self.profile}> ")
            except EOFError:
                break
            except KeyboardInterrupt:
                print()
                break
            if not raw.strip():
                continue
            try:
                await self.handle_command(raw)
            except Exception as exc:
                self._emit_error(command=raw, message=str(exc))
        return 0

    async def start(self, *, commands: list[str] | None = None) -> int:
        self._http_client = httpx.AsyncClient(
            headers=self._auth_headers,
            timeout=10,
            trust_env=False,
        )
        try:
            await self._activate_profile_session()
            if commands:
                return await self.run_commands(commands)
            return await self.repl()
        finally:
            await self._http_client.aclose()
            self._http_client = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open Talon scriptable per-user collaboration client",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--gateway", default="http://127.0.0.1:8000", help="Gateway base URL")
    parser.add_argument("--profile", default=None, help="Named local user profile")
    parser.add_argument(
        "--oidc-issuer-url",
        default=os.getenv("OPEN_TALON_OIDC_ISSUER_URL", _DEFAULT_OIDC_ISSUER_URL),
        help="Keycloak OIDC issuer URL for device login",
    )
    parser.add_argument(
        "--oidc-client-id",
        default=os.getenv("OPEN_TALON_OIDC_CLIENT_ID", _DEFAULT_OIDC_CLIENT_ID),
        help="Keycloak OIDC client id for the user client device-flow login",
    )
    parser.add_argument(
        "--display-name",
        default=os.getenv("USER", "operator"),
        help="Fallback local display label shown before Keycloak identity is loaded",
    )
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Command output format",
    )
    parser.add_argument(
        "--command",
        action="append",
        default=[],
        help="Run a command non-interactively; may be passed multiple times",
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
    client = UserClient(
        gateway=args.gateway,
        profile=profile,
        oidc_issuer_url=args.oidc_issuer_url,
        oidc_client_id=args.oidc_client_id,
        display_name=args.display_name,
        output_format=args.output,
    )
    raise SystemExit(asyncio.run(client.start(commands=list(args.command))))


if __name__ == "__main__":
    main()
