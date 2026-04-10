CREATE TABLE IF NOT EXISTS collab_event_log (
    event_id UUID PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    workspace_id UUID NOT NULL,
    thread_id UUID,
    actor_type TEXT NOT NULL,
    actor_id UUID NOT NULL,
    target_type TEXT NOT NULL,
    target_id UUID NOT NULL,
    visibility TEXT NOT NULL,
    correlation_id UUID NOT NULL,
    causation_id UUID,
    sequence BIGINT,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_collab_event_log_thread_sequence
    ON collab_event_log(thread_id, sequence);

CREATE INDEX IF NOT EXISTS idx_collab_event_log_workspace_created_at
    ON collab_event_log(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS workspace_sequences (
    workspace_id UUID PRIMARY KEY,
    last_sequence BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS thread_sequences (
    thread_id UUID PRIMARY KEY,
    last_sequence BIGINT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS processed_event_ids (
    event_id UUID PRIMARY KEY,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS users (
    user_id UUID PRIMARY KEY,
    display_name TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_display_name
    ON users(display_name);

CREATE TABLE IF NOT EXISTS system_agents (
    agent_id UUID PRIMARY KEY,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    role TEXT NOT NULL,
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    endpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
    system_prompt TEXT NOT NULL,
    interaction_contract JSONB NOT NULL DEFAULT '{}'::jsonb,
    definition JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE system_agents
    ADD COLUMN IF NOT EXISTS interaction_contract JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_system_agents_display_name
    ON system_agents(display_name);

CREATE TABLE IF NOT EXISTS threads (
    thread_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    state TEXT NOT NULL,
    parent_thread_id UUID,
    previous_thread_id UUID,
    related_thread_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_threads_workspace
    ON threads(workspace_id, created_at);

CREATE TABLE IF NOT EXISTS participants (
    participant_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    participant_type TEXT NOT NULL,
    user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    description TEXT,
    roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL,
    visibility_scope TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_participants_workspace
    ON participants(workspace_id, participant_type);

CREATE INDEX IF NOT EXISTS idx_participants_workspace_user
    ON participants(workspace_id, user_id);

CREATE INDEX IF NOT EXISTS idx_participants_workspace_system_agent
    ON participants(workspace_id, system_agent_id);

CREATE TABLE IF NOT EXISTS memberships (
    membership_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    participant_id UUID NOT NULL REFERENCES participants(participant_id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    joined_at TIMESTAMPTZ NOT NULL,
    left_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memberships_thread_participant_active
    ON memberships(thread_id, participant_id)
    WHERE left_at IS NULL;

CREATE TABLE IF NOT EXISTS workspace_memory_entries (
    memory_entry_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    entry_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by UUID NOT NULL,
    updated_by UUID NOT NULL,
    version INTEGER NOT NULL,
    visibility TEXT NOT NULL,
    linked_thread_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_workspace_memory_workspace
    ON workspace_memory_entries(workspace_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS timeline_messages (
    message_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    actor_type TEXT NOT NULL,
    actor_id UUID NOT NULL,
    visibility TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    correlation_id UUID NOT NULL,
    causation_id UUID,
    sequence BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_timeline_messages_thread_sequence
    ON timeline_messages(thread_id, sequence);

CREATE TABLE IF NOT EXISTS tasks (
    task_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL,
    requested_by UUID NOT NULL,
    claimed_by UUID,
    visibility TEXT NOT NULL,
    correlation_id UUID NOT NULL,
    causation_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_tasks_thread_created_at
    ON tasks(thread_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tasks_target_agent_status
    ON tasks((metadata->>'target_system_agent_id'), status, created_at);

CREATE TABLE IF NOT EXISTS runs (
    run_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    task_id UUID NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
    participant_id UUID,
    status TEXT NOT NULL,
    output JSONB NOT NULL DEFAULT '{}'::jsonb,
    correlation_id UUID NOT NULL,
    causation_id UUID,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_runs_task_created_at
    ON runs(task_id, created_at DESC);

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    task_id UUID,
    run_id UUID,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    visibility TEXT NOT NULL,
    correlation_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_artifacts_thread_created_at
    ON artifacts(thread_id, created_at DESC);

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id UUID PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    message_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
    correlation_id UUID,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created_at
    ON chat_messages(session_id, created_at DESC);
