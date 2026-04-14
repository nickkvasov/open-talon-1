from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest

_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_WORKSPACE_MEMORY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/workspace-memory")
)
for path in (_CONTRACTS_DIR, _WORKSPACE_MEMORY_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_contracts.models import MemoryProviderDefinition  # noqa: E402
from workspace_memory.providers import Mem0MemoryProvider  # noqa: E402


def _provider_definition(*, config: dict | None = None) -> MemoryProviderDefinition:
    now = datetime.now(timezone.utc)
    actor_id = uuid4()
    return MemoryProviderDefinition(
        provider_id=uuid4(),
        provider_key="mem0",
        display_name="Mem0",
        description="Semantic memory provider",
        provider="mem0",
        enabled=True,
        config=config or {},
        secret_config={},
        created_by=actor_id,
        created_at=now,
        updated_by=actor_id,
        updated_at=now,
        metadata={},
    )


@pytest.mark.asyncio
async def test_mem0_provider_defaults_to_pgvector_without_graph(monkeypatch):
    monkeypatch.delenv("OPEN_TALON_MEM0_ENABLE_GRAPH", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "db.local")
    monkeypatch.setenv("POSTGRES_PORT", "5544")
    monkeypatch.setenv("POSTGRES_USER", "vector_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "vector_pass")
    monkeypatch.setenv("POSTGRES_DB", "vector_db")
    monkeypatch.setenv("OPEN_TALON_MEM0_COLLECTION", "test_memories")

    provider = Mem0MemoryProvider()
    config = await provider._resolved_config(_provider_definition())  # noqa: SLF001

    assert config.get("enable_graph", False) is False
    assert "graph_store" not in config
    assert config["vector_store"]["provider"] == "pgvector"
    assert config["vector_store"]["config"] == {
        "host": "db.local",
        "port": 5544,
        "user": "vector_user",
        "password": "vector_pass",
        "dbname": "vector_db",
        "collection_name": "test_memories",
    }


@pytest.mark.asyncio
async def test_mem0_provider_can_enable_graph_from_env(monkeypatch):
    monkeypatch.setenv("OPEN_TALON_MEM0_ENABLE_GRAPH", "true")
    monkeypatch.setenv("OPEN_TALON_MEMGRAPH_URL", "bolt://localhost:7688")
    monkeypatch.setenv("OPEN_TALON_MEMGRAPH_USER", "memgraph")
    monkeypatch.setenv("OPEN_TALON_MEMGRAPH_PASSWORD", "topsecret")

    provider = Mem0MemoryProvider()
    config = await provider._resolved_config(  # noqa: SLF001
        _provider_definition(config={"enable_graph": False})
    )

    assert config["enable_graph"] is True
    assert config["graph_store"]["provider"] == "memgraph"
    assert config["graph_store"]["config"] == {
        "url": "bolt://localhost:7688",
        "username": "memgraph",
        "password": "topsecret",
    }
