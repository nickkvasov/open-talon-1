"""Admin routes — API key management."""
from __future__ import annotations

from fastapi import APIRouter, Request

from gateway_edge.auth.api_key import create_api_key, list_api_keys, revoke_api_key
from gateway_edge.authz import require_admin_access
from gateway_edge.models import ApiKeyCreate, ApiKeyInfo

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.post("/api-keys", response_model=ApiKeyInfo, summary="Create a new API key")
async def create_key(request: Request, payload: ApiKeyCreate) -> ApiKeyInfo:
    """Create an API key. The raw key is returned **once only**."""
    require_admin_access(request)
    return await create_api_key(payload)


@router.get("/api-keys", response_model=list[ApiKeyInfo], summary="List all API keys")
async def list_keys(request: Request) -> list[ApiKeyInfo]:
    require_admin_access(request)
    return await list_api_keys()


@router.delete("/api-keys/{key_id}", summary="Revoke an API key")
async def revoke_key(request: Request, key_id: str) -> dict:
    require_admin_access(request)
    deleted = await revoke_api_key(key_id)
    return {"deleted": deleted, "key_id": key_id}
