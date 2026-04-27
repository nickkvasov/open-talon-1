from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

_GW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/gateway-edge")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
for path in (_GW_DIR, _CONTRACTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from gateway_edge.models import (
    GitRepository,
    ParticipantInput,
    PublishAssetFromGitRequest,
    UploadFileAssetRequest,
    WorkspaceAssetVersion,
)
from gateway_edge.services.collaboration import CollaborationService
from gateway_edge.services.git_publish import GitPublishService
from gateway_edge.services.object_storage import MinioObjectStorage, StoredObject


@pytest.mark.asyncio
async def test_git_publish_service_reads_file_at_specific_revision(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True, capture_output=True)

    agent_dir = repo_path / "agents" / "admin"
    agent_dir.mkdir(parents=True)
    agent_file = agent_dir / "AGENT.md"
    agent_file.write_text("version one\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "first"], cwd=repo_path, check=True, capture_output=True)
    first_revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    agent_file.write_text("version two\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "second"], cwd=repo_path, check=True, capture_output=True)

    service = GitPublishService()
    content, revision = await service.read_file(
        str(repo_path),
        first_revision,
        "agents/admin/AGENT.md",
    )

    assert revision == first_revision
    assert content == b"version one\n"


@pytest.mark.asyncio
async def test_minio_put_object_signs_request_and_returns_checksum(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def put(self, url, *, content, headers):
            captured["url"] = url
            captured["content"] = content
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("gateway_edge.services.object_storage.httpx.AsyncClient", FakeAsyncClient)

    storage = MinioObjectStorage(
        endpoint="http://127.0.0.1:9090",
        bucket="open-talon-assets",
        access_key="minio",
        secret_key="miniosecret",
    )

    stored = await storage.put_object(
        object_key="global/assets/agent-md/head/AGENT.md",
        payload=b"# agent\n",
        content_type="text/markdown",
    )

    assert stored.bucket == "open-talon-assets"
    assert stored.object_key.endswith("AGENT.md")
    assert stored.size_bytes == len(b"# agent\n")
    assert stored.content_type == "text/markdown"
    assert captured["url"] == "http://127.0.0.1:9090/open-talon-assets/global/assets/agent-md/head/AGENT.md"
    assert captured["headers"]["Content-Type"] == "text/markdown"
    assert "AWS4-HMAC-SHA256" in captured["headers"]["Authorization"]
    assert "x-amz-date" in {key.lower() for key in captured["headers"].keys()}


def test_minio_presign_get_includes_expected_query_fields():
    storage = MinioObjectStorage(
        endpoint="http://127.0.0.1:9090",
        bucket="open-talon-assets",
        access_key="minio",
        secret_key="miniosecret",
    )

    url = storage.presign_get(
        object_key="workspaces/123/assets/agent-md/rev/AGENT.md",
        expires_seconds=600,
    )

    assert url.startswith("http://127.0.0.1:9090/open-talon-assets/workspaces/123/assets/agent-md/rev/AGENT.md?")
    assert "X-Amz-Algorithm=AWS4-HMAC-SHA256" in url
    assert "X-Amz-SignedHeaders=host" in url
    assert "X-Amz-Signature=" in url


@pytest.mark.asyncio
async def test_collaboration_service_publish_asset_from_git_uses_repo_revision_and_content_type():
    actor = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        display_name="Nikolay",
    )
    repository_id = uuid4()
    fake_repo = GitRepository(
        repo_id=repository_id,
        scope="global",
        workspace_id=None,
        name="definitions",
        local_path="/tmp/definitions",
        default_branch="main",
        created_by=actor.participant_id,
    )
    captured: dict[str, object] = {}

    class FakeKernel:
        async def get_git_repository(self, repo_id):
            assert repo_id == repository_id
            return fake_repo

        async def publish_asset_from_git(self, **kwargs):
            captured.update(kwargs)
            version = WorkspaceAssetVersion(
                asset_version_id=uuid4(),
                asset_id=uuid4(),
                version=1,
                source_kind="git_publish",
                git_repository_id=repository_id,
                git_revision=kwargs["payload"].revision,
                git_path=kwargs["payload"].git_path,
                storage_backend="minio",
                bucket=kwargs["bucket"],
                object_key=kwargs["object_key"],
                content_type=kwargs["content_type"],
                size_bytes=kwargs["size_bytes"],
                sha256=kwargs["sha256"],
                created_by=actor.participant_id,
            )
            return SimpleNamespace(version=version)

    class FakeGitPublish:
        async def read_file(self, local_path, revision, file_path):
            assert local_path == "/tmp/definitions"
            assert revision == "main"
            assert file_path == "agents/admin/AGENT.md"
            return (b"# admin\n", "resolved-sha")

    class FakeStorage:
        async def put_object(self, *, object_key, payload, content_type):
            captured["stored_object_key"] = object_key
            captured["stored_payload"] = payload
            captured["stored_content_type"] = content_type
            return StoredObject(
                bucket="open-talon-assets",
                object_key=object_key,
                size_bytes=len(payload),
                sha256="a" * 64,
                content_type=content_type,
            )

    service = CollaborationService()
    service._kernel = FakeKernel()
    service._git_publish = FakeGitPublish()
    service._storage = FakeStorage()

    version = await service.publish_asset_from_git(
        scope="global",
        workspace_id=None,
        payload=PublishAssetFromGitRequest(
            actor=actor,
            repository_id=repository_id,
            asset_type="agent_instruction",
            logical_name="admin-agent-md",
            title="Admin Agent",
            git_path="agents/admin/AGENT.md",
        ),
    )

    assert version.git_revision == "resolved-sha"
    assert version.content_type == "text/markdown"
    assert captured["stored_payload"] == b"# admin\n"
    assert captured["stored_content_type"] == "text/markdown"
    assert captured["stored_object_key"] == "global/assets/admin-agent-md/resolved-sha/AGENT.md"


@pytest.mark.asyncio
async def test_collaboration_service_upload_file_asset_uses_direct_upload_source_kind():
    actor = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        display_name="Nikolay",
    )
    captured: dict[str, object] = {}

    class FakeKernel:
        async def publish_asset_from_upload(self, **kwargs):
            captured.update(kwargs)
            version = WorkspaceAssetVersion(
                asset_version_id=uuid4(),
                asset_id=uuid4(),
                version=1,
                source_kind="direct_upload",
                storage_backend="minio",
                bucket=kwargs["bucket"],
                object_key=kwargs["object_key"],
                content_type=kwargs["content_type"],
                size_bytes=kwargs["size_bytes"],
                sha256=kwargs["sha256"],
                created_by=actor.participant_id,
            )
            return SimpleNamespace(version=version)

    class FakeStorage:
        async def put_object(self, *, object_key, payload, content_type):
            captured["stored_object_key"] = object_key
            captured["stored_payload"] = payload
            captured["stored_content_type"] = content_type
            return StoredObject(
                bucket="open-talon-assets",
                object_key=object_key,
                size_bytes=len(payload),
                sha256="b" * 64,
                content_type=content_type,
            )

    service = CollaborationService()
    service._kernel = FakeKernel()
    service._storage = FakeStorage()

    version = await service.upload_file_asset(
        scope="global",
        workspace_id=None,
        payload=UploadFileAssetRequest(
            actor=actor,
            logical_name="uploaded-book",
            title="Uploaded Book",
        ),
        filename="book.md",
        content=b"# Book\n",
    )

    assert version.source_kind == "direct_upload"
    assert version.content_type == "text/markdown"
    assert captured["stored_payload"] == b"# Book\n"
    assert str(captured["stored_object_key"]).startswith("global/files/uploaded-book/")
    assert captured["payload"].metadata["filename"] == "book.md"
