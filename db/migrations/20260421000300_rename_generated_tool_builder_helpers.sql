UPDATE system_tools
SET
    name = CASE tool_id
        WHEN '55555555-5555-5555-5555-555555555551' THEN 'generated_tool_repo_bootstrap'
        WHEN '55555555-5555-5555-5555-555555555552' THEN 'generated_tool_repo_write'
        WHEN '55555555-5555-5555-5555-555555555553' THEN 'generated_tool_build'
        WHEN '55555555-5555-5555-5555-555555555554' THEN 'generated_tool_registry_push'
        WHEN '55555555-5555-5555-5555-555555555555' THEN 'generated_tool_smoke_test'
        WHEN '55555555-5555-5555-5555-555555555556' THEN 'generated_tool_asset_publish'
        WHEN '55555555-5555-5555-5555-555555555557' THEN 'generated_tool_request_status_update'
        WHEN '55555555-5555-5555-5555-555555555558' THEN 'generated_tool_registry_pull_verify'
        ELSE name
    END,
    description = CASE tool_id
        WHEN '55555555-5555-5555-5555-555555555551' THEN 'Bootstrap or refresh the generated-tools worktree for a tool-generation request.'
        WHEN '55555555-5555-5555-5555-555555555552' THEN 'Write or patch generated tool source files inside the generated-tools repository.'
        WHEN '55555555-5555-5555-5555-555555555553' THEN 'Build a generated tool image and capture the resulting image reference and digest.'
        WHEN '55555555-5555-5555-5555-555555555554' THEN 'Push a generated tool image to the configured OCI registry.'
        WHEN '55555555-5555-5555-5555-555555555555' THEN 'Run generated-tool smoke tests against the built image before approval.'
        WHEN '55555555-5555-5555-5555-555555555556' THEN 'Publish generated-tool source, manifest, and validation report assets.'
        WHEN '55555555-5555-5555-5555-555555555557' THEN 'Update tool-generation request and revision status as the generated-tool agent progresses work.'
        WHEN '55555555-5555-5555-5555-555555555558' THEN 'Verify that a generated tool image can be pulled from the configured OCI registry by a real worker.'
        ELSE description
    END,
    execution_profile = jsonb_set(
        execution_profile,
        '{command,2}',
        to_jsonb('generated_tools_builder.cli'::text),
        false
    ),
    updated_at = NOW()
WHERE tool_id IN (
    '55555555-5555-5555-5555-555555555551',
    '55555555-5555-5555-5555-555555555552',
    '55555555-5555-5555-5555-555555555553',
    '55555555-5555-5555-5555-555555555554',
    '55555555-5555-5555-5555-555555555555',
    '55555555-5555-5555-5555-555555555556',
    '55555555-5555-5555-5555-555555555557',
    '55555555-5555-5555-5555-555555555558'
);
