from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from urllib.parse import urlparse

from open_talon_contracts.models import ArtifactRef, ExecutionResult, ExecutionSpec, ToolCallResult


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def prepare_invocation_files(spec: ExecutionSpec, execution_root: str) -> tuple[Path, Path, Path]:
    invocation_dir = Path(execution_root) / str(spec.invocation_id)
    input_dir = invocation_dir / "input"
    output_dir = invocation_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    request_path = input_dir / "request.json"
    request_path.write_text(
        json.dumps(spec.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    artifacts_dir = input_dir / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    for artifact in spec.artifact_refs:
        source = _artifact_source_path(artifact)
        if source is None or not source.exists():
            continue
        destination = artifacts_dir / artifact.name
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)
    return invocation_dir, input_dir, output_dir


def collect_execution_result(output_dir: Path, *, fallback_status: str, error: str | None = None) -> ExecutionResult:
    result_path = output_dir / "result.json"
    payload: dict | None = None
    if result_path.exists():
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    if payload is None:
        payload = {}
    result = ExecutionResult.model_validate(
        {
            "status": payload.get("status", fallback_status),
            "output_payload": payload.get("output_payload", {}),
            "exit_code": payload.get("exit_code"),
            "error": payload.get("error", error),
            "metadata": payload.get("metadata", {}),
        }
    )
    stdout_path = output_dir / "stdout.txt"
    stderr_path = output_dir / "stderr.txt"
    updates: dict = {}
    if stdout_path.exists():
        updates["stdout_ref"] = ArtifactRef(name="stdout", uri=str(stdout_path), content_type="text/plain")
    if stderr_path.exists():
        updates["stderr_ref"] = ArtifactRef(name="stderr", uri=str(stderr_path), content_type="text/plain")
    artifact_refs = []
    artifacts_dir = output_dir / "artifacts"
    if artifacts_dir.exists():
        for artifact_path in sorted(artifacts_dir.iterdir()):
            artifact_refs.append(
                ArtifactRef(
                    name=artifact_path.name,
                    uri=str(artifact_path),
                    content_type="application/octet-stream",
                )
            )
    if artifact_refs:
        updates["artifacts"] = artifact_refs
    return result.model_copy(update=updates)


def to_tool_call_result(result: ExecutionResult) -> ToolCallResult:
    return ToolCallResult(
        output_payload=result.output_payload,
        stdout_ref=result.stdout_ref,
        stderr_ref=result.stderr_ref,
        artifacts=result.artifacts,
        exit_code=result.exit_code,
        error=result.error,
        metadata=result.metadata,
    )


def _artifact_source_path(artifact: ArtifactRef) -> Path | None:
    if artifact.uri.startswith("file://"):
        parsed = urlparse(artifact.uri)
        return Path(parsed.path)
    if "://" in artifact.uri:
        return None
    return Path(artifact.uri)
