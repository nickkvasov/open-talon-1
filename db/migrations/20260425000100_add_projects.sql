CREATE TABLE IF NOT EXISTS projects (
    project_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT projects_organization_slug_key UNIQUE (organization_id, slug)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_project_organization
    ON projects(project_id, organization_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_organization_slug
    ON projects(organization_id, slug);

CREATE INDEX IF NOT EXISTS idx_projects_organization_created_at
    ON projects(organization_id, created_at ASC);

ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS project_id UUID;

WITH workspace_rollup AS (
    SELECT
        organization_id,
        MIN(created_at) AS first_workspace_created_at,
        (ARRAY_AGG(owner_user_id ORDER BY created_at ASC, workspace_id ASC) FILTER (WHERE owner_user_id IS NOT NULL))[1] AS owner_user_id
    FROM workspaces
    GROUP BY organization_id
),
organization_defaults AS (
    SELECT
        organization.organization_id,
        (
            SUBSTRING(MD5('open-talon-default-project:' || organization.organization_id::text), 1, 8)
            || '-'
            || SUBSTRING(MD5('open-talon-default-project:' || organization.organization_id::text), 9, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-default-project:' || organization.organization_id::text), 13, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-default-project:' || organization.organization_id::text), 17, 4)
            || '-'
            || SUBSTRING(MD5('open-talon-default-project:' || organization.organization_id::text), 21, 12)
        )::uuid AS project_id,
        COALESCE(workspace_rollup.owner_user_id, organization.created_by) AS created_by,
        COALESCE(workspace_rollup.first_workspace_created_at, organization.created_at) AS created_at
    FROM organizations AS organization
    LEFT JOIN workspace_rollup
      ON workspace_rollup.organization_id = organization.organization_id
)
INSERT INTO projects (
    project_id,
    organization_id,
    slug,
    name,
    description,
    created_by,
    created_at,
    updated_at,
    metadata
)
SELECT
    project_id,
    organization_id,
    'default',
    'Default Project',
    'Backfilled default project for legacy workspaces.',
    created_by,
    created_at,
    NOW(),
    '{"seeded": true, "managed": true}'::jsonb
FROM organization_defaults
ON CONFLICT (organization_id, slug) DO NOTHING;

UPDATE workspaces AS workspace
SET project_id = project.project_id
FROM projects AS project
WHERE workspace.project_id IS NULL
  AND project.organization_id = workspace.organization_id
  AND project.slug = 'default';

ALTER TABLE workspaces
    ALTER COLUMN project_id SET NOT NULL;

ALTER TABLE workspaces
    DROP CONSTRAINT IF EXISTS workspaces_project_organization_fkey;

ALTER TABLE workspaces
    ADD CONSTRAINT workspaces_project_organization_fkey
    FOREIGN KEY (project_id, organization_id)
    REFERENCES projects(project_id, organization_id)
    ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_workspaces_project_created_at
    ON workspaces(project_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_workspaces_organization_project_created_at
    ON workspaces(organization_id, project_id, created_at ASC);
