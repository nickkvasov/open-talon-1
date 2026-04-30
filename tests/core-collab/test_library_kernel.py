from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
for path in (_CONTRACTS_DIR, _CORE_COLLAB_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from core_collab.kernel import CollaborationKernel
from core_collab.library_indexing import (
    build_library_corpus,
    build_library_index_record,
    find_library_corpus,
    library_item_source_id,
)
from open_talon_contracts.models import (
    AttachLibraryToWorkspaceRequest,
    CreateLibraryItemRequest,
    IndexLibraryRequest,
    Library,
    LibraryItem,
    LibraryWorkspaceAttachment,
    Organization,
    ParticipantInput,
    Project,
    RetrievalChunk,
    RetrievalCorpus,
    RetrievalIngestionJob,
    RetrievalRun,
    RetrievalSearchHit,
    RetrievalSource,
    RetrievalSourceVersion,
    RunRetrievalSearchRequest,
    Workspace,
    WorkspaceAsset,
    WorkspaceAssetVersion,
)


pytestmark = pytest.mark.asyncio


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def transaction(self):
        return _FakeTransaction()


class _FakeAcquire:
    async def __aenter__(self):
        return _FakeConnection()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def acquire(self):
        return _FakeAcquire()


class LibraryKernelRepository:
    def __init__(self) -> None:
        self._pool = _FakePool()
        self.organizations: dict[UUID, Organization] = {}
        self.projects: dict[UUID, Project] = {}
        self.workspaces: dict[UUID, Workspace] = {}
        self.libraries: dict[UUID, Library] = {}
        self.library_items: dict[UUID, LibraryItem] = {}
        self.library_attachments: dict[tuple[UUID, UUID], LibraryWorkspaceAttachment] = {}
        self.assets: dict[UUID, WorkspaceAsset] = {}
        self.asset_versions: dict[UUID, WorkspaceAssetVersion] = {}
        self.corpora: dict[UUID, RetrievalCorpus] = {}
        self.sources: dict[UUID, RetrievalSource] = {}
        self.source_versions: dict[UUID, RetrievalSourceVersion] = {}
        self.jobs: dict[UUID, RetrievalIngestionJob] = {}
        self.runs: dict[UUID, RetrievalRun] = {}
        self.hits: list[RetrievalSearchHit] = []
        self.chunks_by_corpus: dict[UUID, RetrievalChunk] = {}
        self.search_calls: list[dict[str, object]] = []

    async def fetch_organization(self, organization_id: UUID):
        return self.organizations.get(organization_id)

    async def fetch_project(self, project_id: UUID):
        return self.projects.get(project_id)

    async def fetch_workspace(self, workspace_id: UUID):
        return self.workspaces.get(workspace_id)

    async def fetch_library(self, library_id: UUID):
        return self.libraries.get(library_id)

    async def upsert_library(self, conn, library: Library) -> None:
        self.libraries[library.library_id] = library

    async def list_libraries(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
        include_archived: bool = False,
        include_workspace_attachments: bool = False,
    ) -> list[Library]:
        libraries = [
            library
            for library in self.libraries.values()
            if (scope is None or library.scope == scope)
            and (organization_id is None or library.organization_id == organization_id)
            and (project_id is None or library.project_id == project_id)
            and (workspace_id is None or library.workspace_id == workspace_id)
            and (include_archived or library.status != "archived")
        ]
        if scope == "workspace" and workspace_id is not None and include_workspace_attachments:
            attached_ids = {
                attachment.library_id
                for (attached_workspace_id, _), attachment in self.library_attachments.items()
                if attached_workspace_id == workspace_id and attachment.enabled
            }
            libraries.extend(
                library
                for library_id, library in self.libraries.items()
                if library_id in attached_ids and (include_archived or library.status != "archived")
            )
        return libraries

    async def upsert_library_item(self, conn, item: LibraryItem) -> None:
        self.library_items[item.item_id] = item

    async def fetch_library_item(self, item_id: UUID):
        return self.library_items.get(item_id)

    async def list_library_items(
        self,
        library_id: UUID,
        *,
        item_ids: list[UUID] | None = None,
        include_archived: bool = False,
    ) -> list[LibraryItem]:
        requested = set(item_ids) if item_ids is not None else None
        return [
            item
            for item in self.library_items.values()
            if item.library_id == library_id
            and (requested is None or item.item_id in requested)
            and (include_archived or item.status != "archived")
        ]

    async def upsert_library_workspace_attachment(
        self,
        conn,
        attachment: LibraryWorkspaceAttachment,
    ) -> None:
        self.library_attachments[(attachment.workspace_id, attachment.library_id)] = attachment

    async def fetch_library_workspace_attachment(
        self,
        *,
        workspace_id: UUID,
        library_id: UUID,
    ):
        return self.library_attachments.get((workspace_id, library_id))

    async def fetch_workspace_asset(self, asset_id: UUID):
        return self.assets.get(asset_id)

    async def fetch_workspace_asset_version(self, asset_version_id: UUID):
        return self.asset_versions.get(asset_version_id)

    async def list_workspace_asset_versions(self, asset_id: UUID):
        return [
            version
            for version in self.asset_versions.values()
            if version.asset_id == asset_id
        ]

    async def upsert_retrieval_corpus(self, conn, corpus: RetrievalCorpus) -> None:
        self.corpora[corpus.corpus_id] = corpus

    async def fetch_retrieval_corpus(self, corpus_id: UUID):
        return self.corpora.get(corpus_id)

    async def list_retrieval_corpora(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[RetrievalCorpus]:
        return [
            corpus
            for corpus in self.corpora.values()
            if (scope is None or corpus.scope == scope)
            and (organization_id is None or corpus.organization_id == organization_id)
            and (project_id is None or corpus.project_id == project_id)
            and (workspace_id is None or corpus.workspace_id == workspace_id)
        ]

    async def fetch_retrieval_profile(self, profile_id: UUID):
        return None

    async def upsert_retrieval_source(self, conn, source: RetrievalSource) -> None:
        self.sources[source.source_id] = source

    async def next_retrieval_source_version(self, conn, source_id: UUID) -> int:
        versions = [
            version.version
            for version in self.source_versions.values()
            if version.source_id == source_id
        ]
        return max(versions, default=0) + 1

    async def upsert_retrieval_source_version(
        self,
        conn,
        source_version: RetrievalSourceVersion,
    ) -> None:
        self.source_versions[source_version.source_version_id] = source_version

    async def upsert_retrieval_ingestion_job(
        self,
        conn,
        job: RetrievalIngestionJob,
    ) -> None:
        self.jobs[job.job_id] = job

    async def search_retrieval_chunks(self, **kwargs) -> list[RetrievalSearchHit]:
        self.search_calls.append(kwargs)
        hits: list[RetrievalSearchHit] = []
        for corpus_id in kwargs["corpus_ids"]:
            chunk = self.chunks_by_corpus.get(corpus_id)
            if chunk is not None:
                hits.append(RetrievalSearchHit(chunk=chunk, score=1.0))
        return hits

    async def upsert_retrieval_run(self, conn, run: RetrievalRun) -> None:
        self.runs[run.run_id] = run

    async def upsert_retrieval_hit(self, conn, *, hit_id: UUID, run_id: UUID, hit: RetrievalSearchHit) -> None:
        self.hits.append(hit)


def _seed_library_world() -> tuple[LibraryKernelRepository, dict[str, object]]:
    now = datetime.now(timezone.utc)
    actor_id = uuid4()
    organization_id = uuid4()
    project_id = uuid4()
    workspace_id = uuid4()
    repository = LibraryKernelRepository()
    repository.organizations[organization_id] = Organization(
        organization_id=organization_id,
        slug="org",
        name="Organization",
        created_by=actor_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    repository.projects[project_id] = Project(
        project_id=project_id,
        organization_id=organization_id,
        slug="project",
        name="Project",
        created_by=actor_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    repository.workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        organization_id=organization_id,
        project_id=project_id,
        name="Workspace",
        created_at=now,
        updated_at=now,
    )
    actor = ParticipantInput(
        participant_id=actor_id,
        participant_type="user",
        display_name="Tester",
    )
    return repository, {
        "now": now,
        "actor": actor,
        "actor_id": actor_id,
        "organization_id": organization_id,
        "project_id": project_id,
        "workspace_id": workspace_id,
    }


def _library(
    *,
    context: dict[str, object],
    scope: str = "project",
    library_id: UUID | None = None,
    organization_id: UUID | None = None,
    project_id: UUID | None = None,
    workspace_id: UUID | None = None,
    slug: str = "references",
) -> Library:
    return Library(
        library_id=library_id or uuid4(),
        scope=scope,
        organization_id=organization_id or context["organization_id"],
        project_id=project_id if project_id is not None else (context["project_id"] if scope in {"project", "workspace"} else None),
        workspace_id=workspace_id if workspace_id is not None else (context["workspace_id"] if scope == "workspace" else None),
        slug=slug,
        name=slug.title(),
        created_by=context["actor_id"],
        created_at=context["now"],
        updated_by=context["actor_id"],
        updated_at=context["now"],
        metadata={},
    )


def _asset_and_item(
    repository: LibraryKernelRepository,
    *,
    context: dict[str, object],
    library: Library,
    title: str,
) -> LibraryItem:
    asset_id = uuid4()
    version_id = uuid4()
    repository.assets[asset_id] = WorkspaceAsset(
        asset_id=asset_id,
        scope=library.scope,
        organization_id=library.organization_id,
        project_id=library.project_id,
        workspace_id=library.workspace_id,
        asset_type="file",
        logical_name=title.lower().replace(" ", "-"),
        title=title,
        created_by=context["actor_id"],
        created_at=context["now"],
        updated_at=context["now"],
    )
    repository.asset_versions[version_id] = WorkspaceAssetVersion(
        asset_version_id=version_id,
        asset_id=asset_id,
        version=1,
        source_kind="upload",
        bucket="open-talon-assets",
        object_key=f"{library.scope}/{asset_id}.md",
        content_type="text/markdown",
        size_bytes=10,
        sha256="a" * 64,
        created_by=context["actor_id"],
        created_at=context["now"],
    )
    item = LibraryItem(
        item_id=uuid4(),
        library_id=library.library_id,
        asset_id=asset_id,
        active_asset_version_id=version_id,
        item_kind="text",
        title=title,
        content_type="text/markdown",
        created_by=context["actor_id"],
        created_at=context["now"],
        updated_by=context["actor_id"],
        updated_at=context["now"],
        metadata={},
    )
    repository.library_items[item.item_id] = item
    return item


def _corpus_for_library(
    repository: LibraryKernelRepository,
    *,
    context: dict[str, object],
    library: Library,
) -> RetrievalCorpus:
    corpus = RetrievalCorpus(
        corpus_id=uuid4(),
        scope=library.scope,
        organization_id=library.organization_id,
        project_id=library.project_id,
        workspace_id=library.workspace_id,
        name=f"library:{library.library_id}",
        created_by=context["actor_id"],
        created_at=context["now"],
        updated_at=context["now"],
        metadata={"library_id": str(library.library_id)},
    )
    repository.corpora[corpus.corpus_id] = corpus
    repository.chunks_by_corpus[corpus.corpus_id] = RetrievalChunk(
        chunk_id=uuid4(),
        corpus_id=corpus.corpus_id,
        source_id=uuid4(),
        scope=corpus.scope,
        organization_id=corpus.organization_id,
        project_id=corpus.project_id,
        workspace_id=corpus.workspace_id,
        ordinal=0,
        content=f"{library.slug} content",
        content_hash=corpus.corpus_id.hex,
        created_at=context["now"],
        metadata={"library_id": str(library.library_id)},
    )
    return corpus


async def test_create_library_item_does_not_auto_index() -> None:
    repository, context = _seed_library_world()
    kernel = CollaborationKernel(repository)
    library = _library(context=context)
    repository.libraries[library.library_id] = library
    seeded_item = _asset_and_item(repository, context=context, library=library, title="Manual Note")

    result = await kernel.create_library_item(
        library.library_id,
        CreateLibraryItemRequest(
            actor=context["actor"],
            asset_id=seeded_item.asset_id,
            asset_version_id=seeded_item.active_asset_version_id,
            item_kind="text",
            title="Manual Note Copy",
        ),
    )

    assert result.item is not None
    assert result.item.active_asset_version_id == seeded_item.active_asset_version_id
    assert repository.jobs == {}
    assert repository.corpora == {}


async def test_library_indexing_policy_builds_deterministic_records() -> None:
    repository, context = _seed_library_world()
    library = _library(context=context)
    item = _asset_and_item(repository, context=context, library=library, title="Policy Note")
    corpus = build_library_corpus(
        library=library,
        existing_corpus=None,
        profile_id=None,
        actor_id=context["actor_id"],
        now=context["now"],
    )
    record = build_library_index_record(
        library=library,
        item=item,
        corpus=corpus,
        source_version_number=3,
        profile_id=None,
        actor_id=context["actor_id"],
        now=context["now"],
        metadata={"reason": "manual"},
    )

    assert find_library_corpus([corpus], library) == corpus
    assert record.source.source_id == library_item_source_id(item.item_id)
    assert record.source.metadata["library_id"] == str(library.library_id)
    assert record.source.metadata["library_item_id"] == str(item.item_id)
    assert record.source_version.version == 3
    assert record.source_version.ingestion_job_id is None
    assert record.job.source_version_id == record.source_version.source_version_id
    assert record.job.metadata["reason"] == "manual"
    assert record.job.metadata["library_item_id"] == str(item.item_id)


async def test_index_library_selected_items_reuses_library_corpus() -> None:
    repository, context = _seed_library_world()
    kernel = CollaborationKernel(repository)
    library = _library(context=context)
    repository.libraries[library.library_id] = library
    first_item = _asset_and_item(repository, context=context, library=library, title="First")
    second_item = _asset_and_item(repository, context=context, library=library, title="Second")

    first_result = await kernel.index_library(
        library.library_id,
        IndexLibraryRequest(actor=context["actor"], item_ids=[first_item.item_id]),
    )
    second_result = await kernel.index_library(
        library.library_id,
        IndexLibraryRequest(actor=context["actor"], item_ids=[second_item.item_id]),
    )

    assert len(first_result.jobs) == 1
    assert first_result.jobs[0].metadata["library_item_id"] == str(first_item.item_id)
    assert len(second_result.jobs) == 1
    assert second_result.jobs[0].metadata["library_item_id"] == str(second_item.item_id)
    assert len(repository.corpora) == 1
    assert {source.metadata["library_item_id"] for source in repository.sources.values()} == {
        str(first_item.item_id),
        str(second_item.item_id),
    }


async def test_attach_library_to_workspace_rejects_cross_scope_sources() -> None:
    repository, context = _seed_library_world()
    kernel = CollaborationKernel(repository)
    actor = context["actor"]
    workspace_id = context["workspace_id"]

    workspace_library = _library(context=context, scope="workspace")
    repository.libraries[workspace_library.library_id] = workspace_library
    with pytest.raises(ValueError, match="Workspace-owned libraries"):
        await kernel.attach_library_to_workspace(
            workspace_id,
            workspace_library.library_id,
            AttachLibraryToWorkspaceRequest(actor=actor),
        )

    other_org_id = uuid4()
    other_org_library = _library(
        context=context,
        scope="organization",
        organization_id=other_org_id,
        slug="other-org",
    )
    repository.organizations[other_org_id] = Organization(
        organization_id=other_org_id,
        slug="other",
        name="Other",
        created_by=context["actor_id"],
        created_at=context["now"],
        updated_at=context["now"],
        metadata={},
    )
    repository.libraries[other_org_library.library_id] = other_org_library
    with pytest.raises(ValueError, match="same organization"):
        await kernel.attach_library_to_workspace(
            workspace_id,
            other_org_library.library_id,
            AttachLibraryToWorkspaceRequest(actor=actor),
        )

    other_project_id = uuid4()
    repository.projects[other_project_id] = Project(
        project_id=other_project_id,
        organization_id=context["organization_id"],
        slug="other-project",
        name="Other Project",
        created_by=context["actor_id"],
        created_at=context["now"],
        updated_at=context["now"],
        metadata={},
    )
    other_project_library = _library(
        context=context,
        scope="project",
        project_id=other_project_id,
        slug="other-project",
    )
    repository.libraries[other_project_library.library_id] = other_project_library
    with pytest.raises(ValueError, match="same project"):
        await kernel.attach_library_to_workspace(
            workspace_id,
            other_project_library.library_id,
            AttachLibraryToWorkspaceRequest(actor=actor),
        )

    project_library = _library(context=context, scope="project", slug="same-project")
    repository.libraries[project_library.library_id] = project_library
    result = await kernel.attach_library_to_workspace(
        workspace_id,
        project_library.library_id,
        AttachLibraryToWorkspaceRequest(actor=actor),
    )
    assert result.attachment is not None
    assert result.attachment.library_id == project_library.library_id


async def test_workspace_search_includes_workspace_and_attached_library_corpora_only() -> None:
    repository, context = _seed_library_world()
    kernel = CollaborationKernel(repository)
    workspace_library = _library(context=context, scope="workspace", slug="workspace")
    attached_org_library = _library(context=context, scope="organization", slug="org-attached")
    attached_project_library = _library(context=context, scope="project", slug="project-attached")
    unattached_org_library = _library(context=context, scope="organization", slug="org-hidden")
    for library in [
        workspace_library,
        attached_org_library,
        attached_project_library,
        unattached_org_library,
    ]:
        repository.libraries[library.library_id] = library
        _corpus_for_library(repository, context=context, library=library)

    for library in [attached_org_library, attached_project_library]:
        await kernel.attach_library_to_workspace(
            context["workspace_id"],
            library.library_id,
            AttachLibraryToWorkspaceRequest(actor=context["actor"]),
        )

    response = await kernel.run_retrieval_search(
        scope="workspace",
        workspace_id=context["workspace_id"],
        payload=RunRetrievalSearchRequest(
            actor=context["actor"],
            query="content",
            top_k=10,
        ),
    )

    searched_corpus_ids = {
        corpus_id
        for call in repository.search_calls
        for corpus_id in call["corpus_ids"]
    }
    visible_library_ids = {
        str(hit.chunk.metadata["library_id"])
        for hit in response.hits
    }
    assert visible_library_ids == {
        str(workspace_library.library_id),
        str(attached_org_library.library_id),
        str(attached_project_library.library_id),
    }
    assert str(unattached_org_library.library_id) not in visible_library_ids
    assert searched_corpus_ids == {
        corpus.corpus_id
        for corpus in repository.corpora.values()
        if corpus.metadata["library_id"] in visible_library_ids
    }
