# Open Talon

This repository contains the local infrastructure, Python services, and client apps for Open Talon. The canonical developer Python environment is the repository-root `.venv`.

For coding-agent-specific project guidance, see [`AGENTS.md`](/Users/nikolay.kvasov/Development/open-talon-1/AGENTS.md).

## Documentation Map

- [docs/system-quickstart.md](/Users/nikolay.kvasov/Development/open-talon-1/docs/system-quickstart.md): fastest path to a running local stack
- [docs/system-api-reference.md](/Users/nikolay.kvasov/Development/open-talon-1/docs/system-api-reference.md): current system and API reference for engineers and client builders
- [docs/iam.md](/Users/nikolay.kvasov/Development/open-talon-1/docs/iam.md): provider-neutral principal IAM model, permission catalog, and IAM APIs
- [docs/agent-operations-guide.md](/Users/nikolay.kvasov/Development/open-talon-1/docs/agent-operations-guide.md): operating guide for software development agents and scripted test users
- [docs/tinker-tool-generation.md](/Users/nikolay.kvasov/Development/open-talon-1/docs/tinker-tool-generation.md): Tinker request, approval, catalog, and live-test workflow
- [docs/db-migrations.md](/Users/nikolay.kvasov/Development/open-talon-1/docs/db-migrations.md): migration workflow and schema rules
- [docs/collaboration-system-design.md](/Users/nikolay.kvasov/Development/open-talon-1/docs/collaboration-system-design.md): design background and architecture evolution
- [AGENTS.md](/Users/nikolay.kvasov/Development/open-talon-1/AGENTS.md): repository contribution rules for coding agents

## System Overview

Open Talon is a local-first collaboration system where users and agents are first-class participants.

At a high level:

- `services/gateway-edge` is the main entrypoint for clients and developer tools
- `apps/admin-web` provides the browser-based admin console for organizations, workspace policy edits, provider management, swarm resource management, runtime overview, and API key operations
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

## Identity And Auth

Open Talon now separates:

- `users`: stable human identity records
- `auth_identities`: external IdP mappings for authenticated humans
- `system_agents`: platform-global or organization-scoped agent definitions
- `agent_identities`, `iam_role_definitions`, `human_role_bindings`, and `agent_role_bindings`: principal IAM state for machine identities and global or organization role bindings
- `organizations` and `organization_memberships`: organization tenancy, membership, and membership roles stored in Postgres
- `participants`: workspace-local materializations of a human or agent inside a workspace

Role terminology in this repository:

- `IAM role`: a global or organization authorization role stored in `iam_role_definitions` and bound through `human_role_bindings` or `agent_role_bindings`
- `organization membership role`: the baseline human tenancy role in `organization_memberships.role`, such as `owner`, `admin`, or `member`
- `collaboration role`: a workspace-local role label stored in `participants.roles` and used for collaboration routing such as `@role:frontend_engineer`
- `capability`: a workspace-local advertised skill or routing label stored in `participants.capabilities` and used for selectors such as `@capability:qa_review`
- `collaboration role definition`: a workspace-local role description stored in `workspace.metadata.role_definitions`; this is discovery metadata, not IAM

Collaboration roles are not IAM roles. They are workspace-local collaboration and discovery labels that humans or agents can assume inside a workspace.

Authentication is handled through an external OIDC provider. Local development uses **Keycloak** as the default provider and first machine-identity provisioning adapter, but the runtime contracts are provider-neutral. The default local launcher setting is still `AUTH_MODE=any`, so the running gateway accepts OIDC, API key, or OpenBao auth unless you narrow that setting explicitly. `gateway-edge` validates bearer tokens, maps human `(issuer, subject)` pairs to `users.user_id`, maps machine `(provider_key, issuer, client_id)` tuples to `agent_identities`, and resolves workspace actors server-side.

Important implications:

