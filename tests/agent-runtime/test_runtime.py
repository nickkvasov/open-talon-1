from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

_AGENT_RUNTIME_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/agent-runtime")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
for path in (_AGENT_RUNTIME_DIR, _CONTRACTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from agent_runtime.runtime import AgentTaskRuntime, render_prompt
from open_talon_contracts.models import (
    ActorRef,
    AgentDefinition,
    AgentEndpoint,
    AgentExecutionContext,
    AgentInteractionContract,
    AgentRunResult,
    AgentResponseContract,
    AgentTaskRouting,
    EventEnvelope,
    MemoryEntry,
    ParticipantProfile,
    RoleDefinition,
    Run,
    TargetRef,
    Task,
    Thread,
    TimelineMessage,
    Workspace,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class FakeKernel:
    system_agent: AgentDefinition
    task: Task
    context: AgentExecutionContext
    claim_events: list[EventEnvelope]
    progress_events: list[EventEnvelope]
    completion_events: list[EventEnvelope]
    failure_events: list[EventEnvelope]

    def __post_init__(self) -> None:
        self.progress_calls: list[str] = []
        self.completed_results: list[AgentRunResult] = []
        self.failed_errors: list[str] = []
        self._claimed = False

    async def list_system_agents(self) -> list[AgentDefinition]:
        return [self.system_agent]

    async def list_pending_tasks_for_system_agent(
        self,
        system_agent_id: UUID,
        *,
        limit: int = 10,
    ) -> list[Task]:
        if self._claimed or system_agent_id != self.system_agent.agent_id:
            return []
        return [self.task]

    async def claim_task_for_system_agent(self, task_id: UUID, system_agent_id: UUID):
        assert task_id == self.task.task_id
        assert system_agent_id == self.system_agent.agent_id
        self._claimed = True
        return SimpleNamespace(
            run=self.context.run,
            context=self.context,
            events=self.claim_events,
        )

    async def append_run_progress(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        content: str,
    ):
        assert run_id == self.context.run.run_id
        assert system_agent_id == self.system_agent.agent_id
        self.progress_calls.append(content)
        return SimpleNamespace(events=self.progress_events)

    async def complete_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        result: AgentRunResult,
    ):
        assert run_id == self.context.run.run_id
        assert system_agent_id == self.system_agent.agent_id
        self.completed_results.append(result)
        return SimpleNamespace(events=self.completion_events)

    async def fail_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        error: str,
        *,
        stop_reason: str = "tool_failure",
    ):
        assert run_id == self.context.run.run_id
        assert system_agent_id == self.system_agent.agent_id
        self.failed_errors.append(error)
        return SimpleNamespace(events=self.failure_events)


