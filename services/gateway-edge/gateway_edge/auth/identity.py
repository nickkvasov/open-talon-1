from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from core_collab.repository import AuthIdentityRecord, CollaborationRepository, UserRecord

from gateway_edge.models import AuthContext
from gateway_edge.db.postgres import get_pool


async def sync_oidc_auth_context(context: AuthContext) -> AuthContext:
    if context.kind != "oidc":
        return context
    if not context.issuer or not context.subject:
        raise ValueError("OIDC auth context requires issuer and subject")

    pool = await get_pool()
    repository = CollaborationRepository(pool)
    identity = await repository.fetch_auth_identity(context.issuer, context.subject)
    now = datetime.now(timezone.utc)
    display_name = context.display_name or context.email or context.subject
    email = context.email
    metadata = {
        "claims": context.claims,
        "roles": context.roles,
    }

    async with pool.acquire() as conn:
        async with conn.transaction():
            user_id = identity.user_id if identity is not None else uuid4()
            await repository.upsert_user(
                conn,
                UserRecord(
                    user_id=user_id,
                    display_name=display_name,
                    created_at=now,
                    updated_at=now,
                    metadata={"email": email} if email else {},
                ),
            )
            await repository.upsert_auth_identity(
                conn,
                AuthIdentityRecord(
                    user_id=user_id,
                    issuer=context.issuer,
                    subject=context.subject,
                    email=email,
                    display_name=display_name,
                    metadata=metadata,
                ),
            )

    return context.model_copy(update={"user_id": user_id, "display_name": display_name})
