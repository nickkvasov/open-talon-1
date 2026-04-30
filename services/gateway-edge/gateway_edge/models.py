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
    ActivateAgentDefinitionVersionRequest,
    AgentConfiguration,
    AgentBundleGitSource,
    AgentBundlePublishResult,
    AgentBundleUploadResult,
    AgentBundleValidationDiagnostic,
    AgentBundleValidationResult,
    AgentDefinition,
    AgentDefinitionVersion,
    AgentIdentity,
    AgentIdentityProvisioningResult,
    AgentEndpoint,
    AgentExecutionContext,
    AgentGitCommitRequest,
    AgentGitCommitResult,
    AgentGitDiffResult,
    AgentGitFileContent,
    AgentGitFileMutationRequest,
    AgentGitFileReadRequest,
    AgentGitWorktreeSession,
    AgentHarness,
    AgentInternalToolBinding,
    AgentCompactionPolicy,
    AgentCollaborationPolicy,
    AgentInteractionContract,
    AgentMemoryPolicy,
    AgentPlanningPolicy,
    AgentRunResult,
    AgentRoleBinding,
    AgentStopPolicy,
    CompletionRule,
    AgentToolCallDraft,
    AgentResponseContract,
    AgentTaskRouting,
    ArtifactRef,
    AgentToolUsePolicy,
    AgentValidationPolicy,
    AssetLink,
    ActivateAssetVersionRequest,
    AttachWorkspaceToolRequest,
    AttachLibraryToWorkspaceRequest,
    AttachWorkspaceMcpServerRequest,
    AttachWorkspaceSystemPluginRequest,
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
    BindAgentRoleRequest,
    BindHumanRoleRequest,
    CreateProjectRequest,
    CreateGitRepositoryRequest,
    CreateAgentGitWorktreeSessionRequest,
    CreateAgentParticipantRequest,
    CreateInteractionAnswerRequest,
    CreateInteractionQuestionRequest,
    CreateInteractionRequest,
    CreateInteractionRequestsRequest,
    CreateLibraryRequest,
    CreateLibraryItemRequest,
    CreateLibraryTextItemRequest,
    CreateLlmProviderRequest,
    CreateMemoryProviderRequest,
    CreateMcpServerRequest,
    CreateSystemPluginRequest,
    CreateOrganizationRequest,
    CreateAgentIdentityRequest,
    CreateIamRoleRequest,
    CreateSystemAgentRequest,
    ConfirmWorkspaceMemoryRequest,
    CreateMemoryEntryRequest,
    CreateThreadMemoryRequest,
    CreateMessageRequest,
    CreateToolGenerationRevisionRequest,
    SearchMemoryRequest,
    CreateSystemToolRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteLlmProviderRequest,
    DeleteLibraryRequest,
    DeleteMemoryProviderRequest,
    DeleteMcpServerRequest,
    DeleteSystemPluginRequest,
    DeleteParticipantRequest,
    DeleteRoleDefinitionRequest,
    DeleteSystemAgentRequest,
    DeleteSystemToolRequest,
    DeleteWorkspaceToolRequest,
    DeleteWorkspaceMcpServerRequest,
    DeleteWorkspaceSystemPluginRequest,
    DeleteWorkspaceRequest,
    UpdateWorkspaceRequest,
    EnvRef,
    ExecutionWorkspaceRef,
    EventEnvelope,
    ExecutionHandle,
    ExecutionLimits,
    ExecutionResult,
    ExecutionSpec,
    GitRepository,
    GeneratedToolManifest,
    GeneratedToolSmokeTest,
    GeneratedToolValidationCheck,
    GeneratedToolValidationReport,
    HealthResponse,
    HumanRoleBinding,
    IamPermission,
    IamRoleDefinition,
    IndexLibraryRequest,
    LinkAssetRequest,
    Library,
    LibraryItem,
    LibraryWorkspaceAttachment,
    Membership,
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderHealthCheck,
    MemoryProviderHealthReport,
    MemoryProviderRecord,
    MemorySearchHit,
    MemorySearchResponse,
    PublicationReview,
    McpPromptDefinition,
    McpResourceDefinition,
    McpServerDefinition,
    McpServerSyncJob,
    McpServerSyncResult,
    McpToolDefinition,
    LlmProviderDefinition,
    LlmProviderHealthCheck,
    LlmProviderHealthReport,
    Organization,
    OrganizationMembership,
    Project,
    ProjectAccessBinding,
    ProjectAccessRole,
    ProjectSubjectRef,
    ProjectSubjectType,
    InteractionAnswer,
    InteractionQuestion,
    InteractionQuestionDraft,
    InteractionRequest,
    InteractionRequestDetail,
    InteractionRequestDraft,
    InteractionRequestTarget,
    ParticipantInput,
    ParticipantSelector,
    ParticipantProfile,
    PresenceState,
    PublishAssetFromGitRequest,
    PublishAgentBundleFromGitRequest,
    RequestMcpServerSyncRequest,
    RequestSystemPluginSyncRequest,
    UploadFileAssetRequest,
    PrincipalContext,
    ResolvedAssetBinding,
    CreateRetrievalContextPackRequest,
    CreateRetrievalCorpusRequest,
    CreateRetrievalIngestionJobRequest,
    CreateRetrievalProfileRequest,
    CreateRetrievalSourceRequest,
    CancelMethodicExecutionRequest,
    CreateMethodicAssignmentRequest,
    CreateMethodicExecutionRequest,
    CreateMethodicResourceRequestRequest,
    EvaluateMethodicStepRequest,
    ResultSink,
    MethodicExecution,
    MethodicExecutionAssignment,
    MethodicExecutionCheck,
    MethodicExecutionDetail,
    MethodicExecutionStep,
    MethodicResourceRequest,
    RetrievalChunk,
    RetrievalChunkCitation,
    RetrievalContextPack,
    RetrievalCorpus,
    RetrievalEmbedding,
    RetrievalIngestionJob,
    RetrievalProfile,
    RetrievalRun,
    RetrievalSearchHit,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
    RetrievalSource,
    RetrievalSourceVersion,
    RunRetrievalSearchRequest,
    RoleDefinition,
    ReviewMethodicResourceRequest,
    ServiceStatus,
    SystemToolDefinition,
    SystemPluginCapabilityDefinition,
    SystemPluginDefinition,
    SystemPluginSyncJob,
    SystemPluginSyncResult,
    StopReason,
    RunStep,
    ToolCall,
    ToolCallResult,
    ToolGenerationRequest,
    ToolGenerationRequestDetail,
    ToolGenerationRevision,
    ToolExecutionBinding,
    ToolParameterContract,
    ToolParameterDefinition,
    Task,
    TargetRef,
    Thread,
    ThreadDetail,
    TimelineMessage,
    TimelinePage,
    WorkspaceCommunicationLogEntry,
    WorkspaceCommunicationLogPage,
    UpdateSystemAgentRequest,
    UpdateInteractionRequestRequest,
    UpdateLibraryRequest,
    UpdateLibraryItemRequest,
    UpsertRoleDefinitionRequest,
    UpdateSystemToolRequest,
    UpdateAgentParticipantRequest,
    UpdateLlmProviderRequest,
    UpdateMemoryProviderRequest,
    UpdateMcpServerRequest,
    UpdateSystemPluginRequest,
    UpdateMemoryEntryRequest,
    UpdateOrganizationRequest,
    UpdateProjectRequest,
    UpsertProjectAccessRequest,
    ReviewToolGenerationRevisionRequest,
    RotateAgentIdentitySecretRequest,
    UpdateWorkspaceToolRequest,
    UpdateWorkspaceMcpServerRequest,
    UpdateWorkspaceSystemPluginRequest,
    UploadAgentBundleArchiveRequest,
    UpdateAgentIdentityStatusRequest,
    UpdateIamRoleRequest,
    ValidateAgentBundleFromGitRequest,
    Workspace,
    WorkspaceAsset,
    WorkspaceAssetVersion,
    WorkspaceDetail,
    WorkspaceMcpCapability,
    WorkspaceMcpPrompt,
    WorkspaceMcpResource,
    WorkspaceMcpServer,
    WorkspaceMcpTool,
    WorkspacePluginCapability,
    WorkspacePluginPrompt,
    WorkspacePluginResource,
    WorkspacePluginTool,
    WorkspaceSystemPlugin,
    WorkspaceModerationPolicy,
    WorkspaceTool,
    AddOrganizationMemberRequest,
    RemoveOrganizationMemberRequest,
    RemoveProjectAccessRequest,
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
    principal_type: Literal["human", "agent", "api_key"] = "human"
    user_id: UUID | None = None
    agent_identity_id: UUID | None = None
    system_agent_id: UUID | None = None
    issuer: str | None = None
    subject: str | None = None
    client_id: str | None = None
    provider_key: str | None = None
    email: str | None = None
    display_name: str | None = None
    roles: list[str] = Field(default_factory=list)
    platform_admin: bool = False
    claims: dict[str, Any] = Field(default_factory=dict)


