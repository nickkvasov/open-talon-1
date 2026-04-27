# Open Talon Retriever

`services/retriever` is the reusable retrieval ingestion layer.

Current behavior:

- `talon-retriever-worker` claims queued `retrieval_ingestion_jobs` from Postgres.
- Raw source bytes are read from MinIO through immutable `workspace_asset_versions`.
- V1 extraction supports text, Markdown-like text, HTML, and PDF text.
- PDF page rendering is available through PyMuPDF for optional visual extraction.
- Chunking is structure-aware where possible, then falls back to token-window chunks.
- Embeddings use Ollama by default and write pgvector-backed vectors to Postgres.
- Visual extraction is disabled by default; when enabled, the worker resolves its
  vision LLM through the shared `llm_providers` engine registry. The default
  engine is `local-ollama`, and profile `vision_provider_key` can select either
  an engine id or a provider key such as `openai` or `anthropic`.

Default env:

- `RETRIEVER_DEFAULT_EMBEDDING_PROVIDER=ollama`
- `RETRIEVER_DEFAULT_EMBEDDING_MODEL=bge-m3:567m`
- `RETRIEVER_DEFAULT_VISION_PROVIDER=ollama`
- `RETRIEVER_DEFAULT_VISION_ENGINE_ID=local-ollama`
- `RETRIEVER_DEFAULT_VISION_MODEL=gemma4:31b`
- `RETRIEVER_OLLAMA_BASE_URL=http://127.0.0.1:11434`
- `RETRIEVER_VISUAL_EXTRACTION_ENABLED=false`

The worker returns evidence only. Agents or clients perform synthesis from cited retrieval hits or context packs.
