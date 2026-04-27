from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from uuid import UUID, uuid4

import asyncpg
import httpx
import pytest


pytestmark = pytest.mark.integration

_ROOT_DIR = Path(__file__).resolve().parents[2]
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
from core_collab.migrations import apply_pending_migrations  # noqa: E402
from gateway_edge.services.object_storage import MinioObjectStorage  # noqa: E402
from open_talon_contracts.models import (  # noqa: E402
    CreateRetrievalCorpusRequest,
    CreateRetrievalIngestionJobRequest,
    CreateRetrievalProfileRequest,
    CreateRetrievalSourceRequest,
    ParticipantInput,
    RunRetrievalSearchRequest,
    WorkspaceAsset,
    WorkspaceAssetVersion,
)
from retriever import OllamaEmbeddingProvider, RetrieverSettings  # noqa: E402
from retriever.worker import RetrieverWorker  # noqa: E402


_DEFAULT_EMBEDDING_MODEL = "bge-m3:567m"
_REALISTIC_REPORT_PDF = (
    _ROOT_DIR
    / "tests"
    / "fixtures"
    / "retriever"
    / "cdc-epi-info-2015-annual-report.pdf"
)


def _postgres_dsn() -> str:
    return os.getenv(
        "OPEN_TALON_TEST_POSTGRES_DSN",
        os.getenv("POSTGRES_DSN", "postgresql://admin:password@127.0.0.1:5432/app_db"),
    )


def _ollama_base_url() -> str:
    return os.getenv("RETRIEVER_OLLAMA_BASE_URL", "http://127.0.0.1:11434")


def _embedding_model() -> str:
    return os.getenv("OPEN_TALON_RETRIEVER_LIVE_EMBEDDING_MODEL", _DEFAULT_EMBEDDING_MODEL)


def _vision_model() -> str:
    return os.getenv(
        "OPEN_TALON_RETRIEVER_LIVE_VISION_MODEL",
        os.getenv("RETRIEVER_DEFAULT_VISION_MODEL", "gemma4:31b"),
    )


def _asset_storage() -> MinioObjectStorage:
    return MinioObjectStorage(
        endpoint=os.getenv("ASSET_STORAGE_ENDPOINT", "http://127.0.0.1:9090"),
        bucket=os.getenv("ASSET_STORAGE_BUCKET", "open-talon-assets"),
        access_key=os.getenv("ASSET_STORAGE_ACCESS_KEY", "minio"),
        secret_key=os.getenv("ASSET_STORAGE_SECRET_KEY", "miniosecret"),
        region=os.getenv("ASSET_STORAGE_REGION", "auto"),
        force_path_style=os.getenv("ASSET_STORAGE_FORCE_PATH_STYLE", "true").lower()
        in {"1", "true", "yes", "on"},
    )


async def _require_live_services(
    *,
    embedding_model: str,
    vision_model: str | None = None,
) -> list[float]:
    try:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            response = await client.get(f"{_ollama_base_url()}/api/tags")
            response.raise_for_status()
            models = {
                str(item["name"])
                for item in response.json().get("models", [])
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            }
    except Exception as exc:  # pragma: no cover - local live environment dependent
        pytest.skip(f"Ollama is not available for Retriever live test: {exc}")
    if embedding_model not in models:
        pytest.skip(
            f"Ollama model {embedding_model!r} is not installed; run "
            f"`ollama pull {embedding_model}` before this live test."
        )
    if vision_model is not None and vision_model not in models:
        pytest.skip(
            f"Ollama vision model {vision_model!r} is not installed in the "
            "infrastructure Ollama service."
        )
    try:
        vectors = await OllamaEmbeddingProvider(
            base_url=_ollama_base_url(),
        ).embed_texts(["retriever live embedding probe"], model=embedding_model)
    except Exception as exc:  # pragma: no cover - local live environment dependent
        pytest.skip(f"Ollama embedding model {embedding_model!r} is not usable: {exc}")
    assert vectors and vectors[0]
    return vectors[0]


def _actor() -> ParticipantInput:
    return ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        display_name="Retriever Live Tester",
        iam_permissions=[
            "retrieval.read",
            "retrieval.write",
            "retrieval.search",
            "retrieval.admin",
        ],
    )


