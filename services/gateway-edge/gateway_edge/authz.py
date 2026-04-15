from __future__ import annotations

from fastapi import HTTPException, Request

from gateway_edge.config import settings
from gateway_edge.models import AuthContext


def has_admin_access(request: Request) -> bool:
    if settings.auth_mode == "none":
        return True
    auth_context = getattr(request.state, "auth_context", None)
    if isinstance(auth_context, AuthContext):
        if auth_context.kind == "api_key":
            return True
        if auth_context.kind == "oidc" and settings.oidc_admin_role in auth_context.roles:
            return True
    return False


def require_admin_access(request: Request) -> None:
    if has_admin_access(request):
        return
    raise HTTPException(status_code=403, detail="Admin access required")
