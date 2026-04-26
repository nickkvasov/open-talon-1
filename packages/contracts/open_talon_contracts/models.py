from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from .llm_engines import LlmEngineEndpointKind, LlmEngineLocality

Visibility = Literal["public", "workspace", "agents_only", "private"]
ParticipantType = Literal["user", "agent"]
ParticipantStatus = Literal["active", "idle", "busy", "offline"]
ThreadState = Literal["active", "paused", "resolved", "archived"]
MessageStatus = Literal["draft", "streaming", "completed", "failed"]
CommunicationLogKind = Literal["message", "interaction_request", "interaction_answer"]
InteractionRequestStatus = Literal["open", "completed", "cancelled", "timed_out"]
InteractionTargetStatus = Literal["pending", "acknowledged", "answered", "dismissed"]
ParticipantSelectorType = Literal["participant", "role", "capability"]
CompletionRuleMode = Literal[
    "all_targets",
    "minimum_answers",
    "one_per_selector_bucket",
    "custom_targets",
]
MemoryScope = Literal["run", "thread", "workspace"]
MemoryState = Literal["scratch", "candidate", "confirmed", "archived"]
TaskStatus = Literal["created", "claimed", "released", "completed", "failed"]
RunStatus = Literal["started", "progressing", "completed", "failed"]
RunStepStatus = Literal["created", "claimed", "waiting_tools", "completed", "failed"]
RunStepKind = Literal["model"]
ToolCallStatus = Literal["created", "claimed", "completed", "failed"]
AgentEndpointKind = Literal["local", "system", "remote"]
ExecutionBackendKind = Literal["docker", "local_process", "mcp"]
ToolTrustLevel = Literal["sandboxed", "trusted"]
McpTransportKind = Literal["stdio", "streamable_http", "sse"]
ExecutionWorkspaceRefMode = Literal["local_path"]
NetworkPolicy = Literal["none", "full"]
WorkspaceAccessMode = Literal["none", "read_only", "read_write"]
ExecutionInvocationKind = Literal["tool_call"]
ExecutionStatus = Literal["queued", "running", "completed", "failed", "cancelled", "timed_out"]
RegistryScope = Literal["global", "organization"]
AssetScope = Literal["global", "organization", "workspace"]
AssetStorageBackend = Literal["minio"]
AssetTargetType = Literal["system_agent", "system_tool", "workspace", "workspace_tool"]
AuditScopeType = Literal["global", "organization", "workspace", "thread"]
AuditActorType = Literal["user", "agent", "system", "api_key", "unknown"]
AuditOutcome = Literal["success", "failure", "denied", "error"]
AuditPayloadMode = Literal["metadata_only"]
OrganizationRole = Literal["owner", "admin", "member"]
IamScope = Literal["global", "organization"]
IamSubjectKind = Literal["human", "agent"]
AgentIdentityStatus = Literal["active", "disabled"]
PrincipalType = Literal["human", "agent", "api_key"]
ToolGenerationRequestStatus = Literal[
    "submitted",
    "clarification_needed",
    "drafting",
    "validating",
    "pending_approval",
    "verifying_registry_pull",
    "published",
    "rejected",
    "failed",
]
ToolGenerationRevisionStatus = Literal[
    "drafting",
    "validating",
    "pending_approval",
    "verifying_registry_pull",
    "approved",
    "rejected",
    "failed",
]
GeneratedToolValidationStatus = Literal["passed", "failed", "warning"]
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
HarnessRulePriority = Literal["critical", "high", "normal"]
HarnessRuleScope = Literal[
    "planning",
    "tool_use",
    "validation",
    "communication",
    "completion",
    "security",
]
AgentCompactionStrategy = Literal[
    "full_context",
    "recent_window",
    "rolling_summary",
    "summary_plus_retrieval",
]
AgentCompactionOverflowBehavior = Literal["auto_fallback"]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


_ORGANIZATION_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PROJECT_SLUG_PATTERN = _ORGANIZATION_SLUG_PATTERN


def normalize_organization_slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not normalized:
        raise ValueError("Organization slug must contain at least one letter or number")
    if not _ORGANIZATION_SLUG_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Organization slug must use lowercase letters, numbers, and single hyphens"
        )
    return normalized


def normalize_project_slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    if not normalized:
        raise ValueError("Project slug must contain at least one letter or number")
    if not _PROJECT_SLUG_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Project slug must use lowercase letters, numbers, and single hyphens"
        )
    return normalized


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
        "interaction_request",
        "interaction_request_target",
        "interaction_answer",
        "tool_generation_request",
        "tool_generation_revision",
    ]
    id: UUID


class ParticipantInput(BaseModel):
    participant_id: UUID
    participant_type: ParticipantType
    user_id: UUID | None = None
    display_name: str
    description: str | None = None
    roles: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    iam_permissions: list[str] = Field(default_factory=list, exclude=True)
    visibility_scope: Visibility = "workspace"


class AgentEndpoint(BaseModel):
    kind: AgentEndpointKind
    url: str | None = None
    model: str | None = None
    engine_id: str | None = None
    provider: str | None = None


class WorkspaceMethodology(BaseModel):
    ontology: str | None = None
    axiology: str | None = None
    epistemology: str | None = None
    principles: list[str] = Field(default_factory=list)


class WorkspaceMethodicStep(BaseModel):
    instruction: str
    recommended_tool_patterns: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)
    verification: list[str] = Field(default_factory=list)