class MeResponse(BaseModel):
    user_id: UUID
    principal_type: Literal["human"] = "human"
    issuer: str
    subject: str
    email: str | None = None
    display_name: str
    roles: list[str] = Field(default_factory=list)
    claims: dict[str, Any] = Field(default_factory=dict)


class RuntimeQueueCounts(BaseModel):
    pending: int = 0
    claimed: int = 0


class RuntimeFailedCounts(BaseModel):
    tasks: int = 0
    run_steps: int = 0
    tool_calls: int = 0


class RuntimeOldestPendingAge(BaseModel):
    run_steps: int | None = None
    tool_calls: int | None = None


class WorkspaceTokenTotal(BaseModel):
    workspace_id: UUID
    total_tokens: int = 0


class RuntimeTokenTotals(BaseModel):
    global_total_tokens: int = 0
    by_workspace: list[WorkspaceTokenTotal] = Field(default_factory=list)


class RuntimeOverviewResponse(BaseModel):
    tasks: RuntimeQueueCounts = Field(default_factory=RuntimeQueueCounts)
    run_steps: RuntimeQueueCounts = Field(default_factory=RuntimeQueueCounts)
    tool_calls: RuntimeQueueCounts = Field(default_factory=RuntimeQueueCounts)
    failed_last_24h: RuntimeFailedCounts = Field(default_factory=RuntimeFailedCounts)
    oldest_pending_age_seconds: RuntimeOldestPendingAge = Field(
        default_factory=RuntimeOldestPendingAge
    )
    token_totals: RuntimeTokenTotals = Field(default_factory=RuntimeTokenTotals)

