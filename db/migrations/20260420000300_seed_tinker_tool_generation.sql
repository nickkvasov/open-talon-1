INSERT INTO system_agents (
    agent_id,
    scope,
    organization_id,
    display_name,
    description,
    role,
    capabilities,
    endpoint,
    system_prompt,
    harness,
    interaction_contract,
    definition,
    created_by,
    created_at,
    updated_at,
    metadata
)
VALUES (
    '44444444-4444-4444-4444-444444444444',
    'global',
    NULL,
    'Tinker',
    'Builds new agent-usable tools on demand, validates them, and submits them for approval.',
    'tool generation agent',
    '["tool_generation","tool_validation","tool_catalog","tool_authoring"]'::jsonb,
    '{
      "kind": "system",
      "engine_id": "openai-responses",
      "provider": "openai"
    }'::jsonb,
    'You are Tinker. Reuse existing tools when they already satisfy the need. Ask clarifying questions when requirements are incomplete. When authoring a new tool, produce reviewable revisions, capture trust/network rationale, and prepare concise status updates for the shared thread.',
    '{
      "version": 1,
      "summary": "Global tool generation harness for Tinker.",
      "operating_principles": [
        "Prefer existing visible tools before creating a new one.",
        "Ask follow-up questions when requirements are ambiguous or missing.",
        "Use internal authoring helpers instead of assuming local side effects succeeded.",
        "Do not claim publication until validation evidence exists."
      ],
      "tool_use_policy": {
        "prefer_existing_workspace_tools": true,
        "read_before_write": true,
        "inspect_schema_before_use": true,
        "cite_tool_results_in_reasoning": true,
        "verify_side_effects_after_mutation": true
      },
      "validation_policy": {
        "required_checks": [
          "confirm whether an existing catalog tool already satisfies the request",
          "justify requested network or read_write access",
          "capture validation evidence before moving to pending approval"
        ],
        "require_evidence_for_claims": true,
        "require_tool_results_for_completion": true,
        "require_tests_before_done": true
      },
      "metadata": {
        "seeded": true,
        "tool_generation_agent": true
      }
    }'::jsonb,
    '{
      "instructions": [
        "Operate as Tinker, the system-wide tool generation agent.",
        "Reuse an existing visible tool when that is sufficient.",
        "If requirements are incomplete, create interaction requests instead of guessing.",
        "When proposing a generated tool, summarize trust, network, workspace access, validation, and artifacts."
      ],
      "response_contract": {
        "format": "markdown",
        "title": "Tinker Update",
        "required_sections": ["Summary", "Status"],
        "guidance": [
          "Keep thread replies concise and operational.",
          "Make approval state and next action obvious."
        ],
        "json_schema": {}
      },
      "completion_criteria": [
        "Either identify an existing tool that satisfies the need or advance a generated-tool request.",
        "Leave a clear next action for the user or platform admin."
      ],
      "metadata": {
        "contract_version": 1,
        "seeded": true
      }
    }'::jsonb,
    '{
      "runtime": {
        "engine_id": "openai-responses",
        "preferred_capabilities": ["reasoning", "tool_calling"],
        "preferred_locality": "cloud"
      },
      "seeded": true,
      "tool_generation_agent": true
    }'::jsonb,
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    NOW(),
    '{"managed":true,"seeded":true,"tool_generation_agent":true}'::jsonb
)
ON CONFLICT (agent_id) DO NOTHING;

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
VALUES
(
    '55555555-5555-5555-5555-555555555551',
    'global',
    NULL,
    'tinker_generated_repo_bootstrap',
    'Bootstrap or refresh the generated-tools worktree for a tool-generation request.',
    '{"parameters":[],"additional_properties":true}'::jsonb,
    '{}'::jsonb,
    'local_process',
    'python',
    '{
      "command": ["python", "-m", "agent_runtime.tinker_tools", "bootstrap-worktree"],
      "timeout_seconds": 120,
      "network": "none",
      "workspace_access": "none"
    }'::jsonb,
    'trusted',
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '{"managed":true,"seeded":true,"internal_only":true}'::jsonb
),
(
    '55555555-5555-5555-5555-555555555552',
    'global',
    NULL,
    'tinker_generated_repo_write',
    'Write or patch generated tool source files inside the generated-tools repository.',
    '{"parameters":[],"additional_properties":true}'::jsonb,
    '{}'::jsonb,
    'local_process',
    'python',
    '{
      "command": ["python", "-m", "agent_runtime.tinker_tools", "write-files"],
      "timeout_seconds": 120,
      "network": "none",
      "workspace_access": "none"
    }'::jsonb,
    'trusted',
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '{"managed":true,"seeded":true,"internal_only":true}'::jsonb
),
(
    '55555555-5555-5555-5555-555555555553',
    'global',
    NULL,
    'tinker_generated_tool_build',
    'Build a generated tool image and capture the resulting image reference and digest.',
    '{"parameters":[],"additional_properties":true}'::jsonb,
    '{}'::jsonb,
    'local_process',
    'python',
    '{
      "command": ["python", "-m", "agent_runtime.tinker_tools", "build-image"],
      "timeout_seconds": 600,
      "network": "none",
      "workspace_access": "none"
    }'::jsonb,
    'trusted',
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '{"managed":true,"seeded":true,"internal_only":true}'::jsonb
),
(
    '55555555-5555-5555-5555-555555555554',
    'global',
    NULL,
    'tinker_generated_tool_registry_push',
    'Push a generated tool image to the configured Forgejo container registry.',
    '{"parameters":[],"additional_properties":true}'::jsonb,
    '{}'::jsonb,
    'local_process',
    'python',
    '{
      "command": ["python", "-m", "agent_runtime.tinker_tools", "push-image"],
      "timeout_seconds": 600,
      "network": "full",
      "workspace_access": "none"
    }'::jsonb,
    'trusted',
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '{"managed":true,"seeded":true,"internal_only":true}'::jsonb
),
(
    '55555555-5555-5555-5555-555555555555',
    'global',
    NULL,
    'tinker_generated_tool_smoke_test',
    'Run generated-tool smoke tests against the built image before approval.',
    '{"parameters":[],"additional_properties":true}'::jsonb,
    '{}'::jsonb,
    'local_process',
    'python',
    '{
      "command": ["python", "-m", "agent_runtime.tinker_tools", "smoke-test"],
      "timeout_seconds": 300,
      "network": "none",
      "workspace_access": "none"
    }'::jsonb,
    'trusted',
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '{"managed":true,"seeded":true,"internal_only":true}'::jsonb
),
(
    '55555555-5555-5555-5555-555555555556',
    'global',
    NULL,
    'tinker_generated_tool_asset_publish',
    'Publish generated-tool source, manifest, and validation report assets.',
    '{"parameters":[],"additional_properties":true}'::jsonb,
    '{}'::jsonb,
    'local_process',
    'python',
    '{
      "command": ["python", "-m", "agent_runtime.tinker_tools", "publish-assets"],
      "timeout_seconds": 300,
      "network": "none",
      "workspace_access": "none"
    }'::jsonb,
    'trusted',
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '{"managed":true,"seeded":true,"internal_only":true}'::jsonb
),
(
    '55555555-5555-5555-5555-555555555557',
    'global',
    NULL,
    'tinker_tool_request_status_update',
    'Update tool-generation request and revision status as Tinker progresses work.',
    '{"parameters":[],"additional_properties":true}'::jsonb,
    '{}'::jsonb,
    'local_process',
    'python',
    '{
      "command": ["python", "-m", "agent_runtime.tinker_tools", "update-request-status"],
      "timeout_seconds": 60,
      "network": "none",
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
VALUES
    ('44444444-4444-4444-4444-444444444444', '55555555-5555-5555-5555-555555555551', TRUE, '00000000-0000-0000-0000-000000000000', NOW(), NOW(), '{"managed":true,"seeded":true}'::jsonb),
    ('44444444-4444-4444-4444-444444444444', '55555555-5555-5555-5555-555555555552', TRUE, '00000000-0000-0000-0000-000000000000', NOW(), NOW(), '{"managed":true,"seeded":true}'::jsonb),
    ('44444444-4444-4444-4444-444444444444', '55555555-5555-5555-5555-555555555553', TRUE, '00000000-0000-0000-0000-000000000000', NOW(), NOW(), '{"managed":true,"seeded":true}'::jsonb),
    ('44444444-4444-4444-4444-444444444444', '55555555-5555-5555-5555-555555555554', TRUE, '00000000-0000-0000-0000-000000000000', NOW(), NOW(), '{"managed":true,"seeded":true}'::jsonb),
    ('44444444-4444-4444-4444-444444444444', '55555555-5555-5555-5555-555555555555', TRUE, '00000000-0000-0000-0000-000000000000', NOW(), NOW(), '{"managed":true,"seeded":true}'::jsonb),
    ('44444444-4444-4444-4444-444444444444', '55555555-5555-5555-5555-555555555556', TRUE, '00000000-0000-0000-0000-000000000000', NOW(), NOW(), '{"managed":true,"seeded":true}'::jsonb),
    ('44444444-4444-4444-4444-444444444444', '55555555-5555-5555-5555-555555555557', TRUE, '00000000-0000-0000-0000-000000000000', NOW(), NOW(), '{"managed":true,"seeded":true}'::jsonb)
ON CONFLICT (system_agent_id, tool_id) DO NOTHING;
