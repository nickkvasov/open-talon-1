from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from open_talon_contracts.models import ExecutionHandle, ExecutionResult, ExecutionSpec

from .utils import collect_execution_result, prepare_invocation_files, utcnow

logger = logging.getLogger(__name__)


class DockerExecutionBackend:
    kind = "docker"

    def __init__(self, *, execution_root: str) -> None:
        self._execution_root = execution_root
        self._invocations: dict[str, dict[str, object]] = {}

    async def submit(self, spec: ExecutionSpec) -> ExecutionHandle:
        invocation_dir, input_dir, output_dir = prepare_invocation_files(spec, self._execution_root)
        command = [
            "docker",
            "run",
            "--rm",
            "--detach",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65532:65532",
            "--tmpfs",
            "/tmp:size=64m",
            "--mount",
            f"type=bind,src={input_dir},dst=/input,readonly",
            "--mount",
            f"type=bind,src={output_dir},dst=/output",
            "--env",
            "OPEN_TALON_REQUEST_PATH=/input/request.json",
            "--env",
            "OPEN_TALON_OUTPUT_DIR=/output",
        ]
        if spec.limits.network == "none":
            command.extend(["--network", "none"])
        if spec.limits.cpu_millis is not None:
            command.extend(["--cpus", str(spec.limits.cpu_millis / 1000)])
        if spec.limits.memory_mb is not None:
            command.extend(["--memory", f"{spec.limits.memory_mb}m"])
        if spec.limits.pids_limit is not None:
            command.extend(["--pids-limit", str(spec.limits.pids_limit)])
        workspace_mount = self._workspace_mount_path(spec)
        if workspace_mount is not None:
            readonly = spec.limits.workspace_access != "read_write"
            mount_opt = "readonly" if readonly else "rw"
            command.extend(
                [
                    "--mount",
                    f"type=bind,src={workspace_mount},dst=/workspace,{mount_opt}",
                    "--env",
                    "OPEN_TALON_WORKSPACE_PATH=/workspace",
                ]
            )
        command.append(spec.handler_ref)
        command.extend(spec.profile.get("command", []))
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(
                f"Docker execution failed to start: {(stderr or stdout).decode().strip()}"
            )
        container_id = stdout.decode().strip()
        handle = ExecutionHandle(
            backend_kind=self.kind,
            invocation_id=spec.invocation_id,
            handle=container_id,
            metadata={
                "invocation_dir": str(invocation_dir),
                "output_dir": str(output_dir),
            },
        )
        self._invocations[handle.handle] = {
            "output_dir": output_dir,
            "started_at": utcnow(),
        }
        return handle

    async def poll(self, handle: ExecutionHandle) -> ExecutionResult:
        invocation = self._require_invocation(handle)
        state = await self._inspect_state(handle.handle)
        if state in {"created", "running", "restarting"}:
            return ExecutionResult(status="running", started_at=invocation["started_at"])
        return collect_execution_result(
            invocation["output_dir"],
            fallback_status="completed" if state == "exited" else "failed",
        ).model_copy(
            update={
                "started_at": invocation["started_at"],
                "finished_at": utcnow(),
            }
        )

    async def cancel(self, handle: ExecutionHandle, reason: str | None = None) -> None:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            handle.handle,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        logger.warning("Docker execution cancelled handle=%s reason=%s", handle.handle, reason)

    async def collect(self, handle: ExecutionHandle) -> ExecutionResult:
        invocation = self._require_invocation(handle)
        while True:
            state = await self._inspect_state(handle.handle)
            if state in {"created", "running", "restarting"}:
                await asyncio.sleep(0.5)
                continue
            result = collect_execution_result(
                invocation["output_dir"],
                fallback_status="completed" if state == "exited" else "failed",
            )
            break
        self._invocations.pop(handle.handle, None)
        return result.model_copy(
            update={
                "started_at": invocation["started_at"],
                "finished_at": utcnow(),
            }
        )

    async def _inspect_state(self, handle: str) -> str:
        process = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            "--format",
            "{{.State.Status}}",
            handle,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode().strip()
            if "No such object" in message:
                return "exited"
            raise RuntimeError(f"docker inspect failed: {message}")
        return stdout.decode().strip()

    def _workspace_mount_path(self, spec: ExecutionSpec) -> str | None:
        if spec.execution_workspace is None:
            return None
        return spec.execution_workspace.path or spec.execution_workspace.uri

    def _require_invocation(self, handle: ExecutionHandle) -> dict[str, object]:
        try:
            return self._invocations[handle.handle]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"Unknown docker execution handle {handle.handle}") from exc