- client apps should not treat `participant_id` as a global human identity
- authenticated human requests may still include an `actor` object for compatibility, but the gateway derives the effective human actor from the bearer token
- machine principals authenticate with client credentials issued by the configured OIDC provider and are linked back to `system_agents` through `agent_identities`
- organization membership and membership roles live in Postgres, not in Keycloak claims
- humans and agents share one permission catalog, but global and organization IAM roles are stored separately for each subject kind
- human org membership provides the baseline permission bundle for `owner`, `admin`, and `member`; extra human IAM roles can extend those permissions
- workspace access is enforced through IAM permissions together with participant attachment; collaboration-role definitions do not grant authorization
- OIDC workspace listing and workspace-scoped reads are membership-scoped; non-members should see `404` for workspace, thread, memory, and workspace-scoped asset reads
- organization-scoped reads are also membership-scoped; non-members should see `404` there as well
- out-of-scope reads return `404`; in-scope requests without the required permission return `403`
- global system-definition, global publish, IAM management, and provider-management routes require matching global IAM permissions or platform-admin bootstrap access
- `/v1/me` is intentionally human-only; machine principals use the IAM and collaboration APIs directly
- OpenBao remains part of the local stack for secrets and other internal uses, not as the primary end-user login system
- OpenBao stores provisioned machine secrets and returns them only during create or rotate flows
- the local Keycloak dev setup is intended to allow HTTP during development; `keycloak-init` normalizes `sslRequired=none` for both `master` and `open-talon`, and you can re-apply that with `docker compose up -d keycloak keycloak-init`
- browser-based admin flows use the `open-talon-web` public client with authorization code + PKCE; terminal flows use `open-talon-tui` with device flow; machine principals use client credentials against the configured provider

For the detailed permission catalog and IAM API surface, see [docs/iam.md](/Users/nikolay.kvasov/Development/open-talon-1/docs/iam.md).

## Collaboration Model

Open Talon’s collaboration model is organization-aware and thread-native.

Core entities:

- `organization`: the tenant boundary above workspaces
- `workspace`: the collaboration boundary inside an organization for participants, collaboration roles, attached tools, memory, and execution policy
- `participant`: the workspace-local materialization of a human or system agent, including status, collaboration roles, capabilities, and visibility
- `thread`: the shared collaboration stream inside a workspace
- `timeline_message`: an ordered message in a thread, visible to users, agents, or both depending on `visibility`
- `interaction_request`: a tracked question workflow attached to a thread
- `task` and `run`: the durable execution handoff from collaboration into agent-runtime

Important rules:

- the effective tenant hierarchy is `platform > organization > workspace > thread`
- `users` are global human identities, `organization_memberships` hold org-level access, and `participants` remain workspace-local state
- `system_agents`, `system_tools`, `llm_providers`, and `memory_providers` can now be platform-global or organization-scoped
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

For workspace-level debugging, Open Talon now also exposes a communication log view backed by canonical `timeline_messages`. It aggregates thread messages, rendered interaction requests, and interaction answers across the workspace, and requires both participant attachment and the IAM permission `workspace.audit.read`. Finalized communications are also appended to workspace JSONL files under `OPEN_TALON_COMMUNICATION_LOG_DIR` (default: `infrastructure/data/communication-logs/<workspace_id>.jsonl`) so end-to-end collaboration traces survive outside the database. These JSONL files now rotate automatically with `OPEN_TALON_COMMUNICATION_LOG_MAX_BYTES` and `OPEN_TALON_COMMUNICATION_LOG_BACKUP_COUNT`, and local `./open-talon start` service logs under `.run/` rotate with `OPEN_TALON_SERVICE_LOG_MAX_BYTES` and `OPEN_TALON_SERVICE_LOG_BACKUP_COUNT`.

Common collaboration endpoints:

- `GET /v1/organizations`
- `POST /v1/organizations`
- `GET /v1/organizations/{organization_id}`
- `PATCH /v1/organizations/{organization_id}`
- `GET /v1/organizations/{organization_id}/members`
- `POST /v1/organizations/{organization_id}/members`
- `POST /v1/workspaces`
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

The admin web app lives in [apps/admin-web](/Users/nikolay.kvasov/Development/open-talon-1/apps/admin-web) and is the main browser surface for:

