from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, HTTPException, Query, Request

from gateway_edge.iam.authorization import authorization_engine
from gateway_edge.models import (
    AuthContext,
    CreateExternalAccountRequest,
    CreateExternalIdentityGrantRequest,
    CreateExternalSystemRequest,
    DeleteExternalIdentityGrantRequest,
    DeleteExternalSystemRequest,
    ExecuteExternalOperationRequest,
    ExternalAccount,
    ExternalIdentityGrant,
    ExternalIdentityResolution,
    ExternalOperationRequest,
    ExternalSystemDefinition,
    ParticipantInput,
    ReviewExternalOperationRequest,
    UpdateExternalAccountRequest,
    UpdateExternalIdentityGrantRequest,
    UpdateExternalSystemRequest,
)
from gateway_edge.services import collaboration as collab_svc
from gateway_edge.services.external_operations import direct_external_operation_executor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["external-access"])


def _request_auth_context(request: Request) -> AuthContext | None:
    auth_context = getattr(request.state, "auth_context", None)
    return auth_context if isinstance(auth_context, AuthContext) else None


def _principal_actor(request: Request, fallback: ParticipantInput) -> ParticipantInput:
    auth_context = _request_auth_context(request)
    if auth_context is None or auth_context.kind != "oidc":
        return fallback
    if auth_context.principal_type == "human":
        if auth_context.user_id is None or not auth_context.display_name:
            return fallback
        return fallback.model_copy(
            update={
                "participant_id": auth_context.user_id,
                "participant_type": "user",
                "user_id": auth_context.user_id,
                "display_name": auth_context.display_name,
            }
        )
    participant_id = auth_context.system_agent_id or auth_context.agent_identity_id
    if participant_id is None:
        return fallback
    return fallback.model_copy(
        update={
            "participant_id": participant_id,
            "participant_type": "agent",
            "user_id": None,
            "display_name": (
                auth_context.display_name
                or auth_context.client_id
                or auth_context.subject
                or fallback.display_name
            ),
        }
    )


def _request_actor(request: Request, actor: ParticipantInput | None = None) -> ParticipantInput:
    fallback = actor or ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        display_name="request",
    )
    return _principal_actor(request, fallback)


async def _workspace_organization_id(workspace_id: UUID) -> UUID:
    detail = await collab_svc.collaboration_service.get_workspace(workspace_id)
    return detail.workspace.organization_id


async def _ensure_system_visible_to_workspace(
    system: ExternalSystemDefinition,
    workspace_id: UUID,
) -> UUID:
    detail = await collab_svc.collaboration_service.get_workspace(workspace_id)
    organization_id = detail.workspace.organization_id
    if system.scope == "organization" and system.organization_id != organization_id:
        raise HTTPException(status_code=404, detail=f"External system {system.system_id} not found")
    return organization_id


async def _actor_with_identity_permission(
    request: Request,
    actor: ParticipantInput,
    *,
    permission: str,
    organization_id: UUID | None = None,
) -> ParticipantInput:
    resolution = await authorization_engine.authorize(
        permission,
        {
            "auth_context": _request_auth_context(request),
            "permission_type": "identity",
            "permission": permission,
            "organization_id": organization_id,
        },
    )
    resolved = _request_actor(request, actor)
    return resolved.model_copy(
        update={"iam_permissions": sorted(resolution.identity_permissions)}
    )


async def _workspace_actor(
    request: Request,
    workspace_id: UUID,
) -> ParticipantInput:
    resolution = await authorization_engine.compute_effective_permissions(
        _request_auth_context(request),
        workspace_id=workspace_id,
    )
    if resolution.workspace_participant is None and resolution.principal.principal_type != "api_key":
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")
    if resolution.workspace_participant is None:
        return _request_actor(request)
    return resolution.workspace_participant.model_copy(
        update={"iam_permissions": sorted(resolution.workspace_permissions)}
    )


