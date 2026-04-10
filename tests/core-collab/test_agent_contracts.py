from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest

_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
for path in (_CONTRACTS_DIR, _CORE_COLLAB_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_contracts.agent_contracts import (  # noqa: E402
    build_default_interaction_contract,
    interaction_contract_is_empty,
)
from open_talon_contracts.models import (  # noqa: E402
    ActorRef,
    AgentDefinition,
    AgentEndpoint,
    MemoryEntry,
    ParticipantProfile,
    Run,
    CreateSystemAgentRequest,
    ParticipantInput,
    Task,
    Thread,
    TimelineMessage,
    Workspace,
)
from core_collab.kernel import CollaborationKernel  # noqa: E402


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def transaction(self):
        return _FakeTransaction()


class _FakeAcquire:
    async def __aenter__(self):
        return _FakeConnection()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def acquire(self):
        return _FakeAcquire()


class FakeRepository:
    def __init__(self, agents: list[AgentDefinition] | None = None) -> None:
        self._agents = {agent.agent_id: agent for agent in agents or []}
        self._pool = _FakePool()
        self.setup_schema_calls = 0
        self.upserted_agents: list[AgentDefinition] = []
        self._tasks = {}
        self._runs = {}
        self._workspaces = {}
        self._threads = {}
        self._participants = {}
        self._memory_entries = {}
        self._messages = {}

    async def setup_schema(self) -> None:
        self.setup_schema_calls += 1

    async def list_system_agents(self) -> list[AgentDefinition]:
        return list(self._agents.values())

    async def upsert_system_agent(self, conn, agent: AgentDefinition) -> None:
        self._agents[agent.agent_id] = agent
        self.upserted_agents.append(agent)

    async def fetch_system_agent(self, agent_id):
        return self._agents.get(agent_id)

    async def fetch_task(self, task_id):
        return self._tasks.get(task_id)

    async def fetch_run(self, run_id):
        return self._runs.get(run_id)

    async def fetch_workspace(self, workspace_id):
        return self._workspaces.get(workspace_id)

    async def fetch_thread(self, thread_id):
        return self._threads.get(thread_id)

    async def fetch_participant(self, workspace_id, participant_id):
        return self._participants.get((workspace_id, participant_id))

    async def fetch_agent_participant(self, workspace_id, system_agent_id):
        for participant in self._participants.values():
            if (
                participant.workspace_id == workspace_id
                and participant.participant_type == "agent"
                and participant.system_agent_id == system_agent_id
            ):
                return participant
        return None

    async def list_participants(self, workspace_id):
        return [
            participant
            for participant in self._participants.values()
            if participant.workspace_id == workspace_id
        ]

    async def list_memory_entries(self, workspace_id):
        return list(self._memory_entries.get(workspace_id, []))

    async def list_timeline_messages(self, thread_id):
        return list(self._messages.get(thread_id, []))

    async def fetch_message(self, message_id):
        for messages in self._messages.values():
            for message in messages:
                if message.message_id == message_id:
                    return message
        return None


def _actor() -> ParticipantInput:
    return ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        display_name="Nikolay",
    )


def test_build_default_interaction_contract_reflects_testing_role():
    contract = build_default_interaction_contract(
        display_name="Testing Agent",
        role="testing agent",
        description="Validates changes and reports regressions.",
        capabilities=["tests", "validation"],
    )

    assert contract.response_contract.title == "Testing Agent Response"
    assert contract.response_contract.required_sections == [
        "Summary",
        "Checks performed",
        "Findings",
        "Residual risk",
        "Next action",
    ]
    assert contract.instructions
    assert not interaction_contract_is_empty(contract)


def test_build_default_interaction_contract_reflects_implementation_role():
    contract = build_default_interaction_contract(
        display_name="Builder Agent",
        role="implementation agent",
        description="Implements collaboration kernel changes safely.",
        capabilities=["coding", "backend", "validation"],
    )

    assert contract.response_contract.title == "Implementation Agent Response"
    assert contract.response_contract.required_sections == [
        "Summary",
        "Proposed change",
        "Validation",
        "Residual risk",
        "Next action",
    ]
    assert "Call out residual implementation risk honestly." in contract.response_contract.guidance


@pytest.mark.asyncio
async def test_kernel_create_system_agent_fills_missing_interaction_contract():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    result = await kernel.create_system_agent(
        CreateSystemAgentRequest(
            actor=_actor(),
            display_name="Testing Agent",
            description="Validates changes and reports regressions.",
            role="testing agent",
            capabilities=["tests", "validation"],
            endpoint=AgentEndpoint(kind="local", model="gemma4:latest"),
            system_prompt="You are a careful testing agent.",
        )
    )

    assert result.agent is not None
    assert not interaction_contract_is_empty(result.agent.interaction_contract)
    assert result.agent.interaction_contract.response_contract.required_sections


@pytest.mark.asyncio
async def test_kernel_setup_schema_backfills_existing_agents_without_contracts():
    stale_agent = AgentDefinition(
        agent_id=uuid4(),
        display_name="Legacy Agent",
        description="Older agent definition without explicit contract.",
        role="research agent",
        capabilities=["analysis"],
        endpoint=AgentEndpoint(kind="remote", url="https://example.invalid", model="gpt-5.4"),
        system_prompt="You are a research agent.",
        created_by=uuid4(),
    )
    repository = FakeRepository([stale_agent])
    kernel = CollaborationKernel(repository)

    await kernel.setup_schema()

    assert repository.setup_schema_calls == 1
    assert len(repository.upserted_agents) == 1
    backfilled = repository.upserted_agents[0]
    assert backfilled.agent_id == stale_agent.agent_id
    assert not interaction_contract_is_empty(backfilled.interaction_contract)
    assert backfilled.interaction_contract.response_contract.required_sections == [
        "Summary",
        "Evidence",
        "Open questions",
        "Next action",
    ]


