# Gateway Edge

`gateway-edge` is the supported API gateway for Open Talon.

It exposes:

- health and readiness endpoints
- chat APIs with request/response and streaming flows
- collaboration APIs for workspaces, threads, timelines, and presence
- admin APIs for API key management
- the local web UI entrypoint

## Local Development

Use the repository-root virtualenv and launcher from the repo root:

```bash
./scripts/bootstrap-python.sh
./open-talon start
./open-talon tui
```

The launcher starts the full local infrastructure stack plus this service as a local `uvicorn` process on `http://127.0.0.1:8000`.

## Direct Run

If you want to run the service directly instead of through the launcher:

```bash
source .venv/bin/activate
PYTHONPATH="packages/contracts:services/core-collab:services/gateway-edge:services/agent-runtime:services/generated-tools-builder:apps/tui" \
  uvicorn gateway_edge.main:app --host 0.0.0.0 --port 8000
```

The service expects local Postgres, Kafka, Valkey, OpenBao, Keycloak, and Ollama endpoints to be available. For the standard dev setup, use `./open-talon start`.

## Tests

Gateway unit and integration coverage lives under [`tests/gateway-edge`](/Users/nikolay.kvasov/Development/open-talon-1/tests/gateway-edge).

```bash
source .venv/bin/activate

# unit tests
pytest tests/gateway-edge -q

# infrastructure integration
pytest -m integration tests/infrastructure/test_infrastructure.py -v -s
```

## Key Files

- [`gateway_edge/main.py`](/Users/nikolay.kvasov/Development/open-talon-1/services/gateway-edge/gateway_edge/main.py)
- [`gateway_edge/config.py`](/Users/nikolay.kvasov/Development/open-talon-1/services/gateway-edge/gateway_edge/config.py)
- [`gateway_edge/routers`](/Users/nikolay.kvasov/Development/open-talon-1/services/gateway-edge/gateway_edge/routers)
- [`gateway_edge/services`](/Users/nikolay.kvasov/Development/open-talon-1/services/gateway-edge/gateway_edge/services)
