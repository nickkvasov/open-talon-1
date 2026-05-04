# Contracts Agent Guide

This guide applies under `packages/contracts/` and adds to the root guide.

## Contract Rules

- `packages/contracts` contains shared Pydantic contracts used across services.
- Prefer explicit typed contracts over implicit conventions.
- When a contract changes, inspect every service and app that consumes it,
  including gateway routes, core repository/kernel methods, agent-runtime
  payloads, Retriever payloads, admin web types/usages, TUI parsing, docs, and
  tests.
- Keep execution-side workspace materialization separate from collaboration
  `Workspace` models. Use `ExecutionWorkspaceRef` for executor payloads.
- Use `open_talon_contracts.telemetry` for shared telemetry context and
  redaction behavior instead of inventing per-service variants.
- Agents and Retriever visual extraction must resolve generation/vision models
  through shared LLM contracts in `open_talon_contracts/llm_engines.py` and
  `open_talon_contracts/llm_runtime.py`.
- Retriever embeddings remain on the Retriever embedding-provider abstraction;
  do not collapse embedding contracts into generation/vision LLM contracts.

## Tests

- Run relevant `tests/contracts` coverage for contract-only changes.
- Run the affected service tests when a contract change modifies behavior,
  serialization, validation, enum values, defaults, or backward compatibility.
- Run broader `pytest -q` when the contract is shared across persistence,
  gateway, runtime, and clients.

## Key Files

- `open_talon_contracts/llm_engines.py`
- `open_talon_contracts/llm_runtime.py`
- `open_talon_contracts/telemetry.py`
