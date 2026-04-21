from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from gateway_edge.config import settings
from gateway_edge.iam.authorization import permission_catalog
from gateway_edge.iam.keycloak import build_machine_identity_provisioner
from gateway_edge.iam.openbao import build_secret_store
from gateway_edge.models import (
    AgentDefinition,
    AgentIdentity,
    AgentIdentityProvisioningResult,
    BindAgentRoleRequest,
    BindHumanRoleRequest,
    CreateAgentIdentityRequest,
    CreateIamRoleRequest,
    IamPermission,
    IamRoleDefinition,
    RotateAgentIdentitySecretRequest,
    UpdateAgentIdentityStatusRequest,
    UpdateIamRoleRequest,
)
from gateway_edge.services.collaboration import collaboration_service


class IamService:
    async def get_system_agent(self, system_agent_id: UUID) -> AgentDefinition:
        return await self._require_system_agent(system_agent_id)

    async def list_permissions(self) -> list[IamPermission]:
        return permission_catalog()

    async def list_iam_role_definitions(
        self,
        *,
        subject_kind: str,
        scope: str | None = None,
        organization_id: UUID | None = None,
    ) -> list[IamRoleDefinition]:
        return await collaboration_service.list_iam_role_definitions(
            subject_kind=subject_kind,
            scope=scope,
            organization_id=organization_id,
        )

    async def get_iam_role_definition(self, role_id: UUID) -> IamRoleDefinition | None:
        return await collaboration_service.get_iam_role_definition(role_id)

    async def create_iam_role_definition(
        self,
        payload: CreateIamRoleRequest,
        *,
        subject_kind: str,
        scope: str,
        organization_id: UUID | None = None,
    ) -> IamRoleDefinition:
        return await collaboration_service.create_iam_role_definition(
            payload,
            subject_kind=subject_kind,
            scope=scope,
            organization_id=organization_id,
        )

    async def update_iam_role_definition(
        self,
        role_id: UUID,
        payload: UpdateIamRoleRequest,
    ) -> IamRoleDefinition:
        return await collaboration_service.update_iam_role_definition(role_id, payload)

    async def delete_iam_role_definition(self, role_id: UUID) -> dict[str, bool | str]:
        return await collaboration_service.delete_iam_role_definition(role_id)

    async def list_human_roles_for_user(
        self,
        *,
        user_id: UUID,
        organization_id: UUID | None = None,
    ) -> list[IamRoleDefinition]:
        return await collaboration_service.list_human_roles_for_user(
            user_id=user_id,
            organization_id=organization_id,
        )

    async def bind_human_role(
        self,
        user_id: UUID,
        role_id: UUID,
        payload: BindHumanRoleRequest,
    ) -> dict[str, str]:
        return await collaboration_service.bind_human_role(user_id, role_id, payload)

    async def unbind_human_role(
        self,
        user_id: UUID,
        role_id: UUID,
    ) -> dict[str, bool | str]:
        return await collaboration_service.unbind_human_role(user_id, role_id)

    async def list_agent_identities(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
    ) -> list[AgentIdentity]:
        return await collaboration_service.list_agent_identities(
            scope=scope,
            organization_id=organization_id,
        )

    async def get_agent_identity(self, agent_identity_id: UUID) -> AgentIdentity | None:
        return await collaboration_service.get_agent_identity(agent_identity_id)

    async def create_agent_identity(
        self,
        payload: CreateAgentIdentityRequest,
    ) -> AgentIdentityProvisioningResult:
        system_agent = await self._require_system_agent(payload.system_agent_id)
        client_id = payload.client_id or self._default_client_id(system_agent)
        existing_identities = await self.list_agent_identities(
            scope=system_agent.scope,
            organization_id=system_agent.organization_id,
        )
        if any(identity.client_id == client_id for identity in existing_identities):
            raise ValueError(f"Agent identity client_id {client_id!r} already exists")
        if any(identity.system_agent_id == system_agent.agent_id for identity in existing_identities):
            raise ValueError(
                f"System agent {system_agent.agent_id} already has a provisioned machine identity"
            )

        provisioner = build_machine_identity_provisioner()
        secret_store = build_secret_store()
        provisioned = await provisioner.create_machine_identity(
            client_id=client_id,
            display_name=system_agent.display_name,
            description=system_agent.description,
            metadata={
                "scope": system_agent.scope,
                "organization_id": (
                    str(system_agent.organization_id)
                    if system_agent.organization_id is not None
                    else None
                ),
                **payload.metadata,
            },
        )
        agent_identity_id = uuid4()
        secret_ref = await secret_store.store_secret(
            path=self._secret_path(agent_identity_id),
            values={"client_secret": provisioned.client_secret},
        )
        identity = AgentIdentity(
            agent_identity_id=agent_identity_id,
            system_agent_id=system_agent.agent_id,
            scope=system_agent.scope,
            organization_id=system_agent.organization_id,
            provider_key=settings.identity_provider_key,
            issuer=provisioned.issuer,
            external_subject=provisioned.external_subject or provisioned.client_id,
            client_id=provisioned.client_id,
            status="active",
            secret_ref=self._normalized_secret_ref(secret_ref),
            created_at=self._now(),
            updated_at=self._now(),
            metadata={**payload.metadata, **provisioned.metadata},
        )
        stored = await collaboration_service.store_agent_identity(identity)
        return AgentIdentityProvisioningResult(
            identity=stored,
            client_secret=provisioned.client_secret,
            issuer=provisioned.issuer,
            token_endpoint=provisioned.token_endpoint,
        )

    async def rotate_agent_identity_secret(
        self,
        agent_identity_id: UUID,
        payload: RotateAgentIdentitySecretRequest,
    ) -> AgentIdentityProvisioningResult:
        identity = await self._require_agent_identity(agent_identity_id)
        provisioner = build_machine_identity_provisioner()
        secret_store = build_secret_store()
        provisioned = await provisioner.rotate_machine_secret(client_id=identity.client_id)
        secret_ref = await secret_store.store_secret(
            path=self._existing_secret_path(identity),
            values={"client_secret": provisioned.client_secret},
        )
        updated = identity.model_copy(
            update={
                "issuer": provisioned.issuer,
                "external_subject": provisioned.external_subject or identity.external_subject,
                "secret_ref": self._normalized_secret_ref(secret_ref),
                "updated_at": self._now(),
                "metadata": {**identity.metadata, **payload.metadata, **provisioned.metadata},
            }
        )
        stored = await collaboration_service.store_agent_identity(updated)
        return AgentIdentityProvisioningResult(
            identity=stored,
            client_secret=provisioned.client_secret,
            issuer=provisioned.issuer,
            token_endpoint=provisioned.token_endpoint,
        )

    async def disable_agent_identity(
        self,
        agent_identity_id: UUID,
        payload: UpdateAgentIdentityStatusRequest,
    ) -> AgentIdentity:
        _ = payload
        identity = await self._require_agent_identity(agent_identity_id)
        provisioner = build_machine_identity_provisioner()
        await provisioner.disable_machine_identity(client_id=identity.client_id)
        updated = identity.model_copy(
            update={
                "status": "disabled",
                "updated_at": self._now(),
                "metadata": {**identity.metadata, **payload.metadata},
            }
        )
        return await collaboration_service.store_agent_identity(updated)

    async def enable_agent_identity(
        self,
        agent_identity_id: UUID,
        payload: UpdateAgentIdentityStatusRequest,
    ) -> AgentIdentity:
        _ = payload
        identity = await self._require_agent_identity(agent_identity_id)
        provisioner = build_machine_identity_provisioner()
        await provisioner.enable_machine_identity(client_id=identity.client_id)
        updated = identity.model_copy(
            update={
                "status": "active",
                "updated_at": self._now(),
                "metadata": {**identity.metadata, **payload.metadata},
            }
        )
        return await collaboration_service.store_agent_identity(updated)

    async def list_agent_roles_for_identity(
        self,
        *,
        agent_identity_id: UUID,
    ) -> list[IamRoleDefinition]:
        return await collaboration_service.list_agent_roles_for_identity(
            agent_identity_id=agent_identity_id
        )

    async def bind_agent_role(
        self,
        agent_identity_id: UUID,
        role_id: UUID,
        payload: BindAgentRoleRequest,
    ) -> dict[str, str]:
        return await collaboration_service.bind_agent_role(agent_identity_id, role_id, payload)

    async def unbind_agent_role(
        self,
        agent_identity_id: UUID,
        role_id: UUID,
    ) -> dict[str, bool | str]:
        return await collaboration_service.unbind_agent_role(agent_identity_id, role_id)

    async def _require_system_agent(self, system_agent_id: UUID) -> AgentDefinition:
        system_agent = await collaboration_service.get_system_agent(system_agent_id)
        if system_agent is None:
            raise KeyError(f"System agent {system_agent_id} not found")
        return system_agent

    async def _require_agent_identity(self, agent_identity_id: UUID) -> AgentIdentity:
        identity = await collaboration_service.get_agent_identity(agent_identity_id)
        if identity is None:
            raise KeyError(f"Agent identity {agent_identity_id} not found")
        return identity

    @staticmethod
    def _default_client_id(system_agent: AgentDefinition) -> str:
        slug = system_agent.display_name.strip().lower().replace(" ", "-")
        return f"open-talon-agent-{slug}-{str(system_agent.agent_id)[:8]}"

    @staticmethod
    def _normalized_secret_ref(secret_ref: dict[str, object]) -> dict[str, object]:
        ref = dict(secret_ref)
        openbao = ref.get("openbao")
        if isinstance(openbao, dict):
            normalized = dict(openbao)
            normalized.setdefault("field", "client_secret")
            ref["openbao"] = normalized
        return ref

    @staticmethod
    def _secret_path(agent_identity_id: UUID) -> str:
        prefix = settings.agent_identity_secret_prefix.strip("/")
        return f"{prefix}/{agent_identity_id}"

    @classmethod
    def _existing_secret_path(cls, identity: AgentIdentity) -> str:
        openbao = identity.secret_ref.get("openbao")
        if isinstance(openbao, dict):
            path = openbao.get("path")
            if isinstance(path, str) and path:
                return path
        return cls._secret_path(identity.agent_identity_id)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)


iam_service = IamService()
