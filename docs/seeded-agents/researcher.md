# Researcher

## Agent Card

| Field | Value |
| --- | --- |
| Display name | `Researcher` |
| Agent id | `44444444-4444-4444-4444-444444444449` |
| Agent key | `researcher` |
| Scope | global |
| Role | `evidence discovery and research dossier agent` |
| Endpoint | `local-ollama` through provider `ollama` |
| Primary inputs | topic, target tasks, selected libraries, pre-indexed Retriever corpora, local files, database-visible context, web follow-up results |
| Primary outputs | durable research dossier, source records, context pack links, contradiction map, gaps, readiness decision |

## Idea

Researcher is the seeded specialist for building reusable research dossiers.
It performs multi-step evidence discovery and triage before Methodologist or
another participant synthesizes methodology, decisions, or implementation
plans.

A dossier is a first-class system concept, not just an agent transcript or a
folder. It has durable metadata, status, source records, event history,
contradictions, gaps, attached Retriever context packs, and a retained-source
library for fetched pages, papers, files, and media snapshots. The library keeps
source bytes and scraps; the dossier explains why each source matters, whether
it was included or excluded, and how it relates to the research question.

Researcher does not draft the methodology blueprint. It decides what evidence
is credible and sufficient, records unresolved gaps, and marks the dossier ready
for downstream synthesis.

## Harness And Contract

Researcher seeds an explicit `AgentHarness`:

- start with local libraries, selected organization resources, pre-indexed Retriever corpora, local files, and database-visible context
- use web search only for follow-up discovery, recency checks, missing coverage, or contradiction resolution
- preserve fetched source snapshots in the retained dossier library whenever possible
- create or update structured dossier source records for every included, excluded, duplicate, failed, and unresolved item
- record source quality notes, rationale, citation identifiers, fetch metadata, errors, and retained source references
- map contradictions and disagreements instead of hiding them
- attach Retriever context packs when they define a reusable evidence boundary
- mark a dossier ready only after summary, contradictions, gaps, and context packs are explicit

The response contract is operational rather than conversational: Researcher
persists dossier state through methodology dossier MCP operations and uses
thread messages only for progress, summaries, or blocker notes.

## Dossier Workflow

Creating a methodology blueprint creates the initial blueprint version, a
research dossier, an organization-managed retained-source library, and a
targeted Researcher task in the organization's `Administration / Organization
Operations` workspace.

Researcher can use least-privilege access to Library, Retriever, and Web Search
plus private methodology dossier MCP operations. It records source status and
quality, saves fetched evidence into the retained dossier library when possible,
attaches context packs, and marks the dossier `ready_for_methodologist`.

When the dossier is ready, the service creates a targeted Methodologist task
with the dossier summary, source records, contradictions, gaps, context pack
ids, and retained-source library reference. Humans still review any submitted
blueprint draft before a version can be approved or applied to a workspace.

## What Is Tested

Seed and migration coverage verifies:

- Researcher exists as a seeded global agent
- Researcher uses `normal_message_fanout=false`
- Researcher accepts `methodology_research_dossier_build` and `methodology_research_dossier_refine`
- the harness includes local-library-first research, web follow-up, source quality, contradiction mapping, retained refs, and source status labels
- the `methodology_researcher` IAM role grants least-privilege library, retrieval, web search, and methodology permissions
- the private MCP allowlist includes dossier read/write, source update, context-pack attach, and readiness operations

Repository, gateway, and live-style tests should cover the durable dossier
tables, cross-organization source rejection, human review gating, Methodologist
handoff, cited blueprint draft submission, and the rule that Conductor is never
started automatically.
