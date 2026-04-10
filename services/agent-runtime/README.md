# agent-runtime

Reusable runtime helpers for task-claiming Open Talon agents that emit `task.*` and `run.*` collaboration events.

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
