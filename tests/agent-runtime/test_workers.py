from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace
from uuid import uuid4

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

from agent_runtime.config import RuntimeWorkerSettings
from agent_runtime.events import route_event_topic
from agent_runtime.execution.registry import ExecutionBackendRegistry
from agent_runtime.workers import AgentLoopWorker, Reconciler, ToolWorker
from open_talon_contracts.models import (
    ActorRef,
    EventEnvelope,
    ExecutionHandle,
    ExecutionResult,
    ExecutionSpec,
    ExecutionWorkspaceRef,
    RunStep,
    TargetRef,
    ToolCall,
    ToolCallResult,
)


class _FakePublisher:
    def __init__(self) -> None:
        self.published: list[list[EventEnvelope]] = []

    async def publish(self, events: list[EventEnvelope]) -> None:
        self.published.append(events)


class _FakeCommandResult:
    def __init__(self) -> None:
        self.events: list[EventEnvelope] = []


class _FakeKernel:
    def __init__(self) -> None:
        self.heartbeats: list[str] = []
        self.updated_handle: str | None = None
        self.completed: ToolCallResult | None = None
        self.failed: str | None = None

    async def heartbeat_tool_call(self, *, tool_call_id, worker_id, lease_ttl_seconds):
        self.heartbeats.append(f"{tool_call_id}:{worker_id}:{lease_ttl_seconds}")
        return None

    async def update_tool_call_execution_handle(self, tool_call_id, worker_id, execution_handle):
        self.updated_handle = execution_handle
        return None

    async def complete_tool_call(self, tool_call_id, worker_id, result):
        self.completed = result
        return _FakeCommandResult()

    async def fail_tool_call(self, tool_call_id, worker_id, error):
        self.failed = error
        return _FakeCommandResult()


class _RecordingObservation:
    def __init__(self, sink: list[dict[str, object]], payload: dict[str, object]) -> None:
        self._sink = sink
        self._entry = {**payload, "updates": []}

    def __enter__(self):
        self._sink.append(self._entry)
        return self

    def __exit__(self, exc_type, exc, tb):
        self._entry["error"] = str(exc) if exc is not None else None
        return False

    def update(self, **kwargs):
        self._entry["updates"].append(kwargs)


class _RecordingObserver:
    def __init__(self) -> None:
        self.spans: list[dict[str, object]] = []
        self.events: list[dict[str, object]] = []
        self.flush_count = 0

    def start_span(self, *, name, input=None, metadata=None):
        return _RecordingObservation(
            self.spans,
            {"kind": "span", "name": name, "input": input, "metadata": metadata},
        )

    def start_generation(self, *, name, model=None, input=None, metadata=None):
        return _RecordingObservation(
            self.spans,
            {
                "kind": "generation",
                "name": name,
                "model": model,
                "input": input,
                "metadata": metadata,
            },
        )

    def record_event(self, *, name, input=None, metadata=None):
        self.events.append({"name": name, "input": input, "metadata": metadata})

    def flush(self):
        self.flush_count += 1


class _FakeBackend:
    kind = "local_process"

    def __init__(self, *, running_forever: bool = False) -> None:
        self.running_forever = running_forever
        self.cancelled = False
        self.submit_calls = 0
        self.poll_calls = 0
        self.submitted_specs: list[ExecutionSpec] = []

    async def submit(self, spec: ExecutionSpec) -> ExecutionHandle:
        self.submit_calls += 1
        self.submitted_specs.append(spec)
        return ExecutionHandle(
            backend_kind="local_process",
            invocation_id=spec.invocation_id,
            handle="handle-1",
        )

    async def poll(self, handle: ExecutionHandle) -> ExecutionResult:
        self.poll_calls += 1
        if self.running_forever:
            return ExecutionResult(status="running")
        return ExecutionResult(status="completed", output_payload={"ok": True})

    async def cancel(self, handle: ExecutionHandle, reason: str | None = None) -> None:
        self.cancelled = True

    async def collect(self, handle: ExecutionHandle) -> ExecutionResult:
        return ExecutionResult(status="completed", output_payload={"ok": True})


