CREATE TABLE IF NOT EXISTS tool_generation_requests (
    request_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    requester_participant_id UUID NOT NULL REFERENCES participants(participant_id) ON DELETE RESTRICT,
    requester_message_id UUID NULL REFERENCES timeline_messages(message_id) ON DELETE SET NULL,
    target_system_agent_id UUID NOT NULL REFERENCES system_agents(agent_id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'submitted',
    target_tool_name TEXT NULL,
    summary TEXT NULL,
    final_tool_id UUID NULL REFERENCES system_tools(tool_id) ON DELETE SET NULL,
    latest_revision_id UUID NULL,
    approved_by UUID NULL,
    approved_at TIMESTAMPTZ NULL,
    rejected_by UUID NULL,
    rejected_at TIMESTAMPTZ NULL,
    published_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE tool_generation_requests
    DROP CONSTRAINT IF EXISTS tool_generation_requests_status_check;

ALTER TABLE tool_generation_requests
    ADD CONSTRAINT tool_generation_requests_status_check
    CHECK (
        status IN (
            'submitted',
            'clarification_needed',
            'drafting',
            'validating',
            'pending_approval',
            'published',
            'rejected',
            'failed'
        )
    );

CREATE INDEX IF NOT EXISTS idx_tool_generation_requests_workspace
    ON tool_generation_requests(workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tool_generation_requests_thread
    ON tool_generation_requests(thread_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tool_generation_requests_status
    ON tool_generation_requests(status, created_at DESC);

CREATE TABLE IF NOT EXISTS tool_generation_revisions (
    revision_id UUID PRIMARY KEY,
    request_id UUID NOT NULL REFERENCES tool_generation_requests(request_id) ON DELETE CASCADE,
    revision_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'drafting',
    manifest JSONB NOT NULL,
    validation_report JSONB NULL,
    source_asset_id UUID NULL REFERENCES workspace_assets(asset_id) ON DELETE SET NULL,
    source_asset_version_id UUID NULL REFERENCES workspace_asset_versions(asset_version_id) ON DELETE SET NULL,
    manifest_asset_id UUID NULL REFERENCES workspace_assets(asset_id) ON DELETE SET NULL,
    manifest_asset_version_id UUID NULL REFERENCES workspace_asset_versions(asset_version_id) ON DELETE SET NULL,
    report_asset_id UUID NULL REFERENCES workspace_assets(asset_id) ON DELETE SET NULL,
    report_asset_version_id UUID NULL REFERENCES workspace_asset_versions(asset_version_id) ON DELETE SET NULL,
    image_ref TEXT NULL,
    image_digest TEXT NULL,
    created_by UUID NOT NULL REFERENCES participants(participant_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (request_id, revision_number)
);

ALTER TABLE tool_generation_revisions
    DROP CONSTRAINT IF EXISTS tool_generation_revisions_status_check;

ALTER TABLE tool_generation_revisions
    ADD CONSTRAINT tool_generation_revisions_status_check
    CHECK (
        status IN (
            'drafting',
            'validating',
            'pending_approval',
            'approved',
            'rejected',
            'failed'
        )
    );

CREATE INDEX IF NOT EXISTS idx_tool_generation_revisions_request
    ON tool_generation_revisions(request_id, revision_number DESC);

CREATE INDEX IF NOT EXISTS idx_tool_generation_revisions_status
    ON tool_generation_revisions(status, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_internal_tools (
    system_agent_id UUID NOT NULL REFERENCES system_agents(agent_id) ON DELETE CASCADE,
    tool_id UUID NOT NULL REFERENCES system_tools(tool_id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    attached_by UUID NOT NULL,
    attached_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (system_agent_id, tool_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_internal_tools_agent
    ON agent_internal_tools(system_agent_id, attached_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_internal_tools_tool
    ON agent_internal_tools(tool_id, attached_at DESC);
