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
import re
import shlex
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
import websockets
import websockets.exceptions
from open_talon_contracts.agent_contracts import build_default_interaction_contract
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.suggester import SuggestFromList, Suggester
from textual.widgets import Footer, Header, Input, RichLog, Static

_CFG_DIR = Path.home() / ".open-talon"
_PROFILES_DIR = _CFG_DIR / "profiles"
_LOG_FILE = _CFG_DIR / "tui.log"
_EMPTY_UUID = "00000000-0000-0000-0000-000000000000"
_STATE_VERSION = 2
_TOKEN_STATE_VERSION = 2
_DEFAULT_OIDC_ISSUER_URL = "http://127.0.0.1:8081/realms/open-talon"
_DEFAULT_OIDC_CLIENT_ID = "open-talon-tui"
_URL_PATTERN = re.compile(r"https?://[^\s<>()]+")
_LLM_PROVIDER_COMMAND_HELP = (
    "llm-provider commands: /llm-provider list | /llm-provider show <id|engine_id|name> "
    "| /llm-provider create key=value ... | /llm-provider update <id|engine_id|name> field=value ... "
    "| /llm-provider enable <id|engine_id|name> | /llm-provider disable <id|engine_id|name> "
    "| /llm-provider delete <id|engine_id|name>"
)
_LLM_PROVIDER_CREATE_USAGE = (
    "usage: /llm-provider create engine_id=<id> display_name=\"Provider Name\" provider=<provider> "
    "description=\"...\" [endpoint_kind=remote] [url=https://...] [default_model=model] "
    "[capabilities=text,reasoning] [locality=cloud] [priority=100] [enabled=true] "
    "[secret_config='{\"env\":{\"name\":\"OPENAI_API_KEY\"}}'] [metadata='{\"team\":\"platform\"}']"
)
_LLM_PROVIDER_UPDATE_USAGE = (
    "usage: /llm-provider update <id|engine_id|name> field=value [field=value ...]"
)

_CFG_DIR.mkdir(parents=True, exist_ok=True)
_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
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


def _parse_command_assignments(raw: str) -> dict[str, str]:
    try:
        tokens = shlex.split(raw)
    except ValueError as exc:
        raise ValueError(f"unable to parse arguments: {exc}") from exc
    assignments: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            raise ValueError(f"expected key=value argument, got: {token}")
        key, value = token.split("=", 1)
        normalized_key = key.strip().lower()
        if not normalized_key:
            raise ValueError(f"expected key=value argument, got: {token}")
        assignments[normalized_key] = value
    return assignments


def _parse_bool_argument(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"expected boolean value, got: {value}")


def _parse_json_object_argument(value: str, *, field_name: str) -> dict:
    if not value.strip():
        return {}
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON: {exc.msg}") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must decode to a JSON object")
    return decoded


def _parse_optional_string_argument(value: str) -> str | None:
    normalized = value.strip()
    if normalized.lower() in {"", "null", "none"}:
        return None
    return normalized


def _parse_capabilities_argument(value: str) -> list[str]:
    normalized = value.strip()
    if normalized.lower() in {"", "none", "null"}:
        return []
    return [item.strip() for item in normalized.split(",") if item.strip()]


def _build_llm_provider_payload(
    assignments: dict[str, str],
    *,
    partial: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    normalized_assignments = dict(assignments)
    if "model" in normalized_assignments and "default_model" not in normalized_assignments:
        normalized_assignments["default_model"] = normalized_assignments["model"]
    normalized_assignments.pop("model", None)
    for key, value in normalized_assignments.items():
        if key in {
            "engine_id",
            "display_name",
            "provider",
            "description",
            "endpoint_kind",
            "locality",
        }:
            payload[key] = value.strip()
        elif key in {"url", "default_model"}:
            payload[key] = _parse_optional_string_argument(value)
        elif key == "capabilities":
            payload[key] = _parse_capabilities_argument(value)
        elif key == "priority":
            try:
                payload[key] = int(value)
            except ValueError as exc:
                raise ValueError(f"priority must be an integer, got: {value}") from exc
        elif key == "enabled":
            payload[key] = _parse_bool_argument(value)
        elif key in {"secret_config", "metadata"}:
            payload[key] = _parse_json_object_argument(value, field_name=key)
        else:
            raise ValueError(f"unsupported llm-provider field: {key}")
    if partial:
        return payload
    required_fields = ("engine_id", "display_name", "provider", "description")
    missing_fields = [field for field in required_fields if not payload.get(field)]
    if missing_fields:
        raise ValueError(
            "missing required fields: " + ", ".join(missing_fields)
        )
    payload.setdefault("endpoint_kind", "remote")
    payload.setdefault("url", None)
    payload.setdefault("default_model", None)
    payload.setdefault("capabilities", [])
    payload.setdefault("locality", "cloud")
    payload.setdefault("priority", 100)
    payload.setdefault("enabled", True)
    payload.setdefault("secret_config", {})
    payload.setdefault("metadata", {})
    return payload


def _resolve_llm_provider_target(providers: list[dict], target: str) -> dict | None:
    normalized = target.strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    for provider in providers:
        provider_id = provider.get("provider_id", "")
        if provider_id == normalized:
            return provider
    for provider in providers:
        provider_id = provider.get("provider_id", "")
        if isinstance(provider_id, str) and provider_id.startswith(normalized):
            return provider
    for provider in providers:
        engine_id = provider.get("engine_id", "")
        if isinstance(engine_id, str) and engine_id.lower() == lowered:
            return provider
    for provider in providers:
        display_name = provider.get("display_name", "")
        if isinstance(display_name, str) and display_name.lower() == lowered:
            return provider
    return None


@dataclass
class ClientState:
    participant_id: str | None
    user_id: str | None
    display_name: str
    participant_type: str
    workspace_id: str | None = None
    thread_id: str | None = None
    last_sequence: int = 0
    version: int = _STATE_VERSION


@dataclass
class TokenState:
    access_token: str
    refresh_token: str | None
    expires_at: str | None
    issuer: str
    client_id: str
    version: int = _TOKEN_STATE_VERSION


def _profile_dir(profile: str) -> Path:
    return _PROFILES_DIR / profile


def _profile_state_file(profile: str) -> Path:
    return _profile_dir(profile) / "state.json"


def _profile_tokens_file(profile: str) -> Path:
    return _profile_dir(profile) / "tokens.json"


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _write_private_json(path: Path, payload: dict) -> None:
    _ensure_private_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2))
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _cleanup_profile_dir(profile: str) -> None:
    profile_dir = _profile_dir(profile)
    try:
        if any(profile_dir.iterdir()):
            return
        profile_dir.rmdir()
    except OSError:
        pass


def list_profiles() -> list[str]:
    profiles: list[str] = []
    for item in sorted(_PROFILES_DIR.iterdir()):
        if not item.is_dir():
            continue
        profile = item.name
        state_file = _profile_state_file(profile)
        tokens_file = _profile_tokens_file(profile)
        if state_file.exists():
            try:
                state_data = json.loads(state_file.read_text())
                if state_data.get("version") != _STATE_VERSION:
                    state_file.unlink(missing_ok=True)
            except Exception:
                state_file.unlink(missing_ok=True)
        if tokens_file.exists():
            try:
                token_data = json.loads(tokens_file.read_text())
                if token_data.get("version") != _TOKEN_STATE_VERSION:
                    tokens_file.unlink(missing_ok=True)
            except Exception:
                tokens_file.unlink(missing_ok=True)
        _cleanup_profile_dir(profile)
        if item.exists() and (state_file.exists() or tokens_file.exists()):
            profiles.append(profile)
    return profiles