class WorkspaceMethodic(BaseModel):
    name: str
    goal: str
    applicability: str | None = None
    steps: list[WorkspaceMethodicStep] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class HarnessExecutionRule(BaseModel):
    name: str
    instruction: str
    priority: HarnessRulePriority = "normal"
    scope: HarnessRuleScope = "planning"


class WorkspaceHarness(BaseModel):
    version: int = 1
    summary: str | None = None
    methodology: WorkspaceMethodology | None = None
    methodics: list[WorkspaceMethodic] = Field(default_factory=list)
    execution_rules: list[HarnessExecutionRule] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentPlanningPolicy(BaseModel):
    plan_before_act: bool = True
    incremental_execution: bool = True
    one_goal_at_a_time: bool = True
    explicit_uncertainty: bool = True
    guidance: list[str] = Field(default_factory=list)


class AgentToolUsePolicy(BaseModel):
    selection_principles: list[str] = Field(default_factory=list)
    read_before_write: bool = True
    inspect_schema_before_use: bool = True
    prefer_existing_workspace_tools: bool = True
    cite_tool_results_in_reasoning: bool = True
    verify_side_effects_after_mutation: bool = True
    fallback_when_no_tool_fits: str | None = None


class AgentMemoryPolicy(BaseModel):
    use_run_memory: bool = True
    use_thread_memory: bool = True
    use_workspace_memory: bool = True


class AgentCompactionPolicy(BaseModel):
    enabled: bool = True
    strategy: AgentCompactionStrategy = "full_context"
    overflow_behavior: AgentCompactionOverflowBehavior = "auto_fallback"
    max_estimated_input_tokens: int = Field(default=12_000, ge=1)
    recent_message_count: int = Field(default=12, ge=1)
    min_recent_message_count: int = Field(default=4, ge=1)
    max_run_memory_entries: int = Field(default=6, ge=0)
    max_thread_memory_entries: int = Field(default=6, ge=0)
    max_workspace_memory_entries: int = Field(default=6, ge=0)
    summary_max_chars: int = Field(default=3_000, ge=256)
    retrieval_limit: int = Field(default=5, ge=1)
    retrieval_provider_key: str | None = None


class AgentCollaborationPolicy(BaseModel):
    ask_user_when: list[str] = Field(default_factory=list)
    escalate_when: list[str] = Field(default_factory=list)
    delegation_guidance: list[str] = Field(default_factory=list)
    handoff_guidance: list[str] = Field(default_factory=list)


class AgentValidationPolicy(BaseModel):
    required_checks: list[str] = Field(default_factory=list)
    require_evidence_for_claims: bool = True
    require_tool_results_for_completion: bool = False
    require_tests_before_done: bool = False


class AgentStopPolicy(BaseModel):
    completion_conditions: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=list)
    max_turns: int | None = None


class AgentHarness(BaseModel):
    version: int = 1
    summary: str | None = None
    operating_principles: list[str] = Field(default_factory=list)
    planning: AgentPlanningPolicy = Field(default_factory=AgentPlanningPolicy)
    tool_use_policy: AgentToolUsePolicy = Field(default_factory=AgentToolUsePolicy)
    memory_policy: AgentMemoryPolicy = Field(default_factory=AgentMemoryPolicy)
    compaction_policy: AgentCompactionPolicy = Field(
        default_factory=AgentCompactionPolicy
    )
    collaboration_policy: AgentCollaborationPolicy = Field(
        default_factory=AgentCollaborationPolicy
    )
    validation_policy: AgentValidationPolicy = Field(
        default_factory=AgentValidationPolicy
    )
    stop_policy: AgentStopPolicy = Field(default_factory=AgentStopPolicy)
    skill_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentConfiguration(BaseModel):
    endpoint: AgentEndpoint
    system_prompt: str
    harness: AgentHarness | None = None
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
    agent_key: str | None = None
    scope: RegistryScope = "global"
    organization_id: UUID | None = None
    active_agent_version_id: UUID | None = None
    display_name: str
    description: str
    role: str
    capabilities: list[str] = Field(default_factory=list)
    endpoint: AgentEndpoint
    system_prompt: str
    harness: AgentHarness | None = None
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
    organization_id: UUID | None = None
    project_id: UUID | None = None
    name: str
    description: str | None = None
    owner_user_id: UUID | None = None
    harness: WorkspaceHarness | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Organization(BaseModel):
    organization_id: UUID
    slug: str
    name: str
    description: str | None = None
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Project(BaseModel):
    project_id: UUID
    organization_id: UUID
    slug: str
    name: str
    description: str | None = None
    created_by: UUID
    creator_user_id: UUID | None = None
    creator_system_agent_id: UUID | None = None
    owner_user_id: UUID | None = None
    owner_system_agent_id: UUID | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


ProjectAccessRole = Literal["creator", "owner", "editor", "viewer"]
ProjectSubjectType = Literal["user", "agent"]


class ProjectSubjectRef(BaseModel):
    user_id: UUID | None = None
    system_agent_id: UUID | None = None

    @model_validator(mode="after")
    def _validate_single_subject(self) -> "ProjectSubjectRef":
        if (self.user_id is None) == (self.system_agent_id is None):
            raise ValueError("Exactly one of user_id or system_agent_id is required")
        return self


class ProjectAccessBinding(BaseModel):
    project_id: UUID
    subject_type: ProjectSubjectType
    user_id: UUID | None = None
    system_agent_id: UUID | None = None
    role: ProjectAccessRole
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_subject(self) -> "ProjectAccessBinding":
        if self.subject_type == "user":
            if self.user_id is None or self.system_agent_id is not None:
                raise ValueError("User project access requires user_id only")
        if self.subject_type == "agent":
            if self.system_agent_id is None or self.user_id is not None:
                raise ValueError("Agent project access requires system_agent_id only")
        return self


