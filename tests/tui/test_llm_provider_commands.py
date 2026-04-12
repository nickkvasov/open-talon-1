from __future__ import annotations

import os
import sys
from uuid import uuid4

import pytest

_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_TUI_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../apps/tui")
)
for path in (_CONTRACTS_DIR, _TUI_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_tui.main import (
    CollaborationApp,
    _build_llm_provider_payload,
    _parse_command_assignments,
)


def _provider_dict(**overrides):
    provider = {
        "provider_id": str(uuid4()),
        "engine_id": "openai-responses",
        "display_name": "OpenAI Responses",
        "description": "OpenAI Responses API",
        "provider": "openai",
        "endpoint_kind": "remote",
        "url": "https://api.openai.com/v1/responses",
        "default_model": "gpt-5.4-mini",
        "capabilities": ["text", "reasoning"],
        "locality": "cloud",
        "priority": 100,
        "enabled": True,
        "secret_config": {"openbao": {"path": "open-talon/llm/openai", "field": "api_key"}},
        "metadata": {"team": "platform"},
    }
    provider.update(overrides)
    return provider


def _build_app() -> CollaborationApp:
    return CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="test-profile",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Nikolay",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )


@pytest.mark.asyncio
async def test_llm_provider_list_shows_provider_inventory(monkeypatch):
    app = _build_app()
    writes: list[tuple[str, str]] = []
    provider = _provider_dict()

    async def fake_list_llm_providers():
        return [provider]

    monkeypatch.setattr(app, "_list_llm_providers", fake_list_llm_providers)
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))

    await app._handle_llm_provider_command("/llm-provider list")

    assert ("LLM Providers", "dim") in writes
    assert any("OpenAI Responses (openai-responses)" in content for content, _ in writes)
    assert any("provider: openai" in content for content, _ in writes)


@pytest.mark.asyncio
async def test_llm_provider_create_parses_key_value_payload(monkeypatch):
    app = _build_app()
    writes: list[tuple[str, str]] = []
    captured: dict[str, object] = {}

    async def fake_create_llm_provider(payload: dict[str, object]):
        captured.update(payload)
        return _provider_dict(
            engine_id=str(payload["engine_id"]),
            display_name=str(payload["display_name"]),
            provider=str(payload["provider"]),
            description=str(payload["description"]),
            url=payload.get("url"),
            default_model=payload.get("default_model"),
            capabilities=payload.get("capabilities"),
            locality=payload.get("locality"),
            priority=payload.get("priority"),
            enabled=payload.get("enabled"),
            secret_config=payload.get("secret_config"),
            metadata=payload.get("metadata"),
        )

    monkeypatch.setattr(app, "_create_llm_provider", fake_create_llm_provider)
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))

    await app._handle_llm_provider_command(
        "/llm-provider create "
        'engine_id=anthropic-claude display_name="Anthropic Claude" provider=anthropic '
        'description="Anthropic Messages API" url=https://api.anthropic.com/v1/messages '
        "default_model=claude-sonnet-4 capabilities=text,reasoning locality=cloud priority=120 "
        "enabled=false "
        'secret_config=\'{\"env\":{\"name\":\"ANTHROPIC_API_KEY\"}}\' '
        'metadata=\'{\"team\":\"agents\"}\''
    )

    assert captured["engine_id"] == "anthropic-claude"
    assert captured["display_name"] == "Anthropic Claude"
    assert captured["provider"] == "anthropic"
    assert captured["default_model"] == "claude-sonnet-4"
    assert captured["capabilities"] == ["text", "reasoning"]
    assert captured["priority"] == 120
    assert captured["enabled"] is False
    assert captured["secret_config"] == {"env": {"name": "ANTHROPIC_API_KEY"}}
    assert captured["metadata"] == {"team": "agents"}
    assert any("created llm provider: Anthropic Claude (anthropic-claude)" == content for content, _ in writes)


@pytest.mark.asyncio
async def test_llm_provider_update_resolves_target_and_updates_fields(monkeypatch):
    app = _build_app()
    writes: list[tuple[str, str]] = []
    provider = _provider_dict()
    captured: dict[str, object] = {}

    async def fake_list_llm_providers():
        return [provider]

    async def fake_update_llm_provider(provider_id: str, payload: dict[str, object]):
        captured["provider_id"] = provider_id
        captured["payload"] = payload
        return _provider_dict(
            provider_id=provider_id,
            enabled=payload["enabled"],
            priority=payload["priority"],
            capabilities=payload["capabilities"],
        )

    monkeypatch.setattr(app, "_list_llm_providers", fake_list_llm_providers)
    monkeypatch.setattr(app, "_update_llm_provider", fake_update_llm_provider)
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))

    await app._handle_llm_provider_command(
        "/llm-provider update openai-responses enabled=false priority=250 capabilities=text"
    )

    assert captured["provider_id"] == provider["provider_id"]
    assert captured["payload"] == {
        "enabled": False,
        "priority": 250,
        "capabilities": ["text"],
    }
    assert any("updated llm provider: OpenAI Responses (openai-responses)" == content for content, _ in writes)


def test_llm_provider_payload_builder_supports_model_alias_and_none_capabilities():
    payload = _build_llm_provider_payload(
        _parse_command_assignments(
            'engine_id=openai-responses display_name="OpenAI Responses" provider=openai '
            'description="Cloud responses endpoint" model=gpt-5.4-mini capabilities=none '
            'secret_config=\'{"openbao":{"path":"open-talon/llm/openai","field":"api_key"}}\''
        ),
        partial=False,
    )

    assert payload["default_model"] == "gpt-5.4-mini"
    assert payload["capabilities"] == []
    assert payload["secret_config"] == {
        "openbao": {"path": "open-talon/llm/openai", "field": "api_key"}
    }


def test_llm_provider_payload_builder_rejects_non_key_value_arguments():
    with pytest.raises(ValueError, match="expected key=value argument"):
        _parse_command_assignments("engine_id=openai-responses broken-token")
