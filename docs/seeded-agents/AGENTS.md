# Seeded Agents Documentation Guide

This guide applies under `docs/seeded-agents/` and adds to the root and docs
guides.

## Managed Agent Documentation

- Operational/system-wide agents and managed specialist agents advertise their
  purpose through normal fields such as `display_name`, `role`, and
  `capabilities`.
- Profiles describe mandate, activation, authority, boundaries, handoffs, and
  knowledge layer. Profiles do not authorize anything.
- IAM role bindings, project access, workspace participant attachment, and
  MCP/tool allowlists are the authority for operational agents; role text is
  descriptive, not authorization.
- Runtime behavior must not branch on `agent_key`, display name, role text,
  capability text, or metadata tags.
- `Methodologist` outputs should separate source-grounded methodology basis,
  methodics, methods, tools, actors, and workspace templates.
- Source-derived Methodologist claims need cited retrieval/source evidence.
  Inferred tools or implementation ideas must be labeled as inference or
  ideation.
- `Conductor` is a separate managed global specialist for active workspace
  methodics execution. It must be explicitly attached through normal workspace
  agent attachment, and methodics execution must be explicitly started.
- Workspaces without attached Conductor have no active methodics execution loop.
- Passive `WorkspaceHarness.methodics` remains guidance only.
