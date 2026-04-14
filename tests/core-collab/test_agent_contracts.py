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
    ArtifactRef,
    CreateLlmProviderRequest,
    CreateWorkspaceRequest,
    CreateSystemToolRequest,
    EventEnvelope,
    ExecutionSpec,
    DeleteLlmProviderRequest,
    LlmProviderDefinition,
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderRecord,
    ParticipantProfile,
    Run,
    RunStep,
    ToolCall,
    ToolCallResult,
    SystemToolDefinition,
    ToolExecutionBinding,
    CreateSystemAgentRequest,
    ParticipantInput,
    Task,
    Thread,
    TimelineMessage,
    UpdateLlmProviderRequest,
    Workspace,
    WorkspaceTool,
)
from core_collab.kernel import CollaborationKernel  # noqa: E402
from core_collab.repository import CollaborationRepository  # noqa: E402


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
        self.recorded_events: list[EventEnvelope] = []
        self._tasks = {}
        self._runs = {}
        self._workspaces = {}
        self._threads = {}
        self._participants = {}
        self._memory_entries = {}
        self._messages = {}
        self._system_tools = {}
        self._llm_providers = {}
        self._workspace_sequences = {}
        now = datetime.now(timezone.utc)
        postgres_provider = MemoryProviderDefinition(
            provider_id=uuid4(),
            provider_key="postgres",
            display_name="Postgres",
            description="Canonical memory provider",
            provider="postgres",
            enabled=True,
            config={},
            secret_config={},
            created_by=uuid4(),
            created_at=now,
            updated_by=uuid4(),
            updated_at=now,
            metadata={},
        )
        self._memory_providers = {postgres_provider.provider_id: postgres_provider}
        self._memory_provider_records = {}
        self._workspace_tools = {}
        self._tool_calls = {}

    async def setup_schema(self) -> None:
        self.setup_schema_calls += 1

    async def list_system_agents(self) -> list[AgentDefinition]:
        return list(self._agents.values())

    async def list_system_agents_referencing_llm_engine(self, engine_id: str) -> list[AgentDefinition]:
        referenced: list[AgentDefinition] = []
        for agent in self._agents.values():
            if agent.endpoint.engine_id == engine_id:
                referenced.append(agent)
                continue
            runtime = agent.definition.get("runtime")
            if not isinstance(runtime, dict):
                continue
            if runtime.get("engine_id") == engine_id:
                referenced.append(agent)
                continue
            preferred_engine_ids = runtime.get("preferred_engine_ids")
            if isinstance(preferred_engine_ids, list) and engine_id in preferred_engine_ids:
                referenced.append(agent)
        return referenced

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

    async def list_workspaces(self):
        return list(self._workspaces.values())

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

    async def fetch_user_participant(self, workspace_id, user_id):
        for participant in self._participants.values():
            if (
                participant.workspace_id == workspace_id
                and participant.participant_type == "user"
                and participant.user_id == user_id
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
        return await self.list_memory_entries_for_scope(
            scope="workspace",
            workspace_id=workspace_id,
            state="confirmed",
        )

    async def list_memory_entries_for_scope(
        self,
        *,
        scope,
        workspace_id=None,
        thread_id=None,
        run_id=None,
        state=None,
    ):
        entries = [
            entry
            for workspace_entries in self._memory_entries.values()
            for entry in workspace_entries
            if entry.scope == scope
            and (workspace_id is None or entry.workspace_id == workspace_id)
            and (thread_id is None or entry.thread_id == thread_id)
            and (run_id is None or entry.run_id == run_id)
            and (state is None or entry.state == state)
        ]
        return sorted(entries, key=lambda item: item.updated_at, reverse=True)

    async def search_memory_entries(
        self,
        *,
        scope,
        workspace_id=None,
        thread_id=None,
        run_id=None,
        query,
        limit,
        state=None,
    ):
        lowered = query.lower()
        entries = await self.list_memory_entries_for_scope(
            scope=scope,
            workspace_id=workspace_id,
            thread_id=thread_id,
            run_id=run_id,
            state=state,
        )
        return [
            entry
            for entry in entries
            if lowered in entry.content.lower()
            or lowered in (entry.summary or "").lower()
            or lowered in entry.entry_type.lower()
        ][:limit]

    async def fetch_memory_entry(self, memory_entry_id):
        for workspace_entries in self._memory_entries.values():
            for entry in workspace_entries:
                if entry.memory_entry_id == memory_entry_id:
                    return entry
        return None

    async def upsert_memory_entry(self, conn, entry: MemoryEntry) -> None:
        workspace_entries = self._memory_entries.setdefault(entry.workspace_id, [])
        for index, existing in enumerate(workspace_entries):
            if existing.memory_entry_id == entry.memory_entry_id:
                workspace_entries[index] = entry
                break
        else:
            workspace_entries.append(entry)

    async def list_system_tools(self):
        return list(self._system_tools.values())

    async def fetch_system_tool(self, tool_id):
        return self._system_tools.get(tool_id)

    async def upsert_system_tool(self, conn, tool: SystemToolDefinition) -> None:
        self._system_tools[tool.tool_id] = tool

    async def list_llm_providers(self):
        return list(self._llm_providers.values())

    async def fetch_llm_provider(self, provider_id):
        return self._llm_providers.get(provider_id)

    async def list_memory_providers(self):
        return list(self._memory_providers.values())

    async def list_enabled_memory_providers(self):
        return [provider for provider in self._memory_providers.values() if provider.enabled]

    async def fetch_memory_provider(self, provider_id):
        return self._memory_providers.get(provider_id)

    async def fetch_memory_provider_by_key(self, provider_key):
        for provider in self._memory_providers.values():
            if provider.provider_key == provider_key:
                return provider
        return None

    async def upsert_memory_provider(self, conn, provider: MemoryProviderDefinition) -> None:
        self._memory_providers[provider.provider_id] = provider

    async def delete_memory_provider(self, conn, *, provider_id):
        return self._memory_providers.pop(provider_id, None) is not None

    async def list_memory_provider_records(self, memory_entry_id):
        return [
            record
            for (entry_id, _provider_id), record in self._memory_provider_records.items()
            if entry_id == memory_entry_id
        ]

    async def fetch_memory_provider_record(self, *, memory_entry_id, provider_id):
        return self._memory_provider_records.get((memory_entry_id, provider_id))

    async def upsert_memory_provider_record(self, conn, record: MemoryProviderRecord) -> None:
        self._memory_provider_records[(record.memory_entry_id, record.provider_id)] = record

    async def list_workspace_tools(self, workspace_id):
        return list(self._workspace_tools.get(workspace_id, []))

    async def fetch_workspace_tool(self, workspace_id, tool_id):
        for tool in self._workspace_tools.get(workspace_id, []):
            if tool.tool_id == tool_id:
                return tool
        return None

    async def list_timeline_messages(self, thread_id):
        return list(self._messages.get(thread_id, []))

    async def fetch_message(self, message_id):
        for messages in self._messages.values():
            for message in messages:
                if message.message_id == message_id:
                    return message
        return None

    async def list_completed_tool_calls_for_run(self, run_id):
        return [
            tool_call
            for tool_call in self._tool_calls.get(run_id, [])
            if tool_call.status in {"completed", "failed"}
        ]

    async def upsert_workspace(self, conn, workspace: Workspace) -> None:
        self._workspaces[workspace.workspace_id] = workspace

    async def upsert_user(self, conn, user) -> None:
        return None

    async def upsert_participant(self, conn, participant: ParticipantProfile) -> None:
        self._participants[(participant.workspace_id, participant.participant_id)] = participant

    async def next_workspace_sequence(self, conn, workspace_id):
        next_value = self._workspace_sequences.get(workspace_id, 0) + 1
        self._workspace_sequences[workspace_id] = next_value
        return next_value

    async def record_event(self, conn, event: EventEnvelope) -> None:
        self.recorded_events.append(event)

    async def upsert_llm_provider(self, conn, provider: LlmProviderDefinition) -> None:
        self._llm_providers[provider.provider_id] = provider

    async def delete_llm_provider(self, conn, *, provider_id):
        return self._llm_providers.pop(provider_id, None) is not None


def _actor() -> ParticipantInput:
    return ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        display_name="Nikolay",
    )


