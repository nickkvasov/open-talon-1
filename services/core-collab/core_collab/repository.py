from __future__ import annotations

from collections.abc import Sequence
import json
from typing import Any
from uuid import UUID

import asyncpg

from .contracts import (
    ActorRef,
    AgentConfiguration,
    AgentDefinition,
    AgentEndpoint,
    AgentInteractionContract,
    Artifact,
    EventEnvelope,
    Membership,
    MemoryEntry,
    ParticipantProfile,
    Run,
    RunStep,
    SystemToolDefinition,
    Task,
    ToolCall,
    ToolCallResult,
    ToolExecutionBinding,
    ToolParameterContract,
    Thread,
    TimelineMessage,
    Workspace,
    WorkspaceTool,
)
from .migrations import apply_pending_migrations


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
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

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
        await conn.execute(
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

    async def upsert_workspace(
        self, conn: asyncpg.Connection, workspace: Workspace
    ) -> None:
        await conn.execute(
            """
            INSERT INTO workspaces (workspace_id, name, description, created_at, updated_at, metadata)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (workspace_id) DO UPDATE
                SET name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            workspace.workspace_id,
            workspace.name,
            workspace.description,
            workspace.created_at,
            workspace.updated_at,
            self._json_dumps(workspace.metadata),
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

    async def upsert_system_agent(
        self, conn: asyncpg.Connection, agent: AgentDefinition
    ) -> None:
        await conn.execute(
            """
            INSERT INTO system_agents (
                agent_id, display_name, description, role, capabilities, endpoint,
                system_prompt, interaction_contract, definition, created_by, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (agent_id) DO UPDATE
                SET display_name = EXCLUDED.display_name,
                    description = EXCLUDED.description,
                    role = EXCLUDED.role,
                    capabilities = EXCLUDED.capabilities,
                    endpoint = EXCLUDED.endpoint,
                    system_prompt = EXCLUDED.system_prompt,
                    interaction_contract = EXCLUDED.interaction_contract,
                    definition = EXCLUDED.definition,
                    updated_at = EXCLUDED.updated_at,
                    metadata = EXCLUDED.metadata
            """,
            agent.agent_id,
            agent.display_name,
            agent.description,
            agent.role,
            self._json_dumps(agent.capabilities),
            self._json_dumps(agent.endpoint.model_dump(mode="json")),
            agent.system_prompt,
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
                tool_id, name, description, parameter_contract, input_schema,
                backend_kind, handler_ref, execution_profile, trust_level,
                created_by, created_at, updated_by, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            ON CONFLICT (tool_id) DO UPDATE
                SET name = EXCLUDED.name,
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
            INSERT INTO workspace_memory_entries (
                memory_entry_id, workspace_id, entry_type, title, content, tags,
                created_by, updated_by, version, visibility, linked_thread_ids, created_at, updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (memory_entry_id) DO UPDATE
                SET entry_type = EXCLUDED.entry_type,
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    tags = EXCLUDED.tags,
                    updated_by = EXCLUDED.updated_by,
                    version = EXCLUDED.version,
                    visibility = EXCLUDED.visibility,
                    linked_thread_ids = EXCLUDED.linked_thread_ids,
                    updated_at = EXCLUDED.updated_at
            """,
            entry.memory_entry_id,
            entry.workspace_id,
            entry.entry_type,
            entry.title,
            entry.content,
            self._json_dumps(entry.tags),
            entry.created_by,
            entry.updated_by,
            entry.version,
            entry.visibility,
            self._json_dumps(entry.linked_thread_ids),
            entry.created_at,
            entry.updated_at,
        )

    async def delete_memory_entry(
        self, conn: asyncpg.Connection, memory_entry_id: UUID
    ) -> bool:
        result = await conn.execute(
            "DELETE FROM workspace_memory_entries WHERE memory_entry_id = $1",
            memory_entry_id,
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
                lease_expires_at, last_heartbeat_at, attempt_count, error,
                execution_handle, submitted_at, started_at, finished_at,
                created_at, updated_at, metadata
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10, $11, $12,
                $13, $14, $15, $16,
                $17, $18, $19, $20,
                $21, $22, $23
            )
            ON CONFLICT (step_id) DO UPDATE
                SET status = EXCLUDED.status,
                    input = EXCLUDED.input,
                    output = EXCLUDED.output,
                    claimed_by_worker = EXCLUDED.claimed_by_worker,
                    lease_expires_at = EXCLUDED.lease_expires_at,
                    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
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
                claimed_by_worker, lease_expires_at, last_heartbeat_at, attempt_count,
                error, execution_handle, result, submitted_at, started_at, finished_at,
                created_at, updated_at, metadata
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7, $8, $9, $10, $11, $12,
                $13, $14, $15, $16,
                $17, $18, $19, $20, $21, $22,
                $23, $24, $25
            )
            ON CONFLICT (tool_call_id) DO UPDATE
                SET status = EXCLUDED.status,
                    arguments = EXCLUDED.arguments,
                    execution_spec = EXCLUDED.execution_spec,
                    claimed_by_worker = EXCLUDED.claimed_by_worker,
                    lease_expires_at = EXCLUDED.lease_expires_at,
                    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
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
            SELECT workspace_id, name, description, created_at, updated_at, metadata
            FROM workspaces
            WHERE workspace_id = $1
            """,
            workspace_id,
        )
        return self._workspace_from_row(row) if row else None

    async def list_workspaces(self) -> list[Workspace]:
        rows = await self._pool.fetch(
            """
            SELECT workspace_id, name, description, created_at, updated_at, metadata
            FROM workspaces
            ORDER BY created_at ASC
            """
        )
        return [self._workspace_from_row(row) for row in rows]

    async def list_system_agents(self) -> list[AgentDefinition]:
        rows = await self._pool.fetch(
            """
            SELECT agent_id, display_name, description, role, capabilities, endpoint,
                   system_prompt, interaction_contract, definition, created_by, created_at, updated_at, metadata
            FROM system_agents
            ORDER BY created_at ASC
            """
        )
        return [self._system_agent_from_row(row) for row in rows]

    async def list_system_tools(self) -> list[SystemToolDefinition]:
        rows = await self._pool.fetch(
            """
            SELECT tool_id, name, description, parameter_contract, input_schema,
                   backend_kind, handler_ref, execution_profile, trust_level,
                   created_by, created_at, updated_by, updated_at, metadata
            FROM system_tools
            ORDER BY created_at ASC
            """
        )
        return [self._system_tool_from_row(row) for row in rows]

    async def fetch_system_agent(self, agent_id: UUID) -> AgentDefinition | None:
        row = await self._pool.fetchrow(
            """
            SELECT agent_id, display_name, description, role, capabilities, endpoint,
                   system_prompt, interaction_contract, definition, created_by, created_at, updated_at, metadata
            FROM system_agents
            WHERE agent_id = $1
            """,
            agent_id,
        )
        return self._system_agent_from_row(row) if row else None

    async def fetch_system_tool(self, tool_id: UUID) -> SystemToolDefinition | None:
        row = await self._pool.fetchrow(
            """
            SELECT tool_id, name, description, parameter_contract, input_schema,
                   backend_kind, handler_ref, execution_profile, trust_level,
                   created_by, created_at, updated_by, updated_at, metadata
            FROM system_tools
            WHERE tool_id = $1
            """,
            tool_id,
        )
        return self._system_tool_from_row(row) if row else None

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
                   lease_expires_at, last_heartbeat_at, attempt_count, error,
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
                   lease_expires_at, last_heartbeat_at, attempt_count, error,
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
                started_at = COALESCE(rs.started_at, $3),
                updated_at = $3,
                attempt_count = rs.attempt_count + 1
            FROM candidate
            WHERE rs.step_id = candidate.step_id
            RETURNING rs.step_id, rs.run_id, rs.task_id, rs.workspace_id, rs.thread_id, rs.system_agent_id,
                      rs.step_index, rs.kind, rs.status, rs.input, rs.output, rs.claimed_by_worker,
                      rs.lease_expires_at, rs.last_heartbeat_at, rs.attempt_count, rs.error,
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
                      lease_expires_at, last_heartbeat_at, attempt_count, error,
                      execution_handle, submitted_at, started_at, finished_at,
                      created_at, updated_at, metadata
            """,
            step_id,
            worker_id,
            lease_expires_at,
            now,
        )
        return self._run_step_from_row(row) if row else None

    async def requeue_expired_run_steps(self, *, now) -> list[RunStep]:
        rows = await self._pool.fetch(
            """
            UPDATE run_steps
            SET status = 'created',
                claimed_by_worker = NULL,
                lease_expires_at = NULL,
                last_heartbeat_at = NULL,
                execution_handle = NULL,
                updated_at = $1
            WHERE status = 'claimed'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at < $1
            RETURNING step_id, run_id, task_id, workspace_id, thread_id, system_agent_id,
                      step_index, kind, status, input, output, claimed_by_worker,
                      lease_expires_at, last_heartbeat_at, attempt_count, error,
                      execution_handle, submitted_at, started_at, finished_at,
                      created_at, updated_at, metadata
            """,
            now,
        )
        return [self._run_step_from_row(row) for row in rows]

    async def fetch_tool_call(self, tool_call_id: UUID) -> ToolCall | None:
        row = await self._pool.fetchrow(
            """
            SELECT tool_call_id, run_id, run_step_id, task_id, workspace_id, thread_id,
                   system_agent_id, tool_id, tool_name, status, arguments, execution_spec,
                   claimed_by_worker, lease_expires_at, last_heartbeat_at, attempt_count,
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
                   claimed_by_worker, lease_expires_at, last_heartbeat_at, attempt_count,
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
                   claimed_by_worker, lease_expires_at, last_heartbeat_at, attempt_count,
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
                started_at = COALESCE(tc.started_at, $3),
                updated_at = $3,
                attempt_count = tc.attempt_count + 1
            FROM candidate
            WHERE tc.tool_call_id = candidate.tool_call_id
            RETURNING tc.tool_call_id, tc.run_id, tc.run_step_id, tc.task_id, tc.workspace_id, tc.thread_id,
                      tc.system_agent_id, tc.tool_id, tc.tool_name, tc.status, tc.arguments, tc.execution_spec,
                      tc.claimed_by_worker, tc.lease_expires_at, tc.last_heartbeat_at, tc.attempt_count,
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
                      claimed_by_worker, lease_expires_at, last_heartbeat_at, attempt_count,
                      error, execution_handle, result, submitted_at, started_at, finished_at,
                      created_at, updated_at, metadata
            """,
            tool_call_id,
            worker_id,
            lease_expires_at,
            now,
        )
        return self._tool_call_from_row(row) if row else None

    async def requeue_expired_tool_calls(self, *, now) -> list[ToolCall]:
        rows = await self._pool.fetch(
            """
            UPDATE tool_calls
            SET status = 'created',
                claimed_by_worker = NULL,
                lease_expires_at = NULL,
                last_heartbeat_at = NULL,
                execution_handle = NULL,
                updated_at = $1
            WHERE status = 'claimed'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at < $1
            RETURNING tool_call_id, run_id, run_step_id, task_id, workspace_id, thread_id,
                      system_agent_id, tool_id, tool_name, status, arguments, execution_spec,
                      claimed_by_worker, lease_expires_at, last_heartbeat_at, attempt_count,
                      error, execution_handle, result, submitted_at, started_at, finished_at,
                      created_at, updated_at, metadata
            """,
            now,
        )
        return [self._tool_call_from_row(row) for row in rows]

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
        rows = await self._pool.fetch(
            """
            SELECT memory_entry_id, workspace_id, entry_type, title, content, tags,
                   created_by, updated_by, version, visibility, linked_thread_ids, created_at, updated_at
            FROM workspace_memory_entries
            WHERE workspace_id = $1
            ORDER BY updated_at DESC
            """,
            workspace_id,
        )
        return [self._memory_entry_from_row(row) for row in rows]

    async def fetch_memory_entry(self, memory_entry_id: UUID) -> MemoryEntry | None:
        row = await self._pool.fetchrow(
            """
            SELECT memory_entry_id, workspace_id, entry_type, title, content, tags,
                   created_by, updated_by, version, visibility, linked_thread_ids, created_at, updated_at
            FROM workspace_memory_entries
            WHERE memory_entry_id = $1
            """,
            memory_entry_id,
        )
        return self._memory_entry_from_row(row) if row else None

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
            name=row["name"],
            description=row["description"],
            created_at=row["created_at"],
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
        roles = (
            [row["agent_role"]] if participant_type == "agent" and row["agent_role"] else
            list(CollaborationRepository._json_value(row["roles"], default=[]))
        )
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
    def _system_agent_from_row(row: asyncpg.Record) -> AgentDefinition:
        return AgentDefinition(
            agent_id=row["agent_id"],
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
            workspace_id=row["workspace_id"],
            entry_type=row["entry_type"],
            title=row["title"],
            content=row["content"],
            tags=list(CollaborationRepository._json_value(row["tags"], default=[])),
            created_by=row["created_by"],
            updated_by=row["updated_by"],
            version=row["version"],
            visibility=row["visibility"],
            linked_thread_ids=list(
                CollaborationRepository._json_value(
                    row["linked_thread_ids"], default=[]
                )
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
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
    def _json_dumps(value: Any) -> str:
        return json.dumps(value)

    @staticmethod
    def _json_value(value: Any, *, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, str):
            return json.loads(value)
        return value