@pytest.mark.asyncio
async def test_build_agent_execution_context_filters_messages_and_memory_by_viewer_and_sequence():
    actor_id = uuid4()
    workspace_id = uuid4()
    thread_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    trigger_message_id = uuid4()
    now = datetime.now(timezone.utc)

    agent = AgentDefinition(
        agent_id=system_agent_id,
        display_name="Testing Agent",
        description="Validates changes with only the allowed workspace context.",
        role="testing agent",
        capabilities=["tests", "validation"],
        endpoint=AgentEndpoint(kind="local", model="gemma4:latest"),
        system_prompt="You are a careful testing agent.",
        interaction_contract=build_default_interaction_contract(
            display_name="Testing Agent",
            role="testing agent",
            description="Validates changes with only the allowed workspace context.",
            capabilities=["tests", "validation"],
        ),
        created_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    repository = FakeRepository([agent])
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Kernel",
        description="Collaboration kernel",
        created_at=now,
        updated_at=now,
        metadata={
            "role_definitions": [
                {
                    "name": "testing agent",
                    "definition": "Validates changes and reports regressions.",
                    "updated_by": str(actor_id),
                    "updated_at": now.isoformat(),
                }
            ]
        },
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Visibility",
        created_at=now,
        updated_at=now,
    )
    agent_participant = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Testing Agent",
        description="Validates changes with only the allowed workspace context.",
        roles=["testing agent"],
        capabilities=["tests", "validation"],
        status="active",
        visibility_scope="workspace",
        created_at=now,
        updated_at=now,
    )
    user_participant = ParticipantProfile(
        participant_id=actor_id,
        workspace_id=workspace_id,
        participant_type="user",
        display_name="Nikolay",
        description="Coordinates the rollout.",
        roles=["release lead"],
        capabilities=["planning"],
        status="active",
        visibility_scope="workspace",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, participant_id)] = agent_participant
    repository._participants[(workspace_id, actor_id)] = user_participant
    repository._tasks[task_id] = Task(
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Validate rollout",
        description="Review the visible rollout context.",
        requested_by=actor_id,
        correlation_id=uuid4(),
        causation_id=trigger_message_id,
        created_at=now,
        updated_at=now,
        metadata={
            "target_system_agent_id": str(system_agent_id),
            "target_participant_id": str(participant_id),
            "trigger_message_id": str(trigger_message_id),
            "sequence_ceiling": 3,
            "response_visibility": "workspace",
            "routing_reason": "workspace_attached_agent",
        },
    )
    repository._runs[run_id] = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        task_id=task_id,
        participant_id=participant_id,
        status="started",
        correlation_id=repository._tasks[task_id].correlation_id,
        causation_id=task_id,
        created_at=now,
        updated_at=now,
    )
    repository._memory_entries[workspace_id] = [
        MemoryEntry(
            memory_entry_id=uuid4(),
            workspace_id=workspace_id,
            entry_type="note",
            title="Workspace note",
            content="Visible to the whole workspace.",
            created_by=actor_id,
            updated_by=actor_id,
            visibility="workspace",
            created_at=now,
            updated_at=now,
        ),
        MemoryEntry(
            memory_entry_id=uuid4(),
            workspace_id=workspace_id,
            entry_type="note",
            title="Agents note",
            content="Visible to agents.",
            created_by=actor_id,
            updated_by=actor_id,
            visibility="agents_only",
            created_at=now,
            updated_at=now,
        ),
        MemoryEntry(
            memory_entry_id=uuid4(),
            workspace_id=workspace_id,
            entry_type="note",
            title="User private note",
            content="Should not leak to the agent.",
            created_by=actor_id,
            updated_by=actor_id,
            visibility="private",
            created_at=now,
            updated_at=now,
        ),
    ]
    repository._messages[thread_id] = [
        TimelineMessage(
            message_id=uuid4(),
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=actor_id),
            visibility="workspace",
            content="Visible workspace request",
            sequence=1,
            correlation_id=uuid4(),
            created_at=now,
            updated_at=now,
        ),
        TimelineMessage(
            message_id=uuid4(),
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=actor_id),
            visibility="agents_only",
            content="Visible agent coordination note",
            sequence=2,
            correlation_id=uuid4(),
            created_at=now,
            updated_at=now,
        ),
        TimelineMessage(
            message_id=trigger_message_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=actor_id),
            visibility="workspace",
            content="Validate the rollout carefully",
            sequence=3,
            correlation_id=repository._tasks[task_id].correlation_id,
            created_at=now,
            updated_at=now,
        ),
        TimelineMessage(
            message_id=uuid4(),
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=actor_id),
            visibility="workspace",
            content="Too late for this run",
            sequence=4,
            correlation_id=uuid4(),
            created_at=now,
            updated_at=now,
        ),
        TimelineMessage(
            message_id=uuid4(),
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=actor_id),
            visibility="private",
            content="Private user note",
            sequence=2,
            correlation_id=uuid4(),
            created_at=now,
            updated_at=now,
        ),
    ]

    kernel = CollaborationKernel(repository)
    context = await kernel.build_agent_execution_context(task_id, system_agent_id, run_id)

    assert context.sequence_ceiling == 3
    assert [message.content for message in context.messages] == [
        "Visible workspace request",
        "Visible agent coordination note",
        "Validate the rollout carefully",
    ]
    assert [entry.title for entry in context.memory_entries] == [
        "Workspace note",
        "Agents note",
    ]
    assert context.trigger_message is not None
    assert context.trigger_message.content == "Validate the rollout carefully"
    assert context.thread_reply_contract == agent.interaction_contract
    assert context.role_definitions[0].name == "testing agent"
