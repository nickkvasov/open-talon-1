-- migrate:up

INSERT INTO system_agents (
    agent_id,
    agent_key,
    scope,
    organization_id,
    display_name,
    description,
    role,
    capabilities,
    endpoint,
    system_prompt,
    harness,
    interaction_contract,
    definition,
    created_by,
    created_at,
    updated_at,
    metadata
)
VALUES (
    '44444444-4444-4444-4444-444444444449'::uuid,
    'researcher',
    'global',
    NULL,
    'Researcher',
    'Builds durable research dossiers by discovering, collecting, triaging, and organizing evidence from local libraries, indexed retrieval corpora, databases, files, media, and web follow-up.',
    'evidence discovery and research dossier agent',
    '[
      "discovers sources across selected organization libraries and retrieval corpora",
      "uses web follow-up for recency gaps contradiction checks and missing coverage",
      "triages sources by quality relevance duplication inclusion and unresolved status",
      "maps contradictions disagreements and follow-up questions before synthesis",
      "preserves fetched pages papers files and media in retained dossier libraries",
      "submits structured research dossier source records and readiness updates"
    ]'::jsonb,
    '{"kind":"system","engine_id":"local-ollama","provider":"ollama"}'::jsonb,
    'You are Researcher. Build durable research dossiers for specific topics and tasks. Start with selected local and organization libraries, pre-indexed Retriever corpora, files, media, and database-visible context. Use web search and fetch only for gaps, recency, contradiction checks, or missing source coverage. Preserve fetched sources in the retained dossier library when possible. Record each source with retained refs, quality notes, rationale, status, fetch metadata, contradictions, and errors. Mark a dossier ready only when the evidence boundary, gaps, and disagreements are explicit enough for downstream agents or humans.',
    '{
      "version": 1,
      "summary": "Research dossier harness for auditable multi-step discovery, triage, contradiction mapping, and retained source organization.",
      "operating_principles": [
        "Treat the dossier as a reusable evidence object for agents, users, and participants.",
        "Search local libraries and indexed corpora before broad web discovery.",
        "Use explicit web follow-up for gaps, recency, and contradictions.",
        "Preserve fetched source snapshots in the retained dossier library whenever possible.",
        "Keep included, excluded, duplicate, failed, and unresolved records visible.",
        "Separate evidence, quality judgment, disagreement mapping, and open gaps."
      ],
      "planning": {
        "plan_before_act": true,
        "incremental_execution": true,
        "one_goal_at_a_time": true,
        "explicit_uncertainty": true,
        "guidance": [
          "Start with a research plan covering local libraries, retrieval, web follow-up, and triage criteria.",
          "Iterate when contradictions or gaps imply a follow-up search.",
          "Do a final dossier readiness pass before marking ready for downstream synthesis."
        ]
      },
      "tool_use_policy": {
        "prefer_existing_workspace_tools": true,
        "read_before_write": true,
        "inspect_schema_before_use": true,
        "cite_tool_results_in_reasoning": true,
        "verify_side_effects_after_mutation": true,
        "selection_principles": [
          "Use Library tools to inspect selected and retained dossier libraries.",
          "Use Retriever tools for indexed searches and context packs.",
          "Use Web Search only for explicit follow-up discovery, gaps, or recency.",
          "Use methodology dossier MCP tools to persist every source and readiness update."
        ],
        "fallback_when_no_tool_fits": "Record the limitation as an unresolved dossier gap and continue with visible evidence."
      },
      "memory_policy": {
        "use_run_memory": true,
        "use_thread_memory": true,
        "use_workspace_memory": true
      },
      "validation_policy": {
        "required_checks": [
          "Every fetched source has a retained reference or a clear fetch failure.",
          "Every source has a terminal triage status before readiness.",
          "Quality notes and rationale are present for included and excluded sources.",
          "Contradictions and disagreements are mapped with affected source ids.",
          "Open gaps and follow-up opportunities are explicit before mark_ready."
        ],
        "require_evidence_for_claims": true,
        "require_tool_results_for_completion": true,
        "require_tests_before_done": false
      },
      "stop_policy": {
        "completion_conditions": [
          "The research dossier has structured sources, summary, contradictions, gaps, context packs, and a readiness decision."
        ],
        "stop_conditions": [
          "Do not synthesize the methodology blueprint; hand the completed dossier to Methodologist."
        ]
      },
      "metadata": {
        "seeded": true,
        "managed": true,
        "agent_key": "researcher",
        "research_dossier_agent": true,
        "task_routing": {
          "normal_message_fanout": false,
          "accepted_task_kinds": [
            "methodology_research_dossier_build",
            "methodology_research_dossier_refine"
          ]
        }
      }
    }'::jsonb,
    '{
      "instructions": [
        "Operate as Researcher, the evidence discovery and research dossier agent.",
        "Build and refine durable dossiers through targeted dossier tasks only.",
        "Search local libraries and Retriever context first, then use web follow-up for gaps and recency.",
        "Persist source records, context packs, contradictions, gaps, and readiness through dossier MCP operations.",
        "Do not synthesize the final methodology blueprint."
      ],
      "response_contract": {
        "format": "markdown",
        "title": "Research Dossier Update",
        "required_sections": [
          "Research Scope",
          "Discovery Plan",
          "Sources",
          "Quality Notes",
          "Contradictions",
          "Gaps",
          "Retained References",
          "Readiness"
        ],
        "guidance": [
          "Group sources by status: included, excluded, duplicate, failed, and unresolved.",
          "Cite retained library item ids, context pack ids, asset refs, or source URIs.",
          "State why follow-up searches were or were not needed."
        ],
        "json_schema": {}
      },
      "completion_criteria": [
        "The dossier is durable enough for Methodologist, another agent, or a human reviewer to consume.",
        "Source statuses and retained refs are explicit.",
        "Contradictions and remaining gaps are explicit."
      ],
      "metadata": {
        "contract_version": 1,
        "seeded": true,
        "agent_key": "researcher"
      }
    }'::jsonb,
    '{
      "runtime": {
        "engine_id": "local-ollama",
        "provider": "ollama",
        "preferred_capabilities": ["local", "ollama", "reasoning"],
        "preferred_locality": "host"
      },
      "seeded": true,
      "managed": true,
      "agent_key": "researcher",
      "research_dossier_agent": true,
      "task_routing": {
        "normal_message_fanout": false,
        "accepted_task_kinds": [
          "methodology_research_dossier_build",
          "methodology_research_dossier_refine"
        ]
      }
    }'::jsonb,
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    NOW(),
    '{"managed":true,"seeded":true,"agent_key":"researcher","research_dossier_agent":true,"task_routing":{"normal_message_fanout":false,"accepted_task_kinds":["methodology_research_dossier_build","methodology_research_dossier_refine"]}}'::jsonb
)
ON CONFLICT (agent_id) DO UPDATE
SET agent_key = EXCLUDED.agent_key,
    scope = EXCLUDED.scope,
    organization_id = EXCLUDED.organization_id,
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    role = EXCLUDED.role,
    capabilities = EXCLUDED.capabilities,
    endpoint = EXCLUDED.endpoint,
    system_prompt = EXCLUDED.system_prompt,
    harness = EXCLUDED.harness,
    interaction_contract = EXCLUDED.interaction_contract,
    definition = EXCLUDED.definition,
    updated_at = NOW(),
    metadata = system_agents.metadata || EXCLUDED.metadata;

