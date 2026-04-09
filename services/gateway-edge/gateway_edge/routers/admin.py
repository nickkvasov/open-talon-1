"""Admin routes — API key management."""
from __future__ import annotations

from fastapi import APIRouter

from gateway_edge.auth.api_key import create_api_key, list_api_keys, revoke_api_key
from gateway_edge.models import ApiKeyCreate, ApiKeyInfo

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.post("/api-keys", response_model=ApiKeyInfo, summary="Create a new API key")
async def create_key(payload: ApiKeyCreate) -> ApiKeyInfo:
    """Create an API key. The raw key is returned **once only**."""
    return await create_api_key(payload)


@router.get("/api-keys", response_model=list[ApiKeyInfo], summary="List all API keys")
async def list_keys() -> list[ApiKeyInfo]:
    return await list_api_keys()


@router.delete("/api-keys/{key_id}", summary="Revoke an API key")
async def revoke_key(key_id: str) -> dict:
    deleted = await revoke_api_key(key_id)
    return {"deleted": deleted, "key_id": key_id}
