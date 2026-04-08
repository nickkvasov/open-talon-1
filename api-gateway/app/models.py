from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── Core primitives ───────────────────────────────────────────────────────────

class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionInfo(BaseModel):
    session_id: UUID
    created_at: datetime
    last_active: datetime
    message_count: int = 0


# ── REST request / response ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    # Omit to start a new session; supply to resume an existing one.
    session_id: UUID | None = None


class ChatResponse(BaseModel):
    session_id: UUID
    correlation_id: UUID
    message: Message
    latency_ms: int | None = None


# ── Streaming events (SSE / WebSocket) ────────────────────────────────────────

class StreamEvent(BaseModel):
    type: Literal["token", "done", "error"]
    session_id: UUID
    correlation_id: UUID
    content: str = ""
    error: str | None = None


# ── Kafka wire format ─────────────────────────────────────────────────────────

class KafkaChatRequest(BaseModel):
    """Published to senate.chat.requests by the gateway."""
    correlation_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    message: str
    history: list[Message] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class KafkaChatResponse(BaseModel):
    """Consumed from senate.chat.responses by the gateway."""
    correlation_id: UUID
    session_id: UUID
    # type = "response"         → full completed message (REST path)
    # type = "stream_token"     → partial token (WS/SSE path)
    # type = "stream_done"      → final token, signals stream end
    # type = "error"            → agent error
    type: Literal["response", "stream_token", "stream_done", "error"]
    role: Literal["assistant"] = "assistant"
    content: str = ""
    error: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Auth ─────────────────────────────────────────────────────────────────────

class ApiKeyCreate(BaseModel):
    label: str
    ttl_seconds: int | None = None  # None = never expires


class ApiKeyInfo(BaseModel):
    key_id: str
    label: str
    created_at: datetime
    expires_at: datetime | None = None
    # The raw key is returned only on creation
    raw_key: str | None = None


# ── Health ────────────────────────────────────────────────────────────────────

class ServiceStatus(BaseModel):
    name: str
    healthy: bool
    latency_ms: int | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    services: list[ServiceStatus]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
