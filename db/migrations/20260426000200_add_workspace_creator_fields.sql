ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS created_by UUID,
    ADD COLUMN IF NOT EXISTS creator_user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS creator_system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL;

UPDATE workspaces AS workspace
SET creator_system_agent_id = (workspace.metadata->>'creator_system_agent_id')::uuid
WHERE workspace.creator_system_agent_id IS NULL
  AND workspace.metadata ? 'creator_system_agent_id'
  AND workspace.metadata->>'creator_system_agent_id' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  AND EXISTS (
      SELECT 1
      FROM system_agents AS agent
      WHERE agent.agent_id = (workspace.metadata->>'creator_system_agent_id')::uuid
  );

UPDATE workspaces
SET creator_user_id = owner_user_id
WHERE creator_user_id IS NULL
  AND creator_system_agent_id IS NULL
  AND owner_user_id IS NOT NULL;

UPDATE workspaces
SET created_by = COALESCE(
    CASE
        WHEN metadata ? 'created_by'
         AND metadata->>'created_by' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN (metadata->>'created_by')::uuid
        ELSE NULL
    END,
    creator_user_id,
    creator_system_agent_id,
    owner_user_id,
    workspace_id
)
WHERE created_by IS NULL;

ALTER TABLE workspaces
    ALTER COLUMN created_by SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_workspaces_creator_user
    ON workspaces(creator_user_id)
    WHERE creator_user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_workspaces_creator_system_agent
    ON workspaces(creator_system_agent_id)
    WHERE creator_system_agent_id IS NOT NULL;