INSERT INTO iam_role_definitions (
    role_id,
    scope,
    subject_kind,
    organization_id,
    name,
    description,
    permissions,
    created_at,
    updated_at,
    metadata
)
VALUES
(
    '77777777-7777-7777-7777-777777777773'::uuid,
    'global',
    'agent',
    NULL,
    'methodology_researcher',
    'Least-privilege research dossier permissions for the seeded Researcher specialist.',
    '[
      "organization.read",
      "project.read",
      "workspace.list",
      "workspace.read",
      "library.read",
      "library.write",
      "library.index",
      "retrieval.read",
      "retrieval.search",
      "methodology.read",
      "methodology.write"
    ]'::jsonb,
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"agent_key":"researcher"}'::jsonb
),
(
    '77777777-7777-7777-7777-777777777774'::uuid,
    'global',
    'agent',
    NULL,
    'methodology_methodologist',
    'Least-privilege methodology blueprint drafting permissions for the seeded Methodologist specialist.',
    '[
      "organization.read",
      "workspace.read",
      "library.read",
      "retrieval.read",
      "retrieval.search",
      "methodology.read",
      "methodology.write"
    ]'::jsonb,
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"agent_key":"methodologist"}'::jsonb
)
ON CONFLICT (role_id) DO UPDATE
SET name = EXCLUDED.name,
    description = EXCLUDED.description,
    permissions = EXCLUDED.permissions,
    updated_at = NOW(),
    metadata = iam_role_definitions.metadata || EXCLUDED.metadata;

WITH methodology_tools(tool_name) AS (
    VALUES
        ('methodology.dossiers.get'),
        ('methodology.dossiers.sources.create'),
        ('methodology.dossiers.sources.update'),
        ('methodology.dossiers.context_pack.attach'),
        ('methodology.dossiers.mark_ready'),
        ('methodology.blueprints.submit_draft')
)
INSERT INTO mcp_server_tools (
    server_id,
    tool_name,
    display_name,
    description,
    input_schema,
    output_schema,
    capability_hash,
    discovered_at,
    metadata
)
SELECT
    '66666666-6666-6666-6666-666666666666'::uuid,
    tool_name,
    tool_name,
    'Open Talon control-plane operation ' || tool_name || '.',
    '{}'::jsonb,
    '{}'::jsonb,
    'managed',
    NOW(),
    '{"seeded":true,"managed":true,"control_plane":true}'::jsonb
