CREATE TABLE IF NOT EXISTS publication_reviews (
    review_id UUID PRIMARY KEY,
    review_kind TEXT NOT NULL,
    workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    thread_id UUID NOT NULL REFERENCES threads(thread_id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES timeline_messages(message_id) ON DELETE CASCADE,
    reviewer_system_agent_id UUID NOT NULL REFERENCES system_agents(agent_id) ON DELETE RESTRICT,
    candidate_actor_participant_id UUID NOT NULL REFERENCES participants(participant_id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    level TEXT NOT NULL,
    status TEXT NOT NULL,
    decision TEXT,
    relatedness TEXT NOT NULL DEFAULT 'unknown',
    confidence DOUBLE PRECISION,
    reason TEXT,
    issuer_explanation TEXT,
    policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT publication_reviews_confidence_range
        CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0))
);

CREATE INDEX IF NOT EXISTS idx_publication_reviews_workspace_created
    ON publication_reviews(workspace_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_publication_reviews_message
    ON publication_reviews(message_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_publication_reviews_kind_status_created
    ON publication_reviews(review_kind, status, created_at DESC);

UPDATE workspaces
SET harness = COALESCE(harness, '{}'::jsonb)
    || jsonb_build_object(
        'version',
        COALESCE(harness->'version', '1'::jsonb),
        'moderation_policy',
        COALESCE(
            harness->'moderation_policy',
            '{
              "enabled": true,
              "level": "balanced",
              "topic": null,
              "allowed_adjacent_topics": [],
              "blocked_topics": [],
              "explain_blocked_messages": true
            }'::jsonb
        )
    )
WHERE harness IS NULL
   OR NOT (harness ? 'moderation_policy');

UPDATE system_agents
SET description = 'Builds new agent-usable tools from workspace requests, validates generated tools, and submits reviewable revisions for catalog approval.',
    role = 'generated tool authoring and validation agent',
    capabilities = '[
      "generates new agent-usable tools from workspace requests",
      "checks whether existing tools already satisfy a request",
      "validates generated tools before approval",
      "submits generated tool revisions for catalog review",
      "reports trust network and workspace-access rationale for generated tools"
    ]'::jsonb,
    updated_at = NOW(),
    metadata = metadata || '{"managed":true,"agent_key":"tinker"}'::jsonb
WHERE agent_key = 'tinker'
   OR metadata->>'agent_key' = 'tinker'
   OR metadata->>'tool_generation_agent' = 'true';

UPDATE system_agents
SET description = 'Manages platform-wide Open Talon operations through authorized control-plane APIs and private MCP tools.',
    role = 'platform operations steward',
    capabilities = '[
      "manages platform operations through authorized control-plane tools",
      "reviews platform runtime and audit health",
      "coordinates system-wide catalog and provider administration",
      "repairs managed administration contexts when authorized",
      "keeps tenant IAM audit and secret boundaries explicit"
    ]'::jsonb,
    updated_at = NOW(),
    metadata = metadata || '{"managed":true,"agent_key":"steward"}'::jsonb
WHERE agent_key = 'steward'
   OR metadata->>'agent_key' = 'steward';

UPDATE system_agents
SET description = 'Manages organization-scoped projects, workspaces, and operational context through authorized control-plane APIs and private MCP tools.',
    role = 'organization operations curator',
    capabilities = '[
      "manages organization projects and workspaces through authorized control-plane tools",
      "coordinates organization-scoped workspace administration",
      "reviews organization audit and runtime health",
      "keeps organization resources inside tenant boundaries",
      "maintains managed organization operations contexts"
    ]'::jsonb,
    updated_at = NOW(),
    metadata = metadata || '{"managed":true,"agent_key":"curator"}'::jsonb
WHERE agent_key = 'curator'
   OR metadata->>'agent_key' = 'curator';