async def _cleanup_live_rows(pool: asyncpg.Pool, ids: dict[str, UUID | None]) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM retrieval_context_packs WHERE run_id = $1::uuid",
            ids.get("run_id"),
        )
        await conn.execute(
            "DELETE FROM retrieval_hits WHERE run_id = $1::uuid",
            ids.get("run_id"),
        )
        await conn.execute("DELETE FROM retrieval_runs WHERE run_id = $1::uuid", ids.get("run_id"))
        await conn.execute(
            "DELETE FROM retrieval_embeddings WHERE chunk_id IN "
            "(SELECT chunk_id FROM retrieval_chunks WHERE source_version_id = $1::uuid)",
            ids.get("source_version_id"),
        )
        await conn.execute(
            "DELETE FROM retrieval_chunks WHERE source_version_id = $1::uuid",
            ids.get("source_version_id"),
        )
        await conn.execute(
            "DELETE FROM retrieval_source_versions WHERE source_version_id = $1::uuid",
            ids.get("source_version_id"),
        )
        await conn.execute(
            "DELETE FROM retrieval_ingestion_jobs WHERE job_id = $1::uuid",
            ids.get("job_id"),
        )
        await conn.execute(
            "DELETE FROM retrieval_sources WHERE source_id = $1::uuid",
            ids.get("source_id"),
        )
        await conn.execute(
            "DELETE FROM retrieval_corpora WHERE corpus_id = $1::uuid",
            ids.get("corpus_id"),
        )
        await conn.execute(
            "DELETE FROM retrieval_profiles WHERE profile_id = $1::uuid",
            ids.get("profile_id"),
        )
        await conn.execute(
            "DELETE FROM workspace_asset_versions WHERE asset_version_id = $1::uuid",
            ids.get("asset_version_id"),
        )
        await conn.execute(
            "DELETE FROM workspace_assets WHERE asset_id = $1::uuid",
            ids.get("asset_id"),
        )


async def _wait_for_live_job(
    repository: CollaborationRepository,
    job_id: UUID,
    *,
    timeout_seconds: float = 180.0,
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        job = await repository.fetch_retrieval_ingestion_job(job_id)
        assert job is not None
        if job.status == "completed":
            assert job.stage == "completed"
            assert job.error is None
            return
        if job.status == "failed":
            raise AssertionError(f"Retriever live job failed: {job.error}")
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"Retriever live job did not complete: {job.status}/{job.stage}")
        await asyncio.sleep(0.5)


def _make_text_pdf(text: str) -> bytes:
    fitz = pytest.importorskip("fitz", reason="PDF live tests require PyMuPDF")
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_textbox(
        fitz.Rect(72, 72, 523, 770),
        text,
        fontsize=16,
        fontname="helv",
        color=(0, 0, 0),
    )
    return document.tobytes()


def _extract_pdf_pages(payload: bytes, *, page_numbers: list[int]) -> bytes:
    fitz = pytest.importorskip("fitz", reason="PDF live tests require PyMuPDF")
    output = fitz.open()
    with fitz.open(stream=payload, filetype="pdf") as source:
        for page_number in page_numbers:
            output.insert_pdf(
                source,
                from_page=page_number - 1,
                to_page=page_number - 1,
            )
    return output.tobytes()


def _make_multipage_text_pdf(
    *,
    title: str,
    page_count: int,
    repeated_sentence: str,
    unique_sentence: str,
) -> bytes:
    fitz = pytest.importorskip("fitz", reason="PDF live tests require PyMuPDF")
    document = fitz.open()
    for page_number in range(1, page_count + 1):
        page = document.new_page(width=595, height=842)
        page.insert_textbox(
            fitz.Rect(72, 54, 523, 112),
            f"{title} - page {page_number}",
            fontsize=18,
            fontname="helv",
            color=(0, 0, 0),
        )
        body = "\n\n".join(
            [
                repeated_sentence,
                repeated_sentence,
                (
                    unique_sentence
                    if page_number == page_count
                    else "This filler page keeps the PDF size profile distinct."
                ),
            ]
        )
        page.insert_textbox(
            fitz.Rect(72, 132, 523, 770),
            body,
            fontsize=13,
            fontname="helv",
            color=(0, 0, 0),
        )
    return document.tobytes()


def _render_text_panel_png(text: str, *, width: int = 900, height: int = 360) -> bytes:
    fitz = pytest.importorskip("fitz", reason="PDF visual live tests require PyMuPDF")
    image_source = fitz.open()
    source_page = image_source.new_page(width=width, height=height)
    source_page.draw_rect(source_page.rect, color=(1, 1, 1), fill=(1, 1, 1))
    source_page.draw_rect(
        fitz.Rect(12, 12, width - 12, height - 12),
        color=(0, 0, 0),
        width=3,
    )
    source_page.insert_textbox(
        fitz.Rect(45, 55, width - 45, height - 45),
        text,
        fontsize=64,
        fontname="helv",
        align=1,
        color=(0, 0, 0),
    )
    pixmap = source_page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    return pixmap.tobytes("png")


