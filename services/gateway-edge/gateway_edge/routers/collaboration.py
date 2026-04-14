from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

from gateway_edge.auth.api_key import validate_api_key
from gateway_edge.auth.identity import sync_oidc_auth_context
from gateway_edge.auth.oidc import validate_oidc_token
from gateway_edge.auth.openbao import validate_openbao_token
from gateway_edge.authz import require_admin_access
from gateway_edge.config import settings
from gateway_edge.models import (
    ActivateAssetVersionRequest,
    AuthContext,
    AssumeParticipantRoleRequest,
    AgentDefinition,
    AttachWorkspaceToolRequest,
    AssetLink,
    CreateGitRepositoryRequest,
    CreateAgentParticipantRequest,
    CreateLlmProviderRequest,
    CreateMemoryProviderRequest,
    CreateSystemAgentRequest,
    CreateSystemToolRequest,
    ConfirmWorkspaceMemoryRequest,
    CreateMemoryEntryRequest,
    CreateThreadMemoryRequest,
    CreateMessageRequest,
    SearchMemoryRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteLlmProviderRequest,
    DeleteMemoryProviderRequest,
    DeleteParticipantRequest,
    DeleteWorkspaceToolRequest,
    DeleteWorkspaceRequest,
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderHealthReport,
    MemorySearchResponse,
    LlmEngineDescriptor,
    LlmProviderDefinition,
    LlmProviderHealthReport,
    GitRepository,
    LinkAssetRequest,
    ParticipantInput,
    ParticipantProfile,
    PublishAssetFromGitRequest,
    ResolvedAssetBinding,
    RoleDefinition,
    SystemToolDefinition,
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
from gateway_edge.services import collaboration as collab_svc
from gateway_edge.services.llm_provider_health import check_llm_provider_health
from gateway_edge.services.memory_provider_health import check_memory_provider_health
from gateway_edge.services.llm_registry import list_registered_llm_engines

router = APIRouter(prefix="/v1", tags=["collaboration"])
logger = logging.getLogger(__name__)


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


def _user_auth_context(request: Request) -> AuthContext | None:
    auth_context = _request_auth_context(request)
    if auth_context is None or auth_context.kind != "oidc":
        return None
    return auth_context


def _resolved_create_workspace_actor(
    request: Request,
    actor: ParticipantInput,
) -> ParticipantInput:
    auth_context = _user_auth_context(request)
    if auth_context is None or auth_context.user_id is None or not auth_context.display_name:
        return actor
    return actor.model_copy(
        update={
            "participant_id": uuid4(),
            "participant_type": "user",
            "user_id": auth_context.user_id,
            "display_name": auth_context.display_name,
        }
    )


def _resolve_global_actor(
    request: Request,
    actor: ParticipantInput,
) -> ParticipantInput:
    auth_context = _user_auth_context(request)
    if auth_context is None or auth_context.user_id is None or not auth_context.display_name:
        return actor
    return actor.model_copy(
        update={
            "participant_id": auth_context.user_id,
            "participant_type": "user",
            "user_id": auth_context.user_id,
            "display_name": auth_context.display_name,
        }
    )


async def _resolve_workspace_actor(
    request: Request,
    actor: ParticipantInput,
    *,
    workspace_id: UUID,
    auto_create: bool = True,
) -> ParticipantInput:
    auth_context = _user_auth_context(request)
    if auth_context is None:
        return actor
    return await collab_svc.collaboration_service.resolve_authenticated_user_actor(
        workspace_id=workspace_id,
        auth_context=auth_context,
        auto_create=auto_create,
    )


async def _resolve_thread_actor(
    request: Request,
    actor: ParticipantInput,
    *,
    thread_id: UUID,
    auto_create: bool = True,
) -> ParticipantInput:
    auth_context = _user_auth_context(request)
    if auth_context is None:
        return actor
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
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/workspaces", response_model=WorkspaceDetail, summary="Create a workspace")
async def create_workspace(request: Request, payload: CreateWorkspaceRequest) -> WorkspaceDetail:
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
        return await collab_svc.collaboration_service.create_workspace(payload)
    except Exception as exc:  # pragma: no cover - exercised by tests via error type mapping
        raise _http_error(exc) from exc


@router.get("/workspaces", response_model=list[Workspace], summary="List workspaces")
async def list_workspaces() -> list[Workspace]:
    logger.debug("HTTP list_workspaces")
    return await collab_svc.collaboration_service.list_workspaces()


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
        "HTTP delete_workspace workspace_id=%s actor=%s",
        workspace_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.delete_workspace(workspace_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceDetail,
    summary="Get workspace detail",
)
async def get_workspace(workspace_id: UUID) -> WorkspaceDetail:
    logger.debug("HTTP get_workspace workspace_id=%s", workspace_id)
    try:
        return await collab_svc.collaboration_service.get_workspace(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/participants",
    response_model=list[ParticipantProfile],
    summary="List participant advertisements in a workspace",
)
async def list_workspace_participants(workspace_id: UUID) -> list[ParticipantProfile]:
    logger.debug("HTTP list_workspace_participants workspace_id=%s", workspace_id)
    try:
        return await collab_svc.collaboration_service.list_workspace_participants(
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
    summary="Assume a participant role in a workspace",
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
    require_admin_access(request)
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
    "/llm-providers/validate",
    response_model=LlmProviderHealthReport,
    summary="Validate an LLM provider definition without persisting it",
)
async def validate_llm_provider(
    request: Request,
    payload: CreateLlmProviderRequest,
) -> LlmProviderHealthReport:
    require_admin_access(request)
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
    require_admin_access(request)
    logger.debug("HTTP list_llm_providers")
    try:
        return await collab_svc.collaboration_service.list_llm_providers()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/llm-providers/{provider_id}",
    response_model=LlmProviderDefinition,
    summary="Update a system-level LLM provider definition",
)
async def update_llm_provider(
    request: Request,
    provider_id: UUID,
    payload: UpdateLlmProviderRequest,
) -> LlmProviderDefinition:
    require_admin_access(request)
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


