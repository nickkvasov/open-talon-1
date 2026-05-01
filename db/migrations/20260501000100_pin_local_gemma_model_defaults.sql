UPDATE llm_providers
SET default_model = 'gemma4:31b',
    updated_at = NOW()
WHERE scope = 'global'
  AND organization_id IS NULL
  AND engine_id = 'local-ollama'
  AND default_model = 'gemma4:latest';
