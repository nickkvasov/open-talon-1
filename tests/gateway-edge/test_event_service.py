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

from gateway_edge.models import ActorRef, EventEnvelope, TargetRef
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
