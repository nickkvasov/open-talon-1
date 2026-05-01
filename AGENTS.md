# Open Talon Agent Guide

This file is for coding agents working in this repository, including Codex, Claude Code, and similar tools.

## Project Overview

Open Talon is a local-first collaboration system where humans and agents are first-class participants.

Main components:

- `services/gateway-edge`: FastAPI gateway for REST, SSE, WebSocket, auth, admin, and collaboration APIs
- `services/core-collab`: canonical collaboration domain logic and Postgres repository layer
- `services/agent-runtime`: stateless workers for task dispatch, agent-loop execution, tool execution, and lease reconciliation
- `packages/contracts`: shared Pydantic contracts used across services
- `apps/admin-web`: browser-based admin console for organizations, runtime overview, providers, swarm resources, workspaces, and API keys
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

## Design Principles

- Document and implement the current system, not a planned future shape.
- Always keep documentation current with the implemented system.
- Always reflect the current status of the system in docs, examples, comments, and architecture notes.
- Prefer durable state, explicit ownership, and recoverable workflows over in-memory convenience.
- Keep tenancy, IAM, audit, and secret handling as first-class concerns rather than bolt-ons.
- Keep humans and agents symmetric in collaboration surfaces, but distinct in identity, auth, and role binding.
- Prefer thread-native collaboration and explicit task handoff over hidden orchestration.
- Use the minimum coordination complexity that solves the problem; do not introduce extra agent choreography without a concrete need.

## Software Development Approach

- Read the whole vertical slice before editing: contracts, routers, services, repository, migrations, tests, and docs.
- Prefer small, additive, reviewable changes over broad rewrites.
- Change schema, code, tests, and docs together when behavior changes.
- Keep repository documentation, service READMEs, quickstarts, and architecture notes current as part of normal development work, not as a later cleanup step.
- Cover implemented functionality with comprehensive tests, especially for business rules, cross-service behavior, persistence flows, and regression-prone paths.
- Prefer explicit interfaces, repository methods, and typed contracts over implicit conventions.
- Preserve a reproducible local-first developer path: `./open-talon start`, `.venv`, and checked-in defaults should keep working after the change.
- Treat operational behavior as product behavior. Startup flow, retries, seeded data, env defaults, and admin surfaces all count as implementation, not just wiring.

## Important Architecture Rules

