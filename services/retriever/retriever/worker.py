from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import logging
from pathlib import Path
import sys
from uuid import uuid4

import asyncpg
from open_talon_contracts.models import (
    RetrievalChunk,
    RetrievalChunkCitation,
    RetrievalEmbedding,
)

_ROOT_DIR = Path(__file__).resolve().parents[3]
for relative in (
    "packages/contracts",
    "services/core-collab",
    "services/gateway-edge",
    "services/retriever",
):
    path = str(_ROOT_DIR / relative)
    if path not in sys.path:
        sys.path.insert(0, path)

from core_collab import CollaborationKernel, CollaborationRepository  # noqa: E402
from gateway_edge.services.object_storage import MinioObjectStorage  # noqa: E402

from .chunking import SimpleStructureAwareChunker
from .config import RetrieverSettings
from .extractors import ExtractorRegistry
from .ollama import OllamaEmbeddingProvider, OllamaVisionProvider
from .providers import ExtractedSegment


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class RetrieverWorker:
    def __init__(self, settings: RetrieverSettings) -> None:
        self._settings = settings
        self._extractors = ExtractorRegistry()
        self._chunker = SimpleStructureAwareChunker()
        self._embedding_provider = OllamaEmbeddingProvider(
            base_url=settings.ollama_base_url,
        )
        self._vision_provider = OllamaVisionProvider(base_url=settings.ollama_base_url)
        self._pool: asyncpg.Pool | None = None
        self._repository: CollaborationRepository | None = None
        self._kernel: CollaborationKernel | None = None
        self._storage = MinioObjectStorage(
            endpoint=settings.asset_storage_endpoint,
            bucket=settings.asset_storage_bucket,
            access_key=settings.asset_storage_access_key,
            secret_key=settings.asset_storage_secret_key,
            region=settings.asset_storage_region,
            force_path_style=settings.asset_storage_force_path_style,
        )

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(dsn=self._settings.postgres_dsn)
        assert self._pool is not None
        self._repository = CollaborationRepository(self._pool)
        await self._repository.setup_schema()
        self._kernel = CollaborationKernel(self._repository)

    async def stop(self) -> None:
        if self._pool is not None:
            await self._pool.close()
        self._pool = None
        self._repository = None
        self._kernel = None

    async def run_forever(self) -> None:
        await self.start()
        try:
            while True:
                processed = await self.process_one()
                if not processed:
                    await asyncio.sleep(self._settings.worker_poll_interval_seconds)
        finally:
            await self.stop()

    async def process_one(self) -> bool:
        repository = self._require_repository()
        job = await repository.claim_next_retrieval_ingestion_job(now=_now())
        if job is None:
            return False
        try:
            await self._process_job(job.job_id)
        except Exception as exc:
            logger.exception("Retrieval ingestion job failed: %s", job.job_id)
            await repository.update_retrieval_ingestion_job(
                job.job_id,
                status="failed",
                stage="failed",
                now=_now(),
                error=str(exc),
            )
        return True

    async def _process_job(self, job_id) -> None:
        repository = self._require_repository()
        kernel = self._require_kernel()
        job = await repository.fetch_retrieval_ingestion_job(job_id)
        if job is None or job.source_version_id is None:
            raise KeyError(f"Retrieval ingestion job {job_id} is incomplete")
        source_version = await repository.fetch_retrieval_source_version(job.source_version_id)
        if source_version is None:
            raise KeyError(f"Retrieval source version {job.source_version_id} not found")
        source = await repository.fetch_retrieval_source(source_version.source_id)
        if source is None:
            raise KeyError(f"Retrieval source {source_version.source_id} not found")
        asset_version = await repository.fetch_workspace_asset_version(
            source_version.asset_version_id
        )
        if asset_version is None:
            raise KeyError(f"Asset version {source_version.asset_version_id} not found")
        profile = (
            await repository.fetch_retrieval_profile(job.profile_id)
            if job.profile_id is not None
            else None
        )
        payload = await self._storage.get_object(object_key=asset_version.object_key)
        filename = asset_version.metadata.get("filename") or asset_version.git_path
        document = self._extractors.extract(
            payload,
            content_type=asset_version.content_type,
            filename=filename if isinstance(filename, str) else None,
        )
        if self._visual_extraction_enabled(profile) and self._is_pdf(asset_version):
            document.segments.extend(await self._visual_segments(payload, profile=profile))
        chunk_size = profile.chunk_size_tokens if profile is not None else 800
        chunk_overlap = profile.chunk_overlap_tokens if profile is not None else 80
        chunks = self._chunker.chunk(
            document,
            chunk_size_tokens=chunk_size,
            chunk_overlap_tokens=chunk_overlap,
        )
        retrieval_chunks: list[RetrievalChunk] = []
        for chunk in chunks:
            retrieval_chunks.append(
                RetrievalChunk(
                    chunk_id=uuid4(),
                    corpus_id=job.corpus_id,
                    source_id=source.source_id,
                    source_version_id=source_version.source_version_id,
                    scope=job.scope,
                    organization_id=job.organization_id,
                    workspace_id=job.workspace_id,
                    chunk_kind=chunk.source_segment.segment_kind,
                    ordinal=chunk.ordinal,
                    content=chunk.text,
                    token_count=chunk.token_count,
                    content_hash=_content_hash(chunk.text),
                    citation=self._citation(source.source_id, source_version.source_version_id, asset_version.asset_version_id, chunk.source_segment),
                    created_at=_now(),
                    metadata=chunk.metadata,
                )
            )
        embeddings: list[tuple[RetrievalEmbedding, list[float]]] = []
        embedding_error: str | None = None
        embedding_model = (
            profile.embedding_model
            if profile is not None and profile.embedding_model
            else self._settings.default_embedding_model
        )
        embedding_provider = (
            profile.embedding_provider_key
            if profile is not None and profile.embedding_provider_key
            else self._settings.default_embedding_provider
        )
        if retrieval_chunks and embedding_provider == "ollama" and embedding_model:
            try:
                vectors = await self._embedding_provider.embed_texts(
                    [chunk.content for chunk in retrieval_chunks],
                    model=embedding_model,
                )
                for chunk, vector in zip(retrieval_chunks, vectors, strict=False):
                    embeddings.append(
                        (
                            RetrievalEmbedding(
                                embedding_id=uuid4(),
                                chunk_id=chunk.chunk_id,
                                provider_key=embedding_provider,
                                model=embedding_model,
                                dimensions=len(vector),
                                vector_store_provider_key="pgvector",
                                content_hash=chunk.content_hash,
                                embedded_at=_now(),
                            ),
                            vector,
                        )
                    )
            except Exception as exc:
                embedding_error = str(exc)
                logger.warning("Embedding failed for retrieval job %s: %s", job_id, exc)
        await kernel.store_retrieval_chunks(
            source_version_id=source_version.source_version_id,
            chunks=retrieval_chunks,
            embeddings=embeddings,
        )
        metadata = {
            **job.metadata,
            "chunk_count": len(retrieval_chunks),
            "embedding_count": len(embeddings),
        }
        if embedding_error is not None:
            metadata["embedding_error"] = embedding_error
        await repository.update_retrieval_ingestion_job(
            job.job_id,
            status="completed",
            stage="completed",
            now=_now(),
            metadata=metadata,
        )

    def _visual_extraction_enabled(self, profile) -> bool:
        if profile is not None:
            return profile.visual_extraction_enabled
        return self._settings.visual_extraction_enabled

    def _vision_model(self, profile) -> str:
        if profile is not None and profile.vision_model:
            return profile.vision_model
        return self._settings.default_vision_model

    async def _visual_segments(self, payload: bytes, *, profile) -> list[ExtractedSegment]:
        rendered = self._extractors.render_pdf_pages(payload)
        segments: list[ExtractedSegment] = []
        prompt = (
            "Extract visible textual and semantic evidence from this page. "
            "Return concise notes with table contents when visible."
        )
        for page_number, image_bytes in rendered:
            text = await self._vision_provider.describe_image(
                image_bytes,
                model=self._vision_model(profile),
                prompt=prompt,
            )
            if text:
                segments.append(
                    ExtractedSegment(
                        text=text,
                        page_start=page_number,
                        page_end=page_number,
                        segment_kind="visual",
                        metadata={"visual_extraction": True, "page": page_number},
                    )
                )
        return segments

    @staticmethod
    def _is_pdf(asset_version) -> bool:
        content_type = asset_version.content_type or ""
        return content_type.split(";", 1)[0].strip().lower() == "application/pdf"

    @staticmethod
    def _citation(
        source_id,
        source_version_id,
        asset_version_id,
        segment: ExtractedSegment,
    ) -> RetrievalChunkCitation:
        return RetrievalChunkCitation(
            source_id=source_id,
            source_version_id=source_version_id,
            asset_version_id=asset_version_id,
            page_start=segment.page_start,
            page_end=segment.page_end,
            section=segment.section,
            metadata=segment.metadata,
        )

    def _require_repository(self) -> CollaborationRepository:
        if self._repository is None:
            raise RuntimeError("Retriever worker has not started")
        return self._repository

    def _require_kernel(self) -> CollaborationKernel:
        if self._kernel is None:
            raise RuntimeError("Retriever worker has not started")
        return self._kernel


async def _amain() -> None:
    logging.basicConfig(level=logging.INFO)
    worker = RetrieverWorker(RetrieverSettings.from_env())
    await worker.run_forever()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