def _settings() -> RuntimeWorkerSettings:
    return RuntimeWorkerSettings(
        postgres_dsn="postgresql://admin:password@localhost:5432/app_db",
        kafka_bootstrap_servers="localhost:9092",
        kafka_collab_events_topic="talon.collab.events",
        kafka_workspace_events_topic="talon.workspace.events",
        kafka_agent_tasks_topic="talon.agent.tasks",
        kafka_agent_events_topic="talon.agent.events",
        kafka_presence_topic="talon.presence",
        kafka_audit_events_topic="talon.audit.events",
        kafka_consumer_group="agent-runtime",
        agent_step_worker_concurrency=1,
        tool_worker_concurrency=1,
        max_parallel_tool_calls_per_run=1,
        max_concurrent_calls_per_tool=1,
        lease_ttl_seconds=30,
        lease_heartbeat_seconds=60,
        reconcile_interval_seconds=1,
        poll_interval_seconds=1,
        model_timeout_seconds=60,
        provider_failure_retry_seconds=900,
        global_daily_token_cap=0,
        workspace_daily_token_cap_default=0,
        enable_kafka_wakeups=False,
        execution_root="/tmp/open-talon-executions",
        default_workspace_path=None,
        oci_registry_url="127.0.0.1:3001",
        oci_registry_username="forgejo",
        oci_registry_password_secret_config={"env": "OPEN_TALON_OCI_REGISTRY_PASSWORD"},
        oci_registry_validate_on_startup=False,
    )


def _tool_call(timeout_seconds: int = 30) -> ToolCall:
    spec = ExecutionSpec(
        invocation_id=uuid4(),
        handler_ref="runner",
        limits={"timeout_seconds": timeout_seconds},
        metadata={"backend_kind": "local_process"},
    )
    return ToolCall(
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
        execution_spec=spec.model_dump(mode="json"),
        claimed_by_worker="tool-worker",
    )


def _tool_call_with_workspace_ref() -> ToolCall:
    spec = ExecutionSpec(
        invocation_id=uuid4(),
        handler_ref="runner",
        execution_workspace=ExecutionWorkspaceRef(
            mode="local_path",
            workspace_id=uuid4(),
        ),
        metadata={"backend_kind": "local_process"},
    )
    return ToolCall(
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
        execution_spec=spec.model_dump(mode="json"),
        claimed_by_worker="tool-worker",
    )


def _generated_fibonacci_tool_call() -> ToolCall:
    spec = ExecutionSpec(
        invocation_id=uuid4(),
        handler_ref="registry.example/fibonacci-calculator@sha256:fibonacci55",
        inline_payload={"n": 10},
        limits={"timeout_seconds": 30},
        metadata={"backend_kind": "docker"},
    )
    return ToolCall(
        tool_call_id=uuid4(),
        run_id=uuid4(),
        run_step_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        tool_id=uuid4(),
        tool_name="fibonacci_calculator",
        status="claimed",
        execution_spec=spec.model_dump(mode="json"),
        claimed_by_worker="tool-worker",
    )


def test_route_event_topic_sends_requeue_wakeups_to_agent_tasks_topic():
    settings = _settings()
    tool_event = EventEnvelope(
        event_type="tool_call.requeued",
        workspace_id=uuid4(),
        thread_id=uuid4(),
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="tool_call", id=uuid4()),
        visibility="agents_only",
    )
    step_event = EventEnvelope(
        event_type="run_step.requeued",
        workspace_id=uuid4(),
        thread_id=uuid4(),
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="run_step", id=uuid4()),
        visibility="agents_only",
    )

    assert route_event_topic(tool_event, settings) == settings.kafka_agent_tasks_topic
    assert route_event_topic(step_event, settings) == settings.kafka_agent_tasks_topic


