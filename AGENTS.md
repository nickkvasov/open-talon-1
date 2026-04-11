# Open Talon Agent Guide

This file is for coding agents working in this repository, including Codex, Claude Code, and similar tools.

## Project Overview

Open Talon is a local-first collaboration system where humans and agents are first-class participants.

Main components:

- `services/gateway-edge`: FastAPI gateway for REST, SSE, WebSocket, auth, admin, and collaboration APIs
- `services/core-collab`: canonical collaboration domain logic and Postgres repository layer
- `services/agent-runtime`: stateless workers for agent-loop execution, tool execution, and lease reconciliation
- `packages/contracts`: shared Pydantic contracts used across services
- `apps/tui`: terminal UI client for workspace/thread collaboration
- `infrastructure`: local Docker-based backing services
- `db/migrations`: source of truth for database schema changes

Primary local flow:

1. A client talks to `gateway-edge`.
2. The gateway reads/writes Postgres and Valkey.
3. `core-collab` persists collaboration state and durable execution state such as `tasks`, `runs`, `run_steps`, and `tool_calls`.
4. Stateless `agent-runtime` workers claim work, execute model/tool steps, and publish events through Kafka.
5. Events are streamed back over HTTP/SSE/WebSocket.

## Important Architecture Rules

- Treat `db/migrations` as the schema source of truth.
- Do not reintroduce monolithic in-code DDL strings.
- Postgres is the source of truth for execution state; Kafka is the wake-up and fanout bus.
- Do not move agent loop execution back into `gateway-edge`.
- `participants` is a workspace-scoped attachment/state table.
- Human identity lives in `users`.
- Agent identity/configuration lives in `system_agents`.
- `participants.user_id` and `participants.system_agent_id` are the normalized references.
- Do not duplicate agent profile/config data back into `participants`.
- Keep workspace-local state on `participants`: status, visibility scope, roles, capabilities, timestamps, and metadata.
- Keep execution-side workspace materialization separate from collaboration `Workspace` models. Use `ExecutionWorkspaceRef` for executor payloads.

## Database Rules

- Create a new migration for every schema or backfill change.
- Never edit an old migration after it has been applied in a shared environment.
- Prefer additive migrations and explicit backfills.
- Keep migrations SQL-first and reviewable.
- Use `./scripts/dbmate.sh new <name>` to create a migration.
- Use `./scripts/dbmate.sh up` to apply pending migrations locally.
- Startup/tests also apply pending migrations through the Python migration runner in `services/core-collab/core_collab/migrations.py`.

## Development Environment

- Use the repo root virtualenv: `.venv`
- Bootstrap with:

```bash
./scripts/bootstrap-python.sh
source .venv/bin/activate
```

- Default local Postgres:
  - database: `app_db`
  - user: `admin`
  - password: `password`
- Local infrastructure defaults are documented in `infrastructure/.env.example`.

## Testing Expectations

Before finishing meaningful code changes, run the most relevant tests.

Common commands:

```bash
pytest -q
pytest tests/gateway-edge -q
pytest tests/core-collab -q
pytest tests/tui -q
pytest -m integration tests/infrastructure/test_infrastructure.py -v -s
```

If a change touches schema, repository, participant hydration, routing, or migrations:

- run relevant `core-collab` tests
- run relevant `gateway-edge` tests
- run full `pytest -q` when feasible

## Code Change Rules

- Preserve the normalized participant model.
- Avoid hidden schema changes in app startup code.
- Keep gateway routers thin; prefer logic in services/kernel/repository layers.
- Keep execution orchestration in Open Talon code and isolate only the backend executor behind the execution interface.
- Prefer explicit SQL and repository methods for database changes.
- Keep migration/backfill logic separate from steady-state read/write logic when possible.
- Do not remove compatibility paths from live data unless the corresponding migration is included.
- When cleaning legacy columns or data, update both code and migration flow together.
- When changing worker behavior, cover both durable state transitions and emitted Kafka/thread events in tests.

## TUI Rules

- Keep slash commands discoverable through suggestion text.
- If you add a new command, update:
  - command handling
  - suggestion/help text
  - tests when behavior is nontrivial

## Recommended Workflow For Agents

1. Read the relevant service, repository, and contract files first.
2. Check whether the change requires a migration.
3. If schema changes are involved, add a new file in `db/migrations`.
4. If execution behavior changes, inspect `services/agent-runtime`, `services/core-collab`, and gateway event fanout together.
5. Update code to match the migrated schema.
6. Run targeted tests.
7. Run broader tests if the change affects shared contracts or persistence.

## Key Files

- `README.md`
- `docs/db-migrations.md`
- `services/core-collab/core_collab/migrations.py`
- `services/core-collab/core_collab/repository.py`
- `services/core-collab/core_collab/kernel.py`
- `services/agent-runtime/agent_runtime/workers.py`
- `services/agent-runtime/agent_runtime/execution/`
- `services/gateway-edge/gateway_edge/services/collaboration.py`
- `services/gateway-edge/gateway_edge/services/events.py`
- `services/gateway-edge/gateway_edge/db/postgres.py`
- `apps/tui/open_talon_tui/main.py`

## When In Doubt

- Prefer normalization over duplication.
- Prefer explicit migrations over implicit schema mutation.
- Prefer small, reviewable changes over broad rewrites.
- Keep the repo runnable locally after each change.
