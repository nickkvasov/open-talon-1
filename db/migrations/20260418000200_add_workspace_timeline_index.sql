CREATE INDEX IF NOT EXISTS idx_timeline_messages_workspace_created_at
    ON timeline_messages (workspace_id, created_at DESC, sequence DESC);
