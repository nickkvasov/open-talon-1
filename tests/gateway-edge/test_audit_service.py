from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
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
from gateway_edge.models import AuditEvent, AuthContext
from gateway_edge.services.audit import AuditService
from gateway_edge.services.audit_providers import (
    ClickHouseAuditProjectionProvider,
    NoopAuditArchiveProvider,
    NoopAuditProjectionProvider,
    NoopAuditRelayProvider,
    build_audit_provider_registry,
)
from gateway_edge.services.object_storage import StoredObject


def _audit_event(*, ledger_offset: int, chain_partition: str) -> AuditEvent:
    now = datetime.now(UTC)
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


class _FakeLedger:
    def __init__(self) -> None:
        self.pending_events: list[AuditEvent] = []
        self.retention_events: list[AuditEvent] = []
        self.chain_heads: list[dict[str, object]] = []
        self.retention_candidates: list[dict[str, object]] = []
        self.checkpoints: list[dict[str, object]] = []
        self.snapshots: list[dict[str, object]] = []
        self.pruned: list[dict[str, object]] = []
        self.page_events: list[AuditEvent] = []

    async def setup(self) -> None:
        return None

    async def record_event(self, draft) -> None:
        _ = draft

    async def list_events(self, payload):
        _ = payload
        return SimpleNamespace(events=list(self.page_events))

    async def get_event(self, audit_event_id):
        _ = audit_event_id
        return None

    async def verify_chain(self, chain_partition):
        _ = chain_partition
        return None

    async def resolve_workspace_organization(self, workspace_id):
        _ = workspace_id
        return uuid4()

    async def resolve_thread_scope(self, thread_id):
        _ = thread_id
        return uuid4(), uuid4()

    async def list_pending_export_events(self, *, consumer_name, limit):
        self.pending_request = {"consumer_name": consumer_name, "limit": limit}
        return list(self.pending_events)

    async def advance_export_checkpoint(
        self,
        *,
        consumer_name,
        last_ledger_offset,
        metadata,
    ) -> None:
        self.checkpoints.append(
            {
                "consumer_name": consumer_name,
                "last_ledger_offset": last_ledger_offset,
                "metadata": metadata,
            }
        )

    async def list_retention_candidates(self, *, cutoff_recorded_at):
        self.cutoff = cutoff_recorded_at
        return list(self.retention_candidates)

    async def list_events_for_retention(
        self,
        *,
        chain_partition,
        cutoff_recorded_at,
        limit,
    ):
        self.retention_request = {
            "chain_partition": chain_partition,
            "cutoff_recorded_at": cutoff_recorded_at,
            "limit": limit,
        }
        return list(self.retention_events)

    async def record_retention_snapshot(
        self,
        *,
        chain_partition,
        cutoff_recorded_at,
        last_pruned_sequence,
        last_pruned_event_hash,
        object_key,
        metadata,
    ) -> None:
        self.snapshots.append(
            {
                "chain_partition": chain_partition,
                "cutoff_recorded_at": cutoff_recorded_at,
                "last_pruned_sequence": last_pruned_sequence,
                "last_pruned_event_hash": last_pruned_event_hash,
                "object_key": object_key,
                "metadata": metadata,
            }
        )

    async def prune_events(self, *, chain_partition, max_ledger_offset) -> None:
        self.pruned.append(
            {
                "chain_partition": chain_partition,
                "max_ledger_offset": max_ledger_offset,
            }
        )

    async def list_chain_heads(self):
        return list(self.chain_heads)


class _RecordingProjectionProvider:
    provider_name = "recording"
    consumer_name = "recording-projector"

    def __init__(self) -> None:
        self.inserted: list[list[AuditEvent]] = []
        self.ensure_ready_calls = 0

    def enabled(self) -> bool:
        return True

    async def ensure_ready(self) -> None:
        self.ensure_ready_calls += 1

    async def project_events(self, events: list[AuditEvent]) -> None:
        self.inserted.append(list(events))


