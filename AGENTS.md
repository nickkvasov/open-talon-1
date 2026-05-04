# Open Talon Agent Guide

This root guide applies to every file in this repository. Directory-specific
`AGENTS.md` files add narrower rules for the code beneath them. When a change
crosses boundaries, read every relevant nested guide before editing.

## Directory Guides

- `services/AGENTS.md`: service-wide implementation rules.
- `services/core-collab/AGENTS.md`: collaboration domain, repository, IAM, audit,
  Library, and managed-agent state.
- `services/gateway-edge/AGENTS.md`: FastAPI routes, auth, external operations,
  audit capture, provider health, and browser-facing APIs.
- `services/agent-runtime/AGENTS.md`: stateless workers, model/tool runtime,
  lease recovery, budgets, and execution events.
- `services/retriever/AGENTS.md`: Retriever ingestion, search, visual extraction,
  and embedding behavior.
- `services/workspace-memory/AGENTS.md`: memory providers, canonical memory, and
  graph projection rules.
- `services/generated-tools-builder/AGENTS.md`: Tinker generated-tool packaging.
- `packages/contracts/AGENTS.md`: shared Pydantic contracts and telemetry/LLM
  contract rules.
- `db/AGENTS.md`: migration and schema-source rules.
- `apps/admin-web/AGENTS.md`: admin console runtime config, OIDC, routing, and
  e2e expectations.
- `apps/tui/AGENTS.md`: terminal client, profile, login, and command rules.
- `infrastructure/AGENTS.md`: local stack, default endpoints, seeded credentials,
  OpenBao, Keycloak, Ollama, and live-test environment.
- `docs/AGENTS.md`: documentation maintenance rules.
- `docs/seeded-agents/AGENTS.md`: documentation rules for managed and specialist
  agents.
- `tests/AGENTS.md`: test selection, naming, and live-suite expectations.

## Project Overview

Open Talon is a local-first collaboration system where humans and agents are
first-class participants.

Main components:

- `services/gateway-edge`: FastAPI gateway for REST, SSE, WebSocket, auth, admin,
  and collaboration APIs.
- `services/core-collab`: canonical collaboration domain logic and Postgres
  repository layer.
- `services/agent-runtime`: stateless workers for task dispatch, agent-loop
  execution, tool execution, and lease reconciliation.
- `packages/contracts`: shared Pydantic contracts used across services.
- `apps/admin-web`: browser-based admin console for organizations, runtime
  overview, providers, swarm resources, workspaces, and API keys.
- `apps/tui`: terminal UI client for workspace/thread collaboration.
- `infrastructure`: local Docker-based backing services.
- `db/migrations`: source of truth for database schema changes.

Primary local flow:

1. A client talks to `gateway-edge`.
2. The gateway reads and writes Postgres and Valkey.
3. `core-collab` persists collaboration state and durable execution state such
   as `tasks`, `runs`, `run_steps`, and `tool_calls`.
4. Stateless `agent-runtime` workers claim work, execute model/tool steps, and
   publish events through Kafka.
5. Events stream back over HTTP/SSE/WebSocket.

## Repo Principles

- Document and implement the current system, not a planned future shape.
- Keep documentation, examples, comments, quickstarts, and architecture notes
  aligned with the implemented system.
- Prefer durable state, explicit ownership, and recoverable workflows over
  in-memory convenience.
- Keep tenancy, IAM, audit, and secret handling as first-class concerns.
- Keep humans and agents symmetric in collaboration surfaces, but distinct in
  identity, auth, and role binding.
- Prefer thread-native collaboration and explicit task handoff over hidden
  orchestration.
- Use the minimum coordination complexity that solves the problem.
- Read the whole vertical slice before editing: contracts, routers, services,
  repository, migrations, tests, and docs.
- Prefer small, additive, reviewable changes over broad rewrites.
- Change schema, code, tests, and docs together when behavior changes.
- Cover implemented functionality with tests, especially business rules,
  cross-service behavior, persistence flows, and regression-prone paths.
- Prefer explicit interfaces, repository methods, and typed contracts over
  implicit conventions.
- Preserve the reproducible local-first path: `./open-talon start`, `.venv`, and
  checked-in defaults should keep working after the change.
- Treat operational behavior as product behavior. Startup flow, retries, seeded
  data, env defaults, and admin surfaces all count as implementation.

## Architecture Anchors

- Treat `db/migrations` as the schema source of truth.
- Do not reintroduce monolithic in-code DDL strings.
- Postgres is the source of truth for execution state; Kafka is the wake-up and
  fanout bus.
- Do not move agent loop execution back into `gateway-edge`.
- The tenant hierarchy is `platform > organization > workspace`.
- Principal IAM is provider-neutral: the external OIDC provider handles
  authentication, and Open Talon owns authorization.
- Keycloak is the default local OIDC provider and first machine-identity
  provisioning adapter, not the source of truth for authorization.
- Organization membership and membership roles live in Postgres, not in external
  IdP claims.
