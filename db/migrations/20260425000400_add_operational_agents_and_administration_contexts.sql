CREATE TABLE IF NOT EXISTS agent_internal_mcp_servers (
    system_agent_id UUID NOT NULL REFERENCES system_agents(agent_id) ON DELETE CASCADE,
    server_id UUID NOT NULL REFERENCES mcp_servers(server_id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    tools_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    resources_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    prompts_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    sampling_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    name_prefix TEXT NOT NULL DEFAULT '',
    tool_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
    tool_denylist JSONB NOT NULL DEFAULT '[]'::jsonb,
    resource_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
    attached_by UUID NOT NULL,
    attached_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (system_agent_id, server_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_internal_mcp_servers_agent
    ON agent_internal_mcp_servers(system_agent_id, attached_at);

UPDATE system_agents
SET agent_key = 'tinker',
    metadata = COALESCE(metadata, '{}'::jsonb) || '{"agent_key":"tinker"}'::jsonb
WHERE agent_id = '44444444-4444-4444-4444-444444444444'::uuid
  AND (agent_key IS NULL OR agent_key = '');

INSERT INTO organizations (
    organization_id,
    slug,
    name,
    description,
    created_by,
    created_at,
    updated_at,
    metadata
)
VALUES (
    '22222222-2222-2222-2222-222222222222'::uuid,
    'system-base',
    'System Base',
    'Managed organization for Open Talon platform operations.',
    '00000000-0000-0000-0000-000000000000'::uuid,
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"system_base":true}'::jsonb
)
ON CONFLICT (organization_id) DO UPDATE
SET slug = EXCLUDED.slug,
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    updated_at = NOW(),
    metadata = organizations.metadata || EXCLUDED.metadata;

WITH organizations_to_seed AS (
    SELECT
        organization_id,
        created_by,
        created_at
    FROM organizations
),
default_projects AS (
    SELECT
        organization_id,
        (
            SUBSTRING(MD5('open-talon-default-project:' || organization_id::text), 1, 8)
            || '-'
            || SUBSTRING(MD5('open-talon-default-project:' || organization_id::text), 9, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-default-project:' || organization_id::text), 13, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-default-project:' || organization_id::text), 17, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-default-project:' || organization_id::text), 21, 12)
        )::uuid AS project_id,
        created_by,
        created_at
    FROM organizations_to_seed
)
INSERT INTO projects (
    project_id,
    organization_id,
    slug,
    name,
    description,
    created_by,
    creator_user_id,
    creator_system_agent_id,
    owner_user_id,
    owner_system_agent_id,
    created_at,
    updated_at,
    metadata
)
SELECT
    project_id,
    organization_id,
    'default',
    'Default Project',
    'Default project for ordinary workspaces.',
    created_by,
    created_by,
    NULL::uuid,
    created_by,
    NULL::uuid,
    created_at,
    NOW(),
    '{"seeded":true,"managed":true}'::jsonb
FROM default_projects
ON CONFLICT (organization_id, slug) DO NOTHING;

WITH organizations_to_seed AS (
    SELECT
        organization_id,
        created_by,
        created_at
    FROM organizations
),
administration_projects AS (
    SELECT
        organization_id,
        (
            SUBSTRING(MD5('open-talon-administration-project:' || organization_id::text), 1, 8)
            || '-'
            || SUBSTRING(MD5('open-talon-administration-project:' || organization_id::text), 9, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-administration-project:' || organization_id::text), 13, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-administration-project:' || organization_id::text), 17, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-administration-project:' || organization_id::text), 21, 12)
        )::uuid AS project_id,
        created_by,
        created_at
    FROM organizations_to_seed
)
INSERT INTO projects (
    project_id,
    organization_id,
    slug,
    name,
    description,
    created_by,
    creator_user_id,
    creator_system_agent_id,
    owner_user_id,
    owner_system_agent_id,
    created_at,
    updated_at,
    metadata
)
SELECT
    project_id,
    organization_id,
    'administration',
    'Administration',
    'Managed project for operational agents and administrative workspaces.',
    created_by,
    created_by,
    NULL::uuid,
    created_by,
    NULL::uuid,
    created_at,
    NOW(),
    '{"seeded":true,"managed":true,"administration":true}'::jsonb
FROM administration_projects
ON CONFLICT (organization_id, slug) DO NOTHING;

WITH administration_projects AS (
    SELECT
        organization.organization_id,
        organization.slug AS organization_slug,
        project.project_id,
        organization.created_at
    FROM organizations AS organization
    JOIN projects AS project
      ON project.organization_id = organization.organization_id
     AND project.slug = 'administration'
),
operation_workspaces AS (
    SELECT
        organization_id,
        organization_slug,
        project_id,
        (
            SUBSTRING(MD5('open-talon-operations-workspace:' || organization_id::text), 1, 8)
            || '-'
            || SUBSTRING(MD5('open-talon-operations-workspace:' || organization_id::text), 9, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-operations-workspace:' || organization_id::text), 13, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-operations-workspace:' || organization_id::text), 17, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-operations-workspace:' || organization_id::text), 21, 12)
        )::uuid AS workspace_id,
        created_at
    FROM administration_projects
)
INSERT INTO workspaces (
    workspace_id,
    organization_id,
    project_id,
    name,
    description,
    owner_user_id,
    harness,
    created_at,
    updated_at,
    metadata
)
SELECT
    workspace_id,
    organization_id,
    project_id,
    CASE
        WHEN organization_slug = 'system-base' THEN 'System Operations'
        ELSE 'Organization Operations'
    END,
    CASE
        WHEN organization_slug = 'system-base' THEN 'Managed workspace for platform operations.'
        ELSE 'Managed workspace for organization operations.'
    END,
    NULL::uuid,
    NULL::jsonb,
    created_at,
    NOW(),
    jsonb_build_object(
        'seeded', true,
        'managed', true,
        'administration', true,
        'operations_workspace', true,
        'operations_level', CASE WHEN organization_slug = 'system-base' THEN 'system' ELSE 'organization' END
    )
FROM operation_workspaces
ON CONFLICT (workspace_id) DO NOTHING;

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
    '44444444-4444-4444-4444-444444444445'::uuid,
    'steward',
    'global',
    NULL,
    'Steward',
    'Manages Open Talon platform operations through authorized control-plane APIs.',
    'platform steward',
    '["platform_operations","runtime_operations","audit_verification","catalog_management","provider_management","tool_generation_review"]'::jsonb,
    '{"kind":"system","engine_id":"openai-responses","provider":"openai"}'::jsonb,
    'You are Steward, the platform operations agent. Operate only through authorized APIs and MCP tools. Prefer read, validate, repair, and review actions before mutation. Never bypass IAM, audit, or MCP/tool allowlists.',
    '{
      "version": 1,
      "summary": "Global platform operations harness for Steward.",
      "operating_principles": [
        "Use Open Talon control-plane APIs for platform operations.",
        "Keep IAM, audit, secret handling, and tenant boundaries explicit.",
        "Treat destructive operations as unavailable unless separately granted."
      ],
      "tool_use_policy": {
        "inspect_schema_before_use": true,
        "read_before_write": true,
        "verify_side_effects_after_mutation": true,
        "cite_tool_results_in_reasoning": true
      },
      "metadata": {
        "seeded": true,
        "managed": true
      }
    }'::jsonb,
    '{
      "instructions": [
        "Operate as Steward, the platform steward.",
        "Use only allowlisted control-plane APIs and visible tools.",
        "Do not perform destructive delete, audit export, member removal, or secret rotation unless a later explicit binding grants it."
      ],
      "response_contract": {
        "format": "markdown",
        "title": "Steward Update",
        "required_sections": ["Summary", "Status"],
        "guidance": ["Keep operational replies concise and evidence-backed."],
        "json_schema": {}
      },
      "completion_criteria": [
        "Report the operation outcome and any follow-up needed."
      ],
      "metadata": {
        "contract_version": 1,
        "seeded": true
      }
    }'::jsonb,
    '{"runtime":{"engine_id":"openai-responses","preferred_capabilities":["reasoning","tool_calling"],"preferred_locality":"cloud"},"seeded":true,"managed":true}'::jsonb,
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    NOW(),
    '{"managed":true,"seeded":true,"agent_key":"steward"}'::jsonb
)
ON CONFLICT (agent_id) DO UPDATE
SET agent_key = EXCLUDED.agent_key,
    scope = EXCLUDED.scope,
    organization_id = EXCLUDED.organization_id,
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    role = EXCLUDED.role,
    capabilities = EXCLUDED.capabilities,
    updated_at = NOW(),
    metadata = system_agents.metadata || EXCLUDED.metadata;

