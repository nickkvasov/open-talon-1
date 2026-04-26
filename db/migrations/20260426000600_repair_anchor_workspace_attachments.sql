WITH anchor AS (
    SELECT agent_id, description, role, capabilities
    FROM system_agents
    WHERE agent_key = 'anchor'
    LIMIT 1
),
workspace_anchor_participants AS (
    SELECT
        (
            SUBSTRING(MD5('open-talon-anchor-participant:' || workspace_id::text), 1, 8)
            || '-' || SUBSTRING(MD5('open-talon-anchor-participant:' || workspace_id::text), 9, 4)
            || '-' || SUBSTRING(MD5('open-talon-anchor-participant:' || workspace_id::text), 13, 4)
            || '-' || SUBSTRING(MD5('open-talon-anchor-participant:' || workspace_id::text), 17, 4)
            || '-' || SUBSTRING(MD5('open-talon-anchor-participant:' || workspace_id::text), 21, 12)
        )::uuid AS participant_id,
        workspace_id
    FROM workspaces
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
    workspace_anchor_participants.participant_id,
    workspace_anchor_participants.workspace_id,
    'agent',
    NULL,
    anchor.agent_id,
    anchor.description,
    to_jsonb(ARRAY[anchor.role]::text[]),
    anchor.capabilities,
    'active',
    'workspace',
    NOW(),
    NOW(),
    '{
      "seeded": true,
      "managed": true,
      "agent_key": "anchor",
      "task_routing": {
        "normal_message_fanout": false,
        "accepted_task_kinds": ["workspace_topic_moderation"]
      }
    }'::jsonb
FROM workspace_anchor_participants
CROSS JOIN anchor
ON CONFLICT (participant_id) DO UPDATE
SET system_agent_id = EXCLUDED.system_agent_id,
    description = EXCLUDED.description,
    roles = EXCLUDED.roles,
    capabilities = EXCLUDED.capabilities,
    status = EXCLUDED.status,
    visibility_scope = EXCLUDED.visibility_scope,
    updated_at = NOW(),
    metadata = participants.metadata || EXCLUDED.metadata;
