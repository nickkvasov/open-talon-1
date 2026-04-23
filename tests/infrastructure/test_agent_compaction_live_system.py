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
from typing import Any
from uuid import uuid4

import httpx
import psycopg
import pytest
from open_talon_contracts.iam import WORKSPACE_PERMISSION_NAMES


pytestmark = pytest.mark.integration

_ROOT_DIR = Path(__file__).resolve().parents[2]
_GATEWAY_URL = "http://127.0.0.1:8000"


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


def _read_prompt_dump_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def _fetch_compaction_summary_rows(thread_id: str) -> list[dict[str, Any]]:
    with psycopg.connect(_postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    memory_entry_id::text,
                    run_id::text,
                    version,
                    summary,
                    content,
                    metadata
                FROM memory_entries
                WHERE thread_id = %s
                  AND entry_type = 'context_compaction_summary'
                ORDER BY updated_at DESC
                """,
                (thread_id,),
            )
            rows = cur.fetchall()
    summaries: list[dict[str, Any]] = []
    for memory_entry_id, run_id, version, summary, content, metadata in rows:
        summaries.append(
            {
                "memory_entry_id": memory_entry_id,
                "run_id": run_id,
                "version": version,
                "summary": summary,
                "content": content,
                "metadata": metadata,
            }
        )
    return summaries


@dataclass
class _HarnessState:
    work_root: Path
    requests: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_request(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.requests.append(payload)
        timestamp = int(time.time() * 1000)
        path = self.work_root / "debug" / f"{timestamp}_request.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def latest_request_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        with self._lock:
            for payload in reversed(self.requests):
                if str(payload.get("agent", {}).get("agent_id")) == agent_id:
                    return payload
        return None


class _HarnessServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, *, state: _HarnessState):
        super().__init__(server_address, handler_class)
        self.state = state


class _HarnessHandler(BaseHTTPRequestHandler):
    server: _HarnessServer

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.server.state.record_request(payload)
        body = json.dumps(
            {
                "stop_reason": "completed",
                "message": "Compaction live test complete.",
                "summary": "Compaction live test complete.",
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


@dataclass
class _LiveCompactionSystem:
    gateway_url: str
    temp_root: Path
    env: dict[str, str]
    prompt_dump_path: Path


@pytest.fixture(scope="module")
def live_compaction_system(tmp_path_factory: pytest.TempPathFactory):
    temp_root = tmp_path_factory.mktemp("agent-compaction-live")
    prompt_dump_path = temp_root / "agent-runtime-prompts.jsonl"
    env = os.environ.copy()
    env.update(
        {
            "AUTH_MODE": "none",
            "ENABLE_KAFKA_WAKEUPS": "false",
            "AGENT_RUNTIME_DEBUG_PROMPTS": "1",
            "AGENT_RUNTIME_DEBUG_PROMPTS_FILE": str(prompt_dump_path),
            "AGENT_RUNTIME_DEBUG_PROMPTS_MAX_BYTES": str(2 * 1024 * 1024),
            "AGENT_RUNTIME_DEBUG_PROMPTS_BACKUP_COUNT": "2",
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

    try:
        yield _LiveCompactionSystem(
            gateway_url=_GATEWAY_URL,
            temp_root=temp_root,
            env=env,
            prompt_dump_path=prompt_dump_path,
        )
    finally:
        subprocess.run(
            ["./open-talon", "stop"],
            cwd=_ROOT_DIR,
            env=env,
            check=False,
        )
        shutil.rmtree(temp_root, ignore_errors=True)


def test_agent_runtime_compacts_context_and_persists_summary_on_live_system(
    live_compaction_system: _LiveCompactionSystem,
):
    admin_user_id = str(uuid4())
    admin_actor = _actor_payload(
        user_id=admin_user_id,
        display_name="Live Compaction Test Admin",
    )
    test_suffix = uuid4().hex[:8]
    org_slug = f"compaction-live-{test_suffix}"
    work_root = live_compaction_system.temp_root / "work" / org_slug
    work_root.mkdir(parents=True, exist_ok=True)
    state = _HarnessState(work_root=work_root)
    server = _HarnessServer(("127.0.0.1", 0), _HarnessHandler, state=state)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    harness_base = f"http://127.0.0.1:{server.server_address[1]}"
    organization_id: str | None = None
    workspace_id: str | None = None
    thread_id: str | None = None
    workspace_actor: dict[str, Any] | None = None
    workspace_manager_actor: dict[str, Any] | None = None
    agent_id: str | None = None

    try:
        with httpx.Client(
            base_url=live_compaction_system.gateway_url,
            timeout=60.0,
        ) as client:
            organization = _json_request(
                client,
                "POST",
                "/v1/organizations",
                json_body={
                    "actor": admin_actor,
                    "slug": org_slug,
                    "name": f"Compaction Live Test {test_suffix}",
                    "description": "Real system test organization for compaction policies.",
                    "metadata": {"system_test": True},
                },
            )
            organization_id = str(organization["organization_id"])

            workspace_detail = _json_request(
                client,
                "POST",
                f"/v1/organizations/{organization_id}/workspaces",
                json_body={
                    "name": f"Compaction Workspace {test_suffix}",
                    "description": "Real system test workspace for compaction policies.",
                    "actor": admin_actor,
                    "metadata": {"system_test": True},
                },
            )
            workspace_id = str(workspace_detail["workspace"]["workspace_id"])
            workspace_actor = _workspace_actor_from_participant(
                workspace_detail["participants"][0]
            )
            workspace_manager_actor = {
                **workspace_actor,
                "iam_permissions": list(WORKSPACE_PERMISSION_NAMES),
            }

            agent = _json_request(
                client,
                "POST",
                "/v1/agents",
                json_body={
                    "actor": admin_actor,
                    "display_name": "Compaction Probe Agent",
                    "description": "Captures the runtime prompt after compaction.",
                    "role": "probe agent",
                    "capabilities": ["inspection", "memory"],
                    "endpoint": {
                        "kind": "remote",
                        "url": f"{harness_base}/agent",
                        "provider": "system-test-harness",
                    },
                    "system_prompt": "Reply briefly after inspecting the compacted prompt.",
                    "harness": {
                        "version": 1,
                        "summary": "Exercise summary-plus-retrieval compaction in the live runtime.",
                        "compaction_policy": {
                            "enabled": True,
                            "strategy": "summary_plus_retrieval",
                            "overflow_behavior": "auto_fallback",
                            "max_estimated_input_tokens": 12000,
                            "recent_message_count": 2,
                            "min_recent_message_count": 1,
                            "max_run_memory_entries": 1,
                            "max_thread_memory_entries": 1,
                            "max_workspace_memory_entries": 1,
                            "summary_max_chars": 2000,
                            "retrieval_limit": 1,
                            "retrieval_provider_key": "postgres",
                        },
                    },
                    "metadata": {"system_test": True},
                },
            )
            agent_id = str(agent["agent_id"])

            attached = _json_request(
                    client,
                    "POST",
                    f"/v1/workspaces/{workspace_id}/agents",
                    json_body={
                        "actor": workspace_manager_actor,
                        "agent_id": agent_id,
                    },
                )
            assert attached["display_name"] == "Compaction Probe Agent"

            thread_detail = _json_request(
                client,
                "POST",
                f"/v1/workspaces/{workspace_id}/threads",
                json_body={
                    "title": "Compaction Live Test",
                    "actor": workspace_manager_actor,
                },
            )
            thread_id = str(thread_detail["thread"]["thread_id"])

            retrieval_query = "Reply as Compaction Probe Agent\n\nNeed migration compaction proof."

            _json_request(
                client,
                "POST",
                f"/v1/threads/{thread_id}/memory",
                json_body={
                    "actor": workspace_manager_actor,
                    "entry_type": "decision",
                    "summary": "Compaction retrieval hit",
                    "content": retrieval_query,
                    "visibility": "workspace",
                },
            )
            _json_request(
                client,
                "POST",
                f"/v1/threads/{thread_id}/memory",
                json_body={
                    "actor": workspace_manager_actor,
                    "entry_type": "decision",
                    "summary": "Most recent retained thread note",
                    "content": "This newer thread memory entry should survive normal retention.",
                    "visibility": "workspace",
                },
            )
            _json_request(
                client,
                "POST",
                f"/v1/workspaces/{workspace_id}/memory",
                json_body={
                    "actor": workspace_manager_actor,
                    "entry_type": "decision",
                    "summary": "Workspace retrieval decoy",
                    "content": retrieval_query,
                    "visibility": "workspace",
                },
            )

            for content in (
                "Earlier migration note 1",
                "Earlier migration note 2",
                "Earlier migration note 3",
                "Most recent retained note",
            ):
                _json_request(
                    client,
                    "POST",
                    f"/v1/threads/{thread_id}/messages",
                    json_body={
                        "actor": workspace_manager_actor,
                        "content": content,
                        "visibility": "workspace",
                        "create_task": False,
                        "metadata": {"system_test": True},
                    },
                )

            _json_request(
                client,
                "POST",
                f"/v1/threads/{thread_id}/messages",
                json_body={
                    "actor": workspace_manager_actor,
                    "content": "Need migration compaction proof.",
                    "visibility": "workspace",
                    "target_system_agent_id": agent_id,
                    "metadata": {"system_test": True},
                },
            )

            request_payload = _wait_for(
                "compaction probe request",
                lambda: state.latest_request_for_agent(agent_id),
                timeout_seconds=120.0,
                interval_seconds=1.0,
            )

            compacted_context = request_payload["context"]
            compacted_messages = compacted_context["messages"]
            compaction_metadata = compacted_context["system_agent"]["metadata"][
                "_runtime_compaction"
            ]
            assert [message["content"] for message in compacted_messages] == [
                "Most recent retained note",
                "Need migration compaction proof.",
            ]
            assert compaction_metadata["assigned_strategy"] == "summary_plus_retrieval"
            assert compaction_metadata["strategy"] == "summary_plus_retrieval"
            assert compaction_metadata["fallback_stage"] == "assigned"
            assert compaction_metadata["source_message_count"] == 3
            assert compaction_metadata["source_run_memory_count"] == 0
            assert compaction_metadata["covered_sequence_end"] < compacted_messages[0]["sequence"]
            assert compaction_metadata["estimated_tokens_before"] > 0
            assert compaction_metadata["estimated_tokens_after"] > 0
            assert compaction_metadata["estimated_tokens_after"] <= 12000
            summary_entry = next(
                entry
                for entry in compacted_context["run_memory"]
                if entry["entry_type"] == "context_compaction_summary"
            )
            assert "Compacted older visible context." in summary_entry["content"]
            assert "Earlier migration note 1" in summary_entry["content"]
            assert "Most recent retained note" not in summary_entry["content"]
            assert summary_entry["metadata"]["strategy"] == "summary_plus_retrieval"
            assert (
                summary_entry["metadata"]["covered_sequence_end"]
                == compaction_metadata["covered_sequence_end"]
            )

            retrieved_entry = next(
                entry
                for entry in compacted_context["thread_memory"]
                if entry["summary"] == "Compaction retrieval hit"
            )
            assert retrieved_entry["metadata"]["_compaction_retrieved"] is True
            assert any(
                entry["summary"] == "Most recent retained thread note"
                for entry in compacted_context["thread_memory"]
            )
            assert all(
                not entry["metadata"].get("_compaction_retrieved")
                for entry in compacted_context["workspace_memory"]
            )
            assert "[retrieved]" in request_payload["prompt"]
            assert "Compacted older visible context." in request_payload["prompt"]

            final_message = _wait_for(
                "compaction agent reply",
                lambda: next(
                    (
                        message
                        for message in reversed(
                            _json_request(
                                client,
                                "GET",
                                f"/v1/threads/{thread_id}/timeline",
                            )["messages"]
                        )
                        if "Compaction Probe Agent" in str(message.get("content") or "")
                    ),
                    None,
                ),
                timeout_seconds=120.0,
                interval_seconds=2.0,
            )
            assert "Compaction live test complete." in final_message["content"]

            prompt_record = _wait_for(
                "debug prompt dump record",
                lambda: next(
                    (
                        record
                        for record in reversed(
                            _read_prompt_dump_records(live_compaction_system.prompt_dump_path)
                        )
                        if record.get("source") == "remote-endpoint"
                        and record.get("system_agent_id") == agent_id
                    ),
                    None,
                ),
                timeout_seconds=60.0,
                interval_seconds=1.0,
            )
            assert prompt_record["compaction"]["strategy"] == "summary_plus_retrieval"
            assert prompt_record["compaction"]["fallback_stage"] == "assigned"
            assert (
                prompt_record["compaction"]["estimated_tokens_before"]
                == compaction_metadata["estimated_tokens_before"]
            )
            assert (
                prompt_record["compaction"]["estimated_tokens_after"]
                == compaction_metadata["estimated_tokens_after"]
            )
            assert prompt_record["request"]["prompt"] == request_payload["prompt"]

            summary_rows = _wait_for(
                "persisted compaction summary row",
                lambda: _fetch_compaction_summary_rows(thread_id),
                timeout_seconds=30.0,
                interval_seconds=1.0,
            )
            assert len(summary_rows) == 1
            assert summary_rows[0]["memory_entry_id"] == summary_entry["memory_entry_id"]
            assert summary_rows[0]["version"] >= 1
            assert (
                f"Compacted context through sequence {compaction_metadata['covered_sequence_end']}"
                in str(summary_rows[0]["summary"])
            )
            assert "Compacted older visible context." in str(summary_rows[0]["content"])
            assert summary_rows[0]["metadata"]["strategy"] == "summary_plus_retrieval"
            assert (
                summary_rows[0]["metadata"]["covered_sequence_end"]
                == compaction_metadata["covered_sequence_end"]
            )
            assert summary_rows[0]["metadata"]["retrieved_memory_entry_ids"] == [
                retrieved_entry["memory_entry_id"]
            ]
    finally:
        with httpx.Client(
            base_url=live_compaction_system.gateway_url,
            timeout=30.0,
        ) as client:
            if agent_id is not None:
                try:
                    _json_request(
                        client,
                        "DELETE",
                        f"/v1/agents/{agent_id}",
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
            _cleanup_test_organization(organization_id)
        except Exception:
            pass
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=10.0)
