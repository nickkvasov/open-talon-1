from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
import json
import logging
from datetime import UTC
from pathlib import Path
import sys
from typing import Any, Protocol
from uuid import UUID

import httpx
from aiokafka import AIOKafkaConsumer

_ROOT_DIR = Path(__file__).resolve().parents[4]
_CORE_COLLAB_DIR = _ROOT_DIR / "services" / "core-collab"
if _CORE_COLLAB_DIR.is_dir():
    collab_path = str(_CORE_COLLAB_DIR)
    if collab_path not in sys.path:
        sys.path.insert(0, collab_path)

from core_collab import CollaborationKernel, CollaborationRepository

from gateway_edge.db.postgres import get_pool
from gateway_edge.models import (
    AuditChainVerificationResult,
    AuditEvent,
    AuditEventDraft,
    AuditEventPage,
    AuditExportRequest,
)
from gateway_edge.services.events import event_service
from gateway_edge.services.object_storage import MinioObjectStorage, StoredObject

logger = logging.getLogger(__name__)


class AuditLedger(Protocol):
    async def setup(self) -> None: ...

    async def record_event(self, draft: AuditEventDraft) -> None: ...

    async def list_events(self, payload: AuditExportRequest) -> AuditEventPage: ...

    async def get_event(self, audit_event_id: UUID) -> AuditEvent | None: ...

    async def verify_chain(self, chain_partition: str) -> AuditChainVerificationResult: ...

    async def resolve_workspace_organization(self, workspace_id: UUID) -> UUID | None: ...

    async def resolve_thread_scope(self, thread_id: UUID) -> tuple[UUID | None, UUID | None]: ...

    async def list_pending_export_events(
        self,
        *,
        consumer_name: str,
        limit: int,
    ) -> list[AuditEvent]: ...

    async def advance_export_checkpoint(
        self,
        *,
        consumer_name: str,
        last_ledger_offset: int,
        metadata: dict[str, Any],
    ) -> None: ...

    async def list_retention_candidates(
        self,
        *,
        cutoff_recorded_at,
    ) -> list[dict[str, Any]]: ...

    async def list_events_for_retention(
        self,
        *,
        chain_partition: str,
        cutoff_recorded_at,
        limit: int,
    ) -> list[AuditEvent]: ...

    async def record_retention_snapshot(
        self,
        *,
        chain_partition: str,
        cutoff_recorded_at,
        last_pruned_sequence: int,
        last_pruned_event_hash: str,
        object_key: str,
        metadata: dict[str, Any],
    ) -> None: ...

    async def prune_events(
        self,
        *,
        chain_partition: str,
        max_ledger_offset: int,
    ) -> None: ...

    async def list_chain_heads(self) -> list[dict[str, Any]]: ...


class AuditRelayProvider(Protocol):
    provider_name: str
    consumer_name: str | None

    async def publish_events(self, events: list[AuditEvent]) -> None: ...

    def supports_subscription(self) -> bool: ...

    def subscribe(self) -> AsyncIterator[AuditEvent]: ...


class AuditProjectionProvider(Protocol):
    provider_name: str
    consumer_name: str | None

    def enabled(self) -> bool: ...

    async def ensure_ready(self) -> None: ...

    async def project_events(self, events: list[AuditEvent]) -> None: ...


class AuditArchiveProvider(Protocol):
    provider_name: str

    def enabled(self) -> bool: ...

    async def put_object(
        self,
        *,
        object_key: str,
        payload: bytes,
        content_type: str | None = None,
    ) -> StoredObject: ...

    def presign_get(self, *, object_key: str, expires_seconds: int) -> str | None: ...


@dataclass(frozen=True)
class AuditProviderRegistry:
    ledger: AuditLedger
    relay: AuditRelayProvider
    projection: AuditProjectionProvider
    archive: AuditArchiveProvider


