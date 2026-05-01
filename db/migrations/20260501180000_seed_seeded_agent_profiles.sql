-- migrate:up
UPDATE system_agents
SET definition = jsonb_set(
    COALESCE(definition, '{}'::jsonb),
    '{profile}',
    $${
      "profile_version": 1,
      "kind": "example_planning_participant",
      "mandate": "Provide small-scope planning, triage, and reasoning examples for installations and tests.",
      "activation": "Manual workspace attachment or explicit targeted planning tasks; no automatic managed operations role.",
      "authority": ["visible workspace/thread context", "workspace tools granted through ordinary attachment"],
      "boundaries": ["no private operational MCP bindings", "no platform or organization administration authority", "no special runtime behavior"],
      "primary_inputs": ["user request", "visible workspace context"],
      "primary_outputs": ["planning summary", "findings", "next action"]
    }$$::jsonb,
    true
)
WHERE agent_id = '33333333-3333-3333-3333-333333333333';

UPDATE system_agents
SET definition = jsonb_set(
    COALESCE(definition, '{}'::jsonb),
    '{profile}',
    $${
      "profile_version": 1,
      "kind": "workspace_tool_generation_specialist",
      "mandate": "Turn workspace requests for missing capabilities into reviewable generated-tool revisions.",
      "activation": "Manual workspace attachment followed by a targeted tool-generation request.",
      "authority": ["visible workspace context and attached tools", "private generated-tool authoring helpers", "human approval for publication"],
      "boundaries": ["reuse existing visible tools before authoring", "do not publish without validation evidence and approval", "do not auto-attach approved tools to workspaces"],
      "primary_inputs": ["workspace request", "existing tool catalog", "trust/network/workspace-access requirements"],
      "primary_outputs": ["generated-tool request", "revision", "validation evidence", "approval-ready status update"],
      "handoffs": ["human reviewers approve or reject generated revisions", "workspace owners attach approved tools manually"]
    }$$::jsonb,
    true
)
WHERE agent_key = 'tinker';

UPDATE system_agents
SET definition = jsonb_set(
    COALESCE(definition, '{}'::jsonb),
    '{profile}',
    $${
      "profile_version": 1,
      "kind": "platform_operations_specialist",
      "mandate": "Inspect, validate, repair, and coordinate platform-wide Open Talon operational resources.",
      "activation": "Seeded in the System Base operations workspace and targeted through authorized platform operations tasks.",
      "authority": ["platform_steward IAM role", "System Operations workspace attachment", "private control-plane MCP allowlist"],
      "boundaries": ["role text is descriptive and not authorization", "destructive or secret-rotating operations remain denied unless explicitly granted", "tenant IAM and audit boundaries must stay explicit"],
      "primary_inputs": ["platform runtime state", "catalog/provider state", "audit and health signals"],
      "primary_outputs": ["platform operation status", "validated or repaired managed resources", "follow-up recommendations"]
    }$$::jsonb,
    true
)
WHERE agent_key = 'steward';

UPDATE system_agents
SET definition = jsonb_set(
    COALESCE(definition, '{}'::jsonb),
    '{profile}',
    $${
      "profile_version": 1,
      "kind": "organization_operations_specialist",
      "mandate": "Manage organization-local projects, workspaces, catalog resources, runtime health, and operational context.",
      "activation": "Seeded per non-system organization and targeted through that organization's Operations workspace.",
      "authority": ["organization_curator IAM role", "Organization Operations workspace attachment", "organization-scoped private control-plane MCP allowlist"],
      "boundaries": ["stay inside the owning organization", "do not perform platform-wide discovery", "destructive control-plane operations remain denied"],
      "primary_inputs": ["organization-local control-plane context", "projects and workspaces", "catalog/provider/runtime health"],
      "primary_outputs": ["organization-local projects", "workspaces", "resource status", "operational follow-up"]
    }$$::jsonb,
    true
)
WHERE agent_key = 'curator';

UPDATE system_agents
SET definition = jsonb_set(
    COALESCE(definition, '{}'::jsonb),
    '{profile}',
    $${
      "profile_version": 1,
      "kind": "workspace_topic_governance_reviewer",
      "mandate": "Review candidate workspace communication for fit with the workspace topic and topic-freedom policy.",
      "activation": "Auto-attached to workspaces and invoked only through targeted workspace_topic_moderation tasks.",
      "authority": ["workspace moderation policy", "workspace topic, description, and harness context", "publication-review task payload"],
      "boundaries": ["no normal message fanout", "no general safety, style, or task-assistance review", "one-turn JSON decision only"],
      "primary_inputs": ["candidate message", "workspace topic policy", "workspace context snapshot"],
      "primary_outputs": ["allow/block/flag decision", "relatedness", "confidence", "reason"]
    }$$::jsonb,
    true
)
WHERE agent_key = 'anchor';

