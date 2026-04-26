UPDATE system_agents
SET endpoint = jsonb_set(
        jsonb_set(
            COALESCE(endpoint, '{}'::jsonb),
            '{engine_id}',
            '"local-ollama"'::jsonb,
            true
        ),
        '{provider}',
        '"ollama"'::jsonb,
        true
    ),
    definition = jsonb_set(
        jsonb_set(
            jsonb_set(
                jsonb_set(
                    COALESCE(definition, '{}'::jsonb),
                    '{runtime,engine_id}',
                    '"local-ollama"'::jsonb,
                    true
                ),
                '{runtime,provider}',
                '"ollama"'::jsonb,
                true
            ),
            '{runtime,preferred_capabilities}',
            '["local","ollama"]'::jsonb,
            true
        ),
        '{runtime,preferred_locality}',
        '"host"'::jsonb,
        true
    ),
    updated_at = NOW()
WHERE agent_key = 'anchor';
