# Open Talon TUI

The TUI is a terminal client for Open Talon that talks to `gateway-edge` over REST and WebSocket.

## What It Does

The TUI can:

- create or reuse a workspace
- create or reuse a thread
- post messages into the current thread
- inspect participants, roles, threads, and workspaces
- create local agents and attach them to the current workspace
- inspect system tools and attach or detach them from the current workspace

## Run It

From the repository root:

```bash
source .venv/bin/activate
python -m open_talon_tui.main
```

Common flags:

```bash
python -m open_talon_tui.main \
  --gateway http://127.0.0.1:8000 \
  --display-name Nikolay \
  --workspace-name Workspace \
  --thread-title General
```

## Slash Commands

The TUI supports several slash-command families:

- `/workspace`
- `/participant`
- `/thread`
- `/role`
- `/agent`
- `/tool`

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
- The TUI stores lightweight local client state under `~/.open-talon/`.
- Slash-command suggestions are built into the input box and update as you type.
