from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from .contracts import (
    ActorRef,
    CancelMethodicExecutionRequest,
    CreateMethodicAssignmentRequest,
    CreateMethodicResourceRequestRequest,
    EvaluateMethodicStepRequest,
    MethodicExecution,
    MethodicExecutionAssignment,
    MethodicExecutionCheck,
    MethodicExecutionDetail,
    MethodicExecutionStep,
    MethodicResourceRequest,
    ParticipantProfile,
    TargetRef,
    Task,
    TimelineMessage,
)
from .system_defaults import METHODICS_STEP_COORDINATE_TASK_KIND

_TERMINAL_EXECUTION_STATUSES = {"completed", "cancelled", "failed"}
_ASSIGNMENT_TERMINAL_UPDATE = Literal["completed", "cancelled", "failed"]


@dataclass(frozen=True)
class MethodicsEventSpec:
    event_type: str
    target: TargetRef
    payload: dict[str, Any]
    visibility: str = "workspace"


@dataclass(frozen=True)
class MethodicsCancellationPlan:
    execution: MethodicExecution
    assignment_updates: list[MethodicExecutionAssignment]
    event_spec: MethodicsEventSpec


@dataclass(frozen=True)
class MethodicsResourceRequestPlan:
    resource_request: MethodicResourceRequest
    event_spec: MethodicsEventSpec | None


@dataclass(frozen=True)
class MethodicsAssignmentPlan:
    assignment: MethodicExecutionAssignment
    updated_step: MethodicExecutionStep | None = None
    event_spec: MethodicsEventSpec | None = None


@dataclass(frozen=True)
class MethodicsEvaluationPlan:
    check: MethodicExecutionCheck
    execution: MethodicExecution
    step_updates: list[MethodicExecutionStep] = field(default_factory=list)
    assignment_updates: list[MethodicExecutionAssignment] = field(default_factory=list)
    new_tasks: list[Task] = field(default_factory=list)
    new_assignments: list[MethodicExecutionAssignment] = field(default_factory=list)
    final_message: TimelineMessage | None = None
    event_specs: list[MethodicsEventSpec] = field(default_factory=list)


