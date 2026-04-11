from __future__ import annotations

from typing import Protocol

from open_talon_contracts.models import ExecutionHandle, ExecutionResult, ExecutionSpec


class ExecutionBackend(Protocol):
    kind: str

    async def submit(self, spec: ExecutionSpec) -> ExecutionHandle: ...

    async def poll(self, handle: ExecutionHandle) -> ExecutionResult: ...

    async def cancel(self, handle: ExecutionHandle, reason: str | None = None) -> None: ...

    async def collect(self, handle: ExecutionHandle) -> ExecutionResult: ...
