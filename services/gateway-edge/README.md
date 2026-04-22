# Gateway Edge

`gateway-edge` is the supported API gateway for Open Talon.

It exposes:

- health and readiness endpoints
- chat APIs with request/response and streaming flows
- collaboration APIs for workspaces, threads, timelines, and presence
- provider-neutral principal IAM APIs for human roles, agent roles, and machine identities
- admin APIs for API key management
- a gateway-mounted browser session-chat UI at `/` when `apps/web` is present

## Local Development

Use the repository-root virtualenv and launcher from the repo root:

```bash
./scripts/bootstrap-python.sh
./open-talon start
./open-talon tui2 --profile admin
```

The launcher starts the full local infrastructure stack plus this service as a local `uvicorn` process on `http://127.0.0.1:8000`.

For scripted or multi-user testing, prefer:

```bash
./open-talon user-client --profile user1
```

The gateway also serves the compatibility browser session-chat UI from `apps/web` at `http://127.0.0.1:8000/` when that static app directory is present. The main browser operator surface remains `apps/admin-web`.

## Direct Run

If you want to run the service directly instead of through the launcher:

```bash
source .venv/bin/activate
PYTHONPATH="packages/contracts:services/core-collab:services/gateway-edge:services/agent-runtime:services/generated-tools-builder:apps/tui" \
  uvicorn gateway_edge.main:app --host 0.0.0.0 --port 8000
```

The service expects local Postgres, Kafka, Valkey, OpenBao, an OIDC provider, and Ollama endpoints to be available. In local development the default OIDC provider is Keycloak. For the standard dev setup, use `./open-talon start`.

## Tests

Gateway unit and integration coverage lives under [`tests/gateway-edge`](../../tests/gateway-edge).

```bash
source .venv/bin/activate

# unit tests
pytest tests/gateway-edge -q

# principal IAM and auth resolution
pytest tests/gateway-edge/test_iam.py -q
pytest tests/gateway-edge/test_identity_sync.py -q

# infrastructure integration
pytest -m integration tests/infrastructure/test_infrastructure.py -v -s
```

## Key Files

- [`gateway_edge/main.py`](./gateway_edge/main.py)
- [`gateway_edge/config.py`](./gateway_edge/config.py)
- [`gateway_edge/routers`](./gateway_edge/routers)
- [`gateway_edge/services`](./gateway_edge/services)
