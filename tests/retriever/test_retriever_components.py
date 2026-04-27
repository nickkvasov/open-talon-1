from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "retriever"))

from retriever import ExtractorRegistry, RetrieverSettings, SimpleStructureAwareChunker  # noqa: E402


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
    assert settings.visual_extraction_enabled is True
    assert settings.ollama_base_url == "http://ollama.local:11434"
