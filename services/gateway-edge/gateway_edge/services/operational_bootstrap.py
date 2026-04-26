from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import httpx
from open_talon_contracts.secrets import (
    OpenBaoSecretProvider,
    SecretResolver,
    secret_references_from_config,
)

from gateway_edge.config import settings
from gateway_edge.models import (
    AgentDefinition,
    AgentIdentity,
    BindAgentRoleRequest,
    CreateAgentIdentityRequest,
    IamRoleDefinition,
    ParticipantInput,
    RotateAgentIdentitySecretRequest,
)
from gateway_edge.services.collaboration import collaboration_service
from gateway_edge.services.iam import iam_service

logger = logging.getLogger(__name__)

_SYSTEM_ACTOR = ParticipantInput(
    participant_id=UUID("00000000-0000-0000-0000-000000000000"),
    participant_type="agent",
    display_name="Open Talon System",
    roles=["system"],
    capabilities=["bootstrap"],
    iam_permissions=[],
)


class OperationalBootstrapService:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not settings.operational_agents_bootstrap_enabled:
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_with_retries())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def _run_with_retries(self) -> None:
        attempts = max(1, settings.operational_agents_bootstrap_attempts)
        for attempt in range(1, attempts + 1):
            try:
                await self.run_once()
                logger.info("Operational agent bootstrap completed")
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if attempt >= attempts:
                    logger.warning("Operational agent bootstrap failed: %s", exc)
                    return
                logger.debug(
                    "Operational agent bootstrap attempt %s/%s failed: %s",
                    attempt,
                    attempts,
                    exc,
                )
                await asyncio.sleep(settings.operational_agents_bootstrap_interval_seconds)

    async def run_once(self) -> None:
        steward = await self._find_agent(scope="global", organization_id=None, agent_key="steward")
        if steward is not None:
            role = await self._find_role(
                scope="global",
                organization_id=None,
                name="platform_steward",
            )
            if role is not None:
                identity = await self._ensure_identity(steward)
                await self._ensure_role_binding(identity, role)

        organizations = await collaboration_service.list_organizations()
        for organization in organizations:
            await self.ensure_for_organization(organization.organization_id)

    async def ensure_for_organization(self, organization_id: UUID) -> None:
        organization = await collaboration_service.get_organization(organization_id)
        if organization.slug == "system-base":
            return
        curator = await self._find_agent(
            scope="organization",
            organization_id=organization.organization_id,
            agent_key="curator",
        )
        if curator is None:
            return
        role = await self._find_role(
            scope="organization",
            organization_id=organization.organization_id,
            name="organization_curator",
        )
        if role is None:
            return
        identity = await self._ensure_identity(curator)
        await self._ensure_role_binding(identity, role)

    async def _find_agent(
        self,
        *,
        scope: str,
        organization_id: UUID | None,
        agent_key: str,
    ) -> AgentDefinition | None:
        agents = await collaboration_service.list_system_agents(
            scope=scope,
            organization_id=organization_id,
        )
        return next((agent for agent in agents if agent.agent_key == agent_key), None)

    async def _find_role(
        self,
        *,
        scope: str,
        organization_id: UUID | None,
        name: str,
    ) -> IamRoleDefinition | None:
        roles = await collaboration_service.list_iam_role_definitions(
            subject_kind="agent",
            scope=scope,
            organization_id=organization_id,
        )
        return next((role for role in roles if role.name == name), None)

    async def _ensure_identity(self, agent: AgentDefinition) -> AgentIdentity:
        existing = await iam_service.list_agent_identities(
            scope=agent.scope,
            organization_id=agent.organization_id,
        )
        identity = next(
            (item for item in existing if item.system_agent_id == agent.agent_id),
            None,
        )
        if identity is not None:
            return await self._repair_identity_if_needed(identity)
        result = await iam_service.create_agent_identity(
            CreateAgentIdentityRequest(
                actor=_SYSTEM_ACTOR,
                system_agent_id=agent.agent_id,
                client_id=f"open-talon-agent-{agent.agent_key}-{str(agent.agent_id)[:8]}",
                metadata={
                    "managed": True,
                    "operational_agent": True,
                    "agent_key": agent.agent_key,
                },
            )
        )
        return result.identity

    async def _repair_identity_if_needed(self, identity: AgentIdentity) -> AgentIdentity:
        if identity.status != "active":
            return identity
        try:
            if await self._identity_client_credentials_work(identity):
                return identity
        except Exception as exc:
            logger.info(
                "Managed operational agent identity %s credential validation failed: %s",
                identity.agent_identity_id,
                exc,
            )
        result = await iam_service.rotate_agent_identity_secret(
            identity.agent_identity_id,
            RotateAgentIdentitySecretRequest(
                actor=_SYSTEM_ACTOR,
                metadata={
                    "managed": True,
                    "operational_agent": True,
                    "bootstrap_secret_repaired": True,
                },
            ),
        )
        logger.info(
            "Repaired managed operational agent identity %s secret",
            identity.agent_identity_id,
        )
        return result.identity

    async def _identity_client_credentials_work(self, identity: AgentIdentity) -> bool:
        resolver = SecretResolver(
            [
                OpenBaoSecretProvider(
                    address=settings.openbao_address,
                    token=settings.openbao_admin_token,
                    default_mount=settings.openbao_kv_mount,
                )
            ]
        )
        client_secret = await resolver.resolve(
            secret_references_from_config(identity.secret_ref),
            label=f"managed agent identity {identity.agent_identity_id} client secret",
        )
        token_endpoint = identity.metadata.get("token_endpoint")
        if not isinstance(token_endpoint, str) or not token_endpoint:
            token_endpoint = f"{identity.issuer.rstrip('/')}/protocol/openid-connect/token"
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.post(
                token_endpoint,
                data={
                    "grant_type": "client_credentials",
                    "client_id": identity.client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if response.status_code in {400, 401, 403}:
            return False
        response.raise_for_status()
        access_token = response.json().get("access_token")
        return isinstance(access_token, str) and bool(access_token)

    async def _ensure_role_binding(
        self,
        identity: AgentIdentity,
        role: IamRoleDefinition,
    ) -> None:
        existing = await iam_service.list_agent_roles_for_identity(
            agent_identity_id=identity.agent_identity_id,
        )
        if any(item.role_id == role.role_id for item in existing):
            return
        await iam_service.bind_agent_role(
            identity.agent_identity_id,
            role.role_id,
            BindAgentRoleRequest(
                actor=_SYSTEM_ACTOR,
                metadata={"managed": True, "operational_agent": True},
            ),
        )


operational_bootstrap_service = OperationalBootstrapService()
