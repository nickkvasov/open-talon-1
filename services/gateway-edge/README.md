# Gateway Edge

`gateway-edge` is the supported API gateway for Open Talon.

It exposes:

- health and readiness endpoints
- chat APIs with request/response and streaming flows
- collaboration APIs for workspaces, threads, timelines, and presence
- provider-neutral principal IAM APIs for human roles, agent roles, and agent identities
- external-access APIs for external systems, accounts, participant grants, direct operations, and operation approvals
- an MCP server at `/v1/mcp` that exposes permission-scoped Open Talon system API operations
- admin APIs for API key management
- a gateway-mounted browser session-chat UI at `/` when `apps/web` is present

## Local Development

Use the repository-root virtualenv and launcher from the repo root:

```bash
./scripts/bootstrap-python.sh
./open-talon start
./open-talon tui2 --profile admin
```

The launcher starts the full local infrastructure stack plus this service as a local `uvicorn` process on `http://127.0.0.1:8000`.

For scripted or multi-user testing, prefer:

```bash
./open-talon user-client --profile user1
```

The gateway also serves the compatibility browser session-chat UI from `apps/web` at `http://127.0.0.1:8000/` when that static app directory is present. The main browser operator surface remains `apps/admin-web`.

## MCP System API Adapter

`gateway-edge` mounts an MCP endpoint at `/v1/mcp` when `MCP_ENABLED=true`.

Current behavior:

- it exposes Open Talon system API operations through MCP `tools/list` and `tools/call`
- it does not expose `system_tools`, `workspace_tools`, Tinker-generated tools, System Plugins, or agent-runtime tool execution as MCP callables
- it requires OIDC bearer authentication even when the main gateway auth mode allows API keys or OpenBao
- `initialize` returns `Mcp-Session-Id`, and later `POST` calls plus the `GET /v1/mcp` SSE stream must send that header
- it publishes OAuth protected-resource metadata at `/.well-known/oauth-protected-resource` and `/.well-known/oauth-protected-resource/v1/mcp`
- it accepts requests without `Origin`; if `Origin` is present it must match `MCP_ALLOWED_ORIGINS` or fall back to `CORS_ORIGINS`
- it stores MCP sessions in Valkey with `MCP_SESSION_TTL_SECONDS` controlling expiry
- it keeps MCP session scope separately as `global`, `organization:<id>`, or `workspace:<id>` and filters visible operations accordingly
- scope changes publish `notifications/tools/list_changed` and `notifications/resources/list_changed`
- it exposes read-only session resources at `ot://session/identity`, `ot://session/permissions`, and `ot://session/scope`

System Plugins are managed through `/v1/system-plugins` and workspace plugin attachments. The public API exposes plugin fields such as `plugin_id`, `plugin_key`, and `backing_protocol`; external MCP servers remain the v1 backing protocol and are separate from this gateway-mounted MCP adapter.

## External Access

`gateway-edge` exposes `/v1/external-systems`,
`/v1/workspaces/{workspace_id}/external-identity-grants`, direct external
operation, and external operation approval routes. Route handlers resolve the
OIDC principal, require `external.systems.*`, `external.grants.*`, or
`external.operations.approve` where appropriate, and call `core-collab` for
grant and approval state.

Direct external operations are executed by
[`gateway_edge/services/external_operations.py`](./gateway_edge/services/external_operations.py)
after `core-collab` authorizes the executing workspace participant grant. The
gateway uses the external system `operation_catalog`, resolves account or
system credential references server-side, and redacts `secret_config` and
`credential_ref` from returned Open Talon resolution objects.

For the full route and operation-catalog reference, see
[`docs/external-access.md`](../../docs/external-access.md).

Relevant settings:

- `MCP_ENABLED=true` mounts the MCP router; set it to `false` to disable the feature
- `MCP_SESSION_TTL_SECONDS=3600` controls how long inactive MCP sessions stay valid
- `MCP_ALLOWED_ORIGINS` overrides the MCP `Origin` allowlist; when empty it falls back to `CORS_ORIGINS`

## Direct Run

If you want to run the service directly instead of through the launcher:

```bash
source .venv/bin/activate
PYTHONPATH="packages/contracts:services/core-collab:services/gateway-edge:services/agent-runtime:services/web-search-mcp:services/retriever:services/generated-tools-builder:apps/tui" \
  uvicorn gateway_edge.main:app --host 0.0.0.0 --port 8000
```

The service expects local Postgres, Kafka, Valkey, OpenBao, an OIDC provider, and Ollama endpoints to be available. In local development the default OIDC provider is Keycloak. For the standard dev setup, use `./open-talon start`.

## Tests

Gateway unit and integration coverage lives under [`tests/gateway-edge`](../../tests/gateway-edge).

```bash
source .venv/bin/activate

# unit tests
pytest tests/gateway-edge -q

# principal IAM and auth resolution
pytest tests/gateway-edge/test_iam.py -q
pytest tests/gateway-edge/test_identity_sync.py -q

# external access routes and direct HTTP operation executor
pytest tests/gateway-edge/test_external_access_routes.py -q
pytest tests/gateway-edge/test_external_operation_executor.py -q

# infrastructure integration
pytest -m integration tests/infrastructure/test_infrastructure.py -v -s
```

## Key Files

- [`gateway_edge/main.py`](./gateway_edge/main.py)
- [`gateway_edge/config.py`](./gateway_edge/config.py)
- [`gateway_edge/routers`](./gateway_edge/routers)
- [`gateway_edge/services`](./gateway_edge/services)
