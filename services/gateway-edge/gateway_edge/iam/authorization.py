from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from gateway_edge.config import settings
from gateway_edge.models import (
    AuthContext,
    IamPermission,
    ParticipantInput,
    ParticipantProfile,
    PrincipalContext,
    Workspace,
)
from gateway_edge.services import collaboration as collab_svc
from open_talon_contracts.iam import (
    IDENTITY_PERMISSION_DESCRIPTIONS,
    ORGANIZATION_ROLE_BASE_PERMISSIONS,
    WORKSPACE_PERMISSION_DESCRIPTIONS,
)


@dataclass
class PermissionResolution:
    principal: PrincipalContext
    identity_permissions: set[str] = field(default_factory=set)
    workspace_permissions: set[str] = field(default_factory=set)
    organization_member: bool = False
    workspace_participant: ParticipantInput | None = None
    workspace_profile: ParticipantProfile | None = None
    workspace: Workspace | None = None


def permission_catalog() -> list[IamPermission]:
    permissions: list[IamPermission] = []
    for name, description in IDENTITY_PERMISSION_DESCRIPTIONS.items():
        permissions.append(
            IamPermission(name=name, scope_type="identity", description=description)
        )
    for name, description in WORKSPACE_PERMISSION_DESCRIPTIONS.items():
        permissions.append(
            IamPermission(name=name, scope_type="workspace", description=description)
        )
    return permissions


class AuthorizationEngine:
    async def resolve_principal_context(self, auth_context: AuthContext | None) -> PrincipalContext:
        if auth_context is None:
            return PrincipalContext(principal_type="api_key", auth_method="api_key")
        if auth_context.kind == "api_key":
            return PrincipalContext(principal_type="api_key", auth_method="api_key")
        return PrincipalContext(
            principal_type=auth_context.principal_type,
            auth_method="oidc",
            user_id=auth_context.user_id,
            agent_identity_id=auth_context.agent_identity_id,
            system_agent_id=auth_context.system_agent_id,
            issuer=auth_context.issuer,
            subject=auth_context.subject,
            client_id=auth_context.client_id,
            provider_key=auth_context.provider_key,
            platform_admin=auth_context.platform_admin
            or settings.oidc_admin_role in auth_context.roles,
            claims=auth_context.claims,
        )

    async def compute_effective_permissions(
        self,
        auth_context: AuthContext | None,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> PermissionResolution:
        principal = await self.resolve_principal_context(auth_context)
        if principal.principal_type == "api_key":
            return PermissionResolution(
                principal=principal,
                identity_permissions=set(IDENTITY_PERMISSION_DESCRIPTIONS),
                workspace_permissions=set(WORKSPACE_PERMISSION_DESCRIPTIONS),
            )

        resolution = PermissionResolution(principal=principal)
        effective_organization_id = organization_id
        if workspace_id is not None:
            try:
                workspace_detail = await collab_svc.collaboration_service.get_workspace(workspace_id)
            except KeyError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=f"Workspace {workspace_id} not found",
                ) from exc
            resolution.workspace = workspace_detail.workspace
            effective_organization_id = workspace_detail.workspace.organization_id

        if principal.principal_type == "human" and principal.user_id is not None:
            if effective_organization_id is not None:
                memberships = await collab_svc.collaboration_service.list_organization_memberships(
                    effective_organization_id
                )
                membership = next(
                    (item for item in memberships if item.user_id == principal.user_id),
                    None,
                )
                if membership is not None:
                    resolution.organization_member = True
                    resolution.identity_permissions.update(
                        ORGANIZATION_ROLE_BASE_PERMISSIONS.get(membership.role, ())
                    )
            human_roles = await collab_svc.collaboration_service.list_human_roles_for_user(
                user_id=principal.user_id,
                organization_id=effective_organization_id,
            )
            resolution.identity_permissions.update(
                role_permission
                for role in human_roles
                for role_permission in role.permissions
            )
        elif principal.principal_type == "agent" and principal.agent_identity_id is not None:
            identity = await collab_svc.collaboration_service.get_agent_identity(
                principal.agent_identity_id
            )
            if identity is not None:
                if identity.scope == "global" or identity.organization_id == effective_organization_id:
                    resolution.organization_member = (
                        effective_organization_id is None
                        or identity.scope == "global"
                        or identity.organization_id == effective_organization_id
                    )
                    resolution.identity_permissions.update(
                        role_permission
                        for role in await collab_svc.collaboration_service.list_agent_roles_for_identity(
                            agent_identity_id=identity.agent_identity_id
                        )
                        if role.scope == "global"
                        or role.organization_id == effective_organization_id
                        for role_permission in role.permissions
                    )

        if principal.platform_admin:
            resolution.identity_permissions.update(IDENTITY_PERMISSION_DESCRIPTIONS)
            resolution.workspace_permissions.update(WORKSPACE_PERMISSION_DESCRIPTIONS)

        if workspace_id is not None:
            assert resolution.workspace is not None
            if principal.principal_type == "human" and auth_context is not None:
                try:
                    actor = await collab_svc.collaboration_service.resolve_authenticated_user_actor(
                        workspace_id=workspace_id,
                        auth_context=auth_context,
                        auto_create=False,
                    )
                except KeyError:
                    actor = None
                if actor is not None:
                    participant = next(
                        (
                            item
                            for item in workspace_detail.participants
                            if item.participant_id == actor.participant_id
                        ),
                        None,
                    )
                    resolution.workspace_participant = actor
                    resolution.workspace_profile = participant
            elif principal.principal_type == "agent" and auth_context is not None:
                try:
                    actor = await collab_svc.collaboration_service.resolve_authenticated_agent_actor(
                        workspace_id=workspace_id,
                        auth_context=auth_context,
                    )
                except KeyError:
                    actor = None
                if actor is not None:
                    participant = next(
                        (
                            item
                            for item in workspace_detail.participants
                            if item.participant_id == actor.participant_id
                        ),
                        None,
                    )
                    resolution.workspace_participant = actor
                    resolution.workspace_profile = participant
            resolution.workspace_permissions.update(
                permission
                for permission in resolution.identity_permissions
                if permission in WORKSPACE_PERMISSION_DESCRIPTIONS
            )
        return resolution

    async def authorize(self, action: str, resource_context: dict[str, Any]) -> PermissionResolution:
        auth_context = resource_context.get("auth_context")
        permission_type = resource_context.get("permission_type", "identity")
        permission = resource_context["permission"]
        organization_id = resource_context.get("organization_id")
        workspace_id = resource_context.get("workspace_id")
        resolution = await self.compute_effective_permissions(
            auth_context,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        if permission_type == "workspace":
            if (
                resolution.workspace_participant is None
                and resolution.principal.principal_type != "api_key"
            ):
                raise HTTPException(status_code=404, detail=f"Workspace {workspace_id} not found")
            if permission not in resolution.workspace_permissions:
                raise HTTPException(status_code=403, detail=f"Workspace permission {permission!r} required")
            return resolution

        if (
            resolution.principal.principal_type == "human"
            and organization_id is not None
            and not resolution.organization_member
            and not resolution.principal.platform_admin
        ):
            raise HTTPException(status_code=404, detail=f"Organization {organization_id} not found")
        if permission not in resolution.identity_permissions:
            raise HTTPException(status_code=403, detail=f"Permission {permission!r} required")
        return resolution


authorization_engine = AuthorizationEngine()