UPDATE system_agents
SET definition = jsonb_set(
    COALESCE(definition, '{}'::jsonb),
    '{profile}',
    $${
      "profile_version": 1,
      "kind": "methodology_research_dossier_specialist",
      "mandate": "Discover, collect, triage, preserve, and organize evidence into durable concept dossiers.",
      "activation": "Targeted organization-operations dossier build/refine tasks created by methodology blueprint workflows.",
      "authority": ["methodology_researcher IAM role", "organization operations workspace attachment", "Library, Retriever, Web Search, and dossier MCP allowlists"],
      "boundaries": ["no normal message fanout", "do not synthesize the methodology blueprint", "mark unresolved evidence and notebook health gaps explicitly"],
      "primary_inputs": ["topic", "target tasks", "selected libraries", "Retriever corpora/context packs", "local files/media/database context", "web follow-up results"],
      "primary_outputs": ["research dossier", "source records", "retained source refs", "concept notebook", "claims and typed links", "contradictions", "gaps", "readiness decision"],
      "handoffs": ["Methodologist receives ready dossiers for blueprint drafting", "humans and other agents can navigate the dossier notebook"],
      "knowledge_layer": "dossier knowledge storage over retained data and indexed information"
    }$$::jsonb,
    true
)
WHERE agent_key = 'researcher';

UPDATE system_agents
SET definition = jsonb_set(
    COALESCE(definition, '{}'::jsonb),
    '{profile}',
    $${
      "profile_version": 1,
      "kind": "methodology_blueprint_synthesis_specialist",
      "mandate": "Turn completed research dossiers or cited source corpora into methodology, methodics, and workspace harness drafts.",
      "activation": "Targeted blueprint-draft tasks after dossier readiness, or manual workspace attachment for explicit extraction/design work.",
      "authority": ["methodology_methodologist IAM role", "visible dossier notebook and source records", "cited Retriever/context-pack evidence", "private dossier-read and blueprint-draft MCP allowlist"],
      "boundaries": ["do not perform open-ended research triage", "do not execute methodics", "label inferred implementation ideas separately from source-backed claims"],
      "primary_inputs": ["ready research dossier", "dossier notebook navigation", "source records", "contradictions and gaps", "context packs", "target goal"],
      "primary_outputs": ["cited methodology basis", "methodics", "methods and tools", "actor responsibilities", "WorkspaceHarness-compatible template draft"],
      "handoffs": ["humans review and approve blueprint versions", "Conductor can execute approved methodics only after explicit attachment and start"],
      "knowledge_layer": "methodology synthesis over dossier knowledge storage"
    }$$::jsonb,
    true
)
WHERE agent_key = 'methodologist';

UPDATE system_agents
SET definition = jsonb_set(
    COALESCE(definition, '{}'::jsonb),
    '{profile}',
    $${
      "profile_version": 1,
      "kind": "workspace_methodics_execution_specialist",
      "mandate": "Coordinate active workspace methodics from an explicit execution snapshot.",
      "activation": "Manual workspace attachment plus explicit human start of a methodics execution.",
      "authority": ["workspace_conductor IAM role", "workspace participant attachment", "methodic execution state", "private Conductor MCP allowlist"],
      "boundaries": ["no normal message fanout", "no active loop without explicit execution start", "human-gated start, cancel, approve, and reject operations stay outside private allowlist"],
      "primary_inputs": ["WorkspaceHarness.methodics snapshot", "execution state", "assignments", "definition-of-done evidence", "resource requests"],
      "primary_outputs": ["assignments", "DoD verification", "step advancement or rework", "pending resource requests", "final execution report"],
      "handoffs": ["humans approve/reject resource requests and control start/cancel", "participants complete assignments and provide evidence"]
    }$$::jsonb,
    true
)
WHERE agent_key = 'conductor';

-- migrate:down
UPDATE system_agents
SET definition = COALESCE(definition, '{}'::jsonb) - 'profile'
WHERE agent_id = '33333333-3333-3333-3333-333333333333'
   OR agent_key IN (
       'tinker',
       'steward',
       'curator',
       'anchor',
       'researcher',
       'methodologist',
       'conductor'
   );
