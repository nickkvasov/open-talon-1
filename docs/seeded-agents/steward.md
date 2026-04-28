# Steward

## Agent Card

| Field | Value |
| --- | --- |
| Display name | `Steward` |
| Agent id | `44444444-4444-4444-4444-444444444445` |
| Agent key | `steward` |
| Scope | global |
| Role | `platform steward` |
| Endpoint | `openai-responses` through provider `openai` |
| Managed context | `System Base / Administration / System Operations` |
| IAM role | `platform_steward` for agent subjects |
| Private MCP | `open_talon_control_plane` with platform control-plane allowlist |

## Idea

Steward is the platform operations specialist. It operates the global Open
Talon control plane through authorized APIs and private MCP tools. It is meant
for platform-level maintenance such as inspecting runtime health, validating
catalog/provider state, verifying audit chains, and creating managed platform
resources when authorized.

Steward is not authorized by its role text. Its authority comes from its agent
IAM role, project access, workspace participant attachment, machine identity,
and private MCP allowlist.

## Harness And Contract

Steward seeds an explicit `AgentHarness`:

- use Open Talon control-plane APIs for platform operations
- keep IAM, audit, secret handling, and tenant boundaries explicit
- treat destructive operations as unavailable unless separately granted
- inspect schema before use
- read before write
- verify side effects after mutation
- cite tool results in operational reasoning

Its interaction contract is markdown with `Summary` and `Status`, and replies
should report the operation outcome plus any follow-up needed.

Steward's private MCP binding includes platform and organization control-plane
operations such as organization creation/listing, project/workspace operations,
runtime overview, provider/catalog validation, audit read/verify, and selected
agent Git operations. Destructive file/worktree discard and project-access
removal tools are denied.

## Live Test Design

Primary live tests:

- [`tests/infrastructure/operational_agents_live/test_bootstrap_live_system.py`](../../tests/infrastructure/operational_agents_live/test_bootstrap_live_system.py)
- [`tests/infrastructure/operational_agents_live/test_steward_live_system.py`](../../tests/infrastructure/operational_agents_live/test_steward_live_system.py)

The live suite patches Steward to a deterministic remote harness for the
decision path, while keeping the gateway, runtime, agent identity, MCP, IAM,
Postgres, and thread/task/tool-call persistence real.

Run:

```bash
OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/operational_agents_live/test_steward_live_system.py -q -s
```

## What Is Tested

Bootstrap coverage verifies:

- `system-base` exists
- `Administration / System Operations` exists
- gateway MCP can initialize against the live stack

Steward task coverage verifies:

- Steward exists as a global seeded agent
- Steward has an active machine identity provisioned for OIDC client credentials
- the admin test actor can be attached to the System Operations workspace
- a targeted Steward task is routed through the real runtime
- Steward uses private control-plane MCP tools to create exactly one organization, one project, and one workspace
- created organization, project, and workspace rows record Steward as creator through first-class creator fields
- durable `tool_calls` rows complete for the private MCP operations
- those tool calls record `tool_source=agent_internal_mcp_server`
