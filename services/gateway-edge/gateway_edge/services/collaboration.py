from __future__ import annotations

import asyncio
import io
import logging
import tarfile
import zipfile
from collections import defaultdict
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

_ROOT_DIR = Path(__file__).resolve().parents[4]

_CORE_COLLAB_DIR = _ROOT_DIR / "services" / "core-collab"
if _CORE_COLLAB_DIR.is_dir():
    collab_path = str(_CORE_COLLAB_DIR)
    import sys
    if collab_path not in sys.path:
        sys.path.insert(0, collab_path)

from core_collab import CollaborationKernel, CollaborationRepository  # noqa: E402

from gateway_edge.db.postgres import get_pool
from gateway_edge.config import settings
from gateway_edge.models import (
    AuthContext,
    ActivateAssetVersionRequest,
    ActivateAgentDefinitionVersionRequest,
    AssumeParticipantRoleRequest,
    AgentBundlePublishResult,
    AgentBundleUploadResult,
    AgentBundleValidationResult,
    AgentDefinition,
    AgentDefinitionVersion,
    AgentGitCommitRequest,
    AgentGitCommitResult,
    AgentGitDiffResult,
    AgentGitFileContent,
    AgentGitFileMutationRequest,
    AgentGitWorktreeSession,
    AgentIdentity,
    AgentIdentityProvisioningResult,
    AttachWorkspaceToolRequest,
    AssetLink,
    BindAgentRoleRequest,
    BindHumanRoleRequest,
    CreateGitRepositoryRequest,
    CreateAgentGitWorktreeSessionRequest,
    CreateAgentParticipantRequest,
    CreateAgentIdentityRequest,
    CreateInteractionAnswerRequest,
    CreateInteractionRequestsRequest,
    CreateIamRoleRequest,
    CreateLlmProviderRequest,
    CreateMemoryProviderRequest,
    CreateMcpServerRequest,
    CancelMethodicExecutionRequest,
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
    CreateToolGenerationRevisionRequest,
    SearchMemoryRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteLlmProviderRequest,
    DeleteMemoryProviderRequest,
    DeleteMcpServerRequest,
    DeleteParticipantRequest,
    DeleteRoleDefinitionRequest,
    DeleteSystemAgentRequest,
    DeleteSystemToolRequest,
    DeleteWorkspaceToolRequest,
    DeleteWorkspaceMcpServerRequest,
    DeleteWorkspaceRequest,
    EventEnvelope,
    GitRepository,
    InteractionRequestDetail,
    LinkAssetRequest,
    MemoryEntry,
    MemoryProviderDefinition,
    MemorySearchResponse,
    McpPromptDefinition,
    McpResourceDefinition,
    McpServerDefinition,
    McpToolDefinition,
    LlmProviderDefinition,
    MethodicExecution,
    MethodicExecutionDetail,
    MethodicResourceRequest,
    Organization,
    OrganizationMembership,
    ParticipantInput,
    ParticipantProfile,
    Project,
    IamPermission,
    IamRoleDefinition,
    RoleDefinition,
    PublishAssetFromGitRequest,
    RetrievalContextPack,
    RetrievalCorpus,
    RetrievalIngestionJob,
    RetrievalProfile,
    RetrievalSearchResponse,
    RetrievalSource,
    RetrievalSourceVersion,
    RunRetrievalSearchRequest,
    PublishAgentBundleFromGitRequest,
    ResolvedAssetBinding,
    SystemToolDefinition,
    Thread,
    ThreadDetail,
    TimelineMessage,
    TimelinePage,
    ToolGenerationRequestDetail,
    WorkspaceCommunicationLogPage,
    RotateAgentIdentitySecretRequest,
    UpdateInteractionRequestRequest,
    UpdateAgentIdentityStatusRequest,
    UpdateIamRoleRequest,
    UpdateWorkspaceRequest,
    UpdateSystemAgentRequest,
    UpsertRoleDefinitionRequest,
    UpdateSystemToolRequest,
    UpdateAgentParticipantRequest,
    UpdateLlmProviderRequest,
    UpdateMemoryProviderRequest,
    UpdateMcpServerRequest,
    UpdateMemoryEntryRequest,
    UpdateOrganizationRequest,
    UpdateProjectRequest,
    UpsertProjectAccessRequest,
    ReviewToolGenerationRevisionRequest,
    ReviewMethodicResourceRequest,
    RemoveProjectAccessRequest,
    UpdateWorkspaceToolRequest,
    UpdateWorkspaceMcpServerRequest,
    Workspace,
    WorkspaceAsset,
    WorkspaceAssetVersion,
    WorkspaceDetail,
    WorkspaceMcpPrompt,
    WorkspaceMcpResource,
    WorkspaceMcpServer,
    WorkspaceMcpTool,
    WorkspaceTool,
    AttachWorkspaceMcpServerRequest,
    ValidateAgentBundleFromGitRequest,
    AddOrganizationMemberRequest,
    RemoveOrganizationMemberRequest,
    UploadFileAssetRequest,
)
from gateway_edge.services.agent_bundles import (
    AgentBundleCompiler,
    GitAgentBundleReader,
    join_bundle_path,
    normalize_bundle_path,
    validation_error_result,
)
from gateway_edge.services.git_publish import GitPublishService
from gateway_edge.services.git_worktrees import LocalManagedWorktreeStore
from gateway_edge.services.object_storage import MinioObjectStorage
from gateway_edge.services.events import event_service
from gateway_edge.services.session import (
    get_workspace_participant_presence,
    register_thread_connection,
    touch_thread_presence,
    unregister_thread_connection,
)

logger = logging.getLogger(__name__)