def _http_error(exc: Exception) -> HTTPException:
    logger.exception("External access request failed: %s", exc)
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/external-systems",
    response_model=ExternalSystemDefinition,
    summary="Create a global external system definition",
)
async def create_global_external_system(
    request: Request,
    payload: CreateExternalSystemRequest,
) -> ExternalSystemDefinition:
    try:
        actor = await _actor_with_identity_permission(
            request,
            payload.actor,
            permission="external.systems.write",
        )
        return await collab_svc.collaboration_service.create_external_system(
            payload.model_copy(update={"actor": actor}),
            scope="global",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/organizations/{organization_id}/external-systems",
    response_model=ExternalSystemDefinition,
    summary="Create an organization external system definition",
)
async def create_organization_external_system(
    request: Request,
    organization_id: UUID,
    payload: CreateExternalSystemRequest,
) -> ExternalSystemDefinition:
    try:
        actor = await _actor_with_identity_permission(
            request,
            payload.actor,
            permission="external.systems.write",
            organization_id=organization_id,
        )
        return await collab_svc.collaboration_service.create_external_system(
            payload.model_copy(update={"actor": actor}),
            scope="organization",
            organization_id=organization_id,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/organizations/{organization_id}/external-systems",
    response_model=list[ExternalSystemDefinition],
    summary="List organization external system definitions",
)
async def list_organization_external_systems(
    request: Request,
    organization_id: UUID,
) -> list[ExternalSystemDefinition]:
    try:
        await authorization_engine.authorize(
            "external.systems.read",
            {
                "auth_context": _request_auth_context(request),
                "permission_type": "identity",
                "permission": "external.systems.read",
                "organization_id": organization_id,
            },
        )
        systems = await collab_svc.collaboration_service.list_external_systems(scope="global")
        systems.extend(
            await collab_svc.collaboration_service.list_external_systems(
                scope="organization",
                organization_id=organization_id,
            )
        )
        return systems
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/external-systems/{system_id}",
    response_model=ExternalSystemDefinition,
    summary="Update an external system definition",
)
async def update_external_system(
    request: Request,
    system_id: UUID,
    payload: UpdateExternalSystemRequest,
) -> ExternalSystemDefinition:
    try:
        existing = await collab_svc.collaboration_service.get_external_system(system_id)
        if existing is None:
            raise KeyError(f"External system {system_id} not found")
        actor = await _actor_with_identity_permission(
            request,
            payload.actor,
            permission="external.systems.write",
            organization_id=existing.organization_id,
        )
        return await collab_svc.collaboration_service.update_external_system(
            system_id,
            payload.model_copy(update={"actor": actor}),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/external-systems/{system_id}",
    response_model=dict,
    summary="Delete an external system definition",
)
async def delete_external_system(
    request: Request,
    system_id: UUID,
    payload: DeleteExternalSystemRequest,
) -> dict[str, bool | str]:
    try:
        existing = await collab_svc.collaboration_service.get_external_system(system_id)
        if existing is None:
            raise KeyError(f"External system {system_id} not found")
        actor = await _actor_with_identity_permission(
            request,
            payload.actor,
            permission="external.systems.write",
            organization_id=existing.organization_id,
        )
        return await collab_svc.collaboration_service.delete_external_system(
            system_id,
            payload.model_copy(update={"actor": actor}),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/external-accounts",
    response_model=ExternalAccount,
    summary="Create an external account reference for grants",
)
async def create_external_account(
    request: Request,
    workspace_id: UUID,
    payload: CreateExternalAccountRequest,
) -> ExternalAccount:
    try:
        organization_id = await _workspace_organization_id(workspace_id)
        system = await collab_svc.collaboration_service.get_external_system(
            payload.system_id
        )
        if system is None:
            raise KeyError(f"External system {payload.system_id} not found")
        await _ensure_system_visible_to_workspace(system, workspace_id)
        actor = await _actor_with_identity_permission(
            request,
            payload.actor,
            permission="external.grants.write",
            organization_id=organization_id,
        )
        return await collab_svc.collaboration_service.create_external_account(
            payload.model_copy(update={"actor": actor}),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/external-accounts/{account_id}",
    response_model=ExternalAccount,
    summary="Update an external account reference",
)
async def update_external_account(
    request: Request,
    account_id: UUID,
    workspace_id: UUID = Query(...),
    payload: UpdateExternalAccountRequest = Body(...),
) -> ExternalAccount:
    try:
        account = await collab_svc.collaboration_service.get_external_account(account_id)
        if account is None:
            raise KeyError(f"External account {account_id} not found")
        system = await collab_svc.collaboration_service.get_external_system(
            account.system_id
        )
        if system is None:
            raise KeyError(f"External system {account.system_id} not found")
        organization_id = await _ensure_system_visible_to_workspace(system, workspace_id)
        actor = await _actor_with_identity_permission(
            request,
            payload.actor,
            permission="external.grants.write",
            organization_id=organization_id,
        )
        return await collab_svc.collaboration_service.update_external_account(
            account_id,
            payload.model_copy(update={"actor": actor}),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/external-identity-grants",
    response_model=ExternalIdentityGrant,
    summary="Grant external identity access to a workspace participant",
)
async def create_external_identity_grant(
    request: Request,
    workspace_id: UUID,
    payload: CreateExternalIdentityGrantRequest,
) -> ExternalIdentityGrant:
    try:
        organization_id = await _workspace_organization_id(workspace_id)
        actor = await _actor_with_identity_permission(
            request,
            payload.actor,
            permission="external.grants.write",
            organization_id=organization_id,
        )
        return await collab_svc.collaboration_service.create_external_identity_grant(
            workspace_id,
            payload.model_copy(update={"actor": actor}),
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/external-identity-grants",
    response_model=list[ExternalIdentityGrant],
    summary="List external identity grants in a workspace",
)
async def list_external_identity_grants(
    request: Request,
    workspace_id: UUID,
    participant_id: UUID | None = Query(default=None),
    include_inactive: bool = Query(default=False),
) -> list[ExternalIdentityGrant]:
    try:
        organization_id = await _workspace_organization_id(workspace_id)
        try:
            await authorization_engine.authorize(
                "external.grants.read",
                {
                    "auth_context": _request_auth_context(request),
                    "permission_type": "identity",
                    "permission": "external.grants.read",
                    "organization_id": organization_id,
                },
            )
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
            actor = await _workspace_actor(request, workspace_id)
            return await collab_svc.collaboration_service.list_external_identity_grants(
                workspace_id=workspace_id,
                participant_id=actor.participant_id,
                include_inactive=False,
            )
        return await collab_svc.collaboration_service.list_external_identity_grants(
            workspace_id=workspace_id,
            participant_id=participant_id,
            include_inactive=include_inactive,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


async def _update_external_identity_grant_in_workspace(
    request: Request,
    *,
    workspace_id: UUID,
    grant_id: UUID,
    payload: UpdateExternalIdentityGrantRequest,
) -> ExternalIdentityGrant:
    existing = await collab_svc.collaboration_service.get_external_identity_grant(
        grant_id
    )
    if existing is None:
        raise KeyError(f"External identity grant {grant_id} not found")
    if existing.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"External identity grant {grant_id} not found")
    organization_id = await _workspace_organization_id(existing.workspace_id)
    actor = await _actor_with_identity_permission(
        request,
        payload.actor,
        permission="external.grants.write",
        organization_id=organization_id,
    )
    return await collab_svc.collaboration_service.update_external_identity_grant(
        grant_id,
        payload.model_copy(update={"actor": actor}),
    )


