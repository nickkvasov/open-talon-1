from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys
from uuid import UUID, uuid4

import httpx
from aiokafka import AIOKafkaConsumer

_ROOT_DIR = Path(__file__).resolve().parents[4]
_CORE_COLLAB_DIR = _ROOT_DIR / "services" / "core-collab"
if _CORE_COLLAB_DIR.is_dir():
    collab_path = str(_CORE_COLLAB_DIR)
    if collab_path not in sys.path:
        sys.path.insert(0, collab_path)

from core_collab import CollaborationKernel, CollaborationRepository

from gateway_edge.config import settings
from gateway_edge.db.postgres import get_pool
from gateway_edge.models import (
    AuditChainVerificationResult,
    AuditEvent,
    AuditEventDraft,
    AuditEventPage,
    AuditExportRequest,
    AuditExportResult,
    AuthContext,
)
from gateway_edge.services.events import event_service
from gateway_edge.services.object_storage import MinioObjectStorage

logger = logging.getLogger(__name__)

_SECRET_PATTERN = re.compile(
    r"(?i)(bearer\s+[a-z0-9._-]+|token=[^&\s]+|authorization:\s*[^\s]+|secret=[^&\s]+)"
)


class AuditService:
    def __init__(self) -> None:
        self._repository: CollaborationRepository | None = None
        self._kernel: CollaborationKernel | None = None
        self._storage = MinioObjectStorage(
            endpoint=settings.asset_storage_endpoint,
            bucket=settings.asset_storage_bucket,
            access_key=settings.asset_storage_access_key,
            secret_key=settings.asset_storage_secret_key,
            region=settings.asset_storage_region,
            force_path_style=settings.asset_storage_force_path_style,
        )
        self._relay_task: asyncio.Task[None] | None = None
        self._projector_task: asyncio.Task[None] | None = None
        self._replay_task: asyncio.Task[None] | None = None
        self._checkpoint_task: asyncio.Task[None] | None = None
        self._retention_task: asyncio.Task[None] | None = None
        self._checkpoint_exported_for: str | None = None

    async def start(self) -> None:
        pool = await get_pool()
        self._repository = CollaborationRepository(pool)
        self._kernel = CollaborationKernel(self._repository)
        await self._kernel.setup_schema()
        self._relay_task = asyncio.create_task(self._relay_loop())
        self._projector_task = asyncio.create_task(self._projector_loop())
        self._replay_task = asyncio.create_task(self._replay_loop())
        self._checkpoint_task = asyncio.create_task(self._checkpoint_loop())
        self._retention_task = asyncio.create_task(self._retention_loop())
        logger.info("Audit service started")

    async def stop(self) -> None:
        for task in (
            self._relay_task,
            self._projector_task,
            self._replay_task,
            self._checkpoint_task,
            self._retention_task,
        ):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(
                task
                for task in (
                    self._relay_task,
                    self._projector_task,
                    self._replay_task,
                    self._checkpoint_task,
                    self._retention_task,
                )
                if task is not None
            ),
            return_exceptions=True,
        )
        self._relay_task = None
        self._projector_task = None
        self._replay_task = None
        self._checkpoint_task = None
        self._retention_task = None
        self._kernel = None
        self._repository = None
        logger.info("Audit service stopped")

    async def record_http_audit(
        self,
        *,
        request,
        response=None,
        started_at: datetime,
        error: Exception | None = None,
    ) -> None:
        kernel = self._kernel
        if kernel is None:
            return
        status_code = 500 if error is not None else getattr(response, "status_code", 200)
        auth_context = getattr(request.state, "auth_context", None)
        organization_id, workspace_id, thread_id, scope_type = await self._resolve_scope(
            request.path_params
        )
        action_category, action_name, outcome = self._http_action_details(status_code=status_code, error=error)
        route = request.scope.get("route")
        route_template = getattr(route, "path", request.url.path)
        draft = AuditEventDraft(
            occurred_at=started_at,
            recorded_at=datetime.now(UTC),
            scope_type=scope_type,
            organization_id=organization_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor_type=self._actor_type_from_auth(auth_context),
            actor_id=self._actor_id_from_auth(auth_context),
            user_id=self._user_id_from_auth(auth_context),
            source_service="gateway-edge",
            source_component="http-middleware",
            action_category=action_category,
            action_name=action_name,
            outcome=outcome,
            correlation_id=getattr(request.state, "correlation_id", None),
            request_id=getattr(request.state, "request_id", None),
            error_class=error.__class__.__name__ if error is not None else None,
            error_message_redacted=self._redact_error(str(error)) if error is not None else None,
            metadata={
                "method": request.method,
                "path": request.url.path,
                "route_template": route_template,
                "status_code": status_code,
                "query_keys": sorted(request.query_params.keys()),
                "client_host": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
            },
            chain_partition=self._chain_partition(
                organization_id=organization_id,
                workspace_id=workspace_id,
            ),
        )
        await self._record_audit_draft(draft)

    async def record_websocket_audit(
        self,
        *,
        thread_id: UUID,
        workspace_id: UUID | None,
        action_name: str,
        outcome: str,
        actor_type: str,
        actor_id: UUID | None = None,
        user_id: UUID | None = None,
        system_agent_id: UUID | None = None,
        request_id: UUID | None = None,
        metadata: dict[str, object] | None = None,
        error_message: str | None = None,
    ) -> None:
        organization_id = None
        if workspace_id is not None:
            try:
                workspace = await self._require_kernel().get_workspace_detail(workspace_id)
                organization_id = workspace.workspace.organization_id
            except Exception:
                organization_id = None
        draft = AuditEventDraft(
            occurred_at=datetime.now(UTC),
            recorded_at=datetime.now(UTC),
            scope_type="thread",
            organization_id=organization_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor_type=actor_type,
            actor_id=actor_id,
            user_id=user_id,
            system_agent_id=system_agent_id,
            source_service="gateway-edge",
            source_component="websocket",
            action_category=action_name.split(".", 1)[0],
            action_name=action_name,
            outcome=outcome,
            request_id=request_id,
            error_message_redacted=self._redact_error(error_message) if error_message else None,
            metadata=metadata or {},
            chain_partition=self._chain_partition(
                organization_id=organization_id,
                workspace_id=workspace_id,
            ),
        )
        await self._record_audit_draft(draft)

    async def list_audit_events(self, payload: AuditExportRequest) -> AuditEventPage:
        return await self._require_kernel().list_audit_events(
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

    async def get_audit_event(self, audit_event_id: UUID) -> AuditEvent | None:
        return await self._require_kernel().get_audit_event(audit_event_id)

    async def verify_audit_chain(
        self,
        chain_partition: str,
    ) -> AuditChainVerificationResult:
        return await self._require_kernel().verify_audit_chain(chain_partition)

    async def export_audit_events(self, payload: AuditExportRequest) -> AuditExportResult:
        page = await self.list_audit_events(payload)
        lines = [
            json.dumps(event.model_dump(mode="json"), sort_keys=True)
            for event in page.events
        ]
        body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
        object_key = (
            f"{settings.audit_exports_prefix}/"
            f"{datetime.now(UTC).strftime('%Y/%m/%d')}/"
            f"{uuid4()}.jsonl"
        )
        stored = await self._storage.put_object(
            object_key=object_key,
            payload=body,
            content_type="application/x-ndjson",
        )
        return AuditExportResult(
            object_key=stored.object_key,
            bucket=stored.bucket,
            event_count=len(page.events),
            size_bytes=stored.size_bytes,
            sha256=stored.sha256,
            presigned_url=self._storage.presign_get(
                object_key=stored.object_key,
                expires_seconds=settings.asset_storage_presign_expiry_seconds,
            ),
        )

    async def _record_audit_draft(self, draft: AuditEventDraft) -> None:
        kernel = self._kernel
        if kernel is None:
            return
        try:
            await kernel.record_audit_event(draft)
        except Exception:
            logger.exception("Failed to write audit event action_name=%s", draft.action_name)

    async def _resolve_scope(
        self,
        path_params: dict[str, object],
    ) -> tuple[UUID | None, UUID | None, UUID | None, str]:
        organization_id = path_params.get("organization_id")
        workspace_id = path_params.get("workspace_id")
        thread_id = path_params.get("thread_id")
        if isinstance(thread_id, UUID):
            try:
                thread = await self._require_kernel().get_thread_detail(thread_id)
                workspace = await self._require_kernel().get_workspace_detail(
                    thread.thread.workspace_id
                )
                return (
                    workspace.workspace.organization_id,
                    thread.thread.workspace_id,
                    thread_id,
                    "thread",
                )
            except Exception:
                return (
                    organization_id if isinstance(organization_id, UUID) else None,
                    workspace_id if isinstance(workspace_id, UUID) else None,
                    thread_id,
                    "thread",
                )
        if isinstance(workspace_id, UUID):
            try:
                workspace = await self._require_kernel().get_workspace_detail(workspace_id)
                return workspace.workspace.organization_id, workspace_id, None, "workspace"
            except Exception:
                return (
                    organization_id if isinstance(organization_id, UUID) else None,
                    workspace_id,
                    None,
                    "workspace",
                )
        if isinstance(organization_id, UUID):
            return organization_id, None, None, "organization"
        return None, None, None, "global"

    async def _relay_loop(self) -> None:
        try:
            while True:
                await self._relay_batch_once()
                await asyncio.sleep(settings.audit_relay_interval_seconds)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:
            logger.exception("Audit relay loop failed")

    async def _projector_loop(self) -> None:
        if not settings.audit_clickhouse_enabled:
            return
        consumer = AIOKafkaConsumer(
            settings.kafka_audit_events_topic,
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=f"{settings.kafka_consumer_group}-audit-projector",
            auto_offset_reset="latest",
            enable_auto_commit=True,
            value_deserializer=lambda value: json.loads(value.decode()),
        )
        try:
            await consumer.start()
            while True:
                try:
                    await self._ensure_clickhouse_schema()
                    break
                except asyncio.CancelledError:  # pragma: no cover - shutdown path
                    raise
                except Exception:
                    logger.exception("Audit projector schema sync failed")
                    await asyncio.sleep(
                        settings.audit_clickhouse_replay_interval_seconds
                    )
            async for message in consumer:
                try:
                    event = AuditEvent.model_validate(message.value)
                    await self._insert_clickhouse_events([event])
                    pool = await get_pool()
                    async with pool.acquire() as conn:
                        async with conn.transaction():
                            await self._require_repository().advance_audit_export_checkpoint(
                                conn,
                                consumer_name=settings.audit_clickhouse_projector_consumer_name,
                                last_ledger_offset=event.ledger_offset,
                                metadata={"source": "kafka"},
                            )
                except asyncio.CancelledError:  # pragma: no cover - shutdown path
                    raise
                except Exception:
                    logger.exception(
                        "Audit projector event failed ledger_offset=%s",
                        message.value.get("ledger_offset"),
                    )
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:
            logger.exception("Audit projector loop failed")
        finally:
            await consumer.stop()

    async def _replay_loop(self) -> None:
        if not settings.audit_clickhouse_enabled:
            return
        try:
            while True:
                try:
                    await self._ensure_clickhouse_schema()
                    await self._replay_projection_once()
                except asyncio.CancelledError:  # pragma: no cover - shutdown path
                    raise
                except Exception:
                    logger.exception("Audit replay iteration failed")
                await asyncio.sleep(settings.audit_clickhouse_replay_interval_seconds)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise

    async def _checkpoint_loop(self) -> None:
        try:
            while True:
                day_key = datetime.now(UTC).strftime("%Y-%m-%d")
                if self._checkpoint_exported_for != day_key:
                    exported = await self._export_chain_checkpoint(day_key)
                    if exported:
                        self._checkpoint_exported_for = day_key
                await asyncio.sleep(3600)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:
            logger.exception("Audit checkpoint loop failed")

    async def _retention_loop(self) -> None:
        try:
            while True:
                await self._retention_once()
                await asyncio.sleep(settings.audit_retention_interval_seconds)
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            raise
        except Exception:
            logger.exception("Audit retention loop failed")

    async def _relay_batch_once(self) -> None:
        repository = self._require_repository()
        batch = await repository.list_audit_events_pending_export(
            consumer_name=settings.audit_relay_consumer_name,
            limit=settings.audit_relay_batch_size,
        )
        if not batch:
            return
        for event in batch:
            await event_service.publish_audit_event(event)
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.advance_audit_export_checkpoint(
                    conn,
                    consumer_name=settings.audit_relay_consumer_name,
                    last_ledger_offset=batch[-1].ledger_offset,
                    metadata={"event_count": len(batch)},
                )

    async def _replay_projection_once(self) -> None:
        repository = self._require_repository()
        batch = await repository.list_audit_events_pending_export(
            consumer_name=settings.audit_clickhouse_projector_consumer_name,
            limit=settings.audit_clickhouse_replay_batch_size,
        )
        if not batch:
            return
        await self._insert_clickhouse_events(batch)
        pool = await get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.advance_audit_export_checkpoint(
                    conn,
                    consumer_name=settings.audit_clickhouse_projector_consumer_name,
                    last_ledger_offset=batch[-1].ledger_offset,
                    metadata={"source": "replay", "event_count": len(batch)},
                )

    async def _retention_once(self) -> None:
        repository = self._require_repository()
        cutoff = datetime.now(UTC) - timedelta(days=max(settings.audit_hot_retention_days, 1))
        candidates = await repository.list_audit_retention_candidates(
            cutoff_recorded_at=cutoff,
        )
        for candidate in candidates:
            chain_partition = str(candidate["chain_partition"])
            batch = await repository.list_audit_events_for_retention(
                chain_partition=chain_partition,
                cutoff_recorded_at=cutoff,
                limit=settings.audit_retention_batch_size,
            )
            if not batch:
                continue
            object_key = self._retention_object_key(
                chain_partition=chain_partition,
                first_offset=batch[0].ledger_offset,
                last_offset=batch[-1].ledger_offset,
            )
            payload = (
                "\n".join(
                    json.dumps(event.model_dump(mode="json"), sort_keys=True)
                    for event in batch
                )
                + "\n"
            ).encode("utf-8")
            stored = await self._storage.put_object(
                object_key=object_key,
                payload=payload,
                content_type="application/x-ndjson",
            )
            last_event = batch[-1]
            pool = await get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await repository.record_audit_retention_snapshot(
                        conn,
                        chain_partition=chain_partition,
                        cutoff_recorded_at=cutoff,
                        last_pruned_sequence=last_event.chain_sequence,
                        last_pruned_event_hash=last_event.event_hash,
                        object_key=stored.object_key,
                        metadata={
                            "event_count": len(batch),
                            "first_sequence": batch[0].chain_sequence,
                            "last_sequence": last_event.chain_sequence,
                            "first_ledger_offset": batch[0].ledger_offset,
                            "last_ledger_offset": last_event.ledger_offset,
                            "sha256": stored.sha256,
                        },
                    )
                    await repository.prune_audit_events(
                        conn,
                        chain_partition=chain_partition,
                        max_ledger_offset=last_event.ledger_offset,
                    )

    async def _export_chain_checkpoint(self, day_key: str) -> bool:
        repository = self._require_repository()
        heads = await repository.list_audit_chain_heads()
        payload = json.dumps(
            {
                "exported_at": datetime.now(UTC).isoformat(),
                "chain_heads": heads,
            },
            sort_keys=True,
            default=self._json_default,
        ).encode("utf-8")
        object_key = f"{settings.audit_checkpoint_bucket_prefix}/{day_key}.json"
        try:
            await self._storage.put_object(
                object_key=object_key,
                payload=payload,
                content_type="application/json",
            )
            return True
        except Exception:
            logger.exception("Failed to export audit chain checkpoint")
            return False

    async def _ensure_clickhouse_schema(self) -> None:
        ttl_days = max(settings.audit_clickhouse_retention_days, 1)
        statement = f"""
        CREATE TABLE IF NOT EXISTS {settings.audit_clickhouse_db}.audit_events (
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

    async def _insert_clickhouse_events(self, events: list[AuditEvent]) -> None:
        if not events:
            return
        existing_ids = await self._existing_clickhouse_ids(events)
        rows = []
        for event in events:
            if str(event.audit_event_id) in existing_ids:
                continue
            row = self._clickhouse_event_row(event)
            row["metadata"] = json.dumps(row["metadata"], sort_keys=True)
            rows.append(row)
        if not rows:
            return
        payload = "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n"
        statement = (
            f"INSERT INTO {settings.audit_clickhouse_db}.audit_events FORMAT JSONEachRow"
        )
        await self._clickhouse_query(statement, body=payload)

    async def _existing_clickhouse_ids(self, events: list[AuditEvent]) -> set[str]:
        if not events:
            return set()
        quoted_ids = ",".join(f"'{event.audit_event_id}'" for event in events)
        query = (
            f"SELECT audit_event_id FROM {settings.audit_clickhouse_db}.audit_events "
            f"WHERE audit_event_id IN ({quoted_ids}) FORMAT JSONEachRow"
        )
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.post(
                settings.audit_clickhouse_url,
                params={"database": settings.audit_clickhouse_db, "query": query},
                auth=(settings.audit_clickhouse_user, settings.audit_clickhouse_password),
            )
            response.raise_for_status()
        lines = [line for line in response.text.splitlines() if line.strip()]
        ids = set()
        for line in lines:
            try:
                ids.add(str(json.loads(line)["audit_event_id"]))
            except Exception:
                logger.debug("Failed to parse ClickHouse existence check row")
        return ids

    async def _clickhouse_query(self, query: str, *, body: str | None = None) -> None:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.post(
                settings.audit_clickhouse_url,
                params={"database": settings.audit_clickhouse_db, "query": query},
                auth=(settings.audit_clickhouse_user, settings.audit_clickhouse_password),
                content=body.encode("utf-8") if body is not None else None,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = response.text.strip()
                if detail:
                    message = (
                        f"{exc}. ClickHouse response body: {detail[:1000]}"
                    )
                    raise httpx.HTTPStatusError(
                        message,
                        request=exc.request,
                        response=exc.response,
                    ) from exc
                raise

    @staticmethod
    def _http_action_details(
        *,
        status_code: int,
        error: Exception | None,
    ) -> tuple[str, str, str]:
        if status_code == 401:
            return "auth", "auth.login_failed", "denied"
        if status_code == 403:
            return "authz", "authz.denied", "denied"
        if error is not None or status_code >= 500:
            return "api", "api.request.failed", "error"
        if status_code >= 400:
            return "api", "api.request.failed", "failure"
        return "api", "api.request.completed", "success"

    @staticmethod
    def _actor_type_from_auth(auth_context: object) -> str:
        if isinstance(auth_context, AuthContext):
            if auth_context.kind == "oidc":
                return "user"
            if auth_context.kind == "api_key":
                return "api_key"
        return "unknown"

    @staticmethod
    def _actor_id_from_auth(auth_context: object) -> UUID | None:
        if isinstance(auth_context, AuthContext) and auth_context.kind == "oidc":
            return auth_context.user_id
        return None

    @staticmethod
    def _user_id_from_auth(auth_context: object) -> UUID | None:
        if isinstance(auth_context, AuthContext) and auth_context.kind == "oidc":
            return auth_context.user_id
        return None

    @staticmethod
    def _chain_partition(
        *,
        organization_id: UUID | None,
        workspace_id: UUID | None,
    ) -> str:
        if workspace_id is not None:
            return f"workspace:{workspace_id}"
        if organization_id is not None:
            return f"organization:{organization_id}"
        if workspace_id is None:
            return "global"
        return f"workspace:{workspace_id}"

    @staticmethod
    def _retention_object_key(
        *,
        chain_partition: str,
        first_offset: int,
        last_offset: int,
    ) -> str:
        safe_partition = re.sub(r"[^A-Za-z0-9._-]+", "_", chain_partition)
        return (
            f"{settings.audit_retention_prefix}/"
            f"{datetime.now(UTC).strftime('%Y/%m/%d')}/"
            f"{safe_partition}-{first_offset}-{last_offset}.jsonl"
        )

    @staticmethod
    def _json_default(value: object) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, UUID):
            return str(value)
        raise TypeError(
            f"Object of type {value.__class__.__name__} is not JSON serializable"
        )

    @staticmethod
    def _redact_error(message: str | None) -> str | None:
        if message is None:
            return None
        return _SECRET_PATTERN.sub("[REDACTED]", message)[:512]

    @classmethod
    def _clickhouse_event_row(cls, event: AuditEvent) -> dict[str, object]:
        row = event.model_dump(mode="json")
        row["occurred_at"] = cls._clickhouse_datetime(event.occurred_at)
        row["recorded_at"] = cls._clickhouse_datetime(event.recorded_at)
        return row

    @staticmethod
    def _clickhouse_datetime(value: datetime) -> str:
        normalized = value.astimezone(UTC)
        return normalized.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    def _require_repository(self) -> CollaborationRepository:
        if self._repository is None:
            raise RuntimeError("Audit service is not started")
        return self._repository

    def _require_kernel(self) -> CollaborationKernel:
        if self._kernel is None:
            raise RuntimeError("Audit service is not started")
        return self._kernel


audit_service = AuditService()
