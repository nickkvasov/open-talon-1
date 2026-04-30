from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from gateway_edge.config import settings
from gateway_edge.models import (
    AuthContext,
    Library,
    LibraryItem,
    LibraryWorkspaceAttachment,
    OrganizationMembership,
    ProjectAccessBinding,
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


def _oidc_context(*, roles: list[str], user_id=None) -> AuthContext:
    return AuthContext(
        kind="oidc",
        user_id=user_id or uuid4(),
        issuer="http://issuer.test/realms/open-talon",
        subject="subject-123",
        email="nikolay@example.com",
        display_name="Nikolay",
        roles=roles,
        claims={"sub": "subject-123"},
    )


def _patch_oidc_tokens(monkeypatch, token_map: dict[str, AuthContext]) -> None:
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        return token_map.get(token)

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)


def _grant_org_membership_and_project_access(
    mock_collaboration_service,
    *,
    user_id: UUID,
    role: str | None,
) -> None:
    now = datetime.now(timezone.utc)
    organization_id = mock_collaboration_service.default_organization.organization_id
    project_id = mock_collaboration_service.default_project.project_id
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user_id,
        role="member",
        joined_at=now,
        updated_at=now,
        metadata={},
    )
    mock_collaboration_service.organization_memberships.setdefault(
        str(organization_id),
        {},
    )[str(user_id)] = membership.model_dump(mode="json")
    if role is not None:
        mock_collaboration_service.project_access_bindings[
            (str(project_id), "user", str(user_id))
        ] = ProjectAccessBinding(
            project_id=project_id,
            subject_type="user",
            user_id=user_id,
            role=role,
            created_at=now,
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


async def test_library_delete_accepts_empty_body_for_authenticated_clients(
    client,
    mock_collaboration_service,
    monkeypatch,
):
    organization_id = mock_collaboration_service.default_organization.organization_id
    admin = _oidc_context(roles=["admin"]).model_copy(update={"platform_admin": True})
    _grant_org_membership_and_project_access(
        mock_collaboration_service,
        user_id=admin.user_id,
        role=None,
    )
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})
    library = _library(organization_id=organization_id)
    captured: dict[str, object] = {}

    async def get_library(library_id):
        assert library_id == library.library_id
        return library

    async def delete_library(library_id, payload):
        captured["delete"] = (library_id, payload)
        return {"deleted": True, "library_id": str(library_id)}

    mock_collaboration_service.get_library = get_library
    mock_collaboration_service.delete_library = delete_library

    response = await client.delete(
        f"/v1/libraries/{library.library_id}",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"deleted": True, "library_id": str(library.library_id)}
    assert captured["delete"][0] == library.library_id
    assert captured["delete"][1].actor.user_id == admin.user_id
    assert captured["delete"][1].actor.display_name == "Nikolay"
    assert captured["delete"][1].metadata == {}


async def test_project_library_write_and_index_require_project_permissions(
    client,
    actor_payload,
    mock_collaboration_service,
    monkeypatch,
):
    organization_id = mock_collaboration_service.default_organization.organization_id
    project_id = mock_collaboration_service.default_project.project_id
    viewer = _oidc_context(roles=["workspace-user"])
    _grant_org_membership_and_project_access(
        mock_collaboration_service,
        user_id=viewer.user_id,
        role="viewer",
    )
    _patch_oidc_tokens(monkeypatch, {"viewer-token": viewer})
    library = _library(
        organization_id=organization_id,
        project_id=project_id,
        scope="project",
    )

    async def get_library(library_id):
        assert library_id == library.library_id
        return library

    async def create_library(**kwargs):  # pragma: no cover - should not be authorized
        raise AssertionError("create_library should not be called")

    async def index_library(*args, **kwargs):  # pragma: no cover - should not be authorized
        raise AssertionError("index_library should not be called")

    mock_collaboration_service.get_library = get_library
    mock_collaboration_service.create_library = create_library
    mock_collaboration_service.index_library = index_library
    headers = {"Authorization": "Bearer viewer-token"}

    create_response = await client.post(
        f"/v1/organizations/{organization_id}/projects/{project_id}/libraries",
        headers=headers,
        json={"actor": actor_payload, "name": "Forbidden"},
    )
    index_response = await client.post(
        f"/v1/libraries/{library.library_id}/index",
        headers=headers,
        json={"actor": actor_payload},
    )

    assert create_response.status_code == 403
    assert "library.write" in create_response.json()["detail"]
    assert index_response.status_code == 403
    assert "library.index" in index_response.json()["detail"]


async def test_project_library_read_requires_project_access(
    client,
    mock_collaboration_service,
    monkeypatch,
):
    organization_id = mock_collaboration_service.default_organization.organization_id
    project_id = mock_collaboration_service.default_project.project_id
    org_member = _oidc_context(roles=["workspace-user"])
    _grant_org_membership_and_project_access(
        mock_collaboration_service,
        user_id=org_member.user_id,
        role=None,
    )
    _patch_oidc_tokens(monkeypatch, {"member-token": org_member})

    async def list_libraries(**kwargs):  # pragma: no cover - should not be authorized
        raise AssertionError("list_libraries should not be called")

    mock_collaboration_service.list_libraries = list_libraries

    response = await client.get(
        f"/v1/organizations/{organization_id}/projects/{project_id}/libraries",
        headers={"Authorization": "Bearer member-token"},
    )

    assert response.status_code == 404