class OrganizationMembership(BaseModel):
    organization_id: UUID
    user_id: UUID
    role: OrganizationRole = "member"
    joined_at: datetime = Field(default_factory=utcnow)
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


class IamPermission(BaseModel):
    name: str
    scope_type: Literal["identity", "workspace"]
    description: str


class IamRoleDefinition(BaseModel):
    role_id: UUID
    scope: IamScope
    subject_kind: IamSubjectKind
    organization_id: UUID | None = None
    name: str
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class HumanRoleBinding(BaseModel):
    user_id: UUID
    role_id: UUID
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentIdentity(BaseModel):
    agent_identity_id: UUID
    system_agent_id: UUID
    scope: IamScope
    organization_id: UUID | None = None
    provider_key: str
    issuer: str
    external_subject: str | None = None
    client_id: str
    status: AgentIdentityStatus = "active"
    secret_ref: dict[str, Any] = Field(default_factory=dict)
    last_authenticated_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRoleBinding(BaseModel):
    agent_identity_id: UUID
    role_id: UUID
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentIdentityProvisioningResult(BaseModel):
    identity: AgentIdentity
    client_secret: str
    issuer: str
    token_endpoint: str


class PrincipalContext(BaseModel):
    principal_type: PrincipalType
    auth_method: Literal["oidc", "api_key"]
    user_id: UUID | None = None
    agent_identity_id: UUID | None = None
    system_agent_id: UUID | None = None
    issuer: str | None = None
    subject: str | None = None
    client_id: str | None = None
    provider_key: str | None = None
    platform_admin: bool = False
    claims: dict[str, Any] = Field(default_factory=dict)


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
    scope: RegistryScope = "global"
    organization_id: UUID | None = None
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


class LlmProviderDefinition(BaseModel):
    provider_id: UUID
    scope: RegistryScope = "global"
    organization_id: UUID | None = None
    engine_id: str
    display_name: str
    description: str
    provider: str
    endpoint_kind: LlmEngineEndpointKind = "remote"
    url: str | None = None
    default_model: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    locality: LlmEngineLocality = "cloud"
    priority: int = 100
    enabled: bool = True
    secret_config: dict[str, Any] = Field(default_factory=dict)
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    updated_by: UUID
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LlmProviderHealthCheck(BaseModel):
    name: str
    status: Literal["ok", "warn", "fail"]
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LlmProviderHealthReport(BaseModel):
    provider_id: UUID
    engine_id: str
    status: Literal["healthy", "degraded", "unhealthy"]
    checked_at: datetime = Field(default_factory=utcnow)
    checks: list[LlmProviderHealthCheck] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryProviderDefinition(BaseModel):
    provider_id: UUID
    scope: RegistryScope = "global"
    organization_id: UUID | None = None
    provider_key: str
    display_name: str
    description: str
    provider: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    secret_config: dict[str, Any] = Field(default_factory=dict)
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    updated_by: UUID
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpServerDefinition(BaseModel):
    server_id: UUID
    scope: RegistryScope = "global"
    organization_id: UUID | None = None
    server_key: str
    display_name: str
    description: str
    transport_kind: McpTransportKind = "streamable_http"
    config: dict[str, Any] = Field(default_factory=dict)
    secret_config: dict[str, Any] = Field(default_factory=dict)
    trust_level: ToolTrustLevel = "sandboxed"
    enabled: bool = True
    last_sync_status: str | None = None
    last_sync_error: str | None = None
    last_synced_at: datetime | None = None
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    updated_by: UUID
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpToolDefinition(BaseModel):
    server_id: UUID
    tool_name: str
    display_name: str | None = None
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    capability_hash: str = ""
    discovered_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpResourceDefinition(BaseModel):
    server_id: UUID
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str | None = None
    capability_hash: str = ""
    discovered_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpPromptDefinition(BaseModel):
    server_id: UUID
    prompt_name: str
    description: str = ""
    arguments_schema: dict[str, Any] = Field(default_factory=dict)
    capability_hash: str = ""
    discovered_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceMcpServer(BaseModel):
    server_id: UUID
    server_key: str
    display_name: str
    description: str
    transport_kind: McpTransportKind = "streamable_http"
    trust_level: ToolTrustLevel = "sandboxed"
    server_enabled: bool = True
    enabled: bool = True
    tools_enabled: bool = True
    resources_enabled: bool = False
    prompts_enabled: bool = False
    sampling_enabled: bool = False
    name_prefix: str = ""
    tool_allowlist: list[str] = Field(default_factory=list)
    tool_denylist: list[str] = Field(default_factory=list)
    resource_allowlist: list[str] = Field(default_factory=list)
    prompt_allowlist: list[str] = Field(default_factory=list)
    attached_by: UUID
    attached_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentInternalMcpServer(BaseModel):
    system_agent_id: UUID
    server_id: UUID
    server_key: str
    display_name: str
    description: str
    transport_kind: McpTransportKind = "streamable_http"
    trust_level: ToolTrustLevel = "sandboxed"
    server_enabled: bool = True
    enabled: bool = True
    tools_enabled: bool = True
    resources_enabled: bool = False
    prompts_enabled: bool = False
    sampling_enabled: bool = False
    name_prefix: str = ""
    tool_allowlist: list[str] = Field(default_factory=list)
    tool_denylist: list[str] = Field(default_factory=list)
    resource_allowlist: list[str] = Field(default_factory=list)
    prompt_allowlist: list[str] = Field(default_factory=list)
    attached_by: UUID
    attached_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceMcpCapability(BaseModel):
    server_id: UUID
    server_key: str
    server_display_name: str
    exposed_name: str
    remote_name: str
    description: str = ""
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceMcpTool(WorkspaceMcpCapability):
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class WorkspaceMcpResource(WorkspaceMcpCapability):
    uri: str
    mime_type: str | None = None


