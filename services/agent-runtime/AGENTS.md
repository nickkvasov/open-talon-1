# Agent Runtime Guide

This guide applies under `services/agent-runtime/` and adds to the root and
service guides.

## Runtime Boundaries

- `agent-runtime` workers are stateless. Postgres owns durable execution state;
  Kafka is wake-up and fanout.
- Do not move agent-loop execution into `gateway-edge`.
- Runtime execution must stay generic. Do not branch behavior on `agent_key`,
  display name, role text, capability text, or metadata tags.
- Behavioral specialization belongs in agent definitions, harnesses,
  interaction contracts, task payloads, IAM/project/workspace bindings,
  publication-review records, and tool/MCP allowlists.
- Keep execution-side workspace materialization separate from collaboration
  `Workspace` models. Use `ExecutionWorkspaceRef` for executor payloads.
- Preserve `next_retry_at`-based scheduling, bounded retry semantics, terminal
  failure propagation, and `budget_exhausted` handling when changing claim or
  lease recovery behavior.
- Preserve normalized `run.output["usage"]` payloads when changing model runtime
  or provider integrations.

## Providers and Secrets

- Agents must resolve generation and vision models through the shared LLM
  provider abstraction: `llm_providers`,
  `packages/contracts/open_talon_contracts/llm_engines.py`,
  `packages/contracts/open_talon_contracts/llm_runtime.py`, and the runtime
  resolver in this service.
- Do not add parallel env-only provider registries.
- Keep secret resolution behind runtime abstractions and OpenBao-backed provider
  definitions.
- Runtime observability is provider-backed. Langfuse and OTLP-compatible sinks
  such as HyperDX are integrations, not architectural constants.

## Tool Execution

- Risky tool execution profiles require `trust_level="trusted"`:
  `workspace_access=read_write`, `network=full`, and `local_process`.
- Tinker authoring/build helpers are agent-internal tools and must not be exposed
  through `workspace_tools` or the normal workspace catalog.
- Approved high-risk MCP operations park the tool call until approval and requeue
  it after approval. The resumed execution path must mark the operation request
  `completed` or `failed`.
- Conductor runtime behavior must be resolved through the participant/task
  routing contract, especially `accepted_task_kinds` containing
  `methodics_execution_start`; do not hard-code Conductor UUIDs, `agent_key`,
  display name, role text, capability text, or metadata tags.
- Keep Conductor's private MCP allowlist limited to agent-appropriate execution
  reads and pending resource-request creation. Human-gated operations such as
  start, cancel, approve, and reject must be exercised with a human principal.

## Tests

- Run `tests/agent-runtime/test_runtime.py` for runtime provider/model changes.
- Run relevant `tests/agent-runtime/test_workers.py` for claim, lease,
  reconciliation, retry, or budget behavior.
- Run `tests/agent-runtime/test_execution.py` when local helper execution,
  execution backends, or Tinker runtime behavior changes.
- Run relevant core-collab and gateway tests when runtime behavior changes a
  durable state transition or emitted event contract.

## Key Files

- `agent_runtime/workers.py`
- `agent_runtime/runtime.py`
- `agent_runtime/agent_task_worker.py`
- `agent_runtime/config.py`
- `agent_runtime/secrets.py`
- `agent_runtime/execution/`
- `agent_runtime/observability.py`
- `agent_runtime/tinker_tools.py`
