# Principal IAM

Open Talon now treats IAM as a provider-neutral principal system:

- An external OIDC identity provider authenticates humans and agent principals.
- Open Talon owns authorization, tenant scoping, role bindings, and audit.
- Humans and agents share one permission catalog.
- Workspace-scoped permissions are still IAM permissions.
- Workspace access is enforced by IAM permission checks together with participant attachment.
- Local development uses Keycloak as the default provider adapter, but the core runtime contracts and persistence are provider-neutral.

This document is about IAM roles and IAM bindings. It does not define collaboration roles such as `frontend_engineer` or `team_lead`, and it does not define participant capabilities such as `qa_review` or `tool:fibonacci`. Collaboration-role definitions are also outside IAM.

## Authentication

- Human users authenticate with OIDC user tokens.
- Agents authenticate with OIDC machine credentials issued by the configured identity provider.
- Open Talon does not mint or broker JWTs.

The gateway resolves three principal types:

- `human`
- `agent`
- `api_key`

Keycloak is the first concrete provisioning adapter, but the runtime contracts are provider-neutral:

- `IdentityProvider`
- `MachineIdentityProvisioner`
- `AuthorizationEngine`

Open Talon does not mint or broker JWTs. Human users authenticate through normal OIDC browser or device flows. Agent principals authenticate through OIDC client credentials and are mapped back into Open Talon through `agent_identities`.

`GET /v1/me` is intentionally human-only. Agent identities use the IAM and collaboration APIs directly.

In local development, the launcher still defaults to `AUTH_MODE=any`. OIDC is the intended principal-IAM path, but API key and OpenBao auth remain accepted locally unless you narrow that setting.

The gateway also exposes an MCP adapter at `/v1/mcp` for OIDC-authenticated software clients. That MCP surface reuses the same `agent_identities`, IAM role bindings, and workspace participant attachment rules described here. It does not define a second permission catalog, and it does not expose Open Talon `system_tools`, `workspace_tools`, Tinker-generated tools, or `agent-runtime` execution backends as MCP-imported tools. It does expose gateway-backed agent Git authoring and agent bundle validate/publish operations when the principal has the matching catalog permissions. The current MCP slice also exposes read-only session resources for identity, permissions, and scope, and it emits `tools/list_changed` plus `resources/list_changed` notifications after scope changes.

## Persistence

Provider-neutral principal IAM state lives in:

- `iam_role_definitions`
- `human_role_bindings`
- `agent_identities`
- `agent_role_bindings`

Related ownership boundaries:

- `users` and `auth_identities` remain the global human identity layer
- `system_agents` remains the global or organization agent-definition layer
- `organization_memberships` remains the tenancy and baseline human membership-role layer
- `participants` remain the workspace-local collaboration and presence layer
- workspace `role_definitions` remain workspace-local collaboration-role metadata

## Authorization

Identity permissions are enforced for global and organization control-plane routes.

Examples:

- `organization.read`
- `organization.members.read`
- `organization.members.write`
- `project.read`
- `project.write`
- `workspace.list`
- `organization.runtime.read`
- `agent_catalog.read`
- `agent_catalog.write`
- `tool_catalog.read`
- `tool_catalog.write`
- `provider.llm.read`
- `provider.llm.write`
- `provider.llm.validate`
- `provider.memory.read`
- `provider.memory.write`
- `provider.memory.validate`
- `provider.mcp.read`
- `provider.mcp.write`
- `provider.mcp.validate`
- `git_registry.read`
- `git_registry.write`
- `asset_catalog.read`
- `asset_catalog.publish`
- `asset_catalog.link`
- `asset_catalog.activate`
- `tool_generation.read`
- `tool_generation.review`
- `audit.read`
- `audit.export`
- `audit.verify`

Workspace-scoped IAM permissions are enforced only after the caller is attached as a participant in the target workspace.

Examples:

- `workspace.roles.write`
- `workspace.agents.write`
- `workspace.tools.write`
- `workspace.repositories.write`
- `workspace.assets.publish`
- `workspace.assets.link`
- `workspace.audit.read`
- `workspace.audit.export`
- `workspace.audit.verify`

Workspace lifecycle routes are the current exception:

- `POST /v1/workspaces`
- `PATCH /v1/workspaces/{workspace_id}`
- `DELETE /v1/workspaces/{workspace_id}`

Those routes are treated as organization control-plane management. They still accept workspace-admin callers, but they also allow organization-admin or platform-admin callers to manage a workspace even when they are not attached as workspace participants.

Project routes are organization control-plane routes:

