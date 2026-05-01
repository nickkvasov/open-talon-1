-- migrate:up

CREATE TABLE IF NOT EXISTS research_dossier_notebooks (
    notebook_id UUID PRIMARY KEY,
    dossier_id UUID NOT NULL REFERENCES research_dossiers(dossier_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    provider_kind TEXT NOT NULL DEFAULT 'xwiki',
    provider_key TEXT NOT NULL DEFAULT 'xwiki',
    status TEXT NOT NULL DEFAULT 'created',
    home_note_id UUID,
    external_space_ref TEXT,
    external_url TEXT,
    last_sync_at TIMESTAMPTZ,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (dossier_id)
);

ALTER TABLE research_dossier_notebooks
    DROP CONSTRAINT IF EXISTS research_dossier_notebooks_provider_kind_check;

ALTER TABLE research_dossier_notebooks
    ADD CONSTRAINT research_dossier_notebooks_provider_kind_check
    CHECK (provider_kind IN ('native', 'xwiki'));

ALTER TABLE research_dossier_notebooks
    DROP CONSTRAINT IF EXISTS research_dossier_notebooks_status_check;

ALTER TABLE research_dossier_notebooks
    ADD CONSTRAINT research_dossier_notebooks_status_check
    CHECK (status IN ('created', 'syncing', 'ready', 'degraded', 'failed'));

CREATE INDEX IF NOT EXISTS idx_research_dossier_notebooks_org_status
    ON research_dossier_notebooks(organization_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS research_dossier_notes (
    note_id UUID PRIMARY KEY,
    notebook_id UUID NOT NULL REFERENCES research_dossier_notebooks(notebook_id) ON DELETE CASCADE,
    dossier_id UUID NOT NULL REFERENCES research_dossiers(dossier_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    note_kind TEXT NOT NULL DEFAULT 'other',
    status TEXT NOT NULL DEFAULT 'draft',
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    summary TEXT,
    source_id UUID REFERENCES research_dossier_sources(source_id) ON DELETE SET NULL,
    concept_id UUID,
    citation_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_note_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    external_page_ref TEXT,
    external_url TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (notebook_id, slug)
);

ALTER TABLE research_dossier_notes
    DROP CONSTRAINT IF EXISTS research_dossier_notes_kind_check;

ALTER TABLE research_dossier_notes
    ADD CONSTRAINT research_dossier_notes_kind_check
    CHECK (note_kind IN (
        'home',
        'source',
        'concept',
        'entity',
        'method',
        'question',
        'contradiction',
        'gap',
        'synthesis',
        'other'
    ));

ALTER TABLE research_dossier_notes
    DROP CONSTRAINT IF EXISTS research_dossier_notes_status_check;

ALTER TABLE research_dossier_notes
    ADD CONSTRAINT research_dossier_notes_status_check
    CHECK (status IN ('draft', 'active', 'stale', 'archived', 'failed'));

CREATE INDEX IF NOT EXISTS idx_research_dossier_notes_notebook_kind
    ON research_dossier_notes(notebook_id, note_kind, status, slug);

CREATE TABLE IF NOT EXISTS research_dossier_concepts (
    concept_id UUID PRIMARY KEY,
    notebook_id UUID NOT NULL REFERENCES research_dossier_notebooks(notebook_id) ON DELETE CASCADE,
    dossier_id UUID NOT NULL REFERENCES research_dossiers(dossier_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    slug TEXT NOT NULL,
    name TEXT NOT NULL,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    definition TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    confidence DOUBLE PRECISION,
    source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    claim_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (notebook_id, slug)
);

ALTER TABLE research_dossier_concepts
    DROP CONSTRAINT IF EXISTS research_dossier_concepts_status_check;

ALTER TABLE research_dossier_concepts
    ADD CONSTRAINT research_dossier_concepts_status_check
    CHECK (status IN ('candidate', 'active', 'merged', 'deprecated', 'unresolved'));

CREATE INDEX IF NOT EXISTS idx_research_dossier_concepts_notebook_status
    ON research_dossier_concepts(notebook_id, status, slug);

ALTER TABLE research_dossier_notes
    DROP CONSTRAINT IF EXISTS research_dossier_notes_concept_fk;

ALTER TABLE research_dossier_notes
    ADD CONSTRAINT research_dossier_notes_concept_fk
    FOREIGN KEY (concept_id)
    REFERENCES research_dossier_concepts(concept_id)
    ON DELETE SET NULL
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS research_dossier_claims (
    claim_id UUID PRIMARY KEY,
    notebook_id UUID NOT NULL REFERENCES research_dossier_notebooks(notebook_id) ON DELETE CASCADE,
    dossier_id UUID NOT NULL REFERENCES research_dossiers(dossier_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    claim_key TEXT,
    statement TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    confidence DOUBLE PRECISION,
    provenance TEXT NOT NULL DEFAULT 'source',
    source_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    citation_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    context_pack_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    contradicted_by_claim_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE research_dossier_claims
    DROP CONSTRAINT IF EXISTS research_dossier_claims_status_check;

ALTER TABLE research_dossier_claims
    ADD CONSTRAINT research_dossier_claims_status_check
    CHECK (status IN ('draft', 'supported', 'contradicted', 'ambiguous', 'rejected', 'unresolved'));

CREATE UNIQUE INDEX IF NOT EXISTS idx_research_dossier_claims_notebook_key
    ON research_dossier_claims(notebook_id, claim_key)
    WHERE claim_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_research_dossier_claims_notebook_status
    ON research_dossier_claims(notebook_id, status, created_at ASC);

CREATE TABLE IF NOT EXISTS research_dossier_links (
    link_id UUID PRIMARY KEY,
    notebook_id UUID NOT NULL REFERENCES research_dossier_notebooks(notebook_id) ON DELETE CASCADE,
    dossier_id UUID NOT NULL REFERENCES research_dossiers(dossier_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    source_ref_id UUID NOT NULL,
    target_type TEXT NOT NULL,
    target_ref_id UUID NOT NULL,
    link_kind TEXT NOT NULL DEFAULT 'related',
    rationale TEXT,
    confidence DOUBLE PRECISION,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (notebook_id, source_type, source_ref_id, target_type, target_ref_id, link_kind)
);

ALTER TABLE research_dossier_links
    DROP CONSTRAINT IF EXISTS research_dossier_links_node_type_check;

ALTER TABLE research_dossier_links
    ADD CONSTRAINT research_dossier_links_node_type_check
    CHECK (
        source_type IN ('note', 'concept', 'claim', 'source')
        AND target_type IN ('note', 'concept', 'claim', 'source')
    );

ALTER TABLE research_dossier_links
    DROP CONSTRAINT IF EXISTS research_dossier_links_kind_check;

ALTER TABLE research_dossier_links
    ADD CONSTRAINT research_dossier_links_kind_check
    CHECK (link_kind IN (
        'supports',
        'contradicts',
        'requires',
        'generalizes',
        'specializes',
        'example_of',
        'same_as',
        'derived_from',
        'mentions',
        'answers',
        'questions',
        'related'
    ));

CREATE INDEX IF NOT EXISTS idx_research_dossier_links_notebook_source
    ON research_dossier_links(notebook_id, source_type, source_ref_id);

CREATE INDEX IF NOT EXISTS idx_research_dossier_links_notebook_target
    ON research_dossier_links(notebook_id, target_type, target_ref_id);

CREATE TABLE IF NOT EXISTS research_dossier_provider_bindings (
    binding_id UUID PRIMARY KEY,
    notebook_id UUID NOT NULL REFERENCES research_dossier_notebooks(notebook_id) ON DELETE CASCADE,
    dossier_id UUID NOT NULL REFERENCES research_dossiers(dossier_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    provider_kind TEXT NOT NULL DEFAULT 'xwiki',
    provider_key TEXT NOT NULL DEFAULT 'xwiki',
    status TEXT NOT NULL DEFAULT 'created',
    external_space_ref TEXT,
    external_base_url TEXT,
    auth_kind TEXT NOT NULL DEFAULT 'basic',
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    secret_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_sync_at TIMESTAMPTZ,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_by UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (notebook_id, provider_key)
);

ALTER TABLE research_dossier_provider_bindings
    DROP CONSTRAINT IF EXISTS research_dossier_provider_bindings_provider_kind_check;

ALTER TABLE research_dossier_provider_bindings
    ADD CONSTRAINT research_dossier_provider_bindings_provider_kind_check
    CHECK (provider_kind IN ('native', 'xwiki'));

ALTER TABLE research_dossier_provider_bindings
    DROP CONSTRAINT IF EXISTS research_dossier_provider_bindings_status_check;

ALTER TABLE research_dossier_provider_bindings
    ADD CONSTRAINT research_dossier_provider_bindings_status_check
    CHECK (status IN ('created', 'syncing', 'ready', 'degraded', 'failed'));

CREATE INDEX IF NOT EXISTS idx_research_dossier_provider_bindings_org_kind
    ON research_dossier_provider_bindings(organization_id, provider_kind, status);

CREATE TABLE IF NOT EXISTS research_dossier_provider_external_refs (
    ref_id UUID PRIMARY KEY,
    binding_id UUID NOT NULL REFERENCES research_dossier_provider_bindings(binding_id) ON DELETE CASCADE,
    notebook_id UUID NOT NULL REFERENCES research_dossier_notebooks(notebook_id) ON DELETE CASCADE,
    dossier_id UUID NOT NULL REFERENCES research_dossiers(dossier_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    open_talon_resource_type TEXT NOT NULL,
    open_talon_resource_id UUID NOT NULL,
    external_kind TEXT NOT NULL DEFAULT 'other',
    external_id TEXT NOT NULL,
    external_url TEXT,
    external_parent_id TEXT,
    sync_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (binding_id, open_talon_resource_type, open_talon_resource_id, external_kind)
);

ALTER TABLE research_dossier_provider_external_refs
    DROP CONSTRAINT IF EXISTS research_dossier_provider_external_refs_kind_check;

ALTER TABLE research_dossier_provider_external_refs
    ADD CONSTRAINT research_dossier_provider_external_refs_kind_check
    CHECK (external_kind IN ('notebook', 'space', 'page', 'object', 'attachment', 'search_index', 'other'));

CREATE INDEX IF NOT EXISTS idx_research_dossier_provider_external_refs_external
    ON research_dossier_provider_external_refs(binding_id, external_kind, external_id);

CREATE TABLE IF NOT EXISTS research_dossier_sync_runs (
    sync_run_id UUID PRIMARY KEY,
    binding_id UUID REFERENCES research_dossier_provider_bindings(binding_id) ON DELETE SET NULL,
    notebook_id UUID NOT NULL REFERENCES research_dossier_notebooks(notebook_id) ON DELETE CASCADE,
    dossier_id UUID NOT NULL REFERENCES research_dossiers(dossier_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued',
    direction TEXT NOT NULL DEFAULT 'push',
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor_participant_id UUID,
    system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE research_dossier_sync_runs
    DROP CONSTRAINT IF EXISTS research_dossier_sync_runs_status_check;

ALTER TABLE research_dossier_sync_runs
    ADD CONSTRAINT research_dossier_sync_runs_status_check
    CHECK (status IN ('queued', 'running', 'completed', 'failed'));

ALTER TABLE research_dossier_sync_runs
    DROP CONSTRAINT IF EXISTS research_dossier_sync_runs_direction_check;

ALTER TABLE research_dossier_sync_runs
    ADD CONSTRAINT research_dossier_sync_runs_direction_check
    CHECK (direction IN ('push', 'pull', 'bidirectional', 'health'));

CREATE INDEX IF NOT EXISTS idx_research_dossier_sync_runs_notebook_created
    ON research_dossier_sync_runs(notebook_id, created_at DESC);

CREATE TABLE IF NOT EXISTS research_dossier_health_checks (
    check_id UUID PRIMARY KEY,
    notebook_id UUID NOT NULL REFERENCES research_dossier_notebooks(notebook_id) ON DELETE CASCADE,
    dossier_id UUID NOT NULL REFERENCES research_dossiers(dossier_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'warning',
    summary TEXT,
    findings JSONB NOT NULL DEFAULT '[]'::jsonb,
    unresolved_count INTEGER NOT NULL DEFAULT 0,
    stale_count INTEGER NOT NULL DEFAULT 0,
    broken_link_count INTEGER NOT NULL DEFAULT 0,
    checked_by_participant_id UUID,
    checked_by_system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE research_dossier_health_checks
    DROP CONSTRAINT IF EXISTS research_dossier_health_checks_status_check;

ALTER TABLE research_dossier_health_checks
    ADD CONSTRAINT research_dossier_health_checks_status_check
    CHECK (status IN ('passed', 'warning', 'failed'));

CREATE INDEX IF NOT EXISTS idx_research_dossier_health_checks_notebook_created
    ON research_dossier_health_checks(notebook_id, created_at DESC);

-- migrate:down

DROP TABLE IF EXISTS research_dossier_health_checks;
DROP TABLE IF EXISTS research_dossier_sync_runs;
DROP TABLE IF EXISTS research_dossier_provider_external_refs;
DROP TABLE IF EXISTS research_dossier_provider_bindings;
DROP TABLE IF EXISTS research_dossier_links;
DROP TABLE IF EXISTS research_dossier_claims;

ALTER TABLE research_dossier_notes
    DROP CONSTRAINT IF EXISTS research_dossier_notes_concept_fk;

DROP TABLE IF EXISTS research_dossier_concepts;
DROP TABLE IF EXISTS research_dossier_notes;
DROP TABLE IF EXISTS research_dossier_notebooks;
