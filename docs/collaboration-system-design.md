# Open Senate Peer Collaboration Design

## Goal

Extend the current single-user request/response chat flow into a collaboration system where:

- multiple users can participate in the same shared thread
- multiple agents can participate as first-class peers
- all peers communicate through the event system
- clients can observe the same shared timeline in near real time
- the system remains auditable, replayable, and safe to evolve

## Why The Current Design Is Not Enough

The current gateway is optimized for a single request mapped to a single agent response:

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

The collaboration design should therefore move from `request -> response` to `shared event log + materialized collaboration state`.

## Core Requirements

### Functional

- shared workspaces and threads
- multiple concurrent human participants
- multiple concurrent agent participants
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

- `Workspace`
  - top-level tenant or collaboration boundary
- `Thread`
  - a shared room for users and agents
- `Participant`
  - either `user` or `agent`
- `Membership`
  - participant joined a thread with a role and permissions
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

- `participant.joined`
- `participant.left`
- `presence.updated`
- `participant.role_changed`

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
- `thread.archived`

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
- the current gateway can evolve into a client edge instead of being thrown away
- it supports multiple users and multiple agents without committing to a fully decentralized design too early

## Recommended Topology

```text
Clients (web, tui, bots)
  -> API Gateway
  -> Collaboration Kernel
  -> Kafka
     - commands
     - canonical events
     - agent tasks
     - presence
  -> Postgres
     - event log
     - projections
  -> Valkey
     - presence
     - connection maps
     - short-lived leases
  -> Agent Runtimes
```

## Recommended Kafka Topics

### Commands

- `senate.collab.commands`
  - key: `thread_id`
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

## State Ownership

### Collaboration kernel owns

- membership validation
- permission checks
- canonical sequence numbers
- event persistence
- task lifecycle
- visibility rules

### Gateway owns

- auth/session termination at the edge
- client connection management
- fan-out over SSE and WebSocket
- command submission APIs

### Postgres stores

- append-only event log
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

- join thread
- post message
- reply to message
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
- `POST /v1/threads`
- `GET /v1/threads/{thread_id}`
- `POST /v1/threads/{thread_id}/commands`
- `GET /v1/threads/{thread_id}/events`
- `GET /v1/threads/{thread_id}/participants`
- `POST /v1/threads/{thread_id}/tasks`

### New streaming interfaces

- `WS /v1/threads/{thread_id}/stream`
- `SSE /v1/threads/{thread_id}/events`

### Command examples

- `join_thread`
- `post_message`
- `create_task`
- `claim_task`
- `complete_task`
- `attach_artifact`

## Schema Additions

The current `session_id` should no longer be the primary collaboration boundary.

### Recommended replacements

- keep `session_id` for one client connection or UI session
- add `thread_id` as the shared collaboration boundary
- add `workspace_id` as the tenant boundary
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
- resume gateway fan-out from canonical event stream
- restore presence separately from durable history

## Security Model

### Authentication

- users authenticate through existing gateway auth
- agents authenticate with service credentials and capability claims

### Authorization

- membership at workspace and thread scope
- role-based permissions
- explicit rules for internal events and private artifacts

### Audit

- canonical event log is append-only
- all moderation and access changes are events

## Incremental Rollout Plan

## Phase 1: Introduce collaboration identities

- add `workspace_id`, `thread_id`, `participant_id`
- keep current chat API as a compatibility adapter
- map current `session_id` chat into a synthetic single-user thread

## Phase 2: Canonical collaboration events

- add command envelope
- add canonical event envelope
- add collaboration kernel service
- introduce event log and thread projections

## Phase 3: Multi-user shared threads

- thread membership
- presence
- shared WebSocket stream for the same thread
- replayable thread history

## Phase 4: Multi-agent peer collaboration

- task lifecycle
- agent claims
- private/internal visibility
- public artifact publication

## Phase 5: Advanced coordination

- approvals
- handoffs
- agent capability routing
- policy-based turn selection
- summarization and thread compaction

## Migration Strategy From Today

The safest path is an adapter-based migration.

### Keep current compatibility

- current `POST /v1/chat` becomes:
  - create thread if absent
  - emit `post_message` command
  - wait for first public `message.completed` from the selected agent

- current SSE and WS endpoints become:
  - subscriptions to canonical thread events

This lets the current UI continue working while the underlying collaboration model becomes richer.

## Practical Recommendation

If we want the fastest path that will still scale into true collaboration:

- implement a new collaboration kernel service
- make `thread_id` the ordering key
- use one canonical event envelope for both humans and agents
- treat agent work as `tasks` rather than letting every agent answer every message
- keep private and public visibility in the event schema from day one

That gives us a system where users and agents are true peers, while preserving control over noise, ordering, and security.