WITH organization_curators AS (
    SELECT
        organization_id,
        (
            SUBSTRING(MD5('open-talon-curator-agent:' || organization_id::text), 1, 8)
            || '-'
            || SUBSTRING(MD5('open-talon-curator-agent:' || organization_id::text), 9, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-curator-agent:' || organization_id::text), 13, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-curator-agent:' || organization_id::text), 17, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-curator-agent:' || organization_id::text), 21, 12)
        )::uuid AS agent_id,
        created_by,
        created_at
    FROM organizations
    WHERE slug <> 'system-base'
)
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
SELECT
    agent_id,
    'curator',
    'organization',
    organization_id,
    'Curator',
    'Manages organization, project, and workspace operations through authorized control-plane APIs.',
    'organization curator',
    '["organization_operations","project_administration","workspace_administration","workspace_agent_management","workspace_tool_management","audit_verification"]'::jsonb,
    '{"kind":"system","engine_id":"openai-responses","provider":"openai"}'::jsonb,
    'You are Curator, the organization operations agent. Operate only inside your organization through authorized APIs and MCP tools. Respect organization boundaries and use the Administration project for operational work.',
    '{
      "version": 1,
      "summary": "Organization operations harness for Curator.",
      "operating_principles": [
        "Operate only inside the bound organization.",
        "Use Administration for operational work and leave ordinary workspaces in Default Project unless instructed.",
        "Treat destructive operations as unavailable unless separately granted."
      ],
      "tool_use_policy": {
        "inspect_schema_before_use": true,
        "read_before_write": true,
        "verify_side_effects_after_mutation": true,
        "cite_tool_results_in_reasoning": true
      },
      "metadata": {
        "seeded": true,
        "managed": true
      }
    }'::jsonb,
    '{
      "instructions": [
        "Operate as Curator, the organization curator.",
        "Stay inside the organization scope granted by IAM and MCP session scope.",
        "Do not remove organization members, export audit data, rotate secrets, or delete resources unless a later explicit binding grants it."
      ],
      "response_contract": {
        "format": "markdown",
        "title": "Curator Update",
        "required_sections": ["Summary", "Status"],
        "guidance": ["Keep organization operations concise and evidence-backed."],
        "json_schema": {}
      },
      "completion_criteria": [
        "Report the operation outcome and any follow-up needed."
      ],
      "metadata": {
        "contract_version": 1,
        "seeded": true
      }
    }'::jsonb,
    '{"runtime":{"engine_id":"openai-responses","preferred_capabilities":["reasoning","tool_calling"],"preferred_locality":"cloud"},"seeded":true,"managed":true}'::jsonb,
    created_by,
    created_at,
    NOW(),
    jsonb_build_object('managed', true, 'seeded', true, 'agent_key', 'curator', 'organization_id', organization_id::text)