def _render_chart_panel_png() -> bytes:
    fitz = pytest.importorskip("fitz", reason="PDF visual live tests require PyMuPDF")
    chart = fitz.open()
    page = chart.new_page(width=900, height=500)
    page.draw_rect(page.rect, color=(1, 1, 1), fill=(1, 1, 1))
    page.insert_textbox(
        fitz.Rect(40, 25, 860, 90),
        "BAR CHART: BETA 7 IS HIGHEST",
        fontsize=42,
        fontname="helv",
        align=1,
        color=(0, 0, 0),
    )
    baseline = 420
    bars = [
        ("ALPHA", 2, 120, (0.2, 0.45, 0.8)),
        ("BETA", 7, 360, (0.1, 0.55, 0.25)),
        ("GAMMA", 4, 600, (0.85, 0.45, 0.15)),
    ]
    for label, value, left, color in bars:
        height = value * 38
        page.draw_rect(
            fitz.Rect(left, baseline - height, left + 140, baseline),
            color=color,
            fill=color,
        )
        page.insert_textbox(
            fitz.Rect(left - 20, baseline + 12, left + 160, baseline + 55),
            f"{label} {value}",
            fontsize=28,
            fontname="helv",
            align=1,
            color=(0, 0, 0),
        )
    pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    return pixmap.tobytes("png")


def _make_mixed_text_image_chart_pdf() -> bytes:
    fitz = pytest.importorskip("fitz", reason="PDF visual live tests require PyMuPDF")
    document = fitz.open()
    page = document.new_page(width=900, height=1100)
    page.insert_textbox(
        fitz.Rect(55, 45, 845, 165),
        "Mixed PDF Evidence Report\n"
        "The QUARTZ PDF route uses citrine review gates before synthesis.",
        fontsize=22,
        fontname="helv",
        color=(0, 0, 0),
    )
    page.insert_image(
        fitz.Rect(55, 190, 430, 360),
        stream=_render_text_panel_png("ORCHID 742\nVISUAL OCR"),
    )
    page.insert_image(
        fitz.Rect(55, 400, 845, 840),
        stream=_render_chart_panel_png(),
    )
    page.insert_textbox(
        fitz.Rect(55, 875, 845, 965),
        "The embedded image and chart are intentionally raster content so "
        "the visual extractor must inspect the rendered page.",
        fontsize=18,
        fontname="helv",
        color=(0, 0, 0),
    )
    return document.tobytes()


