from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import (
    AgentDefinition,
    AgentIdentity,
    AgentIdentityProvisioningResult,
    AgentExecutionContext,
    IamRoleDefinition,
    Artifact,
    AssetLink,
    EventEnvelope,
    GitRepository,
    InteractionRequestDetail,
    Library,
    LibraryItem,
    LibraryWorkspaceAttachment,
    LlmProviderDefinition,
    MemoryEntry,
    MemoryProviderDefinition,
    MethodologyBlueprintDetail,
    MethodicExecutionDetail,
    MethodicResourceRequest,
    McpServerDefinition,
    Organization,
    OrganizationMembership,
    ParticipantProfile,
    Project,
    RetrievalContextPack,
    RetrievalCorpus,
    RetrievalIngestionJob,
    RetrievalProfile,
    RetrievalRun,
    RetrievalSearchHit,
    RetrievalSearchResponse,
    RetrievalSource,
    RetrievalSourceVersion,
    ResearchDossier,
    ResearchDossierSource,
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
    ToolGenerationRequestDetail,
    ToolGenerationRevision,
    Workspace,
    WorkspaceAsset,
    WorkspaceAssetVersion,
    WorkspaceDetail,
    WorkspaceMcpServer,
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
class ProjectCommandResult(CommandResult):
    project: Project | None = None


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
class IamRoleCommandResult(CommandResult):
    role: IamRoleDefinition | None = None


@dataclass
class AgentIdentityCommandResult(CommandResult):
    identity: AgentIdentity | None = None
    provisioning: AgentIdentityProvisioningResult | None = None


@dataclass
class LlmProviderCommandResult(CommandResult):
    provider: LlmProviderDefinition | None = None


@dataclass
class MemoryProviderCommandResult(CommandResult):
    provider: MemoryProviderDefinition | None = None


@dataclass
class McpServerCommandResult(CommandResult):
    server: McpServerDefinition | None = None
    binding: WorkspaceMcpServer | None = None


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
class LibraryCommandResult(CommandResult):
    library: Library | None = None
    item: LibraryItem | None = None
    attachment: LibraryWorkspaceAttachment | None = None
    jobs: list[RetrievalIngestionJob] = field(default_factory=list)


@dataclass
class RetrievalCommandResult(CommandResult):
    corpus: RetrievalCorpus | None = None
    profile: RetrievalProfile | None = None
    source: RetrievalSource | None = None
    source_version: RetrievalSourceVersion | None = None
    job: RetrievalIngestionJob | None = None
    run: RetrievalRun | None = None
    hits: list[RetrievalSearchHit] = field(default_factory=list)
    context_pack: RetrievalContextPack | None = None
    search_response: RetrievalSearchResponse | None = None


@dataclass
class MethodicExecutionCommandResult(CommandResult):
    detail: MethodicExecutionDetail | None = None
    resource_request: MethodicResourceRequest | None = None


@dataclass
class MethodologyBlueprintCommandResult(CommandResult):
    detail: MethodologyBlueprintDetail | None = None
    dossier: ResearchDossier | None = None
    source: ResearchDossierSource | None = None


@dataclass
class ToolGenerationRequestCommandResult(CommandResult):
    detail: ToolGenerationRequestDetail | None = None
    revision: ToolGenerationRevision | None = None
    message: TimelineMessage | None = None


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
    "AgentIdentityCommandResult",
    "CommandResult",
    "GitRepositoryCommandResult",
    "IamRoleCommandResult",
    "InteractionRequestCommandResult",
    "LeaseReconciliationResult",
    "LibraryCommandResult",
    "LlmProviderCommandResult",
    "MemoryCommandResult",
    "MemoryProviderCommandResult",
    "MethodicExecutionCommandResult",
    "McpServerCommandResult",
    "MessageCommandResult",
    "OrganizationCommandResult",
    "OrganizationMembershipCommandResult",
    "ParticipantCommandResult",
    "RetrievalCommandResult",
    "RoleDefinitionCommandResult",
    "RunCommandResult",
    "RunStepCommandResult",
    "SystemToolCommandResult",
    "TaskCommandResult",
    "ThreadCommandResult",
    "ToolCallCommandResult",
    "ToolGenerationRequestCommandResult",
    "WorkspaceAssetCommandResult",
    "WorkspaceCommandResult",
    "WorkspaceToolCommandResult",
]