FROM organization_curators
ON CONFLICT (agent_id) DO UPDATE
SET agent_key = EXCLUDED.agent_key,
    scope = EXCLUDED.scope,
    organization_id = EXCLUDED.organization_id,
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    role = EXCLUDED.role,
    capabilities = EXCLUDED.capabilities,
    updated_at = NOW(),
    metadata = system_agents.metadata || EXCLUDED.metadata;

WITH system_operations AS (
    SELECT workspace_id
    FROM workspaces
    WHERE organization_id = '22222222-2222-2222-2222-222222222222'::uuid
      AND metadata->>'operations_level' = 'system'
)
INSERT INTO participants (
    participant_id,
    workspace_id,
    participant_type,
    user_id,
    system_agent_id,
    description,
    roles,
    capabilities,
    status,
    visibility_scope,
    created_at,
    updated_at,
    metadata
)
SELECT
    (
        SUBSTRING(MD5('open-talon-operations-participant:' || workspace_id::text || ':44444444-4444-4444-4444-444444444445'), 1, 8)
        || '-'
        || SUBSTRING(MD5('open-talon-operations-participant:' || workspace_id::text || ':44444444-4444-4444-4444-444444444445'), 9, 4)
        || '-'
        || SUBSTRING(MD5('open-talon-operations-participant:' || workspace_id::text || ':44444444-4444-4444-4444-444444444445'), 13, 4)
        || '-'
        || SUBSTRING(MD5('open-talon-operations-participant:' || workspace_id::text || ':44444444-4444-4444-4444-444444444445'), 17, 4)
        || '-'
        || SUBSTRING(MD5('open-talon-operations-participant:' || workspace_id::text || ':44444444-4444-4444-4444-444444444445'), 21, 12)
    )::uuid,
    workspace_id,
    'agent',
    NULL::uuid,
    '44444444-4444-4444-4444-444444444445'::uuid,
    'Platform steward attached to the system operations workspace.',
    '["platform steward"]'::jsonb,
    '["platform_operations","runtime_operations","audit_verification","catalog_management","provider_management","tool_generation_review"]'::jsonb,
    'active',
    'workspace',
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"operations_participant":true}'::jsonb
FROM system_operations
ON CONFLICT (participant_id) DO NOTHING;

