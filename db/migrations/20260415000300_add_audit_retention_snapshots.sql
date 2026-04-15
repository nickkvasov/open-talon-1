CREATE TABLE IF NOT EXISTS audit_retention_snapshots (
    snapshot_id UUID PRIMARY KEY,
    chain_partition TEXT NOT NULL,
    cutoff_recorded_at TIMESTAMPTZ NOT NULL,
    last_pruned_sequence BIGINT NOT NULL,
    last_pruned_event_hash TEXT NOT NULL,
    object_key TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS audit_retention_snapshots_partition_cutoff_idx
    ON audit_retention_snapshots (chain_partition, cutoff_recorded_at);

CREATE INDEX IF NOT EXISTS audit_retention_snapshots_partition_created_idx
    ON audit_retention_snapshots (chain_partition, created_at DESC);
