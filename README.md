# Open Talon

This repository contains the local infrastructure, Python services, and client apps for Open Talon. The canonical developer Python environment is the repository-root `.venv`.

For coding-agent-specific project guidance, see [`AGENTS.md`](./AGENTS.md).

## Documentation Map

- [docs/system-quickstart.md](./docs/system-quickstart.md): fastest path to a running local stack
- [docs/system-api-reference.md](./docs/system-api-reference.md): current system and API reference for engineers and client builders
- [docs/iam.md](./docs/iam.md): provider-neutral principal IAM model, permission catalog, and IAM APIs
- [docs/agent-operations-guide.md](./docs/agent-operations-guide.md): operating guide for software development agents and scripted test users
- [docs/tinker-tool-generation.md](./docs/tinker-tool-generation.md): Tinker request, approval, catalog, and live-test workflow
- [docs/operational-agents-real-life-test-protocol.md](./docs/operational-agents-real-life-test-protocol.md): real local-stack test protocol for Tinker, Steward, Curator, and managed administration contexts
- [docs/db-migrations.md](./docs/db-migrations.md): migration workflow and schema rules
- [docs/collaboration-system-design.md](./docs/collaboration-system-design.md): historical design background from before the current collaboration implementation
- [docs/research-comparison.md](./docs/research-comparison.md): external ecosystem comparison for multi-agent research and enterprise platforms
- [AGENTS.md](./AGENTS.md): repository contribution rules for coding agents

## System Overview

Open Talon is a local-first collaboration system where users and agents are first-class participants.

At a high level:

- `services/gateway-edge` is the main entrypoint for clients and developer tools
- `apps/admin-web` provides the browser-based admin console for organizations, workspace policy edits, provider management, swarm resource management, runtime overview, and API key operations
- `apps/web` is the gateway-mounted browser session-chat UI for the legacy `/v1/chat` surface
  - it is kept for session-chat compatibility and lightweight local demos, not as the primary collaboration browser client
- `apps/tui` provides a terminal UI that talks to the gateway
  - `tui2` is the recommended scrollback-first terminal client for reliable mouse copy/select and terminal-native link handling
- `services/core-collab` manages shared collaboration concepts like workspaces, threads, participants, presence, and timelines across both humans and agents
- `services/agent-runtime` runs stateless background workers for agent loops, tool execution, and lease reconciliation
- `packages/contracts` defines shared models and contracts used across services
- `infrastructure` provides the local backing services that make the system work end to end

The typical flow is:

1. A client sends a request to `gateway-edge`.
2. The gateway reads and writes state in Postgres and Valkey, and publishes asynchronous work through Kafka.
3. `core-collab` persists durable execution state in Postgres, including `tasks`, `runs`, `run_steps`, and `tool_calls`.
4. Stateless `agent-runtime` workers claim runnable work, execute model turns or tool calls, and publish events back into Kafka.
5. The gateway streams results back to clients over HTTP, SSE, or WebSocket.
6. Runtime observability is exported through a provider layer so Langfuse, OTLP-compatible sinks such as HyperDX, or no-op mode can be selected without changing executor code.

## Current Platform Inventory

| Component | Role today | Notes |
| --- | --- | --- |
| `services/gateway-edge` | public control plane and collaboration API | Owns REST, SSE, WebSocket, auth, admin, IAM, audit, collaboration, and session chat routes. |
| `services/core-collab` | canonical collaboration and execution kernel | Owns Postgres persistence for workspaces, threads, participants, requests, tasks, runs, tool calls, memory, assets, and audit writes. |
| `services/agent-runtime` | stateless execution plane | Runs the `agent-task-worker`, `agent-loop-worker`, `tool-worker`, and `reconciler`. |
| `services/retriever` | reusable retrieval ingestion worker | Claims retrieval ingestion jobs, reads versioned file assets from MinIO, extracts/chunks/embeds evidence, and writes chunks plus pgvector embeddings to Postgres. |
| `services/workspace-memory` | shared memory-provider abstraction | Keeps Postgres canonical while letting Mem0 and optional Memgraph act as derived retrieval layers. |
| `services/generated-tools-builder` | Tinker build/publish helper | Packages generated tools for the OCI-style registry flow used during tool approval. |
| `services/presence-directory` | reusable thread-presence primitives | Provides Valkey-backed websocket presence tracking used by `gateway-edge`. |
| `apps/admin-web` | operator browser console | Manages organizations, workspaces, providers, swarm resources, runtime overview, API keys, and tool-generation review. |
| `apps/web` | gateway-mounted browser session-chat UI | Compatibility browser client for the session-chat routes mounted at `/` by `gateway-edge` when the static app is present. |
| `apps/tui` | human and scripted terminal clients | `tui2` is the preferred human client; `user-client` is the preferred scriptable client for multi-user tests. |
| `packages/contracts` | shared contracts | Defines the Pydantic models and shared telemetry or registry contracts consumed across services. |
| `infrastructure` | local runtime dependencies | Defines Docker-backed Postgres, Kafka, Valkey, Keycloak, OpenBao, Langfuse, ClickHouse, MinIO, Forgejo, Ollama, and optional Memgraph. |

## Current Configuration Surface

The running system is configured from a small set of current sources:

- [`infrastructure/.env.example`](./infrastructure/.env.example): checked-in local defaults for ports, bootstrap credentials, worker settings, audit provider selection, and local model requirements.
- `infrastructure/.env`: local override file read by `./open-talon` and Docker Compose.
- [`services/gateway-edge/gateway_edge/config.py`](./services/gateway-edge/gateway_edge/config.py): gateway-side code defaults when env vars are absent.
- [`services/agent-runtime/agent_runtime/config.py`](./services/agent-runtime/agent_runtime/config.py): runtime worker defaults for leases, concurrency, OCI registry settings, and communication-log paths.
- [`apps/admin-web/public/runtime-config.json`](./apps/admin-web/public/runtime-config.json): browser runtime config loaded at app start so the built SPA stays relocatable across environments.
- `.run/openai.env`: optional ignored local secret file auto-loaded by the Python services for secret access, not for provider definitions.

Auth-mode nuance:

- if you import `gateway-edge` with no env at all, `auth_mode` defaults to `none`
- the checked-in local launcher path and [`infrastructure/.env.example`](./infrastructure/.env.example) set `AUTH_MODE=any`
- the documented local dev path is OIDC-first and also accepts API keys and OpenBao auth unless you narrow the mode explicitly

## Identity And Auth

Open Talon separates:

