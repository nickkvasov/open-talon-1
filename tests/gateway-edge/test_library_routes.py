from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from gateway_edge.models import (
    Library,
    LibraryItem,
    LibraryWorkspaceAttachment,
    RetrievalIngestionJob,
    Workspace,
)


def _library(
    *,
    organization_id: UUID,
    project_id: UUID | None = None,
    workspace_id: UUID | None = None,
    scope: str = "organization",
    slug: str = "references",
) -> Library:
    now = datetime.now(timezone.utc)
    actor_id = uuid4()
    return Library(
        library_id=uuid4(),
        scope=scope,
        organization_id=organization_id,
        project_id=project_id,
        workspace_id=workspace_id,
        slug=slug,
        name="References",
        description="Reference material.",
        created_by=actor_id,
        created_at=now,
        updated_by=actor_id,
        updated_at=now,
        metadata={},
    )


async def test_project_library_routes_create_and_list_multiple_libraries(
    client,
    actor_payload,
    mock_collaboration_service,
):
    organization_id = mock_collaboration_service.default_organization.organization_id
    project_id = mock_collaboration_service.default_project.project_id
    captured: dict[str, object] = {}
    libraries = [
        _library(
            organization_id=organization_id,
            project_id=project_id,
            scope="project",
            slug="references",
        ),
        _library(
            organization_id=organization_id,
            project_id=project_id,
            scope="project",
            slug="diagrams",
        ),
    ]

    async def create_library(*, scope, organization_id=None, project_id=None, workspace_id=None, payload):
        captured["create"] = (scope, organization_id, project_id, workspace_id, payload)
        return libraries[0]

    async def list_libraries(
        *,
        scope=None,
        organization_id=None,
        project_id=None,
        workspace_id=None,
        include_archived=False,
        include_workspace_attachments=False,
    ):
        captured["list"] = (
            scope,
            organization_id,
            project_id,
            workspace_id,
            include_archived,
            include_workspace_attachments,
        )
        return libraries

    mock_collaboration_service.create_library = create_library
    mock_collaboration_service.list_libraries = list_libraries

    create_response = await client.post(
        f"/v1/organizations/{organization_id}/projects/{project_id}/libraries",
        json={"actor": actor_payload, "name": "References", "slug": "references"},
    )
    list_response = await client.get(
        f"/v1/organizations/{organization_id}/projects/{project_id}/libraries"
    )

    assert create_response.status_code == 200
    assert create_response.json()["scope"] == "project"
    assert create_response.json()["project_id"] == str(project_id)
    assert captured["create"][:4] == ("project", organization_id, project_id, None)
    assert list_response.status_code == 200
    assert [item["slug"] for item in list_response.json()] == ["references", "diagrams"]
    assert captured["list"] == ("project", organization_id, project_id, None, False, False)


async def test_library_item_text_download_attachment_and_index_routes(
    client,
    actor_payload,
    mock_collaboration_service,
):
    organization_id = mock_collaboration_service.default_organization.organization_id
    project_id = mock_collaboration_service.default_project.project_id
    workspace_id = uuid4()
    now = datetime.now(timezone.utc)
    library = _library(
        organization_id=organization_id,
        project_id=project_id,
        scope="project",
        slug="reference-pack",
    )
    item = LibraryItem(
        item_id=uuid4(),
        library_id=library.library_id,
        asset_id=uuid4(),
        active_asset_version_id=uuid4(),
        item_kind="text",
        title="Notes",
        content_type="text/markdown",
        created_by=UUID(actor_payload["participant_id"]),
        created_at=now,
        updated_by=UUID(actor_payload["participant_id"]),
        updated_at=now,
        metadata={},
    )
    attachment = LibraryWorkspaceAttachment(
        attachment_id=uuid4(),
        library_id=library.library_id,
        workspace_id=workspace_id,
        organization_id=organization_id,
        project_id=project_id,
        attached_by=UUID(actor_payload["participant_id"]),
        attached_at=now,
        updated_at=now,
        metadata={},
    )
    job = RetrievalIngestionJob(
        job_id=uuid4(),
        corpus_id=uuid4(),
        source_id=uuid4(),
        source_version_id=uuid4(),
        scope="project",
        organization_id=organization_id,
        project_id=project_id,
        requested_by=UUID(actor_payload["participant_id"]),
        created_at=now,
        updated_at=now,
        metadata={"library_id": str(library.library_id)},
    )
    captured: dict[str, object] = {}

    async def get_library(library_id):
        assert library_id == library.library_id
        return library

    async def create_library_text_item(library_id, payload):
        captured["text"] = (library_id, payload)
        return item

    async def get_library_item(item_id):
        assert item_id == item.item_id
        return item

    async def get_library_item_download_url(item_id):
        assert item_id == item.item_id
        return f"http://localhost/download/{item_id}"

    async def attach_library_to_workspace(requested_workspace_id, library_id, payload):
        captured["attach"] = (requested_workspace_id, library_id, payload)
        return attachment

    async def index_library(library_id, payload):
        captured["index"] = (library_id, payload)
        return [job]

    mock_collaboration_service.get_library = get_library
    mock_collaboration_service.create_library_text_item = create_library_text_item
    mock_collaboration_service.get_library_item = get_library_item
    mock_collaboration_service.get_library_item_download_url = get_library_item_download_url
    mock_collaboration_service.attach_library_to_workspace = attach_library_to_workspace
    mock_collaboration_service.index_library = index_library
    mock_collaboration_service.workspaces[str(workspace_id)] = Workspace(
        workspace_id=workspace_id,
        organization_id=organization_id,
        project_id=project_id,
        name="Library Workspace",
        created_at=now,
        updated_at=now,
    )

    text_response = await client.post(
        f"/v1/libraries/{library.library_id}/items/text",
        json={"actor": actor_payload, "title": "Notes", "content": "# Notes"},
    )
    download_response = await client.get(f"/v1/library-items/{item.item_id}/download")
    attach_response = await client.put(
        f"/v1/workspaces/{workspace_id}/library-attachments/{library.library_id}",
        json={"actor": actor_payload},
    )
    index_response = await client.post(
        f"/v1/libraries/{library.library_id}/index",
        json={"actor": actor_payload, "item_ids": [str(item.item_id)]},
    )

    assert text_response.status_code == 200
    assert text_response.json()["item_kind"] == "text"
    assert captured["text"][0] == library.library_id
    assert download_response.json() == {"url": f"http://localhost/download/{item.item_id}"}
    assert attach_response.status_code == 200
    assert captured["attach"][0] == workspace_id
    assert index_response.status_code == 200
    assert index_response.json()[0]["metadata"] == {"library_id": str(library.library_id)}
