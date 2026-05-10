# Methodology Research Console

This document describes the current methodology management workflow across the
admin web feature module, generic dossiers, Researcher, Methodologist, XWiki,
and live-test protocol.

## Product Shape

The admin UI lives inside one feature boundary:

```text
apps/admin-web/src/features/methodologies/
```

Only the feature public API should be imported from outside that directory:

- `MethodologiesPage`
- `methodologiesNavItem`

The browser talks to gateway REST routes only. It does not call MCP directly,
does not introduce a Node backend, and does not add root JavaScript workspace
configuration. Methodology-specific UI stays inside the feature module unless a
primitive is genuinely reusable elsewhere in admin web.

The Research Console is the admin surface for one selected methodology
blueprint. It lets organization admins:

- launch or refine Researcher-led research
- watch dossier lifecycle progress
- inspect search turns, events, sources, source statuses, and coverage gaps
- curate notes, concepts, claims, and links
- inspect the dossier graph and XWiki-backed notebook projection
- answer Researcher clarification or approval requests through interaction
  requests
- approve readiness and hand off to Methodologist
- review, edit, approve, apply, and archive the resulting blueprint

## Workflow

1. An organization admin creates a methodology blueprint request.
2. Core collaboration creates a blueprint, an initial version, a dossier in
   `scoping`, a retained-source organization library, an operations thread, and
   a targeted Researcher task.
3. Researcher scopes the request, performs collection with Library, Retriever,
   Web Search, and database-visible context, then synthesizes the knowledge into
   a generic dossier.
4. Researcher persists source records, retained library references, notes,
   concepts, claims, links, contradictions, gaps, notebook health, and XWiki sync
   state.
5. If human input is needed, Researcher creates ordinary thread interaction
   requests. Waiting for a human answer is not a dossier lifecycle status.
6. When the dossier passes the methodology completion profile, Researcher
   transitions it to `ready`. Core collaboration creates the Methodologist draft
   task and sets the methodology version to `ready_for_draft`.
7. Methodologist consumes the ready dossier, navigates the notebook and graph,
   and submits a cited methodology draft plus a `WorkspaceHarness`-compatible
   draft. Successful submission marks the dossier `consumed`.
8. A human editor can create a new pending-review version from a base version,
   approve it, apply it to a workspace, or archive the blueprint.

Approved methodologies are not edited in place. Editing an approved methodology
creates a new pending-review version. Delete is archive-only: archived
blueprints, dossiers, sources, notebooks, libraries, and audit context remain
readable and are hidden from active lists by default.

## Generic Dossier Lifecycle

Dossiers are workflow-created knowledge objects. Methodology is one consumer of
the dossier lifecycle, not the owner of the lifecycle vocabulary.

Valid statuses are:

```text
created -> scoping -> collecting -> synthesizing -> ready -> consumed -> archived
```

`failed` and `archived` are terminal. `synthesizing -> collecting` is allowed
when a gap requires more evidence. Review, apply, and new revisions are blocked
for archived blueprints; linked dossiers transition to `archived` while
preserving sources, notebooks, retained libraries, and audit context.

Methodology-created dossiers set:

```text
completion_profile=full_methodology_research
```

Readiness for that profile requires these knowledge components:

- `research_plan`
- `source_bibliography`
- `methodology_basis`
- `methodology_principles`
- `methodics_inventory`
- `participants_and_roles`
- `tools_and_methods`
- `information_assets`
- `libraries_and_dossiers`
- `quality_evaluation`
- `contradictions`
- `gaps`
- `synthesis`

Researcher records these as dossier knowledge, usually through notebook notes,
concepts, claims, links, source records, and metadata. They are not just prompt
sections.

## Agent Runtime

Researcher and Methodologist are ordinary seeded global system agents. Their
specialization comes from agent definitions, harnesses, IAM bindings, task
payloads, dossier context, and private MCP allowlists. Runtime workers must not
branch on `agent_key`, display name, role text, capability text, or metadata
tags.

Current seeded methodology specialists use:

- endpoint engine: `openai-responses`
- provider: `openai`
- model: `gpt-5.4-mini`
- harness compaction strategy: `rolling_summary`
- `max_estimated_input_tokens`: `256000`

The compaction policy is stored on each system-agent object. It is not a global
runtime constant. Runtime compacts the execution context before prompt rendering
without mutating canonical collaboration state.

LLM provider failures are recoverable operational events. Retryable provider
failures requeue the affected run step with retry metadata; failed runtime tasks
or claimed tasks waiting on retryable provider work can be resumed through:

```text
POST /v1/organizations/{organization_id}/runtime/tasks/{task_id}/resume
```

Use this after fixing quota, provider health, OpenBao secrets, network issues,
or other transient runtime blockers.

## API Surface

Methodology blueprint routes:

