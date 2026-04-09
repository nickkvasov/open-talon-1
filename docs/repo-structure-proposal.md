# Open Senate Repository Structure Proposal

## Objective

Restructure the repository so high-level functional components are:

- decoupled
- independently testable
- independently releasable
- able to evolve without touching the whole codebase

The main design principle is:

- shared contracts live in packages
- runtime behavior lives in services
- user-facing clients live in apps
- infrastructure and deployment stay outside business logic

## Current Problems

The current layout is still centered around a single gateway package plus infrastructure:

- `api-gateway/` contains API edge, domain models, Kafka integration, auth, TUI, and web UI
- `README.md` still describes the repo mainly as infrastructure
- tests patch gateway internals directly rather than targeting stable cross-service contracts
- collaboration concepts like workspaces, threads, whiteboard memory, and routing are not yet isolated as separate concerns

This makes the gateway the accidental center of the system.

## Proposed Top-Level Structure

```text
open-senate/
  apps/
    web/
    tui/
  services/
    gateway-edge/
    core-collab/
    workspace-memory/
    presence-directory/
    task-router/
    agent-runtime/
  packages/
    contracts/
    events-sdk/
    auth-sdk/
    testing/
  deploy/
    infrastructure/
  docs/
  tests/
```

## Component Responsibilities

## apps/web

Owns:

- browser UI
- thread/workspace navigation
- whiteboard UX
- participant directory UX

Should depend on:

- public APIs and event streams only

Should not depend on:

- Python service internals
- Kafka directly

## apps/tui

Owns:

- terminal UX
- operator workflows
- debugging and admin interaction

Should depend on:

- gateway-edge HTTP and WS APIs

## services/gateway-edge

Owns:

- FastAPI edge
- auth enforcement
- SSE and WebSocket fan-out
- client sessions and connection management
- public REST and streaming APIs

Should not own:

- canonical collaboration truth
- whiteboard persistence
- routing policy

## services/core-collab

This is the main system kernel.

Owns:

- workspaces
- threads
- memberships
- canonical event validation
- event sequencing
- append-only event log
- thread lifecycle
- collaboration permissions

This is the right home for `core-collab`.

## services/workspace-memory

Owns:

- workspace whiteboard memory
- memory entry CRUD and versioning
- promotion of durable insights from threads into workspace memory
- whiteboard projections

## services/presence-directory

Owns:

- participant profiles
- roles
- capabilities
- workspace participant directory
- online/busy/offline state

## services/task-router

Owns:

- mentions and addressing resolution
- role-based routing
- capability-based routing
- task creation
- candidate agent selection
- optional semantic routing later

## services/agent-runtime

Owns:

- reusable execution loop for agents
- task claim/release protocol
- progress publishing
- artifact publication
- capability advertisement

Later, specific agents can live under:

- `services/agents/researcher`
- `services/agents/reviewer`
- `services/agents/coder`

or as separate repos if needed.

## packages/contracts

Owns:

- Pydantic models
- event envelope definitions
- command schemas
- workspace/thread/task/participant schemas
- API DTOs that are shared across services

Rules:

- no FastAPI app bootstrapping
- no DB code
- no Kafka client code

## packages/events-sdk

Owns:

- Kafka topic helpers
- producers and consumers
- event serialization
- schema versioning helpers
- idempotency and correlation helpers

## packages/auth-sdk

Owns:

- shared auth abstractions
- permission types
- workspace/thread access models

## packages/testing

Owns:

- reusable fakes
- contract test helpers
- event builders
- test fixtures for cross-service integration

## deploy/infrastructure

Owns:

- docker-compose
- infra scripts
- local bootstrap
- environment examples

This is just a rename/elevation of the current infrastructure folder.

## Proposed Concrete Tree

