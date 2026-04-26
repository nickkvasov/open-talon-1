from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from gateway_edge.config import settings
from gateway_edge.models import (
    AgentDefinition,
    AgentIdentity,
    BindAgentRoleRequest,
    CreateAgentIdentityRequest,
    IamRoleDefinition,
    ParticipantInput,
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
            if organization.slug == "system-base":
                continue
            curator = await self._find_agent(
                scope="organization",
                organization_id=organization.organization_id,
                agent_key="curator",
            )
            if curator is None:
                continue
            role = await self._find_role(
                scope="organization",
                organization_id=organization.organization_id,
                name="organization_curator",
            )
            if role is None:
                continue
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
            return identity
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
