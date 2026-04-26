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
VALUES (
    '66666666-6666-6666-6666-666666666666'::uuid,
    'organizations.create',
    'organizations.create',
    'Open Talon control-plane operation organizations.create.',
    '{}'::jsonb,
    '{}'::jsonb,
    'managed',
    NOW(),
    '{"seeded":true,"managed":true,"control_plane":true}'::jsonb
)
ON CONFLICT (server_id, tool_name) DO UPDATE
SET display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    metadata = mcp_server_tools.metadata || EXCLUDED.metadata;

UPDATE iam_role_definitions
SET permissions = CASE
        WHEN permissions ? 'organization.write' THEN permissions
        ELSE permissions || '["organization.write"]'::jsonb
    END,
    updated_at = NOW(),
    metadata = metadata || '{"managed":true,"agent_key":"steward"}'::jsonb
WHERE role_id = '77777777-7777-7777-7777-777777777771'::uuid
  AND name = 'platform_steward'
  AND subject_kind = 'agent';

UPDATE agent_internal_mcp_servers AS binding
SET tool_allowlist = CASE
        WHEN binding.tool_allowlist ? 'organizations.create' THEN binding.tool_allowlist
        ELSE binding.tool_allowlist || '["organizations.create"]'::jsonb
    END,
    updated_at = NOW(),
    metadata = binding.metadata || '{"managed":true,"agent_key":"steward"}'::jsonb
FROM system_agents AS agent
WHERE binding.system_agent_id = agent.agent_id
  AND agent.agent_key = 'steward'
  AND agent.scope = 'global'
  AND binding.server_id = '66666666-6666-6666-6666-666666666666'::uuid;
