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
from open_talon_contracts.models import AuditEventDraft, ExecutionSpec, ParticipantInput  # noqa: E402
from open_talon_contracts.observability import (  # noqa: E402
    ObservabilityProvider,
    build_observability_provider_from_env,
)
from open_talon_contracts.telemetry import TelemetryContext, telemetry_metadata  # noqa: E402

from .config import RuntimeWorkerSettings
from .events import KafkaEventPublisher, KafkaWakeConsumer
from .execution import (
    DockerExecutionBackend,
    ExecutionBackendRegistry,
    LocalProcessExecutionBackend,
    McpExecutionBackend,
)
from .execution.utils import to_tool_call_result
from .runtime import RuntimeExecutionManager, is_retryable_llm_provider_error

logger = logging.getLogger(__name__)


async def _record_runtime_audit(
    kernel: CollaborationKernel,
    *,
    workspace_id: UUID,
    thread_id: UUID,
    action_category: str,
    action_name: str,
    outcome: str,
    system_agent_id: UUID | None = None,
    error: Exception | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    message = str(error) if error is not None else None
    try:
        await kernel.record_audit_event(
            AuditEventDraft(
                scope_type="thread",
                workspace_id=workspace_id,
                thread_id=thread_id,
                actor_type="agent" if system_agent_id is not None else "system",
                actor_id=system_agent_id,
                system_agent_id=system_agent_id,
                source_service="agent-runtime",
                source_component="worker",
                action_category=action_category,
                action_name=action_name,
                outcome=outcome,
                error_class=error.__class__.__name__ if isinstance(error, Exception) else None,
                error_message_redacted=message[:512] if message else None,
                metadata=metadata or {},
                chain_partition=f"workspace:{workspace_id}",
            )
        )
    except Exception:
        logger.exception("Failed to record runtime audit event action_name=%s", action_name)


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
    repository = CollaborationRepository(
        pool,
        communication_log_dir=settings.communication_log_dir,
    )
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
        observability: ObservabilityProvider | None = None,
    ) -> None:
        self._kernel = kernel
        self._publisher = publisher
        self._settings = settings
        self._execution = RuntimeExecutionManager(
            model_timeout_seconds=settings.model_timeout_seconds,
            observability=observability,
            engine_registry=engine_registry,
            secret_resolver=secret_resolver,
        )
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
        self._execution.flush()

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
            budget_failure = await self._kernel.enforce_run_step_token_budget(
                step_id=claim.step.step_id,
                worker_id="agent-loop-worker",
                global_daily_token_cap=self._settings.global_daily_token_cap,
                default_workspace_daily_token_cap=self._settings.workspace_daily_token_cap_default,
            )
            if budget_failure is not None:
                if budget_failure.events:
                    await self._publisher.publish(budget_failure.events)
                continue
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
            resolved_context = await self._execution.resolve_context(self._kernel, context)
            executor = self._execution.executor_for(resolved_context)
            result = await executor.execute(resolved_context)
            scratch_content = (result.summary or result.message or "").strip()
            if scratch_content:
                await self._kernel.append_run_scratch(
                    run_id=resolved_context.run.run_id,
                    actor_input=ParticipantInput(
                        participant_id=resolved_context.participant.participant_id,
                        participant_type=resolved_context.participant.participant_type,
                        user_id=resolved_context.participant.user_id,
                        display_name=resolved_context.participant.display_name,
                        description=resolved_context.participant.description,
                        roles=list(resolved_context.participant.roles),
                        capabilities=list(resolved_context.participant.capabilities),
                        visibility_scope=resolved_context.participant.visibility_scope,
                    ),
                    entry_type="agent_step_summary",
                    content=scratch_content,
                    summary=result.summary or "Agent model step summary",
                    metadata={
                        "stop_reason": result.stop_reason,
                        "tool_call_count": len(result.tool_calls),
                        "source": "agent-loop-worker",
                    },
                )
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
            await _record_runtime_audit(
                self._kernel,
                workspace_id=context.workspace.workspace_id,
                thread_id=context.thread.thread_id,
                action_category="worker",
                action_name="worker.exception",
                outcome="error",
                system_agent_id=context.system_agent.agent_id,
                error=exc,
                metadata={
                    "step_id": str(step_id),
                    "run_id": str(context.run.run_id),
                    "task_id": str(context.task.task_id),
                    "worker_id": "agent-loop-worker",
                },
            )
            if is_retryable_llm_provider_error(exc):
                try:
                    requeued = await self._kernel.requeue_run_step_for_retry(
                        step_id,
                        "agent-loop-worker",
                        str(exc),
                        retry_after_seconds=self._settings.provider_failure_retry_seconds,
                        reason="llm_provider_unavailable",
                    )
                    await self._publisher.publish(requeued.events)
                    return
                except Exception:
                    logger.exception(
                        "Failed to requeue retryable provider failure step_id=%s",
                        step_id,
                    )
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

