from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "packages" / "contracts"
if _CONTRACTS_DIR.is_dir():
    contracts_path = str(_CONTRACTS_DIR)
    if contracts_path not in sys.path:
        sys.path.insert(0, contracts_path)

from open_talon_contracts.models import ActorRef, EventEnvelope, Run, TargetRef, Task


class AgentTaskRuntime:
    """Helper for agents that consume Open Talon task events and emit run progress."""

    def __init__(self, agent_id: UUID, display_name: str) -> None:
        self.agent_id = agent_id
        self.display_name = display_name

    def claim_task(self, task: Task) -> EventEnvelope:
        now = datetime.now(timezone.utc)
        return EventEnvelope(
            event_type="task.claimed",
            workspace_id=task.workspace_id,
            thread_id=task.thread_id,
            actor=ActorRef(type="agent", id=self.agent_id),
            target=TargetRef(type="task", id=task.task_id),
            visibility="agents_only",
            correlation_id=task.correlation_id,
            sequence=None,
            timestamp=now,
            payload={
                "task_id": str(task.task_id),
                "claimed_by": str(self.agent_id),
                "display_name": self.display_name,
            },
        )

    def start_run(self, task: Task) -> tuple[Run, EventEnvelope]:
        now = datetime.now(timezone.utc)
        run = Run(
            run_id=uuid4(),
            workspace_id=task.workspace_id,
            thread_id=task.thread_id,
            task_id=task.task_id,
            participant_id=self.agent_id,
            status="started",
            correlation_id=task.correlation_id,
            causation_id=task.task_id,
            created_at=now,
            updated_at=now,
            metadata={"agent_display_name": self.display_name},
        )
        event = EventEnvelope(
            event_type="run.started",
            workspace_id=task.workspace_id,
            thread_id=task.thread_id,
            actor=ActorRef(type="agent", id=self.agent_id),
            target=TargetRef(type="run", id=run.run_id),
            visibility="agents_only",
            correlation_id=task.correlation_id,
            causation_id=task.task_id,
            sequence=None,
            timestamp=now,
            payload=run.model_dump(mode="json"),
        )
        return run, event

    def progress_event(self, run: Run, content: str) -> EventEnvelope:
        return EventEnvelope(
            event_type="run.progressed",
            workspace_id=run.workspace_id,
            thread_id=run.thread_id,
            actor=ActorRef(type="agent", id=self.agent_id),
            target=TargetRef(type="run", id=run.run_id),
            visibility="agents_only",
            correlation_id=run.correlation_id,
            causation_id=run.task_id,
            sequence=None,
            timestamp=datetime.now(timezone.utc),
            payload={"run_id": str(run.run_id), "content": content},
        )

    def complete_run(self, run: Run, output: dict) -> EventEnvelope:
        return EventEnvelope(
            event_type="run.completed",
            workspace_id=run.workspace_id,
            thread_id=run.thread_id,
            actor=ActorRef(type="agent", id=self.agent_id),
            target=TargetRef(type="run", id=run.run_id),
            visibility="agents_only",
            correlation_id=run.correlation_id,
            causation_id=run.task_id,
            sequence=None,
            timestamp=datetime.now(timezone.utc),
            payload={"run_id": str(run.run_id), "output": output},
        )

    def fail_run(self, run: Run, error: str) -> EventEnvelope:
        return EventEnvelope(
            event_type="run.failed",
            workspace_id=run.workspace_id,
            thread_id=run.thread_id,
            actor=ActorRef(type="agent", id=self.agent_id),
            target=TargetRef(type="run", id=run.run_id),
            visibility="agents_only",
            correlation_id=run.correlation_id,
            causation_id=run.task_id,
            sequence=None,
            timestamp=datetime.now(timezone.utc),
            payload={"run_id": str(run.run_id), "error": error},
        )
