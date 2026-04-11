CREATE TABLE IF NOT EXISTS auth_identities (
    user_id UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    email TEXT,
    display_name TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (issuer, subject)
);

CREATE INDEX IF NOT EXISTS idx_auth_identities_user_id
    ON auth_identities(user_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_participants_workspace_user_unique
    ON participants(workspace_id, user_id)
    WHERE user_id IS NOT NULL;
