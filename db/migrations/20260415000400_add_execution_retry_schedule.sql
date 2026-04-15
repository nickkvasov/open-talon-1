ALTER TABLE run_steps
    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;

ALTER TABLE tool_calls
    ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_run_steps_status_next_retry
    ON run_steps(status, next_retry_at, submitted_at, created_at);

CREATE INDEX IF NOT EXISTS idx_tool_calls_status_next_retry
    ON tool_calls(status, next_retry_at, submitted_at, created_at);
