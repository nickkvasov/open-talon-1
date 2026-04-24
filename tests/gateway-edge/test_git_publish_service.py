from __future__ import annotations

import shutil
import subprocess

import pytest

from gateway_edge.services.git_publish import GitPublishService


def _git(repo: str, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", repo, *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_git_publish_service_reads_worktree_commits_and_pushes(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git CLI is required for GitPublishService integration coverage")

    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, stdout=subprocess.PIPE)
    subprocess.run(["git", "init", str(repo)], check=True, stdout=subprocess.PIPE)
    _git(str(repo), "config", "user.name", "Test User")
    _git(str(repo), "config", "user.email", "test@example.com")
    (repo / "agents").mkdir()
    (repo / "agents" / "admin.md").write_text("v1\n", encoding="utf-8")
    _git(str(repo), "add", "--all")
    _git(str(repo), "commit", "-m", "Initial")
    _git(str(repo), "branch", "-M", "main")
    _git(str(repo), "remote", "add", "origin", str(remote))
    _git(str(repo), "push", "-u", "origin", "main")

    service = GitPublishService()
    await service.validate_repository(str(repo))
    head = await service.resolve_revision(str(repo), "main")
    content, resolved = await service.read_file(str(repo), "main", "agents/admin.md")
    worktree = tmp_path / "worktree"
    base = await service.create_worktree(
        str(repo),
        worktree_path=str(worktree),
        branch="agent-admin",
        base_revision="main",
    )
    (worktree / "agents" / "admin.md").write_text("v2\n", encoding="utf-8")
    diff, changed = await service.diff(str(worktree))
    commit_sha, committed = await service.commit(
        str(worktree),
        message="Update agent bundle",
        author_name="Agent Admin",
        author_email="agent-admin@example.com",
    )
    await service.push(str(worktree), "agent-admin")

    remote_branch = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/agent-admin"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()
    assert resolved == head
    assert base == head
    assert content == b"v1\n"
    assert "v2" in diff
    assert changed == ["agents/admin.md"]
    assert committed == ["agents/admin.md"]
    assert remote_branch == commit_sha
