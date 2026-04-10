CREATE TABLE IF NOT EXISTS system_tools (
    tool_id UUID PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    parameter_contract JSONB NOT NULL DEFAULT '{"parameters":[],"additional_properties":false}'::jsonb,
    input_schema JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_system_tools_name
    ON system_tools(name);

CREATE TABLE IF NOT EXISTS workspace_tools (
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    tool_id UUID NOT NULL REFERENCES system_tools(tool_id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    attached_by UUID NOT NULL,
    attached_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (workspace_id, tool_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_tools_workspace
    ON workspace_tools(workspace_id, attached_at);
