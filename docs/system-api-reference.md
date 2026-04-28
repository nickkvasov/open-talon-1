# Open Talon System And API Reference

This document is the current-state implementation reference for Open Talon.

Use it when you need to understand:

- how the running system is put together
- which service owns which responsibility
- how identities, participants, threads, requests, and execution records fit together
- which HTTP APIs exist today
- which APIs are intended for humans, browser clients, terminal clients, and software development agents

This is a reference for the implemented system. For local startup steps, use [system-quickstart.md](./system-quickstart.md). For repository coding guidance, use [../AGENTS.md](../AGENTS.md). For historical design background, use [collaboration-system-design.md](./collaboration-system-design.md).

## Audience

This reference is written for two audiences:

- Human engineers operating, extending, or integrating with Open Talon
- Software development agents that need a stable description of the system and API surface while acting as test users, operator agents, or workspace participants

## Documentation Map

- [system-quickstart.md](./system-quickstart.md): fastest path to a running local stack
- [iam.md](./iam.md): principal IAM model, permission catalog, and IAM API surface
- [agent-operations-guide.md](./agent-operations-guide.md): practical usage guide for software development agents and scripted clients
- [db-migrations.md](./db-migrations.md): schema and migration workflow
- [collaboration-system-design.md](./collaboration-system-design.md): historical design background and archived architecture notes
- [research-comparison.md](./research-comparison.md): external ecosystem comparison for multi-agent research and enterprise platforms
- [../AGENTS.md](../AGENTS.md): repository coding rules for contributors and coding agents

## System At A Glance

Open Talon is a local-first collaboration system where humans and agents are first-class participants inside shared project-owned workspaces under organizations.

The main runtime components are:

- `services/gateway-edge`
  - FastAPI gateway
  - main HTTP, SSE, and WebSocket entrypoint
  - auth, admin, collaboration, audit, and session chat routes
- `services/core-collab`
  - canonical collaboration kernel
  - repository layer over Postgres
  - source of truth for projects, workspaces, threads, participants, requests, tasks, runs, run steps, tool calls, memory, assets, and audit writes
- `services/agent-runtime`
  - stateless background workers
  - task claiming, agent loop execution, tool execution, and lease reconciliation
- `packages/contracts`
  - shared Pydantic contracts used across services and clients
- `apps/admin-web`
  - browser admin console for operators
- `apps/web`
  - gateway-mounted browser session-chat UI for the compatibility chat surface
- `apps/tui`
  - terminal clients for humans and software-driven test users
- `infrastructure`
  - local Docker-backed dependencies such as Postgres, Kafka, Valkey, Keycloak, OpenBao, Langfuse, MinIO, and optional Memgraph

## Current Runtime Inventory

The repository also includes helper packages that matter when you are documenting or extending the running system:

| Component | Role in the current system | Status in local runtime |
| --- | --- | --- |
| `services/workspace-memory` | memory-provider abstraction shared by gateway, core-collab, and runtime | active library, not a standalone service |
| `services/generated-tools-builder` | OCI packaging and publish helpers for generated tools | active helper library used by Tinker flows |
| `services/presence-directory` | Valkey-backed websocket presence state | active library used by `gateway-edge` |
| `apps/web` | browser client for the legacy session-chat routes | static app mounted by `gateway-edge` at `/` when the directory is present |

## Current Configuration Surface

The current implementation reads configuration from a small number of sources:

- [`infrastructure/.env.example`](../infrastructure/.env.example)
  - checked-in local defaults for ports, credentials, worker settings, audit providers, and model requirements
- `infrastructure/.env`
  - local override file consumed by Docker Compose and `./open-talon`
- [`services/gateway-edge/gateway_edge/config.py`](../services/gateway-edge/gateway_edge/config.py)
  - gateway defaults for auth, CORS, Postgres, Kafka, Valkey, audit providers, object storage, and OpenBao
- [`services/agent-runtime/agent_runtime/config.py`](../services/agent-runtime/agent_runtime/config.py)
  - runtime defaults for worker concurrency, leases, token caps, execution root, communication-log path, and OCI registry access
- [`apps/admin-web/public/runtime-config.json`](../apps/admin-web/public/runtime-config.json)
  - runtime-loadable browser config for gateway URL, Keycloak URL, realm, client ID, and SPA base path
- `.run/openai.env`
  - optional ignored local secret file auto-loaded by the Python services for secret resolution

Current auth nuance:

- code defaults in `gateway-edge` use `auth_mode="none"` when no env is set
- the local checked-in launcher and infra defaults set `AUTH_MODE=any`
- the practical local developer path is OIDC-first and also accepts API key and OpenBao auth unless you explicitly narrow the mode

## End-To-End Request Flow

The normal collaboration flow is:

1. A client calls `gateway-edge`.
2. The gateway resolves auth and actor identity.
3. The gateway calls `core-collab`.
4. `core-collab` writes canonical state to Postgres.
5. `core-collab` emits collaboration events and creates durable execution records when needed.
6. `agent-runtime` workers claim runnable work and execute model/tool steps.
7. Events and final state are read back through HTTP, SSE, or WebSocket clients.

The execution system is durable:

- Postgres is the source of truth
- Kafka is the wake-up and fanout bus
- workers are stateless
- retries are bounded and scheduled through `next_retry_at`

## Ownership Boundaries

The most important ownership rules are:

- `users` stores global human identity
- `auth_identities` maps external identity providers to `users`
- `organizations`, `projects`, `project_access_bindings`, and `organization_memberships` store the tenant and work hierarchy above workspaces
- `system_agents` stores platform-global and organization-scoped agent definitions
- managed operational contexts are seeded as `System Base / Administration / System Operations` plus `Administration / Organization Operations` for each non-system organization
- managed agents are ordinary system agents: `Tinker` (`generated tool authoring and validation agent`), `Steward` (`platform operations steward`), organization-scoped `Curator` (`organization operations curator`), workspace-attached `Anchor` (`workspace topic alignment reviewer`), global `Methodologist` (`methodology extraction and workspace design agent`), and global `Conductor` (`workspace methodics execution conductor`)
- the agent runtime is generic and must not branch on `agent_key`, display name, role text, capability text, or metadata tags; specialization belongs in agent definitions, harnesses, interaction contracts, task payloads, bindings, and tool/MCP allowlists
- `participants` stores workspace-local attachment and state for both humans and agents
- `threads` and `timeline_messages` are the shared collaboration surface
- `interaction_requests` and related tables implement tracked, resumable question workflows
- `tasks`, `runs`, `run_steps`, and `tool_calls` are durable execution records
- `memory_entries` in Postgres are canonical memory; provider-specific projections are derived
- `audit_event_ledger` is the canonical append-only audit store
- `collab_event_log` is the collaboration/event fanout stream, not the audit ledger