- Treat `db/migrations` as the schema source of truth.
- Do not reintroduce monolithic in-code DDL strings.
- Postgres is the source of truth for execution state; Kafka is the wake-up and fanout bus.
- Do not move agent loop execution back into `gateway-edge`.
- Principal IAM is provider-neutral: the external OIDC provider handles authentication, and Open Talon owns authorization.
- The tenant hierarchy is `platform > organization > workspace`.
- Keycloak is the default local OIDC provider and first machine-identity provisioning adapter, not the source of truth for authorization.
- Organization membership and membership roles live in Postgres, not in external IdP claims.
- `participants` is a workspace-scoped attachment/state table.
- Human identity lives in `users`.
- External identity mappings live in `auth_identities`.
- Agent identity/configuration lives in `system_agents`.
- Machine principal linkage lives in `agent_identities`.
- Global and organization IAM role definitions live in `iam_role_definitions` with separate human and agent bindings.
- Operational/system-wide agents and managed specialist agents advertise their purpose through normal agent fields such as `display_name`, `role`, and `capabilities`. Do not add extra operational classification columns unless there is a strict product or authorization need.
- IAM role bindings, project access, workspace participant attachment, and MCP/tool allowlists are the authority for operational agents; role text is descriptive, not authorization.
- Runtime execution must stay generic. Do not branch runtime behavior on `agent_key`, display name, role text, capability text, or metadata tags; behavioral specialization belongs in agent definitions, harnesses, interaction contracts, task payloads, IAM/project/workspace bindings, publication-review records, and tool/MCP allowlists.
- Roles and capabilities are descriptive advertisement plus discovery/routing signals only. They are not an authorization layer and must not be the hidden source of agent-specific runtime behavior.
- Use `IAM role` only for `iam_role_definitions` and the direct bindings built on top of them.
- Use `organization membership role` for `organization_memberships.role`.
- Use `collaboration role` for workspace-local labels in `participants.roles` that humans and agents assume for routing and discovery.
- Use `capability` for workspace-local labels in `participants.capabilities`.
- Use `collaboration role definition` for entries in `workspace.metadata.role_definitions`.
- `participants.user_id` and `participants.system_agent_id` are the normalized references.
- Keep `users.user_id` distinct from `participants.participant_id` for human users.
- Do not duplicate agent profile/config data back into `participants`.
- Keep workspace-local state on `participants`: status, visibility scope, collaboration roles, capabilities, timestamps, and metadata.
- Keep workspace `role_definitions` as collaboration-role metadata only. Do not use them as an authorization layer.
- Humans and agents share the same permission names, but not the same global or organization role bindings.
- Keep execution-side workspace materialization separate from collaboration `Workspace` models. Use `ExecutionWorkspaceRef` for executor payloads.
- Authenticated human identity should be derived in `gateway-edge` from OIDC auth context, not trusted from client-provided actor fields.
- Authenticated machine identity should be derived in `gateway-edge` from OIDC client credentials and `agent_identities`, not from client-provided actor fields.
- Require organization membership before resolving workspace actors for authenticated humans.
- Keep OIDC workspace reads membership-scoped. Non-members should get `404` for workspace-scoped reads rather than `403`.
- Keep OIDC organization reads membership-scoped. Non-members should get `404` for organization-scoped reads rather than `403`.
- `/v1/me` is human-only; machine principals should use the IAM and collaboration APIs directly.
- Global system-definition, global publish, provider-management, and IAM-management routes require the matching global IAM permission unless the request is coming through an existing operator/system-auth path or bootstrap platform-admin access.
- Organization CRUD and organization-scoped management routes require the relevant organization permission from baseline membership roles or explicit IAM role bindings, unless the caller is a platform admin.
- Workspace role-definition changes, workspace participant-management, workspace tool management, workspace Git repository creation, and workspace asset publishing require the matching workspace-scoped IAM permission plus participant attachment.
- Agent workspace visibility and runtime claimability must account for workspace participant attachment, not only project access bindings. `participants` is the workspace-local attachment/state record for humans and agents.
- Organization-scoped agents, tools, providers, repositories, and assets must stay inside the same organization as the consuming workspace.
- Managed operational contexts must be seeded and repaired idempotently: `System Base / Administration / System Operations` for platform operations, and each non-system organization's `Administration / Organization Operations` context for organization operations.
- Managed operational-agent identity bootstrap must validate live OIDC client-credentials authentication and repair stale or missing Keycloak clients/OpenBao secrets after local stack restarts or upgrades.
- Tinker-generated tools may publish to `global` or `organization` scope, but approval publishes into the system catalog only.
- Tinker revision approval requires `tool_generation.review` plus `tool_catalog.write` in the target publication scope.
- Tinker-generated tools must not be auto-attached to a workspace as part of approval; manual workspace attachment is a separate action.
- Tinker authoring/build helpers are agent-internal tools and must not be exposed through `workspace_tools` or the normal workspace catalog.
- Treat `collab_event_log` and `audit_event_ledger` as separate concerns: collaboration fanout vs. compliance/investigation.
- `audit_event_ledger` is append-only in steady-state code; do not add update/delete flows for audit rows.
- Audit integrity depends on `chain_partition`, `chain_sequence`, `prev_hash`, and `event_hash`; preserve chain semantics when changing audit writes.
- Organization audit chains use `organization:<id>` partitions; workspace chains stay `workspace:<id>` and platform/global chains stay `global`.
- Audit v1 is metadata-only. Do not store raw bearer tokens, prompt bodies, tool arguments, or message bodies inline in audit metadata.
- Keep Postgres as the canonical audit ledger unless the task explicitly redesigns audit authority.
- Keep non-canonical audit surfaces behind provider boundaries. Do not hard-wire Kafka, ClickHouse, MinIO, Langfuse, HyperDX, or other backend details back into service orchestration.
- Local audit provider defaults are Kafka for relay, ClickHouse for projection, and MinIO for archive/export/checkpoint storage.
- Runtime observability is provider-backed. Langfuse and OTLP-compatible sinks such as HyperDX are integrations, not architectural constants.
- Use `packages/contracts/open_talon_contracts/telemetry.py` for shared telemetry context and redaction behavior instead of inventing per-service variants.
- LLM providers are persistent records in `llm_providers`; do not reintroduce env-defined engine registries.
- Agents and Retriever visual extraction must resolve generation/vision models through the shared LLM provider abstraction: `llm_providers`, `packages/contracts/open_talon_contracts/llm_engines.py`, `packages/contracts/open_talon_contracts/llm_runtime.py`, and the runtime resolver in `services/agent-runtime`.
- Retriever embeddings are separate from generation/vision LLMs. Keep embedding model/provider selection on the Retriever embedding-provider abstraction because embeddings have different request shape, dimensions, vector persistence, and pgvector indexing semantics.
- Retriever visual extraction is a vision-LLM workload and should use the shared LLM engine registry. `RetrievalProfile.vision_provider_key` can refer to an engine id such as `local-ollama` or a provider key such as `openai` or `anthropic`; organization-scoped retrieval should include global plus same-organization LLM providers.
- Retriever visual extraction must prove document understanding, not only object recognition. Chart tests should assert semantic facts such as chart title, labels, approximate values, peaks/highest values, trends, or comparisons rather than accepting vague phrases like "there is a chart."
- Keep Retriever visual tests realistic but bounded. Prefer public, stable, rights-clear PDF fixtures with documented source/rights, then derive the relevant page or crop at test runtime instead of sending an entire multi-page report through a local vision model unless the test is explicitly about throughput.
- Library is store-first and Retriever indexing is explicit. Adding uploads, Markdown/text, webpage scraps, images, or diagrams to a library must not enqueue ingestion unless the caller invokes the library index route or Retriever plugin tool.
- Library/Retriever scope rules must be tested together: organization, project, and workspace libraries can reuse slugs across different owners, workspace search includes workspace libraries plus explicitly attached organization/project libraries, and cross-organization or cross-project attachments must be rejected.
- Keep the storage taxonomy explicit: MinIO/object storage is data storage for immutable bytes and snapshots; Library plus Retriever indexes are information storage for retained, indexed, and vectorized pieces; research dossiers are knowledge storage for concept organization, claims, contradictions, gaps, methods, synthesis, provenance, and navigation.
- Dossier notebooks are external provider projections owned by Open Talon control-plane state. Open Talon stores lifecycle, source provenance, IAM, audit, graph metadata, and sync state in Postgres; XWiki stores the navigable concept repository through the `DossierNotebookProvider` abstraction and must not become the authorization or audit authority.
- `Methodologist` is a managed global specialist agent for evidence-backed methodology extraction and workspace template design. Keep it a normal `system_agents` definition with harness and interaction contract behavior; do not add Methodologist-specific runtime branches.
- Methodologist outputs should separate source-grounded methodology basis, methodics, methods, tools, actors, and workspace templates. Source-derived claims need cited retrieval/source evidence, while inferred tools or implementation ideas must be labeled as inference or ideation.
- `Conductor` is a separate managed global specialist for active workspace methodics execution. It must be explicitly attached through normal workspace agent attachment, and methodics execution must be explicitly started; workspace creation, Methodologist drafts, and methodics APIs must not auto-attach it.
- Workspaces without attached Conductor have no active methodics execution loop. Starting execution must return a clear conflict if Conductor is not attached; passive `WorkspaceHarness.methodics` remains guidance only.
- Conductor uses dedicated `methodic_*` execution tables, targets only methodics task kinds, and sets `normal_message_fanout=false`. Start/cancel and resource request approval/rejection are human-gated. Conductor can read execution state, create assignments, evaluate DoD pass/fail/rework, advance steps, complete final reports, and create pending resource requests through its managed internal MCP binding, but its private allowlist must not include human-gated methodics control tools.
- Local Ollama model roles are configured through `OPEN_TALON_DEFAULT_REASONING_MODEL`, `RETRIEVER_DEFAULT_EMBEDDING_MODEL`, and `RETRIEVER_DEFAULT_VISION_MODEL`. `REQUIRED_MODELS` is only an explicit bootstrap override for the Ollama service, not the canonical place to duplicate model roles.
- Local live tests that use Ollama must use the infrastructure Ollama service from `infrastructure/docker-compose.yaml`; do not rely on a separately running host Ollama with different models.
- Anchor and Retriever visual live tests are real model-path tests. On developer machines where the pinned default `gemma4:31b` cannot return within the live-test window, run the stack with another explicit non-`latest` local model tag and record that model choice in the test report instead of weakening assertions. Because `./open-talon` sources `infrastructure/.env`, update that local env file or the persisted local `llm_providers` row before trusting a shell-prefix override for `OPEN_TALON_DEFAULT_REASONING_MODEL`; do the same for `RETRIEVER_DEFAULT_VISION_MODEL` when Retriever visual tests need a smaller model.
- Memory providers are persistent records in `memory_providers`; do not hardcode provider definitions in application logic after bootstrapping.
- `system_agents`, `system_tools`, `llm_providers`, and `memory_providers` support `global` and `organization` scope; `git_repositories`, `workspace_assets`, and `asset_links` support `global`, `organization`, and `workspace` scope.
- Local OpenBao uses persistent file storage under `infrastructure/data/openbao`; do not assume `docker compose down` clears local secrets.
- Postgres is the canonical memory store. Mem0 and optional graph backends such as Memgraph are derived retrieval projections, not the source of truth.
- Risky tool execution profiles require `trust_level="trusted"`: `workspace_access=read_write`, `network=full`, and `local_process`.
- Execution retries use `next_retry_at` with bounded backoff. Do not reintroduce immediate infinite lease requeue loops.
- Token budgets rely on normalized usage in `run.output["usage"]` and the runtime caps `OPEN_TALON_GLOBAL_DAILY_TOKEN_CAP` and `OPEN_TALON_WORKSPACE_DAILY_TOKEN_CAP`.