- `GET /v1/organizations/{organization_id}/projects`
- `POST /v1/organizations/{organization_id}/projects`
- `GET /v1/organizations/{organization_id}/projects/{project_id}`
- `PATCH /v1/organizations/{organization_id}/projects/{project_id}`
- `GET /v1/organizations/{organization_id}/projects/{project_id}/access`
- `PUT /v1/organizations/{organization_id}/projects/{project_id}/access`
- `DELETE /v1/organizations/{organization_id}/projects/{project_id}/access`

Project creation still requires organization-level `project.write`. Listing projects in an organization requires organization-level `project.read` and returns the organization's project catalog. Reading a specific project, listing workspace structure inside it, creating project workspaces, and managing project access require organization permission plus an explicit project access binding unless the caller is a platform admin or API-key/system path. The project access role then contributes project-local permissions:

| Project role | Project-local permissions |
| --- | --- |
| `creator` | `project.read`, `project.write`, `project.access.write`, `workspace.list`, `workspace.create` |
| `owner` | `project.read`, `project.write`, `project.access.write`, `workspace.list`, `workspace.create` |
| `editor` | `project.read`, `project.write`, `workspace.list`, `workspace.create` |
| `viewer` | `project.read`, `workspace.list` |

Project access bindings can target a user or system agent. When a project is created, the creator is granted `creator`; if no separate owner is supplied, the creator is also the primary owner. Owners and the creator manage access bindings. Workspace creation can target a project directly with `/v1/organizations/{organization_id}/projects/{project_id}/workspaces` or with `project_id` on `POST /v1/workspaces`.

## Baseline human authorization

Human users inherit baseline organization permissions from `organization_memberships.role`:

- `owner`: full organization permission bundle
- `admin`: organization-admin bundle
- `member`: organization-read bundle

Extra human IAM role bindings can extend that baseline.

Agent permissions come from:

- explicit global or organization agent IAM role bindings
- the same workspace-scoped IAM permissions as human principals, evaluated only after the linked agent is attached as a workspace participant

The MCP adapter uses those same agent permissions. It filters visible MCP operations by the current session scope and then rechecks the underlying IAM permission on every call.

External MCP server management is separate from the gateway-mounted MCP adapter and from the Open Talon tool catalog. Global and organization MCP server definitions use `provider.mcp.*` permissions. Workspace MCP server attachment uses `workspace.mcp_servers.write` after participant attachment. Do not use `tool_catalog.*` or `workspace.tools.write` to manage external MCP servers.

Git-managed agent publishing uses the existing permission model: system-wide publish requires global `agent_catalog.write`, organization-wide publish requires organization-scoped `agent_catalog.write`, and Git repository registration requires `git_registry.write`. Agents can author files through gateway/MCP managed-worktree tools, but only gateway validation/publish writes `system_agents`.

## Role layers

Open Talon has several distinct role-like concepts:

- `IAM role`
  Stored in `iam_role_definitions` and bound through `human_role_bindings` or `agent_role_bindings`.
  These govern global and organization control-plane authorization.
- `organization membership role`
  Stored in `organization_memberships.role`.
  This is the baseline human tenancy tier such as `owner`, `admin`, or `member`.
- `collaboration role`
  Stored in `participants.roles`.
  This is a workspace-local label used for collaboration routing and participant presentation, such as `frontend_engineer` or `team_lead`.
- `capability`
  Stored in `participants.capabilities`.
  This is a workspace-local advertised label used for routing and discovery, such as `qa_review` or `tool:fibonacci`.
- `collaboration role definition`
  Stored in `workspace.metadata.role_definitions`.
  This is a workspace-local role description used for collaboration discovery and UI help text. It is not an IAM role and it does not grant permissions.

Do not call collaboration roles, capabilities, or collaboration-role definitions "IAM roles". They are separate layers with different scope and storage.

## IAM APIs

Global APIs:

- `GET /v1/iam/permissions`
- `GET|POST /v1/iam/human-roles`
- `PATCH|DELETE /v1/iam/human-roles/{role_id}`
- `GET|POST /v1/iam/agent-roles`
- `PATCH|DELETE /v1/iam/agent-roles/{role_id}`
- `GET /v1/iam/users/{user_id}/roles`
- `POST|DELETE /v1/iam/users/{user_id}/roles/{role_id}`
- `GET|POST /v1/iam/agent-identities`
- `GET /v1/iam/agent-identities/{agent_identity_id}`
- `GET /v1/iam/agent-identities/{agent_identity_id}/roles`
- `POST|DELETE /v1/iam/agent-identities/{agent_identity_id}/roles/{role_id}`
- `POST /v1/iam/agent-identities/{agent_identity_id}/rotate-secret`
- `POST /v1/iam/agent-identities/{agent_identity_id}/disable`
- `POST /v1/iam/agent-identities/{agent_identity_id}/enable`

