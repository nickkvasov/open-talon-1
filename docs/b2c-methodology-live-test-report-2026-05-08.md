# B2C Market Research Methodology Live Test Report: 2026-05-08

This report describes the implemented B2C market research methodology live test,
the agent activities it now demonstrates, the expected durable results, and the
verification performed during implementation.

## Status

- Test implementation: complete.
- Local static verification: passed.
- Full XWiki plus web-search live execution: not run in this session because the
  live environment gates were not enabled.
- Full-run command:

```bash
./scripts/run_live_tests.py xwiki --fail-fast
```

The XWiki suite now starts the local stack with both optional providers enabled:

```bash
./open-talon start --xwiki --web-search
```

## Scope

Primary executable coverage:

- [tests/infrastructure/test_xwiki_dossier_live_system.py](../tests/infrastructure/test_xwiki_dossier_live_system.py)
- [apps/admin-web/tests/e2e/admin-methodologies.spec.js](../apps/admin-web/tests/e2e/admin-methodologies.spec.js)
- [scripts/run_live_tests.py](../scripts/run_live_tests.py)

The test scenario is an organization-scoped methodology request:

```text
Create a B2C market research methodology for validating subscription wellness
app demand.
```

The target outcome is a reusable methodology blueprint with a cited research
dossier, a Methodologist-produced `WorkspaceHarness`, a human-edited revised
version, and methodics detailed enough to execute the market-research goal.

## System Under Test

The scenario crosses these runtime boundaries:

- Admin and human actor APIs through `gateway-edge`.
- Organization IAM and machine-principal provisioning for Researcher and
  Methodologist agents.
- Web-search MCP backed by local SearXNG.
- Methodology dossier APIs and private methodology MCP operations.
- XWiki-backed dossier notebook projection and readback.
- Methodology blueprint versioning, review, apply, and archive lifecycle.
- Admin-web methodology UI flow.

This stays consistent with the Open Talon architecture: agents are normal system
agents whose authority comes from IAM bindings, task payloads, and MCP/tool
allowlists. Runtime workers remain generic.

## Agent Activity

| Actor | Activities | Durable Results |
| --- | --- | --- |
| Human admin | Creates the temporary organization and B2C methodology blueprint. | Organization, blueprint, initial version, dossier, and notebook binding exist. |
| Researcher | Performs two internet search turns, records selected results as dossier sources, builds concepts, notes, claims, links, health, and readiness state. | Sources `S1` and `S2`, active concept, active note, supported claim, concept-claim link, completed health check, and ready dossier. |
| Methodologist | Navigates the ready dossier and submits a cited `WorkspaceHarness` draft. | Pending-review blueprint version with methodology, methodics, execution rules, and metadata. |
| Human editor | Creates a revised version from the Methodologist draft. | New pending-review version with `base_version_id`, `revision_reason`, human-edit metadata, richer participants/tools/assets, and preserved dossier linkage. |
| XWiki provider | Syncs the dossier notebook and exposes concept/note pages over XWiki REST. | XWiki pages are created and read back by the test. |
| Web-search MCP | Executes live internet searches through SearXNG. | Search result URLs, snippets, citations, query metadata, and selected source records are persisted into the dossier. |

## Multi-Turn Internet Search

The test now requires web-search MCP readiness and runs two real search turns:

1. Broad topic search:

```text
B2C market research methodology consumer segmentation purchase intent
```

2. Refined methodics search:

```text
B2C willingness to pay survey diary study purchase intent methodology
```

Each turn must return at least one result and a matching citation list. The
selected results are saved as dossier sources:

- `S1`: methodology definition and broad B2C market research framing.
- `S2`: refined willingness-to-pay, survey, and diary-study methodics framing.

The source records preserve:

- selected URL
- search turn number
- original query
- result snippet
- citation payload
- provider metadata showing SearXNG as the search source

## Methodology Collection

The Researcher activity converts the search results into a durable dossier:

- concept: `B2C Market Research Methodology`
- concept slug: `b2c-market-research-methodology`
- note: `Collected B2C Methodology`
- note slug: `b2c-methodology-collection-note`
- claim: `claim:b2c-methodology-methodics`
- citations: `S1` and `S2`