class CollaborationService:
    def __init__(self) -> None:
        self._kernel: CollaborationKernel | None = None
        self._subscriptions: dict[str, set[asyncio.Queue[EventEnvelope]]] = defaultdict(set)
        self._git_publish = GitPublishService()
        self._agent_bundle_compiler = AgentBundleCompiler()
        self._worktree_store = LocalManagedWorktreeStore(git_service=self._git_publish)
        self._worktree_sessions: dict[UUID, AgentGitWorktreeSession] = {}
        self._storage = MinioObjectStorage(
            endpoint=settings.asset_storage_endpoint,
            bucket=settings.asset_storage_bucket,
            access_key=settings.asset_storage_access_key,
            secret_key=settings.asset_storage_secret_key,
            region=settings.asset_storage_region,
            force_path_style=settings.asset_storage_force_path_style,
        )

    async def start(self) -> None:
        pool = await get_pool()
        repository = CollaborationRepository(
            pool,
            communication_log_dir=settings.communication_log_dir,
        )
        self._kernel = CollaborationKernel(repository)
        await self._kernel.setup_schema()
        event_service.set_event_handler(self._handle_published_event)
        logger.info("Collaboration service started")

    async def stop(self) -> None:
        event_service.set_event_handler(None)
        self._subscriptions.clear()
        self._kernel = None
        logger.info("Collaboration service stopped")

    async def create_workspace(
        self,
        payload: CreateWorkspaceRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> WorkspaceDetail:
        logger.debug(
            "Service create_workspace participant_id=%s name=%r",
            payload.actor.participant_id,
            payload.name,
        )
        kernel = self._require_kernel()
        result = await kernel.create_workspace(
            payload,
            allow_platform_admin=allow_platform_admin,
        )
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def create_organization(
        self,
        payload: CreateOrganizationRequest,
    ) -> Organization:
        result = await self._require_kernel().create_organization(payload)
        assert result.organization is not None
        return result.organization

    async def list_organizations(
        self,
        *,
        user_id: UUID | None = None,
    ) -> list[Organization]:
        return await self._require_kernel().list_organizations(user_id=user_id)

    async def get_organization(self, organization_id: UUID) -> Organization:
        organization = await self._require_kernel().get_organization(organization_id)
        if organization is None:
            raise KeyError(f"Organization {organization_id} not found")
        return organization

    async def get_organization_by_slug(self, slug: str) -> Organization:
        organization = await self._require_kernel().get_organization_by_slug(slug)
        if organization is None:
            raise KeyError(f"Organization slug {slug!r} not found")
        return organization

    async def create_project(
        self,
        organization_id: UUID,
        payload: CreateProjectRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> Project:
        result = await self._require_kernel().create_project(
            organization_id,
            payload,
            allow_platform_admin=allow_platform_admin,
        )
        assert result.project is not None
        return result.project

    async def list_projects(self, organization_id: UUID) -> list[Project]:
        return await self._require_kernel().list_projects(organization_id)

    async def list_projects_for_principal(
        self,
        organization_id: UUID,
        *,
        user_id: UUID | None = None,
        system_agent_id: UUID | None = None,
        include_all: bool = False,
    ) -> list[Project]:
        return await self._require_kernel().list_projects(
            organization_id,
            user_id=user_id,
            system_agent_id=system_agent_id,
            include_all=include_all,
        )

    async def get_project(self, project_id: UUID) -> Project:
        project = await self._require_kernel().get_project(project_id)
        if project is None:
            raise KeyError(f"Project {project_id} not found")
        return project

    async def update_project(
        self,
        organization_id: UUID,
        project_id: UUID,
        payload: UpdateProjectRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> Project:
        result = await self._require_kernel().update_project(
            organization_id,
            project_id,
            payload,
            allow_platform_admin=allow_platform_admin,
        )
        assert result.project is not None
        return result.project

    async def list_project_access(
        self,
        organization_id: UUID,
        project_id: UUID,
        *,
        actor: ParticipantInput | None = None,
        allow_platform_admin: bool = False,
    ):
        return await self._require_kernel().list_project_access(
            organization_id,
            project_id,
            actor=actor,
            allow_platform_admin=allow_platform_admin,
        )

    async def upsert_project_access(
        self,
        organization_id: UUID,
        project_id: UUID,
        payload: UpsertProjectAccessRequest,
        *,
        allow_platform_admin: bool = False,
    ):
        return await self._require_kernel().upsert_project_access(
            organization_id,
            project_id,
            payload,
            allow_platform_admin=allow_platform_admin,
        )

    async def remove_project_access(
        self,
        organization_id: UUID,
        project_id: UUID,
        payload: RemoveProjectAccessRequest,
        *,
        allow_platform_admin: bool = False,
    ):
        return await self._require_kernel().remove_project_access(
            organization_id,
            project_id,
            payload,
            allow_platform_admin=allow_platform_admin,
        )

    async def update_organization(
        self,
        organization_id: UUID,
        payload: UpdateOrganizationRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> Organization:
        result = await self._require_kernel().update_organization(
            organization_id,
            payload,
            allow_platform_admin=allow_platform_admin,
        )
        assert result.organization is not None
        return result.organization

    async def list_organization_memberships(
        self,
        organization_id: UUID,
    ) -> list[OrganizationMembership]:
        return await self._require_kernel().list_organization_memberships(organization_id)

    async def add_organization_member(
        self,
        organization_id: UUID,
        payload: AddOrganizationMemberRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> OrganizationMembership:
        result = await self._require_kernel().add_organization_member(
            organization_id,
            payload,
            allow_platform_admin=allow_platform_admin,
        )
        assert result.membership is not None
        return result.membership

    async def remove_organization_member(
        self,
        organization_id: UUID,
        user_id: UUID,
        payload: RemoveOrganizationMemberRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> dict[str, bool | str]:
        return await self._require_kernel().remove_organization_member(
            organization_id,
            user_id,
            payload,
            allow_platform_admin=allow_platform_admin,
        )

    async def resolve_authenticated_user_actor(
        self,
        *,
        workspace_id: UUID,
        auth_context: AuthContext,
        auto_create: bool = True,
    ) -> ParticipantInput:
        if auth_context.user_id is None or not auth_context.display_name:
            raise ValueError("Authenticated OIDC user context is incomplete")
        return await self._require_kernel().resolve_authenticated_user_actor(
            workspace_id,
            user_id=auth_context.user_id,
            display_name=auth_context.display_name,
            auto_create=auto_create,
        )

    async def resolve_authenticated_thread_actor(
        self,
        *,
        thread_id: UUID,
        auth_context: AuthContext,
        auto_create: bool = True,
    ) -> ParticipantInput:
        thread = await self._require_kernel().get_thread_detail(thread_id)
        return await self.resolve_authenticated_user_actor(
            workspace_id=thread.thread.workspace_id,
            auth_context=auth_context,
            auto_create=auto_create,
        )

    async def resolve_authenticated_agent_actor(
        self,
        *,
        workspace_id: UUID,
        auth_context: AuthContext,
    ) -> ParticipantInput:
        if auth_context.system_agent_id is None:
            raise ValueError("Authenticated machine context is incomplete")
        participant = await self._require_kernel()._repository.fetch_agent_participant(  # noqa: SLF001
            workspace_id,
            auth_context.system_agent_id,
        )
        if participant is None:
            raise KeyError(
                f"System agent {auth_context.system_agent_id} is not attached to workspace {workspace_id}"
            )
        return ParticipantInput(
            participant_id=participant.participant_id,
            participant_type="agent",
            display_name=participant.display_name,
            roles=participant.roles,
            capabilities=participant.capabilities,
            visibility_scope=participant.visibility_scope,
        )

    async def list_workspaces(
        self,
        *,
        user_id: UUID | None = None,
        system_agent_id: UUID | None = None,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
    ) -> list[Workspace]:
        return await self._require_kernel().list_workspaces(
            user_id=user_id,
            system_agent_id=system_agent_id,
            organization_id=organization_id,
            project_id=project_id,
        )

    async def delete_workspace(
        self, workspace_id: UUID, payload: DeleteWorkspaceRequest
    ) -> dict[str, bool | str]:
        logger.debug(
            "Service delete_workspace workspace_id=%s participant_id=%s",
            workspace_id,
            payload.actor.participant_id,
        )
        return await self._require_kernel().delete_workspace(workspace_id, payload)

    async def update_workspace(
        self,
        workspace_id: UUID,
        payload: UpdateWorkspaceRequest,
        *,
        skip_workspace_permission_check: bool = False,
    ) -> WorkspaceDetail:
        logger.debug(
            "Service update_workspace workspace_id=%s participant_id=%s",
            workspace_id,
            payload.actor.participant_id,
        )
        result = await self._require_kernel().update_workspace(
            workspace_id,
            payload,
            skip_workspace_permission_check=skip_workspace_permission_check,
        )
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def get_workspace(self, workspace_id: UUID) -> WorkspaceDetail:
        logger.debug("Service get_workspace workspace_id=%s", workspace_id)
        detail = await self._require_kernel().get_workspace_detail(workspace_id)
        return detail.model_copy(
            update={
                "participants": await self._overlay_workspace_presence(
                    workspace_id=workspace_id,
                    participants=detail.participants,
                )
            }
        )

    async def list_workspace_participants(self, workspace_id: UUID):
        logger.debug("Service list_workspace_participants workspace_id=%s", workspace_id)
        participants = await self._require_kernel().list_workspace_participants(workspace_id)
        return await self._overlay_workspace_presence(
            workspace_id=workspace_id,
            participants=participants,
        )

    async def delete_participant(
        self,
        workspace_id: UUID,
        participant_id: UUID,
        payload: DeleteParticipantRequest,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Service delete_participant workspace_id=%s participant_id=%s actor_id=%s",
            workspace_id,
            participant_id,
            payload.actor.participant_id,
        )
        return await self._require_kernel().delete_participant(
            workspace_id,
            participant_id,
            payload,
        )

    async def create_system_agent(
        self,
        payload: CreateSystemAgentRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> AgentDefinition:
        result = await self._require_kernel().create_system_agent(
            payload,
            scope=scope,
            organization_id=organization_id,
        )
        assert result.agent is not None
        return result.agent

    async def get_system_agent(self, agent_id: UUID) -> AgentDefinition | None:
        return await self._require_kernel()._repository.fetch_system_agent(agent_id)  # noqa: SLF001

    async def create_llm_provider(
        self,
        payload: CreateLlmProviderRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> LlmProviderDefinition:
        result = await self._require_kernel().create_llm_provider(
            payload,
            scope=scope,
            organization_id=organization_id,
        )
        assert result.provider is not None
        return result.provider

    async def create_memory_provider(
        self,
        payload: CreateMemoryProviderRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> MemoryProviderDefinition:
        result = await self._require_kernel().create_memory_provider(
            payload,
            scope=scope,
            organization_id=organization_id,
        )
        assert result.provider is not None
        return result.provider

    async def create_mcp_server(
        self,
        payload: CreateMcpServerRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> McpServerDefinition:
        result = await self._require_kernel().create_mcp_server(
            payload,
            scope=scope,
            organization_id=organization_id,
        )
        assert result.server is not None
        return result.server

    async def list_system_agents(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[AgentDefinition]:
        return await self._require_kernel().list_system_agents(
            scope=scope,
            organization_id=organization_id,
        )

    async def list_workspace_catalog_agents(
        self,
        workspace_id: UUID,
    ) -> list[AgentDefinition]:
        return await self._require_kernel().list_workspace_catalog_agents(workspace_id)

    async def list_llm_providers(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[LlmProviderDefinition]:
        return await self._require_kernel().list_llm_providers(
            scope=scope,
            organization_id=organization_id,
        )

    async def list_memory_providers(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[MemoryProviderDefinition]:
        return await self._require_kernel().list_memory_providers(
            scope=scope,
            organization_id=organization_id,
        )

    async def list_mcp_servers(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[McpServerDefinition]:
        return await self._require_kernel().list_mcp_servers(
            scope=scope,
            organization_id=organization_id,
        )

    async def list_workspace_catalog_mcp_servers(
        self,
        workspace_id: UUID,
    ) -> list[McpServerDefinition]:
        return await self._require_kernel().list_workspace_catalog_mcp_servers(workspace_id)

    async def get_llm_provider(self, provider_id: UUID) -> LlmProviderDefinition:
        provider = await self._require_kernel().get_llm_provider(provider_id)
        if provider is None:
            raise KeyError(f"LLM provider {provider_id} not found")
        return provider

    async def get_memory_provider(self, provider_id: UUID) -> MemoryProviderDefinition:
        provider = await self._require_kernel().get_memory_provider(provider_id)
        if provider is None:
            raise KeyError(f"Memory provider {provider_id} not found")
        return provider

    async def get_mcp_server(self, server_id: UUID) -> McpServerDefinition:
        server = await self._require_kernel().get_mcp_server(server_id)
        if server is None:
            raise KeyError(f"MCP server {server_id} not found")
        return server

    async def list_mcp_server_tools(self, server_id: UUID) -> list[McpToolDefinition]:
        return await self._require_kernel().list_mcp_server_tools(server_id)

    async def list_mcp_server_resources(self, server_id: UUID) -> list[McpResourceDefinition]:
        return await self._require_kernel().list_mcp_server_resources(server_id)

    async def list_mcp_server_prompts(self, server_id: UUID) -> list[McpPromptDefinition]:
        return await self._require_kernel().list_mcp_server_prompts(server_id)

    async def create_system_tool(
        self,
        payload: CreateSystemToolRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> SystemToolDefinition:
        result = await self._require_kernel().create_system_tool(
            payload,
            scope=scope,
            organization_id=organization_id,
        )
        assert result.tool is not None
        return result.tool

    async def get_system_tool(self, tool_id: UUID) -> SystemToolDefinition | None:
        return await self._require_kernel()._repository.fetch_system_tool(tool_id)  # noqa: SLF001

    async def list_system_tools(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[SystemToolDefinition]:
        return await self._require_kernel().list_system_tools(
            scope=scope,
            organization_id=organization_id,
        )

    async def list_workspace_catalog_tools(
        self,
        workspace_id: UUID,
    ) -> list[SystemToolDefinition]:
        return await self._require_kernel().list_workspace_catalog_tools(workspace_id)

    async def update_system_tool(
        self, tool_id: UUID, payload: UpdateSystemToolRequest
    ) -> SystemToolDefinition:
        result = await self._require_kernel().update_system_tool(tool_id, payload)
        assert result.tool is not None
        return result.tool

    async def delete_system_tool(
        self,
        tool_id: UUID,
        payload: DeleteSystemToolRequest,
    ) -> dict[str, bool | str]:
        return await self._require_kernel().delete_system_tool(tool_id, payload)

    async def update_llm_provider(
        self, provider_id: UUID, payload: UpdateLlmProviderRequest
    ) -> LlmProviderDefinition:
        result = await self._require_kernel().update_llm_provider(provider_id, payload)
        assert result.provider is not None
        return result.provider

    async def update_memory_provider(
        self, provider_id: UUID, payload: UpdateMemoryProviderRequest
    ) -> MemoryProviderDefinition:
        result = await self._require_kernel().update_memory_provider(provider_id, payload)
        assert result.provider is not None
        return result.provider

    async def update_mcp_server(
        self, server_id: UUID, payload: UpdateMcpServerRequest
    ) -> McpServerDefinition:
        result = await self._require_kernel().update_mcp_server(server_id, payload)
        assert result.server is not None
        return result.server

    async def delete_mcp_server(
        self,
        server_id: UUID,
        payload: DeleteMcpServerRequest,
    ) -> dict[str, bool | str]:
        return await self._require_kernel().delete_mcp_server(server_id, payload)

    async def update_system_agent(
        self, agent_id: UUID, payload: UpdateSystemAgentRequest
    ) -> AgentDefinition:
        result = await self._require_kernel().update_system_agent(agent_id, payload)
        assert result.agent is not None
        return result.agent

    async def delete_system_agent(
        self,
        agent_id: UUID,
        payload: DeleteSystemAgentRequest,
    ) -> dict[str, bool | str]:
        return await self._require_kernel().delete_system_agent(agent_id, payload)

    async def create_git_repository(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None,
        payload: CreateGitRepositoryRequest,
    ) -> GitRepository:
        await self._git_publish.validate_repository(payload.local_path)
        result = await self._require_kernel().create_git_repository(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
            payload=payload,
        )
        assert result.repository is not None
        return result.repository

    async def get_git_repository(self, repo_id: UUID) -> GitRepository | None:
        return await self._require_kernel().get_git_repository(repo_id)

    async def validate_agent_bundle_from_git(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        payload: ValidateAgentBundleFromGitRequest,
    ) -> AgentBundleValidationResult:
        repository = await self._require_agent_bundle_repository(
            repository_id=payload.repository_id,
            scope=scope,
            organization_id=organization_id,
        )
        reader = GitAgentBundleReader(
            self._git_publish,
            repository_path=repository.local_path,
            revision=payload.revision or repository.default_branch,
        )
        try:
            compiled = await self._agent_bundle_compiler.compile(
                reader=reader,
                scope=scope,
                organization_id=organization_id,
                bundle_path=payload.bundle_path,
                created_by=payload.actor.participant_id,
                repository_id=repository.repo_id,
                resolved_revision=reader.resolved_revision,
            )
        except Exception as exc:
            return validation_error_result(
                scope=scope,
                organization_id=organization_id,
                repository_id=repository.repo_id,
                resolved_revision=reader.resolved_revision,
                bundle_path=payload.bundle_path,
                message=str(exc),
            )
        resolved_revision = reader.resolved_revision or await self._git_publish.resolve_revision(
            repository.local_path,
            payload.revision or repository.default_branch,
        )
        compiled_agent = compiled.agent.model_copy(
            update={
                "metadata": {
                    **compiled.agent.metadata,
                    "git_bundle": {
                        **compiled.agent.metadata.get("git_bundle", {}),
                        "resolved_revision": resolved_revision,
                    },
                }
            }
        )
        return AgentBundleValidationResult(
            valid=True,
            scope=scope,
            organization_id=organization_id,
            repository_id=repository.repo_id,
            resolved_revision=resolved_revision,
            bundle_path=payload.bundle_path,
            agent_key=compiled.agent.agent_key,
            compiled_agent=compiled_agent,
            source_files=compiled.source_files,
            metadata={
                "manifest_sha256": compiled.manifest_sha256,
                "skill_asset_refs": compiled.skill_asset_refs,
            },
        )

    async def publish_agent_bundle_from_git(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        payload: PublishAgentBundleFromGitRequest,
    ) -> AgentBundlePublishResult:
        validation = await self.validate_agent_bundle_from_git(
            scope=scope,
            organization_id=organization_id,
            payload=ValidateAgentBundleFromGitRequest(
                actor=payload.actor,
                repository_id=payload.repository_id,
                bundle_path=payload.bundle_path,
                revision=payload.revision,
                metadata=payload.metadata,
            ),
        )
        if not validation.valid or validation.compiled_agent is None:
            detail = validation.diagnostics[0].message if validation.diagnostics else "Invalid agent bundle"
            raise ValueError(detail)
        repository = await self._require_agent_bundle_repository(
            repository_id=payload.repository_id,
            scope=scope,
            organization_id=organization_id,
        )
        prompt_asset_id = None
        prompt_asset_version_id = None
        prompt_path = validation.source_files.get("prompt")
        if prompt_path is not None:
            prompt_version = await self.publish_asset_from_git(
                scope=scope,
                organization_id=organization_id,
                workspace_id=None,
                payload=PublishAssetFromGitRequest(
                    actor=payload.actor,
                    repository_id=repository.repo_id,
                    asset_type="agent_prompt",
                    logical_name=f"agent-{validation.agent_key}-prompt",
                    logical_path=prompt_path,
                    title=f"{validation.compiled_agent.display_name} Prompt",
                    description="Git-managed agent prompt.",
                    git_path=prompt_path,
                    revision=validation.resolved_revision,
                    content_type="text/markdown",
                    metadata={"agent_key": validation.agent_key, **payload.metadata},
                ),
            )
            prompt_asset_id = prompt_version.asset_id
            prompt_asset_version_id = prompt_version.asset_version_id

        skill_asset_refs: list[dict] = []
        for item in validation.metadata.get("skill_asset_refs", []):
            if not isinstance(item, dict) or not item.get("path"):
                continue
            skill_ref = str(item.get("ref") or "skill")
            skill_version = await self.publish_asset_from_git(
                scope=scope,
                organization_id=organization_id,
                workspace_id=None,
                payload=PublishAssetFromGitRequest(
                    actor=payload.actor,
                    repository_id=repository.repo_id,
                    asset_type="agent_skill",
                    logical_name=f"agent-{validation.agent_key}-{skill_ref.replace('://', '-').replace('/', '-')}",
                    logical_path=str(item["path"]),
                    title=str(item.get("title") or skill_ref),
                    description="Git-managed agent skill.",
                    git_path=str(item["path"]),
                    revision=validation.resolved_revision,
                    content_type="text/markdown",
                    metadata={"agent_key": validation.agent_key, **payload.metadata},
                ),
            )
            skill_asset_refs.append(
                {
                    **item,
                    "asset_id": str(skill_version.asset_id),
                    "asset_version_id": str(skill_version.asset_version_id),
                }
            )

        agent, version = await self._require_kernel().publish_git_managed_agent_definition(
            compiled_agent=validation.compiled_agent,
            git_repository_id=repository.repo_id,
            git_commit_sha=validation.resolved_revision or "",
            bundle_path=payload.bundle_path,
            manifest_sha256=str(validation.metadata.get("manifest_sha256") or ""),
            prompt_asset_id=prompt_asset_id,
            prompt_asset_version_id=prompt_asset_version_id,
            skill_asset_refs=skill_asset_refs,
            published_by=payload.actor.participant_id,
            metadata=payload.metadata,
        )
        validation = validation.model_copy(update={"compiled_agent": agent})
        return AgentBundlePublishResult(agent=agent, version=version, validation=validation)

    async def list_agent_definition_versions(
        self,
        agent_id: UUID,
    ) -> list[AgentDefinitionVersion]:
        return await self._require_kernel().list_agent_definition_versions(agent_id)

    async def activate_agent_definition_version(
        self,
        *,
        agent_id: UUID,
        agent_version_id: UUID,
        payload: ActivateAgentDefinitionVersionRequest,
    ) -> AgentBundlePublishResult:
        agent, version = await self._require_kernel().activate_agent_definition_version(
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            actor_id=payload.actor.participant_id,
            metadata=payload.metadata,
        )
        validation = AgentBundleValidationResult(
            valid=True,
            scope=agent.scope,
            organization_id=agent.organization_id,
            repository_id=version.git_repository_id,
            resolved_revision=version.git_commit_sha,
            bundle_path=version.bundle_path,
            agent_key=agent.agent_key,
            compiled_agent=agent,
            metadata={"activated_version": version.version},
        )
        return AgentBundlePublishResult(agent=agent, version=version, validation=validation)

    async def create_agent_git_worktree_session(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        payload: CreateAgentGitWorktreeSessionRequest,
    ) -> AgentGitWorktreeSession:
        repository = await self._require_agent_bundle_repository(
            repository_id=payload.repository_id,
            scope=scope,
            organization_id=organization_id,
        )
        session = await self._worktree_store.create_session(
            repository=repository,
            branch=payload.branch,
            bundle_path=payload.bundle_path,
            base_revision=payload.base_revision,
            actor=payload.actor,
            metadata=payload.metadata,
        )
        self._worktree_sessions[session.session_id] = session
        return session

    async def upload_agent_bundle_archive(
        self,
        *,
        scope: str,
        organization_id: UUID | None,
        actor: ParticipantInput,
        repository_id: UUID,
        branch: str,
        bundle_path: str,
        archive_bytes: bytes,
        publish: bool = False,
        base_revision: str | None = None,
        commit_message: str | None = None,
        metadata: dict | None = None,
    ) -> AgentBundleUploadResult:
        if len(archive_bytes) > settings.agent_bundle_max_archive_bytes:
            raise ValueError("Agent bundle archive exceeds maximum size")
        session = await self.create_agent_git_worktree_session(
            scope=scope,
            organization_id=organization_id,
            payload=CreateAgentGitWorktreeSessionRequest(
                actor=actor,
                repository_id=repository_id,
                branch=branch,
                bundle_path=bundle_path,
                base_revision=base_revision,
                metadata=metadata or {},
            ),
        )
        files = self._extract_agent_bundle_archive(archive_bytes)
        if len(files) > settings.agent_bundle_max_files:
            raise ValueError("Agent bundle archive contains too many files")
        for path, content in files.items():
            await self._worktree_store.write_file(
                session=session,
                path=self._archive_member_worktree_path(bundle_path, path),
                content=content,
            )
        commit = await self._worktree_store.commit(
            session=session,
            actor=actor,
            message=commit_message or f"Publish agent bundle {bundle_path}",
            push=True,
        )
        publish_result = None
        if publish:
            publish_result = await self.publish_agent_bundle_from_git(
                scope=scope,
                organization_id=organization_id,
                payload=PublishAgentBundleFromGitRequest(
                    actor=actor,
                    repository_id=repository_id,
                    bundle_path=bundle_path,
                    revision=commit.commit_sha,
                    metadata=metadata or {},
                ),
            )
        return AgentBundleUploadResult(
            session=session,
            commit=commit,
            publish_result=publish_result,
        )

    def _extract_agent_bundle_archive(self, archive_bytes: bytes) -> dict[str, str]:
        files: dict[str, str] = {}
        payload = io.BytesIO(archive_bytes)
        if zipfile.is_zipfile(payload):
            payload.seek(0)
            with zipfile.ZipFile(payload) as archive:
                for item in archive.infolist():
                    if item.is_dir():
                        continue
                    if item.file_size > settings.agent_bundle_max_file_bytes:
                        raise ValueError(f"Archive member {item.filename!r} is too large")
                    files[item.filename] = archive.read(item).decode("utf-8")
            return files
        payload.seek(0)
        try:
            with tarfile.open(fileobj=payload, mode="r:*") as archive:
                for item in archive.getmembers():
                    if item.isdir():
                        continue
                    if item.issym() or item.islnk():
                        raise ValueError("Agent bundle archives must not contain links")
                    if item.size > settings.agent_bundle_max_file_bytes:
                        raise ValueError(f"Archive member {item.name!r} is too large")
                    extracted = archive.extractfile(item)
                    if extracted is None:
                        continue
                    files[item.name] = extracted.read().decode("utf-8")
        except tarfile.TarError as exc:
            raise ValueError("Agent bundle archive must be a zip or tar archive") from exc
        return files

    def _archive_member_worktree_path(self, bundle_path: str, member_path: str) -> str:
        bundle_root = normalize_bundle_path(bundle_path)
        normalized_member = normalize_bundle_path(member_path)
        if normalized_member == bundle_root or normalized_member.startswith(f"{bundle_root}/"):
            return normalized_member
        return join_bundle_path(bundle_root, normalized_member)

    async def read_agent_git_worktree_file(
        self,
        session_id: UUID,
        path: str,
    ) -> AgentGitFileContent:
        session = self._require_worktree_session(session_id)
        return await self._worktree_store.read_file(session=session, path=path)

    async def write_agent_git_worktree_file(
        self,
        session_id: UUID,
        payload: AgentGitFileMutationRequest,
    ) -> AgentGitFileContent:
        if payload.content is None:
            raise ValueError("content is required when writing a file")
        session = self._require_worktree_session(session_id)
        return await self._worktree_store.write_file(
            session=session,
            path=payload.path,
            content=payload.content,
        )

    async def delete_agent_git_worktree_file(
        self,
        session_id: UUID,
        payload: AgentGitFileMutationRequest,
    ) -> dict[str, bool | str]:
        session = self._require_worktree_session(session_id)
        await self._worktree_store.delete_file(session=session, path=payload.path)
        return {"deleted": True, "path": payload.path}

    async def diff_agent_git_worktree(
        self,
        session_id: UUID,
    ) -> AgentGitDiffResult:
        session = self._require_worktree_session(session_id)
        return await self._worktree_store.diff(session=session)

    async def commit_agent_git_worktree(
        self,
        session_id: UUID,
        payload: AgentGitCommitRequest,
    ) -> AgentGitCommitResult:
        session = self._require_worktree_session(session_id)
        return await self._worktree_store.commit(
            session=session,
            actor=payload.actor,
            message=payload.message,
            push=payload.push,
        )

    async def discard_agent_git_worktree(
        self,
        session_id: UUID,
    ) -> dict[str, bool | str]:
        session = self._require_worktree_session(session_id)
        await self._worktree_store.discard(session=session)
        self._worktree_sessions.pop(session_id, None)
        return {"discarded": True, "session_id": str(session_id)}

    def _require_worktree_session(self, session_id: UUID) -> AgentGitWorktreeSession:
        try:
            return self._worktree_sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Git worktree session {session_id} not found") from exc

    def get_agent_git_worktree_session(
        self,
        session_id: UUID,
    ) -> AgentGitWorktreeSession | None:
        return self._worktree_sessions.get(session_id)

    async def _require_agent_bundle_repository(
        self,
        *,
        repository_id: UUID,
        scope: str,
        organization_id: UUID | None,
    ) -> GitRepository:
        repository = await self._require_kernel().get_git_repository(repository_id)
        if repository is None:
            raise KeyError(f"Git repository {repository_id} not found")
        if repository.scope != scope:
            raise ValueError(
                f"Git repository {repository_id} scope {repository.scope!r} does not match {scope!r}"
            )
        if repository.organization_id != organization_id:
            raise ValueError("Git repository organization binding does not match request scope")
        if repository.workspace_id is not None:
            raise ValueError("Agent bundle repositories must be system-wide or organization-wide")
        return repository

    async def list_git_repositories(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[GitRepository]:
        return await self._require_kernel().list_git_repositories(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def publish_asset_from_git(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None,
        payload: PublishAssetFromGitRequest,
    ) -> WorkspaceAssetVersion:
        resolved_organization_id = organization_id
        if scope == "workspace" and resolved_organization_id is None and workspace_id is not None:
            workspace = await self._require_kernel().get_workspace_detail(workspace_id)
            resolved_organization_id = workspace.workspace.organization_id
        repository = await self._require_kernel().get_git_repository(payload.repository_id)
        if repository is None:
            raise KeyError(f"Git repository {payload.repository_id} not found")
        content, resolved_revision = await self._git_publish.read_file(
            repository.local_path,
            payload.revision or repository.default_branch,
            payload.git_path,
        )
        content_type = payload.content_type or self._content_type_for_path(payload.git_path)
        object_key = self._asset_object_key(
            scope=scope,
            organization_id=resolved_organization_id,
            workspace_id=workspace_id,
            logical_name=payload.logical_name,
            git_path=payload.git_path,
            revision=resolved_revision,
        )
        stored = await self._storage.put_object(
            object_key=object_key,
            payload=content,
            content_type=content_type,
        )
        result = await self._require_kernel().publish_asset_from_git(
            scope=scope,
            organization_id=resolved_organization_id,
            workspace_id=workspace_id,
            payload=payload.model_copy(update={"revision": resolved_revision}),
            storage_backend="minio",
            bucket=stored.bucket,
            object_key=stored.object_key,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            content_type=stored.content_type,
        )
        assert result.version is not None
        return result.version

    async def upload_file_asset(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None,
        payload: UploadFileAssetRequest,
        filename: str,
        content: bytes,
    ) -> WorkspaceAssetVersion:
        resolved_organization_id = organization_id
        if scope == "workspace" and resolved_organization_id is None and workspace_id is not None:
            workspace = await self._require_kernel().get_workspace_detail(workspace_id)
            resolved_organization_id = workspace.workspace.organization_id
        content_type = payload.content_type or self._content_type_for_path(filename)
        object_key = self._direct_asset_object_key(
            scope=scope,
            organization_id=resolved_organization_id,
            workspace_id=workspace_id,
            logical_name=payload.logical_name,
            filename=filename,
        )
        stored = await self._storage.put_object(
            object_key=object_key,
            payload=content,
            content_type=content_type,
        )
        result = await self._require_kernel().publish_asset_from_upload(
            scope=scope,
            organization_id=resolved_organization_id,
            workspace_id=workspace_id,
            payload=payload.model_copy(
                update={
                    "content_type": content_type,
                    "metadata": {
                        **payload.metadata,
                        "filename": filename,
                    },
                }
            ),
            storage_backend="minio",
            bucket=stored.bucket,
            object_key=stored.object_key,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            content_type=stored.content_type,
        )
        assert result.version is not None
        return result.version

    async def list_workspace_assets(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[WorkspaceAsset]:
        return await self._require_kernel().list_workspace_assets(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def list_workspace_asset_versions(
        self,
        asset_id: UUID,
    ) -> list[WorkspaceAssetVersion]:
        return await self._require_kernel().list_workspace_asset_versions(asset_id)

    async def get_workspace_asset(self, asset_id: UUID) -> WorkspaceAsset | None:
        return await self._require_kernel().get_workspace_asset(asset_id)

    async def read_workspace_asset_version_bytes(
        self,
        asset_version_id: UUID,
    ) -> bytes:
        version = await self._require_kernel().get_workspace_asset_version(asset_version_id)
        if version is None:
            raise KeyError(f"Asset version {asset_version_id} not found")
        return await self._storage.get_object(object_key=version.object_key)

    async def create_retrieval_profile(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: CreateRetrievalProfileRequest,
    ) -> RetrievalProfile:
        result = await self._require_kernel().create_retrieval_profile(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
            payload=payload,
        )
        assert result.profile is not None
        return result.profile

    async def list_retrieval_profiles(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[RetrievalProfile]:
        return await self._require_kernel().list_retrieval_profiles(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def create_retrieval_corpus(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: CreateRetrievalCorpusRequest,
    ) -> RetrievalCorpus:
        result = await self._require_kernel().create_retrieval_corpus(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
            payload=payload,
        )
        assert result.corpus is not None
        return result.corpus

    async def list_retrieval_corpora(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[RetrievalCorpus]:
        return await self._require_kernel().list_retrieval_corpora(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def create_retrieval_source(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: CreateRetrievalSourceRequest,
    ) -> RetrievalSource:
        result = await self._require_kernel().create_retrieval_source(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
            payload=payload,
        )
        assert result.source is not None
        return result.source

    async def list_retrieval_sources(
        self,
        *,
        corpus_id: UUID | None = None,
        scope: str | None = None,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[RetrievalSource]:
        return await self._require_kernel().list_retrieval_sources(
            corpus_id=corpus_id,
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def create_retrieval_ingestion_job(
        self,
        *,
        corpus_id: UUID,
        payload: CreateRetrievalIngestionJobRequest,
    ) -> RetrievalIngestionJob:
        result = await self._require_kernel().create_retrieval_ingestion_job(
            corpus_id=corpus_id,
            payload=payload,
        )
        assert result.job is not None
        return result.job

    async def list_retrieval_ingestion_jobs(
        self,
        *,
        corpus_id: UUID | None = None,
        source_id: UUID | None = None,
        scope: str | None = None,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        status: str | None = None,
    ) -> list[RetrievalIngestionJob]:
        return await self._require_kernel().list_retrieval_ingestion_jobs(
            corpus_id=corpus_id,
            source_id=source_id,
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
            status=status,
        )

    async def list_retrieval_source_versions(
        self,
        source_id: UUID,
    ) -> list[RetrievalSourceVersion]:
        return await self._require_kernel().list_retrieval_source_versions(source_id)

    async def run_retrieval_search(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: RunRetrievalSearchRequest,
        embedding_vector: list[float] | None = None,
        embedding_provider_key: str | None = None,
        embedding_model: str | None = None,
    ) -> RetrievalSearchResponse:
        return await self._require_kernel().run_retrieval_search(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
            payload=payload,
            embedding_vector=embedding_vector,
            embedding_provider_key=embedding_provider_key,
            embedding_model=embedding_model,
        )

    async def create_retrieval_context_pack(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        payload: CreateRetrievalContextPackRequest,
        embedding_vector: list[float] | None = None,
        embedding_provider_key: str | None = None,
        embedding_model: str | None = None,
    ) -> RetrievalContextPack:
        result = await self._require_kernel().create_retrieval_context_pack(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
            payload=payload,
            embedding_vector=embedding_vector,
            embedding_provider_key=embedding_provider_key,
            embedding_model=embedding_model,
        )
        assert result.context_pack is not None
        return result.context_pack

    async def get_retrieval_context_pack(
        self,
        context_pack_id: UUID,
    ) -> RetrievalContextPack | None:
        return await self._require_kernel().get_retrieval_context_pack(context_pack_id)

    async def create_methodic_execution(
        self,
        workspace_id: UUID,
        payload: CreateMethodicExecutionRequest,
    ) -> MethodicExecutionDetail:
        result = await self._require_kernel().create_methodic_execution(workspace_id, payload)
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def list_methodic_executions(
        self,
        workspace_id: UUID,
        *,
        status: str | None = None,
    ) -> list[MethodicExecution]:
        return await self._require_kernel().list_methodic_executions(
            workspace_id,
            status=status,
        )

    async def get_methodic_execution(
        self,
        workspace_id: UUID,
        execution_id: UUID,
    ) -> MethodicExecutionDetail:
        return await self._require_kernel().get_methodic_execution(
            workspace_id,
            execution_id,
        )

    async def cancel_methodic_execution(
        self,
        workspace_id: UUID,
        execution_id: UUID,
        payload: CancelMethodicExecutionRequest,
    ) -> MethodicExecutionDetail:
        result = await self._require_kernel().cancel_methodic_execution(
            workspace_id,
            execution_id,
            payload,
        )
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def review_methodic_resource_request(
        self,
        workspace_id: UUID,
        resource_request_id: UUID,
        payload: ReviewMethodicResourceRequest,
        *,
        approved: bool,
    ) -> MethodicResourceRequest:
        result = await self._require_kernel().review_methodic_resource_request(
            workspace_id,
            resource_request_id,
            payload,
            approved=approved,
        )
        await self._publish_events(result.events)
        assert result.resource_request is not None
        return result.resource_request

    async def create_methodic_resource_request(
        self,
        workspace_id: UUID,
        execution_id: UUID,
        payload: CreateMethodicResourceRequestRequest,
    ) -> MethodicResourceRequest:
        result = await self._require_kernel().create_methodic_resource_request(
            workspace_id,
            execution_id,
            payload,
        )
        await self._publish_events(result.events)
        assert result.resource_request is not None
        return result.resource_request

    async def list_iam_role_definitions(
        self,
        *,
        subject_kind: str,
        scope: str | None = None,
        organization_id: UUID | None = None,
    ) -> list[IamRoleDefinition]:
        return await self._require_kernel().list_iam_role_definitions(
            subject_kind=subject_kind,
            scope=scope,
            organization_id=organization_id,
        )

    async def get_iam_role_definition(self, role_id: UUID) -> IamRoleDefinition | None:
        return await self._require_kernel().get_iam_role_definition(role_id)

    async def create_iam_role_definition(
        self,
        payload: CreateIamRoleRequest,
        *,
        subject_kind: str,
        scope: str,
        organization_id: UUID | None = None,
    ) -> IamRoleDefinition:
        result = await self._require_kernel().create_iam_role_definition(
            payload,
            subject_kind=subject_kind,
            scope=scope,
            organization_id=organization_id,
        )
        assert result.role is not None
        return result.role

    async def update_iam_role_definition(
        self,
        role_id: UUID,
        payload: UpdateIamRoleRequest,
    ) -> IamRoleDefinition:
        result = await self._require_kernel().update_iam_role_definition(role_id, payload)
        assert result.role is not None
        return result.role

    async def delete_iam_role_definition(self, role_id: UUID) -> dict[str, bool | str]:
        return await self._require_kernel().delete_iam_role_definition(role_id)

    async def list_human_roles_for_user(
        self,
        *,
        user_id: UUID,
        organization_id: UUID | None = None,
    ) -> list[IamRoleDefinition]:
        return await self._require_kernel().list_human_roles_for_user(
            user_id=user_id,
            organization_id=organization_id,
        )

    async def bind_human_role(
        self,
        user_id: UUID,
        role_id: UUID,
        payload: BindHumanRoleRequest,
    ) -> dict[str, str]:
        return await self._require_kernel().bind_human_role(user_id, role_id, payload)

    async def unbind_human_role(
        self,
        user_id: UUID,
        role_id: UUID,
    ) -> dict[str, bool | str]:
        return await self._require_kernel().unbind_human_role(user_id, role_id)

    async def list_agent_identities(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
    ) -> list[AgentIdentity]:
        return await self._require_kernel().list_agent_identities(
            scope=scope,
            organization_id=organization_id,
        )

    async def get_agent_identity(self, agent_identity_id: UUID) -> AgentIdentity | None:
        return await self._require_kernel().get_agent_identity(agent_identity_id)

    async def store_agent_identity(self, identity: AgentIdentity) -> AgentIdentity:
        result = await self._require_kernel().store_agent_identity(identity)
        assert result.identity is not None
        return result.identity

    async def list_agent_roles_for_identity(
        self,
        *,
        agent_identity_id: UUID,
    ) -> list[IamRoleDefinition]:
        return await self._require_kernel().list_agent_roles_for_identity(
            agent_identity_id=agent_identity_id
        )

    async def bind_agent_role(
        self,
        agent_identity_id: UUID,
        role_id: UUID,
        payload: BindAgentRoleRequest,
    ) -> dict[str, str]:
        return await self._require_kernel().bind_agent_role(agent_identity_id, role_id, payload)

    async def unbind_agent_role(
        self,
        agent_identity_id: UUID,
        role_id: UUID,
    ) -> dict[str, bool | str]:
        return await self._require_kernel().unbind_agent_role(agent_identity_id, role_id)

    async def get_workspace_asset_version(
        self,
        asset_version_id: UUID,
    ) -> WorkspaceAssetVersion | None:
        return await self._require_kernel().get_workspace_asset_version(asset_version_id)

    async def activate_asset_version(
        self,
        asset_id: UUID,
        payload: ActivateAssetVersionRequest,
    ) -> AssetLink:
        result = await self._require_kernel().activate_asset_version(asset_id, payload)
        assert result.link is not None
        return result.link

    async def link_asset_version(
        self,
        asset_id: UUID,
        payload: LinkAssetRequest,
    ) -> AssetLink:
        result = await self._require_kernel().link_asset_version(asset_id, payload)
        assert result.link is not None
        return result.link

    async def get_asset_download_url(
        self,
        asset_id: UUID,
        *,
        asset_version_id: UUID | None = None,
    ) -> str:
        asset = await self._require_kernel().get_workspace_asset(asset_id)
        if asset is None:
            raise KeyError(f"Workspace asset {asset_id} not found")
        version = None
        if asset_version_id is not None:
            version = await self._require_kernel().get_workspace_asset_version(asset_version_id)
            if version is None or version.asset_id != asset_id:
                raise KeyError(
                    f"Asset version {asset_version_id} does not belong to asset {asset_id}"
                )
        else:
            versions = await self._require_kernel().list_workspace_asset_versions(asset_id)
            if not versions:
                raise KeyError(f"Workspace asset {asset_id} has no published versions")
            version = versions[-1]
        return self._storage.presign_get(
            object_key=version.object_key,
            expires_seconds=settings.asset_storage_presign_expiry_seconds,
        )

    async def list_resolved_agent_assets(
        self,
        *,
        agent_id: UUID,
        workspace_id: UUID | None = None,
    ) -> list[ResolvedAssetBinding]:
        return await self._require_kernel().list_resolved_agent_assets(
            agent_id=agent_id,
            workspace_id=workspace_id,
        )

    async def list_resolved_tool_assets(
        self,
        *,
        tool_id: UUID,
        workspace_id: UUID | None = None,
    ) -> list[ResolvedAssetBinding]:
        return await self._require_kernel().list_resolved_tool_assets(
            tool_id=tool_id,
            workspace_id=workspace_id,
        )

    async def delete_llm_provider(
        self,
        provider_id: UUID,
        payload: DeleteLlmProviderRequest,
    ) -> dict[str, bool | str]:
        return await self._require_kernel().delete_llm_provider(provider_id, payload)

    async def delete_memory_provider(
        self,
        provider_id: UUID,
        payload: DeleteMemoryProviderRequest,
    ) -> dict[str, bool | str]:
        return await self._require_kernel().delete_memory_provider(provider_id, payload)

    async def upsert_role_definition(
        self,
        workspace_id: UUID,
        payload: UpsertRoleDefinitionRequest,
    ) -> RoleDefinition:
        logger.debug(
            "Service upsert_role_definition workspace_id=%s actor_id=%s name=%r",
            workspace_id,
            payload.actor.participant_id,
            payload.name,
        )
        result = await self._require_kernel().upsert_role_definition(workspace_id, payload)
        await self._publish_events(result.events)
        assert result.role_definition is not None
        return result.role_definition

    async def delete_role_definition(
        self,
        workspace_id: UUID,
        role_name: str,
        payload: DeleteRoleDefinitionRequest,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Service delete_role_definition workspace_id=%s actor_id=%s role_name=%r",
            workspace_id,
            payload.actor.participant_id,
            role_name,
        )
        return await self._require_kernel().delete_role_definition(
            workspace_id,
            role_name,
            payload,
        )

    async def list_workspace_tools(self, workspace_id: UUID) -> list[WorkspaceTool]:
        logger.debug("Service list_workspace_tools workspace_id=%s", workspace_id)
        return await self._require_kernel().list_workspace_tools(workspace_id)

    async def list_workspace_mcp_servers(self, workspace_id: UUID) -> list[WorkspaceMcpServer]:
        return await self._require_kernel().list_workspace_mcp_servers(workspace_id)

    async def list_workspace_mcp_tools(self, workspace_id: UUID) -> list[WorkspaceMcpTool]:
        return await self._require_kernel().list_workspace_mcp_tools(workspace_id)

    async def list_workspace_mcp_resources(self, workspace_id: UUID) -> list[WorkspaceMcpResource]:
        return await self._require_kernel().list_workspace_mcp_resources(workspace_id)

    async def list_workspace_mcp_prompts(self, workspace_id: UUID) -> list[WorkspaceMcpPrompt]:
        return await self._require_kernel().list_workspace_mcp_prompts(workspace_id)

    async def attach_workspace_mcp_server(
        self,
        workspace_id: UUID,
        payload: AttachWorkspaceMcpServerRequest,
    ) -> WorkspaceMcpServer:
        result = await self._require_kernel().attach_workspace_mcp_server(workspace_id, payload)
        assert result.binding is not None
        return result.binding

    async def update_workspace_mcp_server(
        self,
        workspace_id: UUID,
        server_id: UUID,
        payload: UpdateWorkspaceMcpServerRequest,
    ) -> WorkspaceMcpServer:
        result = await self._require_kernel().update_workspace_mcp_server(
            workspace_id,
            server_id,
            payload,
        )
        assert result.binding is not None
        return result.binding

    async def delete_workspace_mcp_server(
        self,
        workspace_id: UUID,
        server_id: UUID,
        payload: DeleteWorkspaceMcpServerRequest,
    ) -> dict[str, bool | str]:
        return await self._require_kernel().delete_workspace_mcp_server(
            workspace_id,
            server_id,
            payload,
        )

    async def attach_workspace_tool(
        self,
        workspace_id: UUID,
        payload: AttachWorkspaceToolRequest,
    ) -> WorkspaceTool:
        logger.debug(
            "Service attach_workspace_tool workspace_id=%s actor_id=%s tool_id=%s",
            workspace_id,
            payload.actor.participant_id,
            payload.tool_id,
        )
        result = await self._require_kernel().attach_workspace_tool(workspace_id, payload)
        await self._publish_events(result.events)
        assert result.tool is not None
        return result.tool

    async def update_workspace_tool(
        self,
        workspace_id: UUID,
        tool_id: UUID,
        payload: UpdateWorkspaceToolRequest,
    ) -> WorkspaceTool:
        logger.debug(
            "Service update_workspace_tool workspace_id=%s actor_id=%s tool_id=%s",
            workspace_id,
            payload.actor.participant_id,
            tool_id,
        )
        result = await self._require_kernel().update_workspace_tool(
            workspace_id,
            tool_id,
            payload,
        )
        await self._publish_events(result.events)
        assert result.tool is not None
        return result.tool

    async def delete_workspace_tool(
        self,
        workspace_id: UUID,
        tool_id: UUID,
        payload: DeleteWorkspaceToolRequest,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Service delete_workspace_tool workspace_id=%s actor_id=%s tool_id=%s",
            workspace_id,
            payload.actor.participant_id,
            tool_id,
        )
        return await self._require_kernel().delete_workspace_tool(
            workspace_id,
            tool_id,
            payload,
        )

    async def get_runtime_overview(
        self,
        *,
        organization_id: UUID | None = None,
    ) -> dict[str, object]:
        return await self._require_kernel().get_runtime_overview(
            organization_id=organization_id,
        )

    async def assume_participant_role(
        self,
        workspace_id: UUID,
        participant_id: UUID,
        payload: AssumeParticipantRoleRequest,
    ):
        logger.debug(
            "Service assume_participant_role workspace_id=%s participant_id=%s actor_id=%s role=%r",
            workspace_id,
            participant_id,
            payload.actor.participant_id,
            payload.role,
        )
        result = await self._require_kernel().assume_participant_role(
            workspace_id,
            participant_id,
            payload,
        )
        await self._publish_events(result.events)
        assert result.participant is not None
        return result.participant

    async def create_agent_participant(
        self,
        workspace_id: UUID,
        payload: CreateAgentParticipantRequest,
    ):
        logger.debug(
            "Service attach_agent_to_workspace workspace_id=%s actor_id=%s agent_id=%s",
            workspace_id,
            payload.actor.participant_id,
            payload.agent_id,
        )
        result = await self._require_kernel().create_agent_participant(workspace_id, payload)
        await self._publish_events(result.events)
        assert result.participant is not None
        return result.participant

    async def update_agent_participant(
        self,
        workspace_id: UUID,
        participant_id: UUID,
        payload: UpdateAgentParticipantRequest,
    ):
        logger.debug(
            "Service update_agent_participant workspace_id=%s participant_id=%s actor_id=%s",
            workspace_id,
            participant_id,
            payload.actor.participant_id,
        )
        result = await self._require_kernel().update_agent_participant(
            workspace_id,
            participant_id,
            payload,
        )
        await self._publish_events(result.events)
        assert result.participant is not None
        return result.participant

    async def create_thread(
        self, workspace_id: UUID, payload: CreateThreadRequest
    ) -> ThreadDetail:
        logger.debug(
            "Service create_thread workspace_id=%s participant_id=%s title=%r",
            workspace_id,
            payload.actor.participant_id,
            payload.title,
        )
        result = await self._require_kernel().create_thread(workspace_id, payload)
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def list_threads(self, workspace_id: UUID) -> list[Thread]:
        return await self._require_kernel().list_threads(workspace_id)

    async def get_thread(self, thread_id: UUID) -> ThreadDetail:
        logger.debug("Service get_thread thread_id=%s", thread_id)
        return await self._require_kernel().get_thread_detail(thread_id)

    async def get_timeline(
        self,
        thread_id: UUID,
        *,
        viewer: ParticipantInput | None = None,
    ) -> TimelinePage:
        logger.debug("Service get_timeline thread_id=%s", thread_id)
        return await self._require_kernel().get_thread_timeline(
            thread_id,
            viewer=viewer,
        )

    async def list_workspace_communication_log(
        self,
        workspace_id: UUID,
        *,
        thread_id: UUID | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> WorkspaceCommunicationLogPage:
        logger.debug(
            "Service list_workspace_communication_log workspace_id=%s thread_id=%s limit=%s offset=%s",
            workspace_id,
            thread_id,
            limit,
            offset,
        )
        return await self._require_kernel().list_workspace_communication_log(
            workspace_id,
            thread_id=thread_id,
            limit=limit,
            offset=offset,
        )

    async def post_message(
        self, thread_id: UUID, payload: CreateMessageRequest
    ) -> TimelineMessage:
        logger.debug(
            "Service post_message thread_id=%s participant_id=%s visibility=%s create_task=%s",
            thread_id,
            payload.actor.participant_id,
            payload.visibility,
            payload.create_task,
        )
        result = await self._require_kernel().post_message(thread_id, payload)
        await self._publish_events(result.events)
        assert result.message is not None
        return result.message

    async def list_tool_generation_requests(
        self,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        thread_id: UUID | None = None,
        status: str | None = None,
    ) -> list[ToolGenerationRequestDetail]:
        return await self._require_kernel().list_tool_generation_requests(
            organization_id=organization_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            status=status,
        )

    async def list_thread_tool_generation_requests(
        self,
        thread_id: UUID,
    ) -> list[ToolGenerationRequestDetail]:
        return await self._require_kernel().list_thread_tool_generation_requests(thread_id)

    async def get_tool_generation_request(
        self,
        request_id: UUID,
    ) -> ToolGenerationRequestDetail:
        return await self._require_kernel().get_tool_generation_request(request_id)

    async def create_tool_generation_revision(
        self,
        request_id: UUID,
        payload: CreateToolGenerationRevisionRequest,
    ) -> ToolGenerationRequestDetail:
        result = await self._require_kernel().create_tool_generation_revision(request_id, payload)
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def approve_tool_generation_revision(
        self,
        revision_id: UUID,
        payload: ReviewToolGenerationRevisionRequest,
    ) -> ToolGenerationRequestDetail:
        result = await self._require_kernel().approve_tool_generation_revision(
            revision_id,
            payload,
        )
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def reject_tool_generation_revision(
        self,
        revision_id: UUID,
        payload: ReviewToolGenerationRevisionRequest,
    ) -> ToolGenerationRequestDetail:
        result = await self._require_kernel().reject_tool_generation_revision(
            revision_id,
            payload,
        )
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def list_interaction_requests(
        self,
        thread_id: UUID,
    ) -> list[InteractionRequestDetail]:
        logger.debug("Service list_interaction_requests thread_id=%s", thread_id)
        return await self._require_kernel().list_interaction_requests(thread_id)

    async def get_interaction_request(
        self,
        request_id: UUID,
    ) -> InteractionRequestDetail:
        logger.debug("Service get_interaction_request request_id=%s", request_id)
        return await self._require_kernel().get_interaction_request(request_id)

    async def create_interaction_requests(
        self,
        thread_id: UUID,
        payload: CreateInteractionRequestsRequest,
    ) -> list[InteractionRequestDetail]:
        logger.debug(
            "Service create_interaction_requests thread_id=%s participant_id=%s request_count=%s",
            thread_id,
            payload.actor.participant_id,
            len(payload.requests),
        )
        result = await self._require_kernel().create_interaction_requests(thread_id, payload)
        await self._publish_events(result.events)
        return result.details

    async def update_interaction_request(
        self,
        request_id: UUID,
        payload: UpdateInteractionRequestRequest,
    ) -> InteractionRequestDetail:
        logger.debug(
            "Service update_interaction_request request_id=%s participant_id=%s action=%s",
            request_id,
            payload.actor.participant_id,
            payload.action,
        )
        result = await self._require_kernel().update_interaction_request(request_id, payload)
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def answer_interaction_request(
        self,
        request_id: UUID,
        payload: CreateInteractionAnswerRequest,
    ) -> InteractionRequestDetail:
        logger.debug(
            "Service answer_interaction_request request_id=%s participant_id=%s question_count=%s",
            request_id,
            payload.actor.participant_id,
            len(payload.question_ids),
        )
        result = await self._require_kernel().answer_interaction_request(request_id, payload)
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def list_memory_entries(self, workspace_id: UUID) -> list[MemoryEntry]:
        logger.debug("Service list_memory_entries workspace_id=%s", workspace_id)
        return await self._require_kernel().list_memory_entries(workspace_id)

    async def list_thread_memory_entries(self, thread_id: UUID) -> list[MemoryEntry]:
        logger.debug("Service list_thread_memory_entries thread_id=%s", thread_id)
        return await self._require_kernel().list_thread_memory_entries(thread_id)

    async def create_memory_entry(
        self, workspace_id: UUID, payload: CreateMemoryEntryRequest
    ) -> MemoryEntry:
        logger.debug(
            "Service create_memory_entry workspace_id=%s participant_id=%s entry_type=%s",
            workspace_id,
            payload.actor.participant_id,
            payload.entry_type,
        )
        result = await self._require_kernel().create_memory_entry(workspace_id, payload)
        await self._publish_events(result.events)
        assert result.entry is not None
        return result.entry

    async def create_thread_memory_entry(
        self, thread_id: UUID, payload: CreateThreadMemoryRequest
    ) -> MemoryEntry:
        logger.debug(
            "Service create_thread_memory_entry thread_id=%s participant_id=%s entry_type=%s",
            thread_id,
            payload.actor.participant_id,
            payload.entry_type,
        )
        result = await self._require_kernel().create_thread_memory_entry(thread_id, payload)
        await self._publish_events(result.events)
        assert result.entry is not None
        return result.entry

    async def confirm_workspace_memory(
        self, workspace_id: UUID, payload: ConfirmWorkspaceMemoryRequest
    ) -> MemoryEntry:
        logger.debug(
            "Service confirm_workspace_memory workspace_id=%s participant_id=%s source_memory_entry_id=%s",
            workspace_id,
            payload.actor.participant_id,
            payload.source_memory_entry_id,
        )
        result = await self._require_kernel().confirm_workspace_memory(workspace_id, payload)
        await self._publish_events(result.events)
        assert result.entry is not None
        return result.entry

    async def update_memory_entry(
        self,
        workspace_id: UUID,
        memory_entry_id: UUID,
        payload: UpdateMemoryEntryRequest,
    ) -> MemoryEntry:
        logger.debug(
            "Service update_memory_entry workspace_id=%s memory_entry_id=%s participant_id=%s",
            workspace_id,
            memory_entry_id,
            payload.actor.participant_id,
        )
        result = await self._require_kernel().update_memory_entry(
            workspace_id, memory_entry_id, payload
        )
        await self._publish_events(result.events)
        assert result.entry is not None
        return result.entry

    async def update_thread_memory_entry(
        self,
        thread_id: UUID,
        memory_entry_id: UUID,
        payload: UpdateMemoryEntryRequest,
    ) -> MemoryEntry:
        logger.debug(
            "Service update_thread_memory_entry thread_id=%s memory_entry_id=%s participant_id=%s",
            thread_id,
            memory_entry_id,
            payload.actor.participant_id,
        )
        result = await self._require_kernel().update_thread_memory_entry(
            thread_id, memory_entry_id, payload
        )
        await self._publish_events(result.events)
        assert result.entry is not None
        return result.entry

    async def delete_memory_entry(
        self,
        workspace_id: UUID,
        memory_entry_id: UUID,
        actor: ParticipantInput,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Service delete_memory_entry workspace_id=%s memory_entry_id=%s participant_id=%s",
            workspace_id,
            memory_entry_id,
            actor.participant_id,
        )
        events = await self._require_kernel().delete_memory_entry(
            workspace_id, memory_entry_id, actor
        )
        await self._publish_events(events)
        return {"deleted": True, "memory_entry_id": str(memory_entry_id)}

    async def delete_thread_memory_entry(
        self,
        thread_id: UUID,
        memory_entry_id: UUID,
        actor: ParticipantInput,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Service delete_thread_memory_entry thread_id=%s memory_entry_id=%s participant_id=%s",
            thread_id,
            memory_entry_id,
            actor.participant_id,
        )
        events = await self._require_kernel().delete_thread_memory_entry(
            thread_id, memory_entry_id, actor
        )
        await self._publish_events(events)
        return {"deleted": True, "memory_entry_id": str(memory_entry_id)}

    async def search_thread_memory(
        self,
        thread_id: UUID,
        payload: SearchMemoryRequest,
    ) -> MemorySearchResponse:
        logger.debug(
            "Service search_thread_memory thread_id=%s participant_id=%s provider=%s",
            thread_id,
            payload.actor.participant_id,
            payload.use_provider,
        )
        return await self._require_kernel().search_thread_memory(thread_id, payload)

    async def publish_presence(
        self,
        *,
        thread_id: UUID,
        actor: ParticipantInput,
        status: str,
        connection_id: str | None = None,
    ) -> EventEnvelope:
        logger.debug(
            "Service publish_presence thread_id=%s participant_id=%s status=%s connection_id=%s",
            thread_id,
            actor.participant_id,
            status,
            connection_id,
        )
        event = await self._require_kernel().publish_presence(
            thread_id=thread_id,
            actor_input=actor,
            status=status,
            connection_id=connection_id,
        )
        await self._publish_events([event])
        return event

    async def on_thread_connected(
        self,
        *,
        thread_id: UUID,
        actor: ParticipantInput,
        connection_id: str,
    ) -> EventEnvelope:
        logger.debug(
            "Service on_thread_connected thread_id=%s participant_id=%s connection_id=%s",
            thread_id,
            actor.participant_id,
            connection_id,
        )
        workspace_id = await self._workspace_id_for_thread(thread_id)
        await register_thread_connection(
            workspace_id=workspace_id,
            thread_id=thread_id,
            participant_id=actor.participant_id,
            connection_id=connection_id,
            status="active",
        )
        return await self.publish_presence(
            thread_id=thread_id,
            actor=actor,
            status="active",
            connection_id=connection_id,
        )

    async def on_thread_disconnected(
        self,
        *,
        thread_id: UUID,
        actor: ParticipantInput,
        connection_id: str,
    ) -> EventEnvelope:
        logger.debug(
            "Service on_thread_disconnected thread_id=%s participant_id=%s connection_id=%s",
            thread_id,
            actor.participant_id,
            connection_id,
        )
        workspace_id = await self._workspace_id_for_thread(thread_id)
        remaining_connection = await unregister_thread_connection(
            workspace_id=workspace_id,
            thread_id=thread_id,
            participant_id=actor.participant_id,
            connection_id=connection_id,
        )
        status = "active" if remaining_connection is not None else "offline"
        publish_connection_id = (
            remaining_connection.get("connection_id")
            if remaining_connection is not None
            else connection_id
        )
        return await self.publish_presence(
            thread_id=thread_id,
            actor=actor,
            status=status,
            connection_id=publish_connection_id,
        )

    async def stream_thread_events(
        self,
        thread_id: UUID,
        *,
        after_sequence: int | None = None,
        follow: bool = True,
        viewer: ParticipantInput | None = None,
    ) -> AsyncIterator[EventEnvelope]:
        logger.debug(
            "Service stream_thread_events thread_id=%s after_sequence=%s follow=%s viewer=%s",
            thread_id,
            after_sequence,
            follow,
            viewer.participant_id if viewer else None,
        )
        kernel = self._require_kernel()
        replay_events = await kernel.list_thread_events(
            thread_id, after_sequence=after_sequence
        )
        for event in replay_events:
            if self._event_visible_to_viewer(event, viewer):
                yield event
        if not follow:
            return
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        key = str(thread_id)
        self._subscriptions[key].add(queue)
        logger.debug(
            "Service stream subscribed thread_id=%s subscriber_count=%s",
            thread_id,
            len(self._subscriptions[key]),
        )
        try:
            while True:
                event = await queue.get()
                if self._event_visible_to_viewer(event, viewer):
                    yield event
        finally:
            self._subscriptions[key].discard(queue)
            if not self._subscriptions[key]:
                self._subscriptions.pop(key, None)
            logger.debug(
                "Service stream unsubscribed thread_id=%s remaining_subscribers=%s",
                thread_id,
                len(self._subscriptions.get(key, set())),
            )

    async def touch_presence(
        self,
        *,
        thread_id: UUID,
        actor: ParticipantInput,
        connection_id: str | None = None,
        status: str = "active",
    ) -> None:
        logger.debug(
            "Service touch_presence thread_id=%s participant_id=%s status=%s connection_id=%s",
            thread_id,
            actor.participant_id,
            status,
            connection_id,
        )
        await touch_thread_presence(
            workspace_id=await self._workspace_id_for_thread(thread_id),
            thread_id=thread_id,
            participant_id=actor.participant_id,
            connection_id=connection_id,
            status=status,
        )

    async def _publish_events(self, events: list[EventEnvelope]) -> None:
        for event in events:
            logger.debug(
                "Service publish_event event_type=%s thread_id=%s workspace_id=%s sequence=%s visibility=%s",
                event.event_type,
                event.thread_id,
                event.workspace_id,
                event.sequence,
                event.visibility,
            )
            await event_service.publish_event(event)

    async def _handle_published_event(self, event: EventEnvelope) -> None:
        for queue in list(self._subscriptions.get(str(event.thread_id), set())):
            await queue.put(event)

    def _require_kernel(self) -> CollaborationKernel:
        if self._kernel is None:
            raise RuntimeError("Collaboration service is not started")
        return self._kernel

    async def _workspace_id_for_thread(self, thread_id: UUID) -> UUID:
        detail = await self._require_kernel().get_thread_detail(thread_id)
        return detail.thread.workspace_id

    async def _overlay_workspace_presence(
        self,
        *,
        workspace_id: UUID,
        participants: list[ParticipantProfile],
    ) -> list[ParticipantProfile]:
        enriched: list[ParticipantProfile] = []
        for participant in participants:
            try:
                presence = await get_workspace_participant_presence(
                    workspace_id=workspace_id,
                    participant_id=participant.participant_id,
                )
            except RuntimeError:
                presence = None
            if presence is None:
                enriched.append(participant)
                continue
            status = presence.get("status")
            if status is None:
                enriched.append(participant)
                continue
            enriched.append(participant.model_copy(update={"status": status}))
        return enriched

    @staticmethod
    def _content_type_for_path(path: str) -> str:
        lowered = path.lower()
        if lowered.endswith(".md"):
            return "text/markdown"
        if lowered.endswith(".json"):
            return "application/json"
        if lowered.endswith(".yaml") or lowered.endswith(".yml"):
            return "application/yaml"
        if lowered.endswith(".txt"):
            return "text/plain"
        return "application/octet-stream"

    @staticmethod
    def _asset_object_key(
        *,
        scope: str,
        organization_id: UUID | None,
        workspace_id: UUID | None,
        logical_name: str,
        git_path: str,
        revision: str,
    ) -> str:
        normalized_name = logical_name.replace("/", "_")
        file_name = git_path.rsplit("/", 1)[-1]
        if scope == "global":
            prefix = "global"
        elif scope == "organization":
            prefix = f"organizations/{organization_id}"
        else:
            prefix = f"organizations/{organization_id}/workspaces/{workspace_id}"
        return f"{prefix}/assets/{normalized_name}/{revision}/{file_name}"

    @staticmethod
    def _direct_asset_object_key(
        *,
        scope: str,
        organization_id: UUID | None,
        workspace_id: UUID | None,
        logical_name: str,
        filename: str,
    ) -> str:
        normalized_name = logical_name.replace("/", "_")
        file_name = filename.rsplit("/", 1)[-1] or "upload.bin"
        if scope == "global":
            prefix = "global"
        elif scope == "organization":
            prefix = f"organizations/{organization_id}"
        else:
            prefix = f"organizations/{organization_id}/workspaces/{workspace_id}"
        return f"{prefix}/files/{normalized_name}/{uuid4()}/{file_name}"

    @staticmethod
    def _event_visible_to_viewer(
        event: EventEnvelope,
        viewer: ParticipantInput | None,
    ) -> bool:
        if viewer is None:
            return True
        if event.visibility in {"public", "workspace"}:
            return True
        if event.visibility == "agents_only":
            return viewer.participant_type == "agent"
        if event.visibility == "private":
            return (
                event.actor.id == viewer.participant_id
                or (
                    event.target.type == "participant"
                    and event.target.id == viewer.participant_id
                )
            )
        return False


collaboration_service = CollaborationService()
