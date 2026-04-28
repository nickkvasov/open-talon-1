# Operational Agents Live Suite

This suite verifies managed operational agents against the real local Open Talon stack.

Run it from the repository root after `./open-talon start`:

```bash
OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/operational_agents_live -q -s
```

Layout:

- `helpers.py`: local Keycloak, gateway MCP, Postgres, and polling helpers.
- `harnesses.py`: deterministic remote harnesses used by task-targeted agent tests.
- `test_bootstrap_live_system.py`: shared managed context and Curator bootstrap checks.
- `test_steward_live_system.py`: system-level Steward task path.
- `test_curator_live_system.py`: organization-level Curator task path.
- `test_conductor_live_system.py`: workspace-level Conductor methodics start, internal MCP,
  resource gate, and fanout checks.

To add another operational agent, create a new `test_<agent>_live_system.py` module
and put any reusable deterministic harness logic in `harnesses.py`. Keep the test
targeted to one agent behavior so the suite remains composable.

Runbook notes:

- Apply pending schema first with `./scripts/dbmate.sh up` after migration changes.
- Restart the stack after route, bootstrap, or managed-agent definition changes before
  trusting a plain live-test `404`; an old gateway process can look like a routing failure.
- Deterministic harnesses that call internal MCP tools must pass the explicit `_mcp_scope`
  for the session they need.
- Patch managed-agent endpoints and local Keycloak settings inside `try` / `finally`
  blocks so failed live runs do not poison the next run.
- Keep model-independent control-plane tests on deterministic harnesses. Use local Ollama
  only when the behavior under test is model quality or provider integration.
