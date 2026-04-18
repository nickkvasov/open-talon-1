CREATE TABLE IF NOT EXISTS interaction_requests (
    request_id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'open',
    requester_participant_id UUID NOT NULL REFERENCES participants(participant_id) ON DELETE CASCADE,
    requester_message_id UUID NULL REFERENCES timeline_messages(message_id) ON DELETE SET NULL,
    requester_run_id UUID NULL REFERENCES runs(run_id) ON DELETE SET NULL,
    requester_task_id UUID NULL REFERENCES tasks(task_id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    summary TEXT NULL,
    completion_rule JSONB NOT NULL DEFAULT '{}'::jsonb,
    timeout_at TIMESTAMPTZ NULL,
    completed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS interaction_request_questions (
    question_id UUID PRIMARY KEY,
    request_id UUID NOT NULL REFERENCES interaction_requests(request_id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    kind TEXT NULL,
    expected_format TEXT NULL,
    question_order INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS interaction_request_targets (
    target_id UUID PRIMARY KEY,
    request_id UUID NOT NULL REFERENCES interaction_requests(request_id) ON DELETE CASCADE,
    participant_id UUID NULL REFERENCES participants(participant_id) ON DELETE CASCADE,
    selector_type TEXT NULL,
    selector_value TEXT NULL,
    selection_source TEXT NOT NULL DEFAULT 'explicit',
    score DOUBLE PRECISION NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    answered_message_id UUID NULL REFERENCES timeline_messages(message_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS interaction_answers (
    answer_id UUID PRIMARY KEY,
    request_id UUID NOT NULL REFERENCES interaction_requests(request_id) ON DELETE CASCADE,
    participant_id UUID NOT NULL REFERENCES participants(participant_id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES timeline_messages(message_id) ON DELETE CASCADE,
    question_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_interaction_requests_thread_created_at
    ON interaction_requests(thread_id, created_at);

CREATE INDEX IF NOT EXISTS idx_interaction_requests_requester_run_id
    ON interaction_requests(requester_run_id)
    WHERE requester_run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_interaction_requests_requester_task_id
    ON interaction_requests(requester_task_id)
    WHERE requester_task_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_interaction_request_questions_request_order
    ON interaction_request_questions(request_id, question_order);

CREATE INDEX IF NOT EXISTS idx_interaction_request_targets_request_status
    ON interaction_request_targets(request_id, status, created_at);

CREATE INDEX IF NOT EXISTS idx_interaction_request_targets_participant
    ON interaction_request_targets(participant_id, status)
    WHERE participant_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_interaction_answers_request_created_at
    ON interaction_answers(request_id, created_at);