@router.delete(
    "/llm-providers/{provider_id}",
    response_model=dict,
    summary="Delete a system-level LLM provider definition",
)
async def delete_llm_provider(
    request: Request,
    provider_id: UUID,
    payload: DeleteLlmProviderRequest = Body(...),
) -> dict[str, bool | str]:
    require_admin_access(request)
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


@router.post(
    "/llm-providers/{provider_id}/health-check",
    response_model=LlmProviderHealthReport,
    summary="Validate a stored LLM provider configuration",
)
async def health_check_llm_provider(
    request: Request,
    provider_id: UUID,
) -> LlmProviderHealthReport:
    require_admin_access(request)
    logger.debug("HTTP health_check_llm_provider provider_id=%s", provider_id)
    try:
        provider = await collab_svc.collaboration_service.get_llm_provider(provider_id)
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
    require_admin_access(request)
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
    "/memory-providers/validate",
    response_model=MemoryProviderHealthReport,
    summary="Validate a memory provider definition without persisting it",
)
async def validate_memory_provider(
    request: Request,
    payload: CreateMemoryProviderRequest,
) -> MemoryProviderHealthReport:
    require_admin_access(request)
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
    require_admin_access(request)
    logger.debug("HTTP list_memory_providers")
    try:
        return await collab_svc.collaboration_service.list_memory_providers()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/memory-providers/{provider_id}",
    response_model=MemoryProviderDefinition,
    summary="Update a system-level memory provider definition",
)
async def update_memory_provider(
    request: Request,
    provider_id: UUID,
    payload: UpdateMemoryProviderRequest,
) -> MemoryProviderDefinition:
    require_admin_access(request)
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


@router.delete(
    "/memory-providers/{provider_id}",
    response_model=dict,
    summary="Delete a system-level memory provider definition",
)
async def delete_memory_provider(
    request: Request,
    provider_id: UUID,
    payload: DeleteMemoryProviderRequest = Body(...),
) -> dict[str, bool | str]:
    require_admin_access(request)
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


@router.post(
    "/memory-providers/{provider_id}/health-check",
    response_model=MemoryProviderHealthReport,
    summary="Validate a stored memory provider configuration",
)
async def health_check_memory_provider(
    request: Request,
    provider_id: UUID,
) -> MemoryProviderHealthReport:
    require_admin_access(request)
    logger.debug("HTTP health_check_memory_provider provider_id=%s", provider_id)
    try:
        provider = await collab_svc.collaboration_service.get_memory_provider(provider_id)
        return await check_memory_provider_health(provider)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/agents",
    response_model=list[AgentDefinition],
    summary="List system-level agent definitions",
)
async def list_system_agents() -> list[AgentDefinition]:
    logger.debug("HTTP list_system_agents")
    try:
        return await collab_svc.collaboration_service.list_system_agents()
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


@router.get(
    "/tools",
    response_model=list[SystemToolDefinition],
    summary="List system-wide tool definitions",
)
async def list_system_tools() -> list[SystemToolDefinition]:
    logger.debug("HTTP list_system_tools")
    try:
        return await collab_svc.collaboration_service.list_system_tools()
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/tools/{tool_id}",
    response_model=SystemToolDefinition,
    summary="Update a system-wide tool definition",
)
async def update_system_tool(
    request: Request,
    tool_id: UUID,
    payload: UpdateSystemToolRequest,
) -> SystemToolDefinition:
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
    "/agents/{agent_id}",
    response_model=AgentDefinition,
    summary="Update a system-level agent definition",
)
async def update_system_agent(
    request: Request,
    agent_id: UUID,
    payload: UpdateSystemAgentRequest,
) -> AgentDefinition:
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