## Database Rules

- Create a new migration for every schema or backfill change.
- Never edit an old migration after it has been applied in a shared environment.
- Prefer additive migrations and explicit backfills.
- Keep migrations SQL-first and reviewable.
- Use `./scripts/dbmate.sh new <name>` to create a migration.
- Use `./scripts/dbmate.sh up` to apply pending migrations locally.
- Use `./scripts/dbmate.sh status` to inspect applied, pending, and local `recorded-only` migration rows before assuming schema drift is a code problem.
- `./scripts/dbmate.sh` is the canonical manual migration entrypoint. It is a compatibility wrapper over the Python runner, not a requirement to install or use external `dbmate`.
- Startup/tests also apply pending migrations through the Python migration runner in `services/core-collab/core_collab/migrations.py`.
- The Python migration runner supports legacy plain SQL files and dbmate-style `-- migrate:up` / `-- migrate:down` files, but application/startup/test migration application must execute only the up block.
- A `recorded-only` migration in local status usually means that historical local state has a row in `schema_migrations` for a file no longer present. Treat it as a local-drift signal to understand, not as permission to edit old migrations.

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
- Default local Keycloak adapter:
  - base URL: `http://127.0.0.1:8081`
  - realm: `open-talon`
  - TUI client: `open-talon-tui`
  - browser client: `open-talon-web`
