"""
OpenBao token auth backend.

The client presents:  Authorization: Bearer <bao_token>

The gateway calls  GET /v1/auth/token/lookup-self  with that token.
If OpenBao returns 200, the token is valid.
"""
from __future__ import annotations

import logging

import httpx

from gateway_edge.config import settings

logger = logging.getLogger(__name__)

_LOOKUP_PATH = "/v1/auth/token/lookup-self"


async def validate_openbao_token(token: str) -> bool:
    """Return True if the bearer token is valid according to OpenBao."""
    url = settings.openbao_address.rstrip("/") + _LOOKUP_PATH
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url, headers={"X-Vault-Token": token})
        if resp.status_code == 200:
            return True
        logger.debug("OpenBao rejected token: HTTP %s", resp.status_code)
        return False
    except httpx.RequestError as exc:
        logger.warning("OpenBao unreachable: %s", exc)
        return False


async def check_openbao_ready() -> bool:
    """Liveness check — returns True if OpenBao responds to sys/health."""
    url = settings.openbao_address.rstrip("/") + "/v1/sys/health"
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(url)
        return resp.status_code in (200, 429, 472, 473)
    except httpx.RequestError:
        return False
