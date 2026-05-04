# Generated Tools Builder Guide

This guide applies under `services/generated-tools-builder/` and adds to the
root and service guides.

## Tinker Boundaries

- Tinker-generated tools may publish to `global` or `organization` scope, but
  approval publishes into the system catalog only.
- Tinker revision approval requires `tool_generation.review` plus
  `tool_catalog.write` in the target publication scope.
- Tinker-generated tools must not be auto-attached to a workspace as part of
  approval; manual workspace attachment is a separate action.
- Tinker authoring/build helpers are agent-internal tools and must not be exposed
  through `workspace_tools` or the normal workspace catalog.
- Preserve global and organization-scoped publication paths separately when
  scope behavior changes.

## Tests

- Run `tests/core-collab/test_agent_contracts.py`,
  `tests/gateway-edge/test_tool_generation.py`, and
  `tests/business-cases/test_tinker_tool_generation.py` for generated-tool
  behavior changes.
- Run `tests/agent-runtime/test_execution.py` when local helper execution or
  execution backends change.
