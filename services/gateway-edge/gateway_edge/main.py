from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from gateway_edge.audit_middleware import AuditMiddleware
from gateway_edge.auth.middleware import AuthMiddleware
from gateway_edge.config import settings
from gateway_edge.db.postgres import setup_postgres, teardown_postgres
from gateway_edge.routers import admin, auth, chat, collaboration, health, iam, mcp
from gateway_edge.services.audit import audit_service
from gateway_edge.services.collaboration import collaboration_service
from gateway_edge.services.events import event_service
from gateway_edge.services.operational_bootstrap import operational_bootstrap_service
from gateway_edge.services.session import setup_valkey, teardown_valkey

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parents[3] / "apps" / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Starting Open Talon API Gateway …")
    await setup_postgres()
    await setup_valkey()
    await event_service.start()
    await collaboration_service.start()
    await audit_service.start()
    await operational_bootstrap_service.start()
    logger.info("Gateway ready — auth_mode=%s", settings.auth_mode)
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Shutting down …")
    await operational_bootstrap_service.stop()
    await audit_service.stop()
    await collaboration_service.stop()
    await event_service.stop()
    await teardown_valkey()
    await teardown_postgres()
    logger.info("Gateway stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Open Talon API Gateway",
        description=(
            "Multi-interface API gateway: REST, SSE streaming, WebSocket.\n\n"
            "Fronts the Open Talon collaboration kernel for workspaces, threads, and shared event timelines."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.state.settings = settings

    # ── Auth ─────────────────────────────────────────────────────────────────
    app.add_middleware(AuthMiddleware)
    app.add_middleware(AuditMiddleware)

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Add CORS last so it wraps auth/audit responses too, including 401/403s.
    if settings.cors_origins.strip() == "*":
        origins = ["*"]
    else:
        configured_origins = [
            origin.strip()
            for origin in settings.cors_origins.split(",")
            if origin.strip() and origin.strip() != "*"
        ]
        origins = list(dict.fromkeys(configured_origins))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(collaboration.router)
    app.include_router(iam.router)
    app.include_router(admin.router)
    if settings.mcp_enabled:
        app.include_router(mcp.router)

    # ── Static Web UI ─────────────────────────────────────────────────────────
    if _WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_WEB_DIR)), name="web-static")

        @app.get("/", include_in_schema=False)
        async def web_index():
            return FileResponse(_WEB_DIR / "index.html")

    return app


app = create_app()


def main():
    import uvicorn

    uvicorn.run(
        "gateway_edge.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=True,
    )


if __name__ == "__main__":
    main()
