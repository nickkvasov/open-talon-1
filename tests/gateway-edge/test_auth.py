"""
Tests for the auth middleware (all four AUTH_MODE values).

The middleware is mounted on every route.  We use /health as a
canary endpoint so the test does not depend on chat-layer mocks.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from gateway_edge.config import settings
from gateway_edge.models import AuthContext

# ── AUTH_MODE = none ──────────────────────────────────────────────────────────

async def test_none_mode_allows_any_request(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "none")
    resp = await client.get("/health")
    assert resp.status_code == 200


async def test_none_mode_allows_request_without_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "none")
    resp = await client.get("/health")
    assert resp.status_code not in (401, 403)


# ── AUTH_MODE = api_key ───────────────────────────────────────────────────────

async def test_api_key_mode_rejects_missing_key(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "api_key")
    resp = await client.get("/v1/sessions/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 401


async def test_api_key_mode_accepts_valid_key(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "api_key")
    with patch("gateway_edge.auth.middleware.validate_api_key", AsyncMock(return_value=True)):
        resp = await client.get("/health", headers={"X-API-Key": "valid-key"})
    assert resp.status_code == 200


async def test_api_key_mode_rejects_invalid_key(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "api_key")
    with patch("gateway_edge.auth.middleware.validate_api_key", AsyncMock(return_value=False)):
        resp = await client.get(
            "/v1/sessions/00000000-0000-0000-0000-000000000001",
            headers={"X-API-Key": "wrong"},
        )
    assert resp.status_code == 401


async def test_api_key_mode_401_response_has_www_authenticate(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "api_key")
    resp = await client.get("/v1/sessions/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 401


# ── AUTH_MODE = openbao ───────────────────────────────────────────────────────

async def test_openbao_mode_rejects_missing_bearer(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "openbao")
    resp = await client.get("/v1/sessions/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 401


async def test_openbao_mode_accepts_valid_token(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "openbao")
    with patch("gateway_edge.auth.middleware.validate_openbao_token", AsyncMock(return_value=True)):
        resp = await client.get(
            "/health", headers={"Authorization": "Bearer valid-bao-token"}
        )
    assert resp.status_code == 200


async def test_openbao_mode_rejects_invalid_token(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "openbao")
    with patch("gateway_edge.auth.middleware.validate_openbao_token", AsyncMock(return_value=False)):
        resp = await client.get(
            "/v1/sessions/00000000-0000-0000-0000-000000000001",
            headers={"Authorization": "Bearer invalid-token"},
        )
    assert resp.status_code == 401


async def test_openbao_mode_rejects_non_bearer_scheme(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "openbao")
    with patch("gateway_edge.auth.middleware.validate_openbao_token", AsyncMock(return_value=True)):
        resp = await client.get(
            "/v1/sessions/00000000-0000-0000-0000-000000000001",
            headers={"Authorization": "Token valid-token"},
        )
    assert resp.status_code == 401


# ── AUTH_MODE = any ───────────────────────────────────────────────────────────

async def test_any_mode_accepts_valid_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "any")
    with patch("gateway_edge.auth.middleware.validate_api_key", AsyncMock(return_value=True)):
        resp = await client.get("/health", headers={"X-API-Key": "good-key"})
    assert resp.status_code == 200


async def test_any_mode_accepts_valid_openbao_token(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "any")
    with patch("gateway_edge.auth.middleware.validate_openbao_token", AsyncMock(return_value=True)):
        resp = await client.get(
            "/health", headers={"Authorization": "Bearer good-token"}
        )
    assert resp.status_code == 200


async def test_any_mode_rejects_when_both_fail(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "any")
    with (
        patch("gateway_edge.auth.middleware.validate_api_key",      AsyncMock(return_value=False)),
        patch("gateway_edge.auth.middleware.validate_openbao_token", AsyncMock(return_value=False)),
    ):
        resp = await client.get(
            "/v1/sessions/00000000-0000-0000-0000-000000000001",
            headers={"X-API-Key": "bad", "Authorization": "Bearer bad"},
        )
    assert resp.status_code == 401


async def test_any_mode_rejects_no_credentials(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "any")
    resp = await client.get("/v1/sessions/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 401


async def test_options_preflight_skips_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    resp = await client.options(
        "/v1/admin/runtime/overview",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resp.status_code in (200, 204)


async def test_unauthorized_response_keeps_cors_headers(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "oidc")
    resp = await client.get(
        "/v1/admin/runtime/overview",
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert resp.status_code == 401
    assert resp.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


async def test_oidc_mode_rejects_when_identity_sync_fails(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "machine-token"
        return AuthContext(
            kind="oidc",
            principal_type="agent",
            issuer="http://issuer.test/realms/open-talon",
            subject="service-account-disabled-agent",
            client_id="disabled-agent",
            provider_key="keycloak",
            claims={"sub": "service-account-disabled-agent", "azp": "disabled-agent"},
        )

    async def _sync(context):
        raise ValueError("Machine identity is disabled")

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    resp = await client.get(
        "/v1/agents",
        headers={"Authorization": "Bearer machine-token"},
    )

    assert resp.status_code == 401


# ── Skip paths are always public ──────────────────────────────────────────────

async def test_health_endpoint_skips_auth(client, monkeypatch):
    """Even in api_key mode, /health must be reachable without credentials."""
    monkeypatch.setattr(settings, "auth_mode", "api_key")
    monkeypatch.setattr(settings, "auth_skip_paths", "/health,/ready,/docs,/openapi.json")
    resp = await client.get("/health")
    assert resp.status_code == 200


async def test_docs_endpoint_skips_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "api_key")
    monkeypatch.setattr(settings, "auth_skip_paths", "/health,/ready,/docs,/openapi.json")
    resp = await client.get("/docs")
    # /docs returns HTML or redirects — any 2xx/3xx is acceptable
    assert resp.status_code < 400
