-- migrate:up

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
    '77777777-7777-7777-7777-777777777772'::uuid,
    'global',
    'agent',
    NULL,
    'workspace_conductor',
    'Least-privilege workspace methodics execution permissions for Conductor after explicit workspace attachment.',
    '[
      "workspace.read",
      "retrieval.read",
      "retrieval.search",
      "methodics.read",
      "methodics.execute"
    ]'::jsonb,
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"agent_key":"conductor"}'::jsonb
)
ON CONFLICT (role_id) DO UPDATE
SET permissions = EXCLUDED.permissions,
    updated_at = NOW(),
    metadata = iam_role_definitions.metadata || EXCLUDED.metadata;

INSERT INTO mcp_server_tools (
    server_id,
    tool_name,
    display_name,
    description,
    capability_hash,
    discovered_at,
    metadata
)
VALUES
    (
        '66666666-6666-6666-6666-666666666666'::uuid,
        'methodics.executions.create',
        'methodics.executions.create',
        'Open Talon control-plane operation methodics.executions.create.',
        'managed',
        NOW(),
        '{"seeded":true,"managed":true,"control_plane":true,"human_gated":true}'::jsonb
    ),
    (
        '66666666-6666-6666-6666-666666666666'::uuid,
        'methodics.executions.list',
        'methodics.executions.list',
        'Open Talon control-plane operation methodics.executions.list.',
        'managed',
        NOW(),
        '{"seeded":true,"managed":true,"control_plane":true}'::jsonb
    ),
    (
        '66666666-6666-6666-6666-666666666666'::uuid,
        'methodics.executions.get',
        'methodics.executions.get',
        'Open Talon control-plane operation methodics.executions.get.',
        'managed',
        NOW(),
        '{"seeded":true,"managed":true,"control_plane":true}'::jsonb
    ),
    (
        '66666666-6666-6666-6666-666666666666'::uuid,
        'methodics.executions.cancel',
        'methodics.executions.cancel',
        'Open Talon control-plane operation methodics.executions.cancel.',
        'managed',
        NOW(),
        '{"seeded":true,"managed":true,"control_plane":true,"human_gated":true}'::jsonb
    ),
    (
        '66666666-6666-6666-6666-666666666666'::uuid,
        'methodics.resource_requests.approve',
        'methodics.resource_requests.approve',
        'Open Talon control-plane operation methodics.resource_requests.approve.',
        'managed',
        NOW(),
        '{"seeded":true,"managed":true,"control_plane":true,"human_gated":true}'::jsonb
    ),
    (
        '66666666-6666-6666-6666-666666666666'::uuid,
        'methodics.resource_requests.reject',
        'methodics.resource_requests.reject',
        'Open Talon control-plane operation methodics.resource_requests.reject.',
        'managed',
        NOW(),
        '{"seeded":true,"managed":true,"control_plane":true,"human_gated":true}'::jsonb
    )
ON CONFLICT (server_id, tool_name) DO UPDATE
SET display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    capability_hash = EXCLUDED.capability_hash,
    discovered_at = EXCLUDED.discovered_at,
    metadata = mcp_server_tools.metadata || EXCLUDED.metadata;

UPDATE iam_role_definitions
SET permissions = (
        SELECT jsonb_agg(permission ORDER BY permission)
        FROM (
            SELECT jsonb_array_elements_text(iam_role_definitions.permissions) AS permission
            UNION
            SELECT unnest(ARRAY[
                'methodology.read',
                'methodology.write',
                'methodics.read',
                'methodics.execute',
                'methodics.admin'
            ]) AS permission
        ) AS merged
    ),
    updated_at = NOW(),
    metadata = metadata || '{"managed":true,"methodics_permissions":true}'::jsonb
WHERE subject_kind = 'agent'
  AND name IN ('platform_steward', 'organization_curator');

UPDATE agent_internal_mcp_servers AS binding
SET tool_allowlist = (
        SELECT jsonb_agg(tool_name ORDER BY tool_name)
        FROM (
            SELECT jsonb_array_elements_text(binding.tool_allowlist) AS tool_name
            UNION
            SELECT unnest(ARRAY[
                'methodics.executions.list',
                'methodics.executions.get'
            ]) AS tool_name
        ) AS merged
    ),
    updated_at = NOW(),
    metadata = binding.metadata || '{"managed":true,"methodics_read_tools":true}'::jsonb
FROM system_agents AS agent
WHERE binding.system_agent_id = agent.agent_id
  AND agent.agent_key IN ('steward', 'curator')
  AND binding.server_id = '66666666-6666-6666-6666-666666666666'::uuid;

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
VALUES (
    '44444444-4444-4444-4444-444444444448'::uuid,
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
      "workspaces.get",
      "threads.create",
      "threads.list",
      "threads.get",
      "threads.timeline.get",
      "threads.messages.create",
      "memory.workspace.list",
      "memory.workspace.create",
      "memory.thread.search",
      "retrieval.corpora.list",
      "retrieval.sources.list",
      "retrieval.search",
      "retrieval.context_pack.create",
      "retrieval.context_pack.get",
      "methodics.executions.list",
      "methodics.executions.get"
    ]'::jsonb,
    '[
      "methodics.executions.create",
      "methodics.executions.cancel",
      "methodics.resource_requests.approve",
      "methodics.resource_requests.reject",
      "agent_git.file.delete",
      "agent_git.worktree.discard",
      "projects.access.remove"
    ]'::jsonb,
    '[]'::jsonb,
    '[]'::jsonb,
    '00000000-0000-0000-0000-000000000000'::uuid,
    NOW(),
    NOW(),
    '{"seeded":true,"managed":true,"agent_key":"conductor"}'::jsonb
)
ON CONFLICT (system_agent_id, server_id) DO UPDATE
SET enabled = EXCLUDED.enabled,
    tools_enabled = EXCLUDED.tools_enabled,
    name_prefix = EXCLUDED.name_prefix,
    tool_allowlist = EXCLUDED.tool_allowlist,
    tool_denylist = EXCLUDED.tool_denylist,
    updated_at = NOW(),
    metadata = agent_internal_mcp_servers.metadata || EXCLUDED.metadata;

-- migrate:down
