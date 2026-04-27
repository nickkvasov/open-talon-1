from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from open_talon_contracts.iam import PROJECT_ROLE_BASE_PERMISSIONS
from open_talon_contracts.models import normalize_organization_slug
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from gateway_edge.auth.api_key import validate_api_key
from gateway_edge.auth.identity import sync_oidc_auth_context
from gateway_edge.auth.oidc import validate_oidc_token
from gateway_edge.auth.openbao import validate_openbao_token
from gateway_edge.authz import has_admin_access, require_admin_access
from gateway_edge.config import settings
from gateway_edge.iam.authorization import authorization_engine
from gateway_edge.models import (
    ActivateAssetVersionRequest,
    ActivateAgentDefinitionVersionRequest,
    AuthContext,
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
    AuditChainVerificationResult,
    AuditEvent,
    AuditEventPage,
    AuditExportRequest,
    AuditExportResult,
    AttachWorkspaceToolRequest,
    AttachWorkspaceMcpServerRequest,
    AssetLink,
    CreateGitRepositoryRequest,
    CreateAgentGitWorktreeSessionRequest,
    CreateAgentParticipantRequest,
    CreateInteractionAnswerRequest,
    CreateInteractionRequestsRequest,
    CreateLlmProviderRequest,
    CreateMemoryProviderRequest,
    CreateMcpServerRequest,
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
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderHealthReport,
    MemorySearchResponse,
    McpPromptDefinition,
    McpResourceDefinition,
    McpServerDefinition,
    McpToolDefinition,
    RuntimeOverviewResponse,
    LlmEngineDescriptor,
    LlmProviderDefinition,
    LlmProviderHealthReport,
    GitRepository,
    InteractionRequestDetail,
    LinkAssetRequest,
    Organization,
    OrganizationMembership,
    ParticipantInput,
    ParticipantProfile,
    Project,
    ProjectAccessBinding,
    ProjectSubjectRef,
    PublishAssetFromGitRequest,
    PublishAgentBundleFromGitRequest,
    RetrievalContextPack,
    RetrievalCorpus,
    RetrievalIngestionJob,
    RetrievalProfile,
    RetrievalSearchResponse,
    RetrievalSource,
    ResolvedAssetBinding,
    RoleDefinition,
    RunRetrievalSearchRequest,
    SystemToolDefinition,
    Thread,
    ThreadDetail,
    TimelineMessage,
    TimelinePage,
    ToolGenerationRequestDetail,
    WorkspaceCommunicationLogPage,
    UpdateSystemAgentRequest,
    UpdateInteractionRequestRequest,
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
    RemoveProjectAccessRequest,
    UpdateWorkspaceToolRequest,
    UpdateWorkspaceMcpServerRequest,
    UpdateWorkspaceRequest,
    Workspace,
    WorkspaceAsset,
    WorkspaceAssetVersion,
    WorkspaceDetail,
    WorkspaceMcpPrompt,
    WorkspaceMcpResource,
    WorkspaceMcpServer,
    WorkspaceMcpTool,
    WorkspaceTool,
    ValidateAgentBundleFromGitRequest,
    AddOrganizationMemberRequest,
    RemoveOrganizationMemberRequest,
    UploadFileAssetRequest,
)
from gateway_edge.services import collaboration as collab_svc
from gateway_edge.services.audit import audit_service
from gateway_edge.services.llm_provider_health import check_llm_provider_health
from gateway_edge.services.memory_provider_health import check_memory_provider_health
from gateway_edge.services.llm_registry import list_registered_llm_engines
from gateway_edge.services.operational_bootstrap import operational_bootstrap_service

router = APIRouter(prefix="/v1", tags=["collaboration"])
logger = logging.getLogger(__name__)


class _AttachWorkspaceToolBody(BaseModel):
    actor: ParticipantInput
    enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)


def _actor_log(actor: ParticipantInput) -> dict[str, str]:
    return {
        "participant_id": str(actor.participant_id),
        "participant_type": actor.participant_type,
        "display_name": actor.display_name,
    }


def _participant_from_ws(
    *,
    participant_id: UUID,
    participant_type: str,
    display_name: str,
) -> ParticipantInput:
    return ParticipantInput(
        participant_id=participant_id,
        participant_type=participant_type,
        display_name=display_name,
    )


def _request_auth_context(request: Request) -> AuthContext | None:
    auth_context = getattr(request.state, "auth_context", None)
    return auth_context if isinstance(auth_context, AuthContext) else None


def _oidc_auth_context(request: Request) -> AuthContext | None:
    auth_context = _request_auth_context(request)
    if auth_context is None or auth_context.kind != "oidc":
        return None
    return auth_context


def _user_auth_context(request: Request) -> AuthContext | None:
    auth_context = _oidc_auth_context(request)
    if auth_context is None or auth_context.principal_type != "human":
        return None
    return auth_context


def _principal_actor(
    request: Request,
    actor: ParticipantInput,
) -> ParticipantInput:
    auth_context = _oidc_auth_context(request)
    if auth_context is None:
        return actor
    if auth_context.principal_type == "human":
        if auth_context.user_id is None or not auth_context.display_name:
            return actor
        return actor.model_copy(
            update={
                "participant_id": auth_context.user_id,
                "participant_type": "user",
                "user_id": auth_context.user_id,
                "display_name": auth_context.display_name,
            }
        )
    participant_id = auth_context.system_agent_id or auth_context.agent_identity_id
    if participant_id is None:
        return actor
    return actor.model_copy(
        update={
            "participant_id": participant_id,
            "participant_type": "agent",
            "user_id": None,
            "display_name": (
                auth_context.display_name
                or auth_context.client_id
                or auth_context.subject
                or actor.display_name
            ),
        }
    )


async def _require_identity_permission(
    request: Request,
    *,
    permission: str,
    organization_id: UUID | None = None,
) -> None:
    await authorization_engine.authorize(
        "collaboration.identity",
        {
            "auth_context": _request_auth_context(request),
            "permission_type": "identity",
            "permission": permission,
            "organization_id": organization_id,
        },
    )


async def _require_workspace_permission(
    request: Request,
    workspace_id: UUID,
    *,
    permission: str,
) -> ParticipantInput | None:
    resolution = await authorization_engine.authorize(
        "collaboration.workspace",
        {
            "auth_context": _request_auth_context(request),
            "permission_type": "workspace",
            "permission": permission,
            "workspace_id": workspace_id,
        },
    )
    if resolution.workspace_participant is None:
        return None
    return resolution.workspace_participant.model_copy(
        update={"iam_permissions": sorted(resolution.workspace_permissions)}
    )


async def _require_worktree_session_permission(
    request: Request,
    session_id: UUID,
) -> AgentGitWorktreeSession:
    session = collab_svc.collaboration_service.get_agent_git_worktree_session(session_id)
    if session is None:
        raise KeyError(f"Git worktree session {session_id} not found")
    await _require_identity_permission(
        request,
        permission="agent_catalog.write",
        organization_id=session.organization_id if session.scope == "organization" else None,
    )
    return session


async def _require_workspace_audit_access(request: Request, workspace_id: UUID) -> None:
    await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.audit.read",
    )


def _resolved_create_workspace_actor(
    request: Request,
    actor: ParticipantInput,
) -> ParticipantInput:
    auth_context = _oidc_auth_context(request)
    resolved = _principal_actor(request, actor)
    if auth_context is not None and auth_context.principal_type == "human":
        return resolved.model_copy(update={"participant_id": uuid4()})
    return resolved


def _resolve_global_actor(
    request: Request,
    actor: ParticipantInput,
) -> ParticipantInput:
    return _principal_actor(request, actor)


async def _resolve_workspace_actor(
    request: Request,
    actor: ParticipantInput,
    *,
    workspace_id: UUID,
    auto_create: bool = True,
) -> ParticipantInput:
    auth_context = _oidc_auth_context(request)
    if auth_context is None:
        return actor
    workspace = await collab_svc.collaboration_service.get_workspace(workspace_id)
    await _require_identity_permission(
        request,
        permission="workspace.read",
        organization_id=workspace.workspace.organization_id,
    )
    if auth_context.principal_type == "agent":
        return await collab_svc.collaboration_service.resolve_authenticated_agent_actor(
            workspace_id=workspace_id,
            auth_context=auth_context,
        )
    try:
        return await collab_svc.collaboration_service.resolve_authenticated_user_actor(
            workspace_id=workspace_id,
            auth_context=auth_context,
            auto_create=auto_create,
        )
    except KeyError:
        raise


async def _resolve_thread_actor(
    request: Request,
    actor: ParticipantInput,
    *,
    thread_id: UUID,
    auto_create: bool = True,
) -> ParticipantInput:
    auth_context = _oidc_auth_context(request)
    if auth_context is None:
        return actor
    thread = await collab_svc.collaboration_service.get_thread(thread_id)
    workspace = await collab_svc.collaboration_service.get_workspace(thread.thread.workspace_id)
    await _require_identity_permission(
        request,
        permission="workspace.read",
        organization_id=workspace.workspace.organization_id,
    )
    if auth_context.principal_type == "agent":
        return await collab_svc.collaboration_service.resolve_authenticated_agent_actor(
            workspace_id=thread.thread.workspace_id,
            auth_context=auth_context,
        )
    return await collab_svc.collaboration_service.resolve_authenticated_thread_actor(
        thread_id=thread_id,
        auth_context=auth_context,
        auto_create=auto_create,
    )


async def _ws_authorize(websocket: WebSocket) -> AuthContext | None:
    mode = settings.auth_mode
    if mode == "none":
        return None

    api_key = websocket.query_params.get("api_key") or websocket.headers.get("x-api-key")
    auth_header = websocket.headers.get("authorization", "")
    bearer = (
        auth_header[7:].strip()
        if auth_header.lower().startswith("bearer ")
        else websocket.query_params.get("token")
    )

    if mode == "api_key":
        if api_key and await validate_api_key(api_key):
            return AuthContext(kind="api_key")
        return None
    if mode == "openbao":
        if bearer and await validate_openbao_token(bearer):
            return AuthContext(kind="api_key")
        return None
    if mode == "oidc":
        if not bearer:
            return None
        auth_context = await validate_oidc_token(bearer)
        if auth_context is None:
            return None
        return await sync_oidc_auth_context(auth_context)
    if mode == "any":
        if api_key and await validate_api_key(api_key):
            return AuthContext(kind="api_key")
        if bearer:
            auth_context = await validate_oidc_token(bearer)
            if auth_context is not None:
                return await sync_oidc_auth_context(auth_context)
            if await validate_openbao_token(bearer):
                return AuthContext(kind="api_key")
    return None


def _http_error(exc: Exception) -> HTTPException:
    logger.exception("Collaboration request failed: %s", exc)
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _workspace_not_found(workspace_id: UUID) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")


def _thread_not_found(thread_id: UUID) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Thread {thread_id} not found")


def _organization_not_found(organization_id: UUID) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Organization {organization_id} not found")


def _require_resource_in_organization(
    *,
    resource_name: str,
    resource_id: UUID,
    organization_id: UUID,
    resource_organization_id: UUID | None,
) -> None:
    if resource_organization_id != organization_id:
        raise _http_error(
            KeyError(f"{resource_name} {resource_id} not found in organization {organization_id}")
        )


async def _load_project(
    request: Request,
    project_id: UUID,
    *,
    permission: str,
    organization_id: UUID | None = None,
    project_permission: str = "project.read",
) -> Project:
    project = await collab_svc.collaboration_service.get_project(project_id)
    if project is None:
        raise _http_error(KeyError(f"Project {project_id} not found"))
    if organization_id is not None:
        _require_resource_in_organization(
            resource_name="Project",
            resource_id=project_id,
            organization_id=organization_id,
            resource_organization_id=project.organization_id,
        )
    await _require_identity_permission(
        request,
        permission=permission,
        organization_id=project.organization_id,
    )
    await _require_project_access(
        request,
        project,
        project_permission=project_permission,
    )
    return project


def _project_subject_from_auth_context(
    auth_context: AuthContext | None,
) -> ProjectSubjectRef | None:
    if auth_context is None or auth_context.kind == "api_key":
        return None
    if auth_context.principal_type == "human" and auth_context.user_id is not None:
        return ProjectSubjectRef(user_id=auth_context.user_id)
    if auth_context.principal_type == "agent" and auth_context.system_agent_id is not None:
        return ProjectSubjectRef(system_agent_id=auth_context.system_agent_id)
    return None


async def _project_access_binding_for_request(
    request: Request,
    project: Project,
) -> ProjectAccessBinding | None:
    subject = _project_subject_from_auth_context(_oidc_auth_context(request))
    if subject is None:
        return None
    bindings = await collab_svc.collaboration_service.list_project_access(
        project.organization_id,
        project.project_id,
        actor=None,
        allow_platform_admin=True,
    )
    for binding in bindings:
        if subject.user_id is not None and binding.user_id == subject.user_id:
            return binding
        if (
            subject.system_agent_id is not None
            and binding.system_agent_id == subject.system_agent_id
        ):
            return binding
    return None


async def _require_project_access(
    request: Request,
    project: Project,
    *,
    project_permission: str,
) -> ProjectAccessBinding | None:
    auth_context = _oidc_auth_context(request)
    if auth_context is None or auth_context.kind == "api_key" or has_admin_access(request):
        return None
    binding = await _project_access_binding_for_request(request, project)
    if binding is None:
        raise _http_error(KeyError(f"Project {project.project_id} not found"))
    effective_permissions = PROJECT_ROLE_BASE_PERMISSIONS.get(binding.role, ())
    if project_permission not in effective_permissions:
        raise HTTPException(
            status_code=403,
            detail=f"Project permission {project_permission!r} required",
        )
    return binding


async def _load_llm_provider(
    request: Request,
    provider_id: UUID,
    *,
    permission: str,
    organization_id: UUID | None = None,
) -> LlmProviderDefinition:
    provider = await collab_svc.collaboration_service.get_llm_provider(provider_id)
    if organization_id is not None:
        _require_resource_in_organization(
            resource_name="LLM provider",
            resource_id=provider_id,
            organization_id=organization_id,
            resource_organization_id=provider.organization_id,
        )
    await _require_identity_permission(
        request,
        permission=permission,
        organization_id=provider.organization_id,
    )
    return provider


async def _load_memory_provider(
    request: Request,
    provider_id: UUID,
    *,
    permission: str,
    organization_id: UUID | None = None,
) -> MemoryProviderDefinition:
    provider = await collab_svc.collaboration_service.get_memory_provider(provider_id)
    if organization_id is not None:
        _require_resource_in_organization(
            resource_name="Memory provider",
            resource_id=provider_id,
            organization_id=organization_id,
            resource_organization_id=provider.organization_id,
        )
    await _require_identity_permission(
        request,
        permission=permission,
        organization_id=provider.organization_id,
    )
    return provider


async def _load_system_agent_definition(
    request: Request,
    agent_id: UUID,
    *,
    permission: str,
    organization_id: UUID | None = None,
) -> AgentDefinition:
    agent = await collab_svc.collaboration_service.get_system_agent(agent_id)
    if agent is None:
        raise _http_error(KeyError(f"System agent {agent_id} not found"))
    if organization_id is not None:
        _require_resource_in_organization(
            resource_name="System agent",
            resource_id=agent_id,
            organization_id=organization_id,
            resource_organization_id=agent.organization_id,
        )
    await _require_identity_permission(
        request,
        permission=permission,
        organization_id=agent.organization_id,
    )
    return agent


async def _load_system_tool_definition(
    request: Request,
    tool_id: UUID,
    *,
    permission: str,
    organization_id: UUID | None = None,
) -> SystemToolDefinition:
    tool = await collab_svc.collaboration_service.get_system_tool(tool_id)
    if tool is None:
        raise _http_error(KeyError(f"System tool {tool_id} not found"))
    if organization_id is not None:
        _require_resource_in_organization(
            resource_name="System tool",
            resource_id=tool_id,
            organization_id=organization_id,
            resource_organization_id=tool.organization_id,
        )
    await _require_identity_permission(
        request,
        permission=permission,
        organization_id=tool.organization_id,
    )
    return tool


def _resolve_organization_actor(
    request: Request,
    actor: ParticipantInput,
) -> ParticipantInput:
    return _resolve_global_actor(request, actor)


async def _organization_membership_for_user(
    request: Request,
    organization_id: UUID,
) -> OrganizationMembership | None:
    auth_context = _user_auth_context(request)
    if auth_context is None or auth_context.user_id is None:
        return None
    try:
        memberships = await collab_svc.collaboration_service.list_organization_memberships(
            organization_id
        )
    except KeyError as exc:
        raise _organization_not_found(organization_id) from exc
    return next(
        (item for item in memberships if item.user_id == auth_context.user_id),
        None,
    )


async def _require_organization_membership(
    request: Request,
    organization_id: UUID,
) -> OrganizationMembership | None:
    auth_context = _oidc_auth_context(request)
    if auth_context is None or auth_context.kind == "api_key":
        return None
    if auth_context.principal_type == "agent":
        await _require_identity_permission(
            request,
            permission="organization.read",
            organization_id=organization_id,
        )
        return None
    membership = await _organization_membership_for_user(request, organization_id)
    if membership is None:
        raise _organization_not_found(organization_id)
    return membership


async def _require_organization_admin(
    request: Request,
    organization_id: UUID,
) -> OrganizationMembership | None:
    await _require_identity_permission(
        request,
        permission="organization.members.write",
        organization_id=organization_id,
    )
    return await _organization_membership_for_user(request, organization_id)


async def _require_workspace_membership(
    request: Request,
    workspace_id: UUID,
) -> ParticipantInput | None:
    auth_context = _oidc_auth_context(request)
    if auth_context is None:
        return None
    try:
        if auth_context.principal_type == "agent":
            actor = await collab_svc.collaboration_service.resolve_authenticated_agent_actor(
                workspace_id=workspace_id,
                auth_context=auth_context,
            )
        else:
            actor = await collab_svc.collaboration_service.resolve_authenticated_user_actor(
                workspace_id=workspace_id,
                auth_context=auth_context,
                auto_create=False,
            )
        workspace = await collab_svc.collaboration_service.get_workspace(workspace_id)
        await _require_identity_permission(
            request,
            permission="workspace.read",
            organization_id=workspace.workspace.organization_id,
        )
        return actor
    except KeyError as exc:
        raise _workspace_not_found(workspace_id) from exc


