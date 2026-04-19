from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
_WORKSPACE_MEMORY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/workspace-memory")
)
for path in (_CONTRACTS_DIR, _CORE_COLLAB_DIR, _WORKSPACE_MEMORY_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_contracts.agent_contracts import (  # noqa: E402
    build_default_interaction_contract,
    interaction_contract_is_empty,
)
from open_talon_contracts.log_management import (  # noqa: E402
    RotationPolicy,
    append_jsonl_with_rotation,
)
from open_talon_contracts.models import (  # noqa: E402
    ActorRef,
    AgentDefinition,
    AgentEndpoint,
    AgentRunResult,
    AssumeParticipantRoleRequest,
    ArtifactRef,
    CreateAgentParticipantRequest,
    CreateGitRepositoryRequest,
    CreateThreadRequest,
    CreateLlmProviderRequest,
    CreateWorkspaceRequest,
    CreateSystemToolRequest,
    EventEnvelope,
    ExecutionSpec,
    CompletionRule,
    CreateInteractionAnswerRequest,
    CreateInteractionQuestionRequest,
    CreateInteractionRequest,
    CreateInteractionRequestsRequest,
    CreateMessageRequest,
    DeleteLlmProviderRequest,
    InteractionAnswer,
    InteractionQuestion,
    InteractionQuestionDraft,
    InteractionRequest,
    InteractionRequestDetail,
    InteractionRequestDraft,
    InteractionRequestTarget,
    LlmProviderDefinition,
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderRecord,
    ParticipantProfile,
    Run,
    RunStep,
    TargetRef,
    ToolCall,
    ToolCallResult,
    SystemToolDefinition,
    ToolExecutionBinding,
    CreateSystemAgentRequest,
    ParticipantInput,
    Task,
    Thread,
    TimelineMessage,
    UpdateInteractionRequestRequest,
    UpdateLlmProviderRequest,
    UpsertRoleDefinitionRequest,
    Workspace,
    WorkspaceCommunicationLogEntry,
    WorkspaceCommunicationLogPage,
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
    def __init__(
        self,
        agents: list[AgentDefinition] | None = None,
        *,
        communication_log_dir: str | Path | None = None,
    ) -> None:
        self._agents = {agent.agent_id: agent for agent in agents or []}
        self._pool = _FakePool()
        self._communication_log_dir = (
            Path(communication_log_dir) if communication_log_dir is not None else None
        )
        self._communication_log_policy = RotationPolicy.from_env(
            max_bytes_var="OPEN_TALON_COMMUNICATION_LOG_MAX_BYTES",
            backup_count_var="OPEN_TALON_COMMUNICATION_LOG_BACKUP_COUNT",
            default_max_bytes=20 * 1024 * 1024,
            default_backup_count=10,
        )
        self.setup_schema_calls = 0
        self.upserted_agents: list[AgentDefinition] = []
        self.recorded_events: list[EventEnvelope] = []
        self._tasks = {}
        self._runs = {}
        self._run_steps = {}
        self._workspaces = {}
        self._threads = {}
        self._participants = {}
        self._memory_entries = {}
        self._messages = {}
        self._system_tools = {}
        self._llm_providers = {}
        self._git_repositories = {}
        self._workspace_sequences = {}
        self._thread_sequences = {}
        self._runtime_queue_stats = {}
        self._global_token_total = 0
        self._workspace_token_totals = {}
        self._memberships = {}
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
        self._interaction_requests = {}
        self._interaction_questions = {}
        self._interaction_targets = {}
        self._interaction_answers = {}

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

    async def upsert_task(self, conn, task):
        self._tasks[task.task_id] = task

    async def list_pending_tasks_for_system_agent(self, system_agent_id, *, limit=10):
        tasks = [
            task
            for task in self._tasks.values()
            if task.status in {"created", "released"}
            and task.metadata.get("target_system_agent_id") == str(system_agent_id)
        ]
        tasks.sort(key=lambda item: item.created_at)
        return tasks[:limit]

    async def claim_task(self, conn, *, task_id, participant_id, updated_at):
        task = self._tasks.get(task_id)
        if task is None or task.status not in {"created", "released"}:
            return None
        claimed = task.model_copy(
            update={
                "status": "claimed",
                "claimed_by": participant_id,
                "updated_at": updated_at,
            }
        )
        self._tasks[task_id] = claimed
        return claimed

    async def fetch_run(self, run_id):
        return self._runs.get(run_id)

    async def fetch_run_step(self, step_id):
        return self._run_steps.get(step_id)

    async def fetch_workspace(self, workspace_id):
        return self._workspaces.get(workspace_id)

    async def list_workspaces(self):
        return list(self._workspaces.values())

    async def list_workspaces_for_user(self, user_id):
        visible = []
        for workspace in self._workspaces.values():
            for participant in self._participants.values():
                if participant.workspace_id == workspace.workspace_id and participant.user_id == user_id:
                    visible.append(workspace)
                    break
        return visible

    async def fetch_thread(self, thread_id):
        return self._threads.get(thread_id)

    async def list_memberships(self, thread_id):
        return list(self._memberships.get(thread_id, []))

    async def fetch_active_membership(self, conn, *, thread_id, participant_id):
        for membership in self._memberships.get(thread_id, []):
            if membership.participant_id == participant_id and membership.left_at is None:
                return membership
        return None

    async def upsert_membership(self, conn, membership):
        memberships = [
            existing
            for existing in self._memberships.get(membership.thread_id, [])
            if existing.membership_id != membership.membership_id
        ]
        memberships.append(membership)
        self._memberships[membership.thread_id] = memberships

    async def fetch_interaction_request(self, request_id):
        return self._interaction_requests.get(request_id)

    async def list_interaction_requests_for_thread(self, thread_id):
        return [
            request
            for request in self._interaction_requests.values()
            if request.thread_id == thread_id
        ]

    async def list_open_interaction_requests_for_run(self, requester_run_id):
        return [
            request
            for request in self._interaction_requests.values()
            if request.requester_run_id == requester_run_id and request.status == "open"
        ]

    async def list_interaction_request_questions(self, request_id):
        return sorted(
            self._interaction_questions.get(request_id, []),
            key=lambda item: item.order,
        )

    async def list_interaction_request_targets(self, request_id):
        return list(self._interaction_targets.get(request_id, []))

    async def fetch_interaction_request_target(self, target_id):
        for targets in self._interaction_targets.values():
            for target in targets:
                if target.target_id == target_id:
                    return target
        return None

    async def list_interaction_answers(self, request_id):
        return list(self._interaction_answers.get(request_id, []))

    async def get_interaction_request_detail(self, request_id):
        request = self._interaction_requests.get(request_id)
        if request is None:
            return None
        return InteractionRequestDetail(
            request=request,
            questions=await self.list_interaction_request_questions(request_id),
            targets=await self.list_interaction_request_targets(request_id),
            answers=await self.list_interaction_answers(request_id),
        )

    async def list_interaction_request_details_for_thread(self, thread_id):
        requests = await self.list_interaction_requests_for_thread(thread_id)
        return [
            InteractionRequestDetail(
                request=request,
                questions=await self.list_interaction_request_questions(request.request_id),
                targets=await self.list_interaction_request_targets(request.request_id),
                answers=await self.list_interaction_answers(request.request_id),
            )
            for request in requests
        ]

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

    async def upsert_workspace_tool(self, conn, *, workspace_id, tool):
        tools = [
            existing
            for existing in self._workspace_tools.get(workspace_id, [])
            if existing.tool_id != tool.tool_id
        ]
        tools.append(tool)
        self._workspace_tools[workspace_id] = tools

    async def upsert_git_repository(self, conn, repository) -> None:
        self._git_repositories[repository.repo_id] = repository

    async def list_timeline_messages(self, thread_id):
        return list(self._messages.get(thread_id, []))

    async def fetch_message(self, message_id):
        for messages in self._messages.values():
            for message in messages:
                if message.message_id == message_id:
                    return message
        return None

    async def list_workspace_communication_log(
        self,
        workspace_id,
        *,
        thread_id=None,
        limit=200,
        offset=0,
    ):
        entries: list[WorkspaceCommunicationLogEntry] = []
        for candidate_thread_id, messages in self._messages.items():
            thread = self._threads.get(candidate_thread_id)
            if thread is None or thread.workspace_id != workspace_id:
                continue
            if thread_id is not None and candidate_thread_id != thread_id:
                continue
            for message in messages:
                actor_display_name = str(message.actor.id)
                participant = self._participants.get((workspace_id, message.actor.id))
                if participant is not None:
                    actor_display_name = participant.display_name
                metadata = dict(message.metadata)
                if metadata.get("interaction_request_id") and "interaction_question_ids" in metadata:
                    kind = "interaction_answer"
                elif metadata.get("interaction_request_id"):
                    kind = "interaction_request"
                else:
                    kind = "message"
                entries.append(
                    WorkspaceCommunicationLogEntry(
                        message_id=message.message_id,
                        workspace_id=message.workspace_id,
                        thread_id=message.thread_id,
                        thread_title=thread.title,
                        actor=message.actor,
                        actor_display_name=actor_display_name,
                        visibility=message.visibility,
                        kind=kind,
                        content=message.content,
                        status=message.status,
                        correlation_id=message.correlation_id,
                        causation_id=message.causation_id,
                        sequence=message.sequence,
                        interaction_request_id=metadata.get("interaction_request_id"),
                        interaction_request_status=metadata.get("interaction_request_status"),
                        interaction_question_ids=metadata.get("interaction_question_ids", []),
                        metadata=metadata,
                        created_at=message.created_at,
                        updated_at=message.updated_at,
                    )
                )
        entries.sort(key=lambda item: (item.created_at, item.sequence, item.message_id), reverse=True)
        return WorkspaceCommunicationLogPage(
            workspace_id=workspace_id,
            entries=entries[offset : offset + limit],
            total_count=len(entries),
        )

    async def upsert_message(self, conn, message):
        messages = [
            existing
            for existing in self._messages.get(message.thread_id, [])
            if existing.message_id != message.message_id
        ]
        messages.append(message)
        self._messages[message.thread_id] = messages

    async def persist_workspace_communication_messages(self, messages):
        if self._communication_log_dir is None:
            return
        grouped_lines: dict[Path, list[str]] = {}
        for message in messages:
            if message.status in {"draft", "streaming"}:
                continue
            thread = self._threads.get(message.thread_id)
            if thread is None:
                continue
            participant = self._participants.get((message.workspace_id, message.actor.id))
            actor_display_name = (
                participant.display_name if participant is not None else str(message.actor.id)
            )
            metadata = dict(message.metadata)
            if metadata.get("interaction_request_id") and "interaction_question_ids" in metadata:
                kind = "interaction_answer"
            elif metadata.get("interaction_request_id"):
                kind = "interaction_request"
            else:
                kind = "message"
            entry = WorkspaceCommunicationLogEntry(
                message_id=message.message_id,
                workspace_id=message.workspace_id,
                thread_id=message.thread_id,
                thread_title=thread.title,
                actor=message.actor,
                actor_display_name=actor_display_name,
                visibility=message.visibility,
                kind=kind,
                content=message.content,
                status=message.status,
                correlation_id=message.correlation_id,
                causation_id=message.causation_id,
                sequence=message.sequence,
                interaction_request_id=metadata.get("interaction_request_id"),
                interaction_request_status=metadata.get("interaction_request_status"),
                interaction_question_ids=metadata.get("interaction_question_ids", []),
                metadata=metadata,
                created_at=message.created_at,
                updated_at=message.updated_at,
            )
            file_path = self._communication_log_dir / f"{message.workspace_id}.jsonl"
            grouped_lines.setdefault(file_path, []).append(
                json.dumps(entry.model_dump(mode="json"), sort_keys=True)
            )
        for file_path, lines in grouped_lines.items():
            append_jsonl_with_rotation(
                file_path,
                lines,
                policy=self._communication_log_policy,
            )

    async def upsert_interaction_request(self, conn, request):
        self._interaction_requests[request.request_id] = request

    async def upsert_interaction_request_question(self, conn, question):
        questions = [
            existing
            for existing in self._interaction_questions.get(question.request_id, [])
            if existing.question_id != question.question_id
        ]
        questions.append(question)
        self._interaction_questions[question.request_id] = questions

    async def upsert_interaction_request_target(self, conn, target):
        targets = [
            existing
            for existing in self._interaction_targets.get(target.request_id, [])
            if existing.target_id != target.target_id
        ]
        targets.append(target)
        self._interaction_targets[target.request_id] = targets

    async def upsert_interaction_answer(self, conn, answer):
        answers = [
            existing
            for existing in self._interaction_answers.get(answer.request_id, [])
            if existing.answer_id != answer.answer_id
        ]
        answers.append(answer)
        self._interaction_answers[answer.request_id] = answers

    async def fetch_tool_call(self, tool_call_id):
        for tool_calls in self._tool_calls.values():
            for tool_call in tool_calls:
                if tool_call.tool_call_id == tool_call_id:
                    return tool_call
        return None

    async def list_completed_tool_calls_for_run(self, run_id):
        return [
            tool_call
            for tool_call in self._tool_calls.get(run_id, [])
            if tool_call.status in {"completed", "failed"}
        ]

    async def list_expired_run_steps(self, *, now):
        return [
            step
            for step in self._run_steps.values()
            if step.status == "claimed"
            and step.lease_expires_at is not None
            and step.lease_expires_at <= now
            and (step.next_retry_at is None or step.next_retry_at <= now)
        ]

    async def list_expired_tool_calls(self, *, now):
        expired = []
        for tool_calls in self._tool_calls.values():
            for tool_call in tool_calls:
                if (
                    tool_call.status == "claimed"
                    and tool_call.lease_expires_at is not None
                    and tool_call.lease_expires_at <= now
                    and (
                        tool_call.next_retry_at is None
                        or tool_call.next_retry_at <= now
                    )
                ):
                    expired.append(tool_call)
        return expired

    async def upsert_workspace(self, conn, workspace: Workspace) -> None:
        self._workspaces[workspace.workspace_id] = workspace

    async def upsert_thread(self, conn, thread: Thread) -> None:
        self._threads[thread.thread_id] = thread

    async def upsert_user(self, conn, user) -> None:
        return None

    async def upsert_participant(self, conn, participant: ParticipantProfile) -> None:
        self._participants[(participant.workspace_id, participant.participant_id)] = participant

    async def upsert_run(self, conn, run: Run) -> None:
        self._runs[run.run_id] = run

    async def upsert_run_step(self, conn, step: RunStep) -> None:
        self._run_steps[step.step_id] = step

    async def upsert_tool_call(self, conn, tool_call: ToolCall) -> None:
        tool_calls = [
            existing
            for existing in self._tool_calls.get(tool_call.run_id, [])
            if existing.tool_call_id != tool_call.tool_call_id
        ]
        tool_calls.append(tool_call)
        self._tool_calls[tool_call.run_id] = tool_calls

    async def next_workspace_sequence(self, conn, workspace_id):
        next_value = self._workspace_sequences.get(workspace_id, 0) + 1
        self._workspace_sequences[workspace_id] = next_value
        return next_value

    async def next_thread_sequence(self, conn, thread_id):
        next_value = self._thread_sequences.get(thread_id, 0) + 1
        self._thread_sequences[thread_id] = next_value
        return next_value

    async def record_event(self, conn, event: EventEnvelope) -> None:
        self.recorded_events.append(event)

    async def upsert_llm_provider(self, conn, provider: LlmProviderDefinition) -> None:
        self._llm_providers[provider.provider_id] = provider

    async def delete_llm_provider(self, conn, *, provider_id):
        return self._llm_providers.pop(provider_id, None) is not None

    async def get_runtime_queue_stats(self, *, now, since):
        return self._runtime_queue_stats

    async def get_global_token_total(self, *, day_start, day_end):
        return self._global_token_total

    async def get_workspace_token_total(self, *, workspace_id, day_start, day_end):
        return self._workspace_token_totals.get(workspace_id, 0)

    async def list_workspace_token_totals(self, *, day_start, day_end):
        return [
            {"workspace_id": workspace_id, "total_tokens": total_tokens}
            for workspace_id, total_tokens in self._workspace_token_totals.items()
        ]


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
async def test_kernel_list_workspaces_filters_by_user_membership():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    first_user_id = uuid4()
    second_user_id = uuid4()

    first = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Visible",
            actor=ParticipantInput(
                participant_id=uuid4(),
                participant_type="user",
                user_id=first_user_id,
                display_name="First",
            ),
        )
    )
    second = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Hidden",
            actor=ParticipantInput(
                participant_id=uuid4(),
                participant_type="user",
                user_id=second_user_id,
                display_name="Second",
            ),
        )
    )

    visible = await kernel.list_workspaces(user_id=first_user_id)

    assert [workspace.workspace_id for workspace in visible] == [first.workspace.workspace_id]
    assert second.workspace is not None
    assert second.workspace.workspace_id not in {workspace.workspace_id for workspace in visible}


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


