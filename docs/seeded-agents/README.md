# Seeded Agent Cards

This directory documents the current seeded Open Talon agents as product and
testable runtime contracts. Each document covers the agent card, product idea,
harness or runtime contract, live-test design, and exact behavior the tests
prove.

The source of truth for seeded definitions is
[`services/core-collab/core_collab/system_defaults.py`](../../services/core-collab/core_collab/system_defaults.py).
Database migrations under [`db/migrations`](../../db/migrations) backfill and
repair older local stacks, while the Python repairer keeps startup idempotent.

Runtime workers must remain generic. Seeded-agent behavior must come from agent
definitions, harnesses, interaction contracts, task payloads, IAM/project/workspace
bindings, and tool/MCP allowlists rather than runtime branching on `agent_key`,
display name, role text, capability text, or metadata tags.

## System Concept

Start with [system-and-roles-concept.md](./system-and-roles-concept.md) for the
shared concept: how seeded agents fit into the system, where authority comes
from, how attachment differs from active execution, and how the agents cooperate
across operations, methodology extraction, tool creation, topic governance, and
methodics execution.

## Agent Documents

| Agent | Agent key | Scope | Document |
| --- | --- | --- | --- |
| Reasoning Planner | none | global example seed | [reasoning-planner.md](./reasoning-planner.md) |
| Tinker | `tinker` | global | [tinker.md](./tinker.md) |
| Steward | `steward` | global | [steward.md](./steward.md) |
| Curator | `curator` | organization | [curator.md](./curator.md) |
| Anchor | `anchor` | global, attached per workspace | [anchor.md](./anchor.md) |
| Researcher | `researcher` | global, targeted organization operations tasks | [researcher.md](./researcher.md) |
| Methodologist | `methodologist` | global | [methodologist.md](./methodologist.md) |
| Conductor | `conductor` | global, attached per workspace only when opted in | [conductor.md](./conductor.md) |

## Live Test Entry Points

Operational-agent live suite:

```bash
OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/operational_agents_live -q -s
```

Anchor live suite:

```bash
OPEN_TALON_RUN_ANCHOR_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/anchor_live_system -q -s
```

Tinker live system test:

```bash
./.venv/bin/python -m pytest -m integration tests/infrastructure/test_tinker_live_system.py -q -s
```

Seed and migration checks:

```bash
./.venv/bin/python -m pytest \
  tests/core-collab/test_repository_integration.py \
  tests/core-collab/test_migration_files.py \
  tests/core-collab/test_agent_contracts.py -q
```
