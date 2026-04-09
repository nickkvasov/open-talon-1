# Open Talon

This repository contains the local infrastructure, Python services, and client apps for Open Talon. The canonical developer Python environment is the repository-root `.venv`.

## Architecture Stack

- **PostgreSQL**: Deployed via `pgvector/pgvector:pg16` directly supporting native `JSONB` properties alongside algorithmic embeddings operations for Vector Similarity Searching natively in the engine.
- **Kafka**: Deployed using `apache/kafka:3.8.0` utilizing `KRaft` mode (omitting Zookeeper), configured natively on mapped loops using high level partition assignments.
- **OpenBao**: Open-source fork of Hashicorp Vault running securely in Development mode tracking explicit Version 2 isolated secrets.
- **Valkey**: Drop-in compatible Redis equivalent caching infrastructure configured to handle immediate TTL caching.
- **Ollama AI**: Serves dynamic generative model orchestration natively mapped across standard REST.
    - Operates natively against Google's modern **Gemma 4** models, with the default test setup pulling the lightweight `gemma4:latest` model.

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
- the gateway edge service from `services/gateway-edge`
- the TUI app from `apps/tui`
- repo-level test dependencies for gateway and infrastructure suites

The nested `api-gateway/.venv` is now legacy-only and should not be the default for day-to-day development.

## Pytest Orchestration

Automations operate sequentially leveraging `pytest` through explicit Python networking wrappers. Calling testing natively maps background parallel assertions executing directly toward HTTP/TCP components actively checking if they are locally alive. You do not need to manually launch anything; `pytest` implicitly binds `./infrastructure/docker-compose.yaml` using Python `subprocess`.

```bash
# Enable the repository virtual environment
source .venv/bin/activate

# Gateway tests
pytest tests/gateway-edge -q

# Infrastructure tests
pytest test/infrastructure/test_infrastructure.py -v -s
```

## AI Model Initialization Note

First-time execution will wait for Ollama to fetch the configured default model from `infrastructure/.env`. The suite still allows long waits for first-run downloads, but it no longer assumes multiple heavyweight models by default.
