from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
from uuid import UUID, uuid4

import asyncpg

from .contracts import (
    ActorRef,
    AgentArtifactDraft,
    AgentConfiguration,
    AgentDefinition,
    AgentExecutionContext,
    AgentRunResult,
    AgentToolCallDraft,
    AgentTaskRouting,
    AttachWorkspaceToolRequest,
    AssumeParticipantRoleRequest,
    Artifact,
    CreateAgentParticipantRequest,
    CreateSystemAgentRequest,
    CreateSystemToolRequest,
    CreateMemoryEntryRequest,
    CreateMessageRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteParticipantRequest,
    DeleteWorkspaceToolRequest,
    DeleteWorkspaceRequest,
    ExecutionWorkspaceRef,
    EventEnvelope,
    Membership,
    MemoryEntry,
    ParticipantInput,
    ParticipantProfile,
    PresenceState,
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
    Run,
    StopReason,
    ToolCall,
    ToolCallResult,
    UpdateSystemAgentRequest,
    UpsertRoleDefinitionRequest,
    UpdateSystemToolRequest,
    build_default_interaction_contract,
    interaction_contract_is_empty,
    UpdateAgentParticipantRequest,
    UpdateMemoryEntryRequest,
    UpdateWorkspaceToolRequest,
    Workspace,
    WorkspaceDetail,
    WorkspaceTool,
)
from .repository import CollaborationRepository, UserRecord

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    events: list[EventEnvelope] = field(default_factory=list)


@dataclass
class WorkspaceCommandResult(CommandResult):
    workspace: Workspace | None = None
    detail: WorkspaceDetail | None = None


@dataclass
class ThreadCommandResult(CommandResult):
    thread: Thread | None = None
    detail: ThreadDetail | None = None


@dataclass
class MessageCommandResult(CommandResult):
    message: TimelineMessage | None = None


@dataclass
class MemoryCommandResult(CommandResult):
    entry: MemoryEntry | None = None


@dataclass
class ParticipantCommandResult(CommandResult):
    participant: ParticipantProfile | None = None


@dataclass
class RoleDefinitionCommandResult(CommandResult):
    role_definition: RoleDefinition | None = None


@dataclass
class WorkspaceToolCommandResult(CommandResult):
    tool: WorkspaceTool | None = None


@dataclass
class SystemToolCommandResult(CommandResult):
    tool: SystemToolDefinition | None = None


@dataclass
class AgentDefinitionCommandResult(CommandResult):
    agent: AgentDefinition | None = None


@dataclass
class TaskCommandResult(CommandResult):
    task: Task | None = None
    run: Run | None = None
    context: AgentExecutionContext | None = None


@dataclass
class RunStepCommandResult(CommandResult):
    step: RunStep | None = None
    run: Run | None = None
    task: Task | None = None
    context: AgentExecutionContext | None = None


@dataclass
class ToolCallCommandResult(CommandResult):
    tool_call: ToolCall | None = None
    step: RunStep | None = None
    run: Run | None = None
    task: Task | None = None


@dataclass
class RunCommandResult(CommandResult):
    run: Run | None = None
    task: Task | None = None
    message: TimelineMessage | None = None
    artifacts: list[Artifact] = field(default_factory=list)


