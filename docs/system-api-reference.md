# Open Talon System And API Reference

This document is the current-state implementation reference for Open Talon.

Use it when you need to understand:

- how the running system is put together
- which service owns which responsibility
- how identities, participants, threads, requests, and execution records fit together
- which HTTP APIs exist today
- which APIs are intended for humans, browser clients, terminal clients, and software development agents

This is a reference for the implemented system. For local startup steps, use [system-quickstart.md](./system-quickstart.md). For repository coding guidance, use [../AGENTS.md](../AGENTS.md). For future-looking architecture rationale, use [collaboration-system-design.md](./collaboration-system-design.md).

## Audience

This reference is written for two audiences:

- Human engineers operating, extending, or integrating with Open Talon
- Software development agents that need a stable description of the system and API surface while acting as test users, operator agents, or workspace participants

## Documentation Map

- [system-quickstart.md](./system-quickstart.md): fastest path to a running local stack
- [agent-operations-guide.md](./agent-operations-guide.md): practical usage guide for software development agents and scripted clients
- [db-migrations.md](./db-migrations.md): schema and migration workflow
- [collaboration-system-design.md](./collaboration-system-design.md): design background and planned evolution
- [../AGENTS.md](../AGENTS.md): repository coding rules for contributors and coding agents

## System At A Glance

Open Talon is a local-first collaboration system where humans and agents are first-class participants inside shared workspaces.

The main runtime components are:

- `services/gateway-edge`
  - FastAPI gateway
  - main HTTP, SSE, and WebSocket entrypoint
  - auth, admin, collaboration, audit, and legacy chat routes
- `services/core-collab`
  - canonical collaboration kernel
  - repository layer over Postgres
  - source of truth for workspaces, threads, participants, requests, tasks, runs, run steps, tool calls, memory, assets, and audit writes
- `services/agent-runtime`
  - stateless background workers
  - task claiming, agent loop execution, tool execution, and lease reconciliation
- `packages/contracts`
  - shared Pydantic contracts used across services and clients
- `apps/admin-web`
  - browser admin console for operators
- `apps/tui`
  - terminal clients for humans and software-driven test users
- `infrastructure`
  - local Docker-backed dependencies such as Postgres, Kafka, Valkey, Keycloak, OpenBao, Langfuse, MinIO, and optional Memgraph

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
- `system_agents` stores global agent definitions
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

### Workspace Presence

- `participants.participant_id` identifies the workspace-local materialization of a user or agent
- participant state includes:
  - status
  - visibility scope
  - roles
  - capabilities
  - timestamps
  - metadata

### Auth Modes

`gateway-edge` supports:

- `none`
- `api_key`
- `openbao`
- `oidc`
- `any`

Current local development defaults are Keycloak/OIDC for humans and admin/API-key flows for operator automation.

### Important Auth Rules

- authenticated human identity is derived server-side from the bearer token
- do not treat `participant_id` as a global human identifier
- non-member workspace-scoped reads return `404`, not `403`
- global system-definition and provider-management APIs are admin-only under OIDC
- workspace role/tool/publish flows require workspace `admin` or `supervisor`

### Auth And Session APIs

| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| `GET` | `/health` | Liveness check | No auth |
| `GET` | `/ready` | Readiness check | No auth |
| `GET` | `/v1/me` | Resolved OIDC identity | Requires OIDC |

## Collaboration Domain Model

The current collaboration model is workspace-first and thread-native.

### Core Entities

| Entity | Meaning |
| --- | --- |
| `workspace` | top-level collaboration boundary |
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
- role-based and capability-based selector routing
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

Most collaboration write requests still carry an `actor` shape for compatibility.

Rules:

- human OIDC requests are resolved server-side
- for thread-scoped writes, the gateway resolves the effective thread actor
- for workspace-scoped writes, the gateway resolves the effective workspace actor
- software agents using API-key or system/operator flows may still supply actor payloads directly

### Visibility

Valid message visibility values are:

- `public`
- `workspace`
- `agents_only`
- `private`

The current business collaboration flow uses thread-native shared messages, most often `workspace`.

### Error Behavior

Important behavior to rely on:

- `404` for non-member workspace-scoped reads
- `403` for membership-present but insufficient role
- validation errors for malformed request payloads
- `PermissionError`-style domain failures mapped into HTTP errors by the gateway

### Pagination

Current explicit pagination appears on:

- workspace communication log
- audit event list

Use `limit` and `offset` where exposed.

## Endpoint Catalog

This section groups the currently implemented API surface by purpose.