@pytest.mark.asyncio
async def test_kernel_participant_profile_preserves_distinct_user_id():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    workspace_id = uuid4()
    user_id = uuid4()
    participant_id = uuid4()

    participant = kernel._participant_profile(  # noqa: SLF001
        workspace_id=workspace_id,
        actor=ParticipantInput(
            participant_id=participant_id,
            participant_type="user",
            user_id=user_id,
            display_name="Nikolay",
        ),
        now=datetime.now(timezone.utc),
    )

    assert participant.participant_id == participant_id
    assert participant.user_id == user_id


@pytest.mark.asyncio
async def test_kernel_create_workspace_sets_owner_admin_role_and_default_role_catalog():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    user_id = uuid4()
    participant_id = uuid4()

    result = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Ownership",
            description="Workspace ownership coverage",
            actor=ParticipantInput(
                participant_id=participant_id,
                participant_type="user",
                user_id=user_id,
                display_name="Nikolay",
            ),
        )
    )

    assert result.workspace is not None
    assert result.workspace.owner_user_id == user_id
    assert result.detail is not None
    assert result.detail.participants[0].roles == ["admin"]
    role_names = [role.name for role in result.detail.role_definitions]
    assert role_names == ["admin", "supervisor", "user"]
    assert repository.recorded_events[0].payload["owner_user_id"] == str(user_id)


