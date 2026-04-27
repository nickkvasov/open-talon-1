# Operational Agents Real-Life Test Protocol

This document defines the real-life verification protocol for the managed operational agents and their administration contexts.

It is for tests that exercise the actual local Open Talon stack rather than only in-process unit coverage. The protocol verifies seeded records, upgrade repair behavior, agent identity bootstrap, private MCP execution, runtime persistence, audit visibility, and tenant boundaries.

Related references:

- [system-quickstart.md](./system-quickstart.md)
- [system-api-reference.md](./system-api-reference.md)
- [iam.md](./iam.md)
- [agent-operations-guide.md](./agent-operations-guide.md)
- [tinker-tool-generation.md](./tinker-tool-generation.md)
- [live-tests-short-stories.md](./live-tests-short-stories.md)
- [operational-agents-test-run-log-2026-04-26.md](./operational-agents-test-run-log-2026-04-26.md)
- [tests/infrastructure/operational_agents_live](../tests/infrastructure/operational_agents_live)
- [tests/infrastructure/test_tinker_live_system.py](../tests/infrastructure/test_tinker_live_system.py)

## Scope

The protocol covers these managed agents and contexts:

- `Tinker` with `agent_key=tinker`, role `generated tool authoring and validation agent`
- `Steward` with `agent_key=steward`, role `platform operations steward`
- `Curator` with `agent_key=curator`, role `organization operations curator`
- `Anchor` with `agent_key=anchor`, role `workspace topic alignment reviewer`, using the managed `local-ollama` provider by default
- `System Base / Administration / System Operations`
- each non-system organization's `Administration / Organization Operations`
- the managed control-plane MCP server `open_talon_control_plane`
- agent-private MCP bindings and OIDC client-credentials authentication

This protocol does not treat agent role names as authorization. IAM role bindings, project access, workspace participant attachment, and private MCP/tool allowlists remain the authority.

## Test Levels

Use three levels of real-life validation.

| Level | Purpose | Typical command |
| --- | --- | --- |
| Business case | Verify behavior through in-process domain logic without external services | `pytest tests/business-cases/test_tinker_tool_generation.py -q` |
| Integration | Verify migrations, repository state, gateway/MCP surfaces, and runtime behavior with test backends | `pytest -m integration tests/core-collab/test_repository_integration.py -q` |
| Live system | Verify the real local stack: Postgres, Valkey, Kafka, Keycloak, OpenBao, gateway, runtime workers, tool worker, and reconciler | `OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 pytest -m integration tests/infrastructure/operational_agents_live -q -s` |

The live-system tests are intentionally gated. They are not part of default `pytest -q` because they depend on local services, credentials, ports, and sometimes model availability.

## Preconditions

Run from the repository root.

Bootstrap Python once:

```bash
./scripts/bootstrap-python.sh
source .venv/bin/activate
```

Start the local stack:

```bash
./open-talon start
```

The live protocol expects these local services to be reachable:

- gateway: `http://127.0.0.1:8000`
- Keycloak realm issuer: `http://127.0.0.1:8081/realms/open-talon`
- OpenBao: `http://127.0.0.1:8200`
- Postgres, Valkey, Kafka, and runtime workers started by `./open-talon start`

Default live-test human credentials:

- username: `admin`
- password: `admin123`
- client id: `open-talon-tui`

Optional environment overrides:

```bash
export OPEN_TALON_GATEWAY_URL=http://127.0.0.1:8000
export OPEN_TALON_OIDC_ISSUER_URL=http://127.0.0.1:8081/realms/open-talon
export OPEN_TALON_TUI_CLIENT_ID=open-talon-tui
export OPEN_TALON_LIVE_ADMIN_USERNAME=admin
export OPEN_TALON_LIVE_ADMIN_PASSWORD=admin123
```

For live tests that depend on model quality, keep the model dependency explicit. The Tinker live path currently expects the configured `OPEN_TALON_DEFAULT_REASONING_MODEL` in local Ollama:

```bash
curl http://127.0.0.1:11434/api/tags
```

## Automated Live Execution

Run the operational-agent live wiring test:

```bash
OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/operational_agents_live -q -s
```

The suite is split by live behavior so new operational agents can add focused modules without expanding one monolithic file:

- `test_bootstrap_live_system.py` verifies managed context bootstrap and organization Curator wiring.
- `test_steward_live_system.py` verifies the system-level `Steward` task path.
- `test_curator_live_system.py` verifies the organization-level `Curator` task path.

This suite verifies:

- `System Base` exists after startup
- `System Base / Administration / System Operations` exists
- creating a fresh organization creates `Administration / Organization Operations`
- the fresh organization receives an organization-scoped `Curator`
- the fresh organization receives an active Curator machine identity during organization creation/bootstrap repair
- the live test admin is attached to the organization operations workspace before thread MCP tools are checked
- gateway MCP can be initialized against the live gateway
- the session can scope itself to the organization operations workspace
- allowed MCP tools such as `threads.messages.create` are visible in that scoped session
- a targeted Steward task can create one organization, one project, and one workspace through private control-plane MCP tools
- Steward is recorded as creator on the created organization, project, and workspace through first-class creator fields
- a targeted Curator task can create a new organization project through the private `control_plane__projects.create` MCP tool
- the same Curator task can create a workspace in that project through the private `control_plane__workspaces.create` MCP tool
- durable `tool_calls` rows are completed for the private control-plane MCP operations, with `tool_source=agent_internal_mcp_server`

For noninteractive local execution, the live test temporarily enables direct password grants on the local `open-talon-tui` Keycloak client and restores the original setting afterward. The normal TUI flow remains device-flow based.

Run the Tinker live regression separately:

```bash
./.venv/bin/python -m pytest -m integration tests/infrastructure/test_tinker_live_system.py -q -s
```

This test verifies the real generated-tool path:

- attach seeded `Tinker`
- request an organization-scoped generated tool
- build and validate the tool
- approve the generated revision into the catalog
- manually attach the published tool to a workspace
- use another agent to call the generated tool
- preserve the rule that approval publishes only to catalog, not to workspace attachment

## Manual Real-Life Protocol

Use the manual protocol when changing bootstrap, IAM, MCP, runtime execution, audit, or tenant-boundary logic. The goal is to prove that the real stack behaves correctly from an operator's point of view.

### 1. Record The Test Run

Capture:

- git branch and commit SHA
- migration version at the start of the test
- exact command used to start the stack
- environment overrides
- test organization slug
- IDs of created organizations, projects, workspaces, agents, threads, runs, run steps, and tool calls

### 2. Verify Startup And Readiness

Check readiness:

```bash
curl http://127.0.0.1:8000/ready
curl http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration
curl http://127.0.0.1:8200/v1/sys/health
```

Pass criteria:

- gateway reports ready
- Keycloak discovery document responds
- OpenBao responds
- `agent-task-worker`, `agent-loop-worker`, `tool-worker`, and `reconciler` are running

### 3. Verify Managed System Contexts

Authenticate as `admin` through the local OIDC flow or an existing TUI profile.

Verify:

- organization slug `system-base` exists
- project slug `administration` exists inside `system-base`
- workspace `System Operations` exists under that project
- `Steward` exists as a global system agent with role `platform operations steward`
- `Steward` is attached as a participant in `System Operations`
- `Steward` has an active `agent_identities` record after gateway bootstrap

Pass criteria:

- all records exist after startup without manual SQL
- rerunning startup does not create duplicates
- missing managed records are repaired by migrations or gateway bootstrap

### 4. Verify New Organization Bootstrap

Create a fresh organization with a unique slug.

Verify:

- project slug `default` exists
- project slug `administration` exists
- workspace `Organization Operations` exists under `administration`
- one organization-scoped `Curator` exists with role `organization operations curator`
- the Curator is attached to `Organization Operations`
- the Curator has project access for the administration project
- the Curator has the expected organization IAM role binding
- the Curator has an active `agent_identities` record after gateway bootstrap

Pass criteria:

- organization creation produces both ordinary and operational contexts
- ordinary workspace placement still uses `Default Project`
- administration context is available without manual repair

### 5. Verify Agent Identity Authentication

For `Steward` and the fresh organization's `Curator`, verify:

- `agent_identities.secret_ref` points to an OpenBao secret
- the secret contains the client credential needed for Keycloak client-credentials auth
- the Keycloak token endpoint returns an access token for the agent client
- the gateway resolves the token as an agent principal

Pass criteria:

- no raw client secret is stored in API responses or audit metadata
- the token resolves to the expected `system_agent_id`
- disabling or deleting the secret causes authentication to fail cleanly

### 6. Verify Private MCP Visibility

Initialize a gateway MCP session as each operator.

For `Steward`, verify allowed control-plane read and validation tools are visible, including platform/org/project/workspace reads, runtime overview, audit read/verify, provider/catalog validation, and tool-generation review reads.

For `Curator`, verify org-scoped administration tools are visible only inside that Curator's organization context.

Pass criteria:

- allowed MCP operations are listed
- destructive defaults are absent or rejected, including destructive delete, member removal, audit export, and secret rotation
- Curator cannot list or mutate another organization's resources
- hidden tools cannot be invoked directly by name

