from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

_GW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/gateway-edge")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
for path in (_GW_DIR, _CONTRACTS_DIR, _CORE_COLLAB_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_contracts.agent_contracts import (
    build_default_interaction_contract,
    interaction_contract_is_empty,
)


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


class MockCollaborationService:
    def __init__(self) -> None:
        self.workspaces = {}
        self.system_agents = {}
        self.participants = {}
        self.role_definitions = {}
        self.threads = {}
        self.memberships = {}
        self.messages = {}
        self.memory_entries = {}
        self.events = {}
        self.workspace_sequences = {}
        self.thread_sequences = {}
        self.subscriptions = {}

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def create_workspace(self, payload):
        from gateway_edge.models import Workspace, WorkspaceDetail, ParticipantProfile

        now = datetime.now(timezone.utc)
        workspace = Workspace(
            workspace_id=uuid4(),
            name=payload.name,
            description=payload.description,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        participant = ParticipantProfile(
            participant_id=payload.actor.participant_id,
            workspace_id=workspace.workspace_id,
            participant_type=payload.actor.participant_type,
            display_name=payload.actor.display_name,
            description=payload.actor.description,
            roles=payload.actor.roles,
            capabilities=payload.actor.capabilities,
            visibility_scope=payload.actor.visibility_scope,
            created_at=now,
            updated_at=now,
        )
        self.workspaces[str(workspace.workspace_id)] = workspace
        self.participants.setdefault(str(workspace.workspace_id), {})[
            str(participant.participant_id)
        ] = participant
        self.role_definitions[str(workspace.workspace_id)] = {}
        self.workspace_sequences[str(workspace.workspace_id)] = 2
        return WorkspaceDetail(
            workspace=workspace,
            participants=[participant],
            role_definitions=[],
        )

    async def list_workspaces(self):
        return list(self.workspaces.values())

    async def delete_workspace(self, workspace_id: UUID, payload):
        workspace = self.workspaces.pop(str(workspace_id), None)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        self.participants.pop(str(workspace_id), None)
        self.role_definitions.pop(str(workspace_id), None)
        thread_ids = [
            thread_id
            for thread_id, thread in self.threads.items()
            if thread.workspace_id == workspace_id
        ]
        for thread_id in thread_ids:
            self.threads.pop(thread_id, None)
            self.memberships.pop(thread_id, None)
            self.messages.pop(thread_id, None)
            self.events.pop(thread_id, None)
            self.thread_sequences.pop(thread_id, None)
            self.subscriptions.pop(thread_id, None)
        self.memory_entries.pop(str(workspace_id), None)
        self.workspace_sequences.pop(str(workspace_id), None)
        return {"deleted": True, "workspace_id": str(workspace_id)}

    async def get_workspace(self, workspace_id: UUID):
        from gateway_edge.models import WorkspaceDetail

        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        participants = list(self.participants.get(str(workspace_id), {}).values())
        role_definitions = list(self.role_definitions.get(str(workspace_id), {}).values())
        return WorkspaceDetail(
            workspace=workspace,
            participants=participants,
            role_definitions=role_definitions,
        )

    async def list_workspace_participants(self, workspace_id: UUID):
        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return list(self.participants.get(str(workspace_id), {}).values())

    async def delete_participant(self, workspace_id: UUID, participant_id: UUID, payload):
        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        removed = self.participants.get(str(workspace_id), {}).pop(str(participant_id), None)
        if removed is None:
            raise KeyError(f"Participant {participant_id} not found")
        for memberships in self.memberships.values():
            for membership in memberships:
                if membership.participant_id == participant_id and membership.left_at is None:
                    membership.left_at = datetime.now(timezone.utc)
        return {
            "deleted": True,
            "workspace_id": str(workspace_id),
            "participant_id": str(participant_id),
        }

    async def create_system_agent(self, payload):
        from gateway_edge.models import AgentDefinition

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
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            metadata=payload.metadata,
        )
        self.system_agents[str(agent.agent_id)] = agent
        return agent

    async def list_system_agents(self):
        return list(self.system_agents.values())

    async def update_system_agent(self, agent_id: UUID, payload):
        agent = self.system_agents.get(str(agent_id))
        if agent is None:
            raise KeyError(f"System agent {agent_id} not found")
        updated = agent.model_copy(
            update={
                "display_name": payload.display_name or agent.display_name,
                "description": payload.description or agent.description,
                "role": payload.role or agent.role,
                "capabilities": payload.capabilities or agent.capabilities,
                "endpoint": payload.endpoint or agent.endpoint,
                "system_prompt": payload.system_prompt or agent.system_prompt,
                "interaction_contract": (
                    payload.interaction_contract
                    if payload.interaction_contract is not None
                    else agent.interaction_contract
                ),
                "definition": payload.definition if payload.definition is not None else agent.definition,
                "updated_at": datetime.now(timezone.utc),
                "metadata": {**agent.metadata, **payload.metadata} if payload.metadata is not None else agent.metadata,
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
        self.system_agents[str(agent_id)] = updated
        return updated

    async def upsert_role_definition(self, workspace_id: UUID, payload):
        from gateway_edge.models import RoleDefinition

        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        role_definition = RoleDefinition(
            name=payload.name,
            definition=payload.definition,
            updated_by=payload.actor.participant_id,
            updated_at=datetime.now(timezone.utc),
        )
        self.role_definitions.setdefault(str(workspace_id), {})[payload.name] = role_definition
        return role_definition

    async def assume_participant_role(self, workspace_id: UUID, participant_id: UUID, payload):
        from gateway_edge.models import ParticipantProfile

        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        if participant_id != payload.actor.participant_id:
            raise ValueError("Participants may only assume roles for themselves")
        workspace_participants = self.participants.setdefault(str(workspace_id), {})
        existing = workspace_participants.get(str(participant_id))
        now = datetime.now(timezone.utc)
        role_definition = self.role_definitions.get(str(workspace_id), {}).get(payload.role)
        description = payload.description or (
            role_definition.definition if role_definition is not None else None
        )
        if description is None:
            raise ValueError(
                f"Role {payload.role!r} is not defined in this workspace; provide a description or create the role first"
            )
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
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            metadata=existing.metadata if existing is not None else {},
        )
        workspace_participants[str(participant_id)] = participant
        return participant

    async def create_agent_participant(self, workspace_id: UUID, payload):
        from gateway_edge.models import AgentConfiguration, ParticipantProfile

        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        system_agent = self.system_agents.get(str(payload.agent_id))
        if system_agent is None:
            raise KeyError(f"System agent {payload.agent_id} not found")
        now = datetime.now(timezone.utc)
        participant = ParticipantProfile(
            participant_id=uuid4(),
            workspace_id=workspace_id,
            participant_type="agent",
            system_agent_id=system_agent.agent_id,
            display_name=system_agent.display_name,
            description=system_agent.description,
            roles=[system_agent.role],
            capabilities=system_agent.capabilities,
            visibility_scope="workspace",
            agent_config=AgentConfiguration(
                endpoint=system_agent.endpoint,
                system_prompt=system_agent.system_prompt,
                definition=system_agent.definition,
            ),
            created_at=now,
            updated_at=now,
            metadata={
                "system_agent_id": str(system_agent.agent_id),
                "agent_config": {
                    "endpoint": system_agent.endpoint.model_dump(mode="json"),
                    "system_prompt": system_agent.system_prompt,
                    "definition": system_agent.definition,
                },
            },
        )
        self.participants.setdefault(str(workspace_id), {})[
            str(participant.participant_id)
        ] = participant
        return participant

    async def update_agent_participant(self, workspace_id: UUID, participant_id: UUID, payload):
        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        participants = self.participants.setdefault(str(workspace_id), {})
        participant = participants.get(str(participant_id))
        if participant is None:
            raise KeyError(f"Participant {participant_id} not found")
        if participant.participant_type != "agent":
            raise ValueError("Only agent participants can be updated via the agent API")
        metadata = dict(participant.metadata)
        if payload.metadata is not None:
            metadata.update(payload.metadata)
        if participant.agent_config is not None:
            metadata["agent_config"] = participant.agent_config.model_dump(mode="json")
        updated = participant.model_copy(
            update={
                "visibility_scope": payload.visibility_scope or participant.visibility_scope,
                "status": payload.status or participant.status,
                "updated_at": datetime.now(timezone.utc),
                "metadata": metadata,
            }
        )
        participants[str(participant_id)] = updated
        return updated

    async def create_thread(self, workspace_id: UUID, payload):
        from gateway_edge.models import Membership, ParticipantProfile, Thread, ThreadDetail

        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        now = datetime.now(timezone.utc)
        self.participants.setdefault(str(workspace_id), {})[str(payload.actor.participant_id)] = (
            self.participants.get(str(workspace_id), {}).get(
                str(payload.actor.participant_id),
                ParticipantProfile(
                    participant_id=payload.actor.participant_id,
                    workspace_id=workspace_id,
                    participant_type=payload.actor.participant_type,
                    display_name=payload.actor.display_name,
                    description=payload.actor.description,
                    roles=payload.actor.roles,
                    capabilities=payload.actor.capabilities,
                    visibility_scope=payload.actor.visibility_scope,
                    created_at=now,
                    updated_at=now,
                ),
            )
        )
        thread = Thread(
            thread_id=uuid4(),
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
            thread_id=thread.thread_id,
            participant_id=payload.actor.participant_id,
            role="owner",
            permissions=["post_messages", "manage_thread", "edit_memory"],
            joined_at=now,
        )
        self.threads[str(thread.thread_id)] = thread
        self.memberships.setdefault(str(thread.thread_id), []).append(membership)
        self.thread_sequences[str(thread.thread_id)] = 2
        self.events.setdefault(str(thread.thread_id), [])
        return ThreadDetail(thread=thread, memberships=[membership])

    async def list_threads(self, workspace_id: UUID):
        if str(workspace_id) not in self.workspaces:
            raise KeyError(f"Workspace {workspace_id} not found")
        return [
            thread
            for thread in self.threads.values()
            if thread.workspace_id == workspace_id
        ]

    async def get_thread(self, thread_id: UUID):
        from gateway_edge.models import ThreadDetail

        thread = self.threads.get(str(thread_id))
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        memberships = self.memberships.get(str(thread_id), [])
        return ThreadDetail(thread=thread, memberships=memberships)

    async def get_timeline(self, thread_id: UUID):
        from gateway_edge.models import TimelinePage

        if str(thread_id) not in self.threads:
            raise KeyError(f"Thread {thread_id} not found")
        return TimelinePage(
            thread_id=thread_id,
            messages=self.messages.get(str(thread_id), []),
        )

    async def post_message(self, thread_id: UUID, payload):
        from gateway_edge.models import ActorRef, EventEnvelope, TargetRef, TimelineMessage

        thread = self.threads.get(str(thread_id))
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        now = datetime.now(timezone.utc)
        next_sequence = self.thread_sequences.get(str(thread_id), 0) + 1
        self.thread_sequences[str(thread_id)] = next_sequence
        message = TimelineMessage(
            message_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type=payload.actor.participant_type, id=payload.actor.participant_id),
            visibility=payload.visibility,
            content=payload.content,
            status="completed",
            correlation_id=uuid4(),
            sequence=next_sequence,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        self.messages.setdefault(str(thread_id), []).append(message)
        event = EventEnvelope(
            event_type="message.created",
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            actor=message.actor,
            target=TargetRef(type="message", id=message.message_id),
            visibility=payload.visibility,
            correlation_id=message.correlation_id,
            sequence=message.sequence,
            timestamp=now,
            payload=message.model_dump(mode="json"),
        )
        self.events.setdefault(str(thread_id), []).append(event)
        await self._fan_out(thread_id, event)
        if payload.create_task:
            task_event = EventEnvelope(
                event_type="task.created",
                workspace_id=thread.workspace_id,
                thread_id=thread_id,
                actor=message.actor,
                target=TargetRef(type="task", id=uuid4()),
                visibility="agents_only",
                correlation_id=message.correlation_id,
                causation_id=message.message_id,
                sequence=message.sequence + 1,
                timestamp=now,
                payload={"thread_id": str(thread_id)},
            )
            self.thread_sequences[str(thread_id)] = message.sequence + 1
            self.events[str(thread_id)].append(task_event)
            await self._fan_out(thread_id, task_event)
        return message

    async def list_memory_entries(self, workspace_id: UUID):
        if str(workspace_id) not in self.workspaces:
            raise KeyError(f"Workspace {workspace_id} not found")
        return list(self.memory_entries.get(str(workspace_id), {}).values())

    async def create_memory_entry(self, workspace_id: UUID, payload):
        from gateway_edge.models import MemoryEntry

        if str(workspace_id) not in self.workspaces:
            raise KeyError(f"Workspace {workspace_id} not found")
        now = datetime.now(timezone.utc)
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
        self.memory_entries.setdefault(str(workspace_id), {})[
            str(entry.memory_entry_id)
        ] = entry
        return entry

    async def update_memory_entry(self, workspace_id: UUID, memory_entry_id: UUID, payload):
        entries = self.memory_entries.get(str(workspace_id), {})
        entry = entries.get(str(memory_entry_id))
        if entry is None:
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        updated = entry.model_copy(
            update={
                "title": payload.title if payload.title is not None else entry.title,
                "content": payload.content if payload.content is not None else entry.content,
                "tags": payload.tags if payload.tags is not None else entry.tags,
                "visibility": payload.visibility if payload.visibility is not None else entry.visibility,
                "linked_thread_ids": payload.linked_thread_ids
                if payload.linked_thread_ids is not None
                else entry.linked_thread_ids,
                "updated_by": payload.actor.participant_id,
                "updated_at": datetime.now(timezone.utc),
                "version": entry.version + 1,
            }
        )
        entries[str(memory_entry_id)] = updated
        return updated

    async def delete_memory_entry(self, workspace_id: UUID, memory_entry_id: UUID, actor):
        entries = self.memory_entries.get(str(workspace_id), {})
        if str(memory_entry_id) not in entries:
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        entries.pop(str(memory_entry_id))
        return {"deleted": True, "memory_entry_id": str(memory_entry_id)}

    async def publish_presence(self, *, thread_id: UUID, actor, status: str, connection_id: str | None = None):
        from gateway_edge.models import EventEnvelope, TargetRef, ActorRef

        thread = self.threads.get(str(thread_id))
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        sequence = self.thread_sequences.get(str(thread_id), 0) + 1
        self.thread_sequences[str(thread_id)] = sequence
        event = EventEnvelope(
            event_type="presence.updated",
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type=actor.participant_type, id=actor.participant_id),
            target=TargetRef(type="participant", id=actor.participant_id),
            visibility="workspace",
            correlation_id=uuid4(),
            sequence=sequence,
            timestamp=datetime.now(timezone.utc),
            payload={
                "participant_id": str(actor.participant_id),
                "status": status,
                "connection_id": connection_id,
            },
        )
        self.events.setdefault(str(thread_id), []).append(event)
        await self._fan_out(thread_id, event)
        return event

    async def on_thread_connected(self, *, thread_id: UUID, actor, connection_id: str):
        return await self.publish_presence(
            thread_id=thread_id,
            actor=actor,
            status="active",
            connection_id=connection_id,
        )

    async def on_thread_disconnected(self, *, thread_id: UUID, actor, connection_id: str):
        return await self.publish_presence(
            thread_id=thread_id,
            actor=actor,
            status="offline",
            connection_id=connection_id,
        )

    async def stream_thread_events(
        self,
        thread_id: UUID,
        *,
        after_sequence: int | None = None,
        follow: bool = True,
        viewer=None,
    ):
        if str(thread_id) not in self.threads:
            raise KeyError(f"Thread {thread_id} not found")
        sequence_floor = after_sequence or 0
        for event in self.events.get(str(thread_id), []):
            if (event.sequence or 0) > sequence_floor and self._event_visible(event, viewer):
                yield event
        if not follow:
            return
        queue: asyncio.Queue = asyncio.Queue()
        self.subscriptions.setdefault(str(thread_id), set()).add(queue)
        try:
            while True:
                event = await queue.get()
                if self._event_visible(event, viewer):
                    yield event
        finally:
            self.subscriptions[str(thread_id)].discard(queue)

    async def touch_presence(self, *, thread_id: UUID, actor, connection_id: str | None = None, status: str = "active"):
        return None

    async def _fan_out(self, thread_id: UUID, event) -> None:
        for queue in list(self.subscriptions.get(str(thread_id), set())):
            await queue.put(event)

    @staticmethod
    def _event_visible(event, viewer) -> bool:
        if viewer is None:
            return True
        if event.visibility in {"public", "workspace"}:
            return True
        if event.visibility == "agents_only":
            return viewer.participant_type == "agent"
        if event.visibility == "private":
            return event.actor.id == viewer.participant_id or (
                event.target.type == "participant"
                and event.target.id == viewer.participant_id
            )
        return False


@pytest.fixture
def mock_collaboration_service():
    return MockCollaborationService()


@pytest.fixture
def patched(monkeypatch, mock_collaboration_service):
    monkeypatch.setattr("gateway_edge.services.collaboration.collaboration_service", mock_collaboration_service)
    monkeypatch.setattr("gateway_edge.routers.collaboration.collab_svc.collaboration_service", mock_collaboration_service)
    monkeypatch.setattr("gateway_edge.db.postgres.setup_postgres", AsyncMock())
    monkeypatch.setattr("gateway_edge.db.postgres.teardown_postgres", AsyncMock())
    monkeypatch.setattr("gateway_edge.services.session.setup_valkey", AsyncMock())
    monkeypatch.setattr("gateway_edge.services.session.teardown_valkey", AsyncMock())
    monkeypatch.setattr("gateway_edge.services.events.event_service.start", AsyncMock())
    monkeypatch.setattr("gateway_edge.services.events.event_service.stop", AsyncMock())
    return mock_collaboration_service


@pytest_asyncio.fixture
async def client(patched) -> AsyncIterator[AsyncClient]:
    from gateway_edge.main import create_app

    app = create_app()
    app.router.lifespan_context = _null_lifespan
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
def sync_client(patched):
    from starlette.testclient import TestClient
    from gateway_edge.main import create_app

    app = create_app()
    app.router.lifespan_context = _null_lifespan
    with TestClient(app) as tc:
        yield tc


@pytest.fixture
def actor_payload() -> dict[str, str]:
    return {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Nikolay",
    }
