from __future__ import annotations

import asyncio
from pathlib import Path


class GitPublishService:
    async def validate_repository(self, local_path: str) -> None:
        path = Path(local_path).expanduser()
        if not path.exists():
            raise ValueError(f"Git repository path does not exist: {path}")
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(path),
            "rev-parse",
            "--is-bare-repository",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode().strip() or stdout.decode().strip()
            raise ValueError(f"Path is not a readable Git repository: {detail}")

    async def resolve_revision(self, local_path: str, revision: str | None) -> str:
        treeish = revision or "HEAD"
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            local_path,
            "rev-parse",
            treeish,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode().strip() or stdout.decode().strip()
            raise ValueError(f"Unable to resolve revision {treeish!r}: {detail}")
        return stdout.decode().strip()

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
