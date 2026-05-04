# TUI Agent Guide

This guide applies under `apps/tui/` and adds to the root guide.

## Client Rules

- `open_talon_tui.tui2` is the preferred human terminal client when
  copy/select/link behavior matters.
- Keep slash commands discoverable through suggestion text.
- If you add a new command, update command handling, suggestion/help text, and
  tests when behavior is nontrivial.
- Keep `tui2` and `user-client` organization-selection flows aligned with the
  org-aware workspace APIs.
- The TUI is profile-based, not single-user-per-device.
- Do not reintroduce a single global local participant identity file for human
  users.
- Human TUI sessions should authenticate with bearer tokens and rely on
  server-derived participant identity.
- Keep `tui2` resilient: network/auth failures should degrade to readable system
  messages, not tracebacks.
- When changing collaboration bootstrap or response parsing, keep `main.py` and
  `tui2.py` aligned on gateway contract shapes.
- Prefer `tui2` guidance in docs when the goal is reliable mouse copy or link
  interaction in the terminal.

## Tests

- Run `tests/tui` for TUI login, profile, command, bootstrap, or response parsing
  changes.
- Run relevant gateway auth/IAM tests when TUI behavior depends on server-side
  auth or identity changes.

## Key Files

- `open_talon_tui/main.py`
- `open_talon_tui/tui2.py`
