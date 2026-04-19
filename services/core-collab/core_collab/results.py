from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import (
    AgentDefinition,
    AgentExecutionContext,
    Artifact,
    AssetLink,
    EventEnvelope,
    GitRepository,
    InteractionRequestDetail,
    LlmProviderDefinition,
    MemoryEntry,
    MemoryProviderDefinition,
    Organization,
    OrganizationMembership,
    ParticipantProfile,
    ResolvedAssetBinding,
    RoleDefinition,
    Run,
    RunStep,
    SystemToolDefinition,
    Task,
    Thread,
    ThreadDetail,
    TimelineMessage,
    ToolCall,
    Workspace,
    WorkspaceAsset,
    WorkspaceAssetVersion,
    WorkspaceDetail,
    WorkspaceTool,
)


@dataclass
class CommandResult:
    events: list[EventEnvelope] = field(default_factory=list)


@dataclass
class WorkspaceCommandResult(CommandResult):
    workspace: Workspace | None = None
    detail: WorkspaceDetail | None = None


@dataclass
class OrganizationCommandResult(CommandResult):
    organization: Organization | None = None


@dataclass
class OrganizationMembershipCommandResult(CommandResult):
    membership: OrganizationMembership | None = None


@dataclass
class ThreadCommandResult(CommandResult):
    thread: Thread | None = None
    detail: ThreadDetail | None = None


@dataclass
class MessageCommandResult(CommandResult):
    message: TimelineMessage | None = None


@dataclass
class InteractionRequestCommandResult(CommandResult):
    detail: InteractionRequestDetail | None = None
    details: list[InteractionRequestDetail] = field(default_factory=list)
    message: TimelineMessage | None = None
    messages: list[TimelineMessage] = field(default_factory=list)
    answer_message: TimelineMessage | None = None
    resumed_task: Task | None = None


@dataclass
class MemoryCommandResult(CommandResult):
    entry: MemoryEntry | None = None


@dataclass
class ParticipantCommandResult(CommandResult):
    participant: ParticipantProfile | None = None


@dataclass
class RoleDefinitionCommandResult(CommandResult):
    role_definition: RoleDefinition | None = None


@dataclass
class WorkspaceToolCommandResult(CommandResult):
    tool: WorkspaceTool | None = None


@dataclass
class SystemToolCommandResult(CommandResult):
    tool: SystemToolDefinition | None = None


@dataclass
class AgentDefinitionCommandResult(CommandResult):
    agent: AgentDefinition | None = None


@dataclass
class LlmProviderCommandResult(CommandResult):
    provider: LlmProviderDefinition | None = None


@dataclass
class MemoryProviderCommandResult(CommandResult):
    provider: MemoryProviderDefinition | None = None


@dataclass
class GitRepositoryCommandResult(CommandResult):
    repository: GitRepository | None = None


@dataclass
class WorkspaceAssetCommandResult(CommandResult):
    asset: WorkspaceAsset | None = None
    version: WorkspaceAssetVersion | None = None
    link: AssetLink | None = None
    bindings: list[ResolvedAssetBinding] = field(default_factory=list)


@dataclass
class TaskCommandResult(CommandResult):
    task: Task | None = None
    run: Run | None = None
    context: AgentExecutionContext | None = None


@dataclass
class RunStepCommandResult(CommandResult):
    step: RunStep | None = None
    run: Run | None = None
    task: Task | None = None
    context: AgentExecutionContext | None = None


@dataclass
class ToolCallCommandResult(CommandResult):
    tool_call: ToolCall | None = None
    step: RunStep | None = None
    run: Run | None = None
    task: Task | None = None


@dataclass
class RunCommandResult(CommandResult):
    run: Run | None = None
    task: Task | None = None
    message: TimelineMessage | None = None
    artifacts: list[Artifact] = field(default_factory=list)


@dataclass
class LeaseReconciliationResult(CommandResult):
    run_steps: list[RunStep] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)


__all__ = [
    "AgentDefinitionCommandResult",
    "CommandResult",
    "GitRepositoryCommandResult",
    "InteractionRequestCommandResult",
    "LeaseReconciliationResult",
    "LlmProviderCommandResult",
    "MemoryCommandResult",
    "MemoryProviderCommandResult",
    "MessageCommandResult",
    "OrganizationCommandResult",
    "OrganizationMembershipCommandResult",
    "ParticipantCommandResult",
    "RoleDefinitionCommandResult",
    "RunCommandResult",
    "RunStepCommandResult",
    "SystemToolCommandResult",
    "TaskCommandResult",
    "ThreadCommandResult",
    "ToolCallCommandResult",
    "WorkspaceAssetCommandResult",
    "WorkspaceCommandResult",
    "WorkspaceToolCommandResult",
]