WITH organization_operations AS (
    SELECT workspace.workspace_id, workspace.organization_id
    FROM workspaces AS workspace
    JOIN organizations AS organization
      ON organization.organization_id = workspace.organization_id
    WHERE organization.slug <> 'system-base'
      AND workspace.metadata->>'operations_level' = 'organization'
),
curators AS (
    SELECT agent_id, organization_id
    FROM system_agents
    WHERE agent_key = 'curator'
      AND scope = 'organization'
)
INSERT INTO participants (
    participant_id,
    workspace_id,
    participant_type,
    user_id,
    system_agent_id,
    description,
    roles,
    capabilities,
    status,
    visibility_scope,
    created_at,
    updated_at,
    metadata
)
SELECT
    (
        SUBSTRING(MD5('open-talon-operations-participant:' || workspace_id::text || ':' || agent_id::text), 1, 8)
        || '-'
        || SUBSTRING(MD5('open-talon-operations-participant:' || workspace_id::text || ':' || agent_id::text), 9, 4)
        || '-'
        || SUBSTRING(MD5('open-talon-operations-participant:' || workspace_id::text || ':' || agent_id::text), 13, 4)
        || '-'
        || SUBSTRING(MD5('open-talon-operations-participant:' || workspace_id::text || ':' || agent_id::text), 17, 4)
        || '-'
        || SUBSTRING(MD5('open-talon-operations-participant:' || workspace_id::text || ':' || agent_id::text), 21, 12)
    )::uuid,
    workspace_id,
    'agent',
    NULL::uuid,
    agent_id,
    'Organization curator attached to the organization operations workspace.',
    '["organization curator"]'::jsonb,
    '["organization_operations","project_administration","workspace_administration","workspace_agent_management","workspace_tool_management","audit_verification"]'::jsonb,
    'active',
    'workspace',
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"operations_participant":true}'::jsonb
FROM organization_operations
JOIN curators USING (organization_id)
ON CONFLICT (participant_id) DO NOTHING;

