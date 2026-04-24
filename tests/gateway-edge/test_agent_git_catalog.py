from __future__ import annotations

import io
import zipfile
from uuid import uuid4

import pytest

from gateway_edge.config import settings
from gateway_edge.models import AuthContext


async def _create_repo(client, actor_payload, *, organization_id: str | None = None):
    endpoint = (
        f"/v1/organizations/{organization_id}/git-repositories"
        if organization_id is not None
        else "/v1/git-repositories"
    )
    response = await client.post(
        endpoint,
        json={
            "actor": actor_payload,
            "name": "agent-definitions",
            "local_path": "/tmp/agent-definitions",
            "forgejo_url": "http://localhost:3001/open-talon/agent-definitions",
            "clone_url": "ssh://git@localhost:2222/open-talon/agent-definitions.git",
            "default_branch": "main",
        },
    )
    assert response.status_code == 200
    return response.json()


def _zip_bundle() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("agent.yaml", "schema_version: 1\n")
        archive.writestr("PROMPT.md", "Publish safely.\n")
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_agent_bundle_validate_publish_versions_and_activate_flow(client, actor_payload):
    repo = await _create_repo(client, actor_payload)

    validate = await client.post(
        "/v1/agents/validate-from-git",
        json={
            "actor": actor_payload,
            "repository_id": repo["repo_id"],
            "bundle_path": "agents/admin",
            "revision": "commit-one",
        },
    )
    assert validate.status_code == 200
    assert validate.json()["valid"] is True
    assert validate.json()["agent_key"] == "admin"
    assert validate.json()["compiled_agent"]["metadata"]["source"] == "git"

    publish_one = await client.post(
        "/v1/agents/publish-from-git",
        json={
            "actor": actor_payload,
            "repository_id": repo["repo_id"],
            "bundle_path": "agents/admin",
            "revision": "commit-one",
        },
    )
    assert publish_one.status_code == 200
    first = publish_one.json()
    agent_id = first["agent"]["agent_id"]
    first_version_id = first["version"]["agent_version_id"]
    assert first["version"]["version"] == 1
    assert first["agent"]["active_agent_version_id"] == first_version_id

    publish_same = await client.post(
        "/v1/agents/publish-from-git",
        json={
            "actor": actor_payload,
            "repository_id": repo["repo_id"],
            "bundle_path": "agents/admin",
            "revision": "commit-one",
        },
    )
    assert publish_same.status_code == 200
    assert publish_same.json()["version"]["agent_version_id"] == first_version_id

    publish_two = await client.post(
        "/v1/agents/publish-from-git",
        json={
            "actor": actor_payload,
            "repository_id": repo["repo_id"],
            "bundle_path": "agents/admin",
            "revision": "commit-two",
        },
    )
    assert publish_two.status_code == 200
    assert publish_two.json()["version"]["version"] == 2

    versions = await client.get(f"/v1/agents/{agent_id}/versions")
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()] == [2, 1]

    activate = await client.post(
        f"/v1/agents/{agent_id}/versions/{first_version_id}/activate",
        json={"actor": actor_payload, "metadata": {"reason": "rollback"}},
    )
    assert activate.status_code == 200
    assert activate.json()["agent"]["active_agent_version_id"] == first_version_id
    assert activate.json()["agent"]["metadata"]["activated_from_version"] == 1


@pytest.mark.asyncio
async def test_organization_agent_bundle_publish_is_scoped(client, actor_payload):
    organization_id = "11111111-1111-1111-1111-111111111111"
    repo = await _create_repo(client, actor_payload, organization_id=organization_id)

    publish = await client.post(
        f"/v1/organizations/{organization_id}/agents/publish-from-git",
        json={
            "actor": actor_payload,
            "repository_id": repo["repo_id"],
            "bundle_path": "agents/admin",
            "revision": "org-commit",
        },
    )

    assert publish.status_code == 200
    assert publish.json()["agent"]["scope"] == "organization"
    assert publish.json()["agent"]["organization_id"] == organization_id

    global_validate = await client.post(
        "/v1/agents/validate-from-git",
        json={
            "actor": actor_payload,
            "repository_id": repo["repo_id"],
            "bundle_path": "agents/admin",
        },
    )
    assert global_validate.status_code == 403