- `participants` is the workspace-scoped attachment/state table.
- Human identity lives in `users`.
- External identity mappings live in `auth_identities`.
- Agent identity/configuration lives in `system_agents`.
- Machine principal linkage lives in `agent_identities`.
- `participants.user_id` and `participants.system_agent_id` are normalized
  references.
- Keep `users.user_id` distinct from `participants.participant_id` for human
  users.
- Do not duplicate agent profile/config data back into `participants`.
- Keep workspace-local state on `participants`: status, visibility scope,
  collaboration roles, capabilities, timestamps, and metadata.
- Global and organization IAM role definitions live in `iam_role_definitions`
  with separate human and agent bindings.
- Use `IAM role` only for `iam_role_definitions` and direct bindings built on
  top of them.
- Use `organization membership role` for `organization_memberships.role`.
- Use `collaboration role` for workspace-local labels in `participants.roles`.
- Use `capability` for workspace-local labels in `participants.capabilities`.
- Use `collaboration role definition` for entries in
  `workspace.metadata.role_definitions`.
- Roles and capabilities are descriptive advertisement plus discovery/routing
  signals only. They are not an authorization layer.
- Runtime execution must stay generic. Do not branch runtime behavior on
  `agent_key`, display name, role text, capability text, or metadata tags.
- Keep execution-side workspace materialization separate from collaboration
  `Workspace` models. Use `ExecutionWorkspaceRef` for executor payloads.
- Organization-scoped agents, tools, providers, repositories, and assets must
  stay inside the same organization as the consuming workspace.
- `system_agents`, `system_tools`, `llm_providers`, and `memory_providers`
  support `global` and `organization` scope.
- `git_repositories`, `workspace_assets`, and `asset_links` support `global`,
  `organization`, and `workspace` scope.
- Risky tool execution profiles require `trust_level="trusted"`:
  `workspace_access=read_write`, `network=full`, and `local_process`.
- Execution retries use `next_retry_at` with bounded backoff. Do not reintroduce
  immediate infinite lease requeue loops.
- Token budgets rely on normalized usage in `run.output["usage"]` and the
  runtime caps `OPEN_TALON_GLOBAL_DAILY_TOKEN_CAP` and
  `OPEN_TALON_WORKSPACE_DAILY_TOKEN_CAP`.

## Development Environment

- Use the repo root virtualenv: `.venv`.
- Bootstrap with:

```bash
./scripts/bootstrap-python.sh
source .venv/bin/activate
```

- Default local services, ports, credentials, and live-test environment details
  are in `infrastructure/AGENTS.md`.
- Before finishing meaningful code changes, run the most relevant tests. Test
  selection guidance lives in `tests/AGENTS.md`.

## Code Change Rules

- Preserve the normalized participant model.
- Avoid hidden schema changes in app startup code.
- Add comments for non-obvious code paths where intent, invariants,
  cross-service coupling, or operational consequences would otherwise be hard to
  infer.
- Keep tricky control flow, auth decisions, retry logic, and persistence
  assumptions documented in code.
- Prefer explicit SQL and repository methods for database changes.
- Keep migration/backfill logic separate from steady-state read/write logic when
  possible.
- Do not remove compatibility paths from live data unless the corresponding
  migration is included.
- When cleaning compatibility columns or transitional data, update both code and
  migration flow together.
- When changing provider or secret behavior, keep `gateway-edge`, `core-collab`,
  `agent-runtime`, and docs aligned on persistent provider definitions and
  OpenBao-backed secret resolution.

## Recommended Workflow

1. Read the relevant service, repository, and contract files first.
2. Check whether the change requires a migration.
3. If schema changes are involved, add a new file in `db/migrations`.
4. If auth or identity behavior changes, inspect `services/gateway-edge`,
   `services/core-collab`, `packages/contracts`, and TUI flows together.
5. If execution behavior changes, inspect `services/agent-runtime`,
   `services/core-collab`, and gateway event fanout together.
6. If memory behavior changes, inspect `db/migrations`,
   `services/workspace-memory`, `services/core-collab`, `services/gateway-edge`,
   and memory-related contracts together.
7. If LLM provider or secret behavior changes, inspect `llm_providers`
   migrations, gateway provider routes, runtime secret resolution, and local
   OpenBao wiring together.
8. If Retriever ingestion or visual extraction changes, inspect
   `services/retriever`, retrieval contracts, retrieval repository/kernel
   methods, MinIO asset storage, pgvector persistence, and LLM provider
   resolution together.
9. If operational-agent behavior changes, inspect gateway bootstrap, IAM
   bindings, MCP allowlists, `agent_identities`, workspace participant
   attachment, and runtime task claiming together.
10. Before merging local work into `main`, check `git branch --no-merged main`
    and the ancestry between candidate branches.
11. Keep the worktree clean before branch switching or merging; do not hide
    unrelated user edits in a merge.
12. Update code to match the migrated schema.
13. Run targeted tests.
14. Run broader tests if the change affects shared contracts or persistence.

## When In Doubt

- Prefer normalization over duplication.
- Prefer explicit migrations over implicit schema mutation.
- Prefer small, reviewable changes over broad rewrites.
- Keep the repo runnable locally after each change.
