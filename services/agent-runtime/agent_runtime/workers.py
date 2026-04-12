from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

_CORE_COLLAB_DIR = Path(__file__).resolve().parents[3] / "services" / "core-collab"
if _CORE_COLLAB_DIR.is_dir():
    collab_path = str(_CORE_COLLAB_DIR)
    if collab_path not in sys.path:
        sys.path.insert(0, collab_path)

from core_collab import CollaborationKernel, CollaborationRepository  # noqa: E402
from open_talon_contracts.llm_engines import (  # noqa: E402
    LlmEngineRegistry,
    llm_engine_descriptor_from_provider_definition,
)
from open_talon_contracts.models import ExecutionSpec  # noqa: E402

from .config import RuntimeWorkerSettings
from .events import KafkaEventPublisher, KafkaWakeConsumer
from .execution import (
    DockerExecutionBackend,
    ExecutionBackendRegistry,
    LocalProcessExecutionBackend,
)
from .execution.utils import to_tool_call_result
from .runtime import (
    HttpEndpointExecutor,
    LangfuseRuntimeObserver,
    LocalOllamaExecutor,
)
from .llm_engines import (
    build_default_llm_engine_registry,
    resolve_llm_engine_for_context,
)
from .secrets import build_default_secret_resolver

logger = logging.getLogger(__name__)


class _HeartbeatTask:
    def __init__(self, callback, *, interval_seconds: int) -> None:
        self._callback = callback
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval_seconds)
                await self._callback()
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise


async def create_kernel(settings: RuntimeWorkerSettings) -> tuple[asyncpg.Pool, CollaborationKernel]:
    pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=10)
    repository = CollaborationRepository(pool)
    kernel = CollaborationKernel(repository)
    await kernel.setup_schema()
    return pool, kernel


