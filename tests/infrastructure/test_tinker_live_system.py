from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import traceback
from typing import Any
from uuid import uuid4

import httpx
import hvac
from open_talon_contracts.iam import WORKSPACE_PERMISSION_NAMES
import psycopg
import pytest


pytestmark = pytest.mark.integration

_ROOT_DIR = Path(__file__).resolve().parents[2]
_GATEWAY_URL = "http://127.0.0.1:8000"
_OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
_OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
_FORGEJO_URL = "http://127.0.0.1:3001"
_FORGEJO_REGISTRY_URL = "localhost:3001"
_FORGEJO_USERNAME = "forgejo"
_FORGEJO_PASSWORD = "forgejo123"
_FORGEJO_UID = os.getenv("FORGEJO_UID", "1000")
_FORGEJO_GID = os.getenv("FORGEJO_GID", "1000")
_OPENBAO_URL = "http://127.0.0.1:8200"
_OPENBAO_KV_MOUNT = "secret"
_OPENBAO_ROOT_TOKEN = os.getenv("BAO_ROOT_TOKEN", "root")
_SEEDED_TINKER_AGENT_ID = "44444444-4444-4444-4444-444444444444"
_EXECUTOR_MODEL = os.getenv("OPEN_TALON_DEFAULT_REASONING_MODEL", "gemma4:31b")
_MANAGED_TINKER_ENDPOINT = {
    "kind": "system",
    "engine_id": "openai-responses",
    "provider": "openai",
}


def _postgres_dsn() -> str:
    return os.getenv(
        "POSTGRES_DSN",
        "postgresql://admin:password@127.0.0.1:5432/app_db",
    )


def _actor_payload(*, user_id: str, display_name: str) -> dict[str, Any]:
    return {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "user_id": user_id,
        "display_name": display_name,
    }


def _workspace_actor_from_participant(participant: dict[str, Any]) -> dict[str, Any]:
    return {
        "participant_id": participant["participant_id"],
        "participant_type": participant["participant_type"],
        "user_id": participant.get("user_id"),
        "display_name": participant["display_name"],
    }


def _json_request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    expected_status: int = 200,
) -> dict[str, Any] | list[Any]:
    response = client.request(method, path, json=json_body)
    if response.status_code != expected_status:
        raise AssertionError(
            f"{method} {path} returned {response.status_code}: {response.text}"
        )
    return response.json()


def _managed_tinker_restore_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    if endpoint.get("provider") == "system-test-harness":
        return dict(_MANAGED_TINKER_ENDPOINT)
    return endpoint


def _wait_for(
    description: str,
    predicate,
    *,
    timeout_seconds: float = 120.0,
    interval_seconds: float = 1.0,
):
    deadline = time.monotonic() + timeout_seconds
    last_value = None
    while time.monotonic() < deadline:
        last_value = predicate()
        if last_value:
            return last_value
        time.sleep(interval_seconds)
    raise AssertionError(f"Timed out waiting for {description}; last_value={last_value!r}")


def _wait_for_gateway() -> None:
    def _healthy() -> bool:
        try:
            response = httpx.get(f"{_GATEWAY_URL}/health", timeout=5.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    _wait_for("gateway health", _healthy, timeout_seconds=90.0, interval_seconds=1.0)


def _wait_for_ollama_service() -> None:
    def _healthy() -> bool:
        try:
            response = httpx.get(_OLLAMA_TAGS_URL, timeout=10.0)
            response.raise_for_status()
        except Exception:
            return False
        return True

    _wait_for(
        "Ollama service",
        _healthy,
        timeout_seconds=120.0,
        interval_seconds=2.0,
    )


def _wait_for_forgejo_service() -> None:
    def _healthy() -> bool:
        try:
            response = httpx.get(_FORGEJO_URL, timeout=10.0, follow_redirects=False)
        except Exception:
            return False
        return response.status_code in {200, 302}

    _wait_for(
        "Forgejo service",
        _healthy,
        timeout_seconds=120.0,
        interval_seconds=2.0,
    )


def _available_ollama_models() -> list[str]:
    response = httpx.get(_OLLAMA_TAGS_URL, timeout=10.0)
    response.raise_for_status()
    payload = response.json()
    models = payload.get("models", [])
    return [
        str(item["name"])
        for item in models
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    ]


def _write_openbao_secret(*, path: str, value: str) -> None:
    client = hvac.Client(url=_OPENBAO_URL, token=_OPENBAO_ROOT_TOKEN)
    if not client.is_authenticated():
        raise AssertionError("OpenBao root token is not authenticated")
    client.secrets.kv.v2.create_or_update_secret(
        path=path,
        secret={"value": value},
        mount_point=_OPENBAO_KV_MOUNT,
    )


def _delete_openbao_secret(path: str | None) -> None:
    if not path:
        return
    try:
        client = hvac.Client(url=_OPENBAO_URL, token=_OPENBAO_ROOT_TOKEN)
        if not client.is_authenticated():
            return
        client.secrets.kv.v2.delete_metadata_and_all_versions(
            path=path,
            mount_point=_OPENBAO_KV_MOUNT,
        )
    except Exception:
        pass


def _run_forgejo_admin_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "exec",
            "--user",
            f"{_FORGEJO_UID}:{_FORGEJO_GID}",
            "forgejo",
            "forgejo",
            *args,
        ],
        cwd=_ROOT_DIR,
        check=False,
        capture_output=True,
        text=True,
    )


