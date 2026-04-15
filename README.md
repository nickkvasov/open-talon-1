# Open Talon

This repository contains the local infrastructure, Python services, and client apps for Open Talon. The canonical developer Python environment is the repository-root `.venv`.

For coding-agent-specific project guidance, see [`AGENTS.md`](/Users/nikolay.kvasov/Development/open-talon-1/AGENTS.md).

## System Overview

Open Talon is a local-first collaboration system where users and agents are first-class participants.

At a high level:

- `services/gateway-edge` is the main entrypoint for clients and developer tools
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
6. Langfuse captures observability data for prompts, traces, and evaluations.

## Identity And Auth

Open Talon now separates:

- `users`: stable human identity records
- `auth_identities`: external IdP mappings for authenticated humans
- `participants`: workspace-local materializations of a human or agent inside a workspace

Human authentication is handled through **Keycloak** over OIDC. `gateway-edge` validates bearer tokens, maps `(issuer, subject)` to a local `users.user_id`, and then resolves or creates the caller's workspace participant server-side.

Important implications:

- client apps should not treat `participant_id` as a global human identity
- authenticated human requests may still include an `actor` object for compatibility, but the gateway derives the effective human actor from the bearer token
- OpenBao remains part of the local stack for secrets and other internal uses, not as the primary end-user login system
- the local Keycloak dev setup is intended to allow HTTP during development; `keycloak-init` normalizes `sslRequired=none` for both `master` and `open-talon`, and you can re-apply that with `docker compose up -d keycloak keycloak-init`

## Audit Logging

Open Talon now has a dedicated audit subsystem that is separate from the collaboration domain event stream.

- `collab_event_log` remains the collaboration/event fanout stream
- `audit_event_ledger` is the canonical append-only audit ledger
- Kafka topic `talon.audit.events` relays committed audit rows
- ClickHouse stores the searchable audit projection in `default.audit_events`
- MinIO stores audit exports and daily chain checkpoints

V1 audit behavior:

- `gateway-edge` emits boundary audit records for HTTP, SSE, and WebSocket activity
- `core-collab` mirrors semantic workspace/thread/task/run/tool/provider mutations into audit in the same transaction as the business write
- `agent-runtime` emits audit records for worker exceptions and backend failures
- outcomes are explicit: `success`, `failure`, `denied`, and `error`
- payload depth is always `metadata_only`

Security and integrity rules:

- audit rows are append-only in steady-state code
- workspace-scoped chains use `workspace:{workspace_id}`
- system/global chains use `global`
- `prev_hash` and `event_hash` form the tamper-evident chain
- raw bearer tokens, prompt bodies, tool arguments, and message bodies must not be stored inline in audit metadata

Audit APIs:

- `GET /v1/audit/events`
- `GET /v1/audit/events/{audit_event_id}`
- `GET /v1/audit/chains/{partition}/verify`
- `POST /v1/audit/events/export`

Audit access model:

- system `admin` can query, verify, and export globally
- workspace `admin` and `supervisor` can access audit within their workspace scope
- regular `user` cannot read audit data

The current local implementation writes directly into ClickHouse for the audit warehouse path, and the authoritative audit interface remains the Open Talon API backed by Postgres.
An optional local HyperDX all-in-one profile is now available in Docker Compose for UI and OTLP intake experiments:

```bash
docker compose -f infrastructure/docker-compose.yaml --profile hyperdx up -d hyperdx
```

That profile is operational/investigative only. The canonical audit source remains Postgres plus the Open Talon audit APIs.

## Tools Model

Open Talon models tools in two layers:

- `system_tools`: global tool definitions available across the installation
- `workspace_tools`: workspace-scoped attachments that enable a system tool for a specific workspace

This means a tool is defined once, then added to any workspace that wants to advertise it to attached agents.

Each system tool includes:

- a human-readable name and description
- a `parameter_contract` describing accepted parameters
- an `input_schema` for structured validation/integration use
- an explicit `execution` binding that selects the execution backend, handler, execution profile, and trust level