```text
open-senate/
  apps/
    web/
      package.json
      src/
    tui/
      pyproject.toml
      tui_app/
  services/
    gateway-edge/
      pyproject.toml
      gateway_edge/
        main.py
        config.py
        auth/
        routers/
        ws/
        sse/
    core-collab/
      pyproject.toml
      core_collab/
        main.py
        commands/
        events/
        sequencing/
        projections/
        repositories/
        services/
    workspace-memory/
      pyproject.toml
      workspace_memory/
        main.py
        models/
        projections/
        repositories/
        services/
    presence-directory/
      pyproject.toml
      presence_directory/
        main.py
        models/
        services/
        projections/
    task-router/
      pyproject.toml
      task_router/
        main.py
        routing/
        policies/
        services/
    agent-runtime/
      pyproject.toml
      agent_runtime/
        main.py
        claiming/
        execution/
        publishing/
  packages/
    contracts/
      pyproject.toml
      open_senate_contracts/
        events.py
        commands.py
        workspace.py
        thread.py
        participant.py
        task.py
        artifact.py
    events-sdk/
      pyproject.toml
      open_senate_events/
        producer.py
        consumer.py
        topics.py
        envelope.py
    auth-sdk/
      pyproject.toml
      open_senate_auth/
        principals.py
        permissions.py
        policies.py
    testing/
      pyproject.toml
      open_senate_testing/
        fixtures/
        fakes/
        builders/
  deploy/
    infrastructure/
      docker-compose.yaml
      .env.example
      ollama-entrypoint.sh
  docs/
    collaboration-system-design.md
    repo-structure-proposal.md
  tests/
    gateway-edge/
    core-collab/
    workspace-memory/
    presence-directory/
    task-router/
    integration/
```

## Mapping From Current Files

## Move infrastructure

Current:

- `infrastructure/docker-compose.yaml`
- `infrastructure/ollama-entrypoint.sh`
- `infrastructure/.env.example`

Proposed:

- `deploy/infrastructure/docker-compose.yaml`
- `deploy/infrastructure/ollama-entrypoint.sh`
- `deploy/infrastructure/.env.example`

## Split api-gateway

Current:

- `api-gateway/app/main.py`
- `api-gateway/app/config.py`
- `api-gateway/app/auth/*`
- `api-gateway/app/routers/*`
- `api-gateway/app/services/*`
- `api-gateway/app/db/postgres.py`
- `api-gateway/app/models.py`
- `api-gateway/web/*`
- `api-gateway/tui/*`

Proposed:

### gateway-edge

- `api-gateway/app/main.py`
  -> `services/gateway-edge/gateway_edge/main.py`

- `api-gateway/app/config.py`
  -> `services/gateway-edge/gateway_edge/config.py`

- `api-gateway/app/auth/middleware.py`
  -> `services/gateway-edge/gateway_edge/auth/middleware.py`

- `api-gateway/app/auth/api_key.py`
  -> split:
  - edge request validation remains in `services/gateway-edge/gateway_edge/auth/`
  - key management should eventually move to a dedicated identity or access service

- `api-gateway/app/auth/openbao.py`
  -> `services/gateway-edge/gateway_edge/auth/openbao.py`

- `api-gateway/app/routers/health.py`
  -> `services/gateway-edge/gateway_edge/routers/health.py`

- `api-gateway/app/routers/admin.py`
  -> `services/gateway-edge/gateway_edge/routers/admin.py`
  and later likely move most admin operations out of edge

- `api-gateway/app/routers/chat.py`
  -> split into:
  - `services/gateway-edge/gateway_edge/routers/chat_compat.py`
  - later add workspace/thread routers in edge that proxy to core-collab

- `api-gateway/app/services/session.py`
  -> `services/gateway-edge/gateway_edge/services/session.py`

- `api-gateway/app/services/events.py`
  -> split:
  - edge fan-out and client stream correlation in `services/gateway-edge`
  - canonical event handling protocol in `packages/events-sdk`

