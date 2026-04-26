# Operational Agents Live-System Test Run Log: 2026-04-26

This log records real live-system test runs for the operational-agent bootstrap path, the system-level Steward task path, and the extended organization Curator task path.

## Run Context

- Date: `2026-04-26 15:17:31 +04`
- Working directory: `/Users/nikolay.kvasov/Development/open-talon-1`
- Branch: `codex/systemwide-agents`
- Commit: `fb6fb19`
- Python: repository `.venv`
- Test suite: [tests/infrastructure/operational_agents_live](../tests/infrastructure/operational_agents_live)
- Protocol: [operational-agents-real-life-test-protocol.md](./operational-agents-real-life-test-protocol.md)

## Stack Startup

The local stack was restarted so the live test ran against the current implementation, not an already-running gateway process.

Stop command:

```bash
./open-talon stop
```

Relevant stop output:

```text
Stopping reconciler PID 55307...
Stopping tool-worker PID 55303...
Stopping agent-loop-worker PID 55299...
Stopping agent-task-worker PID 55295...
Stopping gateway-edge PID 54737...
Stopping infrastructure services...
```

Start command:

```bash
./open-talon start
```

Relevant start output from the final restart before the full passing run:

```text
Starting local gateway-edge...
Starting local agent-task-worker...
Starting local agent-loop-worker...
Starting local tool-worker...
Starting local reconciler...
Gateway PID: 72941
Gateway log: /Users/nikolay.kvasov/Development/open-talon-1/.run/gateway-edge.log
```

Running Docker services included:

```text
clickhouse        Up 3 minutes (healthy)
forgejo           Up 3 minutes (healthy)
kafka             Up 3 minutes
keycloak          Up 3 minutes
langfuse-web      Up 3 minutes (healthy)
langfuse-worker   Up 3 minutes
minio             Up 3 minutes (healthy)
ollama            Up 3 minutes
openbao           Up 3 minutes (healthy)
pgadmin           Up 3 minutes
postgres          Up 3 minutes
valkey            Up 3 minutes
```

Gateway readiness response:

```json
{
  "status": "ok",
  "services": [
    {"name": "postgres", "healthy": true},
    {"name": "valkey", "healthy": true},
    {"name": "kafka", "healthy": true},
    {"name": "ollama", "healthy": true},
    {"name": "openbao", "healthy": true}
  ]
}
```

Keycloak discovery responded from:

```text
http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration
```

## Harness Corrections During Live Run

The first real live attempts exposed two test-harness issues:

- `open-talon-tui` intentionally has direct password grants disabled, so the live test now temporarily enables direct grants for the test and restores the original setting afterward.
- `threads.messages.create` is visible only to a workspace participant, so the test now attaches the live admin to the new `Organization Operations` workspace before checking thread MCP tools.
- agent-private control-plane MCP tools are exposed to the agent with the configured `control_plane__` prefix, so the Curator task harness calls `control_plane__projects.create` and `control_plane__workspaces.create` while the underlying MCP metadata records `projects.create` and `workspaces.create`.
- after one interrupted full-file run, the gateway was no longer listening on `127.0.0.1:8000`; rerunning `./open-talon start` restored gateway and worker processes before the final pass.
- a later Steward live run exposed stale or missing Keycloak clients for managed agent identities after local stack restart; gateway bootstrap now validates client-credentials auth and repairs the OpenBao secret or reprovisions the missing Keycloak client.

These were test-harness fixes. The final run below used the corrected live test against the real local stack.

## Focused Extended Curator Task Run

Focused command:

```bash
OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration \
  tests/infrastructure/operational_agents_live/test_curator_live_system.py::test_curator_task_creates_project_and_workspace_on_live_system -vv -s
```

Raw output:

```text
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-9.0.3, pluggy-1.6.0 -- /Users/nikolay.kvasov/Development/open-talon-1/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/nikolay.kvasov/Development/open-talon-1
configfile: pytest.ini
plugins: asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 1 item

tests/infrastructure/operational_agents_live/test_curator_live_system.py::test_curator_task_creates_project_and_workspace_on_live_system PASSED

============================== 1 passed in 4.26s ===============================
```

## Final Live Test Command

```bash
OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/operational_agents_live -vv -s
```

Raw output:

```text
============================= test session starts ==============================
platform darwin -- Python 3.13.5, pytest-9.0.3, pluggy-1.6.0 -- /Users/nikolay.kvasov/Development/open-talon-1/.venv/bin/python
cachedir: .pytest_cache
rootdir: /Users/nikolay.kvasov/Development/open-talon-1
configfile: pytest.ini
plugins: asyncio-1.3.0, anyio-4.13.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 3 items

tests/infrastructure/operational_agents_live/test_bootstrap_live_system.py::test_operational_agents_bootstrap_on_live_system PASSED
tests/infrastructure/operational_agents_live/test_steward_live_system.py::test_steward_task_creates_organization_project_and_workspace_on_live_system PASSED
tests/infrastructure/operational_agents_live/test_curator_live_system.py::test_curator_task_creates_project_and_workspace_on_live_system PASSED

============================== 3 passed in 21.08s ===============================
```

