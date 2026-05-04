# Tests Agent Guide

This guide applies under `tests/` and adds to the root guide.

## General Expectations

- Before finishing meaningful code changes, run the most relevant tests.
- Meaningful functionality changes should include comprehensive automated
  coverage for affected behavior, not just superficial smoke checks.
- Give test modules unique basenames across non-package test directories,
  especially when adding the same domain coverage under `tests/core-collab`,
  `tests/gateway-edge`, and `tests/agent-runtime`. Duplicate module basenames can
  trigger pytest import-mismatch failures.

Common commands:

```bash
pytest -q
pytest tests/gateway-edge -q
pytest tests/core-collab -q
pytest tests/tui -q
pytest tests/business-cases -q
pytest -m integration tests/infrastructure/test_infrastructure.py -v -s
./scripts/run-live-tests.sh --list
./scripts/run-live-tests.sh all
```

## Test Selection

- Schema, repository, participant hydration, routing, or migrations: run relevant
  `tests/core-collab`, `tests/gateway-edge`, migration-script coverage
  (`tests/scripts/test_system_scripts.py`,
  `tests/core-collab/test_migration_files.py`), and `./scripts/dbmate.sh up`
  against the local stack when needed.
- External systems, external identity grants, operation requests, MCP external
  identity auth, or direct external-operation APIs: cover ordinary workspace
  participant denial, organization/platform admin success, own-active-grant
  visibility, tenant/workspace mismatch rejection, pre-assigned grant attach
  guards, sanitized operation results, grant resolution failure modes, approval
  policy behavior, requeue after approval, and completed/failed operation
  marking.
- External HTTP executor behavior: use `httpx.MockTransport` or an equivalent
  fake provider, assert credentials are used server-side, and assert
  `secret_config`, `credential_ref`, bearer tokens, and raw sensitive payloads
  are not returned or stored in metadata.
- Layered memory, memory providers, Mem0, or graph-memory support: run relevant
  `tests/workspace-memory` and memory route tests in `tests/gateway-edge`.
- LLM provider resolution, local model defaults, Retriever extraction, or model
  secret handling: run `tests/agent-runtime/test_runtime.py`,
  `tests/retriever`, relevant `tests/core-collab/test_agent_contracts.py`, and
  `tests/gateway-edge/test_llm_provider_health.py`.
- Library, Retriever plugin tools, library attachments, project retrieval scope,
  or library item storage: run `tests/core-collab/test_library_kernel.py`,
  `tests/gateway-edge/test_library_routes.py`,
  `tests/gateway-edge/test_mcp.py`,
  `tests/gateway-edge/test_system_plugins.py`, and relevant repository migration
  tests.
- Library deletion routes should verify `DELETE /v1/libraries/{library_id}` works
  for authenticated no-body clients as well as compatibility callers that still
  send an actor body.
- OIDC auth, Keycloak wiring, or TUI login/profile behavior: run relevant gateway
  auth tests, `tests/gateway-edge/test_iam.py`,
  `tests/gateway-edge/test_identity_sync.py`, and `tests/tui`.
- Admin web, browser OIDC login, admin-browser routing, or deployed browser
  config: run `npm run build` in `apps/admin-web`; run `npm run test:e2e` in
  `apps/admin-web` when browser behavior or destructive admin flows change.
- Workspace authz, global admin routes, or workspace membership filtering: run
  relevant `tests/gateway-edge/test_workspaces.py`,
  `tests/gateway-edge/test_admin.py`, `tests/gateway-edge/test_iam.py`, and
  relevant organization route/member tests.
- Audit logging, audit APIs, event relays, or runtime failure reporting: run at
  least one gateway audit test and one repository chain-verification test.
- Execution lease recovery, budget enforcement, or runtime overview behavior:
  run relevant `tests/core-collab/test_agent_contracts.py` and
  `tests/agent-runtime/test_workers.py`.
- Tinker, tool generation, generated-tool approval, or internal tool execution:
  run `tests/core-collab/test_agent_contracts.py`,
  `tests/gateway-edge/test_tool_generation.py`,
  `tests/business-cases/test_tinker_tool_generation.py`, and
  `tests/agent-runtime/test_execution.py` when local helper execution or
  execution backends change.
- Operational agents, managed administration contexts, agent-private MCP
  bindings, or control-plane MCP operations: run
  `tests/core-collab/test_agent_contracts.py` and relevant gateway IAM/MCP tests.
- Methodologist, Conductor, methodics execution, or other managed specialist
  agents: run `tests/core-collab/test_agent_contracts.py` and relevant
  repository migration tests when seeded specialist definitions change.

## Live Tests

- Use `./scripts/run-live-tests.sh` for coordinated live runs.
- Run
  `OPEN_TALON_RUN_SYSTEM_PLUGINS_LIVE=1 pytest -m integration tests/infrastructure/test_system_plugins_live_system.py -q -s`
  and
  `OPEN_TALON_RUN_RETRIEVER_LIVE=1 pytest -m integration tests/infrastructure/test_retriever_live_system.py -q -s`
  against the real local stack when plugin registration, sync, attachment,
  indexing, or retrieval search changes.
- Run
  `OPEN_TALON_RUN_RETRIEVER_LIVE=1 pytest -m integration tests/infrastructure/test_retriever_live_system.py -q -s`
  when PDF parsing, image understanding, OCR-like extraction, chart extraction,
  Ollama model roles, or Retriever ingestion behavior changes.
- Run
  `pytest -m integration tests/infrastructure/test_tinker_live_system.py -q -s`
  when the end-to-end Tinker/runtime path changes and the configured
  `OPEN_TALON_DEFAULT_REASONING_MODEL` is available in infrastructure Ollama.
- Run
  `OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 pytest -m integration tests/infrastructure/operational_agents_live -q -s`
  for end-to-end operational-agent identity, MCP, runtime, and durable
  `tool_calls` coverage.
- Run
  `OPEN_TALON_RUN_ANCHOR_LIVE=1 pytest -m integration tests/infrastructure/anchor_live_system -q -s`
  when publication review, Anchor, or workspace topic-moderation behavior
  changes.
- Tinker live tests should disable workspace topic moderation unless the test is
  specifically about Anchor.
- Keep deterministic live harnesses under
  `tests/infrastructure/operational_agents_live` so new operational agents can
  add focused test modules instead of growing one monolithic file.
- Deterministic live harnesses that call internal MCP tools must pass the
  explicit `_mcp_scope` expected by the gateway session.
- After changing live gateway routes, bootstrap, or agent definitions, restart
  the local stack before trusting a plain live-test `404`; a stale gateway can
  look like an authorization or routing regression.
- Live tests that patch managed-agent endpoints or local Keycloak client
  settings must restore them in `finally` blocks.
- Conductor live coverage proves attach/start gating, internal MCP reads,
  assignment creation, DoD pass/fail/rework evaluation, step progression, final
  execution report creation, pending resource-request creation, human
  approve/reject/cancel tools, active-step cancellation, and normal-message
  fanout isolation.
- Live tests may need local-service access to Docker Compose services, Keycloak,
  OpenBao, gateway, MinIO, Ollama, or the Docker socket. If sandboxed execution
  fails with a local network or permission error, rerun the same command with
  required escalation rather than weakening the test.

## Key Files

- `tests/infrastructure/test_retriever_live_system.py`
- `tests/infrastructure/test_tinker_live_system.py`
- `tests/infrastructure/operational_agents_live/`
