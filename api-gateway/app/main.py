from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.auth.middleware import AuthMiddleware
from app.config import settings
from app.db.postgres import setup_postgres, teardown_postgres
from app.routers import admin, chat, health
from app.services.events import event_service
from app.services.session import setup_valkey, teardown_valkey

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Starting Open Talon API Gateway …")
    await setup_postgres()
    await setup_valkey()
    await event_service.start()
    logger.info("Gateway ready — auth_mode=%s", settings.auth_mode)
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Shutting down …")
    await event_service.stop()
    await teardown_valkey()
    await teardown_postgres()
    logger.info("Gateway stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Open Talon API Gateway",
        description=(
            "Multi-interface API gateway: REST, SSE streaming, WebSocket.\n\n"
            "Publishes chat requests to Kafka and waits for agent responses."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    origins = (
        ["*"]
        if settings.cors_origins.strip() == "*"
        else [o.strip() for o in settings.cors_origins.split(",")]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Auth ─────────────────────────────────────────────────────────────────
    app.add_middleware(AuthMiddleware)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(admin.router)

    # ── Static Web UI ─────────────────────────────────────────────────────────
    if _WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")

    return app


app = create_app()

def main():
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        reload=True,
    )


if __name__ == "__main__":
    main()
