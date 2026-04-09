from __future__ import annotations

import asyncio
import time

import asyncpg
import httpx
from aiokafka.admin import AIOKafkaAdminClient
from fastapi import APIRouter
from redis.asyncio import Redis

from gateway_edge.config import settings
from gateway_edge.db.postgres import get_pool
from gateway_edge.models import HealthResponse, ServiceStatus
from gateway_edge.services.session import get_redis

router = APIRouter(tags=["health"])


async def _check_postgres() -> ServiceStatus:
    t0 = time.monotonic()
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return ServiceStatus(
            name="postgres",
            healthy=True,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        return ServiceStatus(name="postgres", healthy=False, detail=str(exc))


async def _check_valkey() -> ServiceStatus:
    t0 = time.monotonic()
    try:
        r: Redis = await get_redis()
        await r.ping()
        return ServiceStatus(
            name="valkey",
            healthy=True,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        return ServiceStatus(name="valkey", healthy=False, detail=str(exc))


async def _check_kafka() -> ServiceStatus:
    t0 = time.monotonic()
    try:
        client = AIOKafkaAdminClient(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            request_timeout_ms=3000,
        )
        await client.start()
        await client.close()
        return ServiceStatus(
            name="kafka",
            healthy=True,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        return ServiceStatus(name="kafka", healthy=False, detail=str(exc))


async def _check_ollama() -> ServiceStatus:
    t0 = time.monotonic()
    try:
        url = f"http://{settings.model_config.get('ollama_host', 'localhost') if False else 'localhost'}:11434/api/tags"
        # Read from config if available
        ollama_url = "http://localhost:11434/api/tags"
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(ollama_url)
        return ServiceStatus(
            name="ollama",
            healthy=resp.status_code == 200,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        return ServiceStatus(name="ollama", healthy=False, detail=str(exc))


async def _check_openbao() -> ServiceStatus:
    t0 = time.monotonic()
    try:
        url = settings.openbao_address.rstrip("/") + "/v1/sys/health"
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(url)
        healthy = resp.status_code in (200, 429, 472, 473)
        return ServiceStatus(
            name="openbao",
            healthy=healthy,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        return ServiceStatus(name="openbao", healthy=False, detail=str(exc))


@router.get("/health", response_model=None, include_in_schema=True)
async def liveness() -> dict:
    """Simple liveness probe — returns 200 if the process is alive."""
    return {"status": "ok"}


@router.get("/ready", response_model=HealthResponse)
async def readiness() -> HealthResponse:
    """Readiness probe — checks all downstream dependencies."""
    checks = await asyncio.gather(
        _check_postgres(),
        _check_valkey(),
        _check_kafka(),
        _check_ollama(),
        _check_openbao(),
        return_exceptions=False,
    )
    statuses: list[ServiceStatus] = list(checks)
    all_healthy = all(s.healthy for s in statuses)
    any_healthy = any(s.healthy for s in statuses)
    overall = "ok" if all_healthy else ("degraded" if any_healthy else "down")
    return HealthResponse(status=overall, services=statuses)
