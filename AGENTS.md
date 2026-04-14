# Open Talon Agent Guide

This file is for coding agents working in this repository, including Codex, Claude Code, and similar tools.

## Project Overview

Open Talon is a local-first collaboration system where humans and agents are first-class participants.

Main components:

- `services/gateway-edge`: FastAPI gateway for REST, SSE, WebSocket, auth, admin, and collaboration APIs
- `services/core-collab`: canonical collaboration domain logic and Postgres repository layer
- `services/agent-runtime`: stateless workers for task dispatch, agent-loop execution, tool execution, and lease reconciliation
- `packages/contracts`: shared Pydantic contracts used across services
- `apps/tui`: terminal UI client for workspace/thread collaboration
  - `open_talon_tui.tui2` is the preferred human terminal client when copy/select/link behavior matters
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
- External identity mappings live in `auth_identities`.
- Agent identity/configuration lives in `system_agents`.
- `participants.user_id` and `participants.system_agent_id` are the normalized references.
- Keep `users.user_id` distinct from `participants.participant_id` for human users.
- Do not duplicate agent profile/config data back into `participants`.
- Keep workspace-local state on `participants`: status, visibility scope, roles, capabilities, timestamps, and metadata.
- Keep execution-side workspace materialization separate from collaboration `Workspace` models. Use `ExecutionWorkspaceRef` for executor payloads.
- Authenticated human identity should be derived in `gateway-edge` from OIDC auth context, not trusted from client-provided actor fields.
- LLM providers are persistent records in `llm_providers`; do not reintroduce env-defined engine registries.
- Memory providers are persistent records in `memory_providers`; do not hardcode provider definitions in application logic after bootstrapping.
- Local OpenBao now uses persistent file storage under `infrastructure/data/openbao`; do not assume `docker compose down` clears local secrets.
- Postgres is the canonical memory store. Mem0 and optional graph backends such as Memgraph are derived retrieval projections, not the source of truth.

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
- Default local Keycloak:
  - base URL: `http://127.0.0.1:8081`
  - realm: `open-talon`
  - TUI client: `open-talon-tui`
- Default local OpenBao:
  - base URL: `http://127.0.0.1:8200`
  - root token: `root`
  - persistent data dir: `infrastructure/data/openbao`
- Optional local Memgraph for Mem0 graph mode:
  - bolt URL: `bolt://127.0.0.1:7688`
  - start it locally with `./open-talon start --memgraph`
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

If a change touches layered memory, memory providers, Mem0, or graph-memory support:

- inspect `services/workspace-memory`, `services/core-collab`, `services/gateway-edge`, and `packages/contracts` together
- verify canonical persistence and provider projection both still make sense
- run relevant `tests/workspace-memory`
- run relevant memory route tests in `tests/gateway-edge`
- keep `infrastructure/.env.example`, `infrastructure/docker-compose.yaml`, and `open-talon` aligned if graph mode behavior changes

If a change touches OIDC auth, Keycloak wiring, or TUI login/profile behavior:

- run relevant `gateway-edge` auth tests
- run `tests/tui`
- verify docs and env defaults stay aligned with the actual login flow

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
- When changing provider or secret behavior, keep `gateway-edge`, `core-collab`, `agent-runtime`, and docs aligned on persistent provider definitions and OpenBao-backed secret resolution.
- When adding a new memory provider, implement the shared `MemoryProvider` protocol in `services/workspace-memory/workspace_memory/providers.py` and register it in `build_provider_index(...)` instead of bypassing the abstraction.
- When working on memory search behavior, preserve the rule that graph relations are additive context only and not the canonical memory store.

## TUI Rules

- Keep slash commands discoverable through suggestion text.
- If you add a new command, update:
  - command handling
  - suggestion/help text
  - tests when behavior is nontrivial
- The TUI is profile-based, not single-user-per-device.
- Do not reintroduce a single global local participant identity file for human users.
- Human TUI sessions should authenticate with bearer tokens and rely on server-derived participant identity.
- Keep `tui2` resilient: network/auth failures should degrade to readable system messages, not tracebacks.
- When changing collaboration bootstrap or response parsing, keep `main.py` and `tui2.py` aligned on gateway contract shapes.
- Prefer `tui2` guidance in docs when the goal is reliable mouse copy or link interaction in the terminal.

## Recommended Workflow For Agents

1. Read the relevant service, repository, and contract files first.
2. Check whether the change requires a migration.
3. If schema changes are involved, add a new file in `db/migrations`.
4. If auth or identity behavior changes, inspect `services/gateway-edge`, `services/core-collab`, `packages/contracts`, and TUI flows together.
5. If execution behavior changes, inspect `services/agent-runtime`, `services/core-collab`, and gateway event fanout together.
6. If memory behavior changes, inspect `db/migrations`, `services/workspace-memory`, `services/core-collab`, `services/gateway-edge`, and memory-related contracts together.
7. If LLM provider or secret behavior changes, inspect `llm_providers` migrations, gateway provider routes, runtime secret resolution, and local OpenBao wiring together.
8. Update code to match the migrated schema.
9. Run targeted tests.
10. Run broader tests if the change affects shared contracts or persistence.

## Key Files

- `README.md`
- `docs/db-migrations.md`
- `services/core-collab/core_collab/migrations.py`
- `services/core-collab/core_collab/repository.py`
- `services/core-collab/core_collab/kernel.py`
- `services/agent-runtime/agent_runtime/workers.py`
- `services/agent-runtime/agent_runtime/agent_task_worker.py`
- `services/agent-runtime/agent_runtime/secrets.py`
- `services/agent-runtime/agent_runtime/execution/`
- `services/workspace-memory/workspace_memory/providers.py`
- `services/workspace-memory/workspace_memory/secrets.py`
- `services/gateway-edge/gateway_edge/services/collaboration.py`
- `services/gateway-edge/gateway_edge/services/memory_provider_health.py`
- `services/gateway-edge/gateway_edge/services/llm_provider_health.py`
- `services/gateway-edge/gateway_edge/auth/`
- `services/gateway-edge/gateway_edge/services/events.py`
- `services/gateway-edge/gateway_edge/db/postgres.py`
- `packages/contracts/open_talon_contracts/llm_engines.py`
- `apps/tui/open_talon_tui/main.py`
- `apps/tui/open_talon_tui/tui2.py`

## When In Doubt

- Prefer normalization over duplication.
- Prefer explicit migrations over implicit schema mutation.
- Prefer small, reviewable changes over broad rewrites.
- Keep the repo runnable locally after each change.
