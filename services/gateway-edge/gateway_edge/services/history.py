from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from gateway_edge.db.postgres import get_pool
from gateway_edge.models import Message

logger = logging.getLogger(__name__)


async def save_message(
    session_id: UUID,
    message: Message,
    correlation_id: UUID | None = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Ensure session row exists (upsert)
        await conn.execute(
            """
            INSERT INTO chat_sessions (session_id)
            VALUES ($1)
            ON CONFLICT (session_id) DO UPDATE
                SET last_active = NOW()
            """,
            session_id,
        )
        await conn.execute(
            """
            INSERT INTO chat_messages
                (session_id, correlation_id, role, content, created_at)
            VALUES ($1, $2, $3, $4, $5)
            """,
            session_id,
            correlation_id,
            message.role,
            message.content,
            message.timestamp.replace(tzinfo=timezone.utc)
            if message.timestamp.tzinfo is None
            else message.timestamp,
        )


async def get_history(session_id: UUID, limit: int = 50) -> list[Message]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content, created_at
            FROM chat_messages
            WHERE session_id = $1
            ORDER BY created_at ASC
            LIMIT $2
            """,
            session_id,
            limit,
        )
    return [
        Message(
            role=r["role"],
            content=r["content"],
            timestamp=r["created_at"],
        )
        for r in rows
    ]


async def delete_history(session_id: UUID) -> int:
    """Delete all messages for a session. Returns deleted count."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM chat_messages WHERE session_id = $1",
            session_id,
        )
    # result is "DELETE N"
    try:
        return int(result.split()[-1])
    except Exception:
        return 0