async def _run_live_document_retrieval_case(
    *,
    payload: bytes,
    content_type: str,
    filename: str,
    query: str,
    expected_terms: list[str],
    visual_extraction_enabled: bool = False,
    vision_model: str | None = None,
    top_k: int = 3,
) -> str:
    if os.getenv("OPEN_TALON_RUN_RETRIEVER_LIVE") != "1":
        pytest.skip("Set OPEN_TALON_RUN_RETRIEVER_LIVE=1 to run Retriever live tests")

    embedding_model = _embedding_model()
    await _require_live_services(
        embedding_model=embedding_model,
        vision_model=vision_model if visual_extraction_enabled else None,
    )
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - local live environment dependent
        pytest.skip(f"Postgres is not available for Retriever live test: {exc}")

    ids: dict[str, UUID | None] = {}
    worker: RetrieverWorker | None = None
    try:
        await apply_pending_migrations(pool)
        repository = CollaborationRepository(pool)
        kernel = CollaborationKernel(repository)
        actor = _actor()
        now = datetime.now(timezone.utc)
        run_suffix = uuid4().hex[:12]

        stored = await _asset_storage().put_object(
            object_key=f"global/retriever-live/{run_suffix}/{filename}",
            payload=payload,
            content_type=content_type,
        )

        asset = WorkspaceAsset(
            asset_id=uuid4(),
            scope="global",
            asset_type="file",
            logical_name=f"retriever-live-{run_suffix}",
            title="Retriever Live Handbook.md",
            created_by=actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata={"source": "retriever-live-test"},
        )
        version = WorkspaceAssetVersion(
            asset_version_id=uuid4(),
            asset_id=asset.asset_id,
            version=1,
            source_kind="direct_upload",
            storage_backend="minio",
            bucket=stored.bucket,
            object_key=stored.object_key,
            content_type=stored.content_type,
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            created_by=actor.participant_id,
            created_at=now,
            metadata={"filename": filename, "source": "retriever-live-test"},
        )
        ids.update(asset_id=asset.asset_id, asset_version_id=version.asset_version_id)
        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.upsert_workspace_asset(conn, asset)
                await repository.upsert_workspace_asset_version(conn, version)

        profile = (
            await kernel.create_retrieval_profile(
                scope="global",
                payload=CreateRetrievalProfileRequest(
                    actor=actor,
                    name=f"retriever-live-profile-{run_suffix}",
                    embedding_provider_key="ollama",
                    embedding_model=embedding_model,
                    vision_provider_key="ollama" if visual_extraction_enabled else None,
                    vision_model=vision_model if visual_extraction_enabled else None,
                    visual_extraction_enabled=visual_extraction_enabled,
                    chunk_size_tokens=80,
                    chunk_overlap_tokens=8,
                    top_k=3,
                    metadata={"source": "retriever-live-test"},
                ),
            )
        ).profile
        assert profile is not None
        ids["profile_id"] = profile.profile_id

        corpus = (
            await kernel.create_retrieval_corpus(
                scope="global",
                payload=CreateRetrievalCorpusRequest(
                    actor=actor,
                    name=f"retriever-live-corpus-{run_suffix}",
                    default_profile_id=profile.profile_id,
                    metadata={"source": "retriever-live-test"},
                ),
            )
        ).corpus
        assert corpus is not None
        ids["corpus_id"] = corpus.corpus_id

        source = (
            await kernel.create_retrieval_source(
                scope="global",
                payload=CreateRetrievalSourceRequest(
                    actor=actor,
                    corpus_id=corpus.corpus_id,
                    asset_id=asset.asset_id,
                    asset_version_id=version.asset_version_id,
                    title=filename,
                    content_type=content_type,
                    metadata={"source": "retriever-live-test"},
                ),
            )
        ).source
        assert source is not None
        ids["source_id"] = source.source_id

        job_result = await kernel.create_retrieval_ingestion_job(
            corpus_id=corpus.corpus_id,
            payload=CreateRetrievalIngestionJobRequest(
                actor=actor,
                source_id=source.source_id,
                profile_id=profile.profile_id,
                metadata={"source": "retriever-live-test"},
            ),
        )
        job = job_result.job
        source_version = job_result.source_version
        assert job is not None
        assert source_version is not None
        ids["job_id"] = job.job_id
        ids["source_version_id"] = source_version.source_version_id

        worker = RetrieverWorker(
            RetrieverSettings(
                default_embedding_provider="ollama",
                default_embedding_model=embedding_model,
                default_vision_provider="ollama",
                default_vision_model=os.getenv(
                    "RETRIEVER_DEFAULT_VISION_MODEL",
                    vision_model or "gemma4:31b",
                ),
                ollama_base_url=_ollama_base_url(),
                visual_extraction_enabled=visual_extraction_enabled,
                postgres_dsn=_postgres_dsn(),
                asset_storage_endpoint=os.getenv(
                    "ASSET_STORAGE_ENDPOINT",
                    "http://127.0.0.1:9090",
                ),
                asset_storage_bucket=os.getenv("ASSET_STORAGE_BUCKET", "open-talon-assets"),
                asset_storage_access_key=os.getenv("ASSET_STORAGE_ACCESS_KEY", "minio"),
                asset_storage_secret_key=os.getenv(
                    "ASSET_STORAGE_SECRET_KEY",
                    "miniosecret",
                ),
                asset_storage_region=os.getenv("ASSET_STORAGE_REGION", "auto"),
            )
        )
        await worker.start()
        # Process the known job directly so a developer's unrelated queued live jobs
        # are never claimed by this test run. If the running stack worker claimed
        # it first, wait for that worker to finish instead of processing it twice.
        if not await worker.process_job(job.job_id):
            await _wait_for_live_job(repository, job.job_id)

        completed = await repository.fetch_retrieval_ingestion_job(job.job_id)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.stage == "completed"
        assert completed.error is None
        assert completed.metadata["chunk_count"] >= 1
        assert completed.metadata["embedding_count"] >= 1

        query_vector = (
            await OllamaEmbeddingProvider(base_url=_ollama_base_url()).embed_texts(
                [query],
                model=embedding_model,
            )
        )[0]
        search = await kernel.run_retrieval_search(
            scope="global",
            payload=RunRetrievalSearchRequest(
                actor=actor,
                query=query,
                corpus_ids=[corpus.corpus_id],
                top_k=top_k,
                include_context=True,
            ),
            embedding_vector=query_vector,
            embedding_provider_key="ollama",
            embedding_model=embedding_model,
        )
        ids["run_id"] = search.run.run_id
        assert search.hits
        assert search.context_pack is not None
        assert search.context_pack.hits
        content = search.context_pack.content
        lowered_content = content.lower()
        for expected in expected_terms:
            assert expected.lower() in lowered_content, content
        assert search.hits[0].chunk.citation is not None
        assert search.hits[0].chunk.citation.asset_version_id == version.asset_version_id
        return content
    finally:
        if worker is not None:
            await worker.stop()
        await _cleanup_live_rows(pool, ids)
        await pool.close()


