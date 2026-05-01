# Tinker

## Agent Card

| Field | Value |
| --- | --- |
| Display name | `Tinker` |
| Agent id | `44444444-4444-4444-4444-444444444444` |
| Agent key | `tinker` |
| Scope | global |
| Role | `generated tool authoring and validation agent` |
| Profile kind | `workspace_tool_generation_specialist` |
| Endpoint | `openai-responses` through provider `openai` |
| Attachment | manual workspace attachment required before users can request tools |
| Private tools | generated-tool bootstrap, file write, build, registry push, smoke test, asset publish, status update, registry pull verification |

## Agent Profile

Tinker's seeded profile says its mandate is to turn workspace requests for
missing capabilities into reviewable generated-tool revisions. It is activated
by manual workspace attachment plus a targeted tool-generation request. Its
authority comes from visible workspace context, attached tools, private
authoring helpers, and human approval for publication. It must reuse existing
visible tools when possible, avoid publication claims before validation and
approval, and never auto-attach approved tools to workspaces.

## Idea

Tinker turns a workspace request for a missing capability into a reviewable,
agent-usable tool. It should first check whether an existing visible tool is
enough. If a new tool is needed, it drafts source, builds a container image,
validates it, captures trust and network rationale, and submits the revision
for human approval.

Approval publishes into the global or organization tool catalog only. It must
not auto-attach the generated tool to the workspace; manual workspace
attachment is a separate decision.

## Harness And Contract

Tinker seeds an explicit `AgentHarness`:

- prefer existing visible tools before generating a new one
- ask for clarification when requirements are incomplete
- use internal authoring helpers rather than assuming local side effects
- capture validation evidence before claiming a tool is ready
- read before write, inspect schemas before use, cite tool results, and verify side effects after mutation
- require trust, network, and workspace-access rationale for generated tools

The interaction contract is markdown with `Summary` and `Status`. Completion is
either identifying an existing sufficient tool or advancing a generated-tool
request with a clear next action for a user or platform admin.

Tinker behavior is supported by private internal tools. Those tools are not
workspace tools and are not exposed to other agents through `workspace_tools`.

## Live Test Design

Primary live test:

- [`tests/infrastructure/test_tinker_live_system.py`](../../tests/infrastructure/test_tinker_live_system.py)

The live test runs against the real local stack and patches Tinker to a
deterministic remote harness for the tool-authoring decisions. It still uses
real gateway routes, Postgres state, OpenBao secrets, Forgejo registry support,
Docker-backed generated-tool packaging, runtime task execution, and the
configured local reasoning model where the downstream math runner is exercised.

Run:

```bash
./.venv/bin/python -m pytest -m integration tests/infrastructure/test_tinker_live_system.py -q -s
```

## What Is Tested

The live test verifies:

- seeded Tinker can be attached to a workspace
- a targeted Tinker thread request creates a tool-generation request
- Tinker creates a revision and moves it to `pending_approval`
- internal generated-tool helpers build, push, and smoke-test the tool
- approval starts registry pull verification
- the final generated tool is published to the organization catalog with Docker execution and an immutable digest reference
- approval does not add the generated tool to `workspace_tools`
- a human manually attaches the published tool to the workspace
- another agent can call the generated Fibonacci tool and return `Fibonacci(10) = 55`
- communication log entries record the generation, approval, and publication path
- generated-tool helper artifacts are cleaned up after the test

Additional in-process coverage lives in
[`tests/business-cases/test_tinker_tool_generation.py`](../../tests/business-cases/test_tinker_tool_generation.py)
and focused kernel tests under
[`tests/core-collab/test_agent_contracts.py`](../../tests/core-collab/test_agent_contracts.py).
