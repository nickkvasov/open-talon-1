from __future__ import annotations

import asyncio
from pathlib import Path
import shutil


class GitPublishService:
    async def _run_git(
        self,
        local_path: str,
        *args: str,
        input_bytes: bytes | None = None,
    ) -> tuple[str, str]:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            local_path,
            *args,
            stdin=asyncio.subprocess.PIPE if input_bytes is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(input_bytes)
        out = stdout.decode()
        err = stderr.decode()
        if process.returncode != 0:
            detail = err.strip() or out.strip()
            raise ValueError(f"Git command {' '.join(args)!r} failed: {detail}")
        return out, err

    async def validate_repository(self, local_path: str) -> None:
        path = Path(local_path).expanduser()
        if not path.exists():
            raise ValueError(f"Git repository path does not exist: {path}")
        await self._run_git(str(path), "rev-parse", "--is-bare-repository")

    async def resolve_revision(self, local_path: str, revision: str | None) -> str:
        treeish = revision or "HEAD"
        stdout, _ = await self._run_git(local_path, "rev-parse", treeish)
        return stdout.strip()

    async def read_file(self, local_path: str, revision: str | None, file_path: str) -> tuple[bytes, str]:
        resolved_revision = await self.resolve_revision(local_path, revision)
        spec = f"{resolved_revision}:{file_path}"
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            local_path,
            "show",
            spec,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode().strip() or stdout.decode().strip()
            raise ValueError(f"Unable to read {file_path!r} at {resolved_revision}: {detail}")
        return stdout, resolved_revision

    async def create_worktree(
        self,
        local_path: str,
        *,
        worktree_path: str,
        branch: str,
        base_revision: str | None = None,
    ) -> str:
        resolved_revision = await self.resolve_revision(local_path, base_revision)
        target = Path(worktree_path)
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        await self._run_git(
            local_path,
            "worktree",
            "add",
            "-B",
            branch,
            str(target),
            resolved_revision,
        )
        return resolved_revision

    async def diff(self, worktree_path: str) -> tuple[str, list[str]]:
        stdout, _ = await self._run_git(worktree_path, "diff", "--")
        names, _ = await self._run_git(worktree_path, "status", "--short")
        changed = [line[3:].strip() for line in names.splitlines() if len(line) > 3]
        return stdout, changed

    async def commit(
        self,
        worktree_path: str,
        *,
        message: str,
        author_name: str,
        author_email: str,
    ) -> tuple[str, list[str]]:
        _, changed = await self.diff(worktree_path)
        if not changed:
            raise ValueError("No worktree changes to commit")
        await self._run_git(worktree_path, "add", "--all")
        await self._run_git(
            worktree_path,
            "-c",
            f"user.name={author_name}",
            "-c",
            f"user.email={author_email}",
            "commit",
            "-m",
            message,
        )
        stdout, _ = await self._run_git(worktree_path, "rev-parse", "HEAD")
        return stdout.strip(), changed

    async def push(self, worktree_path: str, branch: str) -> None:
        await self._run_git(worktree_path, "push", "-u", "origin", branch)
