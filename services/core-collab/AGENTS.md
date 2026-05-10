# Core Collaboration Agent Guide

This guide applies under `services/core-collab/` and adds to the root and
service guides.

## Domain Authority

- `core-collab` owns canonical collaboration domain logic and the Postgres
  repository layer.
- Postgres is the source of truth for collaboration state, durable execution
  state, IAM bindings, participants, audit ledger rows, provider records,
  Library state, and managed operational contexts.
- Keep business rules in focused services/modules where possible. Avoid growing
  `CollaborationKernel` with large grant-resolution or approval-policy blocks
  once behavior has stabilized.
- Prefer explicit repository methods and SQL over implicit conventions.
- Keep migration/backfill behavior separate from steady-state read/write logic.

## Identity, IAM, and Participants

- Organization membership and membership roles live in Postgres.
- Require organization membership before resolving workspace actors for
  authenticated humans.
- Agent workspace visibility and runtime claimability must account for workspace
  participant attachment, not only project access bindings.
- IAM role bindings, project access, workspace participant attachment, and
  MCP/tool allowlists are the authority for operational agents; role text is
  descriptive, not authorization.
- Keep workspace `role_definitions` as collaboration-role metadata only. Do not
  use them as an authorization layer.
- Humans and agents share permission names, but not the same global or
  organization role bindings.
- Do not use weak hash helpers such as MD5/SHA-1 UUID generation for
  deterministic identifiers, even when the input is "only" an internal id.
  Prefer an explicit SHA-256 based deterministic UUID helper, and preserve
  existing persisted participant IDs during repair/backfill instead of creating
  duplicate participants.

## External Access

- External system definitions, external identity grants, and external operation
  approvals are control-plane identity authority. Use
  `external.systems.read`, `external.systems.write`,
  `external.systems.validate`, `external.grants.read`,
  `external.grants.write`, and `external.operations.approve`; do not invent
  workspace-local collaboration permissions such as
  `workspace.external_identities.write`.
- Workspace collaboration roles, capabilities, and workspace-admin labels must
  never grant external-system access or external grant management.
- External access grants must remain workspace-participant scoped and keep
  normalized target links to `user_id` or `system_agent_id`.
- Do not authorize external operations from collaboration role names, capability
  text, metadata tags, or client-provided actor fields.
- Pre-assigned external grants during participant attach/update APIs require
  organization or global `external.grants.write`. Ordinary participant
  attachment callers without that permission must reject external grant fields.
- MCP calls with `auth.kind="external_identity"` and direct external-operation
  APIs must resolve grants through the same external-access path.
- Missing, expired, revoked, inactive, wrong-workspace, or wrong-participant
  grants must fail authorization before any outbound operation is attempted.
- High-risk or destructive external operations must create
  `external_operation_requests` unless the grant policy explicitly pre-approves
  that operation for that participant grant.
- Approval and rejection require `external.operations.approve`, not ordinary
  workspace participation.
- Approved high-risk MCP operations park the tool call until approval and requeue
  it after approval. The resumed execution path must mark the operation request
  `completed` or `failed`.

## Audit

- Treat `collab_event_log` and `audit_event_ledger` as separate concerns:
  collaboration fanout vs. compliance/investigation.
- `audit_event_ledger` is append-only in steady-state code; do not add
  update/delete flows for audit rows.
- Audit integrity depends on `chain_partition`, `chain_sequence`, `prev_hash`,
  and `event_hash`; preserve chain semantics when changing audit writes.
- Organization audit chains use `organization:<id>` partitions; workspace chains
  stay `workspace:<id>` and platform/global chains stay `global`.
- Audit v1 is metadata-only. Do not store raw bearer tokens, prompt bodies, tool
  arguments, or message bodies inline in audit metadata.
- Keep Postgres as the canonical audit ledger unless the task explicitly
  redesigns audit authority.
- Keep non-canonical audit surfaces behind provider boundaries. Do not hard-wire
  Kafka, ClickHouse, MinIO, Langfuse, HyperDX, or other backend details back into
  service orchestration.

## Providers, Library, and Assets

