from __future__ import annotations

import asyncio
import logging
import sys
from collections import defaultdict
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

_CORE_COLLAB_DIR = Path(__file__).resolve().parents[3] / "services" / "core-collab"
if _CORE_COLLAB_DIR.is_dir():
    collab_path = str(_CORE_COLLAB_DIR)
    if collab_path not in sys.path:
        sys.path.insert(0, collab_path)

from core_collab import CollaborationKernel, CollaborationRepository  # noqa: E402

from gateway_edge.db.postgres import get_pool
from gateway_edge.models import (
    CreateMemoryEntryRequest,
    CreateMessageRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteWorkspaceRequest,
    EventEnvelope,
    MemoryEntry,
    ParticipantInput,
    Thread,
    ThreadDetail,
    TimelineMessage,
    TimelinePage,
    UpdateMemoryEntryRequest,
    Workspace,
    WorkspaceDetail,
)
from gateway_edge.services.events import event_service
from gateway_edge.services.session import (
    register_thread_connection,
    touch_thread_presence,
    unregister_thread_connection,
)

logger = logging.getLogger(__name__)


class CollaborationService:
    def __init__(self) -> None:
        self._kernel: CollaborationKernel | None = None
        self._subscriptions: dict[str, set[asyncio.Queue[EventEnvelope]]] = defaultdict(set)

    async def start(self) -> None:
        pool = await get_pool()
        repository = CollaborationRepository(pool)
        self._kernel = CollaborationKernel(repository)
        await self._kernel.setup_schema()
        logger.info("Collaboration service started")

    async def stop(self) -> None:
        self._subscriptions.clear()
        self._kernel = None
        logger.info("Collaboration service stopped")

    async def create_workspace(self, payload: CreateWorkspaceRequest) -> WorkspaceDetail:
        logger.debug(
            "Service create_workspace participant_id=%s name=%r",
            payload.actor.participant_id,
            payload.name,
        )
        kernel = self._require_kernel()
        result = await kernel.create_workspace(payload)
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def list_workspaces(self) -> list[Workspace]:
        return await self._require_kernel().list_workspaces()

    async def delete_workspace(
        self, workspace_id: UUID, payload: DeleteWorkspaceRequest
    ) -> dict[str, bool | str]:
        logger.debug(
            "Service delete_workspace workspace_id=%s participant_id=%s",
            workspace_id,
            payload.actor.participant_id,
        )
        return await self._require_kernel().delete_workspace(workspace_id, payload)

    async def get_workspace(self, workspace_id: UUID) -> WorkspaceDetail:
        logger.debug("Service get_workspace workspace_id=%s", workspace_id)
        return await self._require_kernel().get_workspace_detail(workspace_id)

    async def create_thread(
        self, workspace_id: UUID, payload: CreateThreadRequest
    ) -> ThreadDetail:
        logger.debug(
            "Service create_thread workspace_id=%s participant_id=%s title=%r",
            workspace_id,
            payload.actor.participant_id,
            payload.title,
        )
        result = await self._require_kernel().create_thread(workspace_id, payload)
        await self._publish_events(result.events)
        assert result.detail is not None
        return result.detail

    async def list_threads(self, workspace_id: UUID) -> list[Thread]:
        return await self._require_kernel().list_threads(workspace_id)

    async def get_thread(self, thread_id: UUID) -> ThreadDetail:
        logger.debug("Service get_thread thread_id=%s", thread_id)
        return await self._require_kernel().get_thread_detail(thread_id)

    async def get_timeline(self, thread_id: UUID) -> TimelinePage:
        logger.debug("Service get_timeline thread_id=%s", thread_id)
        return await self._require_kernel().get_thread_timeline(thread_id)

    async def post_message(
        self, thread_id: UUID, payload: CreateMessageRequest
    ) -> TimelineMessage:
        logger.debug(
            "Service post_message thread_id=%s participant_id=%s visibility=%s create_task=%s",
            thread_id,
            payload.actor.participant_id,
            payload.visibility,
            payload.create_task,
        )
        result = await self._require_kernel().post_message(thread_id, payload)
        await self._publish_events(result.events)
        assert result.message is not None
        return result.message

    async def list_memory_entries(self, workspace_id: UUID) -> list[MemoryEntry]:
        logger.debug("Service list_memory_entries workspace_id=%s", workspace_id)
        return await self._require_kernel().list_memory_entries(workspace_id)

    async def create_memory_entry(
        self, workspace_id: UUID, payload: CreateMemoryEntryRequest
    ) -> MemoryEntry:
        logger.debug(
            "Service create_memory_entry workspace_id=%s participant_id=%s title=%r",
            workspace_id,
            payload.actor.participant_id,
            payload.title,
        )
        result = await self._require_kernel().create_memory_entry(workspace_id, payload)
        await self._publish_events(result.events)
        assert result.entry is not None
        return result.entry

    async def update_memory_entry(
        self,
        workspace_id: UUID,
        memory_entry_id: UUID,
        payload: UpdateMemoryEntryRequest,
    ) -> MemoryEntry:
        logger.debug(
            "Service update_memory_entry workspace_id=%s memory_entry_id=%s participant_id=%s",
            workspace_id,
            memory_entry_id,
            payload.actor.participant_id,
        )
        result = await self._require_kernel().update_memory_entry(
            workspace_id, memory_entry_id, payload
        )
        await self._publish_events(result.events)
        assert result.entry is not None
        return result.entry

    async def delete_memory_entry(
        self,
        workspace_id: UUID,
        memory_entry_id: UUID,
        actor: ParticipantInput,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Service delete_memory_entry workspace_id=%s memory_entry_id=%s participant_id=%s",
            workspace_id,
            memory_entry_id,
            actor.participant_id,
        )
        events = await self._require_kernel().delete_memory_entry(
            workspace_id, memory_entry_id, actor
        )
        await self._publish_events(events)
        return {"deleted": True, "memory_entry_id": str(memory_entry_id)}

    async def publish_presence(
        self,
        *,
        thread_id: UUID,
        actor: ParticipantInput,
        status: str,
        connection_id: str | None = None,
    ) -> EventEnvelope:
        logger.debug(
            "Service publish_presence thread_id=%s participant_id=%s status=%s connection_id=%s",
            thread_id,
            actor.participant_id,
            status,
            connection_id,
        )
        event = await self._require_kernel().publish_presence(
            thread_id=thread_id,
            actor_input=actor,
            status=status,
            connection_id=connection_id,
        )
        await self._publish_events([event])
        return event

    async def on_thread_connected(
        self,
        *,
        thread_id: UUID,
        actor: ParticipantInput,
        connection_id: str,
    ) -> EventEnvelope:
        logger.debug(
            "Service on_thread_connected thread_id=%s participant_id=%s connection_id=%s",
            thread_id,
            actor.participant_id,
            connection_id,
        )
        await register_thread_connection(
            thread_id=thread_id,
            participant_id=actor.participant_id,
            connection_id=connection_id,
            status="active",
        )
        return await self.publish_presence(
            thread_id=thread_id,
            actor=actor,
            status="active",
            connection_id=connection_id,
        )

    async def on_thread_disconnected(
        self,
        *,
        thread_id: UUID,
        actor: ParticipantInput,
        connection_id: str,
    ) -> EventEnvelope:
        logger.debug(
            "Service on_thread_disconnected thread_id=%s participant_id=%s connection_id=%s",
            thread_id,
            actor.participant_id,
            connection_id,
        )
        await unregister_thread_connection(
            thread_id=thread_id,
            participant_id=actor.participant_id,
            connection_id=connection_id,
        )
        return await self.publish_presence(
            thread_id=thread_id,
            actor=actor,
            status="offline",
            connection_id=connection_id,
        )

    async def stream_thread_events(
        self,
        thread_id: UUID,
        *,
        after_sequence: int | None = None,
        follow: bool = True,
    ) -> AsyncIterator[EventEnvelope]:
        logger.debug(
            "Service stream_thread_events thread_id=%s after_sequence=%s follow=%s",
            thread_id,
            after_sequence,
            follow,
        )
        kernel = self._require_kernel()
        replay_events = await kernel.list_thread_events(
            thread_id, after_sequence=after_sequence
        )
        for event in replay_events:
            yield event
        if not follow:
            return
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        key = str(thread_id)
        self._subscriptions[key].add(queue)
        logger.debug(
            "Service stream subscribed thread_id=%s subscriber_count=%s",
            thread_id,
            len(self._subscriptions[key]),
        )
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscriptions[key].discard(queue)
            if not self._subscriptions[key]:
                self._subscriptions.pop(key, None)
            logger.debug(
                "Service stream unsubscribed thread_id=%s remaining_subscribers=%s",
                thread_id,
                len(self._subscriptions.get(key, set())),
            )

    async def touch_presence(
        self,
        *,
        thread_id: UUID,
        actor: ParticipantInput,
        connection_id: str | None = None,
        status: str = "active",
    ) -> None:
        logger.debug(
            "Service touch_presence thread_id=%s participant_id=%s status=%s connection_id=%s",
            thread_id,
            actor.participant_id,
            status,
            connection_id,
        )
        await touch_thread_presence(
            thread_id=thread_id,
            participant_id=actor.participant_id,
            connection_id=connection_id,
            status=status,
        )

    async def _publish_events(self, events: list[EventEnvelope]) -> None:
        for event in events:
            logger.debug(
                "Service publish_event event_type=%s thread_id=%s workspace_id=%s sequence=%s visibility=%s",
                event.event_type,
                event.thread_id,
                event.workspace_id,
                event.sequence,
                event.visibility,
            )
            await event_service.publish_event(event)
            for queue in list(self._subscriptions.get(str(event.thread_id), set())):
                await queue.put(event)

    def _require_kernel(self) -> CollaborationKernel:
        if self._kernel is None:
            raise RuntimeError("Collaboration service is not started")
        return self._kernel


collaboration_service = CollaborationService()
