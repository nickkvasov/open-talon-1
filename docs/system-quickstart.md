# Open Talon System Quickstart

This is the fastest path to get the full local Open Talon system running with the current Keycloak-based auth flow.

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

`keycloak-init` is a local-only helper that normalizes Keycloak for development after the main container boots. It makes sure both the `master` and `open-talon` realms allow local HTTP access.

`openbao-init` is a local-only helper that initializes and unseals OpenBao, enables the `secret/` KV v2 mount, and recreates the stable local `root` token if needed.

If you want Mem0 graph memory locally, start the system with graph mode enabled:

```bash
./open-talon start --memgraph
```

That keeps Postgres as the canonical memory store and adds the optional local `memgraph` service for Mem0 graph retrieval. Graph retrieval itself is still controlled by the persisted memory-provider definition, not by the launcher flag.

## 3. Check The Main Endpoints

- Gateway: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Keycloak: [http://127.0.0.1:8081](http://127.0.0.1:8081)
- Open Talon realm issuer: [http://127.0.0.1:8081/realms/open-talon](http://127.0.0.1:8081/realms/open-talon)
- OpenID config: [http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration](http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration)
- Langfuse: [http://localhost:3000](http://localhost:3000)
- pgAdmin: [http://localhost:5050](http://localhost:5050)
- Memgraph bolt: `localhost:7688` when started with `./open-talon start --memgraph`

## 4. Default Local Credentials

- Postgres: `admin` / `password`
- pgAdmin: `admin@local.dev` / `admin`
- Keycloak admin: `admin` / `admin`
- Keycloak realm: `open-talon`
- Keycloak realm users:
  - `admin` / `admin123`
  - `supervisor` / `supervisor123`
  - `user1` / `user12345`
  - `user2` / `user22345`
- OpenBao root token: `root`
- Langfuse: `admin@example.com` / `admin123456`

All local defaults come from [`infrastructure/.env.example`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/.env.example).

OpenBao local data is persistent. Secrets survive `./open-talon stop` and `docker compose down` until you remove `infrastructure/data/openbao`.

Relevant layered-memory defaults from [`infrastructure/.env.example`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/.env.example):

- `OPEN_TALON_MEM0_COLLECTION=open_talon_memories`
- `OPEN_TALON_MEMGRAPH_URL=bolt://localhost:7688`
- `OPEN_TALON_MEMGRAPH_USER=memgraph`
- `OPEN_TALON_MEMGRAPH_PASSWORD=memgraph`

## 5. Keycloak Local Auth Model

- The imported `open-talon` realm is configured for local HTTP development with `sslRequired=none`.
- The local startup flow also runs a `keycloak-init` step that sets `sslRequired=none` for both `master` and `open-talon`.
- Keycloak is the primary end-user auth system for local Open Talon development.
- The TUI uses the `open-talon-tui` public client and authenticates with OIDC device flow.
- Future browser apps are expected to use the `open-talon-web` public client with authorization code + PKCE.
- Human identity is global in `users` and `auth_identities`.
- Workspace-local membership and roles are stored in `participants`.

## 6. First Keycloak Sign-In

If you want to inspect the realm in the Keycloak UI before using the TUI:

1. Open [http://127.0.0.1:8081](http://127.0.0.1:8081)
2. Sign in with the bootstrap admin account:
   - username: `admin`
   - password: `admin`
3. Switch to the `open-talon` realm
4. Open `Users` to inspect the default local users:
   - `admin`
   - `supervisor`
   - `user1`
   - `user2`

Important distinction:

- `admin` / `admin` is the Keycloak bootstrap admin account for the admin console
- `admin` / `admin123` is the default Open Talon realm user in `open-talon`
- the Open Talon realm user `admin` has the `open-talon-admin` realm role

## 7. Use The TUI With A Profile

For the most reliable terminal experience, start `tui2` with a named local profile:

```bash
./open-talon tui2 --profile admin
```

That opens the scrollback-first terminal client in normal terminal mode. Mouse selection works like a regular shell session, and URLs are printed as plain text so they stay easy to copy or open.

If you want to authenticate a profile before opening the terminal client, trigger the same device-login flow directly from the CLI:

```bash
./open-talon tui2 auth login --profile admin
```

Inside `tui2`, the basic first-run flow is:

```text
/auth login
/account whoami
/workspace list
```

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
/workspace list
/workspace create <name>
/workspace use <id|name>
/thread list
/thread create <title>
/thread use <id|title>
/links
/open <number|last|url>
/copy
/quit
```

Typical local usage examples:

```bash
./open-talon tui2 --profile supervisor
./open-talon tui2 --profile user1
./open-talon tui2 --profile user2
```

That lets multiple humans use the same machine without sharing identity. Each profile gets its own state and token files under `~/.open-talon/profiles/<profile>/`.

Recent live verification in local dev confirmed the end-to-end `tui2` flow for the realm user `admin`: profile bootstrap, `/account whoami`, `/thread create`, and a real message send all completed successfully against the running stack.

## 8. Quick Verification

Fast endpoint checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration
docker compose -f infrastructure/docker-compose.yaml ps keycloak keycloak-init
docker compose -f infrastructure/docker-compose.yaml logs --tail=50 keycloak-init keycloak
```

Targeted Python tests:

```bash
pytest tests/gateway-edge -q
pytest tests/tui -q
pytest tests/core-collab -q
pytest tests/infrastructure/test_keycloak_local_config.py -q
```

If you changed schema, auth, routing, or participant identity behavior, run:

```bash
pytest -q
```

## 9. Layered Memory Quick Notes

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

## 10. Seeded OpenAI Agent Smoke Test

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

Known current limitation:

- the seeded OpenAI path still posts raw OpenAI response JSON into the final thread message body; execution works, but response formatting is still rough

## 10. Common Keycloak Recovery Commands

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

## 11. Stop Everything

```bash
./open-talon stop
```

## Notes

- Human identity is global in `users` and `auth_identities`.
- Workspace-local presence and roles live in `participants`.
- Do not treat `participant_id` as a global user identity.
- OpenBao remains in the stack, but Keycloak is the primary end-user auth system.