def test_workspace_communication_log_entry_from_row_classifies_interaction_answer():
    request_id = uuid4()
    question_id = uuid4()
    row = {
        "message_id": uuid4(),
        "workspace_id": uuid4(),
        "thread_id": uuid4(),
        "thread_title": "Coordination",
        "actor_type": "user",
        "actor_id": uuid4(),
        "actor_display_name": "Alice",
        "visibility": "workspace",
        "content": "Backend is blocked on API review.",
        "status": "completed",
        "correlation_id": uuid4(),
        "causation_id": request_id,
        "sequence": 7,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "metadata": {
            "interaction_request_id": str(request_id),
            "interaction_question_ids": [str(question_id)],
        },
    }

    entry = CollaborationRepository._workspace_communication_log_entry_from_row(row)  # noqa: SLF001

    assert entry.kind == "interaction_answer"
    assert entry.actor_display_name == "Alice"
    assert entry.interaction_request_id == request_id
    assert entry.interaction_question_ids == [question_id]


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
async def test_kernel_create_system_tool_rejects_full_network_for_untrusted_tool():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    with pytest.raises(ValueError, match="network=full requires trust_level='trusted'"):
        await kernel.create_system_tool(
            CreateSystemToolRequest(
                actor=_actor(),
                name="repo_sync",
                description="Downloads remote content.",
                execution=ToolExecutionBinding(
                    backend_kind="docker",
                    handler_ref="repo_sync",
                    execution_profile={"network": "full"},
                    trust_level="sandboxed",
                ),
            )
        )