@pytest.mark.asyncio
async def test_agent_bundle_upload_can_commit_and_publish_archive(client, actor_payload):
    repo = await _create_repo(client, actor_payload)

    upload = await client.post(
        "/v1/agents/bundles/upload",
        data={
            "repository_id": repo["repo_id"],
            "branch": "agent-admin",
            "bundle_path": "agents/admin",
            "publish": "true",
            "commit_message": "Upload admin agent",
        },
        files={"archive": ("admin-agent.zip", _zip_bundle(), "application/zip")},
    )

    assert upload.status_code == 200
    payload = upload.json()
    assert payload["commit"]["commit_sha"] == "commit-upload"
    assert payload["publish_result"]["agent"]["agent_key"] == "admin"
    assert payload["publish_result"]["version"]["git_commit_sha"] == "commit-upload"


@pytest.mark.asyncio
async def test_agent_git_worktree_file_authoring_flow(client, actor_payload):
    repo = await _create_repo(client, actor_payload)

    create = await client.post(
        "/v1/agent-git/worktrees",
        json={
            "actor": actor_payload,
            "repository_id": repo["repo_id"],
            "branch": "agent-admin",
            "bundle_path": "agents/admin",
            "base_revision": "main",
        },
    )
    assert create.status_code == 200
    session_id = create.json()["session_id"]

    write = await client.put(
        f"/v1/agent-git/worktrees/{session_id}/files",
        json={
            "actor": actor_payload,
            "path": "agents/admin/agent.yaml",
            "content": "schema_version: 1\n",
        },
    )
    assert write.status_code == 200

    read = await client.get(
        f"/v1/agent-git/worktrees/{session_id}/files",
        params={"path": "agents/admin/agent.yaml"},
    )
    assert read.status_code == 200
    assert read.json()["content"] == "schema_version: 1\n"

    rejected = await client.put(
        f"/v1/agent-git/worktrees/{session_id}/files",
        json={
            "actor": actor_payload,
            "path": "agents/other/agent.yaml",
            "content": "schema_version: 1\n",
        },
    )
    assert rejected.status_code == 400

    diff = await client.get(f"/v1/agent-git/worktrees/{session_id}/diff")
    assert diff.status_code == 200
    assert diff.json()["changed_files"] == ["agents/admin/agent.yaml"]

    commit = await client.post(
        f"/v1/agent-git/worktrees/{session_id}/commit",
        json={"actor": actor_payload, "message": "Update bundle", "push": True},
    )
    assert commit.status_code == 200
    assert commit.json()["pushed"] is True

    discard = await client.delete(f"/v1/agent-git/worktrees/{session_id}")
    assert discard.status_code == 200
    assert discard.json()["discarded"] is True


@pytest.mark.asyncio
async def test_agent_bundle_publish_requires_catalog_permission_in_oidc_mode(
    client,
    actor_payload,
    monkeypatch,
):
    repo = await _create_repo(client, actor_payload)
    user_id = uuid4()
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        if token != "reader-token":
            return None
        return AuthContext(
            kind="oidc",
            user_id=user_id,
            issuer="http://issuer.test/realms/open-talon",
            subject="reader",
            email="reader@example.com",
            display_name="Reader",
            roles=[],
            claims={"sub": "reader"},
        )

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    denied = await client.post(
        "/v1/agents/publish-from-git",
        headers={"Authorization": "Bearer reader-token"},
        json={
            "actor": actor_payload,
            "repository_id": repo["repo_id"],
            "bundle_path": "agents/admin",
        },
    )

    assert denied.status_code == 403
    assert "agent_catalog.write" in denied.json()["detail"]
