from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from gateway_edge.services.audit import audit_service


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request.state.request_id = uuid4()
        request.state.correlation_id = uuid4()
        started_at = datetime.now(UTC)
        try:
            response = await call_next(request)
        except Exception as exc:
            await audit_service.record_http_audit(
                request=request,
                response=None,
                started_at=started_at,
                error=exc,
            )
            raise
        await audit_service.record_http_audit(
            request=request,
            response=response,
            started_at=started_at,
        )
        return response
