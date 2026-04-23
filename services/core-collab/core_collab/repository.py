from __future__ import annotations

import asyncio
from collections.abc import Sequence
import hashlib
import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from open_talon_contracts.log_management import RotationPolicy, append_bytes_with_rotation
from open_talon_contracts.observability import (
    ObservabilityProvider,
    build_observability_provider_from_env,
)
from open_talon_contracts.telemetry import TelemetryContext, telemetry_metadata

from .contracts import (
    ActorRef,
    AgentConfiguration,
    AgentDefinition,
    AgentIdentity,
    AgentInternalToolBinding,
    AgentEndpoint,
    AgentHarness,
    AgentInteractionContract,
    Artifact,
    AuditChainVerificationResult,
    AuditEvent,
    AuditEventDraft,
    AuditEventPage,
    AssetLink,
    AgentRoleBinding,
    EventEnvelope,
    GitRepository,
    GeneratedToolManifest,
    GeneratedToolValidationReport,
    InteractionAnswer,
    InteractionQuestion,
    InteractionRequest,
    InteractionRequestDetail,
    InteractionRequestTarget,
    HumanRoleBinding,
    IamRoleDefinition,
    Membership,
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderRecord,
    LlmProviderDefinition,
    Organization,
    OrganizationMembership,
    ParticipantProfile,
    ResolvedAssetBinding,
    Run,
    RunStep,
    SystemToolDefinition,
    Task,
    ToolCall,
    ToolCallResult,
    ToolGenerationRequest,
    ToolGenerationRevision,
    ToolExecutionBinding,
    ToolParameterContract,
    Thread,
    TimelineMessage,
    WorkspaceCommunicationLogEntry,
    WorkspaceCommunicationLogPage,
    Workspace,
    WorkspaceAsset,
    WorkspaceAssetVersion,
    WorkspaceHarness,
    WorkspaceTool,
)
from .migrations import apply_pending_migrations


logger = logging.getLogger(__name__)


