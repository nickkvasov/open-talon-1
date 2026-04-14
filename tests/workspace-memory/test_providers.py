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

from open_talon_contracts.models import MemoryEntry, MemoryProviderDefinition  # noqa: E402
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


def _memory_entry() -> MemoryEntry:
    now = datetime.now(timezone.utc)
    actor_id = uuid4()
    return MemoryEntry(
        memory_entry_id=uuid4(),
        scope="thread",
        state="confirmed",
        workspace_id=uuid4(),
        thread_id=uuid4(),
        entry_type="decision",
        content="Core-collab remains canonical.",
        summary="Canonical ownership",
        created_by=actor_id,
        updated_by=actor_id,
        visibility="workspace",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_mem0_provider_defaults_to_pgvector_without_graph(monkeypatch):
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
async def test_mem0_provider_can_enable_graph_from_definition_config(monkeypatch):
    monkeypatch.setenv("OPEN_TALON_MEMGRAPH_URL", "bolt://localhost:7688")
    monkeypatch.setenv("OPEN_TALON_MEMGRAPH_USER", "memgraph")
    monkeypatch.setenv("OPEN_TALON_MEMGRAPH_PASSWORD", "topsecret")

    provider = Mem0MemoryProvider()
    config = await provider._resolved_config(  # noqa: SLF001
        _provider_definition(config={"enable_graph": True})
    )

    assert config["enable_graph"] is True
    assert config["graph_store"]["provider"] == "memgraph"
    assert config["graph_store"]["config"] == {
        "url": "bolt://localhost:7688",
        "username": "memgraph",
        "password": "topsecret",
    }


@pytest.mark.asyncio
async def test_mem0_provider_ignores_legacy_graph_env_toggle(monkeypatch):
    monkeypatch.setenv("OPEN_TALON_MEM0_ENABLE_GRAPH", "true")
    monkeypatch.setenv("OPEN_TALON_MEMGRAPH_URL", "bolt://localhost:7688")

    provider = Mem0MemoryProvider()
    config = await provider._resolved_config(  # noqa: SLF001
        _provider_definition(config={"enable_graph": False})
    )

    assert config.get("enable_graph", False) is False
    assert "graph_store" not in config


@pytest.mark.asyncio
async def test_mem0_search_omits_relations_when_graph_not_requested(monkeypatch):
    class FakeClient:
        async def search(self, **kwargs):
            _ = kwargs
            return {
                "results": [
                    {
                        "id": "mem-1",
                        "score": 0.91,
                        "metadata": {"memory_entry_id": str(entry.memory_entry_id)},
                    }
                ],
                "relations": [
                    {"source": "A", "relation": "depends_on", "target": "B"},
                ],
            }

    entry = _memory_entry()
    provider = Mem0MemoryProvider()

    async def fake_client_for_config(config):
        _ = config
        return FakeClient()

    monkeypatch.setattr(provider, "_client_for_config", fake_client_for_config)
    result = await provider.search(
        _provider_definition(
            config={
                "enable_graph": True,
                "graph_store": {"provider": "memgraph", "config": {}},
            }
        ),
        scope="thread",
        workspace_id=entry.workspace_id,
        thread_id=entry.thread_id,
        run_id=None,
        query="canonical",
        limit=5,
        include_graph=False,
    )

    assert result.metadata["graph_enabled"] is True
    assert result.metadata["graph_included"] is False
    assert result.metadata["graph_store_provider"] == "memgraph"
    assert len(result.hits) == 1
    assert result.hits[0].relations == []


@pytest.mark.asyncio
async def test_mem0_health_report_surfaces_memgraph_backend(monkeypatch):
    class FakeClient:
        async def search(self, **kwargs):
            _ = kwargs
            return {"results": [], "relations": []}

    provider = Mem0MemoryProvider()

    async def fake_client_for_config(config):
        _ = config
        return FakeClient()

    monkeypatch.setattr(provider, "_client_for_config", fake_client_for_config)
    report = await provider.health_check(
        _provider_definition(
            config={
                "enable_graph": True,
                "vector_store": {"provider": "pgvector", "config": {}},
                "graph_store": {"provider": "memgraph", "config": {}},
            }
        )
    )

    assert report.status == "healthy"
    assert report.metadata["graph_enabled"] is True
    assert report.metadata["vector_store_provider"] == "pgvector"
    assert report.metadata["graph_store_provider"] == "memgraph"
    checks = {check.name: check for check in report.checks}
    assert checks["vector_store"].status == "ok"
    assert checks["graph_store"].status == "ok"
    assert "memgraph" in checks["graph_store"].detail.lower()
