from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "infrastructure" / "docker-compose.yaml"
ENV_EXAMPLE = ROOT / "infrastructure" / ".env.example"
SEARXNG_SETTINGS = ROOT / "infrastructure" / "searxng" / "settings.yml"
LAUNCHER = ROOT / "open-talon"


def test_web_search_local_config_uses_optional_searxng_container():
    compose = COMPOSE_FILE.read_text()
    env_example = ENV_EXAMPLE.read_text()
    settings = SEARXNG_SETTINGS.read_text()
    launcher = LAUNCHER.read_text()

    assert "searxng:" in compose
    assert "image: searxng/searxng:latest" in compose
    assert "container_name: searxng" in compose
    assert "- web-search" in compose
    assert '${SEARXNG_PORT:-8082}:8080' in compose
    assert "- ./searxng:/etc/searxng:ro" in compose
    assert "SEARXNG_BASE_URL: ${SEARXNG_PUBLIC_URL:-http://127.0.0.1:8082/}" in compose
    assert "http://127.0.0.1:8080/healthz" in compose

    assert "SEARXNG_PORT=8082" in env_example
    assert "SEARXNG_BASE_URL=http://127.0.0.1:8082" in env_example
    assert "SEARXNG_PUBLIC_URL=http://127.0.0.1:8082/" in env_example
    assert "OPEN_TALON_WEB_SEARCH_MCP_URL=http://127.0.0.1:8181/mcp" in env_example
    assert "WEB_SEARCH_MCP_PORT=8181" in env_example

    assert "formats:" in settings
    assert "- json" in settings
    assert "limiter: false" in settings

    assert "./open-talon start [--memgraph] [--web-search]" in launcher
    assert "--web-search)" in launcher
    assert "enable_web_search=1" in launcher
    assert "services+=(searxng)" in launcher
    assert "searxng_ready()" in launcher
    assert "OPEN_TALON_SEARXNG_STARTUP_WAIT_SECONDS" in launcher
    assert '"web_search_mcp.main" \\' in launcher
    assert "docker compose --profile mem0-graph --profile web-search down" in launcher
