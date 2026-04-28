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
VALUES
    (
        '66666666-6666-6666-6666-666666666666'::uuid,
        'methodics.assignments.create',
        'methodics.assignments.create',
        'Open Talon control-plane operation methodics.assignments.create.',
        'managed',
        NOW(),
        '{"seeded":true,"managed":true,"control_plane":true}'::jsonb
    ),
    (
        '66666666-6666-6666-6666-666666666666'::uuid,
        'methodics.steps.evaluate',
        'methodics.steps.evaluate',
        'Open Talon control-plane operation methodics.steps.evaluate.',
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
SET tool_allowlist = (
        SELECT jsonb_agg(tool_name ORDER BY tool_name)
        FROM (
            SELECT jsonb_array_elements_text(binding.tool_allowlist) AS tool_name
            UNION
            SELECT unnest(ARRAY[
                'methodics.assignments.create',
                'methodics.steps.evaluate'
            ]) AS tool_name
        ) AS merged
    ),
    updated_at = NOW(),
    metadata = binding.metadata || '{"managed":true,"methodics_loop_tools":true}'::jsonb
FROM system_agents AS agent
WHERE binding.system_agent_id = agent.agent_id
  AND agent.agent_key = 'conductor'
  AND binding.server_id = '66666666-6666-6666-6666-666666666666'::uuid;

-- migrate:down

UPDATE agent_internal_mcp_servers AS binding
SET tool_allowlist = (
        SELECT COALESCE(jsonb_agg(tool_name ORDER BY tool_name), '[]'::jsonb)
        FROM (
            SELECT jsonb_array_elements_text(binding.tool_allowlist) AS tool_name
        ) AS existing
        WHERE tool_name NOT IN (
            'methodics.assignments.create',
            'methodics.steps.evaluate'
        )
    ),
    updated_at = NOW(),
    metadata = binding.metadata - 'methodics_loop_tools'
FROM system_agents AS agent
WHERE binding.system_agent_id = agent.agent_id
  AND agent.agent_key = 'conductor'
  AND binding.server_id = '66666666-6666-6666-6666-666666666666'::uuid;

DELETE FROM mcp_server_tools
WHERE server_id = '66666666-6666-6666-6666-666666666666'::uuid
  AND tool_name IN (
      'methodics.assignments.create',
      'methodics.steps.evaluate'
  );
