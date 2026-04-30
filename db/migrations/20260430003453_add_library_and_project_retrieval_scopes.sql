-- migrate:up
ALTER TABLE workspace_assets
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE;

UPDATE workspace_assets AS asset
SET
    organization_id = COALESCE(asset.organization_id, workspace.organization_id),
    project_id = COALESCE(asset.project_id, workspace.project_id)
FROM workspaces AS workspace
WHERE asset.workspace_id = workspace.workspace_id;

ALTER TABLE retrieval_profiles
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE;

ALTER TABLE retrieval_corpora
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE;

ALTER TABLE retrieval_sources
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE;

ALTER TABLE retrieval_ingestion_jobs
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE;

ALTER TABLE retrieval_chunks
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE;

ALTER TABLE retrieval_runs
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE;

ALTER TABLE retrieval_context_packs
    ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE;

UPDATE retrieval_profiles AS profile
SET project_id = COALESCE(profile.project_id, workspace.project_id)
FROM workspaces AS workspace
WHERE profile.workspace_id = workspace.workspace_id;

UPDATE retrieval_corpora AS corpus
SET project_id = COALESCE(corpus.project_id, workspace.project_id)
FROM workspaces AS workspace
WHERE corpus.workspace_id = workspace.workspace_id;

UPDATE retrieval_sources AS source
SET project_id = COALESCE(source.project_id, workspace.project_id)
FROM workspaces AS workspace
WHERE source.workspace_id = workspace.workspace_id;

UPDATE retrieval_ingestion_jobs AS job
SET project_id = COALESCE(job.project_id, workspace.project_id)
FROM workspaces AS workspace
WHERE job.workspace_id = workspace.workspace_id;

UPDATE retrieval_chunks AS chunk
SET project_id = COALESCE(chunk.project_id, workspace.project_id)
FROM workspaces AS workspace
WHERE chunk.workspace_id = workspace.workspace_id;

UPDATE retrieval_runs AS run
SET project_id = COALESCE(run.project_id, workspace.project_id)
FROM workspaces AS workspace
WHERE run.workspace_id = workspace.workspace_id;

UPDATE retrieval_context_packs AS context_pack
SET project_id = COALESCE(context_pack.project_id, workspace.project_id)
FROM workspaces AS workspace
WHERE context_pack.workspace_id = workspace.workspace_id;

ALTER TABLE workspace_assets
    DROP CONSTRAINT IF EXISTS workspace_assets_scope_organization_check;

ALTER TABLE workspace_assets
    ADD CONSTRAINT workspace_assets_scope_organization_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'project' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NOT NULL)
    );

ALTER TABLE retrieval_profiles
    DROP CONSTRAINT IF EXISTS retrieval_profiles_scope_check;

ALTER TABLE retrieval_profiles
    ADD CONSTRAINT retrieval_profiles_scope_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'project' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NOT NULL)
    );

ALTER TABLE retrieval_corpora
    DROP CONSTRAINT IF EXISTS retrieval_corpora_scope_check;

ALTER TABLE retrieval_corpora
    ADD CONSTRAINT retrieval_corpora_scope_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'project' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NOT NULL)
    );

ALTER TABLE retrieval_sources
    DROP CONSTRAINT IF EXISTS retrieval_sources_scope_check;

ALTER TABLE retrieval_sources
    ADD CONSTRAINT retrieval_sources_scope_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'project' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NOT NULL)
    );

ALTER TABLE retrieval_ingestion_jobs
    DROP CONSTRAINT IF EXISTS retrieval_ingestion_jobs_scope_check;

ALTER TABLE retrieval_ingestion_jobs
    ADD CONSTRAINT retrieval_ingestion_jobs_scope_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'project' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NOT NULL)
    );

ALTER TABLE retrieval_chunks
    DROP CONSTRAINT IF EXISTS retrieval_chunks_scope_check;

ALTER TABLE retrieval_chunks
    ADD CONSTRAINT retrieval_chunks_scope_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'project' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NOT NULL)
    );

ALTER TABLE retrieval_runs
    DROP CONSTRAINT IF EXISTS retrieval_runs_scope_check;

ALTER TABLE retrieval_runs
    ADD CONSTRAINT retrieval_runs_scope_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'project' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NOT NULL)
    );

ALTER TABLE retrieval_context_packs
    DROP CONSTRAINT IF EXISTS retrieval_context_packs_scope_check;

ALTER TABLE retrieval_context_packs
    ADD CONSTRAINT retrieval_context_packs_scope_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'project' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NOT NULL)
    );

DROP INDEX IF EXISTS idx_workspace_assets_scope_organization_workspace_logical_name;
DROP INDEX IF EXISTS idx_workspace_assets_scope_organization_workspace;
DROP INDEX IF EXISTS idx_retrieval_profiles_scope_name;
DROP INDEX IF EXISTS idx_retrieval_corpora_scope_name;
DROP INDEX IF EXISTS idx_retrieval_corpora_scope;
DROP INDEX IF EXISTS idx_retrieval_runs_scope_created_at;
DROP INDEX IF EXISTS idx_retrieval_context_packs_scope_created_at;

CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_assets_scope_owner_logical_name
    ON workspace_assets(
        scope,
        COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
        logical_name
    );

