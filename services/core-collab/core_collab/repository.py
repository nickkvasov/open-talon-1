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
    Task,
    Thread,
    TimelineMessage,
    Workspace,
)
from .schema import MIGRATIONS


class CollaborationRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def setup_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(MIGRATIONS)

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

    async def delete_workspace(
        self, conn: asyncpg.Connection, workspace_id: UUID
    ) -> bool:
        result = await conn.execute(
            "DELETE FROM workspaces WHERE workspace_id = $1",
            workspace_id,
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
                participant_id, workspace_id, participant_type, display_name, description,
                roles, capabilities, status, visibility_scope, created_at, updated_at, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (participant_id) DO UPDATE
                SET workspace_id = EXCLUDED.workspace_id,
                    participant_type = EXCLUDED.participant_type,
                    display_name = EXCLUDED.display_name,
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
            participant.display_name,
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

    async def fetch_agent_participant(
        self, workspace_id: UUID, system_agent_id: UUID
    ) -> ParticipantProfile | None:
        row = await self._pool.fetchrow(
            """
            SELECT participant_id, workspace_id, participant_type, display_name, description,
                   roles, capabilities, status, visibility_scope, created_at, updated_at, metadata
            FROM participants
            WHERE workspace_id = $1
              AND participant_type = 'agent'
              AND metadata->>'system_agent_id' = $2
            ORDER BY created_at ASC
            LIMIT 1
            """,
            workspace_id,
            str(system_agent_id),
        )
        return self._participant_from_row(row) if row else None

    async def list_participants(self, workspace_id: UUID) -> list[ParticipantProfile]:
        rows = await self._pool.fetch(
            """
            SELECT participant_id, workspace_id, participant_type, display_name, description,
                   roles, capabilities, status, visibility_scope, created_at, updated_at, metadata
            FROM participants
            WHERE workspace_id = $1
            ORDER BY display_name ASC
            """,
            workspace_id,
        )
        return [self._participant_from_row(row) for row in rows]

    async def fetch_participant(
        self, workspace_id: UUID, participant_id: UUID
    ) -> ParticipantProfile | None:
        row = await self._pool.fetchrow(
            """
            SELECT participant_id, workspace_id, participant_type, display_name, description,
                   roles, capabilities, status, visibility_scope, created_at, updated_at, metadata
            FROM participants
            WHERE workspace_id = $1
              AND participant_id = $2
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
        return ParticipantProfile(
            participant_id=row["participant_id"],
            workspace_id=row["workspace_id"],
            participant_type=row["participant_type"],
            system_agent_id=metadata.get("system_agent_id"),
            display_name=row["display_name"],
            description=row["description"],
            roles=list(CollaborationRepository._json_value(row["roles"], default=[])),
            capabilities=list(
                CollaborationRepository._json_value(row["capabilities"], default=[])
            ),
            status=row["status"],
            visibility_scope=row["visibility_scope"],
            agent_config=(
                AgentConfiguration.model_validate(metadata["agent_config"])
                if metadata.get("agent_config") is not None
                else None
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            metadata=metadata,
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
