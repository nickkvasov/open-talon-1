from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os
from pathlib import Path

from open_talon_contracts.models import ExecutionHandle, ExecutionResult, ExecutionSpec

from .utils import collect_execution_result, prepare_invocation_files, utcnow

logger = logging.getLogger(__name__)


@dataclass
class _ProcessRecord:
    process: asyncio.subprocess.Process
    invocation_dir: Path
    output_dir: Path
    started_at: object


class LocalProcessExecutionBackend:
    kind = "local_process"

    def __init__(self, *, execution_root: str) -> None:
        self._execution_root = execution_root
        self._processes: dict[str, _ProcessRecord] = {}

    async def submit(self, spec: ExecutionSpec) -> ExecutionHandle:
        invocation_dir, input_dir, output_dir = prepare_invocation_files(spec, self._execution_root)
        stdout_path = output_dir / "stdout.txt"
        stderr_path = output_dir / "stderr.txt"
        command = list(spec.profile.get("command", [])) or [spec.handler_ref]
        env = {
            "OPEN_TALON_REQUEST_PATH": str(input_dir / "request.json"),
            "OPEN_TALON_OUTPUT_DIR": str(output_dir),
        }
        merged_env = os.environ.copy()
        merged_env.update(env)
        if spec.execution_workspace is not None:
            workspace_path = spec.execution_workspace.path or spec.execution_workspace.uri
            if workspace_path:
                merged_env["OPEN_TALON_WORKSPACE_PATH"] = workspace_path
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=merged_env.get("OPEN_TALON_WORKSPACE_PATH"),
            env=merged_env,
            stdout=stdout_path.open("wb"),
            stderr=stderr_path.open("wb"),
        )
        handle = ExecutionHandle(
            backend_kind=self.kind,
            invocation_id=spec.invocation_id,
            handle=str(process.pid),
            metadata={
                "invocation_dir": str(invocation_dir),
                "output_dir": str(output_dir),
            },
        )
        self._processes[handle.handle] = _ProcessRecord(
            process=process,
            invocation_dir=invocation_dir,
            output_dir=output_dir,
            started_at=utcnow(),
        )
        return handle

    async def poll(self, handle: ExecutionHandle) -> ExecutionResult:
        record = self._require_record(handle)
        if record.process.returncode is None:
            return ExecutionResult(status="running", started_at=record.started_at)
        status = "completed" if record.process.returncode == 0 else "failed"
        result = collect_execution_result(record.output_dir, fallback_status=status)
        return result.model_copy(update={"started_at": record.started_at, "finished_at": utcnow()})

    async def cancel(self, handle: ExecutionHandle, reason: str | None = None) -> None:
        record = self._require_record(handle)
        if record.process.returncode is None:
            record.process.terminate()
            try:
                await asyncio.wait_for(record.process.wait(), timeout=5)
            except TimeoutError:  # pragma: no cover - defensive
                record.process.kill()
                await record.process.wait()
        logger.warning("Local process execution cancelled handle=%s reason=%s", handle.handle, reason)

    async def collect(self, handle: ExecutionHandle) -> ExecutionResult:
        record = self._require_record(handle)
        await record.process.wait()
        status = "completed" if record.process.returncode == 0 else "failed"
        result = collect_execution_result(record.output_dir, fallback_status=status)
        self._processes.pop(handle.handle, None)
        return result.model_copy(update={"started_at": record.started_at, "finished_at": utcnow()})

    def _require_record(self, handle: ExecutionHandle) -> _ProcessRecord:
        try:
            return self._processes[handle.handle]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"Unknown local execution handle {handle.handle}") from exc
