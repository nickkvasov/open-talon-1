# Researcher

## Agent Card

| Field | Value |
| --- | --- |
| Display name | `Researcher` |
| Agent id | `44444444-4444-4444-4444-444444444449` |
| Agent key | `researcher` |
| Scope | global |
| Role | `evidence discovery and dossier agent` |
| Profile kind | `methodology_dossier_specialist` |
| Endpoint | `openai-responses` through provider `openai` using `gpt-5.4-mini` |
| Compaction | `rolling_summary`, `max_estimated_input_tokens=256000` |
| Primary inputs | topic, target tasks, selected libraries, pre-indexed Retriever corpora, local files, database-visible context, web follow-up results |
| Primary outputs | durable dossier, source records, concept notebook, claims, typed links, context pack links, contradiction map, gaps, health/sync state, readiness decision |

## Agent Profile

Researcher's seeded profile says its mandate is to discover, collect, triage,
preserve, and organize evidence into durable concept dossiers. It is activated
by targeted organization-operations dossier build/refine tasks created by
methodology blueprint workflows. Its authority comes from the
`methodology_researcher` IAM role, organization Operations workspace
attachment, and Library, Retriever, Web Search, and dossier MCP allowlists. Its
knowledge layer is dossier knowledge storage over retained data and indexed
information.

## Idea

Researcher is the seeded specialist for building reusable dossiers.
It performs multi-step evidence discovery and triage before Methodologist or
another participant synthesizes methodology, decisions, or implementation
plans.

A dossier is a first-class system concept, not just an agent transcript or a
folder. It has durable metadata, status, source records, event history,
contradictions, gaps, attached Retriever context packs, and a retained-source
library for fetched pages, papers, files, and media snapshots. The library keeps
source bytes and scraps; the dossier explains why each source matters, whether
it was included or excluded, and how it relates to the research question.

The storage taxonomy is:

- MinIO/object storage is data storage for immutable source bytes and snapshots.
- Libraries plus Retriever indexes are information storage for retained, indexed, and vectorized pieces.
- Dossiers are knowledge storage for concept organization, claims, contradictions, gaps, methods, synthesis, provenance, and navigation.

Each dossier also has a notebook. The default notebook provider is
XWiki, mapped as one XWiki space per dossier (`Dossiers.<dossier_slug>`).
Open Talon stores the canonical lifecycle, source provenance, IAM, audit,
concept/claim/link metadata, provider binding, external refs, health, and sync
state in Postgres. XWiki stores the navigable concept repository that humans and
agents can read: `Home`, `Sources`, `Concepts`, `Entities`, `Methods`,
`Questions`, `Contradictions`, `Gaps`, and `Synthesis` pages.

Researcher does not draft the methodology blueprint. It decides what evidence
is credible and sufficient, records unresolved gaps, and marks the dossier ready
for downstream synthesis.

## Harness And Contract

Researcher seeds an explicit `AgentHarness`:

- start with local libraries, selected organization resources, pre-indexed Retriever corpora, local files, and database-visible context
- use web search for follow-up discovery, recency checks, missing coverage, contradiction resolution, and full methodology research requests that require internet evidence
- preserve fetched source snapshots in the retained dossier library whenever possible
- create or update structured dossier source records for every included, excluded, duplicate, failed, and unresolved item
- create or update notebook notes, concepts, claims, and typed links so the dossier stays navigable
- record source quality notes, rationale, citation identifiers, fetch metadata, errors, and retained source references
- map contradictions and disagreements instead of hiding them
- ask clarifying or approval questions through thread interaction requests when human input is needed; do not invent a dossier "waiting" status
- attach Retriever context packs when they define a reusable evidence boundary
- run notebook health/sync checks and mark a dossier ready only after required knowledge components, summary, contradictions, gaps, context packs, and unresolved notebook issues are explicit

The response contract is operational rather than conversational: Researcher
persists dossier state through dossier MCP operations and uses
thread messages only for progress, summaries, or blocker notes.

## Dossier Workflow

Creating a methodology blueprint creates the initial blueprint version, a
dossier, an organization-managed retained-source library, and a
notebook provider binding for the XWiki dossier space, then creates a targeted
Researcher task in the organization's `Administration / Organization Operations`
workspace.

Researcher can use least-privilege access to Library, Retriever, and Web Search
plus private dossier MCP operations. It records source status and
quality, saves fetched evidence into the retained dossier library when possible,
attaches context packs, writes notebook notes/concepts/claims/links, submits
notebook health, syncs the provider projection, and transitions the dossier
lifecycle to `ready`.

For methodology-created dossiers, Researcher must satisfy
`completion_profile=full_methodology_research` before readiness. Required
knowledge components are research plan, source bibliography, methodology basis,
methodology principles, methodics inventory, participants and roles, tools and
methods, information assets, libraries and dossiers, quality evaluation,
contradictions, gaps, and synthesis.

When the dossier is ready, the service creates a targeted Methodologist task
with the dossier summary, source records, contradictions, gaps, context pack
ids, and retained-source library reference. Humans still review any submitted
blueprint draft before a version can be approved or applied to a workspace.

## What Is Tested

Seed and migration coverage verifies:

- Researcher exists as a seeded global agent
- Researcher uses `normal_message_fanout=false`
- Researcher accepts `methodology_dossier_build` and `methodology_dossier_refine`
- the harness includes local-library-first research, web follow-up, source quality, contradiction mapping, retained refs, and source status labels
- the `methodology_researcher` IAM role grants least-privilege library, retrieval, web search, and methodology permissions
- the private MCP allowlist includes dossier read/write, source update, context-pack attach, notebook get, note/concept/claim/link upsert, navigation, sync, health, and readiness operations

Repository, gateway, and live-style tests should cover the durable dossier
tables, cross-organization source rejection, human review gating, Methodologist
handoff, XWiki adapter projection, cited blueprint draft submission, and the
rule that Conductor is never started automatically.

Primary full live workflow:

```bash
./scripts/run-live-tests.sh methodology-deep-research
```

That suite uses the real seeded Researcher, real runtime workers, web-search MCP,
generic dossier lifecycle, XWiki notebook projection, and Methodologist handoff.
It is the preferred proof when changing full methodology research behavior.
