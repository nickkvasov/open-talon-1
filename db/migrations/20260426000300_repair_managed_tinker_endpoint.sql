UPDATE system_agents
SET agent_key = 'tinker',
    endpoint = '{"kind":"system","engine_id":"openai-responses","provider":"openai"}'::jsonb,
    definition = COALESCE(definition, '{}'::jsonb)
        || '{
          "runtime": {
            "engine_id": "openai-responses",
            "preferred_capabilities": ["reasoning", "tool_calling"],
            "preferred_locality": "cloud"
          },
          "seeded": true,
          "tool_generation_agent": true
        }'::jsonb,
    updated_at = NOW(),
    metadata = COALESCE(metadata, '{}'::jsonb)
        || '{"managed":true,"seeded":true,"tool_generation_agent":true,"agent_key":"tinker","system_test_harness":false}'::jsonb
WHERE agent_id = '44444444-4444-4444-4444-444444444444'::uuid
  AND (
      agent_key IS DISTINCT FROM 'tinker'
      OR endpoint->>'provider' = 'system-test-harness'
      OR metadata->>'system_test_harness' = 'true'
  );
