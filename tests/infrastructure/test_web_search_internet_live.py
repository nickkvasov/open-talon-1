from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from typing import Any

import httpx
import pytest


pytestmark = pytest.mark.integration

_ROOT_DIR = Path(__file__).resolve().parents[2]
_SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "http://127.0.0.1:8082").rstrip("/")
_WEB_SEARCH_MCP_HEALTH_URL = "http://127.0.0.1:8181/health"
_WEB_SEARCH_MCP_URL = "http://127.0.0.1:8181/mcp"


def _require_internet_live() -> None:
    if os.getenv("OPEN_TALON_RUN_WEB_SEARCH_INTERNET_LIVE") != "1":
        pytest.skip(
            "Set OPEN_TALON_RUN_WEB_SEARCH_INTERNET_LIVE=1 to run the live internet "
            "web-search test against the local SearXNG container"
        )


def _wait_for(description: str, predicate, *, timeout_seconds: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(1.0)
    raise AssertionError(f"Timed out waiting for {description}")


def _wait_for_http_ok(url: str, *, description: str) -> None:
    def _healthy() -> bool:
        try:
            return httpx.get(url, timeout=5.0).status_code == 200
        except httpx.HTTPError:
            return False

    _wait_for(description, _healthy)


def _wait_for_searxng() -> None:
    def _healthy() -> bool:
        for path in ("/healthz", "/"):
            try:
                if httpx.get(f"{_SEARXNG_BASE_URL}{path}", timeout=5.0).status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
        return False

    _wait_for("SearXNG container", _healthy)


def _mcp_rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = httpx.post(
        _WEB_SEARCH_MCP_URL,
        json={"jsonrpc": "2.0", "id": "internet-live", "method": method, "params": params or {}},
        timeout=60.0,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise AssertionError(f"web-search MCP {method} failed: {payload['error']}")
    return payload["result"]


@pytest.fixture(scope="module")
def web_search_internet_system():
    _require_internet_live()
    env = os.environ.copy()
    subprocess.run(
        ["./open-talon", "stop"],
        cwd=_ROOT_DIR,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(["./open-talon", "start", "--web-search"], cwd=_ROOT_DIR, env=env, check=True)
    _wait_for_searxng()
    _wait_for_http_ok(_WEB_SEARCH_MCP_HEALTH_URL, description="web-search MCP health")
    try:
        yield
    finally:
        subprocess.run(["./open-talon", "stop"], cwd=_ROOT_DIR, env=env, check=False)


def test_live_web_search_plugin_searches_public_internet(web_search_internet_system):
    result = _mcp_rpc(
        "tools/call",
        {
            "name": "search",
            "arguments": {
                "query": "Example Domain",
                "limit": 5,
                "safe_search": 1,
                "language": "en",
            },
        },
    )

    payload = result["structuredContent"]
    results = payload["results"]
    citations = payload["citations"]

    assert payload["metadata"]["source"] == "searxng"
    assert payload["metadata"]["searxng_base_url"] == _SEARXNG_BASE_URL
    assert len(results) >= 1
    assert len(citations) == len(results)
    assert all(item["url"].startswith(("http://", "https://")) for item in results)
    assert any("example" in item["title"].lower() or "example" in item["url"].lower() for item in results)
