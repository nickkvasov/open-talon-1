# workspace-memory

Shared layered-memory library for Open Talon.

This package provides the provider abstraction used by `core-collab`,
`gateway-edge`, and `agent-runtime` for:

- run scratch memory
- thread memory
- confirmed workspace memory

The canonical source of truth remains Postgres. External providers such as
Mem0 are used for projection, semantic recall, and optional graph context.

## Mem0 Graph Mode

Mem0 graph support is available as a first-class optional mode.

- Default local mode uses pgvector-backed Mem0 search only.
- Enable graph memory in the persisted memory-provider definition with `config.enable_graph=true`.
- Local graph mode uses Memgraph via the `memgraph` service in
  [infrastructure/docker-compose.yaml](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/docker-compose.yaml).
- When using the local launcher, start Memgraph explicitly with `./open-talon start --memgraph`.
- Graph relations are additive context only and are returned separately from
  vector-ranked memory hits.