def _wait_for_forgejo_admin_user() -> None:
    def _ready() -> bool:
        listed = _run_forgejo_admin_command(
            ["admin", "user", "list", "--config", "/data/gitea/conf/app.ini"]
        )
        if listed.returncode != 0:
            return False
        if _FORGEJO_USERNAME in listed.stdout:
            return True
        created = _run_forgejo_admin_command(
            [
                "admin",
                "user",
                "create",
                "--config",
                "/data/gitea/conf/app.ini",
                "--admin",
                "--username",
                _FORGEJO_USERNAME,
                "--password",
                _FORGEJO_PASSWORD,
                "--email",
                "admin@local.dev",
            ]
        )
        return created.returncode == 0

    _wait_for(
        "Forgejo admin user",
        _ready,
        timeout_seconds=120.0,
        interval_seconds=2.0,
    )


def _create_forgejo_access_token(*, token_name: str) -> dict[str, Any]:
    response = _run_forgejo_admin_command(
        [
            "admin",
            "user",
            "generate-access-token",
            "--config",
            "/data/gitea/conf/app.ini",
            "--username",
            _FORGEJO_USERNAME,
            "--token-name",
            token_name,
            "--scopes",
            "read:package,write:package",
            "--raw",
        ]
    )
    if response.returncode != 0:
        raise AssertionError(
            f"Forgejo token creation failed with {response.returncode}: {response.stderr or response.stdout}"
        )
    token = response.stdout.strip().splitlines()[-1].strip()
    if not token:
        raise AssertionError(f"Forgejo token response missing token body: {response.stdout}")
    return {
        "token_id": None,
        "token_name": token_name,
        "token": token,
    }


def _delete_forgejo_access_token(
    *,
    token_id: int | None,
    token_name: str | None,
) -> None:
    with httpx.Client(
        base_url=_FORGEJO_URL,
        auth=(_FORGEJO_USERNAME, _FORGEJO_PASSWORD),
        timeout=30.0,
    ) as client:
        for token_key in (token_id, token_name):
            if token_key in {None, ""}:
                continue
            response = client.delete(f"/api/v1/users/{_FORGEJO_USERNAME}/tokens/{token_key}")
            if response.status_code in {204, 404}:
                return


def _delete_registry_manifest(
    immutable_ref: str | None,
    *,
    registry_token: str | None,
) -> None:
    if not immutable_ref or "@sha256:" not in immutable_ref:
        return
    repository_with_host, digest = immutable_ref.split("@", 1)
    if "/" not in repository_with_host:
        return
    _, repository = repository_with_host.split("/", 1)
    response = httpx.delete(
        f"{_FORGEJO_URL}/v2/{repository}/manifests/{digest}",
        auth=(_FORGEJO_USERNAME, registry_token or _FORGEJO_PASSWORD),
        timeout=30.0,
    )
    if response.status_code not in {202, 404}:
        raise AssertionError(
            f"Forgejo registry manifest delete failed with {response.status_code}: {response.text}"
        )


def _remove_docker_image(image_ref: str) -> None:
    subprocess.run(
        ["docker", "image", "rm", "-f", image_ref],
        cwd=_ROOT_DIR,
        check=False,
        capture_output=True,
        text=True,
    )


def _cleanup_test_organization(organization_id: str | None) -> None:
    if not organization_id:
        return
    with psycopg.connect(_postgres_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM organization_memberships WHERE organization_id = %s",
                (organization_id,),
            )
            cur.execute(
                "DELETE FROM organizations WHERE organization_id = %s",
                (organization_id,),
            )


def _cleanup_tool_generation_requests(request_ids: list[str]) -> None:
    if not request_ids:
        return
    with psycopg.connect(_postgres_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM tool_generation_revisions WHERE request_id = ANY(%s)",
                (request_ids,),
            )
            cur.execute(
                "DELETE FROM tool_generation_requests WHERE request_id = ANY(%s)",
                (request_ids,),
            )


