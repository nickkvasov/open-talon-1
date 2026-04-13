CREATE TABLE IF NOT EXISTS git_repositories (
    repo_id UUID PRIMARY KEY,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    name TEXT NOT NULL,
    forgejo_url TEXT,
    clone_url TEXT,
    local_path TEXT NOT NULL,
    default_branch TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_git_repositories_scope_workspace
    ON git_repositories(scope, workspace_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_git_repositories_scope_workspace_name
    ON git_repositories(scope, COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid), name);

CREATE TABLE IF NOT EXISTS workspace_assets (
    asset_id UUID PRIMARY KEY,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    logical_name TEXT NOT NULL,
    logical_path TEXT,
    title TEXT NOT NULL,
    description TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_workspace_assets_scope_workspace
    ON workspace_assets(scope, workspace_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_assets_scope_workspace_logical_name
    ON workspace_assets(scope, COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid), logical_name);

CREATE TABLE IF NOT EXISTS workspace_asset_versions (
    asset_version_id UUID PRIMARY KEY,
    asset_id UUID NOT NULL REFERENCES workspace_assets(asset_id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    source_kind TEXT NOT NULL,
    git_repository_id UUID REFERENCES git_repositories(repo_id) ON DELETE SET NULL,
    git_revision TEXT,
    git_path TEXT,
    storage_backend TEXT NOT NULL,
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    content_type TEXT,
    size_bytes BIGINT NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_asset_versions_asset_version
    ON workspace_asset_versions(asset_id, version);

CREATE INDEX IF NOT EXISTS idx_workspace_asset_versions_asset_created_at
    ON workspace_asset_versions(asset_id, created_at DESC);

CREATE TABLE IF NOT EXISTS asset_links (
    link_id UUID PRIMARY KEY,
    asset_id UUID NOT NULL REFERENCES workspace_assets(asset_id) ON DELETE CASCADE,
    asset_version_id UUID NOT NULL REFERENCES workspace_asset_versions(asset_version_id) ON DELETE CASCADE,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    target_type TEXT NOT NULL,
    target_id UUID NOT NULL,
    purpose TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_asset_links_target_lookup
    ON asset_links(target_type, target_id, purpose, workspace_id, active, updated_at DESC);
