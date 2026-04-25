ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS creator_user_id UUID,
    ADD COLUMN IF NOT EXISTS creator_system_agent_id UUID,
    ADD COLUMN IF NOT EXISTS owner_user_id UUID,
    ADD COLUMN IF NOT EXISTS owner_system_agent_id UUID;

UPDATE projects AS project
SET
    creator_user_id = COALESCE(project.creator_user_id, project.created_by),
    owner_user_id = COALESCE(project.owner_user_id, project.created_by)
WHERE project.creator_user_id IS NULL
  AND project.creator_system_agent_id IS NULL
  AND project.owner_user_id IS NULL
  AND project.owner_system_agent_id IS NULL;

ALTER TABLE projects
    DROP CONSTRAINT IF EXISTS projects_creator_subject_check;

ALTER TABLE projects
    ADD CONSTRAINT projects_creator_subject_check
    CHECK (
        (
            creator_user_id IS NOT NULL
            AND creator_system_agent_id IS NULL
        )
        OR (
            creator_user_id IS NULL
            AND creator_system_agent_id IS NOT NULL
        )
    );

ALTER TABLE projects
    DROP CONSTRAINT IF EXISTS projects_owner_subject_check;

ALTER TABLE projects
    ADD CONSTRAINT projects_owner_subject_check
    CHECK (
        (
            owner_user_id IS NOT NULL
            AND owner_system_agent_id IS NULL
        )
        OR (
            owner_user_id IS NULL
            AND owner_system_agent_id IS NOT NULL
        )
    );

CREATE TABLE IF NOT EXISTS project_access_bindings (
    project_id UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    subject_type TEXT NOT NULL,
    user_id UUID,
    system_agent_id UUID,
    role TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT project_access_subject_type_check
        CHECK (subject_type IN ('user', 'agent')),
    CONSTRAINT project_access_role_check
        CHECK (role IN ('owner', 'editor', 'viewer')),
    CONSTRAINT project_access_subject_check
        CHECK (
            (
                subject_type = 'user'
                AND user_id IS NOT NULL
                AND system_agent_id IS NULL
            )
            OR (
                subject_type = 'agent'
                AND system_agent_id IS NOT NULL
                AND user_id IS NULL
            )
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_access_project_user
    ON project_access_bindings(project_id, user_id)
    WHERE subject_type = 'user';

CREATE UNIQUE INDEX IF NOT EXISTS idx_project_access_project_agent
    ON project_access_bindings(project_id, system_agent_id)
    WHERE subject_type = 'agent';

CREATE INDEX IF NOT EXISTS idx_project_access_user_project
    ON project_access_bindings(user_id, project_id)
    WHERE subject_type = 'user';

CREATE INDEX IF NOT EXISTS idx_project_access_agent_project
    ON project_access_bindings(system_agent_id, project_id)
    WHERE subject_type = 'agent';

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
    owner_user_id,
    NULL::uuid,
    'owner',
    created_at,
    NOW(),
    '{"backfilled": true, "source": "project_owner"}'::jsonb
FROM projects
WHERE owner_user_id IS NOT NULL
ON CONFLICT DO NOTHING;

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
SELECT DISTINCT
    workspace.project_id,
    'user',
    participant.user_id,
    NULL::uuid,
    'viewer',
    LEAST(workspace.created_at, participant.created_at),
    NOW(),
    '{"backfilled": true, "source": "workspace_participant"}'::jsonb
FROM workspaces AS workspace
JOIN participants AS participant
  ON participant.workspace_id = workspace.workspace_id
WHERE participant.participant_type = 'user'
  AND participant.user_id IS NOT NULL
ON CONFLICT DO NOTHING;

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
    owner_system_agent_id,
    'owner',
    created_at,
    NOW(),
    '{"backfilled": true, "source": "project_owner"}'::jsonb
FROM projects
WHERE owner_system_agent_id IS NOT NULL
ON CONFLICT DO NOTHING;

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
SELECT DISTINCT
    workspace.project_id,
    'agent',
    NULL::uuid,
    participant.system_agent_id,
    'viewer',
    LEAST(workspace.created_at, participant.created_at),
    NOW(),
    '{"backfilled": true, "source": "workspace_participant"}'::jsonb
FROM workspaces AS workspace
JOIN participants AS participant
  ON participant.workspace_id = workspace.workspace_id
WHERE participant.participant_type = 'agent'
  AND participant.system_agent_id IS NOT NULL
ON CONFLICT DO NOTHING;
