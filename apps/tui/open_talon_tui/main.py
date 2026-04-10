"""
Open Talon collaboration TUI.

The TUI creates or reuses a workspace/thread pair, posts messages over REST,
and listens to the shared thread timeline over WebSocket.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
import websockets
import websockets.exceptions
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.suggester import SuggestFromList, Suggester
from textual.widgets import Footer, Header, Input, RichLog, Static

_CFG_DIR = Path.home() / ".open-talon"
_STATE_FILE = _CFG_DIR / "collaboration.json"
_LOG_FILE = _CFG_DIR / "tui.log"

_CFG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=os.getenv("OPEN_TALON_TUI_LOG_LEVEL", "DEBUG").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        TimedRotatingFileHandler(
            _LOG_FILE,
            when="midnight",
            interval=1,
            backupCount=7,
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class ClientState:
    participant_id: str
    display_name: str
    participant_type: str
    workspace_id: str | None = None
    thread_id: str | None = None
    last_sequence: int = 0


def load_state(display_name: str, participant_type: str) -> ClientState:
    try:
        data = json.loads(_STATE_FILE.read_text())
        return ClientState(
            participant_id=data["participant_id"],
            display_name=data.get("display_name", display_name),
            participant_type=data.get("participant_type", participant_type),
            workspace_id=data.get("workspace_id"),
            thread_id=data.get("thread_id"),
            last_sequence=data.get("last_sequence", 0),
        )
    except Exception:
        state = ClientState(
            participant_id=str(uuid4()),
            display_name=display_name,
            participant_type=participant_type,
        )
        save_state(state)
        return state


def save_state(state: ClientState) -> None:
    _CFG_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(asdict(state), indent=2))


class WorkspaceCommandSuggester(Suggester):
    def __init__(self, app: "CollaborationApp") -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self.app = app
        self._base = SuggestFromList(app._slash_commands, case_sensitive=False)

    async def get_suggestion(self, value: str) -> str | None:
        suggestion = await self._base.get_suggestion(value)
        if suggestion is not None:
            return suggestion

        stripped = value.strip()
        if not stripped.startswith("/workspace ") and not stripped.startswith("/ws "):
            return None

        normalized = stripped.replace("/ws ", "/workspace ", 1)
        workspace_targets = self.app.workspace_suggestion_targets

        for prefix in ("/workspace switch ", "/workspace delete "):
            if normalized.startswith(prefix):
                typed_target = normalized[len(prefix) :].strip().casefold()
                if not typed_target:
                    return prefix + (workspace_targets[0] if workspace_targets else "")
                for target in workspace_targets:
                    if target.casefold().startswith(typed_target):
                        return prefix + target
        if stripped.startswith("/role "):
            role_targets = self.app.role_suggestion_targets
            for prefix in ("/role assume ", "/role create "):
                if stripped.startswith(prefix):
                    typed_target = stripped[len(prefix) :].strip().casefold()
                    if not typed_target:
                        return prefix + (role_targets[0] if role_targets else "")
                    for target in role_targets:
                        if target.casefold().startswith(typed_target):
                            return prefix + target
        return None


CSS = """
Screen {
    background: $surface-darken-3;
}

#body {
    layout: vertical;
    height: 1fr;
}

#timeline {
    height: 1fr;
    border: round $accent 30%;
    margin: 0 1;
    padding: 0 1;
}

#status-bar {
    height: 1;
    background: $boost;
    padding: 0 2;
    color: $text-muted;
}

#composer {
    height: 3;
    margin: 1;
    layout: horizontal;
}

#msg-input {
    width: 1fr;
}

#context-info {
    height: 2;
    background: $panel;
    padding: 0 2;
    color: $text-muted;
}

