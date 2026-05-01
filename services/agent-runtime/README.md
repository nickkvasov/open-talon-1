# agent-runtime

Reusable runtime helpers for task-claiming Open Talon agents that emit `task.*` and `run.*` collaboration events, execute isolated tool calls, sync external System Plugin capabilities, and drive the live generated-tool path used by Tinker.

Provider-backed model generations route through LiteLLM so local Ollama and managed OpenAI-style endpoints share one completion transport while generic remote agent endpoints continue to use their native JSON contract.

`talon-mcp-sync-worker` claims durable `mcp_server_sync_jobs`, validates the backing MCP endpoint for a System Plugin, discovers tools/resources/prompts, and replaces the cached capability rows without importing them into `system_tools`.

## MCP External Identity Auth

Runtime MCP execution supports outbound server configs with
`auth.kind="external_identity"`. Before calling the external MCP endpoint, the
tool worker asks `core-collab` to resolve an active external identity grant for
the executing workspace participant and operation key. The resolver requires
`metadata.workspace_id` and `metadata.system_agent_id`; when present,
`thread_id` and `tool_call_id` are used for approval visibility and approved
tool-call requeue.

If the grant risk policy requires approval, runtime returns a
`pending_approval` result without contacting the external MCP server. Approval
through the gateway requeues the tool call, and the resumed execution path marks
the external operation request `completed` or `failed` after execution.

This is distinct from `auth.kind="open_talon_agent_identity"`, which mints an
OIDC client-credentials token for calls back to the gateway-mounted `/v1/mcp`
system API adapter.

## Langfuse

`agent-runtime` can emit Langfuse traces for:

- agent task execution spans
- local Ollama generations
- remote or system agent endpoint executions

The integration is optional and activates only when these environment variables are present:

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=http://127.0.0.1:3000
```

If the keys are not set, runtime execution stays unchanged and tracing is skipped.

## Live Tinker Path

The real end-to-end generated-tool path is exercised by:

```bash
pytest -m integration tests/infrastructure/test_tinker_live_system.py -q -s
```

That scenario starts the local stack, lets Tinker author and publish a generated tool, and verifies that another agent can execute the published tool through the normal runtime and tool-worker pipeline.

Focused external identity coverage:

```bash
pytest tests/agent-runtime/test_external_identity_mcp.py -q
```