class WorkspaceMcpPrompt(WorkspaceMcpCapability):
    arguments_schema: dict[str, Any] = Field(default_factory=dict)


class MemoryProviderHealthCheck(BaseModel):
    name: str
    status: Literal["ok", "warn", "fail"]
    detail: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryProviderHealthReport(BaseModel):
    provider_id: UUID
    provider_key: str
    status: Literal["healthy", "degraded", "unhealthy"]
    checked_at: datetime = Field(default_factory=utcnow)
    checks: list[MemoryProviderHealthCheck] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryProviderRecord(BaseModel):
    provider_record_id: UUID
    memory_entry_id: UUID
    provider_id: UUID
    external_id: str | None = None
    status: str = "pending"
    last_synced_at: datetime | None = None
    last_error: str | None = None
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


class GeneratedToolSmokeTest(BaseModel):
    command: list[str] = Field(default_factory=list)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    expected_output_schema: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeneratedToolValidationCheck(BaseModel):
    name: str
    status: GeneratedToolValidationStatus
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeneratedToolValidationReport(BaseModel):
    status: GeneratedToolValidationStatus = "passed"
    summary: str | None = None
    checks: list[GeneratedToolValidationCheck] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeneratedToolManifest(BaseModel):
    name: str
    description: str
    parameter_contract: ToolParameterContract = Field(default_factory=ToolParameterContract)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    execution: ToolExecutionBinding = Field(default_factory=ToolExecutionBinding)
    build_context_path: str
    smoke_test: GeneratedToolSmokeTest | None = None
    trust_rationale: str | None = None
    dependency_summary: list[str] = Field(default_factory=list)
    network_access: NetworkPolicy = "none"
    workspace_access: WorkspaceAccessMode = "none"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolGenerationRequest(BaseModel):
    request_id: UUID
    organization_id: UUID
    workspace_id: UUID
    thread_id: UUID
    requester_participant_id: UUID
    requester_message_id: UUID | None = None
    target_system_agent_id: UUID
    requested_scope: RegistryScope = "global"
    status: ToolGenerationRequestStatus = "submitted"
    target_tool_name: str | None = None
    summary: str | None = None
    final_tool_id: UUID | None = None
    latest_revision_id: UUID | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    rejected_by: UUID | None = None
    rejected_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolGenerationRevision(BaseModel):
    revision_id: UUID
    request_id: UUID
    revision_number: int
    status: ToolGenerationRevisionStatus = "drafting"
    manifest: GeneratedToolManifest
    validation_report: GeneratedToolValidationReport | None = None
    source_asset_id: UUID | None = None
    source_asset_version_id: UUID | None = None
    manifest_asset_id: UUID | None = None
    manifest_asset_version_id: UUID | None = None
    report_asset_id: UUID | None = None
    report_asset_version_id: UUID | None = None
    image_ref: str | None = None
    image_digest: str | None = None
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolGenerationRequestDetail(BaseModel):
    request: ToolGenerationRequest
    revisions: list[ToolGenerationRevision] = Field(default_factory=list)


class AgentInternalToolBinding(BaseModel):
    system_agent_id: UUID
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


