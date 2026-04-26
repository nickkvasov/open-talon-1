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

To add another operational agent, create a new `test_<agent>_live_system.py` module and put any reusable deterministic harness logic in `harnesses.py`. Keep the test targeted to one agent behavior so the suite remains composable.