```text
POST   /v1/organizations/{organization_id}/methodology/blueprints
GET    /v1/organizations/{organization_id}/methodology/blueprints
GET    /v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}
DELETE /v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}
POST   /v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}/versions
POST   /v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}/versions/{version_id}/draft
POST   /v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}/versions/{version_id}/approve
POST   /v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}/versions/{version_id}/reject
POST   /v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}/apply
```

Research Console routes:

```text
GET  /v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}/research-state
POST /v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}/research-requests
```

`POST .../research-requests` creates a Researcher refine task. It does not run
research inside the gateway process.

Generic dossier routes used by the console:

```text
GET  /v1/organizations/{organization_id}/dossiers/{dossier_id}
GET  /v1/organizations/{organization_id}/dossiers/{dossier_id}/events
GET  /v1/organizations/{organization_id}/dossiers/{dossier_id}/notebook
GET  /v1/organizations/{organization_id}/dossiers/{dossier_id}/graph
POST /v1/organizations/{organization_id}/dossiers/{dossier_id}/navigate
POST /v1/organizations/{organization_id}/dossiers/{dossier_id}/sync
GET  /v1/organizations/{organization_id}/dossiers/{dossier_id}/sources
POST /v1/organizations/{organization_id}/dossiers/{dossier_id}/sources
PATCH /v1/organizations/{organization_id}/dossiers/{dossier_id}/sources/{source_id}
POST /v1/organizations/{organization_id}/dossiers/{dossier_id}/context-packs
POST /v1/organizations/{organization_id}/dossiers/{dossier_id}/lifecycle
POST /v1/organizations/{organization_id}/dossiers/{dossier_id}/notes
POST /v1/organizations/{organization_id}/dossiers/{dossier_id}/concepts
POST /v1/organizations/{organization_id}/dossiers/{dossier_id}/claims
POST /v1/organizations/{organization_id}/dossiers/{dossier_id}/links
```

The equivalent private MCP operations are named `dossiers.*`, for example
`dossiers.lifecycle.transition`, `dossiers.sources.create`,
`dossiers.notes.upsert`, `dossiers.concepts.upsert`, `dossiers.claims.upsert`,
`dossiers.links.upsert`, `dossiers.navigate`, and `dossiers.sync`.

## Live Test

The real-agent methodology flow is:

```bash
./scripts/run-live-tests.sh methodology-deep-research
```

This suite runs under the XWiki plus web-search stack profile and gates itself
with:

```text
OPEN_TALON_RUN_XWIKI_LIVE=1
OPEN_TALON_RUN_METHODOLOGY_DEEP_RESEARCH_LIVE=1
```

The suite must use the real seeded Researcher and Methodologist agents, the
real runtime workers, the web-search System Plugin/SearXNG path, generic dossier
routes/MCP operations, XWiki notebook projection, and the normal review/apply
archive flow. It should not patch Researcher or Methodologist with deterministic
harnesses when the purpose is proving full methodology/methodics creation.

Before running it, store the OpenAI key in OpenBao or an ignored local secret
source. Do not commit provider keys or paste them into documentation:

```bash
curl -X POST http://127.0.0.1:8200/v1/secret/data/open-talon/llm/openai \
  -H 'X-Vault-Token: root' \
  -H 'Content-Type: application/json' \
  -d '{"data":{"api_key":"sk-..."}}'
```

For a follow-up report, collect durable evidence from both Postgres and
observability:

- methodology blueprint, version, and archive state
- dossier lifecycle events
- dossier sources, notes, concepts, claims, links, contradictions, gaps, and
  readiness metadata
- `tasks`, `runs`, `run_steps`, and `tool_calls`
- retained-source library and XWiki sync records
- Langfuse traces or event exports when runtime observability is enabled
- final Methodologist draft, human revisions, apply result, and archive result

Store raw tracking output in an ignored local run file, such as
`tmp/live-methodology-runs/<run-id>.jsonl`, and summarize the result in a
reviewable report without raw secrets.

## Relevant Files

- [apps/admin-web/src/features/methodologies/](../apps/admin-web/src/features/methodologies/)
- [services/core-collab/core_collab/kernel.py](../services/core-collab/core_collab/kernel.py)
- [services/core-collab/core_collab/system_defaults.py](../services/core-collab/core_collab/system_defaults.py)
- [services/gateway-edge/gateway_edge/routers/collaboration.py](../services/gateway-edge/gateway_edge/routers/collaboration.py)
- [services/gateway-edge/gateway_edge/mcp_api.py](../services/gateway-edge/gateway_edge/mcp_api.py)
- [docs/seeded-agents/researcher.md](./seeded-agents/researcher.md)
- [docs/seeded-agents/methodologist.md](./seeded-agents/methodologist.md)
- [tests/infrastructure/test_xwiki_dossier_live_system.py](../tests/infrastructure/test_xwiki_dossier_live_system.py)
