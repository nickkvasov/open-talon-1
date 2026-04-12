INSERT INTO llm_providers (
    provider_id,
    engine_id,
    display_name,
    description,
    provider,
    endpoint_kind,
    url,
    default_model,
    capabilities,
    locality,
    priority,
    enabled,
    secret_config,
    created_by,
    created_at,
    updated_by,
    updated_at,
    metadata
)
VALUES (
    '11111111-1111-1111-1111-111111111111',
    'local-ollama',
    'Local Ollama',
    'Host-local Ollama generation endpoint.',
    'ollama',
    'local',
    'http://127.0.0.1:11434/api/generate',
    'gemma4:latest',
    '["chat","completion","local","host","ollama"]'::jsonb,
    'host',
    100,
    TRUE,
    '{}'::jsonb,
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '{"managed":true,"seeded":true}'::jsonb
)
ON CONFLICT (engine_id) DO NOTHING;

INSERT INTO llm_providers (
    provider_id,
    engine_id,
    display_name,
    description,
    provider,
    endpoint_kind,
    url,
    default_model,
    capabilities,
    locality,
    priority,
    enabled,
    secret_config,
    created_by,
    created_at,
    updated_by,
    updated_at,
    metadata
)
VALUES (
    '22222222-2222-2222-2222-222222222222',
    'openai-responses',
    'OpenAI Responses',
    'Cloud OpenAI Responses API provider.',
    'openai',
    'remote',
    'https://api.openai.com/v1/responses',
    'gpt-5.4-mini',
    '["chat","completion","tool_calling","reasoning","responses-api","model:gpt-5.4-mini"]'::jsonb,
    'cloud',
    220,
    TRUE,
    '{
      "env": {"name": "OPENAI_API_KEY"},
      "openbao": {
        "mount": "secret",
        "path": "open-talon/llm/openai",
        "field": "api_key"
      }
    }'::jsonb,
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    '{"managed":true,"seeded":true}'::jsonb
)
ON CONFLICT (engine_id) DO NOTHING;