### Health, Auth, And Legacy Chat

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/health` | liveness |
| `GET` | `/ready` | readiness |
| `GET` | `/v1/me` | authenticated user identity |
| `POST` | `/v1/chat` | legacy synchronous chat |
| `POST` | `/v1/chat/stream` | legacy SSE chat streaming |
| `GET` | `/v1/history/{session_id}` | session chat history |
| `GET` | `/v1/sessions/{session_id}` | session info |
| `DELETE` | `/v1/sessions/{session_id}` | session delete |
| `WS` | `/v1/ws/chat/{session_id}` | bidirectional chat streaming |

The `chat` APIs are the older session/chat surface. New collaboration work should prefer workspaces, threads, timeline messages, and interaction requests.

### Workspaces, Participants, And Roles

| Method | Path | Summary |
| --- | --- | --- |
| `POST` | `/v1/workspaces` | create workspace |
| `GET` | `/v1/workspaces` | list visible workspaces |
| `GET` | `/v1/workspaces/{workspace_id}` | workspace detail |
| `PATCH` | `/v1/workspaces/{workspace_id}` | workspace metadata update |
| `DELETE` | `/v1/workspaces/{workspace_id}` | delete workspace |
| `GET` | `/v1/workspaces/{workspace_id}/participants` | list participant advertisements |
| `DELETE` | `/v1/workspaces/{workspace_id}/participants/{participant_id}` | remove participant |
| `PATCH` | `/v1/workspaces/{workspace_id}/participants/{participant_id}/role` | assume participant role |
| `POST` | `/v1/workspaces/{workspace_id}/agents` | attach a system agent to a workspace |
| `PATCH` | `/v1/workspaces/{workspace_id}/agents/{participant_id}` | update attached agent participant |
| `PUT` | `/v1/workspaces/{workspace_id}/roles/{role_name}` | create/update role definition |
| `DELETE` | `/v1/workspaces/{workspace_id}/roles/{role_name}` | delete role definition |

### System Definitions

Global system-definition APIs are operator/admin APIs.

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/v1/llm-engines` | list registered LLM engines |
| `POST` | `/v1/agents` | create system agent definition |
| `GET` | `/v1/agents` | list system agent definitions |
| `PATCH` | `/v1/agents/{agent_id}` | update system agent definition |
| `DELETE` | `/v1/agents/{agent_id}` | delete system agent definition |
| `POST` | `/v1/tools` | create system tool |
| `GET` | `/v1/tools` | list system tools |
| `PATCH` | `/v1/tools/{tool_id}` | update system tool |
| `DELETE` | `/v1/tools/{tool_id}` | delete system tool |
| `POST` | `/v1/llm-providers` | create LLM provider definition |
| `POST` | `/v1/llm-providers/validate` | validate LLM provider without persisting |
| `GET` | `/v1/llm-providers` | list LLM providers |
| `PATCH` | `/v1/llm-providers/{provider_id}` | update LLM provider |
| `DELETE` | `/v1/llm-providers/{provider_id}` | delete LLM provider |
| `POST` | `/v1/llm-providers/{provider_id}/health-check` | validate stored LLM provider |
| `POST` | `/v1/memory-providers` | create memory provider definition |
| `POST` | `/v1/memory-providers/validate` | validate memory provider without persisting |
| `GET` | `/v1/memory-providers` | list memory providers |
| `PATCH` | `/v1/memory-providers/{provider_id}` | update memory provider |
| `DELETE` | `/v1/memory-providers/{provider_id}` | delete memory provider |
| `POST` | `/v1/memory-providers/{provider_id}/health-check` | validate stored memory provider |

### Git Repositories, Assets, And Tool Attachments

| Method | Path | Summary |
| --- | --- | --- |
| `POST` | `/v1/git-repositories` | register global Git repository |
| `GET` | `/v1/git-repositories` | list global Git repositories |
| `POST` | `/v1/assets/publish-from-git` | publish global asset version |
| `GET` | `/v1/assets` | list assets |
| `GET` | `/v1/assets/{asset_id}/versions` | list asset versions |
| `POST` | `/v1/assets/{asset_id}/links` | link asset version to target |
| `POST` | `/v1/assets/{asset_id}/activate` | activate asset version |
| `GET` | `/v1/assets/{asset_id}/download` | presigned asset download URL |
| `GET` | `/v1/agents/{agent_id}/assets` | resolve agent asset bindings |
| `GET` | `/v1/tools/{tool_id}/assets` | resolve tool asset bindings |
| `GET` | `/v1/workspaces/{workspace_id}/tools` | list attached workspace tools |
| `PUT` | `/v1/workspaces/{workspace_id}/tools/{tool_id}` | attach tool to workspace |
| `PATCH` | `/v1/workspaces/{workspace_id}/tools/{tool_id}` | update workspace tool attachment |
| `DELETE` | `/v1/workspaces/{workspace_id}/tools/{tool_id}` | detach tool from workspace |
| `POST` | `/v1/workspaces/{workspace_id}/git-repositories` | register workspace Git repository |
| `GET` | `/v1/workspaces/{workspace_id}/git-repositories` | list workspace Git repositories |
| `POST` | `/v1/workspaces/{workspace_id}/assets/publish-from-git` | publish workspace asset version |

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
| `GET` | `/v1/audit/events/{audit_event_id}` | fetch one audit event |
| `GET` | `/v1/audit/chains/{chain_partition}/verify` | verify audit chain |
| `POST` | `/v1/audit/events/export` | export audit events to object storage |

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

Example using role selectors:

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

Software development agents should prefer the collaboration model, not the legacy chat model, for end-to-end testing.

Recommended rules:

- use one client instance per user profile
- prefer `./open-talon user-client --profile <name>` for scripted human-user simulation
- rely on server-derived actor identity for OIDC-authenticated humans
- do not invent participant IDs as durable human identifiers
- prefer tracked interaction requests when answers must be correlated back into an agent loop
- prefer role selectors when validating advertised role-based routing
- use `GET /v1/workspaces/{workspace_id}/communication-log` and the JSONL workspace log files to debug who said what

For operational details and an end-to-end agent playbook, use [agent-operations-guide.md](./agent-operations-guide.md).

## Current Limitations And Non-Goals

- the `chat` APIs are still present but are not the preferred collaboration surface
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
