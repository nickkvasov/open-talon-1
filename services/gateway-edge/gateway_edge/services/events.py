from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from collections import deque
from uuid import UUID

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError

from gateway_edge.config import settings
from gateway_edge.models import EventEnvelope, KafkaChatRequest, KafkaChatResponse, StreamEvent

logger = logging.getLogger(__name__)


class EventService:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None
        self._admin: AIOKafkaAdminClient | None = None
        self._consumer: AIOKafkaConsumer | None = None
        self._consumer_task: asyncio.Task[None] | None = None
        self._event_handler: Callable[[EventEnvelope], Awaitable[None]] | None = None
        self._recent_event_ids: deque[UUID] = deque(maxlen=4096)
        self._recent_event_id_set: set[UUID] = set()
        self._response_futures: dict[UUID, asyncio.Future[KafkaChatResponse]] = {}
        self._stream_queues: dict[UUID, asyncio.Queue[StreamEvent | None]] = {}

    async def start(self) -> None:
        t0 = time.monotonic()
        self._admin = AIOKafkaAdminClient(
            bootstrap_servers=settings.kafka_bootstrap_servers,
        )
        await self._start_kafka_client(self._admin.start, "admin")
        await self._ensure_topics()
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode(),
        )
        await self._start_kafka_client(self._producer.start, "producer")
        self._consumer = AIOKafkaConsumer(
            settings.kafka_collab_events_topic,
            settings.kafka_workspace_events_topic,
            settings.kafka_agent_tasks_topic,
            settings.kafka_agent_events_topic,
            settings.kafka_presence_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=f"{settings.kafka_consumer_group}-events",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda v: json.loads(v.decode()),
        )
        await self._start_kafka_client(self._consumer.start, "consumer")
        self._consumer_task = asyncio.create_task(self._consume_events())
        logger.info("Kafka event publisher ready (%.0f ms)", (time.monotonic() - t0) * 1000)

    async def stop(self) -> None:
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            await asyncio.gather(self._consumer_task, return_exceptions=True)
            self._consumer_task = None
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
        if self._admin is not None:
            await self._admin.close()
            self._admin = None
        logger.info("Kafka event publisher stopped")

    async def _start_kafka_client(
        self,
        starter: Callable[[], Awaitable[None]],
        client_name: str,
    ) -> None:
        deadline = time.monotonic() + settings.kafka_startup_timeout_seconds
        attempt = 1
        while True:
            try:
                await starter()
                return
            except KafkaConnectionError as exc:
                if time.monotonic() >= deadline:
                    logger.error(
                        "Kafka %s failed to start after %s attempts",
                        client_name,
                        attempt,
                    )
                    raise
                logger.warning(
                    "Kafka %s startup attempt %s failed: %s; retrying in %.1fs",
                    client_name,
                    attempt,
                    exc,
                    settings.kafka_startup_retry_interval_seconds,
                )
                attempt += 1
                await asyncio.sleep(settings.kafka_startup_retry_interval_seconds)

    async def _ensure_topics(self) -> None:
        if self._admin is None:
            return
        existing = await self._admin.list_topics()
        desired = [
            settings.kafka_collab_commands_topic,
            settings.kafka_collab_events_topic,
            settings.kafka_workspace_events_topic,
            settings.kafka_agent_tasks_topic,
            settings.kafka_agent_events_topic,
            settings.kafka_presence_topic,
        ]
        missing = [topic for topic in desired if topic not in existing]
        if not missing:
            return
        await self._admin.create_topics(
            [
                NewTopic(
                    name=topic,
                    num_partitions=1,
                    replication_factor=1,
                )
                for topic in missing
            ]
        )
        logger.info("Created Kafka topics: %s", ", ".join(missing))

    async def publish_event(self, event: EventEnvelope) -> None:
        if self._producer is None:
            await self._dispatch_event(event)
            return
        topic = self._topic_for_event(event)
        key = str(event.thread_id or event.workspace_id).encode()
        await self._producer.send_and_wait(
            topic,
            key=key,
            value=event.model_dump(mode="json"),
        )
        await self._dispatch_event(event)

    def set_event_handler(
        self,
        handler: Callable[[EventEnvelope], Awaitable[None]] | None,
    ) -> None:
        self._event_handler = handler

    def register_response_future(self, correlation_id: UUID) -> None:
        loop = asyncio.get_running_loop()
        self._response_futures[correlation_id] = loop.create_future()

    async def wait_for_response(self, correlation_id: UUID) -> KafkaChatResponse:
        future = self._response_futures.get(correlation_id)
        if future is None:
            raise TimeoutError(f"No response future registered for {correlation_id}")
        try:
            timeout = getattr(settings, "agent_loop_model_timeout_seconds", 60.0)
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._response_futures.pop(correlation_id, None)

    def register_stream_queue(self, correlation_id: UUID) -> None:
        self._stream_queues[correlation_id] = asyncio.Queue()

    async def stream_response(self, correlation_id: UUID):
        queue = self._stream_queues.get(correlation_id)
        if queue is None:
            return
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
                if item.type in {"done", "error"}:
                    break
        finally:
            self._stream_queues.pop(correlation_id, None)

    async def publish_chat_request(self, request: KafkaChatRequest) -> None:
        if settings.echo_agent_enabled:
            asyncio.create_task(self._emit_echo_response(request))

    async def _consume_events(self) -> None:
        if self._consumer is None:
            return
        try:
            async for message in self._consumer:
                try:
                    event = EventEnvelope.model_validate(message.value)
                except Exception:
                    logger.exception("Invalid collaboration event received from Kafka")
                    continue
                await self._dispatch_event(event)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise

    async def _emit_echo_response(self, request: KafkaChatRequest) -> None:
        content = f"Echo: {request.message}"
        response = KafkaChatResponse(
            correlation_id=request.correlation_id,
            session_id=request.session_id,
            type="response",
            content=content,
        )
        future = self._response_futures.get(request.correlation_id)
        if future is not None and not future.done():
            future.set_result(response)

        queue = self._stream_queues.get(request.correlation_id)
        if queue is not None:
            await queue.put(
                StreamEvent(
                    type="token",
                    session_id=request.session_id,
                    correlation_id=request.correlation_id,
                    content=content,
                )
            )
            await queue.put(
                StreamEvent(
                    type="done",
                    session_id=request.session_id,
                    correlation_id=request.correlation_id,
                    content="",
                )
            )
            await queue.put(None)

    @staticmethod
    def _topic_for_event(event: EventEnvelope) -> str:
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

    async def _dispatch_event(self, event: EventEnvelope) -> None:
        if event.event_id in self._recent_event_id_set:
            return
        self._remember_event_id(event.event_id)
        if self._event_handler is not None:
            await self._event_handler(event)

    def _remember_event_id(self, event_id: UUID) -> None:
        if event_id in self._recent_event_id_set:
            return
        if len(self._recent_event_ids) == self._recent_event_ids.maxlen:
            stale = self._recent_event_ids.popleft()
            self._recent_event_id_set.discard(stale)
        self._recent_event_ids.append(event_id)
        self._recent_event_id_set.add(event_id)


event_service = EventService()
