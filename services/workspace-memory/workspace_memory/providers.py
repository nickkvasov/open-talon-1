from __future__ import annotations

from dataclasses import dataclass, field
import inspect
import os
from typing import Any, Protocol
from uuid import UUID

from open_talon_contracts.models import (
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderHealthCheck,
    MemoryProviderHealthReport,
)

from .secrets import (
    SecretResolver,
    build_default_secret_resolver,
    secret_references_from_config,
)


@dataclass
class ProviderSyncResult:
    external_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderSearchHit:
    memory_entry_id: UUID | None = None
    external_id: str | None = None
    score: float | None = None
    relations: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderSearchResult:
    provider: str
    hits: list[ProviderSearchHit] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class CanonicalMemoryStore(Protocol):
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
    ) -> list[MemoryEntry]: ...


class MemoryProvider(Protocol):
    provider_name: str

    async def upsert(
        self,
        definition: MemoryProviderDefinition,
        entry: MemoryEntry,
        *,
        external_id: str | None = None,
    ) -> ProviderSyncResult: ...

    async def delete(
        self,
        definition: MemoryProviderDefinition,
        entry: MemoryEntry,
        *,
        external_id: str | None = None,
    ) -> None: ...

    async def search(
        self,
        definition: MemoryProviderDefinition,
        *,
        scope: str,
        workspace_id: UUID | None,
        thread_id: UUID | None,
        run_id: UUID | None,
        query: str,
        limit: int,
        include_graph: bool = True,
        metadata_filters: dict[str, Any] | None = None,
    ) -> ProviderSearchResult: ...

    async def health_check(
        self,
        definition: MemoryProviderDefinition,
    ) -> MemoryProviderHealthReport: ...


class PostgresMemoryProvider:
    provider_name = "postgres"

    def __init__(self, store: CanonicalMemoryStore) -> None:
        self._store = store

    async def upsert(
        self,
        definition: MemoryProviderDefinition,
        entry: MemoryEntry,
        *,
        external_id: str | None = None,
    ) -> ProviderSyncResult:
        _ = definition
        return ProviderSyncResult(
            external_id=external_id or str(entry.memory_entry_id),
            metadata={"scope": entry.scope},
        )

    async def delete(
        self,
        definition: MemoryProviderDefinition,
        entry: MemoryEntry,
        *,
        external_id: str | None = None,
    ) -> None:
        _ = definition
        _ = entry
        _ = external_id

    async def search(
        self,
        definition: MemoryProviderDefinition,
        *,
        scope: str,
        workspace_id: UUID | None,
        thread_id: UUID | None,
        run_id: UUID | None,
        query: str,
        limit: int,
        include_graph: bool = True,
        metadata_filters: dict[str, Any] | None = None,
    ) -> ProviderSearchResult:
        _ = definition
        _ = include_graph
        _ = metadata_filters
        entries = await self._store.search_memory_entries(
            scope=scope,
            workspace_id=workspace_id,
            thread_id=thread_id,
            run_id=run_id,
            query=query,
            limit=limit,
            state="confirmed" if scope != "run" else "scratch",
        )
        return ProviderSearchResult(
            provider=self.provider_name,
            hits=[
                ProviderSearchHit(
                    memory_entry_id=entry.memory_entry_id,
                    external_id=str(entry.memory_entry_id),
                    metadata={"scope": entry.scope},
                )
                for entry in entries
            ],
        )

    async def health_check(
        self,
        definition: MemoryProviderDefinition,
    ) -> MemoryProviderHealthReport:
        checks = [
            MemoryProviderHealthCheck(
                name="canonical_store",
                status="ok",
                detail="Canonical Postgres memory provider is available through core-collab.",
            )
        ]
        return MemoryProviderHealthReport(
            provider_id=definition.provider_id,
            provider_key=definition.provider_key,
            status="healthy",
            checks=checks,
            metadata={"provider": definition.provider},
        )