@router.post(
    "/git-repositories",
    response_model=GitRepository,
    summary="Register a global Git repository for authored definitions or code",
)
async def create_global_git_repository(
    request: Request,
    payload: CreateGitRepositoryRequest,
) -> GitRepository:
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
async def list_global_git_repositories() -> list[GitRepository]:
    logger.debug("HTTP list_global_git_repositories")
    try:
        return await collab_svc.collaboration_service.list_git_repositories(scope="global")
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
            workspace_id=None,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/assets",
    response_model=list[WorkspaceAsset],
    summary="List published assets with optional workspace scoping",
)
async def list_assets(
    workspace_id: UUID | None = Query(default=None),
    scope: str | None = Query(default=None),
) -> list[WorkspaceAsset]:
    logger.debug("HTTP list_assets workspace_id=%s scope=%s", workspace_id, scope)
    try:
        return await collab_svc.collaboration_service.list_workspace_assets(
            scope=scope,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/assets/{asset_id}/versions",
    response_model=list[WorkspaceAssetVersion],
    summary="List immutable versions for a published asset",
)
async def list_asset_versions(asset_id: UUID) -> list[WorkspaceAssetVersion]:
    logger.debug("HTTP list_asset_versions asset_id=%s", asset_id)
    try:
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
    asset_id: UUID,
    asset_version_id: UUID | None = Query(default=None),
) -> str:
    logger.debug("HTTP get_asset_download_url asset_id=%s asset_version_id=%s", asset_id, asset_version_id)
    try:
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
    agent_id: UUID,
    workspace_id: UUID | None = Query(default=None),
) -> list[ResolvedAssetBinding]:
    logger.debug("HTTP list_resolved_agent_assets agent_id=%s workspace_id=%s", agent_id, workspace_id)
    try:
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
    tool_id: UUID,
    workspace_id: UUID | None = Query(default=None),
) -> list[ResolvedAssetBinding]:
    logger.debug("HTTP list_resolved_tool_assets tool_id=%s workspace_id=%s", tool_id, workspace_id)
    try:
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
    summary="Create or update a named workspace role definition",
)
async def upsert_role_definition(
    request: Request,
    workspace_id: UUID,
    role_name: str,
    payload: UpsertRoleDefinitionRequest,
) -> RoleDefinition:
    payload = payload.model_copy(
        update={
            "name": role_name,
            "actor": await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
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


@router.get(
    "/workspaces/{workspace_id}/tools",
    response_model=list[WorkspaceTool],
    summary="List tools registered for a workspace",
)
async def list_workspace_tools(workspace_id: UUID) -> list[WorkspaceTool]:
    logger.debug("HTTP list_workspace_tools workspace_id=%s", workspace_id)
    try:
        return await collab_svc.collaboration_service.list_workspace_tools(workspace_id)
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
async def list_workspace_git_repositories(workspace_id: UUID) -> list[GitRepository]:
    logger.debug("HTTP list_workspace_git_repositories workspace_id=%s", workspace_id)
    try:
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
    payload: AttachWorkspaceToolRequest,
) -> WorkspaceTool:
    payload = payload.model_copy(
        update={
            "tool_id": tool_id,
            "actor": await _resolve_workspace_actor(
                request,
                payload.actor,
                workspace_id=workspace_id,
                auto_create=False,
            ),
        }
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
    "/workspaces/{workspace_id}/threads",
    response_model=list[Thread],
    summary="List threads in a workspace",
)
async def list_threads(workspace_id: UUID) -> list[Thread]:
    logger.debug("HTTP list_threads workspace_id=%s", workspace_id)
    try:
        return await collab_svc.collaboration_service.list_threads(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/threads/{thread_id}",
    response_model=ThreadDetail,
    summary="Get thread detail",
)
async def get_thread(thread_id: UUID) -> ThreadDetail:
    logger.debug("HTTP get_thread thread_id=%s", thread_id)
    try:
        return await collab_svc.collaboration_service.get_thread(thread_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/threads/{thread_id}/timeline",
    response_model=TimelinePage,
    summary="Get the thread timeline",
)
async def get_thread_timeline(thread_id: UUID) -> TimelinePage:
    logger.debug("HTTP get_thread_timeline thread_id=%s", thread_id)
    try:
        return await collab_svc.collaboration_service.get_timeline(thread_id)
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
    "/workspaces/{workspace_id}/memory",
    response_model=list[MemoryEntry],
    summary="List workspace memory entries",
)
async def list_workspace_memory(workspace_id: UUID) -> list[MemoryEntry]:
    logger.debug("HTTP list_workspace_memory workspace_id=%s", workspace_id)
    try:
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
async def list_thread_memory(thread_id: UUID) -> list[MemoryEntry]:
    logger.debug("HTTP list_thread_memory thread_id=%s", thread_id)
    try:
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
    auth_context = await _ws_authorize(websocket)
    if settings.auth_mode != "none" and auth_context is None:
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
            await websocket.close(code=4002, reason="Missing participant identity")
            return
        participant = _participant_from_ws(
            participant_id=participant_id,
            participant_type=participant_type,
            display_name=display_name,
        )
    connection_id = str(uuid4())
    await websocket.accept()

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
        pass
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
