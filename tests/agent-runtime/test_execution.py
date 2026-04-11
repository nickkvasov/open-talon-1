from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sys
from uuid import uuid4

_AGENT_RUNTIME_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/agent-runtime")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
for path in (_AGENT_RUNTIME_DIR, _CONTRACTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_contracts.models import (
    AgentToolCallDraft,
    ExecutionLimits,
    ExecutionSpec,
    ExecutionWorkspaceRef,
)

from agent_runtime.execution.docker import DockerExecutionBackend
from agent_runtime.execution.local_process import LocalProcessExecutionBackend


async def _collect_local_result(tmp_path: Path):
    script_path = tmp_path / "runner.py"
    script_path.write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "from pathlib import Path",
                "request = json.loads(Path(os.environ['OPEN_TALON_REQUEST_PATH']).read_text())",
                "output_dir = Path(os.environ['OPEN_TALON_OUTPUT_DIR'])",
                "payload = {'status': 'completed', 'output_payload': {'echo': request['inline_payload']}}",
                "(output_dir / 'result.json').write_text(json.dumps(payload))",
            ]
        ),
        encoding="utf-8",
    )
    backend = LocalProcessExecutionBackend(execution_root=str(tmp_path / "exec"))
    spec = ExecutionSpec(
        invocation_id=uuid4(),
        handler_ref="ignored",
        inline_payload={"query": "claim_task_for_system_agent"},
        profile={"command": [sys.executable, str(script_path)]},
    )
    handle = await backend.submit(spec)
    return await backend.collect(handle)


def test_local_process_backend_executes_file_protocol(tmp_path):
    result = asyncio.run(_collect_local_result(tmp_path))
    assert result.status == "completed"
    assert result.output_payload == {"echo": {"query": "claim_task_for_system_agent"}}


def test_docker_backend_submit_uses_isolation_flags(monkeypatch, tmp_path):
    captured: list[list[str]] = []

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (b"container-123\n", b"")

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured.append([str(arg) for arg in args])
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    backend = DockerExecutionBackend(execution_root=str(tmp_path / "exec"))
    spec = ExecutionSpec(
        invocation_id=uuid4(),
        handler_ref="ghcr.io/open-talon/tool:latest",
        inline_payload={"query": "repo_search"},
        execution_workspace=ExecutionWorkspaceRef(
            mode="local_path",
            path=str(tmp_path / "workspace"),
        ),
        limits=ExecutionLimits(
            timeout_seconds=30,
            cpu_millis=500,
            memory_mb=256,
            pids_limit=64,
            network="none",
            workspace_access="read_only",
        ),
        profile={"command": ["/runner"]},
    )

    handle = asyncio.run(backend.submit(spec))

    assert handle.handle == "container-123"
    assert captured
    command = captured[0]
    assert "--read-only" in command
    assert "--cap-drop" in command
    assert "ALL" in command
    assert "--network" in command
    assert "none" in command
    assert "--tmpfs" in command
    assert "--pids-limit" in command
    assert "--memory" in command
    assert "--cpus" in command
    assert "ghcr.io/open-talon/tool:latest" in command


def test_execution_models_accept_legacy_workspace_ref_field():
    spec = ExecutionSpec.model_validate(
        {
            "invocation_id": str(uuid4()),
            "handler_ref": "repo_search",
            "workspace_ref": {
                "mode": "local_path",
                "path": "/tmp/workspace",
            },
        }
    )
    draft = AgentToolCallDraft.model_validate(
        {
            "tool_name": "repo_search",
            "workspace_ref": {
                "mode": "local_path",
                "path": "/tmp/workspace",
            },
        }
    )

    assert spec.execution_workspace is not None
    assert spec.execution_workspace.path == "/tmp/workspace"
    assert "execution_workspace" in spec.model_dump(mode="json")
    assert "workspace_ref" not in spec.model_dump(mode="json")
    assert draft.execution_workspace is not None
    assert draft.execution_workspace.path == "/tmp/workspace"