class _RecordingArchiveProvider:
    provider_name = "recording"

    def __init__(self, *, fail_put: bool = False) -> None:
        self.fail_put = fail_put
        self.records: list[dict[str, object]] = []

    def enabled(self) -> bool:
        return True

    async def put_object(
        self,
        *,
        object_key: str,
        payload: bytes,
        content_type: str | None = None,
    ) -> StoredObject:
        if self.fail_put:
            raise RuntimeError("storage unavailable")
        self.records.append(
            {
                "object_key": object_key,
                "payload": payload,
                "content_type": content_type,
            }
        )
        return StoredObject(
            bucket="open-talon-assets",
            object_key=object_key,
            size_bytes=len(payload),
            sha256="a" * 64,
            content_type=content_type,
        )

    def presign_get(self, *, object_key: str, expires_seconds: int) -> str | None:
        _ = expires_seconds
        return f"http://test/{object_key}"


class _StreamRelayProvider:
    provider_name = "stream"
    consumer_name = "stream-relay"

    def __init__(self, events: list[AuditEvent]) -> None:
        self._events = list(events)
        self.published: list[list[AuditEvent]] = []

    async def publish_events(self, events: list[AuditEvent]) -> None:
        self.published.append(list(events))

    def supports_subscription(self) -> bool:
        return True

    async def subscribe(self):
        for event in self._events:
            yield event
        raise asyncio.CancelledError()


class _RecordingRelayProvider:
    provider_name = "recording-relay"
    consumer_name = "recording-relay"

    def __init__(self) -> None:
        self.published: list[list[AuditEvent]] = []

    async def publish_events(self, events: list[AuditEvent]) -> None:
        self.published.append(list(events))

    def supports_subscription(self) -> bool:
        return False

    async def subscribe(self):
        if False:
            yield


class _DraftCaptureLedger(_FakeLedger):
    def __init__(self) -> None:
        super().__init__()
        self.drafts = []

    async def record_event(self, draft) -> None:
        self.drafts.append(draft)


@pytest.mark.asyncio
async def test_audit_service_replay_once_projects_and_advances_checkpoint():
    ledger = _FakeLedger()
    ledger.pending_events = [
        _audit_event(ledger_offset=1, chain_partition="workspace:test"),
        _audit_event(ledger_offset=2, chain_partition="workspace:test"),
    ]
    projection = _RecordingProjectionProvider()
    service = AuditService(
        ledger=ledger,
        relay_provider=NoopAuditRelayProvider(),
        projection_provider=projection,
        archive_provider=NoopAuditArchiveProvider(),
    )

    await service._replay_projection_once()

    assert len(projection.inserted) == 1
    assert [event.ledger_offset for event in projection.inserted[0]] == [1, 2]
    assert ledger.checkpoints == [
        {
            "consumer_name": projection.consumer_name,
            "last_ledger_offset": 2,
            "metadata": {"source": "replay", "event_count": 2},
        }
    ]


@pytest.mark.asyncio
async def test_audit_service_relay_batch_publishes_and_advances_checkpoint():
    ledger = _FakeLedger()
    ledger.pending_events = [
        _audit_event(ledger_offset=11, chain_partition="workspace:test"),
        _audit_event(ledger_offset=12, chain_partition="workspace:test"),
    ]
    relay = _RecordingRelayProvider()
    service = AuditService(
        ledger=ledger,
        relay_provider=relay,
        projection_provider=NoopAuditProjectionProvider(),
        archive_provider=NoopAuditArchiveProvider(),
    )

    await service._relay_batch_once()

    assert len(relay.published) == 1
    assert [event.ledger_offset for event in relay.published[0]] == [11, 12]
    assert ledger.checkpoints == [
        {
            "consumer_name": relay.consumer_name,
            "last_ledger_offset": 12,
            "metadata": {"event_count": 2},
        }
    ]


@pytest.mark.asyncio
async def test_audit_service_retention_once_exports_and_prunes():
    now = datetime.now(UTC)
    old_event = _audit_event(ledger_offset=10, chain_partition="workspace:test").model_copy(
        update={
            "recorded_at": now - timedelta(days=120),
            "occurred_at": now - timedelta(days=120),
            "chain_sequence": 10,
        }
    )
    ledger = _FakeLedger()
    ledger.retention_candidates = [{"chain_partition": "workspace:test"}]
    ledger.retention_events = [old_event]
    archive = _RecordingArchiveProvider()
    service = AuditService(
        ledger=ledger,
        relay_provider=NoopAuditRelayProvider(),
        projection_provider=NoopAuditProjectionProvider(),
        archive_provider=archive,
    )

    await service._retention_once()

    assert ledger.retention_request["chain_partition"] == "workspace:test"
    assert ledger.snapshots[0]["last_pruned_sequence"] == 10
    assert ledger.pruned[0]["max_ledger_offset"] == 10
    assert archive.records[0]["object_key"].startswith(settings.audit_retention_prefix)


