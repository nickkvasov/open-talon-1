# Seeded Agents System Concept

This document explains how seeded agents fit into Open Talon as a system. The
individual agent cards in this directory describe each agent in detail; this
document describes the shared concept, boundaries, and collaboration model.

## Core Idea

Open Talon treats humans and agents as first-class workspace participants. A
seeded agent is not a special runtime class. It is a normal `system_agents`
record that gives a local installation useful default behavior after bootstrap.

Seeded agents provide the initial operating layer for:

- planning and task triage
- generated-tool creation
- platform and organization operations
- workspace topic governance
- dossier creation
- methodology extraction and workspace design
- opt-in methodics execution

The runtime remains generic. It reads agent definitions, harnesses, interaction
contracts, task payloads, workspace context, tools, MCP bindings, memory, and
provider configuration. It must not branch on `agent_key`, display name, role
text, capability text, or metadata tags.

Each seeded agent also carries a `definition.profile` block. The profile is the
machine-readable counterpart to the card: it records mandate, activation,
authority, boundaries, inputs, outputs, handoffs, and knowledge layer where
relevant. Profiles support admin surfaces, documentation, and agent discovery,
but authorization still comes only from IAM, attachments, task routing, and
tool/MCP allowlists.

## Authority Model

Agent role text is descriptive. It helps humans, routers, and UIs understand
what an agent is for, but it is not an authorization layer.

Authority comes from:

- global or organization IAM role bindings
- project access bindings
- workspace participant attachment
- task targeting and task kind routing
- private tool and MCP allowlists
- human approval gates
- tenant scope and caller permissions

This keeps seeded agents useful without making their names magical.

## System Layers

| Layer | Responsibility | Seeded-agent relevance |
| --- | --- | --- |
| Identity and IAM | Human users, system agents, agent identities, role bindings, permissions | Steward, Curator, Researcher, Methodologist, and Conductor receive authority through IAM and scoped bindings |
| Collaboration | Organizations, projects, workspaces, participants, threads, messages, requests | All seeded agents participate through ordinary workspace attachment when used in a workspace |
| Execution | Durable tasks, runs, run steps, tool calls, runtime workers | Agent behavior is executed through the generic runtime and persisted in Postgres |
| Knowledge and evidence | Dossiers, retained dossier libraries, Retriever context, workspace memory, files, assets, citations | Researcher builds reusable dossiers; Methodologist uses dossier evidence; Conductor can search/read evidence needed for active methodics |
| Operations | Control-plane MCP, provider/catalog management, audit, runtime overview | Steward operates globally; Curator operates inside one organization |
| Governance | Topic policy, methodics execution gates, review and approval flows | Anchor governs topic fit; Conductor uses human gates for start/cancel/resource approval; Tinker uses review gates for generated tools |

## Seeded Agent Role Map

| Agent | Profile kind | System role | Main boundary |
| --- | --- | --- | --- |
| Reasoning Planner | `example_planning_participant` | Example planning participant for cloud reasoning and interaction-contract seeding | No private tools or operational authority by default |
| Tinker | `workspace_tool_generation_specialist` | Creates missing agent-usable tools from workspace requests | Must be attached to a workspace; generated tools require approval and manual workspace attachment |
| Steward | `platform_operations_specialist` | Platform operations specialist for global control-plane work | Global IAM plus System Operations workspace; destructive tools remain denied unless explicitly granted later |
| Curator | `organization_operations_specialist` | Organization operations specialist for one tenant | Organization-scoped IAM and Organization Operations workspace; cannot cross organization boundaries |
| Anchor | `workspace_topic_governance_reviewer` | Workspace topic-alignment reviewer | Auto-attached per workspace, but receives only topic-moderation tasks and no normal message fanout |
| Researcher | `methodology_dossier_specialist` | Evidence discovery and durable dossier specialist | Builds dossier source records, contradiction maps, gaps, and context-pack links; does not synthesize methodology |
| Methodologist | `methodology_blueprint_synthesis_specialist` | Evidence-backed methodology extraction and workspace-template design specialist | Produces cited methodology/methodics/template drafts; does not execute methodics |
| Conductor | `workspace_methodics_execution_specialist` | Active methodics execution coordinator | Must be explicitly attached and explicitly started; human-gated start/cancel/resource decisions |

## Lifecycle

Startup and repair seed global defaults:

- Reasoning Planner
- Tinker
- Steward
- Anchor
- Researcher
- Methodologist
- Conductor
- System Base organization
- Administration project and System Operations workspace
- managed control-plane MCP server and selected private bindings

