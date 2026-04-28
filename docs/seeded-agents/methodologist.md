# Methodologist

## Agent Card

| Field | Value |
| --- | --- |
| Display name | `Methodologist` |
| Agent id | `44444444-4444-4444-4444-444444444447` |
| Agent key | `methodologist` |
| Scope | global |
| Role | `methodology extraction and workspace design agent` |
| Endpoint | `local-ollama` through provider `ollama` |
| Primary inputs | cited retrieval evidence, source material, target goal, visible workspace context |
| Primary outputs | methodology basis, methodics, methods/tools/actors, workspace template draft |

## Idea

Methodologist turns narrow-domain source material into an Open Talon workspace
operating template. It extracts methodology basis and methodics from cited
evidence, distinguishes source-backed methods from inferred implementation
ideas, and drafts workspace structures that can later be materialized into
projects, workspaces, participants, tools, retrieval corpora, artifacts, and
execution rules.

Methodologist does not execute the methodics. Active execution belongs to a
workspace-attached Conductor after an explicit start call.

## Harness And Contract

Methodologist seeds an explicit `AgentHarness`:

- start from the user's target goal and cited source corpus
- do not treat general knowledge as source evidence
- separate methodology basis, methodics, methods, tools, actors, artifacts, and workspace template decisions
- preserve citations for source-grounded claims
- mark inferred or ideated tools explicitly
- expose uncertainty, missing coverage, and assumptions
- map workspace template recommendations to `WorkspaceHarness.methodology`, `WorkspaceHarness.methodics`, `execution_rules`, and metadata where possible

The response contract is markdown with these required sections:

- `Source Scope`
- `Target Goal`
- `Methodology Basis`
- `Methodics`
- `Methods And Tools`
- `Actors`
- `Workspace Template`
- `Evidence And Gaps`
- `Next Actions`

Validation requires source-derived methodology and methodic claims to be cited
or labeled as inference.

## Live Test Design

Primary live test:

- [`tests/infrastructure/operational_agents_live/test_methodologist_live_system.py`](../../tests/infrastructure/operational_agents_live/test_methodologist_live_system.py)

The live test creates a workspace, inserts a bounded Retriever context pack with
cited evidence into Postgres, verifies the context pack through the Retriever
API, attaches Methodologist to the workspace, patches Methodologist to a
deterministic remote harness, and sends a targeted thread task containing the
context-pack citation and evidence text.

Run:

```bash
OPEN_TALON_RUN_OPERATIONAL_AGENTS_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/operational_agents_live/test_methodologist_live_system.py -q -s
```

## What Is Tested

The live test verifies:

- Methodologist exists as a seeded global agent
- Methodologist can be attached to an ordinary workspace through normal agent attachment
- Retriever context-pack evidence is retrievable through workspace-scoped retrieval API
- a targeted Methodologist task receives cited Retriever evidence
- final Methodologist output includes `Methodology Basis`, `Methodics`, `Methods And Tools`, `Actors`, and `Workspace Template`
- output references `WorkspaceHarness.methodology` and `WorkspaceHarness.methodics`
- output cites source-backed claims with `[1]` and `[2]`
- output includes the context pack id
- inferred or ideated implementation items are clearly labeled
- evidence gaps are stated instead of hidden
- output explicitly keeps Conductor execution separate from Methodologist extraction

Seed and migration coverage also verifies the local Ollama endpoint, required
response sections, and workspace-harness output targets.
