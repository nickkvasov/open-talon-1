# agent-runtime

Reusable runtime helpers for task-claiming Open Talon agents that emit `task.*` and `run.*` collaboration events, execute isolated tool calls, and drive the live generated-tool path used by Tinker.

Provider-backed model generations route through LiteLLM so local Ollama and managed OpenAI-style endpoints share one completion transport while generic remote agent endpoints continue to use their native JSON contract.

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
