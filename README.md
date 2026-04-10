# Open Talon

This repository contains the local infrastructure, Python services, and client apps for Open Talon. The canonical developer Python environment is the repository-root `.venv`.

## Architecture Stack

- **PostgreSQL**: Deployed via `pgvector/pgvector:pg16` directly supporting native `JSONB` properties alongside algorithmic embeddings operations for Vector Similarity Searching natively in the engine.
- **Kafka**: Deployed using `apache/kafka:3.8.0` utilizing `KRaft` mode (omitting Zookeeper), configured natively on mapped loops using high level partition assignments.
- **OpenBao**: Open-source fork of Hashicorp Vault running securely in Development mode tracking explicit Version 2 isolated secrets.
- **Valkey**: Drop-in compatible Redis equivalent caching infrastructure configured to handle immediate TTL caching.
- **Langfuse**: Self-hosted LLM observability stack for traces, prompts, and evaluations, deployed with Langfuse Web/Worker plus ClickHouse and MinIO.
- **Ollama AI**: Serves dynamic generative model orchestration natively mapped across standard REST.
    - Operates natively against Google's modern **Gemma 4** models, with the default test setup pulling the lightweight `gemma4:latest` model.

## Infrastructure

`./open-talon start` brings up the full local infrastructure stack and then starts the supported local gateway from [`services/gateway-edge`](/Users/nikolay.kvasov/Development/open-talon-1/services/gateway-edge).

Local services:

- `gateway-edge`: primary local API gateway for REST, SSE, WebSocket, collaboration, and admin APIs
- `postgres`: application database with `pgvector` enabled
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

These are local dev defaults from [`infrastructure/.env.example`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/.env.example). Override them in your local env before starting the stack if you need different values.

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

## Langfuse

The local compose stack now includes a self-hosted Langfuse deployment:

- `langfuse-web` on `http://localhost:3000`
- `langfuse-worker` on port `3030`
- `clickhouse` on ports `8123` and `9000`
- `minio` on ports `9090` and `9091`

This setup reuses the repository Postgres server and Valkey container, but Langfuse now uses its own Postgres database (`LANGFUSE_POSTGRES_DB`) so Prisma migrations do not collide with the application schema. Defaults live in [`infrastructure/.env.example`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/.env.example) and mirrored deploy settings live in [`deploy/infrastructure/.env.example`](/Users/nikolay.kvasov/Development/open-talon-1/deploy/infrastructure/.env.example).

Infra defaults are defined in [`infrastructure/.env.example`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/.env.example), including:

- core ports for Postgres, Kafka, OpenBao, Valkey, Ollama, and Langfuse
- Langfuse database name and bootstrap credentials
- ClickHouse, MinIO, and Valkey credentials used by Langfuse
- the required Ollama model list for local startup

## Pytest Orchestration

Automations operate sequentially leveraging `pytest` through explicit Python networking wrappers. Calling testing natively maps background parallel assertions executing directly toward HTTP/TCP components actively checking if they are locally alive. You do not need to manually launch anything; `pytest` implicitly binds `./infrastructure/docker-compose.yaml` using Python `subprocess`.

```bash
# Enable the repository virtual environment
source .venv/bin/activate

# Default maintained unit suite
pytest -q

# Gateway tests only
pytest tests/gateway-edge -q

# Infrastructure integration tests
pytest -m integration test/infrastructure/test_infrastructure.py -v -s
```

## AI Model Initialization Note

First-time execution will wait for Ollama to fetch the configured default model from `infrastructure/.env`. The suite still allows long waits for first-run downloads, but it no longer assumes multiple heavyweight models by default.