- Default local OpenBao:
  - base URL: `http://127.0.0.1:8200`
  - root token: `root`
  - persistent data dir: `infrastructure/data/openbao`
- Optional local Memgraph for Mem0 graph mode:
  - bolt URL: `bolt://127.0.0.1:7688`
  - start it locally with `./open-talon start --memgraph`
- Local infrastructure defaults are documented in `infrastructure/.env.example`.

Useful local endpoints and credentials:

- Gateway: `http://127.0.0.1:8000`
- Gateway docs: `http://127.0.0.1:8000/docs`
- Admin web dev server: `http://localhost:5173`
- Audit API base: `http://127.0.0.1:8000/v1/audit`
- Kafka: `localhost:9092`
- Valkey: `localhost:6379`
- Keycloak: `http://127.0.0.1:8081`
  - admin console: `admin` / `admin`
  - realm: `open-talon`
  - issuer: `http://127.0.0.1:8081/realms/open-talon`
  - OpenID config: `http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration`
  - realm users: `admin` / `admin123`, `admin2` / `admin223`, `supervisor` / `supervisor123`, `supervisor2` / `supervisor223`, `user1` / `user12345`, `user2` / `user22345`
- OpenBao: `http://127.0.0.1:8200`
  - root token: `root`
- pgAdmin: `http://127.0.0.1:5050`
  - login: `admin@local.dev` / `admin`
- Langfuse: `http://127.0.0.1:3000`
  - login: `admin@example.com` / `admin123456`
- Langfuse worker: `localhost:3030`
- Ollama: `http://127.0.0.1:11434`
- MinIO API: `http://127.0.0.1:9090`
- MinIO console: `http://127.0.0.1:9091`
  - login: `minio` / `miniosecret`
- Forgejo: `http://127.0.0.1:3001`
  - admin: `forgejo` / `forgejo123`
- Forgejo SSH: `localhost:2222`
- ClickHouse HTTP: `http://127.0.0.1:8123`
- ClickHouse native: `localhost:9000`
  - login: `langfuse` / `langfuse`
- Memgraph bolt when started with `./open-talon start --memgraph`: `localhost:7688`
- Memgraph HTTP when started with `./open-talon start --memgraph`: `http://127.0.0.1:7444`
- Memgraph credentials when started with `./open-talon start --memgraph`: `memgraph` / `memgraph`
- Langfuse Postgres DB: `langfuse_db`
- Valkey password: `langfuse-dev-secret`
- Optional HyperDX profile:
  - UI: `http://127.0.0.1:8080`
  - OTLP gRPC: `127.0.0.1:4317`
  - OTLP HTTP: `127.0.0.1:4318`

## Testing Expectations

Before finishing meaningful code changes, run the most relevant tests.

Meaningful functionality changes should include comprehensive automated coverage for the affected behavior, not just superficial smoke checks.

Common commands:

```bash
pytest -q
pytest tests/gateway-edge -q
pytest tests/core-collab -q
pytest tests/tui -q
pytest tests/business-cases -q
pytest -m integration tests/infrastructure/test_infrastructure.py -v -s
./scripts/run-live-tests.sh --list
./scripts/run-live-tests.sh all
```

Use `./scripts/run-live-tests.sh` for coordinated live runs. It provides
fractions such as `core`, `agents`, `providers`, `default-stack`, `web-search`,
and `knowledge`, and it owns the required environment gates and stack profiles
for default, web-search, and XWiki live suites.

If a change touches schema, repository, participant hydration, routing, or migrations:

- run relevant `core-collab` tests
- run relevant `gateway-edge` tests
- run migration-script coverage such as `tests/scripts/test_system_scripts.py` and `tests/core-collab/test_migration_files.py` when migration tooling or migration-file parsing changes
- run `./scripts/dbmate.sh up` against the local stack when schema changes need to be applied before live tests
- run full `pytest -q` when feasible

If a change touches layered memory, memory providers, Mem0, or graph-memory support:

- inspect `services/workspace-memory`, `services/core-collab`, `services/gateway-edge`, and `packages/contracts` together
- verify canonical persistence and provider projection remain coherent together
- run relevant `tests/workspace-memory`
- run relevant memory route tests in `tests/gateway-edge`
- keep `infrastructure/.env.example`, `infrastructure/docker-compose.yaml`, and `open-talon` aligned if graph mode behavior changes

If a change touches LLM provider resolution, local model defaults, Retriever extraction, or model secret handling:

- inspect `packages/contracts/open_talon_contracts/llm_engines.py`, `packages/contracts/open_talon_contracts/llm_runtime.py`, `services/agent-runtime/agent_runtime/runtime.py`, `services/core-collab/core_collab/system_defaults.py`, `services/gateway-edge/gateway_edge/services/llm_provider_health.py`, and `services/retriever`
- keep `llm_providers` as the source of truth for generation and vision provider definitions; do not add parallel env-only provider registries
- verify agent runtime resolution for global and organization-scoped providers when tenant behavior changes
- verify Retriever visual extraction uses the LLM engine registry while Retriever embeddings remain on the embedding-provider path
- verify Retriever visual/chart extraction against realistic PDFs with source/rights documented under `tests/fixtures` when chart understanding changes; tests should assert chart semantics such as labels, values, and highest/peak/trend relationships
- keep local-vision live tests bounded by extracting the specific page/crop under test from larger PDFs; full-document visual extraction with `gemma4:31b` can take minutes and should be reserved for explicit throughput or coverage tests
- account for the always-running `talon-retriever-worker` during live tests. Tests that process a specific ingestion job directly must claim that exact queued job first, or wait if the stack worker already claimed it, instead of processing the same job twice.
- keep retrieval search/hit persistence transactionally consistent when chunks can be replaced. Search results that are persisted into `retrieval_hits` should be selected and written in one transaction with appropriate chunk locking or revalidation so stale chunk ids cannot violate hit foreign keys.
- keep `infrastructure/.env.example`, `infrastructure/docker-compose.yaml`, `infrastructure/ollama-entrypoint.sh`, `README.md`, `docs/system-api-reference.md`, `docs/system-quickstart.md`, and `services/retriever/README.md` aligned with model/provider defaults
- run `tests/agent-runtime/test_runtime.py`, `tests/retriever`, relevant `tests/core-collab/test_agent_contracts.py`, and `tests/gateway-edge/test_llm_provider_health.py`
- run `OPEN_TALON_RUN_RETRIEVER_LIVE=1 pytest -m integration tests/infrastructure/test_retriever_live_system.py -q -s` against the real local stack when PDF parsing, image understanding, OCR-like extraction, chart extraction, Ollama model roles, or Retriever ingestion behavior changes
- live Retriever tests may need local-service access to Docker Compose Postgres, MinIO, and Ollama; if sandboxed execution fails with a local network or Docker socket permission error, rerun the same command with the required escalation rather than weakening the test

If a change touches Library, Retriever plugin tools, library attachments, project retrieval scope, or library item storage:

- inspect `packages/contracts`, `services/core-collab`, `services/gateway-edge`, `services/agent-runtime`, `db/migrations`, `apps/admin-web`, and the managed System Plugin defaults together
- keep Library and Retriever as separate managed System Plugins; Library stores durable reference items, and Retriever creates corpora/sources/jobs only through explicit indexing
- keep the library indexing policy testable outside the kernel when possible; corpus reuse, source id determinism, source-version/job binding, and payload metadata should have direct tests
- verify `DELETE /v1/libraries/{library_id}` works for authenticated no-body clients as well as compatibility callers that still send an actor body
- run `tests/core-collab/test_library_kernel.py`, `tests/gateway-edge/test_library_routes.py`, `tests/gateway-edge/test_mcp.py`, `tests/gateway-edge/test_system_plugins.py`, and relevant repository migration tests
- run `OPEN_TALON_RUN_SYSTEM_PLUGINS_LIVE=1 pytest -m integration tests/infrastructure/test_system_plugins_live_system.py -q -s` and `OPEN_TALON_RUN_RETRIEVER_LIVE=1 pytest -m integration tests/infrastructure/test_retriever_live_system.py -q -s` against the real local stack when plugin registration, sync, attachment, indexing, or retrieval search changes

If a change touches OIDC auth, Keycloak wiring, or TUI login/profile behavior:

- run relevant `gateway-edge` auth tests
- run `tests/gateway-edge/test_iam.py`
- run `tests/gateway-edge/test_identity_sync.py`
- run `tests/tui`
- verify docs and env defaults stay aligned with the actual login flow