class AgentLoopWorker:
    def __init__(
        self,
        *,
        kernel: CollaborationKernel,
        publisher: KafkaEventPublisher,
        settings: RuntimeWorkerSettings,
        engine_registry=None,
        secret_resolver=None,
    ) -> None:
        self._kernel = kernel
        self._publisher = publisher
        self._settings = settings
        self._observability = LangfuseRuntimeObserver.from_env()
        self._engine_registry = engine_registry or build_default_llm_engine_registry()
        self._secret_resolver = secret_resolver or build_default_secret_resolver()
        self._executors = {
            "local": LocalOllamaExecutor(
                timeout_seconds=settings.model_timeout_seconds,
                observability=self._observability,
            ),
            "remote": HttpEndpointExecutor(
                timeout_seconds=settings.model_timeout_seconds,
                endpoint_scope="remote",
                observability=self._observability,
                secret_resolver=self._secret_resolver,
            ),
            "system": HttpEndpointExecutor(
                timeout_seconds=settings.model_timeout_seconds,
                endpoint_scope="system",
                observability=self._observability,
                secret_resolver=self._secret_resolver,
            ),
        }
        self._processing: dict[UUID, asyncio.Task[None]] = {}
        self._wake = asyncio.Event()
        self._wake_consumer = (
            KafkaWakeConsumer(
                settings,
                topics=[
                    settings.kafka_agent_tasks_topic,
                    settings.kafka_agent_events_topic,
                ],
                group_suffix="agent-loop",
            )
            if settings.enable_kafka_wakeups
            else None
        )
        self._wake_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._wake_consumer is not None:
            await self._wake_consumer.start()
            self._wake_task = asyncio.create_task(self._watch_wake_events())

    async def stop(self) -> None:
        if self._wake_task is not None:
            self._wake_task.cancel()
            await asyncio.gather(self._wake_task, return_exceptions=True)
            self._wake_task = None
        if self._wake_consumer is not None:
            await self._wake_consumer.stop()
        pending = list(self._processing.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._processing.clear()

    async def run_forever(self) -> None:
        await self.start()
        try:
            while True:
                await self._fill_capacity()
                self._wake.clear()
                try:
                    await asyncio.wait_for(
                        self._wake.wait(),
                        timeout=self._settings.poll_interval_seconds,
                    )
                except TimeoutError:
                    continue
        finally:
            await self.stop()

    async def _fill_capacity(self) -> None:
        while len(self._processing) < self._settings.agent_step_worker_concurrency:
            claim = await self._kernel.claim_next_run_step(
                worker_id="agent-loop-worker",
                lease_ttl_seconds=self._settings.lease_ttl_seconds,
            )
            if claim.step is None or claim.context is None:
                break
            task = asyncio.create_task(self._process_step(claim.step.step_id, claim.context))
            self._processing[claim.step.step_id] = task
            task.add_done_callback(
                lambda done, step_id=claim.step.step_id: self._processing.pop(step_id, None)
            )

    async def _process_step(self, step_id, context) -> None:
        heartbeat = _HeartbeatTask(
            lambda: self._kernel.heartbeat_run_step(
                step_id=step_id,
                worker_id="agent-loop-worker",
                lease_ttl_seconds=self._settings.lease_ttl_seconds,
            ),
            interval_seconds=self._settings.lease_heartbeat_seconds,
        )
        await heartbeat.start()
        try:
            progress = await self._kernel.append_run_progress(
                context.run.run_id,
                context.run_step.system_agent_id if context.run_step is not None else context.routing.target_system_agent_id,
                f"Executing {context.system_agent.display_name}",
            )
            await self._publisher.publish(progress.events)
            resolved_context = await self._resolve_execution_context(context)
            executor = self._executors[resolved_context.system_agent.endpoint.kind]
            result = await executor.execute(resolved_context)
            if result.tool_calls:
                queued = await self._kernel.queue_tool_calls_for_run_step(
                    step_id,
                    "agent-loop-worker",
                    result.tool_calls,
                )
                await self._publisher.publish(queued.events)
            else:
                completion = await self._kernel.complete_run_step(
                    step_id,
                    "agent-loop-worker",
                    result,
                )
                await self._publisher.publish(completion.events)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception as exc:
            logger.exception("Agent loop worker failed step_id=%s", step_id)
            failure = await self._kernel.fail_run_step(
                step_id,
                "agent-loop-worker",
                str(exc),
            )
            await self._publisher.publish(failure.events)
        finally:
            await heartbeat.stop()

    async def _watch_wake_events(self) -> None:
        assert self._wake_consumer is not None
        async for _event in self._wake_consumer.events():
            self._wake.set()

    async def _resolve_execution_context(self, context):
        managed = [
            llm_engine_descriptor_from_provider_definition(item)
            for item in await self._kernel.list_llm_providers()
        ]
        registry = LlmEngineRegistry.merged(self._engine_registry.list(), managed)
        resolved = resolve_llm_engine_for_context(context, registry)
        metadata = dict(context.system_agent.metadata)
        if resolved.descriptor is not None:
            metadata["_resolved_llm_engine"] = resolved.descriptor.model_dump(mode="json")
        if (
            resolved.endpoint == context.system_agent.endpoint
            and metadata == context.system_agent.metadata
        ):
            return context
        system_agent = context.system_agent.model_copy(
            update={"endpoint": resolved.endpoint, "metadata": metadata}
        )
        return context.model_copy(update={"system_agent": system_agent})


class ToolWorker:
    def __init__(
        self,
        *,
        kernel: CollaborationKernel,
        publisher: KafkaEventPublisher,
        settings: RuntimeWorkerSettings,
        backend_registry: ExecutionBackendRegistry,
    ) -> None:
        self._kernel = kernel
        self._publisher = publisher
        self._settings = settings
        self._backend_registry = backend_registry
        self._processing: dict[UUID, asyncio.Task[None]] = {}
        self._wake = asyncio.Event()
        self._wake_consumer = (
            KafkaWakeConsumer(
                settings,
                topics=[settings.kafka_agent_tasks_topic],
                group_suffix="tool-worker",
            )
            if settings.enable_kafka_wakeups
            else None
        )
        self._wake_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._wake_consumer is not None:
            await self._wake_consumer.start()
            self._wake_task = asyncio.create_task(self._watch_wake_events())

    async def stop(self) -> None:
        if self._wake_task is not None:
            self._wake_task.cancel()
            await asyncio.gather(self._wake_task, return_exceptions=True)
            self._wake_task = None
        if self._wake_consumer is not None:
            await self._wake_consumer.stop()
        pending = list(self._processing.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._processing.clear()

    async def run_forever(self) -> None:
        await self.start()
        try:
            while True:
                await self._fill_capacity()
                self._wake.clear()
                try:
                    await asyncio.wait_for(
                        self._wake.wait(),
                        timeout=self._settings.poll_interval_seconds,
                    )
                except TimeoutError:
                    continue
        finally:
            await self.stop()

    async def _fill_capacity(self) -> None:
        while len(self._processing) < self._settings.tool_worker_concurrency:
            claim = await self._kernel.claim_next_tool_call(
                worker_id="tool-worker",
                lease_ttl_seconds=self._settings.lease_ttl_seconds,
                max_parallel_calls_per_run=self._settings.max_parallel_tool_calls_per_run,
                max_concurrent_calls_per_tool=self._settings.max_concurrent_calls_per_tool,
            )
            if claim.tool_call is None:
                break
            await self._publisher.publish(claim.events)
            task = asyncio.create_task(self._process_tool_call(claim.tool_call))
            self._processing[claim.tool_call.tool_call_id] = task
            task.add_done_callback(
                lambda done, tool_call_id=claim.tool_call.tool_call_id: self._processing.pop(
                    tool_call_id, None
                )
            )

    async def _process_tool_call(self, tool_call) -> None:
        tool_call_id = tool_call.tool_call_id
        heartbeat = _HeartbeatTask(
            lambda: self._kernel.heartbeat_tool_call(
                tool_call_id=tool_call_id,
                worker_id="tool-worker",
                lease_ttl_seconds=self._settings.lease_ttl_seconds,
            ),
            interval_seconds=self._settings.lease_heartbeat_seconds,
        )
        await heartbeat.start()
        handle = None
        try:
            spec = ExecutionSpec.model_validate(tool_call.execution_spec)
            if (
                spec.execution_workspace is not None
                and spec.execution_workspace.path is None
                and spec.execution_workspace.uri is None
                and self._settings.default_workspace_path is not None
            ):
                spec = spec.model_copy(
                    update={
                        "execution_workspace": spec.execution_workspace.model_copy(
                            update={"path": self._settings.default_workspace_path}
                        )
                    }
                )
            backend_kind = str(spec.metadata.get("backend_kind", "docker"))
            backend = self._backend_registry.resolve(backend_kind)
            handle = await backend.submit(spec)
            await self._kernel.update_tool_call_execution_handle(
                tool_call_id,
                "tool-worker",
                handle.handle,
            )
            deadline = time.monotonic() + spec.limits.timeout_seconds
            result: Any
            while True:
                result = await backend.poll(handle)
                if result.status == "running":
                    if time.monotonic() >= deadline:
                        await backend.cancel(
                            handle,
                            reason=f"Timed out after {spec.limits.timeout_seconds}s",
                        )
                        raise TimeoutError(
                            f"Tool execution timed out after {spec.limits.timeout_seconds}s"
                        )
                    await asyncio.sleep(0.5)
                    continue
                break
            result = await backend.collect(handle)
            tool_result = to_tool_call_result(result)
            if result.status == "completed":
                completion = await self._kernel.complete_tool_call(
                    tool_call_id,
                    "tool-worker",
                    tool_result,
                )
            else:
                completion = await self._kernel.fail_tool_call(
                    tool_call_id,
                    "tool-worker",
                    tool_result.error or "Tool execution failed",
                )
            await self._publisher.publish(completion.events)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            if handle is not None:
                try:
                    await backend.cancel(handle, reason="Worker shutdown")
                except Exception:  # pragma: no cover - best effort cleanup
                    logger.exception("Tool worker failed to cancel tool_call_id=%s", tool_call_id)
            raise
        except Exception as exc:
            logger.exception("Tool worker failed tool_call_id=%s", tool_call_id)
            failure = await self._kernel.fail_tool_call(
                tool_call_id,
                "tool-worker",
                str(exc),
            )
            await self._publisher.publish(failure.events)
        finally:
            await heartbeat.stop()

    async def _watch_wake_events(self) -> None:
        assert self._wake_consumer is not None
        async for _event in self._wake_consumer.events():
            self._wake.set()


class Reconciler:
    def __init__(
        self,
        *,
        kernel: CollaborationKernel,
        publisher: KafkaEventPublisher,
        settings: RuntimeWorkerSettings,
    ) -> None:
        self._kernel = kernel
        self._publisher = publisher
        self._settings = settings

    async def run_forever(self) -> None:
        while True:
            steps, tool_calls = await self._kernel.reconcile_expired_execution_leases()
            if steps or tool_calls:
                events = await self._kernel.build_requeued_execution_events(steps, tool_calls)
                if events:
                    await self._publisher.publish(events)
                logger.warning(
                    "Requeued expired execution leases run_steps=%s tool_calls=%s",
                    len(steps),
                    len(tool_calls),
                )
            await asyncio.sleep(self._settings.reconcile_interval_seconds)


def build_execution_backend_registry(settings: RuntimeWorkerSettings) -> ExecutionBackendRegistry:
    return ExecutionBackendRegistry(
        [
            DockerExecutionBackend(execution_root=settings.execution_root),
            LocalProcessExecutionBackend(execution_root=settings.execution_root),
        ]
    )