@pytest.mark.asyncio
async def test_kernel_resolve_authenticated_user_actor_reuses_workspace_participant():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    workspace_id = uuid4()
    user_id = uuid4()
    participant_id = uuid4()
    repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=user_id,
        display_name="Nikolay",
    )

    actor = await kernel.resolve_authenticated_user_actor(
        workspace_id,
        user_id=user_id,
        display_name="Nikolay",
    )

    assert actor.user_id == user_id
    assert actor.participant_id == participant_id


@pytest.mark.asyncio
async def test_kernel_can_create_list_update_and_delete_llm_provider():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    actor = _actor()

    created = await kernel.create_llm_provider(
        CreateLlmProviderRequest(
            actor=actor,
            engine_id="anthropic-sonnet",
            display_name="Anthropic Sonnet",
            description="Reasoning-focused cloud provider.",
            provider="anthropic",
            endpoint_kind="remote",
            url="https://api.anthropic.example/v1/messages",
            default_model="claude-sonnet-4-5",
            capabilities=["chat", "reasoning"],
            locality="cloud",
            priority=180,
            enabled=True,
            secret_config={"env": {"name": "ANTHROPIC_API_KEY"}},
            metadata={"protocol": "anthropic-messages"},
        )
    )

    assert created.provider is not None
    provider_id = created.provider.provider_id

    listed = await kernel.list_llm_providers()
    assert [item.engine_id for item in listed] == ["anthropic-sonnet"]

    updated = await kernel.update_llm_provider(
        provider_id,
        UpdateLlmProviderRequest(
            actor=actor,
            display_name="Anthropic Sonnet Updated",
            priority=240,
            enabled=False,
            capabilities=[],
            metadata={"owner": "platform"},
        ),
    )

    assert updated.provider is not None
    assert updated.provider.display_name == "Anthropic Sonnet Updated"
    assert updated.provider.priority == 240
    assert updated.provider.enabled is False
    assert updated.provider.capabilities == []
    assert updated.provider.metadata == {
        "protocol": "anthropic-messages",
        "owner": "platform",
    }

    deleted = await kernel.delete_llm_provider(
        provider_id,
        DeleteLlmProviderRequest(actor=actor),
    )

    assert deleted == {"deleted": True, "provider_id": str(provider_id)}
    assert await kernel.list_llm_providers() == []


@pytest.mark.asyncio
async def test_kernel_prevents_disabling_or_deleting_referenced_llm_provider():
    now = datetime.now(timezone.utc)
    repository = FakeRepository(
        agents=[
            AgentDefinition(
                agent_id=uuid4(),
                display_name="Planner Agent",
                description="Plans work using a managed engine.",
                role="planner",
                capabilities=["planning"],
                endpoint=AgentEndpoint(kind="remote", engine_id="openai-responses"),
                system_prompt="Plan carefully.",
                created_by=uuid4(),
                created_at=now,
                updated_at=now,
            )
        ]
    )
    kernel = CollaborationKernel(repository)
    actor = _actor()
    created = await kernel.create_llm_provider(
        CreateLlmProviderRequest(
            actor=actor,
            engine_id="openai-responses",
            display_name="OpenAI Responses",
            description="Cloud responses endpoint.",
            provider="openai",
            endpoint_kind="remote",
            url="https://api.openai.com/v1/responses",
            default_model="gpt-5.4-mini",
        )
    )
    provider_id = created.provider.provider_id

    with pytest.raises(ValueError, match="Cannot disable LLM provider"):
        await kernel.update_llm_provider(
            provider_id,
            UpdateLlmProviderRequest(
                actor=actor,
                enabled=False,
            ),
        )

    with pytest.raises(ValueError, match="Cannot rename LLM provider engine_id"):
        await kernel.update_llm_provider(
            provider_id,
            UpdateLlmProviderRequest(
                actor=actor,
                engine_id="openai-responses-v2",
            ),
        )

    with pytest.raises(ValueError, match="Cannot delete LLM provider"):
        await kernel.delete_llm_provider(
            provider_id,
            DeleteLlmProviderRequest(actor=actor),
        )