WITH administration_projects AS (
    SELECT project.project_id, project.organization_id
    FROM projects AS project
    WHERE project.slug = 'administration'
),
steward AS (
    SELECT agent_id
    FROM system_agents
    WHERE agent_key = 'steward'
      AND scope = 'global'
),
curators AS (
    SELECT agent_id, organization_id
    FROM system_agents
    WHERE agent_key = 'curator'
      AND scope = 'organization'
)
INSERT INTO project_access_bindings (
    project_id,
    subject_type,
    user_id,
    system_agent_id,
    role,
    created_at,
    updated_at,
    metadata
)
SELECT
    project_id,
    'agent',
    NULL::uuid,
    steward.agent_id,
    'creator',
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"source":"operational_agent"}'::jsonb
FROM administration_projects
CROSS JOIN steward
WHERE administration_projects.organization_id = '22222222-2222-2222-2222-222222222222'::uuid
UNION ALL
SELECT
    administration_projects.project_id,
    'agent',
    NULL::uuid,
    curators.agent_id,
    'creator',
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"source":"operational_agent"}'::jsonb
FROM administration_projects
JOIN curators
  ON curators.organization_id = administration_projects.organization_id
ON CONFLICT DO NOTHING;

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
VALUES (
    '77777777-7777-7777-7777-777777777771'::uuid,
    'global',
    'agent',
    NULL,
    'platform_steward',
    'Least-privilege platform operations permissions for Steward.',
    '[
      "organization.read",
      "organization.members.read",
      "project.read",
      "project.write",
      "workspace.list",
      "workspace.read",
      "organization.runtime.read",
      "agent_catalog.read",
      "agent_catalog.write",
      "tool_catalog.read",
      "tool_catalog.write",
      "provider.llm.read",
      "provider.llm.write",
      "provider.llm.validate",
      "provider.memory.read",
      "provider.memory.write",
      "provider.memory.validate",
      "provider.mcp.read",
      "provider.mcp.write",
      "provider.mcp.validate",
      "git_registry.read",
      "git_registry.write",
      "asset_catalog.read",
      "asset_catalog.publish",
      "asset_catalog.link",
      "asset_catalog.activate",
      "tool_generation.read",
      "tool_generation.review",
      "audit.read",
      "audit.verify"
    ]'::jsonb,
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"agent_key":"steward"}'::jsonb
)
ON CONFLICT (role_id) DO UPDATE
SET permissions = EXCLUDED.permissions,
    updated_at = NOW(),
    metadata = iam_role_definitions.metadata || EXCLUDED.metadata;

WITH organization_curators AS (
    SELECT
        organization_id,
        (
            SUBSTRING(MD5('open-talon-curator-iam-role:' || organization_id::text), 1, 8)
            || '-'
            || SUBSTRING(MD5('open-talon-curator-iam-role:' || organization_id::text), 9, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-curator-iam-role:' || organization_id::text), 13, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-curator-iam-role:' || organization_id::text), 17, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-curator-iam-role:' || organization_id::text), 21, 12)
        )::uuid AS role_id
    FROM organizations
    WHERE slug <> 'system-base'
)
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
SELECT
    role_id,
    'organization',
    'agent',
    organization_id,
    'organization_curator',
    'Least-privilege organization operations permissions for Curator.',
    '[
      "organization.read",
      "organization.members.read",
      "project.read",
      "project.write",
      "workspace.list",
      "workspace.read",
      "organization.runtime.read",
      "agent_catalog.read",
      "agent_catalog.write",
      "tool_catalog.read",
      "tool_catalog.write",
      "provider.llm.read",
      "provider.llm.write",
      "provider.llm.validate",
      "provider.memory.read",
      "provider.memory.write",
      "provider.memory.validate",
      "provider.mcp.read",
      "provider.mcp.write",
      "provider.mcp.validate",
      "git_registry.read",
      "git_registry.write",
      "asset_catalog.read",
      "asset_catalog.publish",
      "asset_catalog.link",
      "asset_catalog.activate",
      "tool_generation.read",
      "tool_generation.review",
      "audit.read",
      "audit.verify"
    ]'::jsonb,
    NOW(),
    NOW(),
    jsonb_build_object('seeded', true, 'managed', true, 'agent_key', 'curator', 'organization_id', organization_id::text)
