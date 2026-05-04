# Open Talon Service Guide

This guide applies under `services/` and adds to the root guide. Read the more
specific service guide when one exists.

## Service Boundaries

- Keep service behavior aligned with shared contracts, migrations, docs, and
  tests in the same change.
- Keep gateway routers thin; prefer logic in services, kernels, and repositories.
- Keep execution orchestration in Open Talon code and isolate only the backend
  executor behind the execution interface.
- Keep audit capture in dedicated middleware/services instead of scattering
  ad hoc audit inserts through routers.
- When adding or changing audit or observability integrations, update the
  provider/registry layer instead of branching directly on vendor behavior in
  service logic.
- Provider records are persistent state. Do not reintroduce env-defined engine,
  memory, or provider registries after bootstrap.
- Secret resolution should stay behind the relevant service abstraction and local
  OpenBao wiring; do not return raw secrets, bearer tokens, or sensitive payloads
  from service APIs.
- When worker behavior changes, cover both durable state transitions and emitted
  Kafka/thread events in tests.
- Preserve `next_retry_at`-based scheduling and bounded retry semantics when
  changing lease reconciliation or claim logic.
- Preserve normalized `run.output["usage"]` payloads when changing model runtime
  or provider integrations.

## Cross-Service Checks

- Auth or identity changes usually require `gateway-edge`, `core-collab`,
  `packages/contracts`, and TUI checks together.
- Execution changes usually require `agent-runtime`, `core-collab`, gateway
  event fanout, and contract checks together.
- Provider or secret changes usually require `gateway-edge`, `core-collab`,
  `agent-runtime`, infrastructure defaults, and docs together.
- Library/Retriever changes usually require `core-collab`, `gateway-edge`,
  `agent-runtime`, `retriever`, contracts, migrations, admin web, and managed
  System Plugin defaults together.