async def _require_thread_membership(
    request: Request,
    thread_id: UUID,
) -> ParticipantInput | None:
    auth_context = _oidc_auth_context(request)
    if auth_context is None:
        return None
    try:
        thread = await collab_svc.collaboration_service.get_thread(thread_id)
        if auth_context.principal_type == "agent":
            actor = await collab_svc.collaboration_service.resolve_authenticated_agent_actor(
                workspace_id=thread.thread.workspace_id,
                auth_context=auth_context,
            )
        else:
            actor = await collab_svc.collaboration_service.resolve_authenticated_thread_actor(
                thread_id=thread_id,
                auth_context=auth_context,
                auto_create=False,
            )
        workspace = await collab_svc.collaboration_service.get_workspace(thread.thread.workspace_id)
        await _require_identity_permission(
            request,
            permission="workspace.read",
            organization_id=workspace.workspace.organization_id,
        )
        return actor
    except KeyError as exc:
        raise _thread_not_found(thread_id) from exc


async def _require_asset_workspace_membership(
    request: Request,
    asset_id: UUID,
) -> WorkspaceAsset:
    asset = await collab_svc.collaboration_service.get_workspace_asset(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Workspace asset {asset_id} not found")
    if asset.workspace_id is not None:
        await _require_workspace_membership(request, asset.workspace_id)
    elif asset.organization_id is not None:
        await _require_organization_membership(request, asset.organization_id)
    return asset


async def _require_file_asset_visibility(
    request: Request,
    asset_id: UUID,
) -> WorkspaceAsset:
    asset = await _require_asset_workspace_membership(request, asset_id)
    if asset.asset_type != "file":
        raise KeyError(f"File asset {asset_id} not found")
    if asset.workspace_id is None:
        await _require_identity_permission(
            request,
            permission="asset_catalog.read",
            organization_id=asset.organization_id,
        )
    return asset


async def _require_retrieval_permission(
    request: Request,
    *,
    permission: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> ParticipantInput | None:
    if workspace_id is not None:
        return await _require_workspace_permission(
            request,
            workspace_id,
            permission=permission,
        )
    if organization_id is not None:
        await _require_organization_membership(request, organization_id)
        await _require_identity_permission(
            request,
            permission=permission,
            organization_id=organization_id,
        )
        return None
    await _require_identity_permission(request, permission=permission)
    return None


async def _resolve_retrieval_actor(
    request: Request,
    actor: ParticipantInput,
    *,
    permission: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> ParticipantInput:
    scoped_actor = await _require_retrieval_permission(
        request,
        permission=permission,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    if scoped_actor is not None:
        return scoped_actor
    if workspace_id is not None:
        return await _resolve_workspace_actor(
            request,
            actor,
            workspace_id=workspace_id,
            auto_create=False,
        )
    if organization_id is not None:
        return _resolve_organization_actor(request, actor)
    return _resolve_global_actor(request, actor)


async def _apply_retrieval_provider_override_permission(
    request: Request,
    actor: ParticipantInput,
    provider_overrides: dict[str, object],
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> ParticipantInput:
    if not provider_overrides:
        return actor
    await _require_retrieval_permission(
        request,
        permission="retrieval.admin",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    permissions = set(actor.iam_permissions)
    permissions.add("retrieval.admin")
    return actor.model_copy(update={"iam_permissions": sorted(permissions)})


def _form_actor(
    *,
    actor_participant_id: UUID | None,
    actor_type: str,
    actor_display_name: str,
) -> ParticipantInput:
    return ParticipantInput(
        participant_id=actor_participant_id or uuid4(),
        participant_type=actor_type,
        display_name=actor_display_name,
    )


async def _require_workspace_admin_or_supervisor(
    request: Request,
    workspace_id: UUID,
) -> ParticipantInput | None:
    return await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.tools.write",
    )


async def _resolve_workspace_lifecycle_actor(
    request: Request,
    *,
    workspace_id: UUID,
    actor: ParticipantInput,
) -> tuple[ParticipantInput, bool]:
    workspace = await collab_svc.collaboration_service.get_workspace(workspace_id)
    try:
        workspace_actor = await _require_workspace_permission(
            request,
            workspace_id,
            permission="workspace.roles.write",
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        # Workspace lifecycle mutations are organization control-plane operations.
        # A caller who is not attached to the workspace may still administer it if
        # they hold organization-level admin rights in the owning organization.
        await _require_identity_permission(
            request,
            permission="organization.members.write",
            organization_id=workspace.workspace.organization_id,
        )
        return _resolve_organization_actor(request, actor), True
    return workspace_actor or actor, False


async def _tool_generation_request_for_revision(
    revision_id: UUID,
) -> ToolGenerationRequestDetail:
    details = await collab_svc.collaboration_service.list_tool_generation_requests()
    for detail in details:
        if any(revision.revision_id == revision_id for revision in detail.revisions):
            return detail
    raise KeyError(f"Tool generation revision {revision_id} not found")


@router.post(
    "/organizations",
    response_model=Organization,
    summary="Create an organization",
)
async def create_organization(
    request: Request,
    payload: CreateOrganizationRequest,
) -> Organization:
    require_admin_access(request)
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        organization = await collab_svc.collaboration_service.create_organization(payload)
        if settings.operational_agents_bootstrap_enabled:
            try:
                await operational_bootstrap_service.ensure_for_organization(
                    organization.organization_id
                )
            except Exception:
                logger.warning(
                    "Operational agent bootstrap repair failed for organization_id=%s",
                    organization.organization_id,
                    exc_info=True,
                )
        return organization
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations",
    response_model=list[Organization],
    summary="List organizations",
)
async def list_organizations(request: Request) -> list[Organization]:
    auth_context = _oidc_auth_context(request)
    if auth_context is not None and auth_context.principal_type == "agent":
        try:
            await _require_identity_permission(request, permission="organization.read")
        except HTTPException:
            identity = None
            if auth_context.agent_identity_id is not None:
                identity = await collab_svc.collaboration_service.get_agent_identity(
                    auth_context.agent_identity_id
                )
            if identity is None or identity.organization_id is None:
                raise
            return [await collab_svc.collaboration_service.get_organization(identity.organization_id)]
        return await collab_svc.collaboration_service.list_organizations()
    user_context = auth_context if auth_context is not None and auth_context.principal_type == "human" else None
    user_id = None if has_admin_access(request) else (user_context.user_id if user_context else None)
    try:
        return await collab_svc.collaboration_service.list_organizations(user_id=user_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/by-slug/{organization_slug}",
    response_model=Organization,
    summary="Get organization detail by slug",
)
async def get_organization_by_slug(
    request: Request,
    organization_slug: str,
) -> Organization:
    normalized_slug = normalize_organization_slug(organization_slug)
    try:
        organization = await collab_svc.collaboration_service.get_organization_by_slug(
            normalized_slug
        )
        await _require_identity_permission(
            request,
            permission="organization.read",
            organization_id=organization.organization_id,
        )
        return organization
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}",
    response_model=Organization,
    summary="Get organization detail",
)
async def get_organization(request: Request, organization_id: UUID) -> Organization:
    try:
        await _require_identity_permission(
            request,
            permission="organization.read",
            organization_id=organization_id,
        )
        return await collab_svc.collaboration_service.get_organization(organization_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/organizations/{organization_id}",
    response_model=Organization,
    summary="Update an organization",
)
async def update_organization(
    request: Request,
    organization_id: UUID,
    payload: UpdateOrganizationRequest,
) -> Organization:
    await _require_organization_admin(request, organization_id)
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.update_organization(
            organization_id,
            payload,
            allow_platform_admin=has_admin_access(request),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/members",
    response_model=list[OrganizationMembership],
    summary="List organization memberships",
)
async def list_organization_memberships(
    request: Request,
    organization_id: UUID,
) -> list[OrganizationMembership]:
    try:
        await _require_identity_permission(
            request,
            permission="organization.members.read",
            organization_id=organization_id,
        )
        return await collab_svc.collaboration_service.list_organization_memberships(
            organization_id
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/members",
    response_model=OrganizationMembership,
    summary="Add an organization member",
)
async def add_organization_member(
    request: Request,
    organization_id: UUID,
    payload: AddOrganizationMemberRequest,
) -> OrganizationMembership:
    await _require_organization_admin(request, organization_id)
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.add_organization_member(
            organization_id,
            payload,
            allow_platform_admin=has_admin_access(request),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/organizations/{organization_id}/members/{user_id}",
    response_model=dict,
    summary="Remove an organization member",
)
async def remove_organization_member(
    request: Request,
    organization_id: UUID,
    user_id: UUID,
    payload: RemoveOrganizationMemberRequest = Body(...),
) -> dict[str, bool | str]:
    await _require_organization_admin(request, organization_id)
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.remove_organization_member(
            organization_id,
            user_id,
            payload,
            allow_platform_admin=has_admin_access(request),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/projects",
    response_model=Project,
    summary="Create a project inside an organization",
)
async def create_organization_project(
    request: Request,
    organization_id: UUID,
    payload: CreateProjectRequest,
) -> Project:
    await _require_identity_permission(
        request,
        permission="project.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.create_project(
            organization_id,
            payload,
            allow_platform_admin=has_admin_access(request),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/projects",
    response_model=list[Project],
    summary="List projects inside an organization",
)
async def list_organization_projects(
    request: Request,
    organization_id: UUID,
) -> list[Project]:
    await _require_identity_permission(
        request,
        permission="project.read",
        organization_id=organization_id,
    )
    try:
        return await collab_svc.collaboration_service.list_projects(organization_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/projects/{project_id}",
    response_model=Project,
    summary="Get project detail",
)
async def get_organization_project(
    request: Request,
    organization_id: UUID,
    project_id: UUID,
) -> Project:
    try:
        return await _load_project(
            request,
            project_id,
            permission="project.read",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/organizations/{organization_id}/projects/{project_id}",
    response_model=Project,
    summary="Update project metadata",
)
async def update_organization_project(
    request: Request,
    organization_id: UUID,
    project_id: UUID,
    payload: UpdateProjectRequest,
) -> Project:
    await _load_project(
        request,
        project_id,
        permission="project.read",
        organization_id=organization_id,
        project_permission="project.write",
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.update_project(
            organization_id,
            project_id,
            payload,
            allow_platform_admin=has_admin_access(request),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/projects/{project_id}/access",
    response_model=list[ProjectAccessBinding],
    summary="List project access bindings",
)
async def list_project_access(
    request: Request,
    organization_id: UUID,
    project_id: UUID,
) -> list[ProjectAccessBinding]:
    project = await _load_project(
        request,
        project_id,
        permission="project.read",
        organization_id=organization_id,
        project_permission="project.read",
    )
    try:
        return await collab_svc.collaboration_service.list_project_access(
            organization_id,
            project.project_id,
            actor=None,
            allow_platform_admin=True,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put(
    "/organizations/{organization_id}/projects/{project_id}/access",
    response_model=ProjectAccessBinding,
    summary="Create or update project access",
)
async def upsert_project_access(
    request: Request,
    organization_id: UUID,
    project_id: UUID,
    payload: UpsertProjectAccessRequest,
) -> ProjectAccessBinding:
    await _load_project(
        request,
        project_id,
        permission="project.read",
        organization_id=organization_id,
        project_permission="project.access.write",
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.upsert_project_access(
            organization_id,
            project_id,
            payload,
            allow_platform_admin=has_admin_access(request),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/organizations/{organization_id}/projects/{project_id}/access",
    response_model=dict,
    summary="Remove project access",
)
async def remove_project_access(
    request: Request,
    organization_id: UUID,
    project_id: UUID,
    payload: RemoveProjectAccessRequest = Body(...),
) -> dict[str, bool | str]:
    await _load_project(
        request,
        project_id,
        permission="project.read",
        organization_id=organization_id,
        project_permission="project.access.write",
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.remove_project_access(
            organization_id,
            project_id,
            payload,
            allow_platform_admin=has_admin_access(request),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces", response_model=WorkspaceDetail, summary="Create a workspace")
async def create_workspace(request: Request, payload: CreateWorkspaceRequest) -> WorkspaceDetail:
    project = None
    if payload.project_id is not None:
        project = await _load_project(
            request,
            payload.project_id,
            permission="workspace.list",
            organization_id=payload.organization_id,
            project_permission="workspace.create",
        )
    if payload.organization_id is not None and project is None:
        await _require_identity_permission(
            request,
            permission="workspace.list",
            organization_id=payload.organization_id,
        )
    if project is not None and payload.organization_id is None:
        payload = payload.model_copy(update={"organization_id": project.organization_id})
    payload = payload.model_copy(
        update={"actor": _resolved_create_workspace_actor(request, payload.actor)}
    )
    logger.debug(
        "HTTP create_workspace actor=%s name=%r metadata_keys=%s",
        _actor_log(payload.actor),
        payload.name,
        sorted(payload.metadata.keys()),
    )
    try:
        return await collab_svc.collaboration_service.create_workspace(
            payload,
            allow_platform_admin=has_admin_access(request),
        )
    except Exception as exc:  # pragma: no cover - exercised by tests via error type mapping
        raise _http_error(exc) from exc


@router.get("/workspaces", response_model=list[Workspace], summary="List workspaces")
async def list_workspaces(
    request: Request,
    organization_id: UUID | None = Query(default=None),
    project_id: UUID | None = Query(default=None),
) -> list[Workspace]:
    logger.debug(
        "HTTP list_workspaces organization_id=%s project_id=%s",
        organization_id,
        project_id,
    )
    auth_context = _oidc_auth_context(request)
    effective_project_id = project_id
    if project_id is not None:
        project = await _load_project(
            request,
            project_id,
            permission="workspace.list",
            organization_id=organization_id,
            project_permission="workspace.list",
        )
        if organization_id is None:
            organization_id = project.organization_id
    if auth_context is not None and organization_id is not None:
        await _require_identity_permission(
            request,
            permission="workspace.list",
            organization_id=organization_id,
        )
    if auth_context is not None and auth_context.principal_type == "agent":
        effective_organization_id = organization_id
        if effective_organization_id is None and auth_context.agent_identity_id is not None:
            identity = await collab_svc.collaboration_service.get_agent_identity(
                auth_context.agent_identity_id
            )
            effective_organization_id = identity.organization_id if identity is not None else None
            if effective_organization_id is not None:
                await _require_identity_permission(
                    request,
                    permission="workspace.list",
                    organization_id=effective_organization_id,
                )
            else:
                await _require_identity_permission(request, permission="workspace.list")
        if not has_admin_access(request) and auth_context.system_agent_id is None:
            return []
        return await collab_svc.collaboration_service.list_workspaces(
            user_id=None,
            system_agent_id=None
            if has_admin_access(request)
            else auth_context.system_agent_id,
            organization_id=effective_organization_id,
            project_id=effective_project_id,
        )
    user_context = auth_context if auth_context is not None and auth_context.principal_type == "human" else None
    user_id = None if has_admin_access(request) else (user_context.user_id if user_context is not None else None)
    return await collab_svc.collaboration_service.list_workspaces(
        user_id=user_id,
        organization_id=organization_id,
        project_id=effective_project_id,
    )


@router.post(
    "/organizations/{organization_id}/workspaces",
    response_model=WorkspaceDetail,
    summary="Create a workspace inside an organization",
)
async def create_organization_workspace(
    request: Request,
    organization_id: UUID,
    payload: CreateWorkspaceRequest,
) -> WorkspaceDetail:
    await _require_identity_permission(
        request,
        permission="workspace.list",
        organization_id=organization_id,
    )
    if payload.project_id is not None:
        await _load_project(
            request,
            payload.project_id,
            permission="workspace.list",
            organization_id=organization_id,
            project_permission="workspace.create",
        )
    payload = payload.model_copy(
        update={
            "organization_id": organization_id,
            "actor": _resolved_create_workspace_actor(request, payload.actor),
        }
    )
    try:
        return await collab_svc.collaboration_service.create_workspace(
            payload,
            allow_platform_admin=has_admin_access(request),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/workspaces",
    response_model=list[Workspace],
    summary="List workspaces inside an organization",
)
async def list_organization_workspaces(
    request: Request,
    organization_id: UUID,
    project_id: UUID | None = Query(default=None),
) -> list[Workspace]:
    await _require_identity_permission(
        request,
        permission="workspace.list",
        organization_id=organization_id,
    )
    if project_id is not None:
        await _load_project(
            request,
            project_id,
            permission="workspace.list",
            organization_id=organization_id,
            project_permission="workspace.list",
        )
    auth_context = _oidc_auth_context(request)
    user_id = (
        auth_context.user_id
        if auth_context is not None and auth_context.principal_type == "human"
        else None
    )
    system_agent_id = (
        auth_context.system_agent_id
        if auth_context is not None and auth_context.principal_type == "agent"
        else None
    )
    try:
        return await collab_svc.collaboration_service.list_workspaces(
            user_id=None if has_admin_access(request) else user_id,
            system_agent_id=None if has_admin_access(request) else system_agent_id,
            organization_id=organization_id,
            project_id=project_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/projects/{project_id}/workspaces",
    response_model=WorkspaceDetail,
    summary="Create a workspace inside a project",
)
async def create_project_workspace(
    request: Request,
    organization_id: UUID,
    project_id: UUID,
    payload: CreateWorkspaceRequest,
) -> WorkspaceDetail:
    await _load_project(
        request,
        project_id,
        permission="workspace.list",
        organization_id=organization_id,
        project_permission="workspace.create",
    )
    payload = payload.model_copy(
        update={
            "organization_id": organization_id,
            "project_id": project_id,
            "actor": _resolved_create_workspace_actor(request, payload.actor),
        }
    )
    try:
        return await collab_svc.collaboration_service.create_workspace(
            payload,
            allow_platform_admin=has_admin_access(request),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/projects/{project_id}/workspaces",
    response_model=list[Workspace],
    summary="List workspaces inside a project",
)
async def list_project_workspaces(
    request: Request,
    organization_id: UUID,
    project_id: UUID,
) -> list[Workspace]:
    await _load_project(
        request,
        project_id,
        permission="workspace.list",
        organization_id=organization_id,
        project_permission="workspace.list",
    )
    auth_context = _oidc_auth_context(request)
    user_id = (
        auth_context.user_id
        if auth_context is not None and auth_context.principal_type == "human"
        else None
    )
    system_agent_id = (
        auth_context.system_agent_id
        if auth_context is not None and auth_context.principal_type == "agent"
        else None
    )
    try:
        return await collab_svc.collaboration_service.list_workspaces(
            user_id=None if has_admin_access(request) else user_id,
            system_agent_id=None if has_admin_access(request) else system_agent_id,
            organization_id=organization_id,
            project_id=project_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/runtime/overview",
    response_model=RuntimeOverviewResponse,
    summary="View runtime overview for a single organization",
)
async def organization_runtime_overview(
    request: Request,
    organization_id: UUID,
) -> RuntimeOverviewResponse:
    await _require_identity_permission(
        request,
        permission="organization.runtime.read",
        organization_id=organization_id,
    )
    try:
        return RuntimeOverviewResponse.model_validate(
            await collab_svc.collaboration_service.get_runtime_overview(
                organization_id=organization_id
            )
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/workspaces/{workspace_id}",
    response_model=dict,
    summary="Delete a workspace",
)
async def delete_workspace(
    request: Request,
    workspace_id: UUID,
    payload: DeleteWorkspaceRequest = Body(...),
) -> dict[str, bool | str]:
    actor, _ = await _resolve_workspace_lifecycle_actor(
        request,
        workspace_id=workspace_id,
        actor=payload.actor,
    )
    payload = payload.model_copy(
        update={
            "actor": actor
        }
    )
    logger.debug(
        "HTTP delete_workspace workspace_id=%s actor=%s",
        workspace_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.delete_workspace(workspace_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceDetail,
    summary="Update workspace metadata",
)
async def update_workspace(
    request: Request,
    workspace_id: UUID,
    payload: UpdateWorkspaceRequest,
) -> WorkspaceDetail:
    actor, skip_workspace_permission_check = await _resolve_workspace_lifecycle_actor(
        request,
        workspace_id=workspace_id,
        actor=payload.actor,
    )
    payload = payload.model_copy(
        update={
            "actor": actor
        }
    )
    logger.debug(
        "HTTP update_workspace workspace_id=%s actor=%s",
        workspace_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.update_workspace(
            workspace_id,
            payload,
            skip_workspace_permission_check=skip_workspace_permission_check,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceDetail,
    summary="Get workspace detail",
)
async def get_workspace(request: Request, workspace_id: UUID) -> WorkspaceDetail:
    logger.debug("HTTP get_workspace workspace_id=%s", workspace_id)
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.get_workspace(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/participants",
    response_model=list[ParticipantProfile],
    summary="List participant advertisements in a workspace",
)
async def list_workspace_participants(
    request: Request,
    workspace_id: UUID,
) -> list[ParticipantProfile]:
    logger.debug("HTTP list_workspace_participants workspace_id=%s", workspace_id)
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_workspace_participants(
            workspace_id
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/catalog/agents",
    response_model=list[AgentDefinition],
    summary="List agents visible to a workspace",
)
async def list_workspace_catalog_agents(
    request: Request,
    workspace_id: UUID,
) -> list[AgentDefinition]:
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_workspace_catalog_agents(
            workspace_id
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/catalog/tools",
    response_model=list[SystemToolDefinition],
    summary="List tools visible to a workspace",
)
async def list_workspace_catalog_tools(
    request: Request,
    workspace_id: UUID,
) -> list[SystemToolDefinition]:
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_workspace_catalog_tools(
            workspace_id
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/catalog/mcp-servers",
    response_model=list[McpServerDefinition],
    summary="List external MCP servers visible to a workspace",
)
async def list_workspace_catalog_mcp_servers(
    request: Request,
    workspace_id: UUID,
) -> list[McpServerDefinition]:
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_workspace_catalog_mcp_servers(
            workspace_id
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/workspaces/{workspace_id}/participants/{participant_id}",
    response_model=dict,
    summary="Remove a participant from a workspace",
)
async def delete_participant(
    request: Request,
    workspace_id: UUID,
    participant_id: UUID,
    payload: DeleteParticipantRequest = Body(...),
) -> dict[str, bool | str]:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.agents.write",
    )
    payload = payload.model_copy(
        update={
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            )
        }
    )
    logger.debug(
        "HTTP delete_participant workspace_id=%s participant_id=%s actor=%s",
        workspace_id,
        participant_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.delete_participant(
            workspace_id,
            participant_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/workspaces/{workspace_id}/participants/{participant_id}/role",
    response_model=ParticipantProfile,
    summary="Assume a collaboration role in a workspace",
)
async def assume_participant_role(
    request: Request,
    workspace_id: UUID,
    participant_id: UUID,
    payload: AssumeParticipantRoleRequest,
):
    resolved_actor = await _resolve_workspace_actor(
        request,
        payload.actor,
        workspace_id=workspace_id,
    )
    if _user_auth_context(request) is not None:
        participant_id = resolved_actor.participant_id
    payload = payload.model_copy(update={"actor": resolved_actor})
    logger.debug(
        "HTTP assume_participant_role workspace_id=%s participant_id=%s actor=%s role=%r capability_count=%s",
        workspace_id,
        participant_id,
        _actor_log(payload.actor),
        payload.role,
        len(payload.capabilities),
    )
    try:
        return await collab_svc.collaboration_service.assume_participant_role(
            workspace_id,
            participant_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agents",
    response_model=AgentDefinition,
    summary="Create a system-level agent definition",
)
async def create_system_agent(
    request: Request,
    payload: CreateSystemAgentRequest,
) -> AgentDefinition:
    await _require_identity_permission(request, permission="agent_catalog.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP create_system_agent actor=%s display_name=%r endpoint_kind=%s",
        _actor_log(payload.actor),
        payload.display_name,
        payload.endpoint.kind,
    )
    try:
        return await collab_svc.collaboration_service.create_system_agent(payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/agents",
    response_model=AgentDefinition,
    summary="Create an organization-scoped agent definition",
)
async def create_organization_system_agent(
    request: Request,
    organization_id: UUID,
    payload: CreateSystemAgentRequest,
) -> AgentDefinition:
    await _require_identity_permission(
        request,
        permission="agent_catalog.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.create_system_agent(
            payload,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agents/validate-from-git",
    response_model=AgentBundleValidationResult,
    summary="Validate a system-wide Git-managed agent bundle without publishing",
)
async def validate_system_agent_bundle_from_git(
    request: Request,
    payload: ValidateAgentBundleFromGitRequest,
) -> AgentBundleValidationResult:
    await _require_identity_permission(request, permission="agent_catalog.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.validate_agent_bundle_from_git(
            scope="global",
            organization_id=None,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/agents/validate-from-git",
    response_model=AgentBundleValidationResult,
    summary="Validate an organization-wide Git-managed agent bundle without publishing",
)
async def validate_organization_agent_bundle_from_git(
    request: Request,
    organization_id: UUID,
    payload: ValidateAgentBundleFromGitRequest,
) -> AgentBundleValidationResult:
    await _require_identity_permission(
        request,
        permission="agent_catalog.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.validate_agent_bundle_from_git(
            scope="organization",
            organization_id=organization_id,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agents/publish-from-git",
    response_model=AgentBundlePublishResult,
    summary="Publish a system-wide Git-managed agent bundle",
)
async def publish_system_agent_bundle_from_git(
    request: Request,
    payload: PublishAgentBundleFromGitRequest,
) -> AgentBundlePublishResult:
    await _require_identity_permission(request, permission="agent_catalog.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.publish_agent_bundle_from_git(
            scope="global",
            organization_id=None,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/agents/publish-from-git",
    response_model=AgentBundlePublishResult,
    summary="Publish an organization-wide Git-managed agent bundle",
)
async def publish_organization_agent_bundle_from_git(
    request: Request,
    organization_id: UUID,
    payload: PublishAgentBundleFromGitRequest,
) -> AgentBundlePublishResult:
    await _require_identity_permission(
        request,
        permission="agent_catalog.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.publish_agent_bundle_from_git(
            scope="organization",
            organization_id=organization_id,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agents/bundles/upload",
    response_model=AgentBundleUploadResult,
    summary="Upload, commit, and optionally publish a system-wide agent bundle archive",
)
async def upload_system_agent_bundle_archive(
    request: Request,
    repository_id: UUID = Form(...),
    branch: str = Form(...),
    bundle_path: str = Form(...),
    publish: bool = Form(False),
    base_revision: str | None = Form(None),
    commit_message: str | None = Form(None),
    archive: UploadFile = File(...),
) -> AgentBundleUploadResult:
    await _require_identity_permission(request, permission="agent_catalog.write")
    actor = _resolve_global_actor(
        request,
        ParticipantInput(
            participant_id=uuid4(),
            participant_type="user",
            display_name="agent-bundle-uploader",
        ),
    )
    try:
        return await collab_svc.collaboration_service.upload_agent_bundle_archive(
            scope="global",
            organization_id=None,
            actor=actor,
            repository_id=repository_id,
            branch=branch,
            bundle_path=bundle_path,
            archive_bytes=await archive.read(),
            publish=publish,
            base_revision=base_revision,
            commit_message=commit_message,
            metadata={},
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/agents/bundles/upload",
    response_model=AgentBundleUploadResult,
    summary="Upload, commit, and optionally publish an organization-wide agent bundle archive",
)
async def upload_organization_agent_bundle_archive(
    request: Request,
    organization_id: UUID,
    repository_id: UUID = Form(...),
    branch: str = Form(...),
    bundle_path: str = Form(...),
    publish: bool = Form(False),
    base_revision: str | None = Form(None),
    commit_message: str | None = Form(None),
    archive: UploadFile = File(...),
) -> AgentBundleUploadResult:
    await _require_identity_permission(
        request,
        permission="agent_catalog.write",
        organization_id=organization_id,
    )
    actor = _resolve_organization_actor(
        request,
        ParticipantInput(
            participant_id=uuid4(),
            participant_type="user",
            display_name="agent-bundle-uploader",
        ),
    )
    try:
        return await collab_svc.collaboration_service.upload_agent_bundle_archive(
            scope="organization",
            organization_id=organization_id,
            actor=actor,
            repository_id=repository_id,
            branch=branch,
            bundle_path=bundle_path,
            archive_bytes=await archive.read(),
            publish=publish,
            base_revision=base_revision,
            commit_message=commit_message,
            metadata={},
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/llm-engines",
    response_model=list[LlmEngineDescriptor],
    summary="List registered LLM engines available to the system",
)
async def list_llm_engines() -> list[LlmEngineDescriptor]:
    logger.debug("HTTP list_llm_engines")
    return await list_registered_llm_engines()


@router.post(
    "/llm-providers",
    response_model=LlmProviderDefinition,
    summary="Create a system-level LLM provider definition",
)
async def create_llm_provider(
    request: Request,
    payload: CreateLlmProviderRequest,
) -> LlmProviderDefinition:
    await _require_identity_permission(request, permission="provider.llm.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP create_llm_provider actor=%s engine_id=%r provider=%s",
        _actor_log(payload.actor),
        payload.engine_id,
        payload.provider,
    )
    try:
        return await collab_svc.collaboration_service.create_llm_provider(payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/llm-providers",
    response_model=LlmProviderDefinition,
    summary="Create an organization-scoped LLM provider definition",
)
async def create_organization_llm_provider(
    request: Request,
    organization_id: UUID,
    payload: CreateLlmProviderRequest,
) -> LlmProviderDefinition:
    await _require_identity_permission(
        request,
        permission="provider.llm.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.create_llm_provider(
            payload,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/llm-providers/validate",
    response_model=LlmProviderHealthReport,
    summary="Validate an LLM provider definition without persisting it",
)
async def validate_llm_provider(
    request: Request,
    payload: CreateLlmProviderRequest,
) -> LlmProviderHealthReport:
    await _require_identity_permission(request, permission="provider.llm.validate")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP validate_llm_provider actor=%s engine_id=%r provider=%s",
        _actor_log(payload.actor),
        payload.engine_id,
        payload.provider,
    )
    try:
        now = datetime.now(timezone.utc)
        provider = LlmProviderDefinition(
            provider_id=uuid4(),
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
        return await check_llm_provider_health(provider)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/llm-providers",
    response_model=list[LlmProviderDefinition],
    summary="List system-level LLM provider definitions",
)
async def list_llm_providers(request: Request) -> list[LlmProviderDefinition]:
    await _require_identity_permission(request, permission="provider.llm.read")
    logger.debug("HTTP list_llm_providers")
    try:
        return await collab_svc.collaboration_service.list_llm_providers()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/llm-providers",
    response_model=list[LlmProviderDefinition],
    summary="List organization-scoped LLM provider definitions",
)
async def list_organization_llm_providers(
    request: Request,
    organization_id: UUID,
) -> list[LlmProviderDefinition]:
    await _require_identity_permission(
        request,
        permission="provider.llm.read",
        organization_id=organization_id,
    )
    try:
        return await collab_svc.collaboration_service.list_llm_providers(
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/llm-providers/{provider_id}",
    response_model=LlmProviderDefinition,
    summary="Get an LLM provider definition",
)
async def get_llm_provider(
    request: Request,
    provider_id: UUID,
) -> LlmProviderDefinition:
    try:
        return await _load_llm_provider(
            request,
            provider_id,
            permission="provider.llm.read",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/llm-providers/{provider_id}",
    response_model=LlmProviderDefinition,
    summary="Get an organization-scoped LLM provider definition",
)
async def get_organization_llm_provider(
    request: Request,
    organization_id: UUID,
    provider_id: UUID,
) -> LlmProviderDefinition:
    try:
        return await _load_llm_provider(
            request,
            provider_id,
            permission="provider.llm.read",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/llm-providers/{provider_id}",
    response_model=LlmProviderDefinition,
    summary="Update an LLM provider definition",
)
async def update_llm_provider(
    request: Request,
    provider_id: UUID,
    payload: UpdateLlmProviderRequest,
) -> LlmProviderDefinition:
    await _load_llm_provider(
        request,
        provider_id,
        permission="provider.llm.write",
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP update_llm_provider provider_id=%s actor=%s",
        provider_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.update_llm_provider(
            provider_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/organizations/{organization_id}/llm-providers/{provider_id}",
    response_model=LlmProviderDefinition,
    summary="Update an organization-scoped LLM provider definition",
)
async def update_organization_llm_provider(
    request: Request,
    organization_id: UUID,
    provider_id: UUID,
    payload: UpdateLlmProviderRequest,
) -> LlmProviderDefinition:
    await _load_llm_provider(
        request,
        provider_id,
        permission="provider.llm.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.update_llm_provider(
            provider_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/llm-providers/{provider_id}",
    response_model=dict,
    summary="Delete an LLM provider definition",
)
async def delete_llm_provider(
    request: Request,
    provider_id: UUID,
    payload: DeleteLlmProviderRequest = Body(...),
) -> dict[str, bool | str]:
    await _load_llm_provider(
        request,
        provider_id,
        permission="provider.llm.write",
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP delete_llm_provider provider_id=%s actor=%s",
        provider_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.delete_llm_provider(
            provider_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/organizations/{organization_id}/llm-providers/{provider_id}",
    response_model=dict,
    summary="Delete an organization-scoped LLM provider definition",
)
async def delete_organization_llm_provider(
    request: Request,
    organization_id: UUID,
    provider_id: UUID,
    payload: DeleteLlmProviderRequest = Body(...),
) -> dict[str, bool | str]:
    await _load_llm_provider(
        request,
        provider_id,
        permission="provider.llm.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.delete_llm_provider(
            provider_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/llm-providers/{provider_id}/health-check",
    response_model=LlmProviderHealthReport,
    summary="Validate a stored LLM provider configuration",
)
async def health_check_llm_provider(
    request: Request,
    provider_id: UUID,
) -> LlmProviderHealthReport:
    provider = await _load_llm_provider(
        request,
        provider_id,
        permission="provider.llm.validate",
    )
    logger.debug("HTTP health_check_llm_provider provider_id=%s", provider_id)
    try:
        return await check_llm_provider_health(provider)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/llm-providers/{provider_id}/health-check",
    response_model=LlmProviderHealthReport,
    summary="Validate an organization-scoped LLM provider configuration",
)
async def health_check_organization_llm_provider(
    request: Request,
    organization_id: UUID,
    provider_id: UUID,
) -> LlmProviderHealthReport:
    provider = await _load_llm_provider(
        request,
        provider_id,
        permission="provider.llm.validate",
        organization_id=organization_id,
    )
    try:
        return await check_llm_provider_health(provider)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/memory-providers",
    response_model=MemoryProviderDefinition,
    summary="Create a system-level memory provider definition",
)
async def create_memory_provider(
    request: Request,
    payload: CreateMemoryProviderRequest,
) -> MemoryProviderDefinition:
    await _require_identity_permission(request, permission="provider.memory.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP create_memory_provider actor=%s provider_key=%r provider=%s",
        _actor_log(payload.actor),
        payload.provider_key,
        payload.provider,
    )
    try:
        return await collab_svc.collaboration_service.create_memory_provider(payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/memory-providers",
    response_model=MemoryProviderDefinition,
    summary="Create an organization-scoped memory provider definition",
)
async def create_organization_memory_provider(
    request: Request,
    organization_id: UUID,
    payload: CreateMemoryProviderRequest,
) -> MemoryProviderDefinition:
    await _require_identity_permission(
        request,
        permission="provider.memory.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.create_memory_provider(
            payload,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/memory-providers/validate",
    response_model=MemoryProviderHealthReport,
    summary="Validate a memory provider definition without persisting it",
)
async def validate_memory_provider(
    request: Request,
    payload: CreateMemoryProviderRequest,
) -> MemoryProviderHealthReport:
    await _require_identity_permission(request, permission="provider.memory.validate")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP validate_memory_provider actor=%s provider_key=%r provider=%s",
        _actor_log(payload.actor),
        payload.provider_key,
        payload.provider,
    )
    try:
        now = datetime.now(timezone.utc)
        provider = MemoryProviderDefinition(
            provider_id=uuid4(),
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
        return await check_memory_provider_health(provider)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/memory-providers",
    response_model=list[MemoryProviderDefinition],
    summary="List system-level memory provider definitions",
)
async def list_memory_providers(request: Request) -> list[MemoryProviderDefinition]:
    await _require_identity_permission(request, permission="provider.memory.read")
    logger.debug("HTTP list_memory_providers")
    try:
        return await collab_svc.collaboration_service.list_memory_providers()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/memory-providers",
    response_model=list[MemoryProviderDefinition],
    summary="List organization-scoped memory provider definitions",
)
async def list_organization_memory_providers(
    request: Request,
    organization_id: UUID,
) -> list[MemoryProviderDefinition]:
    await _require_identity_permission(
        request,
        permission="provider.memory.read",
        organization_id=organization_id,
    )
    try:
        return await collab_svc.collaboration_service.list_memory_providers(
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/memory-providers/{provider_id}",
    response_model=MemoryProviderDefinition,
    summary="Get a memory provider definition",
)
async def get_memory_provider(
    request: Request,
    provider_id: UUID,
) -> MemoryProviderDefinition:
    try:
        return await _load_memory_provider(
            request,
            provider_id,
            permission="provider.memory.read",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/memory-providers/{provider_id}",
    response_model=MemoryProviderDefinition,
    summary="Get an organization-scoped memory provider definition",
)
async def get_organization_memory_provider(
    request: Request,
    organization_id: UUID,
    provider_id: UUID,
) -> MemoryProviderDefinition:
    try:
        return await _load_memory_provider(
            request,
            provider_id,
            permission="provider.memory.read",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/memory-providers/{provider_id}",
    response_model=MemoryProviderDefinition,
    summary="Update a memory provider definition",
)
async def update_memory_provider(
    request: Request,
    provider_id: UUID,
    payload: UpdateMemoryProviderRequest,
) -> MemoryProviderDefinition:
    await _load_memory_provider(
        request,
        provider_id,
        permission="provider.memory.write",
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP update_memory_provider provider_id=%s actor=%s",
        provider_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.update_memory_provider(
            provider_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/organizations/{organization_id}/memory-providers/{provider_id}",
    response_model=MemoryProviderDefinition,
    summary="Update an organization-scoped memory provider definition",
)
async def update_organization_memory_provider(
    request: Request,
    organization_id: UUID,
    provider_id: UUID,
    payload: UpdateMemoryProviderRequest,
) -> MemoryProviderDefinition:
    await _load_memory_provider(
        request,
        provider_id,
        permission="provider.memory.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.update_memory_provider(
            provider_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/memory-providers/{provider_id}",
    response_model=dict,
    summary="Delete a memory provider definition",
)
async def delete_memory_provider(
    request: Request,
    provider_id: UUID,
    payload: DeleteMemoryProviderRequest = Body(...),
) -> dict[str, bool | str]:
    await _load_memory_provider(
        request,
        provider_id,
        permission="provider.memory.write",
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP delete_memory_provider provider_id=%s actor=%s",
        provider_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.delete_memory_provider(
            provider_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/organizations/{organization_id}/memory-providers/{provider_id}",
    response_model=dict,
    summary="Delete an organization-scoped memory provider definition",
)
async def delete_organization_memory_provider(
    request: Request,
    organization_id: UUID,
    provider_id: UUID,
    payload: DeleteMemoryProviderRequest = Body(...),
) -> dict[str, bool | str]:
    await _load_memory_provider(
        request,
        provider_id,
        permission="provider.memory.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.delete_memory_provider(
            provider_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/memory-providers/{provider_id}/health-check",
    response_model=MemoryProviderHealthReport,
    summary="Validate a stored memory provider configuration",
)
async def health_check_memory_provider(
    request: Request,
    provider_id: UUID,
) -> MemoryProviderHealthReport:
    provider = await _load_memory_provider(
        request,
        provider_id,
        permission="provider.memory.validate",
    )
    logger.debug("HTTP health_check_memory_provider provider_id=%s", provider_id)
    try:
        return await check_memory_provider_health(provider)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/memory-providers/{provider_id}/health-check",
    response_model=MemoryProviderHealthReport,
    summary="Validate an organization-scoped memory provider configuration",
)
async def health_check_organization_memory_provider(
    request: Request,
    organization_id: UUID,
    provider_id: UUID,
) -> MemoryProviderHealthReport:
    provider = await _load_memory_provider(
        request,
        provider_id,
        permission="provider.memory.validate",
        organization_id=organization_id,
    )
    try:
        return await check_memory_provider_health(provider)
    except Exception as exc:
        raise _http_error(exc) from exc


async def _load_mcp_server(
    request: Request,
    server_id: UUID,
    *,
    permission: str,
    organization_id: UUID | None = None,
) -> McpServerDefinition:
    server = await collab_svc.collaboration_service.get_mcp_server(server_id)
    if organization_id is not None and server.organization_id != organization_id:
        raise HTTPException(status_code=404, detail=f"MCP server {server_id} not found")
    await _require_identity_permission(
        request,
        permission=permission,
        organization_id=organization_id or server.organization_id,
    )
    return server


@router.post(
    "/mcp-servers",
    response_model=McpServerDefinition,
    summary="Create a global external MCP server definition",
)
async def create_mcp_server(
    request: Request,
    payload: CreateMcpServerRequest,
) -> McpServerDefinition:
    await _require_identity_permission(request, permission="provider.mcp.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.create_mcp_server(payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/mcp-servers",
    response_model=McpServerDefinition,
    summary="Create an organization-scoped external MCP server definition",
)
async def create_organization_mcp_server(
    request: Request,
    organization_id: UUID,
    payload: CreateMcpServerRequest,
) -> McpServerDefinition:
    await _require_identity_permission(
        request,
        permission="provider.mcp.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.create_mcp_server(
            payload,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/mcp-servers",
    response_model=list[McpServerDefinition],
    summary="List global external MCP server definitions",
)
async def list_mcp_servers(request: Request) -> list[McpServerDefinition]:
    await _require_identity_permission(request, permission="provider.mcp.read")
    try:
        return await collab_svc.collaboration_service.list_mcp_servers()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/mcp-servers",
    response_model=list[McpServerDefinition],
    summary="List organization-scoped external MCP server definitions",
)
async def list_organization_mcp_servers(
    request: Request,
    organization_id: UUID,
) -> list[McpServerDefinition]:
    await _require_identity_permission(
        request,
        permission="provider.mcp.read",
        organization_id=organization_id,
    )
    try:
        return await collab_svc.collaboration_service.list_mcp_servers(
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/mcp-servers/{server_id}", response_model=McpServerDefinition)
async def get_mcp_server(request: Request, server_id: UUID) -> McpServerDefinition:
    try:
        return await _load_mcp_server(
            request,
            server_id,
            permission="provider.mcp.read",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/mcp-servers/{server_id}",
    response_model=McpServerDefinition,
)
async def get_organization_mcp_server(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
) -> McpServerDefinition:
    try:
        return await _load_mcp_server(
            request,
            server_id,
            permission="provider.mcp.read",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch("/mcp-servers/{server_id}", response_model=McpServerDefinition)
async def update_mcp_server(
    request: Request,
    server_id: UUID,
    payload: UpdateMcpServerRequest,
) -> McpServerDefinition:
    await _load_mcp_server(request, server_id, permission="provider.mcp.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.update_mcp_server(server_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/organizations/{organization_id}/mcp-servers/{server_id}",
    response_model=McpServerDefinition,
)
async def update_organization_mcp_server(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    payload: UpdateMcpServerRequest,
) -> McpServerDefinition:
    await _load_mcp_server(
        request,
        server_id,
        permission="provider.mcp.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.update_mcp_server(server_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete("/mcp-servers/{server_id}", response_model=dict)
async def delete_mcp_server(
    request: Request,
    server_id: UUID,
    payload: DeleteMcpServerRequest = Body(...),
) -> dict[str, bool | str]:
    await _load_mcp_server(request, server_id, permission="provider.mcp.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.delete_mcp_server(server_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/organizations/{organization_id}/mcp-servers/{server_id}",
    response_model=dict,
)
async def delete_organization_mcp_server(
    request: Request,
    organization_id: UUID,
    server_id: UUID,
    payload: DeleteMcpServerRequest = Body(...),
) -> dict[str, bool | str]:
    await _load_mcp_server(
        request,
        server_id,
        permission="provider.mcp.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.delete_mcp_server(server_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/mcp-servers/{server_id}/tools", response_model=list[McpToolDefinition])
async def list_mcp_server_tools(request: Request, server_id: UUID) -> list[McpToolDefinition]:
    await _load_mcp_server(request, server_id, permission="provider.mcp.read")
    try:
        return await collab_svc.collaboration_service.list_mcp_server_tools(server_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/mcp-servers/{server_id}/resources", response_model=list[McpResourceDefinition])
async def list_mcp_server_resources(request: Request, server_id: UUID) -> list[McpResourceDefinition]:
    await _load_mcp_server(request, server_id, permission="provider.mcp.read")
    try:
        return await collab_svc.collaboration_service.list_mcp_server_resources(server_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/mcp-servers/{server_id}/prompts", response_model=list[McpPromptDefinition])
async def list_mcp_server_prompts(request: Request, server_id: UUID) -> list[McpPromptDefinition]:
    await _load_mcp_server(request, server_id, permission="provider.mcp.read")
    try:
        return await collab_svc.collaboration_service.list_mcp_server_prompts(server_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/agents",
    response_model=list[AgentDefinition],
    summary="List system-level agent definitions",
)
async def list_system_agents(request: Request) -> list[AgentDefinition]:
    await _require_identity_permission(request, permission="agent_catalog.read")
    logger.debug("HTTP list_system_agents")
    try:
        return await collab_svc.collaboration_service.list_system_agents()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/agents",
    response_model=list[AgentDefinition],
    summary="List organization-scoped agent definitions",
)
async def list_organization_system_agents(
    request: Request,
    organization_id: UUID,
) -> list[AgentDefinition]:
    await _require_identity_permission(
        request,
        permission="agent_catalog.read",
        organization_id=organization_id,
    )
    try:
        return await collab_svc.collaboration_service.list_system_agents(
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/agents/{agent_id}",
    response_model=AgentDefinition,
    summary="Get an agent definition",
)
async def get_system_agent(
    request: Request,
    agent_id: UUID,
) -> AgentDefinition:
    try:
        return await _load_system_agent_definition(
            request,
            agent_id,
            permission="agent_catalog.read",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/agents/{agent_id}",
    response_model=AgentDefinition,
    summary="Get an organization-scoped agent definition",
)
async def get_organization_system_agent(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
) -> AgentDefinition:
    try:
        return await _load_system_agent_definition(
            request,
            agent_id,
            permission="agent_catalog.read",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/agents/{agent_id}/versions",
    response_model=list[AgentDefinitionVersion],
    summary="List published versions for a system-wide agent definition",
)
async def list_agent_definition_versions(
    request: Request,
    agent_id: UUID,
) -> list[AgentDefinitionVersion]:
    await _load_system_agent_definition(
        request,
        agent_id,
        permission="agent_catalog.read",
    )
    try:
        return await collab_svc.collaboration_service.list_agent_definition_versions(agent_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/agents/{agent_id}/versions",
    response_model=list[AgentDefinitionVersion],
    summary="List published versions for an organization-wide agent definition",
)
async def list_organization_agent_definition_versions(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
) -> list[AgentDefinitionVersion]:
    await _load_system_agent_definition(
        request,
        agent_id,
        permission="agent_catalog.read",
        organization_id=organization_id,
    )
    try:
        return await collab_svc.collaboration_service.list_agent_definition_versions(agent_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agents/{agent_id}/versions/{agent_version_id}/activate",
    response_model=AgentBundlePublishResult,
    summary="Activate a published version for a system-wide agent definition",
)
async def activate_agent_definition_version(
    request: Request,
    agent_id: UUID,
    agent_version_id: UUID,
    payload: ActivateAgentDefinitionVersionRequest,
) -> AgentBundlePublishResult:
    await _load_system_agent_definition(
        request,
        agent_id,
        permission="agent_catalog.write",
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.activate_agent_definition_version(
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/agents/{agent_id}/versions/{agent_version_id}/activate",
    response_model=AgentBundlePublishResult,
    summary="Activate a published version for an organization-wide agent definition",
)
async def activate_organization_agent_definition_version(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    agent_version_id: UUID,
    payload: ActivateAgentDefinitionVersionRequest,
) -> AgentBundlePublishResult:
    await _load_system_agent_definition(
        request,
        agent_id,
        permission="agent_catalog.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.activate_agent_definition_version(
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/tools",
    response_model=SystemToolDefinition,
    summary="Create a system-wide tool definition",
)
async def create_system_tool(
    request: Request,
    payload: CreateSystemToolRequest,
) -> SystemToolDefinition:
    await _require_identity_permission(request, permission="tool_catalog.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP create_system_tool actor=%s name=%r",
        _actor_log(payload.actor),
        payload.name,
    )
    try:
        return await collab_svc.collaboration_service.create_system_tool(payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/tools",
    response_model=SystemToolDefinition,
    summary="Create an organization-scoped tool definition",
)
async def create_organization_system_tool(
    request: Request,
    organization_id: UUID,
    payload: CreateSystemToolRequest,
) -> SystemToolDefinition:
    await _require_identity_permission(
        request,
        permission="tool_catalog.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.create_system_tool(
            payload,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/tools",
    response_model=list[SystemToolDefinition],
    summary="List system-wide tool definitions",
)
async def list_system_tools(request: Request) -> list[SystemToolDefinition]:
    await _require_identity_permission(request, permission="tool_catalog.read")
    logger.debug("HTTP list_system_tools")
    try:
        return await collab_svc.collaboration_service.list_system_tools()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/tools",
    response_model=list[SystemToolDefinition],
    summary="List organization-scoped tool definitions",
)
async def list_organization_system_tools(
    request: Request,
    organization_id: UUID,
) -> list[SystemToolDefinition]:
    await _require_identity_permission(
        request,
        permission="tool_catalog.read",
        organization_id=organization_id,
    )
    try:
        return await collab_svc.collaboration_service.list_system_tools(
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/tools/{tool_id}",
    response_model=SystemToolDefinition,
    summary="Get a tool definition",
)
async def get_system_tool(
    request: Request,
    tool_id: UUID,
) -> SystemToolDefinition:
    try:
        return await _load_system_tool_definition(
            request,
            tool_id,
            permission="tool_catalog.read",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/tools/{tool_id}",
    response_model=SystemToolDefinition,
    summary="Get an organization-scoped tool definition",
)
async def get_organization_system_tool(
    request: Request,
    organization_id: UUID,
    tool_id: UUID,
) -> SystemToolDefinition:
    try:
        return await _load_system_tool_definition(
            request,
            tool_id,
            permission="tool_catalog.read",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/tools/{tool_id}",
    response_model=SystemToolDefinition,
    summary="Update a tool definition",
)
async def update_system_tool(
    request: Request,
    tool_id: UUID,
    payload: UpdateSystemToolRequest,
) -> SystemToolDefinition:
    await _load_system_tool_definition(
        request,
        tool_id,
        permission="tool_catalog.write",
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP update_system_tool tool_id=%s actor=%s",
        tool_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.update_system_tool(
            tool_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/organizations/{organization_id}/tools/{tool_id}",
    response_model=SystemToolDefinition,
    summary="Update an organization-scoped tool definition",
)
async def update_organization_system_tool(
    request: Request,
    organization_id: UUID,
    tool_id: UUID,
    payload: UpdateSystemToolRequest,
) -> SystemToolDefinition:
    await _load_system_tool_definition(
        request,
        tool_id,
        permission="tool_catalog.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.update_system_tool(
            tool_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/agents/{agent_id}",
    response_model=AgentDefinition,
    summary="Update an agent definition",
)
async def update_system_agent(
    request: Request,
    agent_id: UUID,
    payload: UpdateSystemAgentRequest,
) -> AgentDefinition:
    await _load_system_agent_definition(
        request,
        agent_id,
        permission="agent_catalog.write",
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP update_system_agent agent_id=%s actor=%s",
        agent_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.update_system_agent(
            agent_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/organizations/{organization_id}/agents/{agent_id}",
    response_model=AgentDefinition,
    summary="Update an organization-scoped agent definition",
)
async def update_organization_system_agent(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    payload: UpdateSystemAgentRequest,
) -> AgentDefinition:
    await _load_system_agent_definition(
        request,
        agent_id,
        permission="agent_catalog.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.update_system_agent(
            agent_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/agents/{agent_id}",
    response_model=dict,
    summary="Delete an agent definition",
)
async def delete_system_agent(
    request: Request,
    agent_id: UUID,
    payload: DeleteSystemAgentRequest = Body(...),
) -> dict[str, bool | str]:
    await _load_system_agent_definition(
        request,
        agent_id,
        permission="agent_catalog.write",
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP delete_system_agent agent_id=%s actor=%s",
        agent_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.delete_system_agent(agent_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/organizations/{organization_id}/agents/{agent_id}",
    response_model=dict,
    summary="Delete an organization-scoped agent definition",
)
async def delete_organization_system_agent(
    request: Request,
    organization_id: UUID,
    agent_id: UUID,
    payload: DeleteSystemAgentRequest = Body(...),
) -> dict[str, bool | str]:
    await _load_system_agent_definition(
        request,
        agent_id,
        permission="agent_catalog.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.delete_system_agent(agent_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/tools/{tool_id}",
    response_model=dict,
    summary="Delete a tool definition",
)
async def delete_system_tool(
    request: Request,
    tool_id: UUID,
    payload: DeleteSystemToolRequest = Body(...),
) -> dict[str, bool | str]:
    await _load_system_tool_definition(
        request,
        tool_id,
        permission="tool_catalog.write",
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP delete_system_tool tool_id=%s actor=%s",
        tool_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.delete_system_tool(tool_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/organizations/{organization_id}/tools/{tool_id}",
    response_model=dict,
    summary="Delete an organization-scoped tool definition",
)
async def delete_organization_system_tool(
    request: Request,
    organization_id: UUID,
    tool_id: UUID,
    payload: DeleteSystemToolRequest = Body(...),
) -> dict[str, bool | str]:
    await _load_system_tool_definition(
        request,
        tool_id,
        permission="tool_catalog.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(
        update={"actor": _resolve_organization_actor(request, payload.actor)}
    )
    try:
        return await collab_svc.collaboration_service.delete_system_tool(tool_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/git-repositories",
    response_model=GitRepository,
    summary="Register a global Git repository for authored definitions or code",
)
async def create_global_git_repository(
    request: Request,
    payload: CreateGitRepositoryRequest,
) -> GitRepository:
    await _require_identity_permission(request, permission="git_registry.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP create_global_git_repository actor=%s name=%r local_path=%s",
        _actor_log(payload.actor),
        payload.name,
        payload.local_path,
    )
    try:
        return await collab_svc.collaboration_service.create_git_repository(
            scope="global",
            organization_id=None,
            workspace_id=None,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/git-repositories",
    response_model=list[GitRepository],
    summary="List globally registered Git repositories",
)
async def list_global_git_repositories(request: Request) -> list[GitRepository]:
    await _require_identity_permission(request, permission="git_registry.read")
    logger.debug("HTTP list_global_git_repositories")
    try:
        return await collab_svc.collaboration_service.list_git_repositories(
            scope="global",
            organization_id=None,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/git-repositories",
    response_model=GitRepository,
    summary="Register an organization Git repository",
)
async def create_organization_git_repository(
    request: Request,
    organization_id: UUID,
    payload: CreateGitRepositoryRequest,
) -> GitRepository:
    await _require_identity_permission(
        request,
        permission="git_registry.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.create_git_repository(
            scope="organization",
            organization_id=organization_id,
            workspace_id=None,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/git-repositories",
    response_model=list[GitRepository],
    summary="List organization Git repositories",
)
async def list_organization_git_repositories(
    request: Request,
    organization_id: UUID,
) -> list[GitRepository]:
    await _require_identity_permission(
        request,
        permission="git_registry.read",
        organization_id=organization_id,
    )
    try:
        return await collab_svc.collaboration_service.list_git_repositories(
            scope="organization",
            organization_id=organization_id,
            workspace_id=None,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agent-git/worktrees",
    response_model=AgentGitWorktreeSession,
    summary="Create a managed worktree session for system-wide agent authoring",
)
async def create_system_agent_git_worktree(
    request: Request,
    payload: CreateAgentGitWorktreeSessionRequest,
) -> AgentGitWorktreeSession:
    await _require_identity_permission(request, permission="agent_catalog.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.create_agent_git_worktree_session(
            scope="global",
            organization_id=None,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/agent-git/worktrees",
    response_model=AgentGitWorktreeSession,
    summary="Create a managed worktree session for organization-wide agent authoring",
)
async def create_organization_agent_git_worktree(
    request: Request,
    organization_id: UUID,
    payload: CreateAgentGitWorktreeSessionRequest,
) -> AgentGitWorktreeSession:
    await _require_identity_permission(
        request,
        permission="agent_catalog.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.create_agent_git_worktree_session(
            scope="organization",
            organization_id=organization_id,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/agent-git/worktrees/{session_id}/files",
    response_model=AgentGitFileContent,
    summary="Read a file from a managed agent-authoring worktree",
)
async def read_agent_git_worktree_file(
    request: Request,
    session_id: UUID,
    path: str = Query(...),
) -> AgentGitFileContent:
    await _require_worktree_session_permission(request, session_id)
    try:
        return await collab_svc.collaboration_service.read_agent_git_worktree_file(
            session_id,
            path,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put(
    "/agent-git/worktrees/{session_id}/files",
    response_model=AgentGitFileContent,
    summary="Write a file in a managed agent-authoring worktree",
)
async def write_agent_git_worktree_file(
    request: Request,
    session_id: UUID,
    payload: AgentGitFileMutationRequest,
) -> AgentGitFileContent:
    session = await _require_worktree_session_permission(request, session_id)
    payload = payload.model_copy(
        update={
            "actor": (
                _resolve_organization_actor(request, payload.actor)
                if session.scope == "organization"
                else _resolve_global_actor(request, payload.actor)
            )
        }
    )
    try:
        return await collab_svc.collaboration_service.write_agent_git_worktree_file(
            session_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/agent-git/worktrees/{session_id}/files",
    response_model=dict,
    summary="Delete a file from a managed agent-authoring worktree",
)
async def delete_agent_git_worktree_file(
    request: Request,
    session_id: UUID,
    payload: AgentGitFileMutationRequest = Body(...),
) -> dict[str, bool | str]:
    session = await _require_worktree_session_permission(request, session_id)
    payload = payload.model_copy(
        update={
            "actor": (
                _resolve_organization_actor(request, payload.actor)
                if session.scope == "organization"
                else _resolve_global_actor(request, payload.actor)
            )
        }
    )
    try:
        return await collab_svc.collaboration_service.delete_agent_git_worktree_file(
            session_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/agent-git/worktrees/{session_id}/diff",
    response_model=AgentGitDiffResult,
    summary="Preview changes in a managed agent-authoring worktree",
)
async def diff_agent_git_worktree(
    request: Request,
    session_id: UUID,
) -> AgentGitDiffResult:
    await _require_worktree_session_permission(request, session_id)
    try:
        return await collab_svc.collaboration_service.diff_agent_git_worktree(session_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/agent-git/worktrees/{session_id}/commit",
    response_model=AgentGitCommitResult,
    summary="Commit and optionally push changes from a managed agent-authoring worktree",
)
async def commit_agent_git_worktree(
    request: Request,
    session_id: UUID,
    payload: AgentGitCommitRequest,
) -> AgentGitCommitResult:
    session = await _require_worktree_session_permission(request, session_id)
    payload = payload.model_copy(
        update={
            "actor": (
                _resolve_organization_actor(request, payload.actor)
                if session.scope == "organization"
                else _resolve_global_actor(request, payload.actor)
            )
        }
    )
    try:
        return await collab_svc.collaboration_service.commit_agent_git_worktree(
            session_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/agent-git/worktrees/{session_id}",
    response_model=dict,
    summary="Discard a managed agent-authoring worktree session",
)
async def discard_agent_git_worktree(
    request: Request,
    session_id: UUID,
) -> dict[str, bool | str]:
    await _require_worktree_session_permission(request, session_id)
    try:
        return await collab_svc.collaboration_service.discard_agent_git_worktree(session_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/assets/publish-from-git",
    response_model=WorkspaceAssetVersion,
    summary="Publish a global immutable asset version from a registered Git repository",
)
async def publish_global_asset_from_git(
    request: Request,
    payload: PublishAssetFromGitRequest,
) -> WorkspaceAssetVersion:
    await _require_identity_permission(request, permission="asset_catalog.publish")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP publish_global_asset_from_git actor=%s repository_id=%s logical_name=%r path=%s",
        _actor_log(payload.actor),
        payload.repository_id,
        payload.logical_name,
        payload.git_path,
    )
    try:
        return await collab_svc.collaboration_service.publish_asset_from_git(
            scope="global",
            organization_id=None,
            workspace_id=None,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/assets/publish-from-git",
    response_model=WorkspaceAssetVersion,
    summary="Publish an organization immutable asset version from Git",
)
async def publish_organization_asset_from_git(
    request: Request,
    organization_id: UUID,
    payload: PublishAssetFromGitRequest,
) -> WorkspaceAssetVersion:
    await _require_identity_permission(
        request,
        permission="asset_catalog.publish",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_organization_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.publish_asset_from_git(
            scope="organization",
            organization_id=organization_id,
            workspace_id=None,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/assets",
    response_model=list[WorkspaceAsset],
    summary="List organization-scoped assets",
)
async def list_organization_assets(
    request: Request,
    organization_id: UUID,
) -> list[WorkspaceAsset]:
    await _require_identity_permission(
        request,
        permission="asset_catalog.read",
        organization_id=organization_id,
    )
    try:
        return await collab_svc.collaboration_service.list_workspace_assets(
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/assets",
    response_model=list[WorkspaceAsset],
    summary="List published assets with optional workspace scoping",
)
async def list_assets(
    request: Request,
    organization_id: UUID | None = Query(default=None),
    workspace_id: UUID | None = Query(default=None),
    scope: str | None = Query(default=None),
) -> list[WorkspaceAsset]:
    logger.debug(
        "HTTP list_assets organization_id=%s workspace_id=%s scope=%s",
        organization_id,
        workspace_id,
        scope,
    )
    try:
        if organization_id is not None and workspace_id is None:
            await _require_identity_permission(
                request,
                permission="asset_catalog.read",
                organization_id=organization_id,
            )
        if workspace_id is not None:
            await _require_workspace_membership(request, workspace_id)
        if organization_id is None and workspace_id is None:
            await _require_identity_permission(request, permission="asset_catalog.read")
        return await collab_svc.collaboration_service.list_workspace_assets(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/files",
    response_model=WorkspaceAssetVersion,
    summary="Upload a global immutable file asset",
)
async def upload_global_file(
    request: Request,
    file: UploadFile = File(...),
    logical_name: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(default=None),
    logical_path: str | None = Form(default=None),
    content_type: str | None = Form(default=None),
    actor_participant_id: UUID | None = Form(default=None),
    actor_type: str = Form(default="user"),
    actor_display_name: str = Form(default="uploader"),
) -> WorkspaceAssetVersion:
    await _require_identity_permission(request, permission="asset_catalog.publish")
    actor = _resolve_global_actor(
        request,
        _form_actor(
            actor_participant_id=actor_participant_id,
            actor_type=actor_type,
            actor_display_name=actor_display_name,
        ),
    )
    payload = UploadFileAssetRequest(
        actor=actor,
        logical_name=logical_name,
        logical_path=logical_path,
        title=title,
        description=description,
        content_type=content_type or file.content_type,
    )
    try:
        return await collab_svc.collaboration_service.upload_file_asset(
            scope="global",
            organization_id=None,
            workspace_id=None,
            payload=payload,
            filename=file.filename or logical_name,
            content=await file.read(),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/files",
    response_model=list[WorkspaceAsset],
    summary="List global file assets",
)
async def list_global_files(request: Request) -> list[WorkspaceAsset]:
    await _require_identity_permission(request, permission="asset_catalog.read")
    try:
        assets = await collab_svc.collaboration_service.list_workspace_assets(scope="global")
        return [asset for asset in assets if asset.asset_type == "file"]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/files",
    response_model=WorkspaceAssetVersion,
    summary="Upload an organization immutable file asset",
)
async def upload_organization_file(
    request: Request,
    organization_id: UUID,
    file: UploadFile = File(...),
    logical_name: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(default=None),
    logical_path: str | None = Form(default=None),
    content_type: str | None = Form(default=None),
    actor_participant_id: UUID | None = Form(default=None),
    actor_type: str = Form(default="user"),
    actor_display_name: str = Form(default="uploader"),
) -> WorkspaceAssetVersion:
    await _require_organization_membership(request, organization_id)
    await _require_identity_permission(
        request,
        permission="asset_catalog.publish",
        organization_id=organization_id,
    )
    actor = _resolve_organization_actor(
        request,
        _form_actor(
            actor_participant_id=actor_participant_id,
            actor_type=actor_type,
            actor_display_name=actor_display_name,
        ),
    )
    payload = UploadFileAssetRequest(
        actor=actor,
        logical_name=logical_name,
        logical_path=logical_path,
        title=title,
        description=description,
        content_type=content_type or file.content_type,
    )
    try:
        return await collab_svc.collaboration_service.upload_file_asset(
            scope="organization",
            organization_id=organization_id,
            workspace_id=None,
            payload=payload,
            filename=file.filename or logical_name,
            content=await file.read(),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/files",
    response_model=list[WorkspaceAsset],
    summary="List organization file assets",
)
async def list_organization_files(
    request: Request,
    organization_id: UUID,
) -> list[WorkspaceAsset]:
    await _require_organization_membership(request, organization_id)
    await _require_identity_permission(
        request,
        permission="asset_catalog.read",
        organization_id=organization_id,
    )
    try:
        assets = await collab_svc.collaboration_service.list_workspace_assets(
            scope="organization",
            organization_id=organization_id,
        )
        return [asset for asset in assets if asset.asset_type == "file"]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/files",
    response_model=WorkspaceAssetVersion,
    summary="Upload a workspace immutable file asset",
)
async def upload_workspace_file(
    request: Request,
    workspace_id: UUID,
    file: UploadFile = File(...),
    logical_name: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(default=None),
    logical_path: str | None = Form(default=None),
    content_type: str | None = Form(default=None),
    actor_participant_id: UUID | None = Form(default=None),
    actor_type: str = Form(default="user"),
    actor_display_name: str = Form(default="uploader"),
) -> WorkspaceAssetVersion:
    authorized_actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.assets.publish",
    )
    form_actor = _form_actor(
        actor_participant_id=actor_participant_id,
        actor_type=actor_type,
        actor_display_name=actor_display_name,
    )
    actor = authorized_actor or await _resolve_workspace_actor(
        request,
        form_actor,
        workspace_id=workspace_id,
        auto_create=False,
    )
    payload = UploadFileAssetRequest(
        actor=actor,
        logical_name=logical_name,
        logical_path=logical_path,
        title=title,
        description=description,
        content_type=content_type or file.content_type,
    )
    try:
        return await collab_svc.collaboration_service.upload_file_asset(
            scope="workspace",
            organization_id=None,
            workspace_id=workspace_id,
            payload=payload,
            filename=file.filename or logical_name,
            content=await file.read(),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/files",
    response_model=list[WorkspaceAsset],
    summary="List workspace file assets",
)
async def list_workspace_files(
    request: Request,
    workspace_id: UUID,
) -> list[WorkspaceAsset]:
    await _require_workspace_membership(request, workspace_id)
    try:
        assets = await collab_svc.collaboration_service.list_workspace_assets(
            scope="workspace",
            workspace_id=workspace_id,
        )
        return [asset for asset in assets if asset.asset_type == "file"]
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/files/{asset_id}",
    response_model=WorkspaceAsset,
    summary="Get a visible file asset",
)
async def get_file_asset(request: Request, asset_id: UUID) -> WorkspaceAsset:
    try:
        return await _require_file_asset_visibility(request, asset_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/files/{asset_id}/versions",
    response_model=list[WorkspaceAssetVersion],
    summary="List immutable versions for a file asset",
)
async def list_file_asset_versions(
    request: Request,
    asset_id: UUID,
) -> list[WorkspaceAssetVersion]:
    try:
        await _require_file_asset_visibility(request, asset_id)
        return await collab_svc.collaboration_service.list_workspace_asset_versions(asset_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/files/{asset_id}/download",
    response_model=dict,
    summary="Generate a presigned download URL for a file asset version",
)
async def get_file_download_url(
    request: Request,
    asset_id: UUID,
    asset_version_id: UUID | None = Query(default=None),
) -> dict[str, str]:
    try:
        await _require_file_asset_visibility(request, asset_id)
        url = await collab_svc.collaboration_service.get_asset_download_url(
            asset_id,
            asset_version_id=asset_version_id,
        )
        return {"url": url}
    except Exception as exc:
        raise _http_error(exc) from exc


async def _create_retrieval_profile(
    request: Request,
    payload: CreateRetrievalProfileRequest,
    *,
    scope: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> RetrievalProfile:
    actor = await _resolve_retrieval_actor(
        request,
        payload.actor,
        permission="retrieval.write",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return await collab_svc.collaboration_service.create_retrieval_profile(
        scope=scope,
        organization_id=organization_id,
        workspace_id=workspace_id,
        payload=payload.model_copy(update={"actor": actor}),
    )


async def _list_retrieval_profiles(
    request: Request,
    *,
    scope: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> list[RetrievalProfile]:
    await _require_retrieval_permission(
        request,
        permission="retrieval.read",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return await collab_svc.collaboration_service.list_retrieval_profiles(
        scope=scope,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )


async def _create_retrieval_corpus(
    request: Request,
    payload: CreateRetrievalCorpusRequest,
    *,
    scope: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> RetrievalCorpus:
    actor = await _resolve_retrieval_actor(
        request,
        payload.actor,
        permission="retrieval.write",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return await collab_svc.collaboration_service.create_retrieval_corpus(
        scope=scope,
        organization_id=organization_id,
        workspace_id=workspace_id,
        payload=payload.model_copy(update={"actor": actor}),
    )


async def _list_retrieval_corpora(
    request: Request,
    *,
    scope: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> list[RetrievalCorpus]:
    await _require_retrieval_permission(
        request,
        permission="retrieval.read",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return await collab_svc.collaboration_service.list_retrieval_corpora(
        scope=scope,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )


async def _create_retrieval_source(
    request: Request,
    payload: CreateRetrievalSourceRequest,
    *,
    scope: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> RetrievalSource:
    await _require_file_asset_visibility(request, payload.asset_id)
    actor = await _resolve_retrieval_actor(
        request,
        payload.actor,
        permission="retrieval.write",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return await collab_svc.collaboration_service.create_retrieval_source(
        scope=scope,
        organization_id=organization_id,
        workspace_id=workspace_id,
        payload=payload.model_copy(update={"actor": actor}),
    )


async def _list_retrieval_sources(
    request: Request,
    *,
    scope: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    corpus_id: UUID | None = None,
) -> list[RetrievalSource]:
    await _require_retrieval_permission(
        request,
        permission="retrieval.read",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return await collab_svc.collaboration_service.list_retrieval_sources(
        corpus_id=corpus_id,
        scope=scope,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )


async def _create_retrieval_job(
    request: Request,
    corpus_id: UUID,
    payload: CreateRetrievalIngestionJobRequest,
    *,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> RetrievalIngestionJob:
    actor = await _resolve_retrieval_actor(
        request,
        payload.actor,
        permission="retrieval.write",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return await collab_svc.collaboration_service.create_retrieval_ingestion_job(
        corpus_id=corpus_id,
        payload=payload.model_copy(update={"actor": actor}),
    )


async def _list_retrieval_jobs(
    request: Request,
    *,
    scope: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
    corpus_id: UUID | None = None,
    source_id: UUID | None = None,
    status: str | None = None,
) -> list[RetrievalIngestionJob]:
    await _require_retrieval_permission(
        request,
        permission="retrieval.read",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return await collab_svc.collaboration_service.list_retrieval_ingestion_jobs(
        corpus_id=corpus_id,
        source_id=source_id,
        scope=scope,
        organization_id=organization_id,
        workspace_id=workspace_id,
        status=status,
    )


async def _run_retrieval_search(
    request: Request,
    payload: RunRetrievalSearchRequest,
    *,
    scope: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> RetrievalSearchResponse:
    actor = await _resolve_retrieval_actor(
        request,
        payload.actor,
        permission="retrieval.search",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    actor = await _apply_retrieval_provider_override_permission(
        request,
        actor,
        payload.provider_overrides,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return await collab_svc.collaboration_service.run_retrieval_search(
        scope=scope,
        organization_id=organization_id,
        workspace_id=workspace_id,
        payload=payload.model_copy(update={"actor": actor}),
    )


async def _create_retrieval_context_pack(
    request: Request,
    payload: CreateRetrievalContextPackRequest,
    *,
    scope: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> RetrievalContextPack:
    actor = await _resolve_retrieval_actor(
        request,
        payload.actor,
        permission="retrieval.search",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    actor = await _apply_retrieval_provider_override_permission(
        request,
        actor,
        payload.provider_overrides,
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    return await collab_svc.collaboration_service.create_retrieval_context_pack(
        scope=scope,
        organization_id=organization_id,
        workspace_id=workspace_id,
        payload=payload.model_copy(update={"actor": actor}),
    )


async def _get_retrieval_context_pack(
    request: Request,
    context_pack_id: UUID,
    *,
    scope: str,
    organization_id: UUID | None = None,
    workspace_id: UUID | None = None,
) -> RetrievalContextPack:
    await _require_retrieval_permission(
        request,
        permission="retrieval.read",
        organization_id=organization_id,
        workspace_id=workspace_id,
    )
    context_pack = await collab_svc.collaboration_service.get_retrieval_context_pack(
        context_pack_id
    )
    if context_pack is None:
        raise KeyError(f"Retrieval context pack {context_pack_id} not found")
    expected_organization_id = organization_id
    if workspace_id is not None and expected_organization_id is None:
        workspace = await collab_svc.collaboration_service.get_workspace(workspace_id)
        expected_organization_id = workspace.workspace.organization_id
    if (
        context_pack.scope != scope
        or context_pack.organization_id != expected_organization_id
        or context_pack.workspace_id != workspace_id
    ):
        raise KeyError(f"Retrieval context pack {context_pack_id} not found")
    return context_pack


@router.post("/retrieval/profiles", response_model=RetrievalProfile)
async def create_global_retrieval_profile(
    request: Request,
    payload: CreateRetrievalProfileRequest,
) -> RetrievalProfile:
    try:
        return await _create_retrieval_profile(request, payload, scope="global")
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/retrieval/profiles", response_model=list[RetrievalProfile])
async def list_global_retrieval_profiles(request: Request) -> list[RetrievalProfile]:
    try:
        return await _list_retrieval_profiles(request, scope="global")
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/retrieval/corpora", response_model=RetrievalCorpus)
async def create_global_retrieval_corpus(
    request: Request,
    payload: CreateRetrievalCorpusRequest,
) -> RetrievalCorpus:
    try:
        return await _create_retrieval_corpus(request, payload, scope="global")
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/retrieval/corpora", response_model=list[RetrievalCorpus])
async def list_global_retrieval_corpora(request: Request) -> list[RetrievalCorpus]:
    try:
        return await _list_retrieval_corpora(request, scope="global")
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/retrieval/sources", response_model=RetrievalSource)
async def create_global_retrieval_source(
    request: Request,
    payload: CreateRetrievalSourceRequest,
) -> RetrievalSource:
    try:
        return await _create_retrieval_source(request, payload, scope="global")
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/retrieval/sources", response_model=list[RetrievalSource])
async def list_global_retrieval_sources(
    request: Request,
    corpus_id: UUID | None = Query(default=None),
) -> list[RetrievalSource]:
    try:
        return await _list_retrieval_sources(
            request,
            scope="global",
            corpus_id=corpus_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/retrieval/corpora/{corpus_id}/jobs", response_model=RetrievalIngestionJob)
async def create_global_retrieval_job(
    request: Request,
    corpus_id: UUID,
    payload: CreateRetrievalIngestionJobRequest,
) -> RetrievalIngestionJob:
    try:
        return await _create_retrieval_job(request, corpus_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/retrieval/jobs", response_model=list[RetrievalIngestionJob])
async def list_global_retrieval_jobs(
    request: Request,
    corpus_id: UUID | None = Query(default=None),
    source_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[RetrievalIngestionJob]:
    try:
        return await _list_retrieval_jobs(
            request,
            scope="global",
            corpus_id=corpus_id,
            source_id=source_id,
            status=status,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/retrieval/search", response_model=RetrievalSearchResponse)
async def run_global_retrieval_search(
    request: Request,
    payload: RunRetrievalSearchRequest,
) -> RetrievalSearchResponse:
    try:
        return await _run_retrieval_search(request, payload, scope="global")
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/retrieval/context-packs", response_model=RetrievalContextPack)
async def create_global_retrieval_context_pack(
    request: Request,
    payload: CreateRetrievalContextPackRequest,
) -> RetrievalContextPack:
    try:
        return await _create_retrieval_context_pack(request, payload, scope="global")
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/retrieval/context-packs/{context_pack_id}", response_model=RetrievalContextPack)
async def get_global_retrieval_context_pack(
    request: Request,
    context_pack_id: UUID,
) -> RetrievalContextPack:
    try:
        return await _get_retrieval_context_pack(
            request,
            context_pack_id,
            scope="global",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/organizations/{organization_id}/retrieval/profiles", response_model=RetrievalProfile)
async def create_organization_retrieval_profile(
    request: Request,
    organization_id: UUID,
    payload: CreateRetrievalProfileRequest,
) -> RetrievalProfile:
    try:
        return await _create_retrieval_profile(
            request,
            payload,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/organizations/{organization_id}/retrieval/profiles", response_model=list[RetrievalProfile])
async def list_organization_retrieval_profiles(
    request: Request,
    organization_id: UUID,
) -> list[RetrievalProfile]:
    try:
        return await _list_retrieval_profiles(
            request,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/organizations/{organization_id}/retrieval/corpora", response_model=RetrievalCorpus)
async def create_organization_retrieval_corpus(
    request: Request,
    organization_id: UUID,
    payload: CreateRetrievalCorpusRequest,
) -> RetrievalCorpus:
    try:
        return await _create_retrieval_corpus(
            request,
            payload,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/organizations/{organization_id}/retrieval/corpora", response_model=list[RetrievalCorpus])
async def list_organization_retrieval_corpora(
    request: Request,
    organization_id: UUID,
) -> list[RetrievalCorpus]:
    try:
        return await _list_retrieval_corpora(
            request,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/organizations/{organization_id}/retrieval/sources", response_model=RetrievalSource)
async def create_organization_retrieval_source(
    request: Request,
    organization_id: UUID,
    payload: CreateRetrievalSourceRequest,
) -> RetrievalSource:
    try:
        return await _create_retrieval_source(
            request,
            payload,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/organizations/{organization_id}/retrieval/sources", response_model=list[RetrievalSource])
async def list_organization_retrieval_sources(
    request: Request,
    organization_id: UUID,
    corpus_id: UUID | None = Query(default=None),
) -> list[RetrievalSource]:
    try:
        return await _list_retrieval_sources(
            request,
            scope="organization",
            organization_id=organization_id,
            corpus_id=corpus_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/organizations/{organization_id}/retrieval/corpora/{corpus_id}/jobs", response_model=RetrievalIngestionJob)
async def create_organization_retrieval_job(
    request: Request,
    organization_id: UUID,
    corpus_id: UUID,
    payload: CreateRetrievalIngestionJobRequest,
) -> RetrievalIngestionJob:
    try:
        return await _create_retrieval_job(
            request,
            corpus_id,
            payload,
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/organizations/{organization_id}/retrieval/jobs", response_model=list[RetrievalIngestionJob])
async def list_organization_retrieval_jobs(
    request: Request,
    organization_id: UUID,
    corpus_id: UUID | None = Query(default=None),
    source_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[RetrievalIngestionJob]:
    try:
        return await _list_retrieval_jobs(
            request,
            scope="organization",
            organization_id=organization_id,
            corpus_id=corpus_id,
            source_id=source_id,
            status=status,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/organizations/{organization_id}/retrieval/search", response_model=RetrievalSearchResponse)
async def run_organization_retrieval_search(
    request: Request,
    organization_id: UUID,
    payload: RunRetrievalSearchRequest,
) -> RetrievalSearchResponse:
    try:
        return await _run_retrieval_search(
            request,
            payload,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/organizations/{organization_id}/retrieval/context-packs", response_model=RetrievalContextPack)
async def create_organization_retrieval_context_pack(
    request: Request,
    organization_id: UUID,
    payload: CreateRetrievalContextPackRequest,
) -> RetrievalContextPack:
    try:
        return await _create_retrieval_context_pack(
            request,
            payload,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/organizations/{organization_id}/retrieval/context-packs/{context_pack_id}", response_model=RetrievalContextPack)
async def get_organization_retrieval_context_pack(
    request: Request,
    organization_id: UUID,
    context_pack_id: UUID,
) -> RetrievalContextPack:
    try:
        return await _get_retrieval_context_pack(
            request,
            context_pack_id,
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces/{workspace_id}/retrieval/profiles", response_model=RetrievalProfile)
async def create_workspace_retrieval_profile(
    request: Request,
    workspace_id: UUID,
    payload: CreateRetrievalProfileRequest,
) -> RetrievalProfile:
    try:
        return await _create_retrieval_profile(
            request,
            payload,
            scope="workspace",
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/workspaces/{workspace_id}/retrieval/profiles", response_model=list[RetrievalProfile])
async def list_workspace_retrieval_profiles(
    request: Request,
    workspace_id: UUID,
) -> list[RetrievalProfile]:
    try:
        return await _list_retrieval_profiles(
            request,
            scope="workspace",
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces/{workspace_id}/retrieval/corpora", response_model=RetrievalCorpus)
async def create_workspace_retrieval_corpus(
    request: Request,
    workspace_id: UUID,
    payload: CreateRetrievalCorpusRequest,
) -> RetrievalCorpus:
    try:
        return await _create_retrieval_corpus(
            request,
            payload,
            scope="workspace",
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/workspaces/{workspace_id}/retrieval/corpora", response_model=list[RetrievalCorpus])
async def list_workspace_retrieval_corpora(
    request: Request,
    workspace_id: UUID,
) -> list[RetrievalCorpus]:
    try:
        return await _list_retrieval_corpora(
            request,
            scope="workspace",
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces/{workspace_id}/retrieval/sources", response_model=RetrievalSource)
async def create_workspace_retrieval_source(
    request: Request,
    workspace_id: UUID,
    payload: CreateRetrievalSourceRequest,
) -> RetrievalSource:
    try:
        return await _create_retrieval_source(
            request,
            payload,
            scope="workspace",
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/workspaces/{workspace_id}/retrieval/sources", response_model=list[RetrievalSource])
async def list_workspace_retrieval_sources(
    request: Request,
    workspace_id: UUID,
    corpus_id: UUID | None = Query(default=None),
) -> list[RetrievalSource]:
    try:
        return await _list_retrieval_sources(
            request,
            scope="workspace",
            workspace_id=workspace_id,
            corpus_id=corpus_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces/{workspace_id}/retrieval/corpora/{corpus_id}/jobs", response_model=RetrievalIngestionJob)
async def create_workspace_retrieval_job(
    request: Request,
    workspace_id: UUID,
    corpus_id: UUID,
    payload: CreateRetrievalIngestionJobRequest,
) -> RetrievalIngestionJob:
    try:
        return await _create_retrieval_job(
            request,
            corpus_id,
            payload,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/workspaces/{workspace_id}/retrieval/jobs", response_model=list[RetrievalIngestionJob])
async def list_workspace_retrieval_jobs(
    request: Request,
    workspace_id: UUID,
    corpus_id: UUID | None = Query(default=None),
    source_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[RetrievalIngestionJob]:
    try:
        return await _list_retrieval_jobs(
            request,
            scope="workspace",
            workspace_id=workspace_id,
            corpus_id=corpus_id,
            source_id=source_id,
            status=status,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces/{workspace_id}/retrieval/search", response_model=RetrievalSearchResponse)
async def run_workspace_retrieval_search(
    request: Request,
    workspace_id: UUID,
    payload: RunRetrievalSearchRequest,
) -> RetrievalSearchResponse:
    try:
        return await _run_retrieval_search(
            request,
            payload,
            scope="workspace",
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post("/workspaces/{workspace_id}/retrieval/context-packs", response_model=RetrievalContextPack)
async def create_workspace_retrieval_context_pack(
    request: Request,
    workspace_id: UUID,
    payload: CreateRetrievalContextPackRequest,
) -> RetrievalContextPack:
    try:
        return await _create_retrieval_context_pack(
            request,
            payload,
            scope="workspace",
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get("/workspaces/{workspace_id}/retrieval/context-packs/{context_pack_id}", response_model=RetrievalContextPack)
async def get_workspace_retrieval_context_pack(
    request: Request,
    workspace_id: UUID,
    context_pack_id: UUID,
) -> RetrievalContextPack:
    try:
        return await _get_retrieval_context_pack(
            request,
            context_pack_id,
            scope="workspace",
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/assets/{asset_id}/versions",
    response_model=list[WorkspaceAssetVersion],
    summary="List immutable versions for a published asset",
)
async def list_asset_versions(request: Request, asset_id: UUID) -> list[WorkspaceAssetVersion]:
    logger.debug("HTTP list_asset_versions asset_id=%s", asset_id)
    try:
        await _require_asset_workspace_membership(request, asset_id)
        return await collab_svc.collaboration_service.list_workspace_asset_versions(asset_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/assets/{asset_id}/links",
    response_model=AssetLink,
    summary="Link an asset version to an agent, tool, workspace, or workspace tool",
)
async def link_asset_version(
    request: Request,
    asset_id: UUID,
    payload: LinkAssetRequest,
) -> AssetLink:
    asset = await _require_asset_workspace_membership(request, asset_id)
    await _require_identity_permission(
        request,
        permission="asset_catalog.link",
        organization_id=asset.organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP link_asset_version asset_id=%s target_type=%s target_id=%s purpose=%s actor=%s",
        asset_id,
        payload.target_type,
        payload.target_id,
        payload.purpose,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.link_asset_version(asset_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/assets/{asset_id}/activate",
    response_model=AssetLink,
    summary="Activate an asset version for a target and purpose",
)
async def activate_asset_version(
    request: Request,
    asset_id: UUID,
    payload: ActivateAssetVersionRequest,
) -> AssetLink:
    asset = await _require_asset_workspace_membership(request, asset_id)
    await _require_identity_permission(
        request,
        permission="asset_catalog.activate",
        organization_id=asset.organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    logger.debug(
        "HTTP activate_asset_version asset_id=%s target_type=%s target_id=%s purpose=%s actor=%s",
        asset_id,
        payload.target_type,
        payload.target_id,
        payload.purpose,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.activate_asset_version(asset_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/assets/{asset_id}/download",
    response_model=str,
    summary="Generate a presigned download URL for a published asset version",
)
async def get_asset_download_url(
    request: Request,
    asset_id: UUID,
    asset_version_id: UUID | None = Query(default=None),
) -> str:
    logger.debug("HTTP get_asset_download_url asset_id=%s asset_version_id=%s", asset_id, asset_version_id)
    try:
        await _require_asset_workspace_membership(request, asset_id)
        return await collab_svc.collaboration_service.get_asset_download_url(
            asset_id,
            asset_version_id=asset_version_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/agents/{agent_id}/assets",
    response_model=list[ResolvedAssetBinding],
    summary="Resolve active global and workspace asset bindings for a system agent",
)
async def list_resolved_agent_assets(
    request: Request,
    agent_id: UUID,
    workspace_id: UUID | None = Query(default=None),
) -> list[ResolvedAssetBinding]:
    logger.debug("HTTP list_resolved_agent_assets agent_id=%s workspace_id=%s", agent_id, workspace_id)
    try:
        if workspace_id is not None:
            await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_resolved_agent_assets(
            agent_id=agent_id,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/tools/{tool_id}/assets",
    response_model=list[ResolvedAssetBinding],
    summary="Resolve active global and workspace asset bindings for a system tool",
)
async def list_resolved_tool_assets(
    request: Request,
    tool_id: UUID,
    workspace_id: UUID | None = Query(default=None),
) -> list[ResolvedAssetBinding]:
    logger.debug("HTTP list_resolved_tool_assets tool_id=%s workspace_id=%s", tool_id, workspace_id)
    try:
        if workspace_id is not None:
            await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_resolved_tool_assets(
            tool_id=tool_id,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/agents",
    response_model=ParticipantProfile,
    summary="Attach a system-level agent to a workspace",
)
async def create_agent_participant(
    request: Request,
    workspace_id: UUID,
    payload: CreateAgentParticipantRequest,
) -> ParticipantProfile:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.agents.write",
    )
    payload = payload.model_copy(
        update={
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
            )
        }
    )
    logger.debug(
        "HTTP attach_agent_to_workspace workspace_id=%s actor=%s agent_id=%s",
        workspace_id,
        _actor_log(payload.actor),
        payload.agent_id,
    )
    try:
        return await collab_svc.collaboration_service.create_agent_participant(
            workspace_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/workspaces/{workspace_id}/agents/{participant_id}",
    response_model=ParticipantProfile,
    summary="Update an existing agent participant in a workspace",
)
async def update_agent_participant(
    request: Request,
    workspace_id: UUID,
    participant_id: UUID,
    payload: UpdateAgentParticipantRequest,
) -> ParticipantProfile:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.agents.write",
    )
    payload = payload.model_copy(
        update={
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            )
        }
    )
    logger.debug(
        "HTTP update_agent_participant workspace_id=%s participant_id=%s actor=%s",
        workspace_id,
        participant_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.update_agent_participant(
            workspace_id,
            participant_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put(
    "/workspaces/{workspace_id}/roles/{role_name}",
    response_model=RoleDefinition,
    summary="Create or update a named collaboration-role definition",
)
async def upsert_role_definition(
    request: Request,
    workspace_id: UUID,
    role_name: str,
    payload: UpsertRoleDefinitionRequest,
) -> RoleDefinition:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.roles.write",
    )
    payload = payload.model_copy(
        update={
            "name": role_name,
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            ),
        }
    )
    logger.debug(
        "HTTP upsert_role_definition workspace_id=%s role_name=%r actor=%s",
        workspace_id,
        role_name,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.upsert_role_definition(
            workspace_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/workspaces/{workspace_id}/roles/{role_name}",
    response_model=dict,
    summary="Delete a collaboration-role definition",
)
async def delete_role_definition(
    request: Request,
    workspace_id: UUID,
    role_name: str,
    payload: DeleteRoleDefinitionRequest = Body(...),
) -> dict[str, bool | str]:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.roles.write",
    )
    payload = payload.model_copy(
        update={
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            ),
        }
    )
    logger.debug(
        "HTTP delete_role_definition workspace_id=%s role_name=%r actor=%s",
        workspace_id,
        role_name,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.delete_role_definition(
            workspace_id,
            role_name,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/tools",
    response_model=list[WorkspaceTool],
    summary="List tools registered for a workspace",
)
async def list_workspace_tools(
    request: Request,
    workspace_id: UUID,
) -> list[WorkspaceTool]:
    logger.debug("HTTP list_workspace_tools workspace_id=%s", workspace_id)
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_workspace_tools(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/mcp-servers",
    response_model=list[WorkspaceMcpServer],
    summary="List external MCP servers attached to a workspace",
)
async def list_workspace_mcp_servers(
    request: Request,
    workspace_id: UUID,
) -> list[WorkspaceMcpServer]:
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_workspace_mcp_servers(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/mcp-tools",
    response_model=list[WorkspaceMcpTool],
    summary="List external MCP tools available in a workspace",
)
async def list_workspace_mcp_tools(
    request: Request,
    workspace_id: UUID,
) -> list[WorkspaceMcpTool]:
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_workspace_mcp_tools(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/mcp-resources",
    response_model=list[WorkspaceMcpResource],
    summary="List external MCP resource references available in a workspace",
)
async def list_workspace_mcp_resources(
    request: Request,
    workspace_id: UUID,
) -> list[WorkspaceMcpResource]:
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_workspace_mcp_resources(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/mcp-prompts",
    response_model=list[WorkspaceMcpPrompt],
    summary="List external MCP prompt templates available in a workspace",
)
async def list_workspace_mcp_prompts(
    request: Request,
    workspace_id: UUID,
) -> list[WorkspaceMcpPrompt]:
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_workspace_mcp_prompts(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put(
    "/workspaces/{workspace_id}/mcp-servers/{server_id}",
    response_model=WorkspaceMcpServer,
    summary="Attach an external MCP server to a workspace",
)
async def attach_workspace_mcp_server(
    request: Request,
    workspace_id: UUID,
    server_id: UUID,
    payload: AttachWorkspaceMcpServerRequest,
) -> WorkspaceMcpServer:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.mcp_servers.write",
    )
    payload = payload.model_copy(
        update={
            "server_id": server_id,
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            ),
        }
    )
    try:
        return await collab_svc.collaboration_service.attach_workspace_mcp_server(
            workspace_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/workspaces/{workspace_id}/mcp-servers/{server_id}",
    response_model=WorkspaceMcpServer,
    summary="Update a workspace MCP server attachment",
)
async def update_workspace_mcp_server(
    request: Request,
    workspace_id: UUID,
    server_id: UUID,
    payload: UpdateWorkspaceMcpServerRequest,
) -> WorkspaceMcpServer:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.mcp_servers.write",
    )
    payload = payload.model_copy(
        update={
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            )
        }
    )
    try:
        return await collab_svc.collaboration_service.update_workspace_mcp_server(
            workspace_id,
            server_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/workspaces/{workspace_id}/mcp-servers/{server_id}",
    response_model=dict,
    summary="Detach an external MCP server from a workspace",
)
async def delete_workspace_mcp_server(
    request: Request,
    workspace_id: UUID,
    server_id: UUID,
    payload: DeleteWorkspaceMcpServerRequest = Body(...),
) -> dict[str, bool | str]:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.mcp_servers.write",
    )
    payload = payload.model_copy(
        update={
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            )
        }
    )
    try:
        return await collab_svc.collaboration_service.delete_workspace_mcp_server(
            workspace_id,
            server_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/git-repositories",
    response_model=GitRepository,
    summary="Register a workspace-scoped Git repository",
)
async def create_workspace_git_repository(
    request: Request,
    workspace_id: UUID,
    payload: CreateGitRepositoryRequest,
) -> GitRepository:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.repositories.write",
    )
    payload = payload.model_copy(
        update={
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            )
        }
    )
    logger.debug(
        "HTTP create_workspace_git_repository workspace_id=%s actor=%s name=%r local_path=%s",
        workspace_id,
        _actor_log(payload.actor),
        payload.name,
        payload.local_path,
    )
    try:
        return await collab_svc.collaboration_service.create_git_repository(
            scope="workspace",
            workspace_id=workspace_id,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/git-repositories",
    response_model=list[GitRepository],
    summary="List workspace-scoped Git repositories",
)
async def list_workspace_git_repositories(
    request: Request,
    workspace_id: UUID,
) -> list[GitRepository]:
    logger.debug("HTTP list_workspace_git_repositories workspace_id=%s", workspace_id)
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_git_repositories(
            scope="workspace",
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/assets/publish-from-git",
    response_model=WorkspaceAssetVersion,
    summary="Publish a workspace-scoped immutable asset version from a registered Git repository",
)
async def publish_workspace_asset_from_git(
    request: Request,
    workspace_id: UUID,
    payload: PublishAssetFromGitRequest,
) -> WorkspaceAssetVersion:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.assets.publish",
    )
    payload = payload.model_copy(
        update={
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            )
        }
    )
    logger.debug(
        "HTTP publish_workspace_asset_from_git workspace_id=%s actor=%s repository_id=%s logical_name=%r path=%s",
        workspace_id,
        _actor_log(payload.actor),
        payload.repository_id,
        payload.logical_name,
        payload.git_path,
    )
    try:
        return await collab_svc.collaboration_service.publish_asset_from_git(
            scope="workspace",
            workspace_id=workspace_id,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.put(
    "/workspaces/{workspace_id}/tools/{tool_id}",
    response_model=WorkspaceTool,
    summary="Attach a system-wide tool to a workspace",
)
async def attach_workspace_tool(
    request: Request,
    workspace_id: UUID,
    tool_id: UUID,
    payload: _AttachWorkspaceToolBody,
) -> WorkspaceTool:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.tools.write",
    )
    payload = AttachWorkspaceToolRequest(
        tool_id=tool_id,
        enabled=payload.enabled,
        metadata=payload.metadata,
        actor=actor
        or await _resolve_workspace_actor(
            request,
            payload.actor,
            workspace_id=workspace_id,
            auto_create=False,
        ),
    )
    logger.debug(
        "HTTP attach_workspace_tool workspace_id=%s tool_id=%s actor=%s enabled=%s",
        workspace_id,
        tool_id,
        _actor_log(payload.actor),
        payload.enabled,
    )
    try:
        return await collab_svc.collaboration_service.attach_workspace_tool(
            workspace_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/workspaces/{workspace_id}/tools/{tool_id}",
    response_model=WorkspaceTool,
    summary="Update a workspace tool attachment",
)
async def update_workspace_tool(
    request: Request,
    workspace_id: UUID,
    tool_id: UUID,
    payload: UpdateWorkspaceToolRequest,
) -> WorkspaceTool:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.tools.write",
    )
    payload = payload.model_copy(
        update={
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            )
        }
    )
    logger.debug(
        "HTTP update_workspace_tool workspace_id=%s tool_id=%s actor=%s",
        workspace_id,
        tool_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.update_workspace_tool(
            workspace_id,
            tool_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/workspaces/{workspace_id}/tools/{tool_id}",
    response_model=dict,
    summary="Detach a tool from a workspace",
)
async def delete_workspace_tool(
    request: Request,
    workspace_id: UUID,
    tool_id: UUID,
    payload: DeleteWorkspaceToolRequest = Body(...),
) -> dict[str, bool | str]:
    actor = await _require_workspace_permission(
        request,
        workspace_id,
        permission="workspace.tools.write",
    )
    payload = payload.model_copy(
        update={
            "actor": actor
            or await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            )
        }
    )
    logger.debug(
        "HTTP delete_workspace_tool workspace_id=%s tool_id=%s actor=%s",
        workspace_id,
        tool_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.delete_workspace_tool(
            workspace_id,
            tool_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/threads",
    response_model=ThreadDetail,
    summary="Create a thread in a workspace",
)
async def create_thread(
    request: Request, workspace_id: UUID, payload: CreateThreadRequest
) -> ThreadDetail:
    payload = payload.model_copy(
        update={
            "actor": await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
            )
        }
    )
    logger.debug(
        "HTTP create_thread workspace_id=%s actor=%s title=%r related_thread_count=%s",
        workspace_id,
        _actor_log(payload.actor),
        payload.title,
        len(payload.related_thread_ids),
    )
    try:
        return await collab_svc.collaboration_service.create_thread(workspace_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/communication-log",
    response_model=WorkspaceCommunicationLogPage,
    summary="List workspace communication log for debugging",
)
async def list_workspace_communication_log(
    request: Request,
    workspace_id: UUID,
    thread_id: UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> WorkspaceCommunicationLogPage:
    logger.debug(
        "HTTP list_workspace_communication_log workspace_id=%s thread_id=%s limit=%s offset=%s",
        workspace_id,
        thread_id,
        limit,
        offset,
    )
    try:
        await _require_workspace_permission(
            request,
            workspace_id,
            permission="workspace.audit.read",
        )
        return await collab_svc.collaboration_service.list_workspace_communication_log(
            workspace_id,
            thread_id=thread_id,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/threads",
    response_model=list[Thread],
    summary="List threads in a workspace",
)
async def list_threads(request: Request, workspace_id: UUID) -> list[Thread]:
    logger.debug("HTTP list_threads workspace_id=%s", workspace_id)
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_threads(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/threads/{thread_id}",
    response_model=ThreadDetail,
    summary="Get thread detail",
)
async def get_thread(request: Request, thread_id: UUID) -> ThreadDetail:
    logger.debug("HTTP get_thread thread_id=%s", thread_id)
    try:
        await _require_thread_membership(request, thread_id)
        return await collab_svc.collaboration_service.get_thread(thread_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/threads/{thread_id}/timeline",
    response_model=TimelinePage,
    summary="Get the thread timeline",
)
async def get_thread_timeline(request: Request, thread_id: UUID) -> TimelinePage:
    logger.debug("HTTP get_thread_timeline thread_id=%s", thread_id)
    try:
        actor = await _require_thread_membership(request, thread_id)
        return await collab_svc.collaboration_service.get_timeline(
            thread_id,
            viewer=actor,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/threads/{thread_id}/messages",
    response_model=TimelineMessage,
    summary="Post a message to a thread",
)
async def post_message(
    request: Request, thread_id: UUID, payload: CreateMessageRequest
) -> TimelineMessage:
    payload = payload.model_copy(
        update={
            "actor": await _resolve_thread_actor(
                request,
                payload.actor,
                thread_id=thread_id,
            )
        }
    )
    logger.debug(
        "HTTP post_message thread_id=%s actor=%s visibility=%s create_task=%s content_len=%s",
        thread_id,
        _actor_log(payload.actor),
        payload.visibility,
        payload.create_task,
        len(payload.content),
    )
    try:
        return await collab_svc.collaboration_service.post_message(thread_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/tool-generation/requests",
    response_model=list[ToolGenerationRequestDetail],
    summary="List tool-generation requests",
)
async def list_tool_generation_requests(
    request: Request,
    organization_id: UUID | None = Query(default=None),
    workspace_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[ToolGenerationRequestDetail]:
    derived_organization_id = organization_id
    if derived_organization_id is None and workspace_id is not None:
        workspace = await collab_svc.collaboration_service.get_workspace(workspace_id)
        derived_organization_id = workspace.workspace.organization_id
    await _require_identity_permission(
        request,
        permission="tool_generation.read",
        organization_id=derived_organization_id,
    )
    logger.debug(
        "HTTP list_tool_generation_requests organization_id=%s workspace_id=%s status=%s",
        organization_id,
        workspace_id,
        status,
    )
    try:
        return await collab_svc.collaboration_service.list_tool_generation_requests(
            organization_id=organization_id,
            workspace_id=workspace_id,
            status=status,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/threads/{thread_id}/tool-generation/requests",
    response_model=list[ToolGenerationRequestDetail],
    summary="List tool-generation requests for a thread",
)
async def list_thread_tool_generation_requests(
    request: Request,
    thread_id: UUID,
) -> list[ToolGenerationRequestDetail]:
    try:
        await _require_thread_membership(request, thread_id)
        return await collab_svc.collaboration_service.list_thread_tool_generation_requests(
            thread_id
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/tool-generation/requests/{request_id}",
    response_model=ToolGenerationRequestDetail,
    summary="Get one tool-generation request",
)
async def get_tool_generation_request(
    request: Request,
    request_id: UUID,
) -> ToolGenerationRequestDetail:
    try:
        detail = await collab_svc.collaboration_service.get_tool_generation_request(request_id)
        try:
            await _require_identity_permission(
                request,
                permission="tool_generation.read",
                organization_id=detail.request.organization_id,
            )
        except HTTPException:
            await _require_thread_membership(request, detail.request.thread_id)
        return detail
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/tool-generation/requests/{request_id}/revisions",
    response_model=ToolGenerationRequestDetail,
    summary="Create a new tool-generation revision for a request",
)
async def create_tool_generation_revision(
    request: Request,
    request_id: UUID,
    payload: CreateToolGenerationRevisionRequest,
) -> ToolGenerationRequestDetail:
    try:
        existing = await collab_svc.collaboration_service.get_tool_generation_request(request_id)
        payload = payload.model_copy(
            update={
                "actor": await _resolve_thread_actor(
                    request,
                    payload.actor,
                    thread_id=existing.request.thread_id,
                )
            }
        )
        return await collab_svc.collaboration_service.create_tool_generation_revision(
            request_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/tool-generation/revisions/{revision_id}/approve",
    response_model=ToolGenerationRequestDetail,
    summary="Approve a tool-generation revision and start worker-side registry verification",
)
async def approve_tool_generation_revision(
    request: Request,
    revision_id: UUID,
    payload: ReviewToolGenerationRevisionRequest,
) -> ToolGenerationRequestDetail:
    detail = await _tool_generation_request_for_revision(revision_id)
    await _require_identity_permission(
        request,
        permission="tool_generation.review",
        organization_id=detail.request.organization_id,
    )
    if detail.request.requested_scope == "organization":
        await _require_identity_permission(
            request,
            permission="tool_catalog.write",
            organization_id=detail.request.organization_id,
        )
    else:
        await _require_identity_permission(request, permission="tool_catalog.write")
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.approve_tool_generation_revision(
            revision_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/tool-generation/revisions/{revision_id}/reject",
    response_model=ToolGenerationRequestDetail,
    summary="Reject a tool-generation revision",
)
async def reject_tool_generation_revision(
    request: Request,
    revision_id: UUID,
    payload: ReviewToolGenerationRevisionRequest,
) -> ToolGenerationRequestDetail:
    detail = await _tool_generation_request_for_revision(revision_id)
    await _require_identity_permission(
        request,
        permission="tool_generation.review",
        organization_id=detail.request.organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_global_actor(request, payload.actor)})
    try:
        return await collab_svc.collaboration_service.reject_tool_generation_revision(
            revision_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/threads/{thread_id}/requests",
    response_model=list[InteractionRequestDetail],
    summary="List tracked interaction requests for a thread",
)
async def list_interaction_requests(
    request: Request,
    thread_id: UUID,
) -> list[InteractionRequestDetail]:
    logger.debug("HTTP list_interaction_requests thread_id=%s", thread_id)
    try:
        await _require_thread_membership(request, thread_id)
        return await collab_svc.collaboration_service.list_interaction_requests(thread_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/threads/{thread_id}/requests",
    response_model=list[InteractionRequestDetail],
    summary="Create tracked interaction requests in a thread",
)
async def create_interaction_requests(
    request: Request,
    thread_id: UUID,
    payload: CreateInteractionRequestsRequest,
) -> list[InteractionRequestDetail]:
    payload = payload.model_copy(
        update={
            "actor": await _resolve_thread_actor(
                request,
                payload.actor,
                thread_id=thread_id,
            )
        }
    )
    logger.debug(
        "HTTP create_interaction_requests thread_id=%s actor=%s request_count=%s",
        thread_id,
        _actor_log(payload.actor),
        len(payload.requests),
    )
    try:
        return await collab_svc.collaboration_service.create_interaction_requests(
            thread_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/requests/{request_id}",
    response_model=InteractionRequestDetail,
    summary="Get a tracked interaction request",
)
async def get_interaction_request(
    request: Request,
    request_id: UUID,
) -> InteractionRequestDetail:
    logger.debug("HTTP get_interaction_request request_id=%s", request_id)
    try:
        detail = await collab_svc.collaboration_service.get_interaction_request(request_id)
        await _require_thread_membership(request, detail.request.thread_id)
        return detail
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/requests/{request_id}",
    response_model=InteractionRequestDetail,
    summary="Update tracked interaction request state",
)
async def update_interaction_request(
    request: Request,
    request_id: UUID,
    payload: UpdateInteractionRequestRequest,
) -> InteractionRequestDetail:
    detail = await collab_svc.collaboration_service.get_interaction_request(request_id)
    payload = payload.model_copy(
        update={
            "actor": await _resolve_thread_actor(
                request,
                payload.actor,
                thread_id=detail.request.thread_id,
            )
        }
    )
    logger.debug(
        "HTTP update_interaction_request request_id=%s actor=%s action=%s",
        request_id,
        _actor_log(payload.actor),
        payload.action,
    )
    try:
        return await collab_svc.collaboration_service.update_interaction_request(
            request_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/requests/{request_id}/answers",
    response_model=InteractionRequestDetail,
    summary="Answer a tracked interaction request",
)
async def answer_interaction_request(
    request: Request,
    request_id: UUID,
    payload: CreateInteractionAnswerRequest,
) -> InteractionRequestDetail:
    detail = await collab_svc.collaboration_service.get_interaction_request(request_id)
    payload = payload.model_copy(
        update={
            "actor": await _resolve_thread_actor(
                request,
                payload.actor,
                thread_id=detail.request.thread_id,
            )
        }
    )
    logger.debug(
        "HTTP answer_interaction_request request_id=%s actor=%s question_count=%s",
        request_id,
        _actor_log(payload.actor),
        len(payload.question_ids),
    )
    try:
        return await collab_svc.collaboration_service.answer_interaction_request(
            request_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/memory",
    response_model=list[MemoryEntry],
    summary="List workspace memory entries",
)
async def list_workspace_memory(
    request: Request,
    workspace_id: UUID,
) -> list[MemoryEntry]:
    logger.debug("HTTP list_workspace_memory workspace_id=%s", workspace_id)
    try:
        await _require_workspace_membership(request, workspace_id)
        return await collab_svc.collaboration_service.list_memory_entries(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/memory",
    response_model=MemoryEntry,
    summary="Create a workspace memory entry",
)
async def create_workspace_memory(
    request: Request, workspace_id: UUID, payload: CreateMemoryEntryRequest
) -> MemoryEntry:
    payload = payload.model_copy(
        update={
            "actor": await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
            )
        }
    )
    logger.debug(
        "HTTP create_workspace_memory workspace_id=%s actor=%s entry_type=%s",
        workspace_id,
        _actor_log(payload.actor),
        payload.entry_type,
    )
    try:
        return await collab_svc.collaboration_service.create_memory_entry(
            workspace_id, payload
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/memory/confirm",
    response_model=MemoryEntry,
    summary="Confirm a thread or candidate memory into workspace memory",
)
async def confirm_workspace_memory(
    request: Request,
    workspace_id: UUID,
    payload: ConfirmWorkspaceMemoryRequest,
) -> MemoryEntry:
    payload = payload.model_copy(
        update={
            "actor": await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
            )
        }
    )
    logger.debug(
        "HTTP confirm_workspace_memory workspace_id=%s actor=%s source_memory_entry_id=%s",
        workspace_id,
        _actor_log(payload.actor),
        payload.source_memory_entry_id,
    )
    try:
        return await collab_svc.collaboration_service.confirm_workspace_memory(
            workspace_id, payload
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/workspaces/{workspace_id}/memory/{memory_entry_id}",
    response_model=MemoryEntry,
    summary="Update a workspace memory entry",
)
async def update_workspace_memory(
    request: Request,
    workspace_id: UUID,
    memory_entry_id: UUID,
    payload: UpdateMemoryEntryRequest,
) -> MemoryEntry:
    payload = payload.model_copy(
        update={
            "actor": await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            )
        }
    )
    logger.debug(
        "HTTP update_workspace_memory workspace_id=%s memory_entry_id=%s actor=%s",
        workspace_id,
        memory_entry_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.update_memory_entry(
            workspace_id,
            memory_entry_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/workspaces/{workspace_id}/memory/{memory_entry_id}",
    response_model=dict,
    summary="Delete a workspace memory entry",
)
async def delete_workspace_memory(
    request: Request,
    workspace_id: UUID,
    memory_entry_id: UUID,
    payload: ParticipantInput = Body(...),
):
    payload = await _resolve_workspace_actor(
        request,
        payload,
        workspace_id=workspace_id,
        auto_create=False,
    )
    logger.debug(
        "HTTP delete_workspace_memory workspace_id=%s memory_entry_id=%s actor=%s",
        workspace_id,
        memory_entry_id,
        _actor_log(payload),
    )
    try:
        return await collab_svc.collaboration_service.delete_memory_entry(
            workspace_id,
            memory_entry_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/threads/{thread_id}/memory",
    response_model=list[MemoryEntry],
    summary="List confirmed thread memory entries",
)
async def list_thread_memory(request: Request, thread_id: UUID) -> list[MemoryEntry]:
    logger.debug("HTTP list_thread_memory thread_id=%s", thread_id)
    try:
        await _require_thread_membership(request, thread_id)
        return await collab_svc.collaboration_service.list_thread_memory_entries(thread_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/threads/{thread_id}/memory",
    response_model=MemoryEntry,
    summary="Create a thread memory entry",
)
async def create_thread_memory(
    request: Request, thread_id: UUID, payload: CreateThreadMemoryRequest
) -> MemoryEntry:
    payload = payload.model_copy(
        update={
            "actor": await _resolve_thread_actor(
                request,
                payload.actor,
                thread_id=thread_id,
            )
        }
    )
    logger.debug(
        "HTTP create_thread_memory thread_id=%s actor=%s entry_type=%s",
        thread_id,
        _actor_log(payload.actor),
        payload.entry_type,
    )
    try:
        return await collab_svc.collaboration_service.create_thread_memory_entry(
            thread_id, payload
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/threads/{thread_id}/memory/search",
    response_model=MemorySearchResponse,
    summary="Semantic search across confirmed thread memory",
)
async def search_thread_memory(
    request: Request,
    thread_id: UUID,
    payload: SearchMemoryRequest,
) -> MemorySearchResponse:
    payload = payload.model_copy(
        update={
            "actor": await _resolve_thread_actor(
                request,
                payload.actor,
                thread_id=thread_id,
                auto_create=False,
            )
        }
    )
    logger.debug(
        "HTTP search_thread_memory thread_id=%s actor=%s provider=%s query=%r",
        thread_id,
        _actor_log(payload.actor),
        payload.use_provider,
        payload.query,
    )
    try:
        return await collab_svc.collaboration_service.search_thread_memory(
            thread_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/threads/{thread_id}/memory/{memory_entry_id}",
    response_model=MemoryEntry,
    summary="Update a thread memory entry",
)
async def update_thread_memory(
    request: Request,
    thread_id: UUID,
    memory_entry_id: UUID,
    payload: UpdateMemoryEntryRequest,
) -> MemoryEntry:
    payload = payload.model_copy(
        update={
            "actor": await _resolve_thread_actor(
                request,
                payload.actor,
                thread_id=thread_id,
                auto_create=False,
            )
        }
    )
    logger.debug(
        "HTTP update_thread_memory thread_id=%s memory_entry_id=%s actor=%s",
        thread_id,
        memory_entry_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.update_thread_memory_entry(
            thread_id,
            memory_entry_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/threads/{thread_id}/memory/{memory_entry_id}",
    response_model=dict,
    summary="Archive a thread memory entry",
)
async def delete_thread_memory(
    request: Request,
    thread_id: UUID,
    memory_entry_id: UUID,
    payload: ParticipantInput = Body(...),
):
    payload = await _resolve_thread_actor(
        request,
        payload,
        thread_id=thread_id,
        auto_create=False,
    )
    logger.debug(
        "HTTP delete_thread_memory thread_id=%s memory_entry_id=%s actor=%s",
        thread_id,
        memory_entry_id,
        _actor_log(payload),
    )
    try:
        return await collab_svc.collaboration_service.delete_thread_memory_entry(
            thread_id,
            memory_entry_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/audit/events",
    response_model=AuditEventPage,
    summary="List audit events",
)
async def list_audit_events(
    request: Request,
    organization_id: UUID | None = Query(default=None),
    workspace_id: UUID | None = Query(default=None),
    thread_id: UUID | None = Query(default=None),
    actor_user_id: UUID | None = Query(default=None),
    actor_system_agent_id: UUID | None = Query(default=None),
    action_prefix: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    target_id: UUID | None = Query(default=None),
    correlation_id: UUID | None = Query(default=None),
    request_id: UUID | None = Query(default=None),
    occurred_after: datetime | None = Query(default=None),
    occurred_before: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
):
    try:
        if workspace_id is not None:
            await _require_workspace_audit_access(request, workspace_id)
        elif organization_id is not None:
            await _require_identity_permission(
                request,
                permission="audit.read",
                organization_id=organization_id,
            )
        else:
            await _require_identity_permission(request, permission="audit.read")
        return await audit_service.list_audit_events(
            AuditExportRequest(
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
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/audit/events",
    response_model=AuditEventPage,
    summary="List organization audit events",
)
async def list_organization_audit_events(
    request: Request,
    organization_id: UUID,
    thread_id: UUID | None = Query(default=None),
    actor_user_id: UUID | None = Query(default=None),
    actor_system_agent_id: UUID | None = Query(default=None),
    action_prefix: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    target_id: UUID | None = Query(default=None),
    correlation_id: UUID | None = Query(default=None),
    request_id: UUID | None = Query(default=None),
    occurred_after: datetime | None = Query(default=None),
    occurred_before: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> AuditEventPage:
    await _require_identity_permission(
        request,
        permission="audit.read",
        organization_id=organization_id,
    )
    try:
        return await audit_service.list_audit_events(
            AuditExportRequest(
                organization_id=organization_id,
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
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/audit/events/{audit_event_id}",
    response_model=AuditEvent,
    summary="Fetch a single audit event",
)
async def get_audit_event(request: Request, audit_event_id: UUID):
    try:
        event = await audit_service.get_audit_event(audit_event_id)
        if event is None:
            raise KeyError(f"Audit event {audit_event_id} not found")
        if event.workspace_id is not None:
            await _require_workspace_audit_access(request, event.workspace_id)
        elif event.organization_id is not None:
            await _require_identity_permission(
                request,
                permission="audit.read",
                organization_id=event.organization_id,
            )
        else:
            await _require_identity_permission(request, permission="audit.read")
        return event
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/audit/chains/{chain_partition}/verify",
    response_model=AuditChainVerificationResult,
    summary="Verify an audit chain partition",
)
async def verify_audit_chain(request: Request, chain_partition: str):
    try:
        if chain_partition.startswith("workspace:"):
            await _require_workspace_permission(
                request,
                UUID(chain_partition.split(":", 1)[1]),
                permission="workspace.audit.verify",
            )
        elif chain_partition.startswith("organization:"):
            await _require_identity_permission(
                request,
                permission="audit.verify",
                organization_id=UUID(chain_partition.split(":", 1)[1]),
            )
        else:
            await _require_identity_permission(request, permission="audit.verify")
        return await audit_service.verify_audit_chain(chain_partition)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/audit/events/export",
    response_model=AuditExportResult,
    summary="Export audit events to object storage",
)
async def export_audit_events(request: Request, payload: AuditExportRequest = Body(...)):
    try:
        if payload.workspace_id is not None:
            await _require_workspace_permission(
                request,
                payload.workspace_id,
                permission="workspace.audit.export",
            )
        elif payload.organization_id is not None:
            await _require_identity_permission(
                request,
                permission="audit.export",
                organization_id=payload.organization_id,
            )
        else:
            await _require_identity_permission(request, permission="audit.export")
        return await audit_service.export_audit_events(payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/audit/events/export",
    response_model=AuditExportResult,
    summary="Export organization audit events to object storage",
)
async def export_organization_audit_events(
    request: Request,
    organization_id: UUID,
    payload: AuditExportRequest = Body(...),
) -> AuditExportResult:
    await _require_identity_permission(
        request,
        permission="audit.export",
        organization_id=organization_id,
    )
    try:
        return await audit_service.export_audit_events(
            payload.model_copy(update={"organization_id": organization_id, "workspace_id": None})
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/threads/{thread_id}/events/stream",
    summary="Stream thread events via Server-Sent Events",
    response_class=EventSourceResponse,  # type: ignore[arg-type]
)
async def stream_thread_events(
    thread_id: UUID,
    after_sequence: int | None = Query(default=None),
    follow: bool = Query(default=True),
):
    logger.debug(
        "HTTP stream_thread_events thread_id=%s after_sequence=%s follow=%s",
        thread_id,
        after_sequence,
        follow,
    )
    try:
        async def generator():
            async for event in collab_svc.collaboration_service.stream_thread_events(
                thread_id,
                after_sequence=after_sequence,
                follow=follow,
            ):
                yield event.model_dump_json()

        return EventSourceResponse(generator())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.websocket("/threads/{thread_id}/ws")
async def stream_thread_events_ws(
    websocket: WebSocket,
    thread_id: UUID,
    participant_id: UUID | None = None,
    display_name: str | None = None,
    participant_type: str = "user",
    after_sequence: int | None = None,
):
    logger.debug(
        "WS connect requested thread_id=%s participant_id=%s participant_type=%s after_sequence=%s",
        thread_id,
        participant_id,
        participant_type,
        after_sequence,
    )
    request_id = uuid4()
    auth_context = await _ws_authorize(websocket)
    if settings.auth_mode != "none" and auth_context is None:
        await audit_service.record_websocket_audit(
            thread_id=thread_id,
            workspace_id=None,
            action_name="auth.login_failed",
            outcome="denied",
            actor_type="unknown",
            request_id=request_id,
            metadata={"close_code": 4001},
            error_message="Unauthorized websocket connection",
        )
        await websocket.close(code=4001, reason="Unauthorized")
        return

    if auth_context is not None and auth_context.kind == "oidc":
        participant = await collab_svc.collaboration_service.resolve_authenticated_thread_actor(
            thread_id=thread_id,
            auth_context=auth_context,
        )
        participant_id = participant.participant_id
    else:
        if participant_id is None or display_name is None:
            await audit_service.record_websocket_audit(
                thread_id=thread_id,
                workspace_id=None,
                action_name="api.websocket.failed",
                outcome="failure",
                actor_type="unknown",
                request_id=request_id,
                metadata={"close_code": 4002},
                error_message="Missing websocket participant identity",
            )
            await websocket.close(code=4002, reason="Missing participant identity")
            return
        participant = _participant_from_ws(
            participant_id=participant_id,
            participant_type=participant_type,
            display_name=display_name,
        )
    workspace_id = None
    try:
        thread_detail = await collab_svc.collaboration_service.get_thread(thread_id)
        workspace_id = thread_detail.thread.workspace_id
    except Exception:
        logger.exception("Failed to resolve websocket thread scope thread_id=%s", thread_id)
    connection_id = str(uuid4())
    await websocket.accept()
    await audit_service.record_websocket_audit(
        thread_id=thread_id,
        workspace_id=workspace_id,
        action_name="api.websocket.connected",
        outcome="success",
        actor_type="user" if auth_context is not None and auth_context.kind == "oidc" else participant.participant_type,
        actor_id=participant.participant_id,
        user_id=participant.user_id,
        request_id=request_id,
        metadata={"connection_id": connection_id},
    )

    try:
        await collab_svc.collaboration_service.on_thread_connected(
            thread_id=thread_id,
            actor=participant,
            connection_id=connection_id,
        )
        async for event in collab_svc.collaboration_service.stream_thread_events(
            thread_id,
            after_sequence=after_sequence,
            follow=True,
            viewer=participant,
        ):
            logger.debug(
                "WS send event thread_id=%s participant_id=%s event_type=%s sequence=%s",
                thread_id,
                participant_id,
                event.event_type,
                event.sequence,
            )
            await collab_svc.collaboration_service.touch_presence(
                thread_id=thread_id,
                actor=participant,
                connection_id=connection_id,
            )
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        logger.debug(
            "WS disconnected thread_id=%s participant_id=%s connection_id=%s",
            thread_id,
            participant_id,
            connection_id,
        )
        await audit_service.record_websocket_audit(
            thread_id=thread_id,
            workspace_id=workspace_id,
            action_name="api.websocket.disconnected",
            outcome="success",
            actor_type=participant.participant_type,
            actor_id=participant.participant_id,
            user_id=participant.user_id,
            request_id=request_id,
            metadata={"connection_id": connection_id},
        )
    finally:
        try:
            await collab_svc.collaboration_service.on_thread_disconnected(
                thread_id=thread_id,
                actor=participant,
                connection_id=connection_id,
            )
        except Exception:
            logger.exception(
                "WS disconnect cleanup failed thread_id=%s participant_id=%s connection_id=%s",
                thread_id,
                participant_id,
                connection_id,
            )
            pass