- organization creation and membership management
- runtime overview and operator visibility
- platform-global and organization-scoped LLM and memory provider management
- platform-global and organization-scoped system agent and system tool management
- Tinker tool-generation request review and approve/reject workflows
- workspace create, update, role override, and delete flows inside the selected organization
- admin API key management

Local usage:

```bash
cd apps/admin-web
npm install
npm run dev
```

With the local stack running, the default browser entrypoint is [http://localhost:5173](http://localhost:5173).

The local stack seeds a single backfilled organization named `Default Organization`, so the browser auto-selects it until you create more organizations.

The app expects:

- gateway API at `http://127.0.0.1:8000`
- Keycloak at `http://127.0.0.1:8081`
- Keycloak realm `open-talon`
- OIDC client `open-talon-web`

Deployment notes:

- the built SPA now reads browser runtime config from `apps/admin-web/public/runtime-config.json`
- that runtime file is meant to be replaced per environment so the same built artifact can move across dev, staging, and prod without rebuilding
- `appBasePath` in that file must match the deployed SPA mount point such as `/` or `/admin`
- the Vite bundle now emits relative asset paths so the app can be served from a subpath

See [apps/admin-web/README.md](/Users/nikolay.kvasov/Development/open-talon-1/apps/admin-web/README.md) for the full browser test and deployment guide.

## Operational Guardrails

The current defaults are aimed at a single medium-sized internal company deployment.

- global reads and writes for system agents, system tools, global Git repositories, global asset publish/link/activate flows, provider management, and global IAM management require the matching global IAM permission or platform-admin bootstrap access
- organization CRUD, organization membership changes, and organization-scoped IAM management require the relevant organization permissions, which are granted by membership baseline roles or explicit IAM role bindings
- workspace role-definition changes, workspace agent attachment/update/removal, workspace tool attach/update/delete, workspace Git repository creation, and workspace asset publishing require the matching workspace-scoped IAM permission together with participant attachment
- Tinker approval requires both `tool_generation.review` and `tool_catalog.write` in the requested publication scope
- human workspace access depends on organization membership first, then workspace participation
- workspace catalogs resolve as the union of platform-global resources and same-organization resources
- `GET /v1/workspaces` only returns workspaces where the authenticated human already has a participant record
- workspace-scoped reads intentionally return `404` for non-members so valid workspace and thread IDs are not enumerable
- risky tool execution profiles require `trust_level="trusted"`: `workspace_access=read_write`, `network=full`, and `local_process`

## Audit Logging

Open Talon now has a dedicated audit subsystem that is separate from the collaboration domain event stream.

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

An optional local HyperDX all-in-one profile is now available in Docker Compose for UI and OTLP intake experiments:

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

This means a tool is defined once at the platform or organization layer, then added to any compatible workspace that wants to advertise it to attached agents.

Generated tools now follow the same model through `Tinker`:

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

Open Talon now runs agent execution through durable stateless workers:

- Postgres is the source of truth for execution state
- Kafka is the wake-up and fanout bus
- `gateway-edge` no longer runs agent loops in-process
- `agent-task-worker` claims `tasks`, creates `runs`, and resolves the target LLM engine
- `agent-loop-worker` claims `run_steps` and executes model turns
- `tool-worker` claims `tool_calls` and dispatches isolated tool execution
- `reconciler` requeues expired leases and republishes wakeup events

Execution contracts are backend-neutral:

- `ExecutionSpec` is the payload envelope for isolated execution
- `ExecutionWorkspaceRef` identifies execution-side workspace materialization and is intentionally separate from the collaboration `Workspace` model
- `ExecutionResult` captures structured outputs, logs, artifacts, and terminal status

V1 execution backends:

- `docker`: default backend for arbitrary or untrusted tools
- `local_process`: minimal backend for tests and explicitly trusted built-ins

The Docker backend uses a short-lived container with a read-only root filesystem, dropped capabilities, no-new-privileges, resource limits, and `--network none` by default.

Runtime guardrails now also include:

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
- `GET /v1/organizations/{organization_id}/tools`: list organization-scoped tool definitions
- `PATCH /v1/tools/{tool_id}`: update a system-wide tool definition
- `GET /v1/workspaces/{workspace_id}/tools`: list tools attached to a workspace
- `PUT /v1/workspaces/{workspace_id}/tools/{tool_id}`: attach a system tool to a workspace
- `PATCH /v1/workspaces/{workspace_id}/tools/{tool_id}`: update workspace attachment state
- `DELETE /v1/workspaces/{workspace_id}/tools/{tool_id}`: detach a tool from a workspace
- `GET /v1/tool-generation/requests`: list tool-generation requests for admins
- `GET /v1/threads/{thread_id}/tool-generation/requests`: list tool-generation requests for a thread
- `POST /v1/tool-generation/revisions/{revision_id}/approve`: publish a generated tool into the system catalog

## Layered Memory

Open Talon now uses a layered memory model with a single canonical store and optional derived providers.

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

The provider abstraction lives in [services/workspace-memory/workspace_memory/providers.py](/Users/nikolay.kvasov/Development/open-talon-1/services/workspace-memory/workspace_memory/providers.py). `core-collab` always writes canonical memory first and then syncs enabled providers through the common provider interface.

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
- `PATCH /v1/memory-providers/{provider_id}`
- `DELETE /v1/memory-providers/{provider_id}`
- `POST /v1/memory-providers/{provider_id}/health-check`

## Extending Memory Providers

Open Talon is abstracted so additional memory providers can be added without changing the memory domain model.

Current built-in providers:

- `PostgresMemoryProvider`
- `Mem0MemoryProvider`

To add another provider:

1. Implement the `MemoryProvider` protocol in [services/workspace-memory/workspace_memory/providers.py](/Users/nikolay.kvasov/Development/open-talon-1/services/workspace-memory/workspace_memory/providers.py).
2. Register it in `build_provider_index(...)`.
3. Add a provider definition through the memory-provider admin API or seed it in a migration.
4. Reuse the shared secret resolution helpers in [services/workspace-memory/workspace_memory/secrets.py](/Users/nikolay.kvasov/Development/open-talon-1/services/workspace-memory/workspace_memory/secrets.py).
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
- **Keycloak**: Default local OIDC provider and the first machine-identity provisioning adapter used in development. Open Talon remains the source of truth for authorization.
- **Valkey**: Drop-in compatible Redis equivalent caching infrastructure configured to handle immediate TTL caching.
- **Langfuse**: Self-hosted LLM observability stack that can be used as one runtime observability backend for traces, prompts, and evaluations.
- **HyperDX**: Optional OTLP-compatible observability sink/UI for local investigations and runtime telemetry experiments.
- **Ollama AI**: Serves dynamic generative model orchestration natively mapped across standard REST.
    - Operates natively against Google's modern **Gemma 4** models, with the default test setup pulling the lightweight `gemma4:latest` model.

## Infrastructure

`./open-talon start` brings up the full local infrastructure stack and then starts the supported local processes for:

It now waits for both the gateway readiness endpoint and the configured OIDC discovery document before returning success. In local development, that means Keycloak browser, device-flow, and machine-credential auth should already have their dependencies online when the command exits.

- `gateway-edge`
- `agent-task-worker`
- `agent-loop-worker`
- `tool-worker`
- `reconciler`

Local services:

- `gateway-edge`: primary local API gateway for REST, SSE, WebSocket, collaboration, and admin APIs
- `agent-task-worker`: local worker that claims durable `tasks`, creates `runs`, and resolves the target LLM engine
- `agent-loop-worker`: local worker that executes agent model steps from durable `run_steps`
- `tool-worker`: local worker that executes isolated tool invocations from durable `tool_calls`
- `reconciler`: local worker that requeues expired leases and republishes wakeups
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
- `forgejo`: local Git forge for live repo workflows and authored agent/tool definitions
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

The compose stack currently pins pgAdmin to `dpage/pgadmin4:9.13.0` in [`infrastructure/docker-compose.yaml`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/docker-compose.yaml#L17) for reproducible local setup.

## Persistence Design

Local persistence uses host bind mounts under `infrastructure/data/...`.

That means:

- `./open-talon stop` and `docker compose down` stop containers without wiping local data
- `docker compose down -v` only removes Docker-managed volumes; it does not remove these bind-mounted directories
- OpenBao secrets, Postgres state, Forgejo repositories, Ollama model data, and other local payloads survive normal restarts until you remove the matching `infrastructure/data/...` directory yourself

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

The local OpenBao container now uses persistent file storage, so secrets survive `./open-talon stop` and `docker compose down`. To fully reset the local secret store, remove `infrastructure/data/openbao` before starting the stack again.

The runtime secret provider will then try `env` first and `openbao` second by default.

Common provider endpoints:

- `GET /v1/llm-providers`
- `POST /v1/llm-providers`
- `PATCH /v1/llm-providers/{provider_id}`
- `DELETE /v1/llm-providers/{provider_id}`
- `POST /v1/llm-providers/{provider_id}/health-check`
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
3. If the provider uses a provider-specific wire protocol, add an execution branch in [runtime.py](/Users/nikolay.kvasov/Development/open-talon-1/services/agent-runtime/agent_runtime/runtime.py), similar to the OpenAI path.
4. If the new provider needs a new secret backend instead of `env` or `openbao`, add a new `SecretProvider` implementation in [secrets.py](/Users/nikolay.kvasov/Development/open-talon-1/services/agent-runtime/agent_runtime/secrets.py) and register it in `build_default_secret_resolver()`.

For most API-key-based providers, the persistence and secret wiring should not require executor changes beyond the provider-specific request/response format.

## Quickstart

For the shortest end-to-end local setup flow, see [`docs/system-quickstart.md`](/Users/nikolay.kvasov/Development/open-talon-1/docs/system-quickstart.md).

## TUI

For TUI setup, usage, and slash command documentation, see [`apps/tui/README.md`](/Users/nikolay.kvasov/Development/open-talon-1/apps/tui/README.md).

For the end-to-end Tinker flow, including approval and manual workspace attachment, see [`docs/tinker-tool-generation.md`](/Users/nikolay.kvasov/Development/open-talon-1/docs/tinker-tool-generation.md).

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

Database schema changes are tracked as `dbmate`-style SQL files in [`db/migrations`](/Users/nikolay.kvasov/Development/open-talon-1/db/migrations).

- App startup and tests apply pending migrations through the repo's Python migration runner.
- For local manual migration work, use [`scripts/dbmate.sh`](/Users/nikolay.kvasov/Development/open-talon-1/scripts/dbmate.sh).
- `dbmate` itself is the recommended CLI for creating and applying new migration files.
- Default local values for `DATABASE_URL` and `DBMATE_MIGRATIONS_DIR` are documented in [`infrastructure/.env.example`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/.env.example).

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

For a longer reference, see [`docs/db-migrations.md`](/Users/nikolay.kvasov/Development/open-talon-1/docs/db-migrations.md).

## Langfuse

The local compose stack now includes a self-hosted Langfuse deployment:

- `langfuse-web` on `http://localhost:3000`
- `langfuse-worker` on port `3030`
- `clickhouse` on ports `8123` and `9000`
- `minio` on ports `9090` and `9091`
- `forgejo` on `http://localhost:3001` with SSH on port `2222`

This setup reuses the repository Postgres server and Valkey container, but Langfuse now uses its own Postgres database (`LANGFUSE_POSTGRES_DB`) so Prisma migrations do not collide with the application schema. Defaults live in `infrastructure/.env.example`.

Langfuse is no longer the only observability shape in the codebase. `agent-runtime` now exports through a provider layer:

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

# Full test coverage: default suite plus integration suite
pytest -q
pytest -m integration tests/infrastructure/test_infrastructure.py -v -s
pytest -m integration tests/infrastructure/test_tinker_live_system.py -q -s
```

## AI Model Initialization Note

First-time execution will wait for Ollama to fetch the configured default model from `infrastructure/.env`. The suite still allows long waits for first-run downloads, but it no longer assumes multiple heavyweight models by default.