Organization-scoped APIs:

- `GET|POST /v1/organizations/{organization_id}/iam/human-roles`
- `PATCH|DELETE /v1/organizations/{organization_id}/iam/human-roles/{role_id}`
- `GET|POST /v1/organizations/{organization_id}/iam/agent-roles`
- `PATCH|DELETE /v1/organizations/{organization_id}/iam/agent-roles/{role_id}`
- `GET /v1/organizations/{organization_id}/iam/users/{user_id}/roles`
- `POST|DELETE /v1/organizations/{organization_id}/iam/users/{user_id}/roles/{role_id}`
- `GET|POST /v1/organizations/{organization_id}/iam/agent-identities`

Identity-specific follow-up routes such as role binding, rotate, disable, and enable operate on `/v1/iam/agent-identities/{agent_identity_id}/...` after the identity has been resolved.

Current IAM management route guards:

- list roles, list bindings, and list agent identities require `organization.members.read`
- create, update, delete, bind, unbind, provision, rotate-secret, enable, and disable operations require `organization.members.write`
- those permissions are evaluated globally on `/v1/iam/...` routes and within the target organization on `/v1/organizations/{organization_id}/iam/...` routes

## Agent identity provisioning

Provisioning an agent identity returns:

- Open Talon `agent_identity_id`
- external `client_id`
- one-time `client_secret`
- `issuer`
- `token_endpoint`

Secrets are stored through the configured secret store and only returned during create or rotate flows.

Local development currently stores agent-identity secrets in OpenBao and uses Keycloak as the first concrete provisioning adapter.

## Agent identity walkthrough

One concrete agent-identity flow looks like this:

1. Create an agent IAM role with the permissions the agent identity needs.
2. Provision an `agent_identity` for an existing `system_agent`.
3. Exchange the returned `client_id` and `client_secret` for an OIDC access token at the provider `token_endpoint`.
4. Call the protected Open Talon API with `Authorization: Bearer <token>`.

Example global role:

```bash
curl -X POST http://127.0.0.1:8000/v1/iam/agent-roles \
  -H "Authorization: Bearer <human-admin-token>" \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "org-tool-publisher",
    "description": "Publish and review generated tools",
    "permissions": ["tool_generation.review", "tool_catalog.write"]
  }'
```

Example agent-identity provisioning:

```bash
curl -X POST http://127.0.0.1:8000/v1/iam/agent-identities \
  -H "Authorization: Bearer <human-admin-token>" \
  -H 'Content-Type: application/json' \
  -d '{
    "system_agent_id": "<system-agent-id>",
    "scope": "global"
  }'
```

The response returns:

- `agent_identity_id`
- `client_id`
- `client_secret`
- `issuer`
- `token_endpoint`

Bind the IAM role to that agent identity:

```bash
curl -X POST \
  "http://127.0.0.1:8000/v1/iam/agent-identities/<agent-identity-id>/roles/<role-id>" \
  -H "Authorization: Bearer <human-admin-token>"
```

Exchange the agent identity client credentials for a token directly with the OIDC provider:

```bash
curl -X POST "http://127.0.0.1:8081/realms/open-talon/protocol/openid-connect/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=client_credentials' \
  -d 'client_id=<client-id>' \
  -d 'client_secret=<client-secret>'
```

Then use the returned token against Open Talon:

```bash
curl -H "Authorization: Bearer <agent-token>" \
  http://127.0.0.1:8000/v1/iam/agent-identities
```

For an organization-scoped agent identity, use the `/v1/organizations/{organization_id}/iam/...` variants instead.

## Authorization outcomes

Open Talon keeps tenant-aware authorization semantics:

- out-of-scope organization and workspace reads return `404`
- in-scope requests without the required permission return `403`
- platform-admin bootstrap access still exists locally through the configured OIDC admin role
- steady-state authorization is intended to come from Open Talon IAM role bindings together with workspace participant attachment

## Current UI scope

This slice is API-first:

- the backend IAM APIs are implemented and documented
- the admin web continues to use OIDC login through the default provider
- dedicated browser IAM management screens are not part of this slice yet

## Audit

Audit writes remain canonical in Open Talon.

- Agent-authenticated HTTP requests are now recorded with `actor_type="agent"`.
- `system_agent_id` is preserved in audit actor metadata.
- Authorization remains tenant-aware with `404` for out-of-scope reads and `403` for in-scope permission denials.