@pytest.mark.asyncio
async def test_retriever_worker_ingests_minio_file_embeds_and_searches_live_stack():
    await _run_live_document_retrieval_case(
        payload=(
            "# Retriever Live Handbook\n\n"
            "The Zephyr process uses calendula checkpoints and basalt acceptance gates.\n\n"
            "Each cited evidence pack must preserve source attribution before synthesis."
        ).encode("utf-8"),
        content_type="text/markdown",
        filename="handbook.md",
        query="calendula basalt acceptance gates",
        expected_terms=["calendula checkpoints", "basalt acceptance gates"],
    )


@pytest.mark.asyncio
async def test_retriever_worker_ingests_text_pdf_and_searches_live_stack():
    cases = [
        (
            "small",
            _make_text_pdf(
                "PDF Retrieval Manual\n\n"
                "The QUARTZ PDF route uses amber clauses and citrine review gates. "
                "Every parsed PDF chunk must keep page-level source evidence."
            ),
            "QUARTZ PDF citrine review gates",
            ["QUARTZ PDF route", "citrine review gates"],
        ),
        (
            "medium",
            _make_multipage_text_pdf(
                title="Medium PDF Retrieval Manual",
                page_count=4,
                repeated_sentence=(
                    "The medium corpus fixture repeats structured retrieval guidance "
                    "for section-aware chunking and page citations."
                ),
                unique_sentence=(
                    "The ONYX medium PDF includes saffron transition notes for "
                    "retrieval validation."
                ),
            ),
            "ONYX medium PDF saffron transition notes",
            ["ONYX medium PDF", "saffron transition notes"],
        ),
        (
            "large",
            _make_multipage_text_pdf(
                title="Large PDF Retrieval Manual",
                page_count=12,
                repeated_sentence=(
                    "The large corpus fixture repeats retrieval operating policy, "
                    "chunk evidence preservation, and citation assembly requirements."
                ),
                unique_sentence=(
                    "The COBALT large PDF stores vermilion appendix markers for "
                    "late-page retrieval validation."
                ),
            ),
            "COBALT large PDF vermilion appendix markers",
            ["COBALT large PDF", "vermilion appendix markers"],
        ),
    ]
    for size, payload, query, expected_terms in cases:
        await _run_live_document_retrieval_case(
            payload=payload,
            content_type="application/pdf",
            filename=f"retriever-pdf-manual-{size}.pdf",
            query=query,
            expected_terms=expected_terms,
        )


@pytest.mark.asyncio
async def test_retriever_worker_uses_pdf_visual_extraction_for_text_image_and_chart_live_stack():
    vision_model = _vision_model()
    content = await _run_live_document_retrieval_case(
        payload=_make_mixed_text_image_chart_pdf(),
        content_type="application/pdf",
        filename="retriever-mixed-text-image-chart.pdf",
        query="QUARTZ ORCHID 742 BETA 7 chart",
        expected_terms=["QUARTZ PDF route", "ORCHID", "742"],
        visual_extraction_enabled=True,
        vision_model=vision_model,
    )
    lowered = content.lower()
    assert (
        "bar chart" in lowered
        or "bar graph" in lowered
        or ("bars" in lowered and "highest" in lowered)
    ), content


@pytest.mark.asyncio
async def test_retriever_worker_understands_real_report_chart_live_stack():
    vision_model = _vision_model()
    report_payload = _REALISTIC_REPORT_PDF.read_bytes()
    content = await _run_live_document_retrieval_case(
        payload=_extract_pdf_pages(report_payload, page_numbers=[6]),
        content_type="application/pdf",
        filename=_REALISTIC_REPORT_PDF.name,
        query=(
            "In the Number of Persons Trained in Epi Info chart, "
            "which month had the highest value and what was it?"
        ),
        expected_terms=["Number of Persons Trained", "May", "200"],
        visual_extraction_enabled=True,
        vision_model=vision_model,
        top_k=5,
    )
    lowered = content.lower()
    assert "bar chart" in lowered or "column chart" in lowered, content
    assert (
        ("highest" in lowered or "peak" in lowered)
        and "may" in lowered
        and "200" in lowered
    ), content