@pytest.mark.asyncio
async def test_kernel_detects_runtime_preferred_engine_id_references_for_llm_provider():
    now = datetime.now(timezone.utc)
    repository = FakeRepository(
        agents=[
            AgentDefinition(
                agent_id=uuid4(),
                display_name="Research Agent",
                description="Uses preferred engine ids for selection.",
                role="researcher",
                capabilities=["research"],
                endpoint=AgentEndpoint(kind="remote"),
                system_prompt="Research carefully.",
                definition={"runtime": {"preferred_engine_ids": ["anthropic-sonnet"]}},
                created_by=uuid4(),
                created_at=now,
                updated_at=now,
            )
        ]
    )
    kernel = CollaborationKernel(repository)
    actor = _actor()
    created = await kernel.create_llm_provider(
        CreateLlmProviderRequest(
            actor=actor,
            engine_id="anthropic-sonnet",
            display_name="Anthropic Sonnet",
            description="Reasoning cloud provider.",
            provider="anthropic",
            endpoint_kind="remote",
            url="https://api.anthropic.example/v1/messages",
            default_model="claude-sonnet-4-5",
        )
    )

    with pytest.raises(ValueError, match="Research Agent"):
        await kernel.delete_llm_provider(
            created.provider.provider_id,
            DeleteLlmProviderRequest(actor=actor),
        )


def test_participant_from_row_falls_back_when_user_display_name_is_missing():
    participant_id = uuid4()
    workspace_id = uuid4()
    row = {
        "participant_id": participant_id,
        "workspace_id": workspace_id,
        "participant_type": "user",
        "user_id": uuid4(),
        "system_agent_id": None,
        "description": None,
        "roles": [],
        "capabilities": [],
        "status": "active",
        "visibility_scope": "workspace",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "metadata": {},
        "user_display_name": None,
        "agent_display_name": None,
        "agent_description": None,
        "agent_role": None,
        "agent_capabilities": [],
        "agent_endpoint": None,
        "agent_system_prompt": None,
        "agent_definition": None,
    }

    participant = CollaborationRepository._participant_from_row(row)  # noqa: SLF001

    assert participant.display_name == str(participant_id)


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
async def test_kernel_create_system_tool_rejects_read_write_workspace_access_for_untrusted_tool():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    with pytest.raises(ValueError, match="read_write workspace access requires trust_level='trusted'"):
        await kernel.create_system_tool(
            CreateSystemToolRequest(
                actor=_actor(),
                name="repo_write",
                description="Writes into a mounted workspace.",
                execution=ToolExecutionBinding(
                    backend_kind="docker",
                    handler_ref="repo_write",
                    execution_profile={"workspace_access": "read_write"},
                    trust_level="sandboxed",
                ),
            )
        )


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
            ],
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
    tool_id = uuid4()
    repository._system_tools[tool_id] = SystemToolDefinition(
        tool_id=tool_id,
        name="repo_search",
        description="Search the current workspace source tree.",
        parameter_contract={
            "parameters": [
                {
                    "name": "query",
                    "type": "string",
                    "description": "Search text to look up in the repository.",
                    "required": True,
                }
            ],
            "additional_properties": False,
        },
        input_schema={"type": "object"},
        created_by=actor_id,
        created_at=now,
        updated_by=actor_id,
        updated_at=now,
    )
    repository._workspace_tools[workspace_id] = [
        WorkspaceTool(
            tool_id=tool_id,
            name="repo_search",
            description="Search the current workspace source tree.",
            parameter_contract={
                "parameters": [
                    {
                        "name": "query",
                        "type": "string",
                        "description": "Search text to look up in the repository.",
                        "required": True,
                    }
                ],
                "additional_properties": False,
            },
            input_schema={"type": "object"},
            enabled=True,
            attached_by=actor_id,
            attached_at=now,
            updated_at=now,
        )
    ]
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
    repository._tool_calls[run_id] = [
        ToolCall(
            tool_call_id=uuid4(),
            run_id=run_id,
            run_step_id=uuid4(),
            task_id=task_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            system_agent_id=system_agent_id,
            tool_id=tool_id,
            tool_name="repo_search",
            status="completed",
            arguments={"query": "migrations"},
            execution_spec=ExecutionSpec(
                invocation_id=uuid4(),
                handler_ref="repo_search",
                inline_payload={"query": "migrations"},
            ).model_dump(mode="json"),
            result=ToolCallResult(
                output_payload={"matches": ["db/migrations/20260411000100_initial_schema.sql"]},
                stdout_ref=ArtifactRef(
                    name="stdout",
                    uri="/tmp/stdout.txt",
                    content_type="text/plain",
                ),
            ),
            created_at=now,
            updated_at=now,
        )
    ]
    repository._memory_entries[workspace_id] = [
        MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            entry_type="note",
            content="Visible to the whole workspace.",
            summary="Workspace note",
            created_by=actor_id,
            updated_by=actor_id,
            visibility="workspace",
            created_at=now,
            updated_at=now,
        ),
        MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            entry_type="note",
            content="Visible to agents.",
            summary="Agents note",
            created_by=actor_id,
            updated_by=actor_id,
            visibility="agents_only",
            created_at=now,
            updated_at=now,
        ),
        MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            entry_type="note",
            content="Should not leak to the agent.",
            summary="User private note",
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
    assert [entry.summary for entry in context.workspace_memory] == [
        "Workspace note",
        "Agents note",
    ]
    assert context.run_memory == []
    assert context.thread_memory == []
    assert context.trigger_message is not None
    assert context.trigger_message.content == "Validate the rollout carefully"
    assert context.thread_reply_contract == agent.interaction_contract
    assert context.role_definitions[0].name == "testing agent"
    assert context.workspace_tools[0].name == "repo_search"
    assert context.workspace_tools[0].parameter_contract.parameters[0].name == "query"
    assert "tool:repo_search" in context.participant.capabilities
    assert "tool:repo_search" in context.participants[0].capabilities
    assert context.tool_results[0].result is not None
    assert context.tool_results[0].result.output_payload["matches"][0].endswith("initial_schema.sql")


