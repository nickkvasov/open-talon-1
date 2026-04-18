# Open Talon TUI

The TUI is a terminal client for Open Talon that talks to `gateway-edge` over REST and WebSocket.

## What It Does

The TUI can:

- create or reuse a workspace
- create or reuse a thread
- post messages into the current thread
- run a scriptable per-user client for multi-user end-to-end testing
- inspect participants, roles, threads, and workspaces
- create local agents and attach them to the current workspace
- inspect system tools and attach or detach them from the current workspace

## Run It

From the repository root:

```bash
source .venv/bin/activate
python -m open_talon_tui.main
```

For the local dev stack, the TUI defaults to the local Keycloak realm:

- issuer: `http://127.0.0.1:8081/realms/open-talon`
- client id: `open-talon-tui`

So this is enough for most local usage:

```bash
./open-talon tui --profile nikolay
```

```bash
python -m open_talon_tui.main \
  --gateway http://127.0.0.1:8000 \
  --profile nikolay \
  --oidc-issuer-url http://127.0.0.1:8081/realms/open-talon \
  --oidc-client-id open-talon-tui \
  --workspace-name Workspace \
  --thread-title General
```

Human TUI users must authenticate through Keycloak. Local unsigned profiles, API-key auth, and OpenBao token auth are not supported for normal human TUI use.
The TUI can still start signed out so you can run `/auth login` from inside the app before joining workspaces or sending messages.

If you want reliable terminal mouse selection and terminal-native clickable links, use `tui2` instead of the full-screen Textual UI:

```bash
./open-talon tui2 --profile nikolay
```

`tui2` is a scrollback-first client. It prints plain timeline lines into the normal terminal, so you can select text with the mouse the same way you would in any shell scrollback. URLs are printed as raw URLs and also emitted as terminal hyperlinks when supported by the terminal emulator.

If you want one user-facing client instance per human profile for software-agent-driven end-to-end testing, use `user-client`:

```bash
./open-talon user-client --profile user1
```

`user-client` is a line-oriented REPL with stable commands and optional JSON output. It is designed for scenarios where several software development agents need to act as different human users at the same time without sharing local state.

You can also trigger the same Keycloak device-login flow directly from the CLI:

```bash
python -m open_talon_tui.main auth login \
  --gateway http://127.0.0.1:8000 \
  --profile nikolay \
  --oidc-issuer-url http://127.0.0.1:8081/realms/open-talon \
  --oidc-client-id open-talon-tui
```

The same device-login flow is available for `user-client`:

```bash
./open-talon user-client auth login --profile user1
```

## Slash Commands

The TUI supports several slash-command families:

- `/auth`
- `/workspace`
- `/account`
- `/participant`
- `/thread`
- `/role`
- `/agent`
- `/tool`

### Auth Commands

```text
/auth login
/auth logout
```

### Tool Commands

```text
/tool list
/tool show <id|name>
/tool attach <id|name>
/tool attached
/tool detach <id|name>
```

These commands work with the system-tool registry and the current workspace attachment APIs.

Typical flow:

1. Create a system tool definition through the API.
2. Inspect available tools with `/tool list` or `/tool show <id|name>`.
3. Attach a tool to the current workspace with `/tool attach <id|name>`.
4. Inspect attached tools with `/tool attached`.
5. Remove a tool from the current workspace with `/tool detach <id|name>`.

### Agent Commands

Current built-in agent flow:

```text
/agent create local <name> :: <role> :: <description> :: <model> [:: <cap1, cap2>] [:: <system prompt>]
```

### Workspace Commands

```text
/workspace list
/workspace show
/workspace create <name>
/workspace use <id|name>
/workspace delete <id|name|current>
```

### Account Commands

```text
/account login
/account whoami
/account list
/account switch <profile>
/account logout
```

### Participant Commands

```text
/participant list
/participant show <id|name|current>
/participant remove <id|name>
```

### Thread Commands

```text
/thread list
/thread show
/thread create <title>
/thread use <id|title>
```

### Role Commands

```text
/role list
/role show
/role create <name> :: <definition>
/role use <role> [:: <description> :: <cap1, cap2>]
```

## Notes

- Tool resolution in the TUI accepts full id, short id prefix, or exact name.
- The TUI stores per-profile state and tokens under `~/.open-talon/profiles/<profile>/`.
- Signed-out startup is allowed only so a human can run `/auth login`; workspace, thread, participant, role, tool, agent, and message actions still require an authenticated Keycloak session.
- The TUI now uses a simpler plain-log timeline again so the core app behavior stays reliable.
- Use `/copy` to copy the full timeline to the clipboard.
- Use `/links` to list detected URLs and `/open <number|last|url>` to open one reliably.
- Use `/quit` to leave the TUI and `/clear` to clear the visible timeline.
- Only the current per-profile state/token format is supported. Old local TUI auth/state is not migrated and users must sign in again.
- Slash-command suggestions are built into the input box and update as you type.

## TUI2

`tui2` is the recommended terminal client when copy/paste and mouse link interaction matter more than full-screen UI layout.

It also keeps a fixed dashboard-style top panel in tty mode, while `Up`/`Down` recall previous entries and `Tab` completes supported slash commands.

Useful commands in `tui2`:

```text
/help
/auth login
/auth logout
/account whoami
/account list
/account switch <profile>
/workspace list
/workspace create <name>
/workspace use <id|name>
/thread list
/thread create <title>
/thread use <id|title>
/links
/open <number|last|url>
/copy
/quit
```

## User Client

`user-client` is the recommended terminal client when you need software development agents to drive several human-user sessions end to end.

Key properties:

- one client instance maps to one local profile
- one profile maps to one human user identity
- state and tokens stay isolated under `~/.open-talon/profiles/<profile>/`
- the command surface is explicit and stable enough for stdin/stdout automation
- `--output json` produces machine-readable command results

Typical multi-user setup:

```bash
./open-talon user-client auth login --profile admin
./open-talon user-client auth login --profile user1
./open-talon user-client auth login --profile user2
```

Then start one client instance per user:

```bash
./open-talon user-client --profile admin
./open-talon user-client --profile user1
./open-talon user-client --profile user2
```

Non-interactive command mode is available through repeated `--command` flags:

```bash
./open-talon user-client --profile admin --command "status"
./open-talon user-client --profile admin --output json --command "workspace list"
```

Useful `user-client` commands:

```text
help
status
auth login
auth logout
workspace list
workspace create <name>
workspace use <id|name>
thread list
thread create <title>
thread use <id|title>
role list
role use <role> [:: <description> :: <cap1,cap2>]
send <text>
timeline [limit]
request list [open|all]
request show <id|title|current>
request answer <id|title|current> :: <text>
log [limit]
quit
```

Notes for end-to-end testing:

- do not share a profile between users; each human test user needs its own client instance
- `workspace use <uuid>` and `thread use <uuid>` accept direct ids, which is useful when another client already created the shared workspace or thread
- plain message lines are sent directly; use `send <text>` when the line would otherwise be mistaken for a client command
- selector mentions such as `@role:frontend_engineer` are parsed into atomic interaction-request payloads automatically when sending messages
