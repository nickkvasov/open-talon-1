CREATE TABLE IF NOT EXISTS mcp_servers (
    server_id UUID PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',
    organization_id UUID NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    server_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    transport_kind TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    secret_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    trust_level TEXT NOT NULL DEFAULT 'sandboxed',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_sync_status TEXT,
    last_sync_error TEXT,
    last_synced_at TIMESTAMPTZ,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE mcp_servers
    DROP CONSTRAINT IF EXISTS mcp_servers_scope_organization_check;

ALTER TABLE mcp_servers
    ADD CONSTRAINT mcp_servers_scope_organization_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL)
    );

ALTER TABLE mcp_servers
    DROP CONSTRAINT IF EXISTS mcp_servers_transport_kind_check;

ALTER TABLE mcp_servers
    ADD CONSTRAINT mcp_servers_transport_kind_check
    CHECK (transport_kind IN ('stdio', 'streamable_http', 'sse'));

ALTER TABLE mcp_servers
    DROP CONSTRAINT IF EXISTS mcp_servers_trust_level_check;

ALTER TABLE mcp_servers
    ADD CONSTRAINT mcp_servers_trust_level_check
    CHECK (trust_level IN ('sandboxed', 'trusted'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_mcp_servers_scope_organization_key_unique
    ON mcp_servers(scope, COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid), server_key);

CREATE INDEX IF NOT EXISTS idx_mcp_servers_scope_organization_key
    ON mcp_servers(scope, organization_id, server_key);

CREATE TABLE IF NOT EXISTS mcp_server_tools (
    server_id UUID NOT NULL REFERENCES mcp_servers(server_id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    display_name TEXT,
    description TEXT NOT NULL DEFAULT '',
    input_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    capability_hash TEXT NOT NULL DEFAULT '',
    discovered_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (server_id, tool_name)
);

CREATE TABLE IF NOT EXISTS mcp_server_resources (
    server_id UUID NOT NULL REFERENCES mcp_servers(server_id) ON DELETE CASCADE,
    uri TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    mime_type TEXT,
    capability_hash TEXT NOT NULL DEFAULT '',
    discovered_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (server_id, uri)
);

CREATE TABLE IF NOT EXISTS mcp_server_prompts (
    server_id UUID NOT NULL REFERENCES mcp_servers(server_id) ON DELETE CASCADE,
    prompt_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    arguments_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    capability_hash TEXT NOT NULL DEFAULT '',
    discovered_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (server_id, prompt_name)
);

CREATE TABLE IF NOT EXISTS workspace_mcp_servers (
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    server_id UUID NOT NULL REFERENCES mcp_servers(server_id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    tools_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    resources_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    prompts_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    sampling_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    name_prefix TEXT NOT NULL DEFAULT '',
    tool_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
    tool_denylist JSONB NOT NULL DEFAULT '[]'::jsonb,
    resource_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
    prompt_allowlist JSONB NOT NULL DEFAULT '[]'::jsonb,
    attached_by UUID NOT NULL,
    attached_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (workspace_id, server_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_mcp_servers_workspace
    ON workspace_mcp_servers(workspace_id, attached_at);

CREATE TABLE IF NOT EXISTS mcp_server_sync_jobs (
    job_id UUID PRIMARY KEY,
    server_id UUID NOT NULL REFERENCES mcp_servers(server_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'created',
    requested_by UUID NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    claimed_by_worker TEXT,
    lease_expires_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    result JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_mcp_server_sync_jobs_status_requested
    ON mcp_server_sync_jobs(status, requested_at, created_at);

ALTER TABLE tool_calls
    ALTER COLUMN tool_id DROP NOT NULL;
