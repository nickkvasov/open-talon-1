# Retriever Agent Guide

This guide applies under `services/retriever/` and adds to the root and service
guides.

## Provider Model

- Retriever visual extraction is a vision-LLM workload and must use the shared
  LLM engine registry.
- `RetrievalProfile.vision_provider_key` can refer to an engine id such as
  `local-ollama` or a provider key such as `openai` or `anthropic`.
- Organization-scoped retrieval should include global plus same-organization LLM
  providers.
- Retriever embeddings are separate from generation/vision LLMs. Keep embedding
  model/provider selection on the Retriever embedding-provider abstraction
  because embeddings have different request shape, dimensions, vector
  persistence, and pgvector indexing semantics.

## Ingestion and Search

- Library is store-first and Retriever indexing is explicit. Adding uploads,
  Markdown/text, webpage scraps, images, or diagrams to a library must not
  enqueue ingestion unless the caller invokes the library index route or
  Retriever plugin tool.
- Search results persisted into `retrieval_hits` should be selected and written
  in one transaction with appropriate chunk locking or revalidation so stale
  chunk ids cannot violate hit foreign keys.
- Account for the always-running `talon-retriever-worker` during live tests.
  Tests that process a specific ingestion job directly must claim that exact
  queued job first, or wait if the stack worker already claimed it, instead of
  processing the same job twice.

## Visual Extraction

- Retriever visual extraction must prove document understanding, not only object
  recognition.
- Chart tests should assert semantic facts such as chart title, labels,
  approximate values, peaks/highest values, trends, or comparisons rather than
  accepting vague phrases like "there is a chart."
- Keep visual tests realistic but bounded. Prefer public, stable, rights-clear
  PDF fixtures with documented source/rights, then derive the relevant page or
  crop at test runtime instead of sending an entire multi-page report through a
  local vision model unless the test is explicitly about throughput.

## Local Models

- Local live tests that use Ollama must use the infrastructure Ollama service
  from `infrastructure/docker-compose.yaml`; do not rely on a separately running
  host Ollama with different models.
- Local Ollama model roles are configured through
  `OPEN_TALON_DEFAULT_REASONING_MODEL`, `RETRIEVER_DEFAULT_EMBEDDING_MODEL`, and
  `RETRIEVER_DEFAULT_VISION_MODEL`.
- `REQUIRED_MODELS` is only an explicit bootstrap override for the Ollama
  service, not the canonical place to duplicate model roles.
- When the pinned default `gemma4:31b` cannot return within the live-test window,
  run the stack with another explicit non-`latest` local model tag and record the
  model choice in the test report instead of weakening assertions.

## Docs and Tests

- Keep `infrastructure/.env.example`, `infrastructure/docker-compose.yaml`,
  `infrastructure/ollama-entrypoint.sh`, `README.md`,
  `docs/system-api-reference.md`, `docs/system-quickstart.md`, and
  `services/retriever/README.md` aligned with model/provider defaults.
- Run `tests/retriever` for Retriever changes.
- Run relevant `tests/core-collab/test_agent_contracts.py`,
  `tests/agent-runtime/test_runtime.py`, and
  `tests/gateway-edge/test_llm_provider_health.py` for LLM provider resolution
  changes.
- Run
  `OPEN_TALON_RUN_RETRIEVER_LIVE=1 pytest -m integration tests/infrastructure/test_retriever_live_system.py -q -s`
  against the real local stack when PDF parsing, image understanding, OCR-like
  extraction, chart extraction, Ollama model roles, or ingestion behavior
  changes.

## Key Files

- `retriever/llm.py`
- `retriever/worker.py`
- `retriever/config.py`
- `README.md`