When a tool is attached to a workspace, attached agent participants advertise it as a capability using the `tool:<name>` form, and the runtime includes the attached tool definitions in the agent execution context.

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

Common tool endpoints:

- `POST /v1/tools`: create a system-wide tool definition
- `GET /v1/tools`: list system-wide tool definitions
- `PATCH /v1/tools/{tool_id}`: update a system-wide tool definition
- `GET /v1/workspaces/{workspace_id}/tools`: list tools attached to a workspace
- `PUT /v1/workspaces/{workspace_id}/tools/{tool_id}`: attach a system tool to a workspace
- `PATCH /v1/workspaces/{workspace_id}/tools/{tool_id}`: update workspace attachment state
- `DELETE /v1/workspaces/{workspace_id}/tools/{tool_id}`: detach a tool from a workspace

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
- **Keycloak**: Local identity provider for registration, login, OIDC token issuance, and device/browser flows.
- **Valkey**: Drop-in compatible Redis equivalent caching infrastructure configured to handle immediate TTL caching.
- **Langfuse**: Self-hosted LLM observability stack for traces, prompts, and evaluations, deployed with Langfuse Web/Worker plus ClickHouse and MinIO.
- **Ollama AI**: Serves dynamic generative model orchestration natively mapped across standard REST.
    - Operates natively against Google's modern **Gemma 4** models, with the default test setup pulling the lightweight `gemma4:latest` model.

## Infrastructure

`./open-talon start` brings up the full local infrastructure stack and then starts the supported local processes for:

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
- `clickhouse`: Langfuse analytics store and audit query projection
- `minio`: object storage for Langfuse, published assets, audit exports, and chain checkpoints
- `openbao`: local secret store and token-validation backend
- `keycloak`: local identity provider for user registration, browser login, and device login
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

In the current auth model, the TUI is a **multi-profile** client:

- each local profile lives under `~/.open-talon/profiles/<profile>/`
- each profile stores separate workspace/thread state and bearer tokens
- human login is designed around Keycloak device flow
- two users on the same device should use different TUI profiles rather than sharing one local participant identity

For terminal-first usage, prefer `tui2`:

```bash
./open-talon tui2 --profile admin
```

`tui2` runs in normal terminal scrollback instead of a full-screen widget layout, so mouse selection works like a regular shell session and raw URLs remain easy to copy or open.

Useful local flows:

```bash
./open-talon tui2 --profile admin
./open-talon tui2 auth login --profile admin
```

Inside `tui2`, the minimum auth path is:

```text
/auth login
/account whoami
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

Infra defaults are defined in `infrastructure/.env.example`, including:

- core ports for Postgres, Kafka, OpenBao, Valkey, Ollama, Forgejo, and Langfuse
- Langfuse database name and bootstrap credentials
- ClickHouse, MinIO, Forgejo, and Valkey credentials used by the local stack
- the required Ollama model list for local startup
- worker scaling and lease settings such as `AGENT_STEP_WORKER_CONCURRENCY`, `TOOL_WORKER_CONCURRENCY`, `LEASE_TTL_SECONDS`, and `RECONCILE_INTERVAL_SECONDS`

## Pytest Orchestration

Automations operate sequentially leveraging `pytest` through explicit Python networking wrappers. Calling testing natively maps background parallel assertions executing directly toward HTTP/TCP components actively checking if they are locally alive. You do not need to manually launch anything; `pytest` implicitly binds `./infrastructure/docker-compose.yaml` using Python `subprocess`.

```bash
# Enable the repository virtual environment
source .venv/bin/activate

# Default maintained suite (excludes integration tests via pytest.ini)
pytest -q

# Gateway tests only
pytest tests/gateway-edge -q

# Infrastructure integration tests
pytest -m integration tests/infrastructure/test_infrastructure.py -v -s

# Full test coverage: default suite plus integration suite
pytest -q
pytest -m integration tests/infrastructure/test_infrastructure.py -v -s
```

## AI Model Initialization Note

First-time execution will wait for Ollama to fetch the configured default model from `infrastructure/.env`. The suite still allows long waits for first-run downloads, but it no longer assumes multiple heavyweight models by default.
