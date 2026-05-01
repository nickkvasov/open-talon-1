# core-collab

`core-collab` is the canonical collaboration and execution kernel for Open Talon.

It owns the durable collaboration model that sits behind `gateway-edge` and feeds `agent-runtime`.

## Responsibilities

`core-collab` is responsible for:

- organization, workspace, thread, and participant persistence
- collaboration-role definitions, participant capabilities, and workspace-local routing state
- timeline messages, interaction requests, answers, and communication-log materialization
- durable execution records such as `tasks`, `runs`, `run_steps`, and `tool_calls`
- workspace memory persistence and provider-sync orchestration
- tool-generation request, revision, approval, and publication state
- external systems, external accounts, participant-scoped external identity grants, and external operation approval records
- audit writes that must happen in the same transaction as business-state changes

## Boundaries

- Postgres is the source of truth for collaboration and execution state.
- `core-collab` owns repository and kernel logic; router and HTTP concerns stay in `gateway-edge`.
- External-access authorization, grant resolution, risk-policy decisions, and durable approval state live here; generic outbound HTTP execution stays in `gateway-edge`.
- `agent-runtime` executes claimed work, but the durable state transitions it consumes are created here.
- External memory systems are projections. Canonical memory writes still land here first.

## Key Modules

- [`core_collab/kernel.py`](./core_collab/kernel.py): collaboration service layer and domain orchestration
- [`core_collab/repository.py`](./core_collab/repository.py): Postgres repository layer and SQL-backed persistence
- [`core_collab/runtime_execution.py`](./core_collab/runtime_execution.py): execution-facing payload shaping and runtime handoff helpers
- [`core_collab/external_access.py`](./core_collab/external_access.py): external-operation approval-policy helpers and metadata redaction
- [`core_collab/migrations.py`](./core_collab/migrations.py): migration runner used by startup and tests
- [`core_collab/contracts.py`](./core_collab/contracts.py): internal contract helpers shared across the package
- [`core_collab/results.py`](./core_collab/results.py): result wrappers used by kernel and repository flows

## Current Role In The System

The typical collaboration path is:

1. `gateway-edge` authenticates the caller and resolves the effective actor.
2. `gateway-edge` calls into `core-collab`.
3. `core-collab` validates tenancy, membership, permissions, and domain invariants.
4. `core-collab` writes canonical state to Postgres and emits the corresponding collaboration or audit side effects.
5. `agent-runtime` later claims runnable tasks created from that durable state.

## Tests

The main package-level coverage lives under:

- [`tests/core-collab/test_repository_integration.py`](../../tests/core-collab/test_repository_integration.py)
- [`tests/core-collab/test_external_access.py`](../../tests/core-collab/test_external_access.py)
- [`tests/core-collab/test_agent_contracts.py`](../../tests/core-collab/test_agent_contracts.py)
- [`tests/core-collab/test_log_management.py`](../../tests/core-collab/test_log_management.py)
- [`tests/core-collab/test_repository_observability.py`](../../tests/core-collab/test_repository_observability.py)

Run the package-focused suite from the repository root with:

```bash
source .venv/bin/activate
pytest tests/core-collab -q
```