If a change touches the admin web, browser OIDC login, admin-browser routing, or deployed browser config:

- inspect `apps/admin-web`, `services/gateway-edge`, and Keycloak defaults together
- keep `apps/admin-web/public/runtime-config.json`, `apps/admin-web/README.md`, `README.md`, and `docs/system-quickstart.md` aligned
- run `npm run build` in `apps/admin-web`
- run admin-web e2e only with the local stack running; several live infrastructure suites stop the stack in teardown, so run `./open-talon start` again before `npm run test:e2e` if Keycloak or gateway was just torn down
- admin e2e tests that remove or change organization membership should not mutate the currently signed-in admin user; sign in a secondary seeded user in a separate browser context first so the backend user row exists, then exercise membership changes on that secondary user
- add a random suffix to browser-created names in addition to timestamps when parallel e2e workers can create resources in the same millisecond
- run `npm run test:e2e` in `apps/admin-web` when browser behavior or destructive admin flows change

If a change touches workspace authz, global admin routes, or workspace membership filtering:

- run relevant `tests/gateway-edge/test_workspaces.py`
- run relevant `tests/gateway-edge/test_admin.py`
- run relevant `tests/gateway-edge/test_iam.py`
- run relevant organization route and org-membership tests when tenant boundaries changed
- make sure non-member workspace reads return `404`
- make sure non-member organization reads return `404`
- make sure global control-plane OIDC reads/writes require the intended IAM permission or platform-admin bootstrap access

If a change touches audit logging, audit APIs, event relays, or runtime failure reporting:

- inspect `packages/contracts`, `services/core-collab`, `services/gateway-edge`, and `services/agent-runtime` together
- verify Postgres remains the canonical audit store even if Kafka or ClickHouse is unavailable
- keep relay/projector failures non-blocking for canonical audit writes
- verify provider selection and no-op provider behavior where relevant
- keep shared telemetry/redaction behavior aligned between gateway audit and runtime observability
- run at least one gateway audit test and one repository chain-verification test
- verify `organization:<id>` and `workspace:<id>` chains both verify when tenant-aware audit behavior changes
- keep MinIO export/checkpoint behavior aligned with docs and env defaults

If a change touches execution lease recovery, budget enforcement, or runtime overview behavior:

- run relevant `tests/core-collab/test_agent_contracts.py`
- run relevant `tests/agent-runtime/test_workers.py`
- verify retry backoff, terminal failure propagation, and `budget_exhausted` handling together
- keep `docs/system-quickstart.md`, `README.md`, and `infrastructure/.env.example` aligned with any new operator knobs or endpoints

If a change touches Tinker, tool generation, generated-tool approval, or internal tool execution:

- inspect `packages/contracts`, `services/core-collab`, `services/gateway-edge`, `services/agent-runtime`, `apps/admin-web`, and `apps/tui` together
- preserve the rule that approval publishes only to the system catalog, not to `workspace_tools`
- preserve the rule that approval requires `tool_generation.review` and `tool_catalog.write` in the publication scope
- verify global and organization-scoped publication paths separately when scope behavior changes
- keep Tinker-only helper tools private to Tinker
- run `tests/core-collab/test_agent_contracts.py`
- run `tests/gateway-edge/test_tool_generation.py`
- run `tests/business-cases/test_tinker_tool_generation.py`
- run `tests/agent-runtime/test_execution.py` when local helper execution or execution backends changed
- Tinker live tests should disable workspace topic moderation unless the test is specifically about Anchor. Otherwise a slow or unavailable local moderation model can obscure the generated-tool/runtime behavior the Tinker test is meant to prove.
- run `pytest -m integration tests/infrastructure/test_tinker_live_system.py -q -s` when the end-to-end Tinker/runtime path changes and the configured `OPEN_TALON_DEFAULT_REASONING_MODEL` is available in the infrastructure Ollama service

If a change touches operational agents, managed administration contexts, agent-private MCP bindings, or control-plane MCP operations:

