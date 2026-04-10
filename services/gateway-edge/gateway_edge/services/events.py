from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError

from gateway_edge.config import settings
from gateway_edge.models import EventEnvelope

logger = logging.getLogger(__name__)


class EventService:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None
        self._admin: AIOKafkaAdminClient | None = None

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
        logger.info("Kafka event publisher ready (%.0f ms)", (time.monotonic() - t0) * 1000)

    async def stop(self) -> None:
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
            return
        topic = self._topic_for_event(event)
        key = str(event.thread_id or event.workspace_id).encode()
        await self._producer.send_and_wait(
            topic,
            key=key,
            value=event.model_dump(mode="json"),
        )

    @staticmethod
    def _topic_for_event(event: EventEnvelope) -> str:
        if event.event_type == "presence.updated":
            return settings.kafka_presence_topic
        if event.event_type.startswith("workspace.") or event.thread_id is None:
            return settings.kafka_workspace_events_topic
        if event.event_type.startswith("task.") and event.visibility == "agents_only":
            return settings.kafka_agent_tasks_topic
        return settings.kafka_collab_events_topic


event_service = EventService()
