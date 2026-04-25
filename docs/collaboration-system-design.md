# Historical Open Talon Collaboration Design Notes

This document preserves the design notes that informed Open Talon's collaboration architecture.

Open Talon today is already a multi-user, multi-agent collaboration system. For the current implementation, use:

- [README.md](../README.md)
- [system-api-reference.md](./system-api-reference.md)
- [system-quickstart.md](./system-quickstart.md)

The sections below are historical design material. They are not the source of truth for the current implementation, API surface, or runtime behavior.

## Original Goal

Extend the earlier single-user request/response chat flow into a collaboration system where:

- multiple workspaces can exist with different participants
- multiple users can participate in the same shared thread
- multiple agents can participate as first-class peers
- every workspace has associated shared whiteboard memory
- every workspace can have several parallel or consecutive threads
- all peers communicate through the event system
- clients can observe the same shared timeline in near real time
- the system remains auditable, replayable, and safe to evolve

## Original Motivation

At the time these notes were written, the gateway was optimized for a single request mapped to a single agent response:

- one `KafkaChatRequest`
- one `correlation_id`
- one `session_id`
- one terminal response stream

That model breaks down when:

- several users are editing the same conversation
- several agents are responding concurrently
- agents need to coordinate with each other
- some events are public and some are private/internal
- collaboration state must survive reconnects and be replayable

The design proposal therefore argued for moving from `request -> response` to `shared event log + materialized collaboration state`.

## Core Requirements

### Functional

- multiple workspaces with independent participant sets
- workspace-scoped shared whiteboard memory
- shared workspaces and threads
- multiple concurrent human participants
- multiple concurrent agent participants
- several parallel active threads in the same workspace
- several consecutive threads chained over time
- peer-to-peer messaging through Kafka events
- presence and membership tracking
- support for public messages, private agent messages, and system events
- support for long-running tasks and artifacts
- deterministic replay of a thread timeline

### Non-Functional

- per-thread ordering
- at-least-once delivery with idempotent consumers
- strong auditability
- gateway fan-out to WebSocket and SSE clients
- room for moderation, permissions, and quotas

## Domain Model

### Primary entities

- `Organization`
  - tenant boundary above projects
- `Project`
  - organization-local work grouping that owns workspaces
  - has typed creator and owner references for either a user or system agent
  - exposes project structure only to explicit `creator`, `owner`, `editor`, or `viewer` project access bindings
  - maps those roles to project-local permissions instead of treating them as workspace collaboration roles
- `Workspace`
  - collaboration boundary inside a project
- `Thread`
  - a shared room for users and agents
- `Participant`
  - either `user` or `agent`
- `Membership`
  - participant joined a thread with a role and permissions
- `WorkspaceMemory`
  - shared editable whiteboard memory for the workspace
- `Message`
  - user, agent, or system content shown in the timeline
- `Task`
  - a unit of work agents can claim, execute, and complete
- `Artifact`
  - file, tool result, summary, patch, or structured output
- `Run`
  - one agent execution attempt on behalf of a task or a message

### Recommended IDs

- `workspace_id`
- `thread_id`
- `participant_id`
- `membership_id`
- `memory_entry_id`
- `message_id`
- `task_id`
- `artifact_id`
- `run_id`
- `event_id`
- `correlation_id`
- `causation_id`

## Shared Event Envelope

Every command-derived event should use one common envelope.

```json
{
  "event_id": "uuid",
  "schema_version": 1,
  "event_type": "message.created",
  "workspace_id": "uuid",
  "thread_id": "uuid",
  "actor": {
    "type": "user",
    "id": "uuid"
  },
  "target": {
    "type": "thread",
    "id": "uuid"
  },
  "visibility": "public",
  "correlation_id": "uuid",
  "causation_id": "uuid",
  "sequence": 184,
  "timestamp": "2026-04-08T00:00:00Z",
  "payload": {}
}
```

### Envelope fields

- `event_id`: immutable dedupe key
- `schema_version`: versioned contract evolution
- `event_type`: behavior-specific event name
- `workspace_id`: tenant boundary
- `thread_id`: ordering and subscription boundary
- `actor`: who emitted the event
- `target`: message, task, thread, or artifact target
- `visibility`: `public`, `workspace`, `agents_only`, `private`
- `correlation_id`: ties together one user action or workflow
- `causation_id`: points to the event that caused this event
- `sequence`: monotonic thread-local sequence assigned by the collaboration service
- `payload`: event-specific body

## Event Types

### Membership and presence

- `workspace.created`
- `workspace.updated`
- `participant.joined`
- `participant.left`
- `presence.updated`
- `participant.role_changed`

### Workspace memory

- `workspace.memory_entry_created`
- `workspace.memory_entry_updated`
- `workspace.memory_entry_deleted`
- `workspace.memory_entry_linked_to_thread`