- `api-gateway/app/db/postgres.py`
  -> do not keep as a shared catch-all
  - edge-specific storage in `services/gateway-edge/gateway_edge/repositories/`

### contracts

- `api-gateway/app/models.py`
  -> split across:
  - `packages/contracts/open_senate_contracts/events.py`
  - `packages/contracts/open_senate_contracts/thread.py`
  - `packages/contracts/open_senate_contracts/participant.py`
  - `packages/contracts/open_senate_contracts/task.py`
  - `packages/contracts/open_senate_contracts/api.py`

### apps

- `api-gateway/web/*`
  -> `apps/web/`

- `api-gateway/tui/*`
  -> `apps/tui/`

## Create new services from today’s planned concepts

These do not exist yet as code, but should be created as first-class components instead of being absorbed into the gateway:

- `services/core-collab/`
- `services/workspace-memory/`
- `services/presence-directory/`
- `services/task-router/`

## Move tests

Current:

- `test/api-gateway/*`
- `test/infrastructure/*`

Proposed:

- `tests/gateway-edge/*`
- `tests/core-collab/*`
- `tests/workspace-memory/*`
- `tests/presence-directory/*`
- `tests/task-router/*`
- `tests/integration/*`
- `tests/infrastructure/*`

## Dependency Rules

Use strict dependency direction:

```text
apps -> gateway-edge API
gateway-edge -> contracts, events-sdk, auth-sdk
core-collab -> contracts, events-sdk, auth-sdk
workspace-memory -> contracts, events-sdk
presence-directory -> contracts, events-sdk
task-router -> contracts, events-sdk
agent-runtime -> contracts, events-sdk
```

Forbidden patterns:

- apps importing service internals
- one service importing another service’s repository layer
- contracts importing runtime libraries like FastAPI or aiokafka
- tests patching private modules across service boundaries unless they are service-local tests

## Packaging Strategy

Prefer one `pyproject.toml` per app, service, and package.

That gives:

- isolated dependency graphs
- smaller install surfaces
- service-local CI jobs
- easier container builds

Examples:

- `services/gateway-edge/pyproject.toml`
- `services/core-collab/pyproject.toml`
- `packages/contracts/pyproject.toml`

## Suggested First Extraction Steps

Do not split everything in one pass.

## Step 1

Extract shared contracts:

- create `packages/contracts`
- move `api-gateway/app/models.py` into contracts
- update imports in the gateway to consume those contracts

## Step 2

Separate clients:

- move `api-gateway/web` to `apps/web`
- move `api-gateway/tui` to `apps/tui`

## Step 3

Rename and isolate gateway:

- move `api-gateway` service code to `services/gateway-edge`
- keep compatibility endpoints there

## Step 4

Introduce `services/core-collab`:

- workspace, thread, membership, canonical events
- gateway becomes an edge adapter instead of the system core

## Step 5

Split secondary concerns:

- workspace-memory
- presence-directory
- task-router

## Suggested Ownership Boundaries

If different teams or contributors work independently, the cleanest ownership split is:

- Team A: `gateway-edge` and public APIs
- Team B: `core-collab`
- Team C: `workspace-memory` and participant directory
- Team D: `task-router` and agent runtime
- Team E: `apps/web` and `apps/tui`

That structure reduces merge conflicts because teams mostly share contracts, not runtime internals.

## Recommended Naming

Your naming idea is good.

I would use:

- `core-collab`
- `gateway-edge`
- `workspace-memory`
- `presence-directory`
- `task-router`
- `agent-runtime`

These names are specific enough to clarify ownership without being too narrow.

## Final Recommendation

If you want a modular architecture without turning the repo into operational chaos too early, make these the first permanent boundaries:

- `packages/contracts`
- `services/gateway-edge`
- `services/core-collab`
- `apps/web`
- `apps/tui`

Then add:

- `services/workspace-memory`
- `services/presence-directory`
- `services/task-router`

once the collaboration behavior starts to outgrow a single kernel.