@dataclass
class _HarnessState:
    gateway_url: str
    work_root: Path
    executor_model: str
    math_llm_models: list[str] = field(default_factory=list)
    math_llm_errors: list[str] = field(default_factory=list)
    built_images: list[str] = field(default_factory=list)
    revision_ids: list[str] = field(default_factory=list)
    request_ids: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def write_debug_artifact(
        self,
        relative_path: str,
        content: str,
    ) -> None:
        path = self.work_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _tool_output(
        self,
        tool_results: list[dict[str, Any]],
        tool_name: str,
    ) -> dict[str, Any] | None:
        for tool_result in tool_results:
            if tool_result.get("tool_name") != tool_name:
                continue
            result = tool_result.get("result") or {}
            output_payload = result.get("output_payload")
            if isinstance(output_payload, dict):
                return output_payload
        return None

    def _tool_result(
        self,
        tool_results: list[dict[str, Any]],
        tool_name: str,
    ) -> dict[str, Any] | None:
        for tool_result in tool_results:
            if tool_result.get("tool_name") == tool_name:
                return tool_result
        return None

    def _build_files(self) -> dict[str, str]:
        run_sh = "\n".join(
            [
                "#!/bin/sh",
                "set -eu",
                "",
                "fib() {",
                "  n=\"$1\"",
                "  a=0",
                "  b=1",
                "  i=0",
                "  while [ \"$i\" -lt \"$n\" ]; do",
                "    next=$((a + b))",
                "    a=\"$b\"",
                "    b=\"$next\"",
                "    i=$((i + 1))",
                "  done",
                "  printf '%s' \"$a\"",
                "}",
                "",
                "if [ -n \"${OPEN_TALON_REQUEST_PATH:-}\" ] && [ -f \"${OPEN_TALON_REQUEST_PATH}\" ]; then",
                "  n=\"$(sed -n 's/.*\\\"n\\\"[[:space:]]*:[[:space:]]*\\([0-9][0-9]*\\).*/\\1/p' \"${OPEN_TALON_REQUEST_PATH}\" | head -n1)\"",
                "  if [ -z \"$n\" ]; then",
                "    n=0",
                "  fi",
                "  value=\"$(fib \"$n\")\"",
                "  mkdir -p \"${OPEN_TALON_OUTPUT_DIR}\"",
                "  printf '{\"status\":\"completed\",\"output_payload\":{\"n\":%s,\"value\":%s}}\\n' \"$n\" \"$value\" > \"${OPEN_TALON_OUTPUT_DIR}/result.json\"",
                "else",
                "  printf 'Fibonacci(10)=55\\n'",
                "fi",
            ]
        )
        dockerfile = "\n".join(
            [
                "FROM alpine:3.20",
                "WORKDIR /app",
                "COPY run.sh /app/run.sh",
                "RUN chmod +x /app/run.sh",
                'ENTRYPOINT ["/app/run.sh"]',
            ]
        )
        return {
            "Dockerfile": dockerfile,
            "run.sh": run_sh,
        }

    def _create_revision(
        self,
        *,
        request_id: str,
        participant: dict[str, Any],
        image_ref: str,
        image_digest: str | None,
    ) -> None:
        with httpx.Client(base_url=self.gateway_url, timeout=60.0) as client:
            response = _json_request(
                client,
                "POST",
                f"/v1/tool-generation/requests/{request_id}/revisions",
                json_body={
                    "actor": {
                        "participant_id": participant["participant_id"],
                        "participant_type": participant["participant_type"],
                        "display_name": participant["display_name"],
                    },
                    "manifest": {
                        "name": "fibonacci_calculator",
                        "description": "Calculates Fibonacci numbers for a provided integer n.",
                        "parameter_contract": {
                            "parameters": [
                                {
                                    "name": "n",
                                    "type": "integer",
                                    "description": "Zero-based Fibonacci index to calculate.",
                                    "required": True,
                                }
                            ]
                        },
                        "input_schema": {
                            "type": "object",
                            "properties": {"n": {"type": "integer", "minimum": 0}},
                            "required": ["n"],
                            "additionalProperties": False,
                        },
                        "execution": {
                            "backend_kind": "docker",
                            "handler_ref": image_ref,
                            "trust_level": "sandboxed",
                            "execution_profile": {
                                "network": "none",
                                "workspace_access": "none",
                            },
                        },
                        "build_context_path": str(self.work_root / request_id),
                        "smoke_test": {
                            "command": [],
                            "input_payload": {"n": 10},
                            "expected_output_schema": {
                                "type": "object",
                                "properties": {"value": {"type": "integer"}},
                                "required": ["value"],
                            },
                        },
                        "trust_rationale": (
                            "The tool is pure computation and does not require network or workspace access."
                        ),
                        "dependency_summary": ["shell"],
                        "network_access": "none",
                        "workspace_access": "none",
                        "metadata": {"system_test": True},
                    },
                    "validation_report": {
                        "status": "passed",
                        "summary": "Smoke test returned Fibonacci(10)=55.",
                        "checks": [
                            {
                                "name": "smoke_test",
                                "status": "passed",
                                "detail": "Container returned Fibonacci(10)=55.",
                            }
                        ],
                        "metadata": {"system_test": True},
                    },
                    "image_ref": image_ref,
                    "image_digest": image_digest,
                    "metadata": {"system_test": True},
                },
            )
        revisions = response.get("revisions", [])
        if revisions:
            with self._lock:
                self.revision_ids.append(revisions[0]["revision_id"])

    def handle_tinker(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = payload["context"]
        participant = context["participant"]
        detail = context.get("tool_generation_request") or {}
        request = detail.get("request") or {}
        request_id = str(request["request_id"])
        with self._lock:
            if request_id not in self.request_ids:
                self.request_ids.append(request_id)
        tool_results = context.get("tool_results") or []
        for tool_name in (
            "generated_tool_repo_bootstrap",
            "generated_tool_repo_write",
            "generated_tool_build",
            "generated_tool_registry_push",
            "generated_tool_smoke_test",
        ):
            tool_result = self._tool_result(tool_results, tool_name)
            if tool_result is None:
                continue
            if tool_result.get("status") == "failed":
                result = tool_result.get("result") or {}
                error = result.get("error") or tool_result.get("error") or "unknown tool failure"
                raise RuntimeError(f"{tool_name} failed: {error}")
        bootstrap = self._tool_output(tool_results, "generated_tool_repo_bootstrap")
        write_result = self._tool_output(tool_results, "generated_tool_repo_write")
        build_result = self._tool_output(tool_results, "generated_tool_build")
        push_result = self._tool_output(tool_results, "generated_tool_registry_push")
        smoke_result = self._tool_output(tool_results, "generated_tool_smoke_test")

        if bootstrap is None:
            return {
                "stop_reason": "completed",
                "summary": "Bootstrapping generated tool worktree.",
                "tool_calls": [
                    {
                        "tool_name": "generated_tool_repo_bootstrap",
                        "arguments": {"request_id": request_id},
                        "summary": "Create an isolated worktree for the generated tool.",
                    }
                ],
            }

        if write_result is None:
            return {
                "stop_reason": "completed",
                "summary": "Writing generated Fibonacci tool files.",
                "tool_calls": [
                    {
                        "tool_name": "generated_tool_repo_write",
                        "arguments": {
                            "worktree_path": bootstrap["worktree_path"],
                            "files": self._build_files(),
                        },
                        "summary": "Write Dockerfile and runner script.",
                    }
                ],
            }

        if build_result is None:
            image_ref = f"localhost:3001/forgejo/generated-tools/fibonacci-calculator:{request_id}"
            with self._lock:
                if image_ref not in self.built_images:
                    self.built_images.append(image_ref)
            return {
                "stop_reason": "completed",
                "summary": "Building generated Fibonacci tool image.",
                "tool_calls": [
                    {
                        "tool_name": "generated_tool_build",
                        "arguments": {
                            "worktree_path": bootstrap["worktree_path"],
                            "image_ref": image_ref,
                            "dockerfile": "Dockerfile",
                            "build_context": ".",
                        },
                        "summary": "Build the Docker image for the generated tool.",
                    }
                ],
            }

        if push_result is None:
            return {
                "stop_reason": "completed",
                "summary": "Pushing generated Fibonacci tool image to the registry.",
                "tool_calls": [
                    {
                        "tool_name": "generated_tool_registry_push",
                        "arguments": {
                            "image_ref": build_result["image_ref"],
                        },
                        "summary": "Push the generated Docker image into the OCI registry.",
                    }
                ],
            }

        if smoke_result is None:
            return {
                "stop_reason": "completed",
                "summary": "Running Fibonacci smoke test.",
                "tool_calls": [
                    {
                        "tool_name": "generated_tool_smoke_test",
                        "arguments": {
                            "image_ref": push_result["image_ref"],
                            "network": "none",
                        },
                        "summary": "Run the generated image and verify its self-test output.",
                    }
                ],
            }

        if request.get("status") != "pending_approval":
            self._create_revision(
                request_id=request_id,
                participant=participant,
                image_ref=push_result["image_ref"],
                image_digest=push_result.get("image_digest"),
            )

        return {
            "stop_reason": "completed",
            "message": "Prepared `fibonacci_calculator` for platform approval.",
            "summary": "Tinker created a real tool revision and submitted it for approval.",
        }

    def _ollama_completion(self, *, model: str, prompt: str) -> str:
        with httpx.Client(timeout=180.0) as client:
            response = client.post(
                _OLLAMA_URL,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0},
                },
            )
            response.raise_for_status()
            payload = response.json()
        text = str(payload.get("response") or "").strip()
        if not text:
            raise RuntimeError(f"Ollama returned no response payload for model {model}")
        return text

    def handle_math(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = payload["context"]
        agent = payload["agent"]
        tool_results = context.get("tool_results") or []
        fib_result = self._tool_output(tool_results, "fibonacci_calculator")
        if fib_result is None:
            return {
                "stop_reason": "completed",
                "summary": "Requesting Fibonacci tool execution.",
                "tool_calls": [
                    {
                        "tool_name": "fibonacci_calculator",
                        "arguments": {"n": 10},
                        "summary": "Compute Fibonacci(10).",
                    }
                ],
            }

        n = int(fib_result["n"])
        value = int(fib_result["value"])
        model = str(agent.get("endpoint", {}).get("model") or self.executor_model)
        with self._lock:
            self.math_llm_models.append(model)
        prompt = (
            f"Given the verified tool result {json.dumps(fib_result, sort_keys=True)}, "
            f"reply with exactly: Fibonacci({n}) = {value}."
        )
        try:
            llm_text = self._ollama_completion(model=model, prompt=prompt)
        except Exception as exc:
            with self._lock:
                self.math_llm_errors.append(str(exc))
            llm_text = f"Fibonacci({n}) = {value}."
        if str(value) not in llm_text:
            llm_text = f"Fibonacci({n}) = {value}."
        return {
            "stop_reason": "completed",
            "message": llm_text.strip(),
            "summary": f"Answered with {model}.",
        }


class _HarnessServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, *, state: _HarnessState):
        super().__init__(server_address, handler_class)
        self.state = state