- inspect `system_agents`, `agent_identities`, IAM bindings, MCP server/binding code, repository workspace visibility, runtime task claiming, and gateway bootstrap together
- keep agent purpose in `display_name`, `role`, and `capabilities`; avoid new classification fields unless they are strictly required
- keep managed contexts idempotent and deterministic: `System Base / Administration / System Operations` plus every organization's `Administration / Organization Operations`
- any code path that creates an organization and its managed `Organization Operations` workspace must attach the global Anchor participant immediately. If a prior path could have created workspaces without Anchor, add an explicit migration/backfill instead of relying on manual repair.
- verify global `Steward`, organization-scoped `Curator`, and workspace-attached `Anchor` paths when changing shared operator or publication-review behavior
- keep deterministic live harnesses under `tests/infrastructure/operational_agents_live` so new operational agents can add focused test modules instead of growing one monolithic file
- deterministic live harnesses that call internal MCP tools must pass the explicit `_mcp_scope` expected by the gateway session; missing scope often appears as tools not being visible despite correct allowlists
- after changing live gateway routes, bootstrap, or agent definitions, restart the local stack before trusting a plain live-test `404`; a stale gateway can look like an authorization or routing regression
- live tests that patch managed-agent endpoints or local Keycloak client settings must restore them in `finally` blocks
- keep operational-agent live tests bounded and deterministic; use harnesses to prove control-plane contracts instead of relying on local model quality unless model behavior is the feature under test
- run `tests/core-collab/test_agent_contracts.py` and relevant gateway IAM/MCP tests
- run `OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 pytest -m integration tests/infrastructure/operational_agents_live -q -s` against the real local stack for end-to-end identity, MCP, runtime, and durable `tool_calls` coverage
- run `OPEN_TALON_RUN_ANCHOR_LIVE=1 pytest -m integration tests/infrastructure/anchor_live_system -q -s` when publication review, Anchor, or workspace topic-moderation behavior changes
- live tests may need local-service access to Keycloak, OpenBao, and gateway; if sandboxed execution fails with a local network `Operation not permitted`, rerun the same test command with the required escalation rather than weakening the test

If a change touches Methodologist, Conductor, methodics execution, or other managed specialist agents:

- keep the specialist as a normal `system_agents` record with `agent_key`, `display_name`, `role`, `capabilities`, `harness`, and `interaction_contract`; do not branch runtime behavior on the agent key
- make the response contract explicit enough that outputs can be translated into existing Open Talon structures such as `WorkspaceHarness.methodology`, `methodics`, `execution_rules`, participants, tools, retrieval corpora, and artifacts
- require cited source evidence for extraction claims and explicit labels for inferred or ideated implementation tools
- keep Conductor opt-in per workspace: no auto-attach, no normal message fanout, and no active methodics loop unless a start API/MCP call creates execution state
- resolve the attached methodics execution agent from the participant/task-routing contract, especially `accepted_task_kinds` containing `methodics_execution_start`; do not hard-code Conductor UUIDs, `agent_key`, display name, role text, capability text, or metadata tags in runtime behavior
- keep Conductor's private MCP allowlist limited to agent-appropriate execution reads and pending resource-request creation; human-gated operations such as start, cancel, approve, and reject must be exercised with a human principal
- Conductor live coverage proves attach/start gating, internal MCP reads, assignment creation, DoD pass/fail/rework evaluation, step progression, final execution report creation, pending resource-request creation, human approve/reject/cancel tools, active-step cancellation, and normal-message fanout isolation.
- run `tests/core-collab/test_agent_contracts.py` and relevant repository migration tests when seeded specialist definitions change

## Code Change Rules

- Preserve the normalized participant model.
- Avoid hidden schema changes in app startup code.
- Add comprehensive comments for non-obvious code paths so intent, invariants, cross-service coupling, and operational consequences are clear to the next reader.
- Do not leave tricky control flow, auth decisions, retry logic, or persistence assumptions undocumented in code.
- Keep the admin web deployable from a subpath; do not reintroduce root-only router, asset, or OIDC redirect assumptions.
- Keep browser runtime config runtime-loadable; do not move admin-web environment selection back to build-time-only config.
- Keep gateway routers thin; prefer logic in services/kernel/repository layers.
- Keep audit capture in dedicated middleware/services instead of scattering ad hoc audit inserts through routers.
- Keep execution orchestration in Open Talon code and isolate only the backend executor behind the execution interface.
- Prefer explicit SQL and repository methods for database changes.
- Keep migration/backfill logic separate from steady-state read/write logic when possible.
- Do not remove compatibility paths from live data unless the corresponding migration is included.
- When cleaning compatibility columns or transitional data, update both code and migration flow together.
- When changing worker behavior, cover both durable state transitions and emitted Kafka/thread events in tests.
- Preserve `next_retry_at`-based scheduling and bounded retry semantics when changing lease reconciliation or claim logic.
- Preserve normalized `run.output["usage"]` payloads when changing model runtime or provider integrations.
- When changing provider or secret behavior, keep `gateway-edge`, `core-collab`, `agent-runtime`, and docs aligned on persistent provider definitions and OpenBao-backed secret resolution.
- When adding or changing audit or observability integrations, implement or update the provider/registry layer instead of branching directly on vendor behavior in service logic.
- When adding a new memory provider, implement the shared `MemoryProvider` protocol in `services/workspace-memory/workspace_memory/providers.py` and register it in `build_provider_index(...)` instead of bypassing the abstraction.
- When working on memory search behavior, preserve the rule that graph relations are additive context only and not the canonical memory store.

## Documentation Maintenance

