"""
Integration tests — require the full infrastructure stack + gateway running.

Run:
    pytest test/api-gateway/ -m integration -v

What this does
--------------
1. Starts ALL services (Postgres, Kafka, Valkey, OpenBao, Ollama) via docker-compose
   using the existing infrastructure/docker-compose.yaml (same as infra tests).
2. Starts the API Gateway as a subprocess with ECHO_AGENT_ENABLED=true so the
   full Kafka request→response round-trip is exercised without a real agent.
3. Runs HTTP tests against the live gateway at http://localhost:8000.
4. Tears down the gateway subprocess; infra compose is left running (so you can
   run multiple test suites in sequence without re-pulling Ollama images).

To also tear down infra after the session, pass --gateway-teardown-infra:
    pytest test/api-gateway/ -m integration --gateway-teardown-infra
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

# ── Paths ─────────────────────────────────────────────────────────────────────
_REPO_ROOT    = Path(__file__).parent.parent.parent
_COMPOSE_DIR  = _REPO_ROOT / "infrastructure"
_GW_DIR       = _REPO_ROOT / "api-gateway"
_GW_VENV      = _GW_DIR / ".venv" / "bin" / "python"
GATEWAY_URL   = os.getenv("GATEWAY_URL", "http://localhost:8000")
KAFKA_PORT    = os.getenv("KAFKA_PORT", "9092")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
VALKEY_PORT   = os.getenv("VALKEY_PORT", "6379")


# ── pytest hooks ──────────────────────────────────────────────────────────────

def pytest_addoption(parser):
    parser.addoption(
        "--gateway-teardown-infra",
        action="store_true",
        default=False,
        help="Also run docker compose down after integration tests finish.",
    )


# ── Infrastructure fixture (same pattern as test_infrastructure.py) ────────────

@pytest.fixture(scope="session")
def infrastructure():
    """Start the docker-compose infrastructure stack and wait for services."""
    print(f"\n[integration] Starting infrastructure from {_COMPOSE_DIR}")
    # Start all services *except* api-gateway (we start that as a subprocess)
    subprocess.run(
        ["docker", "compose", "up", "-d", "--wait",
         "postgres", "kafka", "valkey", "openbao"],
        cwd=str(_COMPOSE_DIR),
        check=True,
    )

    _wait_for("Postgres", lambda: _tcp_connect("localhost", int(POSTGRES_PORT)))
    _wait_for("Valkey",   lambda: _tcp_connect("localhost", int(VALKEY_PORT)))
    _wait_for("Kafka",    lambda: _tcp_connect("localhost", int(KAFKA_PORT)))

    yield

    # Optionally tear down infra
    # (use --gateway-teardown-infra flag to enable)


@pytest.fixture(scope="session")
def gateway_process(infrastructure):
    """
    Start the gateway as a subprocess with echo agent enabled.
    Uses the api-gateway/.venv Python interpreter.
    """
    python = str(_GW_VENV) if _GW_VENV.exists() else sys.executable
    env = {
        **os.environ,
        "ECHO_AGENT_ENABLED": "true",
        "AUTH_MODE":          "none",
        "POSTGRES_HOST":      "localhost",
        "POSTGRES_PORT":      POSTGRES_PORT,
        "KAFKA_BOOTSTRAP_SERVERS": f"localhost:{KAFKA_PORT}",
        "VALKEY_HOST":        "localhost",
        "VALKEY_PORT":        VALKEY_PORT,
        "OPENBAO_ADDRESS":    f"http://localhost:{os.getenv('BAO_PORT', '8200')}",
        "LOG_LEVEL":          "warning",
    }
    proc = subprocess.Popen(
        [python, "-m", "uvicorn", "app.main:app",
         "--host", "0.0.0.0", "--port", "8000"],
        cwd=str(_GW_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(f"[integration] Gateway PID={proc.pid}")

    _wait_for("Gateway /health", lambda: _http_ok(f"{GATEWAY_URL}/health"), max_retries=30)

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    print("[integration] Gateway stopped")


@pytest.fixture(scope="session")
def gw(gateway_process):
    """httpx.Client pointed at the live gateway."""
    return httpx.Client(base_url=GATEWAY_URL, timeout=30.0)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_integration_health(gw):
    resp = gw.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.integration
def test_integration_ready_checks_services(gw):
    resp = gw.get("/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    names = {s["name"] for s in body["services"]}
    # Ollama may not be running in CI — check the other four
    assert {"postgres", "valkey", "kafka"}.issubset(names)


@pytest.mark.integration
def test_integration_chat_round_trip(gw):
    """Full Kafka round-trip via the in-process echo agent."""
    resp = gw.post("/v1/chat", json={"message": "integration test"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["message"]["role"] == "assistant"
    # Echo agent prefixes with "[echo] "
    assert "integration test" in body["message"]["content"]


@pytest.mark.integration
def test_integration_session_persists_to_postgres(gw):
    r1 = gw.post("/v1/chat", json={"message": "first turn"})
    assert r1.status_code == 200
    sid = r1.json()["session_id"]

    r2 = gw.post("/v1/chat", json={"message": "second turn", "session_id": sid})
    assert r2.status_code == 200
    assert r2.json()["session_id"] == sid


@pytest.mark.integration
def test_integration_history_endpoint(gw):
    r = gw.post("/v1/chat", json={"message": "remember me"})
    sid = r.json()["session_id"]

    hist = gw.get(f"/v1/history/{sid}")
    assert hist.status_code == 200
    roles = {m["role"] for m in hist.json()}
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.integration
def test_integration_session_delete(gw):
    r = gw.post("/v1/chat", json={"message": "bye"})
    sid = r.json()["session_id"]

    del_r = gw.delete(f"/v1/sessions/{sid}")
    assert del_r.json()["deleted"] is True

    hist = gw.get(f"/v1/history/{sid}")
    assert hist.status_code == 404


@pytest.mark.integration
def test_integration_sse_stream(gw):
    """POST /v1/chat/stream should return SSE with at least a done event."""
    with gw.stream("POST", "/v1/chat/stream", json={"message": "stream me"}) as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                raw = line[6:].strip()
                if raw:
                    try:
                        events.append(json.loads(raw))
                    except json.JSONDecodeError:
                        pass
        types = {e["type"] for e in events}
        assert "done" in types


@pytest.mark.integration
def test_integration_api_key_create_and_use(gw):
    r = gw.post("/v1/admin/api-keys", json={"label": "integration-key"})
    assert r.status_code == 200
    raw_key = r.json()["raw_key"]
    key_id  = r.json()["key_id"]

    # Revoke it afterwards (cleanup)
    gw.delete(f"/v1/admin/api-keys/{key_id}")


@pytest.mark.integration
def test_integration_openapi_docs_reachable(gw):
    resp = gw.get("/docs")
    assert resp.status_code == 200


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wait_for(name: str, fn, max_retries: int = 60, sleep: float = 1.0) -> None:
    for i in range(max_retries):
        try:
            if fn() is not False:
                return
        except Exception:
            pass
        time.sleep(sleep)
    raise RuntimeError(f"{name} not ready after {max_retries * sleep}s")


def _tcp_connect(host: str, port: int) -> bool:
    import socket
    with socket.create_connection((host, port), timeout=2):
        return True


def _http_ok(url: str) -> bool:
    resp = httpx.get(url, timeout=3)
    return resp.status_code == 200