## Identity, Auth, And Actor Resolution

Open Talon separates identity from workspace presence.

### Global Identity

- Humans are identified globally by `users.user_id`
- External identity mappings live in `auth_identities`
- Agents are identified globally by `system_agents.agent_id`
- OIDC machine-credential linkage lives in `agent_identities`
- Global and organization IAM roles live in `iam_role_definitions` with separate human and agent bindings

### Organization Membership

- Organizations are identified by `organizations.organization_id`
- Projects are identified by `projects.project_id` and belong to one organization
- Projects record typed creator and owner references for either a user or system agent
- Organization-level project listing is controlled by organization `project.read`; specific project metadata, access management, and project workspace structure are controlled by `project_access_bindings`
- Project access bindings use `creator`, `owner`, `editor`, and `viewer` roles for users or system agents
- Project roles are evaluated as project-local permissions: `creator` and `owner` include project read/write, access management, workspace listing, and workspace creation; `editor` includes project read/write plus workspace listing/creation; `viewer` includes project read and workspace listing only
- Human org membership and membership roles live in `organization_memberships`
- Organization membership roles provide the baseline human permission bundle
- The external OIDC provider is not the source of truth for org membership or authorization
- New organizations receive both `Default Project` for ordinary workspace placement and `Administration` for managed operations.

### Workspace Presence

- `participants.participant_id` identifies the workspace-local materialization of a user or agent
- workspace `role_definitions` describe collaboration roles only; they do not grant permissions
- participant state includes:
  - status
  - visibility scope
  - collaboration roles
  - capabilities
  - timestamps
  - metadata

### Role Terminology

- `IAM role`
  Global or organization authorization role stored in `iam_role_definitions`.
- `organization membership role`
  Baseline human tenancy role stored in `organization_memberships.role`.
- `collaboration role`
  Workspace-local assumed role stored in `participants.roles` and used for routing with selectors such as `@role:frontend_engineer`.
- `capability`
  Workspace-local advertised label stored in `participants.capabilities` and used for selectors such as `@capability:qa_review`.
- `collaboration role definition`
  Workspace-local role description stored in `workspace.metadata.role_definitions`.
  This is separate from IAM and separate from collaboration roles used for routing.

### Auth Modes

`gateway-edge` supports:

- `none`
- `api_key`
- `openbao`
- `oidc`
- `any`

Current local development defaults use `AUTH_MODE=any`, with Keycloak as the default OIDC provider adapter. That means OIDC is the intended path for human users and agent identities, and API keys plus OpenBao auth are accepted locally unless you narrow the auth mode.

### Important Auth Rules

- authenticated human identity is derived server-side from the bearer token
- authenticated agent identity is derived server-side from the OIDC client token and mapped through `agent_identities`
- do not treat `participant_id` as a global human identifier
- organization membership is resolved from Postgres, not bearer-token claims
- non-member organization-scoped reads return `404`, not `403`
- non-member workspace-scoped reads return `404`, not `403`
- global system-definition, provider-management, and IAM-management APIs require matching global IAM permissions or platform-admin bootstrap access
- organization-scoped management flows require the relevant organization permissions, whether granted by membership baseline roles or explicit human or agent IAM role bindings
- workspace role, agent, tool, repository, and asset-management flows require the matching workspace-scoped IAM permission together with participant attachment
- out-of-scope reads return `404`; in-scope requests without the required permission return `403`

### Auth And Session APIs

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `GET` | `/health` | Liveness check | No auth |
| `GET` | `/ready` | Readiness check | No auth |
| `GET` | `/v1/me` | Resolved OIDC human identity | Requires OIDC human principal |

### MCP System API Adapter

`gateway-edge` also mounts an MCP server for OIDC-authenticated software clients.

Current MCP behavior:

- the MCP router is mounted only when `MCP_ENABLED=true`; the checked-in default is enabled
- the endpoint is `GET|POST /v1/mcp`
- `POST /v1/mcp` with `initialize` creates a session and returns `Mcp-Session-Id` in the response headers
- subsequent MCP `POST` calls and `GET /v1/mcp` notification streams require that `Mcp-Session-Id` header
- `GET /v1/mcp` opens an SSE stream for an existing MCP session and carries list-change notifications
- OAuth protected-resource metadata is published at `/.well-known/oauth-protected-resource` and `/.well-known/oauth-protected-resource/v1/mcp`
- `/v1/mcp` is always OIDC-only, even when the main gateway auth mode is `any`
- requests without an `Origin` header are allowed; when `Origin` is present it must match `MCP_ALLOWED_ORIGINS` or fall back to `CORS_ORIGINS`
- MCP session state is stored in Valkey with `MCP_SESSION_TTL_SECONDS` controlling session expiry; the default is `3600`
- MCP sessions keep an active scope of `global`, `organization:<id>`, `project:<id>`, or `workspace:<id>`
- successful scope changes emit `notifications/tools/list_changed` and `notifications/resources/list_changed`
- the visible MCP operation set is filtered from the caller's existing IAM permissions, project-local `creator`/`owner`/`editor`/`viewer` permissions in project scope, and workspace participant attachment where the underlying API already requires it
- successful operation calls return both a short text `content` summary and `structuredContent`; protocol/schema failures stay JSON-RPC errors
- MCP exposes system API operations only; it does not expose `system_tools`, `workspace_tools`, Tinker-generated tools, or `agent-runtime` execution backends as imported MCP tools
- External MCP server attachments are modeled separately under `/v1/mcp-servers` and `/v1/workspaces/{workspace_id}/mcp-servers`; they are not imported into Open Talon `system_tools`.

Current MCP session resources:

- `ot://session/identity`
- `ot://session/permissions`
- `ot://session/scope`

