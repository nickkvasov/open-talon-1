# Workspace Memory Agent Guide

This guide applies under `services/workspace-memory/` and adds to the root and
service guides.

## Memory Authority

- Postgres is the canonical memory store.
- Mem0 and optional graph backends such as Memgraph are derived retrieval
  projections, not the source of truth.
- Memory providers are persistent records in `memory_providers`; do not hardcode
  provider definitions in application logic after bootstrapping.
- When adding a new memory provider, implement the shared `MemoryProvider`
  protocol in `workspace_memory/providers.py` and register it in
  `build_provider_index(...)` instead of bypassing the abstraction.
- Graph relations are additive context only and not the canonical memory store.

## Cross-Service Checks

- If a change touches layered memory, memory providers, Mem0, or graph-memory
  support, inspect `services/workspace-memory`, `services/core-collab`,
  `services/gateway-edge`, and `packages/contracts` together.
- Verify canonical persistence and provider projection remain coherent together.
- Keep `infrastructure/.env.example`, `infrastructure/docker-compose.yaml`, and
  `open-talon` aligned if graph mode behavior changes.

## Tests

- Run relevant `tests/workspace-memory` coverage.
- Run relevant memory route tests in `tests/gateway-edge`.
