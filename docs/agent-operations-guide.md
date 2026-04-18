# Open Talon Agent Operations Guide

This guide is for software development agents, scripted test runners, and automation clients that need to operate Open Talon end to end.

This is not the same thing as repository contribution guidance in `AGENTS.md`.

Use this guide when an agent needs to:

- act as one or more human test users
- drive workspaces, threads, requests, and answers through the HTTP APIs
- validate role-based routing and resumable collaboration
- inspect collaboration logs and runtime outcomes

For the full system and API reference, use [system-api-reference.md](./system-api-reference.md).

## Core Operating Rules

### 1. Use One Client Instance Per Human User

If you are simulating several humans, each human must use a separate profile and client instance.

Recommended command:

```bash
./open-talon user-client --profile user1
```

For multiple simulated humans:

```bash
./open-talon user-client --profile user1
./open-talon user-client --profile user2
./open-talon user-client --profile supervisor
```

This keeps:

- auth state separate
- selected workspace/thread separate
- role assumptions separate
- request-answer attribution correct

### 2. Prefer Collaboration APIs Over Legacy Chat

Use:

- workspaces
- threads
- timeline messages
- interaction requests
- communication log

Do not use the legacy `/v1/chat` surface for multi-user, multi-agent collaboration testing.

### 3. Treat Human Identity And Participant Identity As Different Things

Never assume:

- `participant_id == user_id`

The correct model is:

- `user_id`: global human identity
- `participant_id`: workspace-local materialization of that human or agent

### 4. Let The Server Resolve Human Actors Under OIDC

When acting as an authenticated human:

- the gateway resolves the effective human actor
- the `actor` field is compatibility input, not the source of truth

### 5. Use Tracked Requests When You Need Deterministic Resume Behavior

Use plain messages when you only need general thread activity.

Use tracked requests when:

- one or more answers must be linked to a question set
- answers from several participants must be aggregated
- an agent should resume only when a completion rule is satisfied

## Recommended Client Surfaces

### `user-client`

Use `user-client` when an agent must operate several isolated human-user sessions.

Good for:

- stdin/stdout automation
- scripted multi-user test cases
- role assumption
- answering tracked requests
- inspecting communication logs

### `tui2`

Use `tui2` for human operators, manual debugging, or mixed human/agent demos where copy/select behavior matters.

## Minimum End-To-End Playbook

### 1. Authenticate Profiles

```bash
./open-talon user-client auth login --profile user1
./open-talon user-client auth login --profile user2
./open-talon user-client auth login --profile supervisor
```

### 2. Create Or Select A Shared Workspace

Use one admin/supervisor-capable profile to create the workspace, then point every other profile at the same workspace ID.

### 3. Create A Shared Thread

Create one thread for the scenario, then switch all relevant profiles to the same thread.

### 4. Assign Or Assume Roles

For role-based routing tests, make sure each human participant advertises the intended role through the participant-role flow.

Examples:

- `team_lead`
- `frontend_engineer`
- `backend_engineer`

### 5. Post A Kickoff Message

Use a normal thread message to start the flow.

This is appropriate when:

- an agent should be triggered by normal task routing
- the kickoff is not itself a tracked request

### 6. Create Tracked Requests

Prefer selectors over explicit user IDs when validating advertised role-based routing:

- `@role:frontend_engineer`
- `@role:backend_engineer`
- `@capability:security_review`

Completion rules to test:

- `all_targets`
- `minimum_answers`
- `one_per_selector_bucket`

### 7. Answer Requests As Separate User Profiles

Each answering user should respond from that user’s own client instance.

This is necessary for:

- correct participant attribution
- correct target coverage
- correct request completion behavior

### 8. Inspect The Outcome

Check:

- thread timeline
- request detail
- workspace communication log
- JSONL communication file
- runtime overview if an agent should have resumed

## API Choices By Goal

