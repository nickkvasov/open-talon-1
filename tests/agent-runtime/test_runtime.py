from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from types import ModuleType
from uuid import UUID, uuid4

import pytest

_AGENT_RUNTIME_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/agent-runtime")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
_WORKSPACE_MEMORY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/workspace-memory")
)
for path in (
    _AGENT_RUNTIME_DIR,
    _CONTRACTS_DIR,
    _CORE_COLLAB_DIR,
    _WORKSPACE_MEMORY_DIR,
):
    if path not in sys.path:
        sys.path.insert(0, path)

from agent_runtime.runtime import (
    AgentTaskRuntime,
    HttpEndpointExecutor,
    LangfuseRuntimeObserver,
    LocalOllamaExecutor,
    _debug_prompt_payload,
    render_prompt,
)
from agent_runtime.observability import (
    OtlpHttpObservabilityProvider,
    build_observability_provider_from_env,
)
from agent_runtime.secrets import (
    OpenBaoSecretProvider,
    SecretReference,
    SecretResolver,
)
from open_talon_contracts.models import (
    ActorRef,
    AgentDefinition,
    AgentEndpoint,
    AgentExecutionContext,
    AgentHarness,
    AgentInteractionContract,
    AgentRunResult,
    AgentResponseContract,
    AgentTaskRouting,
    AgentToolUsePolicy,
    HarnessExecutionRule,
    InteractionAnswer,
    InteractionQuestion,
    InteractionRequest,
    InteractionRequestDetail,
    InteractionRequestTarget,
    EventEnvelope,
    GeneratedToolManifest,
    MemoryEntry,
    LlmProviderDefinition,
    ParticipantProfile,
    RoleDefinition,
    Run,
    TargetRef,
    Task,
    Thread,
    TimelineMessage,
    ToolExecutionBinding,
    ToolGenerationRequest,
    ToolGenerationRequestDetail,
    ToolGenerationRevision,
    Workspace,
    WorkspaceHarness,
    WorkspaceMethodic,
    WorkspaceMethodicStep,
    WorkspaceMethodology,
    WorkspaceTool,
)
from open_talon_contracts.llm_engines import (
    LlmEngineDescriptor,
    LlmEngineRegistry,
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
    llm_providers: list[object] | None = None

    def __post_init__(self) -> None:
        self.progress_calls: list[str] = []
        self.completed_results: list[AgentRunResult] = []
        self.failed_errors: list[str] = []
        self._claimed = False

    async def list_system_agents(self) -> list[AgentDefinition]:
        return [self.system_agent]

    async def list_llm_providers(self) -> list[object]:
        return list(self.llm_providers or [])

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
        workspace_tools=[
            WorkspaceTool(
                tool_id=uuid4(),
                name="repo_search",
                description="Searches the current workspace source tree.",
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
                attached_by=user_id,
                attached_at=now,
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
        run_memory=[
            MemoryEntry(
                memory_entry_id=uuid4(),
                scope="run",
                state="scratch",
                workspace_id=workspace_id,
                thread_id=thread_id,
                run_id=run_id,
                entry_type="agent_step_summary",
                summary="Reviewed visible context",
                content="Checked the current request and visible execution state.",
                created_by=user_id,
                updated_by=user_id,
                visibility="agents_only",
                created_at=now,
                updated_at=now,
            )
        ],
        thread_memory=[
            MemoryEntry(
                memory_entry_id=uuid4(),
                scope="thread",
                state="confirmed",
                workspace_id=workspace_id,
                thread_id=thread_id,
                entry_type="decision",
                summary="Release checklist",
                content="Run migrations in staging before production.",
                created_by=user_id,
                updated_by=user_id,
                visibility="workspace",
                created_at=now,
                updated_at=now,
            )
        ],
        workspace_memory=[
            MemoryEntry(
                memory_entry_id=uuid4(),
                scope="workspace",
                state="confirmed",
                workspace_id=workspace_id,
                entry_type="decision",
                summary="Canonical sequencing",
                content="core-collab remains the canonical collaboration store.",
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


@pytest.mark.asyncio
async def test_agent_runtime_selects_best_registered_engine_from_runtime_preferences():
    kernel = _build_fixture_context(endpoint_kind="remote")
    kernel.context = kernel.context.model_copy(
        update={
            "system_agent": kernel.context.system_agent.model_copy(
                update={
                    "endpoint": AgentEndpoint(kind="remote"),
                    "definition": {
                        "runtime": {
                            "required_capabilities": ["chat"],
                            "preferred_capabilities": ["tool_calling", "reasoning"],
                            "preferred_locality": "cloud",
                        }
                    },
                }
            )
        }
    )

    class InspectingExecutor:
        def __init__(self) -> None:
            self.endpoint: AgentEndpoint | None = None

        async def execute(self, context: AgentExecutionContext) -> AgentRunResult:
            self.endpoint = context.system_agent.endpoint
            return AgentRunResult(
                stop_reason="completed",
                message="Summary: done.",
                summary="ok",
            )

    inspector = InspectingExecutor()

    async def publish(events: list[EventEnvelope]) -> None:
        return None

    runtime = AgentTaskRuntime(
        kernel=kernel,
        publish_events=publish,
        poll_interval_seconds=0.01,
        engine_registry=LlmEngineRegistry(
            [
                LlmEngineDescriptor(
                    engine_id="lan-llama",
                    display_name="LAN Llama",
                    description="Local network inference endpoint.",
                    endpoint_kind="remote",
                    provider="ollama-proxy",
                    url="http://10.0.0.4:11434/api/generate",
                    default_model="llama3.2:latest",
                    capabilities=["chat"],
                    locality="lan",
                    priority=100,
                ),
                LlmEngineDescriptor(
                    engine_id="cloud-gpt",
                    display_name="Cloud GPT",
                    description="Cloud engine with stronger reasoning and tool calling.",
                    endpoint_kind="remote",
                    provider="openai",
                    url="https://api.example.com/v1/responses",
                    default_model="gpt-5.4-mini",
                    capabilities=["chat", "tool_calling", "reasoning"],
                    locality="cloud",
                    priority=150,
                ),
            ]
        ),
        executors={
            "local": inspector,
            "remote": inspector,
            "system": inspector,
        },
    )

    await runtime._run_iteration()
    await asyncio.gather(*kernel_safe_processing_tasks(runtime))

    assert inspector.endpoint is not None
    assert inspector.endpoint.engine_id == "cloud-gpt"
    assert inspector.endpoint.provider == "openai"
    assert inspector.endpoint.url == "https://api.example.com/v1/responses"
    assert inspector.endpoint.model == "gpt-5.4-mini"


@pytest.mark.asyncio
async def test_agent_runtime_can_resolve_managed_llm_provider_from_kernel():
    kernel = _build_fixture_context(endpoint_kind="remote")
    kernel.context = kernel.context.model_copy(
        update={
            "system_agent": kernel.context.system_agent.model_copy(
                update={
                    "endpoint": AgentEndpoint(
                        kind="remote",
                        engine_id="managed-openai",
                        provider="openai",
                    )
                }
            )
        }
    )
    kernel.llm_providers = [
        LlmProviderDefinition(
            provider_id=uuid4(),
            engine_id="managed-openai",
            display_name="Managed OpenAI",
            description="Managed provider from kernel storage.",
            provider="openai",
            endpoint_kind="remote",
            url="https://api.openai.com/v1/responses",
            default_model="gpt-5.4-mini",
            capabilities=["chat", "reasoning"],
            locality="cloud",
            priority=250,
            enabled=True,
            secret_config={
                "openbao": {
                    "mount": "secret",
                    "path": "open-talon/llm/openai",
                    "field": "api_key",
                }
            },
            created_by=uuid4(),
            updated_by=uuid4(),
        )
    ]

    class InspectingExecutor:
        def __init__(self) -> None:
            self.endpoint: AgentEndpoint | None = None
            self.metadata: dict[str, object] | None = None

        async def execute(self, context: AgentExecutionContext) -> AgentRunResult:
            self.endpoint = context.system_agent.endpoint
            self.metadata = context.system_agent.metadata
            return AgentRunResult(stop_reason="completed", message="Summary: done.", summary="ok")

    inspector = InspectingExecutor()

    async def publish(events: list[EventEnvelope]) -> None:
        return None

    runtime = AgentTaskRuntime(
        kernel=kernel,
        publish_events=publish,
        poll_interval_seconds=0.01,
        executors={
            "local": inspector,
            "remote": inspector,
            "system": inspector,
        },
    )

    await runtime._run_iteration()
    await asyncio.gather(*kernel_safe_processing_tasks(runtime))

    assert inspector.endpoint is not None
    assert inspector.endpoint.url == "https://api.openai.com/v1/responses"
    assert inspector.endpoint.model == "gpt-5.4-mini"
    assert inspector.metadata is not None
    assert inspector.metadata["_resolved_llm_engine"]["metadata"]["managed"] is True


@pytest.mark.asyncio
async def test_agent_runtime_rejects_disabled_managed_llm_provider():
    kernel = _build_fixture_context(endpoint_kind="remote")
    kernel.context = kernel.context.model_copy(
        update={
            "system_agent": kernel.context.system_agent.model_copy(
                update={
                    "endpoint": AgentEndpoint(
                        kind="remote",
                        engine_id="managed-openai",
                        provider="openai",
                    )
                }
            )
        }
    )
    kernel.llm_providers = [
        LlmProviderDefinition(
            provider_id=uuid4(),
            engine_id="managed-openai",
            display_name="Managed OpenAI",
            description="Managed provider from kernel storage.",
            provider="openai",
            endpoint_kind="remote",
            url="https://api.openai.com/v1/responses",
            default_model="gpt-5.4-mini",
            capabilities=["chat", "reasoning"],
            locality="cloud",
            priority=250,
            enabled=False,
            secret_config={},
            created_by=uuid4(),
            updated_by=uuid4(),
        )
    ]

    runtime = AgentTaskRuntime(
        kernel=kernel,
        publish_events=lambda events: asyncio.sleep(0),
        poll_interval_seconds=0.01,
        executors={
            "local": SimpleNamespace(),
            "remote": SimpleNamespace(),
            "system": SimpleNamespace(),
        },
    )

    with pytest.raises(ValueError, match="disabled"):
        await runtime._resolve_execution_context(kernel.context)


def test_render_prompt_includes_participants_memory_and_thread_context():
    kernel = _build_fixture_context(endpoint_kind="system")
    prompt = render_prompt(kernel.context)

    assert "Workspace participants:" in prompt
    assert "Nikolay (user)" in prompt
    assert "Run scratch:" in prompt
    assert "Reviewed visible context" in prompt
    assert "Thread memory:" in prompt
    assert "Workspace memory:" in prompt
    assert "Release checklist" in prompt
    assert "Canonical sequencing" in prompt
    assert "Workspace tools:" in prompt
    assert "repo_search | enabled: yes | Searches the current workspace source tree." in prompt
    assert "Visible thread messages:" in prompt
    assert "Focus on migrations and regression risk." in prompt
    assert "Response contract:" in prompt
    assert "Validation Summary" in prompt
    assert "required sections: Summary, Checks performed, Findings, Residual risk, Next action" in prompt


def test_render_prompt_includes_workspace_and_agent_harness_sections():
    kernel = _build_fixture_context(endpoint_kind="system")
    workspace_harness = WorkspaceHarness(
        summary="Workspace harness summary",
        methodology=WorkspaceMethodology(
            ontology="Evidence comes from visible artifacts.",
            principles=["Prefer direct verification."],
        ),
        methodics=[
            WorkspaceMethodic(
                name="Validate release",
                goal="Check rollout incrementally.",
                steps=[
                    WorkspaceMethodicStep(
                        instruction="Inspect the current workspace tools before acting.",
                        recommended_tool_patterns=["repo_search"],
                        verification=["Confirm the tool catalog is current."],
                    )
                ],
            )
        ],
        execution_rules=[
            HarnessExecutionRule(
                name="evidence-first",
                instruction="Prefer direct evidence over assumptions.",
                priority="critical",
                scope="validation",
            )
        ],
    )
    agent_harness = AgentHarness(
        summary="Agent harness summary",
        operating_principles=["Stay incremental."],
        tool_use_policy=AgentToolUsePolicy(
            selection_principles=["Choose the narrowest tool that answers the question."],
            fallback_when_no_tool_fits="Call out the gap and ask for clarification.",
        ),
    )
    kernel.context = kernel.context.model_copy(
        update={
            "workspace_harness": workspace_harness,
            "agent_harness": agent_harness,
        }
    )

    prompt = render_prompt(kernel.context)

    assert "Workspace harness:" in prompt
    assert "Workspace harness summary" in prompt
    assert "ontology: Evidence comes from visible artifacts." in prompt
    assert "[critical/validation] evidence-first: Prefer direct evidence over assumptions." in prompt
    assert "Agent harness:" in prompt
    assert "Agent harness summary" in prompt
    assert "select tools from the current workspace tool catalog dynamically" in prompt
    assert "fallback when no tool fits: Call out the gap and ask for clarification." in prompt
    assert "repo_search | enabled: yes | Searches the current workspace source tree." in prompt


def test_render_prompt_keeps_full_workspace_tool_catalog_with_tool_use_guidance():
    kernel = _build_fixture_context(endpoint_kind="system")
    now = _now()
    kernel.context = kernel.context.model_copy(
        update={
            "workspace_tools": [
                *kernel.context.workspace_tools,
                WorkspaceTool(
                    tool_id=uuid4(),
                    name="db_query",
                    description="Queries the attached database schema.",
                    parameter_contract={
                        "parameters": [
                            {
                                "name": "sql",
                                "type": "string",
                                "description": "Read-only SQL to execute.",
                                "required": True,
                            }
                        ],
                        "additional_properties": False,
                    },
                    attached_by=uuid4(),
                    attached_at=now,
                    updated_at=now,
                ),
            ],
            "agent_harness": AgentHarness(
                summary="Use the available tools carefully.",
                tool_use_policy=AgentToolUsePolicy(
                    selection_principles=[
                        "Prefer the narrowest tool that provides direct evidence."
                    ],
                    fallback_when_no_tool_fits="Explain the gap and ask for clarification.",
                ),
            ),
        }
    )

    prompt = render_prompt(kernel.context)

    assert "select tools from the current workspace tool catalog dynamically" in prompt
    assert "repo_search | enabled: yes | Searches the current workspace source tree." in prompt
    assert "db_query | enabled: yes | Queries the attached database schema." in prompt


def test_render_prompt_sorts_workspace_harness_execution_rules_by_priority():
    kernel = _build_fixture_context(endpoint_kind="system")
    kernel.context = kernel.context.model_copy(
        update={
            "workspace_harness": WorkspaceHarness(
                summary="Rules should render from highest to lowest priority.",
                execution_rules=[
                    HarnessExecutionRule(
                        name="document-outcome",
                        instruction="Summarize the completion state clearly.",
                        priority="normal",
                        scope="completion",
                    ),
                    HarnessExecutionRule(
                        name="plan-first",
                        instruction="Inspect visible context before changing anything.",
                        priority="high",
                        scope="planning",
                    ),
                    HarnessExecutionRule(
                        name="verify-first",
                        instruction="Prefer direct evidence over assumption.",
                        priority="critical",
                        scope="validation",
                    ),
                ],
            )
        }
    )

    prompt = render_prompt(kernel.context)

    critical_index = prompt.index(
        "[critical/validation] verify-first: Prefer direct evidence over assumption."
    )
    high_index = prompt.index(
        "[high/planning] plan-first: Inspect visible context before changing anything."
    )
    normal_index = prompt.index(
        "[normal/completion] document-outcome: Summarize the completion state clearly."
    )

    assert critical_index < high_index < normal_index


def test_render_prompt_includes_interaction_request_summary():
    kernel = _build_fixture_context(endpoint_kind="system")
    now = _now()
    request_id = uuid4()
    responder_id = kernel.context.participants[0].participant_id
    kernel.context.interaction_requests = [
        InteractionRequestDetail(
            request=InteractionRequest(
                request_id=request_id,
                workspace_id=kernel.context.workspace.workspace_id,
                thread_id=kernel.context.thread.thread_id,
                requester_participant_id=kernel.context.participant.participant_id,
                title="Need coordinated feedback",
                status="open",
                created_at=now,
                updated_at=now,
            ),
            questions=[
                InteractionQuestion(
                    question_id=uuid4(),
                    request_id=request_id,
                    prompt="What blocks release?",
                    order=0,
                )
            ],
            targets=[
                InteractionRequestTarget(
                    target_id=uuid4(),
                    request_id=request_id,
                    participant_id=responder_id,
                    created_at=now,
                    updated_at=now,
                )
            ],
            answers=[
                InteractionAnswer(
                    answer_id=uuid4(),
                    request_id=request_id,
                    participant_id=responder_id,
                    message_id=uuid4(),
                    created_at=now,
                )
            ],
        )
    ]

    prompt = render_prompt(kernel.context)

    assert "Interaction requests:" in prompt
    assert "- Need coordinated feedback | status: open | questions: 1 | targets: 1 | answers: 1" in prompt


def test_render_prompt_includes_tool_generation_requested_scope():
    kernel = _build_fixture_context(endpoint_kind="system")
    now = _now()
    request_id = uuid4()
    kernel.context.tool_generation_request = ToolGenerationRequestDetail(
        request=ToolGenerationRequest(
            request_id=request_id,
            organization_id=uuid4(),
            workspace_id=kernel.context.workspace.workspace_id,
            thread_id=kernel.context.thread.thread_id,
            requester_participant_id=kernel.context.participants[0].participant_id,
            target_system_agent_id=kernel.system_agent.agent_id,
            requested_scope="organization",
            status="pending_approval",
            target_tool_name="fibonacci_calculator",
            summary="Create an organization-scoped Fibonacci tool.",
            created_at=now,
            updated_at=now,
        ),
        revisions=[
            ToolGenerationRevision(
                revision_id=uuid4(),
                request_id=request_id,
                revision_number=1,
                status="pending_approval",
                manifest=GeneratedToolManifest(
                    name="fibonacci_calculator",
                    description="Calculates Fibonacci numbers.",
                    build_context_path="/tmp/generated-tools/fibonacci_calculator",
                    execution=ToolExecutionBinding(
                        backend_kind="docker",
                        handler_ref="registry.example/fibonacci-calculator:latest",
                    ),
                ),
                created_by=kernel.context.participant.participant_id,
                created_at=now,
                updated_at=now,
            )
        ],
    )

    prompt = render_prompt(kernel.context)

    assert "Tool generation request:" in prompt
    assert "requested_scope: organization" in prompt
    assert "target_tool_name: fibonacci_calculator" in prompt


def kernel_safe_processing_tasks(runtime: AgentTaskRuntime) -> list[asyncio.Task[None]]:
    return list(runtime._processing_tasks.values())


class RecordingObservation:
    def __init__(self, sink: list[dict[str, object]], kind: str, payload: dict[str, object]):
        self._sink = sink
        self._entry = {"kind": kind, **payload, "updates": []}

    def __enter__(self):
        self._sink.append(self._entry)
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, **kwargs):
        self._entry["updates"].append(kwargs)


class RecordingObserver:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self.flush_count = 0

    def start_span(self, *, name, input=None, metadata=None):
        return RecordingObservation(
            self.records,
            "span",
            {"name": name, "input": input, "metadata": metadata},
        )

    def start_generation(self, *, name, model=None, input=None, metadata=None):
        return RecordingObservation(
            self.records,
            "generation",
            {"name": name, "model": model, "input": input, "metadata": metadata},
        )

    def flush(self):
        self.flush_count += 1


@pytest.mark.asyncio
async def test_agent_runtime_emits_task_span_to_observer():
    kernel = _build_fixture_context(endpoint_kind="system")
    observer = RecordingObserver()

    class SuccessfulExecutor:
        async def execute(self, context: AgentExecutionContext) -> AgentRunResult:
            return AgentRunResult(
                stop_reason="completed",
                message="Summary: done.",
                summary="ok",
            )

    async def publish(events: list[EventEnvelope]) -> None:
        return None

    runtime = AgentTaskRuntime(
        kernel=kernel,
        publish_events=publish,
        poll_interval_seconds=0.01,
        observability=observer,
        executors={
            "local": SuccessfulExecutor(),
            "remote": SuccessfulExecutor(),
            "system": SuccessfulExecutor(),
        },
    )

    await runtime._run_iteration()
    await asyncio.gather(*kernel_safe_processing_tasks(runtime))

    assert observer.records[0]["kind"] == "span"
    assert observer.records[0]["name"] == "agent-task-run"
    assert observer.records[0]["metadata"]["correlation_id"] == str(kernel.context.run.correlation_id)
    assert observer.records[0]["metadata"]["run_id"] == str(kernel.context.run.run_id)
    assert observer.records[0]["metadata"]["task_id"] == str(kernel.task.task_id)
    updates = observer.records[0]["updates"]
    assert any(update.get("metadata", {}).get("stop_reason") == "completed" for update in updates)
    assert observer.flush_count >= 1


@pytest.mark.asyncio
async def test_local_ollama_executor_emits_generation_observation(monkeypatch):
    kernel = _build_fixture_context(endpoint_kind="local")
    observer = RecordingObserver()

    class FakeResponse:
        headers = {"content-type": "application/json"}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "response": "Validated the request.",
                "prompt_eval_count": 12,
                "eval_count": 7,
                "done": True,
                "done_reason": "stop",
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            return FakeResponse()

    monkeypatch.setattr("agent_runtime.runtime.httpx.AsyncClient", FakeAsyncClient)

    executor = LocalOllamaExecutor(timeout_seconds=1.0, observability=observer)
    result = await executor.execute(kernel.context)

    assert "Testing Agent (testing agent)" in (result.message or "")
    assert observer.records[0]["kind"] == "generation"
    assert observer.records[0]["name"] == "local-ollama-generate"
    langfuse_input = observer.records[0]["input"]
    assert langfuse_input["prompt"] == render_prompt(kernel.context)
    update = observer.records[0]["updates"][0]
    assert update["usage_details"] == {
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "total_tokens": 19,
    }
    assert result.metadata["usage"] == {
        "provider": "ollama",
        "model": "gemma4:latest",
        "prompt_tokens": 12,
        "completion_tokens": 7,
        "total_tokens": 19,
    }


@pytest.mark.asyncio
async def test_http_executor_emits_generation_when_model_present(monkeypatch):
    kernel = _build_fixture_context(endpoint_kind="remote")
    observer = RecordingObserver()

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"message": "Remote validation complete."}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            return FakeResponse()

    monkeypatch.setattr("agent_runtime.runtime.httpx.AsyncClient", FakeAsyncClient)

    executor = HttpEndpointExecutor(
        timeout_seconds=1.0,
        endpoint_scope="remote",
        observability=observer,
    )
    result = await executor.execute(kernel.context)

    assert "Testing Agent (testing agent)" in (result.message or "")
    assert observer.records[0]["kind"] == "generation"
    assert observer.records[0]["name"] == "remote-agent-execute"
    assert observer.records[0]["input"]["prompt"] == render_prompt(kernel.context)


@pytest.mark.asyncio
async def test_http_executor_calls_openai_responses_with_api_key(monkeypatch):
    kernel = _build_fixture_context(endpoint_kind="remote")
    kernel.context = kernel.context.model_copy(
        update={
            "system_agent": kernel.context.system_agent.model_copy(
                update={
                    "endpoint": AgentEndpoint(
                        kind="remote",
                        url="https://api.openai.com/v1/responses",
                        model="gpt-5.4-mini",
                        provider="openai",
                        engine_id="openai-responses",
                    )
                }
            )
        }
    )
    observer = RecordingObserver()
    request_log: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "output_text": "OpenAI validation complete.",
                "usage": {
                    "input_tokens": 21,
                    "output_tokens": 9,
                    "total_tokens": 30,
                },
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            request_log["url"] = url
            request_log["headers"] = headers
            request_log["json"] = json
            return FakeResponse()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setattr("agent_runtime.runtime.httpx.AsyncClient", FakeAsyncClient)

    executor = HttpEndpointExecutor(
        timeout_seconds=1.0,
        endpoint_scope="remote",
        observability=observer,
    )
    result = await executor.execute(kernel.context)

    assert "Testing Agent (testing agent)" in (result.message or "")
    assert request_log["url"] == "https://api.openai.com/v1/responses"
    assert request_log["headers"]["Authorization"] == "Bearer sk-openai-test"
    assert request_log["json"]["model"] == "gpt-5.4-mini"
    assert request_log["json"]["input"] == render_prompt(kernel.context)
    assert observer.records[0]["name"] == "remote-openai-responses"
    update = observer.records[0]["updates"][0]
    assert update["usage_details"] == {
        "prompt_tokens": 21,
        "completion_tokens": 9,
        "total_tokens": 30,
    }
    assert result.metadata["usage"] == {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "prompt_tokens": 21,
        "completion_tokens": 9,
        "total_tokens": 30,
    }


@pytest.mark.asyncio
async def test_openbao_secret_provider_reads_kv_v2_value(monkeypatch):
    request_log: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "data": {
                    "data": {
                        "api_key": "sk-from-openbao",
                    }
                }
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None):
            request_log["url"] = url
            request_log["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("agent_runtime.secrets.httpx.AsyncClient", FakeAsyncClient)

    provider = OpenBaoSecretProvider(
        address="http://localhost:8200",
        token="root-token",
        default_mount="secret",
    )
    value = await provider.get_secret(
        SecretReference(
            provider="openbao",
            path="open-talon/llm/openai",
            field_name="api_key",
        )
    )

    assert value == "sk-from-openbao"
    assert request_log["url"] == "http://localhost:8200/v1/secret/data/open-talon/llm/openai"
    assert request_log["headers"]["X-Vault-Token"] == "root-token"


@pytest.mark.asyncio
async def test_http_executor_can_resolve_openai_api_key_from_openbao(monkeypatch):
    kernel = _build_fixture_context(endpoint_kind="remote")
    kernel.context = kernel.context.model_copy(
        update={
            "system_agent": kernel.context.system_agent.model_copy(
                update={
                    "endpoint": AgentEndpoint(
                        kind="remote",
                        url="https://api.openai.com/v1/responses",
                        model="gpt-5.4-mini",
                        provider="openai",
                        engine_id="openai-responses",
                    ),
                    "metadata": {
                        "_resolved_llm_engine": {
                            "engine_id": "openai-responses",
                            "metadata": {
                                "api_key_secret": {
                                    "openbao": {
                                        "mount": "secret",
                                        "path": "open-talon/llm/openai",
                                        "field": "api_key",
                                    }
                                }
                            },
                        }
                    },
                }
            )
        }
    )
    request_log: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "application/json"}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"output_text": "OpenAI validation complete."}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            request_log["url"] = url
            request_log["headers"] = headers
            request_log["json"] = json
            return FakeResponse()

    monkeypatch.setattr("agent_runtime.runtime.httpx.AsyncClient", FakeAsyncClient)

    resolver = SecretResolver(
        [
            OpenBaoSecretProvider(
                address="http://localhost:8200",
                token="root-token",
                default_mount="secret",
            )
        ]
    )

    async def fake_get_secret(reference):
        assert reference.provider == "openbao"
        assert reference.path == "open-talon/llm/openai"
        return "sk-openbao-test"

    resolver._providers["openbao"].get_secret = fake_get_secret  # type: ignore[attr-defined]

    executor = HttpEndpointExecutor(
        timeout_seconds=1.0,
        endpoint_scope="remote",
        observability=RecordingObserver(),
        secret_resolver=resolver,
    )
    result = await executor.execute(kernel.context)

    assert "Testing Agent (testing agent)" in (result.message or "")
    assert request_log["headers"]["Authorization"] == "Bearer sk-openbao-test"


def test_langfuse_runtime_observer_uses_observation_api_for_generation():
    calls: list[dict[str, object]] = []

    class FakeClient:
        def start_as_current_observation(self, **kwargs):
            calls.append(kwargs)
            return RecordingObservation([], "generation", kwargs)

    observer = LangfuseRuntimeObserver(FakeClient())
    with observer.start_generation(
        name="runtime-generate",
        model="gemma4:latest",
        input={"message": "hi"},
        metadata={"provider": "ollama"},
    ):
        pass

    assert calls == [
        {
            "name": "runtime-generate",
            "as_type": "generation",
            "model": "gemma4:latest",
            "input": {"message": "hi"},
            "metadata": {"provider": "ollama"},
        }
    ]


def test_langfuse_runtime_observer_from_env_uses_sdk_client(monkeypatch):
    fake_client = object()
    fake_module = ModuleType("langfuse")
    fake_module.get_client = lambda: fake_client

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_PUBLIC_URL", "http://localhost:3000")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.setitem(sys.modules, "langfuse", fake_module)

    observer = LangfuseRuntimeObserver.from_env()

    assert observer._client is fake_client
    assert os.environ["LANGFUSE_BASE_URL"] == "http://localhost:3000"


def test_build_observability_provider_from_env_supports_otlp(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_OBSERVABILITY_PROVIDER", "otlp")
    monkeypatch.setenv("AGENT_RUNTIME_OTLP_HTTP_ENDPOINT", "http://127.0.0.1:4318/v1/traces")

    provider = build_observability_provider_from_env()

    assert isinstance(provider, OtlpHttpObservabilityProvider)


def test_build_observability_provider_from_env_supports_none(monkeypatch):
    monkeypatch.setenv("AGENT_RUNTIME_OBSERVABILITY_PROVIDER", "none")

    provider = build_observability_provider_from_env()

    assert provider.provider_name == "none"


def test_otlp_observability_redacts_sensitive_payloads(monkeypatch):
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None):
            requests.append({"url": url, "json": json})
            return FakeResponse()

    monkeypatch.setattr("agent_runtime.observability.httpx.Client", FakeClient)

    provider = OtlpHttpObservabilityProvider(
        endpoint="http://127.0.0.1:4318/v1/traces",
        service_name="agent-runtime",
    )
    with provider.start_generation(
        name="remote-openai-responses",
        model="gpt-5.4-mini",
        input={
            "prompt": "top secret prompt",
            "headers": {
                "authorization": "Bearer sk-test-secret",
                "x-api-key": "sk-test-secret",
            },
        },
        metadata={"provider": "openai"},
    ) as observation:
        observation.update(output={"message": "ok", "token": "secret-token"})

    provider.flush()

    body = json.dumps(requests[0]["json"], sort_keys=True)
    assert "top secret prompt" not in body
    assert "Bearer sk-test-secret" not in body
    assert "secret-token" not in body
    assert "[REDACTED]" in body


@pytest.mark.asyncio
async def test_local_ollama_executor_debug_dump_writes_request_payload(monkeypatch, tmp_path):
    kernel = _build_fixture_context(endpoint_kind="local")
    debug_file = tmp_path / "agent-runtime-prompts.jsonl"

    class FakeResponse:
        headers = {"content-type": "application/json"}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"response": "Validated the request."}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            return FakeResponse()

    monkeypatch.setattr("agent_runtime.runtime.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setenv("AGENT_RUNTIME_DEBUG_PROMPTS", "1")
    monkeypatch.setenv("AGENT_RUNTIME_DEBUG_PROMPTS_FILE", str(debug_file))

    executor = LocalOllamaExecutor(timeout_seconds=1.0, observability=RecordingObserver())
    await executor.execute(kernel.context)

    record = json.loads(debug_file.read_text(encoding="utf-8").strip())
    assert record["source"] == "local-ollama"
    assert record["message_count"] == 2
    assert record["request"]["prompt"] == render_prompt(kernel.context)


def test_debug_prompt_payload_rotates_dump_file(monkeypatch, tmp_path):
    context = _build_fixture_context(endpoint_kind="local").context
    debug_file = tmp_path / "agent-runtime-prompts.jsonl"

    monkeypatch.setenv("AGENT_RUNTIME_DEBUG_PROMPTS", "1")
    monkeypatch.setenv("AGENT_RUNTIME_DEBUG_PROMPTS_FILE", str(debug_file))
    monkeypatch.setenv("AGENT_RUNTIME_DEBUG_PROMPTS_MAX_BYTES", "250")
    monkeypatch.setenv("AGENT_RUNTIME_DEBUG_PROMPTS_BACKUP_COUNT", "2")

    for index in range(5):
        _debug_prompt_payload(
            "local-ollama",
            context,
            {"prompt": f"payload-{index}-" + ("x" * 120)},
        )

    assert debug_file.exists()
    assert (tmp_path / "agent-runtime-prompts.jsonl.1").exists()

    latest_record = json.loads(debug_file.read_text(encoding="utf-8").strip())
    assert latest_record["request"]["prompt"].startswith("payload-4-")
