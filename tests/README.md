# Test Suite Structure

The test tree is organized by runtime boundary first, with pytest markers used
to select by execution cost and test layer.

## Layers

- `unit`: isolated tests for helpers, contracts, serialization, and small
  objects. These tests should not start an app or talk to external services.
- `logic`: in-process domain or service behavior using fakes, fake
  repositories, or mocked providers.
- `route`: in-process HTTP, WebSocket, or API boundary coverage using
  `ASGITransport`, `TestClient`, or equivalent app fakes.
- `repository`: persistence, migrations, seed data, and SQL behavior. These
  usually require Postgres and are commonly also marked `integration`.
- `business_case`: deterministic multi-step collaboration workflows that
  exercise product behavior in-process.
- `integration`: tests that require the local Docker-backed infrastructure or
  another live local dependency.
- `live`: tests that talk to a running Open Talon stack or local external
  service such as Keycloak, Kafka, OpenBao, Ollama, or Docker.

## Current Layout

- `tests/contracts`: shared contract and helper behavior.
- `tests/core-collab`: collaboration kernel/domain behavior plus repository
  integration coverage.
- `tests/gateway-edge`: gateway API, auth, IAM, MCP, audit, provider, and
  workspace boundary behavior.
- `tests/agent-runtime`: runtime execution, compaction, observability, worker,
  and tool execution behavior.
- `tests/tui`: command parsing, profile/session state, rendering, and client
  behavior for the terminal UI.
- `tests/workspace-memory`: memory provider adapter behavior.
- `tests/presence-directory`: presence state behavior against fake Redis.
- `tests/business-cases`: readable product workflow scenarios.
- `tests/infrastructure`: live local infrastructure and end-to-end stack tests.

Default `pytest` excludes `integration` tests. Use explicit paths and markers
for narrower runs, for example:

```bash
pytest -m unit -q
pytest tests/core-collab -q
pytest -m business_case -q
pytest -m integration tests/infrastructure -q -s
```

Markers are applied automatically by `tests/conftest.py` based on the test path.
Individual tests can still add narrower markers when needed.