class _HarnessHandler(BaseHTTPRequestHandler):
    server: _HarnessServer

    def do_POST(self) -> None:  # noqa: N802
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            request_path = self.path.strip("/").replace("/", "_") or "root"
            timestamp = int(time.time() * 1000)
            self.server.state.write_debug_artifact(
                f"debug/{timestamp}_{request_path}_payload.json",
                json.dumps(payload, indent=2, sort_keys=True),
            )
            if self.path == "/tinker":
                response = self.server.state.handle_tinker(payload)
            elif self.path == "/math":
                response = self.server.state.handle_math(payload)
            else:
                self.send_error(404, "unknown harness path")
                return
            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # pragma: no cover - live debugging path
            failure_trace = traceback.format_exc()
            request_path = self.path.strip("/").replace("/", "_") or "root"
            timestamp = int(time.time() * 1000)
            self.server.state.write_debug_artifact(
                f"debug/{timestamp}_{request_path}_failure.txt",
                failure_trace,
            )
            body = json.dumps(
                {
                    "stop_reason": "completed",
                    "message": f"Harness failure: {exc}",
                    "summary": "Harness failure",
                }
            ).encode("utf-8")
            self.send_response(500)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@dataclass
class _LiveSystem:
    gateway_url: str
    temp_root: Path
    env: dict[str, str]
    executor_model: str
    oci_registry_secret_path: str
    oci_registry_token_id: int | None
    oci_registry_token_name: str
    oci_registry_token: str


