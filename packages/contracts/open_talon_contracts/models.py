from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AliasChoices, BaseModel, Field

Visibility = Literal["public", "workspace", "agents_only", "private"]
ParticipantType = Literal["user", "agent"]
ParticipantStatus = Literal["active", "idle", "busy", "offline"]
ThreadState = Literal["active", "paused", "resolved", "archived"]
MessageStatus = Literal["draft", "streaming", "completed", "failed"]
TaskStatus = Literal["created", "claimed", "released", "completed", "failed"]
RunStatus = Literal["started", "progressing", "completed", "failed"]
RunStepStatus = Literal["created", "claimed", "waiting_tools", "completed", "failed"]
RunStepKind = Literal["model"]
ToolCallStatus = Literal["created", "claimed", "completed", "failed"]
AgentEndpointKind = Literal["local", "system", "remote"]
ExecutionBackendKind = Literal["docker", "local_process"]
ToolTrustLevel = Literal["sandboxed", "trusted"]
ExecutionWorkspaceRefMode = Literal["local_path"]
NetworkPolicy = Literal["none", "full"]
WorkspaceAccessMode = Literal["none", "read_only", "read_write"]
ExecutionInvocationKind = Literal["tool_call"]
ExecutionStatus = Literal["queued", "running", "completed", "failed", "cancelled", "timed_out"]
StopReason = Literal[
    "completed",
    "needs_user_input",
    "blocked_dependency",
    "handoff_required",
    "budget_exhausted",
    "tool_failure",
    "policy_refused",
    "cancelled",
    "superseded",
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ActorRef(BaseModel):
    type: ParticipantType
    id: UUID


class TargetRef(BaseModel):
    type: Literal[
        "workspace",
        "thread",
        "message",
        "task",
        "artifact",
        "memory_entry",
        "run",
        "participant",
        "run_step",
        "tool_call",
    ]
    id: UUID


class ParticipantInput(BaseModel):
    participant_id: UUID
    participant_type: ParticipantType
    display_name: str
    description: str | None = None
    roles: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    visibility_scope: Visibility = "workspace"


class AgentEndpoint(BaseModel):
    kind: AgentEndpointKind
    url: str | None = None
    model: str | None = None


class AgentConfiguration(BaseModel):
    endpoint: AgentEndpoint
    system_prompt: str
    definition: dict[str, Any] = Field(default_factory=dict)


class AgentResponseContract(BaseModel):
    format: Literal["markdown", "text", "json"] = "markdown"
    title: str | None = None
    required_sections: list[str] = Field(default_factory=list)
    guidance: list[str] = Field(default_factory=list)
    json_schema: dict[str, Any] = Field(default_factory=dict)


class AgentInteractionContract(BaseModel):
    instructions: list[str] = Field(default_factory=list)
    response_contract: AgentResponseContract = Field(default_factory=AgentResponseContract)
    thread_reply_template: str | None = None
    completion_criteria: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentDefinition(BaseModel):
    agent_id: UUID
    display_name: str
    description: str
    role: str
    capabilities: list[str] = Field(default_factory=list)
    endpoint: AgentEndpoint
    system_prompt: str
    interaction_contract: AgentInteractionContract = Field(
        default_factory=AgentInteractionContract
    )
    definition: dict[str, Any] = Field(default_factory=dict)
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Workspace(BaseModel):
    workspace_id: UUID
    name: str
    description: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Thread(BaseModel):
    thread_id: UUID
    workspace_id: UUID
    title: str
    state: ThreadState = "active"
    parent_thread_id: UUID | None = None
    previous_thread_id: UUID | None = None
    related_thread_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParticipantProfile(BaseModel):
    participant_id: UUID
    workspace_id: UUID
    participant_type: ParticipantType
    user_id: UUID | None = None
    system_agent_id: UUID | None = None
    display_name: str
    description: str | None = None
    roles: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    status: ParticipantStatus = "active"
    visibility_scope: Visibility = "workspace"
    agent_config: AgentConfiguration | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoleDefinition(BaseModel):
    name: str
    definition: str
    updated_by: UUID
    updated_at: datetime = Field(default_factory=utcnow)


class ToolParameterDefinition(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True
    default: Any | None = None
    enum: list[Any] = Field(default_factory=list)


class ToolParameterContract(BaseModel):
    parameters: list[ToolParameterDefinition] = Field(default_factory=list)
    additional_properties: bool = False


class ArtifactRef(BaseModel):
    name: str
    uri: str
    content_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EnvRef(BaseModel):
    name: str
    value: str | None = None
    source: str | None = None
    required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionWorkspaceRef(BaseModel):
    mode: ExecutionWorkspaceRefMode = "local_path"
    workspace_id: UUID | None = None
    uri: str | None = None
    path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResultSink(BaseModel):
    uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionLimits(BaseModel):
    timeout_seconds: int = 60
    cpu_millis: int | None = None
    memory_mb: int | None = None
    pids_limit: int | None = None
    network: NetworkPolicy = "none"
    workspace_access: WorkspaceAccessMode = "none"


class ToolExecutionBinding(BaseModel):
    backend_kind: ExecutionBackendKind = "docker"
    handler_ref: str = ""
    execution_profile: dict[str, Any] = Field(default_factory=dict)
    trust_level: ToolTrustLevel = "sandboxed"


class SystemToolDefinition(BaseModel):
    tool_id: UUID
    name: str
    description: str
    parameter_contract: ToolParameterContract = Field(default_factory=ToolParameterContract)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    execution: ToolExecutionBinding = Field(default_factory=ToolExecutionBinding)
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    updated_by: UUID
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceTool(BaseModel):
    tool_id: UUID
    name: str
    description: str
    parameter_contract: ToolParameterContract = Field(default_factory=ToolParameterContract)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    execution: ToolExecutionBinding = Field(default_factory=ToolExecutionBinding)
    enabled: bool = True
    attached_by: UUID
    attached_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Membership(BaseModel):
    membership_id: UUID
    workspace_id: UUID
    thread_id: UUID
    participant_id: UUID
    role: str
    permissions: list[str] = Field(default_factory=list)
    joined_at: datetime = Field(default_factory=utcnow)
    left_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryEntry(BaseModel):
    memory_entry_id: UUID
    workspace_id: UUID
    entry_type: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    created_by: UUID
    updated_by: UUID
    version: int = 1
    visibility: Visibility = "workspace"
    linked_thread_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TimelineMessage(BaseModel):
    message_id: UUID
    workspace_id: UUID
    thread_id: UUID
    actor: ActorRef
    visibility: Visibility = "public"
    content: str = ""
    status: MessageStatus = "completed"
    correlation_id: UUID = Field(default_factory=uuid4)
    causation_id: UUID | None = None
    sequence: int
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Task(BaseModel):
    task_id: UUID
    workspace_id: UUID
    thread_id: UUID
    title: str
    description: str | None = None
    status: TaskStatus = "created"
    requested_by: UUID
    claimed_by: UUID | None = None
    visibility: Visibility = "agents_only"
    correlation_id: UUID = Field(default_factory=uuid4)
    causation_id: UUID | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTaskRouting(BaseModel):
    target_system_agent_id: UUID | None = None
    target_participant_id: UUID | None = None
    trigger_message_id: UUID | None = None
    response_visibility: Visibility = "workspace"
    sequence_ceiling: int | None = None
    routing_reason: str | None = None


class Artifact(BaseModel):
    artifact_id: UUID
    workspace_id: UUID
    thread_id: UUID
    task_id: UUID | None = None
    run_id: UUID | None = None
    kind: str
    title: str
    content: dict[str, Any] = Field(default_factory=dict)
    visibility: Visibility = "workspace"
    correlation_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Run(BaseModel):
    run_id: UUID
    workspace_id: UUID
    thread_id: UUID
    task_id: UUID
    participant_id: UUID | None = None
    status: RunStatus = "started"
    output: dict[str, Any] = Field(default_factory=dict)
    correlation_id: UUID = Field(default_factory=uuid4)
    causation_id: UUID | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunStep(BaseModel):
    step_id: UUID
    run_id: UUID
    task_id: UUID
    workspace_id: UUID
    thread_id: UUID
    system_agent_id: UUID
    step_index: int = 0
    kind: RunStepKind = "model"
    status: RunStepStatus = "created"
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    claimed_by_worker: str | None = None
    lease_expires_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    attempt_count: int = 0
    error: str | None = None
    execution_handle: str | None = None
    submitted_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    output_payload: dict[str, Any] = Field(default_factory=dict)
    stdout_ref: ArtifactRef | None = None
    stderr_ref: ArtifactRef | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    exit_code: int | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    tool_call_id: UUID
    run_id: UUID
    run_step_id: UUID
    task_id: UUID
    workspace_id: UUID
    thread_id: UUID
    system_agent_id: UUID
    tool_id: UUID
    tool_name: str
    status: ToolCallStatus = "created"
    arguments: dict[str, Any] = Field(default_factory=dict)
    execution_spec: dict[str, Any] = Field(default_factory=dict)
    claimed_by_worker: str | None = None
    lease_expires_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    attempt_count: int = 0
    error: str | None = None
    execution_handle: str | None = None
    result: ToolCallResult | None = None
    submitted_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionSpec(BaseModel):
    invocation_id: UUID
    kind: ExecutionInvocationKind = "tool_call"
    handler_ref: str
    inline_payload: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    execution_workspace: ExecutionWorkspaceRef | None = Field(
        default=None,
        validation_alias=AliasChoices("execution_workspace", "workspace_ref"),
        serialization_alias="execution_workspace",
    )
    limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    env_refs: list[EnvRef] = Field(default_factory=list)
    result_sink: ResultSink | None = None
    profile: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionHandle(BaseModel):
    backend_kind: ExecutionBackendKind
    invocation_id: UUID
    handle: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    status: ExecutionStatus = "completed"
    output_payload: dict[str, Any] = Field(default_factory=dict)
    stdout_ref: ArtifactRef | None = None
    stderr_ref: ArtifactRef | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    exit_code: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentToolCallDraft(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    summary: str | None = None
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    execution_workspace: ExecutionWorkspaceRef | None = Field(
        default=None,
        validation_alias=AliasChoices("execution_workspace", "workspace_ref"),
        serialization_alias="execution_workspace",
    )
    env_refs: list[EnvRef] = Field(default_factory=list)
    result_sink: ResultSink | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentArtifactDraft(BaseModel):
    kind: str
    title: str
    content: dict[str, Any] = Field(default_factory=dict)
    visibility: Visibility = "workspace"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(BaseModel):
    stop_reason: StopReason = "completed"
    message: str | None = None
    summary: str | None = None
    tool_calls: list[AgentToolCallDraft] = Field(default_factory=list)
    artifacts: list[AgentArtifactDraft] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PresenceState(BaseModel):
    participant_id: UUID
    workspace_id: UUID
    thread_id: UUID
    status: ParticipantStatus
    connection_id: str | None = None
    last_seen_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventEnvelope(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    schema_version: int = 1
    event_type: str
    workspace_id: UUID
    thread_id: UUID | None = None
    actor: ActorRef
    target: TargetRef
    visibility: Visibility = "public"
    correlation_id: UUID = Field(default_factory=uuid4)
    causation_id: UUID | None = None
    sequence: int | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)


class CommandEnvelope(BaseModel):
    command_id: UUID = Field(default_factory=uuid4)
    schema_version: int = 1
    command_type: str
    workspace_id: UUID
    thread_id: UUID | None = None
    actor: ActorRef
    target: TargetRef
    visibility: Visibility = "public"
    correlation_id: UUID = Field(default_factory=uuid4)
    causation_id: UUID | None = None
    timestamp: datetime = Field(default_factory=utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: str | None = None
    actor: ParticipantInput
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeleteWorkspaceRequest(BaseModel):
    actor: ParticipantInput


class DeleteParticipantRequest(BaseModel):
    actor: ParticipantInput


class AssumeParticipantRoleRequest(BaseModel):
    actor: ParticipantInput
    role: str
    description: str | None = None
    capabilities: list[str] = Field(default_factory=list)


class UpsertRoleDefinitionRequest(BaseModel):
    actor: ParticipantInput
    name: str
    definition: str


class CreateSystemToolRequest(BaseModel):
    actor: ParticipantInput
    name: str
    description: str
    parameter_contract: ToolParameterContract = Field(default_factory=ToolParameterContract)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    execution: ToolExecutionBinding = Field(default_factory=ToolExecutionBinding)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateSystemToolRequest(BaseModel):
    actor: ParticipantInput
    name: str | None = None
    description: str | None = None
    parameter_contract: ToolParameterContract | None = None
    input_schema: dict[str, Any] | None = None
    execution: ToolExecutionBinding | None = None
    metadata: dict[str, Any] | None = None


class AttachWorkspaceToolRequest(BaseModel):
    actor: ParticipantInput
    tool_id: UUID
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateWorkspaceToolRequest(BaseModel):
    actor: ParticipantInput
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None


class DeleteWorkspaceToolRequest(BaseModel):
    actor: ParticipantInput


class CreateAgentParticipantRequest(BaseModel):
    actor: ParticipantInput
    agent_id: UUID


class UpdateAgentParticipantRequest(BaseModel):
    actor: ParticipantInput
    status: ParticipantStatus | None = None
    visibility_scope: Visibility | None = None
    metadata: dict[str, Any] | None = None


class CreateSystemAgentRequest(BaseModel):
    actor: ParticipantInput
    display_name: str
    description: str
    role: str
    capabilities: list[str] = Field(default_factory=list)
    endpoint: AgentEndpoint
    system_prompt: str
    interaction_contract: AgentInteractionContract = Field(
        default_factory=AgentInteractionContract
    )
    definition: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateSystemAgentRequest(BaseModel):
    actor: ParticipantInput
    display_name: str | None = None
    description: str | None = None
    role: str | None = None
    capabilities: list[str] | None = None
    endpoint: AgentEndpoint | None = None
    system_prompt: str | None = None
    interaction_contract: AgentInteractionContract | None = None
    definition: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class CreateThreadRequest(BaseModel):
    title: str
    actor: ParticipantInput
    parent_thread_id: UUID | None = None
    previous_thread_id: UUID | None = None
    related_thread_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateMessageRequest(BaseModel):
    actor: ParticipantInput
    content: str
    visibility: Visibility = "public"
    create_task: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateMemoryEntryRequest(BaseModel):
    actor: ParticipantInput
    entry_type: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    visibility: Visibility = "workspace"
    linked_thread_ids: list[UUID] = Field(default_factory=list)


class UpdateMemoryEntryRequest(BaseModel):
    actor: ParticipantInput
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    visibility: Visibility | None = None
    linked_thread_ids: list[UUID] | None = None


class WorkspaceDetail(BaseModel):
    workspace: Workspace
    participants: list[ParticipantProfile] = Field(default_factory=list)
    role_definitions: list[RoleDefinition] = Field(default_factory=list)
    tools: list[WorkspaceTool] = Field(default_factory=list)


class ThreadDetail(BaseModel):
    thread: Thread
    memberships: list[Membership] = Field(default_factory=list)


class TimelinePage(BaseModel):
    thread_id: UUID
    messages: list[TimelineMessage] = Field(default_factory=list)


class AgentExecutionContext(BaseModel):
    workspace: Workspace
    thread: Thread
    task: Task
    run: Run
    run_step: RunStep | None = None
    routing: AgentTaskRouting
    system_agent: AgentDefinition
    participant: ParticipantProfile
    participants: list[ParticipantProfile] = Field(default_factory=list)
    role_definitions: list[RoleDefinition] = Field(default_factory=list)
    workspace_tools: list[WorkspaceTool] = Field(default_factory=list)
    messages: list[TimelineMessage] = Field(default_factory=list)
    memory_entries: list[MemoryEntry] = Field(default_factory=list)
    trigger_message: TimelineMessage | None = None
    sequence_ceiling: int = 0
    thread_reply_contract: AgentInteractionContract | None = None
    tool_results: list[ToolCall] = Field(default_factory=list)


class ApiKeyCreate(BaseModel):
    label: str
    ttl_seconds: int | None = None


class ApiKeyInfo(BaseModel):
    key_id: str
    label: str
    created_at: datetime
    expires_at: datetime | None = None
    raw_key: str | None = None


class ServiceStatus(BaseModel):
    name: str
    healthy: bool
    latency_ms: int | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "down"]
    services: list[ServiceStatus]
    timestamp: datetime = Field(default_factory=utcnow)
