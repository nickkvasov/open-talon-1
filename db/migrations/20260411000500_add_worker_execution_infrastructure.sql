ALTER TABLE system_tools
    ADD COLUMN IF NOT EXISTS backend_kind TEXT NOT NULL DEFAULT 'docker',
    ADD COLUMN IF NOT EXISTS handler_ref TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS execution_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS trust_level TEXT NOT NULL DEFAULT 'sandboxed';

UPDATE system_tools
SET handler_ref = name
WHERE handler_ref = '';

CREATE TABLE IF NOT EXISTS run_steps (
    step_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    system_agent_id UUID NOT NULL REFERENCES system_agents(agent_id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    input JSONB NOT NULL DEFAULT '{}'::jsonb,
    output JSONB NOT NULL DEFAULT '{}'::jsonb,
    claimed_by_worker TEXT,
    lease_expires_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    execution_handle TEXT,
    submitted_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (run_id, step_index)
);

CREATE INDEX IF NOT EXISTS idx_run_steps_status_submitted
    ON run_steps(status, submitted_at, created_at);

CREATE INDEX IF NOT EXISTS idx_run_steps_run
    ON run_steps(run_id, step_index);

CREATE INDEX IF NOT EXISTS idx_run_steps_lease
    ON run_steps(status, lease_expires_at);

CREATE TABLE IF NOT EXISTS tool_calls (
    tool_call_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    run_step_id UUID NOT NULL REFERENCES run_steps(step_id) ON DELETE CASCADE,
    task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    system_agent_id UUID NOT NULL REFERENCES system_agents(agent_id) ON DELETE CASCADE,
    tool_id UUID NOT NULL REFERENCES system_tools(tool_id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL,
    arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution_spec JSONB NOT NULL DEFAULT '{}'::jsonb,
    claimed_by_worker TEXT,
    lease_expires_at TIMESTAMPTZ,
    last_heartbeat_at TIMESTAMPTZ,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    execution_handle TEXT,
    result JSONB,
    submitted_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_status_submitted
    ON tool_calls(status, submitted_at, created_at);

CREATE INDEX IF NOT EXISTS idx_tool_calls_run_step
    ON tool_calls(run_step_id, created_at);

CREATE INDEX IF NOT EXISTS idx_tool_calls_run_status
    ON tool_calls(run_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_name_status
    ON tool_calls(tool_name, status, created_at);

CREATE INDEX IF NOT EXISTS idx_tool_calls_lease
    ON tool_calls(status, lease_expires_at);
