from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import sys
from uuid import UUID, uuid4

import asyncpg
from open_talon_contracts.oci_registry import (
    digest_pinned_image_ref,
    is_digest,
    is_digest_pinned_image_ref,
    is_registry_backed_image_ref,
)

_WORKSPACE_MEMORY_DIR = Path(__file__).resolve().parents[2] / "workspace-memory"
if _WORKSPACE_MEMORY_DIR.is_dir():
    workspace_memory_path = str(_WORKSPACE_MEMORY_DIR)
    if workspace_memory_path not in sys.path:
        sys.path.insert(0, workspace_memory_path)

from workspace_memory import (
    ProviderSearchResult,
    build_default_secret_resolver,
    build_provider_index,
)
from open_talon_contracts.iam import (
    ORGANIZATION_ROLE_BASE_PERMISSIONS,
    PROJECT_ROLE_BASE_PERMISSIONS,
)

from .contracts import (
    ActorRef,
    AgentArtifactDraft,
    AgentConfiguration,
    AgentDefinition,
    AgentDefinitionVersion,
    AgentIdentity,
    AgentEndpoint,
    AgentExecutionContext,
    AgentInternalMcpServer,
    AgentInternalToolBinding,
    AgentRunResult,
    AgentRoleBinding,
    CompletionRule,
    AgentToolCallDraft,
    AgentTaskRouting,
    AuditChainVerificationResult,
    AuditEvent,
    AuditEventDraft,
    AuditEventPage,
    AttachWorkspaceMcpServerRequest,
    AttachWorkspaceToolRequest,
    AttachLibraryToWorkspaceRequest,
    AssumeParticipantRoleRequest,
    ApplyMethodologyBlueprintRequest,
    AttachResearchDossierContextPackRequest,
    Artifact,
    AssetLink,
    ActivateAssetVersionRequest,
    BindAgentRoleRequest,
    BindHumanRoleRequest,
    CreateAgentParticipantRequest,
    CreateAgentIdentityRequest,
    CreateGitRepositoryRequest,
    CreateLibraryItemRequest,
    CreateLibraryRequest,
    CreateIamRoleRequest,
    CreateInteractionAnswerRequest,
    CreateInteractionQuestionRequest,
    CreateInteractionRequest,
    CreateInteractionRequestsRequest,
    CreateLlmProviderRequest,
    CreateMemoryProviderRequest,
    CreateMcpServerRequest,
    CancelMethodicExecutionRequest,
    CreateMethodicAssignmentRequest,
    CreateMethodicExecutionRequest,
    CreateMethodicResourceRequestRequest,
    CreateOrganizationRequest,
    CreateProjectRequest,
    CreateRetrievalContextPackRequest,
    CreateRetrievalCorpusRequest,
    CreateRetrievalIngestionJobRequest,
    CreateRetrievalProfileRequest,
    CreateRetrievalSourceRequest,
    CreateSystemAgentRequest,
    CreateSystemToolRequest,
    ConfirmWorkspaceMemoryRequest,
    CreateMemoryEntryRequest,
    CreateThreadMemoryRequest,
    CreateMessageRequest,
    CreateMethodologyBlueprintRequest,
    CreateToolGenerationRevisionRequest,
    CreateResearchDossierSourceRequest,
    SearchMemoryRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteLlmProviderRequest,
    DeleteLibraryRequest,
    DeleteMemoryProviderRequest,
    DeleteMcpServerRequest,
    DeleteParticipantRequest,
    DeleteRoleDefinitionRequest,
    DeleteSystemAgentRequest,
    DeleteSystemToolRequest,
    DeleteWorkspaceToolRequest,
    DeleteWorkspaceMcpServerRequest,
    DeleteWorkspaceRequest,
    ExecutionWorkspaceRef,
    EvaluateMethodicStepRequest,
    EventEnvelope,
    GeneratedToolManifest,
    GeneratedToolValidationReport,
    IndexLibraryRequest,
    InteractionAnswer,
    InteractionQuestion,
    InteractionRequest,
    InteractionRequestDetail,
    InteractionRequestDraft,
    InteractionRequestTarget,
    Membership,
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderRecord,
    MemorySearchHit,
    MemorySearchResponse,
    MethodologyBlueprint,
    MethodologyBlueprintDetail,
    MethodologyBlueprintVersion,
    NavigateResearchDossierRequest,
    PublicationReview,
    McpPromptDefinition,
    McpResourceDefinition,
    McpServerDefinition,
    McpServerSyncJob,
    McpServerSyncResult,
    McpToolDefinition,
    LlmProviderDefinition,
    IamRoleDefinition,
    MethodicExecution,
    MethodicExecutionAssignment,
    MethodicExecutionCheck,
    MethodicExecutionDetail,
    MethodicExecutionStep,
    MethodicResourceRequest,
    Organization,
    OrganizationMembership,
    ParticipantSelector,
    ParticipantInput,
    ParticipantProfile,
    Project,
    ProjectAccessBinding,
    ProjectAccessRole,
    ProjectSubjectRef,
    PublishAssetFromGitRequest,
    RequestMcpServerSyncRequest,
    RetrievalChunk,
    RetrievalContextPack,
    RetrievalCorpus,
    RetrievalEmbedding,
    RetrievalIngestionJob,
    RetrievalProfile,
    RetrievalRun,
    RetrievalSearchHit,
    RetrievalSearchResponse,
    RetrievalSource,
    RetrievalSourceVersion,
    ResearchDossier,
    ResearchDossierClaim,
    ResearchDossierConcept,
    ResearchDossierEvent,
    ResearchDossierGraph,
    ResearchDossierHealthCheck,
    ResearchDossierLink,
    ResearchDossierNavigationResult,
    ResearchDossierNote,
    ResearchDossierNotebook,
    ResearchDossierNotebookDetail,
    ResearchDossierProviderBinding,
    ResearchDossierProviderExternalRef,
    ResearchDossierSource,
    ResearchDossierSyncRun,
    RunRetrievalSearchRequest,
    PresenceState,
    ResolvedAssetBinding,
    RoleDefinition,
    SystemToolDefinition,
    RunStep,
    ExecutionSpec,
    ExecutionLimits,
    Task,
    TargetRef,
    Thread,
    ThreadDetail,
    TimelineMessage,
    TimelinePage,
    ToolGenerationRequest,
    ToolGenerationRequestDetail,
    ToolGenerationRevision,
    WorkspaceCommunicationLogPage,
    Run,
    MarkResearchDossierReadyRequest,
    ReviewToolGenerationRevisionRequest,
    ReviewMethodologyBlueprintVersionRequest,
    ReviewMethodicResourceRequest,
    RotateAgentIdentitySecretRequest,
    StopReason,
    ToolCall,
    ToolCallResult,
    UpdateSystemAgentRequest,
    UpdateAgentIdentityStatusRequest,
    UpdateInteractionRequestRequest,
    UpdateIamRoleRequest,
    LinkAssetRequest,
    Library,
    LibraryItem,
    LibraryWorkspaceAttachment,
    UpdateLibraryItemRequest,
    UpdateLibraryRequest,
    UpdateLlmProviderRequest,
    UpdateMemoryProviderRequest,
    UpdateMcpServerRequest,
    UpdateOrganizationRequest,
    UpdateProjectRequest,
    UpdateResearchDossierSourceRequest,
    UpsertResearchDossierClaimRequest,
    UpsertResearchDossierConceptRequest,
    UpsertResearchDossierLinkRequest,
    UpsertResearchDossierNoteRequest,
    UpsertProjectAccessRequest,
    UpsertRoleDefinitionRequest,
    RemoveOrganizationMemberRequest,
    RemoveProjectAccessRequest,
    UpdateSystemToolRequest,
    build_default_interaction_contract,
    interaction_contract_is_empty,
    AddOrganizationMemberRequest,
    UpdateAgentParticipantRequest,
    UpdateMemoryEntryRequest,
    UpdateWorkspaceRequest,
    SubmitMethodologyBlueprintDraftRequest,
    SubmitResearchDossierHealthCheckRequest,
    SyncResearchDossierNotebookRequest,
    UploadFileAssetRequest,
    UpdateWorkspaceToolRequest,
    UpdateWorkspaceMcpServerRequest,
    Workspace,
    WorkspaceAsset,
    WorkspaceAssetVersion,
    WorkspaceDetail,
    WorkspaceHarness,
    WorkspaceModerationPolicy,
    WorkspaceMcpPrompt,
    WorkspaceMcpResource,
    WorkspaceMcpServer,
    WorkspaceMcpTool,
    WorkspaceTool,
    GitRepository,
)
from .repository import CollaborationRepository, UserRecord
from .library_indexing import (
    bind_source_version_to_job,
    build_library_corpus,
    build_library_index_record,
    find_library_corpus,
    library_item_source_id,
)
from .results import (
    AgentDefinitionCommandResult,
    AgentIdentityCommandResult,
    CommandResult,
    GitRepositoryCommandResult,
    IamRoleCommandResult,
    InteractionRequestCommandResult,
    LeaseReconciliationResult,
    LibraryCommandResult,
    LlmProviderCommandResult,
    MemoryCommandResult,
    MemoryProviderCommandResult,
    MethodologyBlueprintCommandResult,
    MethodicExecutionCommandResult,
    McpServerCommandResult,
    MessageCommandResult,
    OrganizationCommandResult,
    OrganizationMembershipCommandResult,
    ParticipantCommandResult,
    ProjectCommandResult,
    RetrievalCommandResult,
    RoleDefinitionCommandResult,
    RunCommandResult,
    RunStepCommandResult,
    SystemToolCommandResult,
    TaskCommandResult,
    ThreadCommandResult,
    ToolCallCommandResult,
    ToolGenerationRequestCommandResult,
    WorkspaceAssetCommandResult,
    WorkspaceCommandResult,
    WorkspaceToolCommandResult,
)
from .methodics_execution import MethodicsEventSpec, MethodicsExecutionPlanner
from .runtime_execution import RuntimeExecutionService
from .system_defaults import (
    ANCHOR_AGENT_ID,
    ANCHOR_TASK_KIND,
    CONTROL_PLANE_MCP_SERVER_ID,
    METHODOLOGY_BLUEPRINT_DRAFT_TASK_KIND,
    METHODOLOGY_RESEARCH_DOSSIER_BUILD_TASK_KIND,
    METHODICS_EXECUTION_START_TASK_KIND,
    SYSTEM_BASE_ORGANIZATION_ID,
    administration_project_for_organization as managed_administration_project_for_organization,
    anchor_agent_definition as managed_anchor_agent_definition,
    anchor_participant_for_workspace as managed_anchor_participant_for_workspace,
    curator_agent_for_organization as managed_curator_agent_for_organization,
    curator_iam_role_for_organization as managed_curator_iam_role_for_organization,
    curator_internal_mcp_binding as managed_curator_internal_mcp_binding,
    default_project_for_organization as managed_default_project_for_organization,
    ensure_anchor_attached_for_workspace as managed_ensure_anchor_attached_for_workspace,
    operations_participant_for_agent as managed_operations_participant_for_agent,
    operations_workspace_for_organization as managed_operations_workspace_for_organization,
)

logger = logging.getLogger(__name__)

_DEFAULT_WORKSPACE_ROLE_DEFINITIONS = {
    "admin": "Manages the workspace, participants, tools, and provider configuration.",
    "supervisor": "Coordinates delivery, reviews work, and guides workspace members without full administrative control.",
    "user": "Collaborates in the workspace, participates in threads, and uses attached tools.",
}

_ORGANIZATION_ADMIN_ROLES = {"owner", "admin"}
_MAX_RUN_STEP_ATTEMPTS = 3
_MAX_TOOL_CALL_ATTEMPTS = 3
_TOOL_GENERATION_REGISTRY_VERIFY_TOOL = "generated_tool_registry_pull_verify"
_TOOL_GENERATION_APPROVAL_WORKER_ID = "tool-generation-approval"
_RETRY_BACKOFF_SECONDS = (30, 120, 600)


class CollaborationKernel:
    def __init__(self, repository: CollaborationRepository) -> None:
        self._repository = repository
        self._secret_resolver = build_default_secret_resolver()
        self._memory_provider_index = build_provider_index(
            store=repository,
            secret_resolver=self._secret_resolver,
        )
        self._methodics_execution = MethodicsExecutionPlanner()
        self._runtime_execution = RuntimeExecutionService(
            repository=repository,
            task_routing=lambda task: self._task_routing(task),
            resolve_agent_participant=lambda **kwargs: self._resolve_agent_participant(**kwargs),
            require_run_participant=lambda **kwargs: self._require_run_participant(**kwargs),
            resolve_run_for_context=lambda task, participant, run_id: self._resolve_run_for_context(
                task,
                participant,
                run_id,
            ),
            advertise_workspace_tools=lambda participant, workspace_tools: self._advertise_workspace_tools(
                participant,
                workspace_tools,
            ),
            filter_visible_messages=lambda messages, **kwargs: self._filter_visible_messages(
                messages,
                **kwargs,
            ),
            filter_visible_memory_entries=lambda entries, **kwargs: self._filter_visible_memory_entries(
                entries,
                **kwargs,
            ),
            role_definitions_from_workspace=lambda workspace: self._role_definitions_from_workspace(
                workspace
            ),
            build_thread_event=lambda *args, **kwargs: self._build_thread_event(*args, **kwargs),
            now=lambda: self._now(),
            utc_day_window=lambda timestamp: self._utc_day_window(timestamp),
            workspace_daily_token_cap=lambda workspace, default_cap: self._workspace_daily_token_cap(
                workspace,
                default_cap,
            ),
            run_output_from_result=lambda result: self._run_output_from_result(result),
            artifact_from_draft=lambda draft, **kwargs: self._artifact_from_draft(
                draft,
                **kwargs,
            ),
            agent_message_from_result=lambda result, **kwargs: self._agent_message_from_result(
                result,
                **kwargs,
            ),
            stop_reason_returns_to_thread=lambda stop_reason: self._stop_reason_returns_to_thread(
                stop_reason
            ),
            fail_run_step=lambda *args, **kwargs: self.fail_run_step(*args, **kwargs),
        )

    async def setup_schema(self) -> None:
        await self._repository.setup_schema()
        await self._backfill_system_agent_interaction_contracts()

    async def create_organization(
        self,
        payload: CreateOrganizationRequest,
    ) -> OrganizationCommandResult:
        now = self._now()
        created_by = self._actor_user_id(payload.actor) or payload.actor.participant_id
        organization = Organization(
            organization_id=uuid4(),
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            created_by=created_by,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        default_project = self._default_project_for_organization(
            organization,
            actor=payload.actor,
            now=now,
        )
        administration_project = self._administration_project_for_organization(
            organization,
            actor=payload.actor,
            now=now,
        )
        operations_workspace = self._operations_workspace_for_organization(
            organization,
            administration_project,
            now=now,
        )
        curator_agent = (
            self._curator_agent_for_organization(organization, now=now)
            if organization.organization_id != SYSTEM_BASE_ORGANIZATION_ID
            else None
        )
        curator_role = (
            self._curator_iam_role_for_organization(
                organization.organization_id,
                now=now,
            )
            if curator_agent is not None
            else None
        )
        curator_participant = (
            self._operations_participant_for_agent(
                workspace=operations_workspace,
                agent=curator_agent,
                now=now,
            )
            if curator_agent is not None
            else None
        )
        curator_mcp_binding = (
            self._curator_internal_mcp_binding(agent_id=curator_agent.agent_id, now=now)
            if curator_agent is not None
            else None
        )
        actor_user_id = self._actor_user_id(payload.actor)
        membership = (
            OrganizationMembership(
                organization_id=organization.organization_id,
                user_id=actor_user_id,
                role="owner",
                joined_at=now,
                updated_at=now,
                metadata={"created_by": str(created_by)},
            )
            if actor_user_id is not None
            else None
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                if actor_user_id is not None:
                    await self._repository.upsert_user(
                        conn,
                        UserRecord(
                            user_id=actor_user_id,
                            display_name=payload.actor.display_name,
                            created_at=now,
                            updated_at=now,
                            metadata={},
                        ),
                    )
                await self._repository.upsert_organization(conn, organization)
                if hasattr(self._repository, "upsert_project"):
                    await self._repository.upsert_project(conn, default_project)
                    await self._repository.upsert_project(conn, administration_project)
                    if hasattr(self._repository, "upsert_project_access_binding"):
                        await self._repository.upsert_project_access_binding(
                            conn,
                            self._project_access_binding(
                                default_project.project_id,
                                self._actor_project_subject(payload.actor),
                                "creator",
                                now=now,
                                metadata={"created_by": str(created_by), "managed": True},
                            ),
                        )
                        await self._repository.upsert_project_access_binding(
                            conn,
                            self._project_access_binding(
                                administration_project.project_id,
                                self._actor_project_subject(payload.actor),
                                "creator",
                                now=now,
                                metadata={"created_by": str(created_by), "managed": True},
                            ),
                        )
                await self._repository.upsert_workspace(conn, operations_workspace)
                await self._ensure_anchor_attached_for_workspace(
                    conn,
                    operations_workspace.workspace_id,
                    now=now,
                )
                if curator_agent is not None:
                    await self._repository.upsert_system_agent(conn, curator_agent)
                if curator_role is not None and hasattr(
                    self._repository,
                    "upsert_iam_role_definition",
                ):
                    await self._repository.upsert_iam_role_definition(conn, curator_role)
                if curator_participant is not None:
                    await self._repository.upsert_participant(conn, curator_participant)
                    if hasattr(self._repository, "upsert_project_access_binding"):
                        await self._repository.upsert_project_access_binding(
                            conn,
                            self._project_access_binding(
                                administration_project.project_id,
                                ProjectSubjectRef(system_agent_id=curator_agent.agent_id),
                                "creator",
                                now=now,
                                metadata={"managed": True, "source": "operational_agent"},
                            ),
                        )
                if curator_mcp_binding is not None and hasattr(
                    self._repository,
                    "upsert_agent_internal_mcp_server",
                ):
                    await self._repository.upsert_agent_internal_mcp_server(
                        conn,
                        binding=curator_mcp_binding,
                    )
                if membership is not None:
                    await self._repository.upsert_organization_membership(conn, membership)
        return OrganizationCommandResult(organization=organization)

    async def list_organizations(
        self,
        *,
        user_id: UUID | None = None,
    ) -> list[Organization]:
        if user_id is not None:
            return await self._repository.list_organizations_for_user(user_id)
        return await self._repository.list_organizations()

    async def get_organization(self, organization_id: UUID) -> Organization | None:
        return await self._repository.fetch_organization(organization_id)

    async def get_organization_by_slug(self, slug: str) -> Organization | None:
        return await self._repository.fetch_organization_by_slug(slug)

    async def create_project(
        self,
        organization_id: UUID,
        payload: CreateProjectRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> ProjectCommandResult:
        organization = await self._repository.fetch_organization(organization_id)
        if organization is None:
            raise KeyError(f"Organization {organization_id} not found")
        actor_user_id = self._actor_user_id(payload.actor)
        if actor_user_id is not None and not allow_platform_admin:
            await self._require_organization_permission(
                organization_id,
                actor_user_id,
                "project.write",
            )
        now = self._now()
        creator_subject = self._actor_project_subject(payload.actor)
        owner_subject = payload.owner or creator_subject
        project = Project(
            project_id=uuid4(),
            organization_id=organization_id,
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            created_by=actor_user_id or payload.actor.participant_id,
            creator_user_id=creator_subject.user_id,
            creator_system_agent_id=creator_subject.system_agent_id,
            owner_user_id=owner_subject.user_id,
            owner_system_agent_id=owner_subject.system_agent_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        access_bindings = self._project_access_bindings_for_create(
            project.project_id,
            owner=owner_subject,
            creator=creator_subject,
            owners=payload.owners,
            editors=payload.editors,
            viewers=payload.viewers,
            now=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_project(conn, project)
                if hasattr(self._repository, "upsert_project_access_binding"):
                    for binding in access_bindings:
                        await self._repository.upsert_project_access_binding(conn, binding)
        return ProjectCommandResult(project=project)

    async def list_projects(
        self,
        organization_id: UUID,
        *,
        user_id: UUID | None = None,
        system_agent_id: UUID | None = None,
        include_all: bool = False,
    ) -> list[Project]:
        if await self._repository.fetch_organization(organization_id) is None:
            raise KeyError(f"Organization {organization_id} not found")
        if not hasattr(self._repository, "list_projects"):
            return []
        _ = user_id, system_agent_id, include_all
        return await self._repository.list_projects(organization_id)

    async def get_project(self, project_id: UUID) -> Project | None:
        if not hasattr(self._repository, "fetch_project"):
            return None
        return await self._repository.fetch_project(project_id)

    async def update_project(
        self,
        organization_id: UUID,
        project_id: UUID,
        payload: UpdateProjectRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> ProjectCommandResult:
        project = await self._repository.fetch_project(project_id)
        if project is None or project.organization_id != organization_id:
            raise KeyError(f"Project {project_id} not found in organization {organization_id}")
        actor_user_id = self._actor_user_id(payload.actor)
        if not allow_platform_admin:
            if actor_user_id is not None:
                await self._require_organization_membership(organization_id, actor_user_id)
            await self._require_project_permission(
                project_id,
                payload.actor,
                permission="project.write",
            )
        updated = project.model_copy(
            update={
                "slug": payload.slug or project.slug,
                "name": payload.name or project.name,
                "description": (
                    payload.description
                    if payload.description is not None
                    else project.description
                ),
                "updated_at": self._now(),
                "metadata": (
                    {**project.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else project.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_project(conn, updated)
        return ProjectCommandResult(project=updated)

    async def list_project_access(
        self,
        organization_id: UUID,
        project_id: UUID,
        *,
        actor: ParticipantInput | None = None,
        allow_platform_admin: bool = False,
    ) -> list[ProjectAccessBinding]:
        project = await self._repository.fetch_project(project_id)
        if project is None or project.organization_id != organization_id:
            raise KeyError(f"Project {project_id} not found in organization {organization_id}")
        if actor is not None and not allow_platform_admin:
            actor_user_id = self._actor_user_id(actor)
            if actor_user_id is not None:
                await self._require_organization_membership(organization_id, actor_user_id)
            await self._require_project_permission(
                project_id,
                actor,
                permission="project.read",
            )
        if not hasattr(self._repository, "list_project_access_bindings"):
            return []
        return await self._repository.list_project_access_bindings(project_id)

    async def upsert_project_access(
        self,
        organization_id: UUID,
        project_id: UUID,
        payload: UpsertProjectAccessRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> ProjectAccessBinding:
        project = await self._repository.fetch_project(project_id)
        if project is None or project.organization_id != organization_id:
            raise KeyError(f"Project {project_id} not found in organization {organization_id}")
        if not allow_platform_admin:
            actor_user_id = self._actor_user_id(payload.actor)
            if actor_user_id is not None:
                await self._require_organization_membership(organization_id, actor_user_id)
            await self._require_project_permission(
                project_id,
                payload.actor,
                permission="project.access.write",
            )
        now = self._now()
        subject_is_creator = self._project_subject_matches(
            payload.subject,
            user_id=project.creator_user_id,
            system_agent_id=project.creator_system_agent_id,
        )
        if payload.role == "creator" and not subject_is_creator:
            raise ValueError("Project creator cannot be reassigned through access bindings")
        binding = self._project_access_binding(
            project_id,
            payload.subject,
            "creator" if subject_is_creator else payload.role,
            now=now,
            metadata=payload.metadata,
        )
        project_update: Project | None = None
        if payload.role == "owner":
            project_update = project.model_copy(
                update={
                    "owner_user_id": payload.subject.user_id,
                    "owner_system_agent_id": payload.subject.system_agent_id,
                    "updated_at": now,
                }
            )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                if project_update is not None:
                    await self._repository.upsert_project(conn, project_update)
                await self._repository.upsert_project_access_binding(conn, binding)
        return binding

    async def remove_project_access(
        self,
        organization_id: UUID,
        project_id: UUID,
        payload: RemoveProjectAccessRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> dict[str, bool | str]:
        project = await self._repository.fetch_project(project_id)
        if project is None or project.organization_id != organization_id:
            raise KeyError(f"Project {project_id} not found in organization {organization_id}")
        if self._project_subject_matches(
            payload.subject,
            user_id=project.owner_user_id,
            system_agent_id=project.owner_system_agent_id,
        ):
            raise ValueError("Cannot remove the project owner")
        if self._project_subject_matches(
            payload.subject,
            user_id=project.creator_user_id,
            system_agent_id=project.creator_system_agent_id,
        ):
            raise ValueError("Cannot remove the project creator")
        if not allow_platform_admin:
            actor_user_id = self._actor_user_id(payload.actor)
            if actor_user_id is not None:
                await self._require_organization_membership(organization_id, actor_user_id)
            await self._require_project_permission(
                project_id,
                payload.actor,
                permission="project.access.write",
            )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_project_access_binding(
                    conn,
                    project_id=project_id,
                    user_id=payload.subject.user_id,
                    system_agent_id=payload.subject.system_agent_id,
                )
        if not deleted:
            raise KeyError(f"Project access binding for project {project_id} not found")
        return {"deleted": True, "project_id": str(project_id)}

    async def update_organization(
        self,
        organization_id: UUID,
        payload: UpdateOrganizationRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> OrganizationCommandResult:
        organization = await self._repository.fetch_organization(organization_id)
        if organization is None:
            raise KeyError(f"Organization {organization_id} not found")
        actor_user_id = self._actor_user_id(payload.actor)
        if actor_user_id is not None and not allow_platform_admin:
            await self._require_organization_permission(
                organization_id,
                actor_user_id,
                "organization.members.write",
            )
        updated = organization.model_copy(
            update={
                "slug": payload.slug or organization.slug,
                "name": payload.name or organization.name,
                "description": (
                    payload.description
                    if payload.description is not None
                    else organization.description
                ),
                "updated_at": self._now(),
                "metadata": (
                    {**organization.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else organization.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_organization(conn, updated)
        return OrganizationCommandResult(organization=updated)

    async def list_organization_memberships(
        self,
        organization_id: UUID,
    ) -> list[OrganizationMembership]:
        if await self._repository.fetch_organization(organization_id) is None:
            raise KeyError(f"Organization {organization_id} not found")
        return await self._repository.list_organization_memberships(organization_id)

    async def add_organization_member(
        self,
        organization_id: UUID,
        payload: AddOrganizationMemberRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> OrganizationMembershipCommandResult:
        if await self._repository.fetch_organization(organization_id) is None:
            raise KeyError(f"Organization {organization_id} not found")
        actor_user_id = self._actor_user_id(payload.actor)
        if actor_user_id is not None and not allow_platform_admin:
            await self._require_organization_permission(
                organization_id,
                actor_user_id,
                "organization.members.write",
            )
        user = await self._repository.fetch_user(payload.user_id)
        if user is None:
            raise KeyError(f"User {payload.user_id} not found")
        now = self._now()
        membership = OrganizationMembership(
            organization_id=organization_id,
            user_id=payload.user_id,
            role=payload.role,
            joined_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_organization_membership(conn, membership)
        return OrganizationMembershipCommandResult(membership=membership)

    async def remove_organization_member(
        self,
        organization_id: UUID,
        user_id: UUID,
        payload: RemoveOrganizationMemberRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> dict[str, bool | str]:
        if await self._repository.fetch_organization(organization_id) is None:
            raise KeyError(f"Organization {organization_id} not found")
        actor_user_id = self._actor_user_id(payload.actor)
        if actor_user_id is not None and not allow_platform_admin:
            await self._require_organization_permission(
                organization_id,
                actor_user_id,
                "organization.members.write",
            )
        membership = await self._repository.fetch_organization_membership(
            organization_id,
            user_id,
        )
        if membership is None:
            raise KeyError(
                f"User {user_id} is not a member of organization {organization_id}"
            )
        if membership.role == "owner":
            memberships = await self._repository.list_organization_memberships(organization_id)
            if not any(
                item.user_id != user_id and item.role == "owner"
                for item in memberships
            ):
                raise ValueError("Cannot remove the last organization owner")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_organization_membership(
                    conn,
                    organization_id=organization_id,
                    user_id=user_id,
                )
                if not deleted:
                    raise KeyError(
                        f"User {user_id} is not a member of organization {organization_id}"
                    )
                await self._repository.remove_user_participants_for_organization(
                    conn,
                    organization_id=organization_id,
                    user_id=user_id,
                )
        return {
            "deleted": True,
            "organization_id": str(organization_id),
            "user_id": str(user_id),
        }

    async def list_iam_role_definitions(
        self,
        *,
        subject_kind: str,
        scope: str | None = None,
        organization_id: UUID | None = None,
    ) -> list[IamRoleDefinition]:
        return await self._repository.list_iam_role_definitions(
            subject_kind=subject_kind,
            scope=scope,
            organization_id=organization_id,
        )

    async def get_iam_role_definition(self, role_id: UUID) -> IamRoleDefinition | None:
        return await self._repository.fetch_iam_role_definition(role_id)

    async def create_iam_role_definition(
        self,
        payload: CreateIamRoleRequest,
        *,
        subject_kind: str,
        scope: str,
        organization_id: UUID | None = None,
    ) -> IamRoleCommandResult:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        now = self._now()
        role = IamRoleDefinition(
            role_id=uuid4(),
            scope=scope,
            subject_kind=subject_kind,
            organization_id=organization_id,
            name=payload.name,
            description=payload.description,
            permissions=list(dict.fromkeys(payload.permissions)),
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_iam_role_definition(conn, role)
        return IamRoleCommandResult(role=role)

    async def update_iam_role_definition(
        self,
        role_id: UUID,
        payload: UpdateIamRoleRequest,
    ) -> IamRoleCommandResult:
        existing = await self._repository.fetch_iam_role_definition(role_id)
        if existing is None:
            raise KeyError(f"IAM role {role_id} not found")
        updated = existing.model_copy(
            update={
                "name": payload.name or existing.name,
                "description": (
                    payload.description
                    if payload.description is not None
                    else existing.description
                ),
                "permissions": (
                    list(dict.fromkeys(payload.permissions))
                    if payload.permissions is not None
                    else existing.permissions
                ),
                "updated_at": self._now(),
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_iam_role_definition(conn, updated)
        return IamRoleCommandResult(role=updated)

    async def delete_iam_role_definition(self, role_id: UUID) -> dict[str, bool | str]:
        existing = await self._repository.fetch_iam_role_definition(role_id)
        if existing is None:
            raise KeyError(f"IAM role {role_id} not found")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_iam_role_definition(conn, role_id=role_id)
        if not deleted:
            raise KeyError(f"IAM role {role_id} not found")
        return {"deleted": True, "role_id": str(role_id)}

    async def list_human_roles_for_user(
        self,
        *,
        user_id: UUID,
        organization_id: UUID | None = None,
    ) -> list[IamRoleDefinition]:
        return await self._repository.list_human_roles_for_user(
            user_id=user_id,
            organization_id=organization_id,
        )

    async def bind_human_role(
        self,
        user_id: UUID,
        role_id: UUID,
        payload: BindHumanRoleRequest,
    ) -> dict[str, str]:
        role = await self._repository.fetch_iam_role_definition(role_id)
        if role is None or role.subject_kind != "human":
            raise KeyError(f"Human IAM role {role_id} not found")
        if await self._repository.fetch_user(user_id) is None:
            raise KeyError(f"User {user_id} not found")
        if role.organization_id is not None:
            membership = await self._repository.fetch_organization_membership(
                role.organization_id,
                user_id,
            )
            if membership is None:
                raise PermissionError(
                    f"User {user_id} is not a member of organization {role.organization_id}"
                )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.bind_human_role(
                    conn,
                    user_id=user_id,
                    role_id=role_id,
                    created_at=self._now(),
                    metadata=payload.metadata,
                )
        return {"user_id": str(user_id), "role_id": str(role_id)}

    async def unbind_human_role(
        self,
        user_id: UUID,
        role_id: UUID,
    ) -> dict[str, bool | str]:
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.unbind_human_role(
                    conn,
                    user_id=user_id,
                    role_id=role_id,
                )
        if not deleted:
            raise KeyError(f"Human role binding user={user_id} role={role_id} not found")
        return {"deleted": True, "user_id": str(user_id), "role_id": str(role_id)}

    async def list_agent_identities(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
    ) -> list[AgentIdentity]:
        return await self._repository.list_agent_identities(
            scope=scope,
            organization_id=organization_id,
        )

    async def get_agent_identity(self, agent_identity_id: UUID) -> AgentIdentity | None:
        return await self._repository.fetch_agent_identity(agent_identity_id)

    async def get_active_agent_identity_for_system_agent(
        self,
        system_agent_id: UUID,
    ) -> AgentIdentity | None:
        if hasattr(self._repository, "fetch_active_agent_identity_for_system_agent"):
            return await self._repository.fetch_active_agent_identity_for_system_agent(
                system_agent_id
            )
        return None

    async def store_agent_identity(
        self,
        identity: AgentIdentity,
    ) -> AgentIdentityCommandResult:
        system_agent = await self._repository.fetch_system_agent(identity.system_agent_id)
        if system_agent is None:
            raise KeyError(f"System agent {identity.system_agent_id} not found")
        if system_agent.scope != identity.scope:
            raise ValueError("Agent identity scope must match the backing system agent scope")
        if system_agent.organization_id != identity.organization_id:
            raise ValueError("Agent identity organization binding must match the backing system agent")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_agent_identity(conn, identity)
        return AgentIdentityCommandResult(identity=identity)

    async def list_agent_roles_for_identity(
        self,
        *,
        agent_identity_id: UUID,
    ) -> list[IamRoleDefinition]:
        return await self._repository.list_agent_roles_for_identity(
            agent_identity_id=agent_identity_id
        )

    async def bind_agent_role(
        self,
        agent_identity_id: UUID,
        role_id: UUID,
        payload: BindAgentRoleRequest,
    ) -> dict[str, str]:
        identity = await self._repository.fetch_agent_identity(agent_identity_id)
        if identity is None:
            raise KeyError(f"Agent identity {agent_identity_id} not found")
        role = await self._repository.fetch_iam_role_definition(role_id)
        if role is None or role.subject_kind != "agent":
            raise KeyError(f"Agent IAM role {role_id} not found")
        if role.scope != identity.scope or role.organization_id != identity.organization_id:
            raise PermissionError("Agent IAM role scope must match the agent identity scope")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.bind_agent_role(
                    conn,
                    agent_identity_id=agent_identity_id,
                    role_id=role_id,
                    created_at=self._now(),
                    metadata=payload.metadata,
                )
        return {"agent_identity_id": str(agent_identity_id), "role_id": str(role_id)}

    async def unbind_agent_role(
        self,
        agent_identity_id: UUID,
        role_id: UUID,
    ) -> dict[str, bool | str]:
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.unbind_agent_role(
                    conn,
                    agent_identity_id=agent_identity_id,
                    role_id=role_id,
                )
        if not deleted:
            raise KeyError(
                f"Agent role binding identity={agent_identity_id} role={role_id} not found"
            )
        return {
            "deleted": True,
            "agent_identity_id": str(agent_identity_id),
            "role_id": str(role_id),
        }

    async def create_workspace(
        self,
        payload: CreateWorkspaceRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> WorkspaceCommandResult:
        logger.debug(
            "Kernel create_workspace participant_id=%s name=%r",
            payload.actor.participant_id,
            payload.name,
        )
        actor_user_id = self._actor_user_id(payload.actor)
        organization, project, project_requires_upsert = await self._resolve_workspace_location(
            requested_organization_id=payload.organization_id,
            requested_project_id=payload.project_id,
            actor=payload.actor,
        )
        if actor_user_id is not None and not allow_platform_admin:
            await self._require_organization_permission(
                organization.organization_id,
                actor_user_id,
                "workspace.list",
            )
        if not allow_platform_admin and not project_requires_upsert:
            await self._require_project_permission(
                project.project_id,
                payload.actor,
                permission="workspace.create",
            )
        workspace_id = uuid4()
        now = self._now()
        creator_subject = self._actor_project_subject(payload.actor)
        workspace = Workspace(
            workspace_id=workspace_id,
            organization_id=organization.organization_id,
            project_id=project.project_id,
            name=payload.name,
            description=payload.description,
            owner_user_id=actor_user_id,
            created_by=actor_user_id or payload.actor.participant_id,
            creator_user_id=creator_subject.user_id,
            creator_system_agent_id=creator_subject.system_agent_id,
            harness=payload.harness or WorkspaceHarness(),
            created_at=now,
            updated_at=now,
            metadata=self._workspace_metadata_for_create(
                metadata=payload.metadata,
                updated_by=payload.actor.participant_id,
                updated_at=now,
            ),
        )
        actor = self._actor_from_input(payload.actor)
        participant = self._participant_profile(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        ).model_copy(update={"roles": self._workspace_owner_roles(payload.actor.roles)})
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                if project_requires_upsert and hasattr(self._repository, "upsert_project"):
                    await self._repository.upsert_project(conn, project)
                    if hasattr(self._repository, "upsert_project_access_binding"):
                        await self._repository.upsert_project_access_binding(
                            conn,
                            self._project_access_binding(
                                project.project_id,
                                self._actor_project_subject(payload.actor),
                                "creator",
                                now=now,
                                metadata={"managed": True, "source": "default_project"},
                            ),
                        )
                await self._repository.upsert_workspace(conn, workspace)
                await self._repository.upsert_participant(conn, participant)
                anchor_participant = await self._ensure_anchor_attached_for_workspace(
                    conn,
                    workspace_id,
                    now=now,
                )

                events = [
                    await self._build_workspace_event(
                        conn,
                        workspace_id,
                        "workspace.created",
                        actor=actor,
                        target=TargetRef(type="workspace", id=workspace.workspace_id),
                        payload={
                            "workspace_id": str(workspace.workspace_id),
                            "name": workspace.name,
                            "description": workspace.description,
                            "organization_id": str(workspace.organization_id),
                            "project_id": str(workspace.project_id),
                            "owner_user_id": (
                                str(workspace.owner_user_id)
                                if workspace.owner_user_id is not None
                                else None
                            ),
                        },
                        timestamp=now,
                    ),
                    await self._build_workspace_event(
                        conn,
                        workspace_id,
                        "participant.registered",
                        actor=actor,
                        target=TargetRef(type="participant", id=participant.participant_id),
                        payload=participant.model_dump(mode="json"),
                        visibility="workspace",
                        timestamp=now,
                    ),
                    await self._build_workspace_event(
                        conn,
                        workspace_id,
                        "participant.registered",
                        actor=actor,
                        target=TargetRef(
                            type="participant",
                            id=anchor_participant.participant_id,
                        ),
                        payload=anchor_participant.model_dump(mode="json"),
                        visibility="workspace",
                        timestamp=now,
                    ),
                ]
                for event in events:
                    await self._repository.record_event(conn, event)

        detail = WorkspaceDetail(
            workspace=workspace,
            participants=[participant, anchor_participant],
            role_definitions=self._role_definitions_from_workspace(workspace),
            tools=[],
        )
        logger.debug(
            "Kernel create_workspace complete workspace_id=%s event_count=%s",
            workspace_id,
            len(events),
        )
        return WorkspaceCommandResult(workspace=workspace, detail=detail, events=events)

    async def list_workspaces(
        self,
        *,
        user_id: UUID | None = None,
        system_agent_id: UUID | None = None,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> list[Workspace]:
        if user_id is not None:
            try:
                return await self._repository.list_workspaces_for_user(
                    user_id,
                    organization_id=organization_id,
                    project_id=project_id,
                )
            except TypeError:
                return await self._repository.list_workspaces_for_user(user_id)
        if system_agent_id is not None and hasattr(self._repository, "list_workspaces_for_agent"):
            try:
                return await self._repository.list_workspaces_for_agent(
                    system_agent_id,
                    organization_id=organization_id,
                    project_id=project_id,
                )
            except TypeError:
                return await self._repository.list_workspaces_for_agent(system_agent_id)
        try:
            return await self._repository.list_workspaces(
                organization_id=organization_id,
                project_id=project_id,
            )
        except TypeError:
            return await self._repository.list_workspaces()

    async def delete_workspace(self, workspace_id: UUID, payload: DeleteWorkspaceRequest) -> dict[str, bool | str]:
        logger.debug(
            "Kernel delete_workspace workspace_id=%s participant_id=%s",
            workspace_id,
            payload.actor.participant_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_workspace(conn, workspace_id)
        if not deleted:
            raise KeyError(f"Workspace {workspace_id} not found")
        logger.debug("Kernel delete_workspace complete workspace_id=%s", workspace_id)
        return {"deleted": True, "workspace_id": str(workspace_id)}

    async def update_workspace(
        self,
        workspace_id: UUID,
        payload: UpdateWorkspaceRequest,
        *,
        skip_workspace_permission_check: bool = False,
    ) -> WorkspaceCommandResult:
        logger.debug(
            "Kernel update_workspace workspace_id=%s participant_id=%s",
            workspace_id,
            payload.actor.participant_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        if not skip_workspace_permission_check:
            await self._require_workspace_permission(
                workspace_id,
                payload.actor,
                permission="workspace.roles.write",
            )
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        updated = workspace.model_copy(
            update={
                "name": payload.name or workspace.name,
                "description": (
                    payload.description
                    if payload.description is not None
                    else workspace.description
                ),
                "harness": (
                    payload.harness
                    if "harness" in payload.model_fields_set
                    else workspace.harness
                ),
                "updated_at": now,
                "metadata": (
                    {**workspace.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else workspace.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace(conn, updated)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.updated",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=updated.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)

        detail = await self.get_workspace_detail(workspace_id)
        return WorkspaceCommandResult(workspace=updated, detail=detail, events=[event])

    async def get_workspace_detail(self, workspace_id: UUID) -> WorkspaceDetail:
        logger.debug("Kernel get_workspace_detail workspace_id=%s", workspace_id)
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        participants = await self._repository.list_participants(workspace_id)
        tools = await self._repository.list_workspace_tools(workspace_id)
        return WorkspaceDetail(
            workspace=workspace,
            participants=[
                self._advertise_workspace_tools(participant, tools)
                for participant in participants
            ],
            role_definitions=self._role_definitions_from_workspace(workspace),
            tools=tools,
        )

    async def list_workspace_participants(
        self, workspace_id: UUID
    ) -> list[ParticipantProfile]:
        logger.debug("Kernel list_workspace_participants workspace_id=%s", workspace_id)
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        tools = await self._repository.list_workspace_tools(workspace_id)
        participants = await self._repository.list_participants(workspace_id)
        return [
            self._advertise_workspace_tools(participant, tools)
            for participant in participants
        ]

    async def delete_participant(
        self,
        workspace_id: UUID,
        participant_id: UUID,
        payload: DeleteParticipantRequest,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Kernel delete_participant workspace_id=%s participant_id=%s actor_id=%s",
            workspace_id,
            participant_id,
            payload.actor.participant_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        participant = await self._repository.fetch_participant(workspace_id, participant_id)
        if participant is None:
            raise KeyError(f"Participant {participant_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_participant(
                    conn,
                    workspace_id=workspace_id,
                    participant_id=participant_id,
                )
                if not deleted:
                    raise KeyError(f"Participant {participant_id} not found")
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "participant.removed",
                    actor=actor,
                    target=TargetRef(type="participant", id=participant_id),
                    payload=participant.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return {
            "deleted": True,
            "workspace_id": str(workspace_id),
            "participant_id": str(participant_id),
        }

    async def create_system_agent(
        self,
        payload: CreateSystemAgentRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> AgentDefinitionCommandResult:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        now = self._now()
        interaction_contract = (
            build_default_interaction_contract(
                display_name=payload.display_name,
                role=payload.role,
                description=payload.description,
                capabilities=payload.capabilities,
            )
            if interaction_contract_is_empty(payload.interaction_contract)
            else payload.interaction_contract
        )
        agent = AgentDefinition(
            agent_id=uuid4(),
            scope=scope,
            organization_id=organization_id,
            display_name=payload.display_name,
            description=payload.description,
            role=payload.role,
            capabilities=payload.capabilities,
            endpoint=payload.endpoint,
            system_prompt=payload.system_prompt,
            harness=payload.harness,
            interaction_contract=interaction_contract,
            definition=payload.definition,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_agent(conn, agent)
        return AgentDefinitionCommandResult(agent=agent)

    async def delete_system_agent(self, agent_id: UUID, payload: DeleteSystemAgentRequest) -> dict[str, bool | str]:
        _ = payload
        existing = await self._repository.fetch_system_agent(agent_id)
        if existing is None:
            raise KeyError(f"System agent {agent_id} not found")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_system_agent(conn, agent_id=agent_id)
        if not deleted:
            raise KeyError(f"System agent {agent_id} not found")
        return {"deleted": True, "agent_id": str(agent_id)}

    async def list_system_agents(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[AgentDefinition]:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        try:
            return await self._repository.list_system_agents(
                scope=scope,
                organization_id=organization_id,
            )
        except TypeError:
            return await self._repository.list_system_agents()

    async def list_claimable_system_agents(self) -> list[AgentDefinition]:
        if hasattr(self._repository, "list_claimable_system_agents"):
            return await self._repository.list_claimable_system_agents()
        return await self.list_system_agents()

    async def list_workspace_catalog_agents(
        self,
        workspace_id: UUID,
    ) -> list[AgentDefinition]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        agents = await self._repository.list_system_agents(scope="global")
        agents.extend(
            await self._repository.list_system_agents(
                scope="organization",
                organization_id=workspace.organization_id,
            )
        )
        return agents

    async def publish_git_managed_agent_definition(
        self,
        *,
        compiled_agent: AgentDefinition,
        git_repository_id: UUID,
        git_commit_sha: str,
        bundle_path: str,
        manifest_sha256: str,
        prompt_asset_id: UUID | None = None,
        prompt_asset_version_id: UUID | None = None,
        skill_asset_refs: list[dict] | None = None,
        published_by: UUID,
        metadata: dict | None = None,
    ) -> tuple[AgentDefinition, AgentDefinitionVersion]:
        if not compiled_agent.agent_key:
            raise ValueError("Git-managed agent definitions require agent_key")
        self._validate_registry_scope(
            scope=compiled_agent.scope,
            organization_id=compiled_agent.organization_id,
        )
        now = self._now()
        existing = await self._repository.fetch_system_agent_by_key(
            scope=compiled_agent.scope,
            organization_id=compiled_agent.organization_id,
            agent_key=compiled_agent.agent_key,
        )
        agent_id = existing.agent_id if existing is not None else compiled_agent.agent_id
        existing_version = (
            await self._repository.fetch_agent_definition_version_by_source(
                agent_id=agent_id,
                git_repository_id=git_repository_id,
                git_commit_sha=git_commit_sha,
                bundle_path=bundle_path,
            )
            if existing is not None
            else None
        )
        if existing_version is not None:
            agent = compiled_agent.model_copy(
                update={
                    "agent_id": agent_id,
                    "active_agent_version_id": existing_version.agent_version_id,
                    "created_by": existing.created_by,
                    "created_at": existing.created_at,
                    "updated_at": now,
                    "metadata": {
                        **existing.metadata,
                        **compiled_agent.metadata,
                        "source": "git",
                        "active_agent_version_id": str(existing_version.agent_version_id),
                    },
                }
            )
            async with self._repository._pool.acquire() as conn:  # noqa: SLF001
                async with conn.transaction():
                    await self._repository.upsert_system_agent(conn, agent)
            return agent, existing_version

        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                version_number = await self._repository.next_agent_definition_version(
                    conn,
                    agent_id=agent_id,
                )
                version = AgentDefinitionVersion(
                    agent_version_id=uuid4(),
                    agent_id=agent_id,
                    version=version_number,
                    scope=compiled_agent.scope,
                    organization_id=compiled_agent.organization_id,
                    agent_key=compiled_agent.agent_key,
                    git_repository_id=git_repository_id,
                    git_commit_sha=git_commit_sha,
                    bundle_path=bundle_path,
                    manifest_sha256=manifest_sha256,
                    compiled_definition=compiled_agent.model_dump(mode="json"),
                    prompt_asset_id=prompt_asset_id,
                    prompt_asset_version_id=prompt_asset_version_id,
                    skill_asset_refs=skill_asset_refs or [],
                    published_by=published_by,
                    published_at=now,
                    metadata=metadata or {},
                )
                agent = compiled_agent.model_copy(
                    update={
                        "agent_id": agent_id,
                        "active_agent_version_id": version.agent_version_id,
                        "created_by": existing.created_by if existing is not None else compiled_agent.created_by,
                        "created_at": existing.created_at if existing is not None else compiled_agent.created_at,
                        "updated_at": now,
                        "metadata": {
                            **(existing.metadata if existing is not None else {}),
                            **compiled_agent.metadata,
                            "source": "git",
                            "active_agent_version_id": str(version.agent_version_id),
                        },
                    }
                )
                await self._repository.upsert_system_agent(conn, agent)
                await self._repository.upsert_agent_definition_version(conn, version)
        return agent, version

    async def list_agent_definition_versions(
        self,
        agent_id: UUID,
    ) -> list[AgentDefinitionVersion]:
        agent = await self._repository.fetch_system_agent(agent_id)
        if agent is None:
            raise KeyError(f"System agent {agent_id} not found")
        return await self._repository.list_agent_definition_versions(agent_id)

    async def activate_agent_definition_version(
        self,
        *,
        agent_id: UUID,
        agent_version_id: UUID,
        actor_id: UUID,
        metadata: dict | None = None,
    ) -> tuple[AgentDefinition, AgentDefinitionVersion]:
        _ = actor_id, metadata
        existing = await self._repository.fetch_system_agent(agent_id)
        if existing is None:
            raise KeyError(f"System agent {agent_id} not found")
        version = await self._repository.fetch_agent_definition_version(agent_version_id)
        if version is None or version.agent_id != agent_id:
            raise KeyError(
                f"Agent definition version {agent_version_id} does not belong to agent {agent_id}"
            )
        compiled = AgentDefinition.model_validate(version.compiled_definition)
        agent = compiled.model_copy(
            update={
                "agent_id": agent_id,
                "active_agent_version_id": agent_version_id,
                "created_by": existing.created_by,
                "created_at": existing.created_at,
                "updated_at": self._now(),
                "metadata": {
                    **existing.metadata,
                    **compiled.metadata,
                    "source": "git",
                    "active_agent_version_id": str(agent_version_id),
                    "activated_from_version": version.version,
                },
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_agent(conn, agent)
        return agent, version

    async def create_system_tool(
        self,
        payload: CreateSystemToolRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> SystemToolCommandResult:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        now = self._now()
        execution = payload.execution.model_copy(
            update={"handler_ref": payload.execution.handler_ref or payload.name}
        )
        self._validate_tool_execution_binding(execution)
        tool = SystemToolDefinition(
            tool_id=uuid4(),
            scope=scope,
            organization_id=organization_id,
            name=payload.name,
            description=payload.description,
            parameter_contract=payload.parameter_contract,
            input_schema=payload.input_schema,
            execution=execution,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_tool(conn, tool)
        return SystemToolCommandResult(tool=tool)

    async def delete_system_tool(self, tool_id: UUID, payload: DeleteSystemToolRequest) -> dict[str, bool | str]:
        _ = payload
        existing = await self._repository.fetch_system_tool(tool_id)
        if existing is None:
            raise KeyError(f"System tool {tool_id} not found")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_system_tool(conn, tool_id=tool_id)
        if not deleted:
            raise KeyError(f"System tool {tool_id} not found")
        return {"deleted": True, "tool_id": str(tool_id)}

    async def create_llm_provider(
        self,
        payload: CreateLlmProviderRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> LlmProviderCommandResult:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        now = self._now()
        provider = LlmProviderDefinition(
            provider_id=uuid4(),
            scope=scope,
            organization_id=organization_id,
            engine_id=payload.engine_id,
            display_name=payload.display_name,
            description=payload.description,
            provider=payload.provider,
            endpoint_kind=payload.endpoint_kind,
            url=payload.url,
            default_model=payload.default_model,
            capabilities=payload.capabilities,
            locality=payload.locality,
            priority=payload.priority,
            enabled=payload.enabled,
            secret_config=payload.secret_config,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        self._validate_llm_provider_definition(provider)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_llm_provider(conn, provider)
        return LlmProviderCommandResult(provider=provider)

    async def create_memory_provider(
        self,
        payload: CreateMemoryProviderRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> MemoryProviderCommandResult:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        now = self._now()
        provider = MemoryProviderDefinition(
            provider_id=uuid4(),
            scope=scope,
            organization_id=organization_id,
            provider_key=payload.provider_key,
            display_name=payload.display_name,
            description=payload.description,
            provider=payload.provider,
            enabled=payload.enabled,
            config=payload.config,
            secret_config=payload.secret_config,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_memory_provider(conn, provider)
        return MemoryProviderCommandResult(provider=provider)

    async def create_mcp_server(
        self,
        payload: CreateMcpServerRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> McpServerCommandResult:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        if payload.transport_kind == "stdio" and payload.trust_level != "trusted":
            raise ValueError("stdio MCP servers require trust_level='trusted'")
        now = self._now()
        server = McpServerDefinition(
            server_id=uuid4(),
            scope=scope,
            organization_id=organization_id,
            server_key=payload.server_key,
            display_name=payload.display_name,
            description=payload.description,
            transport_kind=payload.transport_kind,
            config=payload.config,
            secret_config=payload.secret_config,
            trust_level=payload.trust_level,
            enabled=payload.enabled,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_mcp_server(conn, server)
        return McpServerCommandResult(server=server)

    async def list_mcp_servers(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[McpServerDefinition]:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        return await self._repository.list_mcp_servers(
            scope=scope,
            organization_id=organization_id,
        )

    async def list_workspace_catalog_mcp_servers(
        self,
        workspace_id: UUID,
    ) -> list[McpServerDefinition]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        servers = await self._repository.list_mcp_servers(scope="global")
        servers.extend(
            await self._repository.list_mcp_servers(
                scope="organization",
                organization_id=workspace.organization_id,
            )
        )
        return servers

    async def get_mcp_server(self, server_id: UUID) -> McpServerDefinition | None:
        return await self._repository.fetch_mcp_server(server_id)

    async def update_mcp_server(
        self,
        server_id: UUID,
        payload: UpdateMcpServerRequest,
    ) -> McpServerCommandResult:
        existing = await self._repository.fetch_mcp_server(server_id)
        if existing is None:
            raise KeyError(f"MCP server {server_id} not found")
        transport_kind = payload.transport_kind or existing.transport_kind
        trust_level = payload.trust_level or existing.trust_level
        if transport_kind == "stdio" and trust_level != "trusted":
            raise ValueError("stdio MCP servers require trust_level='trusted'")
        now = self._now()
        updated = existing.model_copy(
            update={
                "server_key": payload.server_key or existing.server_key,
                "display_name": payload.display_name or existing.display_name,
                "description": payload.description or existing.description,
                "transport_kind": transport_kind,
                "config": existing.config if payload.config is None else payload.config,
                "secret_config": (
                    existing.secret_config
                    if payload.secret_config is None
                    else payload.secret_config
                ),
                "trust_level": trust_level,
                "enabled": existing.enabled if payload.enabled is None else payload.enabled,
                "updated_by": payload.actor.participant_id,
                "updated_at": now,
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_mcp_server(conn, updated)
        return McpServerCommandResult(server=updated)

    async def delete_mcp_server(
        self,
        server_id: UUID,
        payload: DeleteMcpServerRequest,
    ) -> dict[str, bool | str]:
        _ = payload
        existing = await self._repository.fetch_mcp_server(server_id)
        if existing is None:
            raise KeyError(f"MCP server {server_id} not found")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_mcp_server(conn, server_id=server_id)
        if not deleted:
            raise KeyError(f"MCP server {server_id} not found")
        return {"deleted": True, "server_id": str(server_id)}

    async def list_mcp_server_tools(self, server_id: UUID) -> list[McpToolDefinition]:
        if await self._repository.fetch_mcp_server(server_id) is None:
            raise KeyError(f"MCP server {server_id} not found")
        return await self._repository.list_mcp_server_tools(server_id)

    async def list_mcp_server_resources(self, server_id: UUID) -> list[McpResourceDefinition]:
        if await self._repository.fetch_mcp_server(server_id) is None:
            raise KeyError(f"MCP server {server_id} not found")
        return await self._repository.list_mcp_server_resources(server_id)

    async def list_mcp_server_prompts(self, server_id: UUID) -> list[McpPromptDefinition]:
        if await self._repository.fetch_mcp_server(server_id) is None:
            raise KeyError(f"MCP server {server_id} not found")
        return await self._repository.list_mcp_server_prompts(server_id)

    async def request_mcp_server_sync(
        self,
        server_id: UUID,
        payload: RequestMcpServerSyncRequest,
    ) -> McpServerSyncResult:
        existing = await self._repository.fetch_mcp_server(server_id)
        if existing is None:
            raise KeyError(f"MCP server {server_id} not found")
        now = self._now()
        job = McpServerSyncJob(
            job_id=uuid4(),
            server_id=server_id,
            status="created",
            requested_by=payload.actor.participant_id,
            requested_at=now,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.create_mcp_server_sync_job(conn, job)
                server = await self._repository.update_mcp_server_sync_status(
                    conn,
                    server_id=server_id,
                    status="queued",
                    error=None,
                    synced_at=None,
                    updated_at=now,
                )
        if server is None:
            raise KeyError(f"MCP server {server_id} not found")
        return McpServerSyncResult(server=server, job=job)

    async def list_mcp_server_sync_jobs(
        self,
        server_id: UUID,
        *,
        limit: int = 20,
    ) -> list[McpServerSyncJob]:
        if await self._repository.fetch_mcp_server(server_id) is None:
            raise KeyError(f"MCP server {server_id} not found")
        return await self._repository.list_mcp_server_sync_jobs(
            server_id=server_id,
            limit=max(1, min(limit, 100)),
        )

    async def claim_next_mcp_server_sync_job(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> McpServerSyncJob | None:
        now = self._now()
        return await self._repository.claim_next_mcp_server_sync_job(
            worker_id=worker_id,
            now=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )

    async def heartbeat_mcp_server_sync_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> McpServerSyncJob | None:
        now = self._now()
        return await self._repository.heartbeat_mcp_server_sync_job(
            job_id=job_id,
            worker_id=worker_id,
            now=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )

    async def complete_mcp_server_sync_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        tools: list[McpToolDefinition],
        resources: list[McpResourceDefinition],
        prompts: list[McpPromptDefinition],
        metadata: dict | None = None,
    ) -> McpServerSyncResult:
        job = await self._repository.fetch_mcp_server_sync_job(job_id)
        if job is None:
            raise KeyError(f"MCP server sync job {job_id} not found")
        now = self._now()
        tools = [tool.model_copy(update={"server_id": job.server_id}) for tool in tools]
        resources = [
            resource.model_copy(update={"server_id": job.server_id}) for resource in resources
        ]
        prompts = [prompt.model_copy(update={"server_id": job.server_id}) for prompt in prompts]
        result = {
            "tool_count": len(tools),
            "resource_count": len(resources),
            "prompt_count": len(prompts),
            **(metadata or {}),
        }
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.replace_mcp_server_capabilities(
                    conn,
                    server_id=job.server_id,
                    tools=tools,
                    resources=resources,
                    prompts=prompts,
                )
                completed = await self._repository.complete_mcp_server_sync_job(
                    conn,
                    job_id=job_id,
                    worker_id=worker_id,
                    result=result,
                    now=now,
                )
                if completed is None:
                    raise RuntimeError(
                        f"MCP server sync job {job_id} is not claimed by worker {worker_id}"
                    )
                server = await self._repository.update_mcp_server_sync_status(
                    conn,
                    server_id=job.server_id,
                    status="completed",
                    error=None,
                    synced_at=now,
                    updated_at=now,
                )
        if server is None:
            raise KeyError(f"MCP server {job.server_id} not found")
        return McpServerSyncResult(server=server, job=completed)

    async def fail_mcp_server_sync_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        error: str,
    ) -> McpServerSyncResult:
        job = await self._repository.fetch_mcp_server_sync_job(job_id)
        if job is None:
            raise KeyError(f"MCP server sync job {job_id} not found")
        now = self._now()
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                failed = await self._repository.fail_mcp_server_sync_job(
                    conn,
                    job_id=job_id,
                    worker_id=worker_id,
                    error=error,
                    now=now,
                )
                if failed is None:
                    raise RuntimeError(
                        f"MCP server sync job {job_id} is not claimed by worker {worker_id}"
                    )
                server = await self._repository.update_mcp_server_sync_status(
                    conn,
                    server_id=job.server_id,
                    status="failed",
                    error=error,
                    synced_at=None,
                    updated_at=now,
                )
        if server is None:
            raise KeyError(f"MCP server {job.server_id} not found")
        return McpServerSyncResult(server=server, job=failed)

    async def list_system_tools(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[SystemToolDefinition]:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        try:
            return await self._repository.list_system_tools_by_scope(
                scope=scope,
                organization_id=organization_id,
            )
        except AttributeError:
            return await self._repository.list_system_tools()
        except TypeError:
            return await self._repository.list_system_tools()

    async def list_workspace_catalog_tools(
        self,
        workspace_id: UUID,
    ) -> list[SystemToolDefinition]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        tools = await self._repository.list_system_tools_by_scope(scope="global")
        tools.extend(
            await self._repository.list_system_tools_by_scope(
                scope="organization",
                organization_id=workspace.organization_id,
            )
        )
        return tools

    async def list_llm_providers(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[LlmProviderDefinition]:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        try:
            return await self._repository.list_llm_providers(
                scope=scope,
                organization_id=organization_id,
            )
        except TypeError:
            return await self._repository.list_llm_providers()

    async def list_memory_providers(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[MemoryProviderDefinition]:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        try:
            return await self._repository.list_memory_providers(
                scope=scope,
                organization_id=organization_id,
            )
        except TypeError:
            return await self._repository.list_memory_providers()

    async def get_llm_provider(self, provider_id: UUID) -> LlmProviderDefinition | None:
        return await self._repository.fetch_llm_provider(provider_id)

    async def get_memory_provider(
        self, provider_id: UUID
    ) -> MemoryProviderDefinition | None:
        return await self._repository.fetch_memory_provider(provider_id)

    async def update_system_tool(
        self, tool_id: UUID, payload: UpdateSystemToolRequest
    ) -> SystemToolCommandResult:
        existing = await self._repository.fetch_system_tool(tool_id)
        if existing is None:
            raise KeyError(f"System tool {tool_id} not found")
        updated = existing.model_copy(
            update={
                "name": payload.name or existing.name,
                "description": payload.description or existing.description,
                "parameter_contract": (
                    payload.parameter_contract
                    if payload.parameter_contract is not None
                    else existing.parameter_contract
                ),
                "input_schema": (
                    payload.input_schema
                    if payload.input_schema is not None
                    else existing.input_schema
                ),
                "execution": (
                    payload.execution.model_copy(
                        update={
                            "handler_ref": payload.execution.handler_ref
                            or payload.name
                            or existing.name
                        }
                    )
                    if payload.execution is not None
                    else existing.execution
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": self._now(),
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        self._validate_tool_execution_binding(updated.execution)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_tool(conn, updated)
        return SystemToolCommandResult(tool=updated)

    async def update_llm_provider(
        self, provider_id: UUID, payload: UpdateLlmProviderRequest
    ) -> LlmProviderCommandResult:
        existing = await self._repository.fetch_llm_provider(provider_id)
        if existing is None:
            raise KeyError(f"LLM provider {provider_id} not found")
        references = await self._llm_provider_references(existing.engine_id)
        if payload.engine_id is not None and payload.engine_id != existing.engine_id and references:
            raise ValueError(
                f"Cannot rename LLM provider engine_id {existing.engine_id!r}; "
                f"referenced by system agents: {', '.join(agent.display_name for agent in references)}"
            )
        if existing.enabled and payload.enabled is False and references:
            raise ValueError(
                f"Cannot disable LLM provider {existing.engine_id!r}; "
                f"referenced by system agents: {', '.join(agent.display_name for agent in references)}"
            )
        updated = existing.model_copy(
            update={
                "engine_id": payload.engine_id or existing.engine_id,
                "display_name": payload.display_name or existing.display_name,
                "description": payload.description or existing.description,
                "provider": payload.provider or existing.provider,
                "endpoint_kind": payload.endpoint_kind or existing.endpoint_kind,
                "url": payload.url if payload.url is not None else existing.url,
                "default_model": (
                    payload.default_model
                    if payload.default_model is not None
                    else existing.default_model
                ),
                "capabilities": (
                    payload.capabilities
                    if payload.capabilities is not None
                    else existing.capabilities
                ),
                "locality": payload.locality or existing.locality,
                "priority": payload.priority if payload.priority is not None else existing.priority,
                "enabled": payload.enabled if payload.enabled is not None else existing.enabled,
                "secret_config": (
                    payload.secret_config
                    if payload.secret_config is not None
                    else existing.secret_config
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": self._now(),
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        self._validate_llm_provider_definition(updated)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_llm_provider(conn, updated)
        return LlmProviderCommandResult(provider=updated)

    async def update_memory_provider(
        self, provider_id: UUID, payload: UpdateMemoryProviderRequest
    ) -> MemoryProviderCommandResult:
        existing = await self._repository.fetch_memory_provider(provider_id)
        if existing is None:
            raise KeyError(f"Memory provider {provider_id} not found")
        updated = existing.model_copy(
            update={
                "provider_key": payload.provider_key or existing.provider_key,
                "display_name": payload.display_name or existing.display_name,
                "description": payload.description or existing.description,
                "provider": payload.provider or existing.provider,
                "enabled": payload.enabled if payload.enabled is not None else existing.enabled,
                "config": payload.config if payload.config is not None else existing.config,
                "secret_config": (
                    payload.secret_config
                    if payload.secret_config is not None
                    else existing.secret_config
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": self._now(),
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_memory_provider(conn, updated)
        return MemoryProviderCommandResult(provider=updated)

    async def update_system_agent(
        self, agent_id: UUID, payload: UpdateSystemAgentRequest
    ) -> AgentDefinitionCommandResult:
        existing = await self._repository.fetch_system_agent(agent_id)
        if existing is None:
            raise KeyError(f"System agent {agent_id} not found")
        interaction_contract = (
            payload.interaction_contract
            if payload.interaction_contract is not None
            else existing.interaction_contract
        )
        updated = existing.model_copy(
            update={
                "display_name": payload.display_name or existing.display_name,
                "description": payload.description or existing.description,
                "role": payload.role or existing.role,
                "capabilities": payload.capabilities or existing.capabilities,
                "endpoint": payload.endpoint or existing.endpoint,
                "system_prompt": payload.system_prompt or existing.system_prompt,
                "harness": (
                    payload.harness
                    if "harness" in payload.model_fields_set
                    else existing.harness
                ),
                "interaction_contract": interaction_contract,
                "definition": payload.definition if payload.definition is not None else existing.definition,
                "updated_at": self._now(),
                "metadata": {**existing.metadata, **payload.metadata} if payload.metadata is not None else existing.metadata,
            }
        )
        if interaction_contract_is_empty(updated.interaction_contract):
            updated = updated.model_copy(
                update={
                    "interaction_contract": build_default_interaction_contract(
                        display_name=updated.display_name,
                        role=updated.role,
                        description=updated.description,
                        capabilities=updated.capabilities,
                    )
                }
            )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_agent(conn, updated)
        return AgentDefinitionCommandResult(agent=updated)

    async def create_git_repository(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None,
        payload: CreateGitRepositoryRequest,
    ) -> GitRepositoryCommandResult:
        organization = await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if scope == "workspace" and project_id is None and workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            project_id = workspace.project_id
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            await self._require_workspace_permission(
                workspace_id,
                payload.actor,
                permission="workspace.repositories.write",
            )
        now = self._now()
        repository = GitRepository(
            repo_id=uuid4(),
            organization_id=organization.organization_id if organization is not None else None,
            workspace_id=workspace_id,
            scope=scope,
            name=payload.name,
            forgejo_url=payload.forgejo_url,
            clone_url=payload.clone_url,
            local_path=payload.local_path,
            default_branch=payload.default_branch,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_git_repository(conn, repository)
        return GitRepositoryCommandResult(repository=repository)

    async def list_git_repositories(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[GitRepository]:
        await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_git_repositories(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def get_git_repository(self, repo_id: UUID) -> GitRepository | None:
        return await self._repository.fetch_git_repository(repo_id)

    async def publish_asset_from_git(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: PublishAssetFromGitRequest,
        storage_backend: str,
        bucket: str,
        object_key: str,
        size_bytes: int,
        sha256: str,
        content_type: str | None,
    ) -> WorkspaceAssetCommandResult:
        organization = await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if scope == "workspace" and project_id is None and workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            project_id = workspace.project_id
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            await self._require_workspace_permission(
                workspace_id,
                payload.actor,
                permission="workspace.assets.publish",
            )
        repository = await self._repository.fetch_git_repository(payload.repository_id)
        if repository is None:
            raise KeyError(f"Git repository {payload.repository_id} not found")
        if repository.scope != scope:
            raise ValueError(
                f"Repository {repository.repo_id} scope {repository.scope!r} does not match asset scope {scope!r}"
            )
        if repository.organization_id != (
            organization.organization_id if organization is not None else None
        ):
            raise ValueError(
                f"Repository {repository.repo_id} organization binding does not match asset organization scope"
            )
        if repository.workspace_id != workspace_id:
            raise ValueError(
                f"Repository {repository.repo_id} workspace binding does not match asset workspace scope"
            )
        now = self._now()
        asset = await self._repository.fetch_workspace_asset_by_logical_name(
            scope=scope,
            organization_id=organization.organization_id if organization is not None else None,
            project_id=project_id,
            workspace_id=workspace_id,
            logical_name=payload.logical_name,
        )
        if asset is None:
            asset = WorkspaceAsset(
                asset_id=uuid4(),
                organization_id=organization.organization_id if organization is not None else None,
                project_id=project_id,
                workspace_id=workspace_id,
                scope=scope,
                asset_type=payload.asset_type,
                logical_name=payload.logical_name,
                logical_path=payload.logical_path,
                title=payload.title,
                description=payload.description,
                created_by=payload.actor.participant_id,
                created_at=now,
                updated_at=now,
                metadata=payload.metadata,
            )
        else:
            asset = asset.model_copy(
                update={
                    "asset_type": payload.asset_type,
                    "logical_path": payload.logical_path,
                    "title": payload.title,
                    "description": payload.description,
                    "updated_at": now,
                    "metadata": {**asset.metadata, **payload.metadata},
                }
            )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace_asset(conn, asset)
                version_number = await self._repository.next_workspace_asset_version(
                    conn,
                    asset_id=asset.asset_id,
                )
                version = WorkspaceAssetVersion(
                    asset_version_id=uuid4(),
                    asset_id=asset.asset_id,
                    version=version_number,
                    source_kind="git_publish",
                    git_repository_id=repository.repo_id,
                    git_revision=payload.revision,
                    git_path=payload.git_path,
                    storage_backend=storage_backend,
                    bucket=bucket,
                    object_key=object_key,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    created_by=payload.actor.participant_id,
                    created_at=now,
                    metadata={
                        **payload.metadata,
                        "repository_name": repository.name,
                    },
                )
                await self._repository.upsert_workspace_asset_version(conn, version)
        return WorkspaceAssetCommandResult(asset=asset, version=version)

    async def publish_asset_from_upload(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: UploadFileAssetRequest,
        storage_backend: str,
        bucket: str,
        object_key: str,
        size_bytes: int,
        sha256: str,
        content_type: str | None,
    ) -> WorkspaceAssetCommandResult:
        organization = await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if scope == "workspace" and project_id is None and workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            project_id = workspace.project_id
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            await self._require_workspace_permission(
                workspace_id,
                payload.actor,
                permission="workspace.assets.publish",
            )
        now = self._now()
        asset = await self._repository.fetch_workspace_asset_by_logical_name(
            scope=scope,
            organization_id=organization.organization_id if organization is not None else None,
            project_id=project_id,
            workspace_id=workspace_id,
            logical_name=payload.logical_name,
        )
        if asset is None:
            asset = WorkspaceAsset(
                asset_id=uuid4(),
                organization_id=organization.organization_id if organization is not None else None,
                project_id=project_id,
                workspace_id=workspace_id,
                scope=scope,
                asset_type=payload.asset_type,
                logical_name=payload.logical_name,
                logical_path=payload.logical_path,
                title=payload.title,
                description=payload.description,
                created_by=payload.actor.participant_id,
                created_at=now,
                updated_at=now,
                metadata=payload.metadata,
            )
        else:
            asset = asset.model_copy(
                update={
                    "asset_type": payload.asset_type,
                    "logical_path": payload.logical_path,
                    "title": payload.title,
                    "description": payload.description,
                    "updated_at": now,
                    "metadata": {**asset.metadata, **payload.metadata},
                }
            )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace_asset(conn, asset)
                version_number = await self._repository.next_workspace_asset_version(
                    conn,
                    asset_id=asset.asset_id,
                )
                version = WorkspaceAssetVersion(
                    asset_version_id=uuid4(),
                    asset_id=asset.asset_id,
                    version=version_number,
                    source_kind="direct_upload",
                    git_repository_id=None,
                    git_revision=None,
                    git_path=None,
                    storage_backend=storage_backend,
                    bucket=bucket,
                    object_key=object_key,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    created_by=payload.actor.participant_id,
                    created_at=now,
                    metadata=payload.metadata,
                )
                await self._repository.upsert_workspace_asset_version(conn, version)
        return WorkspaceAssetCommandResult(asset=asset, version=version)

    async def list_workspace_assets(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[WorkspaceAsset]:
        if scope is not None:
            await self._resolve_scope_organization(
                scope=scope,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
            )
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_workspace_assets(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )

    async def list_workspace_asset_versions(
        self,
        asset_id: UUID,
    ) -> list[WorkspaceAssetVersion]:
        asset = await self._repository.fetch_workspace_asset(asset_id)
        if asset is None:
            raise KeyError(f"Workspace asset {asset_id} not found")
        return await self._repository.list_workspace_asset_versions(asset_id)

    async def get_workspace_asset(self, asset_id: UUID) -> WorkspaceAsset | None:
        return await self._repository.fetch_workspace_asset(asset_id)

    async def get_workspace_asset_version(
        self,
        asset_version_id: UUID,
    ) -> WorkspaceAssetVersion | None:
        return await self._repository.fetch_workspace_asset_version(asset_version_id)

    async def create_library(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: CreateLibraryRequest,
    ) -> LibraryCommandResult:
        owner = await self._resolve_library_owner(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        now = self._now()
        slug = self._normalize_library_slug(payload.slug or payload.name)
        library = Library(
            library_id=uuid4(),
            scope=scope,
            organization_id=owner[0],
            project_id=owner[1],
            workspace_id=owner[2],
            slug=slug,
            name=payload.name,
            description=payload.description,
            status="active",
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            await self._repository.upsert_library(conn, library)
        return LibraryCommandResult(library=library)

    async def list_libraries(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        include_archived: bool = False,
        include_workspace_attachments: bool = False,
    ) -> list[Library]:
        if scope is not None:
            await self._resolve_library_owner(
                scope=scope,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
            )
        elif workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_libraries(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            include_archived=include_archived,
            include_workspace_attachments=include_workspace_attachments,
        )

    async def get_library(self, library_id: UUID) -> Library | None:
        return await self._repository.fetch_library(library_id)

    async def update_library(
        self,
        library_id: UUID,
        payload: UpdateLibraryRequest,
    ) -> LibraryCommandResult:
        existing = await self._repository.fetch_library(library_id)
        if existing is None:
            raise KeyError(f"Library {library_id} not found")
        update: dict[str, object] = {
            "updated_by": payload.actor.participant_id,
            "updated_at": self._now(),
        }
        if payload.slug is not None:
            update["slug"] = self._normalize_library_slug(payload.slug)
        if payload.name is not None:
            update["name"] = payload.name
        if payload.description is not None:
            update["description"] = payload.description
        if payload.status is not None:
            update["status"] = payload.status
        if payload.metadata is not None:
            update["metadata"] = {**existing.metadata, **payload.metadata}
        library = existing.model_copy(update=update)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            await self._repository.upsert_library(conn, library)
        return LibraryCommandResult(library=library)

    async def delete_library(
        self,
        library_id: UUID,
        payload: DeleteLibraryRequest,
    ) -> dict[str, bool | str]:
        await self.update_library(
            library_id,
            UpdateLibraryRequest(
                actor=payload.actor,
                status="archived",
                metadata=payload.metadata,
            ),
        )
        return {"deleted": True, "library_id": str(library_id)}

    async def create_library_item(
        self,
        library_id: UUID,
        payload: CreateLibraryItemRequest,
    ) -> LibraryCommandResult:
        library = await self._repository.fetch_library(library_id)
        if library is None:
            raise KeyError(f"Library {library_id} not found")
        if library.status == "archived":
            raise ValueError(f"Library {library_id} is archived")
        asset = await self._repository.fetch_workspace_asset(payload.asset_id)
        if asset is None:
            raise KeyError(f"Workspace asset {payload.asset_id} not found")
        self._require_same_retrieval_scope(
            left_name="Workspace asset",
            left_id=asset.asset_id,
            left_scope=asset.scope,
            left_organization_id=asset.organization_id,
            left_workspace_id=asset.workspace_id,
            right_scope=library.scope,
            right_organization_id=library.organization_id,
            right_workspace_id=library.workspace_id,
            left_project_id=asset.project_id,
            right_project_id=library.project_id,
        )
        asset_version = await self._resolve_asset_version_for_source(
            asset_id=asset.asset_id,
            asset_version_id=payload.asset_version_id,
        )
        now = self._now()
        item = LibraryItem(
            item_id=uuid4(),
            library_id=library.library_id,
            asset_id=asset.asset_id,
            active_asset_version_id=asset_version.asset_version_id,
            item_kind=payload.item_kind,
            title=payload.title,
            source_uri=payload.source_uri,
            content_type=payload.content_type or asset_version.content_type,
            status="active",
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            await self._repository.upsert_library_item(conn, item)
        return LibraryCommandResult(library=library, item=item)

    async def list_library_items(
        self,
        library_id: UUID,
        *,
        include_archived: bool = False,
    ) -> list[LibraryItem]:
        if await self._repository.fetch_library(library_id) is None:
            raise KeyError(f"Library {library_id} not found")
        return await self._repository.list_library_items(
            library_id,
            include_archived=include_archived,
        )

    async def get_library_item(self, item_id: UUID) -> LibraryItem | None:
        return await self._repository.fetch_library_item(item_id)

    async def update_library_item(
        self,
        item_id: UUID,
        payload: UpdateLibraryItemRequest,
    ) -> LibraryCommandResult:
        existing = await self._repository.fetch_library_item(item_id)
        if existing is None:
            raise KeyError(f"Library item {item_id} not found")
        update: dict[str, object] = {
            "updated_by": payload.actor.participant_id,
            "updated_at": self._now(),
        }
        if payload.title is not None:
            update["title"] = payload.title
        if payload.status is not None:
            update["status"] = payload.status
        if payload.metadata is not None:
            update["metadata"] = {**existing.metadata, **payload.metadata}
        item = existing.model_copy(update=update)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            await self._repository.upsert_library_item(conn, item)
        return LibraryCommandResult(item=item)

    async def attach_library_to_workspace(
        self,
        workspace_id: UUID,
        library_id: UUID,
        payload: AttachLibraryToWorkspaceRequest,
    ) -> LibraryCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        library = await self._repository.fetch_library(library_id)
        if library is None:
            raise KeyError(f"Library {library_id} not found")
        if library.scope == "workspace":
            raise ValueError("Workspace-owned libraries do not need explicit workspace attachment")
        if library.organization_id != workspace.organization_id:
            raise ValueError("Library and workspace must belong to the same organization")
        if library.scope == "project" and library.project_id != workspace.project_id:
            raise ValueError("Project library can only attach to workspaces in the same project")
        now = self._now()
        existing = await self._repository.fetch_library_workspace_attachment(
            workspace_id=workspace_id,
            library_id=library_id,
        )
        attachment = LibraryWorkspaceAttachment(
            attachment_id=existing.attachment_id if existing is not None else uuid4(),
            library_id=library.library_id,
            workspace_id=workspace.workspace_id,
            organization_id=workspace.organization_id,
            project_id=workspace.project_id,
            enabled=payload.enabled,
            attached_by=existing.attached_by if existing is not None else payload.actor.participant_id,
            attached_at=existing.attached_at if existing is not None else now,
            updated_at=now,
            metadata={
                **(existing.metadata if existing is not None else {}),
                **payload.metadata,
            },
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            await self._repository.upsert_library_workspace_attachment(conn, attachment)
        return LibraryCommandResult(library=library, attachment=attachment)

    async def delete_library_workspace_attachment(
        self,
        workspace_id: UUID,
        library_id: UUID,
    ) -> dict[str, bool | str]:
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            deleted = await self._repository.delete_library_workspace_attachment(
                conn,
                workspace_id=workspace_id,
                library_id=library_id,
            )
        if not deleted:
            raise KeyError(f"Library attachment {library_id} not found in workspace {workspace_id}")
        return {"deleted": True, "workspace_id": str(workspace_id), "library_id": str(library_id)}

    async def index_library(
        self,
        library_id: UUID,
        payload: IndexLibraryRequest,
    ) -> LibraryCommandResult:
        library = await self._repository.fetch_library(library_id)
        if library is None:
            raise KeyError(f"Library {library_id} not found")
        if library.status == "archived":
            raise ValueError(f"Library {library_id} is archived")
        items = await self._repository.list_library_items(
            library_id,
            item_ids=payload.item_ids or None,
            include_archived=False,
        )
        if payload.item_ids and len(items) != len(set(payload.item_ids)):
            found = {item.item_id for item in items}
            missing = [str(item_id) for item_id in payload.item_ids if item_id not in found]
            raise KeyError(f"Library items not found: {missing}")
        if not items:
            return LibraryCommandResult(library=library, jobs=[])
        now = self._now()
        if payload.profile_id is not None:
            profile = await self._repository.fetch_retrieval_profile(payload.profile_id)
            if profile is None:
                raise KeyError(f"Retrieval profile {payload.profile_id} not found")
            self._require_same_retrieval_scope(
                left_name="Retrieval profile",
                left_id=profile.profile_id,
                left_scope=profile.scope,
                left_organization_id=profile.organization_id,
                left_workspace_id=profile.workspace_id,
                right_scope=library.scope,
                right_organization_id=library.organization_id,
                right_workspace_id=library.workspace_id,
                left_project_id=profile.project_id,
                right_project_id=library.project_id,
            )
        existing_corpus = find_library_corpus(
            await self._repository.list_retrieval_corpora(
                scope=library.scope,
                organization_id=library.organization_id,
                project_id=library.project_id,
                workspace_id=library.workspace_id,
            ),
            library,
        )
        corpus = build_library_corpus(
            library=library,
            existing_corpus=existing_corpus,
            profile_id=payload.profile_id,
            actor_id=payload.actor.participant_id,
            now=now,
        )
        jobs: list[RetrievalIngestionJob] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_retrieval_corpus(conn, corpus)
                for item in items:
                    record = build_library_index_record(
                        library=library,
                        item=item,
                        corpus=corpus,
                        source_version_number=await self._repository.next_retrieval_source_version(
                            conn,
                            source_id=library_item_source_id(item.item_id),
                        ),
                        profile_id=payload.profile_id,
                        actor_id=payload.actor.participant_id,
                        now=now,
                        metadata=payload.metadata,
                    )
                    await self._repository.upsert_retrieval_source(conn, record.source)
                    await self._repository.upsert_retrieval_source_version(
                        conn,
                        record.source_version,
                    )
                    await self._repository.upsert_retrieval_ingestion_job(conn, record.job)
                    await self._repository.upsert_retrieval_source_version(
                        conn,
                        bind_source_version_to_job(record.source_version, record.job),
                    )
                    jobs.append(record.job)
        return LibraryCommandResult(library=library, jobs=jobs)

    async def create_retrieval_profile(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: CreateRetrievalProfileRequest,
    ) -> RetrievalCommandResult:
        organization = await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if scope == "workspace" and project_id is None and workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            project_id = workspace.project_id
        now = self._now()
        profile = RetrievalProfile(
            profile_id=uuid4(),
            scope=scope,
            organization_id=organization.organization_id if organization is not None else None,
            project_id=project_id,
            workspace_id=workspace_id,
            name=payload.name,
            description=payload.description,
            embedding_provider_key=payload.embedding_provider_key,
            embedding_model=payload.embedding_model,
            embedding_dimension=payload.embedding_dimension,
            vision_provider_key=payload.vision_provider_key,
            vision_model=payload.vision_model,
            visual_extraction_enabled=payload.visual_extraction_enabled,
            vector_store_provider_key=payload.vector_store_provider_key,
            chunking_strategy=payload.chunking_strategy,
            chunk_size_tokens=payload.chunk_size_tokens,
            chunk_overlap_tokens=payload.chunk_overlap_tokens,
            search_strategy=payload.search_strategy,
            vector_weight=payload.vector_weight,
            keyword_weight=payload.keyword_weight,
            top_k=payload.top_k,
            reranker_provider_key=payload.reranker_provider_key,
            reranker_model=payload.reranker_model,
            context_token_budget=payload.context_token_budget,
            citation_strictness=payload.citation_strictness,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            await self._repository.upsert_retrieval_profile(conn, profile)
        return RetrievalCommandResult(profile=profile)

    async def list_retrieval_profiles(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[RetrievalProfile]:
        if scope is not None:
            await self._resolve_scope_organization(
                scope=scope,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
            )
        return await self._repository.list_retrieval_profiles(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )

    async def get_retrieval_profile(
        self, profile_id: UUID
    ) -> RetrievalProfile | None:
        return await self._repository.fetch_retrieval_profile(profile_id)

    async def create_retrieval_corpus(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: CreateRetrievalCorpusRequest,
    ) -> RetrievalCommandResult:
        organization = await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if scope == "workspace" and project_id is None and workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            project_id = workspace.project_id
        if payload.default_profile_id is not None:
            profile = await self._repository.fetch_retrieval_profile(
                payload.default_profile_id
            )
            if profile is None:
                raise KeyError(f"Retrieval profile {payload.default_profile_id} not found")
            self._require_same_retrieval_scope(
                left_name="Retrieval profile",
                left_id=profile.profile_id,
                left_scope=profile.scope,
                left_organization_id=profile.organization_id,
                left_workspace_id=profile.workspace_id,
                right_scope=scope,
                right_organization_id=organization.organization_id if organization else None,
                right_workspace_id=workspace_id,
                left_project_id=profile.project_id,
                right_project_id=project_id,
            )
        now = self._now()
        corpus = RetrievalCorpus(
            corpus_id=uuid4(),
            scope=scope,
            organization_id=organization.organization_id if organization is not None else None,
            project_id=project_id,
            workspace_id=workspace_id,
            name=payload.name,
            description=payload.description,
            default_profile_id=payload.default_profile_id,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            await self._repository.upsert_retrieval_corpus(conn, corpus)
        return RetrievalCommandResult(corpus=corpus)

    async def list_retrieval_corpora(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[RetrievalCorpus]:
        if scope is not None:
            await self._resolve_scope_organization(
                scope=scope,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
            )
        return await self._repository.list_retrieval_corpora(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )

    async def get_retrieval_corpus(self, corpus_id: UUID) -> RetrievalCorpus | None:
        return await self._repository.fetch_retrieval_corpus(corpus_id)

    async def create_retrieval_source(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: CreateRetrievalSourceRequest,
    ) -> RetrievalCommandResult:
        organization = await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if scope == "workspace" and project_id is None and workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            project_id = workspace.project_id
        corpus = await self._repository.fetch_retrieval_corpus(payload.corpus_id)
        if corpus is None:
            raise KeyError(f"Retrieval corpus {payload.corpus_id} not found")
        self._require_same_retrieval_scope(
            left_name="Retrieval corpus",
            left_id=corpus.corpus_id,
            left_scope=corpus.scope,
            left_organization_id=corpus.organization_id,
            left_workspace_id=corpus.workspace_id,
            right_scope=scope,
            right_organization_id=organization.organization_id if organization else None,
            right_workspace_id=workspace_id,
            left_project_id=corpus.project_id,
            right_project_id=project_id,
        )
        asset = await self._repository.fetch_workspace_asset(payload.asset_id)
        if asset is None:
            raise KeyError(f"Workspace asset {payload.asset_id} not found")
        self._require_same_retrieval_scope(
            left_name="Workspace asset",
            left_id=asset.asset_id,
            left_scope=asset.scope,
            left_organization_id=asset.organization_id,
            left_workspace_id=asset.workspace_id,
            right_scope=scope,
            right_organization_id=organization.organization_id if organization else None,
            right_workspace_id=workspace_id,
            left_project_id=asset.project_id,
            right_project_id=project_id,
        )
        asset_version = await self._resolve_asset_version_for_source(
            asset_id=asset.asset_id,
            asset_version_id=payload.asset_version_id,
        )
        now = self._now()
        existing_sources = await self._repository.list_retrieval_sources(
            corpus_id=corpus.corpus_id,
            scope=scope,
            organization_id=organization.organization_id if organization else None,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        existing = next(
            (source for source in existing_sources if source.asset_id == asset.asset_id),
            None,
        )
        source = RetrievalSource(
            source_id=existing.source_id if existing is not None else uuid4(),
            corpus_id=corpus.corpus_id,
            scope=scope,
            organization_id=organization.organization_id if organization is not None else None,
            project_id=project_id,
            workspace_id=workspace_id,
            asset_id=asset.asset_id,
            active_asset_version_id=asset_version.asset_version_id,
            title=payload.title,
            source_type=payload.source_type,
            content_type=payload.content_type or asset_version.content_type,
            created_by=existing.created_by if existing is not None else payload.actor.participant_id,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            metadata={
                **(existing.metadata if existing is not None else {}),
                **payload.metadata,
            },
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            await self._repository.upsert_retrieval_source(conn, source)
        return RetrievalCommandResult(source=source)

    async def list_retrieval_sources(
        self,
        *,
        corpus_id: UUID | None = None,
        scope: str | None = None,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[RetrievalSource]:
        if scope is not None:
            await self._resolve_scope_organization(
                scope=scope,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
            )
        return await self._repository.list_retrieval_sources(
            corpus_id=corpus_id,
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )

    async def get_retrieval_source(self, source_id: UUID) -> RetrievalSource | None:
        return await self._repository.fetch_retrieval_source(source_id)

    async def list_retrieval_source_versions(
        self,
        source_id: UUID,
    ) -> list[RetrievalSourceVersion]:
        source = await self._repository.fetch_retrieval_source(source_id)
        if source is None:
            raise KeyError(f"Retrieval source {source_id} not found")
        return await self._repository.list_retrieval_source_versions(source_id)

    async def create_retrieval_ingestion_job(
        self,
        *,
        corpus_id: UUID,
        payload: CreateRetrievalIngestionJobRequest,
    ) -> RetrievalCommandResult:
        corpus = await self._repository.fetch_retrieval_corpus(corpus_id)
        if corpus is None:
            raise KeyError(f"Retrieval corpus {corpus_id} not found")
        source_version: RetrievalSourceVersion | None = None
        if payload.source_version_id is not None:
            source_version = await self._repository.fetch_retrieval_source_version(
                payload.source_version_id
            )
            if source_version is None:
                raise KeyError(
                    f"Retrieval source version {payload.source_version_id} not found"
                )
            source = await self._repository.fetch_retrieval_source(source_version.source_id)
        elif payload.source_id is not None:
            source = await self._repository.fetch_retrieval_source(payload.source_id)
        else:
            raise ValueError("source_id or source_version_id is required")
        if source is None:
            raise KeyError("Retrieval source not found")
        if source.corpus_id != corpus.corpus_id:
            raise ValueError("Retrieval source does not belong to the requested corpus")
        if payload.profile_id is not None:
            profile = await self._repository.fetch_retrieval_profile(payload.profile_id)
            if profile is None:
                raise KeyError(f"Retrieval profile {payload.profile_id} not found")
            self._require_same_retrieval_scope(
                left_name="Retrieval profile",
                left_id=profile.profile_id,
                left_scope=profile.scope,
                left_organization_id=profile.organization_id,
                left_workspace_id=profile.workspace_id,
                right_scope=corpus.scope,
                right_organization_id=corpus.organization_id,
                right_workspace_id=corpus.workspace_id,
                left_project_id=profile.project_id,
                right_project_id=corpus.project_id,
            )
        now = self._now()
        job_id = uuid4()
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                if source_version is None:
                    if source.active_asset_version_id is None:
                        raise ValueError("Retrieval source has no active asset version")
                    source_version = RetrievalSourceVersion(
                        source_version_id=uuid4(),
                        source_id=source.source_id,
                        asset_version_id=source.active_asset_version_id,
                        version=await self._repository.next_retrieval_source_version(
                            conn,
                            source_id=source.source_id,
                        ),
                        ingestion_job_id=None,
                        created_by=payload.actor.participant_id,
                        created_at=now,
                        metadata={},
                    )
                    await self._repository.upsert_retrieval_source_version(
                        conn,
                        source_version,
                    )
                job = RetrievalIngestionJob(
                    job_id=job_id,
                    corpus_id=corpus.corpus_id,
                    source_id=source.source_id,
                    source_version_id=source_version.source_version_id,
                    profile_id=payload.profile_id or corpus.default_profile_id,
                    scope=corpus.scope,
                    organization_id=corpus.organization_id,
                    project_id=corpus.project_id,
                    workspace_id=corpus.workspace_id,
                    status="queued",
                    stage="queued",
                    requested_by=payload.actor.participant_id,
                    created_at=now,
                    updated_at=now,
                    metadata=payload.metadata,
                )
                await self._repository.upsert_retrieval_ingestion_job(conn, job)
                if source_version.ingestion_job_id is None:
                    source_version = source_version.model_copy(
                        update={"ingestion_job_id": job.job_id}
                    )
                    await self._repository.upsert_retrieval_source_version(
                        conn,
                        source_version,
                    )
        return RetrievalCommandResult(job=job, source_version=source_version)

    async def list_retrieval_ingestion_jobs(
        self,
        *,
        corpus_id: UUID | None = None,
        source_id: UUID | None = None,
        scope: str | None = None,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        status: str | None = None,
    ) -> list[RetrievalIngestionJob]:
        if scope is not None:
            await self._resolve_scope_organization(
                scope=scope,
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
            )
        return await self._repository.list_retrieval_ingestion_jobs(
            corpus_id=corpus_id,
            source_id=source_id,
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            status=status,
        )

    async def run_retrieval_search(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: RunRetrievalSearchRequest,
        embedding_vector: list[float] | None = None,
        embedding_provider_key: str | None = None,
        embedding_model: str | None = None,
    ) -> RetrievalSearchResponse:
        organization = await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if scope == "workspace" and project_id is None and workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            project_id = workspace.project_id
        if payload.provider_overrides and "retrieval.admin" not in payload.actor.iam_permissions:
            raise PermissionError("retrieval.admin is required for provider overrides")
        corpora = await self._resolve_retrieval_corpora_for_search(
            scope=scope,
            organization_id=organization.organization_id if organization else None,
            project_id=project_id,
            workspace_id=workspace_id,
            corpus_ids=payload.corpus_ids,
        )
        profile = await self._resolve_retrieval_profile_for_search(
            profile_id=payload.profile_id,
            corpora=corpora,
        )
        top_k = payload.top_k or (profile.top_k if profile is not None else 12)
        strategy = payload.strategy or (profile.search_strategy if profile is not None else "hybrid")
        vector_weight = profile.vector_weight if profile is not None else 0.65
        keyword_weight = profile.keyword_weight if profile is not None else 0.35
        run = RetrievalRun(
            run_id=uuid4(),
            run_kind="search",
            scope=scope,
            organization_id=organization.organization_id if organization else None,
            project_id=project_id,
            workspace_id=workspace_id,
            profile_id=profile.profile_id if profile is not None else None,
            query=payload.query,
            status="completed",
            created_by=payload.actor.participant_id,
            created_at=self._now(),
            metadata={
                "corpus_ids": [str(corpus.corpus_id) for corpus in corpora],
                "strategy": strategy,
            },
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                hits: list[RetrievalSearchHit] = []
                for group in self._retrieval_corpus_scope_groups(corpora):
                    group_hits = await self._repository.search_retrieval_chunks(
                        query=payload.query,
                        corpus_ids=[corpus.corpus_id for corpus in group["corpora"]],
                        scope=group["scope"],
                        organization_id=group["organization_id"],
                        project_id=group["project_id"],
                        workspace_id=group["workspace_id"],
                        limit=top_k,
                        strategy=strategy,
                        metadata_filters=payload.metadata_filters,
                        embedding_vector=embedding_vector,
                        embedding_provider_key=embedding_provider_key,
                        embedding_model=embedding_model,
                        vector_weight=vector_weight,
                        keyword_weight=keyword_weight,
                        conn=conn,
                        lock_chunks=True,
                    )
                    hits.extend(group_hits)
                hits = sorted(
                    hits,
                    key=lambda hit: (hit.score if hit.score is not None else 0.0),
                    reverse=True,
                )[:top_k]
                hits = [hit.model_copy(update={"rank": index + 1}) for index, hit in enumerate(hits)]
                await self._repository.upsert_retrieval_run(conn, run)
                for hit in hits:
                    await self._repository.upsert_retrieval_hit(
                        conn,
                        hit_id=uuid4(),
                        run_id=run.run_id,
                        hit=hit,
                    )
        context_pack = None
        if payload.include_context:
            context_pack = self._build_context_pack(
                query=payload.query,
                run=run,
                hits=hits,
                token_budget=(
                    payload.context_token_budget
                    or (profile.context_token_budget if profile is not None else 6000)
                ),
                created_by=payload.actor.participant_id,
                metadata={},
            )
            async with self._repository._pool.acquire() as conn:  # noqa: SLF001
                await self._repository.upsert_retrieval_context_pack(conn, context_pack)
        return RetrievalSearchResponse(run=run, hits=hits, context_pack=context_pack)

    async def create_retrieval_context_pack(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: CreateRetrievalContextPackRequest,
        embedding_vector: list[float] | None = None,
        embedding_provider_key: str | None = None,
        embedding_model: str | None = None,
    ) -> RetrievalCommandResult:
        search = await self.run_retrieval_search(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            payload=RunRetrievalSearchRequest(
                actor=payload.actor,
                query=payload.query,
                corpus_ids=payload.corpus_ids,
                profile_id=payload.profile_id,
                strategy=payload.strategy,
                top_k=payload.top_k,
                metadata_filters=payload.metadata_filters,
                include_context=False,
                context_token_budget=payload.context_token_budget,
                provider_overrides=payload.provider_overrides,
            ),
            embedding_vector=embedding_vector,
            embedding_provider_key=embedding_provider_key,
            embedding_model=embedding_model,
        )
        resolved_profile_id = payload.profile_id or search.run.profile_id
        profile = (
            await self._repository.fetch_retrieval_profile(resolved_profile_id)
            if resolved_profile_id is not None
            else None
        )
        context_pack = self._build_context_pack(
            query=payload.query,
            run=search.run,
            hits=search.hits,
            token_budget=(
                payload.context_token_budget
                or (profile.context_token_budget if profile is not None else 6000)
            ),
            created_by=payload.actor.participant_id,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            await self._repository.upsert_retrieval_context_pack(conn, context_pack)
        return RetrievalCommandResult(
            run=search.run,
            hits=search.hits,
            context_pack=context_pack,
        )

    async def get_retrieval_context_pack(
        self, context_pack_id: UUID
    ) -> RetrievalContextPack | None:
        return await self._repository.fetch_retrieval_context_pack(context_pack_id)

    async def create_methodology_blueprint(
        self,
        organization_id: UUID,
        payload: CreateMethodologyBlueprintRequest,
    ) -> MethodologyBlueprintCommandResult:
        organization = await self._repository.fetch_organization(organization_id)
        if organization is None:
            raise KeyError(f"Organization {organization_id} not found")
        user_id = self._actor_user_id(payload.actor)
        if user_id is not None:
            await self._require_organization_permission(
                organization_id,
                user_id,
                "methodology.write",
            )
        for library_id in payload.library_ids:
            library = await self._repository.fetch_library(library_id)
            if library is None or library.organization_id != organization_id:
                raise KeyError(f"Library {library_id} not found in organization {organization_id}")
            if library.scope not in {"organization", "project"}:
                raise ValueError("Blueprint research can only select organization or project libraries")

        now = self._now()
        blueprint_id = uuid4()
        version_id = uuid4()
        dossier_id = uuid4()
        operations_workspace = await self._organization_operations_workspace(organization_id)
        researcher_agent = await self._repository.fetch_system_agent_by_key(
            scope="global",
            organization_id=None,
            agent_key="researcher",
        )
        if researcher_agent is None:
            raise KeyError("Seeded Researcher agent not found")
        methodologist_agent = await self._repository.fetch_system_agent_by_key(
            scope="global",
            organization_id=None,
            agent_key="methodologist",
        )
        if methodologist_agent is None:
            raise KeyError("Seeded Methodologist agent not found")
        researcher_participant = await self._ensure_operations_agent_participant(
            operations_workspace,
            researcher_agent,
            now=now,
        )
        methodologist_participant = await self._ensure_operations_agent_participant(
            operations_workspace,
            methodologist_agent,
            now=now,
        )
        retained_library = Library(
            library_id=uuid4(),
            scope="organization",
            organization_id=organization_id,
            slug=self._normalize_library_slug(f"research-dossier-{dossier_id.hex[:12]}"),
            name=f"Research Dossier: {payload.title}",
            description="Managed retained-source library for a methodology research dossier.",
            created_by=payload.actor.participant_id,
            updated_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata={
                "managed": True,
                "research_dossier": True,
                "blueprint_id": str(blueprint_id),
                "version_id": str(version_id),
                "dossier_id": str(dossier_id),
            },
        )
        thread = Thread(
            thread_id=uuid4(),
            workspace_id=operations_workspace.workspace_id,
            title=f"Research dossier: {payload.title}",
            created_at=now,
            updated_at=now,
            metadata={
                "managed": True,
                "methodology_blueprint_id": str(blueprint_id),
                "methodology_blueprint_version_id": str(version_id),
                "research_dossier_id": str(dossier_id),
            },
        )
        blueprint = MethodologyBlueprint(
            blueprint_id=blueprint_id,
            organization_id=organization_id,
            title=payload.title,
            topic=payload.topic,
            target_goal=payload.target_goal,
            tasks=list(payload.tasks),
            status="draft",
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        version = MethodologyBlueprintVersion(
            version_id=version_id,
            blueprint_id=blueprint_id,
            organization_id=organization_id,
            version_number=1,
            status="researching",
            research_dossier_id=dossier_id,
            source_policy=payload.source_policy,
            selected_library_ids=list(payload.library_ids),
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata={"created_from_blueprint_request": True},
        )
        dossier = ResearchDossier(
            dossier_id=dossier_id,
            blueprint_id=blueprint_id,
            version_id=version_id,
            organization_id=organization_id,
            retained_library_id=retained_library.library_id,
            operations_workspace_id=operations_workspace.workspace_id,
            thread_id=thread.thread_id,
            researcher_system_agent_id=researcher_agent.agent_id,
            researcher_participant_id=researcher_participant.participant_id,
            methodologist_system_agent_id=methodologist_agent.agent_id,
            methodologist_participant_id=methodologist_participant.participant_id,
            status="researching",
            topic=payload.topic,
            tasks=list(payload.tasks),
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata={
                "source_policy": payload.source_policy,
                "selected_library_ids": [str(item) for item in payload.library_ids],
            },
        )
        (
            notebook,
            provider_binding,
            notebook_notes,
            external_refs,
        ) = self._build_research_dossier_notebook_defaults(
            dossier=dossier,
            title=payload.title,
            actor_id=payload.actor.participant_id,
            now=now,
        )
        task = self._build_researcher_dossier_task(
            dossier=dossier,
            blueprint=blueprint,
            version=version,
            operations_workspace=operations_workspace,
            researcher_participant=researcher_participant,
            requested_by=payload.actor.participant_id,
            now=now,
        )
        event = ResearchDossierEvent(
            event_id=uuid4(),
            dossier_id=dossier_id,
            organization_id=organization_id,
            event_type="research_dossier.created",
            actor_participant_id=payload.actor.participant_id,
            payload={
                "blueprint_id": str(blueprint_id),
                "version_id": str(version_id),
                "retained_library_id": str(retained_library.library_id),
                "notebook_id": str(notebook.notebook_id),
                "notebook_provider": provider_binding.provider_key,
                "notebook_external_space_ref": provider_binding.external_space_ref,
                "researcher_task_id": str(task.task_id),
            },
            created_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_participant(conn, researcher_participant)
                await self._repository.upsert_participant(conn, methodologist_participant)
                await self._repository.upsert_library(conn, retained_library)
                await self._repository.upsert_thread(conn, thread)
                await self._repository.upsert_methodology_blueprint(conn, blueprint)
                await self._repository.upsert_methodology_blueprint_version(conn, version)
                await self._repository.upsert_research_dossier(conn, dossier)
                await self._repository.upsert_research_dossier_notebook(conn, notebook)
                await self._repository.upsert_research_dossier_provider_binding(
                    conn,
                    provider_binding,
                )
                for note in notebook_notes:
                    await self._repository.upsert_research_dossier_note(conn, note)
                for external_ref in external_refs:
                    await self._repository.upsert_research_dossier_provider_external_ref(
                        conn,
                        external_ref,
                    )
                await self._repository.upsert_task(conn, task)
                await self._repository.append_research_dossier_event(conn, event)
        return MethodologyBlueprintCommandResult(
            detail=MethodologyBlueprintDetail(
                blueprint=blueprint,
                versions=[version],
                dossier=dossier,
                sources=[],
            ),
            dossier=dossier,
        )

    async def list_methodology_blueprints(
        self,
        organization_id: UUID,
        *,
        actor: ParticipantInput | None = None,
        status: str | None = None,
    ) -> list[MethodologyBlueprint]:
        if actor is not None:
            user_id = self._actor_user_id(actor)
            if user_id is not None:
                await self._require_organization_permission(
                    organization_id,
                    user_id,
                    "methodology.read",
                )
        return await self._repository.list_methodology_blueprints(
            organization_id,
            status=status,
        )

    async def get_methodology_blueprint_detail(
        self,
        blueprint_id: UUID,
        *,
        actor: ParticipantInput | None = None,
    ) -> MethodologyBlueprintDetail:
        blueprint = await self._repository.fetch_methodology_blueprint(blueprint_id)
        if blueprint is None:
            raise KeyError(f"Methodology blueprint {blueprint_id} not found")
        if actor is not None:
            user_id = self._actor_user_id(actor)
            if user_id is not None:
                await self._require_organization_permission(
                    blueprint.organization_id,
                    user_id,
                    "methodology.read",
                )
        versions = await self._repository.list_methodology_blueprint_versions(blueprint_id)
        dossier = None
        sources: list[ResearchDossierSource] = []
        if versions and versions[0].research_dossier_id is not None:
            dossier = await self._repository.fetch_research_dossier(
                versions[0].research_dossier_id
            )
            if dossier is not None:
                sources = await self._repository.list_research_dossier_sources(
                    dossier.dossier_id
                )
        return MethodologyBlueprintDetail(
            blueprint=blueprint,
            versions=versions,
            dossier=dossier,
            sources=sources,
        )

    async def get_research_dossier(
        self,
        dossier_id: UUID,
        *,
        actor: ParticipantInput | None = None,
    ) -> ResearchDossier:
        dossier = await self._repository.fetch_research_dossier(dossier_id)
        if dossier is None:
            raise KeyError(f"Research dossier {dossier_id} not found")
        if actor is not None:
            user_id = self._actor_user_id(actor)
            if user_id is not None:
                await self._require_organization_permission(
                    dossier.organization_id,
                    user_id,
                    "methodology.read",
                )
        return dossier

    async def get_methodology_blueprint_version(
        self,
        version_id: UUID,
        *,
        actor: ParticipantInput | None = None,
    ) -> MethodologyBlueprintVersion:
        version = await self._repository.fetch_methodology_blueprint_version(version_id)
        if version is None:
            raise KeyError(f"Methodology blueprint version {version_id} not found")
        if actor is not None:
            user_id = self._actor_user_id(actor)
            if user_id is not None:
                await self._require_organization_permission(
                    version.organization_id,
                    user_id,
                    "methodology.read",
                )
        return version

    async def list_research_dossier_sources(
        self,
        dossier_id: UUID,
        *,
        actor: ParticipantInput | None = None,
        status: str | None = None,
    ) -> list[ResearchDossierSource]:
        dossier = await self.get_research_dossier(dossier_id, actor=actor)
        return await self._repository.list_research_dossier_sources(
            dossier.dossier_id,
            status=status,
        )

    async def get_research_dossier_notebook_detail(
        self,
        dossier_id: UUID,
        *,
        actor: ParticipantInput | None = None,
    ) -> ResearchDossierNotebookDetail:
        dossier = await self.get_research_dossier(dossier_id, actor=actor)
        detail = await self._repository.fetch_research_dossier_notebook_detail(
            dossier.dossier_id
        )
        if detail is None:
            raise KeyError(f"Research dossier notebook for {dossier_id} not found")
        return detail

    async def get_research_dossier_graph(
        self,
        dossier_id: UUID,
        *,
        actor: ParticipantInput | None = None,
    ) -> ResearchDossierGraph:
        detail = await self.get_research_dossier_notebook_detail(
            dossier_id,
            actor=actor,
        )
        nodes: list[dict[str, Any]] = []
        nodes.extend(
            {
                "type": "note",
                "id": str(note.note_id),
                "label": note.title,
                "kind": note.note_kind,
                "status": note.status,
                "slug": note.slug,
            }
            for note in detail.notes
        )
        nodes.extend(
            {
                "type": "concept",
                "id": str(concept.concept_id),
                "label": concept.name,
                "status": concept.status,
                "slug": concept.slug,
            }
            for concept in detail.concepts
        )
        nodes.extend(
            {
                "type": "claim",
                "id": str(claim.claim_id),
                "label": claim.statement,
                "status": claim.status,
                "claim_key": claim.claim_key,
            }
            for claim in detail.claims
        )
        sources = await self._repository.list_research_dossier_sources(dossier_id)
        nodes.extend(
            {
                "type": "source",
                "id": str(source.source_id),
                "label": source.title,
                "status": source.status,
                "citation_id": source.citation_id,
            }
            for source in sources
        )
        return ResearchDossierGraph(
            dossier_id=dossier_id,
            notebook_id=detail.notebook.notebook_id,
            nodes=nodes,
            links=detail.links,
            metadata={
                "node_count": len(nodes),
                "link_count": len(detail.links),
                "knowledge_storage": True,
            },
        )

    async def navigate_research_dossier(
        self,
        dossier_id: UUID,
        payload: NavigateResearchDossierRequest,
    ) -> ResearchDossierNavigationResult:
        detail = await self.get_research_dossier_notebook_detail(
            dossier_id,
            actor=payload.actor,
        )
        query = (payload.query or "").strip().lower()
        notes = list(detail.notes)
        concepts = list(detail.concepts)
        claims = list(detail.claims)
        if payload.focus_note_id is not None:
            notes = [note for note in notes if note.note_id == payload.focus_note_id]
        if payload.focus_concept_id is not None:
            concepts = [
                concept
                for concept in concepts
                if concept.concept_id == payload.focus_concept_id
            ]
        if query:
            notes = [
                note
                for note in detail.notes
                if query in note.title.lower()
                or query in note.slug.lower()
                or query in (note.body or "").lower()
                or query in (note.summary or "").lower()
            ]
            concepts = [
                concept
                for concept in detail.concepts
                if query in concept.name.lower()
                or query in concept.slug.lower()
                or any(query in alias.lower() for alias in concept.aliases)
                or query in (concept.definition or "").lower()
            ]
            claims = [
                claim
                for claim in detail.claims
                if query in claim.statement.lower()
                or query in (claim.claim_key or "").lower()
            ]
        note_ids = {note.note_id for note in notes[: payload.max_results]}
        concept_ids = {concept.concept_id for concept in concepts[: payload.max_results]}
        claim_ids = {claim.claim_id for claim in claims[: payload.max_results]}
        links = [
            link
            for link in detail.links
            if link.source_ref_id in note_ids | concept_ids | claim_ids
            or link.target_ref_id in note_ids | concept_ids | claim_ids
        ][: payload.max_results]
        gaps = [note for note in detail.notes if note.note_kind == "gap"][
            : payload.max_results
        ]
        contradictions = [
            note for note in detail.notes if note.note_kind == "contradiction"
        ][: payload.max_results]
        recommended_next = [
            {
                "type": "note",
                "id": str(note.note_id),
                "title": note.title,
                "reason": "entry_note_match" if query else "dossier_entrypoint",
            }
            for note in (notes or detail.notes)[: payload.max_results]
        ]
        return ResearchDossierNavigationResult(
            dossier_id=dossier_id,
            notebook_id=detail.notebook.notebook_id,
            query=payload.query,
            entry_notes=notes[: payload.max_results],
            concepts=concepts[: payload.max_results],
            claims=claims[: payload.max_results],
            links=links,
            gaps=gaps,
            contradictions=contradictions,
            recommended_next=recommended_next,
            metadata={"include_sources": payload.include_sources},
        )

    async def upsert_research_dossier_note(
        self,
        dossier_id: UUID,
        payload: UpsertResearchDossierNoteRequest,
    ) -> MethodologyBlueprintCommandResult:
        dossier = await self.get_research_dossier(dossier_id, actor=payload.actor)
        await self._require_dossier_write_actor(dossier, payload.actor)
        notebook = await self._require_research_dossier_notebook(dossier_id)
        now = self._now()
        normalized_slug = self._normalize_library_slug(payload.slug)
        existing = (
            await self._repository.fetch_research_dossier_note(payload.note_id)
            if payload.note_id is not None
            else await self._repository.fetch_research_dossier_note_by_slug(
                notebook.notebook_id,
                normalized_slug,
            )
        )
        if existing is not None and existing.notebook_id != notebook.notebook_id:
            raise KeyError(f"Research dossier note {payload.note_id} not found")
        await self._validate_dossier_note_refs(dossier, notebook, payload)
        note = ResearchDossierNote(
            note_id=existing.note_id if existing is not None else payload.note_id or uuid4(),
            notebook_id=notebook.notebook_id,
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            note_kind=payload.note_kind,
            status=payload.status,
            slug=normalized_slug,
            title=payload.title,
            body=payload.body,
            summary=payload.summary,
            source_id=payload.source_id,
            concept_id=payload.concept_id,
            citation_ids=list(payload.citation_ids),
            related_note_ids=list(payload.related_note_ids),
            external_page_ref=payload.external_page_ref,
            external_url=payload.external_url,
            created_by=existing.created_by if existing is not None else payload.actor.participant_id,
            created_at=existing.created_at if existing is not None else now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata={
                **(existing.metadata if existing is not None else {}),
                **payload.metadata,
            },
        )
        event = self._build_dossier_notebook_event(
            dossier=dossier,
            actor=payload.actor,
            system_agent_id=await self._dossier_actor_system_agent_id(
                dossier,
                payload.actor,
            ),
            event_type="research_dossier_notebook.note_upserted",
            payload={"note_id": str(note.note_id), "slug": note.slug, "kind": note.note_kind},
            now=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_research_dossier_note(conn, note)
                await self._repository.append_research_dossier_event(conn, event)
        return MethodologyBlueprintCommandResult(dossier=dossier, note=note)

    async def upsert_research_dossier_concept(
        self,
        dossier_id: UUID,
        payload: UpsertResearchDossierConceptRequest,
    ) -> MethodologyBlueprintCommandResult:
        dossier = await self.get_research_dossier(dossier_id, actor=payload.actor)
        await self._require_dossier_write_actor(dossier, payload.actor)
        notebook = await self._require_research_dossier_notebook(dossier_id)
        now = self._now()
        normalized_slug = self._normalize_library_slug(payload.slug)
        existing = (
            await self._repository.fetch_research_dossier_concept(payload.concept_id)
            if payload.concept_id is not None
            else await self._repository.fetch_research_dossier_concept_by_slug(
                notebook.notebook_id,
                normalized_slug,
            )
        )
        if existing is not None and existing.notebook_id != notebook.notebook_id:
            raise KeyError(f"Research dossier concept {payload.concept_id} not found")
        for source_id in payload.source_ids:
            source = await self._repository.fetch_research_dossier_source(source_id)
            if source is None or source.dossier_id != dossier_id:
                raise KeyError(f"Research dossier source {source_id} not found")
        concept = ResearchDossierConcept(
            concept_id=(
                existing.concept_id
                if existing is not None
                else payload.concept_id or uuid4()
            ),
            notebook_id=notebook.notebook_id,
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            slug=normalized_slug,
            name=payload.name,
            aliases=list(payload.aliases),
            definition=payload.definition,
            status=payload.status,
            confidence=payload.confidence,
            source_ids=list(payload.source_ids),
            claim_ids=list(payload.claim_ids),
            created_by=existing.created_by if existing is not None else payload.actor.participant_id,
            created_at=existing.created_at if existing is not None else now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata={
                **(existing.metadata if existing is not None else {}),
                **payload.metadata,
            },
        )
        event = self._build_dossier_notebook_event(
            dossier=dossier,
            actor=payload.actor,
            system_agent_id=await self._dossier_actor_system_agent_id(
                dossier,
                payload.actor,
            ),
            event_type="research_dossier_notebook.concept_upserted",
            payload={"concept_id": str(concept.concept_id), "slug": concept.slug},
            now=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_research_dossier_concept(conn, concept)
                await self._repository.append_research_dossier_event(conn, event)
        return MethodologyBlueprintCommandResult(dossier=dossier, concept=concept)

    async def upsert_research_dossier_claim(
        self,
        dossier_id: UUID,
        payload: UpsertResearchDossierClaimRequest,
    ) -> MethodologyBlueprintCommandResult:
        dossier = await self.get_research_dossier(dossier_id, actor=payload.actor)
        await self._require_dossier_write_actor(dossier, payload.actor)
        notebook = await self._require_research_dossier_notebook(dossier_id)
        now = self._now()
        existing = (
            await self._repository.fetch_research_dossier_claim(payload.claim_id)
            if payload.claim_id is not None
            else (
                await self._repository.fetch_research_dossier_claim_by_key(
                    notebook.notebook_id,
                    payload.claim_key,
                )
                if payload.claim_key is not None
                else None
            )
        )
        if existing is not None and existing.notebook_id != notebook.notebook_id:
            raise KeyError(f"Research dossier claim {payload.claim_id} not found")
        for source_id in payload.source_ids:
            source = await self._repository.fetch_research_dossier_source(source_id)
            if source is None or source.dossier_id != dossier_id:
                raise KeyError(f"Research dossier source {source_id} not found")
        for context_pack_id in payload.context_pack_ids:
            context_pack = await self._repository.fetch_retrieval_context_pack(
                context_pack_id
            )
            if context_pack is None or context_pack.organization_id != dossier.organization_id:
                raise KeyError(f"Retrieval context pack {context_pack_id} not found")
        claim = ResearchDossierClaim(
            claim_id=existing.claim_id if existing is not None else payload.claim_id or uuid4(),
            notebook_id=notebook.notebook_id,
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            claim_key=payload.claim_key,
            statement=payload.statement,
            status=payload.status,
            confidence=payload.confidence,
            provenance=payload.provenance,
            source_ids=list(payload.source_ids),
            citation_ids=list(payload.citation_ids),
            context_pack_ids=list(payload.context_pack_ids),
            contradicted_by_claim_ids=list(payload.contradicted_by_claim_ids),
            created_by=existing.created_by if existing is not None else payload.actor.participant_id,
            created_at=existing.created_at if existing is not None else now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata={
                **(existing.metadata if existing is not None else {}),
                **payload.metadata,
            },
        )
        event = self._build_dossier_notebook_event(
            dossier=dossier,
            actor=payload.actor,
            system_agent_id=await self._dossier_actor_system_agent_id(
                dossier,
                payload.actor,
            ),
            event_type="research_dossier_notebook.claim_upserted",
            payload={"claim_id": str(claim.claim_id), "claim_key": claim.claim_key},
            now=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_research_dossier_claim(conn, claim)
                await self._repository.append_research_dossier_event(conn, event)
        return MethodologyBlueprintCommandResult(dossier=dossier, claim=claim)

    async def upsert_research_dossier_link(
        self,
        dossier_id: UUID,
        payload: UpsertResearchDossierLinkRequest,
    ) -> MethodologyBlueprintCommandResult:
        dossier = await self.get_research_dossier(dossier_id, actor=payload.actor)
        await self._require_dossier_write_actor(dossier, payload.actor)
        notebook = await self._require_research_dossier_notebook(dossier_id)
        await self._validate_dossier_graph_ref(
            notebook,
            payload.source_type,
            payload.source_ref_id,
        )
        await self._validate_dossier_graph_ref(
            notebook,
            payload.target_type,
            payload.target_ref_id,
        )
        now = self._now()
        existing = (
            await self._repository.fetch_research_dossier_link(payload.link_id)
            if payload.link_id is not None
            else await self._repository.fetch_research_dossier_link_by_tuple(
                notebook.notebook_id,
                source_type=payload.source_type,
                source_ref_id=payload.source_ref_id,
                target_type=payload.target_type,
                target_ref_id=payload.target_ref_id,
                link_kind=payload.link_kind,
            )
        )
        if existing is not None and existing.notebook_id != notebook.notebook_id:
            raise KeyError(f"Research dossier link {payload.link_id} not found")
        link = ResearchDossierLink(
            link_id=existing.link_id if existing is not None else payload.link_id or uuid4(),
            notebook_id=notebook.notebook_id,
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            source_type=payload.source_type,
            source_ref_id=payload.source_ref_id,
            target_type=payload.target_type,
            target_ref_id=payload.target_ref_id,
            link_kind=payload.link_kind,
            rationale=payload.rationale,
            confidence=payload.confidence,
            created_by=existing.created_by if existing is not None else payload.actor.participant_id,
            created_at=existing.created_at if existing is not None else now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata={
                **(existing.metadata if existing is not None else {}),
                **payload.metadata,
            },
        )
        event = self._build_dossier_notebook_event(
            dossier=dossier,
            actor=payload.actor,
            system_agent_id=await self._dossier_actor_system_agent_id(
                dossier,
                payload.actor,
            ),
            event_type="research_dossier_notebook.link_upserted",
            payload={"link_id": str(link.link_id), "link_kind": link.link_kind},
            now=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_research_dossier_link(conn, link)
                await self._repository.append_research_dossier_event(conn, event)
        return MethodologyBlueprintCommandResult(dossier=dossier, link=link)

    async def sync_research_dossier_notebook(
        self,
        dossier_id: UUID,
        payload: SyncResearchDossierNotebookRequest,
        *,
        status: str = "completed",
        error: str | None = None,
        stats: dict[str, Any] | None = None,
    ) -> ResearchDossierSyncRun:
        dossier = await self.get_research_dossier(dossier_id, actor=payload.actor)
        await self._require_dossier_write_actor(dossier, payload.actor)
        notebook = await self._require_research_dossier_notebook(dossier_id)
        bindings = await self._repository.list_research_dossier_provider_bindings(
            notebook.notebook_id,
            provider_key=payload.provider_key,
        )
        binding = bindings[0] if bindings else None
        if payload.provider_key is not None and binding is None:
            raise KeyError(f"Dossier notebook provider {payload.provider_key!r} not found")
        now = self._now()
        actor_system_agent_id = await self._dossier_actor_system_agent_id(
            dossier,
            payload.actor,
        )
        sync_run = ResearchDossierSyncRun(
            sync_run_id=uuid4(),
            binding_id=binding.binding_id if binding is not None else None,
            notebook_id=notebook.notebook_id,
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            status=status,
            direction="push",
            started_at=now,
            completed_at=now if status in {"completed", "failed"} else None,
            error=error,
            stats=stats or {},
            actor_participant_id=payload.actor.participant_id,
            system_agent_id=actor_system_agent_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        updated_notebook = notebook.model_copy(
            update={
                "status": "ready" if status == "completed" else "failed",
                "last_sync_at": now if status == "completed" else notebook.last_sync_at,
                "updated_by": payload.actor.participant_id,
                "updated_at": now,
            }
        )
        updated_binding = (
            binding.model_copy(
                update={
                    "status": "ready" if status == "completed" else "failed",
                    "last_sync_at": now if status == "completed" else binding.last_sync_at,
                    "updated_by": payload.actor.participant_id,
                    "updated_at": now,
                }
            )
            if binding is not None
            else None
        )
        event = self._build_dossier_notebook_event(
            dossier=dossier,
            actor=payload.actor,
            system_agent_id=actor_system_agent_id,
            event_type="research_dossier_notebook.synced",
            payload={
                "sync_run_id": str(sync_run.sync_run_id),
                "provider_key": binding.provider_key if binding is not None else None,
                "status": sync_run.status,
            },
            now=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_research_dossier_sync_run(conn, sync_run)
                await self._repository.upsert_research_dossier_notebook(
                    conn,
                    updated_notebook,
                )
                if updated_binding is not None:
                    await self._repository.upsert_research_dossier_provider_binding(
                        conn,
                        updated_binding,
                    )
                await self._repository.append_research_dossier_event(conn, event)
        return sync_run

    async def submit_research_dossier_health_check(
        self,
        dossier_id: UUID,
        payload: SubmitResearchDossierHealthCheckRequest,
    ) -> ResearchDossierHealthCheck:
        dossier = await self.get_research_dossier(dossier_id, actor=payload.actor)
        await self._require_dossier_write_actor(dossier, payload.actor)
        notebook = await self._require_research_dossier_notebook(dossier_id)
        now = self._now()
        actor_system_agent_id = await self._dossier_actor_system_agent_id(
            dossier,
            payload.actor,
        )
        check = ResearchDossierHealthCheck(
            check_id=uuid4(),
            notebook_id=notebook.notebook_id,
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            status=payload.status,
            summary=payload.summary,
            findings=list(payload.findings),
            unresolved_count=payload.unresolved_count,
            stale_count=payload.stale_count,
            broken_link_count=payload.broken_link_count,
            checked_by_participant_id=payload.actor.participant_id,
            checked_by_system_agent_id=actor_system_agent_id,
            created_at=now,
            metadata=payload.metadata,
        )
        event = self._build_dossier_notebook_event(
            dossier=dossier,
            actor=payload.actor,
            system_agent_id=actor_system_agent_id,
            event_type="research_dossier_notebook.health_checked",
            payload={
                "check_id": str(check.check_id),
                "status": check.status,
                "unresolved_count": check.unresolved_count,
                "stale_count": check.stale_count,
                "broken_link_count": check.broken_link_count,
            },
            now=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.append_research_dossier_health_check(conn, check)
                await self._repository.append_research_dossier_event(conn, event)
        return check

    async def create_research_dossier_source(
        self,
        dossier_id: UUID,
        payload: CreateResearchDossierSourceRequest,
    ) -> MethodologyBlueprintCommandResult:
        dossier = await self.get_research_dossier(dossier_id, actor=payload.actor)
        await self._require_dossier_write_actor(dossier, payload.actor)
        now = self._now()
        actor_system_agent_id = await self._dossier_actor_system_agent_id(
            dossier,
            payload.actor,
        )
        source = ResearchDossierSource(
            source_id=uuid4(),
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            source_kind=payload.source_kind,
            status=payload.status,
            title=payload.title,
            source_uri=payload.source_uri,
            library_id=payload.library_id,
            library_item_id=payload.library_item_id,
            asset_id=payload.asset_id,
            asset_version_id=payload.asset_version_id,
            context_pack_ids=list(payload.context_pack_ids),
            citation_id=payload.citation_id,
            quality_notes=payload.quality_notes,
            contradictions=list(payload.contradictions),
            rationale=payload.rationale,
            fetch_metadata=payload.fetch_metadata,
            error=payload.error,
            discovered_by_participant_id=payload.actor.participant_id,
            discovered_by_system_agent_id=actor_system_agent_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        await self._validate_research_dossier_source_refs(dossier, source)
        event = ResearchDossierEvent(
            event_id=uuid4(),
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            event_type="research_dossier_source.created",
            actor_participant_id=payload.actor.participant_id,
            system_agent_id=actor_system_agent_id,
            source_id=source.source_id,
            payload=source.model_dump(mode="json"),
            created_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_research_dossier_source(conn, source)
                await self._repository.append_research_dossier_event(conn, event)
        return MethodologyBlueprintCommandResult(dossier=dossier, source=source)

    async def update_research_dossier_source(
        self,
        dossier_id: UUID,
        source_id: UUID,
        payload: UpdateResearchDossierSourceRequest,
    ) -> MethodologyBlueprintCommandResult:
        dossier = await self.get_research_dossier(dossier_id, actor=payload.actor)
        await self._require_dossier_write_actor(dossier, payload.actor)
        source = await self._repository.fetch_research_dossier_source(source_id)
        if source is None or source.dossier_id != dossier_id:
            raise KeyError(f"Research dossier source {source_id} not found")
        now = self._now()
        actor_system_agent_id = await self._dossier_actor_system_agent_id(
            dossier,
            payload.actor,
        )
        update = {
            key: value
            for key, value in payload.model_dump(exclude={"actor"}, exclude_none=True).items()
            if key != "metadata"
        }
        updated = source.model_copy(
            update={
                **update,
                "updated_at": now,
                "metadata": (
                    {**source.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else source.metadata
                ),
            }
        )
        await self._validate_research_dossier_source_refs(dossier, updated)
        event = ResearchDossierEvent(
            event_id=uuid4(),
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            event_type="research_dossier_source.updated",
            actor_participant_id=payload.actor.participant_id,
            system_agent_id=actor_system_agent_id,
            source_id=updated.source_id,
            payload=updated.model_dump(mode="json"),
            created_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_research_dossier_source(conn, updated)
                await self._repository.append_research_dossier_event(conn, event)
        return MethodologyBlueprintCommandResult(dossier=dossier, source=updated)

    async def attach_research_dossier_context_pack(
        self,
        dossier_id: UUID,
        payload: AttachResearchDossierContextPackRequest,
    ) -> ResearchDossier:
        dossier = await self.get_research_dossier(dossier_id, actor=payload.actor)
        await self._require_dossier_write_actor(dossier, payload.actor)
        context_pack = await self._repository.fetch_retrieval_context_pack(
            payload.context_pack_id
        )
        if context_pack is None or context_pack.organization_id != dossier.organization_id:
            raise KeyError(f"Retrieval context pack {payload.context_pack_id} not found")
        now = self._now()
        actor_system_agent_id = await self._dossier_actor_system_agent_id(
            dossier,
            payload.actor,
        )
        updated_dossier = dossier.model_copy(
            update={
                "context_pack_ids": list(
                    dict.fromkeys([*dossier.context_pack_ids, payload.context_pack_id])
                ),
                "updated_at": now,
                "metadata": {**dossier.metadata, **payload.metadata},
            }
        )
        source = None
        if payload.source_id is not None:
            source = await self._repository.fetch_research_dossier_source(payload.source_id)
            if source is None or source.dossier_id != dossier_id:
                raise KeyError(f"Research dossier source {payload.source_id} not found")
            source = source.model_copy(
                update={
                    "context_pack_ids": list(
                        dict.fromkeys([*source.context_pack_ids, payload.context_pack_id])
                    ),
                    "updated_at": now,
                }
            )
        event = ResearchDossierEvent(
            event_id=uuid4(),
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            event_type="research_dossier.context_pack_attached",
            actor_participant_id=payload.actor.participant_id,
            system_agent_id=actor_system_agent_id,
            source_id=payload.source_id,
            payload={"context_pack_id": str(payload.context_pack_id)},
            created_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_research_dossier(conn, updated_dossier)
                if source is not None:
                    await self._repository.upsert_research_dossier_source(conn, source)
                await self._repository.append_research_dossier_event(conn, event)
        return updated_dossier

    async def mark_research_dossier_ready(
        self,
        dossier_id: UUID,
        payload: MarkResearchDossierReadyRequest,
    ) -> ResearchDossier:
        dossier = await self.get_research_dossier(dossier_id, actor=payload.actor)
        await self._require_dossier_write_actor(dossier, payload.actor)
        version = await self._repository.fetch_methodology_blueprint_version(
            dossier.version_id
        )
        if version is None:
            raise KeyError(f"Methodology blueprint version {dossier.version_id} not found")
        now = self._now()
        actor_system_agent_id = await self._dossier_actor_system_agent_id(
            dossier,
            payload.actor,
        )
        updated_dossier = dossier.model_copy(
            update={
                "status": "ready_for_methodologist",
                "summary": payload.summary,
                "contradictions": list(payload.contradictions),
                "gaps": list(payload.gaps),
                "ready_at": now,
                "updated_at": now,
                "metadata": {**dossier.metadata, **payload.metadata},
            }
        )
        updated_version = version.model_copy(
            update={
                "status": "ready_for_methodologist",
                "updated_at": now,
                "metadata": {**version.metadata, "dossier_ready_at": now.isoformat()},
            }
        )
        sources = await self._repository.list_research_dossier_sources(
            dossier.dossier_id
        )
        methodologist_task = self._build_methodologist_blueprint_task(
            dossier=updated_dossier,
            version=updated_version,
            sources=sources,
            requested_by=payload.actor.participant_id,
            now=now,
        )
        event = ResearchDossierEvent(
            event_id=uuid4(),
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            event_type="research_dossier.ready_for_methodologist",
            actor_participant_id=payload.actor.participant_id,
            system_agent_id=actor_system_agent_id,
            payload={
                "methodologist_task_id": str(methodologist_task.task_id),
                "context_pack_ids": [str(item) for item in updated_dossier.context_pack_ids],
            },
            created_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_research_dossier(conn, updated_dossier)
                await self._repository.upsert_methodology_blueprint_version(
                    conn,
                    updated_version,
                )
                await self._repository.upsert_task(conn, methodologist_task)
                await self._repository.append_research_dossier_event(conn, event)
        return updated_dossier

    async def submit_methodology_blueprint_draft(
        self,
        version_id: UUID,
        payload: SubmitMethodologyBlueprintDraftRequest,
    ) -> MethodologyBlueprintDetail:
        version = await self._repository.fetch_methodology_blueprint_version(version_id)
        if version is None:
            raise KeyError(f"Methodology blueprint version {version_id} not found")
        blueprint = await self._repository.fetch_methodology_blueprint(version.blueprint_id)
        if blueprint is None:
            raise KeyError(f"Methodology blueprint {version.blueprint_id} not found")
        if payload.actor.participant_type == "user":
            user_id = self._actor_user_id(payload.actor)
            if user_id is not None:
                await self._require_organization_permission(
                    version.organization_id,
                    user_id,
                    "methodology.write",
                )
        now = self._now()
        dossier = (
            await self._repository.fetch_research_dossier(version.research_dossier_id)
            if version.research_dossier_id is not None
            else None
        )
        actor_system_agent_id = (
            await self._dossier_actor_system_agent_id(dossier, payload.actor)
            if dossier is not None
            else None
        )
        updated_version = version.model_copy(
            update={
                "status": "pending_review",
                "cited_output": payload.cited_output,
                "harness_draft": payload.harness_draft,
                "submitted_by_system_agent_id": actor_system_agent_id,
                "submitted_at": now,
                "updated_at": now,
                "metadata": {**version.metadata, **payload.metadata},
            }
        )
        if dossier is not None:
            dossier = dossier.model_copy(update={"status": "completed", "updated_at": now})
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_methodology_blueprint_version(
                    conn,
                    updated_version,
                )
                if dossier is not None:
                    await self._repository.upsert_research_dossier(conn, dossier)
        return await self.get_methodology_blueprint_detail(blueprint.blueprint_id)

    async def review_methodology_blueprint_version(
        self,
        blueprint_id: UUID,
        version_id: UUID,
        payload: ReviewMethodologyBlueprintVersionRequest,
        *,
        approved: bool,
    ) -> MethodologyBlueprintDetail:
        blueprint = await self._repository.fetch_methodology_blueprint(blueprint_id)
        if blueprint is None:
            raise KeyError(f"Methodology blueprint {blueprint_id} not found")
        version = await self._repository.fetch_methodology_blueprint_version(version_id)
        if version is None or version.blueprint_id != blueprint_id:
            raise KeyError(f"Methodology blueprint version {version_id} not found")
        user_id = self._actor_user_id(payload.actor)
        if user_id is not None:
            await self._require_organization_permission(
                blueprint.organization_id,
                user_id,
                "methodology.write",
            )
        if approved and version.harness_draft is None:
            raise ValueError("Cannot approve a methodology blueprint version without a harness draft")
        now = self._now()
        if approved:
            updated_version = version.model_copy(
                update={
                    "status": "approved",
                    "approved_by": payload.actor.participant_id,
                    "approved_at": now,
                    "review_reason": payload.reason,
                    "updated_at": now,
                    "metadata": {**version.metadata, **payload.metadata},
                }
            )
            updated_blueprint = blueprint.model_copy(
                update={
                    "status": "active",
                    "active_version_id": version.version_id,
                    "updated_at": now,
                }
            )
        else:
            updated_version = version.model_copy(
                update={
                    "status": "rejected",
                    "rejected_by": payload.actor.participant_id,
                    "rejected_at": now,
                    "review_reason": payload.reason,
                    "updated_at": now,
                    "metadata": {**version.metadata, **payload.metadata},
                }
            )
            updated_blueprint = blueprint.model_copy(update={"updated_at": now})
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_methodology_blueprint_version(
                    conn,
                    updated_version,
                )
                await self._repository.upsert_methodology_blueprint(conn, updated_blueprint)
        return await self.get_methodology_blueprint_detail(blueprint_id)

    async def apply_methodology_blueprint(
        self,
        blueprint_id: UUID,
        payload: ApplyMethodologyBlueprintRequest,
    ) -> WorkspaceDetail:
        blueprint = await self._repository.fetch_methodology_blueprint(blueprint_id)
        if blueprint is None:
            raise KeyError(f"Methodology blueprint {blueprint_id} not found")
        version_id = payload.version_id or blueprint.active_version_id
        if version_id is None:
            raise ValueError("Methodology blueprint has no active approved version")
        version = await self._repository.fetch_methodology_blueprint_version(version_id)
        if version is None or version.blueprint_id != blueprint_id:
            raise KeyError(f"Methodology blueprint version {version_id} not found")
        if version.status != "approved" or version.harness_draft is None:
            raise ValueError("Only approved methodology blueprint versions can be applied")
        workspace = await self._repository.fetch_workspace(payload.workspace_id)
        if workspace is None or workspace.organization_id != blueprint.organization_id:
            raise KeyError(f"Workspace {payload.workspace_id} not found")
        await self._require_workspace_permission(
            payload.workspace_id,
            payload.actor,
            permission="workspace.roles.write",
        )
        now = self._now()
        current_harness = workspace.harness or WorkspaceHarness()
        harness = version.harness_draft
        if payload.preserve_moderation_policy:
            harness = harness.model_copy(
                update={"moderation_policy": current_harness.moderation_policy}
            )
        harness = harness.model_copy(
            update={
                "metadata": {
                    **harness.metadata,
                    **payload.metadata,
                    "methodology_blueprint_id": str(blueprint.blueprint_id),
                    "methodology_blueprint_version_id": str(version.version_id),
                }
            }
        )
        updated_workspace = workspace.model_copy(
            update={
                "harness": harness,
                "updated_at": now,
                "metadata": {
                    **workspace.metadata,
                    "methodology_blueprint_id": str(blueprint.blueprint_id),
                    "methodology_blueprint_version_id": str(version.version_id),
                    "methodology_blueprint_applied_at": now.isoformat(),
                },
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace(conn, updated_workspace)
        return await self.get_workspace_detail(payload.workspace_id)

    async def create_methodic_execution(
        self,
        workspace_id: UUID,
        payload: CreateMethodicExecutionRequest,
    ) -> MethodicExecutionCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        actor_participant = await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="methodics.execute",
        )
        methodics_agent_participant = await self._resolve_methodics_execution_participant(
            workspace_id,
        )
        if (
            methodics_agent_participant is None
            or methodics_agent_participant.system_agent_id is None
        ):
            raise ValueError(
                "Conductor must be attached to the workspace before starting methodics execution"
            )
        conductor_system_agent_id = methodics_agent_participant.system_agent_id
        if workspace.harness is None or not workspace.harness.methodics:
            raise ValueError("Workspace has no active methodics to execute")

        methodics = list(workspace.harness.methodics)
        if payload.methodic_indexes:
            invalid = [
                index
                for index in payload.methodic_indexes
                if index < 0 or index >= len(methodics)
            ]
            if invalid:
                raise ValueError(f"Unknown methodic indexes: {invalid}")
            selected_indexes = list(dict.fromkeys(payload.methodic_indexes))
        else:
            selected_indexes = list(range(len(methodics)))

        now = self._now()
        actor = self._actor_from_input(payload.actor)
        thread = None
        thread_memberships: list[Membership] = []
        thread_events: list[EventEnvelope] = []
        if payload.thread_id is not None:
            thread = await self._repository.fetch_thread(payload.thread_id)
            if thread is None or thread.workspace_id != workspace_id:
                raise KeyError(f"Thread {payload.thread_id} not found")
        else:
            thread = Thread(
                thread_id=uuid4(),
                workspace_id=workspace_id,
                title=f"Methodics execution: {payload.target_goal or workspace.name}",
                created_at=now,
                updated_at=now,
                metadata={
                    "methodics_execution_thread": True,
                    "created_by": str(payload.actor.participant_id),
                },
            )
            thread_memberships.append(
                Membership(
                    membership_id=uuid4(),
                    workspace_id=workspace_id,
                    thread_id=thread.thread_id,
                    participant_id=actor_participant.participant_id,
                    role="owner",
                    permissions=["post_messages", "manage_thread", "edit_memory"],
                    joined_at=now,
                    metadata={"source": "methodics_execution_start"},
                )
            )
            thread_memberships.append(
                Membership(
                    membership_id=uuid4(),
                    workspace_id=workspace_id,
                    thread_id=thread.thread_id,
                    participant_id=methodics_agent_participant.participant_id,
                    role="agent",
                    permissions=["post_messages"],
                    joined_at=now,
                    metadata={"source": "methodics_execution_start"},
                )
            )

        execution_id = uuid4()
        steps: list[MethodicExecutionStep] = []
        selected_methodic_snapshots: list[dict[str, object]] = []
        for methodic_index in selected_indexes:
            methodic = methodics[methodic_index]
            selected_methodic_snapshots.append(
                {
                    "methodic_index": methodic_index,
                    **methodic.model_dump(mode="json"),
                }
            )
            for step_index, step in enumerate(methodic.steps):
                instruction = step.instruction.strip()
                if not instruction:
                    continue
                name = instruction.splitlines()[0][:96]
                definition_of_done = list(dict.fromkeys(
                    [*step.verification, *methodic.success_criteria]
                ))
                steps.append(
                    MethodicExecutionStep(
                        step_execution_id=uuid4(),
                        execution_id=execution_id,
                        workspace_id=workspace_id,
                        methodic_index=methodic_index,
                        step_index=step_index,
                        methodic_name=methodic.name,
                        name=name,
                        instruction=instruction,
                        status="pending",
                        expected_artifacts=list(step.expected_artifacts),
                        verification=list(step.verification),
                        definition_of_done=definition_of_done,
                        created_at=now,
                        updated_at=now,
                        metadata={
                            "methodic_goal": methodic.goal,
                            "recommended_tool_patterns": list(step.recommended_tool_patterns),
                        },
                    )
                )
        if not steps:
            raise ValueError("Selected workspace methodics have no executable steps")

        first_step = steps[0].model_copy(
            update={"status": "active", "started_at": now, "updated_at": now}
        )
        steps[0] = first_step
        execution = MethodicExecution(
            execution_id=execution_id,
            workspace_id=workspace_id,
            organization_id=workspace.organization_id,
            thread_id=thread.thread_id,
            conductor_system_agent_id=conductor_system_agent_id,
            conductor_participant_id=methodics_agent_participant.participant_id,
            status="running",
            target_goal=payload.target_goal,
            current_step_execution_id=first_step.step_execution_id,
            started_by=actor_participant.participant_id,
            started_at=now,
            harness_snapshot=workspace.harness.model_dump(mode="json"),
            methodics_snapshot=selected_methodic_snapshots,
            created_at=now,
            updated_at=now,
            metadata={
                **payload.metadata,
                "source": "WorkspaceHarness.methodics",
                "methodic_indexes": selected_indexes,
                "conductor_required": True,
            },
        )
        task, assignment = self._methodics_execution.agent_task_and_assignment(
            execution=execution,
            step=first_step,
            created_by=actor_participant.participant_id,
            now=now,
            task_kind=METHODICS_EXECUTION_START_TASK_KIND,
            title=f"Start methodics execution {execution_id}",
            description="Coordinate the first active methodic execution step.",
            task_instructions=[
                "Read the methodic execution snapshot and coordinate the active first step.",
                "Create participant assignments or resource requests as needed.",
                "Verify definition of done evidence before advancing the execution.",
            ],
        )

        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                if payload.thread_id is None:
                    await self._repository.upsert_thread(conn, thread)
                    for membership in thread_memberships:
                        await self._repository.upsert_membership(conn, membership)
                    thread_events.extend(
                        [
                            await self._build_thread_event(
                                conn,
                                workspace_id,
                                thread.thread_id,
                                "thread.created",
                                actor=actor,
                                target=TargetRef(type="thread", id=thread.thread_id),
                                payload=thread.model_dump(mode="json"),
                                timestamp=now,
                            ),
                            await self._build_thread_event(
                                conn,
                                workspace_id,
                                thread.thread_id,
                                "participant.joined",
                                actor=actor,
                                target=TargetRef(
                                    type="participant",
                                    id=actor_participant.participant_id,
                                ),
                                payload=thread_memberships[0].model_dump(mode="json"),
                                timestamp=now,
                            ),
                            await self._build_thread_event(
                                conn,
                                workspace_id,
                                thread.thread_id,
                                "participant.joined",
                                actor=actor,
                                target=TargetRef(
                                    type="participant",
                                    id=methodics_agent_participant.participant_id,
                                ),
                                payload=thread_memberships[1].model_dump(mode="json"),
                                timestamp=now,
                            ),
                        ]
                    )
                await self._repository.upsert_methodic_execution(conn, execution)
                for step in steps:
                    await self._repository.upsert_methodic_execution_step(conn, step)
                await self._repository.upsert_task(conn, task)
                await self._repository.upsert_methodic_execution_assignment(
                    conn,
                    assignment,
                )
                events = [
                    *thread_events,
                    await self._build_thread_event(
                        conn,
                        workspace_id,
                        thread.thread_id,
                        "methodic_execution.started",
                        actor=actor,
                        target=TargetRef(type="methodic_execution", id=execution_id),
                        visibility="workspace",
                        payload=execution.model_dump(mode="json"),
                        timestamp=now,
                        correlation_id=task.correlation_id,
                        causation_id=execution_id,
                    ),
                    EventEnvelope(
                        event_type="task.created",
                        workspace_id=workspace_id,
                        thread_id=thread.thread_id,
                        actor=actor,
                        target=TargetRef(type="task", id=task.task_id),
                        visibility="agents_only",
                        correlation_id=task.correlation_id,
                        causation_id=execution_id,
                        sequence=await self._repository.next_thread_sequence(
                            conn,
                            thread.thread_id,
                        ),
                        timestamp=now,
                        payload=task.model_dump(mode="json"),
                    ),
                ]
                for event in events:
                    await self._repository.record_event(conn, event)
        detail = await self._repository.get_methodic_execution_detail(execution_id)
        assert detail is not None
        return MethodicExecutionCommandResult(detail=detail, events=events)

    async def list_methodic_executions(
        self,
        workspace_id: UUID,
        *,
        status: str | None = None,
    ) -> list[MethodicExecution]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_methodic_executions(
            workspace_id=workspace_id,
            status=status,
        )

    async def get_methodic_execution(
        self,
        workspace_id: UUID,
        execution_id: UUID,
    ) -> MethodicExecutionDetail:
        detail = await self._repository.get_methodic_execution_detail(execution_id)
        if detail is None or detail.execution.workspace_id != workspace_id:
            raise KeyError(f"Methodic execution {execution_id} not found")
        return detail

    async def cancel_methodic_execution(
        self,
        workspace_id: UUID,
        execution_id: UUID,
        payload: CancelMethodicExecutionRequest,
    ) -> MethodicExecutionCommandResult:
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="methodics.execute",
        )
        detail = await self.get_methodic_execution(workspace_id, execution_id)
        if detail.execution.status in {"completed", "cancelled", "failed"}:
            return MethodicExecutionCommandResult(detail=detail)
        now = self._now()
        plan = self._methodics_execution.build_cancellation_plan(
            detail=detail,
            payload=payload,
            now=now,
        )
        actor = self._actor_from_input(payload.actor)
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                for assignment in plan.assignment_updates:
                    await self._repository.upsert_methodic_execution_assignment(
                        conn,
                        assignment,
                    )
                await self._repository.upsert_methodic_execution(conn, plan.execution)
                if plan.execution.thread_id is not None:
                    event = await self._build_thread_event(
                        conn,
                        workspace_id,
                        plan.execution.thread_id,
                        plan.event_spec.event_type,
                        actor=actor,
                        target=plan.event_spec.target,
                        visibility=plan.event_spec.visibility,
                        payload=plan.event_spec.payload,
                        timestamp=now,
                        causation_id=execution_id,
                    )
                    await self._repository.record_event(conn, event)
                    events.append(event)
        return MethodicExecutionCommandResult(
            detail=await self.get_methodic_execution(workspace_id, execution_id),
            events=events,
        )

    async def review_methodic_resource_request(
        self,
        workspace_id: UUID,
        resource_request_id: UUID,
        payload: ReviewMethodicResourceRequest,
        *,
        approved: bool,
    ) -> MethodicExecutionCommandResult:
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="methodics.admin",
        )
        request = await self._repository.fetch_methodic_resource_request(
            resource_request_id
        )
        if request is None or request.workspace_id != workspace_id:
            raise KeyError(f"Methodic resource request {resource_request_id} not found")
        if request.status != "pending":
            raise ValueError("Only pending methodic resource requests can be reviewed")
        if approved and request.required_permission:
            await self._require_workspace_permission(
                workspace_id,
                payload.actor,
                permission=request.required_permission,
            )
        now = self._now()
        updated = request.model_copy(
            update={
                "status": "approved" if approved else "rejected",
                "approved_by": payload.actor.participant_id if approved else None,
                "rejected_by": None if approved else payload.actor.participant_id,
                "decided_at": now,
                "updated_at": now,
                "metadata": {
                    **request.metadata,
                    **payload.metadata,
                    "review_reason": payload.reason,
                },
            }
        )
        actor = self._actor_from_input(payload.actor)
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_methodic_resource_request(conn, updated)
                execution = await self._repository.fetch_methodic_execution(
                    updated.execution_id
                )
                if execution is not None and execution.thread_id is not None:
                    event = await self._build_thread_event(
                        conn,
                        workspace_id,
                        execution.thread_id,
                        (
                            "methodic_resource_request.approved"
                            if approved
                            else "methodic_resource_request.rejected"
                        ),
                        actor=actor,
                        target=TargetRef(
                            type="methodic_resource_request",
                            id=resource_request_id,
                        ),
                        visibility="workspace",
                        payload=updated.model_dump(mode="json"),
                        timestamp=now,
                        causation_id=resource_request_id,
                    )
                    await self._repository.record_event(conn, event)
                    events.append(event)
        return MethodicExecutionCommandResult(resource_request=updated, events=events)

    async def create_methodic_resource_request(
        self,
        workspace_id: UUID,
        execution_id: UUID,
        payload: CreateMethodicResourceRequestRequest,
    ) -> MethodicExecutionCommandResult:
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="methodics.execute",
        )
        detail = await self.get_methodic_execution(workspace_id, execution_id)
        requester_system_agent_id: UUID | None = None
        if payload.actor.participant_type == "agent":
            participant = await self._repository.fetch_participant(
                workspace_id,
                payload.actor.participant_id,
            )
            if participant is not None:
                requester_system_agent_id = participant.system_agent_id
        now = self._now()
        plan = self._methodics_execution.build_resource_request_plan(
            detail=detail,
            payload=payload,
            requester_system_agent_id=requester_system_agent_id,
            now=now,
        )
        actor = self._actor_from_input(payload.actor)
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_methodic_resource_request(
                    conn,
                    plan.resource_request,
                )
                if detail.execution.thread_id is not None and plan.event_spec is not None:
                    event = await self._build_thread_event(
                        conn,
                        workspace_id,
                        detail.execution.thread_id,
                        plan.event_spec.event_type,
                        actor=actor,
                        target=plan.event_spec.target,
                        visibility=plan.event_spec.visibility,
                        payload=plan.event_spec.payload,
                        timestamp=now,
                        causation_id=execution_id,
                    )
                    await self._repository.record_event(conn, event)
                    events.append(event)
        return MethodicExecutionCommandResult(
            resource_request=plan.resource_request,
            events=events,
        )

    async def create_methodic_assignment(
        self,
        workspace_id: UUID,
        execution_id: UUID,
        payload: CreateMethodicAssignmentRequest,
    ) -> MethodicExecutionCommandResult:
        actor_participant = await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="methodics.execute",
        )
        detail = await self.get_methodic_execution(workspace_id, execution_id)
        assignee_participant_id = payload.assignee_participant_id
        assignee_system_agent_id = payload.assignee_system_agent_id
        if assignee_system_agent_id is not None and assignee_participant_id is None:
            assignee = await self._repository.fetch_agent_participant(
                workspace_id,
                assignee_system_agent_id,
            )
            if assignee is None:
                raise KeyError(
                    f"System agent {assignee_system_agent_id} is not attached to workspace {workspace_id}"
                )
            assignee_participant_id = assignee.participant_id
        if assignee_participant_id is not None:
            assignee = await self._repository.fetch_participant(
                workspace_id,
                assignee_participant_id,
            )
            if assignee is None:
                raise KeyError(f"Participant {assignee_participant_id} not found")
            if assignee_system_agent_id is None:
                assignee_system_agent_id = assignee.system_agent_id

        now = self._now()
        plan = self._methodics_execution.build_assignment_plan(
            detail=detail,
            payload=payload,
            actor_participant=actor_participant,
            assignee_participant_id=assignee_participant_id,
            assignee_system_agent_id=assignee_system_agent_id,
            now=now,
        )
        actor = self._actor_from_input(payload.actor)
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                if plan.updated_step is not None:
                    await self._repository.upsert_methodic_execution_step(
                        conn,
                        plan.updated_step,
                    )
                await self._repository.upsert_methodic_execution_assignment(
                    conn,
                    plan.assignment,
                )
                if detail.execution.thread_id is not None and plan.event_spec is not None:
                    event = await self._build_thread_event(
                        conn,
                        workspace_id,
                        detail.execution.thread_id,
                        plan.event_spec.event_type,
                        actor=actor,
                        target=plan.event_spec.target,
                        visibility=plan.event_spec.visibility,
                        payload=plan.event_spec.payload,
                        timestamp=now,
                        causation_id=execution_id,
                    )
                    await self._repository.record_event(conn, event)
                    events.append(event)
        return MethodicExecutionCommandResult(
            detail=await self.get_methodic_execution(workspace_id, execution_id),
            events=events,
        )

    async def evaluate_methodic_step(
        self,
        workspace_id: UUID,
        execution_id: UUID,
        payload: EvaluateMethodicStepRequest,
    ) -> MethodicExecutionCommandResult:
        actor_participant = await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="methodics.execute",
        )
        detail = await self.get_methodic_execution(workspace_id, execution_id)
        now = self._now()
        plan = self._methodics_execution.build_evaluation_plan(
            detail=detail,
            payload=payload,
            actor_participant=actor_participant,
            now=now,
        )
        actor = self._actor_from_input(payload.actor)
        event_specs = list(plan.event_specs)

        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_methodic_execution_check(conn, plan.check)
                for updated_step in plan.step_updates:
                    await self._repository.upsert_methodic_execution_step(conn, updated_step)
                for updated_assignment in plan.assignment_updates:
                    await self._repository.upsert_methodic_execution_assignment(
                        conn,
                        updated_assignment,
                    )
                await self._repository.upsert_methodic_execution(conn, plan.execution)
                for task in plan.new_tasks:
                    await self._repository.upsert_task(conn, task)
                for assignment in plan.new_assignments:
                    await self._repository.upsert_methodic_execution_assignment(
                        conn,
                        assignment,
                    )
                if plan.final_message is not None:
                    final_message = plan.final_message
                    final_message.sequence = await self._repository.next_thread_sequence(
                        conn,
                        final_message.thread_id,
                    )
                    await self._repository.upsert_message(conn, final_message)
                    event_specs.append(
                        MethodicsEventSpec(
                            event_type="message.created",
                            target=TargetRef(type="message", id=final_message.message_id),
                            payload=final_message.model_dump(mode="json"),
                            visibility=final_message.visibility,
                        )
                    )
                if plan.execution.thread_id is not None:
                    check_event = await self._build_thread_event(
                        conn,
                        workspace_id,
                        plan.execution.thread_id,
                        "methodic_execution_check.created",
                        actor=actor,
                        target=TargetRef(
                            type="methodic_execution_check",
                            id=plan.check.check_id,
                        ),
                        visibility="workspace",
                        payload=plan.check.model_dump(mode="json"),
                        timestamp=now,
                        causation_id=execution_id,
                    )
                    await self._repository.record_event(conn, check_event)
                    events.append(check_event)
                    for event_spec in event_specs:
                        event = await self._build_thread_event(
                            conn,
                            workspace_id,
                            plan.execution.thread_id,
                            event_spec.event_type,
                            actor=actor,
                            target=event_spec.target,
                            visibility=event_spec.visibility,
                            payload=event_spec.payload,
                            timestamp=now,
                            causation_id=execution_id,
                        )
                        await self._repository.record_event(conn, event)
                        events.append(event)
                    for task in plan.new_tasks:
                        event = EventEnvelope(
                            event_type="task.created",
                            workspace_id=workspace_id,
                            thread_id=plan.execution.thread_id,
                            actor=actor,
                            target=TargetRef(type="task", id=task.task_id),
                            visibility="agents_only",
                            correlation_id=task.correlation_id,
                            causation_id=execution_id,
                            sequence=await self._repository.next_thread_sequence(
                                conn,
                                plan.execution.thread_id,
                            ),
                            timestamp=now,
                            payload=task.model_dump(mode="json"),
                        )
                        await self._repository.record_event(conn, event)
                        events.append(event)
        return MethodicExecutionCommandResult(
            detail=await self.get_methodic_execution(workspace_id, execution_id),
            events=events,
        )

    async def store_retrieval_chunks(
        self,
        *,
        source_version_id: UUID,
        chunks: list[RetrievalChunk],
        embeddings: list[tuple[RetrievalEmbedding, list[float]]] | None = None,
    ) -> None:
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.replace_retrieval_chunks(
                    conn,
                    source_version_id=source_version_id,
                    chunks=chunks,
                )
                for embedding, vector in embeddings or []:
                    await self._repository.upsert_retrieval_embedding(
                        conn,
                        embedding,
                        vector=vector,
                    )

    async def activate_asset_version(
        self,
        asset_id: UUID,
        payload: ActivateAssetVersionRequest,
    ) -> WorkspaceAssetCommandResult:
        asset = await self._repository.fetch_workspace_asset(asset_id)
        if asset is None:
            raise KeyError(f"Workspace asset {asset_id} not found")
        version = await self._repository.fetch_workspace_asset_version(payload.asset_version_id)
        if version is None or version.asset_id != asset_id:
            raise KeyError(
                f"Asset version {payload.asset_version_id} does not belong to asset {asset_id}"
            )
        await self._validate_asset_link_target(
            target_type=payload.target_type,
            target_id=payload.target_id,
            organization_id=asset.organization_id,
            workspace_id=payload.workspace_id,
        )
        if payload.workspace_id is not None:
            workspace = await self._repository.fetch_workspace(payload.workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {payload.workspace_id} not found")
            if asset.organization_id is not None and workspace.organization_id != asset.organization_id:
                raise ValueError(
                    "Workspace asset links must stay within the asset organization"
                )
        now = self._now()
        link = AssetLink(
            link_id=uuid4(),
            asset_id=asset_id,
            asset_version_id=payload.asset_version_id,
            organization_id=asset.organization_id,
            workspace_id=payload.workspace_id,
            target_type=payload.target_type,
            target_id=payload.target_id,
            purpose=payload.purpose,
            active=True,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.deactivate_asset_links(
                    conn,
                    organization_id=asset.organization_id,
                    workspace_id=payload.workspace_id,
                    target_type=payload.target_type,
                    target_id=payload.target_id,
                    purpose=payload.purpose,
                )
                await self._repository.upsert_asset_link(conn, link)
        return WorkspaceAssetCommandResult(asset=asset, version=version, link=link)

    async def link_asset_version(
        self,
        asset_id: UUID,
        payload: LinkAssetRequest,
    ) -> WorkspaceAssetCommandResult:
        activation = ActivateAssetVersionRequest.model_validate(payload.model_dump(mode="json"))
        return await self.activate_asset_version(asset_id, activation)

    async def list_resolved_agent_assets(
        self,
        *,
        agent_id: UUID,
        workspace_id: UUID | None = None,
    ) -> list[ResolvedAssetBinding]:
        agent = await self._repository.fetch_system_agent(agent_id)
        if agent is None:
            raise KeyError(f"System agent {agent_id} not found")
        workspace: Workspace | None = None
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            if not self._resource_visible_to_workspace(
                agent.scope,
                agent.organization_id,
                workspace,
            ):
                raise PermissionError(
                    f"System agent {agent_id} is not visible in workspace {workspace_id}"
                )
        return await self._repository.list_asset_links_for_target(
            target_type="system_agent",
            target_id=agent_id,
            organization_id=workspace.organization_id if workspace is not None else None,
            workspace_id=workspace_id,
        )

    async def list_resolved_tool_assets(
        self,
        *,
        tool_id: UUID,
        workspace_id: UUID | None = None,
    ) -> list[ResolvedAssetBinding]:
        tool = await self._repository.fetch_system_tool(tool_id)
        if tool is None:
            raise KeyError(f"System tool {tool_id} not found")
        workspace: Workspace | None = None
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            if not self._resource_visible_to_workspace(
                tool.scope,
                tool.organization_id,
                workspace,
            ):
                raise PermissionError(
                    f"System tool {tool_id} is not visible in workspace {workspace_id}"
                )
        return await self._repository.list_asset_links_for_target(
            target_type="system_tool",
            target_id=tool_id,
            organization_id=workspace.organization_id if workspace is not None else None,
            workspace_id=workspace_id,
        )

    async def delete_llm_provider(
        self, provider_id: UUID, payload: DeleteLlmProviderRequest
    ) -> dict[str, bool | str]:
        existing = await self._repository.fetch_llm_provider(provider_id)
        if existing is None:
            raise KeyError(f"LLM provider {provider_id} not found")
        references = await self._llm_provider_references(existing.engine_id)
        if references:
            raise ValueError(
                f"Cannot delete LLM provider {existing.engine_id!r}; "
                f"referenced by system agents: {', '.join(agent.display_name for agent in references)}"
            )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_llm_provider(
                    conn,
                    provider_id=provider_id,
                )
        if not deleted:
            raise KeyError(f"LLM provider {provider_id} not found")
        return {"deleted": True, "provider_id": str(provider_id)}

    async def delete_memory_provider(
        self, provider_id: UUID, payload: DeleteMemoryProviderRequest
    ) -> dict[str, bool | str]:
        _ = payload
        existing = await self._repository.fetch_memory_provider(provider_id)
        if existing is None:
            raise KeyError(f"Memory provider {provider_id} not found")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_memory_provider(
                    conn,
                    provider_id=provider_id,
                )
        if not deleted:
            raise KeyError(f"Memory provider {provider_id} not found")
        return {"deleted": True, "provider_id": str(provider_id)}

    async def _llm_provider_references(self, engine_id: str) -> list[AgentDefinition]:
        return await self._repository.list_system_agents_referencing_llm_engine(engine_id)

    async def _resolve_search_memory_provider(
        self,
        preferred_provider_key: str | None,
        *,
        organization_id: UUID | None = None,
    ) -> MemoryProviderDefinition:
        providers = await self._visible_enabled_memory_providers(organization_id)
        if preferred_provider_key:
            for provider in providers:
                if provider.provider_key == preferred_provider_key:
                    return provider
            raise KeyError(f"Enabled memory provider {preferred_provider_key!r} not found")
        for provider in providers:
            if provider.provider == "mem0":
                return provider
        for provider in providers:
            if provider.provider == "postgres":
                return provider
        raise ValueError("No enabled memory providers configured")

    async def _sync_memory_entry(self, entry: MemoryEntry) -> None:
        workspace = await self._repository.fetch_workspace(entry.workspace_id)
        organization_id = workspace.organization_id if workspace is not None else None
        providers = await self._visible_enabled_memory_providers(organization_id)
        now = self._now()
        for definition in providers:
            provider = self._memory_provider_index.get(definition.provider)
            if provider is None:
                continue
            existing_record = await self._repository.fetch_memory_provider_record(
                memory_entry_id=entry.memory_entry_id,
                provider_id=definition.provider_id,
            )
            try:
                result = await provider.upsert(
                    definition,
                    entry,
                    external_id=existing_record.external_id if existing_record else None,
                )
                record = MemoryProviderRecord(
                    provider_record_id=(
                        existing_record.provider_record_id
                        if existing_record is not None
                        else uuid4()
                    ),
                    memory_entry_id=entry.memory_entry_id,
                    provider_id=definition.provider_id,
                    external_id=(
                        result.external_id
                        or (existing_record.external_id if existing_record else None)
                    ),
                    status="synced",
                    last_synced_at=now,
                    last_error=None,
                    metadata=result.metadata,
                )
            except Exception as exc:
                logger.warning(
                    "Memory provider sync failed provider=%s memory_entry_id=%s error=%s",
                    definition.provider_key,
                    entry.memory_entry_id,
                    exc,
                )
                record = MemoryProviderRecord(
                    provider_record_id=(
                        existing_record.provider_record_id
                        if existing_record is not None
                        else uuid4()
                    ),
                    memory_entry_id=entry.memory_entry_id,
                    provider_id=definition.provider_id,
                    external_id=existing_record.external_id if existing_record else None,
                    status="failed",
                    last_synced_at=now,
                    last_error=str(exc),
                    metadata=existing_record.metadata if existing_record else {},
                )
            async with self._repository._pool.acquire() as conn:  # noqa: SLF001
                async with conn.transaction():
                    await self._repository.upsert_memory_provider_record(conn, record)

    async def _delete_memory_entry_from_providers(self, entry: MemoryEntry) -> None:
        records = await self._repository.list_memory_provider_records(entry.memory_entry_id)
        now = self._now()
        workspace = await self._repository.fetch_workspace(entry.workspace_id)
        organization_id = workspace.organization_id if workspace is not None else None
        visible_provider_ids = {
            provider.provider_id
            for provider in await self._visible_enabled_memory_providers(organization_id)
        }
        for record in records:
            if record.provider_id not in visible_provider_ids:
                continue
            definition = await self._repository.fetch_memory_provider(record.provider_id)
            if definition is None:
                continue
            provider = self._memory_provider_index.get(definition.provider)
            if provider is None:
                continue
            try:
                await provider.delete(
                    definition,
                    entry,
                    external_id=record.external_id,
                )
                updated_record = record.model_copy(
                    update={
                        "status": "archived",
                        "last_synced_at": now,
                        "last_error": None,
                    }
                )
            except Exception as exc:
                logger.warning(
                    "Memory provider delete failed provider=%s memory_entry_id=%s error=%s",
                    definition.provider_key,
                    entry.memory_entry_id,
                    exc,
                )
                updated_record = record.model_copy(
                    update={
                        "status": "failed",
                        "last_synced_at": now,
                        "last_error": str(exc),
                    }
                )
            async with self._repository._pool.acquire() as conn:  # noqa: SLF001
                async with conn.transaction():
                    await self._repository.upsert_memory_provider_record(conn, updated_record)

    async def _backfill_system_agent_interaction_contracts(self) -> None:
        try:
            agents = await self._repository.list_system_agents(scope="global")
            organizations = await self._repository.list_organizations()
            for organization in organizations:
                agents.extend(
                    await self._repository.list_system_agents(
                        scope="organization",
                        organization_id=organization.organization_id,
                    )
                )
        except (AttributeError, TypeError):
            agents = await self._repository.list_system_agents()
        missing = [
            agent
            for agent in agents
            if interaction_contract_is_empty(agent.interaction_contract)
        ]
        if not missing:
            return
        logger.info(
            "Backfilling interaction contracts for %s system agents",
            len(missing),
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                for agent in missing:
                    updated = agent.model_copy(
                        update={
                            "interaction_contract": build_default_interaction_contract(
                                display_name=agent.display_name,
                                role=agent.role,
                                description=agent.description,
                                capabilities=agent.capabilities,
                            ),
                            "updated_at": self._now(),
                        }
                    )
                    await self._repository.upsert_system_agent(conn, updated)

    async def upsert_role_definition(
        self,
        workspace_id: UUID,
        payload: UpsertRoleDefinitionRequest,
    ) -> RoleDefinitionCommandResult:
        logger.debug(
            "Kernel upsert_role_definition workspace_id=%s actor_id=%s name=%r",
            workspace_id,
            payload.actor.participant_id,
            payload.name,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="workspace.roles.write",
        )
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        role_definition = RoleDefinition(
            name=payload.name,
            definition=payload.definition,
            updated_by=payload.actor.participant_id,
            updated_at=now,
        )
        role_map = {
            role.name: role.model_dump(mode="json")
            for role in self._role_definitions_from_workspace(workspace)
        }
        role_map[role_definition.name] = role_definition.model_dump(mode="json")
        updated_workspace = workspace.model_copy(
            update={
                "updated_at": now,
                "metadata": {
                    **workspace.metadata,
                    "role_definitions": role_map,
                },
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace(conn, updated_workspace)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "role_definition.upserted",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=role_definition.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return RoleDefinitionCommandResult(role_definition=role_definition, events=[event])

    async def delete_role_definition(
        self,
        workspace_id: UUID,
        role_name: str,
        payload: DeleteRoleDefinitionRequest,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Kernel delete_role_definition workspace_id=%s actor_id=%s name=%r",
            workspace_id,
            payload.actor.participant_id,
            role_name,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="workspace.roles.write",
        )
        now = self._now()
        actor = self._actor_from_input(payload.actor)

        role_map = {
            role.name: role.model_dump(mode="json")
            for role in self._role_definitions_from_workspace(workspace)
        }
        if role_name not in role_map:
            raise KeyError(f"Role {role_name} not found in workspace {workspace_id}")

        removed_role_data = role_map.pop(role_name)
        updated_workspace = workspace.model_copy(
            update={
                "updated_at": now,
                "metadata": {**workspace.metadata, "role_definitions": role_map},
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace(conn, updated_workspace)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "role_definition.deleted",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=removed_role_data,
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return {"deleted": True, "workspace_id": str(workspace_id), "role_name": role_name}

    async def list_workspace_tools(self, workspace_id: UUID) -> list[WorkspaceTool]:
        logger.debug("Kernel list_workspace_tools workspace_id=%s", workspace_id)
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_workspace_tools(workspace_id)

    async def list_workspace_mcp_servers(self, workspace_id: UUID) -> list[WorkspaceMcpServer]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_workspace_mcp_servers(workspace_id)

    async def list_workspace_mcp_tools(self, workspace_id: UUID) -> list[WorkspaceMcpTool]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_workspace_mcp_tools(workspace_id)

    async def list_workspace_mcp_resources(self, workspace_id: UUID) -> list[WorkspaceMcpResource]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_workspace_mcp_resources(workspace_id)

    async def list_workspace_mcp_prompts(self, workspace_id: UUID) -> list[WorkspaceMcpPrompt]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_workspace_mcp_prompts(workspace_id)

    async def attach_workspace_mcp_server(
        self,
        workspace_id: UUID,
        payload: AttachWorkspaceMcpServerRequest,
    ) -> McpServerCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="workspace.mcp_servers.write",
        )
        if payload.server_id is None:
            raise ValueError("server_id is required")
        server = await self._repository.fetch_mcp_server(payload.server_id)
        if server is None:
            raise KeyError(f"MCP server {payload.server_id} not found")
        if not self._resource_visible_to_workspace(server.scope, server.organization_id, workspace):
            raise PermissionError(f"MCP server {payload.server_id} is not visible in workspace {workspace_id}")
        now = self._now()
        prefix = payload.name_prefix
        if prefix is None:
            prefix = f"mcp_{server.server_key}__"
        binding = WorkspaceMcpServer(
            server_id=server.server_id,
            server_key=server.server_key,
            display_name=server.display_name,
            description=server.description,
            transport_kind=server.transport_kind,
            trust_level=server.trust_level,
            server_enabled=server.enabled,
            enabled=payload.enabled,
            tools_enabled=payload.tools_enabled,
            resources_enabled=payload.resources_enabled,
            prompts_enabled=payload.prompts_enabled,
            sampling_enabled=payload.sampling_enabled,
            name_prefix=prefix,
            tool_allowlist=payload.tool_allowlist,
            tool_denylist=payload.tool_denylist,
            resource_allowlist=payload.resource_allowlist,
            prompt_allowlist=payload.prompt_allowlist,
            attached_by=payload.actor.participant_id,
            attached_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace_mcp_server(
                    conn,
                    workspace_id=workspace_id,
                    binding=binding,
                )
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.mcp_server_attached",
                    actor=self._actor_from_input(payload.actor),
                    target=TargetRef(type="mcp_server", id=server.server_id),
                    payload=binding.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return McpServerCommandResult(server=server, binding=binding, events=[event])

    async def update_workspace_mcp_server(
        self,
        workspace_id: UUID,
        server_id: UUID,
        payload: UpdateWorkspaceMcpServerRequest,
    ) -> McpServerCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="workspace.mcp_servers.write",
        )
        existing = await self._repository.fetch_workspace_mcp_server(workspace_id, server_id)
        if existing is None:
            raise KeyError(f"MCP server {server_id} not attached to workspace {workspace_id}")
        server = await self._repository.fetch_mcp_server(server_id)
        if server is None:
            raise KeyError(f"MCP server {server_id} not found")
        now = self._now()
        updated = existing.model_copy(
            update={
                "enabled": existing.enabled if payload.enabled is None else payload.enabled,
                "tools_enabled": (
                    existing.tools_enabled
                    if payload.tools_enabled is None
                    else payload.tools_enabled
                ),
                "resources_enabled": (
                    existing.resources_enabled
                    if payload.resources_enabled is None
                    else payload.resources_enabled
                ),
                "prompts_enabled": (
                    existing.prompts_enabled
                    if payload.prompts_enabled is None
                    else payload.prompts_enabled
                ),
                "sampling_enabled": (
                    existing.sampling_enabled
                    if payload.sampling_enabled is None
                    else payload.sampling_enabled
                ),
                "name_prefix": existing.name_prefix if payload.name_prefix is None else payload.name_prefix,
                "tool_allowlist": existing.tool_allowlist if payload.tool_allowlist is None else payload.tool_allowlist,
                "tool_denylist": existing.tool_denylist if payload.tool_denylist is None else payload.tool_denylist,
                "resource_allowlist": existing.resource_allowlist if payload.resource_allowlist is None else payload.resource_allowlist,
                "prompt_allowlist": existing.prompt_allowlist if payload.prompt_allowlist is None else payload.prompt_allowlist,
                "updated_at": now,
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace_mcp_server(
                    conn,
                    workspace_id=workspace_id,
                    binding=updated,
                )
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.mcp_server_updated",
                    actor=self._actor_from_input(payload.actor),
                    target=TargetRef(type="mcp_server", id=server_id),
                    payload=updated.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return McpServerCommandResult(server=server, binding=updated, events=[event])

    async def delete_workspace_mcp_server(
        self,
        workspace_id: UUID,
        server_id: UUID,
        payload: DeleteWorkspaceMcpServerRequest,
    ) -> dict[str, bool | str]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="workspace.mcp_servers.write",
        )
        existing = await self._repository.fetch_workspace_mcp_server(workspace_id, server_id)
        if existing is None:
            raise KeyError(f"MCP server {server_id} not attached to workspace {workspace_id}")
        now = self._now()
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_workspace_mcp_server(
                    conn,
                    workspace_id=workspace_id,
                    server_id=server_id,
                )
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.mcp_server_detached",
                    actor=self._actor_from_input(payload.actor),
                    target=TargetRef(type="mcp_server", id=server_id),
                    payload=existing.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        if not deleted:
            raise KeyError(f"MCP server {server_id} not attached to workspace {workspace_id}")
        return {"deleted": True, "server_id": str(server_id), "workspace_id": str(workspace_id)}

    async def attach_workspace_tool(
        self,
        workspace_id: UUID,
        payload: AttachWorkspaceToolRequest,
    ) -> WorkspaceToolCommandResult:
        logger.debug(
            "Kernel attach_workspace_tool workspace_id=%s actor_id=%s tool_id=%s enabled=%s",
            workspace_id,
            payload.actor.participant_id,
            payload.tool_id,
            payload.enabled,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="workspace.tools.write",
        )
        system_tool = await self._repository.fetch_system_tool(payload.tool_id)
        if system_tool is None:
            raise KeyError(f"System tool {payload.tool_id} not found")
        if bool(system_tool.metadata.get("internal_only")):
            raise PermissionError(
                f"System tool {payload.tool_id} is internal-only and cannot be attached to workspaces"
            )
        if not self._resource_visible_to_workspace(
            system_tool.scope,
            system_tool.organization_id,
            workspace,
        ):
            raise PermissionError(
                f"System tool {payload.tool_id} is not visible in workspace {workspace_id}"
            )
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        tool = WorkspaceTool(
            tool_id=system_tool.tool_id,
            name=system_tool.name,
            description=system_tool.description,
            parameter_contract=system_tool.parameter_contract,
            input_schema=system_tool.input_schema,
            execution=system_tool.execution,
            enabled=payload.enabled,
            attached_by=payload.actor.participant_id,
            attached_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace_tool(
                    conn,
                    workspace_id=workspace_id,
                    tool=tool,
                )
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.tool_attached",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=tool.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return WorkspaceToolCommandResult(tool=tool, events=[event])

    async def update_workspace_tool(
        self,
        workspace_id: UUID,
        tool_id: UUID,
        payload: UpdateWorkspaceToolRequest,
    ) -> WorkspaceToolCommandResult:
        logger.debug(
            "Kernel update_workspace_tool workspace_id=%s actor_id=%s tool_id=%s",
            workspace_id,
            payload.actor.participant_id,
            tool_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="workspace.tools.write",
        )
        existing = await self._repository.fetch_workspace_tool(workspace_id, tool_id)
        if existing is None:
            raise KeyError(f"Workspace tool {tool_id} not attached to workspace {workspace_id}")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        updated = existing.model_copy(
            update={
                "enabled": existing.enabled if payload.enabled is None else payload.enabled,
                "updated_at": now,
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace_tool(
                    conn,
                    workspace_id=workspace_id,
                    tool=updated,
                )
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.tool_updated",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=updated.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return WorkspaceToolCommandResult(tool=updated, events=[event])

    async def delete_workspace_tool(
        self,
        workspace_id: UUID,
        tool_id: UUID,
        payload: DeleteWorkspaceToolRequest,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Kernel delete_workspace_tool workspace_id=%s actor_id=%s tool_id=%s",
            workspace_id,
            payload.actor.participant_id,
            tool_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="workspace.tools.write",
        )
        removed = await self._repository.fetch_workspace_tool(workspace_id, tool_id)
        if removed is None:
            raise KeyError(f"Workspace tool {tool_id} not attached to workspace {workspace_id}")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_workspace_tool(
                    conn,
                    workspace_id=workspace_id,
                    tool_id=tool_id,
                )
                if not deleted:
                    raise KeyError(f"Workspace tool {tool_id} not attached to workspace {workspace_id}")
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.tool_deleted",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=removed.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return {"deleted": True, "workspace_id": str(workspace_id), "tool_id": str(tool_id)}

    async def assume_participant_role(
        self,
        workspace_id: UUID,
        participant_id: UUID,
        payload: AssumeParticipantRoleRequest,
    ) -> ParticipantCommandResult:
        logger.debug(
            "Kernel assume_participant_role workspace_id=%s participant_id=%s actor_id=%s role=%r capability_count=%s",
            workspace_id,
            participant_id,
            payload.actor.participant_id,
            payload.role,
            len(payload.capabilities),
        )
        if participant_id != payload.actor.participant_id:
            raise ValueError("Participants may only assume roles for themselves")
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        existing = await self._repository.fetch_participant(workspace_id, participant_id)
        role_definitions = {
            role_definition.name: role_definition
            for role_definition in self._role_definitions_from_workspace(workspace)
        }
        role_definition = role_definitions.get(payload.role)
        if payload.description is None and role_definition is None:
            raise ValueError(
                f"Role {payload.role!r} is not defined in this workspace; provide a description or create the role first"
            )
        description = payload.description or (role_definition.definition if role_definition else None)
        participant = ParticipantProfile(
            participant_id=participant_id,
            workspace_id=workspace_id,
            participant_type=payload.actor.participant_type,
            user_id=self._actor_user_id(payload.actor)
            if payload.actor.participant_type == "user"
            else None,
            display_name=payload.actor.display_name,
            description=description,
            roles=[payload.role],
            capabilities=payload.capabilities,
            status=existing.status if existing is not None else "active",
            visibility_scope=payload.actor.visibility_scope,
            agent_config=existing.agent_config if existing is not None else None,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            metadata=(existing.metadata if existing is not None else {}),
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                if workspace.project_id is not None and hasattr(
                    self._repository,
                    "upsert_project_access_binding",
                ):
                    await self._repository.upsert_project_access_binding(
                        conn,
                        self._project_access_binding(
                            workspace.project_id,
                            self._actor_project_subject(payload.actor),
                            "viewer",
                            now=now,
                            metadata={"source": "workspace_participant_role_assumed"},
                        ),
                    )
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "participant.role_assumed",
                    actor=actor,
                    target=TargetRef(type="participant", id=participant.participant_id),
                    payload=participant.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        logger.debug(
            "Kernel assume_participant_role complete workspace_id=%s participant_id=%s sequence=%s",
            workspace_id,
            participant_id,
            event.sequence,
        )
        return ParticipantCommandResult(participant=participant, events=[event])

    async def create_agent_participant(
        self,
        workspace_id: UUID,
        payload: CreateAgentParticipantRequest,
    ) -> ParticipantCommandResult:
        logger.debug(
            "Kernel create_agent_participant workspace_id=%s actor_id=%s agent_id=%s",
            workspace_id,
            payload.actor.participant_id,
            payload.agent_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="workspace.agents.write",
        )
        system_agent = await self._repository.fetch_system_agent(payload.agent_id)
        if system_agent is None:
            raise KeyError(f"System agent {payload.agent_id} not found")
        if not self._resource_visible_to_workspace(
            system_agent.scope,
            system_agent.organization_id,
            workspace,
        ):
            raise PermissionError(
                f"System agent {payload.agent_id} is not visible in workspace {workspace_id}"
            )
        workspace_tools = await self._repository.list_workspace_tools(workspace_id)
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant_metadata: dict[str, object] = {}
        task_routing = system_agent.definition.get("task_routing")
        if isinstance(task_routing, dict):
            participant_metadata["task_routing"] = task_routing
        participant = ParticipantProfile(
            participant_id=uuid4(),
            workspace_id=workspace_id,
            participant_type="agent",
            system_agent_id=system_agent.agent_id,
            display_name=system_agent.display_name,
            description=system_agent.description,
            roles=[system_agent.role],
            capabilities=self._advertised_agent_capabilities(
                system_agent.capabilities,
                workspace_tools,
            ),
            status="active",
            visibility_scope="workspace",
            agent_config=AgentConfiguration(
                endpoint=system_agent.endpoint,
                system_prompt=system_agent.system_prompt,
                harness=system_agent.harness,
                definition=system_agent.definition,
            ),
            created_at=now,
            updated_at=now,
            metadata=participant_metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "participant.agent_registered",
                    actor=actor,
                    target=TargetRef(type="participant", id=participant.participant_id),
                    payload=participant.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return ParticipantCommandResult(
            participant=self._advertise_workspace_tools(participant, workspace_tools),
            events=[event],
        )

    async def update_agent_participant(
        self,
        workspace_id: UUID,
        participant_id: UUID,
        payload: UpdateAgentParticipantRequest,
    ) -> ParticipantCommandResult:
        logger.debug(
            "Kernel update_agent_participant workspace_id=%s participant_id=%s actor_id=%s",
            workspace_id,
            participant_id,
            payload.actor.participant_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_permission(
            workspace_id,
            payload.actor,
            permission="workspace.agents.write",
        )
        existing = await self._repository.fetch_participant(workspace_id, participant_id)
        if existing is None:
            raise KeyError(f"Participant {participant_id} not found")
        if existing.participant_type != "agent":
            raise ValueError("Only agent participants can be updated via the agent API")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        workspace_tools = await self._repository.list_workspace_tools(workspace_id)
        updated = existing.model_copy(
            update={
                "visibility_scope": (
                    payload.visibility_scope or existing.visibility_scope
                ),
                "status": payload.status or existing.status,
                "updated_at": now,
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_participant(conn, updated)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "participant.agent_updated",
                    actor=actor,
                    target=TargetRef(type="participant", id=participant_id),
                    payload=updated.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return ParticipantCommandResult(
            participant=self._advertise_workspace_tools(updated, workspace_tools),
            events=[event],
        )

    async def create_thread(
        self, workspace_id: UUID, payload: CreateThreadRequest
    ) -> ThreadCommandResult:
        logger.debug(
            "Kernel create_thread workspace_id=%s participant_id=%s title=%r",
            workspace_id,
            payload.actor.participant_id,
            payload.title,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        thread_id = uuid4()
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        )
        thread = Thread(
            thread_id=thread_id,
            workspace_id=workspace_id,
            title=payload.title,
            parent_thread_id=payload.parent_thread_id,
            previous_thread_id=payload.previous_thread_id,
            related_thread_ids=payload.related_thread_ids,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        membership = Membership(
            membership_id=uuid4(),
            workspace_id=workspace_id,
            thread_id=thread_id,
            participant_id=payload.actor.participant_id,
            role="owner",
            permissions=["post_messages", "manage_thread", "edit_memory"],
            joined_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_thread(conn, thread)
                await self._repository.upsert_membership(conn, membership)
                events = [
                    await self._build_thread_event(
                        conn,
                        workspace_id,
                        thread_id,
                        "thread.created",
                        actor=actor,
                        target=TargetRef(type="thread", id=thread.thread_id),
                        payload=thread.model_dump(mode="json"),
                        timestamp=now,
                    ),
                    await self._build_thread_event(
                        conn,
                        workspace_id,
                        thread_id,
                        "participant.joined",
                        actor=actor,
                        target=TargetRef(type="participant", id=participant.participant_id),
                        payload=membership.model_dump(mode="json"),
                        visibility="workspace",
                        timestamp=now,
                    ),
                ]
                for event in events:
                    await self._repository.record_event(conn, event)

        detail = ThreadDetail(thread=thread, memberships=[membership])
        logger.debug(
            "Kernel create_thread complete thread_id=%s event_count=%s",
            thread_id,
            len(events),
        )
        return ThreadCommandResult(thread=thread, detail=detail, events=events)

    async def list_threads(self, workspace_id: UUID) -> list[Thread]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_threads(workspace_id)

    async def get_thread_detail(self, thread_id: UUID) -> ThreadDetail:
        logger.debug("Kernel get_thread_detail thread_id=%s", thread_id)
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        memberships = await self._repository.list_memberships(thread_id)
        return ThreadDetail(thread=thread, memberships=memberships)

    async def get_thread_timeline(
        self,
        thread_id: UUID,
        *,
        viewer: ParticipantInput | None = None,
    ) -> TimelinePage:
        logger.debug("Kernel get_thread_timeline thread_id=%s", thread_id)
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        messages = await self._repository.list_timeline_messages(thread_id)
        if viewer is not None:
            participant = await self._repository.fetch_participant(
                thread.workspace_id,
                viewer.participant_id,
            )
            if participant is not None:
                messages = self._filter_visible_messages(
                    messages,
                    viewer=participant,
                    sequence_ceiling=None,
                )
        return TimelinePage(thread_id=thread_id, messages=messages)

    async def list_workspace_communication_log(
        self,
        workspace_id: UUID,
        *,
        thread_id: UUID | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> WorkspaceCommunicationLogPage:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        if thread_id is not None:
            thread = await self._repository.fetch_thread(thread_id)
            if thread is None or thread.workspace_id != workspace_id:
                raise KeyError(f"Thread {thread_id} not found")
        return await self._repository.list_workspace_communication_log(
            workspace_id,
            thread_id=thread_id,
            limit=limit,
            offset=offset,
        )

    async def _persist_workspace_communication_messages(
        self,
        messages: list[TimelineMessage],
    ) -> None:
        if not messages:
            return
        await self._repository.persist_workspace_communication_messages(messages)

    async def list_pending_tasks_for_system_agent(
        self, system_agent_id: UUID, *, limit: int = 10
    ) -> list[Task]:
        return await self._runtime_execution.list_pending_tasks_for_system_agent(
            system_agent_id,
            limit=limit,
        )

    async def claim_task_for_system_agent(
        self,
        task_id: UUID,
        system_agent_id: UUID,
    ) -> TaskCommandResult:
        return await self._runtime_execution.claim_task_for_system_agent(
            task_id,
            system_agent_id,
        )

    async def build_agent_execution_context(
        self,
        task_id: UUID,
        system_agent_id: UUID,
        run_id: UUID | None = None,
    ) -> AgentExecutionContext:
        return await self._runtime_execution.build_agent_execution_context(
            task_id,
            system_agent_id,
            run_id,
        )

    async def build_agent_execution_context_for_run_step(
        self,
        step_id: UUID,
    ) -> AgentExecutionContext:
        return await self._runtime_execution.build_agent_execution_context_for_run_step(
            step_id
        )

    async def enforce_run_step_token_budget(
        self,
        *,
        step_id: UUID,
        worker_id: str,
        global_daily_token_cap: int,
        default_workspace_daily_token_cap: int,
    ) -> RunCommandResult | None:
        return await self._runtime_execution.enforce_run_step_token_budget(
            step_id=step_id,
            worker_id=worker_id,
            global_daily_token_cap=global_daily_token_cap,
            default_workspace_daily_token_cap=default_workspace_daily_token_cap,
        )

    async def get_runtime_overview(
        self,
        *,
        organization_id: UUID | None = None,
    ) -> dict[str, object]:
        return await self._runtime_execution.get_runtime_overview(
            organization_id=organization_id,
        )

    async def claim_next_run_step(
        self,
        *,
        worker_id: str,
        lease_ttl_seconds: int,
    ) -> RunStepCommandResult:
        return await self._runtime_execution.claim_next_run_step(
            worker_id=worker_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    async def heartbeat_run_step(
        self,
        *,
        step_id: UUID,
        worker_id: str,
        lease_ttl_seconds: int,
    ) -> RunStep | None:
        now = self._now()
        return await self._repository.heartbeat_run_step(
            step_id=step_id,
            worker_id=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_ttl_seconds),
            now=now,
        )

    async def queue_tool_calls_for_run_step(
        self,
        step_id: UUID,
        worker_id: str,
        drafts: list[AgentToolCallDraft],
    ) -> RunStepCommandResult:
        step = await self._repository.fetch_run_step(step_id)
        if step is None:
            raise KeyError(f"Run step {step_id} not found")
        if step.claimed_by_worker != worker_id:
            raise ValueError(f"Run step {step_id} is not claimed by worker {worker_id}")
        run = await self._repository.fetch_run(step.run_id)
        if run is None:
            raise KeyError(f"Run {step.run_id} not found")
        task = await self._repository.fetch_task(step.task_id)
        if task is None:
            raise KeyError(f"Task {step.task_id} not found")
        system_agent = await self._repository.fetch_system_agent(step.system_agent_id)
        if system_agent is None:
            raise KeyError(f"System agent {step.system_agent_id} not found")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=step.system_agent_id,
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        now = self._now()
        queued_step = step.model_copy(
            update={
                "status": "waiting_tools",
                "output": {
                    "tool_calls_requested": [
                        draft.model_dump(mode="json") for draft in drafts
                    ]
                },
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "updated_at": now,
            }
        )
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run_step(conn, queued_step)
                for draft in drafts:
                    tool = await self._repository.fetch_agent_internal_tool_by_name(
                        step.system_agent_id,
                        draft.tool_name,
                    )
                    mcp_tool = None
                    mcp_source = None
                    if tool is None and hasattr(
                        self._repository,
                        "fetch_agent_internal_mcp_tool_by_name",
                    ):
                        mcp_tool = await self._repository.fetch_agent_internal_mcp_tool_by_name(
                            step.system_agent_id,
                            draft.tool_name,
                        )
                        if mcp_tool is not None:
                            mcp_source = "agent_internal_mcp_server"
                    if tool is None:
                        tool = await self._repository.fetch_workspace_tool_by_name(
                            task.workspace_id,
                            draft.tool_name,
                        )
                    if tool is None:
                        if mcp_tool is None:
                            mcp_tool = await self._repository.fetch_workspace_mcp_tool_by_name(
                                task.workspace_id,
                                draft.tool_name,
                            )
                            if mcp_tool is not None:
                                mcp_source = "mcp_server"
                    if tool is None and mcp_tool is None:
                        raise KeyError(
                            f"Tool {draft.tool_name!r} not found for system agent {step.system_agent_id} in workspace {task.workspace_id}"
                        )
                    execution_spec = (
                        self._build_tool_execution_spec(
                            tool=tool,
                            draft=draft,
                            workspace_id=task.workspace_id,
                        )
                        if tool is not None
                        else self._build_mcp_tool_execution_spec(
                            tool=mcp_tool,
                            draft=draft,
                            workspace_id=task.workspace_id,
                            system_agent_id=step.system_agent_id,
                            source=mcp_source or "mcp_server",
                        )
                    )
                    tool_call = ToolCall(
                        tool_call_id=uuid4(),
                        run_id=run.run_id,
                        run_step_id=step.step_id,
                        task_id=task.task_id,
                        workspace_id=task.workspace_id,
                        thread_id=task.thread_id,
                        system_agent_id=step.system_agent_id,
                        tool_id=tool.tool_id if tool is not None else None,
                        tool_name=tool.name if tool is not None else mcp_tool.exposed_name,
                        status="created",
                        arguments=draft.arguments,
                        execution_spec=execution_spec.model_dump(mode="json"),
                        submitted_at=now,
                        created_at=now,
                        updated_at=now,
                        metadata={
                            **draft.metadata,
                            **(
                                {}
                                if mcp_tool is None
                                else {
                                    "tool_source": mcp_source or "mcp_server",
                                    "mcp_server_id": str(mcp_tool.server_id),
                                    "mcp_server_key": mcp_tool.server_key,
                                    "mcp_tool_name": mcp_tool.remote_name,
                                }
                            ),
                        },
                    )
                    await self._repository.upsert_tool_call(conn, tool_call)
                    event = await self._build_thread_event(
                        conn,
                        task.workspace_id,
                        task.thread_id,
                        "tool_call.created",
                        actor=actor,
                        target=TargetRef(type="tool_call", id=tool_call.tool_call_id),
                        payload=tool_call.model_dump(mode="json"),
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=run.correlation_id,
                        causation_id=task.task_id,
                    )
                    events.append(event)
                for event in events:
                    await self._repository.record_event(conn, event)
        return RunStepCommandResult(
            step=queued_step,
            run=run,
            task=task,
            events=events,
        )

    async def complete_run_step(
        self,
        step_id: UUID,
        worker_id: str,
        result: AgentRunResult,
    ) -> RunCommandResult:
        step = await self._repository.fetch_run_step(step_id)
        if step is None:
            raise KeyError(f"Run step {step_id} not found")
        if step.claimed_by_worker != worker_id:
            raise ValueError(f"Run step {step_id} is not claimed by worker {worker_id}")
        now = self._now()
        updated_step = step.model_copy(
            update={
                "status": "completed",
                "output": result.model_dump(mode="json"),
                "finished_at": now,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run_step(conn, updated_step)
        completion = await self.complete_run(step.run_id, step.system_agent_id, result)
        return completion

    async def fail_run_step(
        self,
        step_id: UUID,
        worker_id: str,
        error: str,
        *,
        stop_reason: StopReason = "tool_failure",
    ) -> RunCommandResult:
        step = await self._repository.fetch_run_step(step_id)
        if step is None:
            raise KeyError(f"Run step {step_id} not found")
        if step.claimed_by_worker != worker_id:
            raise ValueError(f"Run step {step_id} is not claimed by worker {worker_id}")
        now = self._now()
        updated_step = step.model_copy(
            update={
                "status": "failed",
                "error": error,
                "finished_at": now,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run_step(conn, updated_step)
        return await self.fail_run(step.run_id, step.system_agent_id, error, stop_reason=stop_reason)

    async def claim_next_tool_call(
        self,
        *,
        worker_id: str,
        lease_ttl_seconds: int,
        max_parallel_calls_per_run: int,
        max_concurrent_calls_per_tool: int,
    ) -> ToolCallCommandResult:
        now = self._now()
        tool_call = await self._repository.claim_next_tool_call(
            worker_id=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_ttl_seconds),
            now=now,
            max_parallel_calls_per_run=max_parallel_calls_per_run,
            max_concurrent_calls_per_tool=max_concurrent_calls_per_tool,
        )
        if tool_call is None:
            return ToolCallCommandResult()
        step = await self._repository.fetch_run_step(tool_call.run_step_id)
        run = await self._repository.fetch_run(tool_call.run_id)
        task = await self._repository.fetch_task(tool_call.task_id)
        if step is None or run is None or task is None:
            raise KeyError(f"Tool call {tool_call.tool_call_id} is missing execution state")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=tool_call.system_agent_id,
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                event = await self._build_thread_event(
                    conn,
                    task.workspace_id,
                    task.thread_id,
                    "tool_call.claimed",
                    actor=actor,
                    target=TargetRef(type="tool_call", id=tool_call.tool_call_id),
                    payload=tool_call.model_dump(mode="json"),
                    visibility="agents_only",
                    timestamp=now,
                    correlation_id=run.correlation_id,
                    causation_id=task.task_id,
                )
                await self._repository.record_event(conn, event)
        return ToolCallCommandResult(
            tool_call=tool_call,
            step=step,
            run=run,
            task=task,
            events=[event],
        )

    async def heartbeat_tool_call(
        self,
        *,
        tool_call_id: UUID,
        worker_id: str,
        lease_ttl_seconds: int,
    ) -> ToolCall | None:
        now = self._now()
        return await self._repository.heartbeat_tool_call(
            tool_call_id=tool_call_id,
            worker_id=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_ttl_seconds),
            now=now,
        )

    async def update_tool_call_execution_handle(
        self,
        tool_call_id: UUID,
        worker_id: str,
        execution_handle: str,
    ) -> ToolCall | None:
        tool_call = await self._repository.fetch_tool_call(tool_call_id)
        if tool_call is None:
            raise KeyError(f"Tool call {tool_call_id} not found")
        if tool_call.claimed_by_worker != worker_id:
            raise ValueError(
                f"Tool call {tool_call_id} is not claimed by worker {worker_id}"
            )
        now = self._now()
        updated = tool_call.model_copy(
            update={
                "execution_handle": execution_handle,
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_tool_call(conn, updated)
        return updated

    async def complete_tool_call(
        self,
        tool_call_id: UUID,
        worker_id: str,
        result: ToolCallResult,
    ) -> ToolCallCommandResult:
        return await self._finalize_tool_call(
            tool_call_id,
            worker_id,
            status="completed",
            result=result,
            error=result.error,
            event_type="tool_call.completed",
        )

    async def fail_tool_call(
        self,
        tool_call_id: UUID,
        worker_id: str,
        error: str,
    ) -> ToolCallCommandResult:
        return await self._finalize_tool_call(
            tool_call_id,
            worker_id,
            status="failed",
            result=ToolCallResult(error=error),
            error=error,
            event_type="tool_call.failed",
        )

    async def reconcile_expired_execution_leases(self) -> LeaseReconciliationResult:
        now = self._now()
        result = LeaseReconciliationResult()
        for step in await self._repository.list_expired_run_steps(now=now):
            if step.attempt_count >= _MAX_RUN_STEP_ATTEMPTS:
                failure = await self._fail_expired_run_step(
                    step,
                    error=(
                        "Run step lease expired after "
                        f"{step.attempt_count} attempts"
                    ),
                )
                result.events.extend(failure.events)
                continue
            result.run_steps.append(
                await self._requeue_expired_run_step(step, now=now)
            )
        for tool_call in await self._repository.list_expired_tool_calls(now=now):
            if tool_call.attempt_count >= _MAX_TOOL_CALL_ATTEMPTS:
                failure = await self._fail_expired_tool_call(
                    tool_call,
                    error=(
                        "Tool call lease expired after "
                        f"{tool_call.attempt_count} attempts"
                    ),
                )
                result.events.extend(failure.events)
                continue
            result.tool_calls.append(
                await self._requeue_expired_tool_call(tool_call, now=now)
            )
        return result

    async def _requeue_expired_run_step(self, step: RunStep, *, now: datetime) -> RunStep:
        updated_step = step.model_copy(
            update={
                "status": "created",
                "claimed_by_worker": None,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": now
                + timedelta(
                    seconds=self._retry_backoff_for_attempt(step.attempt_count)
                ),
                "execution_handle": None,
                "error": (
                    "Run step lease expired; "
                    f"retry {step.attempt_count + 1} scheduled"
                ),
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run_step(conn, updated_step)
        return updated_step

    async def _requeue_expired_tool_call(
        self,
        tool_call: ToolCall,
        *,
        now: datetime,
    ) -> ToolCall:
        updated_tool_call = tool_call.model_copy(
            update={
                "status": "created",
                "claimed_by_worker": None,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": now
                + timedelta(
                    seconds=self._retry_backoff_for_attempt(tool_call.attempt_count)
                ),
                "execution_handle": None,
                "error": (
                    "Tool call lease expired; "
                    f"retry {tool_call.attempt_count + 1} scheduled"
                ),
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_tool_call(conn, updated_tool_call)
        return updated_tool_call

    async def _fail_expired_run_step(
        self,
        step: RunStep,
        *,
        error: str,
    ) -> RunCommandResult:
        now = self._now()
        updated_step = step.model_copy(
            update={
                "status": "failed",
                "error": error,
                "finished_at": now,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run_step(conn, updated_step)
        run = await self._repository.fetch_run(step.run_id)
        if run is not None and run.status in {"completed", "failed"}:
            return RunCommandResult()
        return await self.fail_run(
            step.run_id,
            step.system_agent_id,
            error,
            stop_reason="tool_failure",
        )

    async def _fail_expired_tool_call(
        self,
        tool_call: ToolCall,
        *,
        error: str,
    ) -> CommandResult:
        step = await self._repository.fetch_run_step(tool_call.run_step_id)
        run = await self._repository.fetch_run(tool_call.run_id)
        task = await self._repository.fetch_task(tool_call.task_id)
        if step is None or run is None or task is None:
            raise KeyError(
                f"Tool call {tool_call.tool_call_id} is missing execution state"
            )
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=tool_call.system_agent_id,
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        now = self._now()
        updated_tool_call = tool_call.model_copy(
            update={
                "status": "failed",
                "error": error,
                "result": ToolCallResult(error=error),
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "finished_at": now,
                "updated_at": now,
            }
        )
        should_fail_step = step.status == "waiting_tools"
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_tool_call(conn, updated_tool_call)
                if should_fail_step:
                    await self._repository.upsert_run_step(
                        conn,
                        step.model_copy(
                            update={
                                "status": "failed",
                                "error": error,
                                "finished_at": now,
                                "lease_expires_at": None,
                                "last_heartbeat_at": None,
                                "next_retry_at": None,
                                "claimed_by_worker": None,
                                "execution_handle": None,
                                "updated_at": now,
                            }
                        ),
                    )
                event = await self._build_thread_event(
                    conn,
                    task.workspace_id,
                    task.thread_id,
                    "tool_call.failed",
                    actor=actor,
                    target=TargetRef(type="tool_call", id=tool_call.tool_call_id),
                    payload=updated_tool_call.model_dump(mode="json"),
                    visibility="agents_only",
                    timestamp=now,
                    correlation_id=run.correlation_id,
                    causation_id=task.task_id,
                )
                await self._repository.record_event(conn, event)
        events = [event]
        if should_fail_step and run.status not in {"completed", "failed"}:
            failure = await self.fail_run(
                tool_call.run_id,
                tool_call.system_agent_id,
                error,
                stop_reason="tool_failure",
            )
            events.extend(failure.events)
        return CommandResult(events=events)

    @staticmethod
    def _retry_backoff_for_attempt(attempt_count: int) -> int:
        index = max(0, min(attempt_count - 1, len(_RETRY_BACKOFF_SECONDS) - 1))
        return _RETRY_BACKOFF_SECONDS[index]

    async def build_requeued_execution_events(
        self,
        run_steps: list[RunStep],
        tool_calls: list[ToolCall],
    ) -> list[EventEnvelope]:
        timestamp = self._now()
        events: list[EventEnvelope] = []
        for step in run_steps:
            run = await self._repository.fetch_run(step.run_id)
            task = await self._repository.fetch_task(step.task_id)
            if run is None or task is None:
                continue
            participant = await self._require_run_participant(
                run=run,
                task=task,
                system_agent_id=step.system_agent_id,
            )
            events.append(
                EventEnvelope(
                    event_type="run_step.requeued",
                    workspace_id=step.workspace_id,
                    thread_id=step.thread_id,
                    actor=ActorRef(type="agent", id=participant.participant_id),
                    target=TargetRef(type="run_step", id=step.step_id),
                    visibility="agents_only",
                    correlation_id=run.correlation_id,
                    causation_id=task.task_id,
                    timestamp=timestamp,
                    payload=step.model_dump(mode="json"),
                )
            )
        for tool_call in tool_calls:
            run = await self._repository.fetch_run(tool_call.run_id)
            task = await self._repository.fetch_task(tool_call.task_id)
            if run is None or task is None:
                continue
            participant = await self._require_run_participant(
                run=run,
                task=task,
                system_agent_id=tool_call.system_agent_id,
            )
            events.append(
                EventEnvelope(
                    event_type="tool_call.requeued",
                    workspace_id=tool_call.workspace_id,
                    thread_id=tool_call.thread_id,
                    actor=ActorRef(type="agent", id=participant.participant_id),
                    target=TargetRef(type="tool_call", id=tool_call.tool_call_id),
                    visibility="agents_only",
                    correlation_id=run.correlation_id,
                    causation_id=task.task_id,
                    timestamp=timestamp,
                    payload=tool_call.model_dump(mode="json"),
                )
            )
        return events

    async def append_run_progress(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        content: str,
    ) -> RunCommandResult:
        return await self._runtime_execution.append_run_progress(
            run_id,
            system_agent_id,
            content,
        )

    async def complete_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        result: AgentRunResult,
    ) -> RunCommandResult:
        completion = await self._runtime_execution.complete_run(
            run_id,
            system_agent_id,
            result,
        )
        if completion.task is not None and (
            completion.task.metadata.get("publication_review_id")
            or completion.task.metadata.get("moderation_review_id")
        ):
            review_events, review_messages = await self._apply_publication_review_result(
                completion,
                result,
            )
            completion.events.extend(review_events)
            await self._persist_workspace_communication_messages(review_messages)
            return completion
        rendered_messages: list[TimelineMessage] = []
        if completion.run is not None and completion.task is not None and (
            result.interaction_requests
            or (completion.message is not None and result.metadata.get("create_task"))
        ):
            participant = await self._repository.fetch_participant(
                completion.run.workspace_id,
                completion.run.participant_id,
            )
            thread = await self._repository.fetch_thread(completion.task.thread_id)
            if participant is not None and thread is not None:
                actor_input = ParticipantInput(
                    participant_id=participant.participant_id,
                    participant_type=participant.participant_type,
                    user_id=participant.user_id,
                    display_name=participant.display_name,
                    description=participant.description,
                    roles=participant.roles,
                    capabilities=participant.capabilities,
                    visibility_scope=participant.visibility_scope,
                )
                now = self._now()
                extra_events: list[EventEnvelope] = []
                async with self._repository._pool.acquire() as conn:  # noqa: SLF001
                    async with conn.transaction():
                        if completion.message is not None and result.metadata.get("create_task"):
                            for task in await self._build_message_tasks(
                                thread=thread,
                                message=completion.message,
                                actor_input=actor_input,
                                visibility=completion.message.visibility,
                                timestamp=now,
                            ):
                                await self._repository.upsert_task(conn, task)
                                extra_events.append(
                                    EventEnvelope(
                                        event_type="task.created",
                                        workspace_id=thread.workspace_id,
                                        thread_id=thread.thread_id,
                                        actor=completion.message.actor,
                                        target=TargetRef(type="task", id=task.task_id),
                                        visibility="agents_only",
                                        correlation_id=completion.message.correlation_id,
                                        causation_id=completion.message.message_id,
                                        sequence=await self._repository.next_thread_sequence(
                                            conn,
                                            thread.thread_id,
                                        ),
                                        timestamp=now,
                                        payload=task.model_dump(mode="json"),
                                    )
                                )
                        if result.interaction_requests:
                            request_payloads = [
                                CreateInteractionRequest(
                                    title=draft.title,
                                    summary=draft.summary,
                                    questions=[
                                        CreateInteractionQuestionRequest(
                                            prompt=question.prompt,
                                            kind=question.kind,
                                            expected_format=question.expected_format,
                                            metadata=question.metadata,
                                        )
                                        for question in draft.questions
                                    ],
                                    selectors=draft.selectors,
                                    target_participant_ids=draft.target_participant_ids,
                                    completion_rule=draft.completion_rule,
                                    timeout_at=draft.timeout_at,
                                    metadata=draft.metadata,
                            )
                                for draft in result.interaction_requests
                            ]
                            request_result = await self._create_interaction_requests_in_transaction(
                                conn,
                                thread=thread,
                                actor_input=actor_input,
                                requests=request_payloads,
                                timestamp=now,
                                correlation_id=completion.task.correlation_id,
                                requester_message=completion.message,
                                requester_run=completion.run,
                                requester_task=completion.task,
                            )
                            rendered_messages.extend(request_result.messages)
                            for rendered_message in request_result.messages:
                                await self._repository.upsert_message(conn, rendered_message)
                                request_result.events.append(
                                    EventEnvelope(
                                        event_type="message.created",
                                        workspace_id=rendered_message.workspace_id,
                                        thread_id=rendered_message.thread_id,
                                        actor=rendered_message.actor,
                                        target=TargetRef(type="message", id=rendered_message.message_id),
                                        visibility=rendered_message.visibility,
                                        correlation_id=rendered_message.correlation_id,
                                        causation_id=rendered_message.causation_id,
                                        sequence=rendered_message.sequence,
                                        timestamp=now,
                                        payload=rendered_message.model_dump(mode="json"),
                                    )
                                )
                            extra_events.extend(request_result.events)
                        for event in extra_events:
                            await self._repository.record_event(conn, event)
                completion.events.extend(extra_events)
        await self._persist_workspace_communication_messages(rendered_messages)
        return completion

    async def fail_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        error: str,
        *,
        stop_reason: StopReason = "tool_failure",
    ) -> RunCommandResult:
        return await self._runtime_execution.fail_run(
            run_id,
            system_agent_id,
            error,
            stop_reason=stop_reason,
        )

    async def post_message(
        self, thread_id: UUID, payload: CreateMessageRequest
    ) -> MessageCommandResult:
        logger.debug(
            "Kernel post_message thread_id=%s participant_id=%s visibility=%s create_task=%s content_len=%s",
            thread_id,
            payload.actor.participant_id,
            payload.visibility,
            payload.create_task,
            len(payload.content),
        )
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        workspace = await self._repository.fetch_workspace(thread.workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {thread.workspace_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=payload.actor,
            now=now,
        )
        correlation_id = uuid4()
        message_metadata = dict(payload.metadata)
        if payload.target_system_agent_id is not None:
            message_metadata["target_system_agent_id"] = str(payload.target_system_agent_id)
        if payload.target_tool_scope is not None:
            message_metadata["target_tool_scope"] = payload.target_tool_scope
        task_instructions = [
            item.strip()
            for item in payload.task_instructions
            if isinstance(item, str) and item.strip()
        ]
        if task_instructions:
            message_metadata["task_instructions"] = task_instructions
        policy = self._workspace_moderation_policy(workspace)
        moderation_enabled = bool(policy.enabled) and not bool(
            message_metadata.get("moderation_bypass")
        )
        strict_pre_publish = moderation_enabled and policy.level == "strict"
        if strict_pre_publish:
            message_metadata.update(
                {
                    "moderation_status": "pending",
                    "moderation_level": policy.level,
                    "moderation_original_create_task": payload.create_task,
                    "publication_review_status": "pending",
                    "publication_original_create_task": payload.create_task,
                }
            )
            if payload.requests:
                message_metadata["moderation_original_requests"] = [
                    request.model_dump(mode="json") for request in payload.requests
                ]
                message_metadata["publication_original_requests"] = list(
                    message_metadata["moderation_original_requests"]
                )
        tool_generation_request = None
        if not strict_pre_publish:
            tool_generation_request = await self._build_tool_generation_request_for_message(
                thread=thread,
                actor_input=payload.actor,
                participant=participant,
                content=payload.content,
                metadata=message_metadata,
                timestamp=now,
            )
        if tool_generation_request is not None:
            message_metadata["tool_generation_request_id"] = str(
                tool_generation_request.request_id
            )
            message_metadata["tool_generation_request_status"] = tool_generation_request.status
        message = TimelineMessage(
            message_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            actor=actor,
            visibility=payload.visibility,
            content=payload.content,
            status="pending_moderation" if strict_pre_publish else "completed",
            correlation_id=correlation_id,
            sequence=0,
            created_at=now,
            updated_at=now,
            metadata=message_metadata,
        )
        interaction_result = None
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                membership = await self._repository.fetch_active_membership(
                    conn,
                    thread_id=thread_id,
                    participant_id=payload.actor.participant_id,
                )
                if membership is None:
                    logger.debug(
                        "Kernel post_message creating membership thread_id=%s participant_id=%s",
                        thread_id,
                        payload.actor.participant_id,
                    )
                    membership = Membership(
                        membership_id=uuid4(),
                        workspace_id=thread.workspace_id,
                        thread_id=thread_id,
                        participant_id=payload.actor.participant_id,
                        role="participant",
                        permissions=["post_messages"],
                        joined_at=now,
                    )
                    await self._repository.upsert_membership(conn, membership)
                else:
                    logger.debug(
                        "Kernel post_message reusing active membership membership_id=%s thread_id=%s participant_id=%s",
                        membership.membership_id,
                        thread_id,
                        payload.actor.participant_id,
                    )
                message.sequence = await self._repository.next_thread_sequence(conn, thread_id)
                await self._repository.upsert_message(conn, message)
                events: list[EventEnvelope] = []
                if strict_pre_publish:
                    events.append(
                        await self._build_thread_event(
                            conn,
                            thread.workspace_id,
                            thread_id,
                            "message.publication_review_pending",
                            actor=actor,
                            target=TargetRef(type="message", id=message.message_id),
                            visibility="private",
                            payload=message.model_dump(mode="json"),
                            timestamp=now,
                            correlation_id=message.correlation_id,
                            causation_id=message.message_id,
                        )
                    )
                    if await self._repository.fetch_agent_participant(
                        thread.workspace_id,
                        ANCHOR_AGENT_ID,
                    ) is None:
                        await self._ensure_anchor_attached_for_workspace(
                            conn,
                            thread.workspace_id,
                            now=now,
                        )
                    await self._create_publication_review_and_task_in_transaction(
                        conn,
                        thread=thread,
                        message=message,
                        workspace=workspace,
                        candidate_participant=participant,
                        policy=policy,
                        phase="pre_publish",
                        review_kind="workspace_topic_alignment",
                        reviewer_system_agent_id=ANCHOR_AGENT_ID,
                        task_kind=ANCHOR_TASK_KIND,
                        timestamp=now,
                        events=events,
                    )
                else:
                    events.append(
                        EventEnvelope(
                            event_type="message.created",
                            workspace_id=thread.workspace_id,
                            thread_id=thread_id,
                            actor=actor,
                            target=TargetRef(type="message", id=message.message_id),
                            visibility=payload.visibility,
                            correlation_id=message.correlation_id,
                            sequence=message.sequence,
                            timestamp=now,
                            payload=message.model_dump(mode="json"),
                        )
                    )
                    if tool_generation_request is not None:
                        tool_generation_request = tool_generation_request.model_copy(
                            update={"requester_message_id": message.message_id}
                        )
                        await self._repository.upsert_tool_generation_request(
                            conn,
                            tool_generation_request,
                        )
                        events.append(
                            await self._build_thread_event(
                                conn,
                                thread.workspace_id,
                                thread_id,
                                "tool_generation_request.created",
                                actor=actor,
                                target=TargetRef(
                                    type="tool_generation_request",
                                    id=tool_generation_request.request_id,
                                ),
                                visibility=payload.visibility,
                                payload=tool_generation_request.model_dump(mode="json"),
                                timestamp=now,
                            )
                        )
                    if payload.create_task:
                        for task in await self._build_message_tasks(
                            thread=thread,
                            message=message,
                            actor_input=payload.actor,
                            visibility=payload.visibility,
                            timestamp=now,
                        ):
                            await self._repository.upsert_task(conn, task)
                            events.append(
                                EventEnvelope(
                                    event_type="task.created",
                                    workspace_id=thread.workspace_id,
                                    thread_id=thread_id,
                                    actor=actor,
                                    target=TargetRef(type="task", id=task.task_id),
                                    visibility="agents_only",
                                    correlation_id=correlation_id,
                                    causation_id=message.message_id,
                                    sequence=await self._repository.next_thread_sequence(
                                        conn,
                                        thread_id,
                                    ),
                                    timestamp=now,
                                    payload=task.model_dump(mode="json"),
                                )
                            )

                    if payload.requests:
                        interaction_result = await self._create_interaction_requests_in_transaction(
                            conn,
                            thread=thread,
                            actor_input=payload.actor,
                            requests=payload.requests,
                            timestamp=now,
                            correlation_id=correlation_id,
                            requester_message=message,
                        )
                        for rendered_message in interaction_result.messages:
                            await self._repository.upsert_message(conn, rendered_message)
                            events.append(
                                EventEnvelope(
                                    event_type="message.created",
                                    workspace_id=rendered_message.workspace_id,
                                    thread_id=rendered_message.thread_id,
                                    actor=rendered_message.actor,
                                    target=TargetRef(
                                        type="message",
                                        id=rendered_message.message_id,
                                    ),
                                    visibility=rendered_message.visibility,
                                    correlation_id=rendered_message.correlation_id,
                                    causation_id=rendered_message.causation_id,
                                    sequence=rendered_message.sequence,
                                    timestamp=now,
                                    payload=rendered_message.model_dump(mode="json"),
                                )
                            )
                        events.extend(interaction_result.events)

                    if moderation_enabled:
                        if await self._repository.fetch_agent_participant(
                            thread.workspace_id,
                            ANCHOR_AGENT_ID,
                        ) is None:
                            await self._ensure_anchor_attached_for_workspace(
                                conn,
                                thread.workspace_id,
                                now=now,
                            )
                        await self._create_publication_review_and_task_in_transaction(
                            conn,
                            thread=thread,
                            message=message,
                            workspace=workspace,
                        candidate_participant=participant,
                        policy=policy,
                        phase="post_publish",
                        review_kind="workspace_topic_alignment",
                        reviewer_system_agent_id=ANCHOR_AGENT_ID,
                        task_kind=ANCHOR_TASK_KIND,
                        timestamp=now,
                        events=events,
                    )

                for event in events:
                    await self._repository.record_event(conn, event)

        persisted_messages = [] if strict_pre_publish else [message]
        if interaction_result is not None:
            persisted_messages.extend(interaction_result.messages)
        await self._persist_workspace_communication_messages(persisted_messages)

        logger.debug(
            "Kernel post_message complete thread_id=%s message_id=%s event_count=%s final_sequence=%s",
            thread_id,
            message.message_id,
            len(events),
            message.sequence,
        )
        return MessageCommandResult(message=message, events=events)

    async def list_interaction_requests(
        self,
        thread_id: UUID,
    ) -> list[InteractionRequestDetail]:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        return await self._repository.list_interaction_request_details_for_thread(thread_id)

    async def get_interaction_request(
        self,
        request_id: UUID,
    ) -> InteractionRequestDetail:
        detail = await self._repository.get_interaction_request_detail(request_id)
        if detail is None:
            raise KeyError(f"Interaction request {request_id} not found")
        return detail

    async def list_tool_generation_requests(
        self,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        thread_id: UUID | None = None,
        status: str | None = None,
    ) -> list[ToolGenerationRequestDetail]:
        requests = await self._repository.list_tool_generation_requests(
            organization_id=organization_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            status=status,
        )
        details: list[ToolGenerationRequestDetail] = []
        for request in requests:
            details.append(await self._tool_generation_request_detail(request.request_id))
        return details

    async def list_thread_tool_generation_requests(
        self,
        thread_id: UUID,
    ) -> list[ToolGenerationRequestDetail]:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        return await self.list_tool_generation_requests(thread_id=thread_id)

    async def get_tool_generation_request(
        self,
        request_id: UUID,
    ) -> ToolGenerationRequestDetail:
        return await self._tool_generation_request_detail(request_id)

    async def create_tool_generation_revision(
        self,
        request_id: UUID,
        payload: CreateToolGenerationRevisionRequest,
    ) -> ToolGenerationRequestCommandResult:
        request = await self._repository.fetch_tool_generation_request(request_id)
        if request is None:
            raise KeyError(f"Tool generation request {request_id} not found")
        if request.final_tool_id is not None or request.status == "published":
            raise ValueError("Tool generation requests that already published a tool cannot be revised")
        now = self._now()
        manifest = self._normalize_generated_tool_manifest(payload.manifest)
        revision = ToolGenerationRevision(
            revision_id=uuid4(),
            request_id=request_id,
            revision_number=1,
            status=payload.status,
            manifest=manifest,
            validation_report=payload.validation_report,
            source_asset_id=payload.source_asset_id,
            source_asset_version_id=payload.source_asset_version_id,
            manifest_asset_id=payload.manifest_asset_id,
            manifest_asset_version_id=payload.manifest_asset_version_id,
            report_asset_id=payload.report_asset_id,
            report_asset_version_id=payload.report_asset_version_id,
            image_ref=payload.image_ref,
            image_digest=payload.image_digest,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        self._validate_tool_generation_revision_submission(revision, status=payload.status)
        updated_request = request.model_copy(
            update={
                "status": payload.status,
                "target_tool_name": manifest.name,
                "summary": manifest.description,
                "latest_revision_id": revision.revision_id,
                "rejected_by": None,
                "rejected_at": None,
                "updated_at": now,
            }
        )
        status_message: TimelineMessage | None = None
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                revision_number = await self._repository.next_tool_generation_revision_number(
                    conn,
                    request_id,
                )
                revision = revision.model_copy(update={"revision_number": revision_number})
                await self._repository.upsert_tool_generation_revision(conn, revision)
                await self._repository.upsert_tool_generation_request(conn, updated_request)
                events.append(
                    await self._build_thread_event(
                        conn,
                        request.workspace_id,
                        request.thread_id,
                        "tool_generation_revision.created",
                        actor=self._actor_from_input(payload.actor),
                        target=TargetRef(
                            type="tool_generation_revision",
                            id=revision.revision_id,
                        ),
                        visibility="workspace",
                        payload=revision.model_dump(mode="json"),
                        timestamp=now,
                    )
                )
                if payload.status == "pending_approval":
                    events.append(
                        await self._build_thread_event(
                            conn,
                            request.workspace_id,
                            request.thread_id,
                            "tool_generation_request.pending_approval",
                            actor=self._actor_from_input(payload.actor),
                            target=TargetRef(
                                type="tool_generation_request",
                                id=updated_request.request_id,
                            ),
                            visibility="workspace",
                            payload=updated_request.model_dump(mode="json"),
                            timestamp=now,
                        )
                    )
                    status_message, message_event = await self._create_tool_generation_status_message(
                        conn,
                        request=updated_request,
                        revision=revision,
                        status="pending_approval",
                        content=self._tool_generation_pending_approval_message(
                            updated_request,
                            revision,
                        ),
                        timestamp=now,
                    )
                    if message_event is not None:
                        events.append(message_event)
                for event in events:
                    await self._repository.record_event(conn, event)
        if status_message is not None:
            await self._persist_workspace_communication_messages([status_message])
        detail = await self._tool_generation_request_detail(request_id)
        return ToolGenerationRequestCommandResult(
            detail=detail,
            revision=revision,
            message=status_message,
            events=events,
        )

    async def approve_tool_generation_revision(
        self,
        revision_id: UUID,
        payload: ReviewToolGenerationRevisionRequest,
    ) -> ToolGenerationRequestCommandResult:
        revision = await self._repository.fetch_tool_generation_revision(revision_id)
        if revision is None:
            raise KeyError(f"Tool generation revision {revision_id} not found")
        request = await self._repository.fetch_tool_generation_request(revision.request_id)
        if request is None:
            raise KeyError(
                f"Tool generation request {revision.request_id} not found for revision {revision_id}"
            )
        if request.final_tool_id is not None or request.status == "published":
            raise ValueError("This tool-generation request has already been published")
        if revision.status != "pending_approval":
            raise ValueError("Only revisions pending approval can be approved")
        now = self._now()
        immutable_ref = self._require_generated_tool_immutable_ref(revision)
        verification_task = await self._build_tool_generation_verification_task(
            request=request,
            revision=revision,
            approver_id=payload.actor.participant_id,
            review_reason=payload.reason,
            immutable_ref=immutable_ref,
            timestamp=now,
        )
        verifying_request = request.model_copy(
            update={
                "status": "verifying_registry_pull",
                "updated_at": now,
                "metadata": self._tool_generation_metadata_with_update(
                    request.metadata,
                    approval_verification_error=None,
                    approval_verification_requested_at=now.isoformat(),
                    approval_verification_requested_by=str(payload.actor.participant_id),
                    approval_verification_reason=payload.reason,
                    approval_verification_task_id=str(verification_task["task"].task_id),
                    approval_verification_run_id=str(verification_task["run"].run_id),
                    approval_verification_tool_call_id=str(
                        verification_task["tool_call"].tool_call_id
                    ),
                    approval_verification_immutable_ref=immutable_ref,
                ),
            }
        )
        verifying_revision = revision.model_copy(
            update={
                "status": "verifying_registry_pull",
                "updated_at": now,
                "metadata": self._tool_generation_metadata_with_update(
                    revision.metadata,
                    approval_verification_error=None,
                    approval_verification_requested_at=now.isoformat(),
                    approval_verification_requested_by=str(payload.actor.participant_id),
                    approval_verification_reason=payload.reason,
                    approval_verification_task_id=str(verification_task["task"].task_id),
                    approval_verification_run_id=str(verification_task["run"].run_id),
                    approval_verification_tool_call_id=str(
                        verification_task["tool_call"].tool_call_id
                    ),
                    approval_verification_immutable_ref=immutable_ref,
                ),
            }
        )
        status_message: TimelineMessage | None = None
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_task(conn, verification_task["task"])
                await self._repository.upsert_run(conn, verification_task["run"])
                await self._repository.upsert_run_step(conn, verification_task["step"])
                await self._repository.upsert_tool_call(conn, verification_task["tool_call"])
                await self._repository.upsert_tool_generation_revision(conn, verifying_revision)
                await self._repository.upsert_tool_generation_request(conn, verifying_request)
                actor = ActorRef(
                    type="agent",
                    id=verification_task["participant"].participant_id,
                )
                verification_events = [
                    await self._build_thread_event(
                        conn,
                        request.workspace_id,
                        request.thread_id,
                        "task.claimed",
                        actor=actor,
                        target=TargetRef(type="task", id=verification_task["task"].task_id),
                        payload={
                            "task_id": str(verification_task["task"].task_id),
                            "claimed_by": str(verification_task["participant"].participant_id),
                            "system_agent_id": str(request.target_system_agent_id),
                            "tool_generation_approval_verification": True,
                        },
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=verification_task["task"].correlation_id,
                        causation_id=verification_task["task"].causation_id,
                    ),
                    await self._build_thread_event(
                        conn,
                        request.workspace_id,
                        request.thread_id,
                        "run.started",
                        actor=actor,
                        target=TargetRef(type="run", id=verification_task["run"].run_id),
                        payload=verification_task["run"].model_dump(mode="json"),
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=verification_task["run"].correlation_id,
                        causation_id=verification_task["task"].task_id,
                    ),
                    await self._build_thread_event(
                        conn,
                        request.workspace_id,
                        request.thread_id,
                        "tool_call.created",
                        actor=actor,
                        target=TargetRef(type="tool_call", id=verification_task["tool_call"].tool_call_id),
                        payload=verification_task["tool_call"].model_dump(mode="json"),
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=verification_task["run"].correlation_id,
                        causation_id=verification_task["task"].task_id,
                    ),
                ]
                for event in verification_events:
                    await self._repository.record_event(conn, event)
                    events.append(event)
                approval_started_event = await self._build_thread_event(
                    conn,
                    request.workspace_id,
                    request.thread_id,
                    "tool_generation_revision.approval_started",
                    actor=self._actor_from_input(payload.actor),
                    target=TargetRef(type="tool_generation_revision", id=verifying_revision.revision_id),
                    visibility="workspace",
                    payload={
                        "request_id": str(verifying_request.request_id),
                        "revision_id": str(verifying_revision.revision_id),
                        "requested_scope": verifying_request.requested_scope,
                        "immutable_ref": immutable_ref,
                    },
                    timestamp=now,
                )
                await self._repository.record_event(conn, approval_started_event)
                events.append(approval_started_event)
                status_message, message_event = await self._create_tool_generation_status_message(
                    conn,
                    request=verifying_request,
                    revision=verifying_revision,
                    status="verifying_registry_pull",
                    content=self._tool_generation_verifying_message(
                        request=verifying_request,
                        revision=verifying_revision,
                        immutable_ref=immutable_ref,
                    ),
                    timestamp=now,
                )
                if message_event is not None:
                    await self._repository.record_event(conn, message_event)
                    events.append(message_event)
        if status_message is not None:
            await self._persist_workspace_communication_messages([status_message])
        detail = await self._tool_generation_request_detail(request.request_id)
        return ToolGenerationRequestCommandResult(
            detail=detail,
            revision=verifying_revision,
            message=status_message,
            events=events,
        )

    async def reject_tool_generation_revision(
        self,
        revision_id: UUID,
        payload: ReviewToolGenerationRevisionRequest,
    ) -> ToolGenerationRequestCommandResult:
        revision = await self._repository.fetch_tool_generation_revision(revision_id)
        if revision is None:
            raise KeyError(f"Tool generation revision {revision_id} not found")
        request = await self._repository.fetch_tool_generation_request(revision.request_id)
        if request is None:
            raise KeyError(
                f"Tool generation request {revision.request_id} not found for revision {revision_id}"
            )
        if request.status == "published":
            raise ValueError("Published tool-generation requests cannot be rejected")
        now = self._now()
        rejected_revision = revision.model_copy(update={"status": "rejected", "updated_at": now})
        rejected_request = request.model_copy(
            update={
                "status": "rejected",
                "rejected_by": payload.actor.participant_id,
                "rejected_at": now,
                "updated_at": now,
            }
        )
        status_message: TimelineMessage | None = None
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_tool_generation_revision(conn, rejected_revision)
                await self._repository.upsert_tool_generation_request(conn, rejected_request)
                rejected_event = await self._build_thread_event(
                    conn,
                    request.workspace_id,
                    request.thread_id,
                    "tool_generation_revision.rejected",
                    actor=self._actor_from_input(payload.actor),
                    target=TargetRef(type="tool_generation_revision", id=rejected_revision.revision_id),
                    visibility="workspace",
                    payload={
                        "request_id": str(rejected_request.request_id),
                        "revision_id": str(rejected_revision.revision_id),
                        "reason": payload.reason,
                    },
                    timestamp=now,
                )
                await self._repository.record_event(conn, rejected_event)
                events.append(rejected_event)
                status_message, message_event = await self._create_tool_generation_status_message(
                    conn,
                    request=rejected_request,
                    revision=rejected_revision,
                    status="rejected",
                    content=self._tool_generation_rejected_message(payload.reason),
                    timestamp=now,
                )
                if message_event is not None:
                    await self._repository.record_event(conn, message_event)
                    events.append(message_event)
        if status_message is not None:
            await self._persist_workspace_communication_messages([status_message])
        detail = await self._tool_generation_request_detail(request.request_id)
        return ToolGenerationRequestCommandResult(
            detail=detail,
            revision=rejected_revision,
            message=status_message,
            events=events,
        )

    async def create_interaction_requests(
        self,
        thread_id: UUID,
        payload: CreateInteractionRequestsRequest,
    ) -> InteractionRequestCommandResult:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        now = self._now()
        correlation_id = uuid4()
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                result = await self._create_interaction_requests_in_transaction(
                    conn,
                    thread=thread,
                    actor_input=payload.actor,
                    requests=payload.requests,
                    timestamp=now,
                    correlation_id=correlation_id,
                    requester_message=None,
                )
                for rendered_message in result.messages:
                    await self._repository.upsert_message(conn, rendered_message)
                    result.events.append(
                        EventEnvelope(
                            event_type="message.created",
                            workspace_id=rendered_message.workspace_id,
                            thread_id=rendered_message.thread_id,
                            actor=rendered_message.actor,
                            target=TargetRef(type="message", id=rendered_message.message_id),
                            visibility=rendered_message.visibility,
                            correlation_id=rendered_message.correlation_id,
                            causation_id=rendered_message.causation_id,
                            sequence=rendered_message.sequence,
                            timestamp=now,
                            payload=rendered_message.model_dump(mode="json"),
                        )
                    )
                for event in result.events:
                    await self._repository.record_event(conn, event)
        await self._persist_workspace_communication_messages(result.messages)
        return result

    async def update_interaction_request(
        self,
        request_id: UUID,
        payload: UpdateInteractionRequestRequest,
    ) -> InteractionRequestCommandResult:
        existing = await self._repository.get_interaction_request_detail(request_id)
        if existing is None:
            raise KeyError(f"Interaction request {request_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._repository.fetch_participant(
            existing.request.workspace_id,
            payload.actor.participant_id,
        )
        if participant is None:
            participant = await self._participant_profile_for_actor(
                workspace_id=existing.request.workspace_id,
                actor=payload.actor,
                now=now,
            )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                detail = await self._repository.get_interaction_request_detail(request_id)
                assert detail is not None
                request = detail.request
                events: list[EventEnvelope] = []
                resumed_task: Task | None = None

                if payload.action == "cancel":
                    request = request.model_copy(
                        update={
                            "status": "cancelled",
                            "updated_at": now,
                            "metadata": {**request.metadata, **payload.metadata},
                        }
                    )
                    await self._repository.upsert_interaction_request(conn, request)
                    events.append(
                        await self._build_thread_event(
                            conn,
                            request.workspace_id,
                            request.thread_id,
                            "interaction_request.cancelled",
                            actor=actor,
                            target=TargetRef(type="interaction_request", id=request.request_id),
                            visibility="workspace",
                            payload={"request_id": str(request.request_id)},
                            timestamp=now,
                        )
                    )
                elif payload.action == "timeout":
                    request = request.model_copy(
                        update={
                            "status": "timed_out",
                            "updated_at": now,
                            "metadata": {**request.metadata, **payload.metadata},
                        }
                    )
                    await self._repository.upsert_interaction_request(conn, request)
                    events.append(
                        await self._build_thread_event(
                            conn,
                            request.workspace_id,
                            request.thread_id,
                            "interaction_request.timed_out",
                            actor=actor,
                            target=TargetRef(type="interaction_request", id=request.request_id),
                            visibility="workspace",
                            payload={"request_id": str(request.request_id)},
                            timestamp=now,
                        )
                    )
                else:
                    if payload.target_id is None:
                        raise ValueError("target_id is required for target actions")
                    target = await self._repository.fetch_interaction_request_target(payload.target_id)
                    if target is None or target.request_id != request_id:
                        raise KeyError(f"Interaction request target {payload.target_id} not found")
                    updated_target = target.model_copy(
                        update={
                            "status": (
                                "acknowledged"
                                if payload.action == "acknowledge_target"
                                else "dismissed"
                            ),
                            "updated_at": now,
                            "metadata": {**target.metadata, **payload.metadata},
                        }
                    )
                    await self._repository.upsert_interaction_request_target(conn, updated_target)
                    detail = await self._repository.get_interaction_request_detail(request_id)
                    assert detail is not None
                    request = detail.request
                    aggregate, completed = await self._interaction_request_aggregate_state(detail)
                    request = request.model_copy(
                        update={
                            "status": "completed" if completed else request.status,
                            "completed_at": now if completed else request.completed_at,
                            "updated_at": now,
                            "metadata": {**request.metadata, "aggregate": aggregate},
                        }
                    )
                    await self._repository.upsert_interaction_request(conn, request)
                    events.append(
                        await self._build_thread_event(
                            conn,
                            request.workspace_id,
                            request.thread_id,
                            (
                                "interaction_request.target_acknowledged"
                                if payload.action == "acknowledge_target"
                                else "interaction_request.target_dismissed"
                            ),
                            actor=actor,
                            target=TargetRef(type="interaction_request_target", id=updated_target.target_id),
                            visibility="workspace",
                            payload={
                                "request_id": str(request.request_id),
                                "target_id": str(updated_target.target_id),
                                "status": updated_target.status,
                            },
                            timestamp=now,
                        )
                    )
                    if completed:
                        resumed_task = await self._create_interaction_request_followup_task(
                            conn,
                            request=request,
                            detail=detail.model_copy(update={"request": request}),
                            answer_message=None,
                            timestamp=now,
                        )
                        if resumed_task is not None:
                            events.append(
                                EventEnvelope(
                                    event_type="task.created",
                                    workspace_id=resumed_task.workspace_id,
                                    thread_id=resumed_task.thread_id,
                                    actor=actor,
                                    target=TargetRef(type="task", id=resumed_task.task_id),
                                    visibility="agents_only",
                                    correlation_id=resumed_task.correlation_id,
                                    causation_id=request.request_id,
                                    sequence=await self._repository.next_thread_sequence(conn, resumed_task.thread_id),
                                    timestamp=now,
                                    payload=resumed_task.model_dump(mode="json"),
                                )
                            )
                for event in events:
                    await self._repository.record_event(conn, event)
        return InteractionRequestCommandResult(
            detail=await self.get_interaction_request(request_id),
            events=events,
            resumed_task=resumed_task,
        )

    async def answer_interaction_request(
        self,
        request_id: UUID,
        payload: CreateInteractionAnswerRequest,
    ) -> InteractionRequestCommandResult:
        detail = await self._repository.get_interaction_request_detail(request_id)
        if detail is None:
            raise KeyError(f"Interaction request {request_id} not found")
        if detail.request.status != "open":
            raise ValueError("Only open interaction requests can be answered")
        thread = await self._repository.fetch_thread(detail.request.thread_id)
        if thread is None:
            raise KeyError(f"Thread {detail.request.thread_id} not found")
        if payload.question_ids:
            valid_question_ids = {question.question_id for question in detail.questions}
            invalid = [question_id for question_id in payload.question_ids if question_id not in valid_question_ids]
            if invalid:
                raise ValueError(f"Unknown interaction question ids: {invalid}")
        if detail.targets:
            if payload.actor.participant_id not in {
                target.participant_id for target in detail.targets if target.participant_id is not None
            }:
                raise PermissionError("Only a targeted participant can answer this request")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._repository.fetch_participant(
            thread.workspace_id,
            payload.actor.participant_id,
        )
        if participant is None:
            participant = await self._participant_profile_for_actor(
                workspace_id=thread.workspace_id,
                actor=payload.actor,
                now=now,
            )
        correlation_id = detail.request.requester_message_id or uuid4()
        answer_message = TimelineMessage(
            message_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread.thread_id,
            actor=actor,
            visibility="workspace",
            content=payload.content,
            status="completed",
            correlation_id=detail.request.requester_message_id or uuid4(),
            causation_id=detail.request.request_id,
            sequence=0,
            created_at=now,
            updated_at=now,
            metadata={
                **payload.metadata,
                "interaction_request_id": str(detail.request.request_id),
                "interaction_question_ids": [str(question_id) for question_id in payload.question_ids],
            },
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                membership = await self._repository.fetch_active_membership(
                    conn,
                    thread_id=thread.thread_id,
                    participant_id=payload.actor.participant_id,
                )
                if membership is None:
                    membership = Membership(
                        membership_id=uuid4(),
                        workspace_id=thread.workspace_id,
                        thread_id=thread.thread_id,
                        participant_id=payload.actor.participant_id,
                        role="participant",
                        permissions=["post_messages"],
                        joined_at=now,
                    )
                    await self._repository.upsert_membership(conn, membership)
                answer_message.sequence = await self._repository.next_thread_sequence(conn, thread.thread_id)
                await self._repository.upsert_message(conn, answer_message)
                answer = InteractionAnswer(
                    answer_id=uuid4(),
                    request_id=request_id,
                    participant_id=payload.actor.participant_id,
                    message_id=answer_message.message_id,
                    question_ids=list(payload.question_ids),
                    created_at=now,
                    metadata=payload.metadata,
                )
                await self._repository.upsert_interaction_answer(conn, answer)
                target = next(
                    (
                        item
                        for item in detail.targets
                        if item.participant_id == payload.actor.participant_id
                    ),
                    None,
                )
                if target is not None:
                    updated_target = target.model_copy(
                        update={
                            "status": "answered",
                            "answered_message_id": answer_message.message_id,
                            "updated_at": now,
                        }
                    )
                    await self._repository.upsert_interaction_request_target(conn, updated_target)
                refreshed = await self._repository.get_interaction_request_detail(request_id)
                assert refreshed is not None
                aggregate, completed = await self._interaction_request_aggregate_state(refreshed)
                updated_request = refreshed.request.model_copy(
                    update={
                        "status": "completed" if completed else refreshed.request.status,
                        "completed_at": now if completed else refreshed.request.completed_at,
                        "updated_at": now,
                        "metadata": {**refreshed.request.metadata, "aggregate": aggregate},
                    }
                )
                await self._repository.upsert_interaction_request(conn, updated_request)
                events = [
                    EventEnvelope(
                        event_type="message.created",
                        workspace_id=answer_message.workspace_id,
                        thread_id=answer_message.thread_id,
                        actor=answer_message.actor,
                        target=TargetRef(type="message", id=answer_message.message_id),
                        visibility=answer_message.visibility,
                        correlation_id=answer_message.correlation_id,
                        causation_id=answer_message.causation_id,
                        sequence=answer_message.sequence,
                        timestamp=now,
                        payload=answer_message.model_dump(mode="json"),
                    ),
                    await self._build_thread_event(
                        conn,
                        updated_request.workspace_id,
                        updated_request.thread_id,
                        "interaction_request.answered",
                        actor=actor,
                        target=TargetRef(type="message", id=answer_message.message_id),
                        visibility="workspace",
                        payload={
                            "request_id": str(updated_request.request_id),
                            "answer_id": str(answer.answer_id),
                            "participant_id": str(answer.participant_id),
                            "completed": completed,
                        },
                        timestamp=now,
                        correlation_id=answer_message.correlation_id,
                        causation_id=updated_request.request_id,
                    ),
                ]
                resumed_task: Task | None = None
                if completed:
                    resumed_task = await self._create_interaction_request_followup_task(
                        conn,
                        request=updated_request,
                        detail=refreshed.model_copy(update={"request": updated_request}),
                        answer_message=answer_message,
                        timestamp=now,
                    )
                    if resumed_task is not None:
                        events.append(
                            EventEnvelope(
                                event_type="task.created",
                                workspace_id=resumed_task.workspace_id,
                                thread_id=resumed_task.thread_id,
                                actor=ActorRef(type=payload.actor.participant_type, id=payload.actor.participant_id),
                                target=TargetRef(type="task", id=resumed_task.task_id),
                                visibility="agents_only",
                                correlation_id=resumed_task.correlation_id,
                                causation_id=updated_request.request_id,
                                sequence=await self._repository.next_thread_sequence(conn, resumed_task.thread_id),
                                timestamp=now,
                                payload=resumed_task.model_dump(mode="json"),
                            )
                        )
                for event in events:
                    await self._repository.record_event(conn, event)
        await self._persist_workspace_communication_messages([answer_message])
        return InteractionRequestCommandResult(
            detail=await self.get_interaction_request(request_id),
            events=events,
            answer_message=answer_message,
            resumed_task=resumed_task,
        )

    async def list_memory_entries(self, workspace_id: UUID) -> list[MemoryEntry]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_memory_entries_for_scope(
            scope="workspace",
            workspace_id=workspace_id,
            state="confirmed",
        )

    async def list_thread_memory_entries(self, thread_id: UUID) -> list[MemoryEntry]:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        return await self._repository.list_memory_entries_for_scope(
            scope="thread",
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            state="confirmed",
        )

    async def create_memory_entry(
        self, workspace_id: UUID, payload: CreateMemoryEntryRequest
    ) -> MemoryCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        )
        entry = MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            thread_id=None,
            run_id=None,
            entry_type=payload.entry_type,
            content=payload.content,
            summary=payload.summary,
            source="manual",
            created_by=payload.actor.participant_id,
            updated_by=payload.actor.participant_id,
            confirmed_by=payload.actor.participant_id,
            confirmed_at=now,
            visibility=payload.visibility,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, entry)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.memory_entry_created",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=entry.memory_entry_id),
                    visibility=entry.visibility,
                    payload=entry.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._sync_memory_entry(entry)
        return MemoryCommandResult(entry=entry, events=[event])

    async def create_thread_memory_entry(
        self, thread_id: UUID, payload: CreateThreadMemoryRequest
    ) -> MemoryCommandResult:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=payload.actor,
            now=now,
        )
        entry = MemoryEntry(
            memory_entry_id=uuid4(),
            scope="thread",
            state="confirmed",
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            run_id=None,
            entry_type=payload.entry_type,
            content=payload.content,
            summary=payload.summary,
            source="manual",
            created_by=payload.actor.participant_id,
            updated_by=payload.actor.participant_id,
            confirmed_by=payload.actor.participant_id,
            confirmed_at=now,
            visibility=payload.visibility,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, entry)
                event = await self._build_thread_event(
                    conn,
                    thread.workspace_id,
                    thread_id,
                    "thread.memory_entry_created",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=entry.memory_entry_id),
                    visibility=entry.visibility,
                    payload=entry.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._sync_memory_entry(entry)
        return MemoryCommandResult(entry=entry, events=[event])

    async def confirm_workspace_memory(
        self,
        workspace_id: UUID,
        payload: ConfirmWorkspaceMemoryRequest,
    ) -> MemoryCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        source_entry = await self._repository.fetch_memory_entry(payload.source_memory_entry_id)
        if source_entry is None or source_entry.workspace_id != workspace_id:
            raise KeyError(f"Memory entry {payload.source_memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        )
        entry = MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            thread_id=None,
            run_id=None,
            entry_type=payload.entry_type or source_entry.entry_type,
            content=payload.content or source_entry.content,
            summary=payload.summary if payload.summary is not None else source_entry.summary,
            source=f"confirmed:{source_entry.scope}:{source_entry.memory_entry_id}",
            created_by=payload.actor.participant_id,
            updated_by=payload.actor.participant_id,
            confirmed_by=payload.actor.participant_id,
            confirmed_at=now,
            visibility=payload.visibility,
            metadata={
                **dict(source_entry.metadata),
                **payload.metadata,
                "source_memory_entry_id": str(source_entry.memory_entry_id),
            },
            created_at=now,
            updated_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, entry)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.memory_entry_confirmed",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=entry.memory_entry_id),
                    visibility=entry.visibility,
                    payload=entry.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._sync_memory_entry(entry)
        return MemoryCommandResult(entry=entry, events=[event])

    async def update_memory_entry(
        self, workspace_id: UUID, memory_entry_id: UUID, payload: UpdateMemoryEntryRequest
    ) -> MemoryCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        existing = await self._repository.fetch_memory_entry(memory_entry_id)
        if (
            existing is None
            or existing.workspace_id != workspace_id
            or existing.scope != "workspace"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        )
        updated = existing.model_copy(
            update={
                "content": payload.content if payload.content is not None else existing.content,
                "summary": payload.summary if payload.summary is not None else existing.summary,
                "visibility": payload.visibility if payload.visibility is not None else existing.visibility,
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": now,
                "version": existing.version + 1,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, updated)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.memory_entry_updated",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=updated.memory_entry_id),
                    visibility=updated.visibility,
                    payload=updated.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._sync_memory_entry(updated)
        return MemoryCommandResult(entry=updated, events=[event])

    async def update_thread_memory_entry(
        self, thread_id: UUID, memory_entry_id: UUID, payload: UpdateMemoryEntryRequest
    ) -> MemoryCommandResult:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        existing = await self._repository.fetch_memory_entry(memory_entry_id)
        if (
            existing is None
            or existing.workspace_id != thread.workspace_id
            or existing.thread_id != thread_id
            or existing.scope != "thread"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=payload.actor,
            now=now,
        )
        updated = existing.model_copy(
            update={
                "content": payload.content if payload.content is not None else existing.content,
                "summary": payload.summary if payload.summary is not None else existing.summary,
                "visibility": payload.visibility if payload.visibility is not None else existing.visibility,
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": now,
                "version": existing.version + 1,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, updated)
                event = await self._build_thread_event(
                    conn,
                    thread.workspace_id,
                    thread_id,
                    "thread.memory_entry_updated",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=updated.memory_entry_id),
                    visibility=updated.visibility,
                    payload=updated.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._sync_memory_entry(updated)
        return MemoryCommandResult(entry=updated, events=[event])

    async def delete_memory_entry(
        self, workspace_id: UUID, memory_entry_id: UUID, actor_input: ParticipantInput
    ) -> list[EventEnvelope]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        existing = await self._repository.fetch_memory_entry(memory_entry_id)
        if (
            existing is None
            or existing.workspace_id != workspace_id
            or existing.scope != "workspace"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(actor_input)
        participant = await self._participant_profile_for_actor(
            workspace_id=workspace_id,
            actor=actor_input,
            now=now,
        )
        archived = existing.model_copy(
            update={
                "state": "archived",
                "updated_by": actor_input.participant_id,
                "updated_at": now,
                "version": existing.version + 1,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, archived)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.memory_entry_deleted",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=memory_entry_id),
                    visibility=existing.visibility,
                    payload={"memory_entry_id": str(memory_entry_id)},
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._delete_memory_entry_from_providers(existing)
        return [event]

    async def delete_thread_memory_entry(
        self, thread_id: UUID, memory_entry_id: UUID, actor_input: ParticipantInput
    ) -> list[EventEnvelope]:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        existing = await self._repository.fetch_memory_entry(memory_entry_id)
        if (
            existing is None
            or existing.workspace_id != thread.workspace_id
            or existing.thread_id != thread_id
            or existing.scope != "thread"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(actor_input)
        participant = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=actor_input,
            now=now,
        )
        archived = existing.model_copy(
            update={
                "state": "archived",
                "updated_by": actor_input.participant_id,
                "updated_at": now,
                "version": existing.version + 1,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, archived)
                event = await self._build_thread_event(
                    conn,
                    thread.workspace_id,
                    thread_id,
                    "thread.memory_entry_deleted",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=memory_entry_id),
                    visibility=existing.visibility,
                    payload={"memory_entry_id": str(memory_entry_id)},
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._delete_memory_entry_from_providers(existing)
        return [event]

    async def search_thread_memory(
        self,
        thread_id: UUID,
        payload: SearchMemoryRequest,
    ) -> MemorySearchResponse:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        workspace = await self._repository.fetch_workspace(thread.workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {thread.workspace_id} not found")
        provider_definition = await self._resolve_search_memory_provider(
            payload.use_provider,
            organization_id=workspace.organization_id,
        )
        provider = self._memory_provider_index.get(provider_definition.provider)
        if provider is None:
            raise ValueError(f"Unsupported memory provider {provider_definition.provider!r}")
        viewer = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=payload.actor,
            now=self._now(),
        )
        raw_results = await provider.search(
            provider_definition,
            scope="thread",
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            run_id=None,
            query=payload.query,
            limit=payload.limit,
            include_graph=payload.include_graph,
            metadata_filters=payload.metadata_filters,
        )
        hits: list[MemorySearchHit] = []
        for hit in raw_results.hits:
            if hit.memory_entry_id is None:
                continue
            entry = await self._repository.fetch_memory_entry(hit.memory_entry_id)
            if entry is None or entry.state == "archived":
                continue
            if not self._filter_visible_memory_entries([entry], viewer=viewer):
                continue
            hits.append(
                MemorySearchHit(
                    entry=entry,
                    score=hit.score,
                    relations=hit.relations,
                    metadata=hit.metadata,
                )
            )
        return MemorySearchResponse(
            query=payload.query,
            provider=provider_definition.provider_key,
            results=hits,
            metadata=raw_results.metadata,
        )

    async def append_run_scratch(
        self,
        *,
        run_id: UUID,
        actor_input: ParticipantInput,
        entry_type: str,
        content: str,
        summary: str | None = None,
        metadata: dict[str, object] | None = None,
        visibility: str = "agents_only",
        source: str = "agent_runtime",
    ) -> MemoryEntry:
        return await self.upsert_run_scratch(
            run_id=run_id,
            actor_input=actor_input,
            entry_type=entry_type,
            content=content,
            summary=summary,
            metadata=metadata,
            visibility=visibility,
            source=source,
        )

    async def upsert_run_scratch(
        self,
        *,
        run_id: UUID,
        actor_input: ParticipantInput,
        entry_type: str,
        content: str,
        summary: str | None = None,
        metadata: dict[str, object] | None = None,
        visibility: str = "agents_only",
        source: str = "agent_runtime",
        memory_entry_id: UUID | None = None,
    ) -> MemoryEntry:
        run = await self._repository.fetch_run(run_id)
        if run is None:
            raise KeyError(f"Run {run_id} not found")
        now = self._now()
        participant = await self._participant_profile_for_actor(
            workspace_id=run.workspace_id,
            actor=actor_input,
            now=now,
        )
        existing_entry: MemoryEntry | None = None
        if memory_entry_id is not None:
            existing_entry = await self._repository.fetch_memory_entry(memory_entry_id)
            if existing_entry is None or existing_entry.run_id != run_id:
                raise KeyError(f"Run scratch entry {memory_entry_id} not found for run {run_id}")
        entry = MemoryEntry(
            memory_entry_id=memory_entry_id or uuid4(),
            scope="run",
            state="scratch",
            workspace_id=run.workspace_id,
            thread_id=run.thread_id,
            run_id=run_id,
            entry_type=entry_type,
            content=content,
            summary=summary,
            source=source,
            created_by=(
                existing_entry.created_by if existing_entry is not None else actor_input.participant_id
            ),
            updated_by=actor_input.participant_id,
            visibility=visibility,
            metadata=dict(metadata or {}),
            created_at=existing_entry.created_at if existing_entry is not None else now,
            updated_at=now,
            version=(existing_entry.version + 1) if existing_entry is not None else 1,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, entry)
        await self._sync_memory_entry(entry)
        return entry

    async def publish_presence(
        self,
        *,
        thread_id: UUID,
        actor_input: ParticipantInput,
        status: str,
        connection_id: str | None = None,
    ) -> EventEnvelope:
        logger.debug(
            "Kernel publish_presence thread_id=%s participant_id=%s status=%s connection_id=%s",
            thread_id,
            actor_input.participant_id,
            status,
            connection_id,
        )
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        now = self._now()
        actor = self._actor_from_input(actor_input)
        participant = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=actor_input,
            now=now,
            status=status,
        )
        presence = PresenceState(
            participant_id=actor_input.participant_id,
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            status=status,
            connection_id=connection_id,
            last_seen_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                if status == "offline":
                    await self._repository.close_active_membership(
                        conn,
                        thread_id=thread_id,
                        participant_id=actor_input.participant_id,
                        left_at=now,
                    )
                else:
                    membership = await self._repository.fetch_active_membership(
                        conn,
                        thread_id=thread_id,
                        participant_id=actor_input.participant_id,
                    )
                    if membership is None:
                        logger.debug(
                            "Kernel publish_presence creating membership thread_id=%s participant_id=%s",
                            thread_id,
                            actor_input.participant_id,
                        )
                        membership = Membership(
                            membership_id=uuid4(),
                            workspace_id=thread.workspace_id,
                            thread_id=thread_id,
                            participant_id=actor_input.participant_id,
                            role="participant",
                            permissions=["post_messages"],
                            joined_at=now,
                        )
                        await self._repository.upsert_membership(conn, membership)
                    else:
                        logger.debug(
                            "Kernel publish_presence reusing membership membership_id=%s thread_id=%s participant_id=%s",
                            membership.membership_id,
                            thread_id,
                            actor_input.participant_id,
                        )
                event = await self._build_thread_event(
                    conn,
                    thread.workspace_id,
                    thread_id,
                    "presence.updated",
                    actor=actor,
                    target=TargetRef(type="participant", id=actor_input.participant_id),
                    visibility="workspace",
                    payload=presence.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        logger.debug(
            "Kernel publish_presence complete thread_id=%s participant_id=%s sequence=%s",
            thread_id,
            actor_input.participant_id,
            event.sequence,
        )
        return event

    async def list_thread_events(
        self, thread_id: UUID, *, after_sequence: int | None = None
    ) -> list[EventEnvelope]:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        return await self._repository.list_thread_events(
            thread_id, after_sequence=after_sequence
        )

    async def record_audit_event(self, draft: AuditEventDraft) -> AuditEvent:
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                return await self._repository.append_audit_event(conn, draft)

    async def get_audit_event(self, audit_event_id: UUID) -> AuditEvent | None:
        return await self._repository.get_audit_event(audit_event_id)

    async def list_audit_events(
        self,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        thread_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        actor_system_agent_id: UUID | None = None,
        action_prefix: str | None = None,
        outcome: str | None = None,
        target_type: str | None = None,
        target_id: UUID | None = None,
        correlation_id: UUID | None = None,
        request_id: UUID | None = None,
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
        limit: int = 100,
    ) -> AuditEventPage:
        return await self._repository.list_audit_events(
            organization_id=organization_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor_user_id=actor_user_id,
            actor_system_agent_id=actor_system_agent_id,
            action_prefix=action_prefix,
            outcome=outcome,
            target_type=target_type,
            target_id=target_id,
            correlation_id=correlation_id,
            request_id=request_id,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
            limit=limit,
        )

    async def verify_audit_chain(
        self,
        chain_partition: str,
    ) -> AuditChainVerificationResult:
        return await self._repository.verify_audit_chain(chain_partition)

    async def _build_message_tasks(
        self,
        *,
        thread: Thread,
        message: TimelineMessage,
        actor_input: ParticipantInput,
        visibility: str,
        timestamp: datetime,
    ) -> list[Task]:
        participants = await self._repository.list_participants(thread.workspace_id)
        active_agents = [
            participant
            for participant in participants
            if participant.participant_type == "agent"
            and participant.status in {"active", "idle"}
            and participant.system_agent_id is not None
        ]
        target_system_agent_id = self._metadata_uuid(message.metadata, "target_system_agent_id")
        target_participant_id = self._metadata_uuid(message.metadata, "target_participant_id")
        tool_generation_request_id = self._metadata_uuid(
            message.metadata,
            "tool_generation_request_id",
        )
        task_instructions = message.metadata.get("task_instructions")
        if not isinstance(task_instructions, list) or not all(
            isinstance(item, str) for item in task_instructions
        ):
            task_instructions = []
        if target_system_agent_id is not None:
            active_agents = [
                participant
                for participant in active_agents
                if participant.system_agent_id == target_system_agent_id
            ]
        if target_participant_id is not None:
            active_agents = [
                participant
                for participant in active_agents
                if participant.participant_id == target_participant_id
            ]
        if target_system_agent_id is None and target_participant_id is None:
            active_agents = [
                participant
                for participant in active_agents
                if self._participant_accepts_normal_message_fanout(participant)
            ]
        tasks: list[Task] = []
        if not active_agents:
            tasks.append(
                Task(
                    task_id=uuid4(),
                    workspace_id=thread.workspace_id,
                    thread_id=thread.thread_id,
                    title=f"Respond to message {message.message_id}",
                    description="Agent response requested for posted message.",
                    requested_by=actor_input.participant_id,
                    correlation_id=message.correlation_id,
                    causation_id=message.message_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                    metadata={
                        "trigger_message_id": str(message.message_id),
                        "sequence_ceiling": message.sequence,
                        "response_visibility": self._response_visibility(visibility),
                        "routing_reason": "no_attached_agents",
                        **(
                            {
                                "tool_generation_request_id": str(tool_generation_request_id),
                                "tool_generation_request_status": message.metadata.get(
                                    "tool_generation_request_status",
                                ),
                            }
                            if tool_generation_request_id is not None
                            else {}
                        ),
                        **(
                            {"task_instructions": task_instructions}
                            if task_instructions
                            else {}
                        ),
                    },
                )
            )
            return tasks

        for participant in active_agents:
            tasks.append(
                Task(
                    task_id=uuid4(),
                    workspace_id=thread.workspace_id,
                    thread_id=thread.thread_id,
                    title=f"Reply as {participant.display_name}",
                    description="Agent response requested for posted message.",
                    requested_by=actor_input.participant_id,
                    correlation_id=message.correlation_id,
                    causation_id=message.message_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                    metadata={
                        "target_system_agent_id": str(participant.system_agent_id),
                        "target_participant_id": str(participant.participant_id),
                        "trigger_message_id": str(message.message_id),
                        "sequence_ceiling": message.sequence,
                        "response_visibility": self._response_visibility(visibility),
                        "routing_reason": "workspace_attached_agent",
                        **(
                            {
                                "tool_generation_request_id": str(tool_generation_request_id),
                                "tool_generation_request_status": message.metadata.get(
                                    "tool_generation_request_status",
                                ),
                            }
                            if tool_generation_request_id is not None
                            else {}
                        ),
                        **(
                            {"task_instructions": task_instructions}
                            if task_instructions
                            else {}
                        ),
                    },
                )
            )
        return tasks

    async def _build_tool_generation_request_for_message(
        self,
        *,
        thread: Thread,
        actor_input: ParticipantInput,
        participant: ParticipantProfile,
        content: str,
        metadata: dict[str, object],
        timestamp: datetime,
    ) -> ToolGenerationRequest | None:
        if actor_input.participant_type != "user":
            return None
        if metadata.get("tool_generation_request_id") is not None:
            return None
        target_system_agent_id = self._metadata_uuid(metadata, "target_system_agent_id")
        if target_system_agent_id is None:
            return None
        target_agent = await self._repository.fetch_system_agent(target_system_agent_id)
        if target_agent is None or not self._is_tool_generation_agent(target_agent):
            return None
        target_participant = await self._repository.fetch_agent_participant(
            thread.workspace_id,
            target_system_agent_id,
        )
        if target_participant is None or target_participant.status not in {"active", "idle", "busy"}:
            return None
        workspace = await self._repository.fetch_workspace(thread.workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {thread.workspace_id} not found")
        summary = content.strip()[:500] or None
        return ToolGenerationRequest(
            request_id=uuid4(),
            organization_id=workspace.organization_id,
            workspace_id=thread.workspace_id,
            thread_id=thread.thread_id,
            requester_participant_id=participant.participant_id,
            requester_message_id=None,
            target_system_agent_id=target_system_agent_id,
            requested_scope=self._tool_generation_requested_scope(metadata),
            status="submitted",
            target_tool_name=self._tool_generation_target_name(metadata, content),
            summary=summary,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "source": "targeted_message",
                "target_system_agent_id": str(target_system_agent_id),
                **dict(metadata),
            },
        )

    async def _tool_generation_request_detail(
        self,
        request_id: UUID,
    ) -> ToolGenerationRequestDetail:
        request = await self._repository.fetch_tool_generation_request(request_id)
        if request is None:
            raise KeyError(f"Tool generation request {request_id} not found")
        revisions = await self._repository.list_tool_generation_revisions(request_id)
        return ToolGenerationRequestDetail(request=request, revisions=revisions)

    def _validate_tool_generation_revision_submission(
        self,
        revision: ToolGenerationRevision,
        *,
        status: str,
    ) -> None:
        if status != "pending_approval":
            return
        manifest = self._normalize_generated_tool_manifest(revision.manifest)
        if manifest.execution.backend_kind != "docker":
            return
        if not revision.image_ref or not revision.image_digest:
            raise ValueError(
                "Pending-approval Docker revisions require both image_ref and image_digest"
            )
        if not is_registry_backed_image_ref(revision.image_ref):
            raise ValueError(
                "Pending-approval Docker revisions require an OCI registry-backed image_ref"
            )
        if not is_digest(revision.image_digest):
            raise ValueError(
                "Pending-approval Docker revisions require an image_digest in sha256 form"
            )

    def _require_generated_tool_immutable_ref(
        self,
        revision: ToolGenerationRevision,
    ) -> str:
        manifest = self._normalize_generated_tool_manifest(revision.manifest)
        if manifest.execution.backend_kind != "docker":
            raise ValueError("Only generated Docker tools require registry pull verification")
        immutable_ref = digest_pinned_image_ref(revision.image_ref, revision.image_digest)
        if immutable_ref is None:
            raise ValueError(
                "Generated Docker tools can be published only from OCI registry images with a recorded sha256 digest"
            )
        if not is_digest_pinned_image_ref(immutable_ref):
            raise ValueError(
                "Generated Docker tools must publish with an immutable digest-pinned OCI image ref"
            )
        return immutable_ref

    @staticmethod
    def _tool_generation_metadata_with_update(
        existing: dict[str, object],
        **updates: object,
    ) -> dict[str, object]:
        metadata = dict(existing)
        for key, value in updates.items():
            if value is None:
                metadata.pop(key, None)
            else:
                metadata[key] = value
        return metadata

    async def _build_tool_generation_verification_task(
        self,
        *,
        request: ToolGenerationRequest,
        revision: ToolGenerationRevision,
        approver_id: UUID,
        review_reason: str | None,
        immutable_ref: str,
        timestamp: datetime,
    ) -> dict[str, object]:
        participant = await self._repository.fetch_agent_participant(
            request.workspace_id,
            request.target_system_agent_id,
        )
        if participant is None:
            raise KeyError(
                f"System agent {request.target_system_agent_id} is not attached to workspace {request.workspace_id}"
            )
        tool = await self._repository.fetch_agent_internal_tool_by_name(
            request.target_system_agent_id,
            _TOOL_GENERATION_REGISTRY_VERIFY_TOOL,
        )
        if tool is None:
            raise KeyError(
                f"Internal tool {_TOOL_GENERATION_REGISTRY_VERIFY_TOOL!r} is not bound to system agent {request.target_system_agent_id}"
            )
        task = Task(
            task_id=uuid4(),
            workspace_id=request.workspace_id,
            thread_id=request.thread_id,
            title=f"Verify registry pull for generated tool {revision.manifest.name}",
            description=f"Verify worker-side pullability for {immutable_ref}.",
            status="claimed",
            requested_by=request.requester_participant_id,
            claimed_by=participant.participant_id,
            visibility="agents_only",
            correlation_id=uuid4(),
            causation_id=request.request_id,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "target_system_agent_id": str(request.target_system_agent_id),
                "target_participant_id": str(participant.participant_id),
                "routing_reason": "tool_generation_registry_pull_verification",
                "response_visibility": "agents_only",
                "tool_generation_request_id": str(request.request_id),
                "tool_generation_revision_id": str(revision.revision_id),
                "tool_generation_approval_verification": True,
                "tool_generation_approval_actor_id": str(approver_id),
                "tool_generation_approval_reason": review_reason,
                "tool_generation_approval_immutable_ref": immutable_ref,
            },
        )
        run = Run(
            run_id=uuid4(),
            workspace_id=request.workspace_id,
            thread_id=request.thread_id,
            task_id=task.task_id,
            participant_id=participant.participant_id,
            status="started",
            correlation_id=task.correlation_id,
            causation_id=task.task_id,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "system_agent_id": str(request.target_system_agent_id),
                "participant_id": str(participant.participant_id),
                "tool_generation_approval_verification": True,
            },
        )
        step = RunStep(
            step_id=uuid4(),
            run_id=run.run_id,
            task_id=task.task_id,
            workspace_id=request.workspace_id,
            thread_id=request.thread_id,
            system_agent_id=request.target_system_agent_id,
            step_index=0,
            status="waiting_tools",
            output={
                "tool_calls_requested": [
                    {
                        "tool_name": tool.name,
                        "arguments": {
                            "immutable_ref": immutable_ref,
                            "image_ref": revision.image_ref,
                            "image_digest": revision.image_digest,
                        },
                        "summary": f"Verify that workers can docker pull {immutable_ref}.",
                    }
                ]
            },
            submitted_at=timestamp,
            started_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "participant_id": str(participant.participant_id),
                "tool_generation_approval_verification": True,
            },
        )
        draft = AgentToolCallDraft(
            tool_name=tool.name,
            arguments={
                "immutable_ref": immutable_ref,
                "image_ref": revision.image_ref,
                "image_digest": revision.image_digest,
            },
            summary=f"Verify worker-side docker pull for {immutable_ref}.",
            metadata={
                "tool_generation_request_id": str(request.request_id),
                "tool_generation_revision_id": str(revision.revision_id),
                "tool_generation_approval_verification": True,
                "tool_generation_approval_actor_id": str(approver_id),
                "tool_generation_approval_reason": review_reason,
                "tool_generation_approval_immutable_ref": immutable_ref,
            },
        )
        tool_call = ToolCall(
            tool_call_id=uuid4(),
            run_id=run.run_id,
            run_step_id=step.step_id,
            task_id=task.task_id,
            workspace_id=request.workspace_id,
            thread_id=request.thread_id,
            system_agent_id=request.target_system_agent_id,
            tool_id=tool.tool_id,
            tool_name=tool.name,
            status="created",
            arguments=draft.arguments,
            execution_spec=self._build_tool_execution_spec(
                tool=tool,
                draft=draft,
                workspace_id=request.workspace_id,
            ).model_dump(mode="json"),
            submitted_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
            metadata=draft.metadata,
        )
        return {
            "task": task,
            "run": run,
            "step": step,
            "tool_call": tool_call,
            "participant": participant,
        }

    @staticmethod
    def _is_tool_generation_agent(agent: AgentDefinition) -> bool:
        return bool(agent.metadata.get("tool_generation_agent")) or bool(
            agent.definition.get("tool_generation_agent")
        )

    @staticmethod
    def _tool_generation_target_name(
        metadata: dict[str, object],
        content: str,
    ) -> str | None:
        explicit = metadata.get("target_tool_name")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        stripped = content.strip()
        if not stripped:
            return None
        lowered = stripped.lower()
        marker = "tool "
        if marker in lowered:
            index = lowered.find(marker) + len(marker)
            candidate = stripped[index:].strip(" :.-")
            return candidate[:200] or None
        return None

    @staticmethod
    def _tool_generation_requested_scope(
        metadata: dict[str, object],
    ) -> str:
        value = metadata.get("target_tool_scope")
        if isinstance(value, str) and value in {"global", "organization"}:
            return value
        return "global"

    def _normalize_generated_tool_manifest(
        self,
        manifest: GeneratedToolManifest,
    ) -> GeneratedToolManifest:
        execution_profile = dict(manifest.execution.execution_profile)
        execution_profile["network"] = manifest.network_access
        execution_profile["workspace_access"] = manifest.workspace_access
        execution = manifest.execution.model_copy(update={"execution_profile": execution_profile})
        self._validate_tool_execution_binding(execution)
        return manifest.model_copy(update={"execution": execution})

    async def _link_generated_tool_assets(
        self,
        conn: asyncpg.Connection,
        *,
        request: ToolGenerationRequest,
        revision: ToolGenerationRevision,
        tool: SystemToolDefinition,
        actor_id: UUID,
        timestamp: datetime,
    ) -> None:
        for purpose, asset_id, asset_version_id in (
            ("generated_source", revision.source_asset_id, revision.source_asset_version_id),
            ("generated_manifest", revision.manifest_asset_id, revision.manifest_asset_version_id),
            ("generated_report", revision.report_asset_id, revision.report_asset_version_id),
        ):
            if asset_id is None or asset_version_id is None:
                continue
            await self._repository.deactivate_asset_links(
                conn,
                target_type="system_tool",
                target_id=tool.tool_id,
                purpose=purpose,
                organization_id=None,
                workspace_id=None,
            )
            await self._repository.upsert_asset_link(
                conn,
                AssetLink(
                    link_id=uuid4(),
                    asset_id=asset_id,
                    asset_version_id=asset_version_id,
                    organization_id=None,
                    workspace_id=None,
                    target_type="system_tool",
                    target_id=tool.tool_id,
                    purpose=purpose,
                    active=True,
                    created_by=actor_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                    metadata={
                        "tool_generation_request_id": str(request.request_id),
                        "tool_generation_revision_id": str(revision.revision_id),
                    },
                ),
            )

    async def _create_tool_generation_status_message(
        self,
        conn: asyncpg.Connection,
        *,
        request: ToolGenerationRequest,
        revision: ToolGenerationRevision | None,
        status: str,
        content: str,
        timestamp: datetime,
    ) -> tuple[TimelineMessage | None, EventEnvelope | None]:
        participant = await self._repository.fetch_agent_participant(
            request.workspace_id,
            request.target_system_agent_id,
        )
        if participant is None:
            return None, None
        membership = await self._repository.fetch_active_membership(
            conn,
            thread_id=request.thread_id,
            participant_id=participant.participant_id,
        )
        if membership is None:
            await self._repository.upsert_membership(
                conn,
                Membership(
                    membership_id=uuid4(),
                    workspace_id=request.workspace_id,
                    thread_id=request.thread_id,
                    participant_id=participant.participant_id,
                    role="participant",
                    permissions=["post_messages"],
                    joined_at=timestamp,
                ),
            )
        message = TimelineMessage(
            message_id=uuid4(),
            workspace_id=request.workspace_id,
            thread_id=request.thread_id,
            actor=ActorRef(type="agent", id=participant.participant_id),
            visibility="workspace",
            content=content,
            status="completed",
            correlation_id=uuid4(),
            sequence=await self._repository.next_thread_sequence(conn, request.thread_id),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "tool_generation_request_id": str(request.request_id),
                "tool_generation_status": status,
                "tool_generation_request_status": request.status,
                **(
                    {"tool_generation_revision_id": str(revision.revision_id)}
                    if revision is not None
                    else {}
                ),
            },
        )
        await self._repository.upsert_message(conn, message)
        event = await self._build_thread_event(
            conn,
            request.workspace_id,
            request.thread_id,
            "message.created",
            actor=message.actor,
            target=TargetRef(type="message", id=message.message_id),
            visibility=message.visibility,
            payload=message.model_dump(mode="json"),
            timestamp=timestamp,
        )
        return message, event

    async def _publish_verified_tool_generation_revision_in_transaction(
        self,
        conn: asyncpg.Connection,
        *,
        request: ToolGenerationRequest,
        revision: ToolGenerationRevision,
        approver_id: UUID,
        timestamp: datetime,
    ) -> tuple[SystemToolDefinition, ToolGenerationRequest, ToolGenerationRevision]:
        manifest = self._normalize_generated_tool_manifest(revision.manifest)
        immutable_ref = self._require_generated_tool_immutable_ref(revision)
        execution = manifest.execution.model_copy(update={"handler_ref": immutable_ref})
        tool_scope = request.requested_scope
        tool = SystemToolDefinition(
            tool_id=uuid4(),
            scope=tool_scope,
            organization_id=(request.organization_id if tool_scope == "organization" else None),
            name=manifest.name,
            description=manifest.description,
            parameter_contract=manifest.parameter_contract,
            input_schema=manifest.input_schema,
            execution=execution,
            created_by=approver_id,
            created_at=timestamp,
            updated_by=approver_id,
            updated_at=timestamp,
            metadata={
                **manifest.metadata,
                "generated": True,
                "tool_generation_request_id": str(request.request_id),
                "tool_generation_revision_id": str(revision.revision_id),
                "tool_generation_requested_scope": tool_scope,
                **({"image_ref": revision.image_ref} if revision.image_ref is not None else {}),
                **(
                    {"image_digest": revision.image_digest}
                    if revision.image_digest is not None
                    else {}
                ),
                "immutable_image_ref": immutable_ref,
            },
        )
        approved_revision = revision.model_copy(
            update={
                "status": "approved",
                "updated_at": timestamp,
                "metadata": self._tool_generation_metadata_with_update(
                    revision.metadata,
                    approval_verification_error=None,
                    approval_verification_completed_at=timestamp.isoformat(),
                    approval_verification_immutable_ref=immutable_ref,
                ),
            }
        )
        published_request = request.model_copy(
            update={
                "status": "published",
                "target_tool_name": manifest.name,
                "summary": manifest.description,
                "final_tool_id": tool.tool_id,
                "latest_revision_id": revision.revision_id,
                "approved_by": approver_id,
                "approved_at": timestamp,
                "published_at": timestamp,
                "rejected_by": None,
                "rejected_at": None,
                "updated_at": timestamp,
                "metadata": self._tool_generation_metadata_with_update(
                    request.metadata,
                    approval_verification_error=None,
                    approval_verification_completed_at=timestamp.isoformat(),
                    approval_verification_immutable_ref=immutable_ref,
                ),
            }
        )
        await self._repository.upsert_system_tool(conn, tool)
        await self._repository.upsert_tool_generation_revision(conn, approved_revision)
        await self._repository.upsert_tool_generation_request(conn, published_request)
        await self._link_generated_tool_assets(
            conn,
            request=published_request,
            revision=approved_revision,
            tool=tool,
            actor_id=approver_id,
            timestamp=timestamp,
        )
        return tool, published_request, approved_revision

    async def _handle_tool_generation_verification_completion(
        self,
        *,
        tool_call: ToolCall,
        run: Run,
        task: Task,
        status: str,
        result: ToolCallResult,
        error: str | None,
    ) -> tuple[list[EventEnvelope], list[TimelineMessage]]:
        request_id = self._metadata_uuid(tool_call.metadata, "tool_generation_request_id")
        revision_id = self._metadata_uuid(tool_call.metadata, "tool_generation_revision_id")
        approver_id = self._metadata_uuid(tool_call.metadata, "tool_generation_approval_actor_id")
        if request_id is None or revision_id is None:
            return [], []
        request = await self._repository.fetch_tool_generation_request(request_id)
        revision = await self._repository.fetch_tool_generation_revision(revision_id)
        if request is None or revision is None:
            return [], []
        rendered_messages: list[TimelineMessage] = []
        events: list[EventEnvelope] = []
        now = self._now()
        effective_approver_id = approver_id or request.requester_participant_id
        verification_error = error or result.error or "Worker-side registry pull verification failed"
        if request.status == "verifying_registry_pull" and revision.status == "verifying_registry_pull":
            async with self._repository._pool.acquire() as conn:  # noqa: SLF001
                async with conn.transaction():
                    if status == "completed":
                        tool, published_request, approved_revision = (
                            await self._publish_verified_tool_generation_revision_in_transaction(
                                conn,
                                request=request,
                                revision=revision,
                                approver_id=effective_approver_id,
                                timestamp=now,
                            )
                        )
                        published_event = await self._build_thread_event(
                            conn,
                            request.workspace_id,
                            request.thread_id,
                            "tool_generation_revision.published",
                            actor=ActorRef(type="user", id=effective_approver_id),
                            target=TargetRef(
                                type="tool_generation_revision",
                                id=approved_revision.revision_id,
                            ),
                            visibility="workspace",
                            payload={
                                "request_id": str(published_request.request_id),
                                "revision_id": str(approved_revision.revision_id),
                                "tool_id": str(tool.tool_id),
                                "scope": tool.scope,
                                "immutable_ref": tool.execution.handler_ref,
                            },
                            timestamp=now,
                        )
                        await self._repository.record_event(conn, published_event)
                        events.append(published_event)
                        status_message, message_event = await self._create_tool_generation_status_message(
                            conn,
                            request=published_request,
                            revision=approved_revision,
                            status="published",
                            content=self._tool_generation_published_message(
                                tool,
                                approved_revision,
                            ),
                            timestamp=now,
                        )
                    else:
                        pending_request = request.model_copy(
                            update={
                                "status": "pending_approval",
                                "updated_at": now,
                                "metadata": self._tool_generation_metadata_with_update(
                                    request.metadata,
                                    approval_verification_error=verification_error,
                                    approval_verification_failed_at=now.isoformat(),
                                ),
                            }
                        )
                        pending_revision = revision.model_copy(
                            update={
                                "status": "pending_approval",
                                "updated_at": now,
                                "metadata": self._tool_generation_metadata_with_update(
                                    revision.metadata,
                                    approval_verification_error=verification_error,
                                    approval_verification_failed_at=now.isoformat(),
                                ),
                            }
                        )
                        await self._repository.upsert_tool_generation_request(conn, pending_request)
                        await self._repository.upsert_tool_generation_revision(conn, pending_revision)
                        verification_failed_event = await self._build_thread_event(
                            conn,
                            request.workspace_id,
                            request.thread_id,
                            "tool_generation_revision.verification_failed",
                            actor=ActorRef(type="user", id=effective_approver_id),
                            target=TargetRef(
                                type="tool_generation_revision",
                                id=pending_revision.revision_id,
                            ),
                            visibility="workspace",
                            payload={
                                "request_id": str(pending_request.request_id),
                                "revision_id": str(pending_revision.revision_id),
                                "error": verification_error,
                            },
                            timestamp=now,
                        )
                        await self._repository.record_event(conn, verification_failed_event)
                        events.append(verification_failed_event)
                        status_message, message_event = await self._create_tool_generation_status_message(
                            conn,
                            request=pending_request,
                            revision=pending_revision,
                            status="pending_approval",
                            content=self._tool_generation_verification_failed_message(
                                verification_error
                            ),
                            timestamp=now,
                        )
                    if status_message is not None:
                        rendered_messages.append(status_message)
                    if message_event is not None:
                        await self._repository.record_event(conn, message_event)
                        events.append(message_event)
        if status == "completed":
            run_completion = await self.complete_run(
                run.run_id,
                tool_call.system_agent_id,
                AgentRunResult(
                    stop_reason="completed",
                    summary="Completed registry pull verification for a generated tool revision.",
                    metadata={"tool_generation_approval_verification": True},
                ),
            )
        else:
            run_completion = await self.fail_run(
                run.run_id,
                tool_call.system_agent_id,
                verification_error,
                stop_reason="tool_failure",
            )
        events.extend(run_completion.events)
        return events, rendered_messages

    @staticmethod
    def _tool_generation_pending_approval_message(
        request: ToolGenerationRequest,
        revision: ToolGenerationRevision,
    ) -> str:
        lines = [
            f"Tinker prepared tool revision `{revision.manifest.name}` for platform approval.",
            f"Requested catalog scope: `{request.requested_scope}`.",
            f"Status: pending approval. Trust: `{revision.manifest.execution.trust_level}`. Network: `{revision.manifest.network_access}`. Workspace access: `{revision.manifest.workspace_access}`.",
        ]
        if revision.image_ref:
            lines.append(f"Image: `{revision.image_ref}`")
        if revision.image_digest:
            lines.append(f"Digest: `{revision.image_digest}`")
        if revision.validation_report and revision.validation_report.summary:
            lines.append(f"Validation: {revision.validation_report.summary}")
        return "\n".join(lines)

    @staticmethod
    def _tool_generation_verifying_message(
        request: ToolGenerationRequest,
        revision: ToolGenerationRevision,
        *,
        immutable_ref: str,
    ) -> str:
        lines = [
            f"Approval started for generated tool `{revision.manifest.name}`.",
            f"Requested catalog scope: `{request.requested_scope}`.",
            f"Status: verifying worker-side registry pull for `{immutable_ref}`.",
        ]
        if revision.image_ref:
            lines.append(f"Pushed image ref: `{revision.image_ref}`")
        if revision.image_digest:
            lines.append(f"Resolved digest: `{revision.image_digest}`")
        return "\n".join(lines)

    @staticmethod
    def _tool_generation_published_message(
        tool: SystemToolDefinition,
        revision: ToolGenerationRevision,
    ) -> str:
        catalog_label = (
            "the organization system tools catalog"
            if tool.scope == "organization"
            else "the global system tools catalog"
        )
        lines = [
            f"Tool `{tool.name}` was approved and added to {catalog_label}.",
            "It is not attached to any workspace automatically. Workspace admins or supervisors can attach it when needed.",
        ]
        if tool.execution.handler_ref:
            lines.append(f"Published image: `{tool.execution.handler_ref}`")
        if revision.image_digest:
            lines.append(f"Published image digest: `{revision.image_digest}`")
        return "\n".join(lines)

    @staticmethod
    def _tool_generation_rejected_message(reason: str | None) -> str:
        if reason and reason.strip():
            return f"Tool-generation revision was rejected for this request.\nReason: {reason.strip()}"
        return "Tool-generation revision was rejected for this request."

    @staticmethod
    def _tool_generation_verification_failed_message(reason: str) -> str:
        return (
            "Worker-side registry pull verification failed, so the request returned to pending approval.\n"
            f"Reason: {reason}"
        )

    @staticmethod
    def _metadata_uuid(metadata: dict[str, object], key: str) -> UUID | None:
        value = metadata.get(key)
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    async def _create_interaction_requests_in_transaction(
        self,
        conn: asyncpg.Connection,
        *,
        thread: Thread,
        actor_input: ParticipantInput,
        requests: list[CreateInteractionRequest],
        timestamp: datetime,
        correlation_id: UUID,
        requester_message: TimelineMessage | None,
        requester_run: Run | None = None,
        requester_task: Task | None = None,
    ) -> InteractionRequestCommandResult:
        actor = self._actor_from_input(actor_input)
        requester = await self._repository.fetch_participant(
            thread.workspace_id,
            actor_input.participant_id,
        )
        if requester is None:
            requester = self._participant_profile(
                workspace_id=thread.workspace_id,
                actor=actor_input,
                now=timestamp,
            )
        await self._ensure_participant_identity(conn, requester)
        await self._repository.upsert_participant(conn, requester)
        details: list[InteractionRequestDetail] = []
        rendered_messages: list[TimelineMessage] = []
        events: list[EventEnvelope] = []
        for request_input in requests:
            detail, rendered_message, request_events = await self._create_interaction_request_in_transaction(
                conn,
                thread=thread,
                requester=requester,
                request_input=request_input,
                timestamp=timestamp,
                correlation_id=correlation_id,
                requester_message=requester_message,
                requester_run=requester_run,
                requester_task=requester_task,
            )
            details.append(detail)
            rendered_messages.append(rendered_message)
            events.extend(request_events)
        return InteractionRequestCommandResult(
            details=details,
            messages=rendered_messages,
            events=events,
        )

    async def _create_interaction_request_in_transaction(
        self,
        conn: asyncpg.Connection,
        *,
        thread: Thread,
        requester: ParticipantProfile,
        request_input: CreateInteractionRequest,
        timestamp: datetime,
        correlation_id: UUID,
        requester_message: TimelineMessage | None,
        requester_run: Run | None,
        requester_task: Task | None,
    ) -> tuple[InteractionRequestDetail, TimelineMessage, list[EventEnvelope]]:
        if not request_input.questions:
            raise ValueError("Interaction requests must include at least one question")
        resolved_targets = await self._resolve_interaction_request_targets(
            thread=thread,
            requester=requester,
            request_input=request_input,
        )
        completion_rule = self._normalize_completion_rule(
            request_input.completion_rule,
            resolved_targets=resolved_targets,
        )
        request = InteractionRequest(
            request_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread.thread_id,
            requester_participant_id=requester.participant_id,
            requester_message_id=(
                requester_message.message_id if requester_message is not None else None
            ),
            requester_run_id=requester_run.run_id if requester_run is not None else None,
            requester_task_id=requester_task.task_id if requester_task is not None else None,
            title=request_input.title,
            summary=request_input.summary,
            completion_rule=completion_rule,
            timeout_at=request_input.timeout_at,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                **request_input.metadata,
                "selectors": [
                    selector.model_dump(mode="json") for selector in request_input.selectors
                ],
                "input_target_participant_ids": [
                    str(participant_id)
                    for participant_id in request_input.target_participant_ids
                ],
            },
        )
        await self._repository.upsert_interaction_request(conn, request)
        questions: list[InteractionQuestion] = []
        for index, question_input in enumerate(request_input.questions):
            question = InteractionQuestion(
                question_id=uuid4(),
                request_id=request.request_id,
                prompt=question_input.prompt,
                kind=question_input.kind,
                expected_format=question_input.expected_format,
                order=index,
                metadata=question_input.metadata,
            )
            questions.append(question)
            await self._repository.upsert_interaction_request_question(conn, question)
        targets: list[InteractionRequestTarget] = []
        for resolved in resolved_targets:
            target = InteractionRequestTarget(
                target_id=uuid4(),
                request_id=request.request_id,
                participant_id=resolved["participant"].participant_id,
                selector_type=resolved["selector_type"],
                selector_value=resolved["selector_value"],
                selection_source=resolved["selection_source"],
                score=resolved["score"],
                created_at=timestamp,
                updated_at=timestamp,
                metadata=resolved["metadata"],
            )
            targets.append(target)
            await self._repository.upsert_interaction_request_target(conn, target)
        detail = InteractionRequestDetail(
            request=request,
            questions=questions,
            targets=targets,
            answers=[],
        )
        aggregate, completed = await self._interaction_request_aggregate_state(detail)
        if completed:
            request = request.model_copy(
                update={
                    "status": "completed",
                    "completed_at": timestamp,
                    "metadata": {**request.metadata, "aggregate": aggregate},
                }
            )
        else:
            request = request.model_copy(
                update={"metadata": {**request.metadata, "aggregate": aggregate}}
            )
        await self._repository.upsert_interaction_request(conn, request)
        detail = detail.model_copy(update={"request": request})
        rendered_message = TimelineMessage(
            message_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread.thread_id,
            actor=ActorRef(type=requester.participant_type, id=requester.participant_id),
            visibility="workspace",
            content=self._render_interaction_request_message(detail),
            status="completed",
            correlation_id=correlation_id,
            causation_id=request.request_id,
            sequence=await self._repository.next_thread_sequence(conn, thread.thread_id),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "interaction_request_id": str(request.request_id),
                "interaction_request_status": request.status,
                "interaction_request_title": request.title,
                "interaction_target_count": len(targets),
                "interaction_questions": [
                    question.model_dump(mode="json") for question in questions
                ],
                "interaction_aggregate": aggregate,
            },
        )
        events = [
            await self._build_thread_event(
                conn,
                request.workspace_id,
                request.thread_id,
                "interaction_request.created",
                actor=ActorRef(type=requester.participant_type, id=requester.participant_id),
                target=TargetRef(type="interaction_request", id=request.request_id),
                visibility="workspace",
                payload={
                    "request": request.model_dump(mode="json"),
                    "questions": [question.model_dump(mode="json") for question in questions],
                    "targets": [target.model_dump(mode="json") for target in targets],
                },
                timestamp=timestamp,
                correlation_id=correlation_id,
                causation_id=request.request_id,
            )
        ]
        return detail, rendered_message, events

    async def _resolve_interaction_request_targets(
        self,
        *,
        thread: Thread,
        requester: ParticipantProfile,
        request_input: CreateInteractionRequest,
    ) -> list[dict[str, object]]:
        participants = await self._repository.list_participants(thread.workspace_id)
        memberships = await self._repository.list_memberships(thread.thread_id)
        active_member_ids = {
            membership.participant_id for membership in memberships if membership.left_at is None
        }
        desired_responder_types = list(
            request_input.metadata.get("desired_responder_types", [])
        )
        if not desired_responder_types:
            desired_responder_types = ["user"] if requester.participant_type == "agent" else ["agent"]

        participant_index = {
            participant.participant_id: participant for participant in participants
        }
        explicit_targets: dict[UUID, dict[str, object]] = {}
        for participant_id in request_input.target_participant_ids:
            participant = participant_index.get(participant_id)
            if participant is None:
                raise KeyError(f"Participant {participant_id} not found in workspace {thread.workspace_id}")
            explicit_targets[participant_id] = {
                "participant": participant,
                "selector_type": "participant",
                "selector_value": str(participant_id),
                "selection_source": "explicit_participant_id",
                "score": 1000.0,
                "metadata": {"matched_selectors": [str(participant_id)]},
            }

        for selector in request_input.selectors:
            if selector.type == "participant":
                participant = self._resolve_participant_selector_match(
                    selector=selector,
                    participants=participants,
                )
                if participant is None:
                    continue
                explicit_targets[participant.participant_id] = {
                    "participant": participant,
                    "selector_type": "participant",
                    "selector_value": selector.value,
                    "selection_source": "participant_selector",
                    "score": 1000.0,
                    "metadata": {"matched_selectors": [selector.value]},
                }

        if explicit_targets:
            return list(explicit_targets.values())

        selector_targets: dict[UUID, dict[str, object]] = {}
        role_or_capability_selectors = [
            selector for selector in request_input.selectors if selector.type in {"role", "capability"}
        ]
        if role_or_capability_selectors:
            for selector in role_or_capability_selectors:
                best = self._best_participant_for_selector(
                    selector=selector,
                    participants=participants,
                    desired_responder_types=desired_responder_types,
                    requester=requester,
                    active_member_ids=active_member_ids,
                )
                if best is None:
                    continue
                existing = selector_targets.get(best.participant_id)
                if existing is None:
                    selector_targets[best.participant_id] = {
                        "participant": best,
                        "selector_type": selector.type,
                        "selector_value": selector.value,
                        "selection_source": "selector",
                        "score": self._interaction_candidate_score(
                            participant=best,
                            selector=selector,
                            requester=requester,
                            active_member_ids=active_member_ids,
                        ),
                        "metadata": {"matched_selectors": [selector.model_dump(mode="json")]},
                    }
                else:
                    existing["metadata"]["matched_selectors"].append(selector.model_dump(mode="json"))  # type: ignore[index]
            if selector_targets:
                return list(selector_targets.values())

        fallback_candidates = [
            participant
            for participant in participants
            if participant.participant_id != requester.participant_id
            and participant.participant_type in desired_responder_types
        ]
        fallback_candidates.sort(
            key=lambda participant: (
                -self._interaction_candidate_score(
                    participant=participant,
                    selector=None,
                    requester=requester,
                    active_member_ids=active_member_ids,
                ),
                participant.display_name.lower(),
            )
        )
        if fallback_candidates:
            best = fallback_candidates[0]
            return [
                {
                    "participant": best,
                    "selector_type": None,
                    "selector_value": None,
                    "selection_source": "auto_best_match",
                    "score": self._interaction_candidate_score(
                        participant=best,
                        selector=None,
                        requester=requester,
                        active_member_ids=active_member_ids,
                    ),
                    "metadata": {},
                }
            ]
        if requester.participant_type == "agent":
            fallback_managers = [
                participant
                for participant in participants
                if participant.participant_type == "user"
                and {"admin", "supervisor"}.intersection(participant.roles)
            ]
            fallback_managers.sort(key=lambda participant: participant.display_name.lower())
            if fallback_managers:
                best = fallback_managers[0]
                return [
                    {
                        "participant": best,
                        "selector_type": None,
                        "selector_value": None,
                        "selection_source": "workspace_manager_fallback",
                        "score": 50.0,
                        "metadata": {},
                    }
                ]
        return []

    @staticmethod
    def _resolve_participant_selector_match(
        *,
        selector: ParticipantSelector,
        participants: list[ParticipantProfile],
    ) -> ParticipantProfile | None:
        if selector.participant_id is not None:
            for participant in participants:
                if participant.participant_id == selector.participant_id:
                    return participant
        normalized = selector.value.strip().lower()
        for participant in participants:
            if str(participant.participant_id).lower() == normalized:
                return participant
            if participant.display_name.lower() == normalized:
                return participant
        return None

    def _best_participant_for_selector(
        self,
        *,
        selector: ParticipantSelector,
        participants: list[ParticipantProfile],
        desired_responder_types: list[str],
        requester: ParticipantProfile,
        active_member_ids: set[UUID],
    ) -> ParticipantProfile | None:
        candidates = [
            participant
            for participant in participants
            if participant.participant_id != requester.participant_id
            and participant.participant_type in desired_responder_types
            and self._participant_matches_selector(participant, selector)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda participant: (
                -self._interaction_candidate_score(
                    participant=participant,
                    selector=selector,
                    requester=requester,
                    active_member_ids=active_member_ids,
                ),
                participant.display_name.lower(),
            )
        )
        return candidates[0]

    @staticmethod
    def _participant_matches_selector(
        participant: ParticipantProfile,
        selector: ParticipantSelector,
    ) -> bool:
        normalized = selector.value.strip().lower()
        if selector.type == "role":
            return normalized in {role.lower() for role in participant.roles}
        if selector.type == "capability":
            return normalized in {capability.lower() for capability in participant.capabilities}
        return False

    def _interaction_candidate_score(
        self,
        *,
        participant: ParticipantProfile,
        selector: ParticipantSelector | None,
        requester: ParticipantProfile,
        active_member_ids: set[UUID],
    ) -> float:
        score = 0.0
        if participant.participant_id in active_member_ids:
            score += 25.0
        score += {
            "active": 20.0,
            "idle": 15.0,
            "busy": 5.0,
            "offline": 0.0,
        }.get(participant.status, 0.0)
        if selector is not None and self._participant_matches_selector(participant, selector):
            score += 50.0
        if requester.participant_type == "agent" and {"admin", "supervisor"}.intersection(participant.roles):
            score += 5.0
        return score

    @staticmethod
    def _normalize_completion_rule(
        completion_rule: CompletionRule | None,
        *,
        resolved_targets: list[dict[str, object]],
    ) -> CompletionRule:
        if completion_rule is not None:
            return completion_rule
        return CompletionRule(
            mode="all_targets",
            target_participant_ids=[
                resolved["participant"].participant_id  # type: ignore[index]
                for resolved in resolved_targets
            ],
        )

    async def _interaction_request_aggregate_state(
        self,
        detail: InteractionRequestDetail,
    ) -> tuple[dict[str, object], bool]:
        participants = {
            participant.participant_id: participant
            for participant in await self._repository.list_participants(detail.request.workspace_id)
        }
        active_targets = [
            target for target in detail.targets if target.status != "dismissed"
        ]
        answered_target_ids = {
            target.participant_id
            for target in detail.targets
            if target.status == "answered" and target.participant_id is not None
        }
        answered_participant_ids = {
            answer.participant_id for answer in detail.answers
        } | answered_target_ids
        completion_rule = detail.request.completion_rule
        selector_buckets = [
            selector
            for selector in detail.request.metadata.get("selectors", [])
            if selector.get("type") in {"role", "capability"}
        ]
        covered_buckets: list[str] = []
        for selector in selector_buckets:
            bucket_type = str(selector["type"])
            bucket_value = str(selector["value"])
            if any(
                self._participant_matches_selector(
                    participants[participant_id],
                    ParticipantSelector(type=bucket_type, value=bucket_value),
                )
                for participant_id in answered_participant_ids
                if participant_id in participants
            ):
                covered_buckets.append(f"{bucket_type}:{bucket_value}")
        completed = False
        if completion_rule.mode == "all_targets":
            required_ids = {
                target.participant_id for target in active_targets if target.participant_id is not None
            }
            completed = required_ids.issubset(answered_participant_ids)
        elif completion_rule.mode == "minimum_answers":
            minimum_answers = completion_rule.minimum_answers or 1
            completed = len(answered_participant_ids) >= minimum_answers
        elif completion_rule.mode == "one_per_selector_bucket":
            required_buckets = {
                f"{selector['type']}:{selector['value']}" for selector in selector_buckets
            }
            completed = required_buckets.issubset(set(covered_buckets))
        elif completion_rule.mode == "custom_targets":
            required_ids = set(completion_rule.target_participant_ids)
            completed = required_ids.issubset(answered_participant_ids)
        aggregate = {
            "answered_participant_ids": [str(participant_id) for participant_id in sorted(answered_participant_ids)],
            "answered_count": len(answered_participant_ids),
            "target_count": len(active_targets),
            "covered_selector_buckets": covered_buckets,
            "completion_rule": completion_rule.model_dump(mode="json"),
            "completed": completed,
        }
        return aggregate, completed

    def _render_interaction_request_message(
        self,
        detail: InteractionRequestDetail,
    ) -> str:
        lines = [f"[Request] {detail.request.title}"]
        if detail.request.summary:
            lines.extend(["", detail.request.summary])
        if detail.questions:
            lines.append("")
            for index, question in enumerate(detail.questions, start=1):
                lines.append(f"{index}. {question.prompt}")
        if detail.targets:
            lines.append("")
            lines.append("Targets:")
            for target in detail.targets:
                label = str(target.participant_id)
                lines.append(f"- {label}")
        return "\n".join(lines)

    async def _create_interaction_request_followup_task(
        self,
        conn: asyncpg.Connection,
        *,
        request: InteractionRequest,
        detail: InteractionRequestDetail,
        answer_message: TimelineMessage | None,
        timestamp: datetime,
    ) -> Task | None:
        requester = await self._repository.fetch_participant(
            request.workspace_id,
            request.requester_participant_id,
        )
        if requester is None or requester.participant_type != "agent" or requester.system_agent_id is None:
            return None
        existing = await self._repository.list_open_interaction_requests_for_run(
            request.requester_run_id
        ) if request.requester_run_id is not None else []
        if request.status != "completed":
            return None
        task = Task(
            task_id=uuid4(),
            workspace_id=request.workspace_id,
            thread_id=request.thread_id,
            title=f"Continue request {request.request_id}",
            description="Interaction request completed and ready for aggregation.",
            requested_by=request.requester_participant_id,
            correlation_id=answer_message.correlation_id if answer_message is not None else uuid4(),
            causation_id=request.request_id,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "target_system_agent_id": str(requester.system_agent_id),
                "target_participant_id": str(requester.participant_id),
                "request_id": str(request.request_id),
                "trigger_message_id": (
                    str(answer_message.message_id) if answer_message is not None else None
                ),
                "sequence_ceiling": answer_message.sequence if answer_message is not None else 0,
                "response_visibility": "workspace",
                "routing_reason": "interaction_request_completed",
                "open_request_count_for_run": len(existing),
            },
        )
        await self._repository.upsert_task(conn, task)
        return task

    async def _resolve_run_for_context(
        self,
        task: Task,
        participant: ParticipantProfile,
        run_id: UUID | None,
    ) -> Run:
        if run_id is not None:
            run = await self._repository.fetch_run(run_id)
            if run is None:
                raise KeyError(f"Run {run_id} not found")
            return run
        raise ValueError(
            f"A run must exist before building execution context for task {task.task_id}"
        )

    async def _resolve_agent_participant(
        self,
        *,
        workspace_id: UUID,
        system_agent_id: UUID,
        routing: AgentTaskRouting,
    ) -> ParticipantProfile | None:
        if routing.target_participant_id is not None:
            participant = await self._repository.fetch_participant(
                workspace_id,
                routing.target_participant_id,
            )
            if (
                participant is not None
                and participant.participant_type == "agent"
                and participant.system_agent_id == system_agent_id
            ):
                return participant
        return await self._repository.fetch_agent_participant(
            workspace_id,
            system_agent_id,
        )

    async def _resolve_methodics_execution_participant(
        self,
        workspace_id: UUID,
    ) -> ParticipantProfile | None:
        participants = await self._repository.list_participants(workspace_id)
        candidates = [
            participant
            for participant in participants
            if participant.participant_type == "agent"
            and participant.system_agent_id is not None
            and participant.status in {"active", "idle", "busy"}
            and self._participant_accepts_task_kind(
                participant,
                METHODICS_EXECUTION_START_TASK_KIND,
            )
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item.created_at, str(item.participant_id)))
        return candidates[0]

    async def _require_run_participant(
        self,
        *,
        run: Run,
        task: Task,
        system_agent_id: UUID,
    ) -> ParticipantProfile:
        participant = await self._resolve_agent_participant(
            workspace_id=task.workspace_id,
            system_agent_id=system_agent_id,
            routing=self._task_routing(task),
        )
        if participant is None:
            raise KeyError(
                f"System agent {system_agent_id} is not attached to workspace {task.workspace_id}"
            )
        if run.participant_id != participant.participant_id:
            raise ValueError(
                f"Run {run.run_id} does not belong to system agent {system_agent_id}"
            )
        return participant

    @staticmethod
    def _task_routing(task: Task) -> AgentTaskRouting:
        metadata = task.metadata
        return AgentTaskRouting(
            target_system_agent_id=(
                UUID(metadata["target_system_agent_id"])
                if metadata.get("target_system_agent_id")
                else None
            ),
            target_participant_id=(
                UUID(metadata["target_participant_id"])
                if metadata.get("target_participant_id")
                else None
            ),
            trigger_message_id=(
                UUID(metadata["trigger_message_id"])
                if metadata.get("trigger_message_id")
                else None
            ),
            response_visibility=metadata.get("response_visibility", "workspace"),
            sequence_ceiling=metadata.get("sequence_ceiling"),
            routing_reason=metadata.get("routing_reason"),
        )

    @staticmethod
    def _filter_visible_messages(
        messages: list[TimelineMessage],
        *,
        viewer: ParticipantProfile,
        sequence_ceiling: int | None,
    ) -> list[TimelineMessage]:
        visible: list[TimelineMessage] = []
        for message in messages:
            if sequence_ceiling is not None and message.sequence > sequence_ceiling:
                continue
            if message.visibility in {"public", "workspace"}:
                visible.append(message)
                continue
            if (
                message.visibility == "agents_only"
                and viewer.participant_type == "agent"
            ):
                visible.append(message)
                continue
            recipient_participant_id = CollaborationKernel._metadata_uuid(
                message.metadata,
                "recipient_participant_id",
            )
            if message.visibility == "private" and (
                message.actor.id == viewer.participant_id
                or recipient_participant_id == viewer.participant_id
            ):
                visible.append(message)
        return visible

    @staticmethod
    def _filter_visible_memory_entries(
        entries: list[MemoryEntry],
        *,
        viewer: ParticipantProfile,
    ) -> list[MemoryEntry]:
        visible: list[MemoryEntry] = []
        for entry in entries:
            if entry.visibility in {"public", "workspace"}:
                visible.append(entry)
                continue
            if entry.visibility == "agents_only" and viewer.participant_type == "agent":
                visible.append(entry)
                continue
            if entry.visibility == "private" and entry.created_by == viewer.participant_id:
                visible.append(entry)
        return visible

    @staticmethod
    def _response_visibility(message_visibility: str) -> str:
        if message_visibility in {"public", "workspace"}:
            return message_visibility
        return "workspace"

    @staticmethod
    def _workspace_moderation_policy(workspace: Workspace | None) -> WorkspaceModerationPolicy:
        if workspace is None or workspace.harness is None:
            return WorkspaceModerationPolicy()
        return workspace.harness.moderation_policy

    @staticmethod
    def _workspace_moderation_topic(
        workspace: Workspace,
        policy: WorkspaceModerationPolicy,
    ) -> str:
        if policy.topic:
            return policy.topic
        parts = [workspace.name]
        if workspace.description:
            parts.append(workspace.description)
        if workspace.harness is not None:
            if workspace.harness.summary:
                parts.append(workspace.harness.summary)
            methodology = workspace.harness.methodology
            if methodology is not None:
                parts.extend(
                    item
                    for item in (
                        methodology.ontology,
                        methodology.axiology,
                        methodology.epistemology,
                    )
                    if item
                )
                parts.extend(methodology.principles)
        return " | ".join(item.strip() for item in parts if item and item.strip())

    @classmethod
    def _moderation_policy_snapshot(
        cls,
        workspace: Workspace,
        policy: WorkspaceModerationPolicy,
    ) -> dict[str, object]:
        return {
            **policy.model_dump(mode="json"),
            "resolved_topic": cls._workspace_moderation_topic(workspace, policy),
            "workspace_name": workspace.name,
            "workspace_description": workspace.description,
        }

    @staticmethod
    def _participant_accepts_normal_message_fanout(
        participant: ParticipantProfile,
    ) -> bool:
        routing = participant.metadata.get("task_routing")
        if isinstance(routing, dict) and routing.get("normal_message_fanout") is False:
            return False
        return True

    @staticmethod
    def _participant_accepts_task_kind(
        participant: ParticipantProfile,
        task_kind: str,
    ) -> bool:
        routing = participant.metadata.get("task_routing")
        if not isinstance(routing, dict):
            return False
        accepted = routing.get("accepted_task_kinds")
        if not isinstance(accepted, list):
            return False
        return task_kind in {item for item in accepted if isinstance(item, str)}

    @staticmethod
    def _participant_input_from_profile(participant: ParticipantProfile) -> ParticipantInput:
        return ParticipantInput(
            participant_id=participant.participant_id,
            participant_type=participant.participant_type,
            user_id=participant.user_id,
            display_name=participant.display_name,
            description=participant.description,
            roles=list(participant.roles),
            capabilities=list(participant.capabilities),
            visibility_scope=participant.visibility_scope,
        )

    def _build_publication_review_task(
        self,
        *,
        thread: Thread,
        workspace: Workspace,
        message: TimelineMessage,
        candidate_participant: ParticipantProfile,
        reviewer_participant: ParticipantProfile,
        review: PublicationReview,
        policy: WorkspaceModerationPolicy,
        task_kind: str,
        timestamp: datetime,
    ) -> Task:
        snapshot = review.policy_snapshot
        return Task(
            task_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread.thread_id,
            title=f"Review topic fit for message {message.message_id}",
            description="Review candidate workspace communication for topic alignment.",
            requested_by=candidate_participant.participant_id,
            visibility="agents_only",
            correlation_id=message.correlation_id,
            causation_id=message.message_id,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "target_system_agent_id": str(review.reviewer_system_agent_id),
                "target_participant_id": str(reviewer_participant.participant_id),
                "trigger_message_id": str(message.message_id),
                "sequence_ceiling": message.sequence,
                "response_visibility": "agents_only",
                "routing_reason": task_kind,
                "task_kind": task_kind,
                "publication_review_id": str(review.review_id),
                "publication_review_reason": "workspace_topic_alignment",
                "thread_reply_policy": {
                    "mode": "suppress",
                    "reason": "publication_review",
                    "review_id": str(review.review_id),
                },
                "review_kind": review.review_kind,
                "publication_candidate_message_id": str(message.message_id),
                "publication_review_phase": review.phase,
                "publication_review_level": policy.level,
                "moderation_review_id": str(review.review_id),
                "moderation_candidate_message_id": str(message.message_id),
                "moderation_phase": review.phase,
                "moderation_level": policy.level,
                "task_instructions": [
                    f"Moderation level: {policy.level}.",
                    f"Workspace topic: {snapshot.get('resolved_topic') or workspace.name}.",
                    "Allowed adjacent topics: "
                    + (
                        ", ".join(policy.allowed_adjacent_topics)
                        if policy.allowed_adjacent_topics
                        else "none"
                    )
                    + ".",
                    "Blocked topics: "
                    + (
                        ", ".join(policy.blocked_topics)
                        if policy.blocked_topics
                        else "none"
                    )
                    + ".",
                    "Candidate message author: "
                    f"{candidate_participant.display_name} ({candidate_participant.participant_type}).",
                    f"Candidate message visibility: {message.visibility}.",
                    "Candidate message content:",
                    message.content,
                ],
                "moderation_policy": snapshot,
            },
        )

    async def _create_publication_review_and_task_in_transaction(
        self,
        conn: asyncpg.Connection,
        *,
        thread: Thread,
        workspace: Workspace,
        message: TimelineMessage,
        candidate_participant: ParticipantProfile,
        policy: WorkspaceModerationPolicy,
        phase: str,
        review_kind: str,
        reviewer_system_agent_id: UUID,
        task_kind: str,
        timestamp: datetime,
        events: list[EventEnvelope],
    ) -> PublicationReview | None:
        reviewer_participant = await self._repository.fetch_agent_participant(
            thread.workspace_id,
            reviewer_system_agent_id,
        )
        if reviewer_participant is None or reviewer_participant.status not in {
            "active",
            "idle",
            "busy",
        }:
            return None
        review = PublicationReview(
            review_id=uuid4(),
            review_kind=review_kind,
            workspace_id=thread.workspace_id,
            thread_id=thread.thread_id,
            message_id=message.message_id,
            reviewer_system_agent_id=reviewer_system_agent_id,
            candidate_actor_participant_id=candidate_participant.participant_id,
            phase=phase,
            level=policy.level,
            status="pending",
            policy_snapshot=self._moderation_policy_snapshot(workspace, policy),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "task_kind": task_kind,
                "review_kind": review_kind,
            },
        )
        task = self._build_publication_review_task(
            thread=thread,
            workspace=workspace,
            message=message,
            candidate_participant=candidate_participant,
            reviewer_participant=reviewer_participant,
            review=review,
            policy=policy,
            task_kind=task_kind,
            timestamp=timestamp,
        )
        await self._repository.upsert_publication_review(conn, review)
        await self._repository.upsert_task(conn, task)
        events.append(
            await self._build_thread_event(
                conn,
                thread.workspace_id,
                thread.thread_id,
                "task.created",
                actor=message.actor,
                target=TargetRef(type="task", id=task.task_id),
                visibility="agents_only",
                payload=task.model_dump(mode="json"),
                timestamp=timestamp,
                correlation_id=task.correlation_id,
                causation_id=message.message_id,
            )
        )
        return review

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, object] | None:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip().startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                payload = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                return None
        return payload if isinstance(payload, dict) else None

    @classmethod
    def _publication_review_decision_from_result(
        cls,
        result: AgentRunResult,
    ) -> dict[str, object] | None:
        if not result.message:
            return None
        payload = cls._extract_json_object(result.message)
        if payload is None:
            return None
        decision = payload.get("decision")
        relatedness = payload.get("relatedness", "unknown")
        confidence = payload.get("confidence")
        reason = payload.get("reason")
        issuer_explanation = payload.get("issuer_explanation")
        if decision not in {"allow", "block", "suppress", "flag"}:
            return None
        if decision == "block":
            decision = "suppress"
        if relatedness not in {
            "direct",
            "adjacent",
            "unrelated",
            "blocked_topic",
            "unknown",
        }:
            relatedness = "unknown"
        if isinstance(confidence, bool) or not isinstance(confidence, int | float):
            confidence = None
        elif confidence < 0 or confidence > 1:
            confidence = None
        return {
            "decision": decision,
            "relatedness": relatedness,
            "confidence": float(confidence) if confidence is not None else None,
            "reason": reason.strip() if isinstance(reason, str) and reason.strip() else None,
            "issuer_explanation": (
                issuer_explanation.strip()
                if isinstance(issuer_explanation, str)
                and issuer_explanation.strip()
                else None
            ),
        }

    async def _apply_publication_review_result(
        self,
        completion: RunCommandResult,
        result: AgentRunResult,
    ) -> tuple[list[EventEnvelope], list[TimelineMessage]]:
        # Publication reviews are intentionally generic: the reviewer may be Anchor
        # today, but the state transition only depends on the review record,
        # task metadata, and the response contract result.
        task = completion.task
        run = completion.run
        if task is None or run is None:
            return [], []
        review_id = self._metadata_uuid(task.metadata, "publication_review_id")
        if review_id is None:
            review_id = self._metadata_uuid(task.metadata, "moderation_review_id")
        if review_id is None:
            return [], []
        review = await self._repository.fetch_publication_review(review_id)
        if review is None:
            return [], []
        message = await self._repository.fetch_message(review.message_id)
        if message is None:
            return [], []
        thread = await self._repository.fetch_thread(review.thread_id)
        if thread is None:
            return [], []
        workspace = await self._repository.fetch_workspace(review.workspace_id)
        if workspace is None:
            return [], []
        candidate_participant = await self._repository.fetch_participant(
            review.workspace_id,
            review.candidate_actor_participant_id,
        )
        if candidate_participant is None:
            return [], []

        now = self._now()
        parsed = self._publication_review_decision_from_result(result)
        if parsed is None:
            failed_review = review.model_copy(
                update={
                    "status": "failed",
                    "reason": "Review response did not match the moderation response contract.",
                    "updated_at": now,
                    "completed_at": now,
                    "metadata": {
                        **review.metadata,
                        "stop_reason": result.stop_reason,
                        "contract_error": True,
                    },
                }
            )
            async with self._repository._pool.acquire() as conn:  # noqa: SLF001
                async with conn.transaction():
                    await self._repository.upsert_publication_review(conn, failed_review)
                    event = await self._build_thread_event(
                        conn,
                        review.workspace_id,
                        review.thread_id,
                        "message.publication_review_failed",
                        actor=ActorRef(type="agent", id=run.participant_id),
                        target=TargetRef(type="message", id=review.message_id),
                        visibility="agents_only",
                        payload=failed_review.model_dump(mode="json"),
                        timestamp=now,
                        correlation_id=task.correlation_id,
                        causation_id=task.task_id,
                    )
                    await self._repository.record_event(conn, event)
            return [event], []

        decision = str(parsed["decision"])
        if review.phase == "post_publish" and decision == "suppress":
            decision = "flag"
        if review.phase == "pre_publish" and decision == "flag":
            decision = "suppress"

        review_status = {
            "allow": "approved",
            "suppress": "suppressed",
            "flag": "flagged",
        }[decision]
        completed_review = review.model_copy(
            update={
                "status": review_status,
                "decision": decision,
                "relatedness": parsed["relatedness"],
                "confidence": parsed["confidence"],
                "reason": parsed["reason"],
                "issuer_explanation": parsed["issuer_explanation"],
                "updated_at": now,
                "completed_at": now,
                "metadata": {
                    **review.metadata,
                    "completed_run_id": str(run.run_id),
                    "stop_reason": result.stop_reason,
                },
            }
        )
        updated_message_metadata = {
            **message.metadata,
            "moderation_status": review_status,
            "publication_review_status": review_status,
            "moderation_review_id": str(review.review_id),
            "publication_review_id": str(review.review_id),
            "publication_review_kind": review.review_kind,
            "moderation_decision": decision,
            "publication_review_decision": decision,
            "moderation_relatedness": parsed["relatedness"],
            "moderation_confidence": parsed["confidence"],
            "moderation_reason": parsed["reason"],
            "publication_review_reason": parsed["reason"],
        }

        events: list[EventEnvelope] = []
        messages_to_persist: list[TimelineMessage] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_publication_review(conn, completed_review)
                if review.phase == "pre_publish" and decision == "allow":
                    # Strict pre-publication approval is the first moment this
                    # message becomes part of the public timeline and JSONL log.
                    approved_message = message.model_copy(
                        update={
                            "status": "completed",
                            "sequence": await self._repository.next_thread_sequence(
                                conn,
                                message.thread_id,
                            ),
                            "updated_at": now,
                            "metadata": updated_message_metadata,
                        }
                    )
                    tool_generation_request = (
                        await self._build_tool_generation_request_for_message(
                            thread=thread,
                            actor_input=self._participant_input_from_profile(
                                candidate_participant
                            ),
                            participant=candidate_participant,
                            content=approved_message.content,
                            metadata=dict(approved_message.metadata),
                            timestamp=now,
                        )
                    )
                    if tool_generation_request is not None:
                        tool_generation_request = tool_generation_request.model_copy(
                            update={"requester_message_id": approved_message.message_id}
                        )
                        approved_message = approved_message.model_copy(
                            update={
                                "metadata": {
                                    **approved_message.metadata,
                                    "tool_generation_request_id": str(
                                        tool_generation_request.request_id
                                    ),
                                    "tool_generation_request_status": (
                                        tool_generation_request.status
                                    ),
                                }
                            }
                        )
                        await self._repository.upsert_tool_generation_request(
                            conn,
                            tool_generation_request,
                        )
                    await self._repository.upsert_message(conn, approved_message)
                    events.append(
                        EventEnvelope(
                            event_type="message.created",
                            workspace_id=approved_message.workspace_id,
                            thread_id=approved_message.thread_id,
                            actor=approved_message.actor,
                            target=TargetRef(
                                type="message",
                                id=approved_message.message_id,
                            ),
                            visibility=approved_message.visibility,
                            correlation_id=approved_message.correlation_id,
                            causation_id=review.review_id,
                            sequence=approved_message.sequence,
                            timestamp=now,
                            payload=approved_message.model_dump(mode="json"),
                        )
                    )
                    if tool_generation_request is not None:
                        events.append(
                            await self._build_thread_event(
                                conn,
                                approved_message.workspace_id,
                                approved_message.thread_id,
                                "tool_generation_request.created",
                                actor=approved_message.actor,
                                target=TargetRef(
                                    type="tool_generation_request",
                                    id=tool_generation_request.request_id,
                                ),
                                visibility=approved_message.visibility,
                                payload=tool_generation_request.model_dump(mode="json"),
                                timestamp=now,
                                correlation_id=approved_message.correlation_id,
                                causation_id=approved_message.message_id,
                            )
                        )
                    if approved_message.metadata.get(
                        "publication_original_create_task",
                        approved_message.metadata.get("moderation_original_create_task"),
                    ):
                        actor_input = self._participant_input_from_profile(
                            candidate_participant
                        )
                        for followup_task in await self._build_message_tasks(
                            thread=thread,
                            message=approved_message,
                            actor_input=actor_input,
                            visibility=approved_message.visibility,
                            timestamp=now,
                        ):
                            await self._repository.upsert_task(conn, followup_task)
                            events.append(
                                EventEnvelope(
                                    event_type="task.created",
                                    workspace_id=approved_message.workspace_id,
                                    thread_id=approved_message.thread_id,
                                    actor=approved_message.actor,
                                    target=TargetRef(
                                        type="task",
                                        id=followup_task.task_id,
                                    ),
                                    visibility="agents_only",
                                    correlation_id=approved_message.correlation_id,
                                    causation_id=approved_message.message_id,
                                    sequence=await self._repository.next_thread_sequence(
                                        conn,
                                        approved_message.thread_id,
                                    ),
                                    timestamp=now,
                                    payload=followup_task.model_dump(mode="json"),
                                )
                            )
                    original_requests = approved_message.metadata.get(
                        "publication_original_requests",
                        approved_message.metadata.get("moderation_original_requests"),
                    )
                    if isinstance(original_requests, list):
                        request_payloads = [
                            CreateInteractionRequest.model_validate(item)
                            for item in original_requests
                            if isinstance(item, dict)
                        ]
                        if request_payloads:
                            interaction_result = await self._create_interaction_requests_in_transaction(
                                conn,
                                thread=thread,
                                actor_input=self._participant_input_from_profile(
                                    candidate_participant
                                ),
                                requests=request_payloads,
                                timestamp=now,
                                correlation_id=approved_message.correlation_id,
                                requester_message=approved_message,
                            )
                            for rendered_message in interaction_result.messages:
                                await self._repository.upsert_message(conn, rendered_message)
                                events.append(
                                    EventEnvelope(
                                        event_type="message.created",
                                        workspace_id=rendered_message.workspace_id,
                                        thread_id=rendered_message.thread_id,
                                        actor=rendered_message.actor,
                                        target=TargetRef(
                                            type="message",
                                            id=rendered_message.message_id,
                                        ),
                                        visibility=rendered_message.visibility,
                                        correlation_id=rendered_message.correlation_id,
                                        causation_id=rendered_message.causation_id,
                                        sequence=rendered_message.sequence,
                                        timestamp=now,
                                        payload=rendered_message.model_dump(mode="json"),
                                    )
                                )
                            events.extend(interaction_result.events)
                            messages_to_persist.extend(interaction_result.messages)
                    events.append(
                        await self._build_thread_event(
                            conn,
                            approved_message.workspace_id,
                            approved_message.thread_id,
                            "message.publication_approved",
                            actor=ActorRef(type="agent", id=run.participant_id),
                            target=TargetRef(
                                type="message",
                                id=approved_message.message_id,
                            ),
                            visibility="agents_only",
                            payload=completed_review.model_dump(mode="json"),
                            timestamp=now,
                            correlation_id=task.correlation_id,
                            causation_id=task.task_id,
                        )
                    )
                    messages_to_persist.insert(0, approved_message)
                elif review.phase == "pre_publish":
                    # Suppressed messages remain durable for audit/review state,
                    # but stay out of timeline queries and communication logs.
                    rejected_message = message.model_copy(
                        update={
                            "status": "rejected",
                            "updated_at": now,
                            "metadata": updated_message_metadata,
                        }
                    )
                    await self._repository.upsert_message(conn, rejected_message)
                    events.append(
                        await self._build_thread_event(
                            conn,
                            rejected_message.workspace_id,
                            rejected_message.thread_id,
                            "message.publication_suppressed",
                            actor=ActorRef(type="agent", id=run.participant_id),
                            target=TargetRef(
                                type="message",
                                id=rejected_message.message_id,
                            ),
                            visibility="agents_only",
                            payload=completed_review.model_dump(mode="json"),
                            timestamp=now,
                            correlation_id=task.correlation_id,
                            causation_id=task.task_id,
                        )
                    )
                    policy = self._workspace_moderation_policy(workspace)
                    if policy.explain_blocked_messages:
                        explanation = (
                            completed_review.issuer_explanation
                            or completed_review.reason
                            or "This message was blocked by the workspace publication policy."
                        )
                        explanation_message = TimelineMessage(
                            message_id=uuid4(),
                            workspace_id=rejected_message.workspace_id,
                            thread_id=rejected_message.thread_id,
                            actor=ActorRef(type="agent", id=run.participant_id),
                            visibility="private",
                            content=explanation,
                            status="completed",
                            correlation_id=rejected_message.correlation_id,
                            causation_id=rejected_message.message_id,
                            sequence=await self._repository.next_thread_sequence(
                                conn,
                                rejected_message.thread_id,
                            ),
                            created_at=now,
                            updated_at=now,
                            metadata={
                                "publication_review_id": str(review.review_id),
                                "publication_suppression_reason": "workspace_topic_alignment",
                                "recipient_participant_id": str(
                                    candidate_participant.participant_id
                                ),
                                "moderation_review_id": str(review.review_id),
                            },
                        )
                        await self._repository.upsert_message(conn, explanation_message)
                        events.append(
                            EventEnvelope(
                                event_type="message.created",
                                workspace_id=explanation_message.workspace_id,
                                thread_id=explanation_message.thread_id,
                                actor=explanation_message.actor,
                                target=TargetRef(
                                    type="participant",
                                    id=candidate_participant.participant_id,
                                ),
                                visibility="private",
                                correlation_id=explanation_message.correlation_id,
                                causation_id=explanation_message.causation_id,
                                sequence=explanation_message.sequence,
                                timestamp=now,
                                payload=explanation_message.model_dump(mode="json"),
                            )
                        )
                else:
                    # Post-publication reviews never retract the message. They
                    # annotate it and fan out a flag/approval event instead.
                    flagged_message = message.model_copy(
                        update={
                            "status": "completed",
                            "updated_at": now,
                            "metadata": updated_message_metadata,
                        }
                    )
                    await self._repository.upsert_message(conn, flagged_message)
                    events.append(
                        await self._build_thread_event(
                            conn,
                            flagged_message.workspace_id,
                            flagged_message.thread_id,
                            (
                                "message.publication_flagged"
                                if decision == "flag"
                                else "message.publication_approved"
                            ),
                            actor=ActorRef(type="agent", id=run.participant_id),
                            target=TargetRef(
                                type="message",
                                id=flagged_message.message_id,
                            ),
                            visibility="workspace" if decision == "flag" else "agents_only",
                            payload=completed_review.model_dump(mode="json"),
                            timestamp=now,
                            correlation_id=task.correlation_id,
                            causation_id=task.task_id,
                        )
                    )
                for event in events:
                    await self._repository.record_event(conn, event)
        return events, messages_to_persist

    @classmethod
    def _run_output_from_result(cls, result: AgentRunResult) -> dict[str, object]:
        payload = result.model_dump(mode="json")
        usage = cls._run_usage_from_result(result)
        if usage is not None:
            payload["usage"] = usage
        return payload

    @staticmethod
    def _run_usage_from_result(result: AgentRunResult) -> dict[str, object] | None:
        raw = result.metadata.get("usage")
        if not isinstance(raw, dict):
            return None

        def _usage_int(name: str) -> int | None:
            value = raw.get(name)
            if isinstance(value, bool):
                return None
            if isinstance(value, int):
                return value
            return None

        provider = raw.get("provider")
        model = raw.get("model")
        usage = {
            "provider": provider if isinstance(provider, str) else None,
            "model": model if isinstance(model, str) else None,
            "prompt_tokens": _usage_int("prompt_tokens"),
            "completion_tokens": _usage_int("completion_tokens"),
            "total_tokens": _usage_int("total_tokens"),
        }
        if all(value is None for value in usage.values()):
            return None
        return usage

    @staticmethod
    def _stop_reason_returns_to_thread(stop_reason: StopReason) -> bool:
        return stop_reason in {
            "completed",
            "needs_user_input",
            "blocked_dependency",
            "handoff_required",
            "budget_exhausted",
            "tool_failure",
        }

    async def _finalize_tool_call(
        self,
        tool_call_id: UUID,
        worker_id: str,
        *,
        status: str,
        result: ToolCallResult,
        error: str | None,
        event_type: str,
    ) -> ToolCallCommandResult:
        tool_call = await self._repository.fetch_tool_call(tool_call_id)
        if tool_call is None:
            raise KeyError(f"Tool call {tool_call_id} not found")
        if tool_call.claimed_by_worker != worker_id:
            raise ValueError(
                f"Tool call {tool_call_id} is not claimed by worker {worker_id}"
            )
        step = await self._repository.fetch_run_step(tool_call.run_step_id)
        run = await self._repository.fetch_run(tool_call.run_id)
        task = await self._repository.fetch_task(tool_call.task_id)
        if step is None or run is None or task is None:
            raise KeyError(f"Tool call {tool_call_id} is missing execution state")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=tool_call.system_agent_id,
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        now = self._now()
        updated_tool_call = tool_call.model_copy(
            update={
                "status": status,
                "error": error,
                "result": result,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "finished_at": now,
                "updated_at": now,
            }
        )
        next_step: RunStep | None = None
        completion_event: EventEnvelope | None = None
        verification_events: list[EventEnvelope] = []
        verification_messages: list[TimelineMessage] = []
        is_tool_generation_verification = bool(
            tool_call.metadata.get("tool_generation_approval_verification")
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_tool_call(conn, updated_tool_call)
                completion_event = await self._build_thread_event(
                    conn,
                    task.workspace_id,
                    task.thread_id,
                    event_type,
                    actor=actor,
                    target=TargetRef(type="tool_call", id=tool_call_id),
                    payload=updated_tool_call.model_dump(mode="json"),
                    visibility="agents_only",
                    timestamp=now,
                    correlation_id=run.correlation_id,
                    causation_id=task.task_id,
                )
                await self._repository.record_event(conn, completion_event)
                remaining = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM tool_calls
                    WHERE run_step_id = $1
                      AND status NOT IN ('completed', 'failed')
                    """,
                    step.step_id,
                )
                step_status = await conn.fetchval(
                    """
                    SELECT status
                    FROM run_steps
                    WHERE step_id = $1
                    FOR UPDATE
                    """,
                    step.step_id,
                )
                if remaining == 0 and step_status == "waiting_tools":
                    step = step.model_copy(
                        update={
                            "status": "completed",
                            "lease_expires_at": None,
                            "last_heartbeat_at": None,
                            "next_retry_at": None,
                            "claimed_by_worker": None,
                            "execution_handle": None,
                            "finished_at": now,
                            "updated_at": now,
                        }
                    )
                    await self._repository.upsert_run_step(conn, step)
                    if not is_tool_generation_verification:
                        next_step = RunStep(
                            step_id=uuid4(),
                            run_id=step.run_id,
                            task_id=step.task_id,
                            workspace_id=step.workspace_id,
                            thread_id=step.thread_id,
                            system_agent_id=step.system_agent_id,
                            step_index=step.step_index + 1,
                            status="created",
                            submitted_at=now,
                            created_at=now,
                            updated_at=now,
                            metadata=step.metadata,
                        )
                        await self._repository.upsert_run_step(conn, next_step)
        if is_tool_generation_verification:
            verification_events, verification_messages = (
                await self._handle_tool_generation_verification_completion(
                    tool_call=updated_tool_call,
                    run=run,
                    task=task,
                    status=status,
                    result=result,
                    error=error,
                )
            )
        if verification_messages:
            await self._persist_workspace_communication_messages(verification_messages)

        return ToolCallCommandResult(
            tool_call=updated_tool_call,
            step=next_step or step,
            run=run,
            task=task,
            events=([completion_event] if completion_event is not None else []) + verification_events,
        )

    def _build_tool_execution_spec(
        self,
        *,
        tool: WorkspaceTool | AgentInternalToolBinding,
        draft: AgentToolCallDraft,
        workspace_id: UUID,
    ) -> ExecutionSpec:
        self._validate_tool_execution_binding(tool.execution)
        profile = dict(tool.execution.execution_profile)
        return ExecutionSpec(
            invocation_id=uuid4(),
            handler_ref=tool.execution.handler_ref or tool.name,
            inline_payload=draft.arguments,
            artifact_refs=draft.artifact_refs,
            execution_workspace=(
                draft.execution_workspace
                if draft.execution_workspace is not None
                else self._execution_workspace_for_workspace(workspace_id)
            ),
            limits=ExecutionLimits(
                timeout_seconds=int(profile.get("timeout_seconds", 60)),
                cpu_millis=profile.get("cpu_millis"),
                memory_mb=profile.get("memory_mb"),
                pids_limit=profile.get("pids_limit"),
                network=profile.get("network", "none"),
                workspace_access=profile.get("workspace_access", "read_only"),
            ),
            env_refs=draft.env_refs,
            result_sink=draft.result_sink,
            profile=profile,
            metadata={
                "tool_id": str(tool.tool_id),
                "tool_name": tool.name,
                "backend_kind": tool.execution.backend_kind,
            },
        )

    def _build_mcp_tool_execution_spec(
        self,
        *,
        tool: WorkspaceMcpTool,
        draft: AgentToolCallDraft,
        workspace_id: UUID,
        system_agent_id: UUID,
        source: str = "mcp_server",
    ) -> ExecutionSpec:
        return ExecutionSpec(
            invocation_id=uuid4(),
            handler_ref=tool.remote_name,
            inline_payload=draft.arguments,
            artifact_refs=draft.artifact_refs,
            execution_workspace=(
                draft.execution_workspace
                if draft.execution_workspace is not None
                else self._execution_workspace_for_workspace(workspace_id)
            ),
            limits=ExecutionLimits(timeout_seconds=60, network="full", workspace_access="none"),
            env_refs=draft.env_refs,
            result_sink=draft.result_sink,
            profile={"workspace_access": "none", "network": "full"},
            metadata={
                "tool_source": source,
                "backend_kind": "mcp",
                "mcp_server_id": str(tool.server_id),
                "mcp_server_key": tool.server_key,
                "mcp_tool_name": tool.remote_name,
                "mcp_workspace_attachment_metadata": tool.metadata.get(
                    "workspace_attachment",
                    {},
                ),
                "tool_name": tool.exposed_name,
                "system_agent_id": str(system_agent_id),
                "workspace_id": str(workspace_id),
            },
        )

    @staticmethod
    def _execution_workspace_for_workspace(workspace_id: UUID) -> ExecutionWorkspaceRef:
        return ExecutionWorkspaceRef(
            mode="local_path",
            workspace_id=workspace_id,
        )

    @staticmethod
    def _artifact_from_draft(
        draft: AgentArtifactDraft,
        *,
        task: Task,
        run: Run,
        timestamp: datetime,
    ) -> Artifact:
        return Artifact(
            artifact_id=uuid4(),
            workspace_id=task.workspace_id,
            thread_id=task.thread_id,
            task_id=task.task_id,
            run_id=run.run_id,
            kind=draft.kind,
            title=draft.title,
            content=draft.content,
            visibility=draft.visibility,
            correlation_id=task.correlation_id,
            created_at=timestamp,
            updated_at=timestamp,
            metadata=draft.metadata,
        )

    @staticmethod
    def _agent_message_from_result(
        result: AgentRunResult,
        *,
        task: Task,
        participant: ParticipantProfile,
        timestamp: datetime,
    ) -> TimelineMessage:
        routing = CollaborationKernel._task_routing(task)
        return TimelineMessage(
            message_id=uuid4(),
            workspace_id=task.workspace_id,
            thread_id=task.thread_id,
            actor=ActorRef(type="agent", id=participant.participant_id),
            visibility=routing.response_visibility,
            content=result.message or "",
            status="completed",
            correlation_id=task.correlation_id,
            causation_id=task.task_id,
            sequence=0,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "system_agent_id": str(participant.system_agent_id)
                if participant.system_agent_id is not None
                else None,
                "stop_reason": result.stop_reason,
                "summary": result.summary,
                **result.metadata,
            },
        )

    async def _build_workspace_event(
        self,
        conn: asyncpg.Connection,
        workspace_id: UUID,
        event_type: str,
        *,
        actor: ActorRef,
        target: TargetRef,
        payload: dict,
        visibility: str = "workspace",
        timestamp: datetime,
    ) -> EventEnvelope:
        sequence = await self._repository.next_workspace_sequence(conn, workspace_id)
        return EventEnvelope(
            event_type=event_type,
            workspace_id=workspace_id,
            actor=actor,
            target=target,
            visibility=visibility,
            sequence=sequence,
            timestamp=timestamp,
            payload=payload,
        )

    async def _build_thread_event(
        self,
        conn: asyncpg.Connection,
        workspace_id: UUID,
        thread_id: UUID,
        event_type: str,
        *,
        actor: ActorRef,
        target: TargetRef,
        payload: dict,
        visibility: str = "public",
        timestamp: datetime,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
    ) -> EventEnvelope:
        sequence = await self._repository.next_thread_sequence(conn, thread_id)
        return EventEnvelope(
            event_type=event_type,
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=actor,
            target=target,
            visibility=visibility,
            correlation_id=correlation_id or uuid4(),
            causation_id=causation_id,
            sequence=sequence,
            timestamp=timestamp,
            payload=payload,
        )

    @staticmethod
    def _actor_from_input(actor: ParticipantInput) -> ActorRef:
        return ActorRef(type=actor.participant_type, id=actor.participant_id)

    @staticmethod
    def _participant_profile(
        *,
        workspace_id: UUID,
        actor: ParticipantInput,
        now: datetime,
        status: str = "active",
        existing: ParticipantProfile | None = None,
    ) -> ParticipantProfile:
        roles = list(actor.roles) if actor.roles else list(existing.roles if existing is not None else [])
        capabilities = (
            list(actor.capabilities)
            if actor.capabilities
            else list(existing.capabilities if existing is not None else [])
        )
        description = actor.description if actor.description is not None else (
            existing.description if existing is not None else None
        )
        if actor.participant_type == "user":
            user_id = actor.user_id if actor.user_id is not None else (
                existing.user_id if existing is not None else None
            )
        else:
            user_id = None
        visibility_scope = actor.visibility_scope
        if (
            existing is not None
            and actor.visibility_scope == "workspace"
            and existing.visibility_scope != "workspace"
        ):
            visibility_scope = existing.visibility_scope
        return ParticipantProfile(
            participant_id=actor.participant_id,
            workspace_id=workspace_id,
            participant_type=actor.participant_type,
            user_id=user_id,
            system_agent_id=existing.system_agent_id if existing is not None else None,
            display_name=actor.display_name,
            description=description,
            roles=roles,
            capabilities=capabilities,
            status=status,
            visibility_scope=visibility_scope,
            agent_config=existing.agent_config if existing is not None else None,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            metadata=dict(existing.metadata) if existing is not None else {},
        )

    async def _participant_profile_for_actor(
        self,
        *,
        workspace_id: UUID,
        actor: ParticipantInput,
        now: datetime,
        status: str = "active",
    ) -> ParticipantProfile:
        if actor.participant_type == "user":
            await self._require_workspace_user_membership(workspace_id, actor)
        existing = await self._repository.fetch_participant(workspace_id, actor.participant_id)
        return self._participant_profile(
            workspace_id=workspace_id,
            actor=actor,
            now=now,
            status=status,
            existing=existing,
        )

    @staticmethod
    def _with_agent_metadata(participant: ParticipantProfile) -> ParticipantProfile:
        return participant

    async def _ensure_participant_identity(
        self,
        conn: asyncpg.Connection,
        participant: ParticipantProfile,
    ) -> None:
        if participant.participant_type != "user" or participant.user_id is None:
            return
        await self._repository.upsert_user(
            conn,
            UserRecord(
                user_id=participant.user_id,
                display_name=participant.display_name,
                created_at=participant.created_at,
                updated_at=participant.updated_at,
                metadata={},
            ),
        )

    async def resolve_authenticated_user_actor(
        self,
        workspace_id: UUID,
        *,
        user_id: UUID,
        display_name: str,
        auto_create: bool = True,
    ) -> ParticipantInput:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if (
            workspace is not None
            and workspace.organization_id is not None
            and hasattr(self._repository, "fetch_organization_membership")
        ):
            membership = await self._repository.fetch_organization_membership(
                workspace.organization_id,
                user_id,
            )
            if membership is None:
                raise KeyError(
                    f"Authenticated user {user_id} is not a member of organization {workspace.organization_id}"
                )
        participant = await self._repository.fetch_user_participant(workspace_id, user_id)
        if participant is None and not auto_create:
            raise KeyError(
                f"Authenticated user {user_id} is not attached to workspace {workspace_id}"
            )
        participant_id = participant.participant_id if participant is not None else uuid4()
        return ParticipantInput(
            participant_id=participant_id,
            participant_type="user",
            user_id=user_id,
            display_name=display_name,
        )

    @staticmethod
    def _actor_user_id(actor: ParticipantInput) -> UUID | None:
        if actor.user_id is not None:
            return actor.user_id
        if actor.participant_type == "user":
            return actor.participant_id
        return None

    @staticmethod
    def _actor_system_agent_id(actor: ParticipantInput) -> UUID | None:
        if actor.participant_type == "agent":
            return actor.participant_id
        return None

    @staticmethod
    def _actor_project_subject(actor: ParticipantInput) -> ProjectSubjectRef:
        if actor.participant_type == "agent":
            return ProjectSubjectRef(system_agent_id=actor.participant_id)
        return ProjectSubjectRef(
            user_id=CollaborationKernel._actor_user_id(actor) or actor.participant_id
        )

    @staticmethod
    def _project_access_binding(
        project_id: UUID,
        subject: ProjectSubjectRef,
        role: ProjectAccessRole,
        *,
        now: datetime,
        metadata: dict[str, object] | None = None,
    ) -> ProjectAccessBinding:
        return ProjectAccessBinding(
            project_id=project_id,
            subject_type="agent" if subject.system_agent_id is not None else "user",
            user_id=subject.user_id,
            system_agent_id=subject.system_agent_id,
            role=role,
            created_at=now,
            updated_at=now,
            metadata=dict(metadata or {}),
        )

    @staticmethod
    def _project_subject_key(subject: ProjectSubjectRef) -> tuple[str, UUID]:
        if subject.system_agent_id is not None:
            return ("agent", subject.system_agent_id)
        assert subject.user_id is not None
        return ("user", subject.user_id)

    @staticmethod
    def _project_subject_matches(
        subject: ProjectSubjectRef,
        *,
        user_id: UUID | None,
        system_agent_id: UUID | None,
    ) -> bool:
        return (
            (subject.user_id is not None and subject.user_id == user_id)
            or (
                subject.system_agent_id is not None
                and subject.system_agent_id == system_agent_id
            )
        )

    @staticmethod
    def _project_access_bindings_for_create(
        project_id: UUID,
        *,
        owner: ProjectSubjectRef,
        creator: ProjectSubjectRef,
        owners: list[ProjectSubjectRef],
        editors: list[ProjectSubjectRef],
        viewers: list[ProjectSubjectRef],
        now: datetime,
    ) -> list[ProjectAccessBinding]:
        role_rank: dict[ProjectAccessRole, int] = {
            "viewer": 0,
            "editor": 1,
            "owner": 2,
            "creator": 3,
        }
        subjects: dict[tuple[str, UUID], tuple[ProjectSubjectRef, ProjectAccessRole]] = {}

        def add(subject: ProjectSubjectRef, role: ProjectAccessRole) -> None:
            key = CollaborationKernel._project_subject_key(subject)
            current = subjects.get(key)
            if current is None or role_rank[role] > role_rank[current[1]]:
                subjects[key] = (subject, role)

        for subject in viewers:
            add(subject, "viewer")
        for subject in editors:
            add(subject, "editor")
        for subject in owners:
            add(subject, "owner")
        add(owner, "owner")
        add(creator, "creator")
        return [
            CollaborationKernel._project_access_binding(
                project_id,
                subject,
                role,
                now=now,
                metadata={"created_with_project": True},
            )
            for subject, role in subjects.values()
        ]

    async def _fetch_project_access_for_actor(
        self,
        project_id: UUID,
        actor: ParticipantInput,
    ) -> ProjectAccessBinding | None:
        user_id = self._actor_user_id(actor)
        if user_id is not None and hasattr(self._repository, "fetch_project_access_for_user"):
            return await self._repository.fetch_project_access_for_user(
                project_id=project_id,
                user_id=user_id,
            )
        system_agent_id = self._actor_system_agent_id(actor)
        if system_agent_id is not None and hasattr(
            self._repository,
            "fetch_project_access_for_agent",
        ):
            return await self._repository.fetch_project_access_for_agent(
                project_id=project_id,
                system_agent_id=system_agent_id,
            )
        return None

    async def _require_project_permission(
        self,
        project_id: UUID,
        actor: ParticipantInput,
        *,
        permission: str,
    ) -> ProjectAccessBinding:
        binding = await self._fetch_project_access_for_actor(project_id, actor)
        effective_permissions = PROJECT_ROLE_BASE_PERMISSIONS.get(binding.role, ()) if binding else ()
        if binding is None or permission not in effective_permissions:
            raise PermissionError(
                f"Project {project_id} requires project permission {permission!r}"
            )
        return binding

    async def _require_workspace_user_membership(
        self,
        workspace_id: UUID,
        actor: ParticipantInput,
    ) -> None:
        user_id = self._actor_user_id(actor)
        if user_id is None:
            return
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        if workspace.organization_id is None or not hasattr(
            self._repository,
            "fetch_organization_membership",
        ):
            return
        membership = await self._repository.fetch_organization_membership(
            workspace.organization_id,
            user_id,
        )
        if membership is None:
            raise PermissionError(
                f"User {user_id} is not a member of organization {workspace.organization_id}"
            )

    async def _require_organization_membership(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> OrganizationMembership:
        if not hasattr(self._repository, "fetch_organization_membership"):
            now = self._now()
            return OrganizationMembership(
                organization_id=organization_id,
                user_id=user_id,
                role="owner",
                joined_at=now,
                updated_at=now,
                metadata={},
            )
        membership = await self._repository.fetch_organization_membership(
            organization_id,
            user_id,
        )
        if membership is None:
            raise KeyError(
                f"User {user_id} is not a member of organization {organization_id}"
            )
        return membership

    async def _require_organization_admin(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> OrganizationMembership:
        membership = await self._require_organization_membership(organization_id, user_id)
        if membership.role not in _ORGANIZATION_ADMIN_ROLES and not await self._human_has_organization_permission(
            organization_id,
            user_id,
            "organization.members.write",
        ):
            raise PermissionError("Organization admin role required")
        return membership

    async def _require_organization_permission(
        self,
        organization_id: UUID,
        user_id: UUID,
        permission: str,
    ) -> OrganizationMembership:
        membership = await self._require_organization_membership(organization_id, user_id)
        if permission in ORGANIZATION_ROLE_BASE_PERMISSIONS.get(membership.role, ()):
            return membership
        if await self._human_has_organization_permission(organization_id, user_id, permission):
            return membership
        raise PermissionError(f"Organization permission {permission!r} required")

    async def _resolve_workspace_location(
        self,
        *,
        requested_organization_id: UUID | None,
        requested_project_id: UUID | None,
        actor: ParticipantInput,
    ) -> tuple[Organization, Project, bool]:
        if requested_project_id is not None:
            if not hasattr(self._repository, "fetch_project"):
                raise ValueError("project_id is not supported by this repository")
            project = await self._repository.fetch_project(requested_project_id)
            if project is None:
                raise KeyError(f"Project {requested_project_id} not found")
            if (
                requested_organization_id is not None
                and project.organization_id != requested_organization_id
            ):
                raise KeyError(
                    f"Project {requested_project_id} not found in organization {requested_organization_id}"
                )
            organization = await self._repository.fetch_organization(project.organization_id)
            if organization is None:
                raise KeyError(f"Organization {project.organization_id} not found")
            return organization, project, False

        organization = await self._resolve_workspace_organization(
            requested_organization_id=requested_organization_id,
            actor=actor,
        )
        project, requires_upsert = await self._resolve_default_project(organization, actor)
        return organization, project, requires_upsert

    async def _resolve_workspace_organization(
        self,
        *,
        requested_organization_id: UUID | None,
        actor: ParticipantInput,
    ) -> Organization:
        if requested_organization_id is not None:
            organization = await self._repository.fetch_organization(requested_organization_id)
            if organization is None:
                raise KeyError(f"Organization {requested_organization_id} not found")
            return organization
        if not hasattr(self._repository, "list_organizations_for_user"):
            return Organization(
                organization_id=UUID("11111111-1111-1111-1111-111111111111"),
                slug="default",
                name="Default Organization",
                description="Implicit test organization",
                created_by=self._actor_user_id(actor) or actor.participant_id,
                created_at=self._now(),
                updated_at=self._now(),
                metadata={},
            )
        user_id = self._actor_user_id(actor)
        organizations = (
            await self._repository.list_organizations_for_user(user_id)
            if user_id is not None
            else await self._repository.list_organizations()
        )
        if len(organizations) == 1:
            return organizations[0]
        raise ValueError("organization_id is required when multiple organizations are available")

    async def _resolve_default_project(
        self,
        organization: Organization,
        actor: ParticipantInput,
    ) -> tuple[Project, bool]:
        if hasattr(self._repository, "fetch_default_project"):
            project = await self._repository.fetch_default_project(organization.organization_id)
            if project is not None:
                return project, False
        return self._default_project_for_organization(
            organization,
            actor=actor,
            now=self._now(),
        ), True

    @staticmethod
    def _default_project_for_organization(
        organization: Organization,
        *,
        actor: ParticipantInput,
        now: datetime,
    ) -> Project:
        subject = CollaborationKernel._actor_project_subject(actor)
        return managed_default_project_for_organization(
            organization,
            created_by=CollaborationKernel._actor_user_id(actor) or actor.participant_id,
            creator_user_id=subject.user_id,
            creator_system_agent_id=subject.system_agent_id,
            owner_user_id=subject.user_id,
            owner_system_agent_id=subject.system_agent_id,
            now=now,
        )

    @staticmethod
    def _administration_project_for_organization(
        organization: Organization,
        *,
        actor: ParticipantInput,
        now: datetime,
    ) -> Project:
        subject = CollaborationKernel._actor_project_subject(actor)
        return managed_administration_project_for_organization(
            organization,
            created_by=CollaborationKernel._actor_user_id(actor) or actor.participant_id,
            creator_user_id=subject.user_id,
            creator_system_agent_id=subject.system_agent_id,
            owner_user_id=subject.user_id,
            owner_system_agent_id=subject.system_agent_id,
            now=now,
        )

    @staticmethod
    def _operations_workspace_for_organization(
        organization: Organization,
        project: Project,
        *,
        now: datetime,
    ) -> Workspace:
        return managed_operations_workspace_for_organization(
            organization,
            project,
            now=now,
        )

    @staticmethod
    def _anchor_agent_definition(*, now: datetime) -> AgentDefinition:
        return managed_anchor_agent_definition(now=now)

    @staticmethod
    def _anchor_participant_for_workspace(
        workspace_id: UUID,
        *,
        now: datetime,
    ) -> ParticipantProfile:
        return managed_anchor_participant_for_workspace(workspace_id, now=now)

    async def _ensure_anchor_attached_for_workspace(
        self,
        conn: asyncpg.Connection,
        workspace_id: UUID,
        *,
        now: datetime,
    ) -> ParticipantProfile:
        return await managed_ensure_anchor_attached_for_workspace(
            self._repository,
            conn,
            workspace_id,
            now=now,
        )

    @staticmethod
    def _curator_agent_for_organization(
        organization: Organization,
        *,
        now: datetime,
    ) -> AgentDefinition:
        return managed_curator_agent_for_organization(organization, now=now)

    @staticmethod
    def _curator_iam_role_for_organization(
        organization_id: UUID,
        *,
        now: datetime,
    ) -> IamRoleDefinition:
        return managed_curator_iam_role_for_organization(organization_id, now=now)

    @staticmethod
    def _operations_participant_for_agent(
        *,
        workspace: Workspace,
        agent: AgentDefinition,
        now: datetime,
    ) -> ParticipantProfile:
        return managed_operations_participant_for_agent(
            workspace=workspace,
            agent=agent,
            now=now,
        )

    async def _organization_operations_workspace(
        self,
        organization_id: UUID,
    ) -> Workspace:
        workspaces = await self.list_workspaces(organization_id=organization_id)
        for workspace in workspaces:
            if (
                workspace.metadata.get("managed") is True
                and workspace.metadata.get("operations_workspace") is True
                and workspace.metadata.get("operations_level") == "organization"
            ):
                return workspace
        raise KeyError(
            "Managed Organization Operations workspace for "
            f"organization {organization_id} not found"
        )

    async def _ensure_operations_agent_participant(
        self,
        workspace: Workspace,
        agent: AgentDefinition,
        *,
        now: datetime,
    ) -> ParticipantProfile:
        participant = self._operations_participant_for_agent(
            workspace=workspace,
            agent=agent,
            now=now,
        )
        existing = await self._repository.fetch_agent_participant(
            workspace.workspace_id,
            agent.agent_id,
        )
        task_routing = agent.definition.get("task_routing")
        metadata = {
            **participant.metadata,
            **({"task_routing": task_routing} if isinstance(task_routing, dict) else {}),
        }
        if existing is None:
            return participant.model_copy(update={"metadata": metadata})
        return participant.model_copy(
            update={
                "participant_id": existing.participant_id,
                "created_at": existing.created_at,
                "metadata": {**existing.metadata, **metadata},
            }
        )

    async def _require_dossier_write_actor(
        self,
        dossier: ResearchDossier,
        actor: ParticipantInput,
    ) -> None:
        if actor.participant_type != "user":
            return
        user_id = self._actor_user_id(actor)
        if user_id is None:
            raise PermissionError("Methodology dossier writes require an authenticated user")
        await self._require_organization_permission(
            dossier.organization_id,
            user_id,
            "methodology.write",
        )

    async def _require_research_dossier_notebook(
        self,
        dossier_id: UUID,
    ) -> ResearchDossierNotebook:
        notebook = await self._repository.fetch_research_dossier_notebook_for_dossier(
            dossier_id
        )
        if notebook is None:
            raise KeyError(f"Research dossier notebook for {dossier_id} not found")
        return notebook

    async def _dossier_actor_system_agent_id(
        self,
        dossier: ResearchDossier,
        actor: ParticipantInput,
    ) -> UUID | None:
        if actor.participant_type != "agent" or dossier.operations_workspace_id is None:
            return None
        participant = await self._repository.fetch_participant(
            dossier.operations_workspace_id,
            actor.participant_id,
        )
        if participant is None or participant.participant_type != "agent":
            return None
        return participant.system_agent_id

    def _build_dossier_notebook_event(
        self,
        *,
        dossier: ResearchDossier,
        actor: ParticipantInput,
        system_agent_id: UUID | None,
        event_type: str,
        payload: dict[str, Any],
        now: datetime,
    ) -> ResearchDossierEvent:
        return ResearchDossierEvent(
            event_id=uuid4(),
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            event_type=event_type,
            actor_participant_id=actor.participant_id,
            system_agent_id=system_agent_id,
            payload=payload,
            created_at=now,
        )

    async def _validate_dossier_note_refs(
        self,
        dossier: ResearchDossier,
        notebook: ResearchDossierNotebook,
        payload: UpsertResearchDossierNoteRequest,
    ) -> None:
        if payload.source_id is not None:
            source = await self._repository.fetch_research_dossier_source(
                payload.source_id
            )
            if source is None or source.dossier_id != dossier.dossier_id:
                raise KeyError(f"Research dossier source {payload.source_id} not found")
        if payload.concept_id is not None:
            concept = await self._repository.fetch_research_dossier_concept(
                payload.concept_id
            )
            if concept is None or concept.notebook_id != notebook.notebook_id:
                raise KeyError(f"Research dossier concept {payload.concept_id} not found")
        for note_id in payload.related_note_ids:
            note = await self._repository.fetch_research_dossier_note(note_id)
            if note is None or note.notebook_id != notebook.notebook_id:
                raise KeyError(f"Research dossier note {note_id} not found")

    async def _validate_dossier_graph_ref(
        self,
        notebook: ResearchDossierNotebook,
        node_type: str,
        ref_id: UUID,
    ) -> None:
        if node_type == "note":
            note = await self._repository.fetch_research_dossier_note(ref_id)
            if note is None or note.notebook_id != notebook.notebook_id:
                raise KeyError(f"Research dossier note {ref_id} not found")
            return
        if node_type == "concept":
            concept = await self._repository.fetch_research_dossier_concept(ref_id)
            if concept is None or concept.notebook_id != notebook.notebook_id:
                raise KeyError(f"Research dossier concept {ref_id} not found")
            return
        if node_type == "claim":
            claim = await self._repository.fetch_research_dossier_claim(ref_id)
            if claim is None or claim.notebook_id != notebook.notebook_id:
                raise KeyError(f"Research dossier claim {ref_id} not found")
            return
        if node_type == "source":
            source = await self._repository.fetch_research_dossier_source(ref_id)
            if source is None or source.dossier_id != notebook.dossier_id:
                raise KeyError(f"Research dossier source {ref_id} not found")
            return
        raise ValueError(f"Unsupported dossier graph node type {node_type!r}")

    async def _validate_research_dossier_source_refs(
        self,
        dossier: ResearchDossier,
        source: ResearchDossierSource,
    ) -> None:
        if source.library_id is not None:
            library = await self._repository.fetch_library(source.library_id)
            if library is None or library.organization_id != dossier.organization_id:
                raise KeyError(
                    f"Library {source.library_id} not found in "
                    f"organization {dossier.organization_id}"
                )
        if source.library_item_id is not None:
            item = await self._repository.fetch_library_item(source.library_item_id)
            if item is None:
                raise KeyError(f"Library item {source.library_item_id} not found")
            item_library = await self._repository.fetch_library(item.library_id)
            if (
                item_library is None
                or item_library.organization_id != dossier.organization_id
            ):
                raise KeyError(
                    f"Library item {source.library_item_id} not found in "
                    f"organization {dossier.organization_id}"
                )
            if source.library_id is not None and source.library_id != item.library_id:
                raise ValueError(
                    "Research dossier source library_id does not match library_item_id"
                )
        asset_id = source.asset_id
        if source.asset_version_id is not None:
            if asset_id is None:
                version = await self._repository.fetch_workspace_asset_version(
                    source.asset_version_id
                )
                if version is None:
                    raise KeyError(
                        f"Workspace asset version {source.asset_version_id} not found"
                    )
                asset_id = version.asset_id
            else:
                await self._resolve_asset_version_for_source(
                    asset_id=asset_id,
                    asset_version_id=source.asset_version_id,
                )
        if asset_id is not None:
            asset = await self._repository.fetch_workspace_asset(asset_id)
            if asset is None:
                raise KeyError(f"Workspace asset {asset_id} not found")
            if (
                asset.organization_id is not None
                and asset.organization_id != dossier.organization_id
            ):
                raise ValueError(
                    "Research dossier source asset belongs to a different organization"
                )
        for context_pack_id in source.context_pack_ids:
            context_pack = await self._repository.fetch_retrieval_context_pack(
                context_pack_id
            )
            if context_pack is None:
                raise KeyError(f"Retrieval context pack {context_pack_id} not found")
            if (
                context_pack.organization_id is not None
                and context_pack.organization_id != dossier.organization_id
            ):
                raise ValueError(
                    "Research dossier source context pack belongs to a different organization"
                )

    def _build_researcher_dossier_task(
        self,
        *,
        dossier: ResearchDossier,
        blueprint: MethodologyBlueprint,
        version: MethodologyBlueprintVersion,
        operations_workspace: Workspace,
        researcher_participant: ParticipantProfile,
        requested_by: UUID,
        now: datetime,
    ) -> Task:
        if dossier.thread_id is None:
            raise ValueError("Research dossier has no operations thread")
        if dossier.researcher_system_agent_id is None:
            raise ValueError("Research dossier has no Researcher system agent")
        return Task(
            task_id=uuid4(),
            workspace_id=operations_workspace.workspace_id,
            thread_id=dossier.thread_id,
            title=f"Build research dossier for {blueprint.title}",
            description=(
                "Discover, collect, triage, and organize evidence into a durable "
                "research dossier for a methodology blueprint version."
            ),
            requested_by=requested_by,
            visibility="agents_only",
            correlation_id=dossier.dossier_id,
            causation_id=version.version_id,
            created_at=now,
            updated_at=now,
            metadata={
                "target_system_agent_id": str(dossier.researcher_system_agent_id),
                "target_participant_id": str(researcher_participant.participant_id),
                "response_visibility": "agents_only",
                "routing_reason": METHODOLOGY_RESEARCH_DOSSIER_BUILD_TASK_KIND,
                "task_kind": METHODOLOGY_RESEARCH_DOSSIER_BUILD_TASK_KIND,
                "methodology_blueprint_id": str(blueprint.blueprint_id),
                "methodology_blueprint_version_id": str(version.version_id),
                "research_dossier_id": str(dossier.dossier_id),
                "retained_library_id": (
                    str(dossier.retained_library_id)
                    if dossier.retained_library_id is not None
                    else None
                ),
                "source_policy": version.source_policy,
                "selected_library_ids": [
                    str(item) for item in version.selected_library_ids
                ],
                "task_instructions": [
                    "Build a research dossier for the supplied topic and tasks.",
                    "Search local and selected organization libraries first.",
                    "Use Retriever searches and context packs for pre-indexed sources.",
                    "Use web follow-up for gaps, recency, and contradiction checks.",
                    "Preserve fetched pages, papers, files, and media in the retained dossier library.",
                    "Create dossier source records for included, excluded, duplicate, failed, and unresolved items.",
                    "Record source-quality notes, contradictions, rationale, fetch metadata, and retained refs.",
                    "Mark the dossier ready only when Methodologist has enough evidence and gaps are explicit.",
                ],
            },
        )

    def _build_methodologist_blueprint_task(
        self,
        *,
        dossier: ResearchDossier,
        version: MethodologyBlueprintVersion,
        sources: list[ResearchDossierSource] | None = None,
        requested_by: UUID,
        now: datetime,
    ) -> Task:
        if dossier.operations_workspace_id is None or dossier.thread_id is None:
            raise ValueError("Research dossier has no operations workspace/thread")
        if dossier.methodologist_system_agent_id is None:
            raise ValueError("Research dossier has no Methodologist system agent")
        if dossier.methodologist_participant_id is None:
            raise ValueError("Research dossier has no Methodologist participant")
        return Task(
            task_id=uuid4(),
            workspace_id=dossier.operations_workspace_id,
            thread_id=dossier.thread_id,
            title=f"Draft methodology blueprint version {version.version_number}",
            description=(
                "Synthesize cited methodology, methodics, and a "
                "WorkspaceHarness-compatible draft from the completed research dossier."
            ),
            requested_by=requested_by,
            visibility="agents_only",
            correlation_id=dossier.dossier_id,
            causation_id=version.version_id,
            created_at=now,
            updated_at=now,
            metadata={
                "target_system_agent_id": str(dossier.methodologist_system_agent_id),
                "target_participant_id": str(dossier.methodologist_participant_id),
                "response_visibility": "agents_only",
                "routing_reason": METHODOLOGY_BLUEPRINT_DRAFT_TASK_KIND,
                "task_kind": METHODOLOGY_BLUEPRINT_DRAFT_TASK_KIND,
                "methodology_blueprint_id": str(dossier.blueprint_id),
                "methodology_blueprint_version_id": str(version.version_id),
                "research_dossier_id": str(dossier.dossier_id),
                "retained_library_id": (
                    str(dossier.retained_library_id)
                    if dossier.retained_library_id is not None
                    else None
                ),
                "context_pack_ids": [str(item) for item in dossier.context_pack_ids],
                "dossier_summary": dossier.summary,
                "dossier_contradictions": dossier.contradictions,
                "dossier_gaps": dossier.gaps,
                "dossier_sources": [
                    source.model_dump(mode="json") for source in sources or []
                ],
                "task_instructions": [
                    "Read the completed research dossier before synthesis.",
                    "Use dossier source records, context packs, contradictions, and gaps as the evidence boundary.",
                    "Submit a cited markdown blueprint draft through methodology.blueprints.submit_draft.",
                    "Submit a WorkspaceHarness-compatible harness_draft with methodology, methodics, execution_rules, and metadata.",
                    "Do not approve or apply the blueprint, and do not start Conductor execution.",
                ],
            },
        )

    @staticmethod
    def _curator_internal_mcp_binding(
        *,
        agent_id: UUID,
        now: datetime,
    ) -> AgentInternalMcpServer:
        return managed_curator_internal_mcp_binding(
            agent_id=agent_id,
            server_id=CONTROL_PLANE_MCP_SERVER_ID,
            now=now,
        )

    async def _require_workspace_management_role(
        self,
        workspace_id: UUID,
        actor: ParticipantInput,
    ) -> ParticipantProfile:
        return await self._require_workspace_permission(
            workspace_id,
            actor,
            permission="workspace.tools.write",
        )

    async def _require_workspace_permission(
        self,
        workspace_id: UUID,
        actor: ParticipantInput,
        *,
        permission: str,
    ) -> ParticipantProfile:
        participant = await self._repository.fetch_participant(
            workspace_id,
            actor.participant_id,
        )
        if participant is None:
            raise PermissionError(
                f"Workspace {workspace_id} requires an attached participant for this action"
            )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        effective_permissions = set(actor.iam_permissions)
        if permission in effective_permissions:
            return participant
        raise PermissionError(f"Workspace permission {permission!r} required")

    @staticmethod
    def _workspace_metadata_for_create(
        *,
        metadata: dict[str, object],
        updated_by: UUID,
        updated_at: datetime,
    ) -> dict[str, object]:
        return {
            **metadata,
            "role_definitions": CollaborationKernel._merge_workspace_role_definitions(
                metadata.get("role_definitions"),
                updated_by=updated_by,
                updated_at=updated_at,
            ),
        }

    @staticmethod
    def _merge_workspace_role_definitions(
        raw: object,
        *,
        updated_by: UUID,
        updated_at: datetime,
    ) -> dict[str, dict[str, object]]:
        role_map: dict[str, dict[str, object]] = {}
        for name, definition in _DEFAULT_WORKSPACE_ROLE_DEFINITIONS.items():
            role_map[name] = RoleDefinition(
                name=name,
                definition=definition,
                updated_by=updated_by,
                updated_at=updated_at,
            ).model_dump(mode="json")
        if isinstance(raw, dict):
            for key, value in raw.items():
                role_map[key] = RoleDefinition.model_validate(value).model_dump(mode="json")
        elif isinstance(raw, list):
            for value in raw:
                role_definition = RoleDefinition.model_validate(value)
                role_map[role_definition.name] = role_definition.model_dump(mode="json")
        return role_map

    @staticmethod
    def _workspace_owner_roles(roles: list[str]) -> list[str]:
        return list(dict.fromkeys([*roles, "admin"]))

    @staticmethod
    def _utc_day_window(timestamp: datetime) -> tuple[datetime, datetime]:
        current = timestamp.astimezone(timezone.utc)
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start, day_start + timedelta(days=1)

    @staticmethod
    def _workspace_daily_token_cap(
        workspace: Workspace,
        default_cap: int,
    ) -> int:
        limits = workspace.metadata.get("limits", {})
        if isinstance(limits, dict):
            override = CollaborationKernel._metadata_int_value(
                limits.get("daily_token_cap")
            )
            if override is not None:
                return override
        override = CollaborationKernel._metadata_int_value(
            workspace.metadata.get("daily_token_cap")
        )
        if override is not None:
            return override
        return default_cap

    @staticmethod
    def _metadata_int_value(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
        return None

    @staticmethod
    def _role_definitions_from_workspace(workspace: Workspace) -> list[RoleDefinition]:
        raw = workspace.metadata.get("role_definitions", {})
        if isinstance(raw, dict):
            return [RoleDefinition.model_validate(item) for item in raw.values()]
        if isinstance(raw, list):
            return [RoleDefinition.model_validate(item) for item in raw]
        return []

    async def _human_has_organization_permission(
        self,
        organization_id: UUID,
        user_id: UUID,
        permission: str,
    ) -> bool:
        if not hasattr(self._repository, "list_human_roles_for_user"):
            return False
        roles = await self._repository.list_human_roles_for_user(
            user_id=user_id,
            organization_id=organization_id,
        )
        return any(permission in role.permissions for role in roles)

    @staticmethod
    def _validate_registry_scope(*, scope: str, organization_id: UUID | None) -> None:
        if scope not in {"global", "organization"}:
            raise ValueError(f"Unsupported registry scope {scope!r}")
        if scope == "global" and organization_id is not None:
            raise ValueError("Global registry resources cannot include an organization_id")
        if scope == "organization" and organization_id is None:
            raise ValueError("Organization-scoped resources require an organization_id")

    @staticmethod
    def _normalize_library_slug(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
        if not normalized:
            raise ValueError("Library slug must contain at least one letter or number")
        return normalized

    def _build_research_dossier_notebook_defaults(
        self,
        *,
        dossier: ResearchDossier,
        title: str,
        actor_id: UUID,
        now: datetime,
    ) -> tuple[
        ResearchDossierNotebook,
        ResearchDossierProviderBinding,
        list[ResearchDossierNote],
        list[ResearchDossierProviderExternalRef],
    ]:
        notebook_id = uuid4()
        binding_id = uuid4()
        dossier_slug = self._normalize_library_slug(
            f"dossier-{dossier.dossier_id.hex[:12]}-{title}"
        )
        space_ref = f"Dossiers.{dossier_slug}"
        base_url = (
            os.getenv("OPEN_TALON_XWIKI_BASE_URL")
            or os.getenv("XWIKI_BASE_URL")
            or "http://127.0.0.1:8083"
        ).rstrip("/")
        wiki_name = (
            os.getenv("OPEN_TALON_XWIKI_WIKI_NAME")
            or os.getenv("XWIKI_WIKI_NAME")
            or "xwiki"
        )
        home_url = f"{base_url}/bin/view/Dossiers/{dossier_slug}/"
        managed_pages = [
            ("home", "home", "Home", "WebHome"),
            ("source", "sources", "Sources", "Sources.WebHome"),
            ("concept", "concepts", "Concepts", "Concepts.WebHome"),
            ("entity", "entities", "Entities", "Entities.WebHome"),
            ("method", "methods", "Methods", "Methods.WebHome"),
            ("question", "questions", "Questions", "Questions.WebHome"),
            (
                "contradiction",
                "contradictions",
                "Contradictions",
                "Contradictions.WebHome",
            ),
            ("gap", "gaps", "Gaps", "Gaps.WebHome"),
            ("synthesis", "synthesis", "Synthesis", "Synthesis.WebHome"),
        ]
        notes: list[ResearchDossierNote] = []
        external_refs: list[ResearchDossierProviderExternalRef] = []
        for note_kind, slug, page_title, page_ref_suffix in managed_pages:
            note_id = uuid4()
            page_ref = f"{space_ref}.{page_ref_suffix}"
            notes.append(
                ResearchDossierNote(
                    note_id=note_id,
                    notebook_id=notebook_id,
                    dossier_id=dossier.dossier_id,
                    organization_id=dossier.organization_id,
                    note_kind=note_kind,
                    status="active",
                    slug=slug,
                    title=page_title,
                    body=self._default_dossier_note_body(
                        dossier=dossier,
                        title=page_title,
                        space_ref=space_ref,
                    ),
                    created_by=actor_id,
                    created_at=now,
                    updated_by=actor_id,
                    updated_at=now,
                    external_page_ref=page_ref,
                    external_url=self._xwiki_page_url(
                        base_url=base_url,
                        space_slug=dossier_slug,
                        page_ref_suffix=page_ref_suffix,
                    ),
                    metadata={
                        "managed": True,
                        "xwiki_page_ref": page_ref,
                        "xwiki_space_ref": space_ref,
                    },
                )
            )
            external_refs.append(
                ResearchDossierProviderExternalRef(
                    ref_id=uuid4(),
                    binding_id=binding_id,
                    notebook_id=notebook_id,
                    dossier_id=dossier.dossier_id,
                    organization_id=dossier.organization_id,
                    open_talon_resource_type="research_dossier_note",
                    open_talon_resource_id=note_id,
                    external_kind="page",
                    external_id=page_ref,
                    external_url=self._xwiki_page_url(
                        base_url=base_url,
                        space_slug=dossier_slug,
                        page_ref_suffix=page_ref_suffix,
                    ),
                    created_at=now,
                    updated_at=now,
                    metadata={"managed": True},
                )
            )
        home_note_id = notes[0].note_id
        notebook = ResearchDossierNotebook(
            notebook_id=notebook_id,
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            provider_kind="xwiki",
            provider_key="xwiki",
            status="created",
            home_note_id=home_note_id,
            external_space_ref=space_ref,
            external_url=home_url,
            created_by=actor_id,
            created_at=now,
            updated_by=actor_id,
            updated_at=now,
            metadata={
                "managed": True,
                "knowledge_storage": True,
                "provider_projection": "xwiki",
                "dossier_slug": dossier_slug,
            },
        )
        provider_binding = ResearchDossierProviderBinding(
            binding_id=binding_id,
            notebook_id=notebook_id,
            dossier_id=dossier.dossier_id,
            organization_id=dossier.organization_id,
            provider_kind="xwiki",
            provider_key="xwiki",
            status="created",
            external_space_ref=space_ref,
            external_base_url=base_url,
            auth_kind="basic",
            config={
                "wiki_name": wiki_name,
                "space_ref": space_ref,
                "dossier_slug": dossier_slug,
                "managed_pages": [
                    {"slug": slug, "title": page_title, "page_ref": f"{space_ref}.{suffix}"}
                    for _, slug, page_title, suffix in managed_pages
                ],
            },
            secret_config={
                "username": {"env": {"name": "OPEN_TALON_XWIKI_USERNAME"}},
                "password": {"env": {"name": "OPEN_TALON_XWIKI_PASSWORD"}},
            },
            created_by=actor_id,
            created_at=now,
            updated_by=actor_id,
            updated_at=now,
            metadata={"managed": True, "system_plugin": "xwiki"},
        )
        external_refs.append(
            ResearchDossierProviderExternalRef(
                ref_id=uuid4(),
                binding_id=binding_id,
                notebook_id=notebook_id,
                dossier_id=dossier.dossier_id,
                organization_id=dossier.organization_id,
                open_talon_resource_type="research_dossier_notebook",
                open_talon_resource_id=notebook_id,
                external_kind="space",
                external_id=space_ref,
                external_url=home_url,
                created_at=now,
                updated_at=now,
                metadata={"managed": True},
            )
        )
        return notebook, provider_binding, notes, external_refs

    @staticmethod
    def _default_dossier_note_body(
        *,
        dossier: ResearchDossier,
        title: str,
        space_ref: str,
    ) -> str:
        return (
            f"= {title} =\n\n"
            f"Open Talon dossier: `{dossier.dossier_id}`\n\n"
            f"XWiki space: `{space_ref}`\n\n"
            "== Purpose ==\n\n"
            "Researcher maintains this page through dossier notebook MCP operations.\n\n"
            "== Notes ==\n\n"
            "_No curated entries yet._\n"
        )

    @staticmethod
    def _xwiki_page_url(
        *,
        base_url: str,
        space_slug: str,
        page_ref_suffix: str,
    ) -> str:
        parts = ["Dossiers", space_slug]
        suffix_parts = page_ref_suffix.split(".")
        if suffix_parts[-1] == "WebHome":
            parts.extend(suffix_parts[:-1])
        else:
            parts.extend(suffix_parts)
        return f"{base_url}/bin/view/" + "/".join(part for part in parts if part) + "/"

    async def _resolve_library_owner(
        self,
        *,
        scope: str,
        organization_id: UUID | None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> tuple[UUID, UUID | None, UUID | None]:
        if scope == "global":
            raise ValueError("Libraries must belong to an organization, project, or workspace")
        organization = await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if organization is None:
            raise ValueError("Libraries require an organization owner")
        if scope == "organization":
            return organization.organization_id, None, None
        if scope == "project":
            if project_id is None:
                raise ValueError("Project libraries require project_id")
            return organization.organization_id, project_id, None
        if scope == "workspace":
            if workspace_id is None:
                raise ValueError("Workspace libraries require workspace_id")
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            return workspace.organization_id, workspace.project_id, workspace.workspace_id
        raise ValueError(f"Unsupported library scope {scope!r}")

    @staticmethod
    def _validate_asset_scope(
        *,
        scope: str,
        organization_id: UUID | None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> None:
        if scope not in {"global", "organization", "project", "workspace"}:
            raise ValueError(f"Unsupported asset scope {scope!r}")
        if scope == "global" and (
            organization_id is not None or project_id is not None or workspace_id is not None
        ):
            raise ValueError("Global scope resources cannot include organization_id, project_id, or workspace_id")
        if scope == "organization" and (
            organization_id is None or project_id is not None or workspace_id is not None
        ):
            raise ValueError("Organization scope resources require organization_id and forbid project_id/workspace_id")
        if scope == "project" and (
            organization_id is None or project_id is None or workspace_id is not None
        ):
            raise ValueError("Project scope resources require organization_id/project_id and forbid workspace_id")
        if scope == "workspace" and workspace_id is None:
            raise ValueError("Workspace scope resources require a workspace_id")

    @staticmethod
    def _validate_tool_execution_binding(execution) -> None:
        workspace_access = execution.execution_profile.get("workspace_access", "read_only")
        network = execution.execution_profile.get("network", "none")
        if workspace_access == "read_write" and execution.trust_level != "trusted":
            raise ValueError("read_write workspace access requires trust_level='trusted'")
        if network == "full" and execution.trust_level != "trusted":
            raise ValueError("network=full requires trust_level='trusted'")
        if execution.backend_kind == "local_process" and execution.trust_level != "trusted":
            raise ValueError("local_process execution requires trust_level='trusted'")

    @staticmethod
    def _validate_llm_provider_definition(provider: LlmProviderDefinition) -> None:
        capabilities = {
            item.strip().lower()
            for item in provider.capabilities
            if isinstance(item, str) and item.strip()
        }
        embedding_markers = {"embed", "embedding", "embeddings", "vector"}
        if capabilities.intersection(embedding_markers):
            raise ValueError(
                "LLM providers must not advertise embedding capabilities; "
                "use Retriever embedding providers for embedding models"
            )

    async def _validate_asset_link_target(
        self,
        *,
        target_type: str,
        target_id: UUID,
        organization_id: UUID | None,
        workspace_id: UUID | None,
    ) -> None:
        if target_type == "system_agent":
            agent = await self._repository.fetch_system_agent(target_id)
            if agent is None:
                raise KeyError(f"System agent {target_id} not found")
            if (
                organization_id is not None
                and agent.scope == "organization"
                and agent.organization_id != organization_id
            ):
                raise ValueError("Organization asset links must target resources in the same organization")
            return
        if target_type == "system_tool":
            tool = await self._repository.fetch_system_tool(target_id)
            if tool is None:
                raise KeyError(f"System tool {target_id} not found")
            if (
                organization_id is not None
                and tool.scope == "organization"
                and tool.organization_id != organization_id
            ):
                raise ValueError("Organization asset links must target resources in the same organization")
            return
        if target_type == "workspace":
            workspace = await self._repository.fetch_workspace(target_id)
            if workspace is None:
                raise KeyError(f"Workspace {target_id} not found")
            if organization_id is not None and workspace.organization_id != organization_id:
                raise ValueError("Organization asset links must target workspaces in the same organization")
            return
        if target_type == "workspace_tool":
            if workspace_id is None:
                raise ValueError("workspace_tool asset links require a workspace_id override scope")
            if await self._repository.fetch_workspace_tool(workspace_id, target_id) is None:
                raise KeyError(f"Workspace tool {target_id} not found in workspace {workspace_id}")
            return
        raise ValueError(f"Unsupported asset link target type {target_type!r}")

    @staticmethod
    def _require_same_retrieval_scope(
        *,
        left_name: str,
        left_id: UUID,
        left_scope: str,
        left_organization_id: UUID | None,
        left_workspace_id: UUID | None,
        right_scope: str,
        right_organization_id: UUID | None,
        right_workspace_id: UUID | None,
        left_project_id: UUID | None = None,
        right_project_id: UUID | None = None,
    ) -> None:
        if (
            left_scope != right_scope
            or left_organization_id != right_organization_id
            or left_project_id != right_project_id
            or left_workspace_id != right_workspace_id
        ):
            raise ValueError(
                f"{left_name} {left_id} does not match retrieval scope "
                f"{right_scope!r}"
            )

    async def _resolve_asset_version_for_source(
        self,
        *,
        asset_id: UUID,
        asset_version_id: UUID | None,
    ) -> WorkspaceAssetVersion:
        if asset_version_id is not None:
            version = await self._repository.fetch_workspace_asset_version(
                asset_version_id
            )
            if version is None or version.asset_id != asset_id:
                raise KeyError(
                    f"Asset version {asset_version_id} does not belong to asset {asset_id}"
                )
            return version
        versions = await self._repository.list_workspace_asset_versions(asset_id)
        if not versions:
            raise KeyError(f"Workspace asset {asset_id} has no versions")
        return versions[-1]

    async def _resolve_retrieval_corpora_for_search(
        self,
        *,
        scope: str,
        organization_id: UUID | None,
        project_id: UUID | None,
        workspace_id: UUID | None,
        corpus_ids: list[UUID],
    ) -> list[RetrievalCorpus]:
        if corpus_ids:
            corpora: list[RetrievalCorpus] = []
            visible_library_ids: set[str] | None = None
            for corpus_id in corpus_ids:
                corpus = await self._repository.fetch_retrieval_corpus(corpus_id)
                if corpus is None:
                    raise KeyError(f"Retrieval corpus {corpus_id} not found")
                same_scope = (
                    corpus.scope == scope
                    and corpus.organization_id == organization_id
                    and corpus.project_id == project_id
                    and corpus.workspace_id == workspace_id
                )
                if not same_scope:
                    library_id = corpus.metadata.get("library_id")
                    if scope != "workspace" or workspace_id is None or not isinstance(library_id, str):
                        self._require_same_retrieval_scope(
                            left_name="Retrieval corpus",
                            left_id=corpus.corpus_id,
                            left_scope=corpus.scope,
                            left_organization_id=corpus.organization_id,
                            left_workspace_id=corpus.workspace_id,
                            right_scope=scope,
                            right_organization_id=organization_id,
                            right_workspace_id=workspace_id,
                            left_project_id=corpus.project_id,
                            right_project_id=project_id,
                        )
                    if visible_library_ids is None:
                        visible_libraries = await self._repository.list_libraries(
                            scope="workspace",
                            organization_id=organization_id,
                            project_id=project_id,
                            workspace_id=workspace_id,
                            include_workspace_attachments=True,
                        )
                        visible_library_ids = {
                            str(library.library_id) for library in visible_libraries
                        }
                    if library_id not in visible_library_ids:
                        raise ValueError(
                            f"Retrieval corpus {corpus.corpus_id} is not visible in workspace scope"
                        )
                corpora.append(corpus)
            return corpora
        corpora = await self._repository.list_retrieval_corpora(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if scope == "workspace" and workspace_id is not None:
            visible_libraries = await self._repository.list_libraries(
                scope="workspace",
                organization_id=organization_id,
                project_id=project_id,
                workspace_id=workspace_id,
                include_workspace_attachments=True,
            )
            seen_corpus_ids = {corpus.corpus_id for corpus in corpora}
            for library in visible_libraries:
                library_corpora = await self._repository.list_retrieval_corpora(
                    scope=library.scope,
                    organization_id=library.organization_id,
                    project_id=library.project_id,
                    workspace_id=library.workspace_id,
                )
                for corpus in library_corpora:
                    if (
                        corpus.metadata.get("library_id") == str(library.library_id)
                        and corpus.corpus_id not in seen_corpus_ids
                    ):
                        corpora.append(corpus)
                        seen_corpus_ids.add(corpus.corpus_id)
        if not corpora:
            raise KeyError(f"No retrieval corpora found for {scope!r} scope")
        return corpora

    @staticmethod
    def _retrieval_corpus_scope_groups(
        corpora: list[RetrievalCorpus],
    ) -> list[dict[str, object]]:
        groups: dict[
            tuple[str, UUID | None, UUID | None, UUID | None],
            list[RetrievalCorpus],
        ] = {}
        for corpus in corpora:
            key = (
                corpus.scope,
                corpus.organization_id,
                corpus.project_id,
                corpus.workspace_id,
            )
            groups.setdefault(key, []).append(corpus)
        return [
            {
                "scope": key[0],
                "organization_id": key[1],
                "project_id": key[2],
                "workspace_id": key[3],
                "corpora": value,
            }
            for key, value in groups.items()
        ]

    async def _resolve_retrieval_profile_for_search(
        self,
        *,
        profile_id: UUID | None,
        corpora: list[RetrievalCorpus],
    ) -> RetrievalProfile | None:
        if profile_id is not None:
            profile = await self._repository.fetch_retrieval_profile(profile_id)
            if profile is None:
                raise KeyError(f"Retrieval profile {profile_id} not found")
            first = corpora[0]
            self._require_same_retrieval_scope(
                left_name="Retrieval profile",
                left_id=profile.profile_id,
                left_scope=profile.scope,
                left_organization_id=profile.organization_id,
                left_workspace_id=profile.workspace_id,
                right_scope=first.scope,
                right_organization_id=first.organization_id,
                right_workspace_id=first.workspace_id,
                left_project_id=profile.project_id,
                right_project_id=first.project_id,
            )
            return profile
        default_profile_id = next(
            (corpus.default_profile_id for corpus in corpora if corpus.default_profile_id),
            None,
        )
        if default_profile_id is None:
            return None
        return await self._repository.fetch_retrieval_profile(default_profile_id)

    def _build_context_pack(
        self,
        *,
        query: str,
        run: RetrievalRun,
        hits: list[RetrievalSearchHit],
        token_budget: int,
        created_by: UUID,
        metadata: dict[str, object],
    ) -> RetrievalContextPack:
        sections: list[str] = []
        token_count = 0
        seen_chunk_ids: set[UUID] = set()
        for hit in hits:
            chunk = hit.chunk
            if chunk.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.chunk_id)
            content = chunk.content.strip()
            if not content:
                continue
            chunk_tokens = len(content.split())
            if sections and token_count + chunk_tokens > token_budget:
                break
            citation_parts = [
                f"source={chunk.source_id}",
                f"chunk={chunk.ordinal}",
            ]
            if chunk.citation is not None:
                if chunk.citation.page_start is not None:
                    if chunk.citation.page_end and chunk.citation.page_end != chunk.citation.page_start:
                        citation_parts.append(
                            f"pages={chunk.citation.page_start}-{chunk.citation.page_end}"
                        )
                    else:
                        citation_parts.append(f"page={chunk.citation.page_start}")
                if chunk.citation.section:
                    citation_parts.append(f"section={chunk.citation.section}")
            sections.append(
                f"[{hit.rank}] {'; '.join(citation_parts)}\n{content}"
            )
            token_count += chunk_tokens
        content = "\n\n".join(sections)
        return RetrievalContextPack(
            context_pack_id=uuid4(),
            run_id=run.run_id,
            scope=run.scope,
            organization_id=run.organization_id,
            project_id=run.project_id,
            workspace_id=run.workspace_id,
            profile_id=run.profile_id,
            query=query,
            content=content,
            token_count=token_count,
            hits=hits,
            created_by=created_by,
            created_at=self._now(),
            metadata=metadata,
        )

    async def _resolve_scope_organization(
        self,
        *,
        scope: str,
        organization_id: UUID | None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> Organization | None:
        self._validate_asset_scope(
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
        )
        if scope == "global":
            return None
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            if organization_id is not None and workspace.organization_id != organization_id:
                raise ValueError(
                    f"Workspace {workspace_id} does not belong to organization {organization_id}"
                )
            if project_id is not None and workspace.project_id != project_id:
                raise ValueError(
                    f"Workspace {workspace_id} does not belong to project {project_id}"
                )
            if not hasattr(self._repository, "fetch_organization"):
                return Organization(
                    organization_id=workspace.organization_id
                    or UUID("11111111-1111-1111-1111-111111111111"),
                    slug="default",
                    name="Default Organization",
                    description="Implicit test organization",
                    created_by=workspace.created_by
                    or workspace.owner_user_id
                    or workspace.workspace_id,
                    created_at=workspace.created_at,
                    updated_at=workspace.updated_at,
                    metadata={},
                )
            organization = await self._repository.fetch_organization(workspace.organization_id)
            if organization is None:
                raise KeyError(f"Organization {workspace.organization_id} not found")
            return organization
        if project_id is not None:
            project = await self._repository.fetch_project(project_id)
            if project is None:
                raise KeyError(f"Project {project_id} not found")
            if organization_id is not None and project.organization_id != organization_id:
                raise ValueError(
                    f"Project {project_id} does not belong to organization {organization_id}"
                )
            if not hasattr(self._repository, "fetch_organization"):
                return Organization(
                    organization_id=project.organization_id,
                    slug="default",
                    name="Default Organization",
                    description="Implicit test organization",
                    created_by=project.created_by,
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                    metadata={},
                )
            organization = await self._repository.fetch_organization(project.organization_id)
            if organization is None:
                raise KeyError(f"Organization {project.organization_id} not found")
            return organization
        assert organization_id is not None
        if not hasattr(self._repository, "fetch_organization"):
            return Organization(
                organization_id=organization_id,
                slug="default",
                name="Default Organization",
                description="Implicit test organization",
                created_by=organization_id,
                created_at=self._now(),
                updated_at=self._now(),
                metadata={},
            )
        organization = await self._repository.fetch_organization(organization_id)
        if organization is None:
            raise KeyError(f"Organization {organization_id} not found")
        return organization

    @staticmethod
    def _resource_visible_to_workspace(
        scope: str,
        organization_id: UUID | None,
        workspace: Workspace,
    ) -> bool:
        if scope == "global":
            return True
        if scope == "organization":
            return organization_id == workspace.organization_id
        return False

    async def _visible_enabled_memory_providers(
        self,
        organization_id: UUID | None,
    ) -> list[MemoryProviderDefinition]:
        try:
            providers = await self._repository.list_enabled_memory_providers(scope="global")
        except TypeError:
            providers = await self._repository.list_enabled_memory_providers()
        if organization_id is None:
            return providers
        try:
            overrides = await self._repository.list_enabled_memory_providers(
                scope="organization",
                organization_id=organization_id,
            )
        except TypeError:
            overrides = []
        by_key = {provider.provider_key: provider for provider in providers}
        for provider in overrides:
            by_key[provider.provider_key] = provider
        return list(by_key.values())

    @staticmethod
    def _advertised_agent_capabilities(
        base_capabilities: list[str],
        workspace_tools: list[WorkspaceTool],
    ) -> list[str]:
        combined = list(base_capabilities)
        for tool in workspace_tools:
            if tool.enabled:
                combined.append(f"tool:{tool.name}")
        return list(dict.fromkeys(combined))

    @classmethod
    def _advertise_workspace_tools(
        cls,
        participant: ParticipantProfile,
        workspace_tools: list[WorkspaceTool],
    ) -> ParticipantProfile:
        if participant.participant_type != "agent":
            return participant
        return participant.model_copy(
            update={
                "capabilities": cls._advertised_agent_capabilities(
                    participant.capabilities,
                    workspace_tools,
                )
            }
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
