-- migrate:up

WITH dossier_notebook_tools(tool_name) AS (
    VALUES
        ('methodology.dossiers.notebook.get'),
        ('methodology.dossiers.notes.upsert'),
        ('methodology.dossiers.concepts.upsert'),
        ('methodology.dossiers.claims.upsert'),
        ('methodology.dossiers.links.upsert'),
        ('methodology.dossiers.navigate'),
        ('methodology.dossiers.sync'),
        ('methodology.dossiers.health.submit')
)
INSERT INTO mcp_server_tools (
    server_id,
    tool_name,
    display_name,
    description,
    input_schema,
    output_schema,
    capability_hash,
    discovered_at,
    metadata
)
SELECT
    '66666666-6666-6666-6666-666666666666'::uuid,
    tool_name,
    tool_name,
    'Open Talon control-plane operation ' || tool_name || '.',
    '{}'::jsonb,
    '{}'::jsonb,
    'managed',
    NOW(),
    '{"seeded":true,"managed":true,"control_plane":true,"dossier_notebook":true}'::jsonb
FROM dossier_notebook_tools
WHERE EXISTS (
    SELECT 1
    FROM mcp_servers
    WHERE server_id = '66666666-6666-6666-6666-666666666666'::uuid
)
ON CONFLICT (server_id, tool_name) DO UPDATE
SET description = EXCLUDED.description,
    capability_hash = EXCLUDED.capability_hash,
    metadata = mcp_server_tools.metadata || EXCLUDED.metadata;

UPDATE agent_internal_mcp_servers
SET tool_allowlist = '[
      "session.get_identity",
      "session.get_permissions",
      "session.list_scopes",
      "session.set_scope",
      "organizations.get",
      "workspaces.list",
      "workspaces.get",
      "threads.get",
      "threads.timeline.get",
      "threads.messages.create",
      "methodology.dossiers.get",
      "methodology.dossiers.sources.create",
      "methodology.dossiers.sources.update",
      "methodology.dossiers.context_pack.attach",
      "methodology.dossiers.mark_ready",
      "methodology.dossiers.notebook.get",
      "methodology.dossiers.notes.upsert",
      "methodology.dossiers.concepts.upsert",
      "methodology.dossiers.claims.upsert",
      "methodology.dossiers.links.upsert",
      "methodology.dossiers.navigate",
      "methodology.dossiers.sync",
      "methodology.dossiers.health.submit"
    ]'::jsonb,
    updated_at = NOW(),
    metadata = metadata || '{"dossier_notebook":true}'::jsonb
WHERE system_agent_id = '44444444-4444-4444-4444-444444444449'::uuid
  AND server_id = '66666666-6666-6666-6666-666666666666'::uuid;

UPDATE agent_internal_mcp_servers
SET tool_allowlist = '[
      "session.get_identity",
      "session.get_permissions",
      "session.list_scopes",
      "session.set_scope",
      "organizations.get",
      "workspaces.get",
      "threads.get",
      "threads.timeline.get",
      "retrieval.context_pack.get",
      "methodology.dossiers.get",
      "methodology.dossiers.notebook.get",
      "methodology.dossiers.navigate",
      "methodology.blueprints.submit_draft"
    ]'::jsonb,
    updated_at = NOW(),
    metadata = metadata || '{"dossier_notebook":true}'::jsonb
WHERE system_agent_id = '44444444-4444-4444-4444-444444444447'::uuid
  AND server_id = '66666666-6666-6666-6666-666666666666'::uuid;

-- migrate:down

UPDATE agent_internal_mcp_servers
SET tool_allowlist = '[
      "session.get_identity",
      "session.get_permissions",
      "session.list_scopes",
      "session.set_scope",
      "organizations.get",
      "workspaces.list",
      "workspaces.get",
      "threads.get",
      "threads.timeline.get",
      "threads.messages.create",
      "methodology.dossiers.get",
      "methodology.dossiers.sources.create",
      "methodology.dossiers.sources.update",
      "methodology.dossiers.context_pack.attach",
      "methodology.dossiers.mark_ready"
    ]'::jsonb,
    updated_at = NOW()
WHERE system_agent_id = '44444444-4444-4444-4444-444444444449'::uuid
  AND server_id = '66666666-6666-6666-6666-666666666666'::uuid;

UPDATE agent_internal_mcp_servers
SET tool_allowlist = '[
      "session.get_identity",
      "session.get_permissions",
      "session.list_scopes",
      "session.set_scope",
      "organizations.get",
      "workspaces.get",
      "threads.get",
      "threads.timeline.get",
      "retrieval.context_pack.get",
      "methodology.dossiers.get",
      "methodology.blueprints.submit_draft"
    ]'::jsonb,
    updated_at = NOW()
WHERE system_agent_id = '44444444-4444-4444-4444-444444444447'::uuid
  AND server_id = '66666666-6666-6666-6666-666666666666'::uuid;

DELETE FROM mcp_server_tools
WHERE server_id = '66666666-6666-6666-6666-666666666666'::uuid
  AND tool_name IN (
      'methodology.dossiers.notebook.get',
      'methodology.dossiers.notes.upsert',
      'methodology.dossiers.concepts.upsert',
      'methodology.dossiers.claims.upsert',
      'methodology.dossiers.links.upsert',
      'methodology.dossiers.navigate',
      'methodology.dossiers.sync',
      'methodology.dossiers.health.submit'
  );
