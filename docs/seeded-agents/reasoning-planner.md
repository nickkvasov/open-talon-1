# Reasoning Planner

## Agent Card

| Field | Value |
| --- | --- |
| Display name | `Reasoning Planner` |
| Agent id | `33333333-3333-3333-3333-333333333333` |
| Agent key | none |
| Scope | global |
| Role | `planning agent` |
| Endpoint | `openai-responses` through provider `openai` |
| Locality | cloud |
| Capabilities | `planning`, `triage`, `reasoning` |
| Metadata | `managed=true`, `seeded=true`, `example=true` |

## Idea

Reasoning Planner is the smallest seeded planning agent. It exists as a default
example and integration sentinel for provider-backed agent definitions, cloud
reasoning endpoint resolution, and interaction-contract persistence.

It is not a managed operational agent with private tools or administration
context. It is a normal system agent that can be attached and routed like other
agents when a workspace wants a general planning participant.

## Harness And Contract

Reasoning Planner does not seed an explicit `AgentHarness`. Its current behavior
is defined by:

- system prompt: plan carefully and explain tradeoffs clearly
- interaction instructions: operate from visible Open Talon context and state uncertainty
- response contract: markdown with `Summary`, `Findings`, and `Next action`
- runtime definition: `engine_id=openai-responses`, preferred capabilities `reasoning` and `tool_calling`, preferred locality `cloud`

Any future specialization should be added through the agent harness,
interaction contract, endpoint definition, or workspace attachment, not through
runtime code branches.

## Live Test Design

Reasoning Planner currently has no dedicated real-stack live test. The current
test design treats it as a seed/migration contract rather than an operational
workflow.

## What Is Tested

Primary coverage:

- [`tests/core-collab/test_repository_integration.py::test_repository_migrations_seed_default_reasoning_planner_agent`](../../tests/core-collab/test_repository_integration.py)

The test verifies:

- the seeded agent id exists after migrations
- display name is `Reasoning Planner`
- endpoint resolves to `openai-responses` and provider `openai`
- runtime definition prefers cloud locality
- response contract requires `Summary`, `Findings`, and `Next action`
- metadata marks the agent as seeded and example-backed
