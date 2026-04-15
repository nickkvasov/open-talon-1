CREATE TABLE IF NOT EXISTS audit_event_ledger (
    ledger_offset BIGSERIAL UNIQUE NOT NULL,
    audit_event_id UUID PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL,
    scope_type TEXT NOT NULL,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID REFERENCES threads(thread_id) ON DELETE CASCADE,
    actor_type TEXT NOT NULL,
    actor_id UUID,
    user_id UUID REFERENCES users(user_id) ON DELETE SET NULL,
    system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    source_service TEXT NOT NULL,
    source_component TEXT NOT NULL,
    action_category TEXT NOT NULL,
    action_name TEXT NOT NULL,
    target_type TEXT,
    target_id UUID,
    outcome TEXT NOT NULL,
    correlation_id UUID,
    causation_id UUID,
    request_id UUID,
    trace_id TEXT,
    error_code TEXT,
    error_class TEXT,
    error_message_redacted TEXT,
    payload_mode TEXT NOT NULL DEFAULT 'metadata_only',
    payload_hash TEXT,
    payload_ref TEXT,
    payload_size_bytes BIGINT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    chain_partition TEXT NOT NULL,
    chain_sequence BIGINT NOT NULL,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS audit_event_ledger_chain_partition_sequence_idx
    ON audit_event_ledger (chain_partition, chain_sequence);

CREATE INDEX IF NOT EXISTS audit_event_ledger_recorded_at_idx
    ON audit_event_ledger (recorded_at DESC);

CREATE INDEX IF NOT EXISTS audit_event_ledger_workspace_recorded_at_idx
    ON audit_event_ledger (workspace_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS audit_event_ledger_thread_recorded_at_idx
    ON audit_event_ledger (thread_id, recorded_at DESC);

CREATE INDEX IF NOT EXISTS audit_event_ledger_correlation_id_idx
    ON audit_event_ledger (correlation_id);

CREATE INDEX IF NOT EXISTS audit_event_ledger_request_id_idx
    ON audit_event_ledger (request_id);

CREATE INDEX IF NOT EXISTS audit_event_ledger_action_name_idx
    ON audit_event_ledger (action_name);

CREATE INDEX IF NOT EXISTS audit_event_ledger_outcome_idx
    ON audit_event_ledger (outcome);

CREATE TABLE IF NOT EXISTS audit_chain_heads (
    chain_partition TEXT PRIMARY KEY,
    last_sequence BIGINT NOT NULL,
    last_event_hash TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_export_checkpoints (
    consumer_name TEXT PRIMARY KEY,
    last_ledger_offset BIGINT NOT NULL DEFAULT 0,
    last_exported_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
