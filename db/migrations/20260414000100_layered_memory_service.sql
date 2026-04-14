CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS workspace_memory_entries;

CREATE TABLE IF NOT EXISTS memory_entries (
    memory_entry_id UUID PRIMARY KEY,
    scope TEXT NOT NULL,
    state TEXT NOT NULL,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID REFERENCES threads(thread_id) ON DELETE CASCADE,
    run_id UUID REFERENCES runs(run_id) ON DELETE CASCADE,
    entry_type TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    source TEXT,
    visibility TEXT NOT NULL,
    created_by UUID NOT NULL,
    updated_by UUID NOT NULL,
    confirmed_by UUID,
    confirmed_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_entries_workspace_scope
    ON memory_entries(workspace_id, scope, state, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_entries_thread_scope
    ON memory_entries(thread_id, scope, state, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_entries_run_scope
    ON memory_entries(run_id, scope, state, updated_at DESC);

CREATE TABLE IF NOT EXISTS memory_providers (
    provider_id UUID PRIMARY KEY,
    provider_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    provider TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    secret_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_memory_providers_provider
    ON memory_providers(provider);

CREATE TABLE IF NOT EXISTS memory_provider_records (
    provider_record_id UUID PRIMARY KEY,
    memory_entry_id UUID NOT NULL REFERENCES memory_entries(memory_entry_id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES memory_providers(provider_id) ON DELETE CASCADE,
    external_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    last_synced_at TIMESTAMPTZ,
    last_error TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (memory_entry_id, provider_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_provider_records_provider
    ON memory_provider_records(provider_id, status, last_synced_at DESC);

INSERT INTO memory_providers (
    provider_id,
    provider_key,
    display_name,
    description,
    provider,
    enabled,
    config,
    secret_config,
    created_by,
    created_at,
    updated_by,
    updated_at,
    metadata
)
VALUES
    (
        '44444444-4444-4444-4444-444444444441',
        'postgres',
        'Canonical Postgres Memory',
        'Canonical layered memory store backed by Open Talon Postgres.',
        'postgres',
        TRUE,
        '{}'::jsonb,
        '{}'::jsonb,
        '00000000-0000-0000-0000-000000000001',
        NOW(),
        '00000000-0000-0000-0000-000000000001',
        NOW(),
        '{"seeded": true, "managed": true}'::jsonb
    ),
    (
        '44444444-4444-4444-4444-444444444442',
        'mem0',
        'Mem0 Layered Memory',
        'Mem0 OSS semantic memory provider with optional graph support.',
        'mem0',
        TRUE,
        '{
            "enable_graph": false,
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "host": "localhost",
                    "port": 5432,
                    "user": "admin",
                    "password": "password",
                    "dbname": "app_db",
                    "collection_name": "open_talon_memories"
                }
            },
            "llm": {
                "provider": "openai",
                "config": {
                    "model": "gpt-4.1-mini"
                }
            },
            "embedder": {
                "provider": "openai",
                "config": {
                    "model": "text-embedding-3-small"
                }
            }
        }'::jsonb,
        '{
            "env": {
                "name": "OPENAI_API_KEY"
            },
            "openbao": {
                "mount": "secret",
                "path": "open-talon/memory/mem0",
                "field": "api_key"
            }
        }'::jsonb,
        '00000000-0000-0000-0000-000000000001',
        NOW(),
        '00000000-0000-0000-0000-000000000001',
        NOW(),
        '{"seeded": true, "managed": true, "graph_optional": true}'::jsonb
    )
ON CONFLICT (provider_key) DO NOTHING;