MCP HTTP endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/.well-known/oauth-protected-resource` | OAuth protected-resource metadata for the MCP resource server |
| `GET` | `/.well-known/oauth-protected-resource/v1/mcp` | versioned OAuth protected-resource metadata for the MCP resource server |
| `GET` | `/v1/mcp` | MCP SSE notification stream for an existing session |
| `POST` | `/v1/mcp` | MCP JSON-RPC request endpoint |

Current MCP bootstrap operations:

- `session.get_identity`
- `session.get_permissions`
- `session.list_scopes`
- `session.set_scope`

Current MCP system API operations:

- `organizations.list`
- `organizations.get`
- `organizations.members.list`
- `projects.list`
- `projects.create`
- `projects.get`
- `projects.update`
- `projects.access.list`
- `projects.access.upsert`
- `projects.access.remove`
- `workspaces.list`
- `workspaces.create`
- `workspaces.get`
- `threads.create`
- `threads.list`
- `threads.get`
- `threads.timeline.get`
- `threads.messages.create`
- `memory.workspace.list`
- `memory.workspace.create`
- `memory.thread.search`
- `retrieval.corpora.list`
- `retrieval.sources.list`
- `retrieval.search`
- `retrieval.context_pack.create`
- `retrieval.context_pack.get`
- `methodics.executions.create`
- `methodics.executions.list`
- `methodics.executions.get`
- `methodics.executions.cancel`
- `methodics.resource_requests.approve`
- `methodics.resource_requests.create`
- `methodics.resource_requests.reject`
- `agent_catalog.list`
- `agent_catalog.bundle.validate`
- `agent_catalog.bundle.publish`
- `tool_catalog.list`
- `llm_providers.list`
- `memory_providers.list`
- `mcp_servers.list`
- `runtime.overview.get`
- `audit.events.list`
- `audit.chains.verify`
- `agent_git.repo.ensure`
- `agent_git.worktree.create`
- `agent_git.file.read`
- `agent_git.file.write`
- `agent_git.file.delete`
- `agent_git.diff.preview`
- `agent_git.commit.push`
- `agent_git.worktree.discard`
- `iam.agent_identities.list`

### Principal IAM APIs

Open Talon uses one permission catalog for both humans and agents:

- identity permissions protect global and organization control-plane APIs
- workspace-scoped IAM permissions protect workspace management APIs, and the caller must also be attached as a workspace participant
- local Keycloak `admin` acts as a bootstrap path, while steady-state authorization comes from Open Talon IAM roles

Representative IAM routes:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/iam/permissions` | list the shared permission catalog |
| `GET` | `/v1/iam/human-roles` | list global human IAM roles |
| `POST` | `/v1/iam/human-roles` | create global human IAM role |
| `PATCH` | `/v1/iam/human-roles/{role_id}` | update global human IAM role |
| `DELETE` | `/v1/iam/human-roles/{role_id}` | delete global human IAM role |
| `GET` | `/v1/iam/agent-roles` | list global agent IAM roles |
| `POST` | `/v1/iam/agent-roles` | create global agent IAM role |
| `PATCH` | `/v1/iam/agent-roles/{role_id}` | update global agent IAM role |
| `DELETE` | `/v1/iam/agent-roles/{role_id}` | delete global agent IAM role |
| `GET` | `/v1/iam/users/{user_id}/roles` | list direct human IAM role bindings |
| `POST` | `/v1/iam/users/{user_id}/roles/{role_id}` | bind a human IAM role |
| `DELETE` | `/v1/iam/users/{user_id}/roles/{role_id}` | unbind a human IAM role |
| `GET` | `/v1/iam/agent-identities` | list agent identities |
| `POST` | `/v1/iam/agent-identities` | provision agent identity and return one-time secret |
| `GET` | `/v1/iam/agent-identities/{agent_identity_id}` | get one agent identity |
| `GET` | `/v1/iam/agent-identities/{agent_identity_id}/roles` | list IAM roles bound to an agent identity |
| `POST` | `/v1/iam/agent-identities/{agent_identity_id}/roles/{role_id}` | bind an IAM role to an agent identity |
| `DELETE` | `/v1/iam/agent-identities/{agent_identity_id}/roles/{role_id}` | unbind an IAM role from an agent identity |
| `POST` | `/v1/iam/agent-identities/{agent_identity_id}/rotate-secret` | rotate agent-identity secret |
| `POST` | `/v1/iam/agent-identities/{agent_identity_id}/disable` | disable agent identity |
| `POST` | `/v1/iam/agent-identities/{agent_identity_id}/enable` | re-enable agent identity |
| `GET` | `/v1/organizations/{organization_id}/iam/human-roles` | list org-scoped human IAM roles |
| `POST` | `/v1/organizations/{organization_id}/iam/human-roles` | create org-scoped human IAM role |
| `PATCH` | `/v1/organizations/{organization_id}/iam/human-roles/{role_id}` | update org-scoped human IAM role |
| `DELETE` | `/v1/organizations/{organization_id}/iam/human-roles/{role_id}` | delete org-scoped human IAM role |
| `GET` | `/v1/organizations/{organization_id}/iam/agent-roles` | list org-scoped agent IAM roles |
| `POST` | `/v1/organizations/{organization_id}/iam/agent-roles` | create org-scoped agent IAM role |
| `PATCH` | `/v1/organizations/{organization_id}/iam/agent-roles/{role_id}` | update org-scoped agent IAM role |
| `DELETE` | `/v1/organizations/{organization_id}/iam/agent-roles/{role_id}` | delete org-scoped agent IAM role |
| `GET` | `/v1/organizations/{organization_id}/iam/users/{user_id}/roles` | list org-scoped human IAM role bindings |
| `POST` | `/v1/organizations/{organization_id}/iam/users/{user_id}/roles/{role_id}` | bind an org-scoped human IAM role |
| `DELETE` | `/v1/organizations/{organization_id}/iam/users/{user_id}/roles/{role_id}` | unbind an org-scoped human IAM role |
| `GET` | `/v1/organizations/{organization_id}/iam/agent-identities` | list org-scoped agent identities |
| `POST` | `/v1/organizations/{organization_id}/iam/agent-identities` | provision org-scoped agent identity |

Current IAM route guards:

- role and agent-identity listing routes require `organization.members.read`
- role, binding, provisioning, rotate, enable, and disable routes require `organization.members.write`
- the same permission names are evaluated globally or inside the target organization scope depending on the route
- the MCP adapter reuses those same permission checks and does not introduce a second authorization system

For the complete permission list and current behavior, use [iam.md](./iam.md).

## Collaboration Domain Model

The current collaboration model uses the tenant hierarchy `platform > organization > project > workspace > thread`.

### Core Entities

| Entity | Meaning |
| --- | --- |
| `organization` | tenant boundary above projects |
| `project` | organization-local work grouping that owns workspaces |
| `workspace` | collaboration boundary inside a project |
| `participant` | workspace-local user or agent presence |
| `thread` | shared collaboration stream inside a workspace |
| `timeline_message` | ordered thread message |
| `interaction_request` | tracked multi-question request workflow |
| `task` | durable unit of work for an agent |
| `run` | concrete execution instance for a task |
| `run_step` | a model step inside a run |
| `tool_call` | isolated tool execution request |
| `memory_entry` | canonical thread/workspace/run memory |
| `workspace_asset` | published immutable asset with versions and links |

### Current Interaction Request Semantics

Tracked requests support:

- one or more ordered questions
- one or more explicit targets
- participant business-role and capability-based selector routing
- answer aggregation across several participants
- gated agent resume only when the completion rule is satisfied

