"""Admin routes — API key management."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from gateway_edge.auth.api_key import create_api_key, list_api_keys, revoke_api_key
from gateway_edge.config import settings
from gateway_edge.models import ApiKeyCreate, ApiKeyInfo, AuthContext

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _require_admin_access(request: Request) -> None:
    if settings.auth_mode == "none":
        return
    auth_context = getattr(request.state, "auth_context", None)
    if isinstance(auth_context, AuthContext):
        if auth_context.kind == "api_key":
            return
        if auth_context.kind == "oidc" and settings.oidc_admin_role in auth_context.roles:
            return
    raise HTTPException(status_code=403, detail="Admin access required")


@router.post("/api-keys", response_model=ApiKeyInfo, summary="Create a new API key")
async def create_key(request: Request, payload: ApiKeyCreate) -> ApiKeyInfo:
    """Create an API key. The raw key is returned **once only**."""
    _require_admin_access(request)
    return await create_api_key(payload)


@router.get("/api-keys", response_model=list[ApiKeyInfo], summary="List all API keys")
async def list_keys(request: Request) -> list[ApiKeyInfo]:
    _require_admin_access(request)
    return await list_api_keys()


@router.delete("/api-keys/{key_id}", summary="Revoke an API key")
async def revoke_key(request: Request, key_id: str) -> dict:
    _require_admin_access(request)
    deleted = await revoke_api_key(key_id)
    return {"deleted": deleted, "key_id": key_id}
