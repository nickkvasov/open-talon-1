from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
import logging
from uuid import UUID, uuid4

from .contracts import (
    ActorRef,
    AgentArtifactDraft,
    AgentExecutionContext,
    AgentRunResult,
    AgentTaskRouting,
    EventEnvelope,
    Membership,
    ParticipantProfile,
    Run,
    RunStep,
    StopReason,
    TargetRef,
    Task,
    TimelineMessage,
    ToolGenerationRequestDetail,
    Workspace,
    WorkspaceTool,
)
from .repository import CollaborationRepository
from .results import RunCommandResult, RunStepCommandResult, TaskCommandResult

logger = logging.getLogger(__name__)


class RuntimeExecutionService:
    def __init__(
        self,
        *,
        repository: CollaborationRepository,
        task_routing: Callable[[Task], AgentTaskRouting],
        resolve_agent_participant: Callable[..., Awaitable[ParticipantProfile | None]],
        require_run_participant: Callable[..., Awaitable[ParticipantProfile]],
        resolve_run_for_context: Callable[..., Awaitable[Run]],
        advertise_workspace_tools: Callable[[ParticipantProfile, list[WorkspaceTool]], ParticipantProfile],
        filter_visible_messages: Callable[..., list[TimelineMessage]],
        filter_visible_memory_entries: Callable[..., list],
        role_definitions_from_workspace: Callable[[Workspace], list],
        build_thread_event: Callable[..., Awaitable[EventEnvelope]],
        now: Callable[[], datetime],
        utc_day_window: Callable[[datetime], tuple[datetime, datetime]],
        workspace_daily_token_cap: Callable[[Workspace, int], int],
        run_output_from_result: Callable[[AgentRunResult], dict[str, object]],
        artifact_from_draft: Callable[..., object],
        agent_message_from_result: Callable[..., TimelineMessage],
        stop_reason_returns_to_thread: Callable[[StopReason], bool],
        fail_run_step: Callable[..., Awaitable[RunCommandResult]],
    ) -> None:
        self._repository = repository
        self._task_routing = task_routing
        self._resolve_agent_participant = resolve_agent_participant
        self._require_run_participant = require_run_participant
        self._resolve_run_for_context = resolve_run_for_context
        self._advertise_workspace_tools = advertise_workspace_tools
        self._filter_visible_messages = filter_visible_messages
        self._filter_visible_memory_entries = filter_visible_memory_entries
        self._role_definitions_from_workspace = role_definitions_from_workspace
        self._build_thread_event = build_thread_event
        self._now = now
        self._utc_day_window = utc_day_window
        self._workspace_daily_token_cap = workspace_daily_token_cap
        self._run_output_from_result = run_output_from_result
        self._artifact_from_draft = artifact_from_draft
        self._agent_message_from_result = agent_message_from_result
        self._stop_reason_returns_to_thread = stop_reason_returns_to_thread
        self._fail_run_step = fail_run_step

    async def list_pending_tasks_for_system_agent(
        self,
        system_agent_id: UUID,
        *,
        limit: int = 10,
    ) -> list[Task]:
        logger.debug(
            "RuntimeExecutionService list_pending_tasks_for_system_agent system_agent_id=%s limit=%s",
            system_agent_id,
            limit,
        )
        return await self._repository.list_pending_tasks_for_system_agent(
            system_agent_id,
            limit=limit,
        )

    async def claim_task_for_system_agent(
        self,
        task_id: UUID,
        system_agent_id: UUID,
    ) -> TaskCommandResult:
        logger.debug(
            "RuntimeExecutionService claim_task_for_system_agent task_id=%s system_agent_id=%s",
            task_id,
            system_agent_id,
        )
        task = await self._repository.fetch_task(task_id)
        if task is None:
            raise KeyError(f"Task {task_id} not found")
        routing = self._task_routing(task)
        if routing.target_system_agent_id != system_agent_id:
            raise ValueError(
                f"Task {task_id} is not targeted to system agent {system_agent_id}"
            )
        workspace = await self._repository.fetch_workspace(task.workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {task.workspace_id} not found")
        thread = await self._repository.fetch_thread(task.thread_id)
        if thread is None:
            raise KeyError(f"Thread {task.thread_id} not found")
        system_agent = await self._repository.fetch_system_agent(system_agent_id)
        if system_agent is None:
            raise KeyError(f"System agent {system_agent_id} not found")
        participant = await self._resolve_agent_participant(
            workspace_id=task.workspace_id,
            system_agent_id=system_agent_id,
            routing=routing,
        )
        if participant is None:
            raise KeyError(
                f"System agent {system_agent_id} is not attached to workspace {task.workspace_id}"
            )

        now = self._now()
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                claimed_task = await self._repository.claim_task(
                    conn,
                    task_id=task_id,
                    participant_id=participant.participant_id,
                    updated_at=now,
                )
                if claimed_task is None:
                    raise ValueError(f"Task {task_id} is no longer claimable")
                run = Run(
                    run_id=uuid4(),
                    workspace_id=claimed_task.workspace_id,
                    thread_id=claimed_task.thread_id,
                    task_id=claimed_task.task_id,
                    participant_id=participant.participant_id,
                    status="started",
                    correlation_id=claimed_task.correlation_id,
                    causation_id=claimed_task.task_id,
                    created_at=now,
                    updated_at=now,
                    metadata={
                        "system_agent_id": str(system_agent_id),
                        "participant_id": str(participant.participant_id),
                        "endpoint_kind": system_agent.endpoint.kind,
                    },
                )
                await self._repository.upsert_run(conn, run)
                initial_step = RunStep(
                    step_id=uuid4(),
                    run_id=run.run_id,
                    task_id=claimed_task.task_id,
                    workspace_id=claimed_task.workspace_id,
                    thread_id=claimed_task.thread_id,
                    system_agent_id=system_agent_id,
                    step_index=0,
                    status="created",
                    submitted_at=now,
                    created_at=now,
                    updated_at=now,
                    metadata={
                        "participant_id": str(participant.participant_id),
                    },
                )
                await self._repository.upsert_run_step(conn, initial_step)
                actor = ActorRef(type="agent", id=participant.participant_id)
                events = [
                    await self._build_thread_event(
                        conn,
                        claimed_task.workspace_id,
                        claimed_task.thread_id,
                        "task.claimed",
                        actor=actor,
                        target=TargetRef(type="task", id=claimed_task.task_id),
                        payload={
                            "task_id": str(claimed_task.task_id),
                            "claimed_by": str(participant.participant_id),
                            "system_agent_id": str(system_agent_id),
                        },
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=claimed_task.correlation_id,
                        causation_id=claimed_task.causation_id,
                    ),
                    await self._build_thread_event(
                        conn,
                        claimed_task.workspace_id,
                        claimed_task.thread_id,
                        "run.started",
                        actor=actor,
                        target=TargetRef(type="run", id=run.run_id),
                        payload=run.model_dump(mode="json"),
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=claimed_task.correlation_id,
                        causation_id=claimed_task.task_id,
                    ),
                ]
                for event in events:
                    await self._repository.record_event(conn, event)

        context = await self.build_agent_execution_context(task_id, system_agent_id, run.run_id)
        return TaskCommandResult(task=claimed_task, run=run, context=context, events=events)

    async def build_agent_execution_context(
        self,
        task_id: UUID,
        system_agent_id: UUID,
        run_id: UUID | None = None,
    ) -> AgentExecutionContext:
        logger.debug(
            "RuntimeExecutionService build_agent_execution_context task_id=%s system_agent_id=%s run_id=%s",
            task_id,
            system_agent_id,
            run_id,
        )
        task = await self._repository.fetch_task(task_id)
        if task is None:
            raise KeyError(f"Task {task_id} not found")
        routing = self._task_routing(task)
        if routing.target_system_agent_id != system_agent_id:
            raise ValueError(
                f"Task {task_id} is not targeted to system agent {system_agent_id}"
            )
        system_agent = await self._repository.fetch_system_agent(system_agent_id)
        if system_agent is None:
            raise KeyError(f"System agent {system_agent_id} not found")
        workspace = await self._repository.fetch_workspace(task.workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {task.workspace_id} not found")
        thread = await self._repository.fetch_thread(task.thread_id)
        if thread is None:
            raise KeyError(f"Thread {task.thread_id} not found")
        participant = await self._resolve_agent_participant(
            workspace_id=task.workspace_id,
            system_agent_id=system_agent_id,
            routing=routing,
        )
        if participant is None:
            raise KeyError(
                f"System agent {system_agent_id} is not attached to workspace {task.workspace_id}"
            )
        run = await self._resolve_run_for_context(task, participant, run_id)
        workspace_tools = await self._repository.list_workspace_tools(task.workspace_id)
        workspace_mcp_servers = await self._optional_repository_list(
            "list_workspace_mcp_servers",
            task.workspace_id,
        )
        workspace_mcp_tools = await self._optional_repository_list(
            "list_workspace_mcp_tools",
            task.workspace_id,
        )
        workspace_mcp_resources = await self._optional_repository_list(
            "list_workspace_mcp_resources",
            task.workspace_id,
        )
        workspace_mcp_prompts = await self._optional_repository_list(
            "list_workspace_mcp_prompts",
            task.workspace_id,
        )
        internal_tools = await self._repository.list_agent_internal_tools(system_agent_id)
        internal_mcp_servers = await self._optional_repository_list(
            "list_agent_internal_mcp_servers",
            system_agent_id,
        )
        internal_mcp_tools = await self._optional_repository_list(
            "list_agent_internal_mcp_tools",
            system_agent_id,
        )
        participants = [
            self._advertise_workspace_tools(item, workspace_tools)
            for item in await self._repository.list_participants(task.workspace_id)
        ]
        run_memory = await self._repository.list_memory_entries_for_scope(
            scope="run",
            workspace_id=task.workspace_id,
            run_id=run.run_id,
            state="scratch",
        )
        thread_memory = await self._repository.list_memory_entries_for_scope(
            scope="thread",
            workspace_id=task.workspace_id,
            thread_id=task.thread_id,
            state="confirmed",
        )
        workspace_memory = await self._repository.list_memory_entries_for_scope(
            scope="workspace",
            workspace_id=task.workspace_id,
            state="confirmed",
        )
        messages = await self._repository.list_timeline_messages(task.thread_id)
        trigger_message = (
            await self._repository.fetch_message(routing.trigger_message_id)
            if routing.trigger_message_id is not None
            else None
        )
        visible_messages = self._filter_visible_messages(
            messages,
            viewer=participant,
            sequence_ceiling=routing.sequence_ceiling,
        )
        visible_run_memory = self._filter_visible_memory_entries(
            run_memory,
            viewer=participant,
        )
        visible_thread_memory = self._filter_visible_memory_entries(
            thread_memory,
            viewer=participant,
        )
        visible_workspace_memory = self._filter_visible_memory_entries(
            workspace_memory,
            viewer=participant,
        )
        if not self._memory_scope_enabled(system_agent, "run"):
            visible_run_memory = []
        if not self._memory_scope_enabled(system_agent, "thread"):
            visible_thread_memory = []
        if not self._memory_scope_enabled(system_agent, "workspace"):
            visible_workspace_memory = []
        tool_results = await self._repository.list_completed_tool_calls_for_run(run.run_id)
        interaction_requests = []
        request_id = task.metadata.get("request_id")
        if isinstance(request_id, str):
            detail = await self._repository.get_interaction_request_detail(UUID(request_id))
            if detail is not None:
                interaction_requests.append(detail)
        tool_generation_request = None
        tool_generation_request_id = task.metadata.get("tool_generation_request_id")
        if isinstance(tool_generation_request_id, str):
            request = await self._repository.fetch_tool_generation_request(
                UUID(tool_generation_request_id)
            )
            if request is not None:
                revisions = await self._repository.list_tool_generation_revisions(
                    request.request_id
                )
                tool_generation_request = ToolGenerationRequestDetail(
                    request=request,
                    revisions=revisions,
                )
        task_instructions = task.metadata.get("task_instructions")
        if not isinstance(task_instructions, list) or not all(
            isinstance(item, str) for item in task_instructions
        ):
            task_instructions = []
        return AgentExecutionContext(
            workspace=workspace,
            workspace_harness=workspace.harness,
            thread=thread,
            task=task,
            run=run,
            routing=routing,
            system_agent=system_agent,
            agent_harness=system_agent.harness,
            participant=self._advertise_workspace_tools(participant, workspace_tools),
            participants=participants,
            role_definitions=self._role_definitions_from_workspace(workspace),
            workspace_tools=workspace_tools,
            workspace_mcp_servers=workspace_mcp_servers,
            workspace_mcp_tools=workspace_mcp_tools,
            workspace_mcp_resources=workspace_mcp_resources,
            workspace_mcp_prompts=workspace_mcp_prompts,
            internal_tools=internal_tools,
            internal_mcp_servers=internal_mcp_servers,
            internal_mcp_tools=internal_mcp_tools,
            task_instructions=task_instructions,
            messages=visible_messages,
            interaction_requests=interaction_requests,
            tool_generation_request=tool_generation_request,
            run_memory=visible_run_memory,
            thread_memory=visible_thread_memory,
            workspace_memory=visible_workspace_memory,
            trigger_message=trigger_message,
            sequence_ceiling=routing.sequence_ceiling or 0,
            thread_reply_contract=system_agent.interaction_contract,
            tool_results=tool_results,
        )

    @staticmethod
    def _memory_scope_enabled(system_agent, scope: str) -> bool:
        harness = system_agent.harness
        if harness is None:
            return True
        policy = harness.memory_policy
        if scope == "run":
            return policy.use_run_memory
        if scope == "thread":
            return policy.use_thread_memory
        if scope == "workspace":
            return policy.use_workspace_memory
        return True

    async def _optional_repository_list(self, method_name: str, *args):
        method = getattr(self._repository, method_name, None)
        if method is None:
            return []
        return await method(*args)

    async def build_agent_execution_context_for_run_step(
        self,
        step_id: UUID,
    ) -> AgentExecutionContext:
        step = await self._repository.fetch_run_step(step_id)
        if step is None:
            raise KeyError(f"Run step {step_id} not found")
        context = await self.build_agent_execution_context(
            step.task_id,
            step.system_agent_id,
            step.run_id,
        )
        return context.model_copy(update={"run_step": step})

    async def enforce_run_step_token_budget(
        self,
        *,
        step_id: UUID,
        worker_id: str,
        global_daily_token_cap: int,
        default_workspace_daily_token_cap: int,
    ) -> RunCommandResult | None:
        if global_daily_token_cap <= 0 and default_workspace_daily_token_cap <= 0:
            return None
        step = await self._repository.fetch_run_step(step_id)
        if step is None:
            raise KeyError(f"Run step {step_id} not found")
        if step.claimed_by_worker != worker_id:
            raise ValueError(f"Run step {step_id} is not claimed by worker {worker_id}")
        workspace = await self._repository.fetch_workspace(step.workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {step.workspace_id} not found")
        day_start, day_end = self._utc_day_window(self._now())
        if global_daily_token_cap > 0:
            global_total = await self._repository.get_global_token_total(
                day_start=day_start,
                day_end=day_end,
            )
            if global_total >= global_daily_token_cap:
                return await self._fail_run_step(
                    step_id,
                    worker_id,
                    f"Global daily token cap exceeded ({global_total}/{global_daily_token_cap})",
                    stop_reason="budget_exhausted",
                )
        workspace_cap = self._workspace_daily_token_cap(
            workspace,
            default_workspace_daily_token_cap,
        )
        if workspace_cap > 0:
            workspace_total = await self._repository.get_workspace_token_total(
                workspace_id=workspace.workspace_id,
                day_start=day_start,
                day_end=day_end,
            )
            if workspace_total >= workspace_cap:
                return await self._fail_run_step(
                    step_id,
                    worker_id,
                    f"Workspace daily token cap exceeded ({workspace_total}/{workspace_cap})",
                    stop_reason="budget_exhausted",
                )
        return None

    async def get_runtime_overview(
        self,
        *,
        organization_id: UUID | None = None,
    ) -> dict[str, object]:
        now = self._now()
        since = now - timedelta(hours=24)
        day_start, day_end = self._utc_day_window(now)
        stats = await self._repository.get_runtime_queue_stats(
            now=now,
            since=since,
            organization_id=organization_id,
        )
        return {
            "tasks": {
                "pending": int(stats.get("tasks_pending") or 0),
                "claimed": int(stats.get("tasks_claimed") or 0),
            },
            "run_steps": {
                "pending": int(stats.get("run_steps_pending") or 0),
                "claimed": int(stats.get("run_steps_claimed") or 0),
            },
            "tool_calls": {
                "pending": int(stats.get("tool_calls_pending") or 0),
                "claimed": int(stats.get("tool_calls_claimed") or 0),
            },
            "failed_last_24h": {
                "tasks": int(stats.get("tasks_failed_last_24h") or 0),
                "run_steps": int(stats.get("run_steps_failed_last_24h") or 0),
                "tool_calls": int(stats.get("tool_calls_failed_last_24h") or 0),
            },
            "oldest_pending_age_seconds": {
                "run_steps": (
                    int(stats["oldest_run_step_pending_age_seconds"])
                    if stats.get("oldest_run_step_pending_age_seconds") is not None
                    else None
                ),
                "tool_calls": (
                    int(stats["oldest_tool_call_pending_age_seconds"])
                    if stats.get("oldest_tool_call_pending_age_seconds") is not None
                    else None
                ),
            },
            "token_totals": {
                "global_total_tokens": await self._repository.get_global_token_total(
                    day_start=day_start,
                    day_end=day_end,
                    organization_id=organization_id,
                ),
                "by_workspace": await self._repository.list_workspace_token_totals(
                    day_start=day_start,
                    day_end=day_end,
                    organization_id=organization_id,
                ),
            },
        }

    async def claim_next_run_step(
        self,
        *,
        worker_id: str,
        lease_ttl_seconds: int,
    ) -> RunStepCommandResult:
        now = self._now()
        step = await self._repository.claim_next_run_step(
            worker_id=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_ttl_seconds),
            now=now,
        )
        if step is None:
            return RunStepCommandResult()
        run = await self._repository.fetch_run(step.run_id)
        if run is None:
            raise KeyError(f"Run {step.run_id} not found")
        task = await self._repository.fetch_task(step.task_id)
        if task is None:
            raise KeyError(f"Task {step.task_id} not found")
        context = await self.build_agent_execution_context_for_run_step(step.step_id)
        return RunStepCommandResult(
            step=step,
            run=run,
            task=task,
            context=context,
        )

    async def append_run_progress(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        content: str,
    ) -> RunCommandResult:
        logger.debug(
            "RuntimeExecutionService append_run_progress run_id=%s system_agent_id=%s content_len=%s",
            run_id,
            system_agent_id,
            len(content),
        )
        run = await self._repository.fetch_run(run_id)
        if run is None:
            raise KeyError(f"Run {run_id} not found")
        task = await self._repository.fetch_task(run.task_id)
        if task is None:
            raise KeyError(f"Task {run.task_id} not found")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=system_agent_id,
        )
        now = self._now()
        updated_run = run.model_copy(
            update={
                "status": "progressing",
                "updated_at": now,
                "metadata": {**run.metadata, "last_progress": content},
            }
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run(conn, updated_run)
                event = await self._build_thread_event(
                    conn,
                    updated_run.workspace_id,
                    updated_run.thread_id,
                    "run.progressed",
                    actor=actor,
                    target=TargetRef(type="run", id=updated_run.run_id),
                    payload={"run_id": str(updated_run.run_id), "content": content},
                    visibility="agents_only",
                    timestamp=now,
                    correlation_id=updated_run.correlation_id,
                    causation_id=updated_run.task_id,
                )
                await self._repository.record_event(conn, event)
        return RunCommandResult(run=updated_run, task=task, events=[event])

    async def complete_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        result: AgentRunResult,
    ) -> RunCommandResult:
        logger.debug(
            "RuntimeExecutionService complete_run run_id=%s system_agent_id=%s stop_reason=%s has_message=%s artifact_count=%s",
            run_id,
            system_agent_id,
            result.stop_reason,
            bool(result.message),
            len(result.artifacts),
        )
        run = await self._repository.fetch_run(run_id)
        if run is None:
            raise KeyError(f"Run {run_id} not found")
        task = await self._repository.fetch_task(run.task_id)
        if task is None:
            raise KeyError(f"Task {run.task_id} not found")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=system_agent_id,
        )
        now = self._now()
        updated_run = run.model_copy(
            update={
                "status": "completed",
                "output": self._run_output_from_result(result),
                "updated_at": now,
                "metadata": {
                    **run.metadata,
                    "stop_reason": result.stop_reason,
                    **result.metadata,
                },
            }
        )
        updated_task = task.model_copy(
            update={
                "status": "completed",
                "claimed_by": participant.participant_id,
                "updated_at": now,
                "metadata": {
                    **task.metadata,
                    "stop_reason": result.stop_reason,
                    "completed_run_id": str(updated_run.run_id),
                },
            }
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        artifacts = [
            self._artifact_from_draft(
                draft,
                task=updated_task,
                run=updated_run,
                timestamp=now,
            )
            for draft in result.artifacts
        ]
        reply_policy = task.metadata.get("thread_reply_policy")
        suppress_thread_reply = (
            isinstance(reply_policy, dict) and reply_policy.get("mode") == "suppress"
        ) or task.metadata.get("suppress_thread_reply") is True
        message = (
            self._agent_message_from_result(
                result,
                task=updated_task,
                participant=participant,
                timestamp=now,
            )
            if self._stop_reason_returns_to_thread(result.stop_reason)
            and result.message
            and not suppress_thread_reply
            else None
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run(conn, updated_run)
                await self._repository.upsert_task(conn, updated_task)
                membership = await self._repository.fetch_active_membership(
                    conn,
                    thread_id=updated_task.thread_id,
                    participant_id=participant.participant_id,
                )
                if membership is None:
                    membership = Membership(
                        membership_id=uuid4(),
                        workspace_id=updated_task.workspace_id,
                        thread_id=updated_task.thread_id,
                        participant_id=participant.participant_id,
                        role="agent",
                        permissions=["post_messages"],
                        joined_at=now,
                    )
                    await self._repository.upsert_membership(conn, membership)
                events = [
                    await self._build_thread_event(
                        conn,
                        updated_run.workspace_id,
                        updated_run.thread_id,
                        "run.completed",
                        actor=actor,
                        target=TargetRef(type="run", id=updated_run.run_id),
                        payload={
                            "run_id": str(updated_run.run_id),
                            "output": updated_run.output,
                            "stop_reason": result.stop_reason,
                        },
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=updated_run.correlation_id,
                        causation_id=updated_run.task_id,
                    ),
                    await self._build_thread_event(
                        conn,
                        updated_task.workspace_id,
                        updated_task.thread_id,
                        "task.completed",
                        actor=actor,
                        target=TargetRef(type="task", id=updated_task.task_id),
                        payload={
                            "task_id": str(updated_task.task_id),
                            "run_id": str(updated_run.run_id),
                            "stop_reason": result.stop_reason,
                        },
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=updated_task.correlation_id,
                        causation_id=updated_task.task_id,
                    ),
                ]
                if message is not None:
                    message.sequence = await self._repository.next_thread_sequence(
                        conn,
                        message.thread_id,
                    )
                    await self._repository.upsert_message(conn, message)
                    events.append(
                        EventEnvelope(
                            event_type="message.created",
                            workspace_id=message.workspace_id,
                            thread_id=message.thread_id,
                            actor=message.actor,
                            target=TargetRef(type="message", id=message.message_id),
                            visibility=message.visibility,
                            correlation_id=message.correlation_id,
                            causation_id=message.causation_id,
                            sequence=message.sequence,
                            timestamp=now,
                            payload=message.model_dump(mode="json"),
                        )
                    )
                for artifact in artifacts:
                    await self._repository.upsert_artifact(conn, artifact)
                    events.append(
                        await self._build_thread_event(
                            conn,
                            artifact.workspace_id,
                            artifact.thread_id,
                            "artifact.created",
                            actor=actor,
                            target=TargetRef(type="artifact", id=artifact.artifact_id),
                            payload=artifact.model_dump(mode="json"),
                            visibility=artifact.visibility,
                            timestamp=now,
                            correlation_id=artifact.correlation_id,
                            causation_id=updated_task.task_id,
                        )
                    )
                for event in events:
                    await self._repository.record_event(conn, event)
        if message is not None:
            await self._repository.persist_workspace_communication_messages([message])
        return RunCommandResult(
            run=updated_run,
            task=updated_task,
            message=message,
            artifacts=artifacts,
            events=events,
        )

    async def fail_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        error: str,
        *,
        stop_reason: StopReason = "tool_failure",
    ) -> RunCommandResult:
        logger.debug(
            "RuntimeExecutionService fail_run run_id=%s system_agent_id=%s stop_reason=%s error_len=%s",
            run_id,
            system_agent_id,
            stop_reason,
            len(error),
        )
        run = await self._repository.fetch_run(run_id)
        if run is None:
            raise KeyError(f"Run {run_id} not found")
        task = await self._repository.fetch_task(run.task_id)
        if task is None:
            raise KeyError(f"Task {run.task_id} not found")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=system_agent_id,
        )
        now = self._now()
        updated_run = run.model_copy(
            update={
                "status": "failed",
                "output": {
                    "error": error,
                    "stop_reason": stop_reason,
                },
                "updated_at": now,
                "metadata": {
                    **run.metadata,
                    "stop_reason": stop_reason,
                },
            }
        )
        updated_task = task.model_copy(
            update={
                "status": "failed",
                "claimed_by": participant.participant_id,
                "updated_at": now,
                "metadata": {
                    **task.metadata,
                    "stop_reason": stop_reason,
                    "failed_run_id": str(updated_run.run_id),
                },
            }
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run(conn, updated_run)
                await self._repository.upsert_task(conn, updated_task)
                events = [
                    await self._build_thread_event(
                        conn,
                        updated_run.workspace_id,
                        updated_run.thread_id,
                        "run.failed",
                        actor=actor,
                        target=TargetRef(type="run", id=updated_run.run_id),
                        payload={
                            "run_id": str(updated_run.run_id),
                            "error": error,
                            "stop_reason": stop_reason,
                        },
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=updated_run.correlation_id,
                        causation_id=updated_run.task_id,
                    ),
                    await self._build_thread_event(
                        conn,
                        updated_task.workspace_id,
                        updated_task.thread_id,
                        "task.failed",
                        actor=actor,
                        target=TargetRef(type="task", id=updated_task.task_id),
                        payload={
                            "task_id": str(updated_task.task_id),
                            "run_id": str(updated_run.run_id),
                            "error": error,
                            "stop_reason": stop_reason,
                        },
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=updated_task.correlation_id,
                        causation_id=updated_task.task_id,
                    ),
                ]
                for event in events:
                    await self._repository.record_event(conn, event)
        return RunCommandResult(run=updated_run, task=updated_task, events=events)