Supported completion rules:

- `all_targets`
- `minimum_answers`
- `one_per_selector_bucket`
- `custom_targets`

### Key Shared Contracts

The canonical model definitions live in `packages/contracts/open_talon_contracts/models.py`.

Important contracts:

- `Organization`
- `OrganizationMembership`
- `ParticipantInput`
- `ParticipantProfile`
- `RoleDefinition`
- `ThreadDetail`
- `CreateMessageRequest`
- `ParticipantSelector`
- `CompletionRule`
- `CreateInteractionRequest`
- `CreateInteractionAnswerRequest`
- `InteractionRequestDetail`
- `WorkspaceCommunicationLogEntry`
- `MemoryEntry`
- `AgentDefinition`
- `SystemToolDefinition`
- `LlmProviderDefinition`
- `MemoryProviderDefinition`
- `GitRepository`
- `WorkspaceAsset`
- `WorkspaceAssetVersion`
- `AgentExecutionContext`
- `AgentRunResult`

## Persistence And Event Model

### Canonical Stores

- Postgres
  - collaboration state
  - execution state
  - canonical memory
  - canonical audit
- Valkey
  - session and ephemeral presence support
- Kafka
  - collaboration event fanout
  - worker wakeups
- MinIO
  - published assets
  - audit exports and checkpoints
- ClickHouse
  - audit projection for query workloads
- Langfuse
  - observability and tracing

### Communication Logging

Open Talon has two collaboration-debugging views:

- API view:
  - `GET /v1/workspaces/{workspace_id}/communication-log`
  - backed by canonical `timeline_messages`
- file view:
  - finalized communication entries are appended to `OPEN_TALON_COMMUNICATION_LOG_DIR/<workspace_id>.jsonl`
  - each line is a `WorkspaceCommunicationLogEntry`

The communication log captures:

- regular thread messages
- rendered interaction request messages
- interaction answers

It does not replace:

- audit
- task/run/run_step/tool_call inspection
- the collaboration event stream

## API Conventions

### Base Path

Most current APIs live under `/v1`.

Main router groups:

- `/health`, `/ready`
- `/v1/me`
- `/v1/chat`, `/v1/chat/stream`, `/v1/ws/chat/{session_id}`
- `/v1/...` collaboration, memory, audit, assets, providers, and system definitions
- `/v1/admin/...`

### Actor Resolution

Many collaboration write requests carry an `actor` shape for compatibility with non-OIDC and system-initiated flows.

Rules:

- human OIDC requests are resolved server-side
- for thread-scoped writes, the gateway resolves the effective thread actor
- for workspace-scoped writes, the gateway resolves the effective workspace actor
- software agents using API-key or system/operator flows can supply actor payloads directly

### Visibility

Valid message visibility values are:

- `public`
- `workspace`
- `agents_only`
- `private`

The current business collaboration flow uses thread-native shared messages, most often `workspace`.

### Error Behavior

Important behavior to rely on:

- `404` for non-member organization-scoped reads
- `404` for non-member workspace-scoped reads
- `403` for membership-present but insufficient role
- validation errors for malformed request payloads
- `PermissionError`-style domain failures mapped into HTTP errors by the gateway

### Pagination

Current explicit pagination appears on:

- workspace communication log
- audit event list

Use `limit` and `offset` where exposed.

## Current API Snapshot

Current implementation snapshot from the FastAPI app:

- HTTP route truth lives in the generated OpenAPI document at `/openapi.json`
- websocket routes implemented outside OpenAPI are:
  - `/v1/ws/chat/{session_id}`
  - `/v1/threads/{thread_id}/ws`
- the router split is:
  - `health`
  - `auth`
  - `chat`
  - `collaboration`
  - `iam`
  - `admin`

For websocket truth, prefer [`services/gateway-edge/gateway_edge/routers/chat.py`](../services/gateway-edge/gateway_edge/routers/chat.py) and [`services/gateway-edge/gateway_edge/routers/collaboration.py`](../services/gateway-edge/gateway_edge/routers/collaboration.py).

## Endpoint Catalog

This section groups the currently implemented API surface by purpose.

### Health, Auth, And Session Chat

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/health` | liveness |
| `GET` | `/ready` | readiness |
| `GET` | `/v1/me` | authenticated user identity |
| `POST` | `/v1/chat` | synchronous session chat |
| `POST` | `/v1/chat/stream` | SSE session chat streaming |
| `GET` | `/v1/history/{session_id}` | session chat history |
| `GET` | `/v1/sessions/{session_id}` | session info |
| `DELETE` | `/v1/sessions/{session_id}` | session delete |
| `WS` | `/v1/ws/chat/{session_id}` | bidirectional chat streaming |

The `chat` APIs provide a session-based chat surface. Shared collaboration flows use workspaces, threads, timeline messages, and interaction requests.

### Workspaces, Participants, And Roles

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/v1/organizations` | list visible organizations |
| `POST` | `/v1/organizations` | create organization |
| `GET` | `/v1/organizations/by-slug/{organization_slug}` | organization detail by normalized slug |
| `GET` | `/v1/organizations/{organization_id}` | organization detail |
| `PATCH` | `/v1/organizations/{organization_id}` | update organization |
| `GET` | `/v1/organizations/{organization_id}/members` | list org memberships |
| `POST` | `/v1/organizations/{organization_id}/members` | add org member |
| `DELETE` | `/v1/organizations/{organization_id}/members/{user_id}` | remove org member |
| `GET` | `/v1/organizations/{organization_id}/projects` | list organization projects |
| `POST` | `/v1/organizations/{organization_id}/projects` | create organization project |
| `GET` | `/v1/organizations/{organization_id}/projects/{project_id}` | project detail |
| `PATCH` | `/v1/organizations/{organization_id}/projects/{project_id}` | update project |
| `GET` | `/v1/organizations/{organization_id}/projects/{project_id}/access` | list project access bindings |
| `PUT` | `/v1/organizations/{organization_id}/projects/{project_id}/access` | create or update project access |
| `DELETE` | `/v1/organizations/{organization_id}/projects/{project_id}/access` | remove project access |
| `POST` | `/v1/workspaces` | create workspace |
| `GET` | `/v1/workspaces` | list visible workspaces |
| `POST` | `/v1/organizations/{organization_id}/workspaces` | create workspace in organization |
| `GET` | `/v1/organizations/{organization_id}/workspaces` | list organization workspaces |
| `POST` | `/v1/organizations/{organization_id}/projects/{project_id}/workspaces` | create workspace in project |
| `GET` | `/v1/organizations/{organization_id}/projects/{project_id}/workspaces` | list project workspaces |
| `GET` | `/v1/organizations/{organization_id}/runtime/overview` | organization runtime overview |
| `GET` | `/v1/workspaces/{workspace_id}` | workspace detail |
| `PATCH` | `/v1/workspaces/{workspace_id}` | workspace metadata update |
| `DELETE` | `/v1/workspaces/{workspace_id}` | delete workspace |
| `GET` | `/v1/workspaces/{workspace_id}/participants` | list participant advertisements |
| `GET` | `/v1/workspaces/{workspace_id}/catalog/agents` | list agents visible to workspace |
| `GET` | `/v1/workspaces/{workspace_id}/catalog/tools` | list tools visible to workspace |
| `DELETE` | `/v1/workspaces/{workspace_id}/participants/{participant_id}` | remove participant |
| `PATCH` | `/v1/workspaces/{workspace_id}/participants/{participant_id}/role` | assume collaboration role |
| `POST` | `/v1/workspaces/{workspace_id}/agents` | attach a system agent to a workspace |
| `PATCH` | `/v1/workspaces/{workspace_id}/agents/{participant_id}` | update attached agent participant |
| `PUT` | `/v1/workspaces/{workspace_id}/roles/{role_name}` | create/update role definition |
| `DELETE` | `/v1/workspaces/{workspace_id}/roles/{role_name}` | delete role definition |

