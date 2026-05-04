# Gateway Edge Agent Guide

This guide applies under `services/gateway-edge/` and adds to the root and
service guides.

## Gateway Responsibilities

- `gateway-edge` owns REST, SSE, WebSocket, auth, admin, collaboration, provider
  health, and browser-facing APIs.
- Keep routers thin; put business logic in services, kernels, and repositories.
- Authenticated human identity should be derived from OIDC auth context, not
  trusted from client-provided actor fields.
- Authenticated machine identity should be derived from OIDC client credentials
  and `agent_identities`, not from client-provided actor fields.
- `/v1/me` is human-only; machine principals should use the IAM and
  collaboration APIs directly.
- Keep OIDC workspace reads membership-scoped. Non-members should get `404` for
  workspace-scoped reads rather than `403`.
- Keep OIDC organization reads membership-scoped. Non-members should get `404`
  for organization-scoped reads rather than `403`.

## Authorization

- Global system-definition, global publish, provider-management, and
  IAM-management routes require the matching global IAM permission unless the
  request is coming through an existing operator/system-auth path or bootstrap
  platform-admin access.
- Organization CRUD and organization-scoped management routes require the
  relevant organization permission from baseline membership roles or explicit
  IAM role bindings, unless the caller is a platform admin.
- Workspace role-definition changes, workspace participant-management, workspace
  tool management, workspace Git repository creation, and workspace asset
  publishing require the matching workspace-scoped IAM permission plus
  participant attachment.
- Workspace collaboration roles, capabilities, and workspace-admin labels must
  never grant external-system access or external grant management.

## External Operations

- Keep external-operation authorization and durable state in `core-collab`, but
  keep generic outbound HTTP execution in `gateway-edge` services using the
  configured external-system operation catalog.
- Never return `secret_config`, `credential_ref`, bearer tokens, raw sensitive
  request payloads, or raw sensitive response payloads through operation results,
  approval metadata, or audit metadata.
- Prefer workspace-path-scoped mutable external-access routes such as
  `/v1/workspaces/{workspace_id}/external-identity-grants/{grant_id}` and
  `/v1/workspaces/{workspace_id}/external-operation-requests/{operation_request_id}/approve`.
- Query-parameter workspace scoping on update, revoke, approve, and reject routes
  is easier to misuse and should only remain as a compatibility alias when
  needed.
- MCP calls with `auth.kind="external_identity"` and direct external-operation
  APIs must resolve grants through the same external-access path.

## Audit and Providers

- Keep audit capture in dedicated middleware/services.
- Keep relay/projector failures non-blocking for canonical audit writes.
- Keep shared telemetry/redaction behavior aligned with runtime observability.
- Keep provider health routes aligned with persistent `llm_providers` and
  `memory_providers` records and OpenBao-backed secret resolution.
- Use shared telemetry/redaction behavior from
  `packages/contracts/open_talon_contracts/telemetry.py` instead of inventing
  gateway-specific variants.

## Browser and Admin Surface

- Keep admin-web runtime config runtime-loadable; do not move environment
  selection back to build-time-only config.
- Keep browser OIDC login, redirect paths, and deployed browser config aligned
  with Keycloak defaults and `apps/admin-web/public/runtime-config.json`.

## Tests

- Run relevant `tests/gateway-edge` coverage for route, auth, IAM, workspace,
  provider, audit, external-operation, MCP, and admin changes.
- Run `tests/gateway-edge/test_iam.py` and
  `tests/gateway-edge/test_identity_sync.py` for auth, OIDC, or identity sync
  behavior.
- Run `tests/gateway-edge/test_workspaces.py`,
  `tests/gateway-edge/test_admin.py`, and relevant organization route tests for
  workspace authz, global admin routes, or membership filtering.
- Run at least one gateway audit test when audit APIs or middleware change.
- Run `npm run build` in `apps/admin-web` when browser-facing config or admin
  surface changes.

## Key Files

- `gateway_edge/services/collaboration.py`
- `gateway_edge/services/memory_provider_health.py`
- `gateway_edge/services/llm_provider_health.py`
- `gateway_edge/auth/`
- `gateway_edge/services/events.py`
- `gateway_edge/services/audit.py`
- `gateway_edge/services/audit_providers.py`
- `gateway_edge/audit_middleware.py`
- `gateway_edge/db/postgres.py`
- `gateway_edge/routers/admin.py`