class GitRepository(BaseModel):
    repo_id: UUID
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    scope: AssetScope = "global"
    name: str
    forgejo_url: str | None = None
    clone_url: str | None = None
    local_path: str
    default_branch: str | None = None
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceAsset(BaseModel):
    asset_id: UUID
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    scope: AssetScope = "global"
    asset_type: str
    logical_name: str
    logical_path: str | None = None
    title: str
    description: str | None = None
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceAssetVersion(BaseModel):
    asset_version_id: UUID
    asset_id: UUID
    version: int
    source_kind: str
    git_repository_id: UUID | None = None
    git_revision: str | None = None
    git_path: str | None = None
    storage_backend: AssetStorageBackend = "minio"
    bucket: str
    object_key: str
    content_type: str | None = None
    size_bytes: int = 0
    sha256: str
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentDefinitionVersion(BaseModel):
    agent_version_id: UUID
    agent_id: UUID
    version: int
    scope: RegistryScope = "global"
    organization_id: UUID | None = None
    agent_key: str
    git_repository_id: UUID | None = None
    git_commit_sha: str
    bundle_path: str
    manifest_sha256: str
    compiled_definition: dict[str, Any] = Field(default_factory=dict)
    prompt_asset_id: UUID | None = None
    prompt_asset_version_id: UUID | None = None
    skill_asset_refs: list[dict[str, Any]] = Field(default_factory=list)
    published_by: UUID
    published_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetLink(BaseModel):
    link_id: UUID
    asset_id: UUID
    asset_version_id: UUID
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    target_type: AssetTargetType
    target_id: UUID
    purpose: str
    active: bool = True
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResolvedAssetBinding(BaseModel):
    purpose: str
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    asset: WorkspaceAsset
    version: WorkspaceAssetVersion
    link: AssetLink


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
    scope: MemoryScope
    state: MemoryState = "confirmed"
    workspace_id: UUID
    thread_id: UUID | None = None
    run_id: UUID | None = None
    entry_type: str
    content: str
    summary: str | None = None
    source: str | None = None
    created_by: UUID
    updated_by: UUID
    confirmed_by: UUID | None = None
    confirmed_at: datetime | None = None
    version: int = 1
    visibility: Visibility = "workspace"
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class MemorySearchHit(BaseModel):
    entry: MemoryEntry
    score: float | None = None
    relations: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemorySearchResponse(BaseModel):
    query: str
    provider: str
    results: list[MemorySearchHit] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class ParticipantSelector(BaseModel):
    type: ParticipantSelectorType
    value: str
    participant_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompletionRule(BaseModel):
    mode: CompletionRuleMode = "all_targets"
    minimum_answers: int | None = None
    target_participant_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InteractionQuestion(BaseModel):
    question_id: UUID
    request_id: UUID
    prompt: str
    kind: str | None = None
    expected_format: str | None = None
    order: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class InteractionRequestTarget(BaseModel):
    target_id: UUID
    request_id: UUID
    participant_id: UUID | None = None
    selector_type: ParticipantSelectorType | None = None
    selector_value: str | None = None
    selection_source: str = "explicit"
    score: float | None = None
    status: InteractionTargetStatus = "pending"
    answered_message_id: UUID | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InteractionAnswer(BaseModel):
    answer_id: UUID
    request_id: UUID
    participant_id: UUID
    message_id: UUID
    question_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InteractionRequest(BaseModel):
    request_id: UUID
    workspace_id: UUID
    thread_id: UUID
    status: InteractionRequestStatus = "open"
    requester_participant_id: UUID
    requester_message_id: UUID | None = None
    requester_run_id: UUID | None = None
    requester_task_id: UUID | None = None
    title: str
    summary: str | None = None
    completion_rule: CompletionRule = Field(default_factory=CompletionRule)
    timeout_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InteractionRequestDetail(BaseModel):
    request: InteractionRequest
    questions: list[InteractionQuestion] = Field(default_factory=list)
    targets: list[InteractionRequestTarget] = Field(default_factory=list)
    answers: list[InteractionAnswer] = Field(default_factory=list)


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
    next_retry_at: datetime | None = None
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
    tool_id: UUID | None = None
    tool_name: str
    status: ToolCallStatus = "created"
    arguments: dict[str, Any] = Field(default_factory=dict)
    execution_spec: dict[str, Any] = Field(default_factory=dict)
    claimed_by_worker: str | None = None
    lease_expires_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    next_retry_at: datetime | None = None
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


class InteractionQuestionDraft(BaseModel):
    prompt: str
    kind: str | None = None
    expected_format: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InteractionRequestDraft(BaseModel):
    title: str
    summary: str | None = None
    questions: list[InteractionQuestionDraft] = Field(default_factory=list)
    selectors: list[ParticipantSelector] = Field(default_factory=list)
    target_participant_ids: list[UUID] = Field(default_factory=list)
    completion_rule: CompletionRule | None = None
    timeout_at: datetime | None = None
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
    interaction_requests: list[InteractionRequestDraft] = Field(default_factory=list)
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


class AuditEventDraft(BaseModel):
    audit_event_id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=utcnow)
    recorded_at: datetime = Field(default_factory=utcnow)
    scope_type: AuditScopeType = "global"
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    thread_id: UUID | None = None
    actor_type: AuditActorType = "unknown"
    actor_id: UUID | None = None
    user_id: UUID | None = None
    system_agent_id: UUID | None = None
    source_service: str
    source_component: str
    action_category: str
    action_name: str
    target_type: str | None = None
    target_id: UUID | None = None
    outcome: AuditOutcome
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    request_id: UUID | None = None
    trace_id: str | None = None
    error_code: str | None = None
    error_class: str | None = None
    error_message_redacted: str | None = None
    payload_mode: AuditPayloadMode = "metadata_only"
    payload_hash: str | None = None
    payload_ref: str | None = None
    payload_size_bytes: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    chain_partition: str = "global"


class AuditEvent(AuditEventDraft):
    ledger_offset: int
    chain_sequence: int
    prev_hash: str
    event_hash: str


class AuditEventPage(BaseModel):
    events: list[AuditEvent] = Field(default_factory=list)
    total_count: int = 0


class AuditChainVerificationResult(BaseModel):
    chain_partition: str
    verified: bool
    checked_events: int = 0
    expected_sequence: int | None = None
    actual_sequence: int | None = None
    expected_prev_hash: str | None = None
    actual_prev_hash: str | None = None
    failing_audit_event_id: UUID | None = None
    detail: str | None = None


class AuditExportRequest(BaseModel):
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    thread_id: UUID | None = None
    actor_user_id: UUID | None = None
    actor_system_agent_id: UUID | None = None
    action_prefix: str | None = None
    outcome: AuditOutcome | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    correlation_id: UUID | None = None
    request_id: UUID | None = None
    occurred_after: datetime | None = None
    occurred_before: datetime | None = None
    limit: int = 1000


class AuditExportResult(BaseModel):
    object_key: str
    bucket: str
    event_count: int
    size_bytes: int
    sha256: str
    presigned_url: str | None = None


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
    organization_id: UUID | None = None
    project_id: UUID | None = None
    actor: ParticipantInput
    harness: WorkspaceHarness | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateOrganizationRequest(BaseModel):
    actor: ParticipantInput
    slug: str
    name: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("slug", mode="before")
    @classmethod
    def _normalize_slug(cls, value: str) -> str:
        return normalize_organization_slug(value)


