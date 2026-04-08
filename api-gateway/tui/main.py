"""
Open Senate — Terminal UI

Usage
-----
  cd api-gateway
  python -m tui.main                           # default http://localhost:8000
  python -m tui.main --gateway http://host:8000
  python -m tui.main --api-key <key>
  python -m tui.main --openbao-token <token>

The TUI connects to the gateway via WebSocket for real-time streaming.
Sessions are persisted in ~/.open-senate/session.json.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import websockets
import websockets.exceptions
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, Input, Label, RichLog, Static

# ── Session persistence ───────────────────────────────────────────
_CFG_DIR  = Path.home() / ".open-senate"
_CFG_FILE = _CFG_DIR / "session.json"


def load_session() -> UUID:
    try:
        _CFG_DIR.mkdir(parents=True, exist_ok=True)
        data = json.loads(_CFG_FILE.read_text())
        return UUID(data["session_id"])
    except Exception:
        sid = uuid4()
        save_session(sid)
        return sid


def save_session(sid: UUID) -> None:
    _CFG_DIR.mkdir(parents=True, exist_ok=True)
    _CFG_FILE.write_text(json.dumps({"session_id": str(sid)}))


# ── TUI App ───────────────────────────────────────────────────────
CSS = """
Screen {
    background: $surface-darken-3;
}

#body {
    layout: vertical;
    height: 1fr;
}

#chat-log {
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

#status-bar .status-ok   { color: ansi_bright_green; }
#status-bar .status-err  { color: ansi_bright_red; }
#status-bar .status-wait { color: ansi_bright_yellow; }

#composer {
    height: 3;
    margin: 1;
    layout: horizontal;
}

#msg-input {
    width: 1fr;
}

#session-info {
    height: 1;
    background: $panel;
    padding: 0 2;
    color: $text-muted;
}

