from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from open_talon_contracts.models import EventEnvelope

from .config import RuntimeWorkerSettings

logger = logging.getLogger(__name__)


def route_event_topic(event: EventEnvelope, settings: RuntimeWorkerSettings) -> str:
    if event.event_type == "presence.updated":
        return settings.kafka_presence_topic
    if event.event_type.startswith("workspace.") or event.thread_id is None:
        return settings.kafka_workspace_events_topic
    if (
        event.visibility == "agents_only"
        and event.event_type in {"task.created", "tool_call.created", "tool_call.requeued", "run_step.requeued"}
    ):
        return settings.kafka_agent_tasks_topic
    if (
        event.visibility == "agents_only"
        and (
            event.event_type.startswith("task.")
            or event.event_type.startswith("run.")
            or event.event_type.startswith("tool_call.")
        )
    ):
        return settings.kafka_agent_events_topic
    return settings.kafka_collab_events_topic


class KafkaEventPublisher:
    def __init__(self, settings: RuntimeWorkerSettings) -> None:
        self._settings = settings
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode(),
        )
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, events: list[EventEnvelope]) -> None:
        if self._producer is None:
            raise RuntimeError("KafkaEventPublisher is not started")
        for event in events:
            topic = route_event_topic(event, self._settings)
            key = str(event.thread_id or event.workspace_id).encode()
            await self._producer.send_and_wait(
                topic,
                key=key,
                value=event.model_dump(mode="json"),
            )


class KafkaWakeConsumer:
    def __init__(self, settings: RuntimeWorkerSettings, *, topics: list[str], group_suffix: str) -> None:
        self._settings = settings
        self._topics = topics
        self._group_suffix = group_suffix
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=f"{self._settings.kafka_consumer_group}-{self._group_suffix}",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda value: json.loads(value.decode()),
        )
        await self._consumer.start()
        self._task = asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None

    async def events(self) -> AsyncIterator[EventEnvelope]:
        while True:
            yield await self._queue.get()

    async def _consume_loop(self) -> None:
        assert self._consumer is not None
        try:
            async for message in self._consumer:
                try:
                    event = EventEnvelope.model_validate(message.value)
                except Exception:
                    logger.exception("Invalid event payload received by worker wake consumer")
                    continue
                await self._queue.put(event)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
