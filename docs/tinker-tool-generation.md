# Tinker Tool Generation

This document describes the current Tinker workflow for generating agent-usable tools on demand.

## Current Model

- `Tinker` is a seeded system agent.
- `Tinker` must be attached to a workspace before users in that workspace can ask it to create a tool.
- A request may target either the `global` system catalog or the current `organization` catalog.
- Tinker’s authoring helpers are private internal tools. They are not exposed through `workspace_tools` and are not visible to other agents.
- Generated tools are published into the matching system catalog only after platform-admin approval.
- Published tools are never auto-attached to any workspace.
- Workspace `admin` or `supervisor` users attach a published tool later through the normal workspace-tool flow.

## User Flow

1. Attach `Tinker` to a workspace.
2. Ask Tinker for a tool in a workspace thread.
3. Wait for Tinker to draft, build, validate, and submit a revision.
4. Review and approve the revision as a platform admin.
5. Attach the published tool to a workspace if you want agents there to use it.

In `tui2`:

```text
/tool request Build a repo statistics tool for this platform
/tool request --scope organization Build a Fibonacci calculator tool that accepts integer n and returns the Fibonacci value
```

The `--scope organization` form requests publication into the current organization catalog instead of the global catalog.

## Approval And Catalog Semantics

- Approval creates a new `system_tool`.
- Global requests publish to `GET /v1/tools`.
- Organization requests publish to `GET /v1/organizations/{organization_id}/tools`.
- Approval does not create any `workspace_tools` rows.
- A published tool is not callable inside a workspace until it is manually attached there.

Manual attachment route:

```text
PUT /v1/workspaces/{workspace_id}/tools/{tool_id}
```

## API Flow

Attach `Tinker` to a workspace:

```text
POST /v1/workspaces/{workspace_id}/agents
```

Create a targeted Tinker request:

```text
POST /v1/threads/{thread_id}/messages
```

Important message fields:

- `target_system_agent_id`: Tinker’s agent id
- `target_tool_scope`: optional, `global` or `organization`
- `metadata.target_tool_name`: optional, explicit intended tool name

Inspect request state:

```text
GET /v1/threads/{thread_id}/tool-generation/requests
GET /v1/tool-generation/requests
GET /v1/tool-generation/requests/{request_id}
```

Approve or reject a revision:

```text
POST /v1/tool-generation/revisions/{revision_id}/approve
POST /v1/tool-generation/revisions/{revision_id}/reject
```

Attach the published tool later:

```text
PUT /v1/workspaces/{workspace_id}/tools/{tool_id}
```

## Admin Web

The admin web includes a dedicated `Tool Generation` page for:

- listing tool-generation requests
- inspecting revisions and validation output
- approving or rejecting a selected revision

Approval still only publishes into the system catalog. Workspace attachment remains a separate workspace-management action.

## Real System Test

The repository includes a live integration test that exercises the full Tinker flow:

- create a real test organization and workspace
- attach seeded `Tinker`
- request an organization-scoped Fibonacci tool
- let Tinker build and validate a real Docker-backed tool
- approve the revision
- manually attach the published tool to the workspace
- create another agent using `gemma4:latest`
- wait for the second agent to call the generated tool and return the final answer
- clean up workspace, agent, tool, image, and organization artifacts

Run it with:

```bash
./.venv/bin/python -m pytest -m integration tests/infrastructure/test_tinker_live_system.py -q -s
```

Prerequisites:

- local Docker working
- local stack dependencies available through `./open-talon start`
- Ollama serving `gemma4:latest`

Check available local Ollama models with:

```bash
curl http://127.0.0.1:11434/api/tags
```

## Related Files

- [README.md](/Users/nikolay.kvasov/Development/open-talon-1/README.md)
- [docs/system-quickstart.md](/Users/nikolay.kvasov/Development/open-talon-1/docs/system-quickstart.md)
- [apps/admin-web/src/pages/ToolGenerationRequests.jsx](/Users/nikolay.kvasov/Development/open-talon-1/apps/admin-web/src/pages/ToolGenerationRequests.jsx)
- [tests/business-cases/test_tinker_tool_generation.py](/Users/nikolay.kvasov/Development/open-talon-1/tests/business-cases/test_tinker_tool_generation.py)
- [tests/infrastructure/test_tinker_live_system.py](/Users/nikolay.kvasov/Development/open-talon-1/tests/infrastructure/test_tinker_live_system.py)