@pytest.mark.asyncio
async def test_kernel_create_system_tool_rejects_local_process_for_untrusted_tool():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    with pytest.raises(ValueError, match="local_process execution requires trust_level='trusted'"):
        await kernel.create_system_tool(
            CreateSystemToolRequest(
                actor=_actor(),
                name="repo_scan",
                description="Scans the local process workspace.",
                execution=ToolExecutionBinding(
                    backend_kind="local_process",
                    handler_ref="repo_scan",
                    trust_level="sandboxed",
                ),
            )
        )


@pytest.mark.asyncio
async def test_kernel_workspace_management_requires_admin_or_supervisor_role():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    owner_user_id = uuid4()
    member_user_id = uuid4()
    created = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Guarded",
            actor=ParticipantInput(
                participant_id=uuid4(),
                participant_type="user",
                user_id=owner_user_id,
                display_name="Owner",
            ),
        )
    )
    assert created.workspace is not None
    workspace_id = created.workspace.workspace_id
    member_participant_id = uuid4()
    repository._participants[(workspace_id, member_participant_id)] = ParticipantProfile(
        participant_id=member_participant_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=member_user_id,
        display_name="Member",
        roles=["user"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(PermissionError, match="Workspace admin or supervisor role required"):
        await kernel.upsert_role_definition(
            workspace_id,
            UpsertRoleDefinitionRequest(
                actor=ParticipantInput(
                    participant_id=member_participant_id,
                    participant_type="user",
                    user_id=member_user_id,
                    display_name="Member",
                ),
                name="qa",
                definition="Reviews release candidates.",
            ),
        )

    with pytest.raises(PermissionError, match="Workspace admin or supervisor role required"):
        await kernel.create_git_repository(
            scope="workspace",
            workspace_id=workspace_id,
            payload=CreateGitRepositoryRequest(
                actor=ParticipantInput(
                    participant_id=member_participant_id,
                    participant_type="user",
                    user_id=member_user_id,
                    display_name="Member",
                ),
                name="workspace-defs",
                local_path="/tmp/workspace-defs",
            ),
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


def test_kernel_run_output_includes_standardized_usage_payload():
    payload = CollaborationKernel._run_output_from_result(  # noqa: SLF001
        AgentRunResult(
            stop_reason="completed",
            message="Done",
            metadata={
                "usage": {
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "prompt_tokens": 21,
                    "completion_tokens": 9,
                    "total_tokens": 30,
                }
            },
        )
    )

    assert payload["usage"] == {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "prompt_tokens": 21,
        "completion_tokens": 9,
        "total_tokens": 30,
    }


@pytest.mark.asyncio
async def test_kernel_enforce_run_step_token_budget_uses_workspace_metadata_override():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    workspace_id = uuid4()
    step = RunStep(
        step_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        workspace_id=workspace_id,
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        status="claimed",
        claimed_by_worker="agent-loop-worker",
    )
    repository._run_steps[step.step_id] = step
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Budgeted",
        metadata={"limits": {"daily_token_cap": 10}},
    )
    repository._global_token_total = 5
    repository._workspace_token_totals[workspace_id] = 10
    budget_failure = object()
    kernel.fail_run_step = AsyncMock(return_value=budget_failure)  # type: ignore[method-assign]

    result = await kernel.enforce_run_step_token_budget(
        step_id=step.step_id,
        worker_id="agent-loop-worker",
        global_daily_token_cap=100,
        default_workspace_daily_token_cap=50,
    )

    assert result is budget_failure
    kernel.fail_run_step.assert_awaited_once()  # type: ignore[attr-defined]
    args = kernel.fail_run_step.await_args.args  # type: ignore[attr-defined]
    kwargs = kernel.fail_run_step.await_args.kwargs  # type: ignore[attr-defined]
    assert args[:2] == (step.step_id, "agent-loop-worker")
    assert "Workspace daily token cap exceeded (10/10)" in args[2]
    assert kwargs == {"stop_reason": "budget_exhausted"}


@pytest.mark.asyncio
async def test_kernel_requeue_expired_run_step_applies_retry_backoff():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    step = RunStep(
        step_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        status="claimed",
        claimed_by_worker="agent-loop-worker",
        lease_expires_at=now,
        last_heartbeat_at=now,
        attempt_count=2,
    )

    requeued = await kernel._requeue_expired_run_step(step, now=now)  # noqa: SLF001

    assert requeued.status == "created"
    assert requeued.claimed_by_worker is None
    assert requeued.lease_expires_at is None
    assert requeued.last_heartbeat_at is None
    assert requeued.next_retry_at == now + timedelta(seconds=120)
    assert requeued.error == "Run step lease expired; retry 3 scheduled"
    assert await repository.fetch_run_step(step.step_id) == requeued


@pytest.mark.asyncio
async def test_kernel_fail_expired_tool_call_fails_waiting_step_and_run():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    step_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    tool_call_id = uuid4()
    correlation_id = uuid4()
    error = "Tool call lease expired after 3 attempts"

    task = Task(
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Reconcile execution",
        description="Validate expired tool-call handling.",
        requested_by=uuid4(),
        status="claimed",
        claimed_by=participant_id,
        correlation_id=correlation_id,
        metadata={
            "target_system_agent_id": str(system_agent_id),
            "target_participant_id": str(participant_id),
            "response_visibility": "workspace",
        },
        created_at=now,
        updated_at=now,
    )
    run = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        task_id=task_id,
        participant_id=participant_id,
        status="started",
        correlation_id=correlation_id,
        causation_id=task_id,
        created_at=now,
        updated_at=now,
    )
    step = RunStep(
        step_id=step_id,
        run_id=run_id,
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        system_agent_id=system_agent_id,
        status="waiting_tools",
        created_at=now,
        updated_at=now,
    )
    tool_call = ToolCall(
        tool_call_id=tool_call_id,
        run_id=run_id,
        run_step_id=step_id,
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        system_agent_id=system_agent_id,
        tool_id=uuid4(),
        tool_name="repo_search",
        status="claimed",
        execution_spec=ExecutionSpec(
            invocation_id=uuid4(),
            handler_ref="repo_search",
        ).model_dump(mode="json"),
        claimed_by_worker="tool-worker",
        attempt_count=3,
        lease_expires_at=now,
        last_heartbeat_at=now,
        created_at=now,
        updated_at=now,
    )
    repository._tasks[task_id] = task
    repository._runs[run_id] = run
    repository._run_steps[step_id] = step
    repository._tool_calls[run_id] = [tool_call]

    participant = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Testing Agent",
        roles=["testing agent"],
        created_at=now,
        updated_at=now,
    )
    failure_event = EventEnvelope(
        event_type="run.failed",
        workspace_id=workspace_id,
        thread_id=thread_id,
        actor=ActorRef(type="agent", id=participant_id),
        target=TargetRef(type="run", id=run_id),
        visibility="agents_only",
    )
    tool_event = EventEnvelope(
        event_type="tool_call.failed",
        workspace_id=workspace_id,
        thread_id=thread_id,
        actor=ActorRef(type="agent", id=participant_id),
        target=TargetRef(type="tool_call", id=tool_call_id),
        visibility="agents_only",
    )
    kernel._require_run_participant = AsyncMock(return_value=participant)  # type: ignore[method-assign]
    kernel._build_thread_event = AsyncMock(return_value=tool_event)  # type: ignore[method-assign]
    kernel.fail_run = AsyncMock(return_value=type("Failure", (), {"events": [failure_event]})())  # type: ignore[method-assign]

    result = await kernel._fail_expired_tool_call(tool_call, error=error)  # noqa: SLF001

    updated_step = await repository.fetch_run_step(step_id)
    updated_tool_call = await repository.fetch_tool_call(tool_call_id)
    assert updated_step is not None
    assert updated_step.status == "failed"
    assert updated_step.error == error
    assert updated_tool_call is not None
    assert updated_tool_call.status == "failed"
    assert updated_tool_call.error == error
    assert updated_tool_call.result is not None
    assert updated_tool_call.result.error == error
    assert updated_tool_call.next_retry_at is None
    kernel.fail_run.assert_awaited_once_with(  # type: ignore[attr-defined]
        run_id,
        system_agent_id,
        error,
        stop_reason="tool_failure",
    )
    assert result.events == [tool_event, failure_event]


