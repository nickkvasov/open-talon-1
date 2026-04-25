ALTER TABLE project_access_bindings
    DROP CONSTRAINT IF EXISTS project_access_role_check;

UPDATE project_access_bindings
SET role = 'creator',
    updated_at = NOW(),
    metadata = metadata || '{"renamed_from": "admin"}'::jsonb
WHERE role = 'admin';

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
    'user',
    creator_user_id,
    NULL::uuid,
    'creator',
    created_at,
    NOW(),
    '{"backfilled": true, "source": "project_creator"}'::jsonb
FROM projects
WHERE creator_user_id IS NOT NULL
ON CONFLICT (project_id, user_id) WHERE subject_type = 'user' DO UPDATE
    SET role = 'creator',
        updated_at = EXCLUDED.updated_at,
        metadata = project_access_bindings.metadata || EXCLUDED.metadata;

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
    creator_system_agent_id,
    'creator',
    created_at,
    NOW(),
    '{"backfilled": true, "source": "project_creator"}'::jsonb
FROM projects
WHERE creator_system_agent_id IS NOT NULL
ON CONFLICT (project_id, system_agent_id) WHERE subject_type = 'agent' DO UPDATE
    SET role = 'creator',
        updated_at = EXCLUDED.updated_at,
        metadata = project_access_bindings.metadata || EXCLUDED.metadata;

ALTER TABLE project_access_bindings
    ADD CONSTRAINT project_access_role_check
    CHECK (role IN ('creator', 'owner', 'editor', 'viewer'));
