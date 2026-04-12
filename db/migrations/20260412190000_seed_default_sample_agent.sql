INSERT INTO system_agents (
    agent_id,
    display_name,
    description,
    role,
    capabilities,
    endpoint,
    system_prompt,
    interaction_contract,
    definition,
    created_by,
    created_at,
    updated_at,
    metadata
)
VALUES (
    '33333333-3333-3333-3333-333333333333',
    'Reasoning Planner',
    'Plans multi-step work with cloud reasoning.',
    'planning agent',
    '["planning","triage","reasoning"]'::jsonb,
    '{
      "kind": "remote",
      "engine_id": "openai-responses",
      "provider": "openai"
    }'::jsonb,
    'You plan carefully and explain tradeoffs clearly.',
    '{
      "instructions": [
        "Operate as Reasoning Planner, fulfilling the role planning agent.",
        "Use only the provided Open Talon execution context and be explicit about uncertainty.",
        "Return a collaborator-friendly reply suitable for the shared thread."
      ],
      "response_contract": {
        "format": "markdown",
        "title": "Planning Agent Response",
        "required_sections": ["Summary", "Findings", "Next action"],
        "guidance": [
          "Keep the response concise and thread-ready.",
          "Reference concrete evidence from the visible context when possible."
        ],
        "json_schema": {}
      },
      "completion_criteria": [
        "Address the latest visible request.",
        "Explain evidence or lack of evidence clearly.",
        "Make the next action obvious to collaborators."
      ],
      "metadata": {
        "contract_version": 1,
        "generated": true
      }
    }'::jsonb,
    '{
      "runtime": {
        "engine_id": "openai-responses",
        "preferred_capabilities": ["reasoning", "tool_calling"],
        "preferred_locality": "cloud"
      },
      "seeded": true
    }'::jsonb,
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    NOW(),
    '{"managed":true,"seeded":true,"example":true}'::jsonb
)
ON CONFLICT (agent_id) DO NOTHING;
