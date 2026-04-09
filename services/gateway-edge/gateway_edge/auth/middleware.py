"""
Auth middleware.

Dispatches to the correct backend(s) depending on AUTH_MODE:

  none     → always allow
  api_key  → require valid X-API-Key header
  openbao  → require valid Bearer token (validated against OpenBao)
  any      → allow if either api_key OR openbao passes
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from gateway_edge.auth.api_key import validate_api_key
from gateway_edge.auth.openbao import validate_openbao_token
from gateway_edge.config import settings

logger = logging.getLogger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        self._skip_paths: set[str] = {
            p.strip() for p in settings.auth_skip_paths.split(",") if p.strip()
        }

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Always allow skipped paths
        if request.url.path in self._skip_paths:
            return await call_next(request)

        mode = settings.auth_mode
        if mode == "none":
            return await call_next(request)

        if mode == "api_key":
            if await self._check_api_key(request):
                return await call_next(request)
            return self._deny("Invalid or missing X-API-Key")

        if mode == "openbao":
            if await self._check_openbao(request):
                return await call_next(request)
            return self._deny("Invalid or missing Bearer token")

        if mode == "any":
            if await self._check_api_key(request) or await self._check_openbao(request):
                return await call_next(request)
            return self._deny("Authentication required (api_key or openbao)")

        return self._deny(f"Unknown auth mode: {mode}")

    @staticmethod
    async def _check_api_key(request: Request) -> bool:
        raw_key = request.headers.get("X-API-Key", "")
        if not raw_key:
            return False
        return await validate_api_key(raw_key)

    @staticmethod
    async def _check_openbao(request: Request) -> bool:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return False
        token = auth_header[7:].strip()
        if not token:
            return False
        return await validate_openbao_token(token)

    @staticmethod
    def _deny(detail: str) -> JSONResponse:
        logger.debug("Auth denied: %s", detail)
        return JSONResponse(
            status_code=401,
            content={"detail": detail},
            headers={"WWW-Authenticate": "Bearer, X-API-Key"},
        )