def resolve_startup_profile(
    explicit_profile: str | None,
    *,
    oidc_enabled: bool,
    prompt=input,
) -> str:
    if explicit_profile is not None:
        return explicit_profile

    profiles = list_profiles()
    if oidc_enabled:
        print("Select a TUI profile for this Keycloak account:")
        if profiles:
            for index, existing in enumerate(profiles, start=1):
                print(f"  {index}. {existing}")
            choice = prompt("Profile number or new name: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(profiles):
                return profiles[int(choice) - 1]
            if choice:
                return choice
        else:
            choice = prompt("Create a local profile name: ").strip()
            if choice:
                return choice
        raise SystemExit("A profile is required for Keycloak login. Re-run with --profile <name>.")

    if len(profiles) == 1:
        return profiles[0]
    if len(profiles) > 1:
        print("Select a TUI profile:")
        for index, existing in enumerate(profiles, start=1):
            print(f"  {index}. {existing}")
        choice = prompt("Profile number or new name: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(profiles):
            return profiles[int(choice) - 1]
        if choice:
            return choice
        raise SystemExit("A profile is required. Re-run with --profile <name>.")
    choice = prompt("Create a local profile name: ").strip()
    if choice:
        return choice
    raise SystemExit("A profile is required. Re-run with --profile <name>.")


def load_state(profile: str, display_name: str, participant_type: str) -> ClientState:
    state_file = _profile_state_file(profile)
    try:
        data = json.loads(state_file.read_text())
        if data.get("version") != _STATE_VERSION:
            state_file.unlink(missing_ok=True)
            _cleanup_profile_dir(profile)
            raise ValueError("legacy state version")
        return ClientState(
            participant_id=data.get("participant_id"),
            user_id=data.get("user_id"),
            display_name=data.get("display_name", display_name),
            participant_type=data.get("participant_type", participant_type),
            workspace_id=data.get("workspace_id"),
            thread_id=data.get("thread_id"),
            last_sequence=data.get("last_sequence", 0),
            version=data.get("version", _STATE_VERSION),
        )
    except Exception:
        state = ClientState(
            participant_id=None,
            user_id=None,
            display_name=display_name,
            participant_type=participant_type,
        )
        save_state(profile, state)
        return state


def save_state(profile: str, state: ClientState) -> None:
    _write_private_json(_profile_state_file(profile), asdict(state))


def reset_profile_session_state(
    profile: str,
    *,
    display_name: str,
    participant_type: str,
) -> ClientState:
    state = ClientState(
        participant_id=None,
        user_id=None,
        display_name=display_name,
        participant_type=participant_type,
        workspace_id=None,
        thread_id=None,
        last_sequence=0,
    )
    save_state(profile, state)
    return state


def load_tokens(profile: str) -> TokenState | None:
    token_file = _profile_tokens_file(profile)
    try:
        data = json.loads(token_file.read_text())
        if data.get("version") != _TOKEN_STATE_VERSION:
            token_file.unlink(missing_ok=True)
            return None
        return TokenState(**data)
    except Exception:
        return None


def save_tokens(profile: str, tokens: TokenState | None) -> None:
    token_file = _profile_tokens_file(profile)
    if tokens is None:
        token_file.unlink(missing_ok=True)
        _cleanup_profile_dir(profile)
        return
    _write_private_json(token_file, asdict(tokens))


async def discover_oidc(issuer_url: str) -> dict:
    normalized_issuer = issuer_url.rstrip("/")
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        response = await client.get(
            f"{normalized_issuer}/.well-known/openid-configuration"
        )
        response.raise_for_status()
        return response.json()


async def run_device_login(
    *,
    issuer_url: str,
    client_id: str,
    write_line,
) -> TokenState:
    discovery = await discover_oidc(issuer_url)
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        response = await client.post(
            discovery["device_authorization_endpoint"],
            data={
                "client_id": client_id,
                "scope": "openid profile email",
            },
        )
        response.raise_for_status()
        body = response.json()
        write_line(
            body.get("verification_uri_complete") or body.get("verification_uri")
        )
        write_line(f"user code: {body['user_code']}")
        interval = int(body.get("interval", 5))
        deadline = datetime.now(timezone.utc) + timedelta(seconds=body.get("expires_in", 600))
        while datetime.now(timezone.utc) < deadline:
            await asyncio.sleep(interval)
            token_response = await client.post(
                discovery["token_endpoint"],
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id,
                    "device_code": body["device_code"],
                },
            )
            if token_response.status_code == 200:
                token_body = token_response.json()
                expires_at = datetime.now(timezone.utc) + timedelta(
                    seconds=token_body.get("expires_in", 300)
                )
                return TokenState(
                    access_token=token_body["access_token"],
                    refresh_token=token_body.get("refresh_token"),
                    expires_at=expires_at.isoformat(),
                    issuer=issuer_url.rstrip("/"),
                    client_id=client_id,
                )
            error = token_response.json().get("error")
            if error in {"authorization_pending", "slow_down"}:
                if error == "slow_down":
                    interval += 1
                continue
            raise RuntimeError(f"OIDC device login failed: {error}")
    raise RuntimeError("OIDC device login timed out")


async def fetch_current_user(
    *,
    gateway: str,
    access_token: str,
) -> dict:
    async with httpx.AsyncClient(
        timeout=10,
        trust_env=False,
        headers={"Authorization": f"Bearer {access_token}"},
    ) as client:
        response = await client.get(f"{gateway.rstrip('/')}/v1/me")
        response.raise_for_status()
        return response.json()


async def run_auth_login(
    *,
    gateway: str,
    profile: str,
    oidc_issuer_url: str,
    oidc_client_id: str,
    display_name: str,
    write_line=print,
) -> dict:
    tokens = await run_device_login(
        issuer_url=oidc_issuer_url,
        client_id=oidc_client_id,
        write_line=write_line,
    )
    save_tokens(profile, tokens)
    current_user = await fetch_current_user(
        gateway=gateway,
        access_token=tokens.access_token,
    )
    state = load_state(profile, display_name, "user")
    state.user_id = current_user["user_id"]
    state.display_name = current_user["display_name"]
    state.participant_type = "user"
    save_state(profile, state)
    return current_user


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
        workspace_targets = self.app.workspace_suggestion_targets
        if stripped.startswith("/workspace "):
            for prefix in ("/workspace use ", "/workspace delete "):
                if stripped.startswith(prefix):
                    typed_target = stripped[len(prefix) :].strip().casefold()
                    if not typed_target:
                        return prefix + (workspace_targets[0] if workspace_targets else "")
                    for target in workspace_targets:
                        if target.casefold().startswith(typed_target):
                            return prefix + target
        if stripped.startswith("/role "):
            role_targets = self.app.role_suggestion_targets
            for prefix in ("/role use ", "/role create "):
                if stripped.startswith(prefix):
                    typed_target = stripped[len(prefix) :].strip().casefold()
                    if not typed_target:
                        return prefix + (role_targets[0] if role_targets else "")
                    for target in role_targets:
                        if target.casefold().startswith(typed_target):
                            return prefix + target
        if stripped.startswith("/thread "):
            thread_targets = self.app.thread_suggestion_targets
            for prefix in ("/thread use ",):
                if stripped.startswith(prefix):
                    typed_target = stripped[len(prefix) :].strip().casefold()
                    if not typed_target:
                        return prefix + (thread_targets[0] if thread_targets else "")
                    for target in thread_targets:
                        if target.casefold().startswith(typed_target):
                            return prefix + target
        if stripped.startswith("/participant "):
            participant_targets = self.app.participant_suggestion_targets
            for prefix in ("/participant show ", "/participant remove "):
                if stripped.startswith(prefix):
                    typed_target = stripped[len(prefix) :].strip().casefold()
                    if not typed_target:
                        return prefix + (
                            participant_targets[0] if participant_targets else ""
                        )
                    for target in participant_targets:
                        if target.casefold().startswith(typed_target):
                            return prefix + target
        if stripped.startswith("/tool "):
            tool_targets = self.app.tool_suggestion_targets
            for prefix in ("/tool show ", "/tool attach ", "/tool detach "):
                if stripped.startswith(prefix):
                    typed_target = stripped[len(prefix) :].strip().casefold()
                    if not typed_target:
                        return prefix + (tool_targets[0] if tool_targets else "")
                    for target in tool_targets:
                        if target.casefold().startswith(typed_target):
                            return prefix + target
        if stripped.startswith("/llm-provider "):
            provider_targets = self.app.llm_provider_suggestion_targets
            for prefix in (
                "/llm-provider show ",
                "/llm-provider update ",
                "/llm-provider delete ",
                "/llm-provider enable ",
                "/llm-provider disable ",
            ):
                if stripped.startswith(prefix):
                    typed_target = stripped[len(prefix) :].strip().casefold()
                    if not typed_target:
                        return prefix + (provider_targets[0] if provider_targets else "")
                    for target in provider_targets:
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
        Binding("ctrl+n", "new_thread", "New Thread", priority=True),
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+l", "clear", "Clear", priority=True),
    ]

    status: reactive[str] = reactive("Connecting...")
    connected: reactive[bool] = reactive(False)

    def __init__(
        self,
        *,
        gateway: str,
        profile: str,
        api_key: str | None,
        openbao_token: str | None,
        oidc_issuer_url: str | None,
        oidc_client_id: str | None,
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
        self.profile = profile
        self.api_key = api_key
        self.openbao_token = openbao_token
        self.oidc_issuer_url = oidc_issuer_url.rstrip("/") if oidc_issuer_url else None
        self.oidc_client_id = oidc_client_id
        if participant_type == "user" and not (self.oidc_issuer_url and self.oidc_client_id):
            raise RuntimeError("Human TUI users must authenticate with Keycloak OIDC.")
        if participant_type == "user" and (api_key or openbao_token):
            raise RuntimeError("Human TUI users cannot use API key or OpenBao auth; use Keycloak login.")
        self.workspace_name = workspace_name
        self.default_thread_title = thread_title
        self.state = load_state(profile, display_name, participant_type)
        self.tokens = load_tokens(profile)
        if participant_type == "user" and self.tokens is None:
            self.state = reset_profile_session_state(
                profile,
                display_name=display_name,
                participant_type=participant_type,
            )
        self.current_user: dict | None = None
        self._fallback_actor_id = str(uuid4())
        self._ws = None
        self._seen_message_ids: set[str] = set()
        self._http_client: httpx.AsyncClient | None = None
        self._slash_commands = [
            "/quit",
            "/clear",
            "/copy",
            "/links",
            "/open ",
            "/auth login",
            "/auth logout",
            "/account login",
            "/account whoami",
            "/account list",
            "/account switch ",
            "/account logout",
            "/agent create local ",
            "/tool attached",
            "/tool detach ",
            "/tool list",
            "/tool show ",
            "/tool attach ",
            "/llm-provider list",
            "/llm-provider show ",
            "/llm-provider create ",
            "/llm-provider update ",
            "/llm-provider enable ",
            "/llm-provider disable ",
            "/llm-provider delete ",
            "/workspace list",
            "/workspace show",
            "/workspace create ",
            "/workspace use ",
            "/workspace delete ",
            "/participant list",
            "/participant show ",
            "/participant remove ",
            "/thread create ",
            "/thread list",
            "/thread show",
            "/thread use ",
            "/role list",
            "/role create ",
            "/role show",
            "/role use ",
        ]
        self._workspace_suggestions: list[dict[str, str]] = []
        self._participant_suggestions: list[dict[str, str]] = []
        self._thread_suggestions: list[dict[str, str]] = []
        self._role_suggestions: list[str] = []
        self._tool_suggestions: list[dict[str, str]] = []
        self._llm_provider_suggestions: list[dict[str, str]] = []
        self._timeline_lines: list[str] = []
        self._detected_links: list[str] = []

    @property
    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        bearer_token = self.tokens.access_token if self.tokens is not None else self.openbao_token
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        return headers

    @property
    def actor_payload(self) -> dict[str, str | None]:
        participant_id = self.state.participant_id or self.state.user_id or self._fallback_actor_id
        return {
            "participant_id": participant_id,
            "participant_type": self.state.participant_type,
            "user_id": self.state.user_id,
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

    @property
    def thread_suggestion_targets(self) -> list[str]:
        targets: list[str] = []
        for thread in self._thread_suggestions:
            title = thread["title"]
            thread_id = thread["thread_id"]
            for candidate in (title, thread_id[:8], thread_id):
                if candidate not in targets:
                    targets.append(candidate)
        return targets

    @property
    def participant_suggestion_targets(self) -> list[str]:
        targets: list[str] = []
        for participant in self._participant_suggestions:
            display_name = participant["display_name"]
            participant_id = participant["participant_id"]
            for candidate in (display_name, participant_id[:8], participant_id):
                if candidate not in targets:
                    targets.append(candidate)
        return targets

    @property
    def tool_suggestion_targets(self) -> list[str]:
        targets: list[str] = []
        for tool in self._tool_suggestions:
            name = tool["name"]
            tool_id = tool["tool_id"]
            for candidate in (name, tool_id[:8], tool_id):
                if candidate not in targets:
                    targets.append(candidate)
        return targets

    @property
    def llm_provider_suggestion_targets(self) -> list[str]:
        targets: list[str] = []
        for provider in self._llm_provider_suggestions:
            display_name = provider["display_name"]
            engine_id = provider["engine_id"]
            provider_id = provider["provider_id"]
            for candidate in (display_name, engine_id, provider_id[:8], provider_id):
                if candidate not in targets:
                    targets.append(candidate)
        return targets

    @property
    def _oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer_url and self.oidc_client_id)

    def _sync_http_auth(self) -> None:
        if self._http_client is None:
            return
        self._http_client.headers.clear()
        self._http_client.headers.update(self._auth_headers)

    @property
    def _is_authenticated(self) -> bool:
        return self.tokens is not None and self.current_user is not None

    @staticmethod
    def _token_expiring_soon(tokens: TokenState | None, *, skew_seconds: int = 30) -> bool:
        if tokens is None or not tokens.expires_at:
            return False
        try:
            expires_at = datetime.fromisoformat(tokens.expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=skew_seconds)

    async def _discover_oidc(self) -> dict:
        if not self._oidc_enabled or self.oidc_issuer_url is None:
            raise RuntimeError("OIDC issuer URL and client ID must be configured")
        return await discover_oidc(self.oidc_issuer_url)

    async def _refresh_oidc_tokens(self) -> bool:
        if not self._oidc_enabled or self.tokens is None or not self.tokens.refresh_token:
            return False
        discovery = await self._discover_oidc()
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
            issuer=self.oidc_issuer_url or self.tokens.issuer,
            client_id=self.oidc_client_id or self.tokens.client_id,
        )
        save_tokens(self.profile, self.tokens)
        self._sync_http_auth()
        return True

    async def _device_login(self) -> None:
        if not self._oidc_enabled:
            raise RuntimeError("OIDC issuer URL and client ID must be configured")
        self.tokens = await run_device_login(
            issuer_url=self.oidc_issuer_url or "",
            client_id=self.oidc_client_id or "",
            write_line=lambda message: self._write_system(
                message,
                style="cyan" if message.startswith("http") else "yellow",
            ),
        )
        save_tokens(self.profile, self.tokens)
        self._sync_http_auth()

    async def _ensure_bearer_token(self) -> None:
        if self._token_expiring_soon(self.tokens):
            refreshed = await self._refresh_oidc_tokens()
            if not refreshed:
                self._write_system("token refresh failed; starting device login", style="yellow")
                await self._device_login()

    async def _load_current_user(self) -> None:
        if self._http_client is None or self.tokens is None:
            return
        response = await self._http_client.get(f"{self.gateway}/v1/me")
        response.raise_for_status()
        self.current_user = response.json()
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

    async def _switch_profile(self, profile: str) -> None:
        self.profile = profile
        self.state = load_state(profile, self.state.display_name, self.state.participant_type)
        self.tokens = load_tokens(profile)
        if self.tokens is None:
            self.state = reset_profile_session_state(
                profile,
                display_name=self.state.display_name,
                participant_type=self.state.participant_type,
            )
        self.current_user = None
        self._seen_message_ids.clear()
        self._sync_http_auth()

    def _require_authenticated_session(self) -> bool:
        if self._is_authenticated:
            return True
        self._write_system("sign in first with /auth login", style="yellow")
        self._update_status("wait", "Sign in required")
        return False

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
        threads = response.json()
        self._thread_suggestions = [
            {"thread_id": item["thread_id"], "title": item["title"]}
            for item in threads
        ]
        return threads

    async def _get_workspace_detail(self, workspace_id: str) -> dict:
        assert self._http_client is not None
        response = await self._http_client.get(f"{self.gateway}/v1/workspaces/{workspace_id}")
        response.raise_for_status()
        detail = response.json()
        self._set_current_participant(detail.get("participants", []))
        save_state(self.profile, self.state)
        self._role_suggestions = [
            role_definition["name"]
            for role_definition in detail.get("role_definitions", [])
        ]
        return detail

    async def _list_participants(self, workspace_id: str) -> list[dict]:
        assert self._http_client is not None
        response = await self._http_client.get(
            f"{self.gateway}/v1/workspaces/{workspace_id}/participants"
        )
        response.raise_for_status()
        participants = response.json()
        self._set_current_participant(participants)
        save_state(self.profile, self.state)
        self._participant_suggestions = [
            {
                "participant_id": item["participant_id"],
                "display_name": item["display_name"],
            }
            for item in participants
        ]
        return participants

    async def _delete_participant(self, workspace_id: str, participant_id: str) -> None:
        assert self._http_client is not None
        response = await self._http_client.request(
            "DELETE",
            f"{self.gateway}/v1/workspaces/{workspace_id}/participants/{participant_id}",
            json={"actor": self.actor_payload},
        )
        response.raise_for_status()

    async def _list_system_tools(self) -> list[dict]:
        assert self._http_client is not None
        response = await self._http_client.get(f"{self.gateway}/v1/tools")
        response.raise_for_status()
        tools = response.json()
        self._tool_suggestions = [
            {"tool_id": item["tool_id"], "name": item["name"]}
            for item in tools
        ]
        return tools

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

    async def _attach_workspace_tool(self, workspace_id: str, tool_id: str) -> dict:
        assert self._http_client is not None
        response = await self._http_client.put(
            f"{self.gateway}/v1/workspaces/{workspace_id}/tools/{tool_id}",
            json={
                "actor": self.actor_payload,
                "tool_id": tool_id,
                "enabled": True,
            },
        )
        response.raise_for_status()
        return response.json()

    async def _delete_workspace_tool(self, workspace_id: str, tool_id: str) -> None:
        assert self._http_client is not None
        response = await self._http_client.request(
            "DELETE",
            f"{self.gateway}/v1/workspaces/{workspace_id}/tools/{tool_id}",
            json={"actor": self.actor_payload},
        )
        response.raise_for_status()

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            yield Static("", id="context-info")
            yield RichLog(id="timeline", markup=False, highlight=False, wrap=True)
            yield Static(" Connecting...", id="status-bar")
            yield Static(" Commands: /workspace list, /participant list, /thread list", id="suggestion-bar")
            with Horizontal(id="composer"):
                yield Input(
                    placeholder="Type a message to the thread... (Enter to send)",
                    id="msg-input",
                    suggester=WorkspaceCommandSuggester(self),
                )
        yield Footer()

    def on_mount(self) -> None:
        self._update_context_info()
        self._focus_input_soon()
        self._initialize()

    @work(thread=False)
    async def _initialize(self) -> None:
        self._http_client = httpx.AsyncClient(
            headers=self._auth_headers,
            timeout=10,
            trust_env=False,
        )
        logger.debug(
            "TUI initialize gateway=%s profile=%s participant_id=%s",
            self.gateway,
            self.profile,
            self.state.participant_id,
        )
        try:
            await self._ensure_bearer_token()
            self._sync_http_auth()
            if self.tokens is not None:
                await self._load_current_user()
                await self._ensure_context()
                await self._load_timeline()
                self._connect_ws()
                self._update_status("ok", "Connected")
            else:
                self.current_user = None
                self._update_status("wait", "Signed out")
                self._write_system("sign in with /auth login", style="yellow")
                self._update_context_info()
        except Exception as exc:
            logger.exception("TUI startup failed")
            self._write_system(f"Startup failed: {exc}", style="red")
            self._update_status("err", "Startup failed")
        finally:
            self._focus_input_soon()

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
            else:
                self._set_current_participant(response.json().get("participants", []))

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
            body = response.json()
            self.state.workspace_id = body["workspace"]["workspace_id"]
            self._set_current_participant(body.get("participants", []))
            logger.debug("TUI created workspace workspace_id=%s", self.state.workspace_id)
            save_state(self.profile, self.state)

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

        save_state(self.profile, self.state)
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
        memberships = body.get("memberships", [])
        if memberships:
            self.state.participant_id = memberships[0]["participant_id"]
        self.state.last_sequence = 0
        self._seen_message_ids.clear()
        logger.debug("TUI created thread thread_id=%s", self.state.thread_id)
        save_state(self.profile, self.state)
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
        save_state(self.profile, self.state)
        self._update_context_info()
        await self._load_timeline()
        self._connect_ws()

    async def _switch_thread(self, thread_id: str) -> None:
        logger.debug("TUI switching thread thread_id=%s", thread_id)
        if self._ws:
            await self._ws.close()
        self.state.thread_id = thread_id
        self.state.last_sequence = 0
        self._seen_message_ids.clear()
        save_state(self.profile, self.state)
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
        body = response.json()
        workspace_id = body["workspace"]["workspace_id"]
        self._set_current_participant(body.get("participants", []))
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

    async def _create_system_agent(
        self,
        *,
        display_name: str,
        description: str,
        role: str,
        model: str,
        capabilities: list[str],
        system_prompt: str,
    ) -> dict:
        assert self._http_client is not None
        definition = {
            "display_name": display_name,
            "role": role,
            "description": description,
            "capabilities": capabilities,
            "runtime": {
                "kind": "ollama",
                "url": "http://127.0.0.1:11434/api/generate",
                "model": model,
            },
        }
        interaction_contract = build_default_interaction_contract(
            display_name=display_name,
            role=role,
            description=description,
            capabilities=capabilities,
        ).model_dump(mode="json")
        response = await self._http_client.post(
            f"{self.gateway}/v1/agents",
            json={
                "actor": self.actor_payload,
                "display_name": display_name,
                "description": description,
                "role": role,
                "capabilities": capabilities,
                "endpoint": {
                    "kind": "local",
                    "url": "http://127.0.0.1:11434/api/generate",
                    "model": model,
                },
                "system_prompt": system_prompt,
                "interaction_contract": interaction_contract,
                "definition": definition,
            },
        )
        response.raise_for_status()
        return response.json()

    async def _attach_system_agent(self, agent_id: str) -> dict:
        assert self._http_client is not None
        assert self.state.workspace_id is not None
        response = await self._http_client.post(
            f"{self.gateway}/v1/workspaces/{self.state.workspace_id}/agents",
            json={"actor": self.actor_payload, "agent_id": agent_id},
        )
        response.raise_for_status()
        return response.json()

    async def _handle_account_command(self, command: str) -> None:
        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._write_system(
                "account commands: /account login | /account whoami | /account list | /account switch <profile> | /account logout",
                style="yellow",
            )
            return

        action = parts[1].lower()
        if action == "login":
            await self._device_login()
            await self._load_current_user()
            await self._ensure_context()
            await self._load_timeline()
            if self._ws:
                await self._ws.close()
            self._connect_ws()
            self._update_context_info()
            self._write_system(f"signed in as {self.state.display_name}", style="green")
            return
        if action == "whoami":
            if self.current_user is None and self.tokens is not None:
                await self._load_current_user()
            if self.current_user is None:
                self._write_system(f"profile: {self.profile}", style="dim")
                self._write_system("not signed in", style="yellow")
                return
            self._write_system(f"profile: {self.profile}", style="dim")
            self._write_system(f"user: {self.current_user['display_name']}", style="cyan")
            self._write_system(f"user id: {self.current_user['user_id']}", style="dim")
            if self.current_user.get("email"):
                self._write_system(f"email: {self.current_user['email']}", style="dim")
            return
        if action == "list":
            self._write_system("profiles:", style="dim")
            for profile in list_profiles():
                marker = "*" if profile == self.profile else "-"
                self._write_system(f"{marker} {profile}", style="cyan" if marker == "*" else "dim")
            return
        if action == "switch":
            target = parts[2].strip() if len(parts) > 2 else ""
            if not target:
                self._write_system("usage: /account switch <profile>", style="yellow")
                return
            await self._switch_profile(target)
            if self._ws:
                await self._ws.close()
            await self._ensure_bearer_token()
            self._sync_http_auth()
            await self._load_current_user()
            await self._ensure_context()
            if self.state.thread_id:
                await self._load_timeline()
                self._connect_ws()
            self._update_context_info()
            self._write_system(f"switched profile: {target}", style="green")
            return
        if action == "logout":
            if self._ws:
                await self._ws.close()
            self.tokens = None
            self.current_user = None
            self.state = reset_profile_session_state(
                self.profile,
                display_name=self.state.display_name,
                participant_type=self.state.participant_type,
            )
            save_tokens(self.profile, None)
            self._sync_http_auth()
            self._update_context_info()
            self._write_system(f"signed out profile: {self.profile}", style="yellow")
            self._update_status("wait", "Signed out")
            return

        self._write_system(f"unknown account action: {action}", style="yellow")

    async def _handle_auth_command(self, command: str) -> None:
        parts = command.strip().split(maxsplit=1)
        if len(parts) < 2:
            self._write_system(
                "auth commands: /auth login | /auth logout",
                style="yellow",
            )
            return

        action = parts[1].strip().lower()
        if action == "login":
            await self._handle_account_command("/account login")
            return
        if action == "logout":
            await self._handle_account_command("/account logout")
            return

        self._write_system("auth commands: /auth login | /auth logout", style="yellow")

    async def _handle_agent_command(self, command: str) -> None:
        if not self.state.workspace_id:
            self._write_system("join or create a workspace first", style="red")
            return

        parts = command.strip().split(maxsplit=3)
        if len(parts) < 3 or parts[1] != "create" or parts[2] != "local":
            self._write_system(
                "agent commands: /agent create local <name> :: <role> :: <description> :: <model> [:: <cap1, cap2>] [:: <system prompt>]",
                style="yellow",
            )
            return
        if len(parts) < 4:
            self._write_system(
                "usage: /agent create local <name> :: <role> :: <description> :: <model> [:: <cap1, cap2>] [:: <system prompt>]",
                style="yellow",
            )
            return

        segments = [segment.strip() for segment in parts[3].split("::")]
        if len(segments) < 4:
            self._write_system(
                "usage: /agent create local <name> :: <role> :: <description> :: <model> [:: <cap1, cap2>] [:: <system prompt>]",
                style="yellow",
            )
            return
        display_name, role, description, model = segments[:4]
        capabilities: list[str] = []
        if len(segments) >= 5 and segments[4]:
            capabilities = [item.strip() for item in segments[4].split(",") if item.strip()]
        system_prompt = (
            segments[5]
            if len(segments) >= 6 and segments[5]
            else (
                f"You are {display_name}, a local workspace agent using the {model} model via Ollama. "
                f"Focus on {role} responsibilities and help with: {', '.join(capabilities) or 'general collaboration'}."
            )
        )
        if not all((display_name, role, description, model)):
            self._write_system(
                "usage: /agent create local <name> :: <role> :: <description> :: <model> [:: <cap1, cap2>] [:: <system prompt>]",
                style="yellow",
            )
            return

        system_agent = await self._create_system_agent(
            display_name=display_name,
            description=description,
            role=role,
            model=model,
            capabilities=capabilities,
            system_prompt=system_prompt,
        )
        participant = await self._attach_system_agent(system_agent["agent_id"])
        self._write_system(
            f"local agent created: {participant['display_name']} ({participant['participant_id'][:8]})",
            style="green",
        )
        self._write_system(f"system agent id: {system_agent['agent_id'][:8]}", style="dim")
        self._write_system(f"model: {model}", style="dim")
        self._write_system("endpoint: local Ollama", style="dim")

    async def _handle_workspace_command(self, command: str) -> None:
        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._write_system(
                "workspace commands: /workspace list | /workspace show | /workspace create <name> | /workspace use <id|name> | /workspace delete <id|name|current>",
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

        if action == "show":
            workspaces = await self._list_workspaces()
            current = self._resolve_workspace_target(workspaces, "current")
            if current is None:
                self._write_system("current workspace not found", style="red")
                return
            self._write_system("Current Workspace")
            self._write_system(f"name: {current['name']}", style="cyan")
            self._write_system(f"id: {current['workspace_id']}", style="dim")
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

        if action == "use":
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

    async def _handle_participant_command(self, command: str) -> None:
        if not self.state.workspace_id:
            self._write_system("join or create a workspace first", style="red")
            return

        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._write_system(
                "participant commands: /participant list | /participant show <id|name|current> | /participant remove <id|name>",
                style="yellow",
            )
            return

        participants = await self._list_participants(self.state.workspace_id)
        action = parts[1].lower()

        if action == "list":
            if not participants:
                self._write_system("no participants found", style="yellow")
                return
            self._write_system("Workspace Participants")
            for participant in participants:
                marker = "*" if participant["participant_id"] == self.state.participant_id else "-"
                roles = ", ".join(participant.get("roles", [])) or "unassigned"
                capabilities = ", ".join(participant.get("capabilities", [])) or "none"
                suffix = f" [{participant['participant_type']}]"
                self._write_system(
                    f"{marker} {participant['display_name']}{suffix} ({participant['participant_id'][:8]})",
                    style="cyan" if marker == "*" else "dim",
                )
                self._write_system(f"  role: {roles}", style="dim")
                self._write_system(f"  capabilities: {capabilities}", style="dim")
            return

        if action == "show":
            target = parts[2].strip() if len(parts) > 2 else "current"
            participant = self._resolve_participant_target(participants, target)
            if participant is None:
                self._write_system(
                    f"participant not found: {target or 'current'}",
                    style="red",
                )
                return
            roles = ", ".join(participant.get("roles", [])) or "unassigned"
            capabilities = ", ".join(participant.get("capabilities", [])) or "none"
            description = participant.get("description") or "no description"
            self._write_system("Participant")
            self._write_system(f"name: {participant['display_name']}", style="cyan")
            self._write_system(f"id: {participant['participant_id']}", style="dim")
            self._write_system(f"type: {participant['participant_type']}", style="dim")
            self._write_system(f"role: {roles}", style="dim")
            self._write_system(f"description: {description}", style="dim")
            self._write_system(f"capabilities: {capabilities}", style="dim")
            agent_config = participant.get("agent_config")
            if agent_config:
                endpoint = agent_config.get("endpoint", {})
                self._write_system("Agent Config", style="magenta")
                self._write_system(
                    f"  endpoint: {endpoint.get('kind', 'unknown')} {endpoint.get('url', '')}".rstrip(),
                    style="dim",
                )
                if endpoint.get("model"):
                    self._write_system(
                        f"  model: {endpoint['model']}",
                        style="dim",
                    )
                if agent_config.get("definition"):
                    self._write_system(
                        f"  definition keys: {', '.join(sorted(agent_config['definition'].keys()))}",
                        style="dim",
                    )
            return

        if action == "remove":
            target = parts[2].strip() if len(parts) > 2 else ""
            if not target:
                self._write_system("usage: /participant remove <id|name>", style="yellow")
                return
            participant = self._resolve_participant_target(participants, target)
            if participant is None:
                self._write_system(f"participant not found: {target}", style="red")
                return
            if participant["participant_id"] == self.state.participant_id:
                self._write_system(
                    "cannot remove the current TUI participant",
                    style="yellow",
                )
                return
            await self._delete_participant(
                self.state.workspace_id,
                participant["participant_id"],
            )
            self._participant_suggestions = [
                item
                for item in self._participant_suggestions
                if item["participant_id"] != participant["participant_id"]
            ]
            self._write_system(
                f"removed participant: {participant['display_name']} ({participant['participant_id'][:8]})",
                style="green",
            )
            return

        self._write_system(f"unknown participant action: {action}", style="yellow")

    async def _handle_tool_command(self, command: str) -> None:
        if not self.state.workspace_id:
            self._write_system("join or create a workspace first", style="red")
            return

        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._write_system(
                "tool commands: /tool list | /tool attached | /tool show <id|name> | /tool attach <id|name> | /tool detach <id|name>",
                style="yellow",
            )
            return

        action = parts[1].lower()

        if action == "list":
            tools = await self._list_system_tools()
            if not tools:
                self._write_system("no system tools found", style="yellow")
                return
            self._write_system("System Tools")
            for tool in tools:
                self._write_system(
                    f"- {tool['name']} ({tool['tool_id'][:8]})",
                    style="cyan",
                )
                contract = tool.get("parameter_contract", {})
                params = contract.get("parameters", [])
                param_names = ", ".join(param["name"] for param in params) or "none"
                self._write_system(f"  parameters: {param_names}", style="dim")
            return

        if action == "attached":
            detail = await self._get_workspace_detail(self.state.workspace_id)
            attached_tools = detail.get("tools", [])
            self._tool_suggestions = [
                {"tool_id": item["tool_id"], "name": item["name"]}
                for item in attached_tools
            ]
            if not attached_tools:
                self._write_system("no tools attached to this workspace", style="yellow")
                return
            self._write_system("Attached Workspace Tools")
            for tool in attached_tools:
                status = "enabled" if tool.get("enabled", True) else "disabled"
                self._write_system(
                    f"- {tool['name']} ({tool['tool_id'][:8]})",
                    style="cyan",
                )
                self._write_system(f"  status: {status}", style="dim")
            return

        tools = await self._list_system_tools()

        target = parts[2].strip() if len(parts) > 2 else ""
        if not target:
            self._write_system(f"usage: /tool {action} <id|name>", style="yellow")
            return

        tool = self._resolve_tool_target(tools, target)
        if tool is None:
            self._write_system(f"tool not found: {target}", style="red")
            return

        if action == "show":
            self._write_system("System Tool")
            self._write_system(f"name: {tool['name']}", style="cyan")
            self._write_system(f"id: {tool['tool_id']}", style="dim")
            self._write_system(
                f"description: {tool.get('description') or 'no description'}",
                style="dim",
            )
            contract = tool.get("parameter_contract", {})
            params = contract.get("parameters", [])
            if params:
                self._write_system("parameter contract:", style="magenta")
                for param in params:
                    required = "required" if param.get("required", True) else "optional"
                    self._write_system(
                        f"  - {param['name']} ({param.get('type', 'any')}, {required})",
                        style="dim",
                    )
            else:
                self._write_system("parameter contract: none", style="dim")
            return

        if action == "attach":
            attached = await self._attach_workspace_tool(
                self.state.workspace_id,
                tool["tool_id"],
            )
            self._write_system(
                f"attached tool: {attached['name']} ({attached['tool_id'][:8]})",
                style="green",
            )
            return

        if action == "detach":
            detail = await self._get_workspace_detail(self.state.workspace_id)
            attached_tools = detail.get("tools", [])
            tool = self._resolve_tool_target(attached_tools, target)
            if tool is None:
                self._write_system(f"attached tool not found: {target}", style="red")
                return
            await self._delete_workspace_tool(self.state.workspace_id, tool["tool_id"])
            self._write_system(
                f"detached tool: {tool['name']} ({tool['tool_id'][:8]})",
                style="green",
            )
            return

        self._write_system(f"unknown tool action: {action}", style="yellow")

    async def _handle_llm_provider_command(self, command: str) -> None:
        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._write_system(_LLM_PROVIDER_COMMAND_HELP, style="yellow")
            return

        action = parts[1].lower()
        target = parts[2].strip() if len(parts) > 2 else ""

        if action == "list":
            providers = await self._list_llm_providers()
            if not providers:
                self._write_system("no llm providers found", style="yellow")
                return
            self._write_system("LLM Providers")
            for provider in providers:
                locality = provider.get("locality") or "unknown"
                enabled = "enabled" if provider.get("enabled", True) else "disabled"
                model = provider.get("default_model") or "auto"
                self._write_system(
                    f"- {provider['display_name']} ({provider['engine_id']})",
                    style="cyan",
                )
                self._write_system(
                    f"  provider: {provider['provider']} | model: {model} | locality: {locality} | {enabled}",
                    style="dim",
                )
            return

        if action == "create":
            if not target:
                self._write_system(_LLM_PROVIDER_CREATE_USAGE, style="yellow")
                return
            try:
                payload = _build_llm_provider_payload(
                    _parse_command_assignments(target),
                    partial=False,
                )
            except ValueError as exc:
                self._write_system(str(exc), style="yellow")
                self._write_system(_LLM_PROVIDER_CREATE_USAGE, style="yellow")
                return
            provider = await self._create_llm_provider(payload)
            self._write_system(
                f"created llm provider: {provider['display_name']} ({provider['engine_id']})",
                style="green",
            )
            self._write_system(f"provider id: {provider['provider_id'][:8]}", style="dim")
            return

        if action not in {"show", "update", "enable", "disable", "delete"}:
            self._write_system(_LLM_PROVIDER_COMMAND_HELP, style="yellow")
            return

        providers = await self._list_llm_providers()
        provider, remainder = None, ""
        if action == "update":
            target_parts = target.split(maxsplit=1)
            lookup_target = target_parts[0] if target_parts else ""
            remainder = target_parts[1] if len(target_parts) > 1 else ""
            provider = _resolve_llm_provider_target(providers, lookup_target)
            if provider is None:
                self._write_system(f"llm provider not found: {lookup_target or 'current'}", style="red")
                return
            if not remainder:
                self._write_system(_LLM_PROVIDER_UPDATE_USAGE, style="yellow")
                return
        else:
            provider = _resolve_llm_provider_target(providers, target)
            if provider is None:
                self._write_system(f"llm provider not found: {target}", style="red")
                return

        if action == "show":
            self._write_system("LLM Provider")
            self._write_system(f"name: {provider['display_name']}", style="cyan")
            self._write_system(f"id: {provider['provider_id']}", style="dim")
            self._write_system(f"engine id: {provider['engine_id']}", style="dim")
            self._write_system(f"provider: {provider['provider']}", style="dim")
            self._write_system(f"description: {provider.get('description') or 'no description'}", style="dim")
            self._write_system(
                f"endpoint: {provider.get('endpoint_kind', 'remote')} {provider.get('url') or ''}".rstrip(),
                style="dim",
            )
            self._write_system(
                f"default model: {provider.get('default_model') or 'auto'}",
                style="dim",
            )
            self._write_system(
                f"locality: {provider.get('locality', 'unknown')} | priority: {provider.get('priority', 100)}",
                style="dim",
            )
            self._write_system(
                f"enabled: {provider.get('enabled', True)}",
                style="dim",
            )
            capabilities = ", ".join(provider.get("capabilities", [])) or "none"
            self._write_system(f"capabilities: {capabilities}", style="dim")
            if provider.get("secret_config"):
                self._write_system(
                    "secret config: " + json.dumps(provider["secret_config"], sort_keys=True),
                    style="dim",
                )
            if provider.get("metadata"):
                self._write_system(
                    "metadata: " + json.dumps(provider["metadata"], sort_keys=True),
                    style="dim",
                )
            return

        if action == "update":
            try:
                payload = _build_llm_provider_payload(
                    _parse_command_assignments(remainder),
                    partial=True,
                )
            except ValueError as exc:
                self._write_system(str(exc), style="yellow")
                self._write_system(_LLM_PROVIDER_UPDATE_USAGE, style="yellow")
                return
            if not payload:
                self._write_system(_LLM_PROVIDER_UPDATE_USAGE, style="yellow")
                return
            updated = await self._update_llm_provider(provider["provider_id"], payload)
            self._write_system(
                f"updated llm provider: {updated['display_name']} ({updated['engine_id']})",
                style="green",
            )
            return

        if action in {"enable", "disable"}:
            enabled = action == "enable"
            updated = await self._update_llm_provider(
                provider["provider_id"],
                {"enabled": enabled},
            )
            self._write_system(
                f"{action}d llm provider: {updated['display_name']} ({updated['engine_id']})",
                style="green",
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
                f"deleted llm provider: {provider['display_name']} ({provider['engine_id']})",
                style="green",
            )
            return

        self._write_system(_LLM_PROVIDER_COMMAND_HELP, style="yellow")

    async def _handle_role_command(self, command: str) -> None:
        if not self.state.workspace_id:
            self._write_system("join or create a workspace first", style="red")
            return

        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2 or parts[1] in {"show", "list"}:
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

        if parts[1] != "use" or len(parts) < 3:
            self._write_system(
                "role commands: /role list | /role show | /role create <name> :: <definition> | /role use <role> [:: <description> :: <cap1, cap2>]",
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
                "usage: /role use <role> [:: <description> :: <cap1, cap2>]",
                style="yellow",
            )
            return
        profile = await self._assume_role(
            role=role,
            description=description,
            capabilities=capabilities,
        )
        self._write_system(f"role in use: {profile['roles'][0]}")
        self._write_system(f"capabilities: {', '.join(profile['capabilities']) or 'none'}", style='dim')

    async def _handle_thread_command(self, command: str) -> None:
        if not self.state.workspace_id:
            self._write_system("join or create a workspace first", style="red")
            return

        parts = command.strip().split(maxsplit=2)
        if len(parts) < 2:
            self._write_system(
                "thread commands: /thread list | /thread show | /thread create <title> | /thread use <id|title>",
                style="yellow",
            )
            return

        action = parts[1].lower()
        threads = await self._list_threads(self.state.workspace_id)

        if action == "list":
            if not threads:
                self._write_system("no threads found", style="yellow")
                return
            self._write_system("Threads")
            for thread in threads:
                marker = "*" if thread["thread_id"] == self.state.thread_id else "-"
                self._write_system(
                    f"{marker} {thread['title']} ({thread['thread_id'][:8]})",
                    style="dim",
                )
            return

        if action == "show":
            current = self._resolve_thread_target(threads, "current")
            if current is None:
                self._write_system("current thread not found", style="red")
                return
            self._write_system("Current Thread")
            self._write_system(f"title: {current['title']}", style="cyan")
            self._write_system(f"id: {current['thread_id']}", style="dim")
            self._write_system(f"state: {current.get('state', 'active')}", style="dim")
            return

        if action == "create":
            target = parts[2].strip() if len(parts) > 2 else ""
            if not target:
                self._write_system("usage: /thread create <title>", style="yellow")
                return
            await self._create_thread(target)
            await self._load_timeline()
            self._connect_ws()
            self._write_system(
                f"created thread: {target} ({self.state.thread_id[:8]})"
            )
            return

        if action == "use":
            target = parts[2].strip() if len(parts) > 2 else ""
            thread = self._resolve_thread_target(threads, target)
            if thread is None:
                self._write_system(f"thread not found: {target or 'current'}", style="red")
                return
            await self._switch_thread(thread["thread_id"])
            self._write_system(
                f"switched thread: {thread['title']} ({thread['thread_id'][:8]})"
            )
            return

        self._write_system(f"unknown thread action: {action}", style="yellow")

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

    def _resolve_thread_target(self, threads: list[dict], target: str) -> dict | None:
        normalized = target.strip()
        if not normalized or normalized == "current":
            for thread in threads:
                if thread["thread_id"] == self.state.thread_id:
                    return thread
            return None

        for thread in threads:
            if thread["thread_id"] == normalized:
                return thread
        for thread in threads:
            if thread["thread_id"].startswith(normalized):
                return thread
        lowered = normalized.lower()
        for thread in threads:
            if thread["title"].lower() == lowered:
                return thread
        return None

    def _resolve_participant_target(
        self, participants: list[dict], target: str
    ) -> dict | None:
        normalized = target.strip()
        if not normalized or normalized == "current":
            for participant in participants:
                if participant["participant_id"] == self.state.participant_id:
                    return participant
            return None

        for participant in participants:
            if participant["participant_id"] == normalized:
                return participant
        for participant in participants:
            if participant["participant_id"].startswith(normalized):
                return participant
        lowered = normalized.lower()
        for participant in participants:
            if participant["display_name"].lower() == lowered:
                return participant
        return None

    def _resolve_tool_target(self, tools: list[dict], target: str) -> dict | None:
        normalized = target.strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        for tool in tools:
            if tool["tool_id"] == normalized:
                return tool
        for tool in tools:
            if tool["tool_id"].startswith(normalized):
                return tool
        for tool in tools:
            if tool["name"].lower() == lowered:
                return tool
        return None

    def _suggestions_for_text(self, text: str) -> str:
        stripped = text.strip()
        if not stripped:
            return " Commands: /workspace list, /workspace create <name>, /workspace use <id|name>"

        if stripped.startswith("/"):
            matches = [
                command for command in self._slash_commands if command.startswith(stripped)
            ]
            if matches:
                return " Suggestions: " + " | ".join(matches[:3])
            return " Slash commands: /auth login | /auth logout | /copy | /open <n>"

        lowered = stripped.lower()
        if "auth" in lowered or "account" in lowered or "login" in lowered or "profile" in lowered:
            return " Tip: /auth login | /auth logout | /account whoami | /account switch <profile>"
        if "copy" in lowered or "clipboard" in lowered:
            return " Tip: /copy copies the full timeline"
        if "link" in lowered or "url" in lowered or "open" in lowered:
            return " Tip: /links lists detected URLs | /open <n> opens one"
        if "workspace" in lowered:
            return " Tip: /workspace list | /workspace show | /workspace use <id|name>"
        if "agent" in lowered:
            return " Tip: /agent create local <name> :: <role> :: <description> :: <model>"
        if "participant" in lowered or "people" in lowered or "team" in lowered:
            return " Tip: /participant list | /participant show <id|name|current> | /participant remove <id|name>"
        if "tool" in lowered:
            return " Tip: /tool list | /tool attached | /tool show <id|name> | /tool attach <id|name> | /tool detach <id|name>"
        if "llm" in lowered or "provider" in lowered or "model registry" in lowered:
            return " Tip: /llm-provider list | /llm-provider show <id|engine_id|name> | /llm-provider create key=value ..."
        if "thread" in lowered:
            return " Tip: /thread list | /thread show | /thread use <id|title>"
        if "role" in lowered:
            return " Tip: /role list | /role show | /role create <name> :: <definition> | /role use <role>"
        if lowered in {"list", "show", "where"}:
            return " Tip: /workspace list shows available workspaces"
        if lowered.startswith("create"):
            return " Tip: /workspace create <name>"
        if lowered.startswith("delete") or lowered.startswith("remove"):
            return " Tip: /workspace delete <id|name|current>"
        return " Enter sends a message. Use /auth, /account, /agent, /workspace, /participant, /thread, /role, /tool, /llm-provider, /copy, or /open commands."

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
        self._timeline_lines = []
        self._detected_links = []
        log = self.query_one("#timeline", RichLog)
        log.clear()
        for message in timeline.get("messages", []):
            self._render_message(message)
            self.state.last_sequence = max(
                self.state.last_sequence, message.get("sequence", 0)
            )
        save_state(self.profile, self.state)
        if timeline.get("messages"):
            self._write_system("history loaded", style="dim")

    @work(thread=False)
    async def _connect_ws(self) -> None:
        assert self.state.thread_id is not None
        ws_base = self.gateway.replace("http://", "ws://").replace("https://", "wss://")
        query_payload: dict[str, str | int] = {"after_sequence": self.state.last_sequence}
        if self.tokens is None:
            query_payload.update(
                {
                    "participant_id": self.state.participant_id or self._fallback_actor_id,
                    "display_name": self.state.display_name,
                    "participant_type": self.state.participant_type,
                }
            )
        query = urlencode(query_payload)
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
        save_state(self.profile, self.state)

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
        content = message.get("content", "")
        time_mark = self._format_message_time(message)
        self._append_timeline_line(f"{time_mark} {prefix}: {content}")

    def _write_system(self, content: str, *, style: str = "dim") -> None:
        self._append_timeline_line(f"-- {content} --")

    def _append_timeline_line(self, line: str) -> None:
        self._timeline_lines.append(line)
        for url in _URL_PATTERN.findall(line):
            if url not in self._detected_links:
                self._detected_links.append(url)
        self.query_one("#timeline", RichLog).write(line)

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
        if self._oidc_enabled and self.tokens is None and self.current_user is None:
            account = f"signed out ({self.profile})"
        else:
            account = f"{self.state.display_name} ({self.profile})"
        self.query_one("#context-info", Static).update(
            " Workspace: [bold]"
            f"{workspace}[/bold]  |  Thread: [bold]{thread}[/bold]  |  "
            f"Account: [bold]{account}[/bold]"
        )

    def _focus_input(self) -> None:
        try:
            self.query_one("#msg-input", Input).focus()
        except Exception:
            pass

    def _focus_input_soon(self) -> None:
        self.call_after_refresh(self._focus_input)

    def _show_links(self) -> None:
        if not self._detected_links:
            self._write_system("no links detected yet", style="yellow")
            return
        self._write_system("detected links:", style="dim")
        for index, url in enumerate(self._detected_links, start=1):
            self._write_system(f"{index}. {url}", style="cyan")

    def _open_link(self, target: str) -> None:
        normalized = target.strip()
        if not normalized:
            self._write_system("usage: /open <number|url|last>", style="yellow")
            return
        url: str | None = None
        if normalized == "last":
            if self._detected_links:
                url = self._detected_links[-1]
        elif normalized.isdigit():
            index = int(normalized) - 1
            if 0 <= index < len(self._detected_links):
                url = self._detected_links[index]
        elif normalized.startswith("http://") or normalized.startswith("https://"):
            url = normalized

        if url is None:
            self._write_system(f"link not found: {normalized}", style="red")
            return
        self.open_url(url)
        self._write_system(f"opened link: {url}", style="green")

    @on(Input.Submitted, "#msg-input")
    async def on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            self._focus_input_soon()
            return
        event.input.clear()
        try:
            if text == "/quit":
                self.exit()
                return
            if text == "/clear":
                self.action_clear()
                return
            if text == "/copy":
                self.action_copy_timeline()
                return
            if text == "/links":
                self._show_links()
                return
            if text.startswith("/open "):
                self._open_link(text[len("/open ") :])
                return
            if text.startswith("/workspace ") or text == "/workspace":
                if not self._require_authenticated_session():
                    return
                try:
                    await self._handle_workspace_command(text)
                    self._update_status("ok", "Connected")
                except Exception as exc:
                    logger.exception("TUI workspace command failed")
                    self._write_system(f"workspace command failed: {exc}", style="red")
                    self._update_status("err", "Workspace failed")
                return
            if text == "/account" or text.startswith("/account "):
                try:
                    await self._handle_account_command(text)
                    self._update_status("ok", "Connected")
                except Exception as exc:
                    logger.exception("TUI account command failed")
                    self._write_system(f"account command failed: {exc}", style="red")
                    self._update_status("err", "Account failed")
                return
            if text == "/auth" or text.startswith("/auth "):
                try:
                    await self._handle_auth_command(text)
                    self._update_status("ok", "Connected")
                except Exception as exc:
                    logger.exception("TUI auth command failed")
                    self._write_system(f"auth command failed: {exc}", style="red")
                    self._update_status("err", "Auth failed")
                return
            if text == "/agent" or text.startswith("/agent "):
                if not self._require_authenticated_session():
                    return
                try:
                    await self._handle_agent_command(text)
                    self._update_status("ok", "Connected")
                except Exception as exc:
                    logger.exception("TUI agent command failed")
                    self._write_system(f"agent command failed: {exc}", style="red")
                    self._update_status("err", "Agent failed")
                return
            if text == "/participant" or text.startswith("/participant "):
                if not self._require_authenticated_session():
                    return
                try:
                    await self._handle_participant_command(text)
                    self._update_status("ok", "Connected")
                except Exception as exc:
                    logger.exception("TUI participant command failed")
                    self._write_system(f"participant command failed: {exc}", style="red")
                    self._update_status("err", "Participant failed")
                return
            if text == "/tool" or text.startswith("/tool "):
                if not self._require_authenticated_session():
                    return
                try:
                    await self._handle_tool_command(text)
                    self._update_status("ok", "Connected")
                except Exception as exc:
                    logger.exception("TUI tool command failed")
                    self._write_system(f"tool command failed: {exc}", style="red")
                    self._update_status("err", "Tool failed")
                return
            if text == "/llm-provider" or text.startswith("/llm-provider "):
                if not self._require_authenticated_session():
                    return
                try:
                    await self._handle_llm_provider_command(text)
                    self._update_status("ok", "Connected")
                except Exception as exc:
                    logger.exception("TUI llm-provider command failed")
                    self._write_system(f"llm-provider command failed: {exc}", style="red")
                    self._update_status("err", "LLM provider failed")
                return
            if text == "/thread" or text.startswith("/thread "):
                if not self._require_authenticated_session():
                    return
                try:
                    await self._handle_thread_command(text)
                    self._update_status("ok", "Connected")
                except Exception as exc:
                    logger.exception("TUI thread command failed")
                    self._write_system(f"thread command failed: {exc}", style="red")
                    self._update_status("err", "Thread failed")
                return
            if text == "/role" or text.startswith("/role "):
                if not self._require_authenticated_session():
                    return
                try:
                    await self._handle_role_command(text)
                    self._update_status("ok", "Connected")
                except Exception as exc:
                    logger.exception("TUI role command failed")
                    self._write_system(f"role command failed: {exc}", style="red")
                    self._update_status("err", "Role failed")
                return
            if not self.state.thread_id:
                if not self._require_authenticated_session():
                    return
                self._write_system("thread not ready yet", style="red")
                return
            if not self._require_authenticated_session():
                return

            self._update_status("wait", "Sending...")
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
        finally:
            self._focus_input_soon()

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

    def action_copy_timeline(self) -> None:
        copied = "\n".join(self._timeline_lines)
        self.app.copy_to_clipboard(copied)
        self._write_system("copied full timeline", style="green")

    def action_clear(self) -> None:
        self._timeline_lines = []
        self._detected_links = []
        self.query_one("#timeline", RichLog).clear()


def _build_tui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Open Talon collaboration terminal UI for Keycloak-authenticated human users",
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


def _build_auth_login_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trigger TUI Keycloak device login for a local profile",
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
    return parser


def _run_auth_login_cli(args: argparse.Namespace) -> None:
    if not (args.oidc_issuer_url and args.oidc_client_id):
        raise SystemExit(
            "The TUI auth login command requires Keycloak OIDC. Pass --oidc-issuer-url and --oidc-client-id."
        )
    profile = resolve_startup_profile(
        args.profile,
        oidc_enabled=True,
    )
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


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:2] == ["auth", "login"]:
        parser = _build_auth_login_parser()
        args = parser.parse_args(argv[2:])
        _run_auth_login_cli(args)
        return

    parser = _build_tui_parser()
    args = parser.parse_args(argv)

    if not (args.oidc_issuer_url and args.oidc_client_id):
        raise SystemExit("The TUI requires Keycloak OIDC for human users. Pass --oidc-issuer-url and --oidc-client-id.")
    profile = resolve_startup_profile(
        args.profile,
        oidc_enabled=bool(args.oidc_issuer_url and args.oidc_client_id),
    )

    app = CollaborationApp(
        gateway=args.gateway,
        profile=profile,
        api_key=None,
        openbao_token=None,
        oidc_issuer_url=args.oidc_issuer_url,
        oidc_client_id=args.oidc_client_id,
        display_name=args.display_name,
        workspace_name=args.workspace_name,
        thread_title=args.thread_title,
        participant_type="user",
    )
    app.run()


if __name__ == "__main__":
    main()
