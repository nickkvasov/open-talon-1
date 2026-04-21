# Principal IAM

Open Talon now treats IAM as a provider-neutral principal system:

- An external OIDC identity provider authenticates humans and machine principals.
- Open Talon owns authorization, tenant scoping, role bindings, and audit.
- Humans and agents share one permission catalog.
- Workspace-scoped management permissions live on workspace role definitions.
- Local development uses Keycloak as the default provider adapter, but the core runtime contracts and persistence are provider-neutral.

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

Open Talon does not mint or broker JWTs. Human users authenticate through normal OIDC browser or device flows. Machine principals authenticate through OIDC client credentials and are mapped back into Open Talon through `agent_identities`.

`GET /v1/me` is intentionally human-only. Machine principals use the IAM and collaboration APIs directly.

## Persistence

Provider-neutral principal IAM state lives in:

- `iam_role_definitions`
- `human_role_bindings`
- `agent_identities`
- `agent_role_bindings`

Related ownership boundaries:

- `users` and `auth_identities` remain the global human identity layer
- `system_agents` remains the global or organization agent-definition layer
- `organization_memberships` remains the tenancy and baseline human-role layer
- `participants` and workspace `role_definitions` remain the workspace-local authority layer

## Authorization

Identity permissions are enforced for global and organization control-plane routes.

Examples:

- `organization.read`
- `organization.members.read`
- `organization.members.write`
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

Workspace role definitions now carry explicit permissions.

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

Default workspace roles are backfilled with permission bundles:

- `admin`
- `supervisor`
- `user`

## Baseline human authorization

Human users inherit baseline organization permissions from `organization_memberships.role`:

- `owner`: full organization permission bundle
- `admin`: organization-admin bundle
- `member`: organization-read bundle

Extra human IAM role bindings can extend that baseline.

Agent permissions come from:

- explicit global or organization agent IAM role bindings
- workspace participant permissions when the agent is attached to a workspace and its participant role carries workspace permissions

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

## Machine identity provisioning

Provisioning an agent identity returns:

- Open Talon `agent_identity_id`
- external `client_id`
- one-time `client_secret`
- `issuer`
- `token_endpoint`

Secrets are stored through the configured secret store and only returned during create or rotate flows.

Local development currently stores machine secrets in OpenBao and uses Keycloak as the first concrete provisioning adapter.

## Authorization outcomes

Open Talon keeps tenant-aware authorization semantics:

- out-of-scope organization and workspace reads return `404`
- in-scope requests without the required permission return `403`
- platform-admin bootstrap access still exists locally through the configured OIDC admin role
- steady-state authorization is intended to come from Open Talon IAM role bindings and workspace role permissions

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