@pytest.mark.asyncio
async def test_kernel_reconcile_expired_execution_leases_routes_requeues_and_terminal_failures():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    kernel._now = lambda: now  # type: ignore[method-assign]
    requeue_step = RunStep(
        step_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        status="claimed",
        attempt_count=1,
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    fail_step = RunStep(
        step_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        status="claimed",
        attempt_count=3,
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    requeue_tool = ToolCall(
        tool_call_id=uuid4(),
        run_id=uuid4(),
        run_step_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        tool_id=uuid4(),
        tool_name="repo_search",
        status="claimed",
        execution_spec=ExecutionSpec(invocation_id=uuid4(), handler_ref="repo_search").model_dump(mode="json"),
        attempt_count=1,
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    fail_tool = ToolCall(
        tool_call_id=uuid4(),
        run_id=uuid4(),
        run_step_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        tool_id=uuid4(),
        tool_name="repo_search",
        status="claimed",
        execution_spec=ExecutionSpec(invocation_id=uuid4(), handler_ref="repo_search").model_dump(mode="json"),
        attempt_count=3,
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    repository._run_steps[requeue_step.step_id] = requeue_step
    repository._run_steps[fail_step.step_id] = fail_step
    repository._tool_calls[requeue_tool.run_id] = [requeue_tool]
    repository._tool_calls[fail_tool.run_id] = [fail_tool]

    expected_step = requeue_step.model_copy(update={"status": "created"})
    expected_tool = requeue_tool.model_copy(update={"status": "created"})
    step_failure_event = EventEnvelope(
        event_type="run.failed",
        workspace_id=fail_step.workspace_id,
        thread_id=fail_step.thread_id,
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="run", id=fail_step.run_id),
        visibility="agents_only",
    )
    tool_failure_event = EventEnvelope(
        event_type="tool_call.failed",
        workspace_id=fail_tool.workspace_id,
        thread_id=fail_tool.thread_id,
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="tool_call", id=fail_tool.tool_call_id),
        visibility="agents_only",
    )
    kernel._requeue_expired_run_step = AsyncMock(return_value=expected_step)  # type: ignore[method-assign]
    kernel._fail_expired_run_step = AsyncMock(  # type: ignore[method-assign]
        return_value=type("Failure", (), {"events": [step_failure_event]})()
    )
    kernel._requeue_expired_tool_call = AsyncMock(return_value=expected_tool)  # type: ignore[method-assign]
    kernel._fail_expired_tool_call = AsyncMock(  # type: ignore[method-assign]
        return_value=type("Failure", (), {"events": [tool_failure_event]})()
    )

    result = await kernel.reconcile_expired_execution_leases()

    assert result.run_steps == [expected_step]
    assert result.tool_calls == [expected_tool]
    assert result.events == [step_failure_event, tool_failure_event]
    kernel._requeue_expired_run_step.assert_awaited_once_with(requeue_step, now=now)  # type: ignore[attr-defined]
    kernel._fail_expired_run_step.assert_awaited_once()  # type: ignore[attr-defined]
    kernel._requeue_expired_tool_call.assert_awaited_once_with(requeue_tool, now=now)  # type: ignore[attr-defined]
    kernel._fail_expired_tool_call.assert_awaited_once()  # type: ignore[attr-defined]


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


@pytest.mark.asyncio
async def test_kernel_create_interaction_request_resolves_capability_targets_and_renders_message():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    requester_id = uuid4()
    user_one_id = uuid4()
    user_two_id = uuid4()
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Questions",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Coordination",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, requester_id)] = ParticipantProfile(
        participant_id=requester_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=uuid4(),
        display_name="Research Agent",
        roles=["research"],
        capabilities=["analysis"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, user_one_id)] = ParticipantProfile(
        participant_id=user_one_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=uuid4(),
        display_name="Alice",
        roles=["reviewer"],
        capabilities=["frontend"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, user_two_id)] = ParticipantProfile(
        participant_id=user_two_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=uuid4(),
        display_name="Bob",
        roles=["reviewer"],
        capabilities=["backend"],
        status="active",
        created_at=now,
        updated_at=now,
    )

    result = await kernel.create_interaction_requests(
        thread_id,
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=requester_id,
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need implementation feedback",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="What blocks backend delivery?"),
                    ],
                    selectors=[{"type": "capability", "value": "backend"}],
                    completion_rule=CompletionRule(mode="all_targets"),
                )
            ],
        ),
    )

    assert len(result.details) == 1
    detail = result.details[0]
    assert detail.targets[0].participant_id == user_two_id
    assert result.messages[0].metadata["interaction_request_id"] == str(detail.request.request_id)
    assert "What blocks backend delivery?" in result.messages[0].content


