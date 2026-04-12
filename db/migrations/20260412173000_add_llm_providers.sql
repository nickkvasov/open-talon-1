CREATE TABLE IF NOT EXISTS llm_providers (
    provider_id UUID PRIMARY KEY,
    engine_id TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    provider TEXT NOT NULL,
    endpoint_kind TEXT NOT NULL,
    url TEXT,
    default_model TEXT,
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    locality TEXT NOT NULL DEFAULT 'cloud',
    priority INTEGER NOT NULL DEFAULT 100,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    secret_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_llm_providers_engine_id
    ON llm_providers(engine_id);

CREATE INDEX IF NOT EXISTS idx_llm_providers_provider
    ON llm_providers(provider);