class PostgresAuditLedger:
    def __init__(self, pool) -> None:
        self._pool = pool
        self._repository = CollaborationRepository(pool)
        self._kernel = CollaborationKernel(self._repository)

    async def setup(self) -> None:
        await self._kernel.setup_schema()

    async def record_event(self, draft: AuditEventDraft) -> None:
        await self._kernel.record_audit_event(draft)

    async def list_events(self, payload: AuditExportRequest) -> AuditEventPage:
        return await self._kernel.list_audit_events(
            organization_id=payload.organization_id,
            workspace_id=payload.workspace_id,
            thread_id=payload.thread_id,
            actor_user_id=payload.actor_user_id,
            actor_system_agent_id=payload.actor_system_agent_id,
            action_prefix=payload.action_prefix,
            outcome=payload.outcome,
            target_type=payload.target_type,
            target_id=payload.target_id,
            correlation_id=payload.correlation_id,
            request_id=payload.request_id,
            occurred_after=payload.occurred_after,
            occurred_before=payload.occurred_before,
            limit=payload.limit,
        )

    async def get_event(self, audit_event_id: UUID) -> AuditEvent | None:
        return await self._kernel.get_audit_event(audit_event_id)

    async def verify_chain(self, chain_partition: str) -> AuditChainVerificationResult:
        return await self._kernel.verify_audit_chain(chain_partition)

    async def resolve_workspace_organization(self, workspace_id: UUID) -> UUID | None:
        workspace = await self._kernel.get_workspace_detail(workspace_id)
        return workspace.workspace.organization_id

    async def resolve_thread_scope(self, thread_id: UUID) -> tuple[UUID | None, UUID | None]:
        thread = await self._kernel.get_thread_detail(thread_id)
        workspace_id = thread.thread.workspace_id
        organization_id = await self.resolve_workspace_organization(workspace_id)
        return organization_id, workspace_id

    async def list_pending_export_events(
        self,
        *,
        consumer_name: str,
        limit: int,
    ) -> list[AuditEvent]:
        return await self._repository.list_audit_events_pending_export(
            consumer_name=consumer_name,
            limit=limit,
        )

    async def advance_export_checkpoint(
        self,
        *,
        consumer_name: str,
        last_ledger_offset: int,
        metadata: dict[str, Any],
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._repository.advance_audit_export_checkpoint(
                    conn,
                    consumer_name=consumer_name,
                    last_ledger_offset=last_ledger_offset,
                    metadata=metadata,
                )

    async def list_retention_candidates(self, *, cutoff_recorded_at) -> list[dict[str, Any]]:
        return await self._repository.list_audit_retention_candidates(
            cutoff_recorded_at=cutoff_recorded_at,
        )

    async def list_events_for_retention(
        self,
        *,
        chain_partition: str,
        cutoff_recorded_at,
        limit: int,
    ) -> list[AuditEvent]:
        return await self._repository.list_audit_events_for_retention(
            chain_partition=chain_partition,
            cutoff_recorded_at=cutoff_recorded_at,
            limit=limit,
        )

    async def record_retention_snapshot(
        self,
        *,
        chain_partition: str,
        cutoff_recorded_at,
        last_pruned_sequence: int,
        last_pruned_event_hash: str,
        object_key: str,
        metadata: dict[str, Any],
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._repository.record_audit_retention_snapshot(
                    conn,
                    chain_partition=chain_partition,
                    cutoff_recorded_at=cutoff_recorded_at,
                    last_pruned_sequence=last_pruned_sequence,
                    last_pruned_event_hash=last_pruned_event_hash,
                    object_key=object_key,
                    metadata=metadata,
                )

    async def prune_events(
        self,
        *,
        chain_partition: str,
        max_ledger_offset: int,
    ) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._repository.prune_audit_events(
                    conn,
                    chain_partition=chain_partition,
                    max_ledger_offset=max_ledger_offset,
                )

    async def list_chain_heads(self) -> list[dict[str, Any]]:
        return await self._repository.list_audit_chain_heads()


class NoopAuditRelayProvider:
    provider_name = "none"
    consumer_name = None

    async def publish_events(self, events: list[AuditEvent]) -> None:
        _ = events

    def supports_subscription(self) -> bool:
        return False

    async def subscribe(self) -> AsyncIterator[AuditEvent]:
        if False:
            yield


class KafkaAuditRelayProvider:
    provider_name = "kafka"

    def __init__(self, gateway_settings) -> None:
        self._settings = gateway_settings
        self.consumer_name = gateway_settings.audit_relay_consumer_name

    async def publish_events(self, events: list[AuditEvent]) -> None:
        for event in events:
            await event_service.publish_audit_event(event)

    def supports_subscription(self) -> bool:
        return True

    async def subscribe(self) -> AsyncIterator[AuditEvent]:
        consumer = AIOKafkaConsumer(
            self._settings.kafka_audit_events_topic,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=f"{self._settings.kafka_consumer_group}-audit-projector",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda value: json.loads(value.decode()),
        )
        await consumer.start()
        try:
            async for message in consumer:
                yield AuditEvent.model_validate(message.value)
        finally:
            await consumer.stop()


class NoopAuditProjectionProvider:
    provider_name = "none"
    consumer_name = None

    def enabled(self) -> bool:
        return False

    async def ensure_ready(self) -> None:
        return None

    async def project_events(self, events: list[AuditEvent]) -> None:
        _ = events


class ClickHouseAuditProjectionProvider:
    provider_name = "clickhouse"

    def __init__(self, gateway_settings) -> None:
        self._settings = gateway_settings
        self.consumer_name = gateway_settings.audit_clickhouse_projector_consumer_name

    def enabled(self) -> bool:
        return bool(self._settings.audit_clickhouse_enabled)

    async def ensure_ready(self) -> None:
        ttl_days = max(self._settings.audit_clickhouse_retention_days, 1)
        statement = f"""
        CREATE TABLE IF NOT EXISTS {self._settings.audit_clickhouse_db}.audit_events (
            audit_event_id UUID,
            ledger_offset UInt64,
            occurred_at DateTime64(3, 'UTC'),
            recorded_at DateTime64(3, 'UTC'),
            scope_type String,
            organization_id Nullable(UUID),
            workspace_id Nullable(UUID),
            thread_id Nullable(UUID),
            actor_type String,
            actor_id Nullable(UUID),
            user_id Nullable(UUID),
            system_agent_id Nullable(UUID),
            source_service String,
            source_component String,
            action_category String,
            action_name String,
            target_type Nullable(String),
            target_id Nullable(UUID),
            outcome String,
            correlation_id Nullable(UUID),
            causation_id Nullable(UUID),
            request_id Nullable(UUID),
            trace_id Nullable(String),
            error_code Nullable(String),
            error_class Nullable(String),
            error_message_redacted Nullable(String),
            payload_mode String,
            payload_hash Nullable(String),
            payload_ref Nullable(String),
            payload_size_bytes Nullable(Int64),
            metadata String,
            chain_partition String,
            chain_sequence UInt64,
            prev_hash String,
            event_hash String
        )
        ENGINE = ReplacingMergeTree(recorded_at)
        PARTITION BY toYYYYMM(recorded_at)
        ORDER BY (recorded_at, chain_partition, chain_sequence, audit_event_id)
        TTL toDateTime(recorded_at) + toIntervalDay({ttl_days})
        """
        await self._clickhouse_query(statement)

    async def project_events(self, events: list[AuditEvent]) -> None:
        if not events:
            return
        existing_ids = await self._existing_ids(events)
        rows = []
        for event in events:
            if str(event.audit_event_id) in existing_ids:
                continue
            row = event.model_dump(mode="json")
            row["occurred_at"] = self._clickhouse_datetime(event.occurred_at)
            row["recorded_at"] = self._clickhouse_datetime(event.recorded_at)
            row["metadata"] = json.dumps(row["metadata"], sort_keys=True)
            rows.append(row)
        if not rows:
            return
        payload = "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"
        statement = (
            f"INSERT INTO {self._settings.audit_clickhouse_db}.audit_events FORMAT JSONEachRow"
        )
        await self._clickhouse_query(statement, body=payload)

    async def _existing_ids(self, events: list[AuditEvent]) -> set[str]:
        quoted_ids = ",".join(f"'{event.audit_event_id}'" for event in events)
        query = (
            f"SELECT audit_event_id FROM {self._settings.audit_clickhouse_db}.audit_events "
            f"WHERE audit_event_id IN ({quoted_ids}) FORMAT JSONEachRow"
        )
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.post(
                self._settings.audit_clickhouse_url,
                params={"database": self._settings.audit_clickhouse_db, "query": query},
                auth=(
                    self._settings.audit_clickhouse_user,
                    self._settings.audit_clickhouse_password,
                ),
            )
            response.raise_for_status()
        ids = set()
        for line in response.text.splitlines():
            if not line.strip():
                continue
            try:
                ids.add(str(json.loads(line)["audit_event_id"]))
            except Exception:
                logger.debug("Failed to parse ClickHouse existence check row")
        return ids

    async def _clickhouse_query(self, query: str, *, body: str | None = None) -> None:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.post(
                self._settings.audit_clickhouse_url,
                params={"database": self._settings.audit_clickhouse_db, "query": query},
                auth=(
                    self._settings.audit_clickhouse_user,
                    self._settings.audit_clickhouse_password,
                ),
                content=body.encode("utf-8") if body is not None else None,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = response.text.strip()
                if detail:
                    raise httpx.HTTPStatusError(
                        f"{exc}. ClickHouse response body: {detail[:1000]}",
                        request=exc.request,
                        response=exc.response,
                    ) from exc
                raise

    @staticmethod
    def _clickhouse_datetime(value) -> str:
        normalized = value.astimezone(UTC)
        return normalized.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


class NoopAuditArchiveProvider:
    provider_name = "none"

    def enabled(self) -> bool:
        return False

    async def put_object(
        self,
        *,
        object_key: str,
        payload: bytes,
        content_type: str | None = None,
    ) -> StoredObject:
        _ = payload
        _ = content_type
        raise RuntimeError(
            f"Audit archive provider is disabled; cannot store {object_key}"
        )

    def presign_get(self, *, object_key: str, expires_seconds: int) -> str | None:
        _ = object_key
        _ = expires_seconds
        return None


class MinioAuditArchiveProvider:
    provider_name = "minio"

    def __init__(self, gateway_settings) -> None:
        self._storage = MinioObjectStorage(
            endpoint=gateway_settings.asset_storage_endpoint,
            bucket=gateway_settings.asset_storage_bucket,
            access_key=gateway_settings.asset_storage_access_key,
            secret_key=gateway_settings.asset_storage_secret_key,
            region=gateway_settings.asset_storage_region,
            force_path_style=gateway_settings.asset_storage_force_path_style,
        )

    def enabled(self) -> bool:
        return True

    async def put_object(
        self,
        *,
        object_key: str,
        payload: bytes,
        content_type: str | None = None,
    ) -> StoredObject:
        return await self._storage.put_object(
            object_key=object_key,
            payload=payload,
            content_type=content_type,
        )

    def presign_get(self, *, object_key: str, expires_seconds: int) -> str | None:
        return self._storage.presign_get(
            object_key=object_key,
            expires_seconds=expires_seconds,
        )


async def build_audit_provider_registry(*, gateway_settings) -> AuditProviderRegistry:
    pool = await get_pool()
    ledger = PostgresAuditLedger(pool)
    relay_provider_name = getattr(gateway_settings, "audit_relay_provider", "kafka")
    projection_provider_name = getattr(gateway_settings, "audit_projection_provider", "clickhouse")
    archive_provider_name = getattr(gateway_settings, "audit_archive_provider", "minio")

    relay: AuditRelayProvider
    if relay_provider_name == "none":
        relay = NoopAuditRelayProvider()
    else:
        relay = KafkaAuditRelayProvider(gateway_settings)

    projection: AuditProjectionProvider
    if projection_provider_name == "none" or not gateway_settings.audit_clickhouse_enabled:
        projection = NoopAuditProjectionProvider()
    else:
        projection = ClickHouseAuditProjectionProvider(gateway_settings)

    archive: AuditArchiveProvider
    if archive_provider_name == "none":
        archive = NoopAuditArchiveProvider()
    else:
        archive = MinioAuditArchiveProvider(gateway_settings)

    return AuditProviderRegistry(
        ledger=ledger,
        relay=relay,
        projection=projection,
        archive=archive,
    )
