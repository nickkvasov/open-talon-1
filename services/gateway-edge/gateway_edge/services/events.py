"""
Kafka event service.

Gateway → agent flow
--------------------
1. Gateway publishes a KafkaChatRequest to ``talon.chat.requests``.
2. An agent (separate repo) consumes the request, calls Ollama, and publishes
   a KafkaChatResponse to ``talon.chat.responses``.
3. This service's background consumer receives the response and resolves the
   matching asyncio.Future (REST) or drains into an asyncio.Queue (WS/SSE).

Dev / echo mode (ECHO_AGENT_ENABLED=true)
-----------------------------------------
An in-process loop consumes its own requests and echoes back a response.
Useful for full-stack testing before agents/ is wired up.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import AsyncIterator
from uuid import UUID

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError

from gateway_edge.config import settings
from gateway_edge.models import KafkaChatRequest, KafkaChatResponse, StreamEvent

logger = logging.getLogger(__name__)


class EventService:
    """Manages Kafka producer + consumer and correlates request futures."""

    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None
        self._consumer: AIOKafkaConsumer | None = None
        # REST path: correlation_id → Future[KafkaChatResponse]
        self._pending: dict[str, asyncio.Future[KafkaChatResponse]] = {}
        # SSE / WS path: correlation_id → Queue[StreamEvent]
        self._streams: dict[str, asyncio.Queue[StreamEvent]] = {}
        self._consumer_task: asyncio.Task | None = None
        self._echo_task: asyncio.Task | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        t0 = time.monotonic()
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            value_serializer=lambda v: json.dumps(v).encode(),
        )
        await self._start_kafka_client(self._producer.start, "producer")

        self._consumer = AIOKafkaConsumer(
            settings.kafka_response_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kafka_consumer_group,
            value_deserializer=lambda b: json.loads(b.decode()),
            auto_offset_reset="latest",
            enable_auto_commit=True,
        )
        await self._start_kafka_client(self._consumer.start, "consumer")
        self._consumer_task = asyncio.create_task(
            self._consume_loop(), name="kafka-consumer"
        )

        if settings.echo_agent_enabled:
            self._echo_task = asyncio.create_task(
                self._echo_agent_loop(), name="echo-agent"
            )
            logger.warning(
                "Echo agent enabled — all chat requests will be echoed back locally"
            )

        logger.info("Kafka event service ready (%.0f ms)", (time.monotonic() - t0) * 1000)

    async def stop(self) -> None:
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        if self._echo_task:
            self._echo_task.cancel()
            try:
                await self._echo_task
            except asyncio.CancelledError:
                pass
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()
        logger.info("Kafka event service stopped")

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

    # ── Pre-registration (call before publish to eliminate dispatch race) ─────

    def register_response_future(self, correlation_id: UUID) -> None:
        """
        Create + store a Future for this correlation_id *before* publishing the
        request.  If the agent responds before ``wait_for_response`` is called,
        the Future is already in ``_pending`` and the response is not lost.
        """
        key = str(correlation_id)
        if key not in self._pending:
            loop = asyncio.get_event_loop()
            self._pending[key] = loop.create_future()

    def register_stream_queue(self, correlation_id: UUID) -> None:
        """
        Create + store a Queue for this correlation_id *before* publishing the
        request so streaming events are not dropped between publish and the first
        ``stream_response`` iteration.
        """
        key = str(correlation_id)
        if key not in self._streams:
            self._streams[key] = asyncio.Queue()

    # ── Publishing ───────────────────────────────────────────────────────────

    async def publish_chat_request(self, request: KafkaChatRequest) -> None:
        if self._producer is None:
            raise RuntimeError("EventService is not started")
        await self._producer.send_and_wait(
            settings.kafka_request_topic,
            value=request.model_dump(mode="json"),
        )
        logger.debug(
            "Published chat request %s → topic %s",
            request.correlation_id,
            settings.kafka_request_topic,
        )

    # ── Waiting (REST path) ──────────────────────────────────────────────────

    async def wait_for_response(
        self, correlation_id: UUID, timeout: float | None = None
    ) -> KafkaChatResponse:
        """
        Block until the agent publishes a response for this correlation_id.

        Reuses a Future created by ``register_response_future`` if one was
        pre-registered; otherwise creates one on demand (best-effort, races
        possible if the agent is very fast).
        """
        loop = asyncio.get_event_loop()
        key = str(correlation_id)
        if key not in self._pending:
            self._pending[key] = loop.create_future()
        future = self._pending[key]
        try:
            return await asyncio.wait_for(
                future,
                timeout=timeout or settings.kafka_response_timeout_seconds,
            )
        finally:
            self._pending.pop(key, None)

    # ── Streaming (SSE / WS path) ────────────────────────────────────────────

    async def stream_response(
        self, correlation_id: UUID
    ) -> AsyncIterator[StreamEvent]:
        """
        Yield StreamEvents until a 'done' or 'error' event arrives.

        Reuses a Queue created by ``register_stream_queue`` if one was
        pre-registered; otherwise creates one on demand.
        """
        key = str(correlation_id)
        if key not in self._streams:
            self._streams[key] = asyncio.Queue()
        queue = self._streams[key]
        try:
            while True:
                event = await asyncio.wait_for(
                    queue.get(),
                    timeout=settings.kafka_response_timeout_seconds,
                )
                yield event
                if event.type in ("done", "error"):
                    break
        finally:
            self._streams.pop(key, None)

    # ── Consumer loop ────────────────────────────────────────────────────────

    async def _consume_loop(self) -> None:
        assert self._consumer is not None
        try:
            async for record in self._consumer:
                await self._dispatch(record.value)
        except asyncio.CancelledError:
            pass
        except KafkaConnectionError as exc:
            logger.error("Kafka consumer lost connection: %s", exc)

    async def _dispatch(self, data: dict) -> None:
        try:
            response = KafkaChatResponse(**data)
        except Exception as exc:
            logger.warning("Dropping malformed kafka response: %s — %s", data, exc)
            return

        key = str(response.correlation_id)
        msg_type = response.type

        # ── REST (future) path ────────────────────────────────────────────
        if msg_type == "response" and key in self._pending:
            fut = self._pending[key]
            if not fut.done():
                fut.set_result(response)

        # ── Streaming path ────────────────────────────────────────────────
        if key in self._streams:
            if msg_type == "stream_token":
                evt = StreamEvent(
                    type="token",
                    session_id=response.session_id,
                    correlation_id=response.correlation_id,
                    content=response.content,
                )
            elif msg_type in ("stream_done", "response"):
                evt = StreamEvent(
                    type="done",
                    session_id=response.session_id,
                    correlation_id=response.correlation_id,
                    content=response.content,
                )
            elif msg_type == "error":
                evt = StreamEvent(
                    type="error",
                    session_id=response.session_id,
                    correlation_id=response.correlation_id,
                    error=response.error,
                )
            else:
                return
            await self._streams[key].put(evt)

        # If a "response" arrived but nobody is streaming, also resolve the
        # future (handles race between REST and streaming registrations).
        if msg_type == "response" and key in self._pending:
            fut = self._pending[key]
            if not fut.done():
                fut.set_result(response)

    # ── Echo agent (dev mode) ────────────────────────────────────────────────

    async def _echo_agent_loop(self) -> None:
        """Consume from request topic and echo back responses — dev only."""
        echo_consumer = AIOKafkaConsumer(
            settings.kafka_request_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=f"{settings.kafka_consumer_group}-echo",
            value_deserializer=lambda b: json.loads(b.decode()),
            auto_offset_reset="latest",
        )
        await echo_consumer.start()
        try:
            async for record in echo_consumer:
                req = record.value
                echo_content = f"[echo] {req.get('message', '')}"
                response = KafkaChatResponse(
                    correlation_id=req["correlation_id"],
                    session_id=req["session_id"],
                    type="response",
                    content=echo_content,
                )
                if self._producer:
                    await self._producer.send_and_wait(
                        settings.kafka_response_topic,
                        value=response.model_dump(mode="json"),
                    )
        except asyncio.CancelledError:
            pass
        finally:
            await echo_consumer.stop()


# Module-level singleton — initialised in app lifespan
event_service = EventService()
