from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from uuid import uuid4, UUID

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from app.auth.api_key import validate_api_key
from app.auth.openbao import validate_openbao_token
from app.config import settings
from app.models import (
    ChatRequest,
    ChatResponse,
    KafkaChatRequest,
    Message,
    SessionInfo,
    StreamEvent,
)
from app.services import events as event_svc
from app.services import history as history_svc
from app.services import session as session_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["chat"])


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _resolve_session(session_id: UUID | None) -> UUID:
    """Return existing session_id or create a new one."""
    if session_id:
        info = await session_svc.get_session(session_id)
        if not info:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return session_id
    new_id = uuid4()
    await session_svc.create_session(new_id)
    return new_id


async def _build_kafka_request(
    session_id: UUID, message: str
) -> KafkaChatRequest:
    history = await history_svc.get_history(session_id, limit=20)
    return KafkaChatRequest(
        correlation_id=uuid4(),
        session_id=session_id,
        message=message,
        history=history,
    )


async def _ws_authorize(websocket: WebSocket) -> bool:
    """
    Validate WebSocket credentials under the current AUTH_MODE.

    Credentials can be supplied as query parameters:
      * ``?api_key=<key>``   — for api_key / any modes
      * ``?token=<bearer>``  — for openbao / any modes

    The ``Authorization: Bearer …`` header is also checked for non-browser
    clients that can set custom headers on the Upgrade request.
    """
    mode = settings.auth_mode
    if mode == "none":
        return True

    api_key = (
        websocket.query_params.get("api_key")
        or websocket.headers.get("x-api-key")
    )
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

    return False


# ── REST — synchronous chat ───────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse, summary="Send a chat message")
async def chat(body: ChatRequest) -> ChatResponse:
    """
    Publishes the message to Kafka and waits for an agent to respond.
    Returns the complete assistant reply.
    """
    t0 = time.monotonic()
    session_id = await _resolve_session(body.session_id)

    # Save user message
    user_msg = Message(role="user", content=body.message)
    kafka_req = await _build_kafka_request(session_id, body.message)
    await history_svc.save_message(session_id, user_msg, kafka_req.correlation_id)
    await session_svc.touch_session(session_id, increment_count=True)

    # Register BEFORE publishing — eliminates the dispatch race where an agent
    # responds before wait_for_response has a chance to create the future.
    event_svc.event_service.register_response_future(kafka_req.correlation_id)
    await event_svc.event_service.publish_chat_request(kafka_req)
    try:
        response = await event_svc.event_service.wait_for_response(
            kafka_req.correlation_id
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Agent did not respond in time. Is an agent consuming talon.chat.requests?",
        )

    # Save assistant message
    assistant_msg = Message(
        role="assistant",
        content=response.content,
        timestamp=datetime.now(timezone.utc),
    )
    await history_svc.save_message(
        session_id, assistant_msg, kafka_req.correlation_id
    )
    await session_svc.touch_session(session_id)

    return ChatResponse(
        session_id=session_id,
        correlation_id=kafka_req.correlation_id,
        message=assistant_msg,
        latency_ms=int((time.monotonic() - t0) * 1000),
    )


# ── SSE — streaming chat ──────────────────────────────────────────────────────

