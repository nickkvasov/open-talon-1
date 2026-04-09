# Open Talon — API Gateway

This package is the legacy gateway layout kept for compatibility during the repo split. New development should use the repository-root `.venv` and the extracted service in `services/gateway-edge`.

## Overview

Multi-interface Kafka-driven API gateway that connects any frontend (Web, Terminal, or future bot adapters) to the agent swarm via a clean, unified HTTP API.

```
┌──────────────┬──────────────┬──────────────────────┐
│   Web UI     │   TUI Client │  Future: Telegram /  │
│  (browser)   │  (terminal)  │        Discord        │
└──────┬───────┴──────┬───────┴────────┬─────────────┘
       │ WebSocket    │ WebSocket      │
       └──────────────┴────────────────┘
                       │
              ┌─────────────────┐
              │  API Gateway    │  ← This service
              │  FastAPI + uvicorn
              └─────────────────┘
              ↓ kafka producer     ↑ kafka consumer
       talon.chat.requests    talon.chat.responses
              ↓                    ↑
              └──── Agent Swarm ───┘  (separate PR)
```

## Quick Start

```bash
# From repository root, create the canonical shared Python env
./scripts/bootstrap-python.sh
source .venv/bin/activate

# Copy env template for this legacy package if needed
cp api-gateway/.env.example api-gateway/.env

# Run (infrastructure must be up)
cd api-gateway
uvicorn app.main:app --reload

# Open the Web UI
open http://localhost:8000
```

### Dev mode (no agent needed)

Enable the in-process echo agent to test the full Kafka round-trip:

```bash
ECHO_AGENT_ENABLED=true uvicorn app.main:app --reload
```

### Terminal UI

```bash
# Run
python -m tui.main
python -m tui.main --gateway http://remote-host:8000
python -m tui.main --api-key <key>
```

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/health` | Liveness probe |
| `GET`  | `/ready` | Readiness (checks all services) |
| `POST` | `/v1/chat` | Synchronous chat (waits for full response) |
| `POST` | `/v1/chat/stream` | SSE streaming response |
| `WS`   | `/v1/ws/chat/{session_id}` | Bidirectional WebSocket |
| `GET`  | `/v1/history/{session_id}` | Load chat history |
| `GET`  | `/v1/sessions/{session_id}` | Session info |
| `DELETE` | `/v1/sessions/{session_id}` | Delete session + history |
| `POST` | `/v1/admin/api-keys` | Create API key |
| `GET`  | `/v1/admin/api-keys` | List API keys |
| `DELETE` | `/v1/admin/api-keys/{id}` | Revoke API key |

Interactive docs: http://localhost:8000/docs

## Auth Modes

Set `AUTH_MODE` env var:

| Mode | Description |
|------|-------------|
| `none` | No auth (dev default) |
| `api_key` | `X-API-Key: <key>` header |
| `openbao` | `Authorization: Bearer <bao_token>` |
| `any` | Accept either |

## Kafka Wire Format

**Request** (`talon.chat.requests`):
```json
{
  "correlation_id": "uuid",
  "session_id": "uuid",
  "message": "Hello",
  "history": [{"role": "user", "content": "...", "timestamp": "..."}],
  "timestamp": "2026-..."
}
```

**Response** (`talon.chat.responses`):
```json
{
  "correlation_id": "uuid",
  "session_id": "uuid",
  "type": "response | stream_token | stream_done | error",
  "role": "assistant",
  "content": "...",
  "error": null,
  "timestamp": "2026-..."
}
```

## Docker

```bash
# From repository root
docker compose up api-gateway
```

## Environment Variables

See [`.env.example`](.env.example) for the full list.
