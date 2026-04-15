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
    AgentToolCallDraft,
    AgentResponseContract,
    AgentTaskRouting,
    ArtifactRef,
    AssetLink,
    ActivateAssetVersionRequest,
    AttachWorkspaceToolRequest,
    AssumeParticipantRoleRequest,
    ApiKeyCreate,
    ApiKeyInfo,
    AuditChainVerificationResult,
    AuditEvent,
    AuditEventDraft,
    AuditEventPage,
    AuditExportRequest,
    AuditExportResult,
    Artifact,
    CreateGitRepositoryRequest,
    CreateAgentParticipantRequest,
    CreateLlmProviderRequest,
    CreateMemoryProviderRequest,
    CreateSystemAgentRequest,
    ConfirmWorkspaceMemoryRequest,
    CreateMemoryEntryRequest,
    CreateThreadMemoryRequest,
    CreateMessageRequest,
    SearchMemoryRequest,
    CreateSystemToolRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteLlmProviderRequest,
    DeleteMemoryProviderRequest,
    DeleteParticipantRequest,
    DeleteWorkspaceToolRequest,
    DeleteWorkspaceRequest,
    EnvRef,
    ExecutionWorkspaceRef,
    EventEnvelope,
    ExecutionHandle,
    ExecutionLimits,
    ExecutionResult,
    ExecutionSpec,
    GitRepository,
    HealthResponse,
    LinkAssetRequest,
    Membership,
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderHealthCheck,
    MemoryProviderHealthReport,
    MemoryProviderRecord,
    MemorySearchHit,
    MemorySearchResponse,
    LlmProviderDefinition,
    LlmProviderHealthCheck,
    LlmProviderHealthReport,
    ParticipantInput,
    ParticipantProfile,
    PresenceState,
    PublishAssetFromGitRequest,
    ResolvedAssetBinding,
    ResultSink,
    RoleDefinition,
    ServiceStatus,
    SystemToolDefinition,
    StopReason,
    RunStep,
    ToolCall,
    ToolCallResult,
    ToolExecutionBinding,
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
    UpdateLlmProviderRequest,
    UpdateMemoryProviderRequest,
    UpdateMemoryEntryRequest,
    UpdateWorkspaceToolRequest,
    Workspace,
    WorkspaceAsset,
    WorkspaceAssetVersion,
    WorkspaceDetail,
    WorkspaceTool,
)
from open_talon_contracts.llm_engines import (  # noqa: E402
    DEFAULT_LOCAL_OLLAMA_ENGINE_ID,
    DEFAULT_LOCAL_OLLAMA_URL,
    DEFAULT_OPENAI_ENGINE_ID,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_OPENAI_RESPONSES_URL,
    LlmEngineDescriptor,
    LlmEngineRegistry,
    LlmEngineSelection,
    LlmEngineSelectionPreferences,
    runtime_preferences_from_definition,
)
from open_talon_contracts.local_env import load_repo_local_env  # noqa: E402


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


class AuthContext(BaseModel):
    kind: Literal["oidc", "api_key"]
    user_id: UUID | None = None
    issuer: str | None = None
    subject: str | None = None
    email: str | None = None
    display_name: str | None = None
    roles: list[str] = Field(default_factory=list)
    claims: dict[str, Any] = Field(default_factory=dict)


class MeResponse(BaseModel):
    user_id: UUID
    issuer: str
    subject: str
    email: str | None = None
    display_name: str
    roles: list[str] = Field(default_factory=list)
    claims: dict[str, Any] = Field(default_factory=dict)

__all__ = [
    "ActorRef",
    "AgentArtifactDraft",
    "AgentConfiguration",
    "AgentDefinition",
    "AgentEndpoint",
    "AgentExecutionContext",
    "AgentInteractionContract",
    "AgentRunResult",
    "AgentToolCallDraft",
    "AgentResponseContract",
    "AgentTaskRouting",
    "ArtifactRef",
    "AssetLink",
    "ActivateAssetVersionRequest",
    "AttachWorkspaceToolRequest",
    "AssumeParticipantRoleRequest",
    "ApiKeyCreate",
    "ApiKeyInfo",
    "AuditChainVerificationResult",
    "AuditEvent",
    "AuditEventDraft",
    "AuditEventPage",
    "AuditExportRequest",
    "AuditExportResult",
    "Artifact",
    "CreateGitRepositoryRequest",
    "CreateAgentParticipantRequest",
    "CreateLlmProviderRequest",
    "CreateMemoryProviderRequest",
    "CreateSystemAgentRequest",
    "ConfirmWorkspaceMemoryRequest",
    "CreateMemoryEntryRequest",
    "CreateThreadMemoryRequest",
    "CreateMessageRequest",
    "SearchMemoryRequest",
    "CreateSystemToolRequest",
    "CreateThreadRequest",
    "CreateWorkspaceRequest",
    "DeleteMemoryProviderRequest",
    "DeleteParticipantRequest",
    "DeleteWorkspaceToolRequest",
    "ChatRequest",
    "ChatResponse",
    "DeleteWorkspaceRequest",
    "DeleteLlmProviderRequest",
    "EnvRef",
    "ExecutionWorkspaceRef",
    "EventEnvelope",
    "ExecutionHandle",
    "ExecutionLimits",
    "ExecutionResult",
    "ExecutionSpec",
    "GitRepository",
    "HealthResponse",
    "LinkAssetRequest",
    "Membership",
    "MemoryEntry",
    "MemoryProviderDefinition",
    "MemoryProviderHealthCheck",
    "MemoryProviderHealthReport",
    "MemoryProviderRecord",
    "MemorySearchHit",
    "MemorySearchResponse",
    "LlmProviderDefinition",
    "LlmProviderHealthCheck",
    "LlmProviderHealthReport",
    "ParticipantInput",
    "ParticipantProfile",
    "PresenceState",
    "PublishAssetFromGitRequest",
    "ResolvedAssetBinding",
    "ResultSink",
    "RoleDefinition",
    "ServiceStatus",
    "SystemToolDefinition",
    "SessionInfo",
    "StopReason",
    "RunStep",
    "ToolCall",
    "ToolCallResult",
    "ToolExecutionBinding",
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
    "UpdateLlmProviderRequest",
    "UpdateMemoryProviderRequest",
    "UpdateMemoryEntryRequest",
    "UpdateWorkspaceToolRequest",
    "KafkaChatRequest",
    "KafkaChatResponse",
    "Message",
    "AuthContext",
    "MeResponse",
    "Workspace",
    "WorkspaceAsset",
    "WorkspaceAssetVersion",
    "WorkspaceDetail",
    "WorkspaceTool",
    "DEFAULT_LOCAL_OLLAMA_ENGINE_ID",
    "DEFAULT_LOCAL_OLLAMA_URL",
    "DEFAULT_OPENAI_ENGINE_ID",
    "DEFAULT_OPENAI_MODEL",
    "DEFAULT_OPENAI_RESPONSES_URL",
    "LlmEngineDescriptor",
    "LlmEngineRegistry",
    "LlmEngineSelection",
    "LlmEngineSelectionPreferences",
    "load_repo_local_env",
    "runtime_preferences_from_definition",
]
