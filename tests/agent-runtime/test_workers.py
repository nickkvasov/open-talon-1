from __future__ import annotations

import asyncio
import os
import sys
from uuid import uuid4

_AGENT_RUNTIME_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/agent-runtime")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
for path in (_AGENT_RUNTIME_DIR, _CONTRACTS_DIR, _CORE_COLLAB_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from agent_runtime.config import RuntimeWorkerSettings
from agent_runtime.events import route_event_topic
from agent_runtime.execution.registry import ExecutionBackendRegistry
from agent_runtime.workers import ToolWorker
from open_talon_contracts.models import (
    ActorRef,
    EventEnvelope,
    ExecutionHandle,
    ExecutionResult,
    ExecutionSpec,
    ExecutionWorkspaceRef,
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
        enable_kafka_wakeups=False,
        execution_root="/tmp/open-talon-executions",
        default_workspace_path=None,
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
