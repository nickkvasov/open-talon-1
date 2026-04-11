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
- `agent-loop-worker`
- `tool-worker`
- `reconciler`
- Postgres
- Kafka
- Valkey
- OpenBao
- Keycloak
- `keycloak-init`
- Ollama
- Langfuse and its backing services

`keycloak-init` is a local-only helper that normalizes Keycloak for development after the main container boots. It makes sure both the `master` and `open-talon` realms allow local HTTP access.

## 3. Check The Main Endpoints

- Gateway: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Keycloak: [http://127.0.0.1:8081](http://127.0.0.1:8081)
- Open Talon realm issuer: [http://127.0.0.1:8081/realms/open-talon](http://127.0.0.1:8081/realms/open-talon)
- OpenID config: [http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration](http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration)
- Langfuse: [http://localhost:3000](http://localhost:3000)
- pgAdmin: [http://localhost:5050](http://localhost:5050)

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

Start the TUI with a named local profile:

```bash
./open-talon tui \
  --profile nikolay \
  --oidc-issuer-url http://127.0.0.1:8081/realms/open-talon \
  --oidc-client-id open-talon-tui
```

For a simpler scrollback-first terminal client with normal mouse selection and terminal-native clickable links, use:

```bash
./open-talon tui2 --profile nikolay
```

For the local dev stack, `./open-talon tui` now defaults to:

- issuer: `http://127.0.0.1:8081/realms/open-talon`
- client id: `open-talon-tui`

So in most local cases you only need:

```bash
./open-talon tui --profile nikolay
```

If you want to authenticate a profile before opening the Textual UI, trigger the same device-login flow from the CLI:

```bash
./open-talon tui auth login \
  --profile nikolay \
  --oidc-issuer-url http://127.0.0.1:8081/realms/open-talon \
  --oidc-client-id open-talon-tui
```

Important behavior:

- each user on the same machine should use a different `--profile`
- profile state and tokens are stored under `~/.open-talon/profiles/<profile>/`
- the TUI uses Keycloak device flow for human login
- the TUI may start signed out so `/auth login` can be used, but collaboration actions still require Keycloak authentication
- the TUI now uses a simpler plain-log timeline so the core terminal controls stay reliable
- `/copy` copies the full timeline to the clipboard
- `/links` lists detected URLs and `/open <number|last|url>` opens one reliably
- `/quit` exits the TUI and `/clear` clears the visible timeline
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
./open-talon tui --profile supervisor --oidc-issuer-url http://127.0.0.1:8081/realms/open-talon --oidc-client-id open-talon-tui
./open-talon tui --profile user1 --oidc-issuer-url http://127.0.0.1:8081/realms/open-talon --oidc-client-id open-talon-tui
./open-talon tui --profile user2 --oidc-issuer-url http://127.0.0.1:8081/realms/open-talon --oidc-client-id open-talon-tui
```

That lets multiple humans use the same machine without sharing identity. Each profile gets its own state and token files under `~/.open-talon/profiles/<profile>/`.

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

## 9. Common Keycloak Recovery Commands

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

## 10. Stop Everything

```bash
./open-talon stop
```

## Notes

- Human identity is global in `users` and `auth_identities`.
- Workspace-local presence and roles live in `participants`.
- Do not treat `participant_id` as a global user identity.
- OpenBao remains in the stack, but Keycloak is the primary end-user auth system.
