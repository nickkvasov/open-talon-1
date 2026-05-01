# External Access And Identity Grants

This document describes the implemented external-access model for Open Talon.
Use it when wiring external SaaS systems, external MCP servers, or direct
external HTTP operations into a workspace.

External access is control-plane authority. It is not granted by workspace
collaboration roles, participant capabilities, or role definitions.

## Concepts

| Concept | Canonical table/model | Meaning |
| --- | --- | --- |
| External system | `external_systems`, `ExternalSystemDefinition` | A global or organization-scoped external system definition such as a CRM, ticketing system, or external MCP-backed service. |
| External account | `external_accounts`, `ExternalAccount` | A credential reference or external subject for one user or system agent in an external system. |
| External identity grant | `external_identity_grants`, `ExternalIdentityGrant` | Permission for one attached workspace participant to use one external system and optional account. |
| External operation request | `external_operation_requests`, `ExternalOperationRequest` | Durable approval record for high-risk or destructive external operations. |
| Operation catalog | `ExternalSystemDefinition.operation_catalog` | Optional HTTP operation definitions used by direct external-operation APIs after grant resolution succeeds. |

Grant targets are workspace-participant scoped. A grant stores `workspace_id`
plus `participant_id` and also records the normalized subject link as either
`user_id` or `system_agent_id`. The normalized link is for audit and
validation; authorization still requires the executing participant attachment
and an active grant.

## Authority Model

External access uses identity permissions:

- `external.systems.read`
- `external.systems.write`
- `external.systems.validate`
- `external.grants.read`
- `external.grants.write`
- `external.operations.approve`

Important rules:

- Platform/global admins can manage global external systems and grants inside
  authorized scope.
- Organization owners/admins or explicit organization IAM role holders can
  manage organization-scoped external systems, accounts, and grants in that
  organization.
- Ordinary workspace participants cannot create, update, revoke, or approve
  external grants through collaboration roles or capabilities.
- A workspace participant may list its own active grants, but that visibility
  does not allow management.
- Pre-assigning grants through participant attach/update APIs that expose
  `external_access_grants` currently applies to agent participant attach/update
  and requires `external.grants.write`; callers without that permission must be
  rejected when they include external grant fields.

Do not add workspace-local permissions such as
`workspace.external_identities.write`. External access is intentionally outside
the ordinary collaboration-role layer.

## Grant Resolution

MCP external-identity auth and direct external operations use the same resolver:

1. Resolve the executing workspace participant from authenticated context.
2. Confirm the participant is attached to the target workspace.
3. Resolve the external system by `system_id` or `system_key`, enforcing tenant
   visibility.
4. Find an active, unexpired grant for `workspace_id + participant_id +
   system_id` whose `allowed_operations` is empty or contains the requested
   operation key.
5. Resolve the optional external account attached to the grant.
6. Apply the grant risk policy to decide whether approval is required.

Missing, expired, revoked, inactive, wrong-workspace, and wrong-participant
grants fail before any outbound network operation is attempted.

## Risk And Approval

Risk levels are:

- `low`
- `medium`
- `high`
- `destructive`

By default, `high` and `destructive` operations require approval. A grant
`risk_policy` can tune that behavior:

```json
{
  "preapproved_operations": ["crm.read"],
  "preapproved_risk_levels": ["high"],
  "approval_required_operations": ["crm.delete"],
  "approval_required_risk_levels": ["medium"],
  "require_approval": true
}
```

The resolver also accepts the compatibility names
`require_approval_operations` and `require_approval_risk_levels`.

When approval is required:

- `external_operation_requests` stores the approval state.
- A thread-visible pending approval message is created when a thread is known.
- Approval and rejection require `external.operations.approve`.
- Approved MCP tool calls are requeued for execution.
- Resumed tool execution marks the request `completed` or `failed` after the
  approved operation finishes.

## Direct External Operations

The direct API route is:

```text
POST /v1/workspaces/{workspace_id}/external-systems/{system_id}/operations/{operation_key}
```

The request body is `ExecuteExternalOperationRequest`:

- `actor`: compatibility actor payload; OIDC callers are resolved server-side
- `operation_key`: compatibility field, while the path value is authoritative
- `arguments`: operation arguments
- `risk_level`: `low`, `medium`, `high`, or `destructive`
- `thread_id`: optional thread for approval visibility
- `metadata`: metadata recorded after redaction

If resolution is approved and the external system has a matching HTTP operation
definition, `gateway-edge` performs the outbound call and returns
`operation_result` on the `ExternalIdentityResolution`. If no operation is
configured for that key, the API returns the authorization resolution without an
outbound call.

HTTP operation definitions can be stored either directly by operation key or
under an `operations` map:

```json
{
  "crm.read": {
    "transport": "http",
    "method": "POST",
    "path": "/customers/{customer_id}",
    "headers": { "X-Operation": "read" },
    "json": { "id": "{customer_id}", "mode": "full" },
    "timeout_seconds": 30
  }
}
```