def _build_fixture_context(*, endpoint_kind: str = "system"):
    workspace_id = uuid4()
    thread_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    user_id = uuid4()
    message_id = uuid4()
    now = _now()
    system_agent = AgentDefinition(
        agent_id=system_agent_id,
        display_name="Testing Agent",
        description="Validates changes and reports regressions.",
        role="testing agent",
        capabilities=["tests", "validation"],
        endpoint=AgentEndpoint(
            kind=endpoint_kind,
            url="http://127.0.0.1:11434/api/generate" if endpoint_kind == "local" else "https://example.invalid/agent",
            model="gemma4:latest",
        ),
        system_prompt="You are a careful testing agent.",
        interaction_contract=AgentInteractionContract(
            instructions=[
                "Validate the latest request using only the provided context.",
                "Explain what was checked, what was found, and what should happen next.",
            ],
            response_contract=AgentResponseContract(
                format="markdown",
                title="Validation Summary",
                required_sections=[
                    "Summary",
                    "Checks performed",
                    "Findings",
                    "Residual risk",
                    "Next action",
                ],
                guidance=[
                    "Be concise and evidence-based.",
                    "If there is no direct execution evidence, say so clearly.",
                ],
            ),
            completion_criteria=[
                "Address the latest visible request.",
                "Call out residual risk honestly.",
            ],
        ),
        definition={"runtime": {"model": "gemma4:latest", "provider": "ollama"}},
        created_by=user_id,
        created_at=now,
        updated_at=now,
    )
    participant = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Testing Agent",
        description="Validates changes and reports regressions.",
        roles=["testing agent"],
        capabilities=["tests", "validation"],
        status="active",
        visibility_scope="workspace",
        created_at=now,
        updated_at=now,
        metadata={"system_agent_id": str(system_agent_id)},
    )
    task = Task(
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Reply as Testing Agent",
        description="Agent response requested for posted message.",
        requested_by=user_id,
        correlation_id=uuid4(),
        causation_id=message_id,
        created_at=now,
        updated_at=now,
        metadata={
            "target_system_agent_id": str(system_agent_id),
            "target_participant_id": str(participant_id),
            "trigger_message_id": str(message_id),
            "sequence_ceiling": 3,
            "response_visibility": "workspace",
            "routing_reason": "workspace_attached_agent",
        },
    )
    run = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        task_id=task_id,
        participant_id=participant_id,
        status="started",
        correlation_id=task.correlation_id,
        causation_id=task_id,
        created_at=now,
        updated_at=now,
        metadata={"system_agent_id": str(system_agent_id)},
    )
    context = AgentExecutionContext(
        workspace=Workspace(
            workspace_id=workspace_id,
            name="Engineering",
            description="Shared engineering workspace",
            created_at=now,
            updated_at=now,
        ),
        thread=Thread(
            thread_id=thread_id,
            workspace_id=workspace_id,
            title="Release prep",
            created_at=now,
            updated_at=now,
        ),
        task=task,
        run=run,
        routing=AgentTaskRouting(
            target_system_agent_id=system_agent_id,
            target_participant_id=participant_id,
            trigger_message_id=message_id,
            response_visibility="workspace",
            sequence_ceiling=3,
            routing_reason="workspace_attached_agent",
        ),
        system_agent=system_agent,
        participant=participant,
        participants=[
            ParticipantProfile(
                participant_id=user_id,
                workspace_id=workspace_id,
                participant_type="user",
                display_name="Nikolay",
                description="Coordinates releases.",
                roles=["release lead"],
                capabilities=["planning", "release"],
                status="active",
                visibility_scope="workspace",
                created_at=now,
                updated_at=now,
            ),
            participant,
        ],
        role_definitions=[
            RoleDefinition(
                name="testing agent",
                definition="Validates changes and reports regressions.",
                updated_by=user_id,
                updated_at=now,
            )
        ],
        messages=[
            TimelineMessage(
                message_id=uuid4(),
                workspace_id=workspace_id,
                thread_id=thread_id,
                actor=ActorRef(type="user", id=user_id),
                visibility="workspace",
                content="Please validate the release candidate before deploy.",
                sequence=2,
                correlation_id=uuid4(),
                created_at=now,
                updated_at=now,
            ),
            TimelineMessage(
                message_id=message_id,
                workspace_id=workspace_id,
                thread_id=thread_id,
                actor=ActorRef(type="user", id=user_id),
                visibility="workspace",
                content="Focus on migrations and regression risk.",
                sequence=3,
                correlation_id=task.correlation_id,
                created_at=now,
                updated_at=now,
            ),
        ],
        memory_entries=[
            MemoryEntry(
                memory_entry_id=uuid4(),
                workspace_id=workspace_id,
                entry_type="note",
                title="Release checklist",
                content="Run migrations in staging before production.",
                created_by=user_id,
                updated_by=user_id,
                visibility="workspace",
                created_at=now,
                updated_at=now,
            )
        ],
        trigger_message=TimelineMessage(
            message_id=message_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=user_id),
            visibility="workspace",
            content="Focus on migrations and regression risk.",
            sequence=3,
            correlation_id=task.correlation_id,
            created_at=now,
            updated_at=now,
        ),
        sequence_ceiling=3,
    )
    claim_events = [
        EventEnvelope(
            event_type="task.claimed",
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="agent", id=participant_id),
            target=TargetRef(type="task", id=task_id),
            visibility="agents_only",
            correlation_id=task.correlation_id,
            sequence=4,
            timestamp=now,
            payload={"task_id": str(task_id)},
        )
    ]
    progress_events = [
        EventEnvelope(
            event_type="run.progressed",
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="agent", id=participant_id),
            target=TargetRef(type="run", id=run_id),
            visibility="agents_only",
            correlation_id=task.correlation_id,
            sequence=5,
            timestamp=now,
            payload={"run_id": str(run_id), "content": "Executing"},
        )
    ]
    completion_events = [
        EventEnvelope(
            event_type="run.completed",
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="agent", id=participant_id),
            target=TargetRef(type="run", id=run_id),
            visibility="agents_only",
            correlation_id=task.correlation_id,
            sequence=6,
            timestamp=now,
            payload={"run_id": str(run_id)},
        ),
        EventEnvelope(
            event_type="message.created",
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="agent", id=participant_id),
            target=TargetRef(type="message", id=uuid4()),
            visibility="workspace",
            correlation_id=task.correlation_id,
            sequence=7,
            timestamp=now,
            payload={"content": "Testing Agent: Focus on migrations and regression risk."},
        ),
    ]
    failure_events = [
        EventEnvelope(
            event_type="run.failed",
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="agent", id=participant_id),
            target=TargetRef(type="run", id=run_id),
            visibility="agents_only",
            correlation_id=task.correlation_id,
            sequence=6,
            timestamp=now,
            payload={"run_id": str(run_id)},
        )
    ]
    return FakeKernel(
        system_agent=system_agent,
        task=task,
        context=context,
        claim_events=claim_events,
        progress_events=progress_events,
        completion_events=completion_events,
        failure_events=failure_events,
    )


