from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from gateway_edge.models import AuthContext, MeResponse

router = APIRouter(prefix="/v1", tags=["auth"])


@router.get("/me", response_model=MeResponse, summary="Get the authenticated user identity")
async def get_me(request: Request) -> MeResponse:
    auth_context = getattr(request.state, "auth_context", None)
    if (
        not isinstance(auth_context, AuthContext)
        or auth_context.kind != "oidc"
        or auth_context.principal_type != "human"
    ):
        raise HTTPException(status_code=401, detail="OIDC authentication required")
    if auth_context.user_id is None or not auth_context.issuer or not auth_context.subject:
        raise HTTPException(status_code=401, detail="Authenticated user context is incomplete")
    return MeResponse(
        user_id=auth_context.user_id,
        issuer=auth_context.issuer,
        subject=auth_context.subject,
        email=auth_context.email,
        display_name=auth_context.display_name or auth_context.subject,
        roles=auth_context.roles,
        claims=auth_context.claims,
    )
