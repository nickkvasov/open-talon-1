"""
Tests for /health and /ready endpoints.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


# ── /health ────────────────────────────────────────────────────────────────────

async def test_liveness_returns_ok(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_liveness_is_fast(client):
    """Liveness must not block on external services."""
    import time
    t0 = time.monotonic()
    await client.get("/health")
    assert (time.monotonic() - t0) < 0.5


# ── /ready ─────────────────────────────────────────────────────────────────────

async def test_readiness_response_shape(client):
    """GET /ready returns a HealthResponse with the correct top-level keys."""
    with (
        patch("app.routers.health._check_postgres",  AsyncMock(return_value=_svc("postgres", True))),
        patch("app.routers.health._check_valkey",    AsyncMock(return_value=_svc("valkey",   True))),
        patch("app.routers.health._check_kafka",     AsyncMock(return_value=_svc("kafka",    True))),
        patch("app.routers.health._check_ollama",    AsyncMock(return_value=_svc("ollama",   True))),
        patch("app.routers.health._check_openbao",   AsyncMock(return_value=_svc("openbao",  True))),
    ):
        resp = await client.get("/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert "services" in body
    assert "timestamp" in body


async def test_readiness_all_healthy(client):
    with (
        patch("app.routers.health._check_postgres",  AsyncMock(return_value=_svc("postgres", True))),
        patch("app.routers.health._check_valkey",    AsyncMock(return_value=_svc("valkey",   True))),
        patch("app.routers.health._check_kafka",     AsyncMock(return_value=_svc("kafka",    True))),
        patch("app.routers.health._check_ollama",    AsyncMock(return_value=_svc("ollama",   True))),
        patch("app.routers.health._check_openbao",   AsyncMock(return_value=_svc("openbao",  True))),
    ):
        resp = await client.get("/ready")

    assert resp.json()["status"] == "ok"
    names = {s["name"] for s in resp.json()["services"]}
    assert names == {"postgres", "valkey", "kafka", "ollama", "openbao"}


async def test_readiness_degraded_when_one_service_down(client):
    with (
        patch("app.routers.health._check_postgres",  AsyncMock(return_value=_svc("postgres", False, "connection refused"))),
        patch("app.routers.health._check_valkey",    AsyncMock(return_value=_svc("valkey",   True))),
        patch("app.routers.health._check_kafka",     AsyncMock(return_value=_svc("kafka",    True))),
        patch("app.routers.health._check_ollama",    AsyncMock(return_value=_svc("ollama",   True))),
        patch("app.routers.health._check_openbao",   AsyncMock(return_value=_svc("openbao",  True))),
    ):
        resp = await client.get("/ready")

    assert resp.json()["status"] == "degraded"


async def test_readiness_down_when_all_services_down(client):
    with (
        patch("app.routers.health._check_postgres",  AsyncMock(return_value=_svc("postgres", False))),
        patch("app.routers.health._check_valkey",    AsyncMock(return_value=_svc("valkey",   False))),
        patch("app.routers.health._check_kafka",     AsyncMock(return_value=_svc("kafka",    False))),
        patch("app.routers.health._check_ollama",    AsyncMock(return_value=_svc("ollama",   False))),
        patch("app.routers.health._check_openbao",   AsyncMock(return_value=_svc("openbao",  False))),
    ):
        resp = await client.get("/ready")

    assert resp.json()["status"] == "down"


async def test_readiness_runs_five_checks_in_parallel(client):
    """All five service checks must be called on every /ready request."""
    mocks = {
        "postgres": AsyncMock(return_value=_svc("postgres", True)),
        "valkey":   AsyncMock(return_value=_svc("valkey",   True)),
        "kafka":    AsyncMock(return_value=_svc("kafka",    True)),
        "ollama":   AsyncMock(return_value=_svc("ollama",   True)),
        "openbao":  AsyncMock(return_value=_svc("openbao",  True)),
    }
    with (
        patch("app.routers.health._check_postgres", mocks["postgres"]),
        patch("app.routers.health._check_valkey",   mocks["valkey"]),
        patch("app.routers.health._check_kafka",    mocks["kafka"]),
        patch("app.routers.health._check_ollama",   mocks["ollama"]),
        patch("app.routers.health._check_openbao",  mocks["openbao"]),
    ):
        await client.get("/ready")

    for m in mocks.values():
        m.assert_called_once()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _svc(name: str, healthy: bool, detail: str | None = None):
    from app.models import ServiceStatus
    return ServiceStatus(name=name, healthy=healthy, detail=detail)