Workspace responses include `created_by`, `creator_user_id`, and `creator_system_agent_id` so human-created and agent-created workspaces can be attributed without relying on metadata.

### System Definitions

Global system-definition APIs are operator/admin APIs.

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/v1/llm-engines` | list registered LLM engines |
| `POST` | `/v1/agents` | create system agent definition |
| `GET` | `/v1/agents` | list system agent definitions |
| `GET` | `/v1/agents/{agent_id}` | get agent definition by id |
| `POST` | `/v1/organizations/{organization_id}/agents` | create org-scoped agent definition |
| `GET` | `/v1/organizations/{organization_id}/agents` | list org-scoped agent definitions |
| `GET` | `/v1/organizations/{organization_id}/agents/{agent_id}` | get org-scoped agent definition by id |
| `PATCH` | `/v1/agents/{agent_id}` | update agent definition by id |
| `PATCH` | `/v1/organizations/{organization_id}/agents/{agent_id}` | update org-scoped agent definition |
| `DELETE` | `/v1/agents/{agent_id}` | delete agent definition by id |
| `DELETE` | `/v1/organizations/{organization_id}/agents/{agent_id}` | delete org-scoped agent definition |
| `POST` | `/v1/tools` | create system tool |
| `GET` | `/v1/tools` | list system tools |
| `GET` | `/v1/tools/{tool_id}` | get tool definition by id |
| `POST` | `/v1/organizations/{organization_id}/tools` | create org-scoped system tool |
| `GET` | `/v1/organizations/{organization_id}/tools` | list org-scoped system tools |
| `GET` | `/v1/organizations/{organization_id}/tools/{tool_id}` | get org-scoped tool definition by id |
| `PATCH` | `/v1/tools/{tool_id}` | update tool definition by id |
| `PATCH` | `/v1/organizations/{organization_id}/tools/{tool_id}` | update org-scoped tool definition |
| `DELETE` | `/v1/tools/{tool_id}` | delete tool definition by id |
| `DELETE` | `/v1/organizations/{organization_id}/tools/{tool_id}` | delete org-scoped tool definition |
| `POST` | `/v1/llm-providers` | create LLM provider definition |
| `POST` | `/v1/organizations/{organization_id}/llm-providers` | create org-scoped LLM provider |
| `POST` | `/v1/llm-providers/validate` | validate LLM provider without persisting |
| `GET` | `/v1/llm-providers` | list LLM providers |
| `GET` | `/v1/organizations/{organization_id}/llm-providers` | list org-scoped LLM providers |
| `GET` | `/v1/llm-providers/{provider_id}` | get LLM provider definition by id |
| `GET` | `/v1/organizations/{organization_id}/llm-providers/{provider_id}` | get org-scoped LLM provider by id |
| `PATCH` | `/v1/llm-providers/{provider_id}` | update LLM provider by id |
| `PATCH` | `/v1/organizations/{organization_id}/llm-providers/{provider_id}` | update org-scoped LLM provider |
| `DELETE` | `/v1/llm-providers/{provider_id}` | delete LLM provider |
| `DELETE` | `/v1/organizations/{organization_id}/llm-providers/{provider_id}` | delete org-scoped LLM provider |
| `POST` | `/v1/llm-providers/{provider_id}/health-check` | validate stored LLM provider |
| `POST` | `/v1/organizations/{organization_id}/llm-providers/{provider_id}/health-check` | validate org-scoped stored LLM provider |
| `POST` | `/v1/memory-providers` | create memory provider definition |
| `POST` | `/v1/organizations/{organization_id}/memory-providers` | create org-scoped memory provider |
| `POST` | `/v1/memory-providers/validate` | validate memory provider without persisting |
| `GET` | `/v1/memory-providers` | list memory providers |
| `GET` | `/v1/organizations/{organization_id}/memory-providers` | list org-scoped memory providers |
| `GET` | `/v1/memory-providers/{provider_id}` | get memory provider definition by id |
| `GET` | `/v1/organizations/{organization_id}/memory-providers/{provider_id}` | get org-scoped memory provider by id |
| `PATCH` | `/v1/memory-providers/{provider_id}` | update memory provider by id |
| `PATCH` | `/v1/organizations/{organization_id}/memory-providers/{provider_id}` | update org-scoped memory provider |
| `DELETE` | `/v1/memory-providers/{provider_id}` | delete memory provider |
| `DELETE` | `/v1/organizations/{organization_id}/memory-providers/{provider_id}` | delete org-scoped memory provider |
| `POST` | `/v1/memory-providers/{provider_id}/health-check` | validate stored memory provider |
| `POST` | `/v1/organizations/{organization_id}/memory-providers/{provider_id}/health-check` | validate org-scoped stored memory provider |

In the current implementation, org-scoped create/list routes are explicit. Update and delete endpoints for providers, tools, and agents live on the top-level admin surface.

System-agent definitions accept an optional typed `harness.compaction_policy` object. Current strategies are `full_context`, `recent_window`, `rolling_summary`, and `summary_plus_retrieval`; the runtime applies this policy immediately before prompt rendering without mutating the canonical `AgentExecutionContext`.

`Methodologist` is a seeded global system agent for turning cited retrieval/source evidence into methodology basis, methodics, methods/tools, actor responsibilities, and workspace template drafts. It does not add a special runtime path; behavior comes from its agent definition, harness, response contract, retrieval context supplied to the run, and any workspace/tool/MCP bindings granted by IAM.

`Conductor` is a separate seeded global system agent for active workspace methodics execution. It is opt-in per workspace through normal agent attachment. If Conductor is not attached, `WorkspaceHarness.methodics` remains passive guidance and starting execution returns `409 Conflict`.

Git-managed system and organization agent definitions are authored as modular bundles under `agents/<agent_key>/` and published through the gateway. The publish flow compiles the bundle into the existing `system_agents` runtime projection and writes immutable `agent_definition_versions` history. Runtime workers continue to read Postgres only; Forgejo and managed worktrees are authoring infrastructure, not runtime dependencies.

### Git Repositories, Assets, And Tool Attachments

| Method | Path | Summary |
| --- | --- | --- |
| `POST` | `/v1/git-repositories` | register global Git repository |
| `GET` | `/v1/git-repositories` | list global Git repositories |
| `POST` | `/v1/organizations/{organization_id}/git-repositories` | register org Git repository |
| `GET` | `/v1/organizations/{organization_id}/git-repositories` | list org Git repositories |
| `POST` | `/v1/agents/validate-from-git` | validate system-wide agent bundle |
| `POST` | `/v1/organizations/{organization_id}/agents/validate-from-git` | validate org-wide agent bundle |
| `POST` | `/v1/agents/publish-from-git` | publish system-wide agent bundle |
| `POST` | `/v1/organizations/{organization_id}/agents/publish-from-git` | publish org-wide agent bundle |
| `POST` | `/v1/agents/bundles/upload` | upload, commit, and optionally publish system-wide agent bundle archive |
| `POST` | `/v1/organizations/{organization_id}/agents/bundles/upload` | upload, commit, and optionally publish org-wide agent bundle archive |
| `GET` | `/v1/agents/{agent_id}/versions` | list published agent definition versions |
| `GET` | `/v1/organizations/{organization_id}/agents/{agent_id}/versions` | list org agent definition versions |
| `POST` | `/v1/agents/{agent_id}/versions/{agent_version_id}/activate` | activate a prior agent definition version |
| `POST` | `/v1/organizations/{organization_id}/agents/{agent_id}/versions/{agent_version_id}/activate` | activate an org agent definition version |
| `POST` | `/v1/agent-git/worktrees` | create system-wide managed agent-authoring worktree |
| `POST` | `/v1/organizations/{organization_id}/agent-git/worktrees` | create org managed agent-authoring worktree |
| `GET` | `/v1/agent-git/worktrees/{session_id}/files` | read managed worktree file |
| `PUT` | `/v1/agent-git/worktrees/{session_id}/files` | write managed worktree file |
| `DELETE` | `/v1/agent-git/worktrees/{session_id}/files` | delete managed worktree file |
| `GET` | `/v1/agent-git/worktrees/{session_id}/diff` | preview managed worktree diff |
| `POST` | `/v1/agent-git/worktrees/{session_id}/commit` | commit and optionally push managed worktree |
| `DELETE` | `/v1/agent-git/worktrees/{session_id}` | discard managed worktree |
| `POST` | `/v1/assets/publish-from-git` | publish global asset version |
| `POST` | `/v1/organizations/{organization_id}/assets/publish-from-git` | publish org asset version |
| `GET` | `/v1/organizations/{organization_id}/assets` | list org assets |
| `GET` | `/v1/assets` | list assets |
| `GET` | `/v1/assets/{asset_id}/versions` | list asset versions |
| `POST` | `/v1/assets/{asset_id}/links` | link asset version to target |
| `POST` | `/v1/assets/{asset_id}/activate` | activate asset version |
| `GET` | `/v1/assets/{asset_id}/download` | presigned asset download URL |
| `GET` | `/v1/agents/{agent_id}/assets` | resolve agent asset bindings |
| `GET` | `/v1/tools/{tool_id}/assets` | resolve tool asset bindings |
| `POST` | `/v1/files` | upload global file asset version |
| `GET` | `/v1/files` | list global file assets |
| `POST` | `/v1/organizations/{organization_id}/files` | upload org file asset version |
| `GET` | `/v1/organizations/{organization_id}/files` | list org file assets |
| `POST` | `/v1/workspaces/{workspace_id}/files` | upload workspace file asset version |
| `GET` | `/v1/workspaces/{workspace_id}/files` | list workspace file assets |
| `GET` | `/v1/files/{asset_id}/versions` | list file asset versions |
| `GET` | `/v1/files/{asset_id}/download` | presigned file download URL |
| `GET` | `/v1/workspaces/{workspace_id}/tools` | list attached workspace tools |
| `PUT` | `/v1/workspaces/{workspace_id}/tools/{tool_id}` | attach tool to workspace |
| `PATCH` | `/v1/workspaces/{workspace_id}/tools/{tool_id}` | update workspace tool attachment |
| `DELETE` | `/v1/workspaces/{workspace_id}/tools/{tool_id}` | detach tool from workspace |
| `POST` | `/v1/mcp-servers` | create global external MCP server |
| `GET` | `/v1/mcp-servers` | list global external MCP servers |
| `GET` | `/v1/mcp-servers/{server_id}` | get external MCP server |
| `PATCH` | `/v1/mcp-servers/{server_id}` | update external MCP server |
| `DELETE` | `/v1/mcp-servers/{server_id}` | delete external MCP server |
| `GET` | `/v1/mcp-servers/{server_id}/tools` | list discovered MCP tools |
| `GET` | `/v1/mcp-servers/{server_id}/resources` | list discovered MCP resources |
| `GET` | `/v1/mcp-servers/{server_id}/prompts` | list discovered MCP prompts |
| `POST` | `/v1/organizations/{organization_id}/mcp-servers` | create organization-scoped external MCP server |
| `GET` | `/v1/organizations/{organization_id}/mcp-servers` | list organization-scoped external MCP servers |
| `GET` | `/v1/workspaces/{workspace_id}/catalog/mcp-servers` | list MCP servers visible to workspace |
| `GET` | `/v1/workspaces/{workspace_id}/mcp-servers` | list MCP servers attached to workspace |
| `PUT` | `/v1/workspaces/{workspace_id}/mcp-servers/{server_id}` | attach MCP server to workspace |
| `PATCH` | `/v1/workspaces/{workspace_id}/mcp-servers/{server_id}` | update MCP server attachment |
| `DELETE` | `/v1/workspaces/{workspace_id}/mcp-servers/{server_id}` | detach MCP server from workspace |
| `GET` | `/v1/workspaces/{workspace_id}/mcp-tools` | list workspace-visible MCP tools |
| `GET` | `/v1/workspaces/{workspace_id}/mcp-resources` | list workspace-visible MCP resources |
| `GET` | `/v1/workspaces/{workspace_id}/mcp-prompts` | list workspace-visible MCP prompts |
| `POST` | `/v1/workspaces/{workspace_id}/git-repositories` | register workspace Git repository |
| `GET` | `/v1/workspaces/{workspace_id}/git-repositories` | list workspace Git repositories |
| `POST` | `/v1/workspaces/{workspace_id}/assets/publish-from-git` | publish workspace asset version |

### Retrieval APIs

Retrieval corpora, sources, jobs, runs, and context packs are scoped as `global`, `organization`, or `workspace`. Raw file bytes stay in MinIO as immutable `workspace_assets` versions; retrieval rows link back to `asset_id` and `asset_version_id`. Workspace retrieval requires participant attachment plus the matching retrieval permission.

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/v1/retrieval/profiles` | list global retrieval profiles |
| `POST` | `/v1/retrieval/profiles` | create global retrieval profile |
| `GET` | `/v1/retrieval/corpora` | list global retrieval corpora |
| `POST` | `/v1/retrieval/corpora` | create global retrieval corpus |
| `GET` | `/v1/retrieval/sources` | list global retrieval sources |
| `POST` | `/v1/retrieval/sources` | link a global file asset to a corpus |
| `GET` | `/v1/retrieval/jobs` | list global retrieval ingestion jobs |
| `POST` | `/v1/retrieval/corpora/{corpus_id}/jobs` | enqueue global source ingestion |
| `POST` | `/v1/retrieval/search` | search global retrieval corpora |
| `POST` | `/v1/retrieval/context-packs` | create global cited context pack |
| `GET` | `/v1/retrieval/context-packs/{context_pack_id}` | get global context pack |
| `GET/POST` | `/v1/organizations/{organization_id}/retrieval/...` | organization-scoped equivalent routes |
| `GET/POST` | `/v1/workspaces/{workspace_id}/retrieval/...` | workspace-scoped equivalent routes |