@pytest.mark.asyncio
async def test_export_chain_checkpoint_serializes_datetime_and_uuid():
    ledger = _FakeLedger()
    ledger.chain_heads = [
        {
            "chain_partition": "organization:test",
            "last_sequence": 7,
            "last_event_hash": "a" * 64,
            "updated_at": datetime.now(UTC),
            "organization_id": uuid4(),
        }
    ]
    archive = _RecordingArchiveProvider()
    service = AuditService(
        ledger=ledger,
        relay_provider=NoopAuditRelayProvider(),
        projection_provider=NoopAuditProjectionProvider(),
        archive_provider=archive,
    )

    exported = await service._export_chain_checkpoint("2026-04-19")

    assert exported is True
    payload = json.loads(archive.records[0]["payload"].decode("utf-8"))
    exported_head = payload["chain_heads"][0]
    assert exported_head["organization_id"]
    assert exported_head["updated_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_export_audit_events_uses_archive_provider_and_presign_url():
    ledger = _FakeLedger()
    ledger.page_events = [
        _audit_event(ledger_offset=21, chain_partition="workspace:test"),
        _audit_event(ledger_offset=22, chain_partition="workspace:test"),
    ]
    archive = _RecordingArchiveProvider()
    service = AuditService(
        ledger=ledger,
        relay_provider=NoopAuditRelayProvider(),
        projection_provider=NoopAuditProjectionProvider(),
        archive_provider=archive,
    )

    result = await service.export_audit_events(SimpleNamespace(limit=1000))

    assert result.event_count == 2
    assert result.presigned_url == f"http://test/{result.object_key}"
    payload_lines = archive.records[0]["payload"].decode("utf-8").strip().splitlines()
    assert len(payload_lines) == 2
    assert json.loads(payload_lines[0])["ledger_offset"] == 21


@pytest.mark.asyncio
async def test_export_chain_checkpoint_returns_false_on_storage_failure():
    ledger = _FakeLedger()
    archive = _RecordingArchiveProvider(fail_put=True)
    service = AuditService(
        ledger=ledger,
        relay_provider=NoopAuditRelayProvider(),
        projection_provider=NoopAuditProjectionProvider(),
        archive_provider=archive,
    )

    exported = await service._export_chain_checkpoint("2026-04-19")

    assert exported is False


@pytest.mark.asyncio
async def test_clickhouse_projection_provider_uses_datetime_strings(monkeypatch):
    provider = ClickHouseAuditProjectionProvider(settings)
    event = _audit_event(ledger_offset=1, chain_partition="workspace:test").model_copy(
        update={
            "organization_id": uuid4(),
            "occurred_at": datetime(2026, 4, 19, 12, 34, 56, 789000, tzinfo=UTC),
            "recorded_at": datetime(2026, 4, 19, 12, 35, 1, 23000, tzinfo=UTC),
            "metadata": {"route": "/health"},
        }
    )
    recorded = {}

    async def _existing_ids(events):
        _ = events
        return set()

    async def _clickhouse_query(statement, *, body=None):
        recorded["statement"] = statement
        recorded["body"] = body

    monkeypatch.setattr(provider, "_existing_ids", _existing_ids)
    monkeypatch.setattr(provider, "_clickhouse_query", _clickhouse_query)

    await provider.project_events([event])

    assert recorded["statement"].startswith("INSERT INTO")
    assert '"occurred_at": "2026-04-19 12:34:56.789"' in recorded["body"]
    assert '"recorded_at": "2026-04-19 12:35:01.023"' in recorded["body"]
    assert '"metadata": "{\\"route\\": \\"/health\\"}"' in recorded["body"]


@pytest.mark.asyncio
async def test_replay_loop_retries_after_iteration_failure(monkeypatch):
    service = AuditService(
        ledger=_FakeLedger(),
        relay_provider=NoopAuditRelayProvider(),
        projection_provider=_RecordingProjectionProvider(),
        archive_provider=NoopAuditArchiveProvider(),
    )
    attempts = {"count": 0}

    async def _ensure_ready():
        return None

    async def _replay_projection_once():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary projection failure")
        raise asyncio.CancelledError()

    monkeypatch.setattr(service._projection_provider, "ensure_ready", _ensure_ready)
    monkeypatch.setattr(service, "_replay_projection_once", _replay_projection_once)

    with pytest.raises(asyncio.CancelledError):
        await service._replay_loop()

    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_projector_loop_continues_after_event_failure():
    first = _audit_event(ledger_offset=1, chain_partition="workspace:test")
    second = _audit_event(ledger_offset=2, chain_partition="workspace:test")
    ledger = _FakeLedger()
    relay = _StreamRelayProvider([first, second])

    class _Projection(_RecordingProjectionProvider):
        async def project_events(self, events: list[AuditEvent]) -> None:
            await super().project_events(events)
            if events[0].ledger_offset == 1:
                raise RuntimeError("temporary projection failure")

    projection = _Projection()
    service = AuditService(
        ledger=ledger,
        relay_provider=relay,
        projection_provider=projection,
        archive_provider=NoopAuditArchiveProvider(),
    )

    with pytest.raises(asyncio.CancelledError):
        await service._projector_loop()


@pytest.mark.asyncio
async def test_record_http_audit_marks_agent_actor_and_system_agent_id():
    ledger = _DraftCaptureLedger()
    service = AuditService(
        ledger=ledger,
        relay_provider=NoopAuditRelayProvider(),
        projection_provider=NoopAuditProjectionProvider(),
        archive_provider=NoopAuditArchiveProvider(),
    )
    auth_context = AuthContext(
        kind="oidc",
        principal_type="agent",
        agent_identity_id=uuid4(),
        system_agent_id=uuid4(),
        issuer="http://issuer.test/realms/open-talon",
        subject="service-account-machine-reader",
        client_id="machine-reader",
        provider_key="keycloak",
        claims={"sub": "service-account-machine-reader", "azp": "machine-reader"},
    )
    request = SimpleNamespace(
        state=SimpleNamespace(
            auth_context=auth_context,
            correlation_id=None,
            request_id=uuid4(),
        ),
        path_params={},
        method="GET",
        url=SimpleNamespace(path="/v1/agents"),
        query_params={},
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
        scope={"route": SimpleNamespace(path="/v1/agents")},
    )

    await service.record_http_audit(
        request=request,
        response=SimpleNamespace(status_code=200),
        started_at=datetime.now(UTC),
    )

    assert len(ledger.drafts) == 1
    draft = ledger.drafts[0]
    assert draft.actor_type == "agent"
    assert draft.actor_id == auth_context.system_agent_id
    assert draft.system_agent_id == auth_context.system_agent_id
    assert draft.user_id is None


@pytest.mark.asyncio
async def test_build_audit_provider_registry_uses_noop_backends(monkeypatch):
    class _FakePool:
        def acquire(self):
            raise AssertionError("not used in provider registry construction")

    async def _get_pool():
        return _FakePool()

    monkeypatch.setattr("gateway_edge.services.audit_providers.get_pool", _get_pool)
    monkeypatch.setattr(settings, "audit_relay_provider", "none")
    monkeypatch.setattr(settings, "audit_projection_provider", "none")
    monkeypatch.setattr(settings, "audit_archive_provider", "none")
    monkeypatch.setattr(settings, "audit_clickhouse_enabled", False)

    registry = await build_audit_provider_registry(gateway_settings=settings)

    assert registry.relay.provider_name == "none"
    assert registry.projection.provider_name == "none"
    assert registry.archive.provider_name == "none"


@pytest.mark.asyncio
async def test_build_audit_provider_registry_uses_default_backends(monkeypatch):
    class _FakePool:
        def acquire(self):
            raise AssertionError("not used in provider registry construction")

    async def _get_pool():
        return _FakePool()

    monkeypatch.setattr("gateway_edge.services.audit_providers.get_pool", _get_pool)
    monkeypatch.setattr(settings, "audit_relay_provider", "kafka")
    monkeypatch.setattr(settings, "audit_projection_provider", "clickhouse")
    monkeypatch.setattr(settings, "audit_archive_provider", "minio")
    monkeypatch.setattr(settings, "audit_clickhouse_enabled", True)

    registry = await build_audit_provider_registry(gateway_settings=settings)

    assert registry.relay.provider_name == "kafka"
    assert registry.projection.provider_name == "clickhouse"
    assert registry.archive.provider_name == "minio"
