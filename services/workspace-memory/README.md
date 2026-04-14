# workspace-memory

Shared layered-memory library for Open Talon.

This package provides the provider abstraction used by `core-collab`,
`gateway-edge`, and `agent-runtime` for:

- run scratch memory
- thread memory
- confirmed workspace memory

The canonical source of truth remains Postgres. External providers such as
Mem0 are used for projection, semantic recall, and optional graph context.
