# Business Case Test Suite

This directory contains end-to-end collaboration scenarios that exercise the system as a business workflow instead of as isolated unit behavior.

These tests are intended to answer questions like:

- Can several humans and several agents collaborate in one workspace?
- Are tracked interaction requests routed correctly?
- Do completion rules gate agent resume correctly?
- Does the workspace communication log provide a debuggable trail of the collaboration?

## Scope

Business-case tests should stay focused on realistic workflow behavior across multiple collaboration steps:

- workspace creation and participant setup
- human and agent participants in the same workspace
- thread creation and message posting
- tracked `interaction_request` creation and answering
- agent task/run/resume behavior
- final communication-log validation when relevant

They are higher-level than the `tests/core-collab` suite, but they still run in-process with the fake repository unless a scenario explicitly needs infrastructure.

## Current Cases

### Role-Based Daily Coordination

Implemented in [test_daily_coordination.py](./test_daily_coordination.py).

This pilot validates a simple delivery-team coordination loop:

- Workspace: `Delivery Team`
- Thread: `Daily Coordination`
- Humans:
  - `Team Lead`
  - `Frontend Engineer`
  - `Backend Engineer`
- Agents:
  - `Standup Coordinator Agent`
  - `Risk Review Agent`

The case intentionally uses advertised collaboration roles for targeting instead of named user selection:

- `@role:frontend_engineer`
- `@role:backend_engineer`
- `@role:team_lead`

The scenario covers three tracked collaborations:

1. The standup coordinator requests engineering updates using `one_per_selector_bucket`.
2. The standup coordinator requests lead prioritization using `all_targets`.
3. The risk review agent requests mitigation ownership using `minimum_answers = 2`.

The case then verifies:

- participant business-role target resolution
- partial vs complete request state transitions
- gated agent resume behavior
- targeted follow-up task routing
- workspace communication-log ordering

### Tinker Tool Generation

Implemented in [test_tinker_tool_generation.py](./test_tinker_tool_generation.py).

This scenario validates the business flow around generated tools without requiring the live infrastructure stack:

- workspace and thread creation
- attaching seeded-style `Tinker` internal helper tools
- drafting and approving an organization-scoped Fibonacci tool
- publishing into the organization system catalog without auto-attaching to the workspace
- manually attaching the published tool to the workspace
- having a second agent call the generated tool and answer back into the thread

This test runs in-process with the fake repository. The companion live-stack path is [tests/infrastructure/test_tinker_live_system.py](../infrastructure/test_tinker_live_system.py), which exercises the real runtime, Docker-backed generated tool path, and local Ollama model.

## Running The Suite

From the repository root:

```bash
source .venv/bin/activate
pytest tests/business-cases -q
```

Run only business-case-marked tests:

```bash
pytest -m business_case -q
```

Run only the daily coordination pilot:

```bash
pytest tests/business-cases/test_daily_coordination.py -q
```

Run only the Tinker business case:

```bash
pytest tests/business-cases/test_tinker_tool_generation.py -q
```

## Communication Logs

Each business-case test run now writes persistent workspace communication-log artifacts under:

- [tests/business-cases/logs](./logs/README.md)

The layout is organized for browsing by scenario, then by test, then by individual run:

```text
tests/business-cases/logs/
  <scenario>/
    <test_name>/
      latest.json
      runs/
        <timestamp>_pid<pid>/
          manifest.json
          <workspace_id>.jsonl
```

Use `latest.json` when you want the newest run quickly, and the `runs/` directory when you want to compare several executions of the same scenario over time.

## Adding A New Business Case

When adding a new scenario:

- keep it in this directory
- mark it with `@pytest.mark.business_case`
- prefer one file per business workflow
- name the file after the workflow, not the subsystem
- keep the scenario readable from top to bottom as a narrative
- use the `business_case_log_dir` fixture when the scenario should persist communication logs

Recommended structure:

1. Create the workspace and participants.
2. Attach any required agents.
3. Assign collaboration roles and capabilities needed for routing.
4. Create the thread.
5. Post the initiating human or agent message.
6. Drive the collaboration through requests, answers, and resumes.
7. Assert final state, task routing, and communication history.

## Design Guidelines

Use business-case tests for scenarios where the value comes from interaction between subsystems. Keep lower-level matching, persistence, or contract edge cases in:

- [tests/core-collab](../core-collab)
- [tests/gateway-edge](../gateway-edge)
- [tests/tui](../tui)

Prefer deterministic scenarios:

- use explicit participant business-role assignments
- avoid ambiguous multi-match selector routing unless that is the point of the test
- assert both intermediate and final collaboration state
- include communication-log assertions when the workflow should be auditable