class UserRecord:
    def __init__(
        self,
        *,
        user_id: UUID,
        display_name: str,
        created_at,
        updated_at,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.user_id = user_id
        self.display_name = display_name
        self.created_at = created_at
        self.updated_at = updated_at
        self.metadata = metadata or {}


class AuthIdentityRecord:
    def __init__(
        self,
        *,
        user_id: UUID,
        issuer: str,
        subject: str,
        email: str | None,
        display_name: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.user_id = user_id
        self.issuer = issuer
        self.subject = subject
        self.email = email
        self.display_name = display_name
        self.metadata = metadata or {}


class CollaborationRepository:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        communication_log_dir: str | Path | None = None,
        observability: ObservabilityProvider | None = None,
    ) -> None:
        self._pool = pool
        self._communication_log_dir = (
            Path(communication_log_dir).expanduser()
            if communication_log_dir is not None
            else None
        )
        self._observability = observability or build_observability_provider_from_env(
            service_name="core-collab"
        )
        self._communication_log_policy = RotationPolicy.from_env(
            max_bytes_var="OPEN_TALON_COMMUNICATION_LOG_MAX_BYTES",
            backup_count_var="OPEN_TALON_COMMUNICATION_LOG_BACKUP_COUNT",
            default_max_bytes=20 * 1024 * 1024,
            default_backup_count=10,
        )

    async def setup_schema(self) -> None:
        await apply_pending_migrations(self._pool)

    async def next_workspace_sequence(
        self, conn: asyncpg.Connection, workspace_id: UUID
    ) -> int:
        return await conn.fetchval(
            """
            INSERT INTO workspace_sequences (workspace_id, last_sequence)
            VALUES ($1, 1)
            ON CONFLICT (workspace_id) DO UPDATE
                SET last_sequence = workspace_sequences.last_sequence + 1
            RETURNING last_sequence
            """,
            workspace_id,
        )

    async def next_thread_sequence(
        self, conn: asyncpg.Connection, thread_id: UUID
    ) -> int:
        return await conn.fetchval(
            """
            INSERT INTO thread_sequences (thread_id, last_sequence)
            VALUES ($1, 1)
            ON CONFLICT (thread_id) DO UPDATE
                SET last_sequence = thread_sequences.last_sequence + 1
            RETURNING last_sequence
            """,
            thread_id,
        )

    async def record_event(
        self, conn: asyncpg.Connection, event: EventEnvelope
    ) -> None:
        await conn.execute(
            """
            INSERT INTO processed_event_ids (event_id)
            VALUES ($1)
            ON CONFLICT (event_id) DO NOTHING
            """,
            event.event_id,
        )
        result = await conn.execute(
            """
            INSERT INTO collab_event_log (
                event_id,
                schema_version,
                event_type,
                workspace_id,
                thread_id,
                actor_type,
                actor_id,
                target_type,
                target_id,
                visibility,
                correlation_id,
                causation_id,
                sequence,
                payload,
                created_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15
            )
            ON CONFLICT (event_id) DO NOTHING
            """,
            event.event_id,
            event.schema_version,
            event.event_type,
            event.workspace_id,
            event.thread_id,
            event.actor.type,
            event.actor.id,
            event.target.type,
            event.target.id,
            event.visibility,
            event.correlation_id,
            event.causation_id,
            event.sequence,
            self._json_dumps(event.payload),
            event.timestamp,
        )
        if result.endswith("1"):
            draft = await self._audit_draft_from_event(conn, event)
            await self.append_audit_event(conn, draft)
            self._record_collaboration_event_observation(event)

    async def append_audit_event(
        self,
        conn: asyncpg.Connection,
        draft: AuditEventDraft,
    ) -> AuditEvent:
        head_row = await conn.fetchrow(
            """
            SELECT last_sequence, last_event_hash
            FROM audit_chain_heads
            WHERE chain_partition = $1
            FOR UPDATE
            """,
            draft.chain_partition,
        )
        if head_row is None:
            chain_sequence = 1
            prev_hash = "0" * 64
        else:
            chain_sequence = int(head_row["last_sequence"]) + 1
            prev_hash = str(head_row["last_event_hash"])
        event_hash = self._build_audit_event_hash(draft, prev_hash)
        row = await conn.fetchrow(
            """
            INSERT INTO audit_event_ledger (
                audit_event_id,
                occurred_at,
                recorded_at,
                scope_type,
                workspace_id,
                thread_id,
                actor_type,
                actor_id,
                user_id,
                system_agent_id,
                source_service,
                source_component,
                action_category,
                action_name,
                target_type,
                target_id,
                outcome,
                correlation_id,
                causation_id,
                request_id,
                trace_id,
                error_code,
                error_class,
                error_message_redacted,
                payload_mode,
                payload_hash,
                payload_ref,
                payload_size_bytes,
                metadata,
                chain_partition,
                chain_sequence,
                prev_hash,
                event_hash
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
                $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22,
                $23, $24, $25, $26, $27, $28, $29, $30, $31, $32, $33
            )
            RETURNING *
            """,
            draft.audit_event_id,
            draft.occurred_at,
            draft.recorded_at,
            draft.scope_type,
            draft.workspace_id,
            draft.thread_id,
            draft.actor_type,
            draft.actor_id,
            draft.user_id,
            draft.system_agent_id,
            draft.source_service,
            draft.source_component,
            draft.action_category,
            draft.action_name,
            draft.target_type,
            draft.target_id,
            draft.outcome,
            draft.correlation_id,
            draft.causation_id,
            draft.request_id,
            draft.trace_id,
            draft.error_code,
            draft.error_class,
            draft.error_message_redacted,
            draft.payload_mode,
            draft.payload_hash,
            draft.payload_ref,
            draft.payload_size_bytes,
            self._json_dumps(draft.metadata),
            draft.chain_partition,
            chain_sequence,
            prev_hash,
            event_hash,
        )
        await conn.execute(
            """
            INSERT INTO audit_chain_heads (
                chain_partition,
                last_sequence,
                last_event_hash,
                updated_at
            )
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (chain_partition) DO UPDATE
                SET last_sequence = EXCLUDED.last_sequence,
                    last_event_hash = EXCLUDED.last_event_hash,
                    updated_at = EXCLUDED.updated_at
            """,
            draft.chain_partition,
            chain_sequence,
            event_hash,
        )
        event = self._audit_event_from_row(row)
        if event is not None:
            self._record_audit_event_observation(event)
        return event

    def _record_collaboration_event_observation(self, event: EventEnvelope) -> None:
        actor_participant_id = (
            event.actor.id if event.actor.type in {"human", "agent"} else None
        )
        context = TelemetryContext(
            source_service="core-collab",
            source_component="repository",
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            workspace_id=event.workspace_id,
            thread_id=event.thread_id,
            participant_id=actor_participant_id,
            metadata={
                "event_type": event.event_type,
                "actor_type": event.actor.type,
                "actor_id": str(event.actor.id),
                "target_type": event.target.type,
                "target_id": str(event.target.id),
                "visibility": event.visibility,
                "sequence": event.sequence,
            },
        )
        self._record_observability_event(
            name="collaboration.event.recorded",
            input={
                "event_id": str(event.event_id),
                "payload": event.payload,
            },
            metadata=telemetry_metadata(context),
        )

    def _record_audit_event_observation(self, event: AuditEvent) -> None:
        context = TelemetryContext(
            source_service=event.source_service,
            source_component=event.source_component,
            request_id=event.request_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            organization_id=event.organization_id,
            workspace_id=event.workspace_id,
            thread_id=event.thread_id,
            system_agent_id=event.system_agent_id,
            trace_id=event.trace_id,
            metadata={
                "action_category": event.action_category,
                "action_name": event.action_name,
                "target_type": event.target_type,
                "target_id": str(event.target_id) if event.target_id is not None else None,
                "outcome": event.outcome,
                "chain_partition": event.chain_partition,
                "chain_sequence": event.chain_sequence,
            },
        )
        self._record_observability_event(
            name="audit.event.recorded",
            input={"audit_event_id": str(event.audit_event_id)},
            metadata=telemetry_metadata(context),
        )

    def _record_observability_event(
        self,
        *,
        name: str,
        input: Any | None,
        metadata: dict[str, Any],
    ) -> None:
        try:
            self._observability.record_event(name=name, input=input, metadata=metadata)
            self._observability.flush()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to record observability event name=%s", name)

    async def get_audit_event(self, audit_event_id: UUID) -> AuditEvent | None:
        row = await self._pool.fetchrow(
            """
            SELECT *
            FROM audit_event_ledger
            WHERE audit_event_id = $1
            """,
            audit_event_id,
        )
        return self._audit_event_from_row(row) if row else None

    async def list_audit_events(
        self,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        thread_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        actor_system_agent_id: UUID | None = None,
        action_prefix: str | None = None,
        outcome: str | None = None,
        target_type: str | None = None,
        target_id: UUID | None = None,
        correlation_id: UUID | None = None,
        request_id: UUID | None = None,
        occurred_after=None,
        occurred_before=None,
        limit: int = 100,
    ) -> AuditEventPage:
        rows = await self._pool.fetch(
            """
            SELECT *
            FROM audit_event_ledger
            WHERE ($1::uuid IS NULL OR organization_id = $1)
              AND ($2::uuid IS NULL OR workspace_id = $2)
              AND ($3::uuid IS NULL OR thread_id = $3)
              AND ($4::uuid IS NULL OR user_id = $4)
              AND ($5::uuid IS NULL OR system_agent_id = $5)
              AND ($6::text IS NULL OR action_name LIKE $6 || '%')
              AND ($7::text IS NULL OR outcome = $7)
              AND ($8::text IS NULL OR target_type = $8)
              AND ($9::uuid IS NULL OR target_id = $9)
              AND ($10::uuid IS NULL OR correlation_id = $10)
              AND ($11::uuid IS NULL OR request_id = $11)
              AND ($12::timestamptz IS NULL OR occurred_at >= $12)
              AND ($13::timestamptz IS NULL OR occurred_at <= $13)
            ORDER BY recorded_at DESC, ledger_offset DESC
            LIMIT $14
            """,
            organization_id,
            workspace_id,
            thread_id,
            actor_user_id,
            actor_system_agent_id,
            action_prefix,
            outcome,
            target_type,
            target_id,
            correlation_id,
            request_id,
            occurred_after,
            occurred_before,
            limit,
        )
        events = [self._audit_event_from_row(row) for row in rows]
        return AuditEventPage(events=events, total_count=len(events))

    async def list_audit_events_pending_export(
        self,
        *,
        consumer_name: str,
        limit: int = 100,
    ) -> list[AuditEvent]:
        rows = await self._pool.fetch(
            """
            SELECT ledger.*
            FROM audit_event_ledger AS ledger
            LEFT JOIN audit_export_checkpoints AS checkpoint
              ON checkpoint.consumer_name = $1
            WHERE ledger.ledger_offset > COALESCE(checkpoint.last_ledger_offset, 0)
            ORDER BY ledger.ledger_offset ASC
            LIMIT $2
            """,
            consumer_name,
            limit,
        )
        return [self._audit_event_from_row(row) for row in rows]

    async def advance_audit_export_checkpoint(
        self,
        conn: asyncpg.Connection,
        *,
        consumer_name: str,
        last_ledger_offset: int,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO audit_export_checkpoints (
                consumer_name,
                last_ledger_offset,
                last_exported_at,
                updated_at,
                metadata
            )
            VALUES ($1, $2, NOW(), NOW(), $3)
            ON CONFLICT (consumer_name) DO UPDATE
                SET last_ledger_offset = GREATEST(
                        audit_export_checkpoints.last_ledger_offset,
                        EXCLUDED.last_ledger_offset
                    ),
                    last_exported_at = EXCLUDED.last_exported_at,
                    updated_at = EXCLUDED.updated_at,
                    metadata = audit_export_checkpoints.metadata || EXCLUDED.metadata
            """,
            consumer_name,
            last_ledger_offset,
            self._json_dumps(metadata or {}),
        )

    async def list_audit_chain_heads(self) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT chain_partition, last_sequence, last_event_hash, updated_at
            FROM audit_chain_heads
            ORDER BY chain_partition ASC
            """
        )
        return [dict(row) for row in rows]

    async def list_audit_events_for_retention(
        self,
        *,
        chain_partition: str,
        cutoff_recorded_at,
        limit: int,
    ) -> list[AuditEvent]:
        rows = await self._pool.fetch(
            """
            SELECT *
            FROM audit_event_ledger
            WHERE chain_partition = $1
              AND recorded_at < $2
            ORDER BY ledger_offset ASC
            LIMIT $3
            """,
            chain_partition,
            cutoff_recorded_at,
            limit,
        )
        return [self._audit_event_from_row(row) for row in rows]

    async def list_audit_retention_candidates(
        self,
        *,
        cutoff_recorded_at,
    ) -> list[dict[str, Any]]:
        rows = await self._pool.fetch(
            """
            SELECT DISTINCT chain_partition
            FROM audit_event_ledger
            WHERE recorded_at < $1
            ORDER BY chain_partition ASC
            """,
            cutoff_recorded_at,
        )
        return [dict(row) for row in rows]

    async def record_audit_retention_snapshot(
        self,
        conn: asyncpg.Connection,
        *,
        chain_partition: str,
        cutoff_recorded_at,
        last_pruned_sequence: int,
        last_pruned_event_hash: str,
        object_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO audit_retention_snapshots (
                snapshot_id,
                chain_partition,
                cutoff_recorded_at,
                last_pruned_sequence,
                last_pruned_event_hash,
                object_key,
                metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (chain_partition, cutoff_recorded_at) DO UPDATE
                SET last_pruned_sequence = EXCLUDED.last_pruned_sequence,
                    last_pruned_event_hash = EXCLUDED.last_pruned_event_hash,
                    object_key = EXCLUDED.object_key,
                    metadata = audit_retention_snapshots.metadata || EXCLUDED.metadata,
                    created_at = NOW()
            """,
            uuid4(),
            chain_partition,
            cutoff_recorded_at,
            last_pruned_sequence,
            last_pruned_event_hash,
            object_key,
            self._json_dumps(metadata or {}),
        )

    async def fetch_latest_audit_retention_snapshot(
        self,
        chain_partition: str,
    ) -> dict[str, Any] | None:
        row = await self._pool.fetchrow(
            """
            SELECT chain_partition,
                   cutoff_recorded_at,
                   last_pruned_sequence,
                   last_pruned_event_hash,
                   object_key,
                   metadata,
                   created_at
            FROM audit_retention_snapshots
            WHERE chain_partition = $1
            ORDER BY created_at DESC, cutoff_recorded_at DESC
            LIMIT 1
            """,
            chain_partition,
        )
        if row is None:
            return None
        data = dict(row)
        data["metadata"] = self._json_value(row["metadata"], default={})
        return data

    async def prune_audit_events(
        self,
        conn: asyncpg.Connection,
        *,
        chain_partition: str,
        max_ledger_offset: int,
    ) -> int:
        result = await conn.execute(
            """
            DELETE FROM audit_event_ledger
            WHERE chain_partition = $1
              AND ledger_offset <= $2
            """,
            chain_partition,
            max_ledger_offset,
        )
        return int(result.split()[-1])

    async def verify_audit_chain(
        self,
        chain_partition: str,
    ) -> AuditChainVerificationResult:
        snapshot = await self.fetch_latest_audit_retention_snapshot(chain_partition)
        rows = await self._pool.fetch(
            """
            SELECT *
            FROM audit_event_ledger
            WHERE chain_partition = $1
            ORDER BY chain_sequence ASC
            """,
            chain_partition,
        )
        if snapshot is None:
            expected_sequence = 1
            prev_hash = "0" * 64
        else:
            expected_sequence = int(snapshot["last_pruned_sequence"]) + 1
            prev_hash = str(snapshot["last_pruned_event_hash"])
        checked = 0
        for row in rows:
            event = self._audit_event_from_row(row)
            if event.chain_sequence != expected_sequence:
                return AuditChainVerificationResult(
                    chain_partition=chain_partition,
                    verified=False,
                    checked_events=checked,
                    expected_sequence=expected_sequence,
                    actual_sequence=event.chain_sequence,
                    expected_prev_hash=prev_hash,
                    actual_prev_hash=event.prev_hash,
                    failing_audit_event_id=event.audit_event_id,
                    detail="Audit chain sequence gap detected",
                )
            if event.prev_hash != prev_hash:
                return AuditChainVerificationResult(
                    chain_partition=chain_partition,
                    verified=False,
                    checked_events=checked,
                    expected_sequence=expected_sequence,
                    actual_sequence=event.chain_sequence,
                    expected_prev_hash=prev_hash,
                    actual_prev_hash=event.prev_hash,
                    failing_audit_event_id=event.audit_event_id,
                    detail="Audit chain previous hash mismatch",
                )
            expected_hash = self._build_audit_event_hash(event, prev_hash)
            if event.event_hash != expected_hash:
                return AuditChainVerificationResult(
                    chain_partition=chain_partition,
                    verified=False,
                    checked_events=checked,
                    expected_sequence=expected_sequence,
                    actual_sequence=event.chain_sequence,
                    expected_prev_hash=prev_hash,
                    actual_prev_hash=event.prev_hash,
                    failing_audit_event_id=event.audit_event_id,
                    detail="Audit chain event hash mismatch",
                )
            checked += 1
            expected_sequence += 1
            prev_hash = event.event_hash
        return AuditChainVerificationResult(
            chain_partition=chain_partition,
            verified=True,
            checked_events=checked,
            detail="Audit chain verified successfully",
        )

    async def upsert_workspace(
        self, conn: asyncpg.Connection, workspace: Workspace
    ) -> None:
        organization_id = workspace.organization_id or await self._default_organization_id(conn)
        await conn.execute(
            """
            INSERT INTO workspaces (
                workspace_id, organization_id, name, description, owner_user_id, harness, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (workspace_id) DO UPDATE
                SET organization_id = EXCLUDED.organization_id,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    owner_user_id = EXCLUDED.owner_user_id,
                    harness = EXCLUDED.harness,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            workspace.workspace_id,
            organization_id,
            workspace.name,
            workspace.description,
            workspace.owner_user_id,
            (
                self._json_dumps(workspace.harness.model_dump(mode="json"))
                if workspace.harness is not None
                else None
            ),
            workspace.created_at,
            workspace.updated_at,
            self._json_dumps(workspace.metadata),
        )

    async def upsert_organization(
        self,
        conn: asyncpg.Connection,
        organization: Organization,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO organizations (
                organization_id, slug, name, description, created_by, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (organization_id) DO UPDATE
                SET slug = EXCLUDED.slug,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            organization.organization_id,
            organization.slug,
            organization.name,
            organization.description,
            organization.created_by,
            organization.created_at,
            organization.updated_at,
            self._json_dumps(organization.metadata),
        )

    async def fetch_organization(self, organization_id: UUID) -> Organization | None:
        row = await self._pool.fetchrow(
            """
            SELECT organization_id, slug, name, description, created_by, created_at, updated_at, metadata
            FROM organizations
            WHERE organization_id = $1
            """,
            organization_id,
        )
        return self._organization_from_row(row) if row else None

    async def fetch_organization_by_slug(self, slug: str) -> Organization | None:
        row = await self._pool.fetchrow(
            """
            SELECT organization_id, slug, name, description, created_by, created_at, updated_at, metadata
            FROM organizations
            WHERE slug = $1
            """,
            slug,
        )
        return self._organization_from_row(row) if row else None

    async def list_organizations(self) -> list[Organization]:
        rows = await self._pool.fetch(
            """
            SELECT organization_id, slug, name, description, created_by, created_at, updated_at, metadata
            FROM organizations
            ORDER BY created_at ASC
            """
        )
        return [self._organization_from_row(row) for row in rows]

    async def list_organizations_for_user(self, user_id: UUID) -> list[Organization]:
        rows = await self._pool.fetch(
            """
            SELECT o.organization_id, o.slug, o.name, o.description, o.created_by,
                   o.created_at, o.updated_at, o.metadata
            FROM organizations AS o
            JOIN organization_memberships AS membership
              ON membership.organization_id = o.organization_id
            WHERE membership.user_id = $1
            ORDER BY o.created_at ASC
            """,
            user_id,
        )
        return [self._organization_from_row(row) for row in rows]

    async def fetch_organization_membership(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> OrganizationMembership | None:
        row = await self._pool.fetchrow(
            """
            SELECT organization_id, user_id, role, joined_at, updated_at, metadata
            FROM organization_memberships
            WHERE organization_id = $1
              AND user_id = $2
            """,
            organization_id,
            user_id,
        )
        return self._organization_membership_from_row(row) if row else None

    async def list_organization_memberships(
        self,
        organization_id: UUID,
    ) -> list[OrganizationMembership]:
        rows = await self._pool.fetch(
            """
            SELECT organization_id, user_id, role, joined_at, updated_at, metadata
            FROM organization_memberships
            WHERE organization_id = $1
            ORDER BY joined_at ASC, user_id ASC
            """,
            organization_id,
        )
        return [self._organization_membership_from_row(row) for row in rows]

    async def upsert_organization_membership(
        self,
        conn: asyncpg.Connection,
        membership: OrganizationMembership,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO organization_memberships (
                organization_id, user_id, role, joined_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (organization_id, user_id) DO UPDATE
                SET role = EXCLUDED.role,
                    updated_at = EXCLUDED.updated_at,
                    metadata = organization_memberships.metadata || EXCLUDED.metadata
            """,
            membership.organization_id,
            membership.user_id,
            membership.role,
            membership.joined_at,
            membership.updated_at,
            self._json_dumps(membership.metadata),
        )

    async def delete_organization_membership(
        self,
        conn: asyncpg.Connection,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        result = await conn.execute(
            """
            DELETE FROM organization_memberships
            WHERE organization_id = $1
              AND user_id = $2
            """,
            organization_id,
            user_id,
        )
        return result.endswith("1")

    async def remove_user_participants_for_organization(
        self,
        conn: asyncpg.Connection,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> None:
        await conn.execute(
            """
            UPDATE memberships AS membership
            SET left_at = NOW()
            FROM participants AS participant
            JOIN workspaces AS workspace
              ON workspace.workspace_id = participant.workspace_id
            WHERE membership.workspace_id = participant.workspace_id
              AND membership.participant_id = participant.participant_id
              AND membership.left_at IS NULL
              AND workspace.organization_id = $1
              AND participant.user_id = $2
            """,
            organization_id,
            user_id,
        )
        await conn.execute(
            """
            DELETE FROM participants AS participant
            USING workspaces AS workspace
            WHERE participant.workspace_id = workspace.workspace_id
              AND workspace.organization_id = $1
              AND participant.user_id = $2
            """,
            organization_id,
            user_id,
        )

    async def upsert_user(
        self, conn: asyncpg.Connection, user: UserRecord
    ) -> None:
        await conn.execute(
            """
            INSERT INTO users (user_id, display_name, metadata, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (user_id) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    metadata = users.metadata || EXCLUDED.metadata,
                    updated_at = EXCLUDED.updated_at
            """,
            user.user_id,
            user.display_name,
            self._json_dumps(user.metadata),
            user.created_at,
            user.updated_at,
        )

    async def fetch_user(self, user_id: UUID) -> UserRecord | None:
        row = await self._pool.fetchrow(
            """
            SELECT user_id, display_name, metadata, created_at, updated_at
            FROM users
            WHERE user_id = $1
            """,
            user_id,
        )
        return self._user_from_row(row) if row else None

    async def fetch_auth_identity(
        self,
        issuer: str,
        subject: str,
    ) -> AuthIdentityRecord | None:
        row = await self._pool.fetchrow(
            """
            SELECT user_id, issuer, subject, email, display_name, metadata
            FROM auth_identities
            WHERE issuer = $1
              AND subject = $2
            """,
            issuer,
            subject,
        )
        return self._auth_identity_from_row(row) if row else None

    async def upsert_auth_identity(
        self,
        conn: asyncpg.Connection,
        identity: AuthIdentityRecord,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO auth_identities (
                user_id, issuer, subject, email, display_name, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (issuer, subject) DO UPDATE
                SET user_id = EXCLUDED.user_id,
                    email = EXCLUDED.email,
                    display_name = EXCLUDED.display_name,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
            """,
            identity.user_id,
            identity.issuer,
            identity.subject,
            identity.email,
            identity.display_name,
            self._json_dumps(identity.metadata),
        )

    async def list_iam_role_definitions(
        self,
        *,
        subject_kind: str,
        scope: str | None = None,
        organization_id: UUID | None = None,
    ) -> list[IamRoleDefinition]:
        rows = await self._pool.fetch(
            """
            SELECT role_id, scope, subject_kind, organization_id, name, description,
                   permissions, created_at, updated_at, metadata
            FROM iam_role_definitions
            WHERE subject_kind = $1
              AND ($2::text IS NULL OR scope = $2)
              AND (
                    $2::text IS NULL
                    OR ($2 = 'global' AND organization_id IS NULL)
                    OR ($2 = 'organization' AND organization_id = $3)
                  )
            ORDER BY scope ASC, name ASC
            """,
            subject_kind,
            scope,
            organization_id,
        )
        return [self._iam_role_definition_from_row(row) for row in rows]

    async def fetch_iam_role_definition(self, role_id: UUID) -> IamRoleDefinition | None:
        row = await self._pool.fetchrow(
            """
            SELECT role_id, scope, subject_kind, organization_id, name, description,
                   permissions, created_at, updated_at, metadata
            FROM iam_role_definitions
            WHERE role_id = $1
            """,
            role_id,
        )
        return self._iam_role_definition_from_row(row) if row else None

    async def upsert_iam_role_definition(
        self,
        conn: asyncpg.Connection,
        role: IamRoleDefinition,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO iam_role_definitions (
                role_id, scope, subject_kind, organization_id, name, description,
                permissions, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (role_id) DO UPDATE
                SET scope = EXCLUDED.scope,
                    subject_kind = EXCLUDED.subject_kind,
                    organization_id = EXCLUDED.organization_id,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    permissions = EXCLUDED.permissions,
                    updated_at = EXCLUDED.updated_at,
                    metadata = iam_role_definitions.metadata || EXCLUDED.metadata
            """,
            role.role_id,
            role.scope,
            role.subject_kind,
            role.organization_id,
            role.name,
            role.description,
            self._json_dumps(role.permissions),
            role.created_at,
            role.updated_at,
            self._json_dumps(role.metadata),
        )

    async def delete_iam_role_definition(
        self,
        conn: asyncpg.Connection,
        *,
        role_id: UUID,
    ) -> bool:
        result = await conn.execute(
            """
            DELETE FROM iam_role_definitions
            WHERE role_id = $1
            """,
            role_id,
        )
        return result.endswith("1")

    async def list_human_role_bindings(
        self,
        *,
        user_id: UUID,
    ) -> list[HumanRoleBinding]:
        rows = await self._pool.fetch(
            """
            SELECT user_id, role_id, created_at, metadata
            FROM human_role_bindings
            WHERE user_id = $1
            ORDER BY created_at ASC, role_id ASC
            """,
            user_id,
        )
        return [self._human_role_binding_from_row(row) for row in rows]

    async def list_human_roles_for_user(
        self,
        *,
        user_id: UUID,
        organization_id: UUID | None = None,
    ) -> list[IamRoleDefinition]:
        rows = await self._pool.fetch(
            """
            SELECT role.role_id, role.scope, role.subject_kind, role.organization_id, role.name,
                   role.description, role.permissions, role.created_at, role.updated_at, role.metadata
            FROM human_role_bindings AS binding
            JOIN iam_role_definitions AS role ON role.role_id = binding.role_id
            WHERE binding.user_id = $1
              AND role.subject_kind = 'human'
              AND (role.scope = 'global' OR role.organization_id = $2)
            ORDER BY role.scope ASC, role.name ASC
            """,
            user_id,
            organization_id,
        )
        return [self._iam_role_definition_from_row(row) for row in rows]

    async def bind_human_role(
        self,
        conn: asyncpg.Connection,
        *,
        user_id: UUID,
        role_id: UUID,
        created_at,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO human_role_bindings (user_id, role_id, created_at, metadata)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, role_id) DO UPDATE
                SET metadata = human_role_bindings.metadata || EXCLUDED.metadata
            """,
            user_id,
            role_id,
            created_at,
            self._json_dumps(metadata or {}),
        )

    async def unbind_human_role(
        self,
        conn: asyncpg.Connection,
        *,
        user_id: UUID,
        role_id: UUID,
    ) -> bool:
        result = await conn.execute(
            """
            DELETE FROM human_role_bindings
            WHERE user_id = $1
              AND role_id = $2
            """,
            user_id,
            role_id,
        )
        return result.endswith("1")

    async def list_agent_identities(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
    ) -> list[AgentIdentity]:
        rows = await self._pool.fetch(
            """
            SELECT agent_identity_id, system_agent_id, scope, organization_id, provider_key, issuer,
                   external_subject, client_id, status, secret_ref, last_authenticated_at,
                   created_at, updated_at, metadata
            FROM agent_identities
            WHERE ($1::text IS NULL OR scope = $1)
              AND (
                    $1::text IS NULL
                    OR ($1 = 'global' AND organization_id IS NULL)
                    OR ($1 = 'organization' AND organization_id = $2)
                  )
            ORDER BY created_at ASC, agent_identity_id ASC
            """,
            scope,
            organization_id,
        )
        return [self._agent_identity_from_row(row) for row in rows]

    async def fetch_agent_identity(self, agent_identity_id: UUID) -> AgentIdentity | None:
        row = await self._pool.fetchrow(
            """
            SELECT agent_identity_id, system_agent_id, scope, organization_id, provider_key, issuer,
                   external_subject, client_id, status, secret_ref, last_authenticated_at,
                   created_at, updated_at, metadata
            FROM agent_identities
            WHERE agent_identity_id = $1
            """,
            agent_identity_id,
        )
        return self._agent_identity_from_row(row) if row else None

    async def fetch_agent_identity_by_client(
        self,
        *,
        provider_key: str,
        issuer: str,
        client_id: str,
    ) -> AgentIdentity | None:
        row = await self._pool.fetchrow(
            """
            SELECT agent_identity_id, system_agent_id, scope, organization_id, provider_key, issuer,
                   external_subject, client_id, status, secret_ref, last_authenticated_at,
                   created_at, updated_at, metadata
            FROM agent_identities
            WHERE provider_key = $1
              AND issuer = $2
              AND client_id = $3
            """,
            provider_key,
            issuer,
            client_id,
        )
        return self._agent_identity_from_row(row) if row else None

    async def upsert_agent_identity(
        self,
        conn: asyncpg.Connection,
        identity: AgentIdentity,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO agent_identities (
                agent_identity_id, system_agent_id, scope, organization_id, provider_key,
                issuer, external_subject, client_id, status, secret_ref, last_authenticated_at,
                created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (agent_identity_id) DO UPDATE
                SET system_agent_id = EXCLUDED.system_agent_id,
                    scope = EXCLUDED.scope,
                    organization_id = EXCLUDED.organization_id,
                    provider_key = EXCLUDED.provider_key,
                    issuer = EXCLUDED.issuer,
                    external_subject = EXCLUDED.external_subject,
                    client_id = EXCLUDED.client_id,
                    status = EXCLUDED.status,
                    secret_ref = EXCLUDED.secret_ref,
                    last_authenticated_at = EXCLUDED.last_authenticated_at,
                    updated_at = EXCLUDED.updated_at,
                    metadata = agent_identities.metadata || EXCLUDED.metadata
            """,
            identity.agent_identity_id,
            identity.system_agent_id,
            identity.scope,
            identity.organization_id,
            identity.provider_key,
            identity.issuer,
            identity.external_subject,
            identity.client_id,
            identity.status,
            self._json_dumps(identity.secret_ref),
            identity.last_authenticated_at,
            identity.created_at,
            identity.updated_at,
            self._json_dumps(identity.metadata),
        )

    async def list_agent_role_bindings(
        self,
        *,
        agent_identity_id: UUID,
    ) -> list[AgentRoleBinding]:
        rows = await self._pool.fetch(
            """
            SELECT agent_identity_id, role_id, created_at, metadata
            FROM agent_role_bindings
            WHERE agent_identity_id = $1
            ORDER BY created_at ASC, role_id ASC
            """,
            agent_identity_id,
        )
        return [self._agent_role_binding_from_row(row) for row in rows]

    async def list_agent_roles_for_identity(
        self,
        *,
        agent_identity_id: UUID,
    ) -> list[IamRoleDefinition]:
        rows = await self._pool.fetch(
            """
            SELECT role.role_id, role.scope, role.subject_kind, role.organization_id, role.name,
                   role.description, role.permissions, role.created_at, role.updated_at, role.metadata
            FROM agent_role_bindings AS binding
            JOIN iam_role_definitions AS role ON role.role_id = binding.role_id
            WHERE binding.agent_identity_id = $1
              AND role.subject_kind = 'agent'
            ORDER BY role.scope ASC, role.name ASC
            """,
            agent_identity_id,
        )
        return [self._iam_role_definition_from_row(row) for row in rows]

    async def bind_agent_role(
        self,
        conn: asyncpg.Connection,
        *,
        agent_identity_id: UUID,
        role_id: UUID,
        created_at,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO agent_role_bindings (agent_identity_id, role_id, created_at, metadata)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (agent_identity_id, role_id) DO UPDATE
                SET metadata = agent_role_bindings.metadata || EXCLUDED.metadata
            """,
            agent_identity_id,
            role_id,
            created_at,
            self._json_dumps(metadata or {}),
        )

    async def unbind_agent_role(
        self,
        conn: asyncpg.Connection,
        *,
        agent_identity_id: UUID,
        role_id: UUID,
    ) -> bool:
        result = await conn.execute(
            """
            DELETE FROM agent_role_bindings
            WHERE agent_identity_id = $1
              AND role_id = $2
            """,
            agent_identity_id,
            role_id,
        )
        return result.endswith("1")

    async def upsert_system_agent(
        self, conn: asyncpg.Connection, agent: AgentDefinition
    ) -> None:
        await conn.execute(
            """
            INSERT INTO system_agents (
                agent_id, scope, organization_id, display_name, description, role, capabilities, endpoint,
                system_prompt, harness, interaction_contract, definition, created_by, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            ON CONFLICT (agent_id) DO UPDATE
                SET scope = EXCLUDED.scope,
                    organization_id = EXCLUDED.organization_id,
                    display_name = EXCLUDED.display_name,
                    description = EXCLUDED.description,
                    role = EXCLUDED.role,
                    capabilities = EXCLUDED.capabilities,
                    endpoint = EXCLUDED.endpoint,
                    system_prompt = EXCLUDED.system_prompt,
                    harness = EXCLUDED.harness,
                    interaction_contract = EXCLUDED.interaction_contract,
                    definition = EXCLUDED.definition,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            agent.agent_id,
            agent.scope,
            agent.organization_id,
            agent.display_name,
            agent.description,
            agent.role,
            self._json_dumps(agent.capabilities),
            self._json_dumps(agent.endpoint.model_dump(mode="json")),
            agent.system_prompt,
            (
                self._json_dumps(agent.harness.model_dump(mode="json"))
                if agent.harness is not None
                else None
            ),
            self._json_dumps(agent.interaction_contract.model_dump(mode="json")),
            self._json_dumps(agent.definition),
            agent.created_by,
            agent.created_at,
            agent.updated_at,
            self._json_dumps(agent.metadata),
        )

    async def upsert_system_tool(
        self, conn: asyncpg.Connection, tool: SystemToolDefinition
    ) -> None:
        await conn.execute(
            """
            INSERT INTO system_tools (
                tool_id, scope, organization_id, name, description, parameter_contract, input_schema,
                backend_kind, handler_ref, execution_profile, trust_level,
                created_by, created_at, updated_by, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
            ON CONFLICT (tool_id) DO UPDATE
                SET scope = EXCLUDED.scope,
                    organization_id = EXCLUDED.organization_id,
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    parameter_contract = EXCLUDED.parameter_contract,
                    input_schema = EXCLUDED.input_schema,
                    backend_kind = EXCLUDED.backend_kind,
                    handler_ref = EXCLUDED.handler_ref,
                    execution_profile = EXCLUDED.execution_profile,
                    trust_level = EXCLUDED.trust_level,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            tool.tool_id,
            tool.scope,
            tool.organization_id,
            tool.name,
            tool.description,
            self._json_dumps(tool.parameter_contract.model_dump(mode="json")),
            self._json_dumps(tool.input_schema),
            tool.execution.backend_kind,
            tool.execution.handler_ref,
            self._json_dumps(tool.execution.execution_profile),
            tool.execution.trust_level,
            tool.created_by,
            tool.created_at,
            tool.updated_by,
            tool.updated_at,
            self._json_dumps(tool.metadata),
        )

    async def upsert_llm_provider(
        self, conn: asyncpg.Connection, provider: LlmProviderDefinition
    ) -> None:
        await conn.execute(
            """
            INSERT INTO llm_providers (
                provider_id, scope, organization_id, engine_id, display_name, description, provider, endpoint_kind,
                url, default_model, capabilities, locality, priority, enabled, secret_config,
                created_by, created_at, updated_by, updated_at, metadata
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8,
                $9, $10, $11, $12, $13, $14, $15,
                $16, $17, $18, $19, $20
            )
            ON CONFLICT (provider_id) DO UPDATE
                SET scope = EXCLUDED.scope,
                    organization_id = EXCLUDED.organization_id,
                    engine_id = EXCLUDED.engine_id,
                    display_name = EXCLUDED.display_name,
                    description = EXCLUDED.description,
                    provider = EXCLUDED.provider,
                    endpoint_kind = EXCLUDED.endpoint_kind,
                    url = EXCLUDED.url,
                    default_model = EXCLUDED.default_model,
                    capabilities = EXCLUDED.capabilities,
                    locality = EXCLUDED.locality,
                    priority = EXCLUDED.priority,
                    enabled = EXCLUDED.enabled,
                    secret_config = EXCLUDED.secret_config,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            provider.provider_id,
            provider.scope,
            provider.organization_id,
            provider.engine_id,
            provider.display_name,
            provider.description,
            provider.provider,
            provider.endpoint_kind,
            provider.url,
            provider.default_model,
            self._json_dumps(provider.capabilities),
            provider.locality,
            provider.priority,
            provider.enabled,
            self._json_dumps(provider.secret_config),
            provider.created_by,
            provider.created_at,
            provider.updated_by,
            provider.updated_at,
            self._json_dumps(provider.metadata),
        )

    async def upsert_git_repository(
        self, conn: asyncpg.Connection, repository: GitRepository
    ) -> None:
        organization_id = repository.organization_id
        if organization_id is None and repository.workspace_id is not None:
            organization_id = await self._workspace_organization_id(
                conn,
                repository.workspace_id,
            )
        if organization_id is None and repository.scope == "organization":
            organization_id = await self._default_organization_id(conn)
        await conn.execute(
            """
            INSERT INTO git_repositories (
                repo_id, organization_id, workspace_id, scope, name, forgejo_url, clone_url, local_path,
                default_branch, created_by, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (repo_id) DO UPDATE
                SET organization_id = EXCLUDED.organization_id,
                    workspace_id = EXCLUDED.workspace_id,
                    scope = EXCLUDED.scope,
                    name = EXCLUDED.name,
                    forgejo_url = EXCLUDED.forgejo_url,
                    clone_url = EXCLUDED.clone_url,
                    local_path = EXCLUDED.local_path,
                    default_branch = EXCLUDED.default_branch,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            repository.repo_id,
            organization_id,
            repository.workspace_id,
            repository.scope,
            repository.name,
            repository.forgejo_url,
            repository.clone_url,
            repository.local_path,
            repository.default_branch,
            repository.created_by,
            repository.created_at,
            repository.updated_at,
            self._json_dumps(repository.metadata),
        )

    async def upsert_workspace_asset(
        self, conn: asyncpg.Connection, asset: WorkspaceAsset
    ) -> None:
        organization_id = asset.organization_id
        if organization_id is None and asset.workspace_id is not None:
            organization_id = await self._workspace_organization_id(conn, asset.workspace_id)
        if organization_id is None and asset.scope == "organization":
            organization_id = await self._default_organization_id(conn)
        await conn.execute(
            """
            INSERT INTO workspace_assets (
                asset_id, organization_id, workspace_id, scope, asset_type, logical_name, logical_path,
                title, description, created_by, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (asset_id) DO UPDATE
                SET organization_id = EXCLUDED.organization_id,
                    workspace_id = EXCLUDED.workspace_id,
                    scope = EXCLUDED.scope,
                    asset_type = EXCLUDED.asset_type,
                    logical_name = EXCLUDED.logical_name,
                    logical_path = EXCLUDED.logical_path,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            asset.asset_id,
            organization_id,
            asset.workspace_id,
            asset.scope,
            asset.asset_type,
            asset.logical_name,
            asset.logical_path,
            asset.title,
            asset.description,
            asset.created_by,
            asset.created_at,
            asset.updated_at,
            self._json_dumps(asset.metadata),
        )

    async def upsert_workspace_asset_version(
        self, conn: asyncpg.Connection, version: WorkspaceAssetVersion
    ) -> None:
        await conn.execute(
            """
            INSERT INTO workspace_asset_versions (
                asset_version_id, asset_id, version, source_kind, git_repository_id,
                git_revision, git_path, storage_backend, bucket, object_key, content_type,
                size_bytes, sha256, created_by, created_at, metadata
            )
            VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10, $11,
                $12, $13, $14, $15, $16
            )
            ON CONFLICT (asset_version_id) DO UPDATE
                SET version = EXCLUDED.version,
                    source_kind = EXCLUDED.source_kind,
                    git_repository_id = EXCLUDED.git_repository_id,
                    git_revision = EXCLUDED.git_revision,
                    git_path = EXCLUDED.git_path,
                    storage_backend = EXCLUDED.storage_backend,
                    bucket = EXCLUDED.bucket,
                    object_key = EXCLUDED.object_key,
                    content_type = EXCLUDED.content_type,
                    size_bytes = EXCLUDED.size_bytes,
                    sha256 = EXCLUDED.sha256,
                    metadata = EXCLUDED.metadata
            """,
            version.asset_version_id,
            version.asset_id,
            version.version,
            version.source_kind,
            version.git_repository_id,
            version.git_revision,
            version.git_path,
            version.storage_backend,
            version.bucket,
            version.object_key,
            version.content_type,
            version.size_bytes,
            version.sha256,
            version.created_by,
            version.created_at,
            self._json_dumps(version.metadata),
        )

    async def upsert_asset_link(
        self, conn: asyncpg.Connection, link: AssetLink
    ) -> None:
        organization_id = link.organization_id
        if organization_id is None and link.workspace_id is not None:
            organization_id = await self._workspace_organization_id(conn, link.workspace_id)
        if organization_id is None:
            organization_id = await self._asset_organization_id(conn, link.asset_id)
        await conn.execute(
            """
            INSERT INTO asset_links (
                link_id, asset_id, asset_version_id, organization_id, workspace_id, target_type,
                target_id, purpose, active, created_by, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (link_id) DO UPDATE
                SET asset_id = EXCLUDED.asset_id,
                    asset_version_id = EXCLUDED.asset_version_id,
                    organization_id = EXCLUDED.organization_id,
                    workspace_id = EXCLUDED.workspace_id,
                    target_type = EXCLUDED.target_type,
                    target_id = EXCLUDED.target_id,
                    purpose = EXCLUDED.purpose,
                    active = EXCLUDED.active,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            link.link_id,
            link.asset_id,
            link.asset_version_id,
            organization_id,
            link.workspace_id,
            link.target_type,
            link.target_id,
            link.purpose,
            link.active,
            link.created_by,
            link.created_at,
            link.updated_at,
            self._json_dumps(link.metadata),
        )

    async def deactivate_asset_links(
        self,
        conn: asyncpg.Connection,
        *,
        organization_id: UUID | None,
        workspace_id: UUID | None,
        target_type: str,
        target_id: UUID,
        purpose: str,
    ) -> None:
        await conn.execute(
            """
            UPDATE asset_links
            SET active = FALSE,
                updated_at = NOW()
            WHERE (
                    ($1::uuid IS NULL AND organization_id IS NULL)
                 OR organization_id = $1
            )
              AND (
                    ($2::uuid IS NULL AND workspace_id IS NULL)
                 OR workspace_id = $2
            )
              AND target_type = $3
              AND target_id = $4
              AND purpose = $5
              AND active = TRUE
            """,
            organization_id,
            workspace_id,
            target_type,
            target_id,
            purpose,
        )

    async def _default_organization_id(
        self,
        conn: asyncpg.Connection | asyncpg.Pool,
    ) -> UUID:
        row = await conn.fetchrow(
            """
            SELECT organization_id
            FROM organizations
            ORDER BY CASE WHEN slug = 'default' THEN 0 ELSE 1 END, created_at ASC
            LIMIT 1
            """
        )
        if row is None:
            raise ValueError("No organizations configured")
        return row["organization_id"]

    async def _workspace_organization_id(
        self,
        conn: asyncpg.Connection | asyncpg.Pool,
        workspace_id: UUID,
    ) -> UUID:
        row = await conn.fetchrow(
            """
            SELECT organization_id
            FROM workspaces
            WHERE workspace_id = $1
            """,
            workspace_id,
        )
        if row is None or row["organization_id"] is None:
            return await self._default_organization_id(conn)
        return row["organization_id"]

    async def _asset_organization_id(
        self,
        conn: asyncpg.Connection | asyncpg.Pool,
        asset_id: UUID,
    ) -> UUID | None:
        row = await conn.fetchrow(
            """
            SELECT organization_id
            FROM workspace_assets
            WHERE asset_id = $1
            """,
            asset_id,
        )
        return row["organization_id"] if row is not None else None

    async def _effective_organization_filter(
        self,
        *,
        organization_id: UUID | None,
        workspace_id: UUID | None = None,
        asset_id: UUID | None = None,
    ) -> UUID | None:
        if organization_id is not None:
            return organization_id
        if workspace_id is not None:
            return await self._workspace_organization_id(self._pool, workspace_id)
        if asset_id is not None:
            return await self._asset_organization_id(self._pool, asset_id)
        return None

    async def upsert_workspace_tool(
        self,
        conn: asyncpg.Connection,
        *,
        workspace_id: UUID,
        tool: WorkspaceTool,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO workspace_tools (
                workspace_id, tool_id, enabled, attached_by, attached_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (workspace_id, tool_id) DO UPDATE
                SET enabled = EXCLUDED.enabled,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            workspace_id,
            tool.tool_id,
            tool.enabled,
            tool.attached_by,
            tool.attached_at,
            tool.updated_at,
            self._json_dumps(tool.metadata),
        )

    async def upsert_agent_internal_tool_binding(
        self,
        conn: asyncpg.Connection,
        binding: AgentInternalToolBinding,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO agent_internal_tools (
                system_agent_id, tool_id, enabled, attached_by, attached_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (system_agent_id, tool_id) DO UPDATE
                SET enabled = EXCLUDED.enabled,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            binding.system_agent_id,
            binding.tool_id,
            binding.enabled,
            binding.attached_by,
            binding.attached_at,
            binding.updated_at,
            self._json_dumps(binding.metadata),
        )

    async def upsert_tool_generation_request(
        self,
        conn: asyncpg.Connection,
        request: ToolGenerationRequest,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO tool_generation_requests (
                request_id, organization_id, workspace_id, thread_id, requester_participant_id,
                requester_message_id, target_system_agent_id, requested_scope, status,
                target_tool_name, summary, final_tool_id, latest_revision_id, approved_by,
                approved_at, rejected_by, rejected_at, published_at, created_at, updated_at,
                metadata
            )
            VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15,
                $16, $17, $18, $19, $20,
                $21
            )
            ON CONFLICT (request_id) DO UPDATE
                SET requested_scope = EXCLUDED.requested_scope,
                    status = EXCLUDED.status,
                    target_tool_name = EXCLUDED.target_tool_name,
                    summary = EXCLUDED.summary,
                    final_tool_id = EXCLUDED.final_tool_id,
                    latest_revision_id = EXCLUDED.latest_revision_id,
                    approved_by = EXCLUDED.approved_by,
                    approved_at = EXCLUDED.approved_at,
                    rejected_by = EXCLUDED.rejected_by,
                    rejected_at = EXCLUDED.rejected_at,
                    published_at = EXCLUDED.published_at,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            request.request_id,
            request.organization_id,
            request.workspace_id,
            request.thread_id,
            request.requester_participant_id,
            request.requester_message_id,
            request.target_system_agent_id,
            request.requested_scope,
            request.status,
            request.target_tool_name,
            request.summary,
            request.final_tool_id,
            request.latest_revision_id,
            request.approved_by,
            request.approved_at,
            request.rejected_by,
            request.rejected_at,
            request.published_at,
            request.created_at,
            request.updated_at,
            self._json_dumps(request.metadata),
        )

    async def upsert_tool_generation_revision(
        self,
        conn: asyncpg.Connection,
        revision: ToolGenerationRevision,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO tool_generation_revisions (
                revision_id, request_id, revision_number, status, manifest, validation_report,
                source_asset_id, source_asset_version_id, manifest_asset_id, manifest_asset_version_id,
                report_asset_id, report_asset_version_id, image_ref, image_digest,
                created_by, created_at, updated_at, metadata
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10,
                $11, $12, $13, $14,
                $15, $16, $17, $18
            )
            ON CONFLICT (revision_id) DO UPDATE
                SET status = EXCLUDED.status,
                    manifest = EXCLUDED.manifest,
                    validation_report = EXCLUDED.validation_report,
                    source_asset_id = EXCLUDED.source_asset_id,
                    source_asset_version_id = EXCLUDED.source_asset_version_id,
                    manifest_asset_id = EXCLUDED.manifest_asset_id,
                    manifest_asset_version_id = EXCLUDED.manifest_asset_version_id,
                    report_asset_id = EXCLUDED.report_asset_id,
                    report_asset_version_id = EXCLUDED.report_asset_version_id,
                    image_ref = EXCLUDED.image_ref,
                    image_digest = EXCLUDED.image_digest,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            revision.revision_id,
            revision.request_id,
            revision.revision_number,
            revision.status,
            self._json_dumps(revision.manifest.model_dump(mode="json")),
            (
                self._json_dumps(revision.validation_report.model_dump(mode="json"))
                if revision.validation_report is not None
                else None
            ),
            revision.source_asset_id,
            revision.source_asset_version_id,
            revision.manifest_asset_id,
            revision.manifest_asset_version_id,
            revision.report_asset_id,
            revision.report_asset_version_id,
            revision.image_ref,
            revision.image_digest,
            revision.created_by,
            revision.created_at,
            revision.updated_at,
            self._json_dumps(revision.metadata),
        )

    async def next_tool_generation_revision_number(
        self,
        conn: asyncpg.Connection,
        request_id: UUID,
    ) -> int:
        value = await conn.fetchval(
            """
            SELECT COALESCE(MAX(revision_number), 0) + 1
            FROM tool_generation_revisions
            WHERE request_id = $1
            """,
            request_id,
        )
        return int(value or 1)

    async def delete_workspace_tool(
        self,
        conn: asyncpg.Connection,
        *,
        workspace_id: UUID,
        tool_id: UUID,
    ) -> bool:
        result = await conn.execute(
            """
            DELETE FROM workspace_tools
            WHERE workspace_id = $1
              AND tool_id = $2
            """,
            workspace_id,
            tool_id,
        )
        return result.endswith("1")

    async def delete_llm_provider(
        self,
        conn: asyncpg.Connection,
        *,
        provider_id: UUID,
    ) -> bool:
        result = await conn.execute(
            """
            DELETE FROM llm_providers
            WHERE provider_id = $1
            """,
            provider_id,
        )
        return result.endswith("1")

    async def delete_system_agent(
        self,
        conn: asyncpg.Connection,
        *,
        agent_id: UUID,
    ) -> bool:
        result = await conn.execute(
            """
            DELETE FROM system_agents
            WHERE agent_id = $1
            """,
            agent_id,
        )
        return result.endswith("1")

    async def delete_system_tool(
        self,
        conn: asyncpg.Connection,
        *,
        tool_id: UUID,
    ) -> bool:
        result = await conn.execute(
            """
            DELETE FROM system_tools
            WHERE tool_id = $1
            """,
            tool_id,
        )
        return result.endswith("1")

    async def delete_workspace(
        self, conn: asyncpg.Connection, workspace_id: UUID
    ) -> bool:
        result = await conn.execute(
            "DELETE FROM workspaces WHERE workspace_id = $1",
            workspace_id,
        )
        return result.endswith("1")

    async def delete_participant(
        self,
        conn: asyncpg.Connection,
        *,
        workspace_id: UUID,
        participant_id: UUID,
    ) -> bool:
        await conn.execute(
            """
            UPDATE memberships
            SET left_at = NOW()
            WHERE workspace_id = $1
              AND participant_id = $2
              AND left_at IS NULL
            """,
            workspace_id,
            participant_id,
        )
        result = await conn.execute(
            """
            DELETE FROM participants
            WHERE workspace_id = $1
              AND participant_id = $2
            """,
            workspace_id,
            participant_id,
        )
        return result.endswith("1")

    async def upsert_thread(self, conn: asyncpg.Connection, thread: Thread) -> None:
        await conn.execute(
            """
            INSERT INTO threads (
                thread_id, workspace_id, title, state, parent_thread_id,
                previous_thread_id, related_thread_ids, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (thread_id) DO UPDATE
                SET title = EXCLUDED.title,
                    state = EXCLUDED.state,
                    parent_thread_id = EXCLUDED.parent_thread_id,
                    previous_thread_id = EXCLUDED.previous_thread_id,
                    related_thread_ids = EXCLUDED.related_thread_ids,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            thread.thread_id,
            thread.workspace_id,
            thread.title,
            thread.state,
            thread.parent_thread_id,
            thread.previous_thread_id,
            self._json_dumps(thread.related_thread_ids),
            thread.created_at,
            thread.updated_at,
            self._json_dumps(thread.metadata),
        )

    async def upsert_participant(
        self, conn: asyncpg.Connection, participant: ParticipantProfile
    ) -> None:
        await conn.execute(
            """
            INSERT INTO participants (
                participant_id, workspace_id, participant_type, user_id, system_agent_id,
                description, roles, capabilities, status, visibility_scope, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (participant_id) DO UPDATE
                SET workspace_id = EXCLUDED.workspace_id,
                    participant_type = EXCLUDED.participant_type,
                    user_id = EXCLUDED.user_id,
                    system_agent_id = EXCLUDED.system_agent_id,
                    description = EXCLUDED.description,
                    roles = EXCLUDED.roles,
                    capabilities = EXCLUDED.capabilities,
                    status = EXCLUDED.status,
                    visibility_scope = EXCLUDED.visibility_scope,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            participant.participant_id,
            participant.workspace_id,
            participant.participant_type,
            participant.user_id,
            participant.system_agent_id,
            participant.description,
            self._json_dumps(participant.roles),
            self._json_dumps(participant.capabilities),
            participant.status,
            participant.visibility_scope,
            participant.created_at,
            participant.updated_at,
            self._json_dumps(participant.metadata),
        )

    async def upsert_membership(
        self, conn: asyncpg.Connection, membership: Membership
    ) -> None:
        await conn.execute(
            """
            INSERT INTO memberships (
                membership_id, workspace_id, thread_id, participant_id, role,
                permissions, joined_at, left_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (membership_id) DO UPDATE
                SET role = EXCLUDED.role,
                    permissions = EXCLUDED.permissions,
                    left_at = EXCLUDED.left_at,
                    metadata = EXCLUDED.metadata
            """,
            membership.membership_id,
            membership.workspace_id,
            membership.thread_id,
            membership.participant_id,
            membership.role,
            self._json_dumps(membership.permissions),
            membership.joined_at,
            membership.left_at,
            self._json_dumps(membership.metadata),
        )

    async def close_active_membership(
        self,
        conn: asyncpg.Connection,
        *,
        thread_id: UUID,
        participant_id: UUID,
        left_at,
    ) -> None:
        await conn.execute(
            """
            UPDATE memberships
            SET left_at = $3
            WHERE thread_id = $1
              AND participant_id = $2
              AND left_at IS NULL
            """,
            thread_id,
            participant_id,
            left_at,
        )

    async def fetch_active_membership(
        self,
        conn: asyncpg.Connection,
        *,
        thread_id: UUID,
        participant_id: UUID,
    ) -> Membership | None:
        row = await conn.fetchrow(
            """
            SELECT membership_id, workspace_id, thread_id, participant_id, role,
                   permissions, joined_at, left_at, metadata
            FROM memberships
            WHERE thread_id = $1
              AND participant_id = $2
              AND left_at IS NULL
            ORDER BY joined_at DESC
            LIMIT 1
            """,
            thread_id,
            participant_id,
        )
        return self._membership_from_row(row) if row else None

    async def upsert_memory_entry(
        self, conn: asyncpg.Connection, entry: MemoryEntry
    ) -> None:
        await conn.execute(
            """
            INSERT INTO memory_entries (
                memory_entry_id, scope, state, workspace_id, thread_id, run_id,
                entry_type, content, summary, source, visibility,
                created_by, updated_by, confirmed_by, confirmed_at, version,
                metadata, created_at, updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10, $11,
                $12, $13, $14, $15, $16,
                $17, $18, $19
            )
            ON CONFLICT (memory_entry_id) DO UPDATE
                SET scope = EXCLUDED.scope,
                    state = EXCLUDED.state,
                    thread_id = EXCLUDED.thread_id,
                    run_id = EXCLUDED.run_id,
                    entry_type = EXCLUDED.entry_type,
                    content = EXCLUDED.content,
                    summary = EXCLUDED.summary,
                    source = EXCLUDED.source,
                    visibility = EXCLUDED.visibility,
                    updated_by = EXCLUDED.updated_by,
                    confirmed_by = EXCLUDED.confirmed_by,
                    confirmed_at = EXCLUDED.confirmed_at,
                    version = EXCLUDED.version,
                    metadata = EXCLUDED.metadata,
                    updated_at = EXCLUDED.updated_at
            """,
            entry.memory_entry_id,
            entry.scope,
            entry.state,
            entry.workspace_id,
            entry.thread_id,
            entry.run_id,
            entry.entry_type,
            entry.content,
            entry.summary,
            entry.source,
            entry.visibility,
            entry.created_by,
            entry.updated_by,
            entry.confirmed_by,
            entry.confirmed_at,
            entry.version,
            self._json_dumps(entry.metadata),
            entry.created_at,
            entry.updated_at,
        )

    async def upsert_memory_provider(
        self, conn: asyncpg.Connection, provider: MemoryProviderDefinition
    ) -> None:
        await conn.execute(
            """
            INSERT INTO memory_providers (
                provider_id, scope, organization_id, provider_key, display_name, description, provider, enabled,
                config, secret_config, created_by, created_at, updated_by, updated_at, metadata
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8,
                $9, $10, $11, $12, $13, $14, $15
            )
            ON CONFLICT (provider_id) DO UPDATE
                SET scope = EXCLUDED.scope,
                    organization_id = EXCLUDED.organization_id,
                    provider_key = EXCLUDED.provider_key,
                    display_name = EXCLUDED.display_name,
                    description = EXCLUDED.description,
                    provider = EXCLUDED.provider,
                    enabled = EXCLUDED.enabled,
                    config = EXCLUDED.config,
                    secret_config = EXCLUDED.secret_config,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            provider.provider_id,
            provider.scope,
            provider.organization_id,
            provider.provider_key,
            provider.display_name,
            provider.description,
            provider.provider,
            provider.enabled,
            self._json_dumps(provider.config),
            self._json_dumps(provider.secret_config),
            provider.created_by,
            provider.created_at,
            provider.updated_by,
            provider.updated_at,
            self._json_dumps(provider.metadata),
        )

    async def upsert_memory_provider_record(
        self, conn: asyncpg.Connection, record: MemoryProviderRecord
    ) -> None:
        await conn.execute(
            """
            INSERT INTO memory_provider_records (
                provider_record_id, memory_entry_id, provider_id, external_id, status,
                last_synced_at, last_error, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (memory_entry_id, provider_id) DO UPDATE
                SET external_id = EXCLUDED.external_id,
                    status = EXCLUDED.status,
                    last_synced_at = EXCLUDED.last_synced_at,
                    last_error = EXCLUDED.last_error,
                    metadata = EXCLUDED.metadata
            """,
            record.provider_record_id,
            record.memory_entry_id,
            record.provider_id,
            record.external_id,
            record.status,
            record.last_synced_at,
            record.last_error,
            self._json_dumps(record.metadata),
        )

    async def delete_memory_provider(
        self, conn: asyncpg.Connection, *, provider_id: UUID
    ) -> bool:
        result = await conn.execute(
            """
            DELETE FROM memory_providers
            WHERE provider_id = $1
            """,
            provider_id,
        )
        return result.endswith("1")

    async def upsert_message(
        self, conn: asyncpg.Connection, message: TimelineMessage
    ) -> None:
        await conn.execute(
            """
            INSERT INTO timeline_messages (
                message_id, workspace_id, thread_id, actor_type, actor_id, visibility,
                content, status, correlation_id, causation_id, sequence, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (message_id) DO UPDATE
                SET content = EXCLUDED.content,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            message.message_id,
            message.workspace_id,
            message.thread_id,
            message.actor.type,
            message.actor.id,
            message.visibility,
            message.content,
            message.status,
            message.correlation_id,
            message.causation_id,
            message.sequence,
            message.created_at,
            message.updated_at,
            self._json_dumps(message.metadata),
        )

    async def upsert_task(self, conn: asyncpg.Connection, task: Task) -> None:
        await conn.execute(
            """
            INSERT INTO tasks (
                task_id, workspace_id, thread_id, title, description, status,
                requested_by, claimed_by, visibility, correlation_id, causation_id,
                created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (task_id) DO UPDATE
                SET title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    claimed_by = EXCLUDED.claimed_by,
                    visibility = EXCLUDED.visibility,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            task.task_id,
            task.workspace_id,
            task.thread_id,
            task.title,
            task.description,
            task.status,
            task.requested_by,
            task.claimed_by,
            task.visibility,
            task.correlation_id,
            task.causation_id,
            task.created_at,
            task.updated_at,
            self._json_dumps(task.metadata),
        )

    async def upsert_run(self, conn: asyncpg.Connection, run: Run) -> None:
        await conn.execute(
            """
            INSERT INTO runs (
                run_id, workspace_id, thread_id, task_id, participant_id, status,
                output, correlation_id, causation_id, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (run_id) DO UPDATE
                SET participant_id = EXCLUDED.participant_id,
                    status = EXCLUDED.status,
                    output = EXCLUDED.output,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            run.run_id,
            run.workspace_id,
            run.thread_id,
            run.task_id,
            run.participant_id,
            run.status,
            self._json_dumps(run.output),
            run.correlation_id,
            run.causation_id,
            run.created_at,
            run.updated_at,
            self._json_dumps(run.metadata),
        )

    async def upsert_run_step(self, conn: asyncpg.Connection, step: RunStep) -> None:
        await conn.execute(
            """
            INSERT INTO run_steps (
                step_id, run_id, task_id, workspace_id, thread_id, system_agent_id,
                step_index, kind, status, input, output, claimed_by_worker,
                lease_expires_at, last_heartbeat_at, next_retry_at, attempt_count,
                error, execution_handle, submitted_at, started_at, finished_at,
                created_at, updated_at, metadata
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10, $11, $12,
                $13, $14, $15, $16,
                $17, $18, $19, $20,
                $21, $22, $23, $24
            )
            ON CONFLICT (step_id) DO UPDATE
                SET status = EXCLUDED.status,
                    input = EXCLUDED.input,
                    output = EXCLUDED.output,
                    claimed_by_worker = EXCLUDED.claimed_by_worker,
                    lease_expires_at = EXCLUDED.lease_expires_at,
                    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
                    next_retry_at = EXCLUDED.next_retry_at,
                    attempt_count = EXCLUDED.attempt_count,
                    error = EXCLUDED.error,
                    execution_handle = EXCLUDED.execution_handle,
                    submitted_at = EXCLUDED.submitted_at,
                    started_at = EXCLUDED.started_at,
                    finished_at = EXCLUDED.finished_at,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            step.step_id,
            step.run_id,
            step.task_id,
            step.workspace_id,
            step.thread_id,
            step.system_agent_id,
            step.step_index,
            step.kind,
            step.status,
            self._json_dumps(step.input),
            self._json_dumps(step.output),
            step.claimed_by_worker,
            step.lease_expires_at,
            step.last_heartbeat_at,
            step.next_retry_at,
            step.attempt_count,
            step.error,
            step.execution_handle,
            step.submitted_at,
            step.started_at,
            step.finished_at,
            step.created_at,
            step.updated_at,
            self._json_dumps(step.metadata),
        )

    async def upsert_tool_call(self, conn: asyncpg.Connection, tool_call: ToolCall) -> None:
        await conn.execute(
            """
            INSERT INTO tool_calls (
                tool_call_id, run_id, run_step_id, task_id, workspace_id, thread_id,
                system_agent_id, tool_id, tool_name, status, arguments, execution_spec,
                claimed_by_worker, lease_expires_at, last_heartbeat_at, next_retry_at,
                attempt_count, error, execution_handle, result, submitted_at, started_at,
                finished_at, created_at, updated_at, metadata
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10, $11, $12,
                $13, $14, $15, $16,
                $17, $18, $19, $20, $21, $22,
                $23, $24, $25, $26
            )
            ON CONFLICT (tool_call_id) DO UPDATE
                SET status = EXCLUDED.status,
                    arguments = EXCLUDED.arguments,
                    execution_spec = EXCLUDED.execution_spec,
                    claimed_by_worker = EXCLUDED.claimed_by_worker,
                    lease_expires_at = EXCLUDED.lease_expires_at,
                    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
                    next_retry_at = EXCLUDED.next_retry_at,
                    attempt_count = EXCLUDED.attempt_count,
                    error = EXCLUDED.error,
                    execution_handle = EXCLUDED.execution_handle,
                    result = EXCLUDED.result,
                    submitted_at = EXCLUDED.submitted_at,
                    started_at = EXCLUDED.started_at,
                    finished_at = EXCLUDED.finished_at,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            tool_call.tool_call_id,
            tool_call.run_id,
            tool_call.run_step_id,
            tool_call.task_id,
            tool_call.workspace_id,
            tool_call.thread_id,
            tool_call.system_agent_id,
            tool_call.tool_id,
            tool_call.tool_name,
            tool_call.status,
            self._json_dumps(tool_call.arguments),
            self._json_dumps(tool_call.execution_spec),
            tool_call.claimed_by_worker,
            tool_call.lease_expires_at,
            tool_call.last_heartbeat_at,
            tool_call.next_retry_at,
            tool_call.attempt_count,
            tool_call.error,
            tool_call.execution_handle,
            self._json_dumps(
                tool_call.result.model_dump(mode="json") if tool_call.result is not None else None
            ),
            tool_call.submitted_at,
            tool_call.started_at,
            tool_call.finished_at,
            tool_call.created_at,
            tool_call.updated_at,
            self._json_dumps(tool_call.metadata),
        )

    async def upsert_artifact(
        self, conn: asyncpg.Connection, artifact: Artifact
    ) -> None:
        await conn.execute(
            """
            INSERT INTO artifacts (
                artifact_id, workspace_id, thread_id, task_id, run_id, kind, title,
                content, visibility, correlation_id, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (artifact_id) DO UPDATE
                SET kind = EXCLUDED.kind,
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    visibility = EXCLUDED.visibility,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            artifact.artifact_id,
            artifact.workspace_id,
            artifact.thread_id,
            artifact.task_id,
            artifact.run_id,
            artifact.kind,
            artifact.title,
            self._json_dumps(artifact.content),
            artifact.visibility,
            artifact.correlation_id,
            artifact.created_at,
            artifact.updated_at,
            self._json_dumps(artifact.metadata),
        )

    async def fetch_workspace(self, workspace_id: UUID) -> Workspace | None:
        row = await self._pool.fetchrow(
            """
            SELECT workspace_id, organization_id, name, description, owner_user_id, harness, created_at, updated_at, metadata
            FROM workspaces
            WHERE workspace_id = $1
            """,
            workspace_id,
        )
        return self._workspace_from_row(row) if row else None

    async def list_workspaces(self, *, organization_id: UUID | None = None) -> list[Workspace]:
        rows = await self._pool.fetch(
            """
            SELECT workspace_id, organization_id, name, description, owner_user_id, harness, created_at, updated_at, metadata
            FROM workspaces
            WHERE ($1::uuid IS NULL OR organization_id = $1)
            ORDER BY created_at ASC
            """,
            organization_id,
        )
        return [self._workspace_from_row(row) for row in rows]

    async def list_workspaces_for_user(
        self,
        user_id: UUID,
        *,
        organization_id: UUID | None = None,
    ) -> list[Workspace]:
        rows = await self._pool.fetch(
            """
            SELECT w.workspace_id, w.organization_id, w.name, w.description, w.owner_user_id,
                   w.harness, w.created_at, w.updated_at, w.metadata
            FROM workspaces AS w
            JOIN organization_memberships AS membership
              ON membership.organization_id = w.organization_id
             AND membership.user_id = $1
            WHERE EXISTS (
                SELECT 1
                FROM participants AS p
                WHERE p.workspace_id = w.workspace_id
                  AND p.participant_type = 'user'
                  AND p.user_id = $1
            )
              AND ($2::uuid IS NULL OR w.organization_id = $2)
            ORDER BY w.created_at ASC
            """,
            user_id,
            organization_id,
        )
        return [self._workspace_from_row(row) for row in rows]

    async def list_system_agents(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[AgentDefinition]:
        rows = await self._pool.fetch(
            """
            SELECT agent_id, scope, organization_id, display_name, description, role, capabilities, endpoint,
                   system_prompt, harness, interaction_contract, definition, created_by, created_at, updated_at, metadata
            FROM system_agents
            WHERE scope = $1
              AND (
                    ($2::uuid IS NULL AND organization_id IS NULL)
                 OR organization_id = $2
              )
            ORDER BY created_at ASC
            """,
            scope,
            organization_id,
        )
        return [self._system_agent_from_row(row) for row in rows]

    async def list_system_agents_referencing_llm_engine(
        self,
        engine_id: str,
    ) -> list[AgentDefinition]:
        rows = await self._pool.fetch(
            """
            SELECT agent_id, scope, organization_id, display_name, description, role, capabilities, endpoint,
                   system_prompt, harness, interaction_contract, definition, created_by, created_at, updated_at, metadata
            FROM system_agents
            WHERE endpoint->>'engine_id' = $1
               OR definition->'runtime'->>'engine_id' = $1
               OR EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(
                        CASE
                            WHEN jsonb_typeof(definition->'runtime'->'preferred_engine_ids') = 'array'
                                THEN definition->'runtime'->'preferred_engine_ids'
                            ELSE '[]'::jsonb
                        END
                    ) AS preferred(engine_id)
                    WHERE preferred.engine_id = $1
               )
            ORDER BY created_at ASC
            """,
            engine_id,
        )
        return [self._system_agent_from_row(row) for row in rows]

    async def list_system_tools(self) -> list[SystemToolDefinition]:
        return await self.list_system_tools_by_scope()

    async def list_system_tools_by_scope(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[SystemToolDefinition]:
        rows = await self._pool.fetch(
            """
            SELECT tool_id, scope, organization_id, name, description, parameter_contract, input_schema,
                   backend_kind, handler_ref, execution_profile, trust_level,
                   created_by, created_at, updated_by, updated_at, metadata
            FROM system_tools
            WHERE scope = $1
              AND COALESCE((metadata->>'internal_only')::boolean, FALSE) = FALSE
              AND (
                    ($2::uuid IS NULL AND organization_id IS NULL)
                 OR organization_id = $2
              )
            ORDER BY created_at ASC
            """,
            scope,
            organization_id,
        )
        return [self._system_tool_from_row(row) for row in rows]

    async def list_llm_providers(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[LlmProviderDefinition]:
        rows = await self._pool.fetch(
            """
            SELECT provider_id, scope, organization_id, engine_id, display_name, description, provider, endpoint_kind,
                   url, default_model, capabilities, locality, priority, enabled, secret_config,
                   created_by, created_at, updated_by, updated_at, metadata
            FROM llm_providers
            WHERE scope = $1
              AND (
                    ($2::uuid IS NULL AND organization_id IS NULL)
                 OR organization_id = $2
              )
            ORDER BY created_at ASC
            """,
            scope,
            organization_id,
        )
        return [self._llm_provider_from_row(row) for row in rows]

    async def fetch_system_agent(self, agent_id: UUID) -> AgentDefinition | None:
        row = await self._pool.fetchrow(
            """
            SELECT agent_id, scope, organization_id, display_name, description, role, capabilities, endpoint,
                   system_prompt, harness, interaction_contract, definition, created_by, created_at, updated_at, metadata
            FROM system_agents
            WHERE agent_id = $1
            """,
            agent_id,
        )
        return self._system_agent_from_row(row) if row else None

    async def fetch_system_tool(self, tool_id: UUID) -> SystemToolDefinition | None:
        row = await self._pool.fetchrow(
            """
            SELECT tool_id, scope, organization_id, name, description, parameter_contract, input_schema,
                   backend_kind, handler_ref, execution_profile, trust_level,
                   created_by, created_at, updated_by, updated_at, metadata
            FROM system_tools
            WHERE tool_id = $1
            """,
            tool_id,
        )
        return self._system_tool_from_row(row) if row else None

    async def fetch_llm_provider(self, provider_id: UUID) -> LlmProviderDefinition | None:
        row = await self._pool.fetchrow(
            """
            SELECT provider_id, scope, organization_id, engine_id, display_name, description, provider, endpoint_kind,
                   url, default_model, capabilities, locality, priority, enabled, secret_config,
                   created_by, created_at, updated_by, updated_at, metadata
            FROM llm_providers
            WHERE provider_id = $1
            """,
            provider_id,
        )
        return self._llm_provider_from_row(row) if row else None

    async def list_git_repositories(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[GitRepository]:
        effective_organization_id = organization_id
        if scope in {"organization", "workspace"}:
            effective_organization_id = await self._effective_organization_filter(
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
        rows = await self._pool.fetch(
            """
            SELECT repo_id, organization_id, workspace_id, scope, name, forgejo_url, clone_url, local_path,
                   default_branch, created_by, created_at, updated_at, metadata
            FROM git_repositories
            WHERE scope = $1
              AND (
                    ($2::uuid IS NULL AND organization_id IS NULL)
                 OR organization_id = $2
              )
              AND (
                    ($3::uuid IS NULL AND workspace_id IS NULL)
                 OR workspace_id = $3
              )
            ORDER BY created_at ASC
            """,
            scope,
            effective_organization_id,
            workspace_id,
        )
        return [self._git_repository_from_row(row) for row in rows]

    async def fetch_git_repository(self, repo_id: UUID) -> GitRepository | None:
        row = await self._pool.fetchrow(
            """
            SELECT repo_id, organization_id, workspace_id, scope, name, forgejo_url, clone_url, local_path,
                   default_branch, created_by, created_at, updated_at, metadata
            FROM git_repositories
            WHERE repo_id = $1
            """,
            repo_id,
        )
        return self._git_repository_from_row(row) if row else None

    async def fetch_workspace_asset(self, asset_id: UUID) -> WorkspaceAsset | None:
        row = await self._pool.fetchrow(
            """
            SELECT asset_id, organization_id, workspace_id, scope, asset_type, logical_name, logical_path,
                   title, description, created_by, created_at, updated_at, metadata
            FROM workspace_assets
            WHERE asset_id = $1
            """,
            asset_id,
        )
        return self._workspace_asset_from_row(row) if row else None

    async def fetch_workspace_asset_by_logical_name(
        self,
        *,
        scope: str,
        organization_id: UUID | None,
        workspace_id: UUID | None,
        logical_name: str,
    ) -> WorkspaceAsset | None:
        effective_organization_id = organization_id
        if scope in {"organization", "workspace"}:
            effective_organization_id = await self._effective_organization_filter(
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
        row = await self._pool.fetchrow(
            """
            SELECT asset_id, organization_id, workspace_id, scope, asset_type, logical_name, logical_path,
                   title, description, created_by, created_at, updated_at, metadata
            FROM workspace_assets
            WHERE scope = $1
              AND (
                    ($2::uuid IS NULL AND organization_id IS NULL)
                 OR organization_id = $2
              )
              AND (
                    ($3::uuid IS NULL AND workspace_id IS NULL)
                 OR workspace_id = $3
              )
              AND logical_name = $4
            """,
            scope,
            effective_organization_id,
            workspace_id,
            logical_name,
        )
        return self._workspace_asset_from_row(row) if row else None

    async def list_workspace_assets(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[WorkspaceAsset]:
        effective_organization_id = organization_id
        if scope in {None, "organization", "workspace"} and workspace_id is not None:
            effective_organization_id = await self._effective_organization_filter(
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
        rows = await self._pool.fetch(
            """
            SELECT asset_id, organization_id, workspace_id, scope, asset_type, logical_name, logical_path,
                   title, description, created_by, created_at, updated_at, metadata
            FROM workspace_assets
            WHERE ($1::text IS NULL OR scope = $1)
              AND (
                    ($2::uuid IS NULL AND organization_id IS NULL)
                 OR organization_id = $2
              )
              AND (
                    ($3::uuid IS NULL AND workspace_id IS NULL)
                 OR workspace_id = $3
              )
            ORDER BY created_at ASC
            """,
            scope,
            effective_organization_id,
            workspace_id,
        )
        return [self._workspace_asset_from_row(row) for row in rows]

    async def list_workspace_asset_versions(self, asset_id: UUID) -> list[WorkspaceAssetVersion]:
        rows = await self._pool.fetch(
            """
            SELECT asset_version_id, asset_id, version, source_kind, git_repository_id,
                   git_revision, git_path, storage_backend, bucket, object_key, content_type,
                   size_bytes, sha256, created_by, created_at, metadata
            FROM workspace_asset_versions
            WHERE asset_id = $1
            ORDER BY version ASC
            """,
            asset_id,
        )
        return [self._workspace_asset_version_from_row(row) for row in rows]

    async def fetch_workspace_asset_version(
        self, asset_version_id: UUID
    ) -> WorkspaceAssetVersion | None:
        row = await self._pool.fetchrow(
            """
            SELECT asset_version_id, asset_id, version, source_kind, git_repository_id,
                   git_revision, git_path, storage_backend, bucket, object_key, content_type,
                   size_bytes, sha256, created_by, created_at, metadata
            FROM workspace_asset_versions
            WHERE asset_version_id = $1
            """,
            asset_version_id,
        )
        return self._workspace_asset_version_from_row(row) if row else None

    async def next_workspace_asset_version(
        self,
        conn: asyncpg.Connection,
        *,
        asset_id: UUID,
    ) -> int:
        return await conn.fetchval(
            """
            SELECT COALESCE(MAX(version), 0) + 1
            FROM workspace_asset_versions
            WHERE asset_id = $1
            """,
            asset_id,
        )

    async def list_asset_links_for_target(
        self,
        *,
        target_type: str,
        target_id: UUID,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[ResolvedAssetBinding]:
        effective_organization_id = await self._effective_organization_filter(
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        rows = await self._pool.fetch(
            """
            SELECT
                al.link_id, al.asset_id AS link_asset_id, al.asset_version_id AS link_asset_version_id,
                al.organization_id AS link_organization_id, al.workspace_id AS link_workspace_id,
                al.target_type, al.target_id, al.purpose,
                al.active, al.created_by AS link_created_by, al.created_at AS link_created_at,
                al.updated_at AS link_updated_at, al.metadata AS link_metadata,
                wa.asset_id, wa.organization_id AS asset_organization_id, wa.workspace_id AS asset_workspace_id,
                wa.scope, wa.asset_type,
                wa.logical_name, wa.logical_path, wa.title, wa.description, wa.created_by AS asset_created_by,
                wa.created_at AS asset_created_at, wa.updated_at AS asset_updated_at, wa.metadata AS asset_metadata,
                wav.asset_version_id, wav.version, wav.source_kind, wav.git_repository_id, wav.git_revision,
                wav.git_path, wav.storage_backend, wav.bucket, wav.object_key, wav.content_type,
                wav.size_bytes, wav.sha256, wav.created_by AS version_created_by,
                wav.created_at AS version_created_at, wav.metadata AS version_metadata
            FROM asset_links al
            JOIN workspace_assets wa ON wa.asset_id = al.asset_id
            JOIN workspace_asset_versions wav ON wav.asset_version_id = al.asset_version_id
            WHERE al.target_type = $1
              AND al.target_id = $2
              AND al.active = TRUE
              AND (
                    ($3::uuid IS NULL AND $4::uuid IS NULL AND al.organization_id IS NULL AND al.workspace_id IS NULL)
                 OR (
                        $3::uuid IS NOT NULL
                    AND (
                            al.organization_id = $3
                         OR al.organization_id IS NULL
                    )
                    AND (
                            $4::uuid IS NULL
                         OR al.workspace_id = $4
                         OR al.workspace_id IS NULL
                    )
                 )
              )
            ORDER BY al.updated_at DESC
            """,
            target_type,
            target_id,
            effective_organization_id,
            workspace_id,
        )
        by_purpose: dict[str, ResolvedAssetBinding] = {}
        for row in rows:
            binding = self._resolved_asset_binding_from_row(row)
            existing = by_purpose.get(binding.purpose)
            if existing is None:
                by_purpose[binding.purpose] = binding
                continue
            if self._asset_binding_specificity(binding) > self._asset_binding_specificity(existing):
                by_purpose[binding.purpose] = binding
        return list(by_purpose.values())

    async def list_workspace_tools(self, workspace_id: UUID) -> list[WorkspaceTool]:
        rows = await self._pool.fetch(
            """
            SELECT wt.workspace_id, wt.tool_id, st.name, st.description, st.parameter_contract, st.input_schema,
                   st.backend_kind, st.handler_ref, st.execution_profile, st.trust_level,
                   wt.enabled, wt.attached_by, wt.attached_at, wt.updated_at, wt.metadata
            FROM workspace_tools wt
            JOIN system_tools st ON wt.tool_id = st.tool_id
            WHERE wt.workspace_id = $1
            ORDER BY wt.attached_at ASC
            """,
            workspace_id,
        )
        return [self._workspace_tool_from_row(row) for row in rows]

    async def fetch_workspace_tool(
        self,
        workspace_id: UUID,
        tool_id: UUID,
    ) -> WorkspaceTool | None:
        row = await self._pool.fetchrow(
            """
            SELECT wt.workspace_id, wt.tool_id, st.name, st.description, st.parameter_contract, st.input_schema,
                   st.backend_kind, st.handler_ref, st.execution_profile, st.trust_level,
                   wt.enabled, wt.attached_by, wt.attached_at, wt.updated_at, wt.metadata
            FROM workspace_tools wt
            JOIN system_tools st ON wt.tool_id = st.tool_id
            WHERE wt.workspace_id = $1
              AND wt.tool_id = $2
            """,
            workspace_id,
            tool_id,
        )
        return self._workspace_tool_from_row(row) if row else None

    async def fetch_workspace_tool_by_name(
        self,
        workspace_id: UUID,
        tool_name: str,
    ) -> WorkspaceTool | None:
        row = await self._pool.fetchrow(
            """
            SELECT wt.workspace_id, wt.tool_id, st.name, st.description, st.parameter_contract, st.input_schema,
                   st.backend_kind, st.handler_ref, st.execution_profile, st.trust_level,
                   wt.enabled, wt.attached_by, wt.attached_at, wt.updated_at, wt.metadata
            FROM workspace_tools wt
            JOIN system_tools st ON wt.tool_id = st.tool_id
            WHERE wt.workspace_id = $1
              AND st.name = $2
            """,
            workspace_id,
            tool_name,
        )
        return self._workspace_tool_from_row(row) if row else None

    async def list_agent_internal_tools(
        self,
        system_agent_id: UUID,
    ) -> list[AgentInternalToolBinding]:
        rows = await self._pool.fetch(
            """
            SELECT ait.system_agent_id, ait.tool_id, st.name, st.description, st.parameter_contract,
                   st.input_schema, st.backend_kind, st.handler_ref, st.execution_profile,
                   st.trust_level, ait.enabled, ait.attached_by, ait.attached_at, ait.updated_at,
                   ait.metadata
            FROM agent_internal_tools ait
            JOIN system_tools st ON st.tool_id = ait.tool_id
            WHERE ait.system_agent_id = $1
            ORDER BY ait.attached_at ASC
            """,
            system_agent_id,
        )
        return [self._agent_internal_tool_from_row(row) for row in rows]

    async def fetch_agent_internal_tool_by_name(
        self,
        system_agent_id: UUID,
        tool_name: str,
    ) -> AgentInternalToolBinding | None:
        row = await self._pool.fetchrow(
            """
            SELECT ait.system_agent_id, ait.tool_id, st.name, st.description, st.parameter_contract,
                   st.input_schema, st.backend_kind, st.handler_ref, st.execution_profile,
                   st.trust_level, ait.enabled, ait.attached_by, ait.attached_at, ait.updated_at,
                   ait.metadata
            FROM agent_internal_tools ait
            JOIN system_tools st ON st.tool_id = ait.tool_id
            WHERE ait.system_agent_id = $1
              AND st.name = $2
            LIMIT 1
            """,
            system_agent_id,
            tool_name,
        )
        return self._agent_internal_tool_from_row(row) if row else None

    async def fetch_tool_generation_request(
        self,
        request_id: UUID,
    ) -> ToolGenerationRequest | None:
        row = await self._pool.fetchrow(
            """
            SELECT request_id, organization_id, workspace_id, thread_id, requester_participant_id,
                   requester_message_id, target_system_agent_id, requested_scope, status,
                   target_tool_name, summary, final_tool_id, latest_revision_id, approved_by,
                   approved_at, rejected_by, rejected_at, published_at, created_at, updated_at,
                   metadata
            FROM tool_generation_requests
            WHERE request_id = $1
            """,
            request_id,
        )
        return self._tool_generation_request_from_row(row) if row else None

    async def list_tool_generation_requests(
        self,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        thread_id: UUID | None = None,
        status: str | None = None,
    ) -> list[ToolGenerationRequest]:
        rows = await self._pool.fetch(
            """
            SELECT request_id, organization_id, workspace_id, thread_id, requester_participant_id,
                   requester_message_id, target_system_agent_id, requested_scope, status,
                   target_tool_name, summary, final_tool_id, latest_revision_id, approved_by,
                   approved_at, rejected_by, rejected_at, published_at, created_at, updated_at,
                   metadata
            FROM tool_generation_requests
            WHERE ($1::uuid IS NULL OR organization_id = $1)
              AND ($2::uuid IS NULL OR workspace_id = $2)
              AND ($3::uuid IS NULL OR thread_id = $3)
              AND ($4::text IS NULL OR status = $4)
            ORDER BY created_at DESC
            """,
            organization_id,
            workspace_id,
            thread_id,
            status,
        )
        return [self._tool_generation_request_from_row(row) for row in rows]

    async def fetch_tool_generation_revision(
        self,
        revision_id: UUID,
    ) -> ToolGenerationRevision | None:
        row = await self._pool.fetchrow(
            """
            SELECT revision_id, request_id, revision_number, status, manifest, validation_report,
                   source_asset_id, source_asset_version_id, manifest_asset_id, manifest_asset_version_id,
                   report_asset_id, report_asset_version_id, image_ref, image_digest,
                   created_by, created_at, updated_at, metadata
            FROM tool_generation_revisions
            WHERE revision_id = $1
            """,
            revision_id,
        )
        return self._tool_generation_revision_from_row(row) if row else None

    async def list_tool_generation_revisions(
        self,
        request_id: UUID,
    ) -> list[ToolGenerationRevision]:
        rows = await self._pool.fetch(
            """
            SELECT revision_id, request_id, revision_number, status, manifest, validation_report,
                   source_asset_id, source_asset_version_id, manifest_asset_id, manifest_asset_version_id,
                   report_asset_id, report_asset_version_id, image_ref, image_digest,
                   created_by, created_at, updated_at, metadata
            FROM tool_generation_revisions
            WHERE request_id = $1
            ORDER BY revision_number DESC
            """,
            request_id,
        )
        return [self._tool_generation_revision_from_row(row) for row in rows]

    async def fetch_agent_participant(
        self, workspace_id: UUID, system_agent_id: UUID
    ) -> ParticipantProfile | None:
        row = await self._pool.fetchrow(
            """
            SELECT p.participant_id, p.workspace_id, p.participant_type, p.user_id, p.system_agent_id,
                   p.description, p.roles, p.capabilities, p.status, p.visibility_scope,
                   p.created_at, p.updated_at, p.metadata,
                   u.display_name AS user_display_name,
                   sa.display_name AS agent_display_name,
                   sa.description AS agent_description,
                   sa.role AS agent_role,
                   sa.capabilities AS agent_capabilities,
                   sa.endpoint AS agent_endpoint,
                   sa.system_prompt AS agent_system_prompt,
                   sa.harness AS agent_harness,
                   sa.definition AS agent_definition
            FROM participants p
            LEFT JOIN users u ON p.user_id = u.user_id
            LEFT JOIN system_agents sa ON p.system_agent_id = sa.agent_id
            WHERE p.workspace_id = $1
              AND p.participant_type = 'agent'
              AND p.system_agent_id = $2
            ORDER BY created_at ASC
            LIMIT 1
            """,
            workspace_id,
            system_agent_id,
        )
        return self._participant_from_row(row) if row else None

    async def fetch_user_participant(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> ParticipantProfile | None:
        row = await self._pool.fetchrow(
            """
            SELECT p.participant_id, p.workspace_id, p.participant_type, p.user_id, p.system_agent_id,
                   p.description, p.roles, p.capabilities, p.status, p.visibility_scope,
                   p.created_at, p.updated_at, p.metadata,
                   u.display_name AS user_display_name,
                   sa.display_name AS agent_display_name,
                   sa.description AS agent_description,
                   sa.role AS agent_role,
                   sa.capabilities AS agent_capabilities,
                   sa.endpoint AS agent_endpoint,
                   sa.system_prompt AS agent_system_prompt,
                   sa.harness AS agent_harness,
                   sa.definition AS agent_definition
            FROM participants p
            LEFT JOIN users u ON p.user_id = u.user_id
            LEFT JOIN system_agents sa ON p.system_agent_id = sa.agent_id
            WHERE p.workspace_id = $1
              AND p.participant_type = 'user'
              AND p.user_id = $2
            ORDER BY p.created_at ASC
            LIMIT 1
            """,
            workspace_id,
            user_id,
        )
        return self._participant_from_row(row) if row else None

    async def list_participants(self, workspace_id: UUID) -> list[ParticipantProfile]:
        rows = await self._pool.fetch(
            """
            SELECT p.participant_id, p.workspace_id, p.participant_type, p.user_id, p.system_agent_id,
                   p.description, p.roles, p.capabilities, p.status, p.visibility_scope,
                   p.created_at, p.updated_at, p.metadata,
                   u.display_name AS user_display_name,
                   sa.display_name AS agent_display_name,
                   sa.description AS agent_description,
                   sa.role AS agent_role,
                   sa.capabilities AS agent_capabilities,
                   sa.endpoint AS agent_endpoint,
                   sa.system_prompt AS agent_system_prompt,
                   sa.harness AS agent_harness,
                   sa.definition AS agent_definition
            FROM participants p
            LEFT JOIN users u ON p.user_id = u.user_id
            LEFT JOIN system_agents sa ON p.system_agent_id = sa.agent_id
            WHERE p.workspace_id = $1
            ORDER BY COALESCE(u.display_name, sa.display_name, p.participant_id::text) ASC
            """,
            workspace_id,
        )
        return [self._participant_from_row(row) for row in rows]

    async def fetch_participant(
        self, workspace_id: UUID, participant_id: UUID
    ) -> ParticipantProfile | None:
        row = await self._pool.fetchrow(
            """
            SELECT p.participant_id, p.workspace_id, p.participant_type, p.user_id, p.system_agent_id,
                   p.description, p.roles, p.capabilities, p.status, p.visibility_scope,
                   p.created_at, p.updated_at, p.metadata,
                   u.display_name AS user_display_name,
                   sa.display_name AS agent_display_name,
                   sa.description AS agent_description,
                   sa.role AS agent_role,
                   sa.capabilities AS agent_capabilities,
                   sa.endpoint AS agent_endpoint,
                   sa.system_prompt AS agent_system_prompt,
                   sa.harness AS agent_harness,
                   sa.definition AS agent_definition
            FROM participants p
            LEFT JOIN users u ON p.user_id = u.user_id
            LEFT JOIN system_agents sa ON p.system_agent_id = sa.agent_id
            WHERE p.workspace_id = $1
              AND p.participant_id = $2
            """,
            workspace_id,
            participant_id,
        )
        return self._participant_from_row(row) if row else None

    async def fetch_task(self, task_id: UUID) -> Task | None:
        row = await self._pool.fetchrow(
            """
            SELECT task_id, workspace_id, thread_id, title, description, status,
                   requested_by, claimed_by, visibility, correlation_id, causation_id,
                   created_at, updated_at, metadata
            FROM tasks
            WHERE task_id = $1
            """,
            task_id,
        )
        return self._task_from_row(row) if row else None

    async def list_pending_tasks_for_system_agent(
        self,
        system_agent_id: UUID,
        *,
        limit: int = 10,
    ) -> list[Task]:
        rows = await self._pool.fetch(
            """
            SELECT task_id, workspace_id, thread_id, title, description, status,
                   requested_by, claimed_by, visibility, correlation_id, causation_id,
                   created_at, updated_at, metadata
            FROM tasks
            WHERE status IN ('created', 'released')
              AND metadata->>'target_system_agent_id' = $1
            ORDER BY created_at ASC
            LIMIT $2
            """,
            str(system_agent_id),
            limit,
        )
        return [self._task_from_row(row) for row in rows]

    async def claim_task(
        self,
        conn: asyncpg.Connection,
        *,
        task_id: UUID,
        participant_id: UUID,
        updated_at,
    ) -> Task | None:
        row = await conn.fetchrow(
            """
            UPDATE tasks
            SET status = 'claimed',
                claimed_by = $2,
                updated_at = $3
            WHERE task_id = $1
              AND status IN ('created', 'released')
            RETURNING task_id, workspace_id, thread_id, title, description, status,
                      requested_by, claimed_by, visibility, correlation_id, causation_id,
                      created_at, updated_at, metadata
            """,
            task_id,
            participant_id,
            updated_at,
        )
        return self._task_from_row(row) if row else None

    async def fetch_run(self, run_id: UUID) -> Run | None:
        row = await self._pool.fetchrow(
            """
            SELECT run_id, workspace_id, thread_id, task_id, participant_id, status,
                   output, correlation_id, causation_id, created_at, updated_at, metadata
            FROM runs
            WHERE run_id = $1
            """,
            run_id,
        )
        return self._run_from_row(row) if row else None

    async def fetch_run_step(self, step_id: UUID) -> RunStep | None:
        row = await self._pool.fetchrow(
            """
            SELECT step_id, run_id, task_id, workspace_id, thread_id, system_agent_id,
                   step_index, kind, status, input, output, claimed_by_worker,
                   lease_expires_at, last_heartbeat_at, next_retry_at, attempt_count, error,
                   execution_handle, submitted_at, started_at, finished_at,
                   created_at, updated_at, metadata
            FROM run_steps
            WHERE step_id = $1
            """,
            step_id,
        )
        return self._run_step_from_row(row) if row else None

    async def list_run_steps(self, run_id: UUID) -> list[RunStep]:
        rows = await self._pool.fetch(
            """
            SELECT step_id, run_id, task_id, workspace_id, thread_id, system_agent_id,
                   step_index, kind, status, input, output, claimed_by_worker,
                   lease_expires_at, last_heartbeat_at, next_retry_at, attempt_count, error,
                   execution_handle, submitted_at, started_at, finished_at,
                   created_at, updated_at, metadata
            FROM run_steps
            WHERE run_id = $1
            ORDER BY step_index ASC, created_at ASC
            """,
            run_id,
        )
        return [self._run_step_from_row(row) for row in rows]

    async def claim_next_run_step(
        self,
        *,
        worker_id: str,
        lease_expires_at,
        now,
    ) -> RunStep | None:
        row = await self._pool.fetchrow(
            """
            WITH candidate AS (
                SELECT step_id
                FROM run_steps
                WHERE status = 'created'
                  AND (next_retry_at IS NULL OR next_retry_at <= $3)
                  AND (
                    SELECT COUNT(*)
                    FROM run_steps active
                    WHERE active.run_id = run_steps.run_id
                      AND active.status = 'claimed'
                  ) = 0
                ORDER BY submitted_at ASC, created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE run_steps rs
            SET status = 'claimed',
                claimed_by_worker = $1,
                lease_expires_at = $2,
                last_heartbeat_at = $3,
                next_retry_at = NULL,
                started_at = COALESCE(rs.started_at, $3),
                updated_at = $3,
                attempt_count = rs.attempt_count + 1
            FROM candidate
            WHERE rs.step_id = candidate.step_id
            RETURNING rs.step_id, rs.run_id, rs.task_id, rs.workspace_id, rs.thread_id, rs.system_agent_id,
                      rs.step_index, rs.kind, rs.status, rs.input, rs.output, rs.claimed_by_worker,
                      rs.lease_expires_at, rs.last_heartbeat_at, rs.next_retry_at, rs.attempt_count, rs.error,
                      rs.execution_handle, rs.submitted_at, rs.started_at, rs.finished_at,
                      rs.created_at, rs.updated_at, rs.metadata
            """,
            worker_id,
            lease_expires_at,
            now,
        )
        return self._run_step_from_row(row) if row else None

    async def heartbeat_run_step(
        self,
        *,
        step_id: UUID,
        worker_id: str,
        lease_expires_at,
        now,
    ) -> RunStep | None:
        row = await self._pool.fetchrow(
            """
            UPDATE run_steps
            SET lease_expires_at = $3,
                last_heartbeat_at = $4,
                updated_at = $4
            WHERE step_id = $1
              AND claimed_by_worker = $2
              AND status = 'claimed'
            RETURNING step_id, run_id, task_id, workspace_id, thread_id, system_agent_id,
                      step_index, kind, status, input, output, claimed_by_worker,
                      lease_expires_at, last_heartbeat_at, next_retry_at, attempt_count, error,
                      execution_handle, submitted_at, started_at, finished_at,
                      created_at, updated_at, metadata
            """,
            step_id,
            worker_id,
            lease_expires_at,
            now,
        )
        return self._run_step_from_row(row) if row else None

    async def list_expired_run_steps(self, *, now) -> list[RunStep]:
        rows = await self._pool.fetch(
            """
            SELECT step_id, run_id, task_id, workspace_id, thread_id, system_agent_id,
                   step_index, kind, status, input, output, claimed_by_worker,
                   lease_expires_at, last_heartbeat_at, next_retry_at, attempt_count, error,
                   execution_handle, submitted_at, started_at, finished_at,
                   created_at, updated_at, metadata
            FROM run_steps
            WHERE status = 'claimed'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at < $1
            ORDER BY lease_expires_at ASC, submitted_at ASC, created_at ASC
            """,
            now,
        )
        return [self._run_step_from_row(row) for row in rows]

    async def fetch_tool_call(self, tool_call_id: UUID) -> ToolCall | None:
        row = await self._pool.fetchrow(
            """
            SELECT tool_call_id, run_id, run_step_id, task_id, workspace_id, thread_id,
                   system_agent_id, tool_id, tool_name, status, arguments, execution_spec,
                   claimed_by_worker, lease_expires_at, last_heartbeat_at, next_retry_at, attempt_count,
                   error, execution_handle, result, submitted_at, started_at, finished_at,
                   created_at, updated_at, metadata
            FROM tool_calls
            WHERE tool_call_id = $1
            """,
            tool_call_id,
        )
        return self._tool_call_from_row(row) if row else None

    async def list_tool_calls_for_run_step(self, run_step_id: UUID) -> list[ToolCall]:
        rows = await self._pool.fetch(
            """
            SELECT tool_call_id, run_id, run_step_id, task_id, workspace_id, thread_id,
                   system_agent_id, tool_id, tool_name, status, arguments, execution_spec,
                   claimed_by_worker, lease_expires_at, last_heartbeat_at, next_retry_at, attempt_count,
                   error, execution_handle, result, submitted_at, started_at, finished_at,
                   created_at, updated_at, metadata
            FROM tool_calls
            WHERE run_step_id = $1
            ORDER BY created_at ASC
            """,
            run_step_id,
        )
        return [self._tool_call_from_row(row) for row in rows]

    async def list_completed_tool_calls_for_run(self, run_id: UUID) -> list[ToolCall]:
        rows = await self._pool.fetch(
            """
            SELECT tool_call_id, run_id, run_step_id, task_id, workspace_id, thread_id,
                   system_agent_id, tool_id, tool_name, status, arguments, execution_spec,
                   claimed_by_worker, lease_expires_at, last_heartbeat_at, next_retry_at, attempt_count,
                   error, execution_handle, result, submitted_at, started_at, finished_at,
                   created_at, updated_at, metadata
            FROM tool_calls
            WHERE run_id = $1
              AND status IN ('completed', 'failed')
            ORDER BY created_at ASC
            """,
            run_id,
        )
        return [self._tool_call_from_row(row) for row in rows]

    async def claim_next_tool_call(
        self,
        *,
        worker_id: str,
        lease_expires_at,
        now,
        max_parallel_calls_per_run: int,
        max_concurrent_calls_per_tool: int,
    ) -> ToolCall | None:
        row = await self._pool.fetchrow(
            """
            WITH candidate AS (
                SELECT tc.tool_call_id
                FROM tool_calls tc
                WHERE tc.status = 'created'
                  AND (tc.next_retry_at IS NULL OR tc.next_retry_at <= $3)
                  AND (
                    SELECT COUNT(*)
                    FROM tool_calls active
                    WHERE active.run_id = tc.run_id
                      AND active.status = 'claimed'
                  ) < $4
                  AND (
                    SELECT COUNT(*)
                    FROM tool_calls active
                    WHERE active.tool_name = tc.tool_name
                      AND active.status = 'claimed'
                  ) < $5
                ORDER BY tc.submitted_at ASC, tc.created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE tool_calls tc
            SET status = 'claimed',
                claimed_by_worker = $1,
                lease_expires_at = $2,
                last_heartbeat_at = $3,
                next_retry_at = NULL,
                started_at = COALESCE(tc.started_at, $3),
                updated_at = $3,
                attempt_count = tc.attempt_count + 1
            FROM candidate
            WHERE tc.tool_call_id = candidate.tool_call_id
            RETURNING tc.tool_call_id, tc.run_id, tc.run_step_id, tc.task_id, tc.workspace_id, tc.thread_id,
                      tc.system_agent_id, tc.tool_id, tc.tool_name, tc.status, tc.arguments, tc.execution_spec,
                      tc.claimed_by_worker, tc.lease_expires_at, tc.last_heartbeat_at, tc.next_retry_at, tc.attempt_count,
                      tc.error, tc.execution_handle, tc.result, tc.submitted_at, tc.started_at, tc.finished_at,
                      tc.created_at, tc.updated_at, tc.metadata
            """,
            worker_id,
            lease_expires_at,
            now,
            max_parallel_calls_per_run,
            max_concurrent_calls_per_tool,
        )
        return self._tool_call_from_row(row) if row else None

    async def heartbeat_tool_call(
        self,
        *,
        tool_call_id: UUID,
        worker_id: str,
        lease_expires_at,
        now,
    ) -> ToolCall | None:
        row = await self._pool.fetchrow(
            """
            UPDATE tool_calls
            SET lease_expires_at = $3,
                last_heartbeat_at = $4,
                updated_at = $4
            WHERE tool_call_id = $1
              AND claimed_by_worker = $2
              AND status = 'claimed'
            RETURNING tool_call_id, run_id, run_step_id, task_id, workspace_id, thread_id,
                      system_agent_id, tool_id, tool_name, status, arguments, execution_spec,
                      claimed_by_worker, lease_expires_at, last_heartbeat_at, next_retry_at, attempt_count,
                      error, execution_handle, result, submitted_at, started_at, finished_at,
                      created_at, updated_at, metadata
            """,
            tool_call_id,
            worker_id,
            lease_expires_at,
            now,
        )
        return self._tool_call_from_row(row) if row else None

    async def list_expired_tool_calls(self, *, now) -> list[ToolCall]:
        rows = await self._pool.fetch(
            """
            SELECT tool_call_id, run_id, run_step_id, task_id, workspace_id, thread_id,
                   system_agent_id, tool_id, tool_name, status, arguments, execution_spec,
                   claimed_by_worker, lease_expires_at, last_heartbeat_at, next_retry_at, attempt_count,
                   error, execution_handle, result, submitted_at, started_at, finished_at,
                   created_at, updated_at, metadata
            FROM tool_calls
            WHERE status = 'claimed'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at < $1
            ORDER BY lease_expires_at ASC, submitted_at ASC, created_at ASC
            """,
            now,
        )
        return [self._tool_call_from_row(row) for row in rows]

    async def get_runtime_queue_stats(
        self,
        *,
        now,
        since,
        organization_id: UUID | None = None,
    ) -> dict[str, int | None]:
        row = await self._pool.fetchrow(
            """
            SELECT
                (
                    SELECT COUNT(*)
                    FROM tasks
                    JOIN workspaces ON workspaces.workspace_id = tasks.workspace_id
                    WHERE tasks.status IN ('created', 'released')
                      AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
                ) AS tasks_pending,
                (
                    SELECT COUNT(*)
                    FROM tasks
                    JOIN workspaces ON workspaces.workspace_id = tasks.workspace_id
                    WHERE tasks.status = 'claimed'
                      AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
                ) AS tasks_claimed,
                (
                    SELECT COUNT(*)
                    FROM run_steps
                    JOIN workspaces ON workspaces.workspace_id = run_steps.workspace_id
                    WHERE run_steps.status = 'created'
                      AND (run_steps.next_retry_at IS NULL OR run_steps.next_retry_at <= $1)
                      AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
                ) AS run_steps_pending,
                (
                    SELECT COUNT(*)
                    FROM run_steps
                    JOIN workspaces ON workspaces.workspace_id = run_steps.workspace_id
                    WHERE run_steps.status = 'claimed'
                      AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
                ) AS run_steps_claimed,
                (
                    SELECT COUNT(*)
                    FROM tool_calls
                    JOIN workspaces ON workspaces.workspace_id = tool_calls.workspace_id
                    WHERE tool_calls.status = 'created'
                      AND (tool_calls.next_retry_at IS NULL OR tool_calls.next_retry_at <= $1)
                      AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
                ) AS tool_calls_pending,
                (
                    SELECT COUNT(*)
                    FROM tool_calls
                    JOIN workspaces ON workspaces.workspace_id = tool_calls.workspace_id
                    WHERE tool_calls.status = 'claimed'
                      AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
                ) AS tool_calls_claimed,
                (
                    SELECT COUNT(*)
                    FROM tasks
                    JOIN workspaces ON workspaces.workspace_id = tasks.workspace_id
                    WHERE tasks.status = 'failed'
                      AND tasks.updated_at >= $2
                      AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
                ) AS tasks_failed_last_24h,
                (
                    SELECT COUNT(*)
                    FROM run_steps
                    JOIN workspaces ON workspaces.workspace_id = run_steps.workspace_id
                    WHERE run_steps.status = 'failed'
                      AND run_steps.updated_at >= $2
                      AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
                ) AS run_steps_failed_last_24h,
                (
                    SELECT COUNT(*)
                    FROM tool_calls
                    JOIN workspaces ON workspaces.workspace_id = tool_calls.workspace_id
                    WHERE tool_calls.status = 'failed'
                      AND tool_calls.updated_at >= $2
                      AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
                ) AS tool_calls_failed_last_24h,
                (
                    SELECT EXTRACT(EPOCH FROM ($1 - MIN(submitted_at)))::bigint
                    FROM run_steps
                    JOIN workspaces ON workspaces.workspace_id = run_steps.workspace_id
                    WHERE run_steps.status = 'created'
                      AND (run_steps.next_retry_at IS NULL OR run_steps.next_retry_at <= $1)
                      AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
                ) AS oldest_run_step_pending_age_seconds,
                (
                    SELECT EXTRACT(EPOCH FROM ($1 - MIN(submitted_at)))::bigint
                    FROM tool_calls
                    JOIN workspaces ON workspaces.workspace_id = tool_calls.workspace_id
                    WHERE tool_calls.status = 'created'
                      AND (tool_calls.next_retry_at IS NULL OR tool_calls.next_retry_at <= $1)
                      AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
                ) AS oldest_tool_call_pending_age_seconds
            """,
            now,
            since,
            organization_id,
        )
        return dict(row or {})

    async def get_global_token_total(
        self,
        *,
        day_start,
        day_end,
        organization_id: UUID | None = None,
    ) -> int:
        total = await self._pool.fetchval(
            """
            SELECT COALESCE(
                SUM(
                    CASE
                        WHEN output ? 'usage'
                         AND output->'usage' ? 'total_tokens'
                        THEN COALESCE((output->'usage'->>'total_tokens')::bigint, 0)
                        ELSE 0
                    END
                ),
                0
            )
            FROM runs
            JOIN workspaces ON workspaces.workspace_id = runs.workspace_id
            WHERE runs.updated_at >= $1
              AND runs.updated_at < $2
              AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
            """,
            day_start,
            day_end,
            organization_id,
        )
        return int(total or 0)

    async def get_workspace_token_total(
        self,
        *,
        workspace_id: UUID,
        day_start,
        day_end,
    ) -> int:
        total = await self._pool.fetchval(
            """
            SELECT COALESCE(
                SUM(
                    CASE
                        WHEN output ? 'usage'
                         AND output->'usage' ? 'total_tokens'
                        THEN COALESCE((output->'usage'->>'total_tokens')::bigint, 0)
                        ELSE 0
                    END
                ),
                0
            )
            FROM runs
            WHERE workspace_id = $1
              AND runs.updated_at >= $2
              AND runs.updated_at < $3
            """,
            workspace_id,
            day_start,
            day_end,
        )
        return int(total or 0)

    async def list_workspace_token_totals(
        self,
        *,
        day_start,
        day_end,
        organization_id: UUID | None = None,
    ) -> list[dict[str, int | UUID]]:
        rows = await self._pool.fetch(
            """
            SELECT runs.workspace_id,
                   COALESCE(
                       SUM(
                           CASE
                               WHEN output ? 'usage'
                                AND output->'usage' ? 'total_tokens'
                               THEN COALESCE((output->'usage'->>'total_tokens')::bigint, 0)
                               ELSE 0
                           END
                       ),
                       0
            ) AS total_tokens
            FROM runs
            JOIN workspaces ON workspaces.workspace_id = runs.workspace_id
            WHERE runs.updated_at >= $1
              AND runs.updated_at < $2
              AND ($3::uuid IS NULL OR workspaces.organization_id = $3)
            GROUP BY runs.workspace_id
            HAVING COALESCE(
                SUM(
                    CASE
                        WHEN output ? 'usage'
                         AND output->'usage' ? 'total_tokens'
                        THEN COALESCE((output->'usage'->>'total_tokens')::bigint, 0)
                        ELSE 0
                    END
                ),
                0
            ) > 0
            ORDER BY total_tokens DESC, runs.workspace_id ASC
            """,
            day_start,
            day_end,
            organization_id,
        )
        return [
            {"workspace_id": row["workspace_id"], "total_tokens": int(row["total_tokens"] or 0)}
            for row in rows
        ]

    async def upsert_interaction_request(
        self,
        conn: asyncpg.Connection,
        request: InteractionRequest,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO interaction_requests (
                request_id, workspace_id, thread_id, status, requester_participant_id,
                requester_message_id, requester_run_id, requester_task_id, title, summary,
                completion_rule, timeout_at, completed_at, created_at, updated_at, metadata
            )
            VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16
            )
            ON CONFLICT (request_id) DO UPDATE
                SET status = EXCLUDED.status,
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    completion_rule = EXCLUDED.completion_rule,
                    timeout_at = EXCLUDED.timeout_at,
                    completed_at = EXCLUDED.completed_at,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            request.request_id,
            request.workspace_id,
            request.thread_id,
            request.status,
            request.requester_participant_id,
            request.requester_message_id,
            request.requester_run_id,
            request.requester_task_id,
            request.title,
            request.summary,
            self._json_dumps(request.completion_rule.model_dump(mode="json")),
            request.timeout_at,
            request.completed_at,
            request.created_at,
            request.updated_at,
            self._json_dumps(request.metadata),
        )

    async def upsert_interaction_request_question(
        self,
        conn: asyncpg.Connection,
        question: InteractionQuestion,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO interaction_request_questions (
                question_id, request_id, prompt, kind, expected_format, question_order, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (question_id) DO UPDATE
                SET prompt = EXCLUDED.prompt,
                    kind = EXCLUDED.kind,
                    expected_format = EXCLUDED.expected_format,
                    question_order = EXCLUDED.question_order,
                    metadata = EXCLUDED.metadata
            """,
            question.question_id,
            question.request_id,
            question.prompt,
            question.kind,
            question.expected_format,
            question.order,
            self._json_dumps(question.metadata),
        )

    async def upsert_interaction_request_target(
        self,
        conn: asyncpg.Connection,
        target: InteractionRequestTarget,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO interaction_request_targets (
                target_id, request_id, participant_id, selector_type, selector_value,
                selection_source, score, status, answered_message_id, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (target_id) DO UPDATE
                SET participant_id = EXCLUDED.participant_id,
                    selector_type = EXCLUDED.selector_type,
                    selector_value = EXCLUDED.selector_value,
                    selection_source = EXCLUDED.selection_source,
                    score = EXCLUDED.score,
                    status = EXCLUDED.status,
                    answered_message_id = EXCLUDED.answered_message_id,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            target.target_id,
            target.request_id,
            target.participant_id,
            target.selector_type,
            target.selector_value,
            target.selection_source,
            target.score,
            target.status,
            target.answered_message_id,
            target.created_at,
            target.updated_at,
            self._json_dumps(target.metadata),
        )

    async def upsert_interaction_answer(
        self,
        conn: asyncpg.Connection,
        answer: InteractionAnswer,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO interaction_answers (
                answer_id, request_id, participant_id, message_id, question_ids, created_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (answer_id) DO UPDATE
                SET message_id = EXCLUDED.message_id,
                    question_ids = EXCLUDED.question_ids,
                    metadata = EXCLUDED.metadata
            """,
            answer.answer_id,
            answer.request_id,
            answer.participant_id,
            answer.message_id,
            answer.question_ids,
            answer.created_at,
            self._json_dumps(answer.metadata),
        )

    async def fetch_interaction_request(
        self,
        request_id: UUID,
    ) -> InteractionRequest | None:
        row = await self._pool.fetchrow(
            """
            SELECT request_id, workspace_id, thread_id, status, requester_participant_id,
                   requester_message_id, requester_run_id, requester_task_id, title, summary,
                   completion_rule, timeout_at, completed_at, created_at, updated_at, metadata
            FROM interaction_requests
            WHERE request_id = $1
            """,
            request_id,
        )
        return self._interaction_request_from_row(row) if row else None

    async def list_interaction_requests_for_thread(
        self,
        thread_id: UUID,
    ) -> list[InteractionRequest]:
        rows = await self._pool.fetch(
            """
            SELECT request_id, workspace_id, thread_id, status, requester_participant_id,
                   requester_message_id, requester_run_id, requester_task_id, title, summary,
                   completion_rule, timeout_at, completed_at, created_at, updated_at, metadata
            FROM interaction_requests
            WHERE thread_id = $1
            ORDER BY created_at ASC
            """,
            thread_id,
        )
        return [self._interaction_request_from_row(row) for row in rows]

    async def list_open_interaction_requests_for_run(
        self,
        requester_run_id: UUID,
    ) -> list[InteractionRequest]:
        rows = await self._pool.fetch(
            """
            SELECT request_id, workspace_id, thread_id, status, requester_participant_id,
                   requester_message_id, requester_run_id, requester_task_id, title, summary,
                   completion_rule, timeout_at, completed_at, created_at, updated_at, metadata
            FROM interaction_requests
            WHERE requester_run_id = $1
              AND status = 'open'
            ORDER BY created_at ASC
            """,
            requester_run_id,
        )
        return [self._interaction_request_from_row(row) for row in rows]

    async def list_interaction_request_questions(
        self,
        request_id: UUID,
    ) -> list[InteractionQuestion]:
        rows = await self._pool.fetch(
            """
            SELECT question_id, request_id, prompt, kind, expected_format, question_order, metadata
            FROM interaction_request_questions
            WHERE request_id = $1
            ORDER BY question_order ASC, question_id ASC
            """,
            request_id,
        )
        return [self._interaction_question_from_row(row) for row in rows]

    async def list_interaction_request_targets(
        self,
        request_id: UUID,
    ) -> list[InteractionRequestTarget]:
        rows = await self._pool.fetch(
            """
            SELECT target_id, request_id, participant_id, selector_type, selector_value,
                   selection_source, score, status, answered_message_id, created_at, updated_at, metadata
            FROM interaction_request_targets
            WHERE request_id = $1
            ORDER BY created_at ASC, target_id ASC
            """,
            request_id,
        )
        return [self._interaction_request_target_from_row(row) for row in rows]

    async def fetch_interaction_request_target(
        self,
        target_id: UUID,
    ) -> InteractionRequestTarget | None:
        row = await self._pool.fetchrow(
            """
            SELECT target_id, request_id, participant_id, selector_type, selector_value,
                   selection_source, score, status, answered_message_id, created_at, updated_at, metadata
            FROM interaction_request_targets
            WHERE target_id = $1
            """,
            target_id,
        )
        return self._interaction_request_target_from_row(row) if row else None

    async def list_interaction_answers(
        self,
        request_id: UUID,
    ) -> list[InteractionAnswer]:
        rows = await self._pool.fetch(
            """
            SELECT answer_id, request_id, participant_id, message_id, question_ids, created_at, metadata
            FROM interaction_answers
            WHERE request_id = $1
            ORDER BY created_at ASC, answer_id ASC
            """,
            request_id,
        )
        return [self._interaction_answer_from_row(row) for row in rows]

    async def get_interaction_request_detail(
        self,
        request_id: UUID,
    ) -> InteractionRequestDetail | None:
        request = await self.fetch_interaction_request(request_id)
        if request is None:
            return None
        return InteractionRequestDetail(
            request=request,
            questions=await self.list_interaction_request_questions(request_id),
            targets=await self.list_interaction_request_targets(request_id),
            answers=await self.list_interaction_answers(request_id),
        )

    async def list_interaction_request_details_for_thread(
        self,
        thread_id: UUID,
    ) -> list[InteractionRequestDetail]:
        requests = await self.list_interaction_requests_for_thread(thread_id)
        details: list[InteractionRequestDetail] = []
        for request in requests:
            details.append(
                InteractionRequestDetail(
                    request=request,
                    questions=await self.list_interaction_request_questions(request.request_id),
                    targets=await self.list_interaction_request_targets(request.request_id),
                    answers=await self.list_interaction_answers(request.request_id),
                )
            )
        return details

    async def fetch_message(self, message_id: UUID) -> TimelineMessage | None:
        row = await self._pool.fetchrow(
            """
            SELECT message_id, workspace_id, thread_id, actor_type, actor_id, visibility,
                   content, status, correlation_id, causation_id, sequence, created_at, updated_at, metadata
            FROM timeline_messages
            WHERE message_id = $1
            """,
            message_id,
        )
        return self._timeline_message_from_row(row) if row else None

    async def fetch_thread(self, thread_id: UUID) -> Thread | None:
        row = await self._pool.fetchrow(
            """
            SELECT thread_id, workspace_id, title, state, parent_thread_id,
                   previous_thread_id, related_thread_ids, created_at, updated_at, metadata
            FROM threads
            WHERE thread_id = $1
            """,
            thread_id,
        )
        return self._thread_from_row(row) if row else None

    async def list_threads(self, workspace_id: UUID) -> list[Thread]:
        rows = await self._pool.fetch(
            """
            SELECT thread_id, workspace_id, title, state, parent_thread_id,
                   previous_thread_id, related_thread_ids, created_at, updated_at, metadata
            FROM threads
            WHERE workspace_id = $1
            ORDER BY created_at ASC
            """,
            workspace_id,
        )
        return [self._thread_from_row(row) for row in rows]

    async def list_memberships(self, thread_id: UUID) -> list[Membership]:
        rows = await self._pool.fetch(
            """
            SELECT membership_id, workspace_id, thread_id, participant_id, role,
                   permissions, joined_at, left_at, metadata
            FROM memberships
            WHERE thread_id = $1
            ORDER BY joined_at ASC
            """,
            thread_id,
        )
        return [self._membership_from_row(row) for row in rows]

    async def list_memory_entries(self, workspace_id: UUID) -> list[MemoryEntry]:
        return await self.list_memory_entries_for_scope(
            scope="workspace",
            workspace_id=workspace_id,
            state="confirmed",
        )

    async def list_memory_entries_for_scope(
        self,
        *,
        scope: str,
        workspace_id: UUID | None = None,
        thread_id: UUID | None = None,
        run_id: UUID | None = None,
        state: str | None = None,
    ) -> list[MemoryEntry]:
        rows = await self._pool.fetch(
            """
            SELECT memory_entry_id, scope, state, workspace_id, thread_id, run_id,
                   entry_type, content, summary, source, visibility, created_by, updated_by,
                   confirmed_by, confirmed_at, version, metadata, created_at, updated_at
            FROM memory_entries
            WHERE scope = $1
              AND ($2::uuid IS NULL OR workspace_id = $2)
              AND ($3::uuid IS NULL OR thread_id = $3)
              AND ($4::uuid IS NULL OR run_id = $4)
              AND ($5::text IS NULL OR state = $5)
            ORDER BY updated_at DESC
            """,
            scope,
            workspace_id,
            thread_id,
            run_id,
            state,
        )
        return [self._memory_entry_from_row(row) for row in rows]

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
        pattern = f"%{query.strip()}%"
        rows = await self._pool.fetch(
            """
            SELECT memory_entry_id, scope, state, workspace_id, thread_id, run_id,
                   entry_type, content, summary, source, visibility, created_by, updated_by,
                   confirmed_by, confirmed_at, version, metadata, created_at, updated_at
            FROM memory_entries
            WHERE scope = $1
              AND ($2::uuid IS NULL OR workspace_id = $2)
              AND ($3::uuid IS NULL OR thread_id = $3)
              AND ($4::uuid IS NULL OR run_id = $4)
              AND ($5::text IS NULL OR state = $5)
              AND (
                    content ILIKE $6
                 OR COALESCE(summary, '') ILIKE $6
                 OR entry_type ILIKE $6
              )
            ORDER BY updated_at DESC
            LIMIT $7
            """,
            scope,
            workspace_id,
            thread_id,
            run_id,
            state,
            pattern,
            limit,
        )
        return [self._memory_entry_from_row(row) for row in rows]

    async def fetch_memory_entry(self, memory_entry_id: UUID) -> MemoryEntry | None:
        row = await self._pool.fetchrow(
            """
            SELECT memory_entry_id, scope, state, workspace_id, thread_id, run_id,
                   entry_type, content, summary, source, visibility, created_by, updated_by,
                   confirmed_by, confirmed_at, version, metadata, created_at, updated_at
            FROM memory_entries
            WHERE memory_entry_id = $1
            """,
            memory_entry_id,
        )
        return self._memory_entry_from_row(row) if row else None

    async def list_memory_providers(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[MemoryProviderDefinition]:
        rows = await self._pool.fetch(
            """
            SELECT provider_id, scope, organization_id, provider_key, display_name, description, provider, enabled,
                   config, secret_config, created_by, created_at, updated_by, updated_at, metadata
            FROM memory_providers
            WHERE scope = $1
              AND (
                    ($2::uuid IS NULL AND organization_id IS NULL)
                 OR organization_id = $2
              )
            ORDER BY created_at ASC
            """,
            scope,
            organization_id,
        )
        return [self._memory_provider_from_row(row) for row in rows]

    async def list_enabled_memory_providers(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[MemoryProviderDefinition]:
        rows = await self._pool.fetch(
            """
            SELECT provider_id, scope, organization_id, provider_key, display_name, description, provider, enabled,
                   config, secret_config, created_by, created_at, updated_by, updated_at, metadata
            FROM memory_providers
            WHERE enabled = TRUE
              AND scope = $1
              AND (
                    ($2::uuid IS NULL AND organization_id IS NULL)
                 OR organization_id = $2
              )
            ORDER BY created_at ASC
            """,
            scope,
            organization_id,
        )
        return [self._memory_provider_from_row(row) for row in rows]

    async def fetch_memory_provider(
        self, provider_id: UUID
    ) -> MemoryProviderDefinition | None:
        row = await self._pool.fetchrow(
            """
            SELECT provider_id, scope, organization_id, provider_key, display_name, description, provider, enabled,
                   config, secret_config, created_by, created_at, updated_by, updated_at, metadata
            FROM memory_providers
            WHERE provider_id = $1
            """,
            provider_id,
        )
        return self._memory_provider_from_row(row) if row else None

    async def fetch_memory_provider_by_key(
        self,
        provider_key: str,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> MemoryProviderDefinition | None:
        row = await self._pool.fetchrow(
            """
            SELECT provider_id, scope, organization_id, provider_key, display_name, description, provider, enabled,
                   config, secret_config, created_by, created_at, updated_by, updated_at, metadata
            FROM memory_providers
            WHERE provider_key = $1
              AND scope = $2
              AND (
                    ($3::uuid IS NULL AND organization_id IS NULL)
                 OR organization_id = $3
              )
            """,
            provider_key,
            scope,
            organization_id,
        )
        return self._memory_provider_from_row(row) if row else None

    async def list_memory_provider_records(
        self, memory_entry_id: UUID
    ) -> list[MemoryProviderRecord]:
        rows = await self._pool.fetch(
            """
            SELECT provider_record_id, memory_entry_id, provider_id, external_id, status,
                   last_synced_at, last_error, metadata
            FROM memory_provider_records
            WHERE memory_entry_id = $1
            ORDER BY provider_id ASC
            """,
            memory_entry_id,
        )
        return [self._memory_provider_record_from_row(row) for row in rows]

    async def fetch_memory_provider_record(
        self,
        *,
        memory_entry_id: UUID,
        provider_id: UUID,
    ) -> MemoryProviderRecord | None:
        row = await self._pool.fetchrow(
            """
            SELECT provider_record_id, memory_entry_id, provider_id, external_id, status,
                   last_synced_at, last_error, metadata
            FROM memory_provider_records
            WHERE memory_entry_id = $1
              AND provider_id = $2
            """,
            memory_entry_id,
            provider_id,
        )
        return self._memory_provider_record_from_row(row) if row else None

    async def list_timeline_messages(self, thread_id: UUID) -> list[TimelineMessage]:
        rows = await self._pool.fetch(
            """
            SELECT message_id, workspace_id, thread_id, actor_type, actor_id, visibility,
                   content, status, correlation_id, causation_id, sequence, created_at, updated_at, metadata
            FROM timeline_messages
            WHERE thread_id = $1
            ORDER BY sequence ASC
            """,
            thread_id,
        )
        return [self._timeline_message_from_row(row) for row in rows]

    async def list_workspace_communication_log(
        self,
        workspace_id: UUID,
        *,
        thread_id: UUID | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> WorkspaceCommunicationLogPage:
        total_count = await self._pool.fetchval(
            """
            SELECT COUNT(*)
            FROM timeline_messages
            WHERE workspace_id = $1
              AND ($2::uuid IS NULL OR thread_id = $2)
            """,
            workspace_id,
            thread_id,
        )
        rows = await self._pool.fetch(
            """
            SELECT m.message_id,
                   m.workspace_id,
                   m.thread_id,
                   t.title AS thread_title,
                   m.actor_type,
                   m.actor_id,
                   COALESCE(u.display_name, sa.display_name, p.metadata->>'display_name', m.actor_id::text)
                       AS actor_display_name,
                   m.visibility,
                   m.content,
                   m.status,
                   m.correlation_id,
                   m.causation_id,
                   m.sequence,
                   m.created_at,
                   m.updated_at,
                   m.metadata
            FROM timeline_messages AS m
            JOIN threads AS t ON t.thread_id = m.thread_id
            LEFT JOIN participants AS p
                   ON p.participant_id = m.actor_id
                  AND p.workspace_id = m.workspace_id
            LEFT JOIN users AS u ON u.user_id = p.user_id
            LEFT JOIN system_agents AS sa ON sa.agent_id = p.system_agent_id
            WHERE m.workspace_id = $1
              AND ($2::uuid IS NULL OR m.thread_id = $2)
            ORDER BY m.created_at DESC, m.sequence DESC, m.message_id DESC
            LIMIT $3 OFFSET $4
            """,
            workspace_id,
            thread_id,
            limit,
            offset,
        )
        return WorkspaceCommunicationLogPage(
            workspace_id=workspace_id,
            entries=[
                self._workspace_communication_log_entry_from_row(row)
                for row in rows
            ],
            total_count=int(total_count or 0),
        )

    async def persist_workspace_communication_messages(
        self,
        messages: Sequence[TimelineMessage],
    ) -> None:
        if self._communication_log_dir is None:
            return
        entries: list[WorkspaceCommunicationLogEntry] = []
        for message in messages:
            if message.status in {"draft", "streaming"}:
                continue
            thread = await self.fetch_thread(message.thread_id)
            if thread is None:
                continue
            participant = await self.fetch_participant(
                message.workspace_id,
                message.actor.id,
            )
            actor_display_name = (
                participant.display_name if participant is not None else str(message.actor.id)
            )
            entries.append(
                self._workspace_communication_log_entry_from_message(
                    message,
                    thread_title=thread.title,
                    actor_display_name=actor_display_name,
                )
            )
        if not entries:
            return
        await asyncio.to_thread(
            self._append_workspace_communication_log_entries_sync,
            entries,
        )

    async def list_thread_events(
        self, thread_id: UUID, *, after_sequence: int | None = None
    ) -> list[EventEnvelope]:
        sequence_floor = after_sequence or 0
        rows = await self._pool.fetch(
            """
            SELECT event_id, schema_version, event_type, workspace_id, thread_id,
                   actor_type, actor_id, target_type, target_id, visibility,
                   correlation_id, causation_id, sequence, payload, created_at
            FROM collab_event_log
            WHERE thread_id = $1
              AND COALESCE(sequence, 0) > $2
            ORDER BY sequence ASC, created_at ASC
            """,
            thread_id,
            sequence_floor,
        )
        return [self._event_from_row(row) for row in rows]

    @staticmethod
    def _task_from_row(row: asyncpg.Record) -> Task:
        return Task(
            task_id=row["task_id"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            title=row["title"],
            description=row["description"],
            status=row["status"],
            requested_by=row["requested_by"],
            claimed_by=row["claimed_by"],
            visibility=row["visibility"],
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _run_from_row(row: asyncpg.Record) -> Run:
        return Run(
            run_id=row["run_id"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            task_id=row["task_id"],
            participant_id=row["participant_id"],
            status=row["status"],
            output=CollaborationRepository._json_value(row["output"], default={}),
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _run_step_from_row(row: asyncpg.Record) -> RunStep:
        return RunStep(
            step_id=row["step_id"],
            run_id=row["run_id"],
            task_id=row["task_id"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            system_agent_id=row["system_agent_id"],
            step_index=row["step_index"],
            kind=row["kind"],
            status=row["status"],
            input=CollaborationRepository._json_value(row["input"], default={}),
            output=CollaborationRepository._json_value(row["output"], default={}),
            claimed_by_worker=row["claimed_by_worker"],
            lease_expires_at=row["lease_expires_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
            next_retry_at=row["next_retry_at"],
            attempt_count=row["attempt_count"],
            error=row["error"],
            execution_handle=row["execution_handle"],
            submitted_at=row["submitted_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _tool_call_from_row(row: asyncpg.Record) -> ToolCall:
        result_payload = CollaborationRepository._json_value(row["result"], default=None)
        return ToolCall(
            tool_call_id=row["tool_call_id"],
            run_id=row["run_id"],
            run_step_id=row["run_step_id"],
            task_id=row["task_id"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            system_agent_id=row["system_agent_id"],
            tool_id=row["tool_id"],
            tool_name=row["tool_name"],
            status=row["status"],
            arguments=CollaborationRepository._json_value(row["arguments"], default={}),
            execution_spec=CollaborationRepository._json_value(
                row["execution_spec"], default={}
            ),
            claimed_by_worker=row["claimed_by_worker"],
            lease_expires_at=row["lease_expires_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
            next_retry_at=row["next_retry_at"],
            attempt_count=row["attempt_count"],
            error=row["error"],
            execution_handle=row["execution_handle"],
            result=(
                ToolCallResult.model_validate(result_payload)
                if result_payload is not None
                else None
            ),
            submitted_at=row["submitted_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _workspace_from_row(row: asyncpg.Record) -> Workspace:
        return Workspace(
            workspace_id=row["workspace_id"],
            organization_id=row["organization_id"],
            name=row["name"],
            description=row["description"],
            owner_user_id=row["owner_user_id"],
            harness=(
                WorkspaceHarness.model_validate(
                    CollaborationRepository._json_value(row["harness"], default={})
                )
                if row["harness"] is not None
                else None
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _organization_from_row(row: asyncpg.Record) -> Organization:
        return Organization(
            organization_id=row["organization_id"],
            slug=row["slug"],
            name=row["name"],
            description=row["description"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _user_from_row(row: asyncpg.Record) -> UserRecord:
        return UserRecord(
            user_id=row["user_id"],
            display_name=row["display_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _organization_membership_from_row(
        row: asyncpg.Record,
    ) -> OrganizationMembership:
        return OrganizationMembership(
            organization_id=row["organization_id"],
            user_id=row["user_id"],
            role=row["role"],
            joined_at=row["joined_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _thread_from_row(row: asyncpg.Record) -> Thread:
        return Thread(
            thread_id=row["thread_id"],
            workspace_id=row["workspace_id"],
            title=row["title"],
            state=row["state"],
            parent_thread_id=row["parent_thread_id"],
            previous_thread_id=row["previous_thread_id"],
            related_thread_ids=list(
                CollaborationRepository._json_value(
                    row["related_thread_ids"], default=[]
                )
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _participant_from_row(row: asyncpg.Record) -> ParticipantProfile:
        metadata = CollaborationRepository._json_value(row["metadata"], default={})
        participant_type = row["participant_type"]
        display_name = (
            row["agent_display_name"]
            if participant_type == "agent"
            else row["user_display_name"]
        )
        if not display_name:
            display_name = metadata.get("display_name") or str(row["participant_id"])
        description = (
            row["agent_description"]
            if participant_type == "agent"
            else row["description"]
        )
        roles = list(CollaborationRepository._json_value(row["roles"], default=[]))
        capabilities = (
            list(CollaborationRepository._json_value(row["agent_capabilities"], default=[]))
            if participant_type == "agent"
            else list(CollaborationRepository._json_value(row["capabilities"], default=[]))
        )
        return ParticipantProfile(
            participant_id=row["participant_id"],
            workspace_id=row["workspace_id"],
            participant_type=participant_type,
            user_id=row["user_id"],
            system_agent_id=row["system_agent_id"],
            display_name=display_name,
            description=description,
            roles=roles,
            capabilities=capabilities,
            status=row["status"],
            visibility_scope=row["visibility_scope"],
            agent_config=(
                AgentConfiguration(
                    endpoint=AgentEndpoint.model_validate(
                        CollaborationRepository._json_value(row["agent_endpoint"], default={})
                    ),
                    system_prompt=row["agent_system_prompt"],
                    harness=(
                        AgentHarness.model_validate(
                            CollaborationRepository._json_value(
                                row["agent_harness"], default={}
                            )
                        )
                        if row["agent_harness"] is not None
                        else None
                    ),
                    definition=CollaborationRepository._json_value(
                        row["agent_definition"], default={}
                    ),
                )
                if participant_type == "agent" and row["agent_system_prompt"] is not None
                else None
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=metadata,
        )

    @staticmethod
    def _auth_identity_from_row(row: asyncpg.Record) -> AuthIdentityRecord:
        return AuthIdentityRecord(
            user_id=row["user_id"],
            issuer=row["issuer"],
            subject=row["subject"],
            email=row["email"],
            display_name=row["display_name"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _iam_role_definition_from_row(row: asyncpg.Record) -> IamRoleDefinition:
        return IamRoleDefinition(
            role_id=row["role_id"],
            scope=row["scope"],
            subject_kind=row["subject_kind"],
            organization_id=row["organization_id"],
            name=row["name"],
            description=row["description"],
            permissions=list(
                CollaborationRepository._json_value(row["permissions"], default=[])
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _human_role_binding_from_row(row: asyncpg.Record) -> HumanRoleBinding:
        return HumanRoleBinding(
            user_id=row["user_id"],
            role_id=row["role_id"],
            created_at=row["created_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _agent_identity_from_row(row: asyncpg.Record) -> AgentIdentity:
        return AgentIdentity(
            agent_identity_id=row["agent_identity_id"],
            system_agent_id=row["system_agent_id"],
            scope=row["scope"],
            organization_id=row["organization_id"],
            provider_key=row["provider_key"],
            issuer=row["issuer"],
            external_subject=row["external_subject"],
            client_id=row["client_id"],
            status=row["status"],
            secret_ref=CollaborationRepository._json_value(row["secret_ref"], default={}),
            last_authenticated_at=row["last_authenticated_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _agent_role_binding_from_row(row: asyncpg.Record) -> AgentRoleBinding:
        return AgentRoleBinding(
            agent_identity_id=row["agent_identity_id"],
            role_id=row["role_id"],
            created_at=row["created_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _system_agent_from_row(row: asyncpg.Record) -> AgentDefinition:
        return AgentDefinition(
            agent_id=row["agent_id"],
            scope=row["scope"],
            organization_id=row["organization_id"],
            display_name=row["display_name"],
            description=row["description"],
            role=row["role"],
            capabilities=list(
                CollaborationRepository._json_value(row["capabilities"], default=[])
            ),
            endpoint=AgentEndpoint.model_validate(
                CollaborationRepository._json_value(row["endpoint"], default={})
            ),
            system_prompt=row["system_prompt"],
            harness=(
                AgentHarness.model_validate(
                    CollaborationRepository._json_value(row["harness"], default={})
                )
                if row["harness"] is not None
                else None
            ),
            interaction_contract=AgentInteractionContract.model_validate(
                CollaborationRepository._json_value(
                    row["interaction_contract"],
                    default={},
                )
            ),
            definition=CollaborationRepository._json_value(row["definition"], default={}),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _system_tool_from_row(row: asyncpg.Record) -> SystemToolDefinition:
        return SystemToolDefinition(
            tool_id=row["tool_id"],
            scope=row["scope"],
            organization_id=row["organization_id"],
            name=row["name"],
            description=row["description"],
            parameter_contract=ToolParameterContract.model_validate(
                CollaborationRepository._json_value(
                    row["parameter_contract"], default={}
                )
            ),
            input_schema=CollaborationRepository._json_value(
                row["input_schema"], default={}
            ),
            execution=ToolExecutionBinding(
                backend_kind=row["backend_kind"],
                handler_ref=row["handler_ref"],
                execution_profile=CollaborationRepository._json_value(
                    row["execution_profile"], default={}
                ),
                trust_level=row["trust_level"],
            ),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_by=row["updated_by"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _llm_provider_from_row(row: asyncpg.Record) -> LlmProviderDefinition:
        return LlmProviderDefinition(
            provider_id=row["provider_id"],
            scope=row["scope"],
            organization_id=row["organization_id"],
            engine_id=row["engine_id"],
            display_name=row["display_name"],
            description=row["description"],
            provider=row["provider"],
            endpoint_kind=row["endpoint_kind"],
            url=row["url"],
            default_model=row["default_model"],
            capabilities=list(
                CollaborationRepository._json_value(row["capabilities"], default=[])
            ),
            locality=row["locality"],
            priority=row["priority"],
            enabled=row["enabled"],
            secret_config=CollaborationRepository._json_value(
                row["secret_config"],
                default={},
            ),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_by=row["updated_by"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _workspace_tool_from_row(row: asyncpg.Record) -> WorkspaceTool:
        return WorkspaceTool(
            tool_id=row["tool_id"],
            name=row["name"],
            description=row["description"],
            parameter_contract=ToolParameterContract.model_validate(
                CollaborationRepository._json_value(
                    row["parameter_contract"], default={}
                )
            ),
            input_schema=CollaborationRepository._json_value(
                row["input_schema"], default={}
            ),
            execution=ToolExecutionBinding(
                backend_kind=row["backend_kind"],
                handler_ref=row["handler_ref"],
                execution_profile=CollaborationRepository._json_value(
                    row["execution_profile"], default={}
                ),
                trust_level=row["trust_level"],
            ),
            enabled=row["enabled"],
            attached_by=row["attached_by"],
            attached_at=row["attached_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _agent_internal_tool_from_row(row: asyncpg.Record) -> AgentInternalToolBinding:
        return AgentInternalToolBinding(
            system_agent_id=row["system_agent_id"],
            tool_id=row["tool_id"],
            name=row["name"],
            description=row["description"],
            parameter_contract=ToolParameterContract.model_validate(
                CollaborationRepository._json_value(
                    row["parameter_contract"], default={}
                )
            ),
            input_schema=CollaborationRepository._json_value(
                row["input_schema"], default={}
            ),
            execution=ToolExecutionBinding(
                backend_kind=row["backend_kind"],
                handler_ref=row["handler_ref"],
                execution_profile=CollaborationRepository._json_value(
                    row["execution_profile"], default={}
                ),
                trust_level=row["trust_level"],
            ),
            enabled=row["enabled"],
            attached_by=row["attached_by"],
            attached_at=row["attached_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _tool_generation_request_from_row(
        row: asyncpg.Record,
    ) -> ToolGenerationRequest:
        return ToolGenerationRequest(
            request_id=row["request_id"],
            organization_id=row["organization_id"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            requester_participant_id=row["requester_participant_id"],
            requester_message_id=row["requester_message_id"],
            target_system_agent_id=row["target_system_agent_id"],
            requested_scope=row["requested_scope"],
            status=row["status"],
            target_tool_name=row["target_tool_name"],
            summary=row["summary"],
            final_tool_id=row["final_tool_id"],
            latest_revision_id=row["latest_revision_id"],
            approved_by=row["approved_by"],
            approved_at=row["approved_at"],
            rejected_by=row["rejected_by"],
            rejected_at=row["rejected_at"],
            published_at=row["published_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _tool_generation_revision_from_row(
        row: asyncpg.Record,
    ) -> ToolGenerationRevision:
        return ToolGenerationRevision(
            revision_id=row["revision_id"],
            request_id=row["request_id"],
            revision_number=row["revision_number"],
            status=row["status"],
            manifest=GeneratedToolManifest.model_validate(
                CollaborationRepository._json_value(row["manifest"], default={})
            ),
            validation_report=(
                GeneratedToolValidationReport.model_validate(
                    CollaborationRepository._json_value(
                        row["validation_report"], default={}
                    )
                )
                if row["validation_report"] is not None
                else None
            ),
            source_asset_id=row["source_asset_id"],
            source_asset_version_id=row["source_asset_version_id"],
            manifest_asset_id=row["manifest_asset_id"],
            manifest_asset_version_id=row["manifest_asset_version_id"],
            report_asset_id=row["report_asset_id"],
            report_asset_version_id=row["report_asset_version_id"],
            image_ref=row["image_ref"],
            image_digest=row["image_digest"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _git_repository_from_row(row: asyncpg.Record) -> GitRepository:
        return GitRepository(
            repo_id=row["repo_id"],
            organization_id=row["organization_id"],
            workspace_id=row["workspace_id"],
            scope=row["scope"],
            name=row["name"],
            forgejo_url=row["forgejo_url"],
            clone_url=row["clone_url"],
            local_path=row["local_path"],
            default_branch=row["default_branch"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _workspace_asset_from_row(row: asyncpg.Record) -> WorkspaceAsset:
        return WorkspaceAsset(
            asset_id=row["asset_id"],
            organization_id=row["organization_id"],
            workspace_id=row["workspace_id"],
            scope=row["scope"],
            asset_type=row["asset_type"],
            logical_name=row["logical_name"],
            logical_path=row["logical_path"],
            title=row["title"],
            description=row["description"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _workspace_asset_version_from_row(row: asyncpg.Record) -> WorkspaceAssetVersion:
        return WorkspaceAssetVersion(
            asset_version_id=row["asset_version_id"],
            asset_id=row["asset_id"],
            version=row["version"],
            source_kind=row["source_kind"],
            git_repository_id=row["git_repository_id"],
            git_revision=row["git_revision"],
            git_path=row["git_path"],
            storage_backend=row["storage_backend"],
            bucket=row["bucket"],
            object_key=row["object_key"],
            content_type=row["content_type"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _asset_link_from_alias_row(row: asyncpg.Record) -> AssetLink:
        return AssetLink(
            link_id=row["link_id"],
            asset_id=row["link_asset_id"],
            asset_version_id=row["link_asset_version_id"],
            organization_id=row["link_organization_id"],
            workspace_id=row["link_workspace_id"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            purpose=row["purpose"],
            active=row["active"],
            created_by=row["link_created_by"],
            created_at=row["link_created_at"],
            updated_at=row["link_updated_at"],
            metadata=CollaborationRepository._json_value(row["link_metadata"], default={}),
        )

    @staticmethod
    def _resolved_asset_binding_from_row(row: asyncpg.Record) -> ResolvedAssetBinding:
        return ResolvedAssetBinding(
            purpose=row["purpose"],
            organization_id=row["link_organization_id"],
            workspace_id=row["link_workspace_id"],
            asset=WorkspaceAsset(
                asset_id=row["asset_id"],
                organization_id=row["asset_organization_id"],
                workspace_id=row["asset_workspace_id"],
                scope=row["scope"],
                asset_type=row["asset_type"],
                logical_name=row["logical_name"],
                logical_path=row["logical_path"],
                title=row["title"],
                description=row["description"],
                created_by=row["asset_created_by"],
                created_at=row["asset_created_at"],
                updated_at=row["asset_updated_at"],
                metadata=CollaborationRepository._json_value(row["asset_metadata"], default={}),
            ),
            version=WorkspaceAssetVersion(
                asset_version_id=row["asset_version_id"],
                asset_id=row["asset_id"],
                version=row["version"],
                source_kind=row["source_kind"],
                git_repository_id=row["git_repository_id"],
                git_revision=row["git_revision"],
                git_path=row["git_path"],
                storage_backend=row["storage_backend"],
                bucket=row["bucket"],
                object_key=row["object_key"],
                content_type=row["content_type"],
                size_bytes=row["size_bytes"],
                sha256=row["sha256"],
                created_by=row["version_created_by"],
                created_at=row["version_created_at"],
                metadata=CollaborationRepository._json_value(row["version_metadata"], default={}),
            ),
            link=CollaborationRepository._asset_link_from_alias_row(row),
        )

    @staticmethod
    def _interaction_request_from_row(row: asyncpg.Record) -> InteractionRequest:
        from open_talon_contracts.models import CompletionRule

        return InteractionRequest(
            request_id=row["request_id"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            status=row["status"],
            requester_participant_id=row["requester_participant_id"],
            requester_message_id=row["requester_message_id"],
            requester_run_id=row["requester_run_id"],
            requester_task_id=row["requester_task_id"],
            title=row["title"],
            summary=row["summary"],
            completion_rule=CompletionRule.model_validate(
                CollaborationRepository._json_value(row["completion_rule"], default={})
            ),
            timeout_at=row["timeout_at"],
            completed_at=row["completed_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _interaction_question_from_row(row: asyncpg.Record) -> InteractionQuestion:
        return InteractionQuestion(
            question_id=row["question_id"],
            request_id=row["request_id"],
            prompt=row["prompt"],
            kind=row["kind"],
            expected_format=row["expected_format"],
            order=row["question_order"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _interaction_request_target_from_row(
        row: asyncpg.Record,
    ) -> InteractionRequestTarget:
        return InteractionRequestTarget(
            target_id=row["target_id"],
            request_id=row["request_id"],
            participant_id=row["participant_id"],
            selector_type=row["selector_type"],
            selector_value=row["selector_value"],
            selection_source=row["selection_source"],
            score=row["score"],
            status=row["status"],
            answered_message_id=row["answered_message_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _interaction_answer_from_row(row: asyncpg.Record) -> InteractionAnswer:
        question_ids = row["question_ids"] or []
        return InteractionAnswer(
            answer_id=row["answer_id"],
            request_id=row["request_id"],
            participant_id=row["participant_id"],
            message_id=row["message_id"],
            question_ids=list(question_ids),
            created_at=row["created_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _membership_from_row(row: asyncpg.Record) -> Membership:
        return Membership(
            membership_id=row["membership_id"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            participant_id=row["participant_id"],
            role=row["role"],
            permissions=list(
                CollaborationRepository._json_value(row["permissions"], default=[])
            ),
            joined_at=row["joined_at"],
            left_at=row["left_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _memory_entry_from_row(row: asyncpg.Record) -> MemoryEntry:
        return MemoryEntry(
            memory_entry_id=row["memory_entry_id"],
            scope=row["scope"],
            state=row["state"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            run_id=row["run_id"],
            entry_type=row["entry_type"],
            content=row["content"],
            summary=row["summary"],
            source=row["source"],
            created_by=row["created_by"],
            updated_by=row["updated_by"],
            confirmed_by=row["confirmed_by"],
            confirmed_at=row["confirmed_at"],
            version=row["version"],
            visibility=row["visibility"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _memory_provider_from_row(row: asyncpg.Record) -> MemoryProviderDefinition:
        return MemoryProviderDefinition(
            provider_id=row["provider_id"],
            scope=row["scope"],
            organization_id=row["organization_id"],
            provider_key=row["provider_key"],
            display_name=row["display_name"],
            description=row["description"],
            provider=row["provider"],
            enabled=row["enabled"],
            config=CollaborationRepository._json_value(row["config"], default={}),
            secret_config=CollaborationRepository._json_value(
                row["secret_config"], default={}
            ),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_by=row["updated_by"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _memory_provider_record_from_row(row: asyncpg.Record) -> MemoryProviderRecord:
        return MemoryProviderRecord(
            provider_record_id=row["provider_record_id"],
            memory_entry_id=row["memory_entry_id"],
            provider_id=row["provider_id"],
            external_id=row["external_id"],
            status=row["status"],
            last_synced_at=row["last_synced_at"],
            last_error=row["last_error"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _timeline_message_from_row(row: asyncpg.Record) -> TimelineMessage:
        return TimelineMessage(
            message_id=row["message_id"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            actor=ActorRef(type=row["actor_type"], id=row["actor_id"]),
            visibility=row["visibility"],
            content=row["content"],
            status=row["status"],
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            sequence=row["sequence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
        )

    @staticmethod
    def _workspace_communication_log_entry_from_row(
        row: asyncpg.Record,
    ) -> WorkspaceCommunicationLogEntry:
        metadata = CollaborationRepository._json_value(row["metadata"], default={})
        interaction_request_id = CollaborationRepository._uuid_or_none(
            metadata.get("interaction_request_id")
        )
        interaction_question_ids = CollaborationRepository._uuid_list(
            metadata.get("interaction_question_ids", [])
        )
        if interaction_request_id is not None and "interaction_question_ids" in metadata:
            kind = "interaction_answer"
        elif interaction_request_id is not None:
            kind = "interaction_request"
        else:
            kind = "message"
        return WorkspaceCommunicationLogEntry(
            message_id=row["message_id"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            thread_title=row["thread_title"],
            actor=ActorRef(type=row["actor_type"], id=row["actor_id"]),
            actor_display_name=str(row["actor_display_name"] or row["actor_id"]),
            visibility=row["visibility"],
            kind=kind,
            content=row["content"],
            status=row["status"],
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            sequence=row["sequence"],
            interaction_request_id=interaction_request_id,
            interaction_request_status=metadata.get("interaction_request_status"),
            interaction_question_ids=interaction_question_ids,
            metadata=metadata,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _workspace_communication_log_entry_from_message(
        message: TimelineMessage,
        *,
        thread_title: str,
        actor_display_name: str,
    ) -> WorkspaceCommunicationLogEntry:
        metadata = dict(message.metadata)
        interaction_request_id = CollaborationRepository._uuid_or_none(
            metadata.get("interaction_request_id")
        )
        interaction_question_ids = CollaborationRepository._uuid_list(
            metadata.get("interaction_question_ids", [])
        )
        if interaction_request_id is not None and "interaction_question_ids" in metadata:
            kind = "interaction_answer"
        elif interaction_request_id is not None:
            kind = "interaction_request"
        else:
            kind = "message"
        return WorkspaceCommunicationLogEntry(
            message_id=message.message_id,
            workspace_id=message.workspace_id,
            thread_id=message.thread_id,
            thread_title=thread_title,
            actor=message.actor,
            actor_display_name=actor_display_name,
            visibility=message.visibility,
            kind=kind,
            content=message.content,
            status=message.status,
            correlation_id=message.correlation_id,
            causation_id=message.causation_id,
            sequence=message.sequence,
            interaction_request_id=interaction_request_id,
            interaction_request_status=metadata.get("interaction_request_status"),
            interaction_question_ids=interaction_question_ids,
            metadata=metadata,
            created_at=message.created_at,
            updated_at=message.updated_at,
        )

    def _append_workspace_communication_log_entries_sync(
        self,
        entries: Sequence[WorkspaceCommunicationLogEntry],
    ) -> None:
        if self._communication_log_dir is None:
            return
        grouped_payloads: dict[Path, list[bytes]] = {}
        for entry in entries:
            file_path = self._communication_log_dir / f"{entry.workspace_id}.jsonl"
            payload = (
                json.dumps(entry.model_dump(mode="json"), sort_keys=True).encode("utf-8")
                + b"\n"
            )
            grouped_payloads.setdefault(file_path, []).append(payload)
        for file_path, payloads in grouped_payloads.items():
            append_bytes_with_rotation(
                file_path,
                payloads,
                policy=self._communication_log_policy,
            )

    @staticmethod
    def _event_from_row(row: asyncpg.Record) -> EventEnvelope:
        from open_talon_contracts.models import TargetRef

        return EventEnvelope(
            event_id=row["event_id"],
            schema_version=row["schema_version"],
            event_type=row["event_type"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            actor=ActorRef(type=row["actor_type"], id=row["actor_id"]),
            target=TargetRef(type=row["target_type"], id=row["target_id"]),
            visibility=row["visibility"],
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            sequence=row["sequence"],
            timestamp=row["created_at"],
            payload=CollaborationRepository._json_value(row["payload"], default={}),
        )

    @staticmethod
    def _audit_event_from_row(row: asyncpg.Record) -> AuditEvent:
        return AuditEvent(
            audit_event_id=row["audit_event_id"],
            ledger_offset=row["ledger_offset"],
            occurred_at=row["occurred_at"],
            recorded_at=row["recorded_at"],
            scope_type=row["scope_type"],
            organization_id=row["organization_id"],
            workspace_id=row["workspace_id"],
            thread_id=row["thread_id"],
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            user_id=row["user_id"],
            system_agent_id=row["system_agent_id"],
            source_service=row["source_service"],
            source_component=row["source_component"],
            action_category=row["action_category"],
            action_name=row["action_name"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            outcome=row["outcome"],
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            request_id=row["request_id"],
            trace_id=row["trace_id"],
            error_code=row["error_code"],
            error_class=row["error_class"],
            error_message_redacted=row["error_message_redacted"],
            payload_mode=row["payload_mode"],
            payload_hash=row["payload_hash"],
            payload_ref=row["payload_ref"],
            payload_size_bytes=row["payload_size_bytes"],
            metadata=CollaborationRepository._json_value(row["metadata"], default={}),
            chain_partition=row["chain_partition"],
            chain_sequence=row["chain_sequence"],
            prev_hash=row["prev_hash"],
            event_hash=row["event_hash"],
        )

    async def _audit_draft_from_event(
        self,
        conn: asyncpg.Connection,
        event: EventEnvelope,
    ) -> AuditEventDraft:
        workspace_row = await conn.fetchrow(
            """
            SELECT organization_id
            FROM workspaces
            WHERE workspace_id = $1
            """,
            event.workspace_id,
        )
        actor_row = await conn.fetchrow(
            """
            SELECT user_id, system_agent_id
            FROM participants
            WHERE workspace_id = $1
              AND participant_id = $2
            """,
            event.workspace_id,
            event.actor.id,
        )
        action_category = event.event_type.split(".", 1)[0]
        outcome = self._audit_outcome_for_action(event.event_type)
        payload_dump = self._canonical_json(event.payload)
        scope_type = "thread" if event.thread_id is not None else "workspace"
        return AuditEventDraft(
            audit_event_id=event.event_id,
            occurred_at=event.timestamp,
            recorded_at=event.timestamp,
            scope_type=scope_type,
            organization_id=workspace_row["organization_id"] if workspace_row else None,
            workspace_id=event.workspace_id,
            thread_id=event.thread_id,
            actor_type=event.actor.type,
            actor_id=event.actor.id,
            user_id=actor_row["user_id"] if actor_row else None,
            system_agent_id=actor_row["system_agent_id"] if actor_row else None,
            source_service="core-collab",
            source_component="kernel",
            action_category=action_category,
            action_name=event.event_type,
            target_type=event.target.type,
            target_id=event.target.id,
            outcome=outcome,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            payload_hash=self._sha256_hex(payload_dump.encode("utf-8")),
            payload_size_bytes=len(payload_dump.encode("utf-8")),
            metadata={
                "visibility": event.visibility,
                "sequence": event.sequence,
                "payload_keys": sorted(event.payload.keys()),
            },
            chain_partition=self._audit_chain_partition(
                scope_type=scope_type,
                organization_id=workspace_row["organization_id"] if workspace_row else None,
                workspace_id=event.workspace_id,
            ),
        )

    @staticmethod
    def _audit_chain_partition(
        *,
        scope_type: str,
        organization_id: UUID | None,
        workspace_id: UUID | None,
    ) -> str:
        if scope_type == "organization" and organization_id is not None:
            return f"organization:{organization_id}"
        if scope_type in {"workspace", "thread"} and workspace_id is not None:
            return f"workspace:{workspace_id}"
        return "global"

    @staticmethod
    def _asset_binding_specificity(binding: ResolvedAssetBinding) -> int:
        if binding.workspace_id is not None:
            return 3
        if binding.organization_id is not None:
            return 2
        return 1

    @staticmethod
    def _audit_outcome_for_action(action_name: str) -> str:
        if action_name.endswith(".failed"):
            return "failure"
        return "success"

    @classmethod
    def _build_audit_event_hash(
        cls,
        event: AuditEventDraft | AuditEvent,
        prev_hash: str,
    ) -> str:
        payload = event.model_dump(mode="json", exclude={"ledger_offset", "chain_sequence", "prev_hash", "event_hash"})
        canonical_json = cls._canonical_json(payload)
        return cls._sha256_hex(f"{canonical_json}{prev_hash}".encode("utf-8"))

    @staticmethod
    def _canonical_json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _sha256_hex(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _json_dumps(value: Any) -> str:
        return json.dumps(value)

    @staticmethod
    def _json_value(value: Any, *, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def _uuid_or_none(value: Any) -> UUID | None:
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _uuid_list(values: Any) -> list[UUID]:
        if not isinstance(values, list):
            return []
        converted: list[UUID] = []
        for value in values:
            item = CollaborationRepository._uuid_or_none(value)
            if item is not None:
                converted.append(item)
        return converted
