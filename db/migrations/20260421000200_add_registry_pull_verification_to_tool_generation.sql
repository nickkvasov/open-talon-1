ALTER TABLE tool_generation_requests
    DROP CONSTRAINT IF EXISTS tool_generation_requests_status_check;

ALTER TABLE tool_generation_requests
    ADD CONSTRAINT tool_generation_requests_status_check
    CHECK (
        status IN (
            'submitted',
            'clarification_needed',
            'drafting',
            'validating',
            'pending_approval',
            'verifying_registry_pull',
            'published',
            'rejected',
            'failed'
        )
    );

ALTER TABLE tool_generation_revisions
    DROP CONSTRAINT IF EXISTS tool_generation_revisions_status_check;

ALTER TABLE tool_generation_revisions
    ADD CONSTRAINT tool_generation_revisions_status_check
    CHECK (
        status IN (
            'drafting',
            'validating',
            'pending_approval',
            'verifying_registry_pull',
            'approved',
            'rejected',
            'failed'
        )
    );

INSERT INTO system_tools (
    tool_id,
    scope,
    organization_id,
    name,
    description,
    parameter_contract,
    input_schema,
    backend_kind,
    handler_ref,
    execution_profile,
    trust_level,
    created_by,
    created_at,
    updated_by,
    updated_at,
    metadata
)
VALUES (
    '55555555-5555-5555-5555-555555555558',
    'global',
    NULL,
    'tinker_generated_tool_registry_pull_verify',
    'Verify that a generated tool image can be pulled from the configured OCI registry by a real worker.',
    '{"parameters":[],"additional_properties":true}'::jsonb,
    '{}'::jsonb,
    'local_process',
    'python',
    '{
      "command": ["python", "-m", "agent_runtime.tinker_tools", "verify-registry-pull"],
      "timeout_seconds": 300,
      "network": "full",
      "workspace_access": "none"
    }'::jsonb,
    'trusted',
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '{"managed":true,"seeded":true,"internal_only":true}'::jsonb
)
ON CONFLICT (tool_id) DO NOTHING;

INSERT INTO agent_internal_tools (
    system_agent_id,
    tool_id,
    enabled,
    attached_by,
    attached_at,
    updated_at,
    metadata
)
VALUES (
    '44444444-4444-4444-4444-444444444444',
    '55555555-5555-5555-5555-555555555558',
    TRUE,
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    NOW(),
    '{"managed":true,"seeded":true}'::jsonb
)
ON CONFLICT (system_agent_id, tool_id) DO NOTHING;
