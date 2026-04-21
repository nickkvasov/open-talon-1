from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from core_collab.repository import AuthIdentityRecord, CollaborationRepository, UserRecord

from gateway_edge.models import AuthContext
from gateway_edge.db.postgres import get_pool


async def sync_oidc_auth_context(context: AuthContext) -> AuthContext:
    if context.kind != "oidc":
        return context
    if context.principal_type == "agent":
        if not context.issuer or not context.client_id or not context.provider_key:
            raise ValueError("OIDC machine auth context is incomplete")
        pool = await get_pool()
        repository = CollaborationRepository(pool)
        identity = await repository.fetch_agent_identity_by_client(
            provider_key=context.provider_key,
            issuer=context.issuer,
            client_id=context.client_id,
        )
        if identity is None:
            raise ValueError(f"Unknown machine identity for client_id {context.client_id}")
        if identity.status != "active":
            raise ValueError(f"Machine identity {identity.agent_identity_id} is disabled")
        now = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.upsert_agent_identity(
                    conn,
                    identity.model_copy(update={"last_authenticated_at": now, "updated_at": now}),
                )
        return context.model_copy(
            update={
                "agent_identity_id": identity.agent_identity_id,
                "system_agent_id": identity.system_agent_id,
                "display_name": context.display_name or context.client_id,
            }
        )
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