@router.post(
    "/chat/stream",
    summary="Stream a chat response via Server-Sent Events",
    response_class=EventSourceResponse,  # type: ignore[arg-type]
)
async def chat_stream(body: ChatRequest):
    """
    Publishes to Kafka and streams back tokens as SSE events.

    Event format::

        data: {"type": "token", "content": "Hello"}
        data: {"type": "done", "content": ""}
        data: {"type": "error", "error": "..."}
    """
    session_id = await _resolve_session(body.session_id)
    user_msg = Message(role="user", content=body.message)
    kafka_req = await _build_kafka_request(session_id, body.message)
    await history_svc.save_message(session_id, user_msg, kafka_req.correlation_id)
    await session_svc.touch_session(session_id, increment_count=True)

    # Register queue BEFORE publishing to avoid dropping early stream events.
    event_svc.event_service.register_stream_queue(kafka_req.correlation_id)
    await event_svc.event_service.publish_chat_request(kafka_req)

    accumulated_content: list[str] = []

    async def generator():
        async for evt in event_svc.event_service.stream_response(
            kafka_req.correlation_id
        ):
            if evt.type == "token":
                accumulated_content.append(evt.content)
            elif evt.type == "done":
                full_content = "".join(accumulated_content) + evt.content
                assistant_msg = Message(
                    role="assistant",
                    content=full_content,
                    timestamp=datetime.now(timezone.utc),
                )
                await history_svc.save_message(
                    session_id, assistant_msg, kafka_req.correlation_id
                )
                await session_svc.touch_session(session_id)
            yield evt.model_dump_json()

    return EventSourceResponse(generator())


# ── WebSocket — bidirectional streaming ───────────────────────────────────────

@router.websocket("/ws/chat/{session_id}")
async def ws_chat(websocket: WebSocket, session_id: UUID):
    """
    Bidirectional WebSocket.  Client sends JSON ``{"message": "..."}`` and
    receives a stream of JSON events until ``"type": "done"`` or ``"type": "error"``.

    Auth credentials (when AUTH_MODE != none) must be passed as query params:
      * ``?api_key=<key>``  for api_key / any modes
      * ``?token=<bearer>`` for openbao / any modes
    """
    # ── Auth gate — checked before accept() ───────────────────────────────────
    if not await _ws_authorize(websocket):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    info = await session_svc.get_session(session_id)
    if not info:
        await session_svc.create_session(session_id)

    try:
        while True:
            raw = await websocket.receive_json()
            message: str = raw.get("message", "").strip()
            if not message:
                await websocket.send_json({"type": "error", "error": "Empty message"})
                continue

            user_msg = Message(role="user", content=message)
            kafka_req = await _build_kafka_request(session_id, message)
            await history_svc.save_message(
                session_id, user_msg, kafka_req.correlation_id
            )
            await session_svc.touch_session(session_id, increment_count=True)

            # Register queue BEFORE publishing.
            event_svc.event_service.register_stream_queue(kafka_req.correlation_id)
            await event_svc.event_service.publish_chat_request(kafka_req)

            accumulated: list[str] = []
            async for evt in event_svc.event_service.stream_response(
                kafka_req.correlation_id
            ):
                await websocket.send_json(evt.model_dump(mode="json"))
                if evt.type == "token":
                    accumulated.append(evt.content)
                elif evt.type == "done":
                    full_content = "".join(accumulated) + evt.content
                    assistant_msg = Message(
                        role="assistant",
                        content=full_content,
                        timestamp=datetime.now(timezone.utc),
                    )
                    await history_svc.save_message(
                        session_id, assistant_msg, kafka_req.correlation_id
                    )
                    await session_svc.touch_session(session_id)

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)


# ── History ───────────────────────────────────────────────────────────────────

@router.get(
    "/history/{session_id}",
    response_model=list[Message],
    summary="Get chat history for a session",
)
async def get_history(session_id: UUID, limit: int = 50) -> list[Message]:
    info = await session_svc.get_session(session_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return await history_svc.get_history(session_id, limit=limit)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionInfo,
    summary="Get session info",
)
async def get_session(session_id: UUID) -> SessionInfo:
    info = await session_svc.get_session(session_id)
    if not info:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return info


@router.delete(
    "/sessions/{session_id}",
    summary="Delete a session and its history",
)
async def delete_session(session_id: UUID) -> dict:
    info = await session_svc.get_session(session_id)
    if not info:
        raise HTTPException(status_code=404, detail="Session not found")
    await history_svc.delete_history(session_id)
    await session_svc.delete_session(session_id)
    return {"deleted": True, "session_id": str(session_id)}
