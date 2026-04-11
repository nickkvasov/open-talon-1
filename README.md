# Open Talon

This repository contains the local infrastructure, Python services, and client apps for Open Talon. The canonical developer Python environment is the repository-root `.venv`.

For coding-agent-specific project guidance, see [`AGENTS.md`](/Users/nikolay.kvasov/Development/open-talon-1/AGENTS.md).

## System Overview

Open Talon is a local-first collaboration system where users and agents are first-class participants.

At a high level:

- `services/gateway-edge` is the main entrypoint for clients and developer tools
- `apps/tui` provides a terminal UI that talks to the gateway
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

## Architecture Stack

- **PostgreSQL**: Deployed via `pgvector/pgvector:pg16` directly supporting native `JSONB` properties alongside algorithmic embeddings operations for Vector Similarity Searching natively in the engine.
- **Kafka**: Deployed using `apache/kafka:3.8.0` utilizing `KRaft` mode (omitting Zookeeper), configured natively on mapped loops using high level partition assignments.
- **OpenBao**: Open-source fork of Hashicorp Vault running securely in Development mode tracking explicit Version 2 isolated secrets.
- **Valkey**: Drop-in compatible Redis equivalent caching infrastructure configured to handle immediate TTL caching.
- **Langfuse**: Self-hosted LLM observability stack for traces, prompts, and evaluations, deployed with Langfuse Web/Worker plus ClickHouse and MinIO.
- **Ollama AI**: Serves dynamic generative model orchestration natively mapped across standard REST.
    - Operates natively against Google's modern **Gemma 4** models, with the default test setup pulling the lightweight `gemma4:latest` model.

## Infrastructure

`./open-talon start` brings up the full local infrastructure stack and then starts the supported local processes for:

- `gateway-edge`
- `agent-loop-worker`
- `tool-worker`
- `reconciler`

Local services:

- `gateway-edge`: primary local API gateway for REST, SSE, WebSocket, collaboration, and admin APIs
- `agent-loop-worker`: local worker that executes agent model steps from durable `run_steps`
- `tool-worker`: local worker that executes isolated tool invocations from durable `tool_calls`
- `reconciler`: local worker that requeues expired leases and republishes wakeups
- `postgres`: application database with `pgvector` enabled
- `pgadmin`: pgAdmin 4 web UI for inspecting and querying the local Postgres instance
- `kafka`: event bus for chat, collaboration, and agent-runtime traffic
- `openbao`: local secret store and token-validation backend
- `valkey`: session store, API-key cache, and short-lived gateway state
- `langfuse-web`: Langfuse UI and API surface
- `langfuse-worker`: Langfuse background processing
- `clickhouse`: Langfuse analytics/event store
- `minio`: Langfuse object storage for uploads and media
- `ollama`: local model serving endpoint

## Endpoints

Common local endpoints:

- `gateway-edge`: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- `gateway-edge health`: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- `gateway-edge readiness`: [http://127.0.0.1:8000/ready](http://127.0.0.1:8000/ready)
- `gateway-edge docs`: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- `langfuse-web`: [http://localhost:3000](http://localhost:3000)
- `pgadmin`: [http://localhost:5050](http://localhost:5050)
- `openbao`: [http://localhost:8200](http://localhost:8200)
- `ollama`: [http://localhost:11434](http://localhost:11434)
- `clickhouse HTTP`: [http://localhost:8123](http://localhost:8123)
- `minio API`: [http://localhost:9090](http://localhost:9090)
- `minio console`: [http://localhost:9091](http://localhost:9091)

Ports and protocols:

- `postgres`: `localhost:5432`
- `kafka`: `localhost:9092`
- `valkey`: `localhost:6379`
- `clickhouse native`: `localhost:9000`
- `langfuse-worker`: `localhost:3030`

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
- `Langfuse UI`
  URL: [http://localhost:3000](http://localhost:3000)
  email: `admin@example.com`
  password: `admin123456`
- `MinIO`
  console: [http://localhost:9091](http://localhost:9091)
  username: `minio`
  password: `miniosecret`
- `ClickHouse`
  username: `langfuse`
  password: `langfuse`

These are local dev defaults from `infrastructure/.env.example`. Override them in your local env before starting the stack if you need different values.

The bundled pgAdmin server import is also pinned to the default local Postgres connection (`postgres:5432`, database `app_db`, user `admin`). If you change those Postgres values in `infrastructure/.env`, update `infrastructure/pgadmin/servers.json` and `infrastructure/pgadmin/pgpass` to keep the preconfigured connection working.

The compose stack currently pins pgAdmin to `dpage/pgadmin4:9.13.0` in [`infrastructure/docker-compose.yaml`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/docker-compose.yaml#L17) for reproducible local setup.

## Persistence Design

Data persistence relies purely on strictly scoped host bind-mounts mapped recursively into `infrastructure/data/...`
Standard container operations or isolated unit tests can freely execute `docker compose down -v` across the infrastructure securely deleting the environment without affecting native AI parameters, databases blocks, or Kafka volumes hosted locally safely on the host physical drive.

> **Note**: Do not commit the `infrastructure/data/` payloads directly. It contains multi-gigabyte neural weight matrices specifically blocked via the repository `.gitignore` configuration.

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

## TUI

For TUI setup, usage, and slash command documentation, see [`apps/tui/README.md`](/Users/nikolay.kvasov/Development/open-talon-1/apps/tui/README.md).

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

This setup reuses the repository Postgres server and Valkey container, but Langfuse now uses its own Postgres database (`LANGFUSE_POSTGRES_DB`) so Prisma migrations do not collide with the application schema. Defaults live in `infrastructure/.env.example`.

Infra defaults are defined in `infrastructure/.env.example`, including:

- core ports for Postgres, Kafka, OpenBao, Valkey, Ollama, and Langfuse
- Langfuse database name and bootstrap credentials
- ClickHouse, MinIO, and Valkey credentials used by Langfuse
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
pytest -m integration test/infrastructure/test_infrastructure.py -v -s

# Full test coverage: default suite plus integration suite
pytest -q
pytest -m integration test/infrastructure/test_infrastructure.py -v -s
```

## AI Model Initialization Note

First-time execution will wait for Ollama to fetch the configured default model from `infrastructure/.env`. The suite still allows long waits for first-run downloads, but it no longer assumes multiple heavyweight models by default.