def _seed_interaction_workspace(
    repository: FakeRepository,
    *,
    users: list[tuple[str, str]],
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    requester_id = uuid4()
    requester_system_agent_id = uuid4()
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Questions",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Coordination",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, requester_id)] = ParticipantProfile(
        participant_id=requester_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=requester_system_agent_id,
        display_name="Research Agent",
        roles=["research"],
        capabilities=["analysis"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    user_ids: dict[str, UUID] = {}
    for display_name, capability in users:
        participant_id = uuid4()
        repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
            participant_id=participant_id,
            workspace_id=workspace_id,
            participant_type="user",
            user_id=uuid4(),
            display_name=display_name,
            roles=["reviewer"],
            capabilities=[capability],
            status="active",
            created_at=now,
            updated_at=now,
        )
        user_ids[display_name] = participant_id
    return {
        "workspace_id": workspace_id,
        "thread_id": thread_id,
        "requester_id": requester_id,
        "requester_system_agent_id": requester_system_agent_id,
        "users": user_ids,
    }


async def _claim_single_pending_task(
    kernel: CollaborationKernel,
    system_agent_id,
):
    tasks = await kernel.list_pending_tasks_for_system_agent(system_agent_id)
    assert len(tasks) == 1
    return await kernel.claim_task_for_system_agent(tasks[0].task_id, system_agent_id)


@pytest.mark.asyncio
async def test_answer_interaction_request_minimum_answers_waits_for_quorum():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[
            ("Alice", "frontend"),
            ("Bob", "backend"),
            ("Carol", "qa"),
        ],
    )

    create_result = await kernel.create_interaction_requests(
        seeded["thread_id"],
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need two viewpoints",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="What is your blocker?"),
                    ],
                    target_participant_ids=list(seeded["users"].values()),
                    completion_rule=CompletionRule(mode="minimum_answers", minimum_answers=2),
                )
            ],
        ),
    )
    request_id = create_result.details[0].request.request_id

    first_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Alice"],
                participant_type="user",
                display_name="Alice",
            ),
            content="Frontend is blocked on design review.",
        ),
    )
    assert first_answer.detail.request.status == "open"
    assert first_answer.resumed_task is None

    second_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Bob"],
                participant_type="user",
                display_name="Bob",
            ),
            content="Backend is blocked on API pagination.",
        ),
    )

    assert second_answer.detail.request.status == "completed"
    assert second_answer.resumed_task is not None
    assert second_answer.detail.request.metadata["aggregate"]["answered_count"] == 2
    pending_targets = [
        target
        for target in second_answer.detail.targets
        if target.status == "pending"
    ]
    assert len(pending_targets) == 1
    assert pending_targets[0].participant_id == seeded["users"]["Carol"]


