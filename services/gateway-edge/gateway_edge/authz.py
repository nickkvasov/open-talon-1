from __future__ import annotations

from fastapi import HTTPException, Request

from gateway_edge.config import settings
from gateway_edge.models import AuthContext


def require_admin_access(request: Request) -> None:
    if settings.auth_mode == "none":
        return
    auth_context = getattr(request.state, "auth_context", None)
    if isinstance(auth_context, AuthContext):
        if auth_context.kind == "api_key":
            return
        if auth_context.kind == "oidc" and settings.oidc_admin_role in auth_context.roles:
            return
    raise HTTPException(status_code=403, detail="Admin access required")