class ToolWorker:
    def __init__(
        self,
        *,
        kernel: CollaborationKernel,
        publisher: KafkaEventPublisher,
        settings: RuntimeWorkerSettings,
        backend_registry: ExecutionBackendRegistry,
        observability: ObservabilityProvider | None = None,
    ) -> None:
        self._kernel = kernel
        self._publisher = publisher
        self._settings = settings
        self._backend_registry = backend_registry
        self._backend_registry.register(McpExecutionBackend(kernel=kernel))
        self._observability = observability or build_observability_provider_from_env(
            service_name="agent-runtime",
            legacy_env_prefix="AGENT_RUNTIME",
        )
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
        self._observability.flush()

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
        observation = None
        observation_cm = None
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
            observation_context = TelemetryContext(
                source_service="agent-runtime",
                source_component="tool-worker",
                workspace_id=tool_call.workspace_id,
                thread_id=tool_call.thread_id,
                system_agent_id=tool_call.system_agent_id,
                task_id=tool_call.task_id,
                run_id=tool_call.run_id,
                run_step_id=tool_call.run_step_id,
                tool_call_id=tool_call.tool_call_id,
                metadata={
                    "tool_id": str(tool_call.tool_id),
                    "tool_name": tool_call.tool_name,
                    "worker_id": "tool-worker",
                    "backend_kind": backend_kind,
                    "handler_ref": spec.handler_ref,
                },
            )
            observation_cm = self._observability.start_span(
                name="tool-call-execution",
                input={
                    "tool_call_id": str(tool_call.tool_call_id),
                    "tool_name": tool_call.tool_name,
                    "inline_payload": spec.inline_payload,
                },
                metadata=telemetry_metadata(observation_context),
            )
            observation = observation_cm.__enter__()
            backend = self._backend_registry.resolve(backend_kind)
            handle = await backend.submit(spec)
            await self._kernel.update_tool_call_execution_handle(
                tool_call_id,
                "tool-worker",
                handle.handle,
            )
            observation.update(execution_handle=handle.handle, status="submitted")
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
            observation.update(
                status=result.status,
                output=tool_result.model_dump(mode="json"),
            )
            if result.status == "completed":
                completion = await self._kernel.complete_tool_call(
                    tool_call_id,
                    "tool-worker",
                    tool_result,
                )
            elif result.status == "pending_approval":
                completion = await self._kernel.mark_tool_call_pending_external_approval(
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
            if observation is not None:
                observation.update(status="failed", error=str(exc))
            await _record_runtime_audit(
                self._kernel,
                workspace_id=tool_call.workspace_id,
                thread_id=tool_call.thread_id,
                action_category="execution",
                action_name="execution.backend_failed",
                outcome="failure",
                system_agent_id=tool_call.system_agent_id,
                error=exc,
                metadata={
                    "tool_call_id": str(tool_call_id),
                    "run_id": str(tool_call.run_id),
                    "task_id": str(tool_call.task_id),
                    "worker_id": "tool-worker",
                },
            )
            failure = await self._kernel.fail_tool_call(
                tool_call_id,
                "tool-worker",
                str(exc),
            )
            await self._publisher.publish(failure.events)
        finally:
            if observation_cm is not None:
                observation_cm.__exit__(None, None, None)
            self._observability.flush()
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
            reconciliation = await self._kernel.reconcile_expired_execution_leases()
            if reconciliation.run_steps or reconciliation.tool_calls or reconciliation.events:
                events = list(reconciliation.events)
                events.extend(
                    await self._kernel.build_requeued_execution_events(
                        reconciliation.run_steps,
                        reconciliation.tool_calls,
                    )
                )
                if events:
                    await self._publisher.publish(events)
                logger.warning(
                    "Reconciled expired execution leases run_steps=%s tool_calls=%s failure_events=%s",
                    len(reconciliation.run_steps),
                    len(reconciliation.tool_calls),
                    len(reconciliation.events),
                )
            await asyncio.sleep(self._settings.reconcile_interval_seconds)


def build_execution_backend_registry(settings: RuntimeWorkerSettings) -> ExecutionBackendRegistry:
    return ExecutionBackendRegistry(
        [
            DockerExecutionBackend(execution_root=settings.execution_root),
            LocalProcessExecutionBackend(execution_root=settings.execution_root),
        ]
    )
