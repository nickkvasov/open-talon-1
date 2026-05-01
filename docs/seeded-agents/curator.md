# Curator

## Agent Card

| Field | Value |
| --- | --- |
| Display name | `Curator` |
| Agent key | `curator` |
| Scope | organization |
| Agent id | deterministic per organization |
| Role | `organization operations curator` |
| Profile kind | `organization_operations_specialist` |
| Endpoint | `openai-responses` through provider `openai` |
| Managed context | each organization's `Administration / Organization Operations` workspace |
| IAM role | `organization_curator` for agent subjects in the same organization |
| Private MCP | `open_talon_control_plane` with organization-scoped allowlist |

## Agent Profile

Curator's seeded profile says its mandate is to manage organization-local
projects, workspaces, catalog resources, runtime health, and operational
context. It is seeded per non-system organization and activated through that
organization's Operations workspace. Its authority comes from the
`organization_curator` IAM role, workspace attachment, and organization-scoped
private control-plane MCP allowlist. It must stay inside the owning
organization and must not perform platform-wide discovery.

## Idea

Curator is the organization operations specialist. Each non-system organization
receives its own Curator, bound to that organization and attached to the
organization operations workspace. Curator handles organization-local project,
workspace, catalog, provider, runtime, audit, memory, retrieval, methodics, and
agent Git operations through authorized control-plane APIs.

Curator must stay inside its organization boundary. It should not perform
platform-wide discovery or mutate other organizations.

## Harness And Contract

Curator currently does not seed an explicit `AgentHarness`. Its behavior is
defined by:

- organization-scoped `system_agents` record
- system prompt that requires operating only inside the organization
- organization IAM role and project access
- attachment to the managed organization operations workspace
- private MCP binding for organization-scoped control-plane operations
- denylist that prevents `organizations.list` and destructive control-plane tools

This is a deliberate documentation point for maintainability: if Curator needs
richer behavioral guidance, add an explicit harness and interaction contract to
the seeded definition. Do not add runtime branches based on `agent_key`,
display name, role text, capability text, or metadata tags.

## Live Test Design

Primary live tests:

- [`tests/infrastructure/operational_agents_live/test_bootstrap_live_system.py`](../../tests/infrastructure/operational_agents_live/test_bootstrap_live_system.py)
- [`tests/infrastructure/operational_agents_live/test_curator_live_system.py`](../../tests/infrastructure/operational_agents_live/test_curator_live_system.py)

The live suite creates a fresh organization, verifies managed organization
contexts, patches that organization's Curator to a deterministic remote
harness, and then drives a targeted Curator task through the real runtime and
private MCP execution path.

Run:

```bash
OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/operational_agents_live/test_curator_live_system.py -q -s
```

## What Is Tested

Bootstrap coverage verifies:

- fresh organization creation creates `Default Project`
- fresh organization creation creates `Administration`
- `Organization Operations` exists under `Administration`
- an organization-scoped Curator exists with role `organization operations curator`
- Curator has an active machine identity after bootstrap repair
- Curator's private MCP tool list includes organization-local operations and excludes `organizations.list`

Curator task coverage verifies:

- Curator can be targeted in the organization operations workspace
- Curator creates one organization-local project through private MCP
- Curator creates one workspace inside that project through private MCP
- final thread response mentions the created project and workspace
- durable `tool_calls` rows complete for `projects.create` and `workspaces.create`
- private MCP tool calls record `tool_source=agent_internal_mcp_server`