.user-msg   { color: $accent; }
.bot-msg    { color: $text; }
.system-msg { color: $text-muted; }
.error-msg  { color: $error; }
"""


class ChatApp(App):
    """Open Senate Terminal Chat Client."""

    TITLE   = "Open Senate"
    SUB_TITLE = "Gateway TUI"
    CSS     = CSS
    BINDINGS = [
        Binding("ctrl+n", "new_session", "New Session"),
        Binding("ctrl+q", "quit",        "Quit"),
        Binding("ctrl+l", "clear",       "Clear"),
    ]

    status: reactive[str] = reactive("Connecting…")
    connected: reactive[bool] = reactive(False)

    def __init__(self, gateway: str, api_key: str | None, openbao_token: str | None):
        super().__init__()
        self.gateway      = gateway.rstrip("/")
        self.api_key      = api_key
        self.openbao_token= openbao_token
        self.session_id   = load_session()
        self._ws          = None
        self._streaming   = False
        self._send_queue: asyncio.Queue[str] = asyncio.Queue()

    # ── Auth headers ──────────────────────────────────────────────
    @property
    def _auth_headers(self) -> dict[str, str]:
        hdrs: dict[str, str] = {}
        if self.api_key:
            hdrs["X-API-Key"] = self.api_key
        if self.openbao_token:
            hdrs["Authorization"] = f"Bearer {self.openbao_token}"
        return hdrs

    # ── Layout ────────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="body"):
            yield Static(
                f" Session: [bold]{str(self.session_id)[:8]}…[/bold]  |  "
                f"Gateway: [bold]{self.gateway}[/bold]",
                id="session-info",
            )
            yield RichLog(id="chat-log", markup=True, highlight=False, wrap=True)
            yield Static(f" ⟳ {self.status}", id="status-bar")
            with Horizontal(id="composer"):
                yield Input(placeholder="Type a message… (Enter to send)", id="msg-input")
        yield Footer()

    def on_mount(self) -> None:
        self._load_history()
        self._connect_ws()

    # ── History ───────────────────────────────────────────────────
    @work(thread=False)
    async def _load_history(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        try:
            async with httpx.AsyncClient(headers=self._auth_headers, timeout=10) as client:
                resp = await client.get(
                    f"{self.gateway}/v1/history/{self.session_id}"
                )
            if resp.status_code == 200:
                messages = resp.json()
                for msg in messages:
                    role = msg.get("role", "assistant")
                    content = msg.get("content", "")
                    if role == "user":
                        log.write(f"[bold cyan]You:[/bold cyan] {content}")
                    else:
                        log.write(f"[bold magenta]⚖  AI:[/bold magenta] {content}")
                if messages:
                    log.write("[dim]── history loaded ──[/dim]")
        except Exception as exc:
            log.write(f"[yellow]History unavailable: {exc}[/yellow]")

    # ── WebSocket ─────────────────────────────────────────────────
    @work(thread=False)
    async def _connect_ws(self) -> None:
        log  = self.query_one("#chat-log", RichLog)
        ws_scheme = "wss" if self.gateway.startswith("https") else "ws"
        ws_base   = self.gateway.replace("http://", "ws://").replace("https://", "wss://")
        url = f"{ws_base}/v1/ws/chat/{self.session_id}"

        extra_headers = list(self._auth_headers.items())

        while True:
            try:
                async with websockets.connect(url, additional_headers=extra_headers) as ws:
                    self._ws = ws
                    self.connected = True
                    self._update_status("ok", "Connected")
                    log.write("[dim]── connected ──[/dim]")

                    async def _sender():
                        while True:
                            msg = await self._send_queue.get()
                            if ws.open:
                                await ws.send(json.dumps({"message": msg}))

                    sender_task = asyncio.create_task(_sender())
                    try:
                        async for raw in ws:
                            data = json.loads(raw)
                            await self._handle_ws_event(data, log)
                    finally:
                        sender_task.cancel()

            except websockets.exceptions.ConnectionClosed:
                pass
            except Exception as exc:
                log.write(f"[red]WS error: {exc}[/red]")

            self._ws = None
            self.connected = False
            self._update_status("err", "Reconnecting…")
            await asyncio.sleep(3)

    async def _handle_ws_event(self, data: dict, log: RichLog) -> None:
        evt_type = data.get("type")
        if evt_type == "token":
            if not self._streaming:
                self._streaming = True
                log.write("[bold magenta]⚖  AI:[/bold magenta] ", end="")
            log.write(data.get("content", ""), end="")
        elif evt_type == "done":
            if self._streaming:
                log.write(data.get("content", ""))
                self._streaming = False
            else:
                log.write(f"[bold magenta]⚖  AI:[/bold magenta] {data.get('content', '')}")
            self._update_status("ok", "Connected")
        elif evt_type == "error":
            self._streaming = False
            log.write(f"[red]Error: {data.get('error', 'unknown')}[/red]")
            self._update_status("ok", "Connected")

    # ── UI helpers ────────────────────────────────────────────────
    def _update_status(self, state: str, label: str) -> None:
        icons = {"ok": "●", "err": "✖", "wait": "⟳"}
        colours = {"ok": "green", "err": "red", "wait": "yellow"}
        col = colours.get(state, "white")
        try:
            self.query_one("#status-bar", Static).update(
                f" [{col}]{icons.get(state, '?')}[/{col}]  {label}"
            )
        except Exception:
            pass

    # ── Input handler ─────────────────────────────────────────────
    @on(Input.Submitted, "#msg-input")
    async def on_submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[bold cyan]You:[/bold cyan] {text}")

        if self._ws and self.connected:
            await self._send_queue.put(text)
            self._update_status("wait", "Generating…")
        else:
            log.write("[yellow]Not connected — waiting for reconnect…[/yellow]")

    # ── Keybindings ───────────────────────────────────────────────
    def action_new_session(self) -> None:
        self.session_id = uuid4()
        save_session(self.session_id)
        self.query_one("#chat-log", RichLog).clear()
        self.query_one("#session-info", Static).update(
            f" Session: [bold]{str(self.session_id)[:8]}…[/bold]  |  "
            f"Gateway: [bold]{self.gateway}[/bold]"
        )
        if self._ws:
            asyncio.create_task(self._ws.close())
        self._connect_ws()

    def action_clear(self) -> None:
        self.query_one("#chat-log", RichLog).clear()


# ── CLI entry point ───────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Open Senate Gateway — Terminal UI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--gateway",       default="http://localhost:8000", help="Gateway base URL")
    parser.add_argument("--api-key",       default=None,                    help="X-API-Key value")
    parser.add_argument("--openbao-token", default=None,                    help="OpenBao Bearer token")
    args = parser.parse_args()

    app = ChatApp(
        gateway       = args.gateway,
        api_key       = args.api_key,
        openbao_token = args.openbao_token,
    )
    app.run()


if __name__ == "__main__":
    main()