The default vector backend is pgvector. The default embedding provider is configurable Ollama via `RETRIEVER_DEFAULT_EMBEDDING_PROVIDER`, `RETRIEVER_DEFAULT_EMBEDDING_MODEL`, and `RETRIEVER_OLLAMA_BASE_URL`. Visual extraction is disabled by default; when enabled, Retriever resolves the visual extraction LLM through the shared `llm_providers` engine registry, defaulting to `RETRIEVER_DEFAULT_VISION_ENGINE_ID=local-ollama`.

### Methodics Execution APIs

Methodics execution is workspace-scoped and opt-in. Conductor must already be attached as a workspace agent participant before an authorized human caller starts execution from the active `WorkspaceHarness.methodics`; otherwise the start route returns `409 Conflict`. Start/cancel and resource request approval/rejection are human-gated. Conductor receives targeted methodics tasks and can read execution state or create pending resource requests, but its managed internal MCP allowlist excludes the human control operations.

| Method | Path | Summary |
| --- | --- | --- |
| `POST` | `/v1/workspaces/{workspace_id}/methodics/executions` | start Conductor execution of active workspace methodics |
| `GET` | `/v1/workspaces/{workspace_id}/methodics/executions` | list workspace methodics executions |
| `GET` | `/v1/workspaces/{workspace_id}/methodics/executions/{execution_id}` | get execution detail with steps, assignments, checks, and resource requests |
| `POST` | `/v1/workspaces/{workspace_id}/methodics/executions/{execution_id}/cancel` | cancel a methodics execution |
| `POST` | `/v1/workspaces/{workspace_id}/methodics/executions/{execution_id}/resource-requests` | create a pending Conductor resource request |
| `POST` | `/v1/workspaces/{workspace_id}/methodics/resource-requests/{resource_request_id}/approve` | approve a Conductor resource request |
| `POST` | `/v1/workspaces/{workspace_id}/methodics/resource-requests/{resource_request_id}/reject` | reject a Conductor resource request |