class UpdateOrganizationRequest(BaseModel):
    actor: ParticipantInput
    slug: str | None = None
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("slug", mode="before")
    @classmethod
    def _normalize_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_organization_slug(value)


class CreateProjectRequest(BaseModel):
    actor: ParticipantInput
    slug: str
    name: str
    description: str | None = None
    owner: ProjectSubjectRef | None = None
    owners: list[ProjectSubjectRef] = Field(default_factory=list)
    editors: list[ProjectSubjectRef] = Field(default_factory=list)
    viewers: list[ProjectSubjectRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("slug", mode="before")
    @classmethod
    def _normalize_slug(cls, value: str) -> str:
        return normalize_project_slug(value)


class UpdateProjectRequest(BaseModel):
    actor: ParticipantInput
    slug: str | None = None
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("slug", mode="before")
    @classmethod
    def _normalize_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_project_slug(value)


class UpsertProjectAccessRequest(BaseModel):
    actor: ParticipantInput
    subject: ProjectSubjectRef
    role: ProjectAccessRole
    metadata: dict[str, Any] = Field(default_factory=dict)


class RemoveProjectAccessRequest(BaseModel):
    actor: ParticipantInput
    subject: ProjectSubjectRef


class AddOrganizationMemberRequest(BaseModel):
    actor: ParticipantInput
    user_id: UUID
    role: OrganizationRole = "member"
    metadata: dict[str, Any] = Field(default_factory=dict)


class RemoveOrganizationMemberRequest(BaseModel):
    actor: ParticipantInput


class DeleteWorkspaceRequest(BaseModel):
    actor: ParticipantInput


class UpdateWorkspaceRequest(BaseModel):
    actor: ParticipantInput
    name: str | None = None
    description: str | None = None
    harness: WorkspaceHarness | None = None
    metadata: dict[str, Any] | None = None


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


class DeleteRoleDefinitionRequest(BaseModel):
    actor: ParticipantInput


class CreateSystemToolRequest(BaseModel):
    actor: ParticipantInput
    name: str
    description: str
    parameter_contract: ToolParameterContract = Field(default_factory=ToolParameterContract)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    execution: ToolExecutionBinding = Field(default_factory=ToolExecutionBinding)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeleteSystemToolRequest(BaseModel):
    actor: ParticipantInput


class UpdateSystemToolRequest(BaseModel):
    actor: ParticipantInput
    name: str | None = None
    description: str | None = None
    parameter_contract: ToolParameterContract | None = None
    input_schema: dict[str, Any] | None = None
    execution: ToolExecutionBinding | None = None
    metadata: dict[str, Any] | None = None


class CreateLlmProviderRequest(BaseModel):
    actor: ParticipantInput
    engine_id: str
    display_name: str
    description: str
    provider: str
    endpoint_kind: LlmEngineEndpointKind = "remote"
    url: str | None = None
    default_model: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    locality: LlmEngineLocality = "cloud"
    priority: int = 100
    enabled: bool = True
    secret_config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateMemoryProviderRequest(BaseModel):
    actor: ParticipantInput
    provider_key: str
    display_name: str
    description: str
    provider: str
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    secret_config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateMcpServerRequest(BaseModel):
    actor: ParticipantInput
    server_key: str
    display_name: str
    description: str
    transport_kind: McpTransportKind = "streamable_http"
    config: dict[str, Any] = Field(default_factory=dict)
    secret_config: dict[str, Any] = Field(default_factory=dict)
    trust_level: ToolTrustLevel = "sandboxed"
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateLlmProviderRequest(BaseModel):
    actor: ParticipantInput
    engine_id: str | None = None
    display_name: str | None = None
    description: str | None = None
    provider: str | None = None
    endpoint_kind: LlmEngineEndpointKind | None = None
    url: str | None = None
    default_model: str | None = None
    capabilities: list[str] | None = None
    locality: LlmEngineLocality | None = None
    priority: int | None = None
    enabled: bool | None = None
    secret_config: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class UpdateMemoryProviderRequest(BaseModel):
    actor: ParticipantInput
    provider_key: str | None = None
    display_name: str | None = None
    description: str | None = None
    provider: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    secret_config: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class UpdateMcpServerRequest(BaseModel):
    actor: ParticipantInput
    server_key: str | None = None
    display_name: str | None = None
    description: str | None = None
    transport_kind: McpTransportKind | None = None
    config: dict[str, Any] | None = None
    secret_config: dict[str, Any] | None = None
    trust_level: ToolTrustLevel | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None


class DeleteLlmProviderRequest(BaseModel):
    actor: ParticipantInput


class DeleteMemoryProviderRequest(BaseModel):
    actor: ParticipantInput


class DeleteMcpServerRequest(BaseModel):
    actor: ParticipantInput


class AttachWorkspaceMcpServerRequest(BaseModel):
    actor: ParticipantInput
    server_id: UUID | None = None
    enabled: bool = True
    tools_enabled: bool = True
    resources_enabled: bool = False
    prompts_enabled: bool = False
    sampling_enabled: bool = False
    name_prefix: str | None = None
    tool_allowlist: list[str] = Field(default_factory=list)
    tool_denylist: list[str] = Field(default_factory=list)
    resource_allowlist: list[str] = Field(default_factory=list)
    prompt_allowlist: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateWorkspaceMcpServerRequest(BaseModel):
    actor: ParticipantInput
    enabled: bool | None = None
    tools_enabled: bool | None = None
    resources_enabled: bool | None = None
    prompts_enabled: bool | None = None
    sampling_enabled: bool | None = None
    name_prefix: str | None = None
    tool_allowlist: list[str] | None = None
    tool_denylist: list[str] | None = None
    resource_allowlist: list[str] | None = None
    prompt_allowlist: list[str] | None = None
    metadata: dict[str, Any] | None = None


class DeleteWorkspaceMcpServerRequest(BaseModel):
    actor: ParticipantInput


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


class CreateIamRoleRequest(BaseModel):
    actor: ParticipantInput
    name: str
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateIamRoleRequest(BaseModel):
    actor: ParticipantInput
    name: str | None = None
    description: str | None = None
    permissions: list[str] | None = None
    metadata: dict[str, Any] | None = None


class BindHumanRoleRequest(BaseModel):
    actor: ParticipantInput
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateAgentIdentityRequest(BaseModel):
    actor: ParticipantInput
    system_agent_id: UUID
    client_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateAgentIdentityStatusRequest(BaseModel):
    actor: ParticipantInput
    metadata: dict[str, Any] = Field(default_factory=dict)


class RotateAgentIdentitySecretRequest(BaseModel):
    actor: ParticipantInput
    metadata: dict[str, Any] = Field(default_factory=dict)


class BindAgentRoleRequest(BaseModel):
    actor: ParticipantInput
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateSystemAgentRequest(BaseModel):
    actor: ParticipantInput
    display_name: str
    description: str
    role: str
    capabilities: list[str] = Field(default_factory=list)
    endpoint: AgentEndpoint
    system_prompt: str
    harness: AgentHarness | None = None
    interaction_contract: AgentInteractionContract = Field(
        default_factory=AgentInteractionContract
    )
    definition: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeleteSystemAgentRequest(BaseModel):
    actor: ParticipantInput


class UpdateSystemAgentRequest(BaseModel):
    actor: ParticipantInput
    display_name: str | None = None
    description: str | None = None
    role: str | None = None
    capabilities: list[str] | None = None
    endpoint: AgentEndpoint | None = None
    system_prompt: str | None = None
    harness: AgentHarness | None = None
    interaction_contract: AgentInteractionContract | None = None
    definition: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class CreateGitRepositoryRequest(BaseModel):
    actor: ParticipantInput
    name: str
    local_path: str
    forgejo_url: str | None = None
    clone_url: str | None = None
    default_branch: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PublishAssetFromGitRequest(BaseModel):
    actor: ParticipantInput
    repository_id: UUID
    asset_type: str
    logical_name: str
    logical_path: str | None = None
    title: str
    description: str | None = None
    git_path: str
    revision: str | None = None
    content_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentBundleGitSource(BaseModel):
    repository_id: UUID
    bundle_path: str
    revision: str | None = None


class ValidateAgentBundleFromGitRequest(BaseModel):
    actor: ParticipantInput
    repository_id: UUID
    bundle_path: str
    revision: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PublishAgentBundleFromGitRequest(BaseModel):
    actor: ParticipantInput
    repository_id: UUID
    bundle_path: str
    revision: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActivateAgentDefinitionVersionRequest(BaseModel):
    actor: ParticipantInput
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentBundleValidationDiagnostic(BaseModel):
    code: str
    message: str
    path: str | None = None
    severity: Literal["error", "warning"] = "error"
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentBundleValidationResult(BaseModel):
    valid: bool
    scope: RegistryScope = "global"
    organization_id: UUID | None = None
    repository_id: UUID | None = None
    resolved_revision: str | None = None
    bundle_path: str | None = None
    agent_key: str | None = None
    compiled_agent: AgentDefinition | None = None
    diagnostics: list[AgentBundleValidationDiagnostic] = Field(default_factory=list)
    source_files: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentBundlePublishResult(BaseModel):
    agent: AgentDefinition
    version: AgentDefinitionVersion
    validation: AgentBundleValidationResult


class UploadAgentBundleArchiveRequest(BaseModel):
    actor: ParticipantInput
    repository_id: UUID
    branch: str
    bundle_path: str
    publish: bool = False
    revision: str | None = None
    commit_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentGitWorktreeSession(BaseModel):
    session_id: UUID
    repository_id: UUID
    scope: RegistryScope = "global"
    organization_id: UUID | None = None
    branch: str
    base_revision: str | None = None
    bundle_path: str
    worktree_path: str
    created_by: UUID
    created_at: datetime = Field(default_factory=utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateAgentGitWorktreeSessionRequest(BaseModel):
    actor: ParticipantInput
    repository_id: UUID
    branch: str
    bundle_path: str
    base_revision: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentGitFileReadRequest(BaseModel):
    path: str


class AgentGitFileContent(BaseModel):
    path: str
    content: str
    content_type: str | None = None
    sha256: str | None = None


class AgentGitFileMutationRequest(BaseModel):
    actor: ParticipantInput
    path: str
    content: str | None = None
    content_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentGitDiffResult(BaseModel):
    session_id: UUID
    diff: str
    changed_files: list[str] = Field(default_factory=list)


class AgentGitCommitRequest(BaseModel):
    actor: ParticipantInput
    message: str
    push: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentGitCommitResult(BaseModel):
    session_id: UUID
    commit_sha: str
    branch: str
    pushed: bool = False
    changed_files: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentBundleUploadResult(BaseModel):
    session: AgentGitWorktreeSession
    commit: AgentGitCommitResult
    publish_result: AgentBundlePublishResult | None = None


class LinkAssetRequest(BaseModel):
    actor: ParticipantInput
    asset_version_id: UUID
    target_type: AssetTargetType
    target_id: UUID
    purpose: str
    workspace_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActivateAssetVersionRequest(BaseModel):
    actor: ParticipantInput
    asset_version_id: UUID
    target_type: AssetTargetType
    target_id: UUID
    purpose: str
    workspace_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    target_system_agent_id: UUID | None = None
    target_tool_scope: RegistryScope | None = None
    create_task: bool = True
    task_instructions: list[str] = Field(default_factory=list)
    requests: list["CreateInteractionRequest"] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateInteractionQuestionRequest(BaseModel):
    prompt: str
    kind: str | None = None
    expected_format: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateInteractionRequest(BaseModel):
    title: str
    summary: str | None = None
    questions: list[CreateInteractionQuestionRequest] = Field(default_factory=list)
    selectors: list[ParticipantSelector] = Field(default_factory=list)
    target_participant_ids: list[UUID] = Field(default_factory=list)
    completion_rule: CompletionRule | None = None
    timeout_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateInteractionRequestsRequest(BaseModel):
    actor: ParticipantInput
    requests: list[CreateInteractionRequest] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateToolGenerationRevisionRequest(BaseModel):
    actor: ParticipantInput
    status: ToolGenerationRevisionStatus = "pending_approval"
    manifest: GeneratedToolManifest
    validation_report: GeneratedToolValidationReport | None = None
    source_asset_id: UUID | None = None
    source_asset_version_id: UUID | None = None
    manifest_asset_id: UUID | None = None
    manifest_asset_version_id: UUID | None = None
    report_asset_id: UUID | None = None
    report_asset_version_id: UUID | None = None
    image_ref: str | None = None
    image_digest: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewToolGenerationRevisionRequest(BaseModel):
    actor: ParticipantInput
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateInteractionAnswerRequest(BaseModel):
    actor: ParticipantInput
    content: str
    question_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateInteractionRequestRequest(BaseModel):
    actor: ParticipantInput
    action: Literal["acknowledge_target", "dismiss_target", "cancel", "timeout"]
    target_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateMemoryEntryRequest(BaseModel):
    actor: ParticipantInput
    entry_type: str
    content: str
    summary: str | None = None
    visibility: Visibility = "workspace"
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateThreadMemoryRequest(BaseModel):
    actor: ParticipantInput
    entry_type: str
    content: str
    summary: str | None = None
    visibility: Visibility = "workspace"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfirmWorkspaceMemoryRequest(BaseModel):
    actor: ParticipantInput
    source_memory_entry_id: UUID
    entry_type: str | None = None
    content: str | None = None
    summary: str | None = None
    visibility: Visibility = "workspace"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchMemoryRequest(BaseModel):
    actor: ParticipantInput
    query: str
    limit: int = 10
    use_provider: str | None = None
    include_graph: bool = True
    metadata_filters: dict[str, Any] = Field(default_factory=dict)


class UpdateMemoryEntryRequest(BaseModel):
    actor: ParticipantInput
    content: str | None = None
    summary: str | None = None
    visibility: Visibility | None = None
    metadata: dict[str, Any] | None = None


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


class WorkspaceCommunicationLogEntry(BaseModel):
    message_id: UUID
    workspace_id: UUID
    thread_id: UUID
    thread_title: str | None = None
    actor: ActorRef
    actor_display_name: str
    visibility: Visibility = "workspace"
    kind: CommunicationLogKind = "message"
    content: str = ""
    status: MessageStatus = "completed"
    correlation_id: UUID
    causation_id: UUID | None = None
    sequence: int = 0
    interaction_request_id: UUID | None = None
    interaction_request_status: InteractionRequestStatus | None = None
    interaction_question_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class WorkspaceCommunicationLogPage(BaseModel):
    workspace_id: UUID
    entries: list[WorkspaceCommunicationLogEntry] = Field(default_factory=list)
    total_count: int = 0


class AgentExecutionContext(BaseModel):
    workspace: Workspace
    workspace_harness: WorkspaceHarness | None = None
    thread: Thread
    task: Task
    run: Run
    run_step: RunStep | None = None
    routing: AgentTaskRouting
    system_agent: AgentDefinition
    agent_harness: AgentHarness | None = None
    participant: ParticipantProfile
    participants: list[ParticipantProfile] = Field(default_factory=list)
    role_definitions: list[RoleDefinition] = Field(default_factory=list)
    workspace_tools: list[WorkspaceTool] = Field(default_factory=list)
    workspace_mcp_servers: list[WorkspaceMcpServer] = Field(default_factory=list)
    workspace_mcp_tools: list[WorkspaceMcpTool] = Field(default_factory=list)
    workspace_mcp_resources: list[WorkspaceMcpResource] = Field(default_factory=list)
    workspace_mcp_prompts: list[WorkspaceMcpPrompt] = Field(default_factory=list)
    internal_tools: list[AgentInternalToolBinding] = Field(default_factory=list)
    internal_mcp_servers: list[AgentInternalMcpServer] = Field(default_factory=list)
    internal_mcp_tools: list[WorkspaceMcpTool] = Field(default_factory=list)
    task_instructions: list[str] = Field(default_factory=list)
    messages: list[TimelineMessage] = Field(default_factory=list)
    interaction_requests: list[InteractionRequestDetail] = Field(default_factory=list)
    tool_generation_request: ToolGenerationRequestDetail | None = None
    run_memory: list[MemoryEntry] = Field(default_factory=list)
    thread_memory: list[MemoryEntry] = Field(default_factory=list)
    workspace_memory: list[MemoryEntry] = Field(default_factory=list)
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