class MethodicsExecutionPlanner:
    """Build methodics execution state transitions without repository side effects."""

    @staticmethod
    def require_non_terminal(detail: MethodicExecutionDetail, *, action: str) -> None:
        if detail.execution.status in _TERMINAL_EXECUTION_STATUSES:
            raise ValueError(f"Cannot {action} for a terminal methodic execution")

    @staticmethod
    def step_by_id(
        detail: MethodicExecutionDetail,
        step_execution_id: UUID,
    ) -> MethodicExecutionStep:
        for step in detail.steps:
            if step.step_execution_id == step_execution_id:
                return step
        raise KeyError(f"Methodic execution step {step_execution_id} not found")

    @staticmethod
    def next_step(
        steps: list[MethodicExecutionStep],
        current: MethodicExecutionStep,
    ) -> MethodicExecutionStep | None:
        ordered_steps = sorted(
            steps,
            key=lambda item: (item.methodic_index, item.step_index, item.created_at),
        )
        for index, step in enumerate(ordered_steps):
            if step.step_execution_id != current.step_execution_id:
                continue
            for candidate in ordered_steps[index + 1 :]:
                if candidate.status == "pending":
                    return candidate
            return None
        return None

    @staticmethod
    def assignment_terminal_updates(
        assignments: list[MethodicExecutionAssignment],
        *,
        step_execution_id: UUID,
        status: _ASSIGNMENT_TERMINAL_UPDATE,
        timestamp: datetime,
    ) -> list[MethodicExecutionAssignment]:
        return [
            assignment.model_copy(
                update={
                    "status": status,
                    "completed_at": timestamp,
                    "updated_at": timestamp,
                }
            )
            for assignment in assignments
            if assignment.step_execution_id == step_execution_id
            and assignment.status in {"created", "waiting"}
        ]

    @staticmethod
    def agent_task_and_assignment(
        *,
        execution: MethodicExecution,
        step: MethodicExecutionStep,
        created_by: UUID,
        now: datetime,
        task_kind: str,
        title: str,
        description: str,
        task_instructions: list[str],
    ) -> tuple[Task, MethodicExecutionAssignment]:
        task = Task(
            task_id=uuid4(),
            workspace_id=execution.workspace_id,
            thread_id=execution.thread_id,
            title=title,
            description=description,
            requested_by=created_by,
            visibility="agents_only",
            correlation_id=uuid4(),
            causation_id=execution.execution_id,
            created_at=now,
            updated_at=now,
            metadata={
                "target_system_agent_id": str(execution.conductor_system_agent_id),
                "target_participant_id": str(execution.conductor_participant_id),
                "response_visibility": "workspace",
                "routing_reason": task_kind,
                "task_kind": task_kind,
                "methodic_execution_id": str(execution.execution_id),
                "methodic_execution_step_id": str(step.step_execution_id),
                "task_instructions": task_instructions,
            },
        )
        assignment = MethodicExecutionAssignment(
            assignment_id=uuid4(),
            execution_id=execution.execution_id,
            step_execution_id=step.step_execution_id,
            workspace_id=execution.workspace_id,
            assignment_kind="agent_task",
            status="waiting",
            title=title,
            instructions=description,
            assignee_participant_id=execution.conductor_participant_id,
            assignee_system_agent_id=execution.conductor_system_agent_id,
            task_id=task.task_id,
            created_by=created_by,
            created_at=now,
            updated_at=now,
            metadata={"task_kind": task_kind},
        )
        return task, assignment

    def build_cancellation_plan(
        self,
        *,
        detail: MethodicExecutionDetail,
        payload: CancelMethodicExecutionRequest,
        now: datetime,
    ) -> MethodicsCancellationPlan:
        execution = detail.execution.model_copy(
            update={
                "status": "cancelled",
                "current_step_execution_id": None,
                "cancelled_at": now,
                "updated_at": now,
                "error": payload.reason,
                "metadata": {
                    **detail.execution.metadata,
                    **payload.metadata,
                    "cancelled_by": str(payload.actor.participant_id),
                },
            }
        )
        assignment_updates: list[MethodicExecutionAssignment] = []
        if detail.execution.current_step_execution_id is not None:
            assignment_updates = self.assignment_terminal_updates(
                detail.assignments,
                step_execution_id=detail.execution.current_step_execution_id,
                status="cancelled",
                timestamp=now,
            )
        return MethodicsCancellationPlan(
            execution=execution,
            assignment_updates=assignment_updates,
            event_spec=MethodicsEventSpec(
                event_type="methodic_execution.cancelled",
                target=TargetRef(
                    type="methodic_execution",
                    id=detail.execution.execution_id,
                ),
                payload=execution.model_dump(mode="json"),
            ),
        )

    def build_resource_request_plan(
        self,
        *,
        detail: MethodicExecutionDetail,
        payload: CreateMethodicResourceRequestRequest,
        requester_system_agent_id: UUID | None,
        now: datetime,
    ) -> MethodicsResourceRequestPlan:
        self.require_non_terminal(detail, action="create resource requests")
        step_execution_id = (
            payload.step_execution_id or detail.execution.current_step_execution_id
        )
        if step_execution_id is not None and not any(
            step.step_execution_id == step_execution_id for step in detail.steps
        ):
            raise KeyError(f"Methodic execution step {step_execution_id} not found")
        resource_request = MethodicResourceRequest(
            resource_request_id=uuid4(),
            execution_id=detail.execution.execution_id,
            workspace_id=detail.execution.workspace_id,
            step_execution_id=step_execution_id,
            resource_kind=payload.resource_kind,
            action=payload.action,
            status="pending",
            title=payload.title,
            description=payload.description,
            required_permission=payload.required_permission,
            payload=payload.payload,
            requested_by_system_agent_id=requester_system_agent_id,
            created_at=now,
            updated_at=now,
            metadata={
                **payload.metadata,
                "created_by": str(payload.actor.participant_id),
            },
        )
        event_spec = None
        if detail.execution.thread_id is not None:
            event_spec = MethodicsEventSpec(
                event_type="methodic_resource_request.created",
                target=TargetRef(
                    type="methodic_resource_request",
                    id=resource_request.resource_request_id,
                ),
                payload=resource_request.model_dump(mode="json"),
            )
        return MethodicsResourceRequestPlan(
            resource_request=resource_request,
            event_spec=event_spec,
        )

    def build_assignment_plan(
        self,
        *,
        detail: MethodicExecutionDetail,
        payload: CreateMethodicAssignmentRequest,
        actor_participant: ParticipantProfile,
        assignee_participant_id: UUID | None,
        assignee_system_agent_id: UUID | None,
        now: datetime,
    ) -> MethodicsAssignmentPlan:
        self.require_non_terminal(detail, action="create assignments")
        step = self.step_by_id(detail, payload.step_execution_id)
        assignment = MethodicExecutionAssignment(
            assignment_id=uuid4(),
            execution_id=detail.execution.execution_id,
            step_execution_id=step.step_execution_id,
            workspace_id=detail.execution.workspace_id,
            assignment_kind=payload.assignment_kind,
            status="waiting",
            title=payload.title,
            instructions=payload.instructions,
            assignee_participant_id=assignee_participant_id,
            assignee_system_agent_id=assignee_system_agent_id,
            created_by=actor_participant.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        updated_step = None
        if assignee_participant_id is not None and step.assigned_participant_id is None:
            updated_step = step.model_copy(
                update={
                    "assigned_participant_id": assignee_participant_id,
                    "updated_at": now,
                }
            )
        event_spec = None
        if detail.execution.thread_id is not None:
            event_spec = MethodicsEventSpec(
                event_type="methodic_execution_assignment.created",
                target=TargetRef(
                    type="methodic_execution_assignment",
                    id=assignment.assignment_id,
                ),
                payload=assignment.model_dump(mode="json"),
            )
        return MethodicsAssignmentPlan(
            assignment=assignment,
            updated_step=updated_step,
            event_spec=event_spec,
        )

    def build_evaluation_plan(
        self,
        *,
        detail: MethodicExecutionDetail,
        payload: EvaluateMethodicStepRequest,
        actor_participant: ParticipantProfile,
        now: datetime,
    ) -> MethodicsEvaluationPlan:
        self.require_non_terminal(detail, action="evaluate steps")
        step = self.step_by_id(detail, payload.step_execution_id)
        if detail.execution.current_step_execution_id != step.step_execution_id:
            raise ValueError("Only the current methodic execution step can be evaluated")
        if step.status not in {"active", "rework"}:
            raise ValueError(f"Methodic execution step {step.step_execution_id} is not active")

        checked_by_system_agent_id: UUID | None = None
        if actor_participant.participant_type == "agent":
            checked_by_system_agent_id = actor_participant.system_agent_id
        check = MethodicExecutionCheck(
            check_id=uuid4(),
            execution_id=detail.execution.execution_id,
            step_execution_id=step.step_execution_id,
            workspace_id=detail.execution.workspace_id,
            status="passed" if payload.outcome == "passed" else "failed",
            confidence=payload.confidence,
            reason=payload.reason,
            evidence_refs=list(payload.evidence_refs),
            checked_by_system_agent_id=checked_by_system_agent_id,
            created_at=now,
            metadata={
                **payload.metadata,
                "outcome": payload.outcome,
            },
        )
        if payload.outcome == "rework":
            return self._build_rework_plan(
                detail=detail,
                payload=payload,
                actor_participant=actor_participant,
                step=step,
                check=check,
                now=now,
            )
        if payload.outcome == "failed":
            return self._build_failure_plan(
                detail=detail,
                payload=payload,
                step=step,
                check=check,
                now=now,
            )
        return self._build_pass_plan(
            detail=detail,
            payload=payload,
            actor_participant=actor_participant,
            step=step,
            check=check,
            now=now,
        )

    def _build_rework_plan(
        self,
        *,
        detail: MethodicExecutionDetail,
        payload: EvaluateMethodicStepRequest,
        actor_participant: ParticipantProfile,
        step: MethodicExecutionStep,
        check: MethodicExecutionCheck,
        now: datetime,
    ) -> MethodicsEvaluationPlan:
        updated_step = step.model_copy(
            update={
                "status": "rework",
                "evidence_refs": [*step.evidence_refs, *payload.evidence_refs],
                "updated_at": now,
                "metadata": {
                    **step.metadata,
                    **payload.metadata,
                    "rework_reason": payload.reason,
                    "rework_instructions": payload.rework_instructions,
                },
            }
        )
        execution = detail.execution.model_copy(
            update={
                "current_step_execution_id": step.step_execution_id,
                "updated_at": now,
                "metadata": {
                    **detail.execution.metadata,
                    "last_step_outcome": "rework",
                    "last_rework_step_execution_id": str(step.step_execution_id),
                },
            }
        )
        task, assignment = self.agent_task_and_assignment(
            execution=execution,
            step=updated_step,
            created_by=actor_participant.participant_id,
            now=now,
            task_kind=METHODICS_STEP_COORDINATE_TASK_KIND,
            title=f"Rework methodic step {updated_step.name}",
            description=payload.rework_instructions
            or "Coordinate rework for the current methodic execution step.",
            task_instructions=[
                payload.rework_instructions
                or "Coordinate rework for the current methodic execution step.",
                "Collect revised evidence and evaluate the definition of done again.",
            ],
        )
        return MethodicsEvaluationPlan(
            check=check,
            execution=execution,
            step_updates=[updated_step],
            new_tasks=[task],
            new_assignments=[assignment],
            event_specs=[
                MethodicsEventSpec(
                    event_type="methodic_execution_step.rework",
                    target=TargetRef(
                        type="methodic_execution_step",
                        id=step.step_execution_id,
                    ),
                    payload=updated_step.model_dump(mode="json"),
                )
            ],
        )

    def _build_failure_plan(
        self,
        *,
        detail: MethodicExecutionDetail,
        payload: EvaluateMethodicStepRequest,
        step: MethodicExecutionStep,
        check: MethodicExecutionCheck,
        now: datetime,
    ) -> MethodicsEvaluationPlan:
        updated_step = step.model_copy(
            update={
                "status": "failed",
                "completed_at": now,
                "evidence_refs": [*step.evidence_refs, *payload.evidence_refs],
                "updated_at": now,
                "metadata": {
                    **step.metadata,
                    **payload.metadata,
                    "failure_reason": payload.reason,
                },
            }
        )
        execution = detail.execution.model_copy(
            update={
                "status": "failed",
                "current_step_execution_id": None,
                "completed_at": now,
                "updated_at": now,
                "error": payload.reason,
                "metadata": {
                    **detail.execution.metadata,
                    **payload.metadata,
                    "last_step_outcome": "failed",
                },
            }
        )
        return MethodicsEvaluationPlan(
            check=check,
            execution=execution,
            step_updates=[updated_step],
            assignment_updates=self.assignment_terminal_updates(
                detail.assignments,
                step_execution_id=step.step_execution_id,
                status="failed",
                timestamp=now,
            ),
            event_specs=[
                MethodicsEventSpec(
                    event_type="methodic_execution_step.failed",
                    target=TargetRef(
                        type="methodic_execution_step",
                        id=step.step_execution_id,
                    ),
                    payload=updated_step.model_dump(mode="json"),
                ),
                MethodicsEventSpec(
                    event_type="methodic_execution.failed",
                    target=TargetRef(
                        type="methodic_execution",
                        id=detail.execution.execution_id,
                    ),
                    payload=execution.model_dump(mode="json"),
                ),
            ],
        )

    def _build_pass_plan(
        self,
        *,
        detail: MethodicExecutionDetail,
        payload: EvaluateMethodicStepRequest,
        actor_participant: ParticipantProfile,
        step: MethodicExecutionStep,
        check: MethodicExecutionCheck,
        now: datetime,
    ) -> MethodicsEvaluationPlan:
        updated_step = step.model_copy(
            update={
                "status": "passed",
                "completed_at": now,
                "evidence_refs": [*step.evidence_refs, *payload.evidence_refs],
                "updated_at": now,
                "metadata": {
                    **step.metadata,
                    **payload.metadata,
                    "pass_reason": payload.reason,
                },
            }
        )
        assignment_updates = self.assignment_terminal_updates(
            detail.assignments,
            step_execution_id=step.step_execution_id,
            status="completed",
            timestamp=now,
        )
        event_specs = [
            MethodicsEventSpec(
                event_type="methodic_execution_step.passed",
                target=TargetRef(
                    type="methodic_execution_step",
                    id=step.step_execution_id,
                ),
                payload=updated_step.model_dump(mode="json"),
            )
        ]
        next_step = self.next_step(detail.steps, step)
        if next_step is not None:
            return self._build_progression_plan(
                detail=detail,
                check=check,
                actor_participant=actor_participant,
                updated_step=updated_step,
                assignment_updates=assignment_updates,
                event_specs=event_specs,
                next_step=next_step,
                now=now,
            )
        return self._build_completion_plan(
            detail=detail,
            payload=payload,
            check=check,
            actor_participant=actor_participant,
            updated_step=updated_step,
            assignment_updates=assignment_updates,
            event_specs=event_specs,
            now=now,
        )

    def _build_progression_plan(
        self,
        *,
        detail: MethodicExecutionDetail,
        check: MethodicExecutionCheck,
        actor_participant: ParticipantProfile,
        updated_step: MethodicExecutionStep,
        assignment_updates: list[MethodicExecutionAssignment],
        event_specs: list[MethodicsEventSpec],
        next_step: MethodicExecutionStep,
        now: datetime,
    ) -> MethodicsEvaluationPlan:
        active_next_step = next_step.model_copy(
            update={"status": "active", "started_at": now, "updated_at": now}
        )
        execution = detail.execution.model_copy(
            update={
                "current_step_execution_id": active_next_step.step_execution_id,
                "updated_at": now,
                "metadata": {
                    **detail.execution.metadata,
                    "last_step_outcome": "passed",
                    "last_passed_step_execution_id": str(updated_step.step_execution_id),
                },
            }
        )
        task, assignment = self.agent_task_and_assignment(
            execution=execution,
            step=active_next_step,
            created_by=actor_participant.participant_id,
            now=now,
            task_kind=METHODICS_STEP_COORDINATE_TASK_KIND,
            title=f"Coordinate methodic step {active_next_step.name}",
            description="Coordinate the next active methodic execution step.",
            task_instructions=[
                "Read the methodic execution snapshot and coordinate the active step.",
                "Create participant assignments or resource requests as needed.",
                "Verify definition of done evidence before advancing the execution.",
            ],
        )
        event_specs.append(
            MethodicsEventSpec(
                event_type="methodic_execution_step.activated",
                target=TargetRef(
                    type="methodic_execution_step",
                    id=active_next_step.step_execution_id,
                ),
                payload=active_next_step.model_dump(mode="json"),
            )
        )
        return MethodicsEvaluationPlan(
            check=check,
            execution=execution,
            step_updates=[updated_step, active_next_step],
            assignment_updates=assignment_updates,
            new_tasks=[task],
            new_assignments=[assignment],
            event_specs=event_specs,
        )

    def _build_completion_plan(
        self,
        *,
        detail: MethodicExecutionDetail,
        payload: EvaluateMethodicStepRequest,
        check: MethodicExecutionCheck,
        actor_participant: ParticipantProfile,
        updated_step: MethodicExecutionStep,
        assignment_updates: list[MethodicExecutionAssignment],
        event_specs: list[MethodicsEventSpec],
        now: datetime,
    ) -> MethodicsEvaluationPlan:
        final_report = payload.final_report or (
            f"Methodics execution {detail.execution.execution_id} completed successfully."
        )
        execution = detail.execution.model_copy(
            update={
                "status": "completed",
                "current_step_execution_id": None,
                "completed_at": now,
                "updated_at": now,
                "metadata": {
                    **detail.execution.metadata,
                    **payload.metadata,
                    "last_step_outcome": "passed",
                    "final_report": final_report,
                },
            }
        )
        final_message = None
        if execution.thread_id is not None:
            final_message = TimelineMessage(
                message_id=uuid4(),
                workspace_id=detail.execution.workspace_id,
                thread_id=execution.thread_id,
                actor=ActorRef(
                    type=actor_participant.participant_type,
                    id=actor_participant.participant_id,
                ),
                visibility="workspace",
                content=final_report,
                status="completed",
                correlation_id=uuid4(),
                causation_id=detail.execution.execution_id,
                sequence=0,
                created_at=now,
                updated_at=now,
                metadata={
                    "methodic_execution_id": str(detail.execution.execution_id),
                    "methodics_final_report": True,
                },
            )
        event_specs.append(
            MethodicsEventSpec(
                event_type="methodic_execution.completed",
                target=TargetRef(
                    type="methodic_execution",
                    id=detail.execution.execution_id,
                ),
                payload=execution.model_dump(mode="json"),
            )
        )
        return MethodicsEvaluationPlan(
            check=check,
            execution=execution,
            step_updates=[updated_step],
            assignment_updates=assignment_updates,
            final_message=final_message,
            event_specs=event_specs,
        )
