ALTER TABLE participants
    ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(user_id) ON DELETE SET NULL;

ALTER TABLE participants
    ADD COLUMN IF NOT EXISTS system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'participants'
          AND column_name = 'display_name'
    ) THEN
        INSERT INTO users (user_id, display_name, metadata, created_at, updated_at)
        SELECT participant_id, display_name, '{}'::jsonb, created_at, updated_at
        FROM participants
        WHERE participant_type = 'user'
          AND display_name IS NOT NULL
        ON CONFLICT (user_id) DO NOTHING;
    END IF;
END
$$;

UPDATE participants
SET user_id = participant_id
WHERE participant_type = 'user'
  AND user_id IS NULL;

UPDATE participants
SET system_agent_id = NULLIF(metadata->>'system_agent_id', '')::uuid
WHERE participant_type = 'agent'
  AND system_agent_id IS NULL
  AND metadata ? 'system_agent_id';

UPDATE participants
SET description = NULL,
    roles = '[]'::jsonb,
    capabilities = '[]'::jsonb,
    metadata = metadata - 'system_agent_id' - 'agent_config'
WHERE participant_type = 'agent'
  AND system_agent_id IS NOT NULL;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'participants'
          AND column_name = 'display_name'
    ) THEN
        EXECUTE 'ALTER TABLE participants DROP COLUMN display_name';
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_participants_workspace
    ON participants(workspace_id, participant_type);

CREATE INDEX IF NOT EXISTS idx_participants_workspace_user
    ON participants(workspace_id, user_id);

CREATE INDEX IF NOT EXISTS idx_participants_workspace_system_agent
    ON participants(workspace_id, system_agent_id);