@router.patch(
    "/workspaces/{workspace_id}/external-identity-grants/{grant_id}",
    response_model=ExternalIdentityGrant,
    summary="Update a workspace external identity grant",
)
async def update_workspace_external_identity_grant(
    request: Request,
    workspace_id: UUID,
    grant_id: UUID,
    payload: UpdateExternalIdentityGrantRequest,
) -> ExternalIdentityGrant:
    try:
        return await _update_external_identity_grant_in_workspace(
            request,
            workspace_id=workspace_id,
            grant_id=grant_id,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/external-identity-grants/{grant_id}",
    response_model=ExternalIdentityGrant,
    summary="Update an external identity grant (legacy query workspace scope)",
)
async def update_external_identity_grant(
    request: Request,
    grant_id: UUID,
    workspace_id: UUID = Query(...),
    payload: UpdateExternalIdentityGrantRequest = Body(...),
) -> ExternalIdentityGrant:
    try:
        return await _update_external_identity_grant_in_workspace(
            request,
            workspace_id=workspace_id,
            grant_id=grant_id,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


async def _delete_external_identity_grant_in_workspace(
    request: Request,
    *,
    workspace_id: UUID,
    grant_id: UUID,
    payload: DeleteExternalIdentityGrantRequest,
) -> ExternalIdentityGrant:
    existing = await collab_svc.collaboration_service.get_external_identity_grant(
        grant_id
    )
    if existing is None:
        raise KeyError(f"External identity grant {grant_id} not found")
    if existing.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"External identity grant {grant_id} not found")
    organization_id = await _workspace_organization_id(existing.workspace_id)
    actor = await _actor_with_identity_permission(
        request,
        payload.actor,
        permission="external.grants.write",
        organization_id=organization_id,
    )
    return await collab_svc.collaboration_service.delete_external_identity_grant(
        grant_id,
        payload.model_copy(update={"actor": actor}),
    )


