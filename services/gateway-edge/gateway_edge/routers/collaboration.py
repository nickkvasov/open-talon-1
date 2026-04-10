from __future__ import annotations

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, HTTPException, Query, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

from gateway_edge.auth.api_key import validate_api_key
from gateway_edge.auth.openbao import validate_openbao_token
from gateway_edge.config import settings
from gateway_edge.models import (
    CreateMemoryEntryRequest,
    CreateMessageRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteWorkspaceRequest,
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
from gateway_edge.services import collaboration as collab_svc

router = APIRouter(prefix="/v1", tags=["collaboration"])
logger = logging.getLogger(__name__)


def _actor_log(actor: ParticipantInput) -> dict[str, str]:
    return {
        "participant_id": str(actor.participant_id),
        "participant_type": actor.participant_type,
        "display_name": actor.display_name,
    }


def _participant_from_ws(
    *,
    participant_id: UUID,
    participant_type: str,
    display_name: str,
) -> ParticipantInput:
    return ParticipantInput(
        participant_id=participant_id,
        participant_type=participant_type,
        display_name=display_name,
    )


async def _ws_authorize(websocket: WebSocket) -> bool:
    mode = settings.auth_mode
    if mode == "none":
        return True

    api_key = websocket.query_params.get("api_key") or websocket.headers.get("x-api-key")
    auth_header = websocket.headers.get("authorization", "")
    bearer = (
        auth_header[7:].strip()
        if auth_header.lower().startswith("bearer ")
        else websocket.query_params.get("token")
    )

    if mode == "api_key":
        return bool(api_key) and await validate_api_key(api_key)
    if mode == "openbao":
        return bool(bearer) and await validate_openbao_token(bearer)
    if mode == "any":
        if api_key and await validate_api_key(api_key):
            return True
        if bearer and await validate_openbao_token(bearer):
            return True
    return False


def _http_error(exc: Exception) -> HTTPException:
    logger.exception("Collaboration request failed: %s", exc)
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/workspaces", response_model=WorkspaceDetail, summary="Create a workspace")
async def create_workspace(payload: CreateWorkspaceRequest) -> WorkspaceDetail:
    logger.debug(
        "HTTP create_workspace actor=%s name=%r metadata_keys=%s",
        _actor_log(payload.actor),
        payload.name,
        sorted(payload.metadata.keys()),
    )
    try:
        return await collab_svc.collaboration_service.create_workspace(payload)
    except Exception as exc:  # pragma: no cover - exercised by tests via error type mapping
        raise _http_error(exc) from exc


@router.get("/workspaces", response_model=list[Workspace], summary="List workspaces")
async def list_workspaces() -> list[Workspace]:
    logger.debug("HTTP list_workspaces")
    return await collab_svc.collaboration_service.list_workspaces()


@router.delete(
    "/workspaces/{workspace_id}",
    response_model=dict,
    summary="Delete a workspace",
)
async def delete_workspace(
    workspace_id: UUID,
    payload: DeleteWorkspaceRequest = Body(...),
) -> dict[str, bool | str]:
    logger.debug(
        "HTTP delete_workspace workspace_id=%s actor=%s",
        workspace_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.delete_workspace(workspace_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceDetail,
    summary="Get workspace detail",
)
async def get_workspace(workspace_id: UUID) -> WorkspaceDetail:
    logger.debug("HTTP get_workspace workspace_id=%s", workspace_id)
    try:
        return await collab_svc.collaboration_service.get_workspace(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/threads",
    response_model=ThreadDetail,
    summary="Create a thread in a workspace",
)
async def create_thread(
    workspace_id: UUID, payload: CreateThreadRequest
) -> ThreadDetail:
    logger.debug(
        "HTTP create_thread workspace_id=%s actor=%s title=%r related_thread_count=%s",
        workspace_id,
        _actor_log(payload.actor),
        payload.title,
        len(payload.related_thread_ids),
    )
    try:
        return await collab_svc.collaboration_service.create_thread(workspace_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/threads",
    response_model=list[Thread],
    summary="List threads in a workspace",
)
async def list_threads(workspace_id: UUID) -> list[Thread]:
    logger.debug("HTTP list_threads workspace_id=%s", workspace_id)
    try:
        return await collab_svc.collaboration_service.list_threads(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/threads/{thread_id}",
    response_model=ThreadDetail,
    summary="Get thread detail",
)
async def get_thread(thread_id: UUID) -> ThreadDetail:
    logger.debug("HTTP get_thread thread_id=%s", thread_id)
    try:
        return await collab_svc.collaboration_service.get_thread(thread_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/threads/{thread_id}/timeline",
    response_model=TimelinePage,
    summary="Get the thread timeline",
)
async def get_thread_timeline(thread_id: UUID) -> TimelinePage:
    logger.debug("HTTP get_thread_timeline thread_id=%s", thread_id)
    try:
        return await collab_svc.collaboration_service.get_timeline(thread_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/threads/{thread_id}/messages",
    response_model=TimelineMessage,
    summary="Post a message to a thread",
)
async def post_message(
    thread_id: UUID, payload: CreateMessageRequest
) -> TimelineMessage:
    logger.debug(
        "HTTP post_message thread_id=%s actor=%s visibility=%s create_task=%s content_len=%s",
        thread_id,
        _actor_log(payload.actor),
        payload.visibility,
        payload.create_task,
        len(payload.content),
    )
    try:
        return await collab_svc.collaboration_service.post_message(thread_id, payload)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/workspaces/{workspace_id}/memory",
    response_model=list[MemoryEntry],
    summary="List workspace memory entries",
)
async def list_workspace_memory(workspace_id: UUID) -> list[MemoryEntry]:
    logger.debug("HTTP list_workspace_memory workspace_id=%s", workspace_id)
    try:
        return await collab_svc.collaboration_service.list_memory_entries(workspace_id)
    except Exception as exc:
        raise _http_error(exc) from exc


@router.post(
    "/workspaces/{workspace_id}/memory",
    response_model=MemoryEntry,
    summary="Create a workspace memory entry",
)
async def create_workspace_memory(
    workspace_id: UUID, payload: CreateMemoryEntryRequest
) -> MemoryEntry:
    logger.debug(
        "HTTP create_workspace_memory workspace_id=%s actor=%s entry_type=%s title=%r",
        workspace_id,
        _actor_log(payload.actor),
        payload.entry_type,
        payload.title,
    )
    try:
        return await collab_svc.collaboration_service.create_memory_entry(
            workspace_id, payload
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.patch(
    "/workspaces/{workspace_id}/memory/{memory_entry_id}",
    response_model=MemoryEntry,
    summary="Update a workspace memory entry",
)
async def update_workspace_memory(
    workspace_id: UUID,
    memory_entry_id: UUID,
    payload: UpdateMemoryEntryRequest,
) -> MemoryEntry:
    logger.debug(
        "HTTP update_workspace_memory workspace_id=%s memory_entry_id=%s actor=%s",
        workspace_id,
        memory_entry_id,
        _actor_log(payload.actor),
    )
    try:
        return await collab_svc.collaboration_service.update_memory_entry(
            workspace_id,
            memory_entry_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/workspaces/{workspace_id}/memory/{memory_entry_id}",
    response_model=dict,
    summary="Delete a workspace memory entry",
)
async def delete_workspace_memory(
    workspace_id: UUID,
    memory_entry_id: UUID,
    payload: ParticipantInput = Body(...),
):
    logger.debug(
        "HTTP delete_workspace_memory workspace_id=%s memory_entry_id=%s actor=%s",
        workspace_id,
        memory_entry_id,
        _actor_log(payload),
    )
    try:
        return await collab_svc.collaboration_service.delete_memory_entry(
            workspace_id,
            memory_entry_id,
            payload,
        )
    except Exception as exc:
        raise _http_error(exc) from exc


@router.get(
    "/threads/{thread_id}/events/stream",
    summary="Stream thread events via Server-Sent Events",
    response_class=EventSourceResponse,  # type: ignore[arg-type]
)
async def stream_thread_events(
    thread_id: UUID,
    after_sequence: int | None = Query(default=None),
    follow: bool = Query(default=True),
):
    logger.debug(
        "HTTP stream_thread_events thread_id=%s after_sequence=%s follow=%s",
        thread_id,
        after_sequence,
        follow,
    )
    try:
        async def generator():
            async for event in collab_svc.collaboration_service.stream_thread_events(
                thread_id,
                after_sequence=after_sequence,
                follow=follow,
            ):
                yield event.model_dump_json()

        return EventSourceResponse(generator())
    except Exception as exc:
        raise _http_error(exc) from exc


@router.websocket("/threads/{thread_id}/ws")
async def stream_thread_events_ws(
    websocket: WebSocket,
    thread_id: UUID,
    participant_id: UUID,
    display_name: str,
    participant_type: str = "user",
    after_sequence: int | None = None,
):
    logger.debug(
        "WS connect requested thread_id=%s participant_id=%s participant_type=%s after_sequence=%s",
        thread_id,
        participant_id,
        participant_type,
        after_sequence,
    )
    if not await _ws_authorize(websocket):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    participant = _participant_from_ws(
        participant_id=participant_id,
        participant_type=participant_type,
        display_name=display_name,
    )
    connection_id = str(uuid4())
    await websocket.accept()

    try:
        await collab_svc.collaboration_service.on_thread_connected(
            thread_id=thread_id,
            actor=participant,
            connection_id=connection_id,
        )
        async for event in collab_svc.collaboration_service.stream_thread_events(
            thread_id,
            after_sequence=after_sequence,
            follow=True,
        ):
            logger.debug(
                "WS send event thread_id=%s participant_id=%s event_type=%s sequence=%s",
                thread_id,
                participant_id,
                event.event_type,
                event.sequence,
            )
            await collab_svc.collaboration_service.touch_presence(
                thread_id=thread_id,
                actor=participant,
                connection_id=connection_id,
            )
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        logger.debug(
            "WS disconnected thread_id=%s participant_id=%s connection_id=%s",
            thread_id,
            participant_id,
            connection_id,
        )
        pass
    finally:
        try:
            await collab_svc.collaboration_service.on_thread_disconnected(
                thread_id=thread_id,
                actor=participant,
                connection_id=connection_id,
            )
        except Exception:
            logger.exception(
                "WS disconnect cleanup failed thread_id=%s participant_id=%s connection_id=%s",
                thread_id,
                participant_id,
                connection_id,
            )
            pass