FROM organization_curators
ON CONFLICT (role_id) DO UPDATE
SET permissions = EXCLUDED.permissions,
    updated_at = NOW(),
    metadata = iam_role_definitions.metadata || EXCLUDED.metadata;

INSERT INTO mcp_servers (
    server_id,
    scope,
    organization_id,
    server_key,
    display_name,
    description,
    transport_kind,
    config,
    secret_config,
    trust_level,
    enabled,
    last_sync_status,
    last_sync_error,
    last_synced_at,
    created_by,
    created_at,
    updated_by,
    updated_at,
    metadata
)
VALUES (
    '66666666-6666-6666-6666-666666666666'::uuid,
    'global',
    NULL,
    'open_talon_control_plane',
    'Open Talon Control Plane',
    'Managed MCP server exposing authorized Open Talon control-plane APIs.',
    'streamable_http',
    '{"url":"http://127.0.0.1:8000/v1/mcp","auth":{"kind":"open_talon_agent_identity"}}'::jsonb,
    '{}'::jsonb,
    'trusted',
    TRUE,
    'managed',
    NULL,
    NOW(),
    '00000000-0000-0000-0000-000000000000'::uuid,
    NOW(),
    '00000000-0000-0000-0000-000000000000'::uuid,
    NOW(),
    '{"seeded":true,"managed":true,"control_plane":true}'::jsonb
)
ON CONFLICT (server_id) DO UPDATE
SET server_key = EXCLUDED.server_key,
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    transport_kind = EXCLUDED.transport_kind,
    config = EXCLUDED.config,
    trust_level = EXCLUDED.trust_level,
    enabled = EXCLUDED.enabled,
    updated_at = NOW(),
    metadata = mcp_servers.metadata || EXCLUDED.metadata;

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
    operation_name,
    operation_name,
    'Open Talon control-plane operation ' || operation_name || '.',
    '{}'::jsonb,
    '{}'::jsonb,
    'managed',
    NOW(),
    '{"seeded":true,"managed":true,"control_plane":true}'::jsonb
FROM (
    VALUES
        ('session.get_identity'),
        ('session.get_permissions'),
        ('session.list_scopes'),
        ('session.set_scope'),
        ('organizations.list'),
        ('organizations.get'),
        ('organizations.members.list'),
        ('projects.list'),
        ('projects.create'),
        ('projects.get'),
        ('projects.update'),
        ('projects.access.list'),
        ('projects.access.upsert'),
        ('workspaces.list'),
        ('workspaces.create'),
        ('workspaces.get'),
        ('threads.create'),
        ('threads.list'),
        ('threads.get'),
        ('threads.timeline.get'),
        ('threads.messages.create'),
        ('memory.workspace.list'),
        ('memory.workspace.create'),
        ('memory.thread.search'),
        ('agent_catalog.list'),
        ('agent_catalog.bundle.validate'),
        ('agent_catalog.bundle.publish'),
        ('tool_catalog.list'),
        ('llm_providers.list'),
        ('memory_providers.list'),
        ('mcp_servers.list'),
        ('runtime.overview.get'),
        ('audit.events.list'),
        ('audit.chains.verify'),
        ('agent_git.repo.ensure'),
        ('agent_git.worktree.create'),
        ('agent_git.file.read'),
        ('agent_git.file.write'),
        ('agent_git.diff.preview'),
        ('agent_git.commit.push'),
        ('iam.agent_identities.list')
) AS operations(operation_name)
ON CONFLICT (server_id, tool_name) DO UPDATE
SET display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    metadata = mcp_server_tools.metadata || EXCLUDED.metadata;