### Tool Generation And Approval

These routes support the current Tinker flow:

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/v1/tool-generation/requests` | list tool-generation requests |
| `GET` | `/v1/tool-generation/requests/{request_id}` | get one tool-generation request |
| `GET` | `/v1/threads/{thread_id}/tool-generation/requests` | list thread-local tool-generation requests |
| `POST` | `/v1/tool-generation/requests/{request_id}/revisions` | create a new generated-tool revision |
| `POST` | `/v1/tool-generation/revisions/{revision_id}/approve` | approve revision and trigger registry verification |
| `POST` | `/v1/tool-generation/revisions/{revision_id}/reject` | reject revision |

Current business rules:

- generated tools can target `global` or `organization` publication scope
- approval publishes only into the system catalog, never directly into `workspace_tools`
- approval requires `tool_generation.review` plus `tool_catalog.write` in the target scope
- after approval, workspace participants attach the tool manually with `PUT /v1/workspaces/{workspace_id}/tools/{tool_id}`

### Threads, Timeline, And Interaction Requests

| Method | Path | Summary |
| --- | --- | --- |
| `POST` | `/v1/workspaces/{workspace_id}/threads` | create thread |
| `GET` | `/v1/workspaces/{workspace_id}/threads` | list threads |
| `GET` | `/v1/workspaces/{workspace_id}/communication-log` | workspace communication log |
| `GET` | `/v1/threads/{thread_id}` | thread detail |
| `GET` | `/v1/threads/{thread_id}/timeline` | timeline |
| `POST` | `/v1/threads/{thread_id}/messages` | post message |
| `GET` | `/v1/threads/{thread_id}/requests` | list tracked requests |
| `POST` | `/v1/threads/{thread_id}/requests` | create tracked requests |
| `GET` | `/v1/requests/{request_id}` | request detail |
| `PATCH` | `/v1/requests/{request_id}` | update request state |
| `POST` | `/v1/requests/{request_id}/answers` | answer request |
| `GET` | `/v1/threads/{thread_id}/events/stream` | SSE thread event stream |
| `WS` | `/v1/threads/{thread_id}/ws` | WebSocket thread event stream |

Important request behavior:

- `POST /v1/threads/{thread_id}/messages`
  - can create a plain timeline message
  - can also atomically create tracked interaction requests through `CreateMessageRequest.requests`
  - can include `task_instructions`, which are persisted into the created task metadata and rendered as run-local instructions without expanding IAM or MCP/tool allowlists
- `POST /v1/threads/{thread_id}/requests`
  - directly creates tracked requests
- `POST /v1/requests/{request_id}/answers`
  - appends a normal thread message linked to the request

### Memory APIs

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/v1/workspaces/{workspace_id}/memory` | list workspace memory |
| `POST` | `/v1/workspaces/{workspace_id}/memory` | create workspace memory |
| `POST` | `/v1/workspaces/{workspace_id}/memory/confirm` | confirm candidate/thread memory into workspace memory |
| `PATCH` | `/v1/workspaces/{workspace_id}/memory/{memory_entry_id}` | update workspace memory |
| `DELETE` | `/v1/workspaces/{workspace_id}/memory/{memory_entry_id}` | delete workspace memory |
| `GET` | `/v1/threads/{thread_id}/memory` | list confirmed thread memory |
| `POST` | `/v1/threads/{thread_id}/memory` | create thread memory |
| `POST` | `/v1/threads/{thread_id}/memory/search` | semantic search thread memory |
| `PATCH` | `/v1/threads/{thread_id}/memory/{memory_entry_id}` | update thread memory |
| `DELETE` | `/v1/threads/{thread_id}/memory/{memory_entry_id}` | archive thread memory |

