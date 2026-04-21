# Open Talon System Quickstart

This is the fastest path to get the full local Open Talon system running with the current Keycloak-based auth flow.

For full current-state reference material, use:

- [system-api-reference.md](./system-api-reference.md)
- [agent-operations-guide.md](./agent-operations-guide.md)

## Prerequisites

- Docker with `docker compose`
- Python 3.12+
- A clean repo checkout

## 1. Bootstrap Python

From the repo root:

```bash
./scripts/bootstrap-python.sh
source .venv/bin/activate
```

This installs the shared contracts, services, TUI, and repo test dependencies into the root `.venv`.

## 2. Start The System

Launch the local infrastructure and the supported Python processes:

```bash
./open-talon start
```

The launcher now waits for both the gateway readiness endpoint and the Keycloak OIDC discovery document before it exits successfully, so browser and terminal auth flows should be ready when the command returns.

This starts:

- `gateway-edge`
- `agent-task-worker`
- `agent-loop-worker`
- `tool-worker`
- `reconciler`
- Postgres
- Kafka
- Valkey
- OpenBao
- `openbao-init`
- Keycloak
- `keycloak-init`
- Ollama
- Langfuse and its backing services

For audit specifically, the local stack now also provides:

- Postgres as the canonical append-only audit ledger store
- provider-backed non-canonical audit surfaces with local defaults:
  - relay provider: Kafka topic `talon.audit.events`
  - projection provider: ClickHouse
  - archive provider: MinIO for exports and daily chain checkpoints

If you want a local HyperDX UI plus OTLP intake endpoints, start the optional profile:

```bash
docker compose -f infrastructure/docker-compose.yaml --profile hyperdx up -d hyperdx
```

That exposes:

- HyperDX UI on [http://127.0.0.1:8080](http://127.0.0.1:8080)
- OTLP gRPC on `127.0.0.1:4317`
- OTLP HTTP on `127.0.0.1:4318`

If you want `agent-runtime` to export observability there, set these env vars before `./open-talon start`:

```bash
export AGENT_RUNTIME_OBSERVABILITY_PROVIDER=otlp
export AGENT_RUNTIME_OTLP_HTTP_ENDPOINT=http://127.0.0.1:4318/v1/traces
```

Optional provider-selection env vars for audit surfaces:

```bash
export AUDIT_RELAY_PROVIDER=kafka
export AUDIT_PROJECTION_PROVIDER=clickhouse
export AUDIT_ARCHIVE_PROVIDER=minio
```

Each audit provider can also be set to `none` for a local no-op derived surface while Postgres remains canonical.

`keycloak-init` is a local-only helper that normalizes Keycloak for development after the main container boots. It makes sure both the `master` and `open-talon` realms allow local HTTP access.

`openbao-init` is a local-only helper that initializes and unseals OpenBao, enables the `secret/` KV v2 mount, and recreates the stable local `root` token if needed.

If you want Mem0 graph memory locally, start the system with graph mode enabled:

```bash
./open-talon start --memgraph
```

That keeps Postgres as the canonical memory store and adds the optional local `memgraph` service for Mem0 graph retrieval. Graph retrieval itself is still controlled by the persisted memory-provider definition, not by the launcher flag.

## 3. Check The Main Endpoints

- Gateway: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- Gateway health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- Gateway ready: [http://127.0.0.1:8000/ready](http://127.0.0.1:8000/ready)
- API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Audit events API: [http://127.0.0.1:8000/v1/audit/events](http://127.0.0.1:8000/v1/audit/events)
- Audit export API: [http://127.0.0.1:8000/v1/audit/events/export](http://127.0.0.1:8000/v1/audit/events/export)
- Runtime overview API (admin only): [http://127.0.0.1:8000/v1/admin/runtime/overview](http://127.0.0.1:8000/v1/admin/runtime/overview)
- Keycloak: [http://127.0.0.1:8081](http://127.0.0.1:8081)
- Open Talon realm issuer: [http://127.0.0.1:8081/realms/open-talon](http://127.0.0.1:8081/realms/open-talon)
- OpenID config: [http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration](http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration)
- OpenBao: [http://127.0.0.1:8200](http://127.0.0.1:8200)
- Langfuse: [http://localhost:3000](http://localhost:3000)
- Langfuse worker: `localhost:3030`
- ClickHouse HTTP: [http://127.0.0.1:8123](http://127.0.0.1:8123)
- ClickHouse native: `localhost:9000`
- Kafka: `localhost:9092`
- Valkey: `localhost:6379`
- MinIO API: [http://127.0.0.1:9090](http://127.0.0.1:9090)
- MinIO console: [http://127.0.0.1:9091](http://127.0.0.1:9091)
- Forgejo: [http://127.0.0.1:3001](http://127.0.0.1:3001)
- Forgejo SSH: `localhost:2222`
- Ollama: [http://127.0.0.1:11434](http://127.0.0.1:11434)
- HyperDX UI when started with `--profile hyperdx`: [http://127.0.0.1:8080](http://127.0.0.1:8080)
- HyperDX OTLP gRPC when started with `--profile hyperdx`: `localhost:4317`
- HyperDX OTLP HTTP when started with `--profile hyperdx`: `localhost:4318`
- pgAdmin: [http://localhost:5050](http://localhost:5050)
- Memgraph bolt: `localhost:7688` when started with `./open-talon start --memgraph`
- Memgraph HTTP: [http://127.0.0.1:7444](http://127.0.0.1:7444) when started with `./open-talon start --memgraph`

## 4. Start The Admin Web

The browser admin app is optional, but it is the easiest way to exercise the OIDC browser flow and the admin-only management surfaces.

From the repo root:

```bash
cd apps/admin-web
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) and sign in with a seeded realm user that has the Keycloak `admin` role such as:

- `admin` / `admin123`
- `admin2` / `admin223`

Local browser defaults:

- SPA URL: `http://localhost:5173`
- gateway API: `http://127.0.0.1:8000`
- Keycloak base URL: `http://127.0.0.1:8081`
- realm: `open-talon`
- browser OIDC client: `open-talon-web`

The app also includes Playwright coverage:

```bash
npm run test:e2e:install
npm run test:e2e
```

See [apps/admin-web/README.md](/Users/nikolay.kvasov/Development/open-talon-1/apps/admin-web/README.md) for the full browser test matrix.

Current admin-web highlights:

- `Organizations` manages org creation and org memberships
- `Workspaces` filters by organization and creates workspaces in the selected org
- `Providers` switches between `Platform Global` and `Organization` scope
- `Swarm Resources` switches between `Platform Global` and `Organization` scope

## 5. Default Local Credentials

- Postgres: `admin` / `password`
- pgAdmin: `admin@local.dev` / `admin`
- Langfuse Postgres DB: `langfuse_db`
- Keycloak admin: `admin` / `admin`
- Keycloak realm: `open-talon`
- Keycloak realm users:
  - `admin` / `admin123`
  - `admin2` / `admin223`
  - `supervisor` / `supervisor123`
  - `supervisor2` / `supervisor223`
  - `user1` / `user12345`
  - `user2` / `user22345`
- OpenBao root token: `root`
- Langfuse: `admin@example.com` / `admin123456`
- Valkey password: `langfuse-dev-secret`
- MinIO: `minio` / `miniosecret`
- Forgejo: `forgejo` / `forgejo123`
- ClickHouse: `langfuse` / `langfuse`
- Memgraph: `memgraph` / `memgraph` when started with `./open-talon start --memgraph`

All local defaults come from [`infrastructure/.env.example`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/.env.example).

OpenBao local data is persistent. Secrets survive `./open-talon stop` and `docker compose down` until you remove `infrastructure/data/openbao`.

Relevant layered-memory defaults from [`infrastructure/.env.example`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/.env.example):

- `OPEN_TALON_MEM0_COLLECTION=open_talon_memories`
- `OPEN_TALON_MEMGRAPH_URL=bolt://localhost:7688`
- `OPEN_TALON_MEMGRAPH_USER=memgraph`
- `OPEN_TALON_MEMGRAPH_PASSWORD=memgraph`

Relevant runtime-guardrail defaults from [`infrastructure/.env.example`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/.env.example):

- `OPEN_TALON_GLOBAL_DAILY_TOKEN_CAP=0`
- `OPEN_TALON_WORKSPACE_DAILY_TOKEN_CAP=0`

`0` disables the cap. Workspace-specific overrides can be set in workspace metadata using either `limits.daily_token_cap` or top-level `daily_token_cap`.

## 6. Keycloak Local Auth Model

- The imported `open-talon` realm is configured for local HTTP development with `sslRequired=none`.
- The local startup flow also runs a `keycloak-init` step that sets `sslRequired=none` for both `master` and `open-talon`.
- Keycloak is the primary end-user auth system for local Open Talon development.
- The TUI uses the `open-talon-tui` public client and authenticates with OIDC device flow.
- The admin web uses the `open-talon-web` public client with authorization code + PKCE.
- Human identity is global in `users` and `auth_identities`.
- Organization membership and org roles are stored in `organization_memberships`.
- Workspace-local membership and roles are stored in `participants`.

Local multi-tenant defaults:

- the migration seeds one organization named `Default Organization` with slug `default`
- every workspace belongs to an organization
- `tui2`, `user-client`, and the admin web auto-select the org when exactly one organization is visible

Current local hardening defaults:

- global system-definition, global publish, provider-management, and runtime-overview APIs require the Keycloak `admin` role when using OIDC
- `GET /v1/workspaces` only returns workspaces where the authenticated human already has a participant
- non-members should receive `404` for workspace, thread, memory, and workspace-scoped asset reads
- workspace `admin` or `supervisor` is required for workspace role-definition changes, workspace tool management, workspace Git repository creation, and workspace asset publishing
- risky tools must be created as `trust_level="trusted"` if they use `workspace_access=read_write`, `network=full`, or `local_process`

## 6A. Collaboration Domain Model

The running system uses the tenant hierarchy `platform > organization > workspace > thread`:

- `organization` is the tenant boundary above workspaces
- `workspace` is the collaboration boundary inside an organization
- `participant` is the workspace-local state for a human or agent
- `thread` is the shared conversation and event stream inside a workspace
- `timeline_message` is the ordered thread-visible message record
- `interaction_request` is the tracked question workflow attached to a thread
- `task`, `run`, `run_step`, and `tool_call` are the durable execution records owned by the collaboration kernel and consumed by `agent-runtime`

Identity and execution boundaries:

- human identity is global in `users` and `auth_identities`
- organization membership and org roles live in `organizations` and `organization_memberships`
- agent identity/configuration is global in `system_agents`
- workspace-local presence, roles, capabilities, and visibility live in `participants`
- Postgres is the source of truth for collaboration and execution state
- Kafka is the fanout and worker wake-up bus, not the canonical store

Tracked interaction requests are the resumable collaboration path when one participant, often an agent, needs answers from one or more other participants before continuing work. Each request may contain multiple ordered questions, target explicit participants or selector buckets, and wait for a completion rule such as:

- `all_targets`
- `minimum_answers`
- `one_per_selector_bucket`
- `custom_targets`

Current thread-native request flow:

1. A user or agent posts a message or structured request to a thread.
2. `core-collab` persists the request, resolved targets, rendered thread message, and collaboration events.
3. Participants answer in-thread with normal messages linked to the request.
4. `core-collab` aggregates answers until the completion rule is satisfied.
5. When complete, `core-collab` creates a follow-up task only for the original requesting agent.
6. `agent-runtime` resumes that agent with the request and accumulated answers in context.

For workspace debugging, there is also a workspace communication-log view backed by canonical `timeline_messages`. It aggregates regular thread messages, rendered interaction requests, and interaction answers across the workspace. Finalized communication entries are also appended to workspace JSONL files under `OPEN_TALON_COMMUNICATION_LOG_DIR` so the collaboration trace can be inspected from disk. Those JSONL files rotate automatically using `OPEN_TALON_COMMUNICATION_LOG_MAX_BYTES` and `OPEN_TALON_COMMUNICATION_LOG_BACKUP_COUNT`. Local `./open-talon start` service logs under `.run/` also rotate automatically using `OPEN_TALON_SERVICE_LOG_MAX_BYTES` and `OPEN_TALON_SERVICE_LOG_BACKUP_COUNT`. The HTTP route is intended for workspace `admin` or `supervisor` users when using OIDC.

Relevant collaboration APIs:

- `GET /v1/workspaces/{workspace_id}/communication-log`
- `POST /v1/threads/{thread_id}/messages`
- `GET /v1/threads/{thread_id}/timeline`
- `GET /v1/threads/{thread_id}/requests`
- `POST /v1/threads/{thread_id}/requests`
- `GET /v1/requests/{request_id}`
- `PATCH /v1/requests/{request_id}`
- `POST /v1/requests/{request_id}/answers`

## 7. First Keycloak Sign-In

If you want to inspect the realm in the Keycloak UI before using the TUI:

1. Open [http://127.0.0.1:8081](http://127.0.0.1:8081)
2. Sign in with the bootstrap admin account:
   - username: `admin`
   - password: `admin`
3. Switch to the `open-talon` realm
4. Open `Users` to inspect the default local users:
   - `admin`
   - `admin2`
   - `supervisor`
   - `supervisor2`
   - `user1`
   - `user2`

Important distinction:

- `admin` / `admin` is the Keycloak bootstrap admin account for the admin console
- `admin` / `admin123` is the default Open Talon realm user in `open-talon`
- the Open Talon realm user `admin` has the `admin` realm role

## 8. Use The TUI With A Profile

For the most reliable terminal experience, start `tui2` with a named local profile:

```bash
./open-talon tui2 --profile admin
```

That opens the scrollback-first terminal client in normal terminal mode. Mouse selection works like a regular shell session, and URLs are printed as plain text so they stay easy to copy or open.

If you need software development agents to operate several human-user sessions end to end, start one `user-client` instance per user profile instead:

```bash
./open-talon user-client --profile user1
```

`user-client` is line-oriented and profile-isolated, so it is easier to drive over stdin/stdout than `tui2` when multiple automated users need to coordinate in parallel.

If you want to authenticate a profile before opening the terminal client, trigger the same device-login flow directly from the CLI:

```bash
./open-talon tui2 auth login --profile admin
```

The same device-login flow is available for `user-client`:

```bash
./open-talon user-client auth login --profile user1
```

Inside `tui2`, the basic first-run flow is:

```text
/auth login
/account whoami
/organization list
/organization use <id|slug|name>
/workspace list
```

If your user can only see one organization, `tui2` auto-selects it after login. On a fresh local stack that is usually the seeded `Default Organization`.

The full-screen Textual UI is still available:

```bash
./open-talon tui --profile admin
```

For the local dev stack, both TUI entrypoints default to:

- issuer: `http://127.0.0.1:8081/realms/open-talon`
- client id: `open-talon-tui`

So in most local cases you only need:

```bash
./open-talon tui2 --profile admin
```

If you want to authenticate a profile before opening the full-screen Textual UI, trigger the same device-login flow from the CLI:

```bash
./open-talon tui auth login \
  --profile admin \
  --oidc-issuer-url http://127.0.0.1:8081/realms/open-talon \
  --oidc-client-id open-talon-tui
```

Important behavior:

- each user on the same machine should use a different `--profile`
- profile state and tokens are stored under `~/.open-talon/profiles/<profile>/`
- the TUI uses Keycloak device flow for human login
- the TUI may start signed out so `/auth login` can be used, but collaboration actions still require Keycloak authentication
- `tui2` is the recommended client when you want reliable terminal scrollback, mouse copy/select, and plain clickable/copyable URLs
- `/copy` copies the full `tui2` timeline to the clipboard
- `/links` lists detected URLs and `/open <number|last|url>` opens one reliably in `tui2`
- `/quit` exits the active TUI client and `/clear` clears the visible timeline
- the gateway derives the authenticated human actor server-side
- the TUI no longer owns human identity through a local `participant_id`
- only the current per-profile TUI state/token format is supported; older local auth/state is not migrated and existing users must sign in again
- `user-client` is the recommended entrypoint when one software agent needs to control each human test user separately
- `user-client --output json` emits machine-readable command results for automation
- `workspace list` defaults to the selected organization in `tui2` and `user-client`; use `workspace list all` to see every visible workspace
- `workspace create` requires a selected organization in `tui2` and `user-client`
- `user-client` accepts direct `workspace use <uuid>` and `thread use <uuid>` commands, which helps multiple profiles join the same shared scenario explicitly

Useful TUI commands:

```text
/auth login
/auth logout
/account login
/account whoami
/account list
/account switch <profile>
/account logout
```

Useful `tui2` commands:

```text
/help
/auth login
/auth logout
/organization list
/organization show [id|slug|name]
/organization use <id|slug|name>
/workspace list [all]
/workspace create <name>
/workspace use <id|name>
/thread list
/thread create <title>
/thread use <id|title>
/tool request [--scope global|organization] <text>
/links
/open <number|last|url>
/copy
/quit
```

Useful `user-client` commands:

```text
help
status
auth login
auth logout
organization list
organization show [id|slug|name]
organization use <id|slug|name>
workspace list [all]
workspace create <name>
workspace use <id|name>
thread list
thread create <title>
thread use <id|title>
role list
role use <role> [:: <description> :: <cap1,cap2>]
send <text>
timeline [limit]
request list [open|all]
request show <id|title|current>
request answer <id|title|current> :: <text>
log [limit]
quit
```

Typical local usage examples:

```bash
./open-talon tui2 --profile supervisor
./open-talon tui2 --profile user1
./open-talon tui2 --profile user2
./open-talon user-client --profile user1
./open-talon user-client --profile user2
```

That lets multiple humans use the same machine without sharing identity. Each profile gets its own state and token files under `~/.open-talon/profiles/<profile>/`.

Recent live verification in local dev confirmed the end-to-end `tui2` flow for the realm user `admin`: profile bootstrap, `/account whoami`, `/thread create`, and a real message send all completed successfully against the running stack.

## 8A. Generate A Tool With Tinker

Tinker is the seeded tool-generation agent. It must be attached to a workspace before it can accept tool requests there.

Typical local flow:

1. Sign in as a workspace `admin` or `supervisor`.
2. Select an organization and workspace.
3. Attach `Tinker` to that workspace.
4. Open a thread and ask Tinker for a tool.
5. Approve the generated revision in the admin web `Tool Generation` page.
6. Manually attach the published tool to the workspace.
7. Ask another attached agent to use the tool.

In `tui2`, a request looks like:

```text
/tool request Build a repo statistics tool for this platform
/tool request --scope organization Build a Fibonacci calculator tool that accepts integer n and returns the Fibonacci value
```

Current publication rules:

- `global` requests publish to the global system catalog
- `organization` requests publish to the current organization catalog
- approval never auto-attaches the tool to a workspace
- workspace `admin` or `supervisor` users attach it later with `PUT /v1/workspaces/{workspace_id}/tools/{tool_id}`

Useful routes:

```text
POST /v1/workspaces/{workspace_id}/agents
POST /v1/threads/{thread_id}/messages
GET /v1/threads/{thread_id}/tool-generation/requests
POST /v1/tool-generation/revisions/{revision_id}/approve
PUT /v1/workspaces/{workspace_id}/tools/{tool_id}
```

For a deeper walkthrough, see [tinker-tool-generation.md](/Users/nikolay.kvasov/Development/open-talon-1/docs/tinker-tool-generation.md).

## 9. Quick Verification

Fast endpoint checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration
docker compose -f infrastructure/docker-compose.yaml ps keycloak keycloak-init
docker compose -f infrastructure/docker-compose.yaml logs --tail=50 keycloak-init keycloak
```

Operator check for the runtime overview endpoint:

```bash
curl -H "Authorization: Bearer <admin-token>" \
  http://127.0.0.1:8000/v1/admin/runtime/overview
```

Expected operator signals:

- pending and claimed counts for tasks, run steps, and tool calls
- failed counts for the last 24 hours
- oldest pending ages for run steps and tool calls
- current-day token totals globally and by workspace

If you enable token caps and a run hits the limit, the affected run step should fail with stop reason `budget_exhausted`.

Targeted Python tests:

```bash
pytest tests/gateway-edge -q
pytest tests/tui -q
pytest tests/core-collab -q
pytest tests/infrastructure/test_keycloak_local_config.py -q
```

Tinker-specific verification:

```bash
pytest tests/business-cases/test_tinker_tool_generation.py -q
pytest -m integration tests/infrastructure/test_tinker_live_system.py -q -s
```

The live Tinker system test expects `gemma4:latest` to be available in the local Ollama instance.

If you changed schema, auth, routing, or participant identity behavior, run:

```bash
pytest -q
```

## 10. Admin Web Deployment Notes

The built admin SPA can now be promoted across environments without rebuilding if you replace [`apps/admin-web/public/runtime-config.json`](/Users/nikolay.kvasov/Development/open-talon-1/apps/admin-web/public/runtime-config.json) in the deployed artifact.

Example deployed config:

```json
{
  "gatewayUrl": "https://api.example.com",
  "keycloakBaseUrl": "https://sso.example.com",
  "keycloakRealm": "open-talon",
  "oidcClientId": "open-talon-web",
  "appBasePath": "/admin"
}
```

Important deployment rules:

- `appBasePath` must match the subpath where the SPA is mounted
- the reverse proxy or static host still needs normal SPA fallback behavior for deep links such as `/admin/workspaces`
- the built bundle uses relative asset paths, so it can be served from `/` or a subpath
- the Keycloak client redirect URIs and post-logout redirect URIs must include the deployed browser URL

## 11. Audit Logging Quick Checks

Audit is available as soon as the stack is up.

Current model:

- Postgres `audit_event_ledger` is the source of truth
- workspace-scoped chains use `workspace:{workspace_id}`
- organization-scoped chains use `organization:{organization_id}`
- global/system audit uses the `global` partition
- relay, projection, and archive surfaces are provider-backed and replaceable
- local defaults are Kafka for relay, ClickHouse for projection, and MinIO for archive/export/checkpoint storage
- background replay repopulates the configured projection provider from the Postgres ledger if the projector falls behind
- background retention exports old ledger rows through the configured archive provider and prunes the Postgres hot window after snapshotting chain state

Current audit APIs:

```bash
curl -H "Authorization: Bearer <admin-token>" \
  "http://127.0.0.1:8000/v1/audit/events?limit=20"

curl -H "Authorization: Bearer <admin-token>" \
  "http://127.0.0.1:8000/v1/audit/chains/global/verify"

curl -H "Authorization: Bearer <org-admin-token>" \
  "http://127.0.0.1:8000/v1/organizations/<organization_id>/audit/events?limit=20"

curl -X POST http://127.0.0.1:8000/v1/audit/events/export \
  -H "Authorization: Bearer <admin-token>" \
  -H 'Content-Type: application/json' \
  -d '{"limit":100}'
```

Current access model:

- system `admin` can query, verify, and export globally
- organization `owner` and `admin` can query and export organization-scoped audit
- workspace `admin` and `supervisor` can read workspace-scoped audit
- regular `user` cannot read audit

Useful local checks:

```bash
docker compose -f infrastructure/docker-compose.yaml ps kafka clickhouse minio
docker compose -f infrastructure/docker-compose.yaml logs --tail=50 kafka clickhouse minio
pytest tests/gateway-edge/test_audit_api.py -q
pytest tests/gateway-edge/test_event_service.py -q
pytest tests/core-collab/test_repository_integration.py -q
```

Note:

- the canonical audit API remains Postgres-backed even when relay, projection, or archive providers are disabled or failing
- HyperDX is available through the optional `hyperdx` compose profile, but it is an observability sink, not the authoritative audit interface
- `agent-runtime` observability export is provider-backed and selected with `AGENT_RUNTIME_OBSERVABILITY_PROVIDER`

## 12. Layered Memory Quick Notes

Open Talon uses layered memory with three scopes:

- `run`: scratch memory for a single agent run
- `thread`: shared memory for thread participants
- `workspace`: confirmed memory promoted from thread-level work

Canonical memory always lives in Postgres. Mem0 and optional Memgraph are derived retrieval layers.

Useful memory-provider endpoints:

```bash
curl http://127.0.0.1:8000/v1/memory-providers
curl -X POST http://127.0.0.1:8000/v1/memory-providers/validate \
  -H 'Content-Type: application/json' \
  -d '{
    "actor": {
      "participant_id": "00000000-0000-0000-0000-000000000001",
      "participant_type": "user",
      "display_name": "admin"
    },
    "provider_key": "mem0-graph",
    "display_name": "Mem0 Graph",
    "description": "Local graph-enabled memory provider",
    "provider": "mem0",
    "enabled": true,
    "config": {
      "enable_graph": true,
      "vector_store": {"provider": "pgvector", "config": {}},
      "graph_store": {"provider": "memgraph", "config": {"url": "bolt://memgraph:7687"}}
    }
  }'
```

If you run Docker Compose directly instead of `./open-talon start`, enable the optional graph service with:

```bash
docker compose -f infrastructure/docker-compose.yaml --profile mem0-graph up -d
```

## 13. Seeded OpenAI Agent Smoke Test

The local migrations seed:

- `local-ollama`
- `openai-responses`
- sample system agent `Reasoning Planner` with `agent_id` `33333333-3333-3333-3333-333333333333`

To test the seeded OpenAI-backed agent end to end:

1. Store a real OpenAI key in local OpenBao:

```bash
curl -X POST http://127.0.0.1:8200/v1/secret/data/open-talon/llm/openai \
  -H 'X-Vault-Token: root' \
  -H 'Content-Type: application/json' \
  -d '{"data":{"api_key":"sk-..."}}'
```

2. Run the local smoke harness from the repo root:

```bash
VALKEY_PASSWORD=langfuse-dev-secret PYTHONPATH=services/gateway-edge:packages/contracts ./.venv/bin/python - <<'PY'
import asyncio
import json
import time

import httpx

from gateway_edge.auth.api_key import create_api_key
from gateway_edge.models import ApiKeyCreate
from gateway_edge.services.session import setup_valkey, teardown_valkey

AGENT_ID = "33333333-3333-3333-3333-333333333333"
ACTOR = {
    "participant_id": "00000000-0000-0000-0000-000000000001",
    "participant_type": "user",
    "display_name": "Admin",
}

async def main() -> None:
    await setup_valkey()
    try:
        api_key = await create_api_key(ApiKeyCreate(label="quickstart-agent-smoke"))
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:8000",
            headers={"X-API-Key": api_key.raw_key},
            timeout=30.0,
            trust_env=False,
        ) as client:
            workspace_resp = await client.post(
                "/v1/workspaces",
                json={"name": f"Quickstart Agent Test {int(time.time())}", "actor": ACTOR},
            )
            workspace_resp.raise_for_status()
            workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

            attach_resp = await client.post(
                f"/v1/workspaces/{workspace_id}/agents",
                json={"actor": ACTOR, "agent_id": AGENT_ID},
            )
            attach_resp.raise_for_status()

            thread_resp = await client.post(
                f"/v1/workspaces/{workspace_id}/threads",
                json={"title": "Seeded agent smoke test", "actor": ACTOR},
            )
            thread_resp.raise_for_status()
            thread_id = thread_resp.json()["thread"]["thread_id"]

            message_resp = await client.post(
                f"/v1/threads/{thread_id}/messages",
                json={
                    "actor": ACTOR,
                    "content": "Plan a three-step rollout for adding Anthropic as a new provider, including validation and tests.",
                    "visibility": "public",
                },
            )
            message_resp.raise_for_status()

            for _ in range(60):
                timeline_resp = await client.get(f"/v1/threads/{thread_id}/timeline")
                timeline_resp.raise_for_status()
                timeline = timeline_resp.json()
                if len(timeline.get("messages", [])) >= 2:
                    print(json.dumps(timeline, indent=2))
                    return
                await asyncio.sleep(2)

            raise RuntimeError("seeded agent did not reply within 120 seconds")
    finally:
        await teardown_valkey()

asyncio.run(main())
PY
```

Expected result:

- the thread timeline contains your message and at least one reply from `Reasoning Planner`
- the reply confirms the full path is working: gateway, durable task creation, `agent-task-worker`, `agent-loop-worker`, OpenBao secret resolution, and the OpenAI provider call
- the same flow should also create correlated boundary, semantic, and runtime audit events for the workspace/thread path

Known current limitation:

- the seeded OpenAI path still posts raw OpenAI response JSON into the final thread message body; execution works, but response formatting is still rough

## 14. Common Keycloak Recovery Commands

If the local Keycloak UI says HTTPS is required or the realm state looks stale:

```bash
cd /Users/nikolay.kvasov/Development/open-talon-1/infrastructure
docker compose up -d keycloak keycloak-init
docker compose logs --tail=100 keycloak-init keycloak
```

If you need to fully recreate the local Keycloak state:

```bash
cd /Users/nikolay.kvasov/Development/open-talon-1/infrastructure
docker compose stop keycloak keycloak-init
rm -rf /Users/nikolay.kvasov/Development/open-talon-1/infrastructure/data/keycloak
docker compose up -d keycloak keycloak-init
```

Expected healthy signal from the helper logs:

- `Keycloak local dev realms updated.`

## 15. Stop Everything

```bash
./open-talon stop
```

## Notes

- Human identity is global in `users` and `auth_identities`.
- Workspace-local presence and roles live in `participants`.
- Do not treat `participant_id` as a global user identity.
- OpenBao remains in the stack, but Keycloak is the primary end-user auth system.