- `users`: stable human identity records
- `auth_identities`: external IdP mappings for authenticated humans
- `system_agents`: platform-global or organization-scoped agent definitions
- `agent_identities`, `iam_role_definitions`, `human_role_bindings`, and `agent_role_bindings`: principal IAM state for agent identities and global or organization role bindings
- `organizations`, `projects`, `project_access_bindings`, and `organization_memberships`: organization tenancy, project ownership/access, membership, and membership roles stored in Postgres
- `participants`: workspace-local materializations of a human or agent inside a workspace
- managed system agents are ordinary `system_agents`: `Tinker` for generated-tool authoring, global `Steward` for platform operations, organization-scoped `Curator` for organization operations, and workspace-attached `Anchor` for topic-alignment review through the managed `local-ollama` provider
- agent runtime remains generic: it renders agent definitions, harnesses, response contracts, task metadata, workspace context, tools, MCP, and memory without branching on agent key, display name, role text, capability text, or metadata tags

Role terminology in this repository:

- `IAM role`: a global or organization authorization role stored in `iam_role_definitions` and bound through `human_role_bindings` or `agent_role_bindings`
- `organization membership role`: the baseline human tenancy role in `organization_memberships.role`, such as `owner`, `admin`, or `member`
- `collaboration role`: a workspace-local role label stored in `participants.roles` and used for collaboration routing such as `@role:frontend_engineer`
- `capability`: a workspace-local advertised skill or routing label stored in `participants.capabilities` and used for selectors such as `@capability:qa_review`
- `collaboration role definition`: a workspace-local role description stored in `workspace.metadata.role_definitions`; this is discovery metadata, not IAM

Collaboration roles are not IAM roles. They are workspace-local collaboration and discovery labels that humans or agents can assume inside a workspace.

Authentication is handled through an external OIDC provider. Local development uses **Keycloak** as the default provider and first agent-identity provisioning adapter, but the runtime contracts are provider-neutral. The default local launcher setting is `AUTH_MODE=any`, so the running gateway accepts OIDC, API key, or OpenBao auth unless you narrow that setting explicitly. `gateway-edge` validates bearer tokens, maps human `(issuer, subject)` pairs to `users.user_id`, maps OIDC client `(provider_key, issuer, client_id)` tuples to `agent_identities`, and resolves workspace actors server-side.

Important implications:

- client apps should not treat `participant_id` as a global human identity
- authenticated human requests may include an `actor` object for compatibility, but the gateway derives the effective human actor from the bearer token
- agent identities authenticate with client credentials issued by the configured OIDC provider and are linked back to `system_agents` through `agent_identities`
- when `MCP_ENABLED=true`, the gateway-mounted MCP server at `/v1/mcp` is OIDC-only and exposes permission-scoped system API operations across organization, project, workspace, thread, memory, retrieval, runtime overview, audit read/verify, catalog/provider lookup, IAM lookup, and agent authoring surfaces, not Open Talon catalog/runtime tools
- the managed `open_talon_control_plane` MCP server uses agent identity client credentials so operational agents can call allowlisted gateway MCP operations through runtime tool execution
- the current MCP slice exposes read-only session resources at `ot://session/identity`, `ot://session/permissions`, and `ot://session/scope`
- organization membership and membership roles live in Postgres, not in Keycloak claims
- humans and agents share one permission catalog, but global and organization IAM roles are stored separately for each subject kind
- human org membership provides the baseline permission bundle for `owner`, `admin`, and `member`; extra human IAM roles can extend those permissions
- project access is explicit: each project records typed creator and primary owner references, and `creator`, `owner`, `editor`, or `viewer` bindings for users or system agents
- organization-level project listings require organization `project.read`; project details, access management, and project workspace structure also require local project access
- project access roles map to project-local permissions: creators and owners can read/write/manage access/create workspaces, editors can read/write/create workspaces, and viewers can read/list workspace structure
- workspace detail and workspace-scoped operations still require IAM permissions together with participant attachment; collaboration-role definitions do not grant authorization
- OIDC workspace-scoped reads are membership-scoped; non-members should see `404` for workspace, thread, memory, and workspace-scoped asset reads
- organization-scoped reads are also membership-scoped; non-members should see `404` there as well
- out-of-scope reads return `404`; in-scope requests without the required permission return `403`
- global system-definition, global publish, IAM management, and provider-management routes require matching global IAM permissions or platform-admin bootstrap access
- `/v1/me` is intentionally human-only; agent identities use the IAM and collaboration APIs directly
- OpenBao remains part of the local stack for secrets and other internal uses, not as the primary end-user login system
- OpenBao stores provisioned agent-identity secrets and returns them only during create or rotate flows
- the local Keycloak dev setup is intended to allow HTTP during development; `keycloak-init` normalizes `sslRequired=none` for both `master` and `open-talon`, and you can re-apply that with `docker compose up -d keycloak keycloak-init`
- browser-based admin flows use the `open-talon-web` public client with authorization code + PKCE; terminal flows use `open-talon-tui` with device flow; agent identities use client credentials against the configured provider

For the detailed permission catalog and IAM API surface, see [docs/iam.md](./docs/iam.md).

## Collaboration Model

Open Talon’s collaboration model is organization-aware and thread-native.

Core entities:

- `organization`: the tenant boundary above projects
- `project`: an organization-local work grouping that owns workspaces
- `workspace`: the collaboration boundary inside a project for participants, collaboration roles, attached tools, memory, and execution policy
- `participant`: the workspace-local materialization of a human or system agent, including status, collaboration roles, capabilities, and visibility
- `thread`: the shared collaboration stream inside a workspace
- `timeline_message`: an ordered message in a thread, visible to users, agents, or both depending on `visibility`
- `interaction_request`: a tracked question workflow attached to a thread
- `task` and `run`: the durable execution handoff from collaboration into agent-runtime

Important rules:

- the effective tenant hierarchy is `platform > organization > project > workspace > thread`
- `users` are global human identities, `organization_memberships` hold org-level access, and `participants` remain workspace-local state
- `system_agents`, `system_tools`, `llm_providers`, and `memory_providers` can be platform-global or organization-scoped
- `mcp_servers` are separate external MCP integration definitions; they are not Open Talon `system_tools`
- thread activity is ordered by a monotonic thread-local `sequence`
- Postgres is the source of truth for collaboration and execution state; Kafka is the wake-up and fanout bus
- threads are the shared surface in v1; tracked requests are rendered into the same thread instead of using private DM semantics
- plain messages can create agent work, but tracked requests are the resumable path when answers need to be correlated back into an agent loop

Tracked interaction requests support:

- one request containing one or more ordered questions
- explicit participant targets plus selector-based routing with `@participant`, participant business-role selectors `@role:<name>`, and capability selectors `@capability:<name>`
- aggregated answers from multiple participants
- completion rules including `all_targets`, `minimum_answers`, `one_per_selector_bucket`, and `custom_targets`
- agent resume only when the request becomes complete, not on every partial answer

The current thread-native request flow is:

1. A user or agent posts a message or structured interaction request into a thread.
2. `core-collab` persists the request, resolved targets, rendered thread message, and collaboration events.
3. Participants answer through normal thread messages linked to the request.
4. `core-collab` aggregates answers against the request’s completion rule.
5. When the request is complete, `core-collab` creates a follow-up task targeted only to the original requesting agent.
6. `agent-runtime` resumes that agent with the original request, targets, and accumulated answers in execution context.

