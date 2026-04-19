from __future__ import annotations

import asyncio
import os
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

_GW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/gateway-edge")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
_WORKSPACE_MEMORY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/workspace-memory")
)
for path in (_GW_DIR, _CONTRACTS_DIR, _CORE_COLLAB_DIR, _WORKSPACE_MEMORY_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from gateway_edge.config import settings
from gateway_edge.models import AuditEvent
from gateway_edge.services.audit import AuditService
from gateway_edge.services.object_storage import StoredObject


class _FakeConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def transaction(self):
        return self


class _FakeAcquire:
    async def __aenter__(self):
        return _FakeConnection()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def acquire(self):
        return _FakeAcquire()


def _audit_event(*, ledger_offset: int, chain_partition: str) -> AuditEvent:
    now = datetime.now(timezone.utc)
    return AuditEvent(
        audit_event_id=uuid4(),
        ledger_offset=ledger_offset,
        occurred_at=now,
        recorded_at=now,
        scope_type="workspace",
        workspace_id=uuid4(),
        thread_id=None,
        actor_type="user",
        actor_id=uuid4(),
        user_id=uuid4(),
        system_agent_id=None,
        source_service="gateway-edge",
        source_component="test",
        action_category="api",
        action_name="api.request.completed",
        target_type="workspace",
        target_id=uuid4(),
        outcome="success",
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        trace_id=None,
        error_code=None,
        error_class=None,
        error_message_redacted=None,
        payload_mode="metadata_only",
        payload_hash=None,
        payload_ref=None,
        payload_size_bytes=None,
        metadata={},
        chain_partition=chain_partition,
        chain_sequence=ledger_offset,
        prev_hash="0" * 64,
        event_hash="1" * 64,
    )


@pytest.mark.asyncio
async def test_audit_service_replay_once_inserts_and_advances_checkpoint(monkeypatch):
    recorded = {}

    class _Repository:
        async def list_audit_events_pending_export(self, *, consumer_name, limit):
            recorded["consumer_name"] = consumer_name
            recorded["limit"] = limit
            return [
                _audit_event(ledger_offset=1, chain_partition="workspace:test"),
                _audit_event(ledger_offset=2, chain_partition="workspace:test"),
            ]

        async def advance_audit_export_checkpoint(
            self,
            conn,
            *,
            consumer_name,
            last_ledger_offset,
            metadata,
        ):
            recorded["advanced"] = {
                "consumer_name": consumer_name,
                "last_ledger_offset": last_ledger_offset,
                "metadata": metadata,
            }

    service = AuditService()
    service._repository = _Repository()

    inserted = []

    async def _insert(events):
        inserted.extend(events)

    monkeypatch.setattr(service, "_insert_clickhouse_events", _insert)

    async def _get_pool():
        return _FakePool()

    monkeypatch.setattr("gateway_edge.services.audit.get_pool", _get_pool)

    await service._replay_projection_once()

    assert len(inserted) == 2
    assert recorded["consumer_name"] == settings.audit_clickhouse_projector_consumer_name
    assert recorded["advanced"]["last_ledger_offset"] == 2
    assert recorded["advanced"]["metadata"]["source"] == "replay"


@pytest.mark.asyncio
async def test_audit_service_retention_once_exports_and_prunes(monkeypatch):
    now = datetime.now(timezone.utc)
    old_event = _audit_event(ledger_offset=10, chain_partition="workspace:test")
    old_event = old_event.model_copy(
        update={
            "recorded_at": now - timedelta(days=120),
            "occurred_at": now - timedelta(days=120),
            "chain_sequence": 10,
        }
    )
    recorded = {}

    class _Repository:
        async def list_audit_retention_candidates(self, *, cutoff_recorded_at):
            recorded["cutoff"] = cutoff_recorded_at
            return [{"chain_partition": "workspace:test"}]

        async def list_audit_events_for_retention(
            self,
            *,
            chain_partition,
            cutoff_recorded_at,
            limit,
        ):
            recorded["retention_query"] = {
                "chain_partition": chain_partition,
                "limit": limit,
            }
            return [old_event]

        async def record_audit_retention_snapshot(
            self,
            conn,
            *,
            chain_partition,
            cutoff_recorded_at,
            last_pruned_sequence,
            last_pruned_event_hash,
            object_key,
            metadata,
        ):
            recorded["snapshot"] = {
                "chain_partition": chain_partition,
                "last_pruned_sequence": last_pruned_sequence,
                "last_pruned_event_hash": last_pruned_event_hash,
                "object_key": object_key,
                "metadata": metadata,
            }

        async def prune_audit_events(self, conn, *, chain_partition, max_ledger_offset):
            recorded["pruned"] = {
                "chain_partition": chain_partition,
                "max_ledger_offset": max_ledger_offset,
            }
            return 1

    service = AuditService()
    service._repository = _Repository()
    service._storage = SimpleNamespace(
        put_object=lambda **kwargs: StoredObject(
            bucket="open-talon-assets",
            object_key=kwargs["object_key"],
            size_bytes=len(kwargs["payload"]),
            sha256="a" * 64,
            content_type=kwargs.get("content_type"),
        )
    )

    async def _put_object(**kwargs):
        return StoredObject(
            bucket="open-talon-assets",
            object_key=kwargs["object_key"],
            size_bytes=len(kwargs["payload"]),
            sha256="a" * 64,
            content_type=kwargs.get("content_type"),
        )

    service._storage = SimpleNamespace(put_object=_put_object)

    async def _get_pool():
        return _FakePool()

    monkeypatch.setattr("gateway_edge.services.audit.get_pool", _get_pool)
    monkeypatch.setattr(settings, "audit_hot_retention_days", 90)
    monkeypatch.setattr(settings, "audit_retention_batch_size", 500)

    await service._retention_once()

    assert recorded["retention_query"]["chain_partition"] == "workspace:test"
    assert recorded["snapshot"]["last_pruned_sequence"] == 10
    assert recorded["pruned"]["max_ledger_offset"] == 10
    assert recorded["snapshot"]["object_key"].startswith(settings.audit_retention_prefix)


@pytest.mark.asyncio
async def test_export_chain_checkpoint_serializes_datetime_and_uuid(monkeypatch):
    checkpoint_payload = {}

    class _Repository:
        async def list_audit_chain_heads(self):
            return [
                {
                    "chain_partition": "organization:test",
                    "last_sequence": 7,
                    "last_event_hash": "a" * 64,
                    "updated_at": datetime.now(timezone.utc),
                    "organization_id": uuid4(),
                }
            ]

    async def _put_object(**kwargs):
        checkpoint_payload["payload"] = json.loads(kwargs["payload"].decode("utf-8"))
        return StoredObject(
            bucket="open-talon-assets",
            object_key=kwargs["object_key"],
            size_bytes=len(kwargs["payload"]),
            sha256="b" * 64,
            content_type=kwargs.get("content_type"),
        )

    service = AuditService()
    service._repository = _Repository()
    service._storage = SimpleNamespace(put_object=_put_object)

    exported = await service._export_chain_checkpoint("2026-04-19")

    assert exported is True
    exported_head = checkpoint_payload["payload"]["chain_heads"][0]
    assert exported_head["organization_id"]
    assert exported_head["updated_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_export_chain_checkpoint_returns_false_on_storage_failure():
    class _Repository:
        async def list_audit_chain_heads(self):
            return []

    async def _put_object(**kwargs):
        raise RuntimeError("storage unavailable")

    service = AuditService()
    service._repository = _Repository()
    service._storage = SimpleNamespace(put_object=_put_object)

    exported = await service._export_chain_checkpoint("2026-04-19")

    assert exported is False


@pytest.mark.asyncio
async def test_ensure_clickhouse_schema_uses_datetime_ttl(monkeypatch):
    recorded = {}
    service = AuditService()

    async def _clickhouse_query(statement, *, body=None):
        recorded["statement"] = statement
        recorded["body"] = body

    monkeypatch.setattr(service, "_clickhouse_query", _clickhouse_query)
    monkeypatch.setattr(settings, "audit_clickhouse_retention_days", 365)

    await service._ensure_clickhouse_schema()

    assert "TTL toDateTime(recorded_at) + toIntervalDay(365)" in recorded["statement"]


@pytest.mark.asyncio
async def test_insert_clickhouse_events_uses_clickhouse_datetime_strings(monkeypatch):
    service = AuditService()
    event = _audit_event(ledger_offset=1, chain_partition="workspace:test")
    event = event.model_copy(
        update={
            "organization_id": uuid4(),
            "occurred_at": datetime(2026, 4, 19, 12, 34, 56, 789000, tzinfo=timezone.utc),
            "recorded_at": datetime(2026, 4, 19, 12, 35, 1, 23000, tzinfo=timezone.utc),
            "metadata": {"route": "/health"},
        }
    )
    recorded = {}

    async def _existing_clickhouse_ids(events):
        return set()

    async def _clickhouse_query(statement, *, body=None):
        recorded["statement"] = statement
        recorded["body"] = body

    monkeypatch.setattr(service, "_existing_clickhouse_ids", _existing_clickhouse_ids)
    monkeypatch.setattr(service, "_clickhouse_query", _clickhouse_query)

    await service._insert_clickhouse_events([event])

    assert recorded["statement"].startswith("INSERT INTO")
    assert '"occurred_at": "2026-04-19 12:34:56.789"' in recorded["body"]
    assert '"recorded_at": "2026-04-19 12:35:01.023"' in recorded["body"]
    assert '"organization_id":' in recorded["body"]
    assert '"metadata": "{\\"route\\": \\"/health\\"}"' in recorded["body"]
    assert recorded["body"].endswith("\n")


@pytest.mark.asyncio
async def test_replay_loop_retries_after_iteration_failure(monkeypatch):
    service = AuditService()
    attempts = {"count": 0}

    async def _ensure_clickhouse_schema():
        return None

    async def _replay_projection_once():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary clickhouse failure")
        raise asyncio.CancelledError()

    monkeypatch.setattr(service, "_ensure_clickhouse_schema", _ensure_clickhouse_schema)
    monkeypatch.setattr(service, "_replay_projection_once", _replay_projection_once)
    monkeypatch.setattr(settings, "audit_clickhouse_enabled", True)

    with pytest.raises(asyncio.CancelledError):
        await service._replay_loop()

    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_projector_loop_continues_after_event_failure(monkeypatch):
    first = _audit_event(ledger_offset=1, chain_partition="workspace:test")
    second = _audit_event(ledger_offset=2, chain_partition="workspace:test")
    checkpoints = []
    inserted = []

    class _Repository:
        async def advance_audit_export_checkpoint(
            self,
            conn,
            *,
            consumer_name,
            last_ledger_offset,
            metadata,
        ):
            checkpoints.append(
                {
                    "consumer_name": consumer_name,
                    "last_ledger_offset": last_ledger_offset,
                    "metadata": metadata,
                }
            )

    class _FakeConsumer:
        def __init__(self, *args, **kwargs):
            self._messages = [
                SimpleNamespace(value=first.model_dump(mode="json")),
                SimpleNamespace(value=second.model_dump(mode="json")),
            ]

        async def start(self):
            return None

        async def stop(self):
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._messages:
                return self._messages.pop(0)
            raise asyncio.CancelledError()

    async def _insert_clickhouse_events(events):
        inserted.append(events[0].ledger_offset)
        if events[0].ledger_offset == 1:
            raise RuntimeError("temporary clickhouse failure")

    async def _ensure_clickhouse_schema():
        return None

    async def _get_pool():
        return _FakePool()

    service = AuditService()
    service._repository = _Repository()

    monkeypatch.setattr("gateway_edge.services.audit.AIOKafkaConsumer", _FakeConsumer)
    monkeypatch.setattr(service, "_insert_clickhouse_events", _insert_clickhouse_events)
    monkeypatch.setattr(service, "_ensure_clickhouse_schema", _ensure_clickhouse_schema)
    monkeypatch.setattr("gateway_edge.services.audit.get_pool", _get_pool)
    monkeypatch.setattr(settings, "audit_clickhouse_enabled", True)

    with pytest.raises(asyncio.CancelledError):
        await service._projector_loop()

    assert inserted == [1, 2]
    assert checkpoints == [
        {
            "consumer_name": settings.audit_clickhouse_projector_consumer_name,
            "last_ledger_offset": 2,
            "metadata": {"source": "kafka"},
        }
    ]