The executor supports:

- `transport` or `kind`: currently `http`
- `method`: defaults to `POST`
- `url`: absolute URL, or `base_url`/`path`; `system.config.base_url` can supply
  the base URL
- `params`, `headers`, `json`, and `body`
- `{argument_name}` template substitution in strings
- `auth.header_name` and `auth.scheme` for bearer or API key headers

Credentials come from the grant account's `credential_ref` when present, or from
the external system's `secret_config` otherwise. Secret values may be direct
values for tests, environment references, or OpenBao references:

```json
{
  "bearer_token": {
    "openbao": {
      "mount": "secret",
      "path": "open-talon/external/crm",
      "field": "token"
    }
  },
  "headers": {
    "X-External-Subject": { "env": { "name": "CRM_EXTERNAL_SUBJECT" } }
  }
}
```

Do not store raw bearer tokens, API keys, prompt bodies, full operation
arguments, or raw sensitive response payloads in audit or approval metadata.
The gateway redacts `secret_config` and `credential_ref` from returned Open
Talon resolution objects.

## MCP External Identity Auth

Runtime MCP execution can use an external participant grant by configuring a
workspace-visible MCP server with:

```json
{
  "auth": {
    "kind": "external_identity",
    "external_system_key": "crm",
    "operation_key": "crm.read",
    "risk_level": "low"
  }
}
```

`external_system_id` may be used instead of `external_system_key`. If
`operation_key` is omitted, runtime falls back to the MCP tool name or handler
reference. The execution spec must carry `metadata.workspace_id` and
`metadata.system_agent_id`; `thread_id` and `tool_call_id` are carried when the
tool call is tied to a workspace thread.

If approval is required, runtime does not call the external MCP endpoint. It
marks the tool call `pending_approval`, records the
`external_operation_request`, and waits for approval. Approval requeues the tool
call; the resumed execution path then uses the resolved account or system
credentials as request headers.

This is separate from the gateway-mounted `/v1/mcp` system API adapter. The
gateway adapter exposes Open Talon control-plane APIs to OIDC-authenticated
clients; `auth.kind="external_identity"` is for runtime outbound calls to an
external MCP server.

## API Surface

| Method | Path | Permission |
| --- | --- | --- |
| `POST` | `/v1/external-systems` | global `external.systems.write` |
| `POST` | `/v1/organizations/{organization_id}/external-systems` | org `external.systems.write` |
| `GET` | `/v1/organizations/{organization_id}/external-systems` | org `external.systems.read` |
| `PATCH` | `/v1/external-systems/{system_id}` | scoped `external.systems.write` |
| `DELETE` | `/v1/external-systems/{system_id}` | scoped `external.systems.write` |
| `POST` | `/v1/workspaces/{workspace_id}/external-accounts` | org `external.grants.write` |
| `PATCH` | `/v1/external-accounts/{account_id}?workspace_id=...` | org `external.grants.write` |
| `POST` | `/v1/workspaces/{workspace_id}/external-identity-grants` | org `external.grants.write` |
| `GET` | `/v1/workspaces/{workspace_id}/external-identity-grants` | org `external.grants.read`, or own active grants for attached participants |
| `PATCH` | `/v1/workspaces/{workspace_id}/external-identity-grants/{grant_id}` | org `external.grants.write` |
| `DELETE` | `/v1/workspaces/{workspace_id}/external-identity-grants/{grant_id}` | org `external.grants.write` |
| `POST` | `/v1/workspaces/{workspace_id}/external-systems/{system_id}/operations/{operation_key}` | attached participant plus active grant |
| `GET` | `/v1/workspaces/{workspace_id}/external-operation-requests` | org `external.operations.approve` |
| `POST` | `/v1/workspaces/{workspace_id}/external-operation-requests/{operation_request_id}/approve` | org `external.operations.approve` |
| `POST` | `/v1/workspaces/{workspace_id}/external-operation-requests/{operation_request_id}/reject` | org `external.operations.approve` |

Legacy query-scoped grant update/revoke and request approve/reject routes remain
as compatibility aliases. Prefer the workspace-path-scoped forms for mutable
operations.

## Tests

Relevant focused coverage lives in:

- `tests/core-collab/test_external_access.py`
- `tests/gateway-edge/test_external_access_routes.py`
- `tests/gateway-edge/test_external_operation_executor.py`
- `tests/agent-runtime/test_external_identity_mcp.py`
- `tests/core-collab/test_migration_files.py`
- `tests/core-collab/test_repository_integration.py`

Run the focused suite with:

```bash
pytest tests/core-collab/test_external_access.py \
  tests/gateway-edge/test_external_access_routes.py \
  tests/gateway-edge/test_external_operation_executor.py \
  tests/agent-runtime/test_external_identity_mcp.py \
  tests/core-collab/test_migration_files.py -q
```

Repository integration tests may skip when local Postgres is not running. When
schema or SQL filtering changes, run the repository integration coverage against
the local stack as well.
