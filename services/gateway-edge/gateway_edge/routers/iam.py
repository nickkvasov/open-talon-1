from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Request

from gateway_edge.iam.authorization import authorization_engine
from gateway_edge.models import (
    AgentIdentity,
    AgentIdentityProvisioningResult,
    AuthContext,
    BindAgentRoleRequest,
    BindHumanRoleRequest,
    CreateAgentIdentityRequest,
    CreateIamRoleRequest,
    IamPermission,
    IamRoleDefinition,
    ParticipantInput,
    RotateAgentIdentitySecretRequest,
    UpdateAgentIdentityStatusRequest,
    UpdateIamRoleRequest,
)
from gateway_edge.services.iam import iam_service

router = APIRouter(prefix="/v1", tags=["iam"])
logger = logging.getLogger(__name__)


def _http_error(exc: Exception) -> HTTPException:
    logger.exception("IAM request failed: %s", exc)
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _request_auth_context(request: Request) -> AuthContext | None:
    auth_context = getattr(request.state, "auth_context", None)
    return auth_context if isinstance(auth_context, AuthContext) else None


def _resolve_actor(request: Request, actor: ParticipantInput) -> ParticipantInput:
    auth_context = _request_auth_context(request)
    if auth_context is None or auth_context.kind != "oidc":
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
        "iam.route",
        {
            "auth_context": _request_auth_context(request),
            "permission_type": "identity",
            "permission": permission,
            "organization_id": organization_id,
        },
    )


@router.get(
    "/iam/permissions",
    response_model=list[IamPermission],
    summary="List the platform IAM permission catalog",
)
async def list_permissions() -> list[IamPermission]:
    return await iam_service.list_permissions()


