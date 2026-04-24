from __future__ import annotations

from pathlib import Path
import shutil
from uuid import UUID, uuid4

from gateway_edge.config import settings
from gateway_edge.models import (
    AgentGitCommitResult,
    AgentGitDiffResult,
    AgentGitFileContent,
    AgentGitWorktreeSession,
    GitRepository,
    ParticipantInput,
)

from .agent_bundles import normalize_bundle_path


_ALLOWED_EXTENSIONS = {".yaml", ".yml", ".md", ".json", ".txt"}


class LocalManagedWorktreeStore:
    def __init__(self, *, root: str | None = None, git_service=None) -> None:
        self._root = Path(root or settings.git_worktree_root)
        self._git_service = git_service

    async def create_session(
        self,
        *,
        repository: GitRepository,
        branch: str,
        bundle_path: str,
        base_revision: str | None,
        actor: ParticipantInput,
        metadata: dict,
    ) -> AgentGitWorktreeSession:
        if self._git_service is None:
            raise RuntimeError("Git service is not configured")
        session_id = uuid4()
        bundle_root = normalize_bundle_path(bundle_path)
        worktree_path = self._session_path(
            scope=repository.scope,
            organization_id=repository.organization_id,
            repository_id=repository.repo_id,
            session_id=session_id,
        )
        await self._git_service.create_worktree(
            repository.local_path,
            worktree_path=str(worktree_path),
            branch=branch,
            base_revision=base_revision or repository.default_branch,
        )
        return AgentGitWorktreeSession(
            session_id=session_id,
            repository_id=repository.repo_id,
            scope=repository.scope,
            organization_id=repository.organization_id,
            branch=branch,
            base_revision=base_revision,
            bundle_path=bundle_root,
            worktree_path=str(worktree_path),
            created_by=actor.participant_id,
            metadata=metadata,
        )

    async def read_file(
        self,
        *,
        session: AgentGitWorktreeSession,
        path: str,
    ) -> AgentGitFileContent:
        resolved = self._resolve_path(session, path)
        content = resolved.read_text(encoding="utf-8")
        return AgentGitFileContent(path=path, content=content)

    async def write_file(
        self,
        *,
        session: AgentGitWorktreeSession,
        path: str,
        content: str,
    ) -> AgentGitFileContent:
        if len(content.encode("utf-8")) > settings.agent_bundle_max_file_bytes:
            raise ValueError("File exceeds maximum agent bundle file size")
        resolved = self._resolve_path(session, path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        return AgentGitFileContent(path=path, content=content)

    async def delete_file(
        self,
        *,
        session: AgentGitWorktreeSession,
        path: str,
    ) -> None:
        resolved = self._resolve_path(session, path)
        if resolved.exists():
            resolved.unlink()

    async def diff(self, *, session: AgentGitWorktreeSession) -> AgentGitDiffResult:
        if self._git_service is None:
            raise RuntimeError("Git service is not configured")
        diff, changed_files = await self._git_service.diff(session.worktree_path)
        return AgentGitDiffResult(
            session_id=session.session_id,
            diff=diff,
            changed_files=changed_files,
        )

    async def commit(
        self,
        *,
        session: AgentGitWorktreeSession,
        actor: ParticipantInput,
        message: str,
        push: bool,
    ) -> AgentGitCommitResult:
        if self._git_service is None:
            raise RuntimeError("Git service is not configured")
        commit_sha, changed_files = await self._git_service.commit(
            session.worktree_path,
            message=message,
            author_name=actor.display_name or str(actor.participant_id),
            author_email=f"{actor.participant_id}@open-talon.local",
        )
        pushed = False
        if push:
            await self._git_service.push(session.worktree_path, session.branch)
            pushed = True
        return AgentGitCommitResult(
            session_id=session.session_id,
            commit_sha=commit_sha,
            branch=session.branch,
            pushed=pushed,
            changed_files=changed_files,
        )

    async def discard(self, *, session: AgentGitWorktreeSession) -> None:
        path = Path(session.worktree_path)
        if path.exists() and path.is_dir():
            shutil.rmtree(path)

    def _session_path(
        self,
        *,
        scope: str,
        organization_id: UUID | None,
        repository_id: UUID,
        session_id: UUID,
    ) -> Path:
        if scope == "organization":
            base = self._root / "organizations" / str(organization_id)
        else:
            base = self._root / "system"
        return base / str(repository_id) / str(session_id)

    def _resolve_path(self, session: AgentGitWorktreeSession, path: str) -> Path:
        normalized = normalize_bundle_path(path)
        bundle_root = normalize_bundle_path(session.bundle_path)
        if normalized != bundle_root and not normalized.startswith(f"{bundle_root}/"):
            raise ValueError("File path must stay inside the session bundle path")
        suffix = Path(normalized).suffix.lower()
        if suffix not in _ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported agent bundle file extension: {suffix}")
        root = Path(session.worktree_path).resolve()
        resolved = (root / normalized).resolve()
        if root != resolved and root not in resolved.parents:
            raise ValueError("File path escapes managed worktree")
        return resolved