class Mem0MemoryProvider:
    provider_name = "mem0"

    def __init__(
        self,
        *,
        secret_resolver: SecretResolver | None = None,
    ) -> None:
        self._secret_resolver = secret_resolver or build_default_secret_resolver()

    async def upsert(
        self,
        definition: MemoryProviderDefinition,
        entry: MemoryEntry,
        *,
        external_id: str | None = None,
    ) -> ProviderSyncResult:
        client = await self._client_for_definition(definition)
        content = entry.summary or entry.content
        owner = _scope_owner(scope=entry.scope, workspace_id=entry.workspace_id, thread_id=entry.thread_id, run_id=entry.run_id)
        metadata = _entry_metadata(entry)
        if external_id:
            try:
                await client.update(external_id, data=content)
                return ProviderSyncResult(external_id=external_id, metadata=metadata)
            except Exception:
                pass
        await client.add(
            messages=[{"role": "user", "content": content}],
            user_id=owner,
            metadata=metadata,
            infer=False,
        )
        resolved_external_id = await self._lookup_external_id(
            client,
            owner=owner,
            memory_entry_id=entry.memory_entry_id,
        )
        return ProviderSyncResult(external_id=resolved_external_id, metadata=metadata)

    async def delete(
        self,
        definition: MemoryProviderDefinition,
        entry: MemoryEntry,
        *,
        external_id: str | None = None,
    ) -> None:
        client = await self._client_for_definition(definition)
        if external_id:
            await client.delete(external_id)
            return
        owner = _scope_owner(scope=entry.scope, workspace_id=entry.workspace_id, thread_id=entry.thread_id, run_id=entry.run_id)
        resolved_external_id = await self._lookup_external_id(
            client,
            owner=owner,
            memory_entry_id=entry.memory_entry_id,
        )
        if resolved_external_id:
            await client.delete(resolved_external_id)

    async def search(
        self,
        definition: MemoryProviderDefinition,
        *,
        scope: str,
        workspace_id: UUID | None,
        thread_id: UUID | None,
        run_id: UUID | None,
        query: str,
        limit: int,
        include_graph: bool = True,
        metadata_filters: dict[str, Any] | None = None,
    ) -> ProviderSearchResult:
        config = await self._resolved_config(definition)
        client = await self._client_for_config(config)
        graph_enabled = bool(config.get("enable_graph", False))
        graph_included = bool(include_graph and graph_enabled)
        payload = await client.search(
            query=query,
            user_id=_scope_owner(
                scope=scope,
                workspace_id=workspace_id,
                thread_id=thread_id,
                run_id=run_id,
            ),
            limit=limit,
            filters=_metadata_filter_payload(metadata_filters),
        )
        results = payload.get("results") if isinstance(payload, dict) else payload
        relations = payload.get("relations") if isinstance(payload, dict) else []
        hits: list[ProviderSearchHit] = []
        for item in results or []:
            if not isinstance(item, dict):
                continue
            metadata = dict(item.get("metadata") or {})
            memory_entry_id = metadata.get("memory_entry_id")
            parsed_memory_entry_id: UUID | None = None
            if isinstance(memory_entry_id, str):
                try:
                    parsed_memory_entry_id = UUID(memory_entry_id)
                except ValueError:
                    parsed_memory_entry_id = None
            hits.append(
                ProviderSearchHit(
                    memory_entry_id=parsed_memory_entry_id,
                    external_id=_result_external_id(item),
                    score=_float_or_none(item.get("score")),
                    relations=(
                        [item for item in relations or [] if isinstance(item, dict)]
                        if graph_included
                        else []
                    ),
                    metadata=metadata,
                )
            )
        return ProviderSearchResult(
            provider=self.provider_name,
            hits=hits,
            metadata={
                "graph_enabled": graph_enabled,
                "graph_included": graph_included,
                **_backend_metadata(config),
            },
        )

    async def health_check(
        self,
        definition: MemoryProviderDefinition,
    ) -> MemoryProviderHealthReport:
        checks: list[MemoryProviderHealthCheck] = []
        config: dict[str, Any] | None = None
        try:
            config = await self._resolved_config(definition)
            backend_metadata = _backend_metadata(config)
            checks.append(
                MemoryProviderHealthCheck(
                    name="config",
                    status="ok",
                    detail="Mem0 configuration loaded successfully.",
                )
            )
            checks.append(
                MemoryProviderHealthCheck(
                    name="vector_store",
                    status="ok",
                    detail=(
                        "Vector store configured as "
                        f"{backend_metadata['vector_store_provider']}."
                    ),
                    metadata={
                        "provider": backend_metadata["vector_store_provider"],
                    },
                )
            )
            if backend_metadata["graph_enabled"]:
                checks.append(
                    MemoryProviderHealthCheck(
                        name="graph_store",
                        status="ok",
                        detail=(
                            "Graph memory enabled with backend "
                            f"{backend_metadata['graph_store_provider']}."
                        ),
                        metadata={
                            "provider": backend_metadata["graph_store_provider"],
                        },
                    )
                )
            else:
                checks.append(
                    MemoryProviderHealthCheck(
                        name="graph_store",
                        status="ok",
                        detail="Graph memory is disabled for this provider.",
                    )
                )
            client = await self._client_for_config(config)
            await client.search(query="health", user_id="open-talon-healthcheck", limit=1)
            checks.append(
                MemoryProviderHealthCheck(
                    name="search",
                    status="ok",
                    detail="Mem0 search probe completed successfully.",
                )
            )
        except ImportError as exc:
            checks.append(
                MemoryProviderHealthCheck(
                    name="import",
                    status="fail",
                    detail=str(exc),
                )
            )
        except Exception as exc:
            checks.append(
                MemoryProviderHealthCheck(
                    name="search",
                    status="fail",
                    detail=f"Mem0 health check failed: {exc}",
                )
            )
        status = (
            "unhealthy"
            if any(check.status == "fail" for check in checks)
            else "degraded"
            if any(check.status == "warn" for check in checks)
            else "healthy"
        )
        return MemoryProviderHealthReport(
            provider_id=definition.provider_id,
            provider_key=definition.provider_key,
            status=status,
            checks=checks,
            metadata={
                "provider": definition.provider,
                **(_backend_metadata(config) if config is not None else {}),
            },
        )

    async def _client_for_definition(self, definition: MemoryProviderDefinition) -> Any:
        config = await self._resolved_config(definition)
        return await self._client_for_config(config)

    async def _client_for_config(self, config: dict[str, Any]) -> Any:
        try:
            from mem0 import AsyncMemory
        except ImportError as exc:  # pragma: no cover - depends on external package
            raise ImportError(
                "Mem0 support requires the 'mem0ai' package to be installed."
            ) from exc
        factory = getattr(AsyncMemory, "from_config", None)
        if callable(factory):
            client = factory(config)
            if inspect.isawaitable(client):
                client = await client
            return client
        return AsyncMemory(config=config)

    async def _resolved_config(
        self,
        definition: MemoryProviderDefinition,
    ) -> dict[str, Any]:
        config = dict(definition.config)
        vector_store = dict(config.get("vector_store") or {})
        vector_store.setdefault("provider", "pgvector")
        vector_store_config = dict(vector_store.get("config") or {})
        vector_store_config.setdefault("host", os.getenv("POSTGRES_HOST", "localhost"))
        vector_store_config.setdefault("port", int(os.getenv("POSTGRES_PORT", "5432")))
        vector_store_config.setdefault("user", os.getenv("POSTGRES_USER", "admin"))
        vector_store_config.setdefault("password", os.getenv("POSTGRES_PASSWORD", "password"))
        vector_store_config.setdefault("dbname", os.getenv("POSTGRES_DB", "app_db"))
        vector_store_config.setdefault(
            "collection_name",
            os.getenv("OPEN_TALON_MEM0_COLLECTION", "open_talon_memories"),
        )
        vector_store["config"] = vector_store_config
        config["vector_store"] = vector_store

        if config.get("enable_graph"):
            graph_store = dict(config.get("graph_store") or {})
            graph_store.setdefault("provider", "memgraph")
            graph_config = dict(graph_store.get("config") or {})
            graph_config.setdefault("url", os.getenv("OPEN_TALON_MEMGRAPH_URL", "bolt://localhost:7688"))
            graph_config.setdefault("username", os.getenv("OPEN_TALON_MEMGRAPH_USER", "memgraph"))
            graph_config.setdefault("password", os.getenv("OPEN_TALON_MEMGRAPH_PASSWORD", "memgraph"))
            graph_store["config"] = graph_config
            config["graph_store"] = graph_store

        secret = await self._secret_resolver.resolve(
            secret_references_from_config(definition.secret_config),
            label=f"memory provider {definition.provider_key} secret",
            required=False,
        )
        if secret:
            for block_name in ("llm", "embedder"):
                block = dict(config.get(block_name) or {})
                if not block:
                    continue
                block_config = dict(block.get("config") or {})
                block_config.setdefault("api_key", secret)
                block["config"] = block_config
                config[block_name] = block
        return config

    async def _lookup_external_id(
        self,
        client: Any,
        *,
        owner: str,
        memory_entry_id: UUID,
    ) -> str | None:
        payload = await client.get_all(
            user_id=owner,
            filters={
                "AND": [
                    {"metadata": {"memory_entry_id": str(memory_entry_id)}},
                ]
            },
            limit=5,
        )
        results = payload.get("results") if isinstance(payload, dict) else payload
        for item in results or []:
            if not isinstance(item, dict):
                continue
            external_id = _result_external_id(item)
            if external_id:
                return external_id
        return None


