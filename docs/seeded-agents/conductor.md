# Conductor

## Agent Card

| Field | Value |
| --- | --- |
| Display name | `Conductor` |
| Agent id | `44444444-4444-4444-4444-444444444448` |
| Agent key | `conductor` |
| Scope | global definition, opt-in workspace participant |
| Role | `workspace methodics execution conductor` |
| Endpoint | `local-ollama` through provider `ollama` |
| Task routing | `normal_message_fanout=false` |
| Accepted task kinds | `methodics_execution_start`, `methodics_step_coordinate`, `methodics_step_verify`, `methodics_resource_review` |
| IAM role | `workspace_conductor` for agent subjects |
| Execution source | active `WorkspaceHarness.methodics` snapshot |
| Human gates | execution start/cancel and resource request approve/reject |

## Idea

Conductor actively executes workspace methodics only when it is explicitly
attached to that workspace and an authorized human starts a methodics execution.
Without attachment, the workspace has no active methodics loop. Without a start
call, attachment only makes Conductor available for targeted methodics work.

Conductor coordinates participants, creates assignments, evaluates definition
of done evidence, advances or reworks steps, and produces final execution
reports. It proposes resource attachments as pending requests. Humans approve
or reject those requests.

## Harness And Contract

Conductor seeds an explicit `AgentHarness`:

- do nothing unless a targeted methodics execution task is assigned
- treat the methodics snapshot captured at execution start as the execution contract
- coordinate one active methodic step at a time unless the snapshot supports parallel work
- create assignments with expected evidence and definition of done
- verify evidence before marking a step passed
- create rework when evidence is missing or weak
- request resource attachments through human-gated resource requests
- keep ordinary workspace conversation unaffected

Its response contract is markdown with:

- `Execution State`
- `Current Step`
- `Assignments`
- `DoD Verification`
- `Resource Requests`
- `Next Action`

Conductor's private MCP allowlist includes execution reads, assignment creation,
step evaluation, resource request creation, retrieval search/context packs,
thread messaging, and workspace memory. Its private denylist excludes
human-gated methodics control tools such as execution create/cancel and resource
request approve/reject.

## Live Test Design

Primary live tests:

- [`tests/infrastructure/operational_agents_live/test_conductor_live_system.py`](../../tests/infrastructure/operational_agents_live/test_conductor_live_system.py)

The live suite creates real workspaces with `WorkspaceHarness.methodics`, uses
normal workspace agent attachment for Conductor, patches Conductor to a
deterministic remote harness, and then drives targeted execution tasks through
the real runtime, private MCP, methodic execution tables, thread timeline, and
MCP tool visibility.

Run:

```bash
OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/operational_agents_live/test_conductor_live_system.py -q -s
```

## What Is Tested

The live tests verify:

- starting methodics execution without attached Conductor returns `409 Conflict`
- normal workspace agent attachment gives Conductor `normal_message_fanout=false`
- accepted task kinds are the methodics task kinds only
- a start call snapshots active `WorkspaceHarness.methodics`
- execution starts with the first step active and later steps pending
- definition of done is assembled from step verification and methodic success criteria
- a targeted `methodics_execution_start` task is created for Conductor
- Conductor can read execution state through private MCP
- Conductor can create pending resource requests through private MCP
- human approve and reject endpoints change resource request state
- human MCP sessions can list/get/cancel executions and approve/reject resource requests
- Conductor does not receive normal-message fanout tasks
- Conductor can create assignments through private MCP
- Conductor can evaluate DoD outcomes as rework or passed through private MCP
- failed/weak evidence creates a rework loop
- passed steps advance execution to the next step
- final passed step completes execution and writes final report metadata
- a final execution report message is posted to the thread
- cancellation works during an active execution
- private MCP `tool_calls` complete with `tool_source=agent_internal_mcp_server`

Seed and migration coverage also verifies the `workspace_conductor` IAM role,
absence of `methodics.admin`, private MCP allowlist, and the absence of
human-gated methodics control tools from Conductor's private binding.
