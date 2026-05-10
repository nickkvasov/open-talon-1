-- migrate:up

UPDATE system_agents
SET harness = jsonb_set(
        COALESCE(harness, '{}'::jsonb),
        '{compaction_policy}',
        jsonb_build_object(
            'enabled', true,
            'strategy', 'summary_plus_retrieval',
            'overflow_behavior', 'auto_fallback',
            'max_estimated_input_tokens',
                CASE
                    WHEN agent_key = 'researcher' THEN 256000
                    WHEN agent_key = 'methodologist' THEN 256000
                    ELSE 256000
                END,
            'recent_message_count', 16,
            'min_recent_message_count', 4,
            'max_run_memory_entries', 8,
            'max_thread_memory_entries', 8,
            'max_workspace_memory_entries', 8,
            'summary_max_chars', 6000,
            'retrieval_limit', 8,
            'retrieval_provider_key', NULL
        ),
        true
    ),
    updated_at = NOW(),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || jsonb_build_object(
            'managed', true,
            'seeded', true,
            'compaction_policy_source', 'managed_agent_object'
        )
WHERE agent_id IN (
    '44444444-4444-4444-4444-444444444447'::uuid,
    '44444444-4444-4444-4444-444444444449'::uuid
)
AND agent_key IN ('methodologist', 'researcher');

-- migrate:down

UPDATE system_agents
SET harness = jsonb_set(
        COALESCE(harness, '{}'::jsonb),
        '{compaction_policy,max_estimated_input_tokens}',
        '12000'::jsonb,
        true
    ),
    updated_at = NOW(),
    metadata = COALESCE(metadata, '{}'::jsonb)
        - 'compaction_policy_source'
WHERE agent_id IN (
    '44444444-4444-4444-4444-444444444447'::uuid,
    '44444444-4444-4444-4444-444444444449'::uuid
)
AND agent_key IN ('methodologist', 'researcher');
