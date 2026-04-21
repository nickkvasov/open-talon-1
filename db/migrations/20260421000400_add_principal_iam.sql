CREATE TABLE IF NOT EXISTS iam_role_definitions (
    role_id UUID PRIMARY KEY,
    scope TEXT NOT NULL,
    subject_kind TEXT NOT NULL,
    organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE iam_role_definitions
    DROP CONSTRAINT IF EXISTS iam_role_definitions_scope_check;

ALTER TABLE iam_role_definitions
    ADD CONSTRAINT iam_role_definitions_scope_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL)
    );

ALTER TABLE iam_role_definitions
    DROP CONSTRAINT IF EXISTS iam_role_definitions_subject_kind_check;

ALTER TABLE iam_role_definitions
    ADD CONSTRAINT iam_role_definitions_subject_kind_check
    CHECK (subject_kind IN ('human', 'agent'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_iam_role_definitions_unique_name
    ON iam_role_definitions(scope, subject_kind, COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid), name);

CREATE INDEX IF NOT EXISTS idx_iam_role_definitions_by_subject
    ON iam_role_definitions(subject_kind, scope, organization_id);

CREATE TABLE IF NOT EXISTS human_role_bindings (
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES iam_role_definitions(role_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_human_role_bindings_role
    ON human_role_bindings(role_id, user_id);

CREATE TABLE IF NOT EXISTS agent_identities (
    agent_identity_id UUID PRIMARY KEY,
    system_agent_id UUID NOT NULL REFERENCES system_agents(agent_id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE,
    provider_key TEXT NOT NULL,
    issuer TEXT NOT NULL,
    external_subject TEXT,
    client_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    secret_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_authenticated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE agent_identities
    DROP CONSTRAINT IF EXISTS agent_identities_scope_check;

ALTER TABLE agent_identities
    ADD CONSTRAINT agent_identities_scope_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL)
    );

ALTER TABLE agent_identities
    DROP CONSTRAINT IF EXISTS agent_identities_status_check;

ALTER TABLE agent_identities
    ADD CONSTRAINT agent_identities_status_check
    CHECK (status IN ('active', 'disabled'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_identities_provider_client
    ON agent_identities(provider_key, client_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_identities_provider_subject
    ON agent_identities(provider_key, issuer, external_subject)
    WHERE external_subject IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agent_identities_system_agent
    ON agent_identities(system_agent_id, scope, organization_id);

CREATE TABLE IF NOT EXISTS agent_role_bindings (
    agent_identity_id UUID NOT NULL REFERENCES agent_identities(agent_identity_id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES iam_role_definitions(role_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (agent_identity_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_role_bindings_role
    ON agent_role_bindings(role_id, agent_identity_id);

WITH role_source AS (
    SELECT
        workspace_id,
        CASE
            WHEN jsonb_typeof(metadata->'role_definitions') = 'object' THEN metadata->'role_definitions'
            WHEN jsonb_typeof(metadata->'role_definitions') = 'array' THEN COALESCE(
                (
                    SELECT jsonb_object_agg(item->>'name', item)
                    FROM jsonb_array_elements(metadata->'role_definitions') AS item
                    WHERE item ? 'name'
                ),
                '{}'::jsonb
            )
            ELSE '{}'::jsonb
        END AS role_definitions
    FROM workspaces
),
role_backfill AS (
    SELECT
        workspace_id,
        COALESCE(
            jsonb_object_agg(
                role_name,
                jsonb_set(
                    role_value,
                    '{permissions}',
                    CASE
                        WHEN role_value ? 'permissions' THEN role_value->'permissions'
                        WHEN role_name IN ('admin', 'supervisor') THEN to_jsonb(ARRAY[
                            'workspace.roles.write',
                            'workspace.agents.write',
                            'workspace.tools.write',
                            'workspace.repositories.write',
                            'workspace.assets.publish',
                            'workspace.assets.link',
                            'workspace.audit.read',
                            'workspace.audit.export',
                            'workspace.audit.verify'
                        ]::text[])
                        ELSE '[]'::jsonb
                    END,
                    true
                )
            ),
            '{}'::jsonb
        )
        AS patched_role_definitions
    FROM role_source
    CROSS JOIN LATERAL jsonb_each(role_definitions) AS entry(role_name, role_value)
    GROUP BY workspace_id
)
UPDATE workspaces AS workspace
SET metadata = jsonb_set(
    COALESCE(workspace.metadata, '{}'::jsonb),
    '{role_definitions}',
    role_backfill.patched_role_definitions,
    true
)
FROM role_backfill
WHERE workspace.workspace_id = role_backfill.workspace_id;