| Goal | Preferred API |
| --- | --- |
| create shared collaboration space | `/v1/workspaces` |
| inspect workspace state | `/v1/workspaces/{workspace_id}` |
| inspect participants and advertised roles | `/v1/workspaces/{workspace_id}/participants` |
| create a collaboration stream | `/v1/workspaces/{workspace_id}/threads` |
| inspect thread messages | `/v1/threads/{thread_id}/timeline` |
| post general thread activity | `/v1/threads/{thread_id}/messages` |
| create resumable multi-question workflow | `/v1/threads/{thread_id}/requests` |
| answer tracked question workflow | `/v1/requests/{request_id}/answers` |
| inspect request aggregation state | `/v1/requests/{request_id}` |
| inspect workspace-wide communication trail | `/v1/workspaces/{workspace_id}/communication-log` |
| inspect persisted communication trail on disk | `OPEN_TALON_COMMUNICATION_LOG_DIR/<workspace_id>.jsonl` |
| inspect runtime queues/failures/tokens | `/v1/admin/runtime/overview` |
| inspect compliance/investigation events | `/v1/audit/events` |

## Request Construction Guidance

### Plain Message

Use `CreateMessageRequest` when:

- a participant is simply speaking in the thread
- the message may optionally create generic downstream agent work

Important fields:

- `content`
- `visibility`
- `create_task`
- `requests`

### Tracked Interaction Request

Use `CreateInteractionRequest` when:

- questions and answers must be correlated
- several participants are involved
- partial answers should not resume the requesting agent

Important fields:

- `title`
- `questions`
- `selectors`
- `target_participant_ids`
- `completion_rule`

### Interaction Answer

Use `CreateInteractionAnswerRequest` when:

- the participant is answering a tracked request
- you want to optionally bind the answer to a subset of question IDs

## Role-Based Collaboration Guidance

When validating role-based routing:

- define the role in the workspace if needed
- ensure the participant advertises the role
- target the request by selector, not by display name
- keep the pilot deterministic by having one active human per role where possible

Good selector examples:

- `{"type": "role", "value": "team_lead"}`
- `{"type": "role", "value": "frontend_engineer"}`
- `{"type": "capability", "value": "qa_review"}`

## Debugging Checklist

If the flow behaves unexpectedly, inspect in this order:

1. `GET /v1/me`
   - confirm which authenticated human you are
2. `GET /v1/workspaces/{workspace_id}/participants`
   - confirm advertised roles/capabilities and participant IDs
3. `GET /v1/threads/{thread_id}/timeline`
   - confirm the messages were created
4. `GET /v1/requests/{request_id}`
   - confirm targets, answers, and aggregate status
5. `GET /v1/workspaces/{workspace_id}/communication-log`
   - confirm workspace-wide communication ordering
6. `OPEN_TALON_COMMUNICATION_LOG_DIR/<workspace_id>.jsonl`
   - confirm finalized messages were persisted to disk
7. `GET /v1/admin/runtime/overview`
   - confirm runnable or failed work when an agent should have resumed
8. `GET /v1/audit/events`
   - inspect authorization or mutation history when needed

## Common Mistakes

- reusing one local profile for multiple humans
- assuming `participant_id` is the human identity
- testing role-based selection with explicit participant IDs
- using `/v1/chat` for workflows that should use workspaces and threads
- expecting the communication log to include every internal runtime transition
- forgetting that non-member workspace reads intentionally return `404`

## Recommended Minimal Scenario

A good first end-to-end validation is:

1. create one workspace
2. attach two agents
3. create three human participants with advertised roles
4. create one shared thread
5. post one kickoff message
6. let an agent create a tracked request with role selectors
7. answer from separate user profiles
8. verify the requesting agent resumes only after the completion rule is satisfied
9. inspect the communication log API and JSONL file

That scenario exercises:

- auth
- participant materialization
- role-based selection
- tracked requests
- answer aggregation
- resumed execution
- collaboration logging

## Source Pointers

The most relevant implementation files for agent operators are:

- `apps/tui/open_talon_tui/user_client.py`
- `apps/tui/open_talon_tui/tui2.py`
- `services/gateway-edge/gateway_edge/routers/collaboration.py`
- `services/gateway-edge/gateway_edge/routers/auth.py`
- `services/gateway-edge/gateway_edge/routers/admin.py`
- `packages/contracts/open_talon_contracts/models.py`