__all__ = [
    "ActorRef",
    "AgentArtifactDraft",
    "AgentConfiguration",
    "AgentDefinition",
    "AgentEndpoint",
    "AgentExecutionContext",
    "AgentCompactionPolicy",
    "AgentInteractionContract",
    "AgentRunResult",
    "CompletionRule",
    "AgentToolCallDraft",
    "AgentResponseContract",
    "AgentTaskRouting",
    "ArtifactRef",
    "AssetLink",
    "ActivateAssetVersionRequest",
    "AttachWorkspaceToolRequest",
    "AttachWorkspaceMcpServerRequest",
    "AttachWorkspaceSystemPluginRequest",
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
    "AddOrganizationMemberRequest",
    "CreateOrganizationRequest",
    "CreateProjectRequest",
    "CreateGitRepositoryRequest",
    "CreateAgentParticipantRequest",
    "CreateInteractionAnswerRequest",
    "CreateInteractionQuestionRequest",
    "CreateInteractionRequest",
    "CreateInteractionRequestsRequest",
    "CreateLlmProviderRequest",
    "CreateMemoryProviderRequest",
    "CreateMcpServerRequest",
    "CreateSystemPluginRequest",
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
    "DeleteMcpServerRequest",
    "DeleteSystemPluginRequest",
    "DeleteParticipantRequest",
    "DeleteRoleDefinitionRequest",
    "DeleteSystemAgentRequest",
    "DeleteSystemToolRequest",
    "DeleteWorkspaceToolRequest",
    "DeleteWorkspaceMcpServerRequest",
    "DeleteWorkspaceSystemPluginRequest",
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
    "McpPromptDefinition",
    "McpResourceDefinition",
    "McpServerDefinition",
    "McpServerSyncJob",
    "McpServerSyncResult",
    "McpToolDefinition",
    "MemoryProviderHealthCheck",
    "MemoryProviderHealthReport",
    "MemoryProviderRecord",
    "MemorySearchHit",
    "MemorySearchResponse",
    "PublicationReview",
    "LlmProviderDefinition",
    "LlmProviderHealthCheck",
    "LlmProviderHealthReport",
    "Organization",
    "OrganizationMembership",
    "Project",
    "ProjectAccessBinding",
    "ProjectAccessRole",
    "ProjectSubjectRef",
    "ProjectSubjectType",
    "InteractionAnswer",
    "InteractionQuestion",
    "InteractionQuestionDraft",
    "InteractionRequest",
    "InteractionRequestDetail",
    "InteractionRequestDraft",
    "InteractionRequestTarget",
    "ParticipantInput",
    "ParticipantSelector",
    "ParticipantProfile",
    "PresenceState",
    "PublishAssetFromGitRequest",
    "RequestMcpServerSyncRequest",
    "RequestSystemPluginSyncRequest",
    "UploadFileAssetRequest",
    "ResolvedAssetBinding",
    "CreateRetrievalContextPackRequest",
    "CreateRetrievalCorpusRequest",
    "CreateRetrievalIngestionJobRequest",
    "CreateRetrievalProfileRequest",
    "CreateRetrievalSourceRequest",
    "CancelMethodicExecutionRequest",
    "CreateMethodicAssignmentRequest",
    "CreateMethodicExecutionRequest",
    "CreateMethodicResourceRequestRequest",
    "EvaluateMethodicStepRequest",
    "ResultSink",
    "MethodicExecution",
    "MethodicExecutionAssignment",
    "MethodicExecutionCheck",
    "MethodicExecutionDetail",
    "MethodicExecutionStep",
    "MethodicResourceRequest",
    "RetrievalChunk",
    "RetrievalChunkCitation",
    "RetrievalContextPack",
    "RetrievalCorpus",
    "RetrievalEmbedding",
    "RetrievalIngestionJob",
    "RetrievalProfile",
    "RetrievalRun",
    "RetrievalSearchHit",
    "RetrievalSearchRequest",
    "RetrievalSearchResponse",
    "RetrievalSource",
    "RetrievalSourceVersion",
    "RunRetrievalSearchRequest",
    "RoleDefinition",
    "ReviewMethodicResourceRequest",
    "RuntimeFailedCounts",
    "RuntimeOldestPendingAge",
    "RuntimeOverviewResponse",
    "RuntimeQueueCounts",
    "RuntimeTokenTotals",
    "ServiceStatus",
    "SystemToolDefinition",
    "SystemPluginCapabilityDefinition",
    "SystemPluginDefinition",
    "SystemPluginSyncJob",
    "SystemPluginSyncResult",
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
    "WorkspaceCommunicationLogEntry",
    "WorkspaceCommunicationLogPage",
    "RemoveOrganizationMemberRequest",
    "RemoveProjectAccessRequest",
    "UpdateSystemAgentRequest",
    "UpdateInteractionRequestRequest",
    "UpsertRoleDefinitionRequest",
    "UpdateSystemToolRequest",
    "UpdateAgentParticipantRequest",
    "UpdateLlmProviderRequest",
    "UpdateMemoryProviderRequest",
    "UpdateMcpServerRequest",
    "UpdateSystemPluginRequest",
    "UpdateMemoryEntryRequest",
    "UpdateWorkspaceToolRequest",
    "UpdateWorkspaceMcpServerRequest",
    "UpdateWorkspaceSystemPluginRequest",
    "UpdateWorkspaceRequest",
    "UpdateOrganizationRequest",
    "UpdateProjectRequest",
    "UpsertProjectAccessRequest",
    "KafkaChatRequest",
    "KafkaChatResponse",
    "Message",
    "AuthContext",
    "MeResponse",
    "Workspace",
    "WorkspaceAsset",
    "WorkspaceAssetVersion",
    "WorkspaceDetail",
    "WorkspaceMcpCapability",
    "WorkspaceMcpPrompt",
    "WorkspaceMcpResource",
    "WorkspaceMcpServer",
    "WorkspaceMcpTool",
    "WorkspacePluginCapability",
    "WorkspacePluginPrompt",
    "WorkspacePluginResource",
    "WorkspacePluginTool",
    "WorkspaceSystemPlugin",
    "WorkspaceModerationPolicy",
    "WorkspaceTokenTotal",
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