@router.delete(
    "/workspaces/{workspace_id}/external-identity-grants/{grant_id}",
    response_model=ExternalIdentityGrant,
    summary="Revoke a workspace external identity grant",
)
async def delete_workspace_external_identity_grant(
    request: Request,
    workspace_id: UUID,
    grant_id: UUID,
    payload: DeleteExternalIdentityGrantRequest,
) -> ExternalIdentityGrant:
    try:
        return await _delete_external_identity_grant_in_workspace(
            request,
            workspace_id=workspace_id,
            grant_id=grant_id,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/external-identity-grants/{grant_id}",
    response_model=ExternalIdentityGrant,
    summary="Revoke an external identity grant (legacy query workspace scope)",
)
async def delete_external_identity_grant(
    request: Request,
    grant_id: UUID,
    workspace_id: UUID = Query(...),
    payload: DeleteExternalIdentityGrantRequest = Body(...),
) -> ExternalIdentityGrant:
    try:
        return await _delete_external_identity_grant_in_workspace(
            request,
            workspace_id=workspace_id,
            grant_id=grant_id,
            payload=payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/external-systems/{system_id}/operations/{operation_key}",
    response_model=ExternalIdentityResolution,
    summary="Authorize a direct external operation for the executing participant",
)
async def execute_external_operation(
    request: Request,
    workspace_id: UUID,
    system_id: UUID,
    operation_key: str,
    payload: ExecuteExternalOperationRequest,
) -> ExternalIdentityResolution:
    try:
        actor = await _workspace_actor(request, workspace_id)
        resolution = await collab_svc.collaboration_service.resolve_external_identity_for_operation(
            workspace_id=workspace_id,
            participant_id=actor.participant_id,
            system_id=system_id,
            operation_key=operation_key,
            risk_level=payload.risk_level,
            thread_id=payload.thread_id,
            request_metadata={
                **payload.metadata,
                "argument_keys": sorted(payload.arguments.keys()),
            },
        )
        operation_result = None
        if resolution.approved:
            operation_result = await direct_external_operation_executor.execute(
                resolution=resolution,
                operation_key=operation_key,
                arguments=payload.arguments,
            )
        return resolution.model_copy(
            update={
                "system": resolution.system.model_copy(update={"secret_config": {}}),
                "account": (
                    resolution.account.model_copy(update={"credential_ref": {}})
                    if resolution.account is not None
                    else None
                ),
                "operation_result": operation_result,
            }
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/external-operation-requests",
    response_model=list[ExternalOperationRequest],
    summary="List external operation approval requests",
)
async def list_external_operation_requests(
    request: Request,
    workspace_id: UUID,
    status: str | None = Query(default=None),
) -> list[ExternalOperationRequest]:
    try:
        organization_id = await _workspace_organization_id(workspace_id)
        await authorization_engine.authorize(
            "external.operations.approve",
            {
                "auth_context": _request_auth_context(request),
                "permission_type": "identity",
                "permission": "external.operations.approve",
                "organization_id": organization_id,
            },
        )
        return await collab_svc.collaboration_service.list_external_operation_requests(
            workspace_id=workspace_id,
            status=status,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


async def _review_external_operation_request_in_workspace(
    request: Request,
    *,
    workspace_id: UUID,
    operation_request_id: UUID,
    payload: ReviewExternalOperationRequest,
    decision: str,
) -> ExternalOperationRequest:
    existing = await collab_svc.collaboration_service.get_external_operation_request(
        operation_request_id
    )
    if existing is None:
        raise KeyError(f"External operation request {operation_request_id} not found")
    if existing.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail=f"External operation request {operation_request_id} not found")
    organization_id = await _workspace_organization_id(existing.workspace_id)
    actor = await _actor_with_identity_permission(
        request,
        payload.actor,
        permission="external.operations.approve",
        organization_id=organization_id,
    )
    reviewed_payload = payload.model_copy(update={"actor": actor})
    if decision == "approve":
        return await collab_svc.collaboration_service.approve_external_operation_request(
            operation_request_id,
            reviewed_payload,
        )
    if decision == "reject":
        return await collab_svc.collaboration_service.reject_external_operation_request(
            operation_request_id,
            reviewed_payload,
        )
    raise ValueError(f"Unsupported external operation review decision {decision!r}")


