from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from uuid import UUID, uuid4

import asyncpg

from .contracts import (
    ActorRef,
    AgentConfiguration,
    AgentDefinition,
    AssumeParticipantRoleRequest,
    CreateAgentParticipantRequest,
    CreateSystemAgentRequest,
    CreateMemoryEntryRequest,
    CreateMessageRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteWorkspaceRequest,
    EventEnvelope,
    Membership,
    MemoryEntry,
    ParticipantInput,
    ParticipantProfile,
    PresenceState,
    RoleDefinition,
    Task,
    TargetRef,
    Thread,
    ThreadDetail,
    TimelineMessage,
    TimelinePage,
    UpdateSystemAgentRequest,
    UpsertRoleDefinitionRequest,
    UpdateAgentParticipantRequest,
    UpdateMemoryEntryRequest,
    Workspace,
    WorkspaceDetail,
)
from .repository import CollaborationRepository

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
class AgentDefinitionCommandResult(CommandResult):
    agent: AgentDefinition | None = None


class CollaborationKernel:
    def __init__(self, repository: CollaborationRepository) -> None:
        self._repository = repository

    async def setup_schema(self) -> None:
        await self._repository.setup_schema()

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
        return WorkspaceDetail(
            workspace=workspace,
            participants=participants,
            role_definitions=self._role_definitions_from_workspace(workspace),
        )

    async def list_workspace_participants(
        self, workspace_id: UUID
    ) -> list[ParticipantProfile]:
        logger.debug("Kernel list_workspace_participants workspace_id=%s", workspace_id)
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_participants(workspace_id)

    async def create_system_agent(
        self, payload: CreateSystemAgentRequest
    ) -> AgentDefinitionCommandResult:
        now = self._now()
        agent = AgentDefinition(
            agent_id=uuid4(),
            display_name=payload.display_name,
            description=payload.description,
            role=payload.role,
            capabilities=payload.capabilities,
            endpoint=payload.endpoint,
            system_prompt=payload.system_prompt,
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

    async def update_system_agent(
        self, agent_id: UUID, payload: UpdateSystemAgentRequest
    ) -> AgentDefinitionCommandResult:
        existing = await self._repository.fetch_system_agent(agent_id)
        if existing is None:
            raise KeyError(f"System agent {agent_id} not found")
        updated = existing.model_copy(
            update={
                "display_name": payload.display_name or existing.display_name,
                "description": payload.description or existing.description,
                "role": payload.role or existing.role,
                "capabilities": payload.capabilities or existing.capabilities,
                "endpoint": payload.endpoint or existing.endpoint,
                "system_prompt": payload.system_prompt or existing.system_prompt,
                "definition": payload.definition if payload.definition is not None else existing.definition,
                "updated_at": self._now(),
                "metadata": {**existing.metadata, **payload.metadata} if payload.metadata is not None else existing.metadata,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_agent(conn, updated)
        return AgentDefinitionCommandResult(agent=updated)

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
        participant = self._with_agent_metadata(participant)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
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
            capabilities=system_agent.capabilities,
            status="active",
            visibility_scope="workspace",
            agent_config=AgentConfiguration(
                endpoint=system_agent.endpoint,
                system_prompt=system_agent.system_prompt,
                definition=system_agent.definition,
            ),
            created_at=now,
            updated_at=now,
            metadata={"system_agent_id": str(system_agent.agent_id)},
        )
        participant = self._with_agent_metadata(participant)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
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
        return ParticipantCommandResult(participant=participant, events=[event])

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
        updated = self._with_agent_metadata(updated)
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
        return ParticipantCommandResult(participant=updated, events=[event])

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
                    task = Task(
                        task_id=uuid4(),
                        workspace_id=thread.workspace_id,
                        thread_id=thread_id,
                        title=f"Respond to message {message.message_id}",
                        description="Agent response requested for posted message.",
                        requested_by=payload.actor.participant_id,
                        correlation_id=correlation_id,
                        causation_id=message.message_id,
                        created_at=now,
                        updated_at=now,
                    )
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
                            sequence=await self._repository.next_thread_sequence(conn, thread_id),
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
        metadata = dict(participant.metadata)
        if participant.agent_config is None:
            metadata.pop("agent_config", None)
        else:
            metadata["agent_config"] = participant.agent_config.model_dump(mode="json")
        return participant.model_copy(update={"metadata": metadata})

    @staticmethod
    def _role_definitions_from_workspace(workspace: Workspace) -> list[RoleDefinition]:
        raw = workspace.metadata.get("role_definitions", {})
        if isinstance(raw, dict):
            return [RoleDefinition.model_validate(item) for item in raw.values()]
        if isinstance(raw, list):
            return [RoleDefinition.model_validate(item) for item in raw]
        return []

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