For workspace-level debugging, Open Talon exposes a communication log view backed by canonical `timeline_messages`. It aggregates thread messages, rendered interaction requests, and interaction answers across the workspace, and requires both participant attachment and the IAM permission `workspace.audit.read`. Finalized communications are also appended to workspace JSONL files under `OPEN_TALON_COMMUNICATION_LOG_DIR` (default: `infrastructure/data/communication-logs/<workspace_id>.jsonl`) so end-to-end collaboration traces survive outside the database. These JSONL files rotate automatically with `OPEN_TALON_COMMUNICATION_LOG_MAX_BYTES` and `OPEN_TALON_COMMUNICATION_LOG_BACKUP_COUNT`, and local `./open-talon start` service logs under `.run/` rotate with `OPEN_TALON_SERVICE_LOG_MAX_BYTES` and `OPEN_TALON_SERVICE_LOG_BACKUP_COUNT`.

Common collaboration endpoints:

- `GET /v1/organizations`
- `POST /v1/organizations`
- `GET /v1/organizations/by-slug/{organization_slug}`
- `GET /v1/organizations/{organization_id}`
- `PATCH /v1/organizations/{organization_id}`
- `GET /v1/organizations/{organization_id}/members`
- `POST /v1/organizations/{organization_id}/members`
- `GET /v1/organizations/{organization_id}/projects`
- `POST /v1/organizations/{organization_id}/projects`
- `GET /v1/organizations/{organization_id}/projects/{project_id}`
- `PATCH /v1/organizations/{organization_id}/projects/{project_id}`
- `GET /v1/organizations/{organization_id}/projects/{project_id}/access`
- `PUT /v1/organizations/{organization_id}/projects/{project_id}/access`
- `DELETE /v1/organizations/{organization_id}/projects/{project_id}/access`
- `POST /v1/workspaces`
- `GET /v1/workspaces`
- `POST /v1/organizations/{organization_id}/projects/{project_id}/workspaces`
- `GET /v1/organizations/{organization_id}/projects/{project_id}/workspaces`
- `GET /v1/workspaces/{workspace_id}/communication-log`
- `GET /v1/workspaces/{workspace_id}/participants`
- `GET /v1/workspaces/{workspace_id}/catalog/agents`
- `GET /v1/workspaces/{workspace_id}/catalog/tools`
- `POST /v1/workspaces/{workspace_id}/threads`
- `GET /v1/threads/{thread_id}/timeline`
- `POST /v1/threads/{thread_id}/messages`
- `GET /v1/threads/{thread_id}/requests`
- `POST /v1/threads/{thread_id}/requests`
- `GET /v1/requests/{request_id}`
- `PATCH /v1/requests/{request_id}`
- `POST /v1/requests/{request_id}/answers`

## Admin Web

The admin web app lives in [apps/admin-web](./apps/admin-web) and is the main browser surface for:

- organization creation and membership management
- organization project creation and workspace filtering by project
- runtime overview and operator visibility
- platform-global and organization-scoped LLM and memory provider management
- platform-global and organization-scoped system agent and system tool management
- Tinker tool-generation request review and approve/reject workflows
- workspace create, update, role override, and delete flows inside the selected organization and project
- admin API key management

Local usage:

```bash
cd apps/admin-web
npm install
npm run dev
```