def build_provider_index(
    *,
    store: CanonicalMemoryStore,
    secret_resolver: SecretResolver | None = None,
) -> dict[str, MemoryProvider]:
    return {
        "postgres": PostgresMemoryProvider(store),
        "mem0": Mem0MemoryProvider(secret_resolver=secret_resolver),
    }


def _entry_metadata(entry: MemoryEntry) -> dict[str, Any]:
    return {
        **dict(entry.metadata),
        "memory_entry_id": str(entry.memory_entry_id),
        "scope": entry.scope,
        "state": entry.state,
        "workspace_id": str(entry.workspace_id),
        "thread_id": str(entry.thread_id) if entry.thread_id else None,
        "run_id": str(entry.run_id) if entry.run_id else None,
        "visibility": entry.visibility,
        "created_by": str(entry.created_by),
        "updated_by": str(entry.updated_by),
    }


def _scope_owner(
    *,
    scope: str,
    workspace_id: UUID | None,
    thread_id: UUID | None,
    run_id: UUID | None,
) -> str:
    if scope == "workspace" and workspace_id is not None:
        return f"workspace:{workspace_id}"
    if scope == "thread" and thread_id is not None:
        return f"thread:{thread_id}"
    if scope == "run" and run_id is not None:
        return f"run:{run_id}"
    raise ValueError(f"Unable to derive Mem0 scope owner for scope={scope!r}")


def _metadata_filter_payload(filters: dict[str, Any] | None) -> dict[str, Any] | None:
    if not filters:
        return None
    return {"AND": [{"metadata": dict(filters)}]}


def _result_external_id(item: dict[str, Any]) -> str | None:
    for key in ("id", "memory_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _backend_metadata(config: dict[str, Any]) -> dict[str, Any]:
    vector_store = dict(config.get("vector_store") or {})
    graph_store = dict(config.get("graph_store") or {})
    graph_enabled = bool(config.get("enable_graph", False))
    return {
        "graph_enabled": graph_enabled,
        "vector_store_provider": vector_store.get("provider"),
        "graph_store_provider": graph_store.get("provider") if graph_enabled else None,
    }
