ALTER TABLE system_agents
    ADD COLUMN IF NOT EXISTS agent_key TEXT,
    ADD COLUMN IF NOT EXISTS active_agent_version_id UUID;

UPDATE system_agents
SET agent_key = COALESCE(
    agent_key,
    CASE
        WHEN metadata ? 'agent_key' THEN NULLIF(metadata->>'agent_key', '')
        ELSE NULL
    END
)
WHERE agent_key IS NULL;

CREATE TABLE IF NOT EXISTS agent_definition_versions (
    agent_version_id UUID PRIMARY KEY,
    agent_id UUID NOT NULL REFERENCES system_agents(agent_id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    scope TEXT NOT NULL,
    organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE,
    agent_key TEXT NOT NULL,
    git_repository_id UUID REFERENCES git_repositories(repo_id) ON DELETE SET NULL,
    git_commit_sha TEXT NOT NULL,
    bundle_path TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    compiled_definition JSONB NOT NULL DEFAULT '{}'::jsonb,
    prompt_asset_id UUID REFERENCES workspace_assets(asset_id) ON DELETE SET NULL,
    prompt_asset_version_id UUID REFERENCES workspace_asset_versions(asset_version_id) ON DELETE SET NULL,
    skill_asset_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    published_by UUID NOT NULL,
    published_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE agent_definition_versions
    DROP CONSTRAINT IF EXISTS agent_definition_versions_scope_organization_check;

ALTER TABLE agent_definition_versions
    ADD CONSTRAINT agent_definition_versions_scope_organization_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL)
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_system_agents_scope_org_agent_key_unique
    ON system_agents(
        scope,
        COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        agent_key
    )
    WHERE agent_key IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_definition_versions_agent_version
    ON agent_definition_versions(agent_id, version);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_definition_versions_agent_commit_bundle
    ON agent_definition_versions(agent_id, git_repository_id, git_commit_sha, bundle_path);

CREATE INDEX IF NOT EXISTS idx_agent_definition_versions_scope_agent_key
    ON agent_definition_versions(scope, organization_id, agent_key, published_at DESC);

ALTER TABLE system_agents
    DROP CONSTRAINT IF EXISTS system_agents_active_agent_version_fk;

ALTER TABLE system_agents
    ADD CONSTRAINT system_agents_active_agent_version_fk
    FOREIGN KEY (active_agent_version_id)
    REFERENCES agent_definition_versions(agent_version_id)
    ON DELETE SET NULL
    DEFERRABLE INITIALLY DEFERRED;