The claim under test is that a B2C market research methodology should collect
internet sources, define the target segment, and convert evidence into methodics
with participants, tools, and information assets.

The XWiki sync projects this dossier into pages, and the test reads the XWiki
concept and note pages back to verify the provider projection contains the
refined methodology collection.

## Methodics Produced

The Methodologist draft includes two methodics.

### Collect B2C Methodology From Internet Evidence

Goal: turn multi-turn internet search results into a cited dossier.

Required steps:

- Researcher runs broad and refined internet search queries and records selected
  web sources.
- Methodologist converts collected sources into methodology concepts, claims,
  and a reusable methodics outline.

Tools:

- `web_search.search`
- `dossiers.sources.create`
- `dossiers.lifecycle.transition`
- `dossiers.navigate`
- `dossiers.claims.upsert`
- `methodology.blueprints.submit_draft`

Information assets:

- search query log
- selected source bibliography
- methodology concept note
- supported methodics claim

### Execute B2C Demand Validation

Goal: validate consumer segment, purchase intent, and pricing risk for the
subscription wellness app launch decision.

Participants:

- Product lead
- Researcher
- Methodologist
- Analyst
- Consumer respondents

Tools:

- `calendar`
- `crm`
- `workspace.participants`
- `survey`
- `spreadsheet`
- `dossiers.notes.upsert`

Information assets:

- participant responsibility matrix
- consumer respondent screener
- interview guide
- diary-study log
- survey dataset
- willingness-to-pay matrix
- segment scorecard

Success criterion: a launch-channel test is backed by segment, diary, survey,
and pricing evidence.

## Human-Edited Version

After Methodologist submission, the test creates a revised version through:

```text
POST /v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}/versions
```

The revised version adds execution-grade detail:

- participant ownership through a RACI matrix
- decision-gate checklist
- retrieval/search and spreadsheet tooling
- pricing-risk notes
- launch-channel test brief
- explicit information-asset references

The test asserts:

- the new version is `pending_review`
- the version number increases
- `base_version_id` points to the Methodologist draft
- `revision_reason` records the human edit
- metadata contains `human_edit=true`
- methodic steps include `retrieval.search`
- information assets include `launch-channel test brief`

## Admin-Web Flow

The admin e2e test mirrors the same scenario through the web UI:

- creates a B2C methodology request
- seeds a draft with internet-search turns, participants, tools, and assets
- edits the pending draft
- approves it
- creates a human-edited v2
- approves v2
- applies the approved methodology to a workspace
- archives the blueprint

This keeps the browser workflow aligned with the live backend semantics.

## Verification Performed

These checks passed during implementation:

```bash
python -m py_compile \
  tests/infrastructure/test_xwiki_dossier_live_system.py \
  scripts/run_live_tests.py \
  tests/scripts/test_live_test_runner.py
```

```bash
npx eslint src/features/methodologies tests/e2e/admin-methodologies.spec.js
```

```bash
./.venv/bin/python -m pytest tests/scripts/test_live_test_runner.py -q
```

Result:

```text
4 passed
```

Focused live-test collection command:

```bash
./.venv/bin/python -m pytest -m integration \
  tests/infrastructure/test_xwiki_dossier_live_system.py::test_xwiki_live_agent_mcp_workflow_builds_updates_and_consumes_dossier -q
```

Result in this session:

```text
1 skipped
```

Reason: the full live test is gated behind `OPEN_TALON_RUN_XWIKI_LIVE=1` and
requires the local XWiki plus web-search stack.

## Overall Outcome

The test now demonstrates the intended methodology workflow instead of only a
generic draft lifecycle:

- live internet search is part of the Researcher path
- search is multi-turn and query refinement is asserted
- selected internet results become cited dossier sources
- methodology collection is represented as concept, note, claim, and link data
- XWiki projection confirms the dossier is readable outside Postgres
- Methodologist synthesis creates a `WorkspaceHarness` with real methodics
- methodics name required participants, tools, steps, verification, and
  information assets
- human editing creates a versioned methodology revision without mutating
  approved history
- admin UI coverage exercises create, edit, approve, apply, and archive behavior

The remaining evidence gap is a full live run of the XWiki suite with web-search
enabled. That run should be recorded separately with live result IDs, selected
source URLs, XWiki page refs, and final pytest output.