### Thread lifecycle

- `thread.created`
- `thread.updated`
- `thread.archived`
- `thread.linked`

### Timeline

- `message.created`
- `message.delta`
- `message.completed`
- `message.edited`
- `message.deleted`
- `reaction.added`

### Agent workflow

- `task.created`
- `task.claimed`
- `task.released`
- `task.completed`
- `task.failed`
- `run.started`
- `run.progressed`
- `run.completed`
- `run.failed`

### Artifacts and decisions

- `artifact.created`
- `artifact.updated`
- `decision.recorded`

### Governance

- `access.granted`
- `access.revoked`

## Three Architecture Options

## Option A: Central Collaboration Orchestrator

### Idea

Add a dedicated collaboration service between the gateway and agents.

- clients send commands to the gateway
- gateway forwards commands to the collaboration service
- collaboration service validates membership, writes canonical events, assigns sequence numbers, updates projections, and publishes Kafka events
- agents subscribe to collaboration events and emit commands or events back through the same service

### Components

- API Gateway
- Collaboration Service
- Kafka
- Postgres projections + event log
- Valkey presence store
- Agent Runtimes

### Pros

- simplest consistency model
- easiest place to enforce ACLs and moderation
- easiest to assign per-thread sequence numbers
- easiest replay story

### Cons

- central service becomes a throughput bottleneck
- collaboration logic becomes concentrated in one component

### Best when

- correctness and product iteration matter more than maximum horizontal autonomy

## Option B: Event-Sourced Collaboration Kernel

### Idea

Keep the gateway thin, but introduce a collaboration kernel that owns the event log and projections. Users and agents both act as peers by publishing commands against threads, while read models are projected asynchronously.

This is similar to Option A, but more explicitly event-sourced:

- commands are validated by the kernel
- canonical events are persisted first
- projections drive UI state, unread counts, memberships, tasks, and artifacts

### Pros

- clean domain boundaries
- replayable history by design
- easy to add new event consumers later
- strong audit trail

### Cons

- more moving parts than the current request/response design
- demands discipline around schemas and idempotency

### Best when

- collaboration is the product core

## Option C: Fully Decentralized Peer Bus

### Idea

Users and agents all publish directly to thread-scoped Kafka topics, with only lightweight validation at the edge. Multiple services independently project state.

### Pros

- maximum autonomy
- high scalability
- easy agent experimentation

### Cons

- hardest security model
- hard to guarantee ordering and conflict resolution
- harder to reason about private visibility
- hardest migration path from the current gateway

### Best when

- many independent teams own separate peer services and can tolerate more distributed complexity

## Recommended Target

Choose **Option B: Event-Sourced Collaboration Kernel**.

It fits the current architecture best because:

- Kafka is already the backbone
- Postgres already exists for durable history
- Valkey already exists for ephemeral state
- workspaces, whiteboards, and threads all map naturally to event streams + projections
- the current gateway can evolve into a client edge instead of being thrown away
- it supports multiple users and multiple agents without committing to a fully decentralized design too early

## Recommended Topology

```text
Clients (web, tui, bots)
  -> API Gateway
  -> Collaboration Kernel
  -> Kafka
     - workspace events
     - commands
     - canonical events
     - agent tasks
     - presence
  -> Postgres
     - event log
     - workspace projections
     - projections
  -> Valkey
     - presence
     - connection maps
     - short-lived leases
  -> Agent Runtimes
```

## Recommended Kafka Topics

### Workspace events

- `senate.workspace.events`
  - key: `workspace_id`
  - produced by: collaboration kernel
  - consumed by: gateway fan-out, workspace projections, agents

### Commands

- `senate.collab.commands`
  - key: `workspace_id` or `thread_id`
  - producers: gateway, agents, internal services
  - consumed by: collaboration kernel

### Canonical events

- `senate.collab.events`
  - key: `thread_id`
  - produced by: collaboration kernel only
  - consumed by: gateway fan-out, projections, agents, analytics

### Agent task routing

- `senate.agent.tasks`
  - key: `task_id` or `thread_id`
  - produced by: collaboration kernel
  - consumed by: agent pools

- `senate.agent.events`
  - key: `thread_id`
  - produced by: agents
  - consumed by: collaboration kernel

### Presence

- `senate.presence`
  - key: `thread_id`
  - short-lived presence updates

## Ordering Strategy

Ordering should be guaranteed at the `thread_id` level.

- use `thread_id` as the Kafka partition key
- assign a thread-local `sequence` in the collaboration kernel
- never let multiple services assign canonical sequence numbers

This gives:

- stable replay
- deterministic client rebuild
- easier conflict resolution

For workspace-scoped data such as whiteboard memory and participant directory updates:

- partition workspace events by `workspace_id`
- assign workspace-local sequence numbers in the collaboration kernel
- keep thread-local ordering separate from workspace-local ordering

## Workspace As The Main Collaboration Boundary

The workspace should be the primary boundary for identity, permissions, memory, and discovery.

### A workspace contains

- participant directory
- shared whiteboard memory
- active threads
- archived threads
- workspace artifacts
- routing policies
- access rules

### A thread contains

- timeline of messages and events
- participants currently involved
- task and run references
- linked whiteboard memory entries
- optional thread-local summary

This separation is important:

- workspace whiteboard is curated, editable, and long-lived
- thread timeline is append-only, replayable, and execution-focused

## Workspace Participant Directory

Users and agents should both publish discoverable workspace profiles so all workspace members can understand who is present and what they can do.

### Participant profile fields

- `participant_id`
- `workspace_id`
- `participant_type`
- `display_name`
- `description`
- `roles`
- `capabilities`
- `status`
- `visibility_scope`

### Suggested participant events

- `participant.registered`
- `participant.profile_updated`
- `participant.capabilities_updated`
- `participant.status_updated`

This gives the workspace a shared directory of human and agent peers.

## Workspace Whiteboard Memory

Every workspace should have a shared whiteboard memory that acts as long-lived, editable collaboration memory.

### The whiteboard is for

- goals
- decisions
- facts
- constraints
- plans
- open questions
- artifact references

### The whiteboard is not for

- raw chat history
- streaming deltas
- temporary token output

### Recommended whiteboard entry model

- `memory_entry_id`
- `workspace_id`
- `entry_type`
- `title`
- `content`
- `tags`
- `created_by`
- `updated_by`
- `version`
- `visibility`

### Whiteboard behavior

- whiteboard entries are versioned and editable
- important thread outcomes should be promoted into whiteboard memory
- threads may link to whiteboard entries instead of copying context repeatedly

## Parallel And Consecutive Threads

A workspace may contain multiple threads that are active at the same time, as well as new threads that continue older work.

### Parallel threads

Use for:

- independent workstreams
- multiple agent task groups
- simultaneous investigations
- separate decision tracks

### Consecutive threads

Use for:

- phase transitions
- archiving long discussions
- resuming work with a cleaner context window
- splitting execution from planning

### Recommended thread relationship fields

- `parent_thread_id`
- `previous_thread_id`
- `related_thread_ids`
- `workspace_id`

### Recommended thread states

- `active`
- `paused`
- `resolved`
- `archived`

## Thread And Whiteboard Interaction

The most useful pattern is:

1. discussion happens in a thread
2. a decision, fact, or plan becomes stable
3. that outcome is promoted into workspace whiteboard memory
4. later threads can link back to that memory entry

This keeps thread timelines readable and keeps reusable knowledge at the workspace level.

## State Ownership

### Collaboration kernel owns

- workspace membership validation
- membership validation
- permission checks
- workspace and thread sequence numbers
- canonical sequence numbers
- event persistence
- whiteboard lifecycle
- task lifecycle
- visibility rules

### Gateway owns

- auth/session termination at the edge
- client connection management
- fan-out over SSE and WebSocket
- command submission APIs

### Postgres stores

- append-only event log
- workspace projection
- participant directory projection
- whiteboard projection
- thread projection
- message projection
- task projection
- artifact metadata
- membership tables

### Valkey stores

- active connections by thread
- participant presence heartbeat
- short-lived run leases
- rate limit counters

## Public vs Private Collaboration

Not every agent event should be visible to all users.

### Visibility model

- `public`
  - visible to all thread members
- `workspace`
  - visible to workspace members but not necessarily external guests
- `agents_only`
  - internal coordination between agents
- `private`
  - visible only to named recipients

### Recommendation

Keep the canonical event stream complete, but filter at fan-out time based on membership and visibility.

That means:

- audit remains complete
- UX stays clean
- agent-to-agent coordination does not flood the human timeline

## Peer Collaboration Semantics

To make users and agents true peers, use the same core event types for both, but not the same permissions.

### Shared peer actions

- join workspace
- join thread
- post message
- reply to message
- update profile
- propose whiteboard changes
- create task
- claim task
- attach artifact
- mention another peer

### Agent-only or elevated actions

- publish internal reasoning events
- claim work automatically
- emit tool execution progress
- propose structured decisions

### Human-only or policy-gated actions

- invite/remove participants
- approve whiteboard changes if governance requires it
- approve final actions
- change visibility level
- archive a thread

## Recommended Interaction Pattern

Use **task-claim collaboration**, not unrestricted free-for-all chat.

### Why

If several agents can all answer every message, threads become noisy and expensive.

### Better pattern