### Audit APIs

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/v1/audit/events` | list audit events |
| `GET` | `/v1/organizations/{organization_id}/audit/events` | list org audit events |
| `GET` | `/v1/audit/events/{audit_event_id}` | fetch one audit event |
| `GET` | `/v1/audit/chains/{chain_partition}/verify` | verify audit chain |
| `POST` | `/v1/audit/events/export` | export audit events to object storage |
| `POST` | `/v1/organizations/{organization_id}/audit/events/export` | export org audit events |

### Admin APIs

| Method | Path | Summary |
| --- | --- | --- |
| `POST` | `/v1/admin/api-keys` | create API key |
| `GET` | `/v1/admin/api-keys` | list API keys |
| `DELETE` | `/v1/admin/api-keys/{key_id}` | revoke API key |
| `GET` | `/v1/admin/runtime/overview` | runtime queue/failure/token overview |

## Canonical Workflow Examples

### 1. Create A Workspace And Thread

```bash
curl -X POST http://127.0.0.1:8000/v1/workspaces \
  -H 'Content-Type: application/json' \
  -d '{
    "organization_id": "11111111-1111-1111-1111-111111111111",
    "project_id": "<optional project_id; omitted uses the organization default project>",
    "name": "Delivery Team",
    "actor": {
      "participant_id": "11111111-1111-1111-1111-111111111111",
      "participant_type": "user",
      "display_name": "Lead"
    }
  }'
```

Then create a thread in that workspace:

```bash
curl -X POST http://127.0.0.1:8000/v1/workspaces/<workspace_id>/threads \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Daily Coordination",
    "actor": {
      "participant_id": "11111111-1111-1111-1111-111111111111",
      "participant_type": "user",
      "display_name": "Lead"
    }
  }'
```

### 2. Post A Message And Let It Create Work

`CreateMessageRequest` is the normal entrypoint for thread activity.

Important fields:

- `actor`
- `content`
- `visibility`
- `create_task`
- `task_instructions`
- `requests`
- `metadata`

Use `create_task=true` when the message should wake eligible agents through the normal task-routing path.

### 3. Create A Tracked Interaction Request

`CreateInteractionRequest` supports:

- `title`
- `summary`
- `questions`
- `selectors`
- `target_participant_ids`
- `completion_rule`
- `timeout_at`
- `metadata`

Example using participant business-role selectors:

```json
{
  "actor": {
    "participant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "participant_type": "agent",
    "display_name": "Standup Coordinator Agent"
  },
  "requests": [
    {
      "title": "Engineering updates",
      "questions": [
        {"prompt": "What are you working on today?"},
        {"prompt": "Do you have any blocker?"}
      ],
      "selectors": [
        {"type": "role", "value": "frontend_engineer"},
        {"type": "role", "value": "backend_engineer"}
      ],
      "completion_rule": {"mode": "one_per_selector_bucket"}
    }
  ]
}
```

### 4. Answer A Tracked Request

Use `POST /v1/requests/{request_id}/answers` with `CreateInteractionAnswerRequest`.

Important fields:

- `actor`
- `content`
- `question_ids`
- `metadata`

The answer becomes a normal timeline message and also updates request aggregation state.

### 5. Inspect Communication Flow

Use:

- `GET /v1/threads/{thread_id}/timeline` for thread-local ordered messages
- `GET /v1/workspaces/{workspace_id}/communication-log` for workspace debugging
- `OPEN_TALON_COMMUNICATION_LOG_DIR/<workspace_id>.jsonl` for persisted communication trace
- `GET /v1/audit/events` for compliance/investigation activity

## Guidance For Human Engineers

Use Open Talon as follows:

- start with [system-quickstart.md](./system-quickstart.md)
- use the admin web for operator workflows
- use `tui2` for the best human terminal experience
- use the communication log and audit APIs when debugging collaboration state
- treat `packages/contracts/open_talon_contracts/models.py` as the contract source of truth
- treat `db/migrations` as the schema source of truth

When changing behavior, inspect the whole vertical slice:

- contracts
- gateway route/service layer
- collaboration kernel and repository
- runtime workers if execution semantics are involved

## Guidance For Software Development Agents

Software development agents should use workspaces, threads, timeline messages, and interaction requests for end-to-end testing.

Recommended rules:

- use one client instance per user profile
- prefer `./open-talon user-client --profile <name>` for scripted human-user simulation
- select or auto-resolve the organization before creating workspaces in `tui2` or `user-client`
- rely on server-derived actor identity for OIDC-authenticated humans
- do not invent participant IDs as durable human identifiers
- prefer tracked interaction requests when answers must be correlated back into an agent loop
- prefer participant business-role selectors when validating advertised participant business-role routing
- use `GET /v1/workspaces/{workspace_id}/communication-log` and the JSONL workspace log files to debug who said what

For operational details and an end-to-end agent playbook, use [agent-operations-guide.md](./agent-operations-guide.md).

## Current Limitations And Non-Goals

- the `chat` APIs provide session-based chat separate from the shared workspace/thread collaboration surface
- threads are the shared collaboration surface in v1; private participant-to-participant DM semantics are not the main path
- communication logs capture collaboration communications, not every internal runtime transition
- audit is metadata-oriented by design and must not inline sensitive prompt or token payloads

## Source Pointers

When this document and the code disagree, trust the code.

Most important implementation files:

- `services/gateway-edge/gateway_edge/main.py`
- `services/gateway-edge/gateway_edge/routers/`
- `services/gateway-edge/gateway_edge/services/`
- `services/core-collab/core_collab/kernel.py`
- `services/core-collab/core_collab/repository.py`
- `services/agent-runtime/agent_runtime/workers.py`
- `packages/contracts/open_talon_contracts/models.py`
- `README.md`
- `AGENTS.md`