@pytest.mark.asyncio
async def test_answer_interaction_request_one_per_selector_bucket_tracks_bucket_coverage():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[
            ("Alice", "frontend"),
            ("Bob", "backend"),
        ],
    )

    create_result = await kernel.create_interaction_requests(
        seeded["thread_id"],
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need frontend and backend feedback",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="What blocks your area?"),
                    ],
                    selectors=[
                        {"type": "capability", "value": "frontend"},
                        {"type": "capability", "value": "backend"},
                    ],
                    completion_rule=CompletionRule(mode="one_per_selector_bucket"),
                )
            ],
        ),
    )
    request_id = create_result.details[0].request.request_id

    first_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Alice"],
                participant_type="user",
                display_name="Alice",
            ),
            content="Frontend is blocked on responsive QA.",
        ),
    )
    assert first_answer.detail.request.status == "open"
    assert set(first_answer.detail.request.metadata["aggregate"]["covered_selector_buckets"]) == {
        "capability:frontend",
    }

    second_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Bob"],
                participant_type="user",
                display_name="Bob",
            ),
            content="Backend is blocked on API review.",
        ),
    )

    assert second_answer.detail.request.status == "completed"
    assert set(second_answer.detail.request.metadata["aggregate"]["covered_selector_buckets"]) == {
        "capability:frontend",
        "capability:backend",
    }