def test_tool_worker_persists_execution_handle_before_completion():
    backend = _FakeBackend()
    kernel = _FakeKernel()
    worker = ToolWorker(
        kernel=kernel,
        publisher=_FakePublisher(),
        settings=_settings(),
        backend_registry=ExecutionBackendRegistry([backend]),
    )

    asyncio.run(worker._process_tool_call(_tool_call()))

    assert backend.submit_calls == 1
    assert kernel.updated_handle == "handle-1"
    assert kernel.completed is not None
    assert kernel.completed.output_payload == {"ok": True}
    assert kernel.failed is None


def test_tool_worker_executes_generated_fibonacci_tool_call_with_docker_backend():
    class _FakeDockerBackend(_FakeBackend):
        kind = "docker"

        async def submit(self, spec: ExecutionSpec) -> ExecutionHandle:
            self.submit_calls += 1
            self.submitted_specs.append(spec)
            return ExecutionHandle(
                backend_kind="docker",
                invocation_id=spec.invocation_id,
                handle="docker-handle-1",
            )

        async def poll(self, handle: ExecutionHandle) -> ExecutionResult:
            self.poll_calls += 1
            return ExecutionResult(status="completed", output_payload={"n": 10, "value": 55})

        async def collect(self, handle: ExecutionHandle) -> ExecutionResult:
            return ExecutionResult(status="completed", output_payload={"n": 10, "value": 55})

    backend = _FakeDockerBackend()
    kernel = _FakeKernel()
    worker = ToolWorker(
        kernel=kernel,
        publisher=_FakePublisher(),
        settings=_settings(),
        backend_registry=ExecutionBackendRegistry([backend]),
    )

    asyncio.run(worker._process_tool_call(_generated_fibonacci_tool_call()))

    assert backend.submit_calls == 1
    assert backend.submitted_specs[0].handler_ref == "registry.example/fibonacci-calculator@sha256:fibonacci55"
    assert backend.submitted_specs[0].metadata["backend_kind"] == "docker"
    assert kernel.updated_handle == "docker-handle-1"
    assert kernel.completed is not None
    assert kernel.completed.output_payload == {"n": 10, "value": 55}
    assert kernel.failed is None


def test_tool_worker_emits_observability_span_for_execution():
    backend = _FakeBackend()
    kernel = _FakeKernel()
    observer = _RecordingObserver()
    worker = ToolWorker(
        kernel=kernel,
        publisher=_FakePublisher(),
        settings=_settings(),
        backend_registry=ExecutionBackendRegistry([backend]),
        observability=observer,
    )
    tool_call = _tool_call()

    asyncio.run(worker._process_tool_call(tool_call))

    assert len(observer.spans) == 1
    span = observer.spans[0]
    assert span["name"] == "tool-call-execution"
    assert span["metadata"]["tool_call_id"] == str(tool_call.tool_call_id)
    assert span["metadata"]["tool_name"] == tool_call.tool_name
    assert span["metadata"]["backend_kind"] == "local_process"
    assert span["metadata"]["workspace_id"] == str(tool_call.workspace_id)
    assert any(update["status"] == "submitted" for update in span["updates"])
    assert any(update["status"] == "completed" for update in span["updates"])
    assert observer.flush_count == 1


def test_tool_worker_cancels_execution_on_timeout():
    backend = _FakeBackend(running_forever=True)
    kernel = _FakeKernel()
    settings = _settings()
    worker = ToolWorker(
        kernel=kernel,
        publisher=_FakePublisher(),
        settings=settings,
        backend_registry=ExecutionBackendRegistry([backend]),
    )

    asyncio.run(worker._process_tool_call(_tool_call(timeout_seconds=0)))

    assert backend.cancelled is True
    assert kernel.completed is None
    assert kernel.failed is not None
    assert "timed out" in kernel.failed.lower()


