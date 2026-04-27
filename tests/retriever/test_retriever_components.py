from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timezone
import sys
from pathlib import Path
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "retriever"))

from retriever import ExtractorRegistry, RetrieverSettings, SimpleStructureAwareChunker  # noqa: E402
from open_talon_contracts.llm_engines import LlmEngineDescriptor, LlmEngineRegistry  # noqa: E402
from open_talon_contracts.models import LlmProviderDefinition  # noqa: E402
from retriever.llm import (  # noqa: E402
    LlmVisionProvider,
    ResolvedVisionEngine,
    default_vision_engine_descriptor,
    resolve_vision_engine,
)
from retriever.worker import RetrieverWorker  # noqa: E402


pytestmark = pytest.mark.unit


def test_text_and_html_extraction_feed_structure_aware_chunks() -> None:
    registry = ExtractorRegistry()
    text_document = registry.extract(
        b"# Heading\n\nFirst paragraph with useful evidence.\n\nSecond paragraph.",
        content_type="text/markdown",
        filename="source.md",
    )
    html_document = registry.extract(
        b"<html><body><h1>Title</h1><script>ignore()</script><p>Visible text.</p></body></html>",
        content_type="text/html",
        filename="source.html",
    )

    chunker = SimpleStructureAwareChunker()
    chunks = chunker.chunk(
        text_document,
        chunk_size_tokens=4,
        chunk_overlap_tokens=1,
    )

    assert [chunk.ordinal for chunk in chunks] == [0, 1, 2, 3]
    assert chunks[0].text == "# Heading"
    assert "Visible text." in html_document.segments[0].text
    assert "ignore" not in html_document.segments[0].text


def test_retriever_settings_use_ollama_defaults_and_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("RETRIEVER_DEFAULT_EMBEDDING_MODEL", "local-embed")
    monkeypatch.setenv("RETRIEVER_VISUAL_EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("RETRIEVER_OLLAMA_BASE_URL", "http://ollama.local:11434")

    settings = RetrieverSettings.from_env()

    assert settings.default_embedding_provider == "ollama"
    assert settings.default_embedding_model == "local-embed"
    assert settings.default_vision_engine_id == "local-ollama"
    assert settings.visual_extraction_enabled is True
    assert settings.ollama_base_url == "http://ollama.local:11434"


def test_retriever_vision_engine_uses_profile_provider_and_provider_default_model() -> None:
    settings = RetrieverSettings(default_vision_model="gemma4:31b")
    registry = LlmEngineRegistry(
        [
            default_vision_engine_descriptor(settings),
            LlmEngineDescriptor(
                engine_id="openai-vision",
                display_name="OpenAI Vision",
                description="Cloud vision provider.",
                provider="openai",
                endpoint_kind="remote",
                url="https://api.openai.com/v1/responses",
                default_model="gpt-vision-test",
                capabilities=["chat", "vision", "image_input"],
                locality="cloud",
                priority=200,
            ),
        ]
    )

    resolved = resolve_vision_engine(
        registry=registry,
        settings=settings,
        profile=SimpleNamespace(vision_provider_key="openai", vision_model=None),
    )

    assert resolved.descriptor.engine_id == "openai-vision"
    assert resolved.model == "gpt-vision-test"


@pytest.mark.asyncio
async def test_litellm_vision_provider_uses_resolved_cloud_engine(monkeypatch) -> None:
    request_log: dict[str, object] = {}

    async def fake_acompletion(**kwargs):
        request_log.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Chart text extracted.",
                    }
                }
            ]
        }

    class FakeResolver:
        async def resolve(self, references, *, label: str, required: bool = True):
            request_log["secret_references"] = references
            request_log["secret_label"] = label
            return "sk-anthropic-test"

    monkeypatch.setattr(
        "retriever.llm._load_litellm",
        lambda: SimpleNamespace(acompletion=fake_acompletion),
    )
    provider = LlmVisionProvider(
        settings=RetrieverSettings(),
        secret_resolver=FakeResolver(),
        timeout_seconds=3.0,
    )
    engine = ResolvedVisionEngine(
        descriptor=LlmEngineDescriptor(
            engine_id="anthropic-vision",
            display_name="Anthropic Vision",
            description="Cloud Anthropic vision provider.",
            provider="anthropic",
            endpoint_kind="remote",
            url="https://api.anthropic.com/v1/messages",
            default_model="claude-vision-test",
            capabilities=["chat", "vision", "image_input"],
            locality="cloud",
            metadata={"secret_config": {"env": {"name": "ANTHROPIC_API_KEY"}}},
        ),
        model="claude-vision-test",
    )

    text = await provider.describe_image(b"fake image", engine=engine, prompt="Read it.")

    assert text == "Chart text extracted."
    assert request_log["model"] == "anthropic/claude-vision-test"
    assert request_log["api_base"] == "https://api.anthropic.com"
    assert request_log["api_key"] == "sk-anthropic-test"
    assert request_log["timeout"] == 3.0
    assert request_log["secret_label"] == "anthropic API key"


@pytest.mark.asyncio
async def test_retriever_worker_resolves_organization_scoped_vision_provider() -> None:
    organization_id = uuid4()
    actor_id = uuid4()
    now = datetime.now(timezone.utc)
    provider = LlmProviderDefinition(
        provider_id=uuid4(),
        scope="organization",
        organization_id=organization_id,
        engine_id="org-vision",
        display_name="Org Vision",
        description="Organization-specific vision model.",
        provider="anthropic",
        endpoint_kind="remote",
        url="https://api.anthropic.com/v1/messages",
        default_model="org-vision-model",
        capabilities=["chat", "vision", "image_input"],
        locality="cloud",
        priority=250,
        enabled=True,
        secret_config={"env": {"name": "ANTHROPIC_API_KEY"}},
        created_by=actor_id,
        created_at=now,
        updated_by=actor_id,
        updated_at=now,
    )

    class FakeRepository:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        async def list_llm_providers(self, *, scope: str, organization_id=None):
            self.calls.append((scope, organization_id))
            if scope == "organization" and organization_id == provider.organization_id:
                return [provider]
            return []

    repository = FakeRepository()
    worker = RetrieverWorker(RetrieverSettings())
    worker._repository = repository  # noqa: SLF001

    resolved = await worker._vision_engine(  # noqa: SLF001
        profile=SimpleNamespace(vision_provider_key="org-vision", vision_model=None),
        job=SimpleNamespace(organization_id=organization_id),
    )

    assert resolved.descriptor.engine_id == "org-vision"
    assert resolved.model == "org-vision-model"
    assert repository.calls == [("global", None), ("organization", organization_id)]