class CollaborationKernel:
    def __init__(self, repository: CollaborationRepository) -> None:
        self._repository = repository

    async def setup_schema(self) -> None:
        await self._repository.setup_schema()
        await self._backfill_system_agent_interaction_contracts()

    async def create_workspace(
        self, payload: CreateWorkspaceRequest
    ) -> WorkspaceCommandResult:
        logger.debug(
            "Kernel create_workspace participant_id=%s name=%r",
            payload.actor.participant_id,
            payload.name,
        )
        workspace_id = uuid4()
        now = self._now()
        workspace = Workspace(
            workspace_id=workspace_id,
            name=payload.name,
            description=payload.description,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        actor = self._actor_from_input(payload.actor)
        participant = self._participant_profile(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace(conn, workspace)
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)

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
                ]
                for event in events:
                    await self._repository.record_event(conn, event)

        detail = WorkspaceDetail(
            workspace=workspace,
            participants=[participant],
            role_definitions=self._role_definitions_from_workspace(workspace),
            tools=[],
        )
        logger.debug(
            "Kernel create_workspace complete workspace_id=%s event_count=%s",
            workspace_id,
            len(events),
        )
        return WorkspaceCommandResult(workspace=workspace, detail=detail, events=events)

    async def list_workspaces(self) -> list[Workspace]:
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
        self, payload: CreateSystemAgentRequest
    ) -> AgentDefinitionCommandResult:
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
            display_name=payload.display_name,
            description=payload.description,
            role=payload.role,
            capabilities=payload.capabilities,
            endpoint=payload.endpoint,
            system_prompt=payload.system_prompt,
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

    async def list_system_agents(self) -> list[AgentDefinition]:
        return await self._repository.list_system_agents()

    async def create_system_tool(
        self, payload: CreateSystemToolRequest
    ) -> SystemToolCommandResult:
        now = self._now()
        execution = payload.execution.model_copy(
            update={"handler_ref": payload.execution.handler_ref or payload.name}
        )
        tool = SystemToolDefinition(
            tool_id=uuid4(),
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

    async def list_system_tools(self) -> list[SystemToolDefinition]:
        return await self._repository.list_system_tools()

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
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_tool(conn, updated)
        return SystemToolCommandResult(tool=updated)

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

    async def _backfill_system_agent_interaction_contracts(self) -> None:
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

    async def list_workspace_tools(self, workspace_id: UUID) -> list[WorkspaceTool]:
        logger.debug("Kernel list_workspace_tools workspace_id=%s", workspace_id)
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_workspace_tools(workspace_id)

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
        system_tool = await self._repository.fetch_system_tool(payload.tool_id)
        if system_tool is None:
            raise KeyError(f"System tool {payload.tool_id} not found")
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
            user_id=participant_id if payload.actor.participant_type == "user" else None,
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
        system_agent = await self._repository.fetch_system_agent(payload.agent_id)
        if system_agent is None:
            raise KeyError(f"System agent {payload.agent_id} not found")
        workspace_tools = await self._repository.list_workspace_tools(workspace_id)
        now = self._now()
        actor = self._actor_from_input(payload.actor)
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
                definition=system_agent.definition,
            ),
            created_at=now,
            updated_at=now,
            metadata={},
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
        participant = self._participant_profile(
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

    async def get_thread_timeline(self, thread_id: UUID) -> TimelinePage:
        logger.debug("Kernel get_thread_timeline thread_id=%s", thread_id)
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        messages = await self._repository.list_timeline_messages(thread_id)
        return TimelinePage(thread_id=thread_id, messages=messages)

    async def list_pending_tasks_for_system_agent(
        self, system_agent_id: UUID, *, limit: int = 10
    ) -> list[Task]:
        logger.debug(
            "Kernel list_pending_tasks_for_system_agent system_agent_id=%s limit=%s",
            system_agent_id,
            limit,
        )
        return await self._repository.list_pending_tasks_for_system_agent(
            system_agent_id,
            limit=limit,
        )

    async def claim_task_for_system_agent(
        self,
        task_id: UUID,
        system_agent_id: UUID,
    ) -> TaskCommandResult:
        logger.debug(
            "Kernel claim_task_for_system_agent task_id=%s system_agent_id=%s",
            task_id,
            system_agent_id,
        )
        task = await self._repository.fetch_task(task_id)
        if task is None:
            raise KeyError(f"Task {task_id} not found")
        routing = self._task_routing(task)
        if routing.target_system_agent_id != system_agent_id:
            raise ValueError(
                f"Task {task_id} is not targeted to system agent {system_agent_id}"
            )
        workspace = await self._repository.fetch_workspace(task.workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {task.workspace_id} not found")
        thread = await self._repository.fetch_thread(task.thread_id)
        if thread is None:
            raise KeyError(f"Thread {task.thread_id} not found")
        system_agent = await self._repository.fetch_system_agent(system_agent_id)
        if system_agent is None:
            raise KeyError(f"System agent {system_agent_id} not found")
        participant = await self._resolve_agent_participant(
            workspace_id=task.workspace_id,
            system_agent_id=system_agent_id,
            routing=routing,
        )
        if participant is None:
            raise KeyError(
                f"System agent {system_agent_id} is not attached to workspace {task.workspace_id}"
            )

        now = self._now()
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                claimed_task = await self._repository.claim_task(
                    conn,
                    task_id=task_id,
                    participant_id=participant.participant_id,
                    updated_at=now,
                )
                if claimed_task is None:
                    raise ValueError(f"Task {task_id} is no longer claimable")
                run = Run(
                    run_id=uuid4(),
                    workspace_id=claimed_task.workspace_id,
                    thread_id=claimed_task.thread_id,
                    task_id=claimed_task.task_id,
                    participant_id=participant.participant_id,
                    status="started",
                    correlation_id=claimed_task.correlation_id,
                    causation_id=claimed_task.task_id,
                    created_at=now,
                    updated_at=now,
                    metadata={
                        "system_agent_id": str(system_agent_id),
                        "participant_id": str(participant.participant_id),
                        "endpoint_kind": system_agent.endpoint.kind,
                    },
                )
                await self._repository.upsert_run(conn, run)
                initial_step = RunStep(
                    step_id=uuid4(),
                    run_id=run.run_id,
                    task_id=claimed_task.task_id,
                    workspace_id=claimed_task.workspace_id,
                    thread_id=claimed_task.thread_id,
                    system_agent_id=system_agent_id,
                    step_index=0,
                    status="created",
                    submitted_at=now,
                    created_at=now,
                    updated_at=now,
                    metadata={
                        "participant_id": str(participant.participant_id),
                    },
                )
                await self._repository.upsert_run_step(conn, initial_step)
                actor = ActorRef(type="agent", id=participant.participant_id)
                events = [
                    await self._build_thread_event(
                        conn,
                        claimed_task.workspace_id,
                        claimed_task.thread_id,
                        "task.claimed",
                        actor=actor,
                        target=TargetRef(type="task", id=claimed_task.task_id),
                        payload={
                            "task_id": str(claimed_task.task_id),
                            "claimed_by": str(participant.participant_id),
                            "system_agent_id": str(system_agent_id),
                        },
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=claimed_task.correlation_id,
                        causation_id=claimed_task.causation_id,
                    ),
                    await self._build_thread_event(
                        conn,
                        claimed_task.workspace_id,
                        claimed_task.thread_id,
                        "run.started",
                        actor=actor,
                        target=TargetRef(type="run", id=run.run_id),
                        payload=run.model_dump(mode="json"),
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=claimed_task.correlation_id,
                        causation_id=claimed_task.task_id,
                    ),
                ]
                for event in events:
                    await self._repository.record_event(conn, event)

        context = await self.build_agent_execution_context(task_id, system_agent_id, run.run_id)
        return TaskCommandResult(task=claimed_task, run=run, context=context, events=events)

    async def build_agent_execution_context(
        self,
        task_id: UUID,
        system_agent_id: UUID,
        run_id: UUID | None = None,
    ) -> AgentExecutionContext:
        logger.debug(
            "Kernel build_agent_execution_context task_id=%s system_agent_id=%s run_id=%s",
            task_id,
            system_agent_id,
            run_id,
        )
        task = await self._repository.fetch_task(task_id)
        if task is None:
            raise KeyError(f"Task {task_id} not found")
        routing = self._task_routing(task)
        if routing.target_system_agent_id != system_agent_id:
            raise ValueError(
                f"Task {task_id} is not targeted to system agent {system_agent_id}"
            )
        system_agent = await self._repository.fetch_system_agent(system_agent_id)
        if system_agent is None:
            raise KeyError(f"System agent {system_agent_id} not found")
        workspace = await self._repository.fetch_workspace(task.workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {task.workspace_id} not found")
        thread = await self._repository.fetch_thread(task.thread_id)
        if thread is None:
            raise KeyError(f"Thread {task.thread_id} not found")
        participant = await self._resolve_agent_participant(
            workspace_id=task.workspace_id,
            system_agent_id=system_agent_id,
            routing=routing,
        )
        if participant is None:
            raise KeyError(
                f"System agent {system_agent_id} is not attached to workspace {task.workspace_id}"
            )
        run = await self._resolve_run_for_context(task, participant, run_id)
        workspace_tools = await self._repository.list_workspace_tools(task.workspace_id)
        participants = [
            self._advertise_workspace_tools(item, workspace_tools)
            for item in await self._repository.list_participants(task.workspace_id)
        ]
        memory_entries = await self._repository.list_memory_entries(task.workspace_id)
        messages = await self._repository.list_timeline_messages(task.thread_id)
        trigger_message = (
            await self._repository.fetch_message(routing.trigger_message_id)
            if routing.trigger_message_id is not None
            else None
        )
        visible_messages = self._filter_visible_messages(
            messages,
            viewer=participant,
            sequence_ceiling=routing.sequence_ceiling,
        )
        visible_memory_entries = self._filter_visible_memory_entries(
            memory_entries,
            viewer=participant,
        )
        tool_results = await self._repository.list_completed_tool_calls_for_run(run.run_id)
        return AgentExecutionContext(
            workspace=workspace,
            thread=thread,
            task=task,
            run=run,
            routing=routing,
            system_agent=system_agent,
            participant=self._advertise_workspace_tools(participant, workspace_tools),
            participants=participants,
            role_definitions=self._role_definitions_from_workspace(workspace),
            workspace_tools=workspace_tools,
            messages=visible_messages,
            memory_entries=visible_memory_entries,
            trigger_message=trigger_message,
            sequence_ceiling=routing.sequence_ceiling or 0,
            thread_reply_contract=system_agent.interaction_contract,
            tool_results=tool_results,
        )

    async def build_agent_execution_context_for_run_step(
        self,
        step_id: UUID,
    ) -> AgentExecutionContext:
        step = await self._repository.fetch_run_step(step_id)
        if step is None:
            raise KeyError(f"Run step {step_id} not found")
        context = await self.build_agent_execution_context(
            step.task_id,
            step.system_agent_id,
            step.run_id,
        )
        return context.model_copy(update={"run_step": step})

    async def claim_next_run_step(
        self,
        *,
        worker_id: str,
        lease_ttl_seconds: int,
    ) -> RunStepCommandResult:
        now = self._now()
        step = await self._repository.claim_next_run_step(
            worker_id=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_ttl_seconds),
            now=now,
        )
        if step is None:
            return RunStepCommandResult()
        run = await self._repository.fetch_run(step.run_id)
        if run is None:
            raise KeyError(f"Run {step.run_id} not found")
        task = await self._repository.fetch_task(step.task_id)
        if task is None:
            raise KeyError(f"Task {step.task_id} not found")
        context = await self.build_agent_execution_context_for_run_step(step.step_id)
        return RunStepCommandResult(
            step=step,
            run=run,
            task=task,
            context=context,
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
                    tool = await self._repository.fetch_workspace_tool_by_name(
                        task.workspace_id,
                        draft.tool_name,
                    )
                    if tool is None:
                        raise KeyError(
                            f"Workspace tool {draft.tool_name!r} not found in workspace {task.workspace_id}"
                        )
                    tool_call = ToolCall(
                        tool_call_id=uuid4(),
                        run_id=run.run_id,
                        run_step_id=step.step_id,
                        task_id=task.task_id,
                        workspace_id=task.workspace_id,
                        thread_id=task.thread_id,
                        system_agent_id=step.system_agent_id,
                        tool_id=tool.tool_id,
                        tool_name=tool.name,
                        status="created",
                        arguments=draft.arguments,
                        execution_spec=self._build_tool_execution_spec(
                            tool=tool,
                            draft=draft,
                            workspace_id=task.workspace_id,
                        ).model_dump(mode="json"),
                        submitted_at=now,
                        created_at=now,
                        updated_at=now,
                        metadata=draft.metadata,
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

    async def reconcile_expired_execution_leases(self) -> tuple[list[RunStep], list[ToolCall]]:
        now = self._now()
        run_steps = await self._repository.requeue_expired_run_steps(now=now)
        tool_calls = await self._repository.requeue_expired_tool_calls(now=now)
        return run_steps, tool_calls

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
        logger.debug(
            "Kernel append_run_progress run_id=%s system_agent_id=%s content_len=%s",
            run_id,
            system_agent_id,
            len(content),
        )
        run = await self._repository.fetch_run(run_id)
        if run is None:
            raise KeyError(f"Run {run_id} not found")
        task = await self._repository.fetch_task(run.task_id)
        if task is None:
            raise KeyError(f"Task {run.task_id} not found")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=system_agent_id,
        )
        now = self._now()
        updated_run = run.model_copy(
            update={
                "status": "progressing",
                "updated_at": now,
                "metadata": {**run.metadata, "last_progress": content},
            }
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run(conn, updated_run)
                event = await self._build_thread_event(
                    conn,
                    updated_run.workspace_id,
                    updated_run.thread_id,
                    "run.progressed",
                    actor=actor,
                    target=TargetRef(type="run", id=updated_run.run_id),
                    payload={"run_id": str(updated_run.run_id), "content": content},
                    visibility="agents_only",
                    timestamp=now,
                    correlation_id=updated_run.correlation_id,
                    causation_id=updated_run.task_id,
                )
                await self._repository.record_event(conn, event)
        return RunCommandResult(run=updated_run, task=task, events=[event])

    async def complete_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        result: AgentRunResult,
    ) -> RunCommandResult:
        logger.debug(
            "Kernel complete_run run_id=%s system_agent_id=%s stop_reason=%s has_message=%s artifact_count=%s",
            run_id,
            system_agent_id,
            result.stop_reason,
            bool(result.message),
            len(result.artifacts),
        )
        run = await self._repository.fetch_run(run_id)
        if run is None:
            raise KeyError(f"Run {run_id} not found")
        task = await self._repository.fetch_task(run.task_id)
        if task is None:
            raise KeyError(f"Task {run.task_id} not found")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=system_agent_id,
        )
        routing = self._task_routing(task)
        now = self._now()
        updated_run = run.model_copy(
            update={
                "status": "completed",
                "output": result.model_dump(mode="json"),
                "updated_at": now,
                "metadata": {
                    **run.metadata,
                    "stop_reason": result.stop_reason,
                    **result.metadata,
                },
            }
        )
        updated_task = task.model_copy(
            update={
                "status": "completed",
                "claimed_by": participant.participant_id,
                "updated_at": now,
                "metadata": {
                    **task.metadata,
                    "stop_reason": result.stop_reason,
                    "completed_run_id": str(updated_run.run_id),
                },
            }
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        artifacts = [
            self._artifact_from_draft(
                draft,
                task=updated_task,
                run=updated_run,
                timestamp=now,
            )
            for draft in result.artifacts
        ]
        message = (
            self._agent_message_from_result(
                result,
                task=updated_task,
                participant=participant,
                timestamp=now,
            )
            if self._stop_reason_returns_to_thread(result.stop_reason)
            and result.message
            else None
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run(conn, updated_run)
                await self._repository.upsert_task(conn, updated_task)
                membership = await self._repository.fetch_active_membership(
                    conn,
                    thread_id=updated_task.thread_id,
                    participant_id=participant.participant_id,
                )
                if membership is None:
                    membership = Membership(
                        membership_id=uuid4(),
                        workspace_id=updated_task.workspace_id,
                        thread_id=updated_task.thread_id,
                        participant_id=participant.participant_id,
                        role="agent",
                        permissions=["post_messages"],
                        joined_at=now,
                    )
                    await self._repository.upsert_membership(conn, membership)
                events = [
                    await self._build_thread_event(
                        conn,
                        updated_run.workspace_id,
                        updated_run.thread_id,
                        "run.completed",
                        actor=actor,
                        target=TargetRef(type="run", id=updated_run.run_id),
                        payload={
                            "run_id": str(updated_run.run_id),
                            "output": updated_run.output,
                            "stop_reason": result.stop_reason,
                        },
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=updated_run.correlation_id,
                        causation_id=updated_run.task_id,
                    ),
                    await self._build_thread_event(
                        conn,
                        updated_task.workspace_id,
                        updated_task.thread_id,
                        "task.completed",
                        actor=actor,
                        target=TargetRef(type="task", id=updated_task.task_id),
                        payload={
                            "task_id": str(updated_task.task_id),
                            "run_id": str(updated_run.run_id),
                            "stop_reason": result.stop_reason,
                        },
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=updated_task.correlation_id,
                        causation_id=updated_task.task_id,
                    ),
                ]
                if message is not None:
                    message.sequence = await self._repository.next_thread_sequence(
                        conn,
                        message.thread_id,
                    )
                    await self._repository.upsert_message(conn, message)
                    events.append(
                        EventEnvelope(
                            event_type="message.created",
                            workspace_id=message.workspace_id,
                            thread_id=message.thread_id,
                            actor=message.actor,
                            target=TargetRef(type="message", id=message.message_id),
                            visibility=message.visibility,
                            correlation_id=message.correlation_id,
                            causation_id=message.causation_id,
                            sequence=message.sequence,
                            timestamp=now,
                            payload=message.model_dump(mode="json"),
                        )
                    )
                for artifact in artifacts:
                    await self._repository.upsert_artifact(conn, artifact)
                    events.append(
                        await self._build_thread_event(
                            conn,
                            artifact.workspace_id,
                            artifact.thread_id,
                            "artifact.created",
                            actor=actor,
                            target=TargetRef(type="artifact", id=artifact.artifact_id),
                            payload=artifact.model_dump(mode="json"),
                            visibility=artifact.visibility,
                            timestamp=now,
                            correlation_id=artifact.correlation_id,
                            causation_id=updated_task.task_id,
                        )
                    )
                for event in events:
                    await self._repository.record_event(conn, event)
        return RunCommandResult(
            run=updated_run,
            task=updated_task,
            message=message,
            artifacts=artifacts,
            events=events,
        )

    async def fail_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        error: str,
        *,
        stop_reason: StopReason = "tool_failure",
    ) -> RunCommandResult:
        logger.debug(
            "Kernel fail_run run_id=%s system_agent_id=%s stop_reason=%s error_len=%s",
            run_id,
            system_agent_id,
            stop_reason,
            len(error),
        )
        run = await self._repository.fetch_run(run_id)
        if run is None:
            raise KeyError(f"Run {run_id} not found")
        task = await self._repository.fetch_task(run.task_id)
        if task is None:
            raise KeyError(f"Task {run.task_id} not found")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=system_agent_id,
        )
        now = self._now()
        updated_run = run.model_copy(
            update={
                "status": "failed",
                "output": {
                    "error": error,
                    "stop_reason": stop_reason,
                },
                "updated_at": now,
                "metadata": {
                    **run.metadata,
                    "stop_reason": stop_reason,
                },
            }
        )
        updated_task = task.model_copy(
            update={
                "status": "failed",
                "claimed_by": participant.participant_id,
                "updated_at": now,
                "metadata": {
                    **task.metadata,
                    "stop_reason": stop_reason,
                    "failed_run_id": str(updated_run.run_id),
                },
            }
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run(conn, updated_run)
                await self._repository.upsert_task(conn, updated_task)
                events = [
                    await self._build_thread_event(
                        conn,
                        updated_run.workspace_id,
                        updated_run.thread_id,
                        "run.failed",
                        actor=actor,
                        target=TargetRef(type="run", id=updated_run.run_id),
                        payload={
                            "run_id": str(updated_run.run_id),
                            "error": error,
                            "stop_reason": stop_reason,
                        },
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=updated_run.correlation_id,
                        causation_id=updated_run.task_id,
                    ),
                    await self._build_thread_event(
                        conn,
                        updated_task.workspace_id,
                        updated_task.thread_id,
                        "task.failed",
                        actor=actor,
                        target=TargetRef(type="task", id=updated_task.task_id),
                        payload={
                            "task_id": str(updated_task.task_id),
                            "run_id": str(updated_run.run_id),
                            "error": error,
                            "stop_reason": stop_reason,
                        },
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=updated_task.correlation_id,
                        causation_id=updated_task.task_id,
                    ),
                ]
                for event in events:
                    await self._repository.record_event(conn, event)
        return RunCommandResult(run=updated_run, task=updated_task, events=events)

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
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = self._participant_profile(
            workspace_id=thread.workspace_id,
            actor=payload.actor,
            now=now,
        )
        correlation_id = uuid4()
        message = TimelineMessage(
            message_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            actor=actor,
            visibility=payload.visibility,
            content=payload.content,
            status="completed",
            correlation_id=correlation_id,
            sequence=0,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
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
                events = [
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
                ]
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

                for event in events:
                    await self._repository.record_event(conn, event)

        logger.debug(
            "Kernel post_message complete thread_id=%s message_id=%s event_count=%s final_sequence=%s",
            thread_id,
            message.message_id,
            len(events),
            message.sequence,
        )
        return MessageCommandResult(message=message, events=events)

    async def list_memory_entries(self, workspace_id: UUID) -> list[MemoryEntry]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_memory_entries(workspace_id)

    async def create_memory_entry(
        self, workspace_id: UUID, payload: CreateMemoryEntryRequest
    ) -> MemoryCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = self._participant_profile(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        )
        entry = MemoryEntry(
            memory_entry_id=uuid4(),
            workspace_id=workspace_id,
            entry_type=payload.entry_type,
            title=payload.title,
            content=payload.content,
            tags=payload.tags,
            created_by=payload.actor.participant_id,
            updated_by=payload.actor.participant_id,
            visibility=payload.visibility,
            linked_thread_ids=payload.linked_thread_ids,
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
        return MemoryCommandResult(entry=entry, events=[event])

    async def update_memory_entry(
        self, workspace_id: UUID, memory_entry_id: UUID, payload: UpdateMemoryEntryRequest
    ) -> MemoryCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        existing = await self._repository.fetch_memory_entry(memory_entry_id)
        if existing is None or existing.workspace_id != workspace_id:
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = self._participant_profile(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        )
        updated = existing.model_copy(
            update={
                "title": payload.title if payload.title is not None else existing.title,
                "content": payload.content if payload.content is not None else existing.content,
                "tags": payload.tags if payload.tags is not None else existing.tags,
                "visibility": payload.visibility if payload.visibility is not None else existing.visibility,
                "linked_thread_ids": payload.linked_thread_ids
                if payload.linked_thread_ids is not None
                else existing.linked_thread_ids,
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
        return MemoryCommandResult(entry=updated, events=[event])

    async def delete_memory_entry(
        self, workspace_id: UUID, memory_entry_id: UUID, actor_input: ParticipantInput
    ) -> list[EventEnvelope]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        existing = await self._repository.fetch_memory_entry(memory_entry_id)
        if existing is None or existing.workspace_id != workspace_id:
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(actor_input)
        participant = self._participant_profile(
            workspace_id=workspace_id,
            actor=actor_input,
            now=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.delete_memory_entry(conn, memory_entry_id)
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
        return [event]

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
        participant = self._participant_profile(
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
                    },
                )
            )
        return tasks

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
            if message.visibility == "private" and message.actor.id == viewer.participant_id:
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
                "claimed_by_worker": None,
                "execution_handle": None,
                "finished_at": now,
                "updated_at": now,
            }
        )
        next_step: RunStep | None = None
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_tool_call(conn, updated_tool_call)
                event = await self._build_thread_event(
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
                await self._repository.record_event(conn, event)
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
                            "claimed_by_worker": None,
                            "execution_handle": None,
                            "finished_at": now,
                            "updated_at": now,
                        }
                    )
                    await self._repository.upsert_run_step(conn, step)
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

        return ToolCallCommandResult(
            tool_call=updated_tool_call,
            step=next_step or step,
            run=run,
            task=task,
            events=[event],
        )

    def _build_tool_execution_spec(
        self,
        *,
        tool: WorkspaceTool,
        draft: AgentToolCallDraft,
        workspace_id: UUID,
    ) -> ExecutionSpec:
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
    ) -> ParticipantProfile:
        return ParticipantProfile(
            participant_id=actor.participant_id,
            workspace_id=workspace_id,
            participant_type=actor.participant_type,
            user_id=actor.participant_id if actor.participant_type == "user" else None,
            display_name=actor.display_name,
            description=actor.description,
            roles=actor.roles,
            capabilities=actor.capabilities,
            status=status,
            visibility_scope=actor.visibility_scope,
            created_at=now,
            updated_at=now,
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

    @staticmethod
    def _role_definitions_from_workspace(workspace: Workspace) -> list[RoleDefinition]:
        raw = workspace.metadata.get("role_definitions", {})
        if isinstance(raw, dict):
            return [RoleDefinition.model_validate(item) for item in raw.values()]
        if isinstance(raw, list):
            return [RoleDefinition.model_validate(item) for item in raw]
        return []

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