With the local stack running, the default browser entrypoint is [http://localhost:5173](http://localhost:5173).

The local stack seeds a single organization named `Default Organization` with a default project, so the browser auto-selects the organization until you create more organizations.

The app expects:

- gateway API at `http://127.0.0.1:8000`
- Keycloak at `http://127.0.0.1:8081`
- Keycloak realm `open-talon`
- OIDC client `open-talon-web`

Deployment notes:

- the built SPA reads browser runtime config from `apps/admin-web/public/runtime-config.json`
- that runtime file is meant to be replaced per environment so the same built artifact can move across dev, staging, and prod without rebuilding
- `appBasePath` in that file must match the deployed SPA mount point such as `/` or `/admin`
- the Vite bundle emits relative asset paths so the app can be served from a subpath

See [apps/admin-web/README.md](./apps/admin-web/README.md) for the full browser test and deployment guide.

## Operational Guardrails

The current defaults are aimed at a single medium-sized internal company deployment.

- global reads and writes for system agents, system tools, global Git repositories, global file/retrieval flows, global asset publish/link/activate flows, provider management, and global IAM management require the matching global IAM permission or platform-admin bootstrap access
- organization CRUD, organization membership changes, and organization-scoped IAM management require the relevant organization permissions, which are granted by membership baseline roles or explicit IAM role bindings
- workspace role-definition changes, workspace agent attachment/update/removal, workspace tool attach/update/delete, workspace Git repository creation, workspace asset publishing, and workspace retrieval operations require the matching workspace-scoped IAM permission together with participant attachment
- Tinker approval requires both `tool_generation.review` and `tool_catalog.write` in the requested publication scope
- human workspace access depends on organization membership first, then workspace participation
- workspace catalogs resolve as the union of platform-global resources and same-organization resources
- `GET /v1/workspaces` only returns workspaces where the authenticated human already has a participant record
- workspace-scoped reads intentionally return `404` for non-members so valid workspace and thread IDs are not enumerable
- risky tool execution profiles require `trust_level="trusted"`: `workspace_access=read_write`, `network=full`, and `local_process`

## Audit Logging

Open Talon has a dedicated audit subsystem that is separate from the collaboration domain event stream.

- `collab_event_log` remains the collaboration/event fanout stream
- `audit_event_ledger` is the canonical append-only audit ledger
- non-canonical audit surfaces are abstracted behind provider interfaces
- local defaults use Kafka topic `talon.audit.events` as the relay provider
- local defaults use ClickHouse for the audit projection provider in `default.audit_events`
- local defaults use MinIO for the archive provider that stores exports and daily chain checkpoints

V1 audit behavior:

- `gateway-edge` emits boundary audit records for HTTP, SSE, and WebSocket activity
- `core-collab` mirrors semantic workspace/thread/task/run/tool/provider mutations into audit in the same transaction as the business write
- `agent-runtime` emits audit records for worker exceptions and backend failures
- outcomes are explicit: `success`, `failure`, `denied`, and `error`
- payload depth is always `metadata_only`

Security and integrity rules:

- audit rows are append-only in steady-state code
- workspace-scoped chains use `workspace:{workspace_id}`
- organization-scoped chains use `organization:{organization_id}`
- system/global chains use `global`
- `prev_hash` and `event_hash` form the tamper-evident chain
- raw bearer tokens, prompt bodies, tool arguments, and message bodies must not be stored inline in audit metadata

Audit APIs:

- `GET /v1/audit/events`
- `GET /v1/audit/events/{audit_event_id}`
- `GET /v1/audit/chains/{partition}/verify`
- `POST /v1/audit/events/export`

Audit access model:

- global audit APIs require the identity permissions `audit.read`, `audit.verify`, and `audit.export`
- organization audit APIs require the same identity permissions within the target organization scope
- workspace audit APIs require the workspace permissions `workspace.audit.read`, `workspace.audit.verify`, and `workspace.audit.export`
- workspace audit and workspace-management routes are enforced by IAM permissions plus participant attachment; collaboration roles such as `admin`, `supervisor`, and `user` are only workspace-local discovery labels

Provider defaults are selected through env-backed settings:

- `AUDIT_RELAY_PROVIDER=kafka`
- `AUDIT_PROJECTION_PROVIDER=clickhouse`
- `AUDIT_ARCHIVE_PROVIDER=minio`
- each of those can also be set to `none` for a local no-op surface while Postgres remains canonical

The authoritative audit interface remains the Open Talon API backed by Postgres. Projection, relay, export, and checkpoint backends are replaceable and must stay non-blocking for canonical writes.

An optional local HyperDX all-in-one profile is available in Docker Compose for UI and OTLP intake experiments:

```bash
docker compose -f infrastructure/docker-compose.yaml --profile hyperdx up -d hyperdx
```

That profile is operational/investigative only. The canonical audit source remains Postgres plus the Open Talon audit APIs. To route runtime observability there, configure:

- `AGENT_RUNTIME_OBSERVABILITY_PROVIDER=otlp`
- `AGENT_RUNTIME_OTLP_HTTP_ENDPOINT=http://127.0.0.1:4318/v1/traces`
- optional `AGENT_RUNTIME_OBSERVABILITY_RICH_PAYLOADS=true|false`

The runtime observability path is separate from the canonical audit ledger. Rich payload capture belongs on the observability side and is centrally redacted before export.

## Tools Model

Open Talon models tools in two layers:

- `system_tools`: platform-global or organization-scoped tool definitions
- `workspace_tools`: workspace-scoped attachments that enable a system tool for a specific workspace

External MCP integrations use a separate model:

- `mcp_servers`: platform-global or organization-scoped external MCP server definitions
- `mcp_server_tools`, `mcp_server_resources`, and `mcp_server_prompts`: discovered MCP capabilities cached from those servers
- `workspace_mcp_servers`: workspace-scoped attachments that make selected MCP capabilities visible to agents

MCP tools are rendered and executed as external MCP capabilities. They are never inserted into `system_tools`, never attached through `workspace_tools`, and never published by Tinker. The gateway-mounted `/v1/mcp` endpoint remains the inbound Open Talon system API adapter and does not import or proxy these external MCP servers.

This means a tool is defined once at the platform or organization layer, then added to any compatible workspace that wants to advertise it to attached agents.

Generated tools follow the same model through `Tinker`:

- `Tinker` is a seeded system agent that must be attached to a workspace before users can ask it for new tools
- a request can target `global` or `organization` scope
- approval publishes the generated tool into the matching system catalog only and requires `tool_generation.review` plus scoped `tool_catalog.write`
- generated tools are never auto-attached to workspaces
- workspace participants with `workspace.tools.write` attach the published tool later with `PUT /v1/workspaces/{workspace_id}/tools/{tool_id}`

Each system tool includes:

- a human-readable name and description
- a `parameter_contract` describing accepted parameters
- an `input_schema` for structured validation/integration use
- an explicit `execution` binding that selects the execution backend, handler, execution profile, and trust level

When a tool is attached to a workspace, attached agent participants advertise it as a capability using the `tool:<name>` form, and the runtime includes the attached tool definitions in the agent execution context. Workspace catalog APIs expose the union of global and same-organization definitions visible to that workspace.

## Execution Infrastructure

Open Talon runs agent execution through durable stateless workers:

- Postgres is the source of truth for execution state
- Kafka is the wake-up and fanout bus
- `gateway-edge` delegates agent-loop execution to `agent-runtime`
- `agent-task-worker` claims `tasks`, creates `runs`, and resolves the target LLM engine
- `agent-loop-worker` claims `run_steps` and executes model turns
- `tool-worker` claims `tool_calls` and dispatches isolated tool execution
- `reconciler` requeues expired leases and republishes wakeup events
- `retriever-worker` claims retrieval ingestion jobs and populates retrieval chunks, full-text search data, and pgvector embeddings

Execution contracts are backend-neutral:

- `ExecutionSpec` is the payload envelope for isolated execution
- `ExecutionWorkspaceRef` identifies execution-side workspace materialization and is intentionally separate from the collaboration `Workspace` model
- `ExecutionResult` captures structured outputs, logs, artifacts, and terminal status

V1 execution backends:

- `docker`: default backend for arbitrary or untrusted tools
- `local_process`: minimal backend for tests and explicitly trusted built-ins

The Docker backend uses a short-lived container with a read-only root filesystem, dropped capabilities, no-new-privileges, resource limits, and `--network none` by default.

Runtime guardrails include:

- bounded retry scheduling through `next_retry_at` on `run_steps` and `tool_calls`
- reconciler backoff of `30s`, `2m`, and `10m`, with terminal failure after the third expired lease
- terminal expired tool calls fail the waiting run step and then fail the parent run with stop reason `tool_failure`
- normalized token usage persisted in `run.output["usage"]` with `provider`, `model`, `prompt_tokens`, `completion_tokens`, and `total_tokens`
- optional token caps through `OPEN_TALON_GLOBAL_DAILY_TOKEN_CAP` and `OPEN_TALON_WORKSPACE_DAILY_TOKEN_CAP`
- workspace-specific token-cap overrides from `workspace.metadata["limits"]["daily_token_cap"]` or `workspace.metadata["daily_token_cap"]`
- admin visibility at `GET /v1/admin/runtime/overview` for queue counts, recent failures, pending age, and current-day token totals

Common tool endpoints:

- `POST /v1/tools`: create a system-wide tool definition
- `GET /v1/tools`: list system-wide tool definitions
- `GET /v1/tools/{tool_id}`: get a tool definition by id
- `GET /v1/organizations/{organization_id}/tools`: list organization-scoped tool definitions
- `GET /v1/organizations/{organization_id}/tools/{tool_id}`: get an organization-scoped tool definition by id
- `PATCH /v1/tools/{tool_id}`: update a tool definition by id
- `PATCH /v1/organizations/{organization_id}/tools/{tool_id}`: update an organization-scoped tool definition
- `DELETE /v1/tools/{tool_id}`: delete a tool definition by id
- `DELETE /v1/organizations/{organization_id}/tools/{tool_id}`: delete an organization-scoped tool definition
- `GET /v1/workspaces/{workspace_id}/tools`: list tools attached to a workspace
- `PUT /v1/workspaces/{workspace_id}/tools/{tool_id}`: attach a system tool to a workspace
- `PATCH /v1/workspaces/{workspace_id}/tools/{tool_id}`: update workspace attachment state
- `DELETE /v1/workspaces/{workspace_id}/tools/{tool_id}`: detach a tool from a workspace
- `GET /v1/mcp-servers`: list global external MCP server definitions
- `POST /v1/mcp-servers`: create a global external MCP server definition
- `GET /v1/organizations/{organization_id}/mcp-servers`: list organization-scoped external MCP server definitions
- `POST /v1/organizations/{organization_id}/mcp-servers`: create an organization-scoped external MCP server definition
- `GET /v1/workspaces/{workspace_id}/mcp-servers`: list external MCP servers attached to a workspace
- `PUT /v1/workspaces/{workspace_id}/mcp-servers/{server_id}`: attach an external MCP server to a workspace
- `GET /v1/tool-generation/requests`: list tool-generation requests for admins
- `GET /v1/threads/{thread_id}/tool-generation/requests`: list tool-generation requests for a thread
- `POST /v1/tool-generation/revisions/{revision_id}/approve`: publish a generated tool into the system catalog

Common file and retrieval endpoints:

- `POST /v1/files`, `POST /v1/organizations/{organization_id}/files`, and `POST /v1/workspaces/{workspace_id}/files`: upload immutable file asset versions to MinIO-backed storage
- `GET /v1/files`, `GET /v1/organizations/{organization_id}/files`, and `GET /v1/workspaces/{workspace_id}/files`: list visible file assets
- `POST /v1/retrieval/corpora`, `POST /v1/organizations/{organization_id}/retrieval/corpora`, and `POST /v1/workspaces/{workspace_id}/retrieval/corpora`: create scoped retrieval corpora
- `POST /v1/retrieval/sources`, `POST /v1/organizations/{organization_id}/retrieval/sources`, and `POST /v1/workspaces/{workspace_id}/retrieval/sources`: link file assets into corpora
- `POST /v1/.../retrieval/corpora/{corpus_id}/jobs`: enqueue ingestion for a retrieval source version
- `POST /v1/.../retrieval/search` and `POST /v1/.../retrieval/context-packs`: search indexed chunks and create cited context packs

## Layered Memory

Open Talon uses a layered memory model with a single canonical store and optional derived providers.

Memory layers:

- `run` memory: per-run scratch memory written during agent execution
- `thread` memory: shared collaboration memory for all users and agents participating in a thread
- `workspace` memory: confirmed cross-thread memory for a workspace

Storage model:

- Postgres `memory_entries` is the source of truth
- external memory systems are projections, not authoritative stores
- projection state is tracked in `memory_provider_records`

Default provider shape:

- canonical provider: Postgres
- semantic provider: Mem0
- optional graph backend for Mem0: Memgraph

This intentionally means there is physical duplication between canonical rows and derived provider indexes. The duplication is deliberate:

- Postgres owns correctness, visibility, confirmation state, lifecycle, and auditability
- Mem0 and optional graph backends own semantic or relational retrieval

The provider abstraction lives in [services/workspace-memory/workspace_memory/providers.py](./services/workspace-memory/workspace_memory/providers.py). `core-collab` always writes canonical memory first and then syncs enabled providers through the common provider interface.

Common memory endpoints:

- `GET /v1/workspaces/{workspace_id}/memory`
- `POST /v1/workspaces/{workspace_id}/memory`
- `POST /v1/workspaces/{workspace_id}/memory/confirm`
- `GET /v1/threads/{thread_id}/memory`
- `POST /v1/threads/{thread_id}/memory`
- `POST /v1/threads/{thread_id}/memory/search`
- `POST /v1/memory-providers`
- `POST /v1/memory-providers/validate`
- `GET /v1/memory-providers`
- `GET /v1/memory-providers/{provider_id}`
- `GET /v1/organizations/{organization_id}/memory-providers/{provider_id}`
- `PATCH /v1/memory-providers/{provider_id}`
- `PATCH /v1/organizations/{organization_id}/memory-providers/{provider_id}`
- `DELETE /v1/memory-providers/{provider_id}`
- `DELETE /v1/organizations/{organization_id}/memory-providers/{provider_id}`
- `POST /v1/memory-providers/{provider_id}/health-check`
- `POST /v1/organizations/{organization_id}/memory-providers/{provider_id}/health-check`

## Extending Memory Providers

Open Talon is abstracted so additional memory providers can be added without changing the memory domain model.

Current built-in providers:

- `PostgresMemoryProvider`
- `Mem0MemoryProvider`

To add another provider:

1. Implement the `MemoryProvider` protocol in [services/workspace-memory/workspace_memory/providers.py](./services/workspace-memory/workspace_memory/providers.py).
2. Register it in `build_provider_index(...)`.
3. Add a provider definition through the memory-provider admin API or seed it in a migration.
4. Reuse the shared secret resolution helpers in [services/workspace-memory/workspace_memory/secrets.py](./services/workspace-memory/workspace_memory/secrets.py).
5. Add route, health, and provider-level tests.

The provider contract is intentionally small:

- `upsert(...)`
- `delete(...)`
- `search(...)`
- `health_check(...)`

### Provider Sketch

Example shape for another provider:

```python
from workspace_memory.providers import (
    MemoryProvider,
    ProviderSearchHit,
    ProviderSearchResult,
    ProviderSyncResult,
)


class ExampleMemoryProvider:
    provider_name = "example"

    async def upsert(self, definition, entry, *, external_id=None):
        # Persist or update the provider-side representation.
        return ProviderSyncResult(
            external_id=external_id or "provider-generated-id",
            metadata={"provider": self.provider_name},
        )

    async def delete(self, definition, entry, *, external_id=None):
        # Remove the provider-side projection.
        return None

    async def search(
        self,
        definition,
        *,
        scope,
        workspace_id,
        thread_id,
        run_id,
        query,
        limit,
        include_graph=True,
        metadata_filters=None,
    ):
        return ProviderSearchResult(
            provider=self.provider_name,
            hits=[
                ProviderSearchHit(
                    memory_entry_id=entry_id,
                    external_id="provider-hit-id",
                    score=0.9,
                    relations=[],
                    metadata={"scope": scope},
                )
            ],
            metadata={"graph_enabled": False},
        )

    async def health_check(self, definition):
        ...
```

That provider can then be exposed by registering it in `build_provider_index(...)` and persisting a matching `memory_providers.provider` value such as `"example"`.

## Architecture Stack

- **PostgreSQL**: Deployed via `pgvector/pgvector:pg16` directly supporting native `JSONB` properties alongside algorithmic embeddings operations for Vector Similarity Searching natively in the engine.
- **Kafka**: Deployed using `apache/kafka:3.8.0` utilizing `KRaft` mode (omitting Zookeeper), configured natively on mapped loops using high level partition assignments.
- **OpenBao**: Open-source fork of Hashicorp Vault running in local development for secrets-oriented workflows, backed by a persistent local file store under `infrastructure/data/openbao`.
- **Keycloak**: Default local OIDC provider and the first agent-identity provisioning adapter used in development. Open Talon remains the source of truth for authorization.
- **Valkey**: Drop-in compatible Redis equivalent caching infrastructure configured to handle immediate TTL caching.
- **Langfuse**: Self-hosted LLM observability stack that can be used as one runtime observability backend for traces, prompts, and evaluations.
- **HyperDX**: Optional OTLP-compatible observability sink/UI for local investigations and runtime telemetry experiments.
- **Ollama AI**: Serves dynamic generative model orchestration natively mapped across standard REST.
    - Operates natively against Google's modern **Gemma 4** models, with the default test setup pulling the lightweight `gemma4:latest` model.

## Infrastructure

`./open-talon start` brings up the full local infrastructure stack and then starts the supported local processes for:

It waits for both the gateway readiness endpoint and the configured OIDC discovery document before returning success. In local development, that means Keycloak browser, device-flow, and machine-credential auth should already have their dependencies online when the command exits.

- `gateway-edge`
- `agent-task-worker`
- `agent-loop-worker`
- `tool-worker`
- `reconciler`
- `retriever-worker`

Local services:

- `gateway-edge`: primary local API gateway for REST, SSE, WebSocket, collaboration, and admin APIs
- `agent-task-worker`: local worker that claims durable `tasks`, creates `runs`, and resolves the target LLM engine
- `agent-loop-worker`: local worker that executes agent model steps from durable `run_steps`
- `tool-worker`: local worker that executes isolated tool invocations from durable `tool_calls`
- `reconciler`: local worker that requeues expired leases and republishes wakeups
- `retriever-worker`: local worker that extracts and indexes retrieval sources stored as immutable file assets
- `postgres`: application database with `pgvector` enabled
- `pgadmin`: pgAdmin 4 web UI for inspecting and querying the local Postgres instance
- `kafka`: event bus for chat, collaboration, and agent-runtime traffic
- `clickhouse`: Langfuse analytics store and the default local audit projection provider
- `minio`: object storage for Langfuse, published assets, and the default local audit archive provider
- `openbao`: local secret store and token-validation backend
- `keycloak`: local default OIDC provider for browser login, device login, and machine credentials
- `valkey`: session store, API-key cache, and short-lived gateway state
- `langfuse-web`: Langfuse UI and API surface
- `langfuse-worker`: Langfuse background processing
- `forgejo`: local Git forge for live repo workflows and authored agent/tool definitions; agent bundles are validated/published through the gateway into `system_agents` and immutable `agent_definition_versions`
- `ollama`: local model serving endpoint
- `memgraph`: optional local graph backend for Mem0 graph memory when started with `./open-talon start --memgraph`

## Endpoints

Common local endpoints:

- `gateway-edge`: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- `gateway-edge health`: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- `gateway-edge readiness`: [http://127.0.0.1:8000/ready](http://127.0.0.1:8000/ready)
- `gateway-edge docs`: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- `gateway-edge audit list`: [http://127.0.0.1:8000/v1/audit/events](http://127.0.0.1:8000/v1/audit/events)
- `gateway-edge audit export`: [http://127.0.0.1:8000/v1/audit/events/export](http://127.0.0.1:8000/v1/audit/events/export)
- `gateway-edge runtime overview` (admin only): [http://127.0.0.1:8000/v1/admin/runtime/overview](http://127.0.0.1:8000/v1/admin/runtime/overview)
- `admin-web` dev server: [http://localhost:5173](http://localhost:5173)
- `langfuse-web`: [http://localhost:3000](http://localhost:3000)
- `hyperdx` when started with `--profile hyperdx`: [http://127.0.0.1:8080](http://127.0.0.1:8080)
- `pgadmin`: [http://localhost:5050](http://localhost:5050)
- `openbao`: [http://localhost:8200](http://localhost:8200)
- `keycloak`: [http://localhost:8081](http://localhost:8081)
  default local login: `admin` / `admin`
  default realm: `open-talon`
- `keycloak issuer`: [http://127.0.0.1:8081/realms/open-talon](http://127.0.0.1:8081/realms/open-talon)
- `keycloak OpenID config`: [http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration](http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration)
- `ollama`: [http://localhost:11434](http://localhost:11434)
- `clickhouse HTTP`: [http://localhost:8123](http://localhost:8123)
- `minio API`: [http://localhost:9090](http://localhost:9090)
- `minio console`: [http://localhost:9091](http://localhost:9091)
- `forgejo`: [http://localhost:3001](http://localhost:3001)
- `memgraph HTTP` when started with `./open-talon start --memgraph`: [http://127.0.0.1:7444](http://127.0.0.1:7444)

Ports and protocols:

- `postgres`: `localhost:5432`
- `kafka`: `localhost:9092`
- `valkey`: `localhost:6379`
- `clickhouse native`: `localhost:9000`
- `langfuse-worker`: `localhost:3030`
- `forgejo ssh`: `localhost:2222`
- `memgraph bolt` when started with `./open-talon start --memgraph`: `localhost:7688`
- `hyperdx OTLP gRPC` when started with `--profile hyperdx`: `localhost:4317`
- `hyperdx OTLP HTTP` when started with `--profile hyperdx`: `localhost:4318`

## Credentials

Default local development credentials:

- `Postgres`
  username: `admin`
  password: `password`
  database: `app_db`
- `pgAdmin`
  URL: [http://localhost:5050](http://localhost:5050)
  email: `admin@local.dev`
  password: `admin`
  preconfigured server: `Open Talon Postgres`
  uses default Postgres settings: database `app_db`, user `admin`
- `Langfuse Postgres database`
  database: `langfuse_db`
- `Valkey`
  password: `langfuse-dev-secret`
- `OpenBao`
  root token: `root`
- `Keycloak`
  URL: [http://localhost:8081](http://localhost:8081)
  admin username: `admin`
  admin password: `admin`
  default realm: `open-talon`
  realm users:
  `admin` / `admin123`, `admin2` / `admin223`, `supervisor` / `supervisor123`, `supervisor2` / `supervisor223`, `user1` / `user12345`, `user2` / `user22345`
- `Langfuse UI`
  URL: [http://localhost:3000](http://localhost:3000)
  email: `admin@example.com`
  password: `admin123456`
- `MinIO`
  console: [http://localhost:9091](http://localhost:9091)
  username: `minio`
  password: `miniosecret`
- `Forgejo`
  URL: [http://localhost:3001](http://localhost:3001)
  admin username: `forgejo`
  admin password: `forgejo123`
- `ClickHouse`
  username: `langfuse`
  password: `langfuse`
- `Memgraph` when started with `./open-talon start --memgraph`
  username: `memgraph`
  password: `memgraph`
- `HyperDX`
  URL when started with `--profile hyperdx`: [http://localhost:8080](http://localhost:8080)
  no repo-pinned bootstrap username/password is currently documented for the all-in-one image

These are local dev defaults from `infrastructure/.env.example`. Override them in your local env before starting the stack if you need different values.

The bundled pgAdmin server import is also pinned to the default local Postgres connection (`postgres:5432`, database `app_db`, user `admin`). If you change those Postgres values in `infrastructure/.env`, update `infrastructure/pgadmin/servers.json` and `infrastructure/pgadmin/pgpass` to keep the preconfigured connection working.

The compose stack currently pins pgAdmin to `dpage/pgadmin4:9.13.0` in [`infrastructure/docker-compose.yaml`](./infrastructure/docker-compose.yaml#L17) for reproducible local setup.

## Persistence Design

Local persistence uses host bind mounts under `infrastructure/data/...`.

That means:

- `./open-talon stop` and `docker compose down` stop containers without wiping local data
- `docker compose down -v` only removes Docker-managed volumes; it does not remove these bind-mounted directories
- OpenBao secrets, Postgres state, Forgejo repositories, Ollama model data, and other local payloads survive normal restarts until you remove the matching `infrastructure/data/...` directory yourself
- `./open-talon repair` starts the local stack and idempotently restores missing managed defaults and operational-agent machine identities in an existing local system
- `./open-talon reset --yes --init` stops the stack, removes local runtime data under `infrastructure/data`, preserves the Ollama model cache by default, and starts a fresh system initialized with the checked-in defaults
- pass `--include-models` to `./open-talon reset` only when you also want to discard the local Ollama model cache

> **Note**: Do not commit `infrastructure/data/`. It contains local databases, secret storage, model artifacts, and other large runtime data already excluded by `.gitignore`.

## Python Environment

Use one virtualenv at the repository root for all local Python work:

```bash
./scripts/bootstrap-python.sh
source .venv/bin/activate
```

That root environment installs:

- shared contracts from `packages/contracts`
- the collaboration kernel from `services/core-collab`
- the agent runtime helpers from `services/agent-runtime`
- the retriever worker from `services/retriever`
- the gateway edge service from `services/gateway-edge`
- the browser admin app source lives separately in `apps/admin-web` and uses its own npm dependencies and build tooling
- the TUI app from `apps/tui`
- repo-level test dependencies for gateway and infrastructure suites

`services/gateway-edge` is the only supported local gateway path for day-to-day development.

## OpenAI Engine

LLM provider and engine definitions are persistent system resources. They are managed through the `llm-providers` API and stored in Postgres, not defined from environment variables.

The local migrations seed two default providers:

- `local-ollama`
- `openai-responses`

They also seed a sample system agent:

- `Reasoning Planner`
- `agent_id`: `33333333-3333-3333-3333-333333333333`
- `engine_id`: `openai-responses`

For local secret handling, prefer an ignored repo-local file that only carries secret access, not provider definitions:

```bash
mkdir -p .run
cat > .run/openai.env <<'EOF'
OPEN_TALON_OPENBAO_TOKEN=root
EOF
```

`gateway-edge` and `agent-runtime` load `.run/openai.env` automatically if it exists.

If you want the `openai-responses` provider to resolve credentials from OpenBao, store the key in KV v2:

```bash
curl -X POST http://127.0.0.1:8200/v1/secret/data/open-talon/llm/openai \
  -H 'X-Vault-Token: root' \
  -H 'Content-Type: application/json' \
  -d '{"data":{"api_key":"sk-..."}}'
```

The local OpenBao container uses persistent file storage, so secrets survive `./open-talon stop` and `docker compose down`. To fully reset the local secret store together with the rest of the local runtime state, use `./open-talon reset --yes --init`; for a narrower manual reset, remove `infrastructure/data/openbao` before starting the stack again.

The runtime secret provider will then try `env` first and `openbao` second by default.

Common provider endpoints:

- `GET /v1/llm-providers`
- `POST /v1/llm-providers`
- `GET /v1/llm-providers/{provider_id}`
- `GET /v1/organizations/{organization_id}/llm-providers/{provider_id}`
- `PATCH /v1/llm-providers/{provider_id}`
- `PATCH /v1/organizations/{organization_id}/llm-providers/{provider_id}`
- `DELETE /v1/llm-providers/{provider_id}`
- `DELETE /v1/organizations/{organization_id}/llm-providers/{provider_id}`
- `POST /v1/llm-providers/{provider_id}/health-check`
- `POST /v1/organizations/{organization_id}/llm-providers/{provider_id}/health-check`
- `POST /v1/llm-providers/validate`
- `GET /v1/llm-engines`

Other providers follow the same pattern: the runtime resolves secrets from an ordered provider chain, and engine metadata can advertise one or more secret references. The supported reference shape today is:

```json
{
  "env": { "name": "PROVIDER_API_KEY" },
  "openbao": {
    "mount": "secret",
    "path": "open-talon/llm/provider-name",
    "field": "api_key"
  }
}
```

That lets a provider try local env for development and OpenBao KV for shared or longer-lived setups without changing executor code.

Example system agent targeting the OpenAI engine:

```json
{
  "actor": {
    "participant_id": "00000000-0000-0000-0000-000000000001",
    "participant_type": "user",
    "display_name": "Admin"
  },
  "display_name": "Reasoning Planner",
  "description": "Plans multi-step work with cloud reasoning.",
  "role": "planning agent",
  "capabilities": ["planning", "triage", "reasoning"],
  "endpoint": {
    "kind": "remote",
    "engine_id": "openai-responses",
    "provider": "openai"
  },
  "system_prompt": "You plan carefully and explain tradeoffs clearly.",
  "definition": {
    "runtime": {
      "engine_id": "openai-responses",
      "preferred_capabilities": ["reasoning", "tool_calling"],
      "preferred_locality": "cloud"
    }
  }
}
```

Example LLM provider definition for `POST /v1/llm-providers`:

```json
{
  "actor": {
    "participant_id": "00000000-0000-0000-0000-000000000001",
    "participant_type": "user",
    "display_name": "Admin"
  },
  "engine_id": "openai-responses",
  "display_name": "OpenAI Responses",
  "description": "Cloud OpenAI Responses API provider.",
  "provider": "openai",
  "endpoint_kind": "remote",
  "url": "https://api.openai.com/v1/responses",
  "default_model": "gpt-5.4-mini",
  "capabilities": ["chat", "completion", "tool_calling", "reasoning"],
  "locality": "cloud",
  "priority": 220,
  "enabled": true,
  "secret_config": {
    "env": { "name": "OPENAI_API_KEY" },
    "openbao": {
      "mount": "secret",
      "path": "open-talon/llm/openai",
      "field": "api_key"
    }
  }
}
```

## Adding Another LLM Provider

To add another hosted or network LLM provider cleanly:

1. Create or validate the provider through `POST /v1/llm-providers` or `POST /v1/llm-providers/validate` with a unique `engine_id`, endpoint details, capabilities, locality, and `secret_config`.
2. Store the provider secret in OpenBao, or point `secret_config.env` at an environment variable for local-only development.
3. If the provider uses a provider-specific wire protocol, add an execution branch in [runtime.py](./services/agent-runtime/agent_runtime/runtime.py), similar to the OpenAI path.
4. If the new provider needs a new secret backend instead of `env` or `openbao`, add a new `SecretProvider` implementation in [secrets.py](./services/agent-runtime/agent_runtime/secrets.py) and register it in `build_default_secret_resolver()`.

For most API-key-based providers, the persistence and secret wiring should not require executor changes beyond the provider-specific request/response format.

## Quickstart

For the shortest end-to-end local setup flow, see [`docs/system-quickstart.md`](./docs/system-quickstart.md).

## TUI

For TUI setup, usage, and slash command documentation, see [`apps/tui/README.md`](./apps/tui/README.md).

For the end-to-end Tinker flow, including approval and manual workspace attachment, see [`docs/tinker-tool-generation.md`](./docs/tinker-tool-generation.md).

In the current auth model, the TUI is a **multi-profile** client:

- each local profile lives under `~/.open-talon/profiles/<profile>/`
- `tui2` and `user-client` also persist the selected `organization_id` in that profile state
- each profile stores separate workspace/thread state and bearer tokens
- human login uses the local Keycloak device flow by default
- two users on the same device should use different TUI profiles rather than sharing one local participant identity

For terminal-first usage, prefer `tui2`:

```bash
./open-talon tui2 --profile admin
```

`tui2` runs in normal terminal scrollback instead of a full-screen widget layout, so mouse selection works like a regular shell session and raw URLs remain easy to copy or open.

For multi-user end-to-end testing driven by software development agents, use `user-client` instead:

```bash
./open-talon user-client --profile user1
```

`user-client` is a scriptable per-user terminal client. One client instance should be used per human test user, and each instance should have its own local profile.

In multi-tenant flows, `tui2` and `user-client` expose explicit `organization` commands and default `workspace list` to the selected organization. If the authenticated user can only see one organization, the clients auto-select it.

Useful local flows:

```bash
./open-talon tui2 --profile admin
./open-talon tui2 auth login --profile admin
./open-talon user-client --profile user1
./open-talon user-client auth login --profile user1
```

Inside `tui2`, the minimum auth path is:

```text
/auth login
/account whoami
/organization list
/organization use <id|slug|name>
/workspace list
```

Tinker requests can also be opened directly from `tui2`:

```text
/tool request Build a repo statistics tool for this platform
/tool request --scope organization Build a Fibonacci calculator tool that accepts integer n and returns the Fibonacci value
```

Inside `user-client`, the minimum multi-user path is:

```text
auth login
status
organization list
organization use <id|slug|name>
workspace use <id|name>
thread use <id|title>
timeline
```

## Database Migrations

Database schema changes are tracked as `dbmate`-style SQL files in [`db/migrations`](./db/migrations).

- App startup and tests apply pending migrations through the repo's Python migration runner.
- For local manual migration work, use [`scripts/dbmate.sh`](./scripts/dbmate.sh).
- `dbmate` itself is the recommended CLI for creating and applying new migration files.
- Default local values for `DATABASE_URL` and `DBMATE_MIGRATIONS_DIR` are documented in [`infrastructure/.env.example`](./infrastructure/.env.example).

Examples:

```bash
# create a new migration file
./scripts/dbmate.sh new add_threads_archive_state

# apply pending migrations
./scripts/dbmate.sh up

# inspect migration status
./scripts/dbmate.sh status
```

Migration authoring rules:

- Treat each migration file as immutable once committed.
- Prefer additive migrations plus explicit backfills over editing old SQL files.
- Keep one logical schema/data change per migration when practical.
- Test new migrations locally with `./scripts/dbmate.sh up` before merging.

CI snippet:

```bash
source .venv/bin/activate
./scripts/dbmate.sh up
pytest -q
```

For a longer reference, see [`docs/db-migrations.md`](./docs/db-migrations.md).

## Langfuse

The local compose stack includes a self-hosted Langfuse deployment:

- `langfuse-web` on `http://localhost:3000`
- `langfuse-worker` on port `3030`
- `clickhouse` on ports `8123` and `9000`
- `minio` on ports `9090` and `9091`
- `forgejo` on `http://localhost:3001` with SSH on port `2222`

This setup reuses the repository Postgres server and Valkey container, but Langfuse uses its own Postgres database (`LANGFUSE_POSTGRES_DB`) so Prisma migrations do not collide with the application schema. Defaults live in `infrastructure/.env.example`.

Runtime observability is provider-backed. `agent-runtime` can export through Langfuse or OTLP-compatible sinks:

- `AGENT_RUNTIME_OBSERVABILITY_PROVIDER=langfuse` to use Langfuse
- `AGENT_RUNTIME_OBSERVABILITY_PROVIDER=otlp` to use OTLP-compatible sinks such as HyperDX
- `AGENT_RUNTIME_OBSERVABILITY_PROVIDER=none` to disable runtime observability export

Audit relay/projection/archive surfaces are also provider-backed, with local defaults selected by `AUDIT_RELAY_PROVIDER`, `AUDIT_PROJECTION_PROVIDER`, and `AUDIT_ARCHIVE_PROVIDER`.

Infra defaults are defined in `infrastructure/.env.example`, including:

- core ports for Postgres, Kafka, OpenBao, Valkey, Ollama, Forgejo, and Langfuse
- Langfuse database name and bootstrap credentials
- ClickHouse, MinIO, Forgejo, and Valkey credentials used by the local stack
- the required Ollama model list for local startup
- worker scaling and lease settings such as `AGENT_STEP_WORKER_CONCURRENCY`, `TOOL_WORKER_CONCURRENCY`, `LEASE_TTL_SECONDS`, and `RECONCILE_INTERVAL_SECONDS`
- audit and observability provider selection defaults

## Pytest Orchestration

`pytest.ini` excludes `integration` tests by default, so the maintained suite and the live infrastructure suite are two explicit commands. The Tinker coverage is split between an in-process business-case scenario and a real live integration path.

```bash
# Enable the repository virtual environment
source .venv/bin/activate

# Default maintained suite (excludes integration tests via pytest.ini)
pytest -q

# Gateway tests only
pytest tests/gateway-edge -q

# Business case scenarios only
pytest tests/business-cases -q

# Infrastructure integration tests
pytest -m integration tests/infrastructure/test_infrastructure.py -v -s

# Live Tinker business-case scenario (in-process, fake repository)
pytest tests/business-cases/test_tinker_tool_generation.py -q

# Live Tinker tool-generation system test (real stack, real runtime, real generated tool path)
pytest -m integration tests/infrastructure/test_tinker_live_system.py -q -s

# Live compaction system test (real stack, real runtime, prompt dump + persisted run scratch assertions)
pytest -m integration tests/infrastructure/test_agent_compaction_live_system.py -q -s

# Full test coverage: default suite plus integration suite
pytest -q
pytest -m integration tests/infrastructure/test_infrastructure.py -v -s
pytest -m integration tests/infrastructure/test_tinker_live_system.py -q -s
```

## AI Model Initialization Note

First-time execution will wait for Ollama to fetch the configured default model from `infrastructure/.env`. The suite allows long waits for first-run downloads and uses the configured local model set from `infrastructure/.env`.