FROM methodology_tools
WHERE EXISTS (
    SELECT 1
    FROM mcp_servers
    WHERE server_id = '66666666-6666-6666-6666-666666666666'::uuid
)
ON CONFLICT (server_id, tool_name) DO UPDATE
SET description = EXCLUDED.description,
    capability_hash = EXCLUDED.capability_hash,
    metadata = mcp_server_tools.metadata || EXCLUDED.metadata;

INSERT INTO agent_internal_mcp_servers (
    system_agent_id,
    server_id,
    enabled,
    tools_enabled,
    resources_enabled,
    prompts_enabled,
    sampling_enabled,
    name_prefix,
    tool_allowlist,
    tool_denylist,
    resource_allowlist,
    prompt_allowlist,
    attached_by,
    attached_at,
    updated_at,
    metadata
)
SELECT
    '44444444-4444-4444-4444-444444444449'::uuid,
    '66666666-6666-6666-6666-666666666666'::uuid,
    TRUE,
    TRUE,
    FALSE,
    FALSE,
    FALSE,
    'control_plane__',
    '[
      "session.get_identity",
      "session.get_permissions",
      "session.list_scopes",
      "session.set_scope",
      "organizations.get",
      "workspaces.list",
      "workspaces.get",
      "threads.get",
      "threads.timeline.get",
      "threads.messages.create",
      "methodology.dossiers.get",
      "methodology.dossiers.sources.create",
      "methodology.dossiers.sources.update",
      "methodology.dossiers.context_pack.attach",
      "methodology.dossiers.mark_ready"
    ]'::jsonb,
    '["agent_git.file.delete","agent_git.worktree.discard","projects.access.remove"]'::jsonb,
    '[]'::jsonb,
    '[]'::jsonb,
    '00000000-0000-0000-0000-000000000000'::uuid,
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"agent_key":"researcher"}'::jsonb
WHERE EXISTS (
    SELECT 1
    FROM mcp_servers
    WHERE server_id = '66666666-6666-6666-6666-666666666666'::uuid
)
ON CONFLICT (system_agent_id, server_id) DO UPDATE
SET tool_allowlist = EXCLUDED.tool_allowlist,
    tool_denylist = EXCLUDED.tool_denylist,
    updated_at = NOW(),
    metadata = agent_internal_mcp_servers.metadata || EXCLUDED.metadata;

INSERT INTO agent_internal_mcp_servers (
    system_agent_id,
    server_id,
    enabled,
    tools_enabled,
    resources_enabled,
    prompts_enabled,
    sampling_enabled,
    name_prefix,
    tool_allowlist,
    tool_denylist,
    resource_allowlist,
    prompt_allowlist,
    attached_by,
    attached_at,
    updated_at,
    metadata
)
SELECT
    '44444444-4444-4444-4444-444444444447'::uuid,
    '66666666-6666-6666-6666-666666666666'::uuid,
    TRUE,
    TRUE,
    FALSE,
    FALSE,
    FALSE,
    'control_plane__',
    '[
      "session.get_identity",
      "session.get_permissions",
      "session.list_scopes",
      "session.set_scope",
      "organizations.get",
      "workspaces.get",
      "threads.get",
      "threads.timeline.get",
      "retrieval.context_pack.get",
      "methodology.dossiers.get",
      "methodology.blueprints.submit_draft"
    ]'::jsonb,
    '["agent_git.file.delete","agent_git.worktree.discard","projects.access.remove"]'::jsonb,
    '[]'::jsonb,
    '[]'::jsonb,
    '00000000-0000-0000-0000-000000000000'::uuid,
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"agent_key":"methodologist"}'::jsonb
WHERE EXISTS (
    SELECT 1
    FROM mcp_servers
    WHERE server_id = '66666666-6666-6666-6666-666666666666'::uuid
)
ON CONFLICT (system_agent_id, server_id) DO UPDATE
SET tool_allowlist = EXCLUDED.tool_allowlist,
    tool_denylist = EXCLUDED.tool_denylist,
    updated_at = NOW(),
    metadata = agent_internal_mcp_servers.metadata || EXCLUDED.metadata;

-- migrate:down

DELETE FROM agent_internal_mcp_servers
WHERE system_agent_id IN (
    '44444444-4444-4444-4444-444444444449'::uuid,
    '44444444-4444-4444-4444-444444444447'::uuid
)
  AND server_id = '66666666-6666-6666-6666-666666666666'::uuid;

DELETE FROM mcp_server_tools
WHERE server_id = '66666666-6666-6666-6666-666666666666'::uuid
  AND tool_name IN (
      'methodology.dossiers.get',
      'methodology.dossiers.sources.create',
      'methodology.dossiers.sources.update',
      'methodology.dossiers.context_pack.attach',
      'methodology.dossiers.mark_ready',
      'methodology.blueprints.submit_draft'
  );

DELETE FROM iam_role_definitions
WHERE role_id IN (
    '77777777-7777-7777-7777-777777777773'::uuid,
    '77777777-7777-7777-7777-777777777774'::uuid
);

DELETE FROM system_agents
WHERE agent_id = '44444444-4444-4444-4444-444444444449'::uuid;
