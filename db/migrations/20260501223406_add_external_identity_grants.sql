-- migrate:up
CREATE TABLE IF NOT EXISTS external_systems (
    system_id UUID PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',
    organization_id UUID NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    system_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    auth_kind TEXT NOT NULL,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    secret_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    operation_catalog JSONB NOT NULL DEFAULT '{}'::jsonb,
    webhook_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE external_systems
    DROP CONSTRAINT IF EXISTS external_systems_scope_check;

ALTER TABLE external_systems
    ADD CONSTRAINT external_systems_scope_check
    CHECK (
        (scope = 'global' AND organization_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL)
    );

ALTER TABLE external_systems
    DROP CONSTRAINT IF EXISTS external_systems_auth_kind_check;

ALTER TABLE external_systems
    ADD CONSTRAINT external_systems_auth_kind_check
    CHECK (auth_kind IN ('oauth2', 'oidc', 'api_key', 'bearer_token', 'client_credentials', 'custom'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_systems_scope_key
    ON external_systems(scope, COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid), system_key);

CREATE INDEX IF NOT EXISTS idx_external_systems_organization
    ON external_systems(scope, organization_id, enabled);

CREATE TABLE IF NOT EXISTS external_accounts (
    account_id UUID PRIMARY KEY,
    system_id UUID NOT NULL REFERENCES external_systems(system_id) ON DELETE CASCADE,
    owner_kind TEXT NOT NULL,
    user_id UUID NULL REFERENCES users(user_id) ON DELETE CASCADE,
    system_agent_id UUID NULL REFERENCES system_agents(agent_id) ON DELETE CASCADE,
    external_subject TEXT,
    display_name TEXT,
    scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    credential_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'active',
    expires_at TIMESTAMPTZ,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE external_accounts
    DROP CONSTRAINT IF EXISTS external_accounts_owner_check;

ALTER TABLE external_accounts
    ADD CONSTRAINT external_accounts_owner_check
    CHECK (
        (owner_kind = 'user' AND user_id IS NOT NULL AND system_agent_id IS NULL)
        OR (owner_kind = 'agent' AND system_agent_id IS NOT NULL AND user_id IS NULL)
    );

ALTER TABLE external_accounts
    DROP CONSTRAINT IF EXISTS external_accounts_status_check;

ALTER TABLE external_accounts
    ADD CONSTRAINT external_accounts_status_check
    CHECK (status IN ('active', 'disabled', 'revoked'));

CREATE INDEX IF NOT EXISTS idx_external_accounts_system_owner
    ON external_accounts(system_id, owner_kind, user_id, system_agent_id, status);

CREATE TABLE IF NOT EXISTS external_identity_grants (
    grant_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    participant_id UUID NOT NULL REFERENCES participants(participant_id) ON DELETE CASCADE,
    system_id UUID NOT NULL REFERENCES external_systems(system_id) ON DELETE CASCADE,
    account_id UUID NULL REFERENCES external_accounts(account_id) ON DELETE SET NULL,
    user_id UUID NULL REFERENCES users(user_id) ON DELETE CASCADE,
    system_agent_id UUID NULL REFERENCES system_agents(agent_id) ON DELETE CASCADE,
    allowed_scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    allowed_operations JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'active',
    expires_at TIMESTAMPTZ,
    created_by UUID NOT NULL,
    approved_by UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE external_identity_grants
    DROP CONSTRAINT IF EXISTS external_identity_grants_subject_check;

ALTER TABLE external_identity_grants
    ADD CONSTRAINT external_identity_grants_subject_check
    CHECK (
        (user_id IS NOT NULL AND system_agent_id IS NULL)
        OR (system_agent_id IS NOT NULL AND user_id IS NULL)
    );

ALTER TABLE external_identity_grants
    DROP CONSTRAINT IF EXISTS external_identity_grants_status_check;

ALTER TABLE external_identity_grants
    ADD CONSTRAINT external_identity_grants_status_check
    CHECK (status IN ('active', 'disabled', 'revoked', 'expired'));

CREATE INDEX IF NOT EXISTS idx_external_identity_grants_workspace_participant
    ON external_identity_grants(workspace_id, participant_id, status, expires_at);

CREATE INDEX IF NOT EXISTS idx_external_identity_grants_system
    ON external_identity_grants(system_id, workspace_id, status);

CREATE TABLE IF NOT EXISTS external_operation_requests (
    operation_request_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID NULL REFERENCES threads(thread_id) ON DELETE SET NULL,
    tool_call_id UUID NULL REFERENCES tool_calls(tool_call_id) ON DELETE SET NULL,
    system_id UUID NOT NULL REFERENCES external_systems(system_id) ON DELETE CASCADE,
    grant_id UUID NULL REFERENCES external_identity_grants(grant_id) ON DELETE SET NULL,
    participant_id UUID NOT NULL REFERENCES participants(participant_id) ON DELETE CASCADE,
    user_id UUID NULL REFERENCES users(user_id) ON DELETE SET NULL,
    system_agent_id UUID NULL REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    operation_key TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'direct',
    risk_level TEXT NOT NULL DEFAULT 'low',
    status TEXT NOT NULL DEFAULT 'pending_approval',
    requested_by UUID NOT NULL,
    approved_by UUID,
    rejected_by UUID,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    request_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE external_operation_requests
    DROP CONSTRAINT IF EXISTS external_operation_requests_risk_check;

ALTER TABLE external_operation_requests
    ADD CONSTRAINT external_operation_requests_risk_check
    CHECK (risk_level IN ('low', 'medium', 'high', 'destructive'));

ALTER TABLE external_operation_requests
    DROP CONSTRAINT IF EXISTS external_operation_requests_status_check;

ALTER TABLE external_operation_requests
    ADD CONSTRAINT external_operation_requests_status_check
    CHECK (status IN ('pending_approval', 'approved', 'rejected', 'completed', 'failed', 'cancelled'));

CREATE INDEX IF NOT EXISTS idx_external_operation_requests_workspace_status
    ON external_operation_requests(workspace_id, status, requested_at);

CREATE INDEX IF NOT EXISTS idx_external_operation_requests_tool_call
    ON external_operation_requests(tool_call_id)
    WHERE tool_call_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS external_webhook_endpoints (
    endpoint_id UUID PRIMARY KEY,
    system_id UUID NOT NULL REFERENCES external_systems(system_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    signing_secret_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'active',
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE external_webhook_endpoints
    DROP CONSTRAINT IF EXISTS external_webhook_endpoints_status_check;

ALTER TABLE external_webhook_endpoints
    ADD CONSTRAINT external_webhook_endpoints_status_check
    CHECK (status IN ('active', 'disabled', 'revoked'));

CREATE INDEX IF NOT EXISTS idx_external_webhook_endpoints_workspace
    ON external_webhook_endpoints(workspace_id, system_id, status);

CREATE TABLE IF NOT EXISTS external_event_inbox (
    event_id UUID PRIMARY KEY,
    endpoint_id UUID NOT NULL REFERENCES external_webhook_endpoints(endpoint_id) ON DELETE CASCADE,
    system_id UUID NOT NULL REFERENCES external_systems(system_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    external_event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'received',
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE external_event_inbox
    DROP CONSTRAINT IF EXISTS external_event_inbox_status_check;

ALTER TABLE external_event_inbox
    ADD CONSTRAINT external_event_inbox_status_check
    CHECK (status IN ('received', 'processed', 'ignored', 'failed'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_event_inbox_dedupe
    ON external_event_inbox(endpoint_id, external_event_id);

CREATE INDEX IF NOT EXISTS idx_external_event_inbox_workspace
    ON external_event_inbox(workspace_id, received_at);

-- migrate:down
DROP TABLE IF EXISTS external_event_inbox;
DROP TABLE IF EXISTS external_webhook_endpoints;
DROP TABLE IF EXISTS external_operation_requests;
DROP TABLE IF EXISTS external_identity_grants;
DROP TABLE IF EXISTS external_accounts;
DROP TABLE IF EXISTS external_systems;
