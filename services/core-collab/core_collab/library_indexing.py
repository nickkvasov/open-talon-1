from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from .contracts import (
    Library,
    LibraryItem,
    RetrievalCorpus,
    RetrievalIngestionJob,
    RetrievalSource,
    RetrievalSourceVersion,
)


@dataclass(frozen=True)
class LibraryIndexRecord:
    source: RetrievalSource
    source_version: RetrievalSourceVersion
    job: RetrievalIngestionJob


def find_library_corpus(
    corpora: list[RetrievalCorpus],
    library: Library,
) -> RetrievalCorpus | None:
    return next(
        (
            corpus
            for corpus in corpora
            if corpus.metadata.get("library_id") == str(library.library_id)
        ),
        None,
    )


def library_item_source_id(item_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"open-talon:library-item-source:{item_id}")


def build_library_corpus(
    *,
    library: Library,
    existing_corpus: RetrievalCorpus | None,
    profile_id: UUID | None,
    actor_id: UUID,
    now: datetime,
) -> RetrievalCorpus:
    if existing_corpus is not None:
        return existing_corpus.model_copy(
            update={
                "default_profile_id": profile_id or existing_corpus.default_profile_id,
                "updated_at": now,
            }
        )
    return RetrievalCorpus(
        corpus_id=uuid4(),
        scope=library.scope,
        organization_id=library.organization_id,
        project_id=library.project_id,
        workspace_id=library.workspace_id,
        name=f"library:{library.library_id}",
        description=f"Retriever corpus for library {library.name}.",
        default_profile_id=profile_id,
        created_by=actor_id,
        created_at=now,
        updated_at=now,
        metadata={"library_id": str(library.library_id), "library_slug": library.slug},
    )


def build_library_index_record(
    *,
    library: Library,
    item: LibraryItem,
    corpus: RetrievalCorpus,
    source_version_number: int,
    profile_id: UUID | None,
    actor_id: UUID,
    now: datetime,
    metadata: dict[str, object],
) -> LibraryIndexRecord:
    if item.active_asset_version_id is None:
        raise ValueError(f"Library item {item.item_id} has no active asset version")
    source = RetrievalSource(
        source_id=library_item_source_id(item.item_id),
        corpus_id=corpus.corpus_id,
        scope=library.scope,
        organization_id=library.organization_id,
        project_id=library.project_id,
        workspace_id=library.workspace_id,
        asset_id=item.asset_id,
        active_asset_version_id=item.active_asset_version_id,
        title=item.title,
        source_type=item.item_kind,
        content_type=item.content_type,
        created_by=actor_id,
        created_at=now,
        updated_at=now,
        metadata={
            **item.metadata,
            "library_id": str(library.library_id),
            "library_item_id": str(item.item_id),
        },
    )
    source_version = RetrievalSourceVersion(
        source_version_id=uuid4(),
        source_id=source.source_id,
        asset_version_id=item.active_asset_version_id,
        version=source_version_number,
        ingestion_job_id=None,
        created_by=actor_id,
        created_at=now,
        metadata={"library_item_id": str(item.item_id)},
    )
    job = RetrievalIngestionJob(
        job_id=uuid4(),
        corpus_id=corpus.corpus_id,
        source_id=source.source_id,
        source_version_id=source_version.source_version_id,
        profile_id=profile_id or corpus.default_profile_id,
        scope=library.scope,
        organization_id=library.organization_id,
        project_id=library.project_id,
        workspace_id=library.workspace_id,
        status="queued",
        stage="queued",
        requested_by=actor_id,
        created_at=now,
        updated_at=now,
        metadata={
            **metadata,
            "library_id": str(library.library_id),
            "library_item_id": str(item.item_id),
        },
    )
    return LibraryIndexRecord(source=source, source_version=source_version, job=job)


def bind_source_version_to_job(
    source_version: RetrievalSourceVersion,
    job: RetrievalIngestionJob,
) -> RetrievalSourceVersion:
    return source_version.model_copy(update={"ingestion_job_id": job.job_id})