- LLM providers are persistent records in `llm_providers`; do not reintroduce
  env-defined engine registries.
- Memory providers are persistent records in `memory_providers`; do not hardcode
  provider definitions in application logic after bootstrapping.
- Library is store-first and Retriever indexing is explicit. Adding uploads,
  Markdown/text, webpage scraps, images, or diagrams to a library must not
  enqueue ingestion unless the caller invokes the library index route or
  Retriever plugin tool.
- Organization, project, and workspace libraries can reuse slugs across different
  owners.
- Workspace search includes workspace libraries plus explicitly attached
  organization/project libraries.
- Cross-organization or cross-project library attachments must be rejected.
- Keep the storage taxonomy explicit: MinIO/object storage is immutable bytes and
  snapshots; Library plus Retriever indexes are retained indexed information;
  dossiers are concept organization, claims, contradictions, methods,
  synthesis, provenance, and navigation.
- Dossier notebooks are external provider projections owned by Open Talon
  control-plane state. Open Talon stores lifecycle, source provenance, IAM,
  audit, graph metadata, and sync state in Postgres; XWiki stores the navigable
  concept repository through the `DossierNotebookProvider` abstraction and must
  not become the authorization or audit authority.

## Managed Agents

- Operational/system-wide agents and managed specialist agents advertise their
  purpose through normal fields such as `display_name`, `role`, and
  `capabilities`. Do not add extra operational classification columns unless
  there is a strict product or authorization need.
- Managed operational contexts must be seeded and repaired idempotently:
  `System Base / Administration / System Operations` for platform operations,
  and each non-system organization's `Administration / Organization Operations`
  context for organization operations.
- Managed operational-agent identity bootstrap must validate live OIDC
  client-credentials authentication and repair stale or missing Keycloak
  clients/OpenBao secrets after local stack restarts or upgrades.
- Keep seeded `definition.profile` blocks aligned with each agent card; profiles
  describe mandate, activation, authority, boundaries, handoffs, and knowledge
  layer but do not authorize anything.
- Any code path that creates an organization and its managed
  `Organization Operations` workspace must attach the global Anchor participant
  immediately. If a prior path could have created workspaces without Anchor, add
  an explicit migration/backfill.
- Anchor participant repair must be idempotent: when an Anchor participant is
  already attached, keep its existing `participant_id` and creation timestamp
  while updating managed metadata and routing defaults.
- `Methodologist` is a managed global specialist agent for evidence-backed
  methodology extraction and workspace template design. Keep it a normal
  `system_agents` definition.
- `Conductor` is a separate managed global specialist for active workspace
  methodics execution. It must be explicitly attached through normal workspace
  agent attachment, and methodics execution must be explicitly started.
- Workspaces without attached Conductor have no active methodics execution loop.
  Starting execution must return a clear conflict if Conductor is not attached.
- Conductor uses dedicated `methodic_*` execution tables, targets only methodics
  task kinds, and sets `normal_message_fanout=false`.
- Methodologist outputs should separate source-grounded methodology basis,
  methodics, methods, tools, actors, and workspace templates. Source-derived
  claims need cited retrieval/source evidence, while inferred tools or
  implementation ideas must be labeled as inference or ideation.
- Make specialist response contracts explicit enough that outputs can be
  translated into existing Open Talon structures such as
  `WorkspaceHarness.methodology`, `methodics`, `execution_rules`, participants,
  tools, retrieval corpora, and artifacts.

## Key Files

- `core_collab/migrations.py`
- `core_collab/repository.py`
- `core_collab/kernel.py`
- `core_collab/system_defaults.py`

## Tests

- Run relevant `tests/core-collab` coverage for repository, kernel, IAM,
  Library, audit, provider, and managed-agent changes.
- Run `tests/core-collab/test_agent_contracts.py` when agent contracts, seeded
  agent definitions, execution contracts, or provider records change.
- Run migration-file coverage when schema or migration parsing changes:
  `tests/core-collab/test_migration_files.py` and
  `tests/scripts/test_system_scripts.py`.
- Run relevant gateway and agent-runtime tests when core behavior changes a
  cross-service contract.
