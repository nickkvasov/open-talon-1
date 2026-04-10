from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "packages" / "contracts"
if _CONTRACTS_DIR.is_dir():
    contracts_path = str(_CONTRACTS_DIR)
    if contracts_path not in sys.path:
        sys.path.insert(0, contracts_path)

from open_talon_contracts.models import (  # noqa: E402
    ActorRef,
    AgentArtifactDraft,
    AgentConfiguration,
    AgentDefinition,
    AgentEndpoint,
    AgentExecutionContext,
    AgentInteractionContract,
    AgentRunResult,
    AgentResponseContract,
    AgentTaskRouting,
    AttachWorkspaceToolRequest,
    AssumeParticipantRoleRequest,
    ApiKeyCreate,
    ApiKeyInfo,
    Artifact,
    CreateAgentParticipantRequest,
    CreateSystemAgentRequest,
    CreateMemoryEntryRequest,
    CreateMessageRequest,
    CreateSystemToolRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteParticipantRequest,
    DeleteWorkspaceToolRequest,
    DeleteWorkspaceRequest,
    EventEnvelope,
    HealthResponse,
    Membership,
    MemoryEntry,
    ParticipantInput,
    ParticipantProfile,
    PresenceState,
    RoleDefinition,
    ServiceStatus,
    SystemToolDefinition,
    StopReason,
    ToolParameterContract,
    ToolParameterDefinition,
    Task,
    TargetRef,
    Thread,
    ThreadDetail,
    TimelineMessage,
    TimelinePage,
    UpdateSystemAgentRequest,
    UpsertRoleDefinitionRequest,
    UpdateSystemToolRequest,
    UpdateAgentParticipantRequest,
    UpdateMemoryEntryRequest,
    UpdateWorkspaceToolRequest,
    Workspace,
    WorkspaceDetail,
    WorkspaceTool,
)


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


class ChatRequest(BaseModel):
    message: str
    session_id: UUID | None = None


class ChatResponse(BaseModel):
    session_id: UUID
    correlation_id: UUID
    message: Message
    latency_ms: int | None = None


class StreamEvent(BaseModel):
    type: Literal["token", "done", "error"]
    session_id: UUID
    correlation_id: UUID
    content: str = ""
    error: str | None = None


class KafkaChatRequest(BaseModel):
    correlation_id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    message: str
    history: list[Message] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class KafkaChatResponse(BaseModel):
    correlation_id: UUID
    session_id: UUID
    type: Literal["response", "stream_token", "stream_done", "error"]
    role: Literal["assistant"] = "assistant"
    content: str = ""
    error: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)

__all__ = [
    "ActorRef",
    "AgentArtifactDraft",
    "AgentConfiguration",
    "AgentDefinition",
    "AgentEndpoint",
    "AgentExecutionContext",
    "AgentInteractionContract",
    "AgentRunResult",
    "AgentResponseContract",
    "AgentTaskRouting",
    "AttachWorkspaceToolRequest",
    "AssumeParticipantRoleRequest",
    "ApiKeyCreate",
    "ApiKeyInfo",
    "Artifact",
    "CreateAgentParticipantRequest",
    "CreateSystemAgentRequest",
    "CreateMemoryEntryRequest",
    "CreateMessageRequest",
    "CreateSystemToolRequest",
    "CreateThreadRequest",
    "CreateWorkspaceRequest",
    "DeleteParticipantRequest",
    "DeleteWorkspaceToolRequest",
    "ChatRequest",
    "ChatResponse",
    "DeleteWorkspaceRequest",
    "EventEnvelope",
    "HealthResponse",
    "Membership",
    "MemoryEntry",
    "ParticipantInput",
    "ParticipantProfile",
    "PresenceState",
    "RoleDefinition",
    "ServiceStatus",
    "SystemToolDefinition",
    "SessionInfo",
    "StopReason",
    "ToolParameterContract",
    "ToolParameterDefinition",
    "StreamEvent",
    "Task",
    "TargetRef",
    "Thread",
    "ThreadDetail",
    "TimelineMessage",
    "TimelinePage",
    "UpdateSystemAgentRequest",
    "UpsertRoleDefinitionRequest",
    "UpdateSystemToolRequest",
    "UpdateAgentParticipantRequest",
    "UpdateMemoryEntryRequest",
    "UpdateWorkspaceToolRequest",
    "KafkaChatRequest",
    "KafkaChatResponse",
    "Message",
    "Workspace",
    "WorkspaceDetail",
    "WorkspaceTool",
]
