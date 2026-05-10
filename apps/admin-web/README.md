# Open Talon Admin Web

This app includes a Playwright browser suite that signs in through the default local Keycloak OIDC provider, validates the main admin surfaces, and exercises a few real management flows against the local gateway. Authorization decisions are still enforced by Open Talon IAM on the backend.

Agent catalog management supports both manual database-backed definitions and Git-managed definitions. Git-managed agents are authored as Forgejo bundles and published through gateway APIs into the active `system_agents` projection with immutable `agent_definition_versions` history. The Swarm Resources page exposes validation, publish, archive upload, and version activation controls for Git-managed bundles.

The Libraries page manages organization, project, and workspace libraries, adds text or uploaded file items, attaches organization/project libraries to workspaces, and queues explicit retriever indexing jobs.

The Methodologies page manages organization methodology blueprints. It creates
Researcher-backed dossier requests, shows Methodologist drafts, supports
human draft edits and versioned edits for approved methodologies, approves or
rejects versions, applies approved harness drafts to workspaces, and archives
methodologies without deleting their dossier provenance.

## Prerequisites

Start the local backend stack from the repo root:

```bash
./scripts/bootstrap-python.sh
source .venv/bin/activate
./open-talon start
```

`./open-talon start` now waits for both the gateway readiness check and the Keycloak OIDC discovery document, so the browser suite should not race the local auth stack on a clean startup.

That should make these endpoints available:

- Gateway: `http://127.0.0.1:8000`
- Keycloak: `http://127.0.0.1:8081`

Install admin-web dependencies once:

```bash
cd apps/admin-web
npm install
```

Install the Playwright browser once:

```bash
npm run test:e2e:install
```

## Run The Browser Suite

The Playwright config starts the Vite dev server automatically on `http://localhost:5173`.

```bash
cd apps/admin-web
npm run test:e2e
```

For a visible browser:

```bash
npm run test:e2e:headed
```

## Default Credentials

The smoke test uses the seeded local Keycloak admin account by default:

- username: `admin`
- password: `admin123`

Override them if needed:

```bash
ADMIN_WEB_E2E_USERNAME=admin2 ADMIN_WEB_E2E_PASSWORD=admin223 npm run test:e2e
```

The local Keycloak `admin` role is still the bootstrap path for platform-admin access in development. Steady-state global and organization authorization is modeled in Open Talon IAM.

## Runtime Config

The built app now reads browser runtime config from `public/runtime-config.json`, so one artifact can be promoted across environments without rebuilding. Defaults are aligned to the repo's local stack:

- `gatewayUrl: 'http://127.0.0.1:8000'`
- `keycloakBaseUrl: 'http://127.0.0.1:8081'`
- `keycloakRealm: 'open-talon'`
- `oidcClientId: 'open-talon-web'`
- `appBasePath: '/'`

For local development, the app still accepts Vite env overrides:

- `VITE_GATEWAY_URL`
- `VITE_KEYCLOAK_BASE_URL`
- `VITE_KEYCLOAK_REALM`
- `VITE_OIDC_CLIENT_ID`
- `VITE_APP_BASE_PATH`

You can override them when starting the dev server, for example:

```bash
VITE_GATEWAY_URL=http://127.0.0.1:8000 \
VITE_KEYCLOAK_BASE_URL=http://127.0.0.1:8081 \
npm run dev
```

For a deployed environment, replace the generated `runtime-config.json` with values for that environment. Example:

```json
{
  "gatewayUrl": "https://api.example.com",
  "keycloakBaseUrl": "https://sso.example.com",
  "keycloakRealm": "open-talon",
  "oidcClientId": "open-talon-web",
  "appBasePath": "/admin"
}
```

`appBasePath` should match the subpath where the SPA is hosted so routing, login callbacks, and logout redirects resolve correctly.

## What The Playwright Suite Covers

- browser sign-in through Keycloak
- dashboard load and page-level navigation checks
- organization page load and membership management surface
- API key create and revoke flow
- project create with optional owner/editor/viewer seed bindings plus workspace create and delete flow inside the selected organization
- library scoped create/list, text/upload item add, workspace attachment, and manual indexing controls
- methodology request, draft edit, approval, workspace apply, and archive flow
- swarm resource `Platform Global` and `Organization` scope switching
- swarm resource agent create/delete flow
- swarm resource tool create/delete flow
- provider tab switching, scope switching, and memory provider create/delete flow

Current scope note:

- the browser app uses OIDC login, but dedicated IAM role-management and machine-identity management screens are not part of this slice yet
- use the documented `/v1/iam/...` APIs directly for human-role, agent-role, and machine-identity administration
- dedicated external-access screens are not part of this slice yet; use
  `/v1/external-systems`,
  `/v1/workspaces/{workspace_id}/external-identity-grants`, and
  `/v1/workspaces/{workspace_id}/external-operation-requests/...` directly for
  supervisor/admin-managed external grants and approvals

## Notes

- The test expects the gateway and Keycloak to already be running.
- The local stack seeds a single organization named `Default Organization` and a default project. Project visibility is now scoped by project access bindings, so users and agents only see project/workspace structure for projects where they are owner, editor, or viewer.
- If the browser closes immediately with auth errors, confirm the gateway is running with OIDC enabled and Keycloak is healthy.