WITH steward AS (
    SELECT agent_id
    FROM system_agents
    WHERE agent_key = 'steward'
      AND scope = 'global'
),
curators AS (
    SELECT agent_id
    FROM system_agents
    WHERE agent_key = 'curator'
      AND scope = 'organization'
)
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
    agent_id,
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
      "organizations.list",
      "organizations.get",
      "organizations.members.list",
      "projects.list",
      "projects.create",
      "projects.get",
      "projects.update",
      "projects.access.list",
      "projects.access.upsert",
      "workspaces.list",
      "workspaces.create",
      "workspaces.get",
      "threads.create",
      "threads.list",
      "threads.get",
      "threads.timeline.get",
      "threads.messages.create",
      "memory.workspace.list",
      "memory.workspace.create",
      "memory.thread.search",
      "agent_catalog.list",
      "agent_catalog.bundle.validate",
      "agent_catalog.bundle.publish",
      "tool_catalog.list",
      "llm_providers.list",
      "memory_providers.list",
      "mcp_servers.list",
      "runtime.overview.get",
      "audit.events.list",
      "audit.chains.verify",
      "agent_git.repo.ensure",
      "agent_git.worktree.create",
      "agent_git.file.read",
      "agent_git.file.write",
      "agent_git.diff.preview",
      "agent_git.commit.push",
      "iam.agent_identities.list"
    ]'::jsonb,
    '["agent_git.file.delete","agent_git.worktree.discard","projects.access.remove"]'::jsonb,
    '[]'::jsonb,
    '[]'::jsonb,
    '00000000-0000-0000-0000-000000000000'::uuid,
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"agent_key":"steward"}'::jsonb
FROM steward
UNION ALL
SELECT
    agent_id,
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
      "organizations.members.list",
      "projects.list",
      "projects.create",
      "projects.get",
      "projects.update",
      "projects.access.list",
      "projects.access.upsert",
      "workspaces.list",
      "workspaces.create",
      "workspaces.get",
      "threads.create",
      "threads.list",
      "threads.get",
      "threads.timeline.get",
      "threads.messages.create",
      "memory.workspace.list",
      "memory.workspace.create",
      "memory.thread.search",
      "agent_catalog.list",
      "agent_catalog.bundle.validate",
      "agent_catalog.bundle.publish",
      "tool_catalog.list",
      "llm_providers.list",
      "memory_providers.list",
      "mcp_servers.list",
      "runtime.overview.get",
      "audit.events.list",
      "audit.chains.verify",
      "agent_git.repo.ensure",
      "agent_git.worktree.create",
      "agent_git.file.read",
      "agent_git.file.write",
      "agent_git.diff.preview",
      "agent_git.commit.push",
      "iam.agent_identities.list"
    ]'::jsonb,
    '["organizations.list","agent_git.file.delete","agent_git.worktree.discard","projects.access.remove"]'::jsonb,
    '[]'::jsonb,
    '[]'::jsonb,
    '00000000-0000-0000-0000-000000000000'::uuid,
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"agent_key":"curator"}'::jsonb
FROM curators
ON CONFLICT (system_agent_id, server_id) DO UPDATE
SET enabled = EXCLUDED.enabled,
    tools_enabled = EXCLUDED.tools_enabled,
    name_prefix = EXCLUDED.name_prefix,
    tool_allowlist = EXCLUDED.tool_allowlist,
    tool_denylist = EXCLUDED.tool_denylist,
    updated_at = NOW(),
    metadata = agent_internal_mcp_servers.metadata || EXCLUDED.metadata;