@pytest.fixture(scope="module")
def live_open_talon_system(tmp_path_factory: pytest.TempPathFactory):
    temp_root = tmp_path_factory.mktemp("tinker-live-system")
    registry_secret_path = f"open-talon/oci-registry/{uuid4().hex}"
    env = os.environ.copy()
    env.update(
        {
            "AUTH_MODE": "none",
            "ENABLE_KAFKA_WAKEUPS": "false",
            "OPEN_TALON_OCI_REGISTRY_URL": _FORGEJO_REGISTRY_URL,
            "OPEN_TALON_OCI_REGISTRY_USERNAME": _FORGEJO_USERNAME,
            "OPEN_TALON_OCI_REGISTRY_PASSWORD_SECRET_CONFIG": json.dumps(
                {
                    "openbao": {
                        "mount": _OPENBAO_KV_MOUNT,
                        "path": registry_secret_path,
                        "field": "value",
                    }
                }
            ),
            "OPEN_TALON_OCI_REGISTRY_VALIDATE_ON_STARTUP": "false",
            "OPEN_TALON_OCI_REGISTRY_REPOSITORY_PREFIX": "forgejo/generated-tools",
            "OPEN_TALON_OPENBAO_ADDRESS": _OPENBAO_URL,
            "BAO_ROOT_TOKEN": _OPENBAO_ROOT_TOKEN,
            "OPEN_TALON_EXECUTION_ROOT": str(temp_root / "executions"),
            "OPEN_TALON_GENERATED_TOOLS_ROOT": str(temp_root / "generated-tools"),
            "OPEN_TALON_DEFAULT_WORKSPACE_PATH": str(_ROOT_DIR),
            "AGENT_LOOP_POLL_INTERVAL_SECONDS": "0.5",
            "RECONCILE_INTERVAL_SECONDS": "1.0",
            "LEASE_TTL_SECONDS": "120",
            "LEASE_HEARTBEAT_SECONDS": "10",
        }
    )

    subprocess.run(
        ["./open-talon", "stop"],
        cwd=_ROOT_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["./open-talon", "start"],
        cwd=_ROOT_DIR,
        env=env,
        check=True,
    )
    _wait_for_gateway()
    _wait_for_forgejo_service()
    _wait_for_forgejo_admin_user()
    _wait_for_ollama_service()
    token_detail = _create_forgejo_access_token(
        token_name=f"tinker-live-{uuid4().hex[:12]}"
    )
    _write_openbao_secret(
        path=registry_secret_path,
        value=token_detail["token"],
    )
    available_models = _available_ollama_models()
    if _EXECUTOR_MODEL not in available_models:
        pytest.skip(
            f"Required local Ollama model `{_EXECUTOR_MODEL}` is not preloaded for the live Tinker system test. "
            f"Available models: {available_models}"
        )

    try:
        yield _LiveSystem(
            gateway_url=_GATEWAY_URL,
            temp_root=temp_root,
            env=env,
            executor_model=_EXECUTOR_MODEL,
            oci_registry_secret_path=registry_secret_path,
            oci_registry_token_id=(
                int(token_detail["token_id"]) if token_detail["token_id"] is not None else None
            ),
            oci_registry_token_name=str(token_detail["token_name"]),
            oci_registry_token=str(token_detail["token"]),
        )
    finally:
        _delete_openbao_secret(registry_secret_path)
        _delete_forgejo_access_token(
            token_id=(
                int(token_detail["token_id"]) if "token_detail" in locals() and token_detail.get("token_id") is not None else None
            ),
            token_name=(
                str(token_detail["token_name"]) if "token_detail" in locals() and token_detail.get("token_name") else None
            ),
        )
        subprocess.run(
            ["./open-talon", "stop"],
            cwd=_ROOT_DIR,
            env=env,
            check=False,
        )
        shutil.rmtree(temp_root, ignore_errors=True)


