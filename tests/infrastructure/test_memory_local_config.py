from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "infrastructure" / "docker-compose.yaml"
ENV_EXAMPLE = ROOT / "infrastructure" / ".env.example"
LAUNCHER = ROOT / "open-talon"


def test_mem0_graph_local_config_uses_optional_memgraph_service():
    compose = COMPOSE_FILE.read_text()
    env_example = ENV_EXAMPLE.read_text()
    launcher = LAUNCHER.read_text()

    assert "memgraph:" in compose
    assert "image: memgraph/memgraph:latest" in compose
    assert "- mem0-graph" in compose
    assert '${MEMGRAPH_BOLT_PORT:-7688}:7687' in compose
    assert '${MEMGRAPH_HTTP_PORT:-7444}:7444' in compose
    assert "OPEN_TALON_MEMGRAPH_URL=bolt://localhost:7688" in env_example
    assert "OPEN_TALON_MEM0_COLLECTION=open_talon_memories" in env_example
    assert "Usage:" in launcher
    assert "./open-talon start [--memgraph]" in launcher
    assert 'case "$1" in' in launcher
    assert "--memgraph)" in launcher
    assert "enable_memgraph=1" in launcher
    assert "if ((enable_memgraph)); then" in launcher
    assert "services+=(memgraph)" in launcher