@pytest.mark.asyncio
async def test_agent_runtime_processes_system_agent_task_end_to_end():
    kernel = _build_fixture_context(endpoint_kind="system")
    published: list[list[EventEnvelope]] = []

    class SuccessfulExecutor:
        async def execute(self, context: AgentExecutionContext) -> AgentRunResult:
            return AgentRunResult(
                stop_reason="completed",
                message=(
                    "Summary: Validation check completed for the latest visible request.\n\n"
                    "Checks performed:\n"
                    "- Reviewed visible thread messages\n"
                    "- Reviewed workspace memory\n\n"
                    "Findings:\n"
                    "- Migration-related risk is in scope.\n"
                    "- No direct test execution evidence is present in the shared context.\n\n"
                    "Residual risk: Medium until real validation results are attached to the thread.\n"
                    "Next action: Run targeted migration and regression checks, then post concrete results."
                ),
                summary="Completed via contract-driven executor",
            )

    async def publish(events: list[EventEnvelope]) -> None:
        published.append(events)

    runtime = AgentTaskRuntime(
        kernel=kernel,
        publish_events=publish,
        poll_interval_seconds=0.01,
        executors={
            "local": SuccessfulExecutor(),
            "remote": SuccessfulExecutor(),
            "system": SuccessfulExecutor(),
        },
    )

    await runtime._run_iteration()
    await asyncio.gather(*kernel_safe_processing_tasks(runtime))

    assert kernel.progress_calls == ["Executing Testing Agent"]
    assert len(kernel.completed_results) == 1
    message = kernel.completed_results[0].message or ""
    assert "Testing Agent (testing agent)" in message
    assert "Validation Summary" in message
    assert "Checks performed:" in message
    assert "Findings:" in message
    assert "Residual risk:" in message
    assert "Next action:" in message
    assert "migration" in message.lower()
    assert [events[0].event_type for events in published] == [
        "task.claimed",
        "run.progressed",
        "run.completed",
    ]
    assert kernel.failed_errors == []


@pytest.mark.asyncio
async def test_agent_runtime_records_failure_when_executor_raises():
    kernel = _build_fixture_context(endpoint_kind="remote")
    published: list[list[EventEnvelope]] = []

    class FailingExecutor:
        async def execute(self, context: AgentExecutionContext) -> AgentRunResult:
            raise RuntimeError("remote endpoint timed out")

    async def publish(events: list[EventEnvelope]) -> None:
        published.append(events)

    runtime = AgentTaskRuntime(
        kernel=kernel,
        publish_events=publish,
        poll_interval_seconds=0.01,
        executors={
            "local": FailingExecutor(),
            "remote": FailingExecutor(),
            "system": FailingExecutor(),
        },
    )

    await runtime._run_iteration()
    await asyncio.gather(*kernel_safe_processing_tasks(runtime))

    assert kernel.completed_results == []
    assert kernel.failed_errors == ["remote endpoint timed out"]
    assert [events[0].event_type for events in published] == [
        "task.claimed",
        "run.progressed",
        "run.failed",
    ]


@pytest.mark.asyncio
async def test_agent_runtime_uses_thread_reply_template_from_interaction_contract():
    kernel = _build_fixture_context(endpoint_kind="system")
    base_contract = kernel.context.system_agent.interaction_contract
    kernel.context.thread_reply_contract = base_contract.model_copy(
        update={
            "response_contract": base_contract.response_contract.model_copy(
                update={"title": "Structured Validation"}
            ),
            "thread_reply_template": (
                "[{title}] {agent_name}/{agent_role}\n\n{body}"
            ),
        }
    )
    published: list[list[EventEnvelope]] = []

    class SuccessfulExecutor:
        async def execute(self, context: AgentExecutionContext) -> AgentRunResult:
            return AgentRunResult(
                stop_reason="completed",
                message="Summary: Validation finished.\n\nNext action: Share the concrete results.",
                summary="Completed with template",
            )

    async def publish(events: list[EventEnvelope]) -> None:
        published.append(events)

    runtime = AgentTaskRuntime(
        kernel=kernel,
        publish_events=publish,
        poll_interval_seconds=0.01,
        executors={
            "local": SuccessfulExecutor(),
            "remote": SuccessfulExecutor(),
            "system": SuccessfulExecutor(),
        },
    )

    await runtime._run_iteration()
    await asyncio.gather(*kernel_safe_processing_tasks(runtime))

    assert len(kernel.completed_results) == 1
    message = kernel.completed_results[0].message or ""
    assert message.startswith("[Structured Validation] Testing Agent/testing agent")
    assert "Summary: Validation finished." in message


def test_render_prompt_includes_participants_memory_and_thread_context():
    kernel = _build_fixture_context(endpoint_kind="system")
    prompt = render_prompt(kernel.context)

    assert "Workspace participants:" in prompt
    assert "Nikolay (user)" in prompt
    assert "Workspace memory:" in prompt
    assert "Release checklist" in prompt
    assert "Visible thread messages:" in prompt
    assert "Focus on migrations and regression risk." in prompt
    assert "Response contract:" in prompt
    assert "Validation Summary" in prompt
    assert "required sections: Summary, Checks performed, Findings, Residual risk, Next action" in prompt


def kernel_safe_processing_tasks(runtime: AgentTaskRuntime) -> list[asyncio.Task[None]]:
    return list(runtime._processing_tasks.values())
