CREATE TABLE IF NOT EXISTS organizations (
    organization_id UUID PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_organizations_slug
    ON organizations(slug);

CREATE TABLE IF NOT EXISTS organization_memberships (
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    joined_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (organization_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_organization_memberships_user
    ON organization_memberships(user_id, organization_id);

ALTER TABLE workspaces
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE;

ALTER TABLE system_agents
    ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'global',
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE;

ALTER TABLE system_tools
    ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'global',
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE;

ALTER TABLE llm_providers
    ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'global',
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE;

ALTER TABLE memory_providers
    ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'global',
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE;

ALTER TABLE git_repositories
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE;

ALTER TABLE workspace_assets
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE;

ALTER TABLE asset_links
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE;

ALTER TABLE audit_event_ledger
    ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE;

WITH default_creator AS (
    SELECT COALESCE(
        (
            SELECT owner_user_id
            FROM workspaces
            WHERE owner_user_id IS NOT NULL
            ORDER BY created_at ASC, workspace_id ASC
            LIMIT 1
        ),
        (
            SELECT user_id
            FROM participants
            WHERE user_id IS NOT NULL
            ORDER BY created_at ASC, participant_id ASC
            LIMIT 1
        ),
        '00000000-0000-0000-0000-000000000000'::uuid
    ) AS user_id
)
INSERT INTO organizations (
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
    '11111111-1111-1111-1111-111111111111'::uuid,
    'default',
    'Default Organization',
    'Backfilled default organization for legacy workspaces.',
    default_creator.user_id,
    NOW(),
    NOW(),
    '{"seeded": true, "managed": true}'::jsonb
FROM default_creator
ON CONFLICT (organization_id) DO NOTHING;

UPDATE workspaces
SET organization_id = '11111111-1111-1111-1111-111111111111'::uuid
WHERE organization_id IS NULL;

WITH membership_sources AS (
    SELECT
        w.organization_id,
        p.user_id,
        p.created_at AS joined_at,
        CASE WHEN p.roles @> '["admin"]'::jsonb THEN 1 ELSE 0 END AS is_admin,
        0 AS is_owner
    FROM participants AS p
    JOIN workspaces AS w ON w.workspace_id = p.workspace_id
    WHERE p.user_id IS NOT NULL

    UNION ALL

    SELECT
        w.organization_id,
        w.owner_user_id AS user_id,
        w.created_at AS joined_at,
        1 AS is_admin,
        1 AS is_owner
    FROM workspaces AS w
    WHERE w.owner_user_id IS NOT NULL
),
membership_rollup AS (
    SELECT
        organization_id,
        user_id,
        MIN(joined_at) AS joined_at,
        MAX(is_admin) AS is_admin,
        MAX(is_owner) AS is_owner
    FROM membership_sources
    GROUP BY organization_id, user_id
),
membership_owner AS (
    SELECT organization_id, user_id
    FROM (
        SELECT
            organization_id,
            user_id,
            ROW_NUMBER() OVER (
                PARTITION BY organization_id
                ORDER BY is_owner DESC, joined_at ASC, user_id ASC
            ) AS row_number
        FROM membership_rollup
        WHERE is_admin = 1 OR is_owner = 1
    ) ranked
    WHERE row_number = 1
)
INSERT INTO organization_memberships (
    organization_id,
    user_id,
    role,
    joined_at,
    updated_at,
    metadata
)
SELECT
    rollup.organization_id,
    rollup.user_id,
    CASE
        WHEN owner.user_id IS NOT NULL THEN 'owner'
        WHEN rollup.is_admin = 1 OR rollup.is_owner = 1 THEN 'admin'
        ELSE 'member'
    END AS role,
    rollup.joined_at,
    NOW(),
    '{}'::jsonb
FROM membership_rollup AS rollup
LEFT JOIN membership_owner AS owner
    ON owner.organization_id = rollup.organization_id
   AND owner.user_id = rollup.user_id
ON CONFLICT (organization_id, user_id) DO UPDATE
SET role = EXCLUDED.role,
    updated_at = EXCLUDED.updated_at,
    metadata = organization_memberships.metadata || EXCLUDED.metadata;

UPDATE git_repositories AS repository
SET organization_id = workspace.organization_id
FROM workspaces AS workspace
WHERE repository.workspace_id = workspace.workspace_id
  AND repository.organization_id IS NULL;

UPDATE workspace_assets AS asset
SET organization_id = workspace.organization_id
FROM workspaces AS workspace
WHERE asset.workspace_id = workspace.workspace_id
  AND asset.organization_id IS NULL;

UPDATE asset_links AS link
SET organization_id = workspace.organization_id
FROM workspaces AS workspace
WHERE link.workspace_id = workspace.workspace_id
  AND link.organization_id IS NULL;

UPDATE audit_event_ledger AS ledger
SET organization_id = workspace.organization_id
FROM workspaces AS workspace
WHERE ledger.workspace_id = workspace.workspace_id
  AND ledger.organization_id IS NULL;

ALTER TABLE workspaces
    ALTER COLUMN organization_id SET NOT NULL;

ALTER TABLE system_agents
    DROP CONSTRAINT IF EXISTS system_agents_scope_organization_check;

ALTER TABLE system_agents
    ADD CONSTRAINT system_agents_scope_organization_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL)
    );

ALTER TABLE system_tools
    DROP CONSTRAINT IF EXISTS system_tools_scope_organization_check;

ALTER TABLE system_tools
    ADD CONSTRAINT system_tools_scope_organization_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL)
    );