@router.post(
    "/workspaces/{workspace_id}/external-operation-requests/{operation_request_id}/approve",
    response_model=ExternalOperationRequest,
    summary="Approve a workspace external operation request",
)
async def approve_workspace_external_operation_request(
    request: Request,
    workspace_id: UUID,
    operation_request_id: UUID,
    payload: ReviewExternalOperationRequest,
) -> ExternalOperationRequest:
    try:
        return await _review_external_operation_request_in_workspace(
            request,
            workspace_id=workspace_id,
            operation_request_id=operation_request_id,
            payload=payload,
            decision="approve",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/external-operation-requests/{operation_request_id}/approve",
    response_model=ExternalOperationRequest,
    summary="Approve an external operation request (legacy query workspace scope)",
)
async def approve_external_operation_request(
    request: Request,
    operation_request_id: UUID,
    workspace_id: UUID = Query(...),
    payload: ReviewExternalOperationRequest = Body(...),
) -> ExternalOperationRequest:
    try:
        return await _review_external_operation_request_in_workspace(
            request,
            workspace_id=workspace_id,
            operation_request_id=operation_request_id,
            payload=payload,
            decision="approve",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/external-operation-requests/{operation_request_id}/reject",
    response_model=ExternalOperationRequest,
    summary="Reject a workspace external operation request",
)
async def reject_workspace_external_operation_request(
    request: Request,
    workspace_id: UUID,
    operation_request_id: UUID,
    payload: ReviewExternalOperationRequest,
) -> ExternalOperationRequest:
    try:
        return await _review_external_operation_request_in_workspace(
            request,
            workspace_id=workspace_id,
            operation_request_id=operation_request_id,
            payload=payload,
            decision="reject",
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/external-operation-requests/{operation_request_id}/reject",
    response_model=ExternalOperationRequest,
    summary="Reject an external operation request (legacy query workspace scope)",
)
async def reject_external_operation_request(
    request: Request,
    operation_request_id: UUID,
    workspace_id: UUID = Query(...),
    payload: ReviewExternalOperationRequest = Body(...),
) -> ExternalOperationRequest:
    try:
        return await _review_external_operation_request_in_workspace(
            request,
            workspace_id=workspace_id,
            operation_request_id=operation_request_id,
            payload=payload,
            decision="reject",
        )
    except Exception as exc:
        raise _http_error(exc) from exc
