-- migrate:up

ALTER TABLE IF EXISTS research_dossiers RENAME TO dossiers;
ALTER TABLE IF EXISTS research_dossier_sources RENAME TO dossier_sources;
ALTER TABLE IF EXISTS research_dossier_events RENAME TO dossier_events;
ALTER TABLE IF EXISTS research_dossier_notebooks RENAME TO dossier_notebooks;
ALTER TABLE IF EXISTS research_dossier_notes RENAME TO dossier_notes;
ALTER TABLE IF EXISTS research_dossier_concepts RENAME TO dossier_concepts;
ALTER TABLE IF EXISTS research_dossier_claims RENAME TO dossier_claims;
ALTER TABLE IF EXISTS research_dossier_links RENAME TO dossier_links;
ALTER TABLE IF EXISTS research_dossier_provider_bindings RENAME TO dossier_provider_bindings;
ALTER TABLE IF EXISTS research_dossier_provider_external_refs RENAME TO dossier_provider_external_refs;
ALTER TABLE IF EXISTS research_dossier_sync_runs RENAME TO dossier_sync_runs;
ALTER TABLE IF EXISTS research_dossier_health_checks RENAME TO dossier_health_checks;

ALTER INDEX IF EXISTS idx_research_dossiers_org_status RENAME TO idx_dossiers_org_status;
ALTER INDEX IF EXISTS idx_research_dossier_sources_dossier_status RENAME TO idx_dossier_sources_dossier_status;
ALTER INDEX IF EXISTS idx_research_dossier_events_dossier_created RENAME TO idx_dossier_events_dossier_created;
ALTER INDEX IF EXISTS idx_research_dossier_notebooks_org_status RENAME TO idx_dossier_notebooks_org_status;
ALTER INDEX IF EXISTS idx_research_dossier_notes_notebook_kind RENAME TO idx_dossier_notes_notebook_kind;
ALTER INDEX IF EXISTS idx_research_dossier_concepts_notebook_status RENAME TO idx_dossier_concepts_notebook_status;
ALTER INDEX IF EXISTS idx_research_dossier_claims_notebook_key RENAME TO idx_dossier_claims_notebook_key;
ALTER INDEX IF EXISTS idx_research_dossier_claims_notebook_status RENAME TO idx_dossier_claims_notebook_status;
ALTER INDEX IF EXISTS idx_research_dossier_links_notebook_source RENAME TO idx_dossier_links_notebook_source;
ALTER INDEX IF EXISTS idx_research_dossier_links_notebook_target RENAME TO idx_dossier_links_notebook_target;
ALTER INDEX IF EXISTS idx_research_dossier_provider_bindings_org_kind RENAME TO idx_dossier_provider_bindings_org_kind;
ALTER INDEX IF EXISTS idx_research_dossier_provider_external_refs_external RENAME TO idx_dossier_provider_external_refs_external;
ALTER INDEX IF EXISTS idx_research_dossier_sync_runs_notebook_created RENAME TO idx_dossier_sync_runs_notebook_created;
ALTER INDEX IF EXISTS idx_research_dossier_health_checks_notebook_created RENAME TO idx_dossier_health_checks_notebook_created;

ALTER TABLE IF EXISTS methodology_blueprint_versions
    DROP CONSTRAINT IF EXISTS methodology_blueprint_versions_dossier_fk;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'methodology_blueprint_versions'
          AND column_name = 'research_dossier_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'methodology_blueprint_versions'
          AND column_name = 'dossier_id'
    ) THEN
        ALTER TABLE methodology_blueprint_versions
            RENAME COLUMN research_dossier_id TO dossier_id;
    END IF;
END $$;

ALTER TABLE IF EXISTS dossiers
    DROP CONSTRAINT IF EXISTS research_dossiers_status_check;
ALTER TABLE IF EXISTS dossiers
    DROP CONSTRAINT IF EXISTS dossiers_status_check;

UPDATE dossiers
SET status = CASE status
    WHEN 'researching' THEN 'collecting'
    WHEN 'ready_for_methodologist' THEN 'ready'
    WHEN 'completed' THEN 'consumed'
    ELSE status
END
WHERE status IN ('researching', 'ready_for_methodologist', 'completed');

ALTER TABLE dossiers
    ADD CONSTRAINT dossiers_status_check
    CHECK (status IN (
        'created',
        'scoping',
        'collecting',
        'synthesizing',
        'ready',
        'consumed',
        'archived',
        'failed'
    ));

ALTER TABLE IF EXISTS methodology_blueprint_versions
    DROP CONSTRAINT IF EXISTS methodology_blueprint_versions_status_check;

UPDATE methodology_blueprint_versions
SET status = 'ready_for_draft'
WHERE status = 'ready_for_methodologist';

ALTER TABLE methodology_blueprint_versions
    ADD CONSTRAINT methodology_blueprint_versions_status_check
    CHECK (status IN (
        'researching',
        'ready_for_draft',
        'drafted',
        'pending_review',
        'approved',
        'rejected',
        'failed'
    ));

ALTER TABLE methodology_blueprint_versions
    ADD CONSTRAINT methodology_blueprint_versions_dossier_fk
    FOREIGN KEY (dossier_id)
    REFERENCES dossiers(dossier_id)
    ON DELETE SET NULL
    DEFERRABLE INITIALLY DEFERRED;

DO $$
DECLARE
    constraint_record RECORD;
    next_name TEXT;
BEGIN
    FOR constraint_record IN
        SELECT conrelid::regclass AS table_name, conrelid, conname
        FROM pg_constraint
        WHERE conname LIKE '%research_dossier%'
    LOOP
        next_name := replace(constraint_record.conname, 'research_dossier', 'dossier');
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = constraint_record.conrelid
              AND conname = next_name
        ) THEN
            EXECUTE format(
                'ALTER TABLE %s RENAME CONSTRAINT %I TO %I',
                constraint_record.table_name,
                constraint_record.conname,
                next_name
            );
        END IF;
    END LOOP;
END $$;

UPDATE libraries
SET metadata = (metadata - 'research_dossier_id' - 'research_dossier')
    || CASE WHEN metadata ? 'research_dossier_id'
        THEN jsonb_build_object('dossier_id', metadata->'research_dossier_id')
        ELSE '{}'::jsonb
    END
    || CASE WHEN metadata ? 'research_dossier'
        THEN jsonb_build_object('dossier', metadata->'research_dossier')
        ELSE '{}'::jsonb
    END
WHERE metadata ? 'research_dossier_id' OR metadata ? 'research_dossier';

UPDATE threads
SET metadata = (metadata - 'research_dossier_id')
    || jsonb_build_object('dossier_id', metadata->'research_dossier_id')
WHERE metadata ? 'research_dossier_id';

UPDATE tasks
SET metadata = (metadata - 'research_dossier_id')
    || jsonb_build_object('dossier_id', metadata->'research_dossier_id')
WHERE metadata ? 'research_dossier_id';

WITH tool_map(old_name, new_name) AS (
    VALUES
        ('methodology.dossiers.get', 'dossiers.get'),
        ('methodology.dossiers.sources.create', 'dossiers.sources.create'),
        ('methodology.dossiers.sources.update', 'dossiers.sources.update'),
        ('methodology.dossiers.context_pack.attach', 'dossiers.context_pack.attach'),
        ('methodology.dossiers.mark_ready', 'dossiers.lifecycle.transition'),
        ('methodology.dossiers.notebook.get', 'dossiers.notebook.get'),
        ('methodology.dossiers.notes.upsert', 'dossiers.notes.upsert'),
        ('methodology.dossiers.concepts.upsert', 'dossiers.concepts.upsert'),
        ('methodology.dossiers.claims.upsert', 'dossiers.claims.upsert'),
        ('methodology.dossiers.links.upsert', 'dossiers.links.upsert'),
        ('methodology.dossiers.navigate', 'dossiers.navigate'),
        ('methodology.dossiers.sync', 'dossiers.sync'),
        ('methodology.dossiers.health.submit', 'dossiers.health.submit')
),
old_tools AS (
    SELECT tools.server_id, tool_map.new_name, tools.description, tools.input_schema,
           tools.output_schema, tools.capability_hash, tools.discovered_at,
           tools.metadata
    FROM mcp_server_tools tools
    JOIN tool_map ON tool_map.old_name = tools.tool_name
)
INSERT INTO mcp_server_tools (
    server_id, tool_name, display_name, description, input_schema, output_schema,
    capability_hash, discovered_at, metadata
)
SELECT server_id, new_name, new_name, replace(description, 'methodology.dossiers', 'dossiers'),
       input_schema, output_schema, capability_hash, discovered_at, metadata
FROM old_tools
ON CONFLICT (server_id, tool_name) DO UPDATE
SET description = EXCLUDED.description,
    capability_hash = EXCLUDED.capability_hash,
    metadata = mcp_server_tools.metadata || EXCLUDED.metadata;

WITH tool_map(old_name, new_name) AS (
    VALUES
        ('methodology.dossiers.get', 'dossiers.get'),
        ('methodology.dossiers.sources.create', 'dossiers.sources.create'),
        ('methodology.dossiers.sources.update', 'dossiers.sources.update'),
        ('methodology.dossiers.context_pack.attach', 'dossiers.context_pack.attach'),
        ('methodology.dossiers.mark_ready', 'dossiers.lifecycle.transition'),
        ('methodology.dossiers.notebook.get', 'dossiers.notebook.get'),
        ('methodology.dossiers.notes.upsert', 'dossiers.notes.upsert'),
        ('methodology.dossiers.concepts.upsert', 'dossiers.concepts.upsert'),
        ('methodology.dossiers.claims.upsert', 'dossiers.claims.upsert'),
        ('methodology.dossiers.links.upsert', 'dossiers.links.upsert'),
        ('methodology.dossiers.navigate', 'dossiers.navigate'),
        ('methodology.dossiers.sync', 'dossiers.sync'),
        ('methodology.dossiers.health.submit', 'dossiers.health.submit')
)
UPDATE agent_internal_mcp_servers servers
SET tool_allowlist = COALESCE((
    SELECT jsonb_agg(COALESCE(tool_map.new_name, item.value) ORDER BY item.ordinality)
    FROM jsonb_array_elements_text(servers.tool_allowlist) WITH ORDINALITY AS item(value, ordinality)
    LEFT JOIN tool_map ON tool_map.old_name = item.value
), '[]'::jsonb)
WHERE servers.tool_allowlist::text LIKE '%methodology.dossiers.%';