INSERT INTO system_agents (
    agent_id,
    agent_key,
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
    '44444444-4444-4444-4444-444444444446'::uuid,
    'anchor',
    'global',
    NULL,
    'Anchor',
    'Reviews workspace communication for topic fit, applies the workspace topic-freedom policy, and explains blocked messages when configured.',
    'workspace topic alignment reviewer',
    '[
      "reviews messages for alignment with the workspace topic",
      "applies strict balanced or open topic-freedom policy",
      "blocks off-topic messages before publication in strict workspaces",
      "flags conversation drift after publication in balanced and open workspaces",
      "privately explains blocked messages to the issuer when enabled"
    ]'::jsonb,
    '{"kind":"system","engine_id":"local-ollama","provider":"ollama"}'::jsonb,
    'You are Anchor. Review the supplied candidate workspace communication only for fit with the workspace topic and moderation policy. Do not provide general safety review, style review, or task assistance. Return only the JSON object required by your response contract.',
    '{
      "version": 1,
      "summary": "Reviews candidate workspace communication for topic fit using the workspace moderation policy.",
      "operating_principles": [
        "Judge topic relevance, not general quality or style.",
        "Use the workspace topic, description, harness, and configured policy as the authority.",
        "Prefer allowing messages when relevance is plausible outside strict mode.",
        "Give concise, actionable issuer guidance when a strict-mode message is blocked."
      ],
      "planning": {
        "plan_before_act": false,
        "incremental_execution": false,
        "one_goal_at_a_time": true,
        "explicit_uncertainty": true
      },
      "tool_use_policy": {
        "prefer_existing_workspace_tools": false,
        "read_before_write": false,
        "inspect_schema_before_use": false,
        "cite_tool_results_in_reasoning": false,
        "verify_side_effects_after_mutation": false,
        "selection_principles": [
          "Do not call workspace tools during ordinary topic review.",
          "Use only the moderation context supplied with the task."
        ],
        "fallback_when_no_tool_fits": "Return a structured moderation decision from the supplied context."
      },
      "memory_policy": {
        "use_run_memory": false,
        "use_thread_memory": true,
        "use_workspace_memory": false
      },
      "validation_policy": {
        "require_evidence_for_claims": true,
        "require_tool_results_for_completion": false,
        "require_tests_before_done": false
      },
      "stop_policy": {
        "completion_conditions": [
          "Return one structured moderation decision for the candidate message."
        ],
        "stop_conditions": [
          "Do not continue into conversation or task assistance."
        ],
        "max_turns": 1
      },
      "metadata": {
        "managed": true,
        "agent_key": "anchor",
        "moderation_agent": true
      }
    }'::jsonb,
    '{
      "instructions": [
        "Review only the supplied candidate message for workspace-topic fit.",
        "Apply the workspace moderation policy supplied in task instructions.",
        "Return only a JSON moderation decision."
      ],
      "response_contract": {
        "format": "json",
        "title": "Topic moderation decision",
        "required_sections": [],
        "guidance": [
          "Use decision=allow when the message fits the topic policy.",
          "Use decision=block for strict-mode messages that must not be published.",
          "Use decision=flag for balanced or open mode messages that should remain visible but be marked as drift."
        ],
        "json_schema": {
          "type": "object",
          "additionalProperties": false,
          "required": ["decision", "relatedness", "confidence", "reason"],
          "properties": {
            "decision": {"type": "string", "enum": ["allow", "block", "flag"]},
            "relatedness": {"type": "string", "enum": ["direct", "adjacent", "unrelated", "blocked_topic", "unknown"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
            "issuer_explanation": {"type": "string"}
          }
        }
      },
      "completion_criteria": [
        "The decision matches the supplied workspace topic-freedom policy.",
        "The reason cites concrete topic fit or topic drift without exposing hidden policy data."
      ],
      "metadata": {
        "contract_version": 1,
        "seeded": true,
        "agent_key": "anchor"
      }
    }'::jsonb,
    '{
      "runtime": {
        "engine_id": "local-ollama",
        "provider": "ollama",
        "preferred_capabilities": ["local", "ollama"],
        "preferred_locality": "host"
      },
      "seeded": true,
      "managed": true,
      "agent_key": "anchor",
      "moderation_agent": true,
      "task_routing": {
        "normal_message_fanout": false,
        "accepted_task_kinds": ["workspace_topic_moderation"]
      }
    }'::jsonb,
    '00000000-0000-0000-0000-000000000000',
    NOW(),
    NOW(),
    '{"managed":true,"seeded":true,"agent_key":"anchor","moderation_agent":true}'::jsonb
)
ON CONFLICT (agent_id) DO UPDATE
SET agent_key = EXCLUDED.agent_key,
    scope = EXCLUDED.scope,
    organization_id = EXCLUDED.organization_id,
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    role = EXCLUDED.role,
    capabilities = EXCLUDED.capabilities,
    endpoint = EXCLUDED.endpoint,
    system_prompt = EXCLUDED.system_prompt,
    harness = EXCLUDED.harness,
    interaction_contract = EXCLUDED.interaction_contract,
    definition = EXCLUDED.definition,
    updated_at = NOW(),
    metadata = system_agents.metadata || EXCLUDED.metadata;

WITH anchor AS (
    SELECT agent_id, description, role, capabilities, endpoint, system_prompt, harness, definition
    FROM system_agents
    WHERE agent_key = 'anchor'
    LIMIT 1
),
workspace_anchor_participants AS (
    SELECT
        (
            SUBSTRING(MD5('open-talon-anchor-participant:' || workspace_id::text), 1, 8)
            || '-' || SUBSTRING(MD5('open-talon-anchor-participant:' || workspace_id::text), 9, 4)
            || '-' || SUBSTRING(MD5('open-talon-anchor-participant:' || workspace_id::text), 13, 4)
            || '-' || SUBSTRING(MD5('open-talon-anchor-participant:' || workspace_id::text), 17, 4)
            || '-' || SUBSTRING(MD5('open-talon-anchor-participant:' || workspace_id::text), 21, 12)
        )::uuid AS participant_id,
        workspace_id
    FROM workspaces
)
INSERT INTO participants (
    participant_id,
    workspace_id,
    participant_type,
    user_id,
    system_agent_id,
    description,
    roles,
    capabilities,
    status,
    visibility_scope,
    created_at,
    updated_at,
    metadata
)
SELECT
    workspace_anchor_participants.participant_id,
    workspace_anchor_participants.workspace_id,
    'agent',
    NULL,
    anchor.agent_id,
    anchor.description,
    to_jsonb(ARRAY[anchor.role]::text[]),
    anchor.capabilities,
    'active',
    'workspace',
    NOW(),
    NOW(),
    '{
      "seeded": true,
      "managed": true,
      "agent_key": "anchor",
      "task_routing": {
        "normal_message_fanout": false,
        "accepted_task_kinds": ["workspace_topic_moderation"]
      }
    }'::jsonb
FROM workspace_anchor_participants
CROSS JOIN anchor
ON CONFLICT (participant_id) DO UPDATE
SET system_agent_id = EXCLUDED.system_agent_id,
    description = EXCLUDED.description,
    roles = EXCLUDED.roles,
    capabilities = EXCLUDED.capabilities,
    status = EXCLUDED.status,
    visibility_scope = EXCLUDED.visibility_scope,
    updated_at = NOW(),
    metadata = participants.metadata || EXCLUDED.metadata;
