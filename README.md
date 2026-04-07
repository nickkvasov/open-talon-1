# Open Senate Infrastructure

This repository contains the foundational infrastructure for the project. It explicitly builds a locally containerized ecosystem enabling robust transient execution while persistently maintaining explicit host bindings for heavy AI model caching.

## Architecture Stack

- **PostgreSQL**: Deployed via `pgvector/pgvector:pg16` directly supporting native `JSONB` properties alongside algorithmic embeddings operations for Vector Similarity Searching natively in the engine.
- **Kafka**: Deployed using `apache/kafka:3.8.0` utilizing `KRaft` mode (omitting Zookeeper), configured natively on mapped loops using high level partition assignments.
- **OpenBao**: Open-source fork of Hashicorp Vault running securely in Development mode tracking explicit Version 2 isolated secrets.
- **Valkey**: Drop-in compatible Redis equivalent caching infrastructure configured to handle immediate TTL caching.
- **Ollama AI**: Serves dynamic generative model orchestration natively mapped across standard REST.
    - Operates natively against Google's modern **Gemma 4** models, spinning up explicitly via an asynchronous startup script natively pulling both `gemma4:31b` and `gemma4:e4b`.

## Persistence Design

Data persistence relies purely on strictly scoped host bind-mounts mapped recursively into `infrastructure/data/...`
Standard container operations or isolated unit tests can freely execute `docker compose down -v` across the infrastructure securely deleting the environment without affecting native AI parameters, databases blocks, or Kafka volumes hosted locally safely on the host physical drive.

> **Note**: Do not commit the `infrastructure/data/` payloads directly. It contains multi-gigabyte neural weight matrices specifically blocked via the repository `.gitignore` configuration.

## Pytest Orchestration

Automations operate sequentially leveraging `pytest` through explicit Python networking wrappers. Calling testing natively maps background parallel assertions executing directly toward HTTP/TCP components actively checking if they are locally alive. You do not need to manually launch anything; `pytest` implicitly binds `./infrastructure/docker-compose.yaml` using Python `subprocess`.

```bash
# Enable the virtual environment
source .venv/bin/activate

# Execute tests locally using standard verbosity while enabling stdout tracing
pytest test/infrastructure/test_infrastructure.py -v -s
```

## AI Model Initialization Note

First-time execution will recursively wait locally until Ollama has successfully traversed fetching BOTH standard `gemma4` configurations (roughly 22+ Total GB). This polling loop guarantees you never execute tests against empty orchestration containers. The testing suite will politely stall upwards to 25 minutes allowing gigabit pulls prior to continuing sequentially cleanly.