CREATE INDEX IF NOT EXISTS idx_workspace_assets_scope_owner
    ON workspace_assets(scope, organization_id, project_id, workspace_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_retrieval_profiles_scope_name
    ON retrieval_profiles (
        scope,
        COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
        name
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_retrieval_corpora_scope_name
    ON retrieval_corpora (
        scope,
        COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
        name
    );

CREATE INDEX IF NOT EXISTS idx_retrieval_corpora_scope
    ON retrieval_corpora(scope, organization_id, project_id, workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_retrieval_runs_scope_created_at
    ON retrieval_runs(scope, organization_id, project_id, workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_retrieval_context_packs_scope_created_at
    ON retrieval_context_packs(scope, organization_id, project_id, workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS libraries (
    library_id UUID PRIMARY KEY,
    scope TEXT NOT NULL,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(project_id) ON DELETE CASCADE,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT libraries_scope_check CHECK (
        (scope = 'organization' AND organization_id IS NOT NULL AND project_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'project' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND project_id IS NOT NULL AND workspace_id IS NOT NULL)
    ),
    CONSTRAINT libraries_status_check CHECK (status IN ('active', 'archived'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_libraries_scope_owner_slug
    ON libraries(
        scope,
        organization_id,
        COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
        slug
    );

CREATE INDEX IF NOT EXISTS idx_libraries_scope_owner
    ON libraries(scope, organization_id, project_id, workspace_id, created_at ASC);

CREATE TABLE IF NOT EXISTS library_items (
    item_id UUID PRIMARY KEY,
    library_id UUID NOT NULL REFERENCES libraries(library_id) ON DELETE CASCADE,
    asset_id UUID NOT NULL REFERENCES workspace_assets(asset_id) ON DELETE CASCADE,
    active_asset_version_id UUID REFERENCES workspace_asset_versions(asset_version_id) ON DELETE SET NULL,
    item_kind TEXT NOT NULL,
    title TEXT NOT NULL,
    source_uri TEXT,
    content_type TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT library_items_kind_check CHECK (item_kind IN ('file', 'text', 'webpage', 'image', 'diagram', 'other')),
    CONSTRAINT library_items_status_check CHECK (status IN ('active', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_library_items_library_created_at
    ON library_items(library_id, created_at ASC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_library_items_library_asset
    ON library_items(library_id, asset_id);

CREATE TABLE IF NOT EXISTS library_workspace_attachments (
    attachment_id UUID PRIMARY KEY,
    library_id UUID NOT NULL REFERENCES libraries(library_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    attached_by UUID NOT NULL,
    attached_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_library_workspace_attachments_workspace_library
    ON library_workspace_attachments(workspace_id, library_id);

CREATE INDEX IF NOT EXISTS idx_library_workspace_attachments_workspace
    ON library_workspace_attachments(workspace_id, enabled, attached_at ASC);

-- migrate:down
DROP TABLE IF EXISTS library_workspace_attachments;
DROP TABLE IF EXISTS library_items;
DROP TABLE IF EXISTS libraries;

DROP INDEX IF EXISTS idx_retrieval_context_packs_scope_created_at;
DROP INDEX IF EXISTS idx_retrieval_runs_scope_created_at;
DROP INDEX IF EXISTS idx_retrieval_corpora_scope;
DROP INDEX IF EXISTS idx_retrieval_corpora_scope_name;
DROP INDEX IF EXISTS idx_retrieval_profiles_scope_name;
DROP INDEX IF EXISTS idx_workspace_assets_scope_owner;
DROP INDEX IF EXISTS idx_workspace_assets_scope_owner_logical_name;

ALTER TABLE retrieval_context_packs
    DROP CONSTRAINT IF EXISTS retrieval_context_packs_scope_check;
ALTER TABLE retrieval_runs
    DROP CONSTRAINT IF EXISTS retrieval_runs_scope_check;
ALTER TABLE retrieval_chunks
    DROP CONSTRAINT IF EXISTS retrieval_chunks_scope_check;
ALTER TABLE retrieval_ingestion_jobs
    DROP CONSTRAINT IF EXISTS retrieval_ingestion_jobs_scope_check;
ALTER TABLE retrieval_sources
    DROP CONSTRAINT IF EXISTS retrieval_sources_scope_check;
ALTER TABLE retrieval_corpora
    DROP CONSTRAINT IF EXISTS retrieval_corpora_scope_check;
ALTER TABLE retrieval_profiles
    DROP CONSTRAINT IF EXISTS retrieval_profiles_scope_check;
ALTER TABLE workspace_assets
    DROP CONSTRAINT IF EXISTS workspace_assets_scope_organization_check;

ALTER TABLE retrieval_context_packs DROP COLUMN IF EXISTS project_id;
ALTER TABLE retrieval_runs DROP COLUMN IF EXISTS project_id;
ALTER TABLE retrieval_chunks DROP COLUMN IF EXISTS project_id;
ALTER TABLE retrieval_ingestion_jobs DROP COLUMN IF EXISTS project_id;
ALTER TABLE retrieval_sources DROP COLUMN IF EXISTS project_id;
ALTER TABLE retrieval_corpora DROP COLUMN IF EXISTS project_id;
ALTER TABLE retrieval_profiles DROP COLUMN IF EXISTS project_id;
ALTER TABLE workspace_assets DROP COLUMN IF EXISTS project_id;