#suggestion-bar {
    height: 1;
    background: $surface;
    padding: 0 2;
    color: $text-muted;
}
"""


class CollaborationApp(App):
    TITLE = "Open Talon"
    SUB_TITLE = "Collaboration TUI"
    CSS = CSS
    BINDINGS = [
        Binding("ctrl+n", "new_thread", "New Thread"),
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+l", "clear", "Clear"),
    ]

    status: reactive[str] = reactive("Connecting...")
    connected: reactive[bool] = reactive(False)

    def __init__(
        self,
        *,
        gateway: str,
        api_key: str | None,
        openbao_token: str | None,
        display_name: str,
        workspace_name: str,
        thread_title: str,
        participant_type: str,
    ) -> None:
        super().__init__()
        normalized_gateway = gateway.rstrip("/")
        if normalized_gateway.startswith("http://localhost"):
            normalized_gateway = normalized_gateway.replace(
                "http://localhost", "http://127.0.0.1", 1
            )
        elif normalized_gateway.startswith("ws://localhost"):
            normalized_gateway = normalized_gateway.replace(
                "ws://localhost", "ws://127.0.0.1", 1
            )
        self.gateway = normalized_gateway
        self.api_key = api_key
        self.openbao_token = openbao_token
        self.workspace_name = workspace_name
        self.default_thread_title = thread_title
        self.state = load_state(display_name, participant_type)
        self._ws = None
        self._seen_message_ids: set[str] = set()
        self._http_client: httpx.AsyncClient | None = None
        self._slash_commands = [
            "/workspaces",
            "/workspace list",
            "/workspace create ",
            "/workspace switch ",
            "/workspace delete ",
            "/role create ",
            "/role show",
            "/role assume ",
            "/ws list",
            "/ws create ",
            "/ws switch ",
            "/ws delete ",
        ]
        self._workspace_suggestions: list[dict[str, str]] = []
        self._role_suggestions: list[str] = []

    @property
    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if self.openbao_token:
            headers["Authorization"] = f"Bearer {self.openbao_token}"
        return headers

    @property
    def actor_payload(self) -> dict[str, str]:
        return {
            "participant_id": self.state.participant_id,
            "participant_type": self.state.participant_type,
            "display_name": self.state.display_name,
        }

    @property
    def workspace_suggestion_targets(self) -> list[str]:
        targets: list[str] = []
        for workspace in self._workspace_suggestions:
            name = workspace["name"]
            workspace_id = workspace["workspace_id"]
            for candidate in (name, workspace_id[:8], workspace_id):
                if candidate not in targets:
                    targets.append(candidate)
        return targets

    @property
    def role_suggestion_targets(self) -> list[str]:
        return list(self._role_suggestions)

    async def _list_workspaces(self) -> list[dict]:
        assert self._http_client is not None
        response = await self._http_client.get(f"{self.gateway}/v1/workspaces")
        response.raise_for_status()
        workspaces = response.json()
        self._workspace_suggestions = [
            {"workspace_id": item["workspace_id"], "name": item["name"]}
            for item in workspaces
        ]
        return workspaces

    async def _list_threads(self, workspace_id: str) -> list[dict]:
        assert self._http_client is not None
        response = await self._http_client.get(
            f"{self.gateway}/v1/workspaces/{workspace_id}/threads"
        )
        response.raise_for_status()
        return response.json()

    async def _get_workspace_detail(self, workspace_id: str) -> dict:
        assert self._http_client is not None
        response = await self._http_client.get(f"{self.gateway}/v1/workspaces/{workspace_id}")
        response.raise_for_status()
        detail = response.json()
        self._role_suggestions = [
            role_definition["name"]
            for role_definition in detail.get("role_definitions", [])
        ]
        return detail

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            yield Static("", id="context-info")
            yield RichLog(id="timeline", markup=True, highlight=False, wrap=True)
            yield Static(" Connecting...", id="status-bar")
            yield Static(" Commands: /workspaces, /workspace create <name>", id="suggestion-bar")
            with Horizontal(id="composer"):
                yield Input(
                    placeholder="Type a message to the thread... (Enter to send)",
                    id="msg-input",
                    suggester=WorkspaceCommandSuggester(self),
                )
        yield Footer()

    def on_mount(self) -> None:
        self._update_context_info()
        self._initialize()

    @work(thread=False)
    async def _initialize(self) -> None:
        self._http_client = httpx.AsyncClient(
            headers=self._auth_headers,
            timeout=10,
            trust_env=False,
        )
        logger.debug("TUI initialize gateway=%s participant_id=%s", self.gateway, self.state.participant_id)
        try:
            await self._ensure_context()
            await self._load_timeline()
            self._connect_ws()
        except Exception as exc:
            logger.exception("TUI startup failed")
            self._write_system(f"Startup failed: {exc}", style="red")
            self._update_status("err", "Startup failed")

    async def _ensure_context(self) -> None:
        assert self._http_client is not None

        workspace_id = self.state.workspace_id
        if workspace_id:
            logger.debug("TUI checking workspace workspace_id=%s", workspace_id)
            response = await self._http_client.get(f"{self.gateway}/v1/workspaces/{workspace_id}")
            if response.status_code != 200:
                logger.debug(
                    "TUI cached workspace invalid workspace_id=%s status=%s body=%s",
                    workspace_id,
                    response.status_code,
                    response.text,
                )
                self.state.workspace_id = None

        if self.state.workspace_id is None:
            logger.debug("TUI creating workspace name=%r", self.workspace_name)
            response = await self._http_client.post(
                f"{self.gateway}/v1/workspaces",
                json={
                    "name": self.workspace_name,
                    "description": "Workspace created by the Open Talon TUI",
                    "actor": self.actor_payload,
                },
            )
            response.raise_for_status()
            self.state.workspace_id = response.json()["workspace"]["workspace_id"]
            logger.debug("TUI created workspace workspace_id=%s", self.state.workspace_id)
            save_state(self.state)

        thread_id = self.state.thread_id
        if thread_id:
            logger.debug("TUI checking thread thread_id=%s", thread_id)
            response = await self._http_client.get(f"{self.gateway}/v1/threads/{thread_id}")
            if response.status_code != 200:
                logger.debug(
                    "TUI cached thread invalid thread_id=%s status=%s body=%s",
                    thread_id,
                    response.status_code,
                    response.text,
                )
                self.state.thread_id = None
                self.state.last_sequence = 0

        if self.state.thread_id is None:
            await self._create_thread(self.default_thread_title)

        save_state(self.state)
        self._update_context_info()

    async def _create_thread(self, title: str) -> None:
        assert self._http_client is not None
        assert self.state.workspace_id is not None
        logger.debug(
            "TUI creating thread workspace_id=%s title=%r participant_id=%s",
            self.state.workspace_id,
            title,
            self.state.participant_id,
        )
        response = await self._http_client.post(
            f"{self.gateway}/v1/workspaces/{self.state.workspace_id}/threads",
            json={"title": title, "actor": self.actor_payload},
        )
        response.raise_for_status()
        body = response.json()
        self.state.thread_id = body["thread"]["thread_id"]
        self.state.last_sequence = 0
        self._seen_message_ids.clear()
        logger.debug("TUI created thread thread_id=%s", self.state.thread_id)
        save_state(self.state)
        self._update_context_info()

    async def _delete_workspace(self, workspace_id: str) -> None:
        assert self._http_client is not None
        logger.debug(
            "TUI deleting workspace workspace_id=%s participant_id=%s",
            workspace_id,
            self.state.participant_id,
        )
        response = await self._http_client.request(
            "DELETE",
            f"{self.gateway}/v1/workspaces/{workspace_id}",
            json={"actor": self.actor_payload},
        )
        response.raise_for_status()

    async def _switch_workspace(self, workspace_id: str) -> None:
        logger.debug("TUI switching workspace workspace_id=%s", workspace_id)
        if self._ws:
            await self._ws.close()
        self.state.workspace_id = workspace_id
        self.state.thread_id = None
        self.state.last_sequence = 0
        self._seen_message_ids.clear()
        threads = await self._list_threads(workspace_id)
        if threads:
            self.state.thread_id = threads[0]["thread_id"]
            logger.debug(
                "TUI switched to existing thread thread_id=%s workspace_id=%s",
                self.state.thread_id,
                workspace_id,
            )
        else:
            await self._create_thread(self.default_thread_title)
        save_state(self.state)
        self._update_context_info()
        await self._load_timeline()
        self._connect_ws()

    async def _create_workspace_and_switch(self, name: str) -> None:
        assert self._http_client is not None
        response = await self._http_client.post(
            f"{self.gateway}/v1/workspaces",
            json={
                "name": name,
                "description": "Workspace created by the Open Talon TUI",
                "actor": self.actor_payload,
            },
        )
        response.raise_for_status()
        workspace_id = response.json()["workspace"]["workspace_id"]
        await self._switch_workspace(workspace_id)
        self._write_system(f"workspace created: {name} ({workspace_id[:8]})")

    async def _assume_role(
        self,
        *,
        role: str,
        description: str | None,
        capabilities: list[str],
    ) -> dict:
        assert self._http_client is not None
        assert self.state.workspace_id is not None
        response = await self._http_client.patch(
            f"{self.gateway}/v1/workspaces/{self.state.workspace_id}/participants/{self.state.participant_id}/role",
            json={
                "actor": self.actor_payload,
                "role": role,
                "description": description,
                "capabilities": capabilities,
            },
        )
        response.raise_for_status()
        return response.json()

    async def _create_role_definition(
        self,
        *,
        name: str,
        definition: str,
    ) -> dict:
        assert self._http_client is not None
        assert self.state.workspace_id is not None
        response = await self._http_client.put(
            f"{self.gateway}/v1/workspaces/{self.state.workspace_id}/roles/{name}",
            json={
                "actor": self.actor_payload,
                "name": name,
                "definition": definition,
            },
        )
        response.raise_for_status()
        return response.json()

    async def _handle_workspace_command(self, command: str) -> None:
        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._write_system(
                "workspace commands: /workspace list|create <name>|switch <id|name>|delete <id|name|current>",
                style="yellow",
            )
            return

        action = parts[1].lower()
        target = parts[2].strip() if len(parts) > 2 else ""

        if action == "list":
            workspaces = await self._list_workspaces()
            if not workspaces:
                self._write_system("no workspaces found", style="yellow")
                return
            self._write_system("workspaces:", style="dim")
            for workspace in workspaces:
                marker = "*" if workspace["workspace_id"] == self.state.workspace_id else "-"
                self._write_system(
                    f"{marker} {workspace['name']} ({workspace['workspace_id'][:8]})",
                    style="dim",
                )
            return

        if action == "create":
            if not target:
                self._write_system("usage: /workspace create <name>", style="yellow")
                return
            await self._create_workspace_and_switch(target)
            return

        workspaces = await self._list_workspaces()
        workspace = self._resolve_workspace_target(workspaces, target)
        if workspace is None:
            self._write_system(f"workspace not found: {target or 'current'}", style="red")
            return

        if action == "switch":
            await self._switch_workspace(workspace["workspace_id"])
            self._write_system(
                f"switched workspace: {workspace['name']} ({workspace['workspace_id'][:8]})"
            )
            return

        if action == "delete":
            workspace_id = workspace["workspace_id"]
            was_current = workspace_id == self.state.workspace_id
            await self._delete_workspace(workspace_id)
            self._write_system(
                f"deleted workspace: {workspace['name']} ({workspace_id[:8]})"
            )
            if was_current:
                remaining = [
                    item for item in workspaces if item["workspace_id"] != workspace_id
                ]
                if remaining:
                    await self._switch_workspace(remaining[0]["workspace_id"])
                else:
                    self.state.workspace_id = None
                    self.state.thread_id = None
                    self.state.last_sequence = 0
                    self._seen_message_ids.clear()
                    await self._ensure_context()
                    await self._load_timeline()
                    self._connect_ws()
            return

        self._write_system(f"unknown workspace action: {action}", style="yellow")

    async def _handle_role_command(self, command: str) -> None:
        if not self.state.workspace_id:
            self._write_system("join or create a workspace first", style="red")
            return

        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2 or parts[1] == "show":
            detail = await self._get_workspace_detail(self.state.workspace_id)
            participants = detail.get("participants", [])
            role_definitions = detail.get("role_definitions", [])
            current = next(
                (
                    participant
                    for participant in participants
                    if participant["participant_id"] == self.state.participant_id
                ),
                None,
            )
            if current is None:
                self._write_system("participant profile not found", style="red")
                return
            roles = ", ".join(current.get("roles", [])) or "unassigned"
            capabilities = ", ".join(current.get("capabilities", [])) or "none"
            description = current.get("description") or "no description"
            self._write_system("My Role")
            self._write_system(f"role: {roles}", style="cyan")
            self._write_system(f"description: {description}", style="dim")
            self._write_system(f"capabilities: {capabilities}", style="dim")
            if role_definitions:
                self._write_system("Workspace Roles")
                for role_definition in role_definitions:
                    self._write_system(
                        f"{role_definition['name']}",
                        style="magenta",
                    )
                    self._write_system(
                        f"  {role_definition['definition']}",
                        style="dim",
                    )
            return

        if parts[1] == "create":
            if len(parts) < 3 or "::" not in parts[2]:
                self._write_system(
                    "usage: /role create <name> :: <definition>",
                    style="yellow",
                )
                return
            name, definition = [segment.strip() for segment in parts[2].split("::", 1)]
            if not name or not definition:
                self._write_system(
                    "usage: /role create <name> :: <definition>",
                    style="yellow",
                )
                return
            role_definition = await self._create_role_definition(
                name=name,
                definition=definition,
            )
            self._write_system(
                f"role definition saved: {role_definition['name']}",
            )
            self._write_system(role_definition["definition"], style="dim")
            return

        if parts[1] != "assume" or len(parts) < 3:
            self._write_system(
                "role commands: /role show | /role create <name> :: <definition> | /role assume <role> [:: <description> :: <cap1, cap2>]",
                style="yellow",
            )
            return

        segments = [segment.strip() for segment in parts[2].split("::")]
        role = segments[0]
        description = None
        capabilities = []
        if len(segments) >= 2:
            description = segments[1] or None
        if len(segments) > 2 and segments[2]:
            capabilities = [item.strip() for item in segments[2].split(",") if item.strip()]
        if not role:
            self._write_system(
                "usage: /role assume <role> [:: <description> :: <cap1, cap2>]",
                style="yellow",
            )
            return
        profile = await self._assume_role(
            role=role,
            description=description,
            capabilities=capabilities,
        )
        self._write_system(f"role assumed: {profile['roles'][0]}")
        self._write_system(f"capabilities: {', '.join(profile['capabilities']) or 'none'}", style='dim')

    def _resolve_workspace_target(self, workspaces: list[dict], target: str) -> dict | None:
        normalized = target.strip()
        if not normalized or normalized == "current":
            for workspace in workspaces:
                if workspace["workspace_id"] == self.state.workspace_id:
                    return workspace
            return None

        for workspace in workspaces:
            if workspace["workspace_id"] == normalized:
                return workspace
        for workspace in workspaces:
            if workspace["workspace_id"].startswith(normalized):
                return workspace
        lowered = normalized.lower()
        for workspace in workspaces:
            if workspace["name"].lower() == lowered:
                return workspace
        return None

    def _suggestions_for_text(self, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return " Commands: /workspaces, /workspace create <name>, /workspace switch <id|name>"

        if stripped.startswith("/"):
            matches = [
                command for command in self._slash_commands if command.startswith(stripped)
            ]
            if matches:
                return " Suggestions: " + " | ".join(matches[:3])
            return " Slash commands: /workspaces | /workspace list | /workspace create <name>"

        lowered = stripped.lower()
        if "workspace" in lowered:
            return " Tip: use /workspaces or /workspace switch <id|name>"
        if "role" in lowered:
            return " Tip: /role show | /role create <name> :: <definition> | /role assume <role>"
        if lowered in {"list", "show", "where"}:
            return " Tip: /workspaces lists available workspaces"
        if lowered.startswith("switch"):
            return " Tip: /workspace switch <id|name>"
        if lowered.startswith("create"):
            return " Tip: /workspace create <name>"
        if lowered.startswith("delete") or lowered.startswith("remove"):
            return " Tip: /workspace delete <id|name|current>"
        return " Enter sends a message. Use /workspace or /role commands for collaboration context."

    async def _load_timeline(self) -> None:
        assert self._http_client is not None
        assert self.state.thread_id is not None

        response = await self._http_client.get(
            f"{self.gateway}/v1/threads/{self.state.thread_id}/timeline"
        )
        response.raise_for_status()
        timeline = response.json()
        logger.debug(
            "TUI loaded timeline thread_id=%s message_count=%s",
            self.state.thread_id,
            len(timeline.get("messages", [])),
        )
        log = self.query_one("#timeline", RichLog)
        log.clear()
        for message in timeline.get("messages", []):
            self._render_message(message)
            self.state.last_sequence = max(
                self.state.last_sequence, message.get("sequence", 0)
            )
        save_state(self.state)
        if timeline.get("messages"):
            self._write_system("history loaded", style="dim")

    @work(thread=False)
    async def _connect_ws(self) -> None:
        assert self.state.thread_id is not None
        ws_base = self.gateway.replace("http://", "ws://").replace("https://", "wss://")
        query = urlencode(
            {
                "participant_id": self.state.participant_id,
                "display_name": self.state.display_name,
                "participant_type": self.state.participant_type,
                "after_sequence": self.state.last_sequence,
            }
        )
        url = f"{ws_base}/v1/threads/{self.state.thread_id}/ws?{query}"
        extra_headers = list(self._auth_headers.items())
        logger.debug(
            "TUI opening websocket thread_id=%s after_sequence=%s url=%s",
            self.state.thread_id,
            self.state.last_sequence,
            url,
        )

        while True:
            try:
                async with websockets.connect(url, additional_headers=extra_headers) as ws:
                    self._ws = ws
                    self.connected = True
                    self._update_status("ok", "Connected")
                    self._write_system("connected", style="dim")
                    async for raw in ws:
                        logger.debug("TUI received websocket frame bytes=%s", len(raw))
                        event = json.loads(raw)
                        self._handle_event(event)
            except websockets.exceptions.ConnectionClosed:
                logger.debug("TUI websocket closed")
                pass
            except Exception as exc:
                logger.exception("TUI websocket error")
                self._write_system(f"WS error: {exc}", style="red")
            self._ws = None
            self.connected = False
            self._update_status("wait", "Reconnecting...")
            await asyncio.sleep(3)

    def _handle_event(self, event: dict) -> None:
        logger.debug(
            "TUI handle event event_type=%s event_id=%s sequence=%s",
            event.get("event_type"),
            event.get("event_id"),
            event.get("sequence"),
        )
        event_id = event.get("event_id")
        if event_id and event_id in self._seen_message_ids:
            return

        sequence = event.get("sequence") or 0
        self.state.last_sequence = max(self.state.last_sequence, sequence)
        save_state(self.state)

        event_type = event.get("event_type")
        payload = event.get("payload", {})

        if event_type == "message.created":
            message_id = payload.get("message_id")
            if message_id and message_id in self._seen_message_ids:
                return
            self._render_message(payload)
            if message_id:
                self._seen_message_ids.add(message_id)
        elif event_type == "task.created":
            self._write_system("agent task created", style="yellow")
        elif event_type == "presence.updated":
            participant_id = payload.get("participant_id", "")
            if participant_id != self.state.participant_id or payload.get("status") == "offline":
                who = "you" if participant_id == self.state.participant_id else participant_id[:8]
                self._write_system(f"{who} is {payload.get('status', 'active')}", style="dim")
        else:
            self._write_system(event_type or "event received", style="dim")

    @staticmethod
    def _format_message_time(message: dict) -> str:
        raw_timestamp = message.get("created_at") or message.get("updated_at")
        if not raw_timestamp:
            return "--:--"
        try:
            normalized = raw_timestamp.replace("Z", "+00:00")
            timestamp = datetime.fromisoformat(normalized)
            return timestamp.astimezone().strftime("%H:%M")
        except Exception:
            return "--:--"

    def _render_message(self, message: dict) -> None:
        message_id = message.get("message_id")
        if message_id:
            self._seen_message_ids.add(message_id)
        actor = message.get("actor", {})
        actor_id = actor.get("id", "")
        prefix = "You" if actor_id == self.state.participant_id else f"Peer {actor_id[:8]}"
        colour = "cyan" if actor_id == self.state.participant_id else "magenta"
        content = message.get("content", "")
        time_mark = self._format_message_time(message)
        self.query_one("#timeline", RichLog).write(
            f"[dim]{time_mark}[/dim] [bold {colour}]{prefix}:[/bold {colour}] {content}"
        )

    def _write_system(self, content: str, *, style: str = "dim") -> None:
        self.query_one("#timeline", RichLog).write(f"[{style}]-- {content} --[/{style}]")

    def _update_status(self, state: str, label: str) -> None:
        icons = {"ok": "●", "err": "✖", "wait": "⟳"}
        colours = {"ok": "green", "err": "red", "wait": "yellow"}
        colour = colours.get(state, "white")
        try:
            self.query_one("#status-bar", Static).update(
                f" [{colour}]{icons.get(state, '?')}[/{colour}]  {label}"
            )
        except Exception:
            pass

    def _update_context_info(self) -> None:
        workspace = self.state.workspace_id[:8] if self.state.workspace_id else "pending"
        thread = self.state.thread_id[:8] if self.state.thread_id else "pending"
        self.query_one("#context-info", Static).update(
            " Workspace: [bold]"
            f"{workspace}[/bold]  |  Thread: [bold]{thread}[/bold]  |  "
            f"Participant: [bold]{self.state.display_name}[/bold]"
        )

    @on(Input.Submitted, "#msg-input")
    async def on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        if (
            text == "/workspaces"
            or text.startswith("/workspace ")
            or text == "/workspace"
            or text.startswith("/ws ")
        ):
            if text == "/workspaces":
                command = "/workspace list"
            elif text.startswith("/ws"):
                command = text.replace("/ws", "/workspace", 1)
            else:
                command = text
            try:
                await self._handle_workspace_command(command)
                self._update_status("ok", "Connected")
            except Exception as exc:
                logger.exception("TUI workspace command failed")
                self._write_system(f"workspace command failed: {exc}", style="red")
                self._update_status("err", "Workspace failed")
            return
        if text == "/role" or text.startswith("/role "):
            try:
                await self._handle_role_command(text)
                self._update_status("ok", "Connected")
            except Exception as exc:
                logger.exception("TUI role command failed")
                self._write_system(f"role command failed: {exc}", style="red")
                self._update_status("err", "Role failed")
            return
        if not self.state.thread_id:
            self._write_system("thread not ready yet", style="red")
            return

        self._update_status("wait", "Sending...")
        try:
            assert self._http_client is not None
            logger.debug(
                "TUI posting message thread_id=%s participant_id=%s content_len=%s",
                self.state.thread_id,
                self.state.participant_id,
                len(text),
            )
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
            logger.debug(
                "TUI message posted thread_id=%s status=%s",
                self.state.thread_id,
                response.status_code,
            )
            self._update_status("ok", "Connected")
        except Exception as exc:
            logger.exception("TUI send failed")
            self._write_system(f"send failed: {exc}", style="red")
            self._update_status("err", "Send failed")

    @on(Input.Changed, "#msg-input")
    def on_input_changed(self, event: Input.Changed) -> None:
        self.query_one("#suggestion-bar", Static).update(
            self._suggestions_for_text(event.value)
        )

    def action_new_thread(self) -> None:
        async def _reset_thread() -> None:
            try:
                title = f"{self.default_thread_title} {uuid4().hex[:6]}"
                await self._create_thread(title)
                await self._load_timeline()
                if self._ws:
                    await self._ws.close()
                self._connect_ws()
            except Exception as exc:
                self._write_system(f"new thread failed: {exc}", style="red")

        asyncio.create_task(_reset_thread())

    def action_clear(self) -> None:
        self.query_one("#timeline", RichLog).clear()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open Talon collaboration terminal UI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--gateway", default="http://127.0.0.1:8000", help="Gateway base URL")
    parser.add_argument("--api-key", default=None, help="X-API-Key value")
    parser.add_argument("--openbao-token", default=None, help="OpenBao Bearer token")
    parser.add_argument(
        "--display-name",
        default=os.getenv("USER", "operator"),
        help="Display name used for the local participant",
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
    parser.add_argument(
        "--participant-type",
        default="user",
        choices=["user", "agent"],
        help="Participant type for the local TUI client",
    )
    args = parser.parse_args()

    app = CollaborationApp(
        gateway=args.gateway,
        api_key=args.api_key,
        openbao_token=args.openbao_token,
        display_name=args.display_name,
        workspace_name=args.workspace_name,
        thread_title=args.thread_title,
        participant_type=args.participant_type,
    )
    app.run()


if __name__ == "__main__":
    main()
