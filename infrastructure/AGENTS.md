# Infrastructure Agent Guide

This guide applies under `infrastructure/` and adds to the root guide.

## Local Stack

- `infrastructure` contains the local Docker-based backing services.
- Preserve the reproducible local-first path: `./open-talon start`, `.venv`, and
  checked-in defaults should keep working after infrastructure changes.
- Local infrastructure defaults are documented in `infrastructure/.env.example`;
  keep it aligned with `infrastructure/docker-compose.yaml`, `open-talon`,
  service READMEs, and docs.
- Keycloak is the default local OIDC provider and first machine-identity
  provisioning adapter, not the source of truth for authorization.
- Local OpenBao uses persistent file storage under `infrastructure/data/openbao`;
  do not assume `docker compose down` clears local secrets.
- Optional local Memgraph for Mem0 graph mode starts with
  `./open-talon start --memgraph`.
- Local live tests that use Ollama must use the infrastructure Ollama service
  from `infrastructure/docker-compose.yaml`; do not rely on a separately running
  host Ollama with different models.
- Local Ollama model roles are configured through
  `OPEN_TALON_DEFAULT_REASONING_MODEL`, `RETRIEVER_DEFAULT_EMBEDDING_MODEL`, and
  `RETRIEVER_DEFAULT_VISION_MODEL`.
- `REQUIRED_MODELS` is only an explicit bootstrap override for the Ollama
  service, not the canonical place to duplicate model roles.
- Because `./open-talon` sources `infrastructure/.env`, update that local env
  file or the persisted local `llm_providers` row before trusting a shell-prefix
  override for `OPEN_TALON_DEFAULT_REASONING_MODEL`; do the same for
  `RETRIEVER_DEFAULT_VISION_MODEL` when Retriever visual tests need a smaller
  model.
- Local audit provider defaults are Kafka for relay, ClickHouse for projection,
  and MinIO for archive/export/checkpoint storage.

## Default Endpoints

- Gateway: `http://127.0.0.1:8000`
- Gateway docs: `http://127.0.0.1:8000/docs`
- Admin web dev server: `http://localhost:5173`
- Audit API base: `http://127.0.0.1:8000/v1/audit`
- Kafka: `localhost:9092`
- Valkey: `localhost:6379`
- Keycloak: `http://127.0.0.1:8081`
  - admin console: `admin` / `admin`
  - realm: `open-talon`
  - issuer: `http://127.0.0.1:8081/realms/open-talon`
  - OpenID config:
    `http://127.0.0.1:8081/realms/open-talon/.well-known/openid-configuration`
  - realm users: `admin` / `admin123`, `admin2` / `admin223`, `supervisor` /
    `supervisor123`, `supervisor2` / `supervisor223`, `user1` / `user12345`,
    `user2` / `user22345`
- OpenBao: `http://127.0.0.1:8200`
  - root token: `root`
- pgAdmin: `http://127.0.0.1:5050`
  - login: `admin@local.dev` / `admin`
- Langfuse: `http://127.0.0.1:3000`
  - login: `admin@example.com` / `admin123456`
- Langfuse worker: `localhost:3030`
- Ollama: `http://127.0.0.1:11434`
- MinIO API: `http://127.0.0.1:9090`
- MinIO console: `http://127.0.0.1:9091`
  - login: `minio` / `miniosecret`
- Forgejo: `http://127.0.0.1:3001`
  - admin: `forgejo` / `forgejo123`
- Forgejo SSH: `localhost:2222`
- ClickHouse HTTP: `http://127.0.0.1:8123`
- ClickHouse native: `localhost:9000`
  - login: `langfuse` / `langfuse`
- Memgraph bolt when started with `./open-talon start --memgraph`:
  `localhost:7688`
- Memgraph HTTP when started with `./open-talon start --memgraph`:
  `http://127.0.0.1:7444`
- Memgraph credentials when started with `./open-talon start --memgraph`:
  `memgraph` / `memgraph`
- Langfuse Postgres DB: `langfuse_db`
- Valkey password: `langfuse-dev-secret`
- Optional HyperDX profile:
  - UI: `http://127.0.0.1:8080`
  - OTLP gRPC: `127.0.0.1:4317`
  - OTLP HTTP: `127.0.0.1:4318`

## Tests

- Use `./scripts/run-live-tests.sh` for coordinated live runs. It provides
  fractions such as `core`, `agents`, `providers`, `default-stack`,
  `web-search`, and `knowledge`, and owns required environment gates and stack
  profiles for default, web-search, and XWiki live suites.
- Run `pytest -m integration tests/infrastructure/test_infrastructure.py -v -s`
  for infrastructure integration coverage.
- Live tests may need local-service access to Docker Compose services, Keycloak,
  OpenBao, gateway, MinIO, Ollama, or the Docker socket. If sandboxed execution
  fails with a local network or permission error, rerun the same command with
  the required escalation rather than weakening the test.

## Key Files

- `docker-compose.yaml`
- `ollama-entrypoint.sh`
- `.env.example`
