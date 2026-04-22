# Open Talon TUI

This package provides Open Talon's terminal clients, all of which talk to `gateway-edge` over REST and WebSocket.

The main surfaces are:

- `tui2`: recommended scrollback-first human terminal client
- `user-client`: line-oriented client for scripted and multi-user testing
- `tui`: legacy full-screen Textual client

## What It Does

These clients can:

- create or reuse a workspace
- create or reuse a thread
- post messages into the current thread
- run a scriptable per-user client for multi-user end-to-end testing
- inspect participants, collaboration roles, threads, and workspaces
- select an organization before listing or creating workspaces in `tui2` and `user-client`
- create local agents and attach them to the current workspace
- inspect system tools and attach or detach them from the current workspace
- submit Tinker tool-generation requests from `tui2` and `user-client`

## Run It

For most human terminal use, start with `tui2` from the repository root:

```bash
source .venv/bin/activate
./open-talon tui2 --profile nikolay
```

For scripted or multi-user end-to-end testing, start with `user-client`:

```bash
source .venv/bin/activate
./open-talon user-client --profile user1
```

If you specifically want the older full-screen client, it is still available:

```bash
source .venv/bin/activate
./open-talon tui --profile nikolay
```

For the local dev stack, the terminal clients default to the local Keycloak realm:

- issuer: `http://127.0.0.1:8081/realms/open-talon`
- client id: `open-talon-tui`

Explicit full-screen `tui` invocation:

```bash
python -m open_talon_tui.main \
  --gateway http://127.0.0.1:8000 \
  --profile nikolay \
  --oidc-issuer-url http://127.0.0.1:8081/realms/open-talon \
  --oidc-client-id open-talon-tui \
  --workspace-name Workspace \
  --thread-title General
```

Human terminal users authenticate through the configured OIDC provider. In local development that is Keycloak. Local unsigned profiles, API-key auth, OpenBao token auth, and machine client credentials are not supported for normal human use.
The full-screen `tui` can still start signed out so you can run `/auth login` from inside the app before joining workspaces or sending messages.

Machine principals use OIDC client credentials plus the `/v1/iam/agent-identities` APIs directly. The TUI surfaces are human-oriented and `/v1/me` is human-only.

Terminology:

- `IAM role` means a global or organization authorization role managed through `/v1/iam/...`
- `collaboration role` means a workspace-local role a participant assumes through `/role use ...`
- `capability` means a workspace-local advertised label used for routing and discovery

The TUI `/role ...` commands work with collaboration roles, not IAM roles.

`tui2` is a scrollback-first client. It prints plain timeline lines into the normal terminal, so you can select text with the mouse the same way you would in any shell scrollback. URLs are printed as raw URLs and also emitted as terminal hyperlinks when supported by the terminal emulator.

`tui2` and `user-client` are the preferred clients for multi-organization setups. They track `organization_id`, expose explicit `organization` commands, and default workspace listing to the selected organization.

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

These are the legacy full-screen `tui` workspace commands. The full-screen client does not expose `/organization ...` commands yet. Workspace creation through this path only works cleanly when the authenticated user resolves to exactly one visible organization.

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

These commands manage workspace collaboration roles and their local definitions. They do not create or bind IAM roles.

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
/organization list
/organization show [id|slug|name]
/organization use <id|slug|name>
/workspace list [all]
/workspace create <name>
/workspace use <id|name>
/thread list
/thread create <title>
/thread use <id|title>
/tool request [--scope global|organization] <text>
/links
/open <number|last|url>
/copy
/quit
```

If the authenticated user can see exactly one organization, `tui2` auto-selects it after login. On a fresh local stack that is usually `Default Organization`.

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
./open-talon user-client --profile admin --output json --command "organization list"
./open-talon user-client --profile admin --output json --command "workspace list all"
```

Useful `user-client` commands:

```text
help
status
auth login
auth logout
organization list
organization show [id|slug|name]
organization use <id|slug|name>
workspace list [all]
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
- `workspace list` defaults to the selected organization; use `workspace list all` when you need every visible workspace
- `workspace create` requires a selected organization in `tui2` and `user-client`
- `workspace use <uuid>` and `thread use <uuid>` accept direct ids, which is useful when another client already created the shared workspace or thread
- plain message lines are sent directly; use `send <text>` when the line would otherwise be mistaken for a client command
- selector mentions such as `@role:frontend_engineer` are parsed into atomic interaction-request payloads automatically when sending messages
