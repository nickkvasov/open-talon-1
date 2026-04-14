from __future__ import annotations

from uuid import UUID

from gateway_edge.models import (
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderHealthReport,
)
from workspace_memory import Mem0MemoryProvider, PostgresMemoryProvider


class _NullStore:
    async def search_memory_entries(
        self,
        *,
        scope: str,
        workspace_id: UUID | None = None,
        thread_id: UUID | None = None,
        run_id: UUID | None = None,
        query: str,
        limit: int,
        state: str | None = None,
    ) -> list[MemoryEntry]:
        _ = scope
        _ = workspace_id
        _ = thread_id
        _ = run_id
        _ = query
        _ = limit
        _ = state
        return []


async def check_memory_provider_health(
    provider: MemoryProviderDefinition,
) -> MemoryProviderHealthReport:
    if provider.provider == "postgres":
        return await PostgresMemoryProvider(_NullStore()).health_check(provider)
    if provider.provider == "mem0":
        return await Mem0MemoryProvider().health_check(provider)
    raise ValueError(f"Unsupported memory provider {provider.provider!r}")