@pytest.mark.asyncio
async def test_dismiss_interaction_target_reduces_all_targets_quorum():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[
            ("Alice", "frontend"),
            ("Bob", "backend"),
        ],
    )

    create_result = await kernel.create_interaction_requests(
        seeded["thread_id"],
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need both viewpoints",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="What blocks delivery?"),
                    ],
                    target_participant_ids=list(seeded["users"].values()),
                    completion_rule=CompletionRule(mode="all_targets"),
                )
            ],
        ),
    )
    request_id = create_result.details[0].request.request_id

    answer_result = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Alice"],
                participant_type="user",
                display_name="Alice",
            ),
            content="Frontend is blocked on approvals.",
        ),
    )
    assert answer_result.detail.request.status == "open"

    bob_target = next(
        target
        for target in answer_result.detail.targets
        if target.participant_id == seeded["users"]["Bob"]
    )
    dismiss_result = await kernel.update_interaction_request(
        request_id,
        UpdateInteractionRequestRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            action="dismiss_target",
            target_id=bob_target.target_id,
        ),
    )

    assert dismiss_result.detail.request.status == "completed"
    assert dismiss_result.resumed_task is not None
    assert dismiss_result.detail.request.metadata["aggregate"]["target_count"] == 1
    dismissed_target = next(
        target
        for target in dismiss_result.detail.targets
        if target.target_id == bob_target.target_id
    )
    assert dismissed_target.status == "dismissed"


@pytest.mark.asyncio
async def test_answer_interaction_request_completes_and_requeues_requesting_agent():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    requester_id = uuid4()
    requester_system_agent_id = uuid4()
    user_one_id = uuid4()
    user_two_id = uuid4()
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Questions",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Coordination",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, requester_id)] = ParticipantProfile(
        participant_id=requester_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=requester_system_agent_id,
        display_name="Research Agent",
        roles=["research"],
        capabilities=["analysis"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    for participant_id, display_name, capability in (
        (user_one_id, "Alice", "frontend"),
        (user_two_id, "Bob", "backend"),
    ):
        repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
            participant_id=participant_id,
            workspace_id=workspace_id,
            participant_type="user",
            user_id=uuid4(),
            display_name=display_name,
            roles=["reviewer"],
            capabilities=[capability],
            status="active",
            created_at=now,
            updated_at=now,
        )

    create_result = await kernel.create_interaction_requests(
        thread_id,
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=requester_id,
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need both perspectives",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="Frontend concerns?"),
                        CreateInteractionQuestionRequest(prompt="Backend concerns?"),
                    ],
                    target_participant_ids=[user_one_id, user_two_id],
                    completion_rule=CompletionRule(mode="all_targets"),
                )
            ],
        ),
    )
    request_id = create_result.details[0].request.request_id

    first_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=user_one_id,
                participant_type="user",
                display_name="Alice",
            ),
            content="Frontend is blocked on responsive states.",
        ),
    )
    assert first_answer.detail.request.status == "open"

    second_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=user_two_id,
                participant_type="user",
                display_name="Bob",
            ),
            content="Backend needs API pagination.",
        ),
    )

    assert second_answer.detail.request.status == "completed"
    assert second_answer.resumed_task is not None
    assert second_answer.resumed_task.metadata["routing_reason"] == "interaction_request_completed"
    assert second_answer.resumed_task.metadata["target_system_agent_id"] == str(requester_system_agent_id)