def test_tool_worker_fills_execution_workspace_path_from_settings():
    backend = _FakeBackend()
    kernel = _FakeKernel()
    settings = _settings()
    settings = RuntimeWorkerSettings(
        **{**settings.__dict__, "default_workspace_path": "/tmp/default-workspace"}
    )
    worker = ToolWorker(
        kernel=kernel,
        publisher=_FakePublisher(),
        settings=settings,
        backend_registry=ExecutionBackendRegistry([backend]),
    )

    asyncio.run(worker._process_tool_call(_tool_call_with_workspace_ref()))

    assert backend.submitted_specs
    assert backend.submitted_specs[0].execution_workspace is not None
    assert backend.submitted_specs[0].execution_workspace.path == "/tmp/default-workspace"


def test_agent_loop_worker_fails_claimed_step_when_budget_is_exhausted():
    publisher = _FakePublisher()
    step = RunStep(
        step_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        status="claimed",
        claimed_by_worker="agent-loop-worker",
    )
    failure_event = EventEnvelope(
        event_type="run.failed",
        workspace_id=step.workspace_id,
        thread_id=step.thread_id,
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="run", id=step.run_id),
        visibility="agents_only",
    )

    class _BudgetKernel:
        def __init__(self) -> None:
            self.claimed = False
            self.budget_checks: list[tuple[int, int]] = []

        async def claim_next_run_step(self, *, worker_id, lease_ttl_seconds):
            if self.claimed:
                return SimpleNamespace(step=None, context=None)
            self.claimed = True
            return SimpleNamespace(
                step=step,
                context=SimpleNamespace(run_step=step),
            )

        async def enforce_run_step_token_budget(
            self,
            *,
            step_id,
            worker_id,
            global_daily_token_cap,
            default_workspace_daily_token_cap,
        ):
            self.budget_checks.append(
                (global_daily_token_cap, default_workspace_daily_token_cap)
            )
            return SimpleNamespace(events=[failure_event])

    settings = RuntimeWorkerSettings(
        **{
            **_settings().__dict__,
            "global_daily_token_cap": 100,
            "workspace_daily_token_cap_default": 25,
        }
    )
    worker = AgentLoopWorker(
        kernel=_BudgetKernel(),
        publisher=publisher,
        settings=settings,
    )

    asyncio.run(worker._fill_capacity())

    assert worker._processing == {}
    assert publisher.published == [[failure_event]]


def test_reconciler_publishes_failure_and_requeue_events(monkeypatch):
    publisher = _FakePublisher()
    failure_event = EventEnvelope(
        event_type="run.failed",
        workspace_id=uuid4(),
        thread_id=uuid4(),
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="run", id=uuid4()),
        visibility="agents_only",
    )
    requeue_event = EventEnvelope(
        event_type="run_step.requeued",
        workspace_id=uuid4(),
        thread_id=uuid4(),
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="run_step", id=uuid4()),
        visibility="agents_only",
    )
    requeued_step = RunStep(
        step_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
    )
    requeued_tool_call = ToolCall(
        tool_call_id=uuid4(),
        run_id=uuid4(),
        run_step_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        tool_id=uuid4(),
        tool_name="repo_search",
        execution_spec=ExecutionSpec(
            invocation_id=uuid4(),
            handler_ref="repo_search",
        ).model_dump(mode="json"),
    )

    class _ReconcilingKernel:
        def __init__(self) -> None:
            self.requeued_batches: list[tuple[list[RunStep], list[ToolCall]]] = []

        async def reconcile_expired_execution_leases(self):
            return SimpleNamespace(
                run_steps=[requeued_step],
                tool_calls=[requeued_tool_call],
                events=[failure_event],
            )

        async def build_requeued_execution_events(self, run_steps, tool_calls):
            self.requeued_batches.append((run_steps, tool_calls))
            return [requeue_event]

    async def _cancel_after_first_sleep(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr("agent_runtime.workers.asyncio.sleep", _cancel_after_first_sleep)
    kernel = _ReconcilingKernel()
    reconciler = Reconciler(
        kernel=kernel,
        publisher=publisher,
        settings=_settings(),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(reconciler.run_forever())

    assert kernel.requeued_batches == [([requeued_step], [requeued_tool_call])]
    assert publisher.published == [[failure_event, requeue_event]]