def test_tinker_can_generate_and_execute_fibonacci_tool_on_live_system(
    live_open_talon_system: _LiveSystem,
):
    admin_user_id = str(uuid4())
    admin_actor = _actor_payload(
        user_id=admin_user_id,
        display_name="Live System Test Admin",
    )
    test_suffix = uuid4().hex[:8]
    org_slug = f"tinker-system-test-{test_suffix}"
    work_root = live_open_talon_system.temp_root / "worktrees" / org_slug
    work_root.mkdir(parents=True, exist_ok=True)
    state = _HarnessState(
        gateway_url=live_open_talon_system.gateway_url,
        work_root=work_root,
        executor_model=live_open_talon_system.executor_model,
    )
    server = _HarnessServer(("127.0.0.1", 0), _HarnessHandler, state=state)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    harness_base = f"http://127.0.0.1:{server.server_address[1]}"
    original_tinker_endpoint: dict[str, Any] | None = None
    organization_id: str | None = None
    workspace_id: str | None = None
    workspace_actor: dict[str, Any] | None = None
    workspace_manager_actor: dict[str, Any] | None = None
    math_agent_id: str | None = None
    published_tool_id: str | None = None
    published_handler_ref: str | None = None

    try:
        with httpx.Client(
            base_url=live_open_talon_system.gateway_url,
            timeout=60.0,
        ) as client:
            agents = _json_request(client, "GET", "/v1/agents")
            tinker = next(
                agent
                for agent in agents
                if agent["agent_id"] == _SEEDED_TINKER_AGENT_ID
            )
            original_tinker_endpoint = _managed_tinker_restore_endpoint(tinker["endpoint"])

            _json_request(
                client,
                "PATCH",
                f"/v1/agents/{_SEEDED_TINKER_AGENT_ID}",
                json_body={
                    "actor": admin_actor,
                    "endpoint": {
                        "kind": "remote",
                        "url": f"{harness_base}/tinker",
                        "model": tinker["endpoint"].get("model"),
                        "provider": "system-test-harness",
                    },
                    "metadata": {"system_test_harness": True},
                },
            )

            organization = _json_request(
                client,
                "POST",
                "/v1/organizations",
                json_body={
                    "actor": admin_actor,
                    "slug": org_slug,
                    "name": f"Tinker Live Test {test_suffix}",
                    "description": "Real system test organization for Tinker.",
                    "metadata": {"system_test": True},
                },
            )
            organization_id = organization["organization_id"]

            workspace_detail = _json_request(
                client,
                "POST",
                f"/v1/organizations/{organization_id}/workspaces",
                json_body={
                    "name": f"Tinker Workspace {test_suffix}",
                    "description": "Real system test workspace.",
                    "actor": admin_actor,
                    "metadata": {"system_test": True},
                },
            )
            workspace_id = workspace_detail["workspace"]["workspace_id"]
            workspace_actor = _workspace_actor_from_participant(
                workspace_detail["participants"][0]
            )
            workspace_manager_actor = {
                **workspace_actor,
                "iam_permissions": list(WORKSPACE_PERMISSION_NAMES),
            }

            thread_detail = _json_request(
                client,
                "POST",
                f"/v1/workspaces/{workspace_id}/threads",
                json_body={
                    "title": "Live Fibonacci Tool Request",
                    "actor": workspace_manager_actor,
                },
            )
            thread_id = thread_detail["thread"]["thread_id"]

            attached_tinker = _json_request(
                client,
                "POST",
                f"/v1/workspaces/{workspace_id}/agents",
                json_body={
                    "actor": workspace_manager_actor,
                    "agent_id": _SEEDED_TINKER_AGENT_ID,
                },
            )
            assert attached_tinker["display_name"] == "Tinker"

            kickoff = _json_request(
                client,
                "POST",
                f"/v1/threads/{thread_id}/messages",
                json_body={
                    "actor": workspace_actor,
                    "content": (
                        "Tinker, create a Fibonacci calculator tool for this organization. "
                        "It must accept integer n and return the Fibonacci value."
                    ),
                    "visibility": "workspace",
                    "target_system_agent_id": _SEEDED_TINKER_AGENT_ID,
                    "target_tool_scope": "organization",
                    "metadata": {
                        "target_tool_name": "fibonacci_calculator",
                        "system_test": True,
                    },
                },
            )
            request_id = kickoff["metadata"]["tool_generation_request_id"]
            assert request_id

            def _pending_request_detail():
                detail_list = _json_request(
                    client,
                    "GET",
                    f"/v1/threads/{thread_id}/tool-generation/requests",
                )
                if not detail_list:
                    return None
                detail = detail_list[0]
                if (
                    detail["request"]["request_id"] == request_id
                    and detail["request"]["status"] == "pending_approval"
                    and detail["revisions"]
                ):
                    return detail
                return None

            request_detail = _wait_for(
                "Tinker tool-generation revision",
                _pending_request_detail,
                timeout_seconds=240.0,
                interval_seconds=2.0,
            )
            revision_id = request_detail["revisions"][0]["revision_id"]

            approval = _json_request(
                client,
                "POST",
                f"/v1/tool-generation/revisions/{revision_id}/approve",
                json_body={"actor": admin_actor},
            )
            assert approval["request"]["status"] == "verifying_registry_pull"
            assert approval["request"]["requested_scope"] == "organization"

            def _published_request_detail():
                detail = _json_request(
                    client,
                    "GET",
                    f"/v1/tool-generation/requests/{request_id}",
                )
                if detail["request"]["status"] == "published" and detail["request"]["final_tool_id"]:
                    return detail
                return None

            published_detail = _wait_for(
                "published generated tool after registry pull verification",
                _published_request_detail,
                timeout_seconds=240.0,
                interval_seconds=2.0,
            )
            published_tool_id = published_detail["request"]["final_tool_id"]
            assert published_tool_id

            workspace_after_publish = _json_request(
                client,
                "GET",
                f"/v1/workspaces/{workspace_id}",
            )
            assert workspace_after_publish["tools"] == []

            organization_tools = _json_request(
                client,
                "GET",
                f"/v1/organizations/{organization_id}/tools",
            )
            fib_tool = next(
                tool for tool in organization_tools if tool["tool_id"] == published_tool_id
            )
            assert fib_tool["scope"] == "organization"
            assert fib_tool["execution"]["backend_kind"] == "docker"
            assert "@sha256:" in fib_tool["execution"]["handler_ref"]
            published_handler_ref = str(fib_tool["execution"]["handler_ref"])

            attached_tool = _json_request(
                client,
                "PUT",
                f"/v1/workspaces/{workspace_id}/tools/{published_tool_id}",
                json_body={
                    "actor": workspace_manager_actor,
                    "enabled": True,
                },
            )
            assert attached_tool["name"] == "fibonacci_calculator"

            math_agent = _json_request(
                client,
                "POST",
                "/v1/agents",
                json_body={
                    "actor": admin_actor,
                    "display_name": "Small Math Runner",
                    "description": "Uses the narrowest available tool and responds briefly.",
                    "role": "calculator agent",
                    "capabilities": ["calculation", "tool_use"],
                    "endpoint": {
                        "kind": "remote",
                        "url": f"{harness_base}/math",
                        "model": live_open_talon_system.executor_model,
                        "provider": "system-test-harness",
                    },
                    "system_prompt": (
                        "Use the provided tool results carefully and answer with the final numeric result."
                    ),
                    "metadata": {"system_test": True},
                },
            )
            math_agent_id = math_agent["agent_id"]

            attached_math = _json_request(
                client,
                "POST",
                f"/v1/workspaces/{workspace_id}/agents",
                json_body={
                    "actor": workspace_manager_actor,
                    "agent_id": math_agent_id,
                },
            )
            assert attached_math["display_name"] == "Small Math Runner"

            _json_request(
                client,
                "POST",
                f"/v1/threads/{thread_id}/messages",
                json_body={
                    "actor": workspace_actor,
                    "content": "Use fibonacci_calculator to compute Fibonacci for n=10.",
                    "visibility": "workspace",
                    "target_system_agent_id": math_agent_id,
                    "metadata": {"system_test": True},
                },
            )

            def _final_timeline_message():
                timeline = _json_request(
                    client,
                    "GET",
                    f"/v1/threads/{thread_id}/timeline",
                )
                for message in reversed(timeline["messages"]):
                    content = str(message.get("content") or "")
                    if "Small Math Runner" in content and "55" in content:
                        return message
                return None

            final_message = _wait_for(
                "final Fibonacci answer",
                _final_timeline_message,
                timeout_seconds=180.0,
                interval_seconds=2.0,
            )
            assert "Fibonacci(10)" in final_message["content"]
            assert "55" in final_message["content"]

            communication_log = _json_request(
                client,
                "GET",
                f"/v1/workspaces/{workspace_id}/communication-log?thread_id={thread_id}&limit=100&offset=0",
            )
            assert any(
                entry["content"].startswith(
                    "Tinker prepared tool revision `fibonacci_calculator` for platform approval."
                )
                for entry in communication_log["entries"]
            )
            assert any(
                entry["content"].startswith("Approval started for generated tool `fibonacci_calculator`.")
                for entry in communication_log["entries"]
            )
            assert any(
                "organization system tools catalog" in entry["content"]
                for entry in communication_log["entries"]
            )

            assert state.math_llm_models
            assert live_open_talon_system.executor_model in state.math_llm_models
            assert state.math_llm_errors == []
            assert state.built_images
    finally:
        with httpx.Client(
            base_url=live_open_talon_system.gateway_url,
            timeout=30.0,
        ) as client:
            if original_tinker_endpoint is not None:
                try:
                    _json_request(
                        client,
                        "PATCH",
                        f"/v1/agents/{_SEEDED_TINKER_AGENT_ID}",
                        json_body={
                            "actor": admin_actor,
                            "endpoint": original_tinker_endpoint,
                            "metadata": {"system_test_harness": False},
                        },
                    )
                except Exception:
                    pass
            try:
                _cleanup_tool_generation_requests(list(state.request_ids))
            except Exception:
                pass
            if published_tool_id is not None:
                try:
                    _json_request(
                        client,
                        "DELETE",
                        f"/v1/tools/{published_tool_id}",
                        json_body={"actor": admin_actor},
                    )
                except Exception:
                    pass
            if math_agent_id is not None:
                try:
                    _json_request(
                        client,
                        "DELETE",
                        f"/v1/agents/{math_agent_id}",
                        json_body={"actor": admin_actor},
                    )
                except Exception:
                    pass
            if workspace_id is not None and workspace_manager_actor is not None:
                try:
                    _json_request(
                        client,
                        "DELETE",
                        f"/v1/workspaces/{workspace_id}",
                        json_body={"actor": workspace_manager_actor},
                    )
                except Exception:
                    pass
        try:
            _delete_registry_manifest(
                published_handler_ref,
                registry_token=live_open_talon_system.oci_registry_token,
            )
        except Exception:
            pass
        for image_ref in state.built_images:
            _remove_docker_image(image_ref)
        _cleanup_test_organization(organization_id)
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=10.0)