Organization creation and repair seed organization-local defaults:

- Default Project
- Administration project
- Organization Operations workspace
- one organization-scoped Curator
- Curator machine identity and scoped IAM role
- Curator attachment to Organization Operations

Workspace creation and repair attach:

- Anchor, with `normal_message_fanout=false` and `workspace_topic_moderation` as its accepted task kind

Manual workspace attachment is still required for:

- Tinker, before generated-tool requests can be targeted in that workspace
- Methodologist, before it participates in a workspace extraction/design thread
- Conductor, before methodics execution can be started
- any other non-auto-attached agent

Conductor has an extra activation step: attachment only makes Conductor
available. A human with the required permission must explicitly start a
methodics execution from the active `WorkspaceHarness.methodics`.

## How The Agents Work Together

A typical methodology-driven workflow can look like this:

1. Users create a methodology blueprint request with a topic, tasks, and optional selected libraries.
2. The service creates a dossier and a retained-source library, then creates a targeted Researcher task in the organization's operations workspace.
3. Researcher searches local libraries, Retriever corpora, files, database-visible context, and web follow-up sources, then records included, excluded, duplicate, failed, and unresolved source records.
4. Researcher maps contradictions, attaches context packs, stores fetched source snapshots in the retained dossier library when possible, and marks the dossier ready.
5. Methodologist receives the ready dossier and drafts methodology basis,
   methodics, methods/tools/actors, and a workspace template.
6. Humans decide whether to approve the draft and materialize the template into workspace harness
   fields, participants, tools, retrieval corpora, and artifacts.
7. If tools are missing, Tinker can generate candidate tools, subject to review
   and manual attachment.
8. Humans attach Conductor and explicitly start methodics execution when they
   want active orchestration.
9. Conductor snapshots the methodics, creates assignments, verifies definition
   of done evidence, requests rework when needed, advances steps, and writes a
   final report.
10. Curator can help manage organization-local operational resources. Steward can
   help with platform-level operational resources.
11. Anchor remains the workspace topic-governance participant for publication
   review, independent of the methodics workflow.

The important separation is that Researcher builds the evidence dossier,
Methodologist designs the approach, and Conductor executes an approved active
methodics snapshot.

## Attachment Versus Activity

Attachment means an agent is present as a workspace participant and can be
targeted according to its routing metadata and permissions.

Activity means a specific task or workflow has been created for that agent.

Examples:

- Anchor is attached automatically, but only topic-moderation tasks should reach it.
- Conductor can be attached, but no methodics loop runs until a start API or MCP
  call creates methodic execution state.
- Tinker can be attached, but no tool-generation request exists until a targeted
  request asks for a tool.
- Researcher is not a normal workspace chat participant; methodology blueprint
  creation targets it in the organization operations workspace for dossier work.
- Methodologist can be attached, but source-backed extraction requires visible or
  cited evidence in the task context, often from a ready dossier.

## Human Gates

Seeded agents can propose, coordinate, and execute within their contracts, but
several decisions intentionally remain human-gated:

- Tinker-generated tool approval or rejection
- generated-tool workspace attachment after approval
- Conductor methodics execution start and cancellation
- Conductor resource request approval or rejection
- destructive or privileged control-plane operations unless separately granted

This preserves local-first automation while keeping organization and workspace
owners in control of durable changes.

## Maintainability Rules

When changing a seeded agent:

- update its `definition.profile` when the mandate, activation, authority,
  boundaries, or handoffs change
- update the Python seed/repair definition and any migration/backfill needed for existing installs
- update the agent card in this directory
- update relevant API, quickstart, and live-test docs
- add or update seed, migration, kernel, MCP, and live tests for changed behavior
- keep behavior contract-driven through harnesses, interaction contracts, task payloads, IAM, attachments, and tool/MCP allowlists
- do not add runtime branches based on agent identity names or descriptive text

## Test Strategy

Seeded-agent confidence comes from three layers:

- seed and migration tests that prove the records, scopes, endpoints, harnesses,
  routing metadata, IAM roles, and private bindings exist
- kernel and gateway tests that prove permissions, attachment, task routing,
  human gates, and state transitions
- gated live tests that prove the real local stack can execute end-to-end
  workflows through gateway, runtime workers, Keycloak, OpenBao, Postgres, MCP,
  local Ollama where relevant, and durable `tool_calls`

The live tests are intentionally split by agent so each role can evolve without
turning the suite into one monolithic scenario.
