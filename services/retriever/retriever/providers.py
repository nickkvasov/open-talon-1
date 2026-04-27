from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ExtractedSegment:
    text: str
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    segment_kind: str = "text"
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedDocument:
    segments: list[ExtractedSegment]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    text: str
    ordinal: int
    source_segment: ExtractedSegment
    token_count: int
    metadata: dict[str, object] = field(default_factory=dict)


class DocumentExtractor(Protocol):
    def supports(self, *, content_type: str | None, filename: str | None) -> bool:
        ...

    def extract(
        self,
        payload: bytes,
        *,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> ExtractedDocument:
        ...


class Chunker(Protocol):
    def chunk(
        self,
        document: ExtractedDocument,
        *,
        chunk_size_tokens: int,
        chunk_overlap_tokens: int,
    ) -> list[Chunk]:
        ...


class TextEmbeddingProvider(Protocol):
    provider_key: str

    async def embed_texts(self, texts: list[str], *, model: str) -> list[list[float]]:
        ...


class VisualExtractor(Protocol):
    provider_key: str

    async def describe_image(
        self,
        image_bytes: bytes,
        *,
        model: str,
        prompt: str,
    ) -> str:
        ...