DELETE FROM mcp_server_tools
WHERE tool_name LIKE 'methodology.dossiers.%';

UPDATE system_agents
SET system_prompt = replace(
        replace(system_prompt, 'methodology.dossiers.mark_ready', 'dossiers.lifecycle.transition'),
        'methodology.dossiers',
        'dossiers'
    ),
    definition = replace(
        replace(
            replace(definition::text, 'methodology.dossiers.mark_ready', 'dossiers.lifecycle.transition'),
            'methodology.dossiers',
            'dossiers'
        ),
        'methodology_research_dossier',
        'methodology_dossier'
    )::jsonb,
    metadata = replace(metadata::text, 'research_dossier', 'dossier')::jsonb,
    updated_at = NOW()
WHERE agent_key = 'researcher'
   OR metadata->>'agent_key' = 'researcher';

UPDATE agent_definition_versions
SET compiled_definition = replace(
        replace(
            replace(compiled_definition::text, 'methodology.dossiers.mark_ready', 'dossiers.lifecycle.transition'),
            'methodology.dossiers',
            'dossiers'
        ),
        'methodology_research_dossier',
        'methodology_dossier'
    )::jsonb,
    metadata = replace(metadata::text, 'research_dossier', 'dossier')::jsonb
WHERE agent_key = 'researcher'
   OR metadata->>'agent_key' = 'researcher';

-- migrate:down

ALTER TABLE IF EXISTS methodology_blueprint_versions
    DROP CONSTRAINT IF EXISTS methodology_blueprint_versions_dossier_fk;
ALTER TABLE IF EXISTS methodology_blueprint_versions
    DROP CONSTRAINT IF EXISTS methodology_blueprint_versions_status_check;
UPDATE methodology_blueprint_versions
SET status = 'ready_for_methodologist'
WHERE status = 'ready_for_draft';
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

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'methodology_blueprint_versions'
          AND column_name = 'dossier_id'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'methodology_blueprint_versions'
          AND column_name = 'research_dossier_id'
    ) THEN
        ALTER TABLE methodology_blueprint_versions
            RENAME COLUMN dossier_id TO research_dossier_id;
    END IF;
END $$;

ALTER TABLE IF EXISTS dossiers
    DROP CONSTRAINT IF EXISTS dossiers_status_check;
UPDATE dossiers
SET status = CASE status
    WHEN 'scoping' THEN 'researching'
    WHEN 'collecting' THEN 'researching'
    WHEN 'synthesizing' THEN 'researching'
    WHEN 'ready' THEN 'ready_for_methodologist'
    WHEN 'consumed' THEN 'completed'
    WHEN 'archived' THEN 'completed'
    ELSE status
END
WHERE status IN ('scoping', 'collecting', 'synthesizing', 'ready', 'consumed', 'archived');
ALTER TABLE dossiers
    ADD CONSTRAINT research_dossiers_status_check
    CHECK (status IN ('created', 'researching', 'ready_for_methodologist', 'completed', 'failed'));

ALTER TABLE IF EXISTS methodology_blueprint_versions
    ADD CONSTRAINT methodology_blueprint_versions_dossier_fk
    FOREIGN KEY (research_dossier_id)
    REFERENCES dossiers(dossier_id)
    ON DELETE SET NULL
    DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE IF EXISTS dossier_health_checks RENAME TO research_dossier_health_checks;
ALTER TABLE IF EXISTS dossier_sync_runs RENAME TO research_dossier_sync_runs;
ALTER TABLE IF EXISTS dossier_provider_external_refs RENAME TO research_dossier_provider_external_refs;
ALTER TABLE IF EXISTS dossier_provider_bindings RENAME TO research_dossier_provider_bindings;
ALTER TABLE IF EXISTS dossier_links RENAME TO research_dossier_links;
ALTER TABLE IF EXISTS dossier_claims RENAME TO research_dossier_claims;
ALTER TABLE IF EXISTS dossier_concepts RENAME TO research_dossier_concepts;
ALTER TABLE IF EXISTS dossier_notes RENAME TO research_dossier_notes;
ALTER TABLE IF EXISTS dossier_notebooks RENAME TO research_dossier_notebooks;
ALTER TABLE IF EXISTS dossier_events RENAME TO research_dossier_events;
ALTER TABLE IF EXISTS dossier_sources RENAME TO research_dossier_sources;
ALTER TABLE IF EXISTS dossiers RENAME TO research_dossiers;
