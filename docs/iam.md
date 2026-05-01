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

The gateway also exposes an MCP adapter at `/v1/mcp` for OIDC-authenticated software clients. That MCP surface reuses the same `agent_identities`, IAM role bindings, project-local `creator`/`owner`/`editor`/`viewer` access bindings, and workspace participant attachment rules described here. It does not define a second permission catalog, and it does not expose Open Talon `system_tools`, `workspace_tools`, Tinker-generated tools, arbitrary System Plugins, or `agent-runtime` execution backends as MCP-imported tools. It exposes organization, project, workspace, thread, memory, library, retrieval/Retriever, runtime overview, audit read/verify, catalog/provider list, IAM lookup, gateway-backed agent Git authoring, and agent bundle validate/publish operations when the principal has the matching permissions. The managed Library and Retriever System Plugins use this gateway adapter as their backing MCP surface. The current MCP slice also exposes read-only session resources for identity, permissions, and scope, and it emits `tools/list_changed` plus `resources/list_changed` notifications after scope changes.

The managed control-plane MCP server is stored as `open_talon_control_plane` and uses `auth.kind=open_talon_agent_identity`. Runtime MCP execution resolves the current `system_agent_id`, reads that agent identity's `secret_ref`, mints an OIDC client-credentials token, and sends it to `/v1/mcp`. Agent-private MCP bindings then expose only the allowlisted operations to that agent's execution context.

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
- `external.systems.read`
- `external.systems.write`
- `external.systems.validate`
- `external.grants.read`
- `external.grants.write`
- `external.operations.approve`
- `git_registry.read`
- `git_registry.write`
- `asset_catalog.read`
- `asset_catalog.publish`
- `asset_catalog.link`
- `asset_catalog.activate`
- `retrieval.read`
- `retrieval.write`
- `retrieval.search`
- `retrieval.admin`
- `methodology.read`
- `methodology.write`
- `methodics.read`
- `methodics.execute`
- `methodics.admin`
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
- `retrieval.read`
- `retrieval.write`
- `retrieval.search`
- `retrieval.admin`
- `methodology.read`
- `methodology.write`
- `methodics.read`
- `methodics.execute`
- `methodics.admin`
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

Operational and managed specialist agents use this same model. `Tinker`, `Steward`, `Curator`, `Anchor`, `Researcher`, `Methodologist`, and `Conductor` are normal `system_agents` whose purpose is advertised through `display_name`, `role`, and `capabilities`; their authority comes from IAM bindings, project access, workspace participant attachment, task payloads, and private MCP/tool allowlists. Runtime workers stay generic and do not authorize or specialize behavior from agent keys, role text, capability text, or metadata tags. `Researcher` uses the managed `methodology_researcher` agent IAM role and private dossier MCP allowlist to build durable research dossiers from local libraries, Retriever context, database-visible context, and web follow-up sources inside one organization. `Conductor` is opt-in per workspace: attaching it enables targeted methodics tasks, but active execution still requires an explicit human methodics execution start call and otherwise the workspace has no methodics loop. The managed `workspace_conductor` agent IAM role allows Conductor to read/search workspace execution context and create pending resource requests after attachment; start/cancel and resource request approval/rejection remain human-gated.

System Plugin management is separate from the gateway-mounted MCP adapter and from the Open Talon tool catalog. V1 stores System Plugins in `mcp_servers`, so global and organization plugin definitions, validation, and capability sync use `provider.mcp.*` permissions. Workspace plugin attachment uses `workspace.mcp_servers.write` after participant attachment. If an attachment enables parsed-page asset-candidate output, the caller also needs `workspace.assets.publish`. Do not use `tool_catalog.*` or `workspace.tools.write` to manage System Plugins.

External identity grants are a separate control-plane authority. Global/platform admins and organization owners/admins can manage `external_systems`, `external_accounts`, and participant-scoped `external_identity_grants` through the `external.systems.*` and `external.grants.*` identity permissions. A grant targets one attached workspace participant (`workspace_id` plus `participant_id`) and records the normalized `user_id` or `system_agent_id`, external system, optional external account, allowed scopes/operations, risk policy, status, expiry, creator, and approver. Authorized callers can also pre-assign grants while attaching or updating an agent participant. Workspace collaboration roles, collaboration capabilities, and workspace-local role definitions do not grant external system access and do not grant grant-management authority.

Runtime MCP execution with `auth.kind="external_identity"` and direct external-operation APIs both resolve the executing participant through the same active-grant check. If no active grant covers the operation, execution fails with a permission error. High-risk operations create `external_operation_requests` and thread-visible pending approval messages unless the participant grant's risk policy pre-approves the operation. Approving or rejecting those requests requires `external.operations.approve`; ordinary workspace participation is not enough. Grant update/revoke and operation approval routes are workspace-path scoped under `/v1/workspaces/{workspace_id}/...`; older query-scoped forms remain compatibility aliases.

Direct external-operation APIs can execute configured HTTP operations from an external system's `operation_catalog` after authorization succeeds. The gateway performs the HTTP call at the edge using the resolved participant grant/account credentials, returns the external operation result to the caller, and redacts `secret_config`/`credential_ref` from the returned Open Talon resolution. If no HTTP operation is configured for the requested operation key, the API returns the authorization resolution without making an external call.

For full route shape, operation-catalog examples, MCP external identity auth
configuration, and tests, see [external-access.md](./external-access.md).

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

External-access control-plane APIs:

- `POST /v1/external-systems`
- `POST|GET /v1/organizations/{organization_id}/external-systems`
- `PATCH|DELETE /v1/external-systems/{system_id}`
- `POST /v1/workspaces/{workspace_id}/external-accounts`
- `PATCH /v1/external-accounts/{account_id}?workspace_id=...`
- `POST|GET /v1/workspaces/{workspace_id}/external-identity-grants`
- `PATCH|DELETE /v1/workspaces/{workspace_id}/external-identity-grants/{grant_id}`
- `POST /v1/workspaces/{workspace_id}/external-systems/{system_id}/operations/{operation_key}`
- `GET /v1/workspaces/{workspace_id}/external-operation-requests`
- `POST /v1/workspaces/{workspace_id}/external-operation-requests/{operation_request_id}/approve`
- `POST /v1/workspaces/{workspace_id}/external-operation-requests/{operation_request_id}/reject`

The legacy query-scoped grant update/revoke and operation approve/reject routes
remain compatibility aliases, but new clients should use the workspace-path
forms above.

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
- dedicated browser external-access screens are not part of this slice yet; use
  the `/v1/external-systems`, workspace grant, and operation-request APIs
  directly

## Audit

Audit writes remain canonical in Open Talon.

- Agent-authenticated HTTP requests are now recorded with `actor_type="agent"`.
- `system_agent_id` is preserved in audit actor metadata.
- Authorization remains tenant-aware with `404` for out-of-scope reads and `403` for in-scope permission denials.
