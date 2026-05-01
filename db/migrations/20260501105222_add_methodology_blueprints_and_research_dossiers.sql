-- migrate:up

CREATE TABLE IF NOT EXISTS methodology_blueprints (
    blueprint_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    topic TEXT NOT NULL,
    target_goal TEXT,
    tasks JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'draft',
    active_version_id UUID,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE methodology_blueprints
    DROP CONSTRAINT IF EXISTS methodology_blueprints_status_check;

ALTER TABLE methodology_blueprints
    ADD CONSTRAINT methodology_blueprints_status_check
    CHECK (status IN ('draft', 'active', 'archived'));

CREATE INDEX IF NOT EXISTS idx_methodology_blueprints_org_created
    ON methodology_blueprints(organization_id, created_at DESC);

CREATE TABLE IF NOT EXISTS methodology_blueprint_versions (
    version_id UUID PRIMARY KEY,
    blueprint_id UUID NOT NULL REFERENCES methodology_blueprints(blueprint_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'researching',
    research_dossier_id UUID,
    source_policy TEXT NOT NULL DEFAULT 'hybrid',
    selected_library_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    cited_output TEXT,
    harness_draft JSONB,
    submitted_by_system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    submitted_at TIMESTAMPTZ,
    approved_by UUID,
    approved_at TIMESTAMPTZ,
    rejected_by UUID,
    rejected_at TIMESTAMPTZ,
    review_reason TEXT,
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (blueprint_id, version_number)
);

ALTER TABLE methodology_blueprint_versions
    DROP CONSTRAINT IF EXISTS methodology_blueprint_versions_status_check;

ALTER TABLE methodology_blueprint_versions
    ADD CONSTRAINT methodology_blueprint_versions_status_check
    CHECK (status IN (
        'researching',
        'ready_for_methodologist',
        'drafted',
        'pending_review',
        'approved',
        'rejected',
        'failed'
    ));

CREATE INDEX IF NOT EXISTS idx_methodology_blueprint_versions_blueprint
    ON methodology_blueprint_versions(blueprint_id, version_number DESC);

CREATE TABLE IF NOT EXISTS research_dossiers (
    dossier_id UUID PRIMARY KEY,
    blueprint_id UUID NOT NULL REFERENCES methodology_blueprints(blueprint_id) ON DELETE CASCADE,
    version_id UUID NOT NULL REFERENCES methodology_blueprint_versions(version_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    retained_library_id UUID REFERENCES libraries(library_id) ON DELETE SET NULL,
    operations_workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE SET NULL,
    thread_id UUID REFERENCES threads(thread_id) ON DELETE SET NULL,
    researcher_system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    researcher_participant_id UUID REFERENCES participants(participant_id) ON DELETE SET NULL,
    methodologist_system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    methodologist_participant_id UUID REFERENCES participants(participant_id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'created',
    topic TEXT NOT NULL,
    tasks JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary TEXT,
    contradictions JSONB NOT NULL DEFAULT '[]'::jsonb,
    gaps JSONB NOT NULL DEFAULT '[]'::jsonb,
    context_pack_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by UUID NOT NULL,
    ready_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (version_id)
);

ALTER TABLE research_dossiers
    DROP CONSTRAINT IF EXISTS research_dossiers_status_check;

ALTER TABLE research_dossiers
    ADD CONSTRAINT research_dossiers_status_check
    CHECK (status IN ('created', 'researching', 'ready_for_methodologist', 'completed', 'failed'));

CREATE INDEX IF NOT EXISTS idx_research_dossiers_org_status
    ON research_dossiers(organization_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS research_dossier_sources (
    source_id UUID PRIMARY KEY,
    dossier_id UUID NOT NULL REFERENCES research_dossiers(dossier_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    source_kind TEXT NOT NULL DEFAULT 'other',
    status TEXT NOT NULL DEFAULT 'discovered',
    title TEXT NOT NULL,
    source_uri TEXT,
    library_id UUID REFERENCES libraries(library_id) ON DELETE SET NULL,
    library_item_id UUID REFERENCES library_items(item_id) ON DELETE SET NULL,
    asset_id UUID REFERENCES workspace_assets(asset_id) ON DELETE SET NULL,
    asset_version_id UUID REFERENCES workspace_asset_versions(asset_version_id) ON DELETE SET NULL,
    context_pack_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    citation_id TEXT,
    quality_notes TEXT,
    contradictions JSONB NOT NULL DEFAULT '[]'::jsonb,
    rationale TEXT,
    fetch_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    discovered_by_participant_id UUID,
    discovered_by_system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

ALTER TABLE research_dossier_sources
    DROP CONSTRAINT IF EXISTS research_dossier_sources_kind_check;

ALTER TABLE research_dossier_sources
    ADD CONSTRAINT research_dossier_sources_kind_check
    CHECK (source_kind IN (
        'library_item',
        'webpage',
        'paper',
        'file',
        'media',
        'image',
        'video',
        'audio',
        'dataset',
        'other'
    ));

ALTER TABLE research_dossier_sources
    DROP CONSTRAINT IF EXISTS research_dossier_sources_status_check;

ALTER TABLE research_dossier_sources
    ADD CONSTRAINT research_dossier_sources_status_check
    CHECK (status IN (
        'discovered',
        'fetched',
        'included',
        'excluded',
        'duplicate',
        'failed',
        'rejected',
        'unresolved'
    ));

CREATE INDEX IF NOT EXISTS idx_research_dossier_sources_dossier_status
    ON research_dossier_sources(dossier_id, status, created_at ASC);

CREATE TABLE IF NOT EXISTS research_dossier_events (
    event_id UUID PRIMARY KEY,
    dossier_id UUID NOT NULL REFERENCES research_dossiers(dossier_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES organizations(organization_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    actor_participant_id UUID,
    system_agent_id UUID REFERENCES system_agents(agent_id) ON DELETE SET NULL,
    source_id UUID REFERENCES research_dossier_sources(source_id) ON DELETE SET NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_research_dossier_events_dossier_created
    ON research_dossier_events(dossier_id, created_at ASC);

ALTER TABLE methodology_blueprints
    DROP CONSTRAINT IF EXISTS methodology_blueprints_active_version_fk;

ALTER TABLE methodology_blueprints
    ADD CONSTRAINT methodology_blueprints_active_version_fk
    FOREIGN KEY (active_version_id)
    REFERENCES methodology_blueprint_versions(version_id)
    ON DELETE SET NULL;

ALTER TABLE methodology_blueprint_versions
    DROP CONSTRAINT IF EXISTS methodology_blueprint_versions_dossier_fk;

ALTER TABLE methodology_blueprint_versions
    ADD CONSTRAINT methodology_blueprint_versions_dossier_fk
    FOREIGN KEY (research_dossier_id)
    REFERENCES research_dossiers(dossier_id)
    ON DELETE SET NULL
    DEFERRABLE INITIALLY DEFERRED;

-- migrate:down

ALTER TABLE methodology_blueprint_versions
    DROP CONSTRAINT IF EXISTS methodology_blueprint_versions_dossier_fk;

ALTER TABLE methodology_blueprints
    DROP CONSTRAINT IF EXISTS methodology_blueprints_active_version_fk;

DROP TABLE IF EXISTS research_dossier_events;
DROP TABLE IF EXISTS research_dossier_sources;
DROP TABLE IF EXISTS research_dossiers;
DROP TABLE IF EXISTS methodology_blueprint_versions;
DROP TABLE IF EXISTS methodology_blueprints;
