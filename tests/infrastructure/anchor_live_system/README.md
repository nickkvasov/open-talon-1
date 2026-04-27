# Anchor Live System Tests

These gated integration tests exercise the real local stack path for workspace
topic publication review:

- strict pre-publication approval
- strict suppression with issuer-visible private explanation
- balanced post-publication flagging
- blocked-message absence from the workspace communication log

Run them only against a started local stack with gateway, runtime workers,
Kafka, Postgres, Keycloak, OpenBao, and the managed `local-ollama` provider.
The default local provider uses `OPEN_TALON_DEFAULT_REASONING_MODEL`.

For the narrative behind the live-test idea, setup, protocol, and run-log style,
see [docs/live-tests-short-stories.md](../../../docs/live-tests-short-stories.md).

```bash
OPEN_TALON_RUN_ANCHOR_LIVE=1 ./.venv/bin/python -m pytest -m integration tests/infrastructure/anchor_live_system -q -s
```
