-- migrate:up

CREATE TABLE IF NOT EXISTS methodic_executions (
    execution_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE,
    thread_id UUID REFERENCES threads(thread_id) ON DELETE SET NULL,
    conductor_system_agent_id UUID NOT NULL REFERENCES system_agents(agent_id) ON DELETE RESTRICT,
    conductor_participant_id UUID NOT NULL REFERENCES participants(participant_id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'submitted',
    target_goal TEXT,
    current_step_execution_id UUID,
    started_by UUID NOT NULL REFERENCES participants(participant_id) ON DELETE RESTRICT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    error TEXT,
    harness_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    methodics_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE methodic_executions
    DROP CONSTRAINT IF EXISTS methodic_executions_status_check;

ALTER TABLE methodic_executions
    ADD CONSTRAINT methodic_executions_status_check
    CHECK (status IN ('submitted', 'running', 'completed', 'cancelled', 'failed'));

CREATE INDEX IF NOT EXISTS idx_methodic_executions_workspace_created
    ON methodic_executions(workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_methodic_executions_workspace_status
    ON methodic_executions(workspace_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS methodic_execution_steps (
    step_execution_id UUID PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES methodic_executions(execution_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    methodic_index INTEGER NOT NULL DEFAULT 0,
    step_index INTEGER NOT NULL DEFAULT 0,
    methodic_name TEXT NOT NULL,
    name TEXT NOT NULL,
    instruction TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    expected_artifacts JSONB NOT NULL DEFAULT '[]'::jsonb,
    verification JSONB NOT NULL DEFAULT '[]'::jsonb,
    definition_of_done JSONB NOT NULL DEFAULT '[]'::jsonb,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    assigned_participant_id UUID REFERENCES participants(participant_id) ON DELETE SET NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE methodic_execution_steps
    DROP CONSTRAINT IF EXISTS methodic_execution_steps_status_check;

ALTER TABLE methodic_execution_steps
    ADD CONSTRAINT methodic_execution_steps_status_check
    CHECK (status IN ('pending', 'active', 'blocked', 'passed', 'failed', 'rework', 'skipped'));

CREATE INDEX IF NOT EXISTS idx_methodic_execution_steps_execution_order
    ON methodic_execution_steps(execution_id, methodic_index, step_index);

CREATE INDEX IF NOT EXISTS idx_methodic_execution_steps_workspace_status
    ON methodic_execution_steps(workspace_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS methodic_execution_assignments (
    assignment_id UUID PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES methodic_executions(execution_id) ON DELETE CASCADE,
    step_execution_id UUID NOT NULL REFERENCES methodic_execution_steps(step_execution_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    assignment_kind TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'created',
    title TEXT NOT NULL,
    instructions TEXT,
    assignee_participant_id UUID REFERENCES participants(participant_id) ON DELETE SET NULL,
    assignee_system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    interaction_request_id UUID REFERENCES interaction_requests(request_id) ON DELETE SET NULL,
    task_id UUID REFERENCES tasks(task_id) ON DELETE SET NULL,
    run_id UUID REFERENCES runs(run_id) ON DELETE SET NULL,
    artifact_id UUID REFERENCES artifacts(artifact_id) ON DELETE SET NULL,
    created_by UUID NOT NULL REFERENCES participants(participant_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE methodic_execution_assignments
    DROP CONSTRAINT IF EXISTS methodic_execution_assignments_kind_check;

ALTER TABLE methodic_execution_assignments
    ADD CONSTRAINT methodic_execution_assignments_kind_check
    CHECK (assignment_kind IN ('interaction_request', 'agent_task', 'message', 'manual'));

ALTER TABLE methodic_execution_assignments
    DROP CONSTRAINT IF EXISTS methodic_execution_assignments_status_check;

ALTER TABLE methodic_execution_assignments
    ADD CONSTRAINT methodic_execution_assignments_status_check
    CHECK (status IN ('created', 'waiting', 'completed', 'cancelled', 'failed'));

CREATE INDEX IF NOT EXISTS idx_methodic_execution_assignments_step
    ON methodic_execution_assignments(step_execution_id, created_at DESC);

CREATE TABLE IF NOT EXISTS methodic_execution_checks (
    check_id UUID PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES methodic_executions(execution_id) ON DELETE CASCADE,
    step_execution_id UUID NOT NULL REFERENCES methodic_execution_steps(step_execution_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'inconclusive',
    confidence DOUBLE PRECISION,
    reason TEXT,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    checked_by_system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE methodic_execution_checks
    DROP CONSTRAINT IF EXISTS methodic_execution_checks_status_check;

ALTER TABLE methodic_execution_checks
    ADD CONSTRAINT methodic_execution_checks_status_check
    CHECK (status IN ('passed', 'failed', 'inconclusive'));

CREATE INDEX IF NOT EXISTS idx_methodic_execution_checks_step
    ON methodic_execution_checks(step_execution_id, created_at DESC);

CREATE TABLE IF NOT EXISTS methodic_resource_requests (
    resource_request_id UUID PRIMARY KEY,
    execution_id UUID NOT NULL REFERENCES methodic_executions(execution_id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    step_execution_id UUID REFERENCES methodic_execution_steps(step_execution_id) ON DELETE SET NULL,
    resource_kind TEXT NOT NULL DEFAULT 'other',
    action TEXT NOT NULL DEFAULT 'other',
    status TEXT NOT NULL DEFAULT 'pending',
    title TEXT NOT NULL,
    description TEXT,
    required_permission TEXT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    requested_by_system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    approved_by UUID REFERENCES participants(participant_id) ON DELETE SET NULL,
    rejected_by UUID REFERENCES participants(participant_id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE methodic_resource_requests
    DROP CONSTRAINT IF EXISTS methodic_resource_requests_kind_check;

ALTER TABLE methodic_resource_requests
    ADD CONSTRAINT methodic_resource_requests_kind_check
    CHECK (resource_kind IN ('user', 'agent', 'tool', 'mcp_server', 'asset', 'retrieval_corpus', 'retrieval_source', 'other'));

ALTER TABLE methodic_resource_requests
    DROP CONSTRAINT IF EXISTS methodic_resource_requests_action_check;

ALTER TABLE methodic_resource_requests
    ADD CONSTRAINT methodic_resource_requests_action_check
    CHECK (action IN ('attach', 'link', 'activate', 'configure', 'invite', 'other'));

ALTER TABLE methodic_resource_requests
    DROP CONSTRAINT IF EXISTS methodic_resource_requests_status_check;

ALTER TABLE methodic_resource_requests
    ADD CONSTRAINT methodic_resource_requests_status_check
    CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled'));

CREATE INDEX IF NOT EXISTS idx_methodic_resource_requests_workspace_status
    ON methodic_resource_requests(workspace_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_methodic_resource_requests_execution
    ON methodic_resource_requests(execution_id, created_at DESC);

-- migrate:down

DROP TABLE IF EXISTS methodic_resource_requests;
DROP TABLE IF EXISTS methodic_execution_checks;
DROP TABLE IF EXISTS methodic_execution_assignments;
DROP TABLE IF EXISTS methodic_execution_steps;
DROP TABLE IF EXISTS methodic_executions;
