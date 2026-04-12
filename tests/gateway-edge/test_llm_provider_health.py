from __future__ import annotations

import os
import sys
from uuid import uuid4

import httpx
import pytest

_GW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/gateway-edge")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
for path in (_GW_DIR, _CONTRACTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from gateway_edge.models import LlmProviderDefinition
from gateway_edge.services.llm_provider_health import check_llm_provider_health


def _provider(**overrides) -> LlmProviderDefinition:
    payload = {
        "provider_id": uuid4(),
        "engine_id": "anthropic-sonnet",
        "display_name": "Anthropic Sonnet",
        "description": "Health-check test provider.",
        "provider": "anthropic",
        "endpoint_kind": "remote",
        "url": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-sonnet-4-5",
        "capabilities": ["chat", "reasoning"],
        "locality": "cloud",
        "priority": 180,
        "enabled": True,
        "secret_config": {
            "openbao": {
                "mount": "secret",
                "path": "open-talon/llm/anthropic",
                "field": "api_key",
            }
        },
        "created_by": uuid4(),
        "updated_by": uuid4(),
        "metadata": {},
    }
    payload.update(overrides)
    return LlmProviderDefinition(**payload)


@pytest.mark.asyncio
async def test_llm_provider_health_uses_openbao_secret_and_anthropic_headers(monkeypatch):
    monkeypatch.setenv("OPEN_TALON_OPENBAO_TOKEN", "root-token")

    calls: list[tuple[str, dict[str, str] | None]] = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, follow_redirects=False):
            calls.append((url, headers))
            if url.endswith("/v1/secret/data/open-talon/llm/anthropic"):
                return httpx.Response(
                    200,
                    request=httpx.Request("GET", url),
                    json={"data": {"data": {"api_key": "anthropic-secret"}}},
                )
            assert url == "https://api.anthropic.com/v1/messages"
            assert headers == {
                "x-api-key": "anthropic-secret",
                "anthropic-version": "2023-06-01",
            }
            return httpx.Response(405, request=httpx.Request("GET", url))

    monkeypatch.setattr(
        "gateway_edge.services.llm_provider_health.httpx.AsyncClient",
        FakeAsyncClient,
    )

    report = await check_llm_provider_health(_provider())

    assert report.status == "healthy"
    checks = {check.name: check for check in report.checks}
    assert checks["secret"].status == "ok"
    assert checks["secret"].metadata["source"] == "openbao"
    assert checks["connectivity"].status == "ok"
    assert calls[0][0].endswith("/v1/secret/data/open-talon/llm/anthropic")


@pytest.mark.asyncio
async def test_llm_provider_health_treats_401_as_degraded(monkeypatch):
    provider = _provider(
        provider="openai",
        url="https://api.openai.com/v1/responses",
        secret_config={"env": {"name": "OPENAI_API_KEY"}},
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, follow_redirects=False):
            assert headers == {"Authorization": "Bearer sk-test"}
            return httpx.Response(401, request=httpx.Request("GET", url))

    monkeypatch.setattr(
        "gateway_edge.services.llm_provider_health.httpx.AsyncClient",
        FakeAsyncClient,
    )

    report = await check_llm_provider_health(provider)

    assert report.status == "degraded"
    checks = {check.name: check for check in report.checks}
    assert checks["secret"].status == "ok"
    assert checks["connectivity"].status == "warn"
    assert checks["connectivity"].metadata["status_code"] == 401


@pytest.mark.asyncio
async def test_llm_provider_health_accepts_system_provider_without_url():
    report = await check_llm_provider_health(
        _provider(
            provider="internal",
            endpoint_kind="system",
            url=None,
            secret_config={},
        )
    )

    assert report.status == "degraded"
    checks = {check.name: check for check in report.checks}
    assert checks["url"].status == "ok"
    assert checks["connectivity"].status == "warn"
