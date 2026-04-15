from __future__ import annotations

import os
import sys
from uuid import uuid4

_GW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/gateway-edge")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
for path in (_GW_DIR, _CONTRACTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from gateway_edge.models import ActorRef, AuditEvent, EventEnvelope, TargetRef
from gateway_edge.services.events import EventService


async def _dispatch_once():
    service = EventService()
    received = []

    async def handler(event: EventEnvelope) -> None:
        received.append(event.event_type)

    service.set_event_handler(handler)
    event = EventEnvelope(
        event_type="run.completed",
        workspace_id=uuid4(),
        thread_id=uuid4(),
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="run", id=uuid4()),
        visibility="agents_only",
        payload={"status": "completed"},
    )
    await service.publish_event(event)
    await service._dispatch_event(event)
    return received


def test_event_service_deduplicates_local_dispatch():
    import asyncio

    received = asyncio.run(_dispatch_once())
    assert received == ["run.completed"]


def test_event_service_routes_tool_call_created_to_agent_tasks_topic():
    event = EventEnvelope(
        event_type="tool_call.created",
        workspace_id=uuid4(),
        thread_id=uuid4(),
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="tool_call", id=uuid4()),
        visibility="agents_only",
        payload={},
    )

    assert EventService._topic_for_event(event).endswith("agent.tasks")


def test_event_service_routes_requeue_wake_events_to_agent_tasks_topic():
    tool_event = EventEnvelope(
        event_type="tool_call.requeued",
        workspace_id=uuid4(),
        thread_id=uuid4(),
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="tool_call", id=uuid4()),
        visibility="agents_only",
        payload={},
    )
    step_event = EventEnvelope(
        event_type="run_step.requeued",
        workspace_id=uuid4(),
        thread_id=uuid4(),
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="run_step", id=uuid4()),
        visibility="agents_only",
        payload={},
    )

    assert EventService._topic_for_event(tool_event).endswith("agent.tasks")
    assert EventService._topic_for_event(step_event).endswith("agent.tasks")


def test_event_service_publishes_audit_events_to_audit_topic():
    import asyncio

    class _Producer:
        def __init__(self) -> None:
            self.calls = []

        async def send_and_wait(self, topic, *, key=None, value=None):
            self.calls.append({"topic": topic, "key": key, "value": value})

    async def _run():
        service = EventService()
        producer = _Producer()
        service._producer = producer  # noqa: SLF001
        event = AuditEvent(
            audit_event_id=uuid4(),
            ledger_offset=1,
            occurred_at="2026-01-01T00:00:00Z",
            recorded_at="2026-01-01T00:00:00Z",
            scope_type="workspace",
            workspace_id=uuid4(),
            thread_id=None,
            actor_type="user",
            actor_id=uuid4(),
            user_id=uuid4(),
            system_agent_id=None,
            source_service="gateway-edge",
            source_component="test",
            action_category="api",
            action_name="api.request.completed",
            target_type="workspace",
            target_id=uuid4(),
            outcome="success",
            correlation_id=uuid4(),
            causation_id=None,
            request_id=uuid4(),
            trace_id=None,
            error_code=None,
            error_class=None,
            error_message_redacted=None,
            payload_mode="metadata_only",
            payload_hash=None,
            payload_ref=None,
            payload_size_bytes=None,
            metadata={},
            chain_partition="workspace:test",
            chain_sequence=1,
            prev_hash="0" * 64,
            event_hash="1" * 64,
        )
        await service.publish_audit_event(event)
        return producer.calls

    calls = asyncio.run(_run())
    assert len(calls) == 1
    assert calls[0]["topic"].endswith("audit.events")
    assert calls[0]["key"] == b"workspace:test"
