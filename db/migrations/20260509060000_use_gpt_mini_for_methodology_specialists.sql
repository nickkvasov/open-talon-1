-- Use the lower-cost GPT mini model for methodology specialists.

-- migrate:up

UPDATE system_agents
SET
    endpoint = jsonb_set(
        jsonb_set(
            jsonb_set(
                COALESCE(endpoint, '{}'::jsonb),
                '{engine_id}',
                '"openai-responses"'::jsonb,
                true
            ),
            '{provider}',
            '"openai"'::jsonb,
            true
        ),
        '{model}',
        '"gpt-5.4-mini"'::jsonb,
        true
    ),
    definition = jsonb_set(
        jsonb_set(
            jsonb_set(
                jsonb_set(
                    COALESCE(definition, '{}'::jsonb),
                    '{runtime,engine_id}',
                    '"openai-responses"'::jsonb,
                    true
                ),
                '{runtime,provider}',
                '"openai"'::jsonb,
                true
            ),
            '{runtime,model}',
            '"gpt-5.4-mini"'::jsonb,
            true
        ),
        '{runtime,preferred_locality}',
        '"cloud"'::jsonb,
        true
    ),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"managed": true, "seeded": true, "runtime_provider": "openai", "runtime_model": "gpt-5.4-mini"}'::jsonb,
    updated_at = NOW()
WHERE scope = 'global'
  AND agent_key IN ('researcher', 'methodologist');

-- migrate:down

UPDATE system_agents
SET
    endpoint = jsonb_set(
        jsonb_set(
            jsonb_set(
                COALESCE(endpoint, '{}'::jsonb),
                '{engine_id}',
                '"openai-responses"'::jsonb,
                true
            ),
            '{provider}',
            '"openai"'::jsonb,
            true
        ),
        '{model}',
        '"gpt-5.4"'::jsonb,
        true
    ),
    definition = jsonb_set(
        jsonb_set(
            jsonb_set(
                jsonb_set(
                    COALESCE(definition, '{}'::jsonb),
                    '{runtime,engine_id}',
                    '"openai-responses"'::jsonb,
                    true
                ),
                '{runtime,provider}',
                '"openai"'::jsonb,
                true
            ),
            '{runtime,model}',
            '"gpt-5.4"'::jsonb,
            true
        ),
        '{runtime,preferred_locality}',
        '"cloud"'::jsonb,
        true
    ),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"managed": true, "seeded": true, "runtime_provider": "openai", "runtime_model": "gpt-5.4"}'::jsonb,
    updated_at = NOW()
WHERE scope = 'global'
  AND agent_key IN ('researcher', 'methodologist');
