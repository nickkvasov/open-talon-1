ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES users(user_id) ON DELETE SET NULL;

UPDATE workspaces
SET owner_user_id = participant_owner.user_id
FROM (
    SELECT workspace_id, user_id
    FROM (
        SELECT p.workspace_id, p.user_id,
               ROW_NUMBER() OVER(PARTITION BY p.workspace_id ORDER BY p.created_at ASC, p.participant_id ASC) as rn
        FROM participants p
        WHERE p.user_id IS NOT NULL
    ) sub
    WHERE rn = 1
) participant_owner
WHERE workspaces.workspace_id = participant_owner.workspace_id
  AND workspaces.owner_user_id IS NULL;

WITH workspace_defaults AS (
    SELECT
        w.workspace_id,
        COALESCE(first_participant.participant_id, w.owner_user_id, w.workspace_id) AS updated_by,
        jsonb_build_object(
            'admin',
            jsonb_build_object(
                'name', 'admin',
                'definition', 'Manages the workspace, participants, tools, and provider configuration.',
                'updated_by', COALESCE(first_participant.participant_id, w.owner_user_id, w.workspace_id),
                'updated_at', to_jsonb(w.updated_at)
            ),
            'supervisor',
            jsonb_build_object(
                'name', 'supervisor',
                'definition', 'Coordinates delivery, reviews work, and guides workspace members without full administrative control.',
                'updated_by', COALESCE(first_participant.participant_id, w.owner_user_id, w.workspace_id),
                'updated_at', to_jsonb(w.updated_at)
            ),
            'user',
            jsonb_build_object(
                'name', 'user',
                'definition', 'Collaborates in the workspace, participates in threads, and uses attached tools.',
                'updated_by', COALESCE(first_participant.participant_id, w.owner_user_id, w.workspace_id),
                'updated_at', to_jsonb(w.updated_at)
            )
        ) AS default_roles,
        CASE
            WHEN jsonb_typeof(w.metadata->'role_definitions') = 'object' THEN w.metadata->'role_definitions'
            WHEN jsonb_typeof(w.metadata->'role_definitions') = 'array' THEN COALESCE(
                (
                    SELECT jsonb_object_agg(role_item->>'name', role_item)
                    FROM jsonb_array_elements(w.metadata->'role_definitions') AS role_item
                    WHERE role_item ? 'name'
                ),
                '{}'::jsonb
            )
            ELSE '{}'::jsonb
        END AS existing_roles
    FROM workspaces w
    LEFT JOIN LATERAL (
        SELECT p.participant_id
        FROM participants p
        WHERE p.workspace_id = w.workspace_id
        ORDER BY p.created_at ASC, p.participant_id ASC
        LIMIT 1
    ) AS first_participant ON TRUE
)
UPDATE workspaces
SET metadata = jsonb_set(
    COALESCE(workspaces.metadata, '{}'::jsonb),
    '{role_definitions}',
    workspace_defaults.default_roles || workspace_defaults.existing_roles,
    true
)
FROM workspace_defaults
WHERE workspaces.workspace_id = workspace_defaults.workspace_id;
