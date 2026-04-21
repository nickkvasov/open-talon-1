from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest

_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
for path in (_CONTRACTS_DIR, _CORE_COLLAB_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from core_collab.repository import CollaborationRepository
from open_talon_contracts.models import (
    ActorRef,
    AuditEvent,
    AuditEventDraft,
    EventEnvelope,
    TargetRef,
)


class _RecordingObserver:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.flush_count = 0

    def start_span(self, *, name, input=None, metadata=None):
        raise AssertionError("start_span should not be used in repository observability tests")

    def start_generation(self, *, name, model=None, input=None, metadata=None):
        raise AssertionError(
            "start_generation should not be used in repository observability tests"
        )

    def record_event(self, *, name, input=None, metadata=None):
        self.events.append({"name": name, "input": input, "metadata": metadata})

    def flush(self):
        self.flush_count += 1


class _FakeConn:
    def __init__(self, *, inserted: bool = True) -> None:
        self._inserted = inserted
        self.execute_calls = 0
        self.fetchrow_calls = 0

    async def execute(self, *_args, **_kwargs):
        self.execute_calls += 1
        return "INSERT 0 1" if self._inserted else "INSERT 0 0"

    async def fetchrow(self, *_args, **_kwargs):
        self.fetchrow_calls += 1
        if self.fetchrow_calls == 1:
            return None
        return {"dummy": True}


@pytest.mark.asyncio
async def test_record_event_mirrors_collaboration_event_to_observability(monkeypatch):
    observer = _RecordingObserver()
    repository = CollaborationRepository(None, observability=observer)
    conn = _FakeConn()
    event = EventEnvelope(
        event_type="tool_generation_revision.approval_started",
        workspace_id=uuid4(),
        thread_id=uuid4(),
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="tool_generation_revision", id=uuid4()),
        visibility="workspace",
        payload={"request_id": str(uuid4())},
    )

    async def _fake_audit_draft(_conn, _event):
        return AuditEventDraft(
            workspace_id=event.workspace_id,
            thread_id=event.thread_id,
            scope_type="thread",
            actor_type="agent",
            actor_id=event.actor.id,
            source_service="core-collab",
            source_component="repository",
            action_category="collaboration",
            action_name=event.event_type,
            target_type=event.target.type,
            target_id=event.target.id,
            outcome="success",
            chain_partition=f"workspace:{event.workspace_id}",
        )

    async def _fake_append(_conn, _draft):
        return None

    monkeypatch.setattr(repository, "_audit_draft_from_event", _fake_audit_draft)
    monkeypatch.setattr(repository, "append_audit_event", _fake_append)

    await repository.record_event(conn, event)

    assert observer.events == [
        {
            "name": "collaboration.event.recorded",
            "input": {
                "event_id": str(event.event_id),
                "payload": event.payload,
            },
            "metadata": {
                "source_service": "core-collab",
                "source_component": "repository",
                "correlation_id": str(event.correlation_id),
                "workspace_id": str(event.workspace_id),
                "thread_id": str(event.thread_id),
                "participant_id": str(event.actor.id),
                "event_type": event.event_type,
                "actor_type": event.actor.type,
                "actor_id": str(event.actor.id),
                "target_type": event.target.type,
                "target_id": str(event.target.id),
                "visibility": event.visibility,
                "sequence": event.sequence,
            },
        }
    ]
    assert observer.flush_count == 1


@pytest.mark.asyncio
async def test_append_audit_event_mirrors_audit_entry_to_observability(monkeypatch):
    observer = _RecordingObserver()
    repository = CollaborationRepository(None, observability=observer)
    conn = _FakeConn()
    now = datetime.now(timezone.utc)
    draft = AuditEventDraft(
        workspace_id=uuid4(),
        thread_id=uuid4(),
        scope_type="thread",
        actor_type="system",
        source_service="agent-runtime",
        source_component="tool-worker",
        action_category="execution",
        action_name="execution.backend_failed",
        target_type="tool_call",
        target_id=uuid4(),
        outcome="failure",
        chain_partition=f"workspace:{uuid4()}",
        occurred_at=now,
        recorded_at=now,
    )
    audit_event = AuditEvent(
        audit_event_id=draft.audit_event_id,
        occurred_at=draft.occurred_at,
        recorded_at=draft.recorded_at,
        scope_type=draft.scope_type,
        organization_id=draft.organization_id,
        workspace_id=draft.workspace_id,
        thread_id=draft.thread_id,
        actor_type=draft.actor_type,
        actor_id=draft.actor_id,
        user_id=draft.user_id,
        system_agent_id=draft.system_agent_id,
        source_service=draft.source_service,
        source_component=draft.source_component,
        action_category=draft.action_category,
        action_name=draft.action_name,
        target_type=draft.target_type,
        target_id=draft.target_id,
        outcome=draft.outcome,
        correlation_id=draft.correlation_id,
        causation_id=draft.causation_id,
        request_id=draft.request_id,
        trace_id=draft.trace_id,
        error_code=draft.error_code,
        error_class=draft.error_class,
        error_message_redacted=draft.error_message_redacted,
        payload_mode=draft.payload_mode,
        payload_hash=draft.payload_hash,
        payload_ref=draft.payload_ref,
        payload_size_bytes=draft.payload_size_bytes,
        metadata=draft.metadata,
        ledger_offset=1,
        chain_partition=draft.chain_partition,
        chain_sequence=1,
        prev_hash="0" * 64,
        event_hash="1" * 64,
    )

    monkeypatch.setattr(repository, "_audit_event_from_row", lambda _row: audit_event)

    result = await repository.append_audit_event(conn, draft)

    assert result == audit_event
    assert observer.events == [
        {
            "name": "audit.event.recorded",
            "input": {"audit_event_id": str(audit_event.audit_event_id)},
            "metadata": {
                "source_service": audit_event.source_service,
                "source_component": audit_event.source_component,
                "workspace_id": str(audit_event.workspace_id),
                "thread_id": str(audit_event.thread_id),
                "action_category": audit_event.action_category,
                "action_name": audit_event.action_name,
                "target_type": audit_event.target_type,
                "target_id": str(audit_event.target_id),
                "outcome": audit_event.outcome,
                "chain_partition": audit_event.chain_partition,
                "chain_sequence": audit_event.chain_sequence,
            },
        }
    ]
    assert observer.flush_count == 1