@pytest.mark.asyncio
async def test_build_agent_execution_context_does_not_advertise_disabled_workspace_tools():
    actor_id = uuid4()
    workspace_id = uuid4()
    thread_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
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
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Visibility",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
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
    repository._tasks[task_id] = Task(
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Validate rollout",
        requested_by=actor_id,
        correlation_id=uuid4(),
        created_at=now,
        updated_at=now,
        metadata={"target_system_agent_id": str(system_agent_id)},
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
    repository._workspace_tools[workspace_id] = [
        WorkspaceTool(
            tool_id=uuid4(),
            name="repo_search",
            description="Search the current workspace source tree.",
            parameter_contract={
                "parameters": [
                    {
                        "name": "query",
                        "type": "string",
                        "description": "Search text to look up in the repository.",
                        "required": True,
                    }
                ],
                "additional_properties": False,
            },
            input_schema={"type": "object"},
            enabled=False,
            attached_by=actor_id,
            attached_at=now,
            updated_at=now,
        )
    ]

    kernel = CollaborationKernel(repository)
    context = await kernel.build_agent_execution_context(task_id, system_agent_id, run_id)

    assert context.workspace_tools[0].enabled is False
    assert "tool:repo_search" not in context.participant.capabilities


@pytest.mark.asyncio
async def test_build_requeued_execution_events_emits_run_step_and_tool_call_wakeups():
    actor_id = uuid4()
    workspace_id = uuid4()
    thread_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    now = datetime.now(timezone.utc)

    repository = FakeRepository()
    repository._tasks[task_id] = Task(
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Run worker",
        requested_by=actor_id,
        correlation_id=uuid4(),
        created_at=now,
        updated_at=now,
        metadata={"target_system_agent_id": str(system_agent_id)},
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
    repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Testing Agent",
        roles=["testing agent"],
        capabilities=["tests"],
        created_at=now,
        updated_at=now,
    )
    kernel = CollaborationKernel(repository)
    run_step = RunStep(
        step_id=uuid4(),
        run_id=run_id,
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        system_agent_id=system_agent_id,
        step_index=1,
        status="created",
        created_at=now,
        updated_at=now,
    )
    tool_call = ToolCall(
        tool_call_id=uuid4(),
        run_id=run_id,
        run_step_id=run_step.step_id,
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        system_agent_id=system_agent_id,
        tool_id=uuid4(),
        tool_name="repo_search",
        status="created",
        created_at=now,
        updated_at=now,
    )

    events = await kernel.build_requeued_execution_events([run_step], [tool_call])

    assert [event.event_type for event in events] == [
        "run_step.requeued",
        "tool_call.requeued",
    ]
    assert all(event.visibility == "agents_only" for event in events)
    assert all(event.correlation_id == repository._runs[run_id].correlation_id for event in events)
    assert events[0].target.type == "run_step"
    assert events[1].target.type == "tool_call"