ALTER TABLE llm_providers
    DROP CONSTRAINT IF EXISTS llm_providers_scope_organization_check;

ALTER TABLE llm_providers
    ADD CONSTRAINT llm_providers_scope_organization_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL)
    );

ALTER TABLE memory_providers
    DROP CONSTRAINT IF EXISTS memory_providers_scope_organization_check;

ALTER TABLE memory_providers
    ADD CONSTRAINT memory_providers_scope_organization_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL)
    );

ALTER TABLE git_repositories
    DROP CONSTRAINT IF EXISTS git_repositories_scope_organization_check;

ALTER TABLE git_repositories
    ADD CONSTRAINT git_repositories_scope_organization_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND workspace_id IS NOT NULL)
    );

ALTER TABLE workspace_assets
    DROP CONSTRAINT IF EXISTS workspace_assets_scope_organization_check;

ALTER TABLE workspace_assets
    ADD CONSTRAINT workspace_assets_scope_organization_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND workspace_id IS NOT NULL)
    );

ALTER TABLE asset_links
    DROP CONSTRAINT IF EXISTS asset_links_scope_organization_check;

ALTER TABLE asset_links
    ADD CONSTRAINT asset_links_scope_organization_check
    CHECK (
        (workspace_id IS NULL)
        OR (workspace_id IS NOT NULL AND organization_id IS NOT NULL)
    );

ALTER TABLE organization_memberships
    DROP CONSTRAINT IF EXISTS organization_memberships_role_check;

ALTER TABLE organization_memberships
    ADD CONSTRAINT organization_memberships_role_check
    CHECK (role IN ('owner', 'admin', 'member'));

ALTER TABLE system_tools
    DROP CONSTRAINT IF EXISTS system_tools_name_key;

DROP INDEX IF EXISTS idx_system_tools_name;
CREATE INDEX IF NOT EXISTS idx_system_tools_name
    ON system_tools(name);

ALTER TABLE llm_providers
    DROP CONSTRAINT IF EXISTS llm_providers_engine_id_key;

DROP INDEX IF EXISTS idx_llm_providers_engine_id;
CREATE INDEX IF NOT EXISTS idx_llm_providers_engine_id
    ON llm_providers(engine_id);

ALTER TABLE memory_providers
    DROP CONSTRAINT IF EXISTS memory_providers_provider_key_key;

DROP INDEX IF EXISTS idx_git_repositories_scope_workspace_name;
DROP INDEX IF EXISTS idx_workspace_assets_scope_workspace_logical_name;

CREATE INDEX IF NOT EXISTS idx_workspaces_organization_created_at
    ON workspaces(organization_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_system_agents_scope_organization_created_at
    ON system_agents(scope, organization_id, created_at ASC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_system_tools_scope_organization_name_unique
    ON system_tools(scope, COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid), name);

CREATE INDEX IF NOT EXISTS idx_system_tools_scope_organization_name
    ON system_tools(scope, organization_id, name);

CREATE UNIQUE INDEX IF NOT EXISTS idx_llm_providers_scope_organization_engine_unique
    ON llm_providers(scope, COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid), engine_id);

CREATE INDEX IF NOT EXISTS idx_llm_providers_scope_organization_engine
    ON llm_providers(scope, organization_id, engine_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_providers_scope_organization_key_unique
    ON memory_providers(scope, COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid), provider_key);

CREATE INDEX IF NOT EXISTS idx_memory_providers_scope_organization_key
    ON memory_providers(scope, organization_id, provider_key);

CREATE UNIQUE INDEX IF NOT EXISTS idx_git_repositories_scope_organization_workspace_name
    ON git_repositories(
        scope,
        COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
        name
    );

CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_assets_scope_organization_workspace_logical_name
    ON workspace_assets(
        scope,
        COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
        logical_name
    );

CREATE INDEX IF NOT EXISTS idx_git_repositories_scope_organization_workspace
    ON git_repositories(scope, organization_id, workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_workspace_assets_scope_organization_workspace
    ON workspace_assets(scope, organization_id, workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_asset_links_organization_workspace_target
    ON asset_links(organization_id, workspace_id, target_type, target_id, purpose, active, updated_at DESC);

CREATE INDEX IF NOT EXISTS audit_event_ledger_organization_recorded_at_idx
    ON audit_event_ledger (organization_id, recorded_at DESC);
