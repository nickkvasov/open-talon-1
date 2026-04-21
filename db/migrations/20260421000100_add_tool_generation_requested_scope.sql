ALTER TABLE tool_generation_requests
    ADD COLUMN IF NOT EXISTS requested_scope TEXT NOT NULL DEFAULT 'global';

ALTER TABLE tool_generation_requests
    DROP CONSTRAINT IF EXISTS tool_generation_requests_requested_scope_check;

ALTER TABLE tool_generation_requests
    ADD CONSTRAINT tool_generation_requests_requested_scope_check
    CHECK (requested_scope IN ('global', 'organization'));