Result: passed.

## System-Level Steward Task Evidence

The passing full-file run created this live organization, project, and workspace through the global `Steward`:

```text
organization slug: steward-created-8becf84be7
organization_id: 21958318-67b1-46e6-b6aa-6d356e11a469
organization.created_by: 44444444-4444-4444-4444-444444444445
created project slug: steward-project-8becf84be7
created project_id: ccdb9363-80ff-4687-990f-eb62b64d7729
project.created_by: 44444444-4444-4444-4444-444444444445
project.creator_system_agent_id: 44444444-4444-4444-4444-444444444445
created workspace: Steward Created Workspace 8becf84be7
created workspace_id: 73f3b4a0-78de-4381-b54e-d91978ece919
workspace.created_by: 44444444-4444-4444-4444-444444444445
workspace.creator_user_id: null
workspace.creator_system_agent_id: 44444444-4444-4444-4444-444444444445
task_id: 3e426c8b-a51e-42c9-85c5-32f3a9eff677
```

Completed durable Steward tool calls:

```text
tool_call_id: 5e8dfd43-bd43-4470-b6a1-0aa3f8a2958d
tool_name: control_plane__organizations.create
status: completed
metadata.tool_source: agent_internal_mcp_server
metadata.mcp_server_key: open_talon_control_plane
metadata.mcp_tool_name: organizations.create

tool_call_id: 50c8620d-c45b-4ecb-8b94-cbe75acdf092
tool_name: control_plane__projects.create
status: completed
metadata.tool_source: agent_internal_mcp_server
metadata.mcp_server_key: open_talon_control_plane
metadata.mcp_tool_name: projects.create

tool_call_id: df6c5fa0-a1ae-4792-9be2-fdc52378224e
tool_name: control_plane__workspaces.create
status: completed
metadata.tool_source: agent_internal_mcp_server
metadata.mcp_server_key: open_talon_control_plane
metadata.mcp_tool_name: workspaces.create
```

## Extended Curator Task Evidence

A passing full-file run created this live organization and task path:

```text
organization slug: operational-task-86ac6e3b94
organization_id: 0334e1d8-aa73-4a07-9d80-cc2d8fc9c88b
created project slug: curator-created-86ac6e3b94
created project_id: 9fe4b1c8-babc-494b-93c4-31bfadca4e72
created workspace: Curator Created Workspace 86ac6e3b94
created workspace_id: c70fc48b-620d-4ca5-86c6-9d73f3639dc2
task_id: 5c2f13e8-34a4-46c5-a3f4-74472b849525
run_id: d3772513-abb7-44c8-a78e-7d1f7ea9bd30
run_step_id: 55bd2588-f465-4940-8138-c768cc434f6d
thread_id: 60cab400-4893-4cee-90ab-d986730c7675
curator system_agent_id: e408c766-7219-51ef-bc91-8b613468caa6
```

Completed durable tool calls:

```text
tool_call_id: a8685841-9ccf-493c-ab74-637d80b4ff76
tool_name: control_plane__projects.create
status: completed
metadata.tool_source: agent_internal_mcp_server
metadata.mcp_server_key: open_talon_control_plane
metadata.mcp_tool_name: projects.create

tool_call_id: d9d261f5-92d8-42e0-b2e5-90251fc79354
tool_name: control_plane__workspaces.create
status: completed
metadata.tool_source: agent_internal_mcp_server
metadata.mcp_server_key: open_talon_control_plane
metadata.mcp_tool_name: workspaces.create
```

## Verified By This Run

The passing live test verified:

- `System Base` exists after startup.
- `System Base / Administration / System Operations` exists.
- a fresh organization can be created through the live gateway.
- the fresh organization receives an `Administration` project.
- the fresh organization receives an `Organization Operations` workspace.
- the fresh organization receives an organization-scoped `Curator` with role `organization operations curator`.
- the fresh organization's Curator receives an active live machine identity during organization bootstrap repair.
- the live admin can be attached to the operations workspace.
- gateway MCP initializes against the live gateway.
- MCP `session.set_scope` succeeds for the organization operations workspace.
- scoped MCP tool discovery exposes `threads.messages.create` after workspace participant attachment.
- a task targeted to the global `Steward` can create an organization, project, and workspace through private control-plane MCP tools.
- the created organization, project, and workspace identify `Steward` as creator through first-class creator fields.
- a task targeted to the organization `Curator` can create a project and workspace through private control-plane MCP tools.
- private MCP tool execution creates completed durable `tool_calls` rows.
- durable tool-call metadata preserves both the agent-visible exposed tool name and underlying remote MCP operation name.

## Notes

- The live test uses the real local Keycloak token endpoint and gateway MCP endpoint.
- The test temporarily changes the local `open-talon-tui` Keycloak client to allow password grants and restores the original value in cleanup.
- The test creates fresh organizations with slugs matching `operational-live-*`.
- The system-level Steward task test creates fresh organizations with slugs matching `steward-created-*` and projects with slugs matching `steward-project-*`.
- The extended Curator task test creates fresh organizations with slugs matching `operational-task-*` and projects with slugs matching `curator-created-*`.
- The test does not depend on external model quality.