@pytest.mark.asyncio
async def test_post_message_can_atomically_create_interaction_request():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[("Alice", "backend")],
    )

    result = await kernel.post_message(
        seeded["thread_id"],
        CreateMessageRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            content="Please coordinate feedback.",
            visibility="workspace",
            create_task=False,
            requests=[
                CreateInteractionRequest(
                    title="Need backend input",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="What blocks backend delivery?"),
                    ],
                    target_participant_ids=[seeded["users"]["Alice"]],
                )
            ],
        ),
    )

    assert result.message.content == "Please coordinate feedback."
    assert len(repository._messages[seeded["thread_id"]]) == 2
    details = await kernel.list_interaction_requests(seeded["thread_id"])
    assert len(details) == 1
    assert details[0].request.requester_message_id == result.message.message_id
    assert details[0].questions[0].prompt == "What blocks backend delivery?"


@pytest.mark.asyncio
async def test_kernel_lists_workspace_communication_log_entries():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[("Alice", "backend")],
    )

    await kernel.post_message(
        seeded["thread_id"],
        CreateMessageRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            content="Please gather blockers.",
            visibility="workspace",
            create_task=False,
        ),
    )
    create_result = await kernel.create_interaction_requests(
        seeded["thread_id"],
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need backend input",
                    questions=[CreateInteractionQuestionRequest(prompt="What blocks backend delivery?")],
                    target_participant_ids=[seeded["users"]["Alice"]],
                )
            ],
        ),
    )
    await kernel.answer_interaction_request(
        create_result.details[0].request.request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Alice"],
                participant_type="user",
                display_name="Alice",
            ),
            content="API review is blocking backend delivery.",
        ),
    )

    page = await kernel.list_workspace_communication_log(
        seeded["workspace_id"],
        thread_id=seeded["thread_id"],
        limit=10,
        offset=0,
    )

    assert page.total_count == 3
    assert {entry.kind for entry in page.entries} == {
        "message",
        "interaction_request",
        "interaction_answer",
    }


@pytest.mark.asyncio
async def test_kernel_persists_workspace_communication_log_to_jsonl(tmp_path):
    repository = FakeRepository(communication_log_dir=tmp_path)
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[("Alice", "backend")],
    )

    await kernel.post_message(
        seeded["thread_id"],
        CreateMessageRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            content="Please gather blockers.",
            visibility="workspace",
            create_task=False,
        ),
    )
    create_result = await kernel.create_interaction_requests(
        seeded["thread_id"],
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need backend input",
                    questions=[CreateInteractionQuestionRequest(prompt="What blocks backend delivery?")],
                    target_participant_ids=[seeded["users"]["Alice"]],
                )
            ],
        ),
    )
    await kernel.answer_interaction_request(
        create_result.details[0].request.request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Alice"],
                participant_type="user",
                display_name="Alice",
            ),
            content="API review is blocking backend delivery.",
        ),
    )

    log_file = tmp_path / f"{seeded['workspace_id']}.jsonl"
    assert log_file.exists()
    entries = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert [entry["kind"] for entry in entries] == [
        "message",
        "interaction_request",
        "interaction_answer",
    ]
    assert entries[0]["thread_title"] == "Coordination"
    assert entries[0]["actor_display_name"] == "Research Agent"
    assert entries[2]["actor_display_name"] == "Alice"
    assert entries[2]["content"] == "API review is blocking backend delivery."


@pytest.mark.asyncio
async def test_kernel_rotates_workspace_communication_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TALON_COMMUNICATION_LOG_MAX_BYTES", "450")
    monkeypatch.setenv("OPEN_TALON_COMMUNICATION_LOG_BACKUP_COUNT", "2")
    repository = FakeRepository(communication_log_dir=tmp_path)
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[("Alice", "backend")],
    )

    for index in range(6):
        await kernel.post_message(
            seeded["thread_id"],
            CreateMessageRequest(
                actor=ParticipantInput(
                    participant_id=seeded["requester_id"],
                    participant_type="agent",
                    display_name="Research Agent",
                ),
                content=f"rotation-test-{index}-" + ("x" * 120),
                visibility="workspace",
                create_task=False,
            ),
        )

    log_file = tmp_path / f"{seeded['workspace_id']}.jsonl"
    rotated_file = tmp_path / f"{seeded['workspace_id']}.jsonl.1"

    assert log_file.exists()
    assert rotated_file.exists()

    latest_entries = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rotated_entries = [
        json.loads(line)
        for line in rotated_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert latest_entries[-1]["content"].startswith("rotation-test-5-")
    assert rotated_entries[0]["content"].startswith("rotation-test-")