### 7. Verify Runtime MCP Execution

Create an operations thread and target the correct agent:

- target `Steward` from `System Operations`
- target `Curator` from the fresh organization's `Organization Operations`

Ask for a control-plane action that requires an MCP call. Minimum coverage is listing projects or reading runtime overview. Extended coverage for `Curator` is creating one organization project and one workspace from a task posted to the organization's `Organization Operations` thread.

Pass criteria:

- a task is created
- a run is created for the targeted agent
- a `run_step` is created for the MCP tool call
- durable `tool_call` records are created for each requested MCP operation
- the MCP call executes with an OIDC client-credentials token minted from the current agent identity
- the thread receives a reply or a clear failure message
- project/workspace creation requests use the agent-visible private MCP names, such as `control_plane__projects.create` and `control_plane__workspaces.create`
- `tool_calls.metadata.mcp_tool_name` records the underlying remote MCP operation name, such as `projects.create` or `workspaces.create`

### 8. Verify Task-Specific Instructions

Post two otherwise similar messages to the same operations thread:

- one with `task_instructions`
- one without `task_instructions`

The task-specific instruction should affect only the run for that message. It must not override:

- system prompt
- agent harness
- IAM authorization
- MCP allowlists
- workspace tool allowlists

Pass criteria:

- `task_instructions` are present in task metadata for the intended task
- `AgentExecutionContext.task_instructions` contains the same instructions
- prompt rendering includes them as run-local instructions
- later tasks do not inherit earlier task-specific instructions
- instructions that request forbidden operations are rejected by IAM or MCP allowlists

### 9. Verify Audit And Runtime Signals

Inspect:

- thread timeline
- runtime overview
- `runs`
- `run_steps`
- `tool_calls`
- audit events
- audit chain verification

Pass criteria:

- successful operator actions produce runtime records
- denied operator actions produce observable failures without bypassing IAM
- audit metadata does not contain raw bearer tokens, prompt bodies, tool arguments, or message bodies
- `organization:<id>` and `workspace:<id>` chains verify where relevant

### 10. Verify Tinker Regression

Run the Tinker business-case and live tests after operational-agent changes that touch system agents, tool generation, internal tools, MCP, runtime execution, or catalog publication.

Pass criteria:

- `Tinker` still uses `agent_key=tinker`
- Tinker helper tools remain private
- generated-tool approval publishes only to the target catalog
- approval does not attach the tool to any workspace
- organization-scoped and global publication paths remain distinct

## Failure And Repair Cases

Run these checks when changing migrations or gateway bootstrap.

| Case | Action | Expected result |
| --- | --- | --- |
| Missing administration project | Delete only a test organization's `administration` project in a disposable database, then restart | managed project and operations workspace are repaired without duplicates |
| Missing Curator identity | Remove the Curator `agent_identities` row in a disposable database, then restart gateway | gateway bootstrap provisions a replacement identity and OpenBao secret |
| Missing private MCP binding | Remove a test Curator private MCP binding, then rerun migrations/startup | binding is restored |
| Cross-org Curator action | Use org A Curator token against org B resources | operation is hidden or rejected |
| Forbidden MCP operation | Invoke a destructive or non-allowlisted operation directly by name | operation is rejected even if the client guesses the tool name |

Only run destructive repair cases against disposable local data.

## Evidence Checklist

A complete real-life test report should include:

- command transcript for startup and tests
- live-test pytest output
- created organization slug and IDs
- managed project and workspace IDs
- `Steward` and `Curator` system agent IDs
- proof of active agent identity records without exposing secrets
- MCP tool list snippets showing allowed and denied operations
- task, run, run step, and tool call IDs for at least one successful MCP action
- one denied cross-organization or forbidden-operation attempt
- audit query or chain verification result
- cleanup confirmation

## Cleanup

For routine live tests, delete only resources created for the test run:

- test organizations with unique slugs such as `operational-live-*`
- test workspaces and threads created under those organizations
- generated tools, images, or agent definitions created by live Tinker runs

Do not delete managed seed records from a shared local database unless the purpose of the run is specifically to validate repair behavior.

## Acceptance Criteria

The real-life protocol passes when:

- managed contexts exist and are idempotent
- each new organization gets both default and administration contexts
- `Steward` and `Curator` authenticate through real Keycloak client credentials resolved from OpenBao
- private MCP allowlists expose only intended operations
- Curator cannot cross organization boundaries
- runtime MCP execution creates durable `run_step` and `tool_call` records
- task-specific instructions stay scoped to one task instance
- audit and runtime signals are produced for successful and denied operations
- Tinker generated-tool behavior remains unchanged