@router.get(
    "/iam/human-roles",
    response_model=list[IamRoleDefinition],
    summary="List global human IAM roles",
)
async def list_global_human_roles(request: Request) -> list[IamRoleDefinition]:
    await _require_identity_permission(request, permission="organization.members.read")
    try:
        return await iam_service.list_iam_role_definitions(
            subject_kind="human",
            scope="global",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/iam/human-roles",
    response_model=IamRoleDefinition,
    summary="Create a global human IAM role",
)
async def create_global_human_role(
    request: Request,
    payload: CreateIamRoleRequest,
) -> IamRoleDefinition:
    await _require_identity_permission(request, permission="organization.members.write")
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        return await iam_service.create_iam_role_definition(
            payload,
            subject_kind="human",
            scope="global",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/iam/human-roles/{role_id}",
    response_model=IamRoleDefinition,
    summary="Update a global human IAM role",
)
async def update_global_human_role(
    request: Request,
    role_id: UUID,
    payload: UpdateIamRoleRequest,
) -> IamRoleDefinition:
    await _require_identity_permission(request, permission="organization.members.write")
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        role = await iam_service.get_iam_role_definition(role_id)
        if role is None or role.subject_kind != "human" or role.scope != "global":
            raise KeyError(f"Human IAM role {role_id} not found")
        return await iam_service.update_iam_role_definition(role_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/iam/human-roles/{role_id}",
    response_model=dict,
    summary="Delete a global human IAM role",
)
async def delete_global_human_role(
    request: Request,
    role_id: UUID,
) -> dict[str, bool | str]:
    await _require_identity_permission(request, permission="organization.members.write")
    try:
        role = await iam_service.get_iam_role_definition(role_id)
        if role is None or role.subject_kind != "human" or role.scope != "global":
            raise KeyError(f"Human IAM role {role_id} not found")
        return await iam_service.delete_iam_role_definition(role_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/iam/human-roles",
    response_model=list[IamRoleDefinition],
    summary="List organization-scoped human IAM roles",
)
async def list_organization_human_roles(
    request: Request,
    organization_id: UUID,
) -> list[IamRoleDefinition]:
    await _require_identity_permission(
        request,
        permission="organization.members.read",
        organization_id=organization_id,
    )
    try:
        return await iam_service.list_iam_role_definitions(
            subject_kind="human",
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/iam/human-roles",
    response_model=IamRoleDefinition,
    summary="Create an organization-scoped human IAM role",
)
async def create_organization_human_role(
    request: Request,
    organization_id: UUID,
    payload: CreateIamRoleRequest,
) -> IamRoleDefinition:
    await _require_identity_permission(
        request,
        permission="organization.members.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        return await iam_service.create_iam_role_definition(
            payload,
            subject_kind="human",
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/organizations/{organization_id}/iam/human-roles/{role_id}",
    response_model=IamRoleDefinition,
    summary="Update an organization-scoped human IAM role",
)
async def update_organization_human_role(
    request: Request,
    organization_id: UUID,
    role_id: UUID,
    payload: UpdateIamRoleRequest,
) -> IamRoleDefinition:
    await _require_identity_permission(
        request,
        permission="organization.members.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        role = await iam_service.get_iam_role_definition(role_id)
        if (
            role is None
            or role.subject_kind != "human"
            or role.scope != "organization"
            or role.organization_id != organization_id
        ):
            raise KeyError(f"Human IAM role {role_id} not found")
        return await iam_service.update_iam_role_definition(role_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/organizations/{organization_id}/iam/human-roles/{role_id}",
    response_model=dict,
    summary="Delete an organization-scoped human IAM role",
)
async def delete_organization_human_role(
    request: Request,
    organization_id: UUID,
    role_id: UUID,
) -> dict[str, bool | str]:
    await _require_identity_permission(
        request,
        permission="organization.members.write",
        organization_id=organization_id,
    )
    try:
        role = await iam_service.get_iam_role_definition(role_id)
        if (
            role is None
            or role.subject_kind != "human"
            or role.scope != "organization"
            or role.organization_id != organization_id
        ):
            raise KeyError(f"Human IAM role {role_id} not found")
        return await iam_service.delete_iam_role_definition(role_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/iam/agent-roles",
    response_model=list[IamRoleDefinition],
    summary="List global agent IAM roles",
)
async def list_global_agent_roles(request: Request) -> list[IamRoleDefinition]:
    await _require_identity_permission(request, permission="organization.members.read")
    try:
        return await iam_service.list_iam_role_definitions(
            subject_kind="agent",
            scope="global",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/iam/agent-roles",
    response_model=IamRoleDefinition,
    summary="Create a global agent IAM role",
)
async def create_global_agent_role(
    request: Request,
    payload: CreateIamRoleRequest,
) -> IamRoleDefinition:
    await _require_identity_permission(request, permission="organization.members.write")
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        return await iam_service.create_iam_role_definition(
            payload,
            subject_kind="agent",
            scope="global",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/iam/agent-roles/{role_id}",
    response_model=IamRoleDefinition,
    summary="Update a global agent IAM role",
)
async def update_global_agent_role(
    request: Request,
    role_id: UUID,
    payload: UpdateIamRoleRequest,
) -> IamRoleDefinition:
    await _require_identity_permission(request, permission="organization.members.write")
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        role = await iam_service.get_iam_role_definition(role_id)
        if role is None or role.subject_kind != "agent" or role.scope != "global":
            raise KeyError(f"Agent IAM role {role_id} not found")
        return await iam_service.update_iam_role_definition(role_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/iam/agent-roles/{role_id}",
    response_model=dict,
    summary="Delete a global agent IAM role",
)
async def delete_global_agent_role(
    request: Request,
    role_id: UUID,
) -> dict[str, bool | str]:
    await _require_identity_permission(request, permission="organization.members.write")
    try:
        role = await iam_service.get_iam_role_definition(role_id)
        if role is None or role.subject_kind != "agent" or role.scope != "global":
            raise KeyError(f"Agent IAM role {role_id} not found")
        return await iam_service.delete_iam_role_definition(role_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/iam/agent-roles",
    response_model=list[IamRoleDefinition],
    summary="List organization-scoped agent IAM roles",
)
async def list_organization_agent_roles(
    request: Request,
    organization_id: UUID,
) -> list[IamRoleDefinition]:
    await _require_identity_permission(
        request,
        permission="organization.members.read",
        organization_id=organization_id,
    )
    try:
        return await iam_service.list_iam_role_definitions(
            subject_kind="agent",
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/iam/agent-roles",
    response_model=IamRoleDefinition,
    summary="Create an organization-scoped agent IAM role",
)
async def create_organization_agent_role(
    request: Request,
    organization_id: UUID,
    payload: CreateIamRoleRequest,
) -> IamRoleDefinition:
    await _require_identity_permission(
        request,
        permission="organization.members.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        return await iam_service.create_iam_role_definition(
            payload,
            subject_kind="agent",
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/organizations/{organization_id}/iam/agent-roles/{role_id}",
    response_model=IamRoleDefinition,
    summary="Update an organization-scoped agent IAM role",
)
async def update_organization_agent_role(
    request: Request,
    organization_id: UUID,
    role_id: UUID,
    payload: UpdateIamRoleRequest,
) -> IamRoleDefinition:
    await _require_identity_permission(
        request,
        permission="organization.members.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        role = await iam_service.get_iam_role_definition(role_id)
        if (
            role is None
            or role.subject_kind != "agent"
            or role.scope != "organization"
            or role.organization_id != organization_id
        ):
            raise KeyError(f"Agent IAM role {role_id} not found")
        return await iam_service.update_iam_role_definition(role_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/organizations/{organization_id}/iam/agent-roles/{role_id}",
    response_model=dict,
    summary="Delete an organization-scoped agent IAM role",
)
async def delete_organization_agent_role(
    request: Request,
    organization_id: UUID,
    role_id: UUID,
) -> dict[str, bool | str]:
    await _require_identity_permission(
        request,
        permission="organization.members.write",
        organization_id=organization_id,
    )
    try:
        role = await iam_service.get_iam_role_definition(role_id)
        if (
            role is None
            or role.subject_kind != "agent"
            or role.scope != "organization"
            or role.organization_id != organization_id
        ):
            raise KeyError(f"Agent IAM role {role_id} not found")
        return await iam_service.delete_iam_role_definition(role_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/iam/users/{user_id}/roles",
    response_model=list[IamRoleDefinition],
    summary="List global human IAM roles bound to a user",
)
async def list_global_user_roles(
    request: Request,
    user_id: UUID,
) -> list[IamRoleDefinition]:
    await _require_identity_permission(request, permission="organization.members.read")
    try:
        return await iam_service.list_human_roles_for_user(user_id=user_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/iam/users/{user_id}/roles",
    response_model=list[IamRoleDefinition],
    summary="List organization human IAM roles bound to a user",
)
async def list_organization_user_roles(
    request: Request,
    organization_id: UUID,
    user_id: UUID,
) -> list[IamRoleDefinition]:
    await _require_identity_permission(
        request,
        permission="organization.members.read",
        organization_id=organization_id,
    )
    try:
        return await iam_service.list_human_roles_for_user(
            user_id=user_id,
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/iam/users/{user_id}/roles/{role_id}",
    response_model=dict,
    summary="Bind a global human IAM role to a user",
)
async def bind_global_human_role(
    request: Request,
    user_id: UUID,
    role_id: UUID,
    payload: BindHumanRoleRequest,
) -> dict[str, str]:
    await _require_identity_permission(request, permission="organization.members.write")
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        return await iam_service.bind_human_role(user_id, role_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/iam/users/{user_id}/roles/{role_id}",
    response_model=dict,
    summary="Unbind a global human IAM role from a user",
)
async def unbind_global_human_role(
    request: Request,
    user_id: UUID,
    role_id: UUID,
) -> dict[str, bool | str]:
    await _require_identity_permission(request, permission="organization.members.write")
    try:
        return await iam_service.unbind_human_role(user_id, role_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/iam/users/{user_id}/roles/{role_id}",
    response_model=dict,
    summary="Bind an organization human IAM role to a user",
)
async def bind_organization_human_role(
    request: Request,
    organization_id: UUID,
    user_id: UUID,
    role_id: UUID,
    payload: BindHumanRoleRequest,
) -> dict[str, str]:
    await _require_identity_permission(
        request,
        permission="organization.members.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        role = await iam_service.get_iam_role_definition(role_id)
        if role is None or role.organization_id != organization_id or role.subject_kind != "human":
            raise KeyError(f"Human IAM role {role_id} not found")
        return await iam_service.bind_human_role(user_id, role_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/organizations/{organization_id}/iam/users/{user_id}/roles/{role_id}",
    response_model=dict,
    summary="Unbind an organization human IAM role from a user",
)
async def unbind_organization_human_role(
    request: Request,
    organization_id: UUID,
    user_id: UUID,
    role_id: UUID,
) -> dict[str, bool | str]:
    await _require_identity_permission(
        request,
        permission="organization.members.write",
        organization_id=organization_id,
    )
    try:
        role = await iam_service.get_iam_role_definition(role_id)
        if role is None or role.organization_id != organization_id or role.subject_kind != "human":
            raise KeyError(f"Human IAM role {role_id} not found")
        return await iam_service.unbind_human_role(user_id, role_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/iam/agent-identities",
    response_model=list[AgentIdentity],
    summary="List global agent identities",
)
async def list_global_agent_identities(request: Request) -> list[AgentIdentity]:
    await _require_identity_permission(request, permission="organization.members.read")
    try:
        return await iam_service.list_agent_identities(scope="global")
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/iam/agent-identities",
    response_model=list[AgentIdentity],
    summary="List organization agent identities",
)
async def list_organization_agent_identities(
    request: Request,
    organization_id: UUID,
) -> list[AgentIdentity]:
    await _require_identity_permission(
        request,
        permission="organization.members.read",
        organization_id=organization_id,
    )
    try:
        return await iam_service.list_agent_identities(
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/iam/agent-identities",
    response_model=AgentIdentityProvisioningResult,
    summary="Provision a global agent identity",
)
async def create_global_agent_identity(
    request: Request,
    payload: CreateAgentIdentityRequest,
) -> AgentIdentityProvisioningResult:
    await _require_identity_permission(request, permission="organization.members.write")
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        return await iam_service.create_agent_identity(payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/iam/agent-identities",
    response_model=AgentIdentityProvisioningResult,
    summary="Provision an organization agent identity",
)
async def create_organization_agent_identity(
    request: Request,
    organization_id: UUID,
    payload: CreateAgentIdentityRequest,
) -> AgentIdentityProvisioningResult:
    await _require_identity_permission(
        request,
        permission="organization.members.write",
        organization_id=organization_id,
    )
    payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
    try:
        system_agent = await iam_service.get_system_agent(payload.system_agent_id)
        if system_agent.scope != "organization" or system_agent.organization_id != organization_id:
            raise PermissionError(
                f"System agent {payload.system_agent_id} does not belong to organization {organization_id}"
            )
        return await iam_service.create_agent_identity(payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/iam/agent-identities/{agent_identity_id}",
    response_model=AgentIdentity,
    summary="Get one agent identity",
)
async def get_agent_identity(
    request: Request,
    agent_identity_id: UUID,
) -> AgentIdentity:
    try:
        identity = await iam_service.get_agent_identity(agent_identity_id)
        if identity is None:
            raise KeyError(f"Agent identity {agent_identity_id} not found")
        await _require_identity_permission(
            request,
            permission="organization.members.read",
            organization_id=identity.organization_id,
        )
        return identity
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/iam/agent-identities/{agent_identity_id}/roles",
    response_model=list[IamRoleDefinition],
    summary="List IAM roles bound to an agent identity",
)
async def list_agent_identity_roles(
    request: Request,
    agent_identity_id: UUID,
) -> list[IamRoleDefinition]:
    try:
        identity = await iam_service.get_agent_identity(agent_identity_id)
        if identity is None:
            raise KeyError(f"Agent identity {agent_identity_id} not found")
        await _require_identity_permission(
            request,
            permission="organization.members.read",
            organization_id=identity.organization_id,
        )
        return await iam_service.list_agent_roles_for_identity(
            agent_identity_id=agent_identity_id
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/iam/agent-identities/{agent_identity_id}/roles/{role_id}",
    response_model=dict,
    summary="Bind an IAM role to an agent identity",
)
async def bind_agent_identity_role(
    request: Request,
    agent_identity_id: UUID,
    role_id: UUID,
    payload: BindAgentRoleRequest,
) -> dict[str, str]:
    try:
        identity = await iam_service.get_agent_identity(agent_identity_id)
        if identity is None:
            raise KeyError(f"Agent identity {agent_identity_id} not found")
        await _require_identity_permission(
            request,
            permission="organization.members.write",
            organization_id=identity.organization_id,
        )
        payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
        return await iam_service.bind_agent_role(agent_identity_id, role_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/iam/agent-identities/{agent_identity_id}/roles/{role_id}",
    response_model=dict,
    summary="Unbind an IAM role from an agent identity",
)
async def unbind_agent_identity_role(
    request: Request,
    agent_identity_id: UUID,
    role_id: UUID,
) -> dict[str, bool | str]:
    try:
        identity = await iam_service.get_agent_identity(agent_identity_id)
        if identity is None:
            raise KeyError(f"Agent identity {agent_identity_id} not found")
        await _require_identity_permission(
            request,
            permission="organization.members.write",
            organization_id=identity.organization_id,
        )
        return await iam_service.unbind_agent_role(agent_identity_id, role_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/iam/agent-identities/{agent_identity_id}/rotate-secret",
    response_model=AgentIdentityProvisioningResult,
    summary="Rotate an agent identity client secret",
)
async def rotate_agent_identity_secret(
    request: Request,
    agent_identity_id: UUID,
    payload: RotateAgentIdentitySecretRequest,
) -> AgentIdentityProvisioningResult:
    try:
        identity = await iam_service.get_agent_identity(agent_identity_id)
        if identity is None:
            raise KeyError(f"Agent identity {agent_identity_id} not found")
        await _require_identity_permission(
            request,
            permission="organization.members.write",
            organization_id=identity.organization_id,
        )
        payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
        return await iam_service.rotate_agent_identity_secret(agent_identity_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/iam/agent-identities/{agent_identity_id}/disable",
    response_model=AgentIdentity,
    summary="Disable an agent identity in the external identity provider",
)
async def disable_agent_identity(
    request: Request,
    agent_identity_id: UUID,
    payload: UpdateAgentIdentityStatusRequest,
) -> AgentIdentity:
    try:
        identity = await iam_service.get_agent_identity(agent_identity_id)
        if identity is None:
            raise KeyError(f"Agent identity {agent_identity_id} not found")
        await _require_identity_permission(
            request,
            permission="organization.members.write",
            organization_id=identity.organization_id,
        )
        payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
        return await iam_service.disable_agent_identity(agent_identity_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/iam/agent-identities/{agent_identity_id}/enable",
    response_model=AgentIdentity,
    summary="Enable an agent identity in the external identity provider",
)
async def enable_agent_identity(
    request: Request,
    agent_identity_id: UUID,
    payload: UpdateAgentIdentityStatusRequest,
) -> AgentIdentity:
    try:
        identity = await iam_service.get_agent_identity(agent_identity_id)
        if identity is None:
            raise KeyError(f"Agent identity {agent_identity_id} not found")
        await _require_identity_permission(
            request,
            permission="organization.members.write",
            organization_id=identity.organization_id,
        )
        payload = payload.model_copy(update={"actor": _resolve_actor(request, payload.actor)})
        return await iam_service.enable_agent_identity(agent_identity_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc
