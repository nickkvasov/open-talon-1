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

## Live Suite Runner

Use `scripts/run-live-tests.sh` for the real local live matrix. It centralizes
the environment flags and stack profiles that were previously scattered across
individual commands.

```bash
# Show runnable live suites and fractions.
./scripts/run-live-tests.sh --list

# Print the full live matrix without executing it.
./scripts/run-live-tests.sh all --dry-run

# Run all live suites sequentially.
./scripts/run-live-tests.sh all

# Run a fraction.
./scripts/run-live-tests.sh default-stack
./scripts/run-live-tests.sh providers
./scripts/run-live-tests.sh xwiki
./scripts/run-live-tests.sh methodology-deep-research
```

The runner has three stack modes:

- `self`: the test fixture starts and stops its own stack.
- `default`: the runner starts one shared `./open-talon start` stack for the
  selected operational, Anchor, and Retriever suites.
- `xwiki`: the runner starts one shared `./open-talon start --xwiki --web-search`
  stack and supplies local XWiki live-test defaults. The
  `methodology-deep-research` suite uses this same stack profile and runs only
  the real seeded Researcher/Methodologist deep methodology workflow. That
  workflow uses the `openai-responses` GPT provider for both specialists, so
  `OPENAI_API_KEY` or the equivalent OpenBao secret must be configured.

The `compose` suite runs the raw Docker Compose infrastructure smoke test and
resets compose volumes through its fixture. Use named fractions when you need a
bounded live check rather than the whole matrix.

## External Access Coverage

External system and participant-grant coverage is split by boundary:

- `tests/core-collab/test_external_access.py`: grant authority, active-grant
  resolution, risk-policy approval decisions, redaction, and operation-request
  lifecycle.
- `tests/gateway-edge/test_external_access_routes.py`: route guards, ordinary
  participant denial, org/platform admin success, own-active-grant listing,
  pre-assigned grant attach guards, and sanitized direct operation responses.
- `tests/gateway-edge/test_external_operation_executor.py`: direct HTTP
  operation catalog execution with fake transports and server-side credential
  use.
- `tests/agent-runtime/test_external_identity_mcp.py`: MCP
  `auth.kind="external_identity"` header resolution, pending-approval parking,
  and post-approval credential use.
- `tests/core-collab/test_migration_files.py` and repository integration tests:
  schema and SQL active-grant filtering.

Use unique test module basenames across non-package test directories when adding
more external-access coverage; duplicate names can trigger pytest
import-mismatch failures.
