-- migrate:up

UPDATE system_agents
SET endpoint = '{
        "kind": "system",
        "engine_id": "openai-responses",
        "provider": "openai",
        "model": "gpt-5.4-mini"
    }'::jsonb,
    definition = jsonb_set(
        COALESCE(definition, '{}'::jsonb),
        '{runtime}',
        '{
            "engine_id": "openai-responses",
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "required_capabilities": ["tool_calling", "reasoning"],
            "preferred_capabilities": ["responses-api", "vision", "image_input"],
            "preferred_locality": "cloud"
        }'::jsonb,
        true
    ),
    harness = jsonb_set(
        COALESCE(harness, '{}'::jsonb),
        '{compaction_policy}',
        '{
            "enabled": true,
            "strategy": "summary_plus_retrieval",
            "overflow_behavior": "auto_fallback",
            "max_estimated_input_tokens": 256000,
            "recent_message_count": 16,
            "min_recent_message_count": 4,
            "max_run_memory_entries": 8,
            "max_thread_memory_entries": 8,
            "max_workspace_memory_entries": 8,
            "summary_max_chars": 6000,
            "retrieval_limit": 8,
            "retrieval_provider_key": null
        }'::jsonb,
        true
    ),
    updated_at = NOW(),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"managed": true, "seeded": true, "runtime_provider": "openai", "runtime_model": "gpt-5.4-mini"}'::jsonb
WHERE agent_id IN (
    '44444444-4444-4444-4444-444444444447'::uuid,
    '44444444-4444-4444-4444-444444444449'::uuid
)
AND agent_key IN ('methodologist', 'researcher');

-- migrate:down

UPDATE system_agents
SET endpoint = '{
        "kind": "system",
        "engine_id": "local-ollama",
        "provider": "ollama"
    }'::jsonb,
    definition = jsonb_set(
        COALESCE(definition, '{}'::jsonb),
        '{runtime}',
        '{
            "engine_id": "local-ollama",
            "provider": "ollama",
            "preferred_capabilities": ["local", "ollama", "reasoning"],
            "preferred_locality": "host"
        }'::jsonb,
        true
    ),
    harness = COALESCE(harness, '{}'::jsonb) - 'compaction_policy',
    updated_at = NOW(),
    metadata = COALESCE(metadata, '{}'::jsonb)
        - 'runtime_provider'
        - 'runtime_model'
WHERE agent_id IN (
    '44444444-4444-4444-4444-444444444447'::uuid,
    '44444444-4444-4444-4444-444444444449'::uuid
)
AND agent_key IN ('methodologist', 'researcher');
