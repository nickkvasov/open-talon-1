from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

Visibility = Literal["public", "workspace", "agents_only", "private"]
ParticipantType = Literal["user", "agent"]
ParticipantStatus = Literal["active", "idle", "busy", "offline"]
ThreadState = Literal["active", "paused", "resolved", "archived"]
MessageStatus = Literal["draft", "streaming", "completed", "failed"]
TaskStatus = Literal["created", "claimed", "released", "completed", "failed"]
RunStatus = Literal["started", "progressing", "completed", "failed"]
AgentEndpointKind = Literal["local", "system", "remote"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ActorRef(BaseModel):
    type: ParticipantType
    id: UUID


class TargetRef(BaseModel):
    type: Literal["workspace", "thread", "message", "task", "artifact", "memory_entry", "run", "participant"]
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


class AgentDefinition(BaseModel):
    agent_id: UUID
    display_name: str
    description: str
    role: str
    capabilities: list[str] = Field(default_factory=list)
    endpoint: AgentEndpoint
    system_prompt: str
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


class AssumeParticipantRoleRequest(BaseModel):
    actor: ParticipantInput
    role: str
    description: str | None = None
    capabilities: list[str] = Field(default_factory=list)


class UpsertRoleDefinitionRequest(BaseModel):
    actor: ParticipantInput
    name: str
    definition: str


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


class ThreadDetail(BaseModel):
    thread: Thread
    memberships: list[Membership] = Field(default_factory=list)


class TimelinePage(BaseModel):
    thread_id: UUID
    messages: list[TimelineMessage] = Field(default_factory=list)


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