- Keep [`README.md`](./README.md), [`docs/system-api-reference.md`](./docs/system-api-reference.md), [`docs/system-quickstart.md`](./docs/system-quickstart.md), and [`docs/iam.md`](./docs/iam.md) aligned with the implemented system.
- Always keep documentation current as part of the same change that updates system behavior.
- When changing routes, auth behavior, permissions, startup flow, ports, env vars, default credentials, seeded resources, or browser runtime config, update the relevant docs in the same change.
- Always describe the current status of the system rather than planned or obsolete behavior unless a document is explicitly marked historical.
- Do not describe placeholder packages or planned services as active runtime components.
- Keep documentation focused on implemented behavior, current configuration, and the current API surface.
- Prefer linking the exact source files that define behavior when prose could drift or become ambiguous.

## TUI Rules

- Keep slash commands discoverable through suggestion text.
- If you add a new command, update:
  - command handling
  - suggestion/help text
  - tests when behavior is nontrivial
- Keep `tui2` and `user-client` organization-selection flows aligned with the org-aware workspace APIs.
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
8. If Retriever ingestion or visual extraction changes, inspect `services/retriever`, retrieval contracts, retrieval repository/kernel methods, MinIO asset storage, pgvector persistence, and LLM provider resolution together.
9. If operational-agent behavior changes, inspect gateway bootstrap, IAM bindings, MCP allowlists, `agent_identities`, workspace participant attachment, and runtime task claiming together.
10. Before merging local work into `main`, check `git branch --no-merged main` and the ancestry between candidate branches. If one unmerged branch already contains another, a single `git merge --ff-only <tip-branch>` into `main` is the cleanest way to bring both in.
11. Keep the worktree clean before branch switching or merging; do not hide unrelated user edits in a merge.
12. Update code to match the migrated schema.
13. Run targeted tests.
14. Run broader tests if the change affects shared contracts or persistence.

## Key Files

- `README.md`
- `apps/admin-web/README.md`
- `apps/admin-web/public/runtime-config.json`
- `apps/admin-web/src/config/runtime.js`
- `apps/admin-web/src/providers/AuthProvider.jsx`
- `docs/db-migrations.md`
- `docs/system-quickstart.md`
- `docs/operational-agents-real-life-test-protocol.md`
- `docs/tinker-tool-generation.md`
- `services/core-collab/core_collab/migrations.py`
- `services/core-collab/core_collab/repository.py`
- `services/core-collab/core_collab/kernel.py`
- `services/agent-runtime/agent_runtime/workers.py`
- `services/agent-runtime/agent_runtime/runtime.py`
- `services/agent-runtime/agent_runtime/agent_task_worker.py`
- `services/agent-runtime/agent_runtime/config.py`
- `services/agent-runtime/agent_runtime/secrets.py`
- `services/agent-runtime/agent_runtime/execution/`
- `services/retriever/retriever/llm.py`
- `services/retriever/retriever/worker.py`
- `services/retriever/retriever/config.py`
- `services/retriever/README.md`
- `infrastructure/docker-compose.yaml`
- `infrastructure/ollama-entrypoint.sh`
- `infrastructure/.env.example`
- `services/workspace-memory/workspace_memory/providers.py`
- `services/workspace-memory/workspace_memory/secrets.py`
- `services/gateway-edge/gateway_edge/services/collaboration.py`
- `services/gateway-edge/gateway_edge/services/memory_provider_health.py`
- `services/gateway-edge/gateway_edge/services/llm_provider_health.py`
- `services/gateway-edge/gateway_edge/auth/`
- `services/gateway-edge/gateway_edge/services/events.py`
- `services/gateway-edge/gateway_edge/services/audit.py`
- `services/gateway-edge/gateway_edge/services/audit_providers.py`
- `services/gateway-edge/gateway_edge/audit_middleware.py`
- `services/gateway-edge/gateway_edge/db/postgres.py`
- `services/gateway-edge/gateway_edge/routers/admin.py`
- `apps/admin-web/src/pages/ToolGenerationRequests.jsx`
- `services/agent-runtime/agent_runtime/observability.py`
- `services/agent-runtime/agent_runtime/tinker_tools.py`
- `packages/contracts/open_talon_contracts/llm_engines.py`
- `packages/contracts/open_talon_contracts/llm_runtime.py`
- `packages/contracts/open_talon_contracts/telemetry.py`
- `apps/tui/open_talon_tui/main.py`
- `apps/tui/open_talon_tui/tui2.py`
- `tests/infrastructure/test_retriever_live_system.py`
- `tests/infrastructure/test_tinker_live_system.py`
- `tests/infrastructure/operational_agents_live/`

## When In Doubt

- Prefer normalization over duplication.
- Prefer explicit migrations over implicit schema mutation.
- Prefer small, reviewable changes over broad rewrites.
- Keep the repo runnable locally after each change.
