from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


def _request_payload() -> dict[str, Any]:
    request_path = os.getenv("OPEN_TALON_REQUEST_PATH")
    if not request_path:
        raise RuntimeError("OPEN_TALON_REQUEST_PATH is not set")
    payload = json.loads(Path(request_path).read_text(encoding="utf-8"))
    inline_payload = payload.get("inline_payload", {})
    if isinstance(inline_payload, dict):
        return inline_payload
    raise ValueError("inline_payload must be a JSON object")


def _output_dir() -> Path:
    path = os.getenv("OPEN_TALON_OUTPUT_DIR")
    if not path:
        raise RuntimeError("OPEN_TALON_OUTPUT_DIR is not set")
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _write_result(
    *,
    status: str = "completed",
    output_payload: dict[str, Any] | None = None,
    error: str | None = None,
    exit_code: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    (_output_dir() / "result.json").write_text(
        json.dumps(
            {
                "status": status,
                "output_payload": output_payload or {},
                "error": error,
                "exit_code": exit_code,
                "metadata": metadata or {},
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _generated_tools_root() -> Path:
    configured = os.getenv("OPEN_TALON_TINKER_GENERATED_TOOLS_ROOT")
    if configured:
        root = Path(configured)
    elif os.getenv("OPEN_TALON_WORKSPACE_PATH"):
        root = Path(os.environ["OPEN_TALON_WORKSPACE_PATH"]) / ".generated-tools"
    else:
        root = Path.cwd() / ".generated-tools"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_child_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    if not str(candidate).startswith(str(root.resolve())):
        raise ValueError(f"Refusing to access path outside root: {relative_path}")
    return candidate


def _run(command: list[str], *, cwd: Path | None = None) -> tuple[int, str, str]:
    process = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if process.stdout:
        print(process.stdout, end="")
    if process.stderr:
        print(process.stderr, end="", file=sys.stderr)
    return process.returncode, process.stdout, process.stderr


def bootstrap_worktree() -> None:
    payload = _request_payload()
    request_id = str(payload.get("request_id") or "default").strip()
    branch = str(payload.get("branch_name") or f"tinker/{request_id}").strip()
    root = _generated_tools_root()
    worktree = _safe_child_path(root, request_id)
    worktree.mkdir(parents=True, exist_ok=True)
    _write_result(
        output_payload={
            "request_id": request_id,
            "branch_name": branch,
            "worktree_path": str(worktree),
        }
    )


def write_files() -> None:
    payload = _request_payload()
    root = Path(str(payload.get("worktree_path") or _generated_tools_root()))
    root.mkdir(parents=True, exist_ok=True)
    files = payload.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("files must be a non-empty object mapping relative paths to contents")
    written: list[str] = []
    for relative_path, contents in files.items():
        if not isinstance(relative_path, str) or not isinstance(contents, str):
            raise ValueError("files entries must map string paths to string contents")
        destination = _safe_child_path(root, relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")
        written.append(str(destination))
    _write_result(output_payload={"written_files": written})


def build_image() -> None:
    payload = _request_payload()
    worktree = Path(str(payload.get("worktree_path") or _generated_tools_root()))
    image_ref = str(payload.get("image_ref") or "").strip()
    if not image_ref:
        raise ValueError("image_ref is required")
    dockerfile = str(payload.get("dockerfile") or "Dockerfile").strip()
    build_context = str(payload.get("build_context") or ".").strip()
    command = [
        "docker",
        "build",
        "-t",
        image_ref,
        "-f",
        dockerfile,
        build_context,
    ]
    code, _, _ = _run(command, cwd=worktree)
    if code != 0:
        raise RuntimeError(f"docker build failed with exit code {code}")
    inspect_code, stdout, _ = _run(
        ["docker", "image", "inspect", image_ref, "--format", "{{json .RepoDigests}}"]
    )
    repo_digests: list[str] = []
    if inspect_code == 0 and stdout.strip():
        repo_digests = json.loads(stdout.strip())
    digest = next((item.split("@", 1)[1] for item in repo_digests if "@" in item), None)
    _write_result(
        output_payload={
            "image_ref": image_ref,
            "image_digest": digest,
            "repo_digests": repo_digests,
        }
    )


def push_image() -> None:
    payload = _request_payload()
    image_ref = str(payload.get("image_ref") or "").strip()
    if not image_ref:
        raise ValueError("image_ref is required")
    code, _, _ = _run(["docker", "push", image_ref])
    if code != 0:
        raise RuntimeError(f"docker push failed with exit code {code}")
    inspect_code, stdout, _ = _run(
        ["docker", "image", "inspect", image_ref, "--format", "{{json .RepoDigests}}"]
    )
    repo_digests: list[str] = []
    if inspect_code == 0 and stdout.strip():
        repo_digests = json.loads(stdout.strip())
    digest = next((item.split("@", 1)[1] for item in repo_digests if "@" in item), None)
    _write_result(
        output_payload={
            "image_ref": image_ref,
            "image_digest": digest,
            "repo_digests": repo_digests,
        }
    )


def smoke_test() -> None:
    payload = _request_payload()
    image_ref = str(payload.get("image_ref") or "").strip()
    if not image_ref:
        raise ValueError("image_ref is required")
    command = ["docker", "run", "--rm"]
    if payload.get("network") == "none":
        command.extend(["--network", "none"])
    env_map = payload.get("env", {})
    if isinstance(env_map, dict):
        for key, value in env_map.items():
            command.extend(["--env", f"{key}={value}"])
    command.append(image_ref)
    container_command = payload.get("command", [])
    if isinstance(container_command, list):
        command.extend(str(item) for item in container_command)
    code, stdout, stderr = _run(command)
    if code != 0:
        raise RuntimeError(f"docker smoke test failed with exit code {code}: {stderr.strip()}")
    _write_result(
        output_payload={
            "image_ref": image_ref,
            "stdout": stdout.strip(),
        }
    )


def publish_assets() -> None:
    payload = _request_payload()
    assets = payload.get("assets")
    if not isinstance(assets, dict) or not assets:
        raise ValueError("assets must be a non-empty object mapping asset names to source paths")
    artifacts_dir = _output_dir() / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    published: dict[str, str] = {}
    for name, source in assets.items():
        source_path = Path(str(source))
        if not source_path.exists():
            raise FileNotFoundError(f"asset source does not exist: {source_path}")
        destination = artifacts_dir / str(name)
        if source_path.is_dir():
            shutil.copytree(source_path, destination, dirs_exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)
        published[str(name)] = str(destination)
    _write_result(
        output_payload={
            "artifacts": published,
            "warning": "Assets were staged locally. Persisting them into workspace assets still requires orchestration through the Open Talon asset APIs.",
        }
    )


def update_request_status() -> None:
    payload = _request_payload()
    _write_result(
        output_payload={
            "requested_status_update": payload,
            "warning": "Status updates are advisory from this helper. Persist the state transition through the collaboration kernel or HTTP API.",
        }
    )


_ACTIONS = {
    "bootstrap-worktree": bootstrap_worktree,
    "write-files": write_files,
    "build-image": build_image,
    "push-image": push_image,
    "smoke-test": smoke_test,
    "publish-assets": publish_assets,
    "update-request-status": update_request_status,
}


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print(f"usage: python -m agent_runtime.tinker_tools <{'|'.join(sorted(_ACTIONS))}>", file=sys.stderr)
        return 2
    action = args[0]
    handler = _ACTIONS.get(action)
    if handler is None:
        print(f"unknown action: {action}", file=sys.stderr)
        return 2
    try:
        handler()
    except Exception as exc:
        _write_result(status="failed", error=str(exc), exit_code=1)
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
