-- migrate:up

INSERT INTO mcp_server_tools (
    server_id,
    tool_name,
    display_name,
    description,
    capability_hash,
    discovered_at,
    metadata
)
VALUES (
    '66666666-6666-6666-6666-666666666666'::uuid,
    'methodics.resource_requests.create',
    'methodics.resource_requests.create',
    'Open Talon control-plane operation methodics.resource_requests.create.',
    'managed',
    NOW(),
    '{"seeded":true,"managed":true,"control_plane":true}'::jsonb
)
ON CONFLICT (server_id, tool_name) DO UPDATE
SET display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    capability_hash = EXCLUDED.capability_hash,
    discovered_at = EXCLUDED.discovered_at,
    metadata = mcp_server_tools.metadata || EXCLUDED.metadata;

UPDATE agent_internal_mcp_servers AS binding
SET tool_allowlist = CASE
        WHEN binding.tool_allowlist ? 'methodics.resource_requests.create' THEN binding.tool_allowlist
        ELSE binding.tool_allowlist || '["methodics.resource_requests.create"]'::jsonb
    END,
    updated_at = NOW(),
    metadata = binding.metadata || '{"managed":true,"methodic_resource_request_create":true}'::jsonb
FROM system_agents AS agent
WHERE binding.system_agent_id = agent.agent_id
  AND agent.agent_key = 'conductor'
  AND binding.server_id = '66666666-6666-6666-6666-666666666666'::uuid;

-- migrate:down