1. user posts a message
2. collaboration kernel creates one or more tasks
3. eligible agents claim tasks
4. agents emit progress and artifacts
5. selected public outputs are posted into the thread timeline

This preserves peer behavior while preventing chaos.

## Suggested API Evolution

### New REST resources

- `POST /v1/workspaces`
- `GET /v1/workspaces/{workspace_id}`
- `GET /v1/workspaces/{workspace_id}/participants`
- `GET /v1/workspaces/{workspace_id}/whiteboard`
- `POST /v1/workspaces/{workspace_id}/whiteboard`
- `POST /v1/threads`
- `GET /v1/threads/{thread_id}`
- `POST /v1/threads/{thread_id}/commands`
- `GET /v1/threads/{thread_id}/events`
- `GET /v1/threads/{thread_id}/participants`
- `POST /v1/threads/{thread_id}/tasks`

### New streaming interfaces

- `WS /v1/workspaces/{workspace_id}/stream`
- `WS /v1/threads/{thread_id}/stream`
- `SSE /v1/workspaces/{workspace_id}/events`
- `SSE /v1/threads/{thread_id}/events`

### Command examples

- `join_workspace`
- `join_thread`
- `post_message`
- `update_whiteboard_entry`
- `create_task`
- `claim_task`
- `complete_task`
- `attach_artifact`

## Schema Additions

In this proposal, `session_id` was treated as a client/UI concern rather than the primary collaboration boundary.

### Recommended replacements

- keep `session_id` for one client connection or UI session
- add `workspace_id` as the tenant boundary
- add `thread_id` as the shared execution boundary inside a workspace
- add `participant_id` and `participant_type`

### Message model evolution

Add:

- `message_id`
- `thread_id`
- `workspace_id`
- `author`
- `visibility`
- `reply_to_message_id`
- `status`
- `task_id` optional

### Workspace memory model

Add a separate workspace memory projection instead of overloading message history:

- `memory_entry_id`
- `workspace_id`
- `entry_type`
- `title`
- `content`
- `tags`
- `linked_thread_ids`
- `version`
- `updated_at`

## Failure Handling

### Idempotency

- dedupe on `event_id`
- dedupe commands on `command_id`
- maintain consumer inbox tables for stateful consumers

### Reliability

- use transactional outbox from Postgres to Kafka for canonical events
- dead-letter malformed agent events
- timeout stale tasks
- lease agent claims in Valkey

### Recovery

- rebuild projections from event log
- rebuild workspace whiteboard and participant directory from workspace events
- resume gateway fan-out from canonical event stream
- restore presence separately from durable history

## Security Model

### Authentication

- users authenticate through existing gateway auth
- agents authenticate with service credentials and capability claims

### Authorization

- membership at workspace and thread scope
- role-based permissions
- whiteboard edit permissions
- explicit rules for internal events and private artifacts

### Audit

- canonical event log is append-only
- all moderation and access changes are events

## Historical Rollout Plan

## Phase 1: Introduce collaboration identities

- add `workspace_id`, `thread_id`, `participant_id`
- add workspace directory and participant profiles
- keep current chat API as a compatibility adapter
- map current `session_id` chat into a synthetic single-user thread

## Phase 2: Canonical collaboration events

- add command envelope
- add canonical event envelope
- add collaboration kernel service
- introduce workspace and thread event logs
- introduce whiteboard and thread projections

## Phase 3: Multi-user shared threads

- shared workspaces
- thread membership
- presence
- shared WebSocket stream for the same thread
- replayable thread history

## Phase 4: Multi-agent peer collaboration

- workspace-level agent directory
- task lifecycle
- agent claims
- private/internal visibility
- public artifact publication

## Phase 5: Advanced coordination

- whiteboard promotion and memory compaction
- approvals
- handoffs
- agent capability routing
- policy-based turn selection
- summarization and thread compaction

## Historical Migration Strategy

The safest path is an adapter-based migration.

### Keep then-current compatibility

- current `POST /v1/chat` becomes:
  - create workspace if needed
  - create thread if absent
  - emit `post_message` command
  - wait for first public `message.completed` from the selected agent

- current SSE and WS endpoints become:
  - subscriptions to canonical thread events

This lets the current UI continue working while the underlying collaboration model becomes richer.

## Historical Recommendation

If we want the fastest path that will still scale into true collaboration:

- implement a new collaboration kernel service
- keep `organization_id` as the tenant boundary and `workspace_id` as the collaboration boundary
- make `thread_id` the ordering key
- add versioned workspace whiteboard memory as a first-class projection
- use one canonical event envelope for both humans and agents
- treat agent work as `tasks` rather than letting every agent answer every message
- keep private and public visibility in the event schema from day one

That gives us a system where users and agents are true peers, while preserving control over noise, ordering, and security.
