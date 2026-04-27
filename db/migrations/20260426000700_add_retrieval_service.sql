CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS retrieval_profiles (
    profile_id UUID PRIMARY KEY,
    scope TEXT NOT NULL,
    organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    embedding_provider_key TEXT,
    embedding_model TEXT,
    embedding_dimension INTEGER,
    vision_provider_key TEXT,
    vision_model TEXT,
    visual_extraction_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    vector_store_provider_key TEXT NOT NULL DEFAULT 'pgvector',
    chunking_strategy TEXT NOT NULL DEFAULT 'structure_aware',
    chunk_size_tokens INTEGER NOT NULL DEFAULT 800,
    chunk_overlap_tokens INTEGER NOT NULL DEFAULT 80,
    search_strategy TEXT NOT NULL DEFAULT 'hybrid',
    vector_weight DOUBLE PRECISION NOT NULL DEFAULT 0.65,
    keyword_weight DOUBLE PRECISION NOT NULL DEFAULT 0.35,
    top_k INTEGER NOT NULL DEFAULT 12,
    reranker_provider_key TEXT,
    reranker_model TEXT,
    context_token_budget INTEGER NOT NULL DEFAULT 6000,
    citation_strictness TEXT NOT NULL DEFAULT 'required',
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT retrieval_profiles_scope_check CHECK (
        (scope = 'global' AND organization_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND workspace_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_retrieval_profiles_scope_name
    ON retrieval_profiles (
        scope,
        COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
        name
    );

CREATE TABLE IF NOT EXISTS retrieval_corpora (
    corpus_id UUID PRIMARY KEY,
    scope TEXT NOT NULL,
    organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    default_profile_id UUID REFERENCES retrieval_profiles(profile_id) ON DELETE SET NULL,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT retrieval_corpora_scope_check CHECK (
        (scope = 'global' AND organization_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND workspace_id IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_retrieval_corpora_scope_name
    ON retrieval_corpora (
        scope,
        COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        COALESCE(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid),
        name
    );

CREATE INDEX IF NOT EXISTS idx_retrieval_corpora_scope
    ON retrieval_corpora(scope, organization_id, workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS retrieval_sources (
    source_id UUID PRIMARY KEY,
    corpus_id UUID NOT NULL REFERENCES retrieval_corpora(corpus_id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    asset_id UUID NOT NULL REFERENCES workspace_assets(asset_id) ON DELETE CASCADE,
    active_asset_version_id UUID REFERENCES workspace_asset_versions(asset_version_id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'file',
    content_type TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT retrieval_sources_scope_check CHECK (
        (scope = 'global' AND organization_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND workspace_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_retrieval_sources_corpus
    ON retrieval_sources(corpus_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_retrieval_sources_corpus_asset
    ON retrieval_sources(corpus_id, asset_id);

CREATE TABLE IF NOT EXISTS retrieval_ingestion_jobs (
    job_id UUID PRIMARY KEY,
    corpus_id UUID NOT NULL REFERENCES retrieval_corpora(corpus_id) ON DELETE CASCADE,
    source_id UUID REFERENCES retrieval_sources(source_id) ON DELETE CASCADE,
    source_version_id UUID,
    profile_id UUID REFERENCES retrieval_profiles(profile_id) ON DELETE SET NULL,
    scope TEXT NOT NULL,
    organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    stage TEXT NOT NULL,
    requested_by UUID NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT retrieval_ingestion_jobs_scope_check CHECK (
        (scope = 'global' AND organization_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND workspace_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_retrieval_ingestion_jobs_status
    ON retrieval_ingestion_jobs(status, stage, created_at ASC);

CREATE TABLE IF NOT EXISTS retrieval_source_versions (
    source_version_id UUID PRIMARY KEY,
    source_id UUID NOT NULL REFERENCES retrieval_sources(source_id) ON DELETE CASCADE,
    asset_version_id UUID NOT NULL REFERENCES workspace_asset_versions(asset_version_id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    ingestion_job_id UUID REFERENCES retrieval_ingestion_jobs(job_id) ON DELETE SET NULL,
    extracted_object_key TEXT,
    extracted_sha256 TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE retrieval_ingestion_jobs
    DROP CONSTRAINT IF EXISTS retrieval_ingestion_jobs_source_version_fkey;

ALTER TABLE retrieval_ingestion_jobs
    ADD CONSTRAINT retrieval_ingestion_jobs_source_version_fkey
    FOREIGN KEY (source_version_id)
    REFERENCES retrieval_source_versions(source_version_id)
    ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_retrieval_source_versions_source_version
    ON retrieval_source_versions(source_id, version);

CREATE TABLE IF NOT EXISTS retrieval_chunks (
    chunk_id UUID PRIMARY KEY,
    corpus_id UUID NOT NULL REFERENCES retrieval_corpora(corpus_id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES retrieval_sources(source_id) ON DELETE CASCADE,
    source_version_id UUID REFERENCES retrieval_source_versions(source_version_id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    chunk_kind TEXT NOT NULL DEFAULT 'text',
    ordinal INTEGER NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    token_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT NOT NULL,
    citation JSONB,
    search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT retrieval_chunks_scope_check CHECK (
        (scope = 'global' AND organization_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND workspace_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_retrieval_chunks_corpus_source_ordinal
    ON retrieval_chunks(corpus_id, source_id, ordinal);

CREATE INDEX IF NOT EXISTS idx_retrieval_chunks_search_vector
    ON retrieval_chunks USING GIN(search_vector);

CREATE TABLE IF NOT EXISTS retrieval_embeddings (
    embedding_id UUID PRIMARY KEY,
    chunk_id UUID NOT NULL REFERENCES retrieval_chunks(chunk_id) ON DELETE CASCADE,
    provider_key TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_store_provider_key TEXT NOT NULL DEFAULT 'pgvector',
    content_hash TEXT NOT NULL,
    embedding vector,
    embedded_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_retrieval_embeddings_chunk_model
    ON retrieval_embeddings(chunk_id, provider_key, model, content_hash);

CREATE INDEX IF NOT EXISTS idx_retrieval_embeddings_provider
    ON retrieval_embeddings(provider_key, model, dimensions, embedded_at DESC);

CREATE TABLE IF NOT EXISTS retrieval_runs (
    run_id UUID PRIMARY KEY,
    run_kind TEXT NOT NULL,
    scope TEXT NOT NULL,
    organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    profile_id UUID REFERENCES retrieval_profiles(profile_id) ON DELETE SET NULL,
    query TEXT,
    status TEXT NOT NULL,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT retrieval_runs_scope_check CHECK (
        (scope = 'global' AND organization_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND workspace_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_retrieval_runs_scope_created_at
    ON retrieval_runs(scope, organization_id, workspace_id, created_at DESC);

CREATE TABLE IF NOT EXISTS retrieval_hits (
    hit_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES retrieval_runs(run_id) ON DELETE CASCADE,
    chunk_id UUID NOT NULL REFERENCES retrieval_chunks(chunk_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    score DOUBLE PRECISION,
    vector_score DOUBLE PRECISION,
    keyword_score DOUBLE PRECISION,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_retrieval_hits_run_rank
    ON retrieval_hits(run_id, rank);

CREATE TABLE IF NOT EXISTS retrieval_context_packs (
    context_pack_id UUID PRIMARY KEY,
    run_id UUID REFERENCES retrieval_runs(run_id) ON DELETE SET NULL,
    scope TEXT NOT NULL,
    organization_id UUID REFERENCES organizations(organization_id) ON DELETE CASCADE,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    profile_id UUID REFERENCES retrieval_profiles(profile_id) ON DELETE SET NULL,
    query TEXT NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    hits JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT retrieval_context_packs_scope_check CHECK (
        (scope = 'global' AND organization_id IS NULL AND workspace_id IS NULL)
        OR (scope = 'organization' AND organization_id IS NOT NULL AND workspace_id IS NULL)
        OR (scope = 'workspace' AND organization_id IS NOT NULL AND workspace_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_retrieval_context_packs_scope_created_at
    ON retrieval_context_packs(scope, organization_id, workspace_id, created_at DESC);
