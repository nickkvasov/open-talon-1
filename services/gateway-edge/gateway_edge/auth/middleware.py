"""
Auth middleware.

Dispatches to the correct backend(s) depending on AUTH_MODE:

  none     → always allow
  api_key  → require valid X-API-Key header
  openbao  → require valid Bearer token (validated against OpenBao)
  oidc     → require valid Bearer token (validated against OIDC discovery + JWKS)
  any      → allow if either api_key, oidc, or openbao passes
"""
from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from gateway_edge.auth.api_key import validate_api_key
from gateway_edge.auth.identity import sync_oidc_auth_context
from gateway_edge.auth.oidc import validate_oidc_token
from gateway_edge.auth.openbao import validate_openbao_token
from gateway_edge.config import settings
from gateway_edge.models import AuthContext

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
        request.state.auth_context = None
        # Browser clients need unauthenticated CORS preflight requests to succeed.
        if request.method == "OPTIONS":
            return await call_next(request)
        # Always allow skipped paths
        if request.url.path in self._skip_paths:
            return await call_next(request)

        mode = settings.auth_mode
        if mode == "none":
            return await call_next(request)

        if mode == "api_key":
            if auth_context := await self._check_api_key(request):
                request.state.auth_context = auth_context
                return await call_next(request)
            return self._deny("Invalid or missing X-API-Key")

        if mode == "openbao":
            if await self._check_openbao(request):
                return await call_next(request)
            return self._deny("Invalid or missing Bearer token")

        if mode == "oidc":
            if auth_context := await self._check_oidc(request):
                request.state.auth_context = auth_context
                return await call_next(request)
            return self._deny("Invalid or missing OIDC Bearer token")

        if mode == "any":
            if auth_context := await self._check_api_key(request):
                request.state.auth_context = auth_context
                return await call_next(request)
            if auth_context := await self._check_oidc(request):
                request.state.auth_context = auth_context
                return await call_next(request)
            if await self._check_openbao(request):
                return await call_next(request)
            return self._deny("Authentication required (api_key, oidc, or openbao)")

        return self._deny(f"Unknown auth mode: {mode}")

    @staticmethod
    async def _check_api_key(request: Request) -> AuthContext | None:
        raw_key = request.headers.get("X-API-Key", "")
        if not raw_key:
            return None
        if not await validate_api_key(raw_key):
            return None
        return AuthContext(kind="api_key")

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
    async def _check_oidc(request: Request) -> AuthContext | None:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return None
        token = auth_header[7:].strip()
        if not token:
            return None
        try:
            auth_context = await validate_oidc_token(token)
            if auth_context is None:
                return None
            return await sync_oidc_auth_context(auth_context)
        except Exception:
            logger.warning("OIDC authentication failed during token synchronization", exc_info=True)
            return None

    @staticmethod
    def _deny(detail: str) -> JSONResponse:
        logger.debug("Auth denied: %s", detail)
        return JSONResponse(
            status_code=401,
            content={"detail": detail},
            headers={"WWW-Authenticate": "Bearer, X-API-Key"},
        )
