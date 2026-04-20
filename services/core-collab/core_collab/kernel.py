from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sys
from uuid import UUID, uuid4

import asyncpg

_WORKSPACE_MEMORY_DIR = Path(__file__).resolve().parents[2] / "workspace-memory"
if _WORKSPACE_MEMORY_DIR.is_dir():
    workspace_memory_path = str(_WORKSPACE_MEMORY_DIR)
    if workspace_memory_path not in sys.path:
        sys.path.insert(0, workspace_memory_path)

from workspace_memory import (
    ProviderSearchResult,
    build_default_secret_resolver,
    build_provider_index,
)

from .contracts import (
    ActorRef,
    AgentArtifactDraft,
    AgentConfiguration,
    AgentDefinition,
    AgentExecutionContext,
    AgentInternalToolBinding,
    AgentRunResult,
    CompletionRule,
    AgentToolCallDraft,
    AgentTaskRouting,
    AuditChainVerificationResult,
    AuditEvent,
    AuditEventDraft,
    AuditEventPage,
    AttachWorkspaceToolRequest,
    AssumeParticipantRoleRequest,
    Artifact,
    AssetLink,
    ActivateAssetVersionRequest,
    CreateAgentParticipantRequest,
    CreateGitRepositoryRequest,
    CreateInteractionAnswerRequest,
    CreateInteractionQuestionRequest,
    CreateInteractionRequest,
    CreateInteractionRequestsRequest,
    CreateLlmProviderRequest,
    CreateMemoryProviderRequest,
    CreateOrganizationRequest,
    CreateSystemAgentRequest,
    CreateSystemToolRequest,
    ConfirmWorkspaceMemoryRequest,
    CreateMemoryEntryRequest,
    CreateThreadMemoryRequest,
    CreateMessageRequest,
    CreateToolGenerationRevisionRequest,
    SearchMemoryRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteLlmProviderRequest,
    DeleteMemoryProviderRequest,
    DeleteParticipantRequest,
    DeleteRoleDefinitionRequest,
    DeleteSystemAgentRequest,
    DeleteSystemToolRequest,
    DeleteWorkspaceToolRequest,
    DeleteWorkspaceRequest,
    ExecutionWorkspaceRef,
    EventEnvelope,
    GeneratedToolManifest,
    GeneratedToolValidationReport,
    InteractionAnswer,
    InteractionQuestion,
    InteractionRequest,
    InteractionRequestDetail,
    InteractionRequestDraft,
    InteractionRequestTarget,
    Membership,
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderRecord,
    MemorySearchHit,
    MemorySearchResponse,
    LlmProviderDefinition,
    Organization,
    OrganizationMembership,
    ParticipantSelector,
    ParticipantInput,
    ParticipantProfile,
    PublishAssetFromGitRequest,
    PresenceState,
    ResolvedAssetBinding,
    RoleDefinition,
    SystemToolDefinition,
    RunStep,
    ExecutionSpec,
    ExecutionLimits,
    Task,
    TargetRef,
    Thread,
    ThreadDetail,
    TimelineMessage,
    TimelinePage,
    ToolGenerationRequest,
    ToolGenerationRequestDetail,
    ToolGenerationRevision,
    WorkspaceCommunicationLogPage,
    Run,
    ReviewToolGenerationRevisionRequest,
    StopReason,
    ToolCall,
    ToolCallResult,
    UpdateSystemAgentRequest,
    UpdateInteractionRequestRequest,
    LinkAssetRequest,
    UpdateLlmProviderRequest,
    UpdateMemoryProviderRequest,
    UpdateOrganizationRequest,
    UpsertRoleDefinitionRequest,
    RemoveOrganizationMemberRequest,
    UpdateSystemToolRequest,
    build_default_interaction_contract,
    interaction_contract_is_empty,
    AddOrganizationMemberRequest,
    UpdateAgentParticipantRequest,
    UpdateMemoryEntryRequest,
    UpdateWorkspaceRequest,
    UpdateWorkspaceToolRequest,
    Workspace,
    WorkspaceAsset,
    WorkspaceAssetVersion,
    WorkspaceDetail,
    WorkspaceTool,
    GitRepository,
)
from .repository import CollaborationRepository, UserRecord
from .results import (
    AgentDefinitionCommandResult,
    CommandResult,
    GitRepositoryCommandResult,
    InteractionRequestCommandResult,
    LeaseReconciliationResult,
    LlmProviderCommandResult,
    MemoryCommandResult,
    MemoryProviderCommandResult,
    MessageCommandResult,
    OrganizationCommandResult,
    OrganizationMembershipCommandResult,
    ParticipantCommandResult,
    RoleDefinitionCommandResult,
    RunCommandResult,
    RunStepCommandResult,
    SystemToolCommandResult,
    TaskCommandResult,
    ThreadCommandResult,
    ToolCallCommandResult,
    ToolGenerationRequestCommandResult,
    WorkspaceAssetCommandResult,
    WorkspaceCommandResult,
    WorkspaceToolCommandResult,
)
from .runtime_execution import RuntimeExecutionService

logger = logging.getLogger(__name__)

_DEFAULT_WORKSPACE_ROLE_DEFINITIONS = {
    "admin": "Manages the workspace, participants, tools, and provider configuration.",
    "supervisor": "Coordinates delivery, reviews work, and guides workspace members without full administrative control.",
    "user": "Collaborates in the workspace, participates in threads, and uses attached tools.",
}

_WORKSPACE_MANAGER_ROLES = {"admin", "supervisor"}
_ORGANIZATION_ADMIN_ROLES = {"owner", "admin"}
_MAX_RUN_STEP_ATTEMPTS = 3
_MAX_TOOL_CALL_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (30, 120, 600)


class CollaborationKernel:
    def __init__(self, repository: CollaborationRepository) -> None:
        self._repository = repository
        self._secret_resolver = build_default_secret_resolver()
        self._memory_provider_index = build_provider_index(
            store=repository,
            secret_resolver=self._secret_resolver,
        )
        self._runtime_execution = RuntimeExecutionService(
            repository=repository,
            task_routing=lambda task: self._task_routing(task),
            resolve_agent_participant=lambda **kwargs: self._resolve_agent_participant(**kwargs),
            require_run_participant=lambda **kwargs: self._require_run_participant(**kwargs),
            resolve_run_for_context=lambda task, participant, run_id: self._resolve_run_for_context(
                task,
                participant,
                run_id,
            ),
            advertise_workspace_tools=lambda participant, workspace_tools: self._advertise_workspace_tools(
                participant,
                workspace_tools,
            ),
            filter_visible_messages=lambda messages, **kwargs: self._filter_visible_messages(
                messages,
                **kwargs,
            ),
            filter_visible_memory_entries=lambda entries, **kwargs: self._filter_visible_memory_entries(
                entries,
                **kwargs,
            ),
            role_definitions_from_workspace=lambda workspace: self._role_definitions_from_workspace(
                workspace
            ),
            build_thread_event=lambda *args, **kwargs: self._build_thread_event(*args, **kwargs),
            now=lambda: self._now(),
            utc_day_window=lambda timestamp: self._utc_day_window(timestamp),
            workspace_daily_token_cap=lambda workspace, default_cap: self._workspace_daily_token_cap(
                workspace,
                default_cap,
            ),
            run_output_from_result=lambda result: self._run_output_from_result(result),
            artifact_from_draft=lambda draft, **kwargs: self._artifact_from_draft(
                draft,
                **kwargs,
            ),
            agent_message_from_result=lambda result, **kwargs: self._agent_message_from_result(
                result,
                **kwargs,
            ),
            stop_reason_returns_to_thread=lambda stop_reason: self._stop_reason_returns_to_thread(
                stop_reason
            ),
            fail_run_step=lambda *args, **kwargs: self.fail_run_step(*args, **kwargs),
        )

    async def setup_schema(self) -> None:
        await self._repository.setup_schema()
        await self._backfill_system_agent_interaction_contracts()

    async def create_organization(
        self,
        payload: CreateOrganizationRequest,
    ) -> OrganizationCommandResult:
        now = self._now()
        created_by = self._actor_user_id(payload.actor) or payload.actor.participant_id
        organization = Organization(
            organization_id=uuid4(),
            slug=payload.slug,
            name=payload.name,
            description=payload.description,
            created_by=created_by,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        actor_user_id = self._actor_user_id(payload.actor)
        membership = (
            OrganizationMembership(
                organization_id=organization.organization_id,
                user_id=actor_user_id,
                role="owner",
                joined_at=now,
                updated_at=now,
                metadata={"created_by": str(created_by)},
            )
            if actor_user_id is not None
            else None
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                if actor_user_id is not None:
                    await self._repository.upsert_user(
                        conn,
                        UserRecord(
                            user_id=actor_user_id,
                            display_name=payload.actor.display_name,
                            created_at=now,
                            updated_at=now,
                            metadata={},
                        ),
                    )
                await self._repository.upsert_organization(conn, organization)
                if membership is not None:
                    await self._repository.upsert_organization_membership(conn, membership)
        return OrganizationCommandResult(organization=organization)

    async def list_organizations(
        self,
        *,
        user_id: UUID | None = None,
    ) -> list[Organization]:
        if user_id is not None:
            return await self._repository.list_organizations_for_user(user_id)
        return await self._repository.list_organizations()

    async def get_organization(self, organization_id: UUID) -> Organization | None:
        return await self._repository.fetch_organization(organization_id)

    async def update_organization(
        self,
        organization_id: UUID,
        payload: UpdateOrganizationRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> OrganizationCommandResult:
        organization = await self._repository.fetch_organization(organization_id)
        if organization is None:
            raise KeyError(f"Organization {organization_id} not found")
        actor_user_id = self._actor_user_id(payload.actor)
        if actor_user_id is not None and not allow_platform_admin:
            await self._require_organization_admin(organization_id, actor_user_id)
        updated = organization.model_copy(
            update={
                "slug": payload.slug or organization.slug,
                "name": payload.name or organization.name,
                "description": (
                    payload.description
                    if payload.description is not None
                    else organization.description
                ),
                "updated_at": self._now(),
                "metadata": (
                    {**organization.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else organization.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_organization(conn, updated)
        return OrganizationCommandResult(organization=updated)

    async def list_organization_memberships(
        self,
        organization_id: UUID,
    ) -> list[OrganizationMembership]:
        if await self._repository.fetch_organization(organization_id) is None:
            raise KeyError(f"Organization {organization_id} not found")
        return await self._repository.list_organization_memberships(organization_id)

    async def add_organization_member(
        self,
        organization_id: UUID,
        payload: AddOrganizationMemberRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> OrganizationMembershipCommandResult:
        if await self._repository.fetch_organization(organization_id) is None:
            raise KeyError(f"Organization {organization_id} not found")
        actor_user_id = self._actor_user_id(payload.actor)
        if actor_user_id is not None and not allow_platform_admin:
            await self._require_organization_admin(organization_id, actor_user_id)
        user = await self._repository.fetch_user(payload.user_id)
        if user is None:
            raise KeyError(f"User {payload.user_id} not found")
        now = self._now()
        membership = OrganizationMembership(
            organization_id=organization_id,
            user_id=payload.user_id,
            role=payload.role,
            joined_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_organization_membership(conn, membership)
        return OrganizationMembershipCommandResult(membership=membership)

    async def remove_organization_member(
        self,
        organization_id: UUID,
        user_id: UUID,
        payload: RemoveOrganizationMemberRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> dict[str, bool | str]:
        if await self._repository.fetch_organization(organization_id) is None:
            raise KeyError(f"Organization {organization_id} not found")
        actor_user_id = self._actor_user_id(payload.actor)
        if actor_user_id is not None and not allow_platform_admin:
            await self._require_organization_admin(organization_id, actor_user_id)
        membership = await self._repository.fetch_organization_membership(
            organization_id,
            user_id,
        )
        if membership is None:
            raise KeyError(
                f"User {user_id} is not a member of organization {organization_id}"
            )
        if membership.role == "owner":
            memberships = await self._repository.list_organization_memberships(organization_id)
            if not any(
                item.user_id != user_id and item.role == "owner"
                for item in memberships
            ):
                raise ValueError("Cannot remove the last organization owner")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_organization_membership(
                    conn,
                    organization_id=organization_id,
                    user_id=user_id,
                )
                if not deleted:
                    raise KeyError(
                        f"User {user_id} is not a member of organization {organization_id}"
                    )
                await self._repository.remove_user_participants_for_organization(
                    conn,
                    organization_id=organization_id,
                    user_id=user_id,
                )
        return {
            "deleted": True,
            "organization_id": str(organization_id),
            "user_id": str(user_id),
        }

    async def create_workspace(
        self,
        payload: CreateWorkspaceRequest,
        *,
        allow_platform_admin: bool = False,
    ) -> WorkspaceCommandResult:
        logger.debug(
            "Kernel create_workspace participant_id=%s name=%r",
            payload.actor.participant_id,
            payload.name,
        )
        actor_user_id = self._actor_user_id(payload.actor)
        organization = await self._resolve_workspace_organization(
            requested_organization_id=payload.organization_id,
            actor=payload.actor,
        )
        if actor_user_id is not None and not allow_platform_admin:
            await self._require_organization_admin(organization.organization_id, actor_user_id)
        workspace_id = uuid4()
        now = self._now()
        workspace = Workspace(
            workspace_id=workspace_id,
            organization_id=organization.organization_id,
            name=payload.name,
            description=payload.description,
            owner_user_id=actor_user_id,
            harness=payload.harness,
            created_at=now,
            updated_at=now,
            metadata=self._workspace_metadata_for_create(
                metadata=payload.metadata,
                updated_by=payload.actor.participant_id,
                updated_at=now,
            ),
        )
        actor = self._actor_from_input(payload.actor)
        participant = self._participant_profile(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        ).model_copy(update={"roles": self._workspace_owner_roles(payload.actor.roles)})
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_workspace(conn, workspace)
                await self._repository.upsert_participant(conn, participant)

                events = [
                    await self._build_workspace_event(
                        conn,
                        workspace_id,
                        "workspace.created",
                        actor=actor,
                        target=TargetRef(type="workspace", id=workspace.workspace_id),
                        payload={
                            "workspace_id": str(workspace.workspace_id),
                            "name": workspace.name,
                            "description": workspace.description,
                            "owner_user_id": (
                                str(workspace.owner_user_id)
                                if workspace.owner_user_id is not None
                                else None
                            ),
                        },
                        timestamp=now,
                    ),
                    await self._build_workspace_event(
                        conn,
                        workspace_id,
                        "participant.registered",
                        actor=actor,
                        target=TargetRef(type="participant", id=participant.participant_id),
                        payload=participant.model_dump(mode="json"),
                        visibility="workspace",
                        timestamp=now,
                    ),
                ]
                for event in events:
                    await self._repository.record_event(conn, event)

        detail = WorkspaceDetail(
            workspace=workspace,
            participants=[participant],
            role_definitions=self._role_definitions_from_workspace(workspace),
            tools=[],
        )
        logger.debug(
            "Kernel create_workspace complete workspace_id=%s event_count=%s",
            workspace_id,
            len(events),
        )
        return WorkspaceCommandResult(workspace=workspace, detail=detail, events=events)

    async def list_workspaces(
        self,
        *,
        user_id: UUID | None = None,
        organization_id: UUID | None = None,
    ) -> list[Workspace]:
        if user_id is not None:
            try:
                return await self._repository.list_workspaces_for_user(
                    user_id,
                    organization_id=organization_id,
                )
            except TypeError:
                return await self._repository.list_workspaces_for_user(user_id)
        try:
            return await self._repository.list_workspaces(organization_id=organization_id)
        except TypeError:
            return await self._repository.list_workspaces()

    async def delete_workspace(self, workspace_id: UUID, payload: DeleteWorkspaceRequest) -> dict[str, bool | str]:
        logger.debug(
            "Kernel delete_workspace workspace_id=%s participant_id=%s",
            workspace_id,
            payload.actor.participant_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_workspace(conn, workspace_id)
        if not deleted:
            raise KeyError(f"Workspace {workspace_id} not found")
        logger.debug("Kernel delete_workspace complete workspace_id=%s", workspace_id)
        return {"deleted": True, "workspace_id": str(workspace_id)}

    async def update_workspace(
        self, workspace_id: UUID, payload: UpdateWorkspaceRequest
    ) -> WorkspaceCommandResult:
        logger.debug(
            "Kernel update_workspace workspace_id=%s participant_id=%s",
            workspace_id,
            payload.actor.participant_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_management_role(workspace_id, payload.actor)
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        updated = workspace.model_copy(
            update={
                "name": payload.name or workspace.name,
                "description": (
                    payload.description
                    if payload.description is not None
                    else workspace.description
                ),
                "harness": (
                    payload.harness
                    if "harness" in payload.model_fields_set
                    else workspace.harness
                ),
                "updated_at": now,
                "metadata": (
                    {**workspace.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else workspace.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace(conn, updated)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.updated",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=updated.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)

        detail = await self.get_workspace_detail(workspace_id)
        return WorkspaceCommandResult(workspace=updated, detail=detail, events=[event])

    async def get_workspace_detail(self, workspace_id: UUID) -> WorkspaceDetail:
        logger.debug("Kernel get_workspace_detail workspace_id=%s", workspace_id)
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        participants = await self._repository.list_participants(workspace_id)
        tools = await self._repository.list_workspace_tools(workspace_id)
        return WorkspaceDetail(
            workspace=workspace,
            participants=[
                self._advertise_workspace_tools(participant, tools)
                for participant in participants
            ],
            role_definitions=self._role_definitions_from_workspace(workspace),
            tools=tools,
        )

    async def list_workspace_participants(
        self, workspace_id: UUID
    ) -> list[ParticipantProfile]:
        logger.debug("Kernel list_workspace_participants workspace_id=%s", workspace_id)
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        tools = await self._repository.list_workspace_tools(workspace_id)
        participants = await self._repository.list_participants(workspace_id)
        return [
            self._advertise_workspace_tools(participant, tools)
            for participant in participants
        ]

    async def delete_participant(
        self,
        workspace_id: UUID,
        participant_id: UUID,
        payload: DeleteParticipantRequest,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Kernel delete_participant workspace_id=%s participant_id=%s actor_id=%s",
            workspace_id,
            participant_id,
            payload.actor.participant_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        participant = await self._repository.fetch_participant(workspace_id, participant_id)
        if participant is None:
            raise KeyError(f"Participant {participant_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_participant(
                    conn,
                    workspace_id=workspace_id,
                    participant_id=participant_id,
                )
                if not deleted:
                    raise KeyError(f"Participant {participant_id} not found")
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "participant.removed",
                    actor=actor,
                    target=TargetRef(type="participant", id=participant_id),
                    payload=participant.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return {
            "deleted": True,
            "workspace_id": str(workspace_id),
            "participant_id": str(participant_id),
        }

    async def create_system_agent(
        self,
        payload: CreateSystemAgentRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> AgentDefinitionCommandResult:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        now = self._now()
        interaction_contract = (
            build_default_interaction_contract(
                display_name=payload.display_name,
                role=payload.role,
                description=payload.description,
                capabilities=payload.capabilities,
            )
            if interaction_contract_is_empty(payload.interaction_contract)
            else payload.interaction_contract
        )
        agent = AgentDefinition(
            agent_id=uuid4(),
            scope=scope,
            organization_id=organization_id,
            display_name=payload.display_name,
            description=payload.description,
            role=payload.role,
            capabilities=payload.capabilities,
            endpoint=payload.endpoint,
            system_prompt=payload.system_prompt,
            harness=payload.harness,
            interaction_contract=interaction_contract,
            definition=payload.definition,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_agent(conn, agent)
        return AgentDefinitionCommandResult(agent=agent)

    async def delete_system_agent(self, agent_id: UUID, payload: DeleteSystemAgentRequest) -> dict[str, bool | str]:
        _ = payload
        existing = await self._repository.fetch_system_agent(agent_id)
        if existing is None:
            raise KeyError(f"System agent {agent_id} not found")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_system_agent(conn, agent_id=agent_id)
        if not deleted:
            raise KeyError(f"System agent {agent_id} not found")
        return {"deleted": True, "agent_id": str(agent_id)}

    async def list_system_agents(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[AgentDefinition]:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        try:
            return await self._repository.list_system_agents(
                scope=scope,
                organization_id=organization_id,
            )
        except TypeError:
            return await self._repository.list_system_agents()

    async def list_workspace_catalog_agents(
        self,
        workspace_id: UUID,
    ) -> list[AgentDefinition]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        agents = await self._repository.list_system_agents(scope="global")
        agents.extend(
            await self._repository.list_system_agents(
                scope="organization",
                organization_id=workspace.organization_id,
            )
        )
        return agents

    async def create_system_tool(
        self,
        payload: CreateSystemToolRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> SystemToolCommandResult:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        now = self._now()
        execution = payload.execution.model_copy(
            update={"handler_ref": payload.execution.handler_ref or payload.name}
        )
        self._validate_tool_execution_binding(execution)
        tool = SystemToolDefinition(
            tool_id=uuid4(),
            scope=scope,
            organization_id=organization_id,
            name=payload.name,
            description=payload.description,
            parameter_contract=payload.parameter_contract,
            input_schema=payload.input_schema,
            execution=execution,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_tool(conn, tool)
        return SystemToolCommandResult(tool=tool)

    async def delete_system_tool(self, tool_id: UUID, payload: DeleteSystemToolRequest) -> dict[str, bool | str]:
        _ = payload
        existing = await self._repository.fetch_system_tool(tool_id)
        if existing is None:
            raise KeyError(f"System tool {tool_id} not found")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_system_tool(conn, tool_id=tool_id)
        if not deleted:
            raise KeyError(f"System tool {tool_id} not found")
        return {"deleted": True, "tool_id": str(tool_id)}

    async def create_llm_provider(
        self,
        payload: CreateLlmProviderRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> LlmProviderCommandResult:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        now = self._now()
        provider = LlmProviderDefinition(
            provider_id=uuid4(),
            scope=scope,
            organization_id=organization_id,
            engine_id=payload.engine_id,
            display_name=payload.display_name,
            description=payload.description,
            provider=payload.provider,
            endpoint_kind=payload.endpoint_kind,
            url=payload.url,
            default_model=payload.default_model,
            capabilities=payload.capabilities,
            locality=payload.locality,
            priority=payload.priority,
            enabled=payload.enabled,
            secret_config=payload.secret_config,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_llm_provider(conn, provider)
        return LlmProviderCommandResult(provider=provider)

    async def create_memory_provider(
        self,
        payload: CreateMemoryProviderRequest,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> MemoryProviderCommandResult:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        now = self._now()
        provider = MemoryProviderDefinition(
            provider_id=uuid4(),
            scope=scope,
            organization_id=organization_id,
            provider_key=payload.provider_key,
            display_name=payload.display_name,
            description=payload.description,
            provider=payload.provider,
            enabled=payload.enabled,
            config=payload.config,
            secret_config=payload.secret_config,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_memory_provider(conn, provider)
        return MemoryProviderCommandResult(provider=provider)

    async def list_system_tools(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[SystemToolDefinition]:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        try:
            return await self._repository.list_system_tools_by_scope(
                scope=scope,
                organization_id=organization_id,
            )
        except AttributeError:
            return await self._repository.list_system_tools()
        except TypeError:
            return await self._repository.list_system_tools()

    async def list_workspace_catalog_tools(
        self,
        workspace_id: UUID,
    ) -> list[SystemToolDefinition]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        tools = await self._repository.list_system_tools_by_scope(scope="global")
        tools.extend(
            await self._repository.list_system_tools_by_scope(
                scope="organization",
                organization_id=workspace.organization_id,
            )
        )
        return tools

    async def list_llm_providers(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[LlmProviderDefinition]:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        try:
            return await self._repository.list_llm_providers(
                scope=scope,
                organization_id=organization_id,
            )
        except TypeError:
            return await self._repository.list_llm_providers()

    async def list_memory_providers(
        self,
        *,
        scope: str = "global",
        organization_id: UUID | None = None,
    ) -> list[MemoryProviderDefinition]:
        self._validate_registry_scope(scope=scope, organization_id=organization_id)
        try:
            return await self._repository.list_memory_providers(
                scope=scope,
                organization_id=organization_id,
            )
        except TypeError:
            return await self._repository.list_memory_providers()

    async def get_llm_provider(self, provider_id: UUID) -> LlmProviderDefinition | None:
        return await self._repository.fetch_llm_provider(provider_id)

    async def get_memory_provider(
        self, provider_id: UUID
    ) -> MemoryProviderDefinition | None:
        return await self._repository.fetch_memory_provider(provider_id)

    async def update_system_tool(
        self, tool_id: UUID, payload: UpdateSystemToolRequest
    ) -> SystemToolCommandResult:
        existing = await self._repository.fetch_system_tool(tool_id)
        if existing is None:
            raise KeyError(f"System tool {tool_id} not found")
        updated = existing.model_copy(
            update={
                "name": payload.name or existing.name,
                "description": payload.description or existing.description,
                "parameter_contract": (
                    payload.parameter_contract
                    if payload.parameter_contract is not None
                    else existing.parameter_contract
                ),
                "input_schema": (
                    payload.input_schema
                    if payload.input_schema is not None
                    else existing.input_schema
                ),
                "execution": (
                    payload.execution.model_copy(
                        update={
                            "handler_ref": payload.execution.handler_ref
                            or payload.name
                            or existing.name
                        }
                    )
                    if payload.execution is not None
                    else existing.execution
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": self._now(),
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        self._validate_tool_execution_binding(updated.execution)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_tool(conn, updated)
        return SystemToolCommandResult(tool=updated)

    async def update_llm_provider(
        self, provider_id: UUID, payload: UpdateLlmProviderRequest
    ) -> LlmProviderCommandResult:
        existing = await self._repository.fetch_llm_provider(provider_id)
        if existing is None:
            raise KeyError(f"LLM provider {provider_id} not found")
        references = await self._llm_provider_references(existing.engine_id)
        if payload.engine_id is not None and payload.engine_id != existing.engine_id and references:
            raise ValueError(
                f"Cannot rename LLM provider engine_id {existing.engine_id!r}; "
                f"referenced by system agents: {', '.join(agent.display_name for agent in references)}"
            )
        if existing.enabled and payload.enabled is False and references:
            raise ValueError(
                f"Cannot disable LLM provider {existing.engine_id!r}; "
                f"referenced by system agents: {', '.join(agent.display_name for agent in references)}"
            )
        updated = existing.model_copy(
            update={
                "engine_id": payload.engine_id or existing.engine_id,
                "display_name": payload.display_name or existing.display_name,
                "description": payload.description or existing.description,
                "provider": payload.provider or existing.provider,
                "endpoint_kind": payload.endpoint_kind or existing.endpoint_kind,
                "url": payload.url if payload.url is not None else existing.url,
                "default_model": (
                    payload.default_model
                    if payload.default_model is not None
                    else existing.default_model
                ),
                "capabilities": (
                    payload.capabilities
                    if payload.capabilities is not None
                    else existing.capabilities
                ),
                "locality": payload.locality or existing.locality,
                "priority": payload.priority if payload.priority is not None else existing.priority,
                "enabled": payload.enabled if payload.enabled is not None else existing.enabled,
                "secret_config": (
                    payload.secret_config
                    if payload.secret_config is not None
                    else existing.secret_config
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": self._now(),
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_llm_provider(conn, updated)
        return LlmProviderCommandResult(provider=updated)

    async def update_memory_provider(
        self, provider_id: UUID, payload: UpdateMemoryProviderRequest
    ) -> MemoryProviderCommandResult:
        existing = await self._repository.fetch_memory_provider(provider_id)
        if existing is None:
            raise KeyError(f"Memory provider {provider_id} not found")
        updated = existing.model_copy(
            update={
                "provider_key": payload.provider_key or existing.provider_key,
                "display_name": payload.display_name or existing.display_name,
                "description": payload.description or existing.description,
                "provider": payload.provider or existing.provider,
                "enabled": payload.enabled if payload.enabled is not None else existing.enabled,
                "config": payload.config if payload.config is not None else existing.config,
                "secret_config": (
                    payload.secret_config
                    if payload.secret_config is not None
                    else existing.secret_config
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": self._now(),
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_memory_provider(conn, updated)
        return MemoryProviderCommandResult(provider=updated)

    async def update_system_agent(
        self, agent_id: UUID, payload: UpdateSystemAgentRequest
    ) -> AgentDefinitionCommandResult:
        existing = await self._repository.fetch_system_agent(agent_id)
        if existing is None:
            raise KeyError(f"System agent {agent_id} not found")
        interaction_contract = (
            payload.interaction_contract
            if payload.interaction_contract is not None
            else existing.interaction_contract
        )
        updated = existing.model_copy(
            update={
                "display_name": payload.display_name or existing.display_name,
                "description": payload.description or existing.description,
                "role": payload.role or existing.role,
                "capabilities": payload.capabilities or existing.capabilities,
                "endpoint": payload.endpoint or existing.endpoint,
                "system_prompt": payload.system_prompt or existing.system_prompt,
                "harness": (
                    payload.harness
                    if "harness" in payload.model_fields_set
                    else existing.harness
                ),
                "interaction_contract": interaction_contract,
                "definition": payload.definition if payload.definition is not None else existing.definition,
                "updated_at": self._now(),
                "metadata": {**existing.metadata, **payload.metadata} if payload.metadata is not None else existing.metadata,
            }
        )
        if interaction_contract_is_empty(updated.interaction_contract):
            updated = updated.model_copy(
                update={
                    "interaction_contract": build_default_interaction_contract(
                        display_name=updated.display_name,
                        role=updated.role,
                        description=updated.description,
                        capabilities=updated.capabilities,
                    )
                }
            )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_agent(conn, updated)
        return AgentDefinitionCommandResult(agent=updated)

    async def create_git_repository(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None,
        payload: CreateGitRepositoryRequest,
    ) -> GitRepositoryCommandResult:
        organization = await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            await self._require_workspace_management_role(
                workspace_id,
                payload.actor,
            )
        now = self._now()
        repository = GitRepository(
            repo_id=uuid4(),
            organization_id=organization.organization_id if organization is not None else None,
            workspace_id=workspace_id,
            scope=scope,
            name=payload.name,
            forgejo_url=payload.forgejo_url,
            clone_url=payload.clone_url,
            local_path=payload.local_path,
            default_branch=payload.default_branch,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_git_repository(conn, repository)
        return GitRepositoryCommandResult(repository=repository)

    async def list_git_repositories(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[GitRepository]:
        await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_git_repositories(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def get_git_repository(self, repo_id: UUID) -> GitRepository | None:
        return await self._repository.fetch_git_repository(repo_id)

    async def publish_asset_from_git(
        self,
        *,
        scope: str,
        organization_id: UUID | None = None,
        workspace_id: UUID | None,
        payload: PublishAssetFromGitRequest,
        storage_backend: str,
        bucket: str,
        object_key: str,
        size_bytes: int,
        sha256: str,
        content_type: str | None,
    ) -> WorkspaceAssetCommandResult:
        organization = await self._resolve_scope_organization(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            await self._require_workspace_management_role(
                workspace_id,
                payload.actor,
            )
        repository = await self._repository.fetch_git_repository(payload.repository_id)
        if repository is None:
            raise KeyError(f"Git repository {payload.repository_id} not found")
        if repository.scope != scope:
            raise ValueError(
                f"Repository {repository.repo_id} scope {repository.scope!r} does not match asset scope {scope!r}"
            )
        if repository.organization_id != (
            organization.organization_id if organization is not None else None
        ):
            raise ValueError(
                f"Repository {repository.repo_id} organization binding does not match asset organization scope"
            )
        if repository.workspace_id != workspace_id:
            raise ValueError(
                f"Repository {repository.repo_id} workspace binding does not match asset workspace scope"
            )
        now = self._now()
        asset = await self._repository.fetch_workspace_asset_by_logical_name(
            scope=scope,
            organization_id=organization.organization_id if organization is not None else None,
            workspace_id=workspace_id,
            logical_name=payload.logical_name,
        )
        if asset is None:
            asset = WorkspaceAsset(
                asset_id=uuid4(),
                organization_id=organization.organization_id if organization is not None else None,
                workspace_id=workspace_id,
                scope=scope,
                asset_type=payload.asset_type,
                logical_name=payload.logical_name,
                logical_path=payload.logical_path,
                title=payload.title,
                description=payload.description,
                created_by=payload.actor.participant_id,
                created_at=now,
                updated_at=now,
                metadata=payload.metadata,
            )
        else:
            asset = asset.model_copy(
                update={
                    "asset_type": payload.asset_type,
                    "logical_path": payload.logical_path,
                    "title": payload.title,
                    "description": payload.description,
                    "updated_at": now,
                    "metadata": {**asset.metadata, **payload.metadata},
                }
            )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace_asset(conn, asset)
                version_number = await self._repository.next_workspace_asset_version(
                    conn,
                    asset_id=asset.asset_id,
                )
                version = WorkspaceAssetVersion(
                    asset_version_id=uuid4(),
                    asset_id=asset.asset_id,
                    version=version_number,
                    source_kind="git_publish",
                    git_repository_id=repository.repo_id,
                    git_revision=payload.revision,
                    git_path=payload.git_path,
                    storage_backend=storage_backend,
                    bucket=bucket,
                    object_key=object_key,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    sha256=sha256,
                    created_by=payload.actor.participant_id,
                    created_at=now,
                    metadata={
                        **payload.metadata,
                        "repository_name": repository.name,
                    },
                )
                await self._repository.upsert_workspace_asset_version(conn, version)
        return WorkspaceAssetCommandResult(asset=asset, version=version)

    async def list_workspace_assets(
        self,
        *,
        scope: str | None = None,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> list[WorkspaceAsset]:
        if scope is not None:
            await self._resolve_scope_organization(
                scope=scope,
                organization_id=organization_id,
                workspace_id=workspace_id,
            )
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_workspace_assets(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )

    async def list_workspace_asset_versions(
        self,
        asset_id: UUID,
    ) -> list[WorkspaceAssetVersion]:
        asset = await self._repository.fetch_workspace_asset(asset_id)
        if asset is None:
            raise KeyError(f"Workspace asset {asset_id} not found")
        return await self._repository.list_workspace_asset_versions(asset_id)

    async def get_workspace_asset(self, asset_id: UUID) -> WorkspaceAsset | None:
        return await self._repository.fetch_workspace_asset(asset_id)

    async def get_workspace_asset_version(
        self,
        asset_version_id: UUID,
    ) -> WorkspaceAssetVersion | None:
        return await self._repository.fetch_workspace_asset_version(asset_version_id)

    async def activate_asset_version(
        self,
        asset_id: UUID,
        payload: ActivateAssetVersionRequest,
    ) -> WorkspaceAssetCommandResult:
        asset = await self._repository.fetch_workspace_asset(asset_id)
        if asset is None:
            raise KeyError(f"Workspace asset {asset_id} not found")
        version = await self._repository.fetch_workspace_asset_version(payload.asset_version_id)
        if version is None or version.asset_id != asset_id:
            raise KeyError(
                f"Asset version {payload.asset_version_id} does not belong to asset {asset_id}"
            )
        await self._validate_asset_link_target(
            target_type=payload.target_type,
            target_id=payload.target_id,
            organization_id=asset.organization_id,
            workspace_id=payload.workspace_id,
        )
        if payload.workspace_id is not None:
            workspace = await self._repository.fetch_workspace(payload.workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {payload.workspace_id} not found")
            if asset.organization_id is not None and workspace.organization_id != asset.organization_id:
                raise ValueError(
                    "Workspace asset links must stay within the asset organization"
                )
        now = self._now()
        link = AssetLink(
            link_id=uuid4(),
            asset_id=asset_id,
            asset_version_id=payload.asset_version_id,
            organization_id=asset.organization_id,
            workspace_id=payload.workspace_id,
            target_type=payload.target_type,
            target_id=payload.target_id,
            purpose=payload.purpose,
            active=True,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.deactivate_asset_links(
                    conn,
                    organization_id=asset.organization_id,
                    workspace_id=payload.workspace_id,
                    target_type=payload.target_type,
                    target_id=payload.target_id,
                    purpose=payload.purpose,
                )
                await self._repository.upsert_asset_link(conn, link)
        return WorkspaceAssetCommandResult(asset=asset, version=version, link=link)

    async def link_asset_version(
        self,
        asset_id: UUID,
        payload: LinkAssetRequest,
    ) -> WorkspaceAssetCommandResult:
        activation = ActivateAssetVersionRequest.model_validate(payload.model_dump(mode="json"))
        return await self.activate_asset_version(asset_id, activation)

    async def list_resolved_agent_assets(
        self,
        *,
        agent_id: UUID,
        workspace_id: UUID | None = None,
    ) -> list[ResolvedAssetBinding]:
        agent = await self._repository.fetch_system_agent(agent_id)
        if agent is None:
            raise KeyError(f"System agent {agent_id} not found")
        workspace: Workspace | None = None
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            if not self._resource_visible_to_workspace(
                agent.scope,
                agent.organization_id,
                workspace,
            ):
                raise PermissionError(
                    f"System agent {agent_id} is not visible in workspace {workspace_id}"
                )
        return await self._repository.list_asset_links_for_target(
            target_type="system_agent",
            target_id=agent_id,
            organization_id=workspace.organization_id if workspace is not None else None,
            workspace_id=workspace_id,
        )

    async def list_resolved_tool_assets(
        self,
        *,
        tool_id: UUID,
        workspace_id: UUID | None = None,
    ) -> list[ResolvedAssetBinding]:
        tool = await self._repository.fetch_system_tool(tool_id)
        if tool is None:
            raise KeyError(f"System tool {tool_id} not found")
        workspace: Workspace | None = None
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            if not self._resource_visible_to_workspace(
                tool.scope,
                tool.organization_id,
                workspace,
            ):
                raise PermissionError(
                    f"System tool {tool_id} is not visible in workspace {workspace_id}"
                )
        return await self._repository.list_asset_links_for_target(
            target_type="system_tool",
            target_id=tool_id,
            organization_id=workspace.organization_id if workspace is not None else None,
            workspace_id=workspace_id,
        )

    async def delete_llm_provider(
        self, provider_id: UUID, payload: DeleteLlmProviderRequest
    ) -> dict[str, bool | str]:
        existing = await self._repository.fetch_llm_provider(provider_id)
        if existing is None:
            raise KeyError(f"LLM provider {provider_id} not found")
        references = await self._llm_provider_references(existing.engine_id)
        if references:
            raise ValueError(
                f"Cannot delete LLM provider {existing.engine_id!r}; "
                f"referenced by system agents: {', '.join(agent.display_name for agent in references)}"
            )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_llm_provider(
                    conn,
                    provider_id=provider_id,
                )
        if not deleted:
            raise KeyError(f"LLM provider {provider_id} not found")
        return {"deleted": True, "provider_id": str(provider_id)}

    async def delete_memory_provider(
        self, provider_id: UUID, payload: DeleteMemoryProviderRequest
    ) -> dict[str, bool | str]:
        _ = payload
        existing = await self._repository.fetch_memory_provider(provider_id)
        if existing is None:
            raise KeyError(f"Memory provider {provider_id} not found")
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_memory_provider(
                    conn,
                    provider_id=provider_id,
                )
        if not deleted:
            raise KeyError(f"Memory provider {provider_id} not found")
        return {"deleted": True, "provider_id": str(provider_id)}

    async def _llm_provider_references(self, engine_id: str) -> list[AgentDefinition]:
        return await self._repository.list_system_agents_referencing_llm_engine(engine_id)

    async def _resolve_search_memory_provider(
        self,
        preferred_provider_key: str | None,
        *,
        organization_id: UUID | None = None,
    ) -> MemoryProviderDefinition:
        providers = await self._visible_enabled_memory_providers(organization_id)
        if preferred_provider_key:
            for provider in providers:
                if provider.provider_key == preferred_provider_key:
                    return provider
            raise KeyError(f"Enabled memory provider {preferred_provider_key!r} not found")
        for provider in providers:
            if provider.provider == "mem0":
                return provider
        for provider in providers:
            if provider.provider == "postgres":
                return provider
        raise ValueError("No enabled memory providers configured")

    async def _sync_memory_entry(self, entry: MemoryEntry) -> None:
        workspace = await self._repository.fetch_workspace(entry.workspace_id)
        organization_id = workspace.organization_id if workspace is not None else None
        providers = await self._visible_enabled_memory_providers(organization_id)
        now = self._now()
        for definition in providers:
            provider = self._memory_provider_index.get(definition.provider)
            if provider is None:
                continue
            existing_record = await self._repository.fetch_memory_provider_record(
                memory_entry_id=entry.memory_entry_id,
                provider_id=definition.provider_id,
            )
            try:
                result = await provider.upsert(
                    definition,
                    entry,
                    external_id=existing_record.external_id if existing_record else None,
                )
                record = MemoryProviderRecord(
                    provider_record_id=(
                        existing_record.provider_record_id
                        if existing_record is not None
                        else uuid4()
                    ),
                    memory_entry_id=entry.memory_entry_id,
                    provider_id=definition.provider_id,
                    external_id=(
                        result.external_id
                        or (existing_record.external_id if existing_record else None)
                    ),
                    status="synced",
                    last_synced_at=now,
                    last_error=None,
                    metadata=result.metadata,
                )
            except Exception as exc:
                logger.warning(
                    "Memory provider sync failed provider=%s memory_entry_id=%s error=%s",
                    definition.provider_key,
                    entry.memory_entry_id,
                    exc,
                )
                record = MemoryProviderRecord(
                    provider_record_id=(
                        existing_record.provider_record_id
                        if existing_record is not None
                        else uuid4()
                    ),
                    memory_entry_id=entry.memory_entry_id,
                    provider_id=definition.provider_id,
                    external_id=existing_record.external_id if existing_record else None,
                    status="failed",
                    last_synced_at=now,
                    last_error=str(exc),
                    metadata=existing_record.metadata if existing_record else {},
                )
            async with self._repository._pool.acquire() as conn:  # noqa: SLF001
                async with conn.transaction():
                    await self._repository.upsert_memory_provider_record(conn, record)

    async def _delete_memory_entry_from_providers(self, entry: MemoryEntry) -> None:
        records = await self._repository.list_memory_provider_records(entry.memory_entry_id)
        now = self._now()
        workspace = await self._repository.fetch_workspace(entry.workspace_id)
        organization_id = workspace.organization_id if workspace is not None else None
        visible_provider_ids = {
            provider.provider_id
            for provider in await self._visible_enabled_memory_providers(organization_id)
        }
        for record in records:
            if record.provider_id not in visible_provider_ids:
                continue
            definition = await self._repository.fetch_memory_provider(record.provider_id)
            if definition is None:
                continue
            provider = self._memory_provider_index.get(definition.provider)
            if provider is None:
                continue
            try:
                await provider.delete(
                    definition,
                    entry,
                    external_id=record.external_id,
                )
                updated_record = record.model_copy(
                    update={
                        "status": "archived",
                        "last_synced_at": now,
                        "last_error": None,
                    }
                )
            except Exception as exc:
                logger.warning(
                    "Memory provider delete failed provider=%s memory_entry_id=%s error=%s",
                    definition.provider_key,
                    entry.memory_entry_id,
                    exc,
                )
                updated_record = record.model_copy(
                    update={
                        "status": "failed",
                        "last_synced_at": now,
                        "last_error": str(exc),
                    }
                )
            async with self._repository._pool.acquire() as conn:  # noqa: SLF001
                async with conn.transaction():
                    await self._repository.upsert_memory_provider_record(conn, updated_record)

    async def _backfill_system_agent_interaction_contracts(self) -> None:
        try:
            agents = await self._repository.list_system_agents(scope="global")
            organizations = await self._repository.list_organizations()
            for organization in organizations:
                agents.extend(
                    await self._repository.list_system_agents(
                        scope="organization",
                        organization_id=organization.organization_id,
                    )
                )
        except (AttributeError, TypeError):
            agents = await self._repository.list_system_agents()
        missing = [
            agent
            for agent in agents
            if interaction_contract_is_empty(agent.interaction_contract)
        ]
        if not missing:
            return
        logger.info(
            "Backfilling interaction contracts for %s system agents",
            len(missing),
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                for agent in missing:
                    updated = agent.model_copy(
                        update={
                            "interaction_contract": build_default_interaction_contract(
                                display_name=agent.display_name,
                                role=agent.role,
                                description=agent.description,
                                capabilities=agent.capabilities,
                            ),
                            "updated_at": self._now(),
                        }
                    )
                    await self._repository.upsert_system_agent(conn, updated)

    async def upsert_role_definition(
        self,
        workspace_id: UUID,
        payload: UpsertRoleDefinitionRequest,
    ) -> RoleDefinitionCommandResult:
        logger.debug(
            "Kernel upsert_role_definition workspace_id=%s actor_id=%s name=%r",
            workspace_id,
            payload.actor.participant_id,
            payload.name,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_management_role(workspace_id, payload.actor)
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        role_definition = RoleDefinition(
            name=payload.name,
            definition=payload.definition,
            updated_by=payload.actor.participant_id,
            updated_at=now,
        )
        role_map = {
            role.name: role.model_dump(mode="json")
            for role in self._role_definitions_from_workspace(workspace)
        }
        role_map[role_definition.name] = role_definition.model_dump(mode="json")
        updated_workspace = workspace.model_copy(
            update={
                "updated_at": now,
                "metadata": {
                    **workspace.metadata,
                    "role_definitions": role_map,
                },
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace(conn, updated_workspace)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "role_definition.upserted",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=role_definition.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return RoleDefinitionCommandResult(role_definition=role_definition, events=[event])

    async def delete_role_definition(
        self,
        workspace_id: UUID,
        role_name: str,
        payload: DeleteRoleDefinitionRequest,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Kernel delete_role_definition workspace_id=%s actor_id=%s name=%r",
            workspace_id,
            payload.actor.participant_id,
            role_name,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_management_role(workspace_id, payload.actor)
        now = self._now()
        actor = self._actor_from_input(payload.actor)

        role_map = {
            role.name: role.model_dump(mode="json")
            for role in self._role_definitions_from_workspace(workspace)
        }
        if role_name not in role_map:
            raise KeyError(f"Role {role_name} not found in workspace {workspace_id}")

        removed_role_data = role_map.pop(role_name)
        updated_workspace = workspace.model_copy(
            update={
                "updated_at": now,
                "metadata": {**workspace.metadata, "role_definitions": role_map},
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace(conn, updated_workspace)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "role_definition.deleted",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=removed_role_data,
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return {"deleted": True, "workspace_id": str(workspace_id), "role_name": role_name}

    async def list_workspace_tools(self, workspace_id: UUID) -> list[WorkspaceTool]:
        logger.debug("Kernel list_workspace_tools workspace_id=%s", workspace_id)
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_workspace_tools(workspace_id)

    async def attach_workspace_tool(
        self,
        workspace_id: UUID,
        payload: AttachWorkspaceToolRequest,
    ) -> WorkspaceToolCommandResult:
        logger.debug(
            "Kernel attach_workspace_tool workspace_id=%s actor_id=%s tool_id=%s enabled=%s",
            workspace_id,
            payload.actor.participant_id,
            payload.tool_id,
            payload.enabled,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_management_role(workspace_id, payload.actor)
        system_tool = await self._repository.fetch_system_tool(payload.tool_id)
        if system_tool is None:
            raise KeyError(f"System tool {payload.tool_id} not found")
        if not self._resource_visible_to_workspace(
            system_tool.scope,
            system_tool.organization_id,
            workspace,
        ):
            raise PermissionError(
                f"System tool {payload.tool_id} is not visible in workspace {workspace_id}"
            )
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        tool = WorkspaceTool(
            tool_id=system_tool.tool_id,
            name=system_tool.name,
            description=system_tool.description,
            parameter_contract=system_tool.parameter_contract,
            input_schema=system_tool.input_schema,
            execution=system_tool.execution,
            enabled=payload.enabled,
            attached_by=payload.actor.participant_id,
            attached_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace_tool(
                    conn,
                    workspace_id=workspace_id,
                    tool=tool,
                )
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.tool_attached",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=tool.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return WorkspaceToolCommandResult(tool=tool, events=[event])

    async def update_workspace_tool(
        self,
        workspace_id: UUID,
        tool_id: UUID,
        payload: UpdateWorkspaceToolRequest,
    ) -> WorkspaceToolCommandResult:
        logger.debug(
            "Kernel update_workspace_tool workspace_id=%s actor_id=%s tool_id=%s",
            workspace_id,
            payload.actor.participant_id,
            tool_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_management_role(workspace_id, payload.actor)
        existing = await self._repository.fetch_workspace_tool(workspace_id, tool_id)
        if existing is None:
            raise KeyError(f"Workspace tool {tool_id} not attached to workspace {workspace_id}")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        updated = existing.model_copy(
            update={
                "enabled": existing.enabled if payload.enabled is None else payload.enabled,
                "updated_at": now,
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_workspace_tool(
                    conn,
                    workspace_id=workspace_id,
                    tool=updated,
                )
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.tool_updated",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=updated.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return WorkspaceToolCommandResult(tool=updated, events=[event])

    async def delete_workspace_tool(
        self,
        workspace_id: UUID,
        tool_id: UUID,
        payload: DeleteWorkspaceToolRequest,
    ) -> dict[str, bool | str]:
        logger.debug(
            "Kernel delete_workspace_tool workspace_id=%s actor_id=%s tool_id=%s",
            workspace_id,
            payload.actor.participant_id,
            tool_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        await self._require_workspace_management_role(workspace_id, payload.actor)
        removed = await self._repository.fetch_workspace_tool(workspace_id, tool_id)
        if removed is None:
            raise KeyError(f"Workspace tool {tool_id} not attached to workspace {workspace_id}")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                deleted = await self._repository.delete_workspace_tool(
                    conn,
                    workspace_id=workspace_id,
                    tool_id=tool_id,
                )
                if not deleted:
                    raise KeyError(f"Workspace tool {tool_id} not attached to workspace {workspace_id}")
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.tool_deleted",
                    actor=actor,
                    target=TargetRef(type="workspace", id=workspace_id),
                    payload=removed.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return {"deleted": True, "workspace_id": str(workspace_id), "tool_id": str(tool_id)}

    async def assume_participant_role(
        self,
        workspace_id: UUID,
        participant_id: UUID,
        payload: AssumeParticipantRoleRequest,
    ) -> ParticipantCommandResult:
        logger.debug(
            "Kernel assume_participant_role workspace_id=%s participant_id=%s actor_id=%s role=%r capability_count=%s",
            workspace_id,
            participant_id,
            payload.actor.participant_id,
            payload.role,
            len(payload.capabilities),
        )
        if participant_id != payload.actor.participant_id:
            raise ValueError("Participants may only assume roles for themselves")
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        existing = await self._repository.fetch_participant(workspace_id, participant_id)
        role_definitions = {
            role_definition.name: role_definition
            for role_definition in self._role_definitions_from_workspace(workspace)
        }
        role_definition = role_definitions.get(payload.role)
        if payload.description is None and role_definition is None:
            raise ValueError(
                f"Role {payload.role!r} is not defined in this workspace; provide a description or create the role first"
            )
        description = payload.description or (role_definition.definition if role_definition else None)
        participant = ParticipantProfile(
            participant_id=participant_id,
            workspace_id=workspace_id,
            participant_type=payload.actor.participant_type,
            user_id=participant_id if payload.actor.participant_type == "user" else None,
            display_name=payload.actor.display_name,
            description=description,
            roles=[payload.role],
            capabilities=payload.capabilities,
            status=existing.status if existing is not None else "active",
            visibility_scope=payload.actor.visibility_scope,
            agent_config=existing.agent_config if existing is not None else None,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            metadata=(existing.metadata if existing is not None else {}),
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "participant.role_assumed",
                    actor=actor,
                    target=TargetRef(type="participant", id=participant.participant_id),
                    payload=participant.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        logger.debug(
            "Kernel assume_participant_role complete workspace_id=%s participant_id=%s sequence=%s",
            workspace_id,
            participant_id,
            event.sequence,
        )
        return ParticipantCommandResult(participant=participant, events=[event])

    async def create_agent_participant(
        self,
        workspace_id: UUID,
        payload: CreateAgentParticipantRequest,
    ) -> ParticipantCommandResult:
        logger.debug(
            "Kernel create_agent_participant workspace_id=%s actor_id=%s agent_id=%s",
            workspace_id,
            payload.actor.participant_id,
            payload.agent_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        system_agent = await self._repository.fetch_system_agent(payload.agent_id)
        if system_agent is None:
            raise KeyError(f"System agent {payload.agent_id} not found")
        if not self._resource_visible_to_workspace(
            system_agent.scope,
            system_agent.organization_id,
            workspace,
        ):
            raise PermissionError(
                f"System agent {payload.agent_id} is not visible in workspace {workspace_id}"
            )
        workspace_tools = await self._repository.list_workspace_tools(workspace_id)
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = ParticipantProfile(
            participant_id=uuid4(),
            workspace_id=workspace_id,
            participant_type="agent",
            system_agent_id=system_agent.agent_id,
            display_name=system_agent.display_name,
            description=system_agent.description,
            roles=[system_agent.role],
            capabilities=self._advertised_agent_capabilities(
                system_agent.capabilities,
                workspace_tools,
            ),
            status="active",
            visibility_scope="workspace",
            agent_config=AgentConfiguration(
                endpoint=system_agent.endpoint,
                system_prompt=system_agent.system_prompt,
                harness=system_agent.harness,
                definition=system_agent.definition,
            ),
            created_at=now,
            updated_at=now,
            metadata={},
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "participant.agent_registered",
                    actor=actor,
                    target=TargetRef(type="participant", id=participant.participant_id),
                    payload=participant.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return ParticipantCommandResult(
            participant=self._advertise_workspace_tools(participant, workspace_tools),
            events=[event],
        )

    async def update_agent_participant(
        self,
        workspace_id: UUID,
        participant_id: UUID,
        payload: UpdateAgentParticipantRequest,
    ) -> ParticipantCommandResult:
        logger.debug(
            "Kernel update_agent_participant workspace_id=%s participant_id=%s actor_id=%s",
            workspace_id,
            participant_id,
            payload.actor.participant_id,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        existing = await self._repository.fetch_participant(workspace_id, participant_id)
        if existing is None:
            raise KeyError(f"Participant {participant_id} not found")
        if existing.participant_type != "agent":
            raise ValueError("Only agent participants can be updated via the agent API")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        workspace_tools = await self._repository.list_workspace_tools(workspace_id)
        updated = existing.model_copy(
            update={
                "visibility_scope": (
                    payload.visibility_scope or existing.visibility_scope
                ),
                "status": payload.status or existing.status,
                "updated_at": now,
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_participant(conn, updated)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "participant.agent_updated",
                    actor=actor,
                    target=TargetRef(type="participant", id=participant_id),
                    payload=updated.model_dump(mode="json"),
                    visibility="workspace",
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        return ParticipantCommandResult(
            participant=self._advertise_workspace_tools(updated, workspace_tools),
            events=[event],
        )

    async def create_thread(
        self, workspace_id: UUID, payload: CreateThreadRequest
    ) -> ThreadCommandResult:
        logger.debug(
            "Kernel create_thread workspace_id=%s participant_id=%s title=%r",
            workspace_id,
            payload.actor.participant_id,
            payload.title,
        )
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        thread_id = uuid4()
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        )
        thread = Thread(
            thread_id=thread_id,
            workspace_id=workspace_id,
            title=payload.title,
            parent_thread_id=payload.parent_thread_id,
            previous_thread_id=payload.previous_thread_id,
            related_thread_ids=payload.related_thread_ids,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        membership = Membership(
            membership_id=uuid4(),
            workspace_id=workspace_id,
            thread_id=thread_id,
            participant_id=payload.actor.participant_id,
            role="owner",
            permissions=["post_messages", "manage_thread", "edit_memory"],
            joined_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_thread(conn, thread)
                await self._repository.upsert_membership(conn, membership)
                events = [
                    await self._build_thread_event(
                        conn,
                        workspace_id,
                        thread_id,
                        "thread.created",
                        actor=actor,
                        target=TargetRef(type="thread", id=thread.thread_id),
                        payload=thread.model_dump(mode="json"),
                        timestamp=now,
                    ),
                    await self._build_thread_event(
                        conn,
                        workspace_id,
                        thread_id,
                        "participant.joined",
                        actor=actor,
                        target=TargetRef(type="participant", id=participant.participant_id),
                        payload=membership.model_dump(mode="json"),
                        visibility="workspace",
                        timestamp=now,
                    ),
                ]
                for event in events:
                    await self._repository.record_event(conn, event)

        detail = ThreadDetail(thread=thread, memberships=[membership])
        logger.debug(
            "Kernel create_thread complete thread_id=%s event_count=%s",
            thread_id,
            len(events),
        )
        return ThreadCommandResult(thread=thread, detail=detail, events=events)

    async def list_threads(self, workspace_id: UUID) -> list[Thread]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_threads(workspace_id)

    async def get_thread_detail(self, thread_id: UUID) -> ThreadDetail:
        logger.debug("Kernel get_thread_detail thread_id=%s", thread_id)
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        memberships = await self._repository.list_memberships(thread_id)
        return ThreadDetail(thread=thread, memberships=memberships)

    async def get_thread_timeline(self, thread_id: UUID) -> TimelinePage:
        logger.debug("Kernel get_thread_timeline thread_id=%s", thread_id)
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        messages = await self._repository.list_timeline_messages(thread_id)
        return TimelinePage(thread_id=thread_id, messages=messages)

    async def list_workspace_communication_log(
        self,
        workspace_id: UUID,
        *,
        thread_id: UUID | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> WorkspaceCommunicationLogPage:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        if thread_id is not None:
            thread = await self._repository.fetch_thread(thread_id)
            if thread is None or thread.workspace_id != workspace_id:
                raise KeyError(f"Thread {thread_id} not found")
        return await self._repository.list_workspace_communication_log(
            workspace_id,
            thread_id=thread_id,
            limit=limit,
            offset=offset,
        )

    async def _persist_workspace_communication_messages(
        self,
        messages: list[TimelineMessage],
    ) -> None:
        if not messages:
            return
        await self._repository.persist_workspace_communication_messages(messages)

    async def list_pending_tasks_for_system_agent(
        self, system_agent_id: UUID, *, limit: int = 10
    ) -> list[Task]:
        return await self._runtime_execution.list_pending_tasks_for_system_agent(
            system_agent_id,
            limit=limit,
        )

    async def claim_task_for_system_agent(
        self,
        task_id: UUID,
        system_agent_id: UUID,
    ) -> TaskCommandResult:
        return await self._runtime_execution.claim_task_for_system_agent(
            task_id,
            system_agent_id,
        )

    async def build_agent_execution_context(
        self,
        task_id: UUID,
        system_agent_id: UUID,
        run_id: UUID | None = None,
    ) -> AgentExecutionContext:
        return await self._runtime_execution.build_agent_execution_context(
            task_id,
            system_agent_id,
            run_id,
        )

    async def build_agent_execution_context_for_run_step(
        self,
        step_id: UUID,
    ) -> AgentExecutionContext:
        return await self._runtime_execution.build_agent_execution_context_for_run_step(
            step_id
        )

    async def enforce_run_step_token_budget(
        self,
        *,
        step_id: UUID,
        worker_id: str,
        global_daily_token_cap: int,
        default_workspace_daily_token_cap: int,
    ) -> RunCommandResult | None:
        return await self._runtime_execution.enforce_run_step_token_budget(
            step_id=step_id,
            worker_id=worker_id,
            global_daily_token_cap=global_daily_token_cap,
            default_workspace_daily_token_cap=default_workspace_daily_token_cap,
        )

    async def get_runtime_overview(
        self,
        *,
        organization_id: UUID | None = None,
    ) -> dict[str, object]:
        return await self._runtime_execution.get_runtime_overview(
            organization_id=organization_id,
        )

    async def claim_next_run_step(
        self,
        *,
        worker_id: str,
        lease_ttl_seconds: int,
    ) -> RunStepCommandResult:
        return await self._runtime_execution.claim_next_run_step(
            worker_id=worker_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    async def heartbeat_run_step(
        self,
        *,
        step_id: UUID,
        worker_id: str,
        lease_ttl_seconds: int,
    ) -> RunStep | None:
        now = self._now()
        return await self._repository.heartbeat_run_step(
            step_id=step_id,
            worker_id=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_ttl_seconds),
            now=now,
        )

    async def queue_tool_calls_for_run_step(
        self,
        step_id: UUID,
        worker_id: str,
        drafts: list[AgentToolCallDraft],
    ) -> RunStepCommandResult:
        step = await self._repository.fetch_run_step(step_id)
        if step is None:
            raise KeyError(f"Run step {step_id} not found")
        if step.claimed_by_worker != worker_id:
            raise ValueError(f"Run step {step_id} is not claimed by worker {worker_id}")
        run = await self._repository.fetch_run(step.run_id)
        if run is None:
            raise KeyError(f"Run {step.run_id} not found")
        task = await self._repository.fetch_task(step.task_id)
        if task is None:
            raise KeyError(f"Task {step.task_id} not found")
        system_agent = await self._repository.fetch_system_agent(step.system_agent_id)
        if system_agent is None:
            raise KeyError(f"System agent {step.system_agent_id} not found")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=step.system_agent_id,
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        now = self._now()
        queued_step = step.model_copy(
            update={
                "status": "waiting_tools",
                "output": {
                    "tool_calls_requested": [
                        draft.model_dump(mode="json") for draft in drafts
                    ]
                },
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "updated_at": now,
            }
        )
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run_step(conn, queued_step)
                for draft in drafts:
                    tool = await self._repository.fetch_agent_internal_tool_by_name(
                        step.system_agent_id,
                        draft.tool_name,
                    )
                    if tool is None:
                        tool = await self._repository.fetch_workspace_tool_by_name(
                            task.workspace_id,
                            draft.tool_name,
                        )
                    if tool is None:
                        raise KeyError(
                            f"Tool {draft.tool_name!r} not found for system agent {step.system_agent_id} in workspace {task.workspace_id}"
                        )
                    tool_call = ToolCall(
                        tool_call_id=uuid4(),
                        run_id=run.run_id,
                        run_step_id=step.step_id,
                        task_id=task.task_id,
                        workspace_id=task.workspace_id,
                        thread_id=task.thread_id,
                        system_agent_id=step.system_agent_id,
                        tool_id=tool.tool_id,
                        tool_name=tool.name,
                        status="created",
                        arguments=draft.arguments,
                        execution_spec=self._build_tool_execution_spec(
                            tool=tool,
                            draft=draft,
                            workspace_id=task.workspace_id,
                        ).model_dump(mode="json"),
                        submitted_at=now,
                        created_at=now,
                        updated_at=now,
                        metadata=draft.metadata,
                    )
                    await self._repository.upsert_tool_call(conn, tool_call)
                    event = await self._build_thread_event(
                        conn,
                        task.workspace_id,
                        task.thread_id,
                        "tool_call.created",
                        actor=actor,
                        target=TargetRef(type="tool_call", id=tool_call.tool_call_id),
                        payload=tool_call.model_dump(mode="json"),
                        visibility="agents_only",
                        timestamp=now,
                        correlation_id=run.correlation_id,
                        causation_id=task.task_id,
                    )
                    events.append(event)
                for event in events:
                    await self._repository.record_event(conn, event)
        return RunStepCommandResult(
            step=queued_step,
            run=run,
            task=task,
            events=events,
        )

    async def complete_run_step(
        self,
        step_id: UUID,
        worker_id: str,
        result: AgentRunResult,
    ) -> RunCommandResult:
        step = await self._repository.fetch_run_step(step_id)
        if step is None:
            raise KeyError(f"Run step {step_id} not found")
        if step.claimed_by_worker != worker_id:
            raise ValueError(f"Run step {step_id} is not claimed by worker {worker_id}")
        now = self._now()
        updated_step = step.model_copy(
            update={
                "status": "completed",
                "output": result.model_dump(mode="json"),
                "finished_at": now,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run_step(conn, updated_step)
        completion = await self.complete_run(step.run_id, step.system_agent_id, result)
        return completion

    async def fail_run_step(
        self,
        step_id: UUID,
        worker_id: str,
        error: str,
        *,
        stop_reason: StopReason = "tool_failure",
    ) -> RunCommandResult:
        step = await self._repository.fetch_run_step(step_id)
        if step is None:
            raise KeyError(f"Run step {step_id} not found")
        if step.claimed_by_worker != worker_id:
            raise ValueError(f"Run step {step_id} is not claimed by worker {worker_id}")
        now = self._now()
        updated_step = step.model_copy(
            update={
                "status": "failed",
                "error": error,
                "finished_at": now,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run_step(conn, updated_step)
        return await self.fail_run(step.run_id, step.system_agent_id, error, stop_reason=stop_reason)

    async def claim_next_tool_call(
        self,
        *,
        worker_id: str,
        lease_ttl_seconds: int,
        max_parallel_calls_per_run: int,
        max_concurrent_calls_per_tool: int,
    ) -> ToolCallCommandResult:
        now = self._now()
        tool_call = await self._repository.claim_next_tool_call(
            worker_id=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_ttl_seconds),
            now=now,
            max_parallel_calls_per_run=max_parallel_calls_per_run,
            max_concurrent_calls_per_tool=max_concurrent_calls_per_tool,
        )
        if tool_call is None:
            return ToolCallCommandResult()
        step = await self._repository.fetch_run_step(tool_call.run_step_id)
        run = await self._repository.fetch_run(tool_call.run_id)
        task = await self._repository.fetch_task(tool_call.task_id)
        if step is None or run is None or task is None:
            raise KeyError(f"Tool call {tool_call.tool_call_id} is missing execution state")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=tool_call.system_agent_id,
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                event = await self._build_thread_event(
                    conn,
                    task.workspace_id,
                    task.thread_id,
                    "tool_call.claimed",
                    actor=actor,
                    target=TargetRef(type="tool_call", id=tool_call.tool_call_id),
                    payload=tool_call.model_dump(mode="json"),
                    visibility="agents_only",
                    timestamp=now,
                    correlation_id=run.correlation_id,
                    causation_id=task.task_id,
                )
                await self._repository.record_event(conn, event)
        return ToolCallCommandResult(
            tool_call=tool_call,
            step=step,
            run=run,
            task=task,
            events=[event],
        )

    async def heartbeat_tool_call(
        self,
        *,
        tool_call_id: UUID,
        worker_id: str,
        lease_ttl_seconds: int,
    ) -> ToolCall | None:
        now = self._now()
        return await self._repository.heartbeat_tool_call(
            tool_call_id=tool_call_id,
            worker_id=worker_id,
            lease_expires_at=now + timedelta(seconds=lease_ttl_seconds),
            now=now,
        )

    async def update_tool_call_execution_handle(
        self,
        tool_call_id: UUID,
        worker_id: str,
        execution_handle: str,
    ) -> ToolCall | None:
        tool_call = await self._repository.fetch_tool_call(tool_call_id)
        if tool_call is None:
            raise KeyError(f"Tool call {tool_call_id} not found")
        if tool_call.claimed_by_worker != worker_id:
            raise ValueError(
                f"Tool call {tool_call_id} is not claimed by worker {worker_id}"
            )
        now = self._now()
        updated = tool_call.model_copy(
            update={
                "execution_handle": execution_handle,
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_tool_call(conn, updated)
        return updated

    async def complete_tool_call(
        self,
        tool_call_id: UUID,
        worker_id: str,
        result: ToolCallResult,
    ) -> ToolCallCommandResult:
        return await self._finalize_tool_call(
            tool_call_id,
            worker_id,
            status="completed",
            result=result,
            error=result.error,
            event_type="tool_call.completed",
        )

    async def fail_tool_call(
        self,
        tool_call_id: UUID,
        worker_id: str,
        error: str,
    ) -> ToolCallCommandResult:
        return await self._finalize_tool_call(
            tool_call_id,
            worker_id,
            status="failed",
            result=ToolCallResult(error=error),
            error=error,
            event_type="tool_call.failed",
        )

    async def reconcile_expired_execution_leases(self) -> LeaseReconciliationResult:
        now = self._now()
        result = LeaseReconciliationResult()
        for step in await self._repository.list_expired_run_steps(now=now):
            if step.attempt_count >= _MAX_RUN_STEP_ATTEMPTS:
                failure = await self._fail_expired_run_step(
                    step,
                    error=(
                        "Run step lease expired after "
                        f"{step.attempt_count} attempts"
                    ),
                )
                result.events.extend(failure.events)
                continue
            result.run_steps.append(
                await self._requeue_expired_run_step(step, now=now)
            )
        for tool_call in await self._repository.list_expired_tool_calls(now=now):
            if tool_call.attempt_count >= _MAX_TOOL_CALL_ATTEMPTS:
                failure = await self._fail_expired_tool_call(
                    tool_call,
                    error=(
                        "Tool call lease expired after "
                        f"{tool_call.attempt_count} attempts"
                    ),
                )
                result.events.extend(failure.events)
                continue
            result.tool_calls.append(
                await self._requeue_expired_tool_call(tool_call, now=now)
            )
        return result

    async def _requeue_expired_run_step(self, step: RunStep, *, now: datetime) -> RunStep:
        updated_step = step.model_copy(
            update={
                "status": "created",
                "claimed_by_worker": None,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": now
                + timedelta(
                    seconds=self._retry_backoff_for_attempt(step.attempt_count)
                ),
                "execution_handle": None,
                "error": (
                    "Run step lease expired; "
                    f"retry {step.attempt_count + 1} scheduled"
                ),
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run_step(conn, updated_step)
        return updated_step

    async def _requeue_expired_tool_call(
        self,
        tool_call: ToolCall,
        *,
        now: datetime,
    ) -> ToolCall:
        updated_tool_call = tool_call.model_copy(
            update={
                "status": "created",
                "claimed_by_worker": None,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": now
                + timedelta(
                    seconds=self._retry_backoff_for_attempt(tool_call.attempt_count)
                ),
                "execution_handle": None,
                "error": (
                    "Tool call lease expired; "
                    f"retry {tool_call.attempt_count + 1} scheduled"
                ),
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_tool_call(conn, updated_tool_call)
        return updated_tool_call

    async def _fail_expired_run_step(
        self,
        step: RunStep,
        *,
        error: str,
    ) -> RunCommandResult:
        now = self._now()
        updated_step = step.model_copy(
            update={
                "status": "failed",
                "error": error,
                "finished_at": now,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "updated_at": now,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_run_step(conn, updated_step)
        run = await self._repository.fetch_run(step.run_id)
        if run is not None and run.status in {"completed", "failed"}:
            return RunCommandResult()
        return await self.fail_run(
            step.run_id,
            step.system_agent_id,
            error,
            stop_reason="tool_failure",
        )

    async def _fail_expired_tool_call(
        self,
        tool_call: ToolCall,
        *,
        error: str,
    ) -> CommandResult:
        step = await self._repository.fetch_run_step(tool_call.run_step_id)
        run = await self._repository.fetch_run(tool_call.run_id)
        task = await self._repository.fetch_task(tool_call.task_id)
        if step is None or run is None or task is None:
            raise KeyError(
                f"Tool call {tool_call.tool_call_id} is missing execution state"
            )
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=tool_call.system_agent_id,
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        now = self._now()
        updated_tool_call = tool_call.model_copy(
            update={
                "status": "failed",
                "error": error,
                "result": ToolCallResult(error=error),
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "finished_at": now,
                "updated_at": now,
            }
        )
        should_fail_step = step.status == "waiting_tools"
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_tool_call(conn, updated_tool_call)
                if should_fail_step:
                    await self._repository.upsert_run_step(
                        conn,
                        step.model_copy(
                            update={
                                "status": "failed",
                                "error": error,
                                "finished_at": now,
                                "lease_expires_at": None,
                                "last_heartbeat_at": None,
                                "next_retry_at": None,
                                "claimed_by_worker": None,
                                "execution_handle": None,
                                "updated_at": now,
                            }
                        ),
                    )
                event = await self._build_thread_event(
                    conn,
                    task.workspace_id,
                    task.thread_id,
                    "tool_call.failed",
                    actor=actor,
                    target=TargetRef(type="tool_call", id=tool_call.tool_call_id),
                    payload=updated_tool_call.model_dump(mode="json"),
                    visibility="agents_only",
                    timestamp=now,
                    correlation_id=run.correlation_id,
                    causation_id=task.task_id,
                )
                await self._repository.record_event(conn, event)
        events = [event]
        if should_fail_step and run.status not in {"completed", "failed"}:
            failure = await self.fail_run(
                tool_call.run_id,
                tool_call.system_agent_id,
                error,
                stop_reason="tool_failure",
            )
            events.extend(failure.events)
        return CommandResult(events=events)

    @staticmethod
    def _retry_backoff_for_attempt(attempt_count: int) -> int:
        index = max(0, min(attempt_count - 1, len(_RETRY_BACKOFF_SECONDS) - 1))
        return _RETRY_BACKOFF_SECONDS[index]

    async def build_requeued_execution_events(
        self,
        run_steps: list[RunStep],
        tool_calls: list[ToolCall],
    ) -> list[EventEnvelope]:
        timestamp = self._now()
        events: list[EventEnvelope] = []
        for step in run_steps:
            run = await self._repository.fetch_run(step.run_id)
            task = await self._repository.fetch_task(step.task_id)
            if run is None or task is None:
                continue
            participant = await self._require_run_participant(
                run=run,
                task=task,
                system_agent_id=step.system_agent_id,
            )
            events.append(
                EventEnvelope(
                    event_type="run_step.requeued",
                    workspace_id=step.workspace_id,
                    thread_id=step.thread_id,
                    actor=ActorRef(type="agent", id=participant.participant_id),
                    target=TargetRef(type="run_step", id=step.step_id),
                    visibility="agents_only",
                    correlation_id=run.correlation_id,
                    causation_id=task.task_id,
                    timestamp=timestamp,
                    payload=step.model_dump(mode="json"),
                )
            )
        for tool_call in tool_calls:
            run = await self._repository.fetch_run(tool_call.run_id)
            task = await self._repository.fetch_task(tool_call.task_id)
            if run is None or task is None:
                continue
            participant = await self._require_run_participant(
                run=run,
                task=task,
                system_agent_id=tool_call.system_agent_id,
            )
            events.append(
                EventEnvelope(
                    event_type="tool_call.requeued",
                    workspace_id=tool_call.workspace_id,
                    thread_id=tool_call.thread_id,
                    actor=ActorRef(type="agent", id=participant.participant_id),
                    target=TargetRef(type="tool_call", id=tool_call.tool_call_id),
                    visibility="agents_only",
                    correlation_id=run.correlation_id,
                    causation_id=task.task_id,
                    timestamp=timestamp,
                    payload=tool_call.model_dump(mode="json"),
                )
            )
        return events

    async def append_run_progress(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        content: str,
    ) -> RunCommandResult:
        return await self._runtime_execution.append_run_progress(
            run_id,
            system_agent_id,
            content,
        )

    async def complete_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        result: AgentRunResult,
    ) -> RunCommandResult:
        completion = await self._runtime_execution.complete_run(
            run_id,
            system_agent_id,
            result,
        )
        rendered_messages: list[TimelineMessage] = []
        if completion.run is not None and completion.task is not None and (
            result.interaction_requests
            or (completion.message is not None and result.metadata.get("create_task"))
        ):
            participant = await self._repository.fetch_participant(
                completion.run.workspace_id,
                completion.run.participant_id,
            )
            thread = await self._repository.fetch_thread(completion.task.thread_id)
            if participant is not None and thread is not None:
                actor_input = ParticipantInput(
                    participant_id=participant.participant_id,
                    participant_type=participant.participant_type,
                    user_id=participant.user_id,
                    display_name=participant.display_name,
                    description=participant.description,
                    roles=participant.roles,
                    capabilities=participant.capabilities,
                    visibility_scope=participant.visibility_scope,
                )
                now = self._now()
                extra_events: list[EventEnvelope] = []
                async with self._repository._pool.acquire() as conn:  # noqa: SLF001
                    async with conn.transaction():
                        if completion.message is not None and result.metadata.get("create_task"):
                            for task in await self._build_message_tasks(
                                thread=thread,
                                message=completion.message,
                                actor_input=actor_input,
                                visibility=completion.message.visibility,
                                timestamp=now,
                            ):
                                await self._repository.upsert_task(conn, task)
                                extra_events.append(
                                    EventEnvelope(
                                        event_type="task.created",
                                        workspace_id=thread.workspace_id,
                                        thread_id=thread.thread_id,
                                        actor=completion.message.actor,
                                        target=TargetRef(type="task", id=task.task_id),
                                        visibility="agents_only",
                                        correlation_id=completion.message.correlation_id,
                                        causation_id=completion.message.message_id,
                                        sequence=await self._repository.next_thread_sequence(
                                            conn,
                                            thread.thread_id,
                                        ),
                                        timestamp=now,
                                        payload=task.model_dump(mode="json"),
                                    )
                                )
                        if result.interaction_requests:
                            request_payloads = [
                                CreateInteractionRequest(
                                    title=draft.title,
                                    summary=draft.summary,
                                    questions=[
                                        CreateInteractionQuestionRequest(
                                            prompt=question.prompt,
                                            kind=question.kind,
                                            expected_format=question.expected_format,
                                            metadata=question.metadata,
                                        )
                                        for question in draft.questions
                                    ],
                                    selectors=draft.selectors,
                                    target_participant_ids=draft.target_participant_ids,
                                    completion_rule=draft.completion_rule,
                                    timeout_at=draft.timeout_at,
                                    metadata=draft.metadata,
                            )
                                for draft in result.interaction_requests
                            ]
                            request_result = await self._create_interaction_requests_in_transaction(
                                conn,
                                thread=thread,
                                actor_input=actor_input,
                                requests=request_payloads,
                                timestamp=now,
                                correlation_id=completion.task.correlation_id,
                                requester_message=completion.message,
                                requester_run=completion.run,
                                requester_task=completion.task,
                            )
                            rendered_messages.extend(request_result.messages)
                            for rendered_message in request_result.messages:
                                await self._repository.upsert_message(conn, rendered_message)
                                request_result.events.append(
                                    EventEnvelope(
                                        event_type="message.created",
                                        workspace_id=rendered_message.workspace_id,
                                        thread_id=rendered_message.thread_id,
                                        actor=rendered_message.actor,
                                        target=TargetRef(type="message", id=rendered_message.message_id),
                                        visibility=rendered_message.visibility,
                                        correlation_id=rendered_message.correlation_id,
                                        causation_id=rendered_message.causation_id,
                                        sequence=rendered_message.sequence,
                                        timestamp=now,
                                        payload=rendered_message.model_dump(mode="json"),
                                    )
                                )
                            extra_events.extend(request_result.events)
                        for event in extra_events:
                            await self._repository.record_event(conn, event)
                completion.events.extend(extra_events)
        await self._persist_workspace_communication_messages(rendered_messages)
        return completion

    async def fail_run(
        self,
        run_id: UUID,
        system_agent_id: UUID,
        error: str,
        *,
        stop_reason: StopReason = "tool_failure",
    ) -> RunCommandResult:
        return await self._runtime_execution.fail_run(
            run_id,
            system_agent_id,
            error,
            stop_reason=stop_reason,
        )

    async def post_message(
        self, thread_id: UUID, payload: CreateMessageRequest
    ) -> MessageCommandResult:
        logger.debug(
            "Kernel post_message thread_id=%s participant_id=%s visibility=%s create_task=%s content_len=%s",
            thread_id,
            payload.actor.participant_id,
            payload.visibility,
            payload.create_task,
            len(payload.content),
        )
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=payload.actor,
            now=now,
        )
        correlation_id = uuid4()
        message_metadata = dict(payload.metadata)
        if payload.target_system_agent_id is not None:
            message_metadata["target_system_agent_id"] = str(payload.target_system_agent_id)
        if payload.target_tool_scope is not None:
            message_metadata["target_tool_scope"] = payload.target_tool_scope
        tool_generation_request = await self._build_tool_generation_request_for_message(
            thread=thread,
            actor_input=payload.actor,
            participant=participant,
            content=payload.content,
            metadata=message_metadata,
            timestamp=now,
        )
        if tool_generation_request is not None:
            message_metadata["tool_generation_request_id"] = str(
                tool_generation_request.request_id
            )
            message_metadata["tool_generation_request_status"] = tool_generation_request.status
        message = TimelineMessage(
            message_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            actor=actor,
            visibility=payload.visibility,
            content=payload.content,
            status="completed",
            correlation_id=correlation_id,
            sequence=0,
            created_at=now,
            updated_at=now,
            metadata=message_metadata,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                membership = await self._repository.fetch_active_membership(
                    conn,
                    thread_id=thread_id,
                    participant_id=payload.actor.participant_id,
                )
                if membership is None:
                    logger.debug(
                        "Kernel post_message creating membership thread_id=%s participant_id=%s",
                        thread_id,
                        payload.actor.participant_id,
                    )
                    membership = Membership(
                        membership_id=uuid4(),
                        workspace_id=thread.workspace_id,
                        thread_id=thread_id,
                        participant_id=payload.actor.participant_id,
                        role="participant",
                        permissions=["post_messages"],
                        joined_at=now,
                    )
                    await self._repository.upsert_membership(conn, membership)
                else:
                    logger.debug(
                        "Kernel post_message reusing active membership membership_id=%s thread_id=%s participant_id=%s",
                        membership.membership_id,
                        thread_id,
                        payload.actor.participant_id,
                    )
                message.sequence = await self._repository.next_thread_sequence(conn, thread_id)
                await self._repository.upsert_message(conn, message)
                events = [
                    EventEnvelope(
                        event_type="message.created",
                        workspace_id=thread.workspace_id,
                        thread_id=thread_id,
                        actor=actor,
                        target=TargetRef(type="message", id=message.message_id),
                        visibility=payload.visibility,
                        correlation_id=message.correlation_id,
                        sequence=message.sequence,
                        timestamp=now,
                        payload=message.model_dump(mode="json"),
                    )
                ]
                if tool_generation_request is not None:
                    tool_generation_request = tool_generation_request.model_copy(
                        update={"requester_message_id": message.message_id}
                    )
                    await self._repository.upsert_tool_generation_request(
                        conn,
                        tool_generation_request,
                    )
                    events.append(
                        await self._build_thread_event(
                            conn,
                            thread.workspace_id,
                            thread_id,
                            "tool_generation_request.created",
                            actor=actor,
                            target=TargetRef(
                                type="tool_generation_request",
                                id=tool_generation_request.request_id,
                            ),
                            visibility=payload.visibility,
                            payload=tool_generation_request.model_dump(mode="json"),
                            timestamp=now,
                        )
                    )
                if payload.create_task:
                    for task in await self._build_message_tasks(
                        thread=thread,
                        message=message,
                        actor_input=payload.actor,
                        visibility=payload.visibility,
                        timestamp=now,
                    ):
                        await self._repository.upsert_task(conn, task)
                        events.append(
                            EventEnvelope(
                                event_type="task.created",
                                workspace_id=thread.workspace_id,
                                thread_id=thread_id,
                                actor=actor,
                                target=TargetRef(type="task", id=task.task_id),
                                visibility="agents_only",
                                correlation_id=correlation_id,
                                causation_id=message.message_id,
                                sequence=await self._repository.next_thread_sequence(
                                    conn,
                                    thread_id,
                                ),
                                timestamp=now,
                                payload=task.model_dump(mode="json"),
                            )
                        )

                if payload.requests:
                    interaction_result = await self._create_interaction_requests_in_transaction(
                        conn,
                        thread=thread,
                        actor_input=payload.actor,
                        requests=payload.requests,
                        timestamp=now,
                        correlation_id=correlation_id,
                        requester_message=message,
                    )
                    for rendered_message in interaction_result.messages:
                        await self._repository.upsert_message(conn, rendered_message)
                        events.append(
                            EventEnvelope(
                                event_type="message.created",
                                workspace_id=rendered_message.workspace_id,
                                thread_id=rendered_message.thread_id,
                                actor=rendered_message.actor,
                                target=TargetRef(type="message", id=rendered_message.message_id),
                                visibility=rendered_message.visibility,
                                correlation_id=rendered_message.correlation_id,
                                causation_id=rendered_message.causation_id,
                                sequence=rendered_message.sequence,
                                timestamp=now,
                                payload=rendered_message.model_dump(mode="json"),
                            )
                        )
                    events.extend(interaction_result.events)

                for event in events:
                    await self._repository.record_event(conn, event)

        persisted_messages = [message]
        if payload.requests:
            persisted_messages.extend(interaction_result.messages)
        await self._persist_workspace_communication_messages(persisted_messages)

        logger.debug(
            "Kernel post_message complete thread_id=%s message_id=%s event_count=%s final_sequence=%s",
            thread_id,
            message.message_id,
            len(events),
            message.sequence,
        )
        return MessageCommandResult(message=message, events=events)

    async def list_interaction_requests(
        self,
        thread_id: UUID,
    ) -> list[InteractionRequestDetail]:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        return await self._repository.list_interaction_request_details_for_thread(thread_id)

    async def get_interaction_request(
        self,
        request_id: UUID,
    ) -> InteractionRequestDetail:
        detail = await self._repository.get_interaction_request_detail(request_id)
        if detail is None:
            raise KeyError(f"Interaction request {request_id} not found")
        return detail

    async def list_tool_generation_requests(
        self,
        *,
        organization_id: UUID | None = None,
        workspace_id: UUID | None = None,
        thread_id: UUID | None = None,
        status: str | None = None,
    ) -> list[ToolGenerationRequestDetail]:
        requests = await self._repository.list_tool_generation_requests(
            organization_id=organization_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            status=status,
        )
        details: list[ToolGenerationRequestDetail] = []
        for request in requests:
            details.append(await self._tool_generation_request_detail(request.request_id))
        return details

    async def list_thread_tool_generation_requests(
        self,
        thread_id: UUID,
    ) -> list[ToolGenerationRequestDetail]:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        return await self.list_tool_generation_requests(thread_id=thread_id)

    async def get_tool_generation_request(
        self,
        request_id: UUID,
    ) -> ToolGenerationRequestDetail:
        return await self._tool_generation_request_detail(request_id)

    async def create_tool_generation_revision(
        self,
        request_id: UUID,
        payload: CreateToolGenerationRevisionRequest,
    ) -> ToolGenerationRequestCommandResult:
        request = await self._repository.fetch_tool_generation_request(request_id)
        if request is None:
            raise KeyError(f"Tool generation request {request_id} not found")
        if request.final_tool_id is not None or request.status == "published":
            raise ValueError("Tool generation requests that already published a tool cannot be revised")
        now = self._now()
        manifest = self._normalize_generated_tool_manifest(payload.manifest)
        revision = ToolGenerationRevision(
            revision_id=uuid4(),
            request_id=request_id,
            revision_number=1,
            status=payload.status,
            manifest=manifest,
            validation_report=payload.validation_report,
            source_asset_id=payload.source_asset_id,
            source_asset_version_id=payload.source_asset_version_id,
            manifest_asset_id=payload.manifest_asset_id,
            manifest_asset_version_id=payload.manifest_asset_version_id,
            report_asset_id=payload.report_asset_id,
            report_asset_version_id=payload.report_asset_version_id,
            image_ref=payload.image_ref,
            image_digest=payload.image_digest,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        updated_request = request.model_copy(
            update={
                "status": payload.status,
                "target_tool_name": manifest.name,
                "summary": manifest.description,
                "latest_revision_id": revision.revision_id,
                "rejected_by": None,
                "rejected_at": None,
                "updated_at": now,
            }
        )
        status_message: TimelineMessage | None = None
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                revision_number = await self._repository.next_tool_generation_revision_number(
                    conn,
                    request_id,
                )
                revision = revision.model_copy(update={"revision_number": revision_number})
                await self._repository.upsert_tool_generation_revision(conn, revision)
                await self._repository.upsert_tool_generation_request(conn, updated_request)
                events.append(
                    await self._build_thread_event(
                        conn,
                        request.workspace_id,
                        request.thread_id,
                        "tool_generation_revision.created",
                        actor=self._actor_from_input(payload.actor),
                        target=TargetRef(
                            type="tool_generation_revision",
                            id=revision.revision_id,
                        ),
                        visibility="workspace",
                        payload=revision.model_dump(mode="json"),
                        timestamp=now,
                    )
                )
                if payload.status == "pending_approval":
                    status_message, message_event = await self._create_tool_generation_status_message(
                        conn,
                        request=updated_request,
                        revision=revision,
                        status="pending_approval",
                        content=self._tool_generation_pending_approval_message(
                            updated_request,
                            revision,
                        ),
                        timestamp=now,
                    )
                    if message_event is not None:
                        events.append(message_event)
        if status_message is not None:
            await self._persist_workspace_communication_messages([status_message])
        detail = await self._tool_generation_request_detail(request_id)
        return ToolGenerationRequestCommandResult(
            detail=detail,
            revision=revision,
            message=status_message,
            events=events,
        )

    async def approve_tool_generation_revision(
        self,
        revision_id: UUID,
        payload: ReviewToolGenerationRevisionRequest,
    ) -> ToolGenerationRequestCommandResult:
        revision = await self._repository.fetch_tool_generation_revision(revision_id)
        if revision is None:
            raise KeyError(f"Tool generation revision {revision_id} not found")
        request = await self._repository.fetch_tool_generation_request(revision.request_id)
        if request is None:
            raise KeyError(
                f"Tool generation request {revision.request_id} not found for revision {revision_id}"
            )
        if request.final_tool_id is not None or request.status == "published":
            raise ValueError("This tool-generation request has already been published")
        if revision.status != "pending_approval":
            raise ValueError("Only revisions pending approval can be approved")
        now = self._now()
        manifest = self._normalize_generated_tool_manifest(revision.manifest)
        execution = manifest.execution.model_copy(
            update={"handler_ref": manifest.execution.handler_ref or manifest.name}
        )
        tool_scope = request.requested_scope
        tool = SystemToolDefinition(
            tool_id=uuid4(),
            scope=tool_scope,
            organization_id=(request.organization_id if tool_scope == "organization" else None),
            name=manifest.name,
            description=manifest.description,
            parameter_contract=manifest.parameter_contract,
            input_schema=manifest.input_schema,
            execution=execution,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata={
                **manifest.metadata,
                "generated": True,
                "tool_generation_request_id": str(request.request_id),
                "tool_generation_revision_id": str(revision.revision_id),
                "tool_generation_requested_scope": tool_scope,
                **(
                    {"image_ref": revision.image_ref}
                    if revision.image_ref is not None
                    else {}
                ),
                **(
                    {"image_digest": revision.image_digest}
                    if revision.image_digest is not None
                    else {}
                ),
            },
        )
        approved_revision = revision.model_copy(update={"status": "approved", "updated_at": now})
        published_request = request.model_copy(
            update={
                "status": "published",
                "target_tool_name": manifest.name,
                "summary": manifest.description,
                "final_tool_id": tool.tool_id,
                "latest_revision_id": revision.revision_id,
                "approved_by": payload.actor.participant_id,
                "approved_at": now,
                "published_at": now,
                "rejected_by": None,
                "rejected_at": None,
                "updated_at": now,
            }
        )
        status_message: TimelineMessage | None = None
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_system_tool(conn, tool)
                await self._repository.upsert_tool_generation_revision(conn, approved_revision)
                await self._repository.upsert_tool_generation_request(conn, published_request)
                await self._link_generated_tool_assets(
                    conn,
                    request=published_request,
                    revision=approved_revision,
                    tool=tool,
                    actor_id=payload.actor.participant_id,
                    timestamp=now,
                )
                status_message, message_event = await self._create_tool_generation_status_message(
                    conn,
                    request=published_request,
                    revision=approved_revision,
                    status="published",
                    content=self._tool_generation_published_message(tool, approved_revision),
                    timestamp=now,
                )
                if message_event is not None:
                    events.append(message_event)
        if status_message is not None:
            await self._persist_workspace_communication_messages([status_message])
        detail = await self._tool_generation_request_detail(request.request_id)
        return ToolGenerationRequestCommandResult(
            detail=detail,
            revision=approved_revision,
            message=status_message,
            events=events,
        )

    async def reject_tool_generation_revision(
        self,
        revision_id: UUID,
        payload: ReviewToolGenerationRevisionRequest,
    ) -> ToolGenerationRequestCommandResult:
        revision = await self._repository.fetch_tool_generation_revision(revision_id)
        if revision is None:
            raise KeyError(f"Tool generation revision {revision_id} not found")
        request = await self._repository.fetch_tool_generation_request(revision.request_id)
        if request is None:
            raise KeyError(
                f"Tool generation request {revision.request_id} not found for revision {revision_id}"
            )
        if request.status == "published":
            raise ValueError("Published tool-generation requests cannot be rejected")
        now = self._now()
        rejected_revision = revision.model_copy(update={"status": "rejected", "updated_at": now})
        rejected_request = request.model_copy(
            update={
                "status": "rejected",
                "rejected_by": payload.actor.participant_id,
                "rejected_at": now,
                "updated_at": now,
            }
        )
        status_message: TimelineMessage | None = None
        events: list[EventEnvelope] = []
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_tool_generation_revision(conn, rejected_revision)
                await self._repository.upsert_tool_generation_request(conn, rejected_request)
                status_message, message_event = await self._create_tool_generation_status_message(
                    conn,
                    request=rejected_request,
                    revision=rejected_revision,
                    status="rejected",
                    content=self._tool_generation_rejected_message(payload.reason),
                    timestamp=now,
                )
                if message_event is not None:
                    events.append(message_event)
        if status_message is not None:
            await self._persist_workspace_communication_messages([status_message])
        detail = await self._tool_generation_request_detail(request.request_id)
        return ToolGenerationRequestCommandResult(
            detail=detail,
            revision=rejected_revision,
            message=status_message,
            events=events,
        )

    async def create_interaction_requests(
        self,
        thread_id: UUID,
        payload: CreateInteractionRequestsRequest,
    ) -> InteractionRequestCommandResult:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        now = self._now()
        correlation_id = uuid4()
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                result = await self._create_interaction_requests_in_transaction(
                    conn,
                    thread=thread,
                    actor_input=payload.actor,
                    requests=payload.requests,
                    timestamp=now,
                    correlation_id=correlation_id,
                    requester_message=None,
                )
                for rendered_message in result.messages:
                    await self._repository.upsert_message(conn, rendered_message)
                    result.events.append(
                        EventEnvelope(
                            event_type="message.created",
                            workspace_id=rendered_message.workspace_id,
                            thread_id=rendered_message.thread_id,
                            actor=rendered_message.actor,
                            target=TargetRef(type="message", id=rendered_message.message_id),
                            visibility=rendered_message.visibility,
                            correlation_id=rendered_message.correlation_id,
                            causation_id=rendered_message.causation_id,
                            sequence=rendered_message.sequence,
                            timestamp=now,
                            payload=rendered_message.model_dump(mode="json"),
                        )
                    )
                for event in result.events:
                    await self._repository.record_event(conn, event)
        await self._persist_workspace_communication_messages(result.messages)
        return result

    async def update_interaction_request(
        self,
        request_id: UUID,
        payload: UpdateInteractionRequestRequest,
    ) -> InteractionRequestCommandResult:
        existing = await self._repository.get_interaction_request_detail(request_id)
        if existing is None:
            raise KeyError(f"Interaction request {request_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._repository.fetch_participant(
            existing.request.workspace_id,
            payload.actor.participant_id,
        )
        if participant is None:
            participant = await self._participant_profile_for_actor(
                workspace_id=existing.request.workspace_id,
                actor=payload.actor,
                now=now,
            )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                detail = await self._repository.get_interaction_request_detail(request_id)
                assert detail is not None
                request = detail.request
                events: list[EventEnvelope] = []
                resumed_task: Task | None = None

                if payload.action == "cancel":
                    request = request.model_copy(
                        update={
                            "status": "cancelled",
                            "updated_at": now,
                            "metadata": {**request.metadata, **payload.metadata},
                        }
                    )
                    await self._repository.upsert_interaction_request(conn, request)
                    events.append(
                        await self._build_thread_event(
                            conn,
                            request.workspace_id,
                            request.thread_id,
                            "interaction_request.cancelled",
                            actor=actor,
                            target=TargetRef(type="interaction_request", id=request.request_id),
                            visibility="workspace",
                            payload={"request_id": str(request.request_id)},
                            timestamp=now,
                        )
                    )
                elif payload.action == "timeout":
                    request = request.model_copy(
                        update={
                            "status": "timed_out",
                            "updated_at": now,
                            "metadata": {**request.metadata, **payload.metadata},
                        }
                    )
                    await self._repository.upsert_interaction_request(conn, request)
                    events.append(
                        await self._build_thread_event(
                            conn,
                            request.workspace_id,
                            request.thread_id,
                            "interaction_request.timed_out",
                            actor=actor,
                            target=TargetRef(type="interaction_request", id=request.request_id),
                            visibility="workspace",
                            payload={"request_id": str(request.request_id)},
                            timestamp=now,
                        )
                    )
                else:
                    if payload.target_id is None:
                        raise ValueError("target_id is required for target actions")
                    target = await self._repository.fetch_interaction_request_target(payload.target_id)
                    if target is None or target.request_id != request_id:
                        raise KeyError(f"Interaction request target {payload.target_id} not found")
                    updated_target = target.model_copy(
                        update={
                            "status": (
                                "acknowledged"
                                if payload.action == "acknowledge_target"
                                else "dismissed"
                            ),
                            "updated_at": now,
                            "metadata": {**target.metadata, **payload.metadata},
                        }
                    )
                    await self._repository.upsert_interaction_request_target(conn, updated_target)
                    detail = await self._repository.get_interaction_request_detail(request_id)
                    assert detail is not None
                    request = detail.request
                    aggregate, completed = await self._interaction_request_aggregate_state(detail)
                    request = request.model_copy(
                        update={
                            "status": "completed" if completed else request.status,
                            "completed_at": now if completed else request.completed_at,
                            "updated_at": now,
                            "metadata": {**request.metadata, "aggregate": aggregate},
                        }
                    )
                    await self._repository.upsert_interaction_request(conn, request)
                    events.append(
                        await self._build_thread_event(
                            conn,
                            request.workspace_id,
                            request.thread_id,
                            (
                                "interaction_request.target_acknowledged"
                                if payload.action == "acknowledge_target"
                                else "interaction_request.target_dismissed"
                            ),
                            actor=actor,
                            target=TargetRef(type="interaction_request_target", id=updated_target.target_id),
                            visibility="workspace",
                            payload={
                                "request_id": str(request.request_id),
                                "target_id": str(updated_target.target_id),
                                "status": updated_target.status,
                            },
                            timestamp=now,
                        )
                    )
                    if completed:
                        resumed_task = await self._create_interaction_request_followup_task(
                            conn,
                            request=request,
                            detail=detail.model_copy(update={"request": request}),
                            answer_message=None,
                            timestamp=now,
                        )
                        if resumed_task is not None:
                            events.append(
                                EventEnvelope(
                                    event_type="task.created",
                                    workspace_id=resumed_task.workspace_id,
                                    thread_id=resumed_task.thread_id,
                                    actor=actor,
                                    target=TargetRef(type="task", id=resumed_task.task_id),
                                    visibility="agents_only",
                                    correlation_id=resumed_task.correlation_id,
                                    causation_id=request.request_id,
                                    sequence=await self._repository.next_thread_sequence(conn, resumed_task.thread_id),
                                    timestamp=now,
                                    payload=resumed_task.model_dump(mode="json"),
                                )
                            )
                for event in events:
                    await self._repository.record_event(conn, event)
        return InteractionRequestCommandResult(
            detail=await self.get_interaction_request(request_id),
            events=events,
            resumed_task=resumed_task,
        )

    async def answer_interaction_request(
        self,
        request_id: UUID,
        payload: CreateInteractionAnswerRequest,
    ) -> InteractionRequestCommandResult:
        detail = await self._repository.get_interaction_request_detail(request_id)
        if detail is None:
            raise KeyError(f"Interaction request {request_id} not found")
        if detail.request.status != "open":
            raise ValueError("Only open interaction requests can be answered")
        thread = await self._repository.fetch_thread(detail.request.thread_id)
        if thread is None:
            raise KeyError(f"Thread {detail.request.thread_id} not found")
        if payload.question_ids:
            valid_question_ids = {question.question_id for question in detail.questions}
            invalid = [question_id for question_id in payload.question_ids if question_id not in valid_question_ids]
            if invalid:
                raise ValueError(f"Unknown interaction question ids: {invalid}")
        if detail.targets:
            if payload.actor.participant_id not in {
                target.participant_id for target in detail.targets if target.participant_id is not None
            }:
                raise PermissionError("Only a targeted participant can answer this request")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._repository.fetch_participant(
            thread.workspace_id,
            payload.actor.participant_id,
        )
        if participant is None:
            participant = await self._participant_profile_for_actor(
                workspace_id=thread.workspace_id,
                actor=payload.actor,
                now=now,
            )
        correlation_id = detail.request.requester_message_id or uuid4()
        answer_message = TimelineMessage(
            message_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread.thread_id,
            actor=actor,
            visibility="workspace",
            content=payload.content,
            status="completed",
            correlation_id=detail.request.requester_message_id or uuid4(),
            causation_id=detail.request.request_id,
            sequence=0,
            created_at=now,
            updated_at=now,
            metadata={
                **payload.metadata,
                "interaction_request_id": str(detail.request.request_id),
                "interaction_question_ids": [str(question_id) for question_id in payload.question_ids],
            },
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                membership = await self._repository.fetch_active_membership(
                    conn,
                    thread_id=thread.thread_id,
                    participant_id=payload.actor.participant_id,
                )
                if membership is None:
                    membership = Membership(
                        membership_id=uuid4(),
                        workspace_id=thread.workspace_id,
                        thread_id=thread.thread_id,
                        participant_id=payload.actor.participant_id,
                        role="participant",
                        permissions=["post_messages"],
                        joined_at=now,
                    )
                    await self._repository.upsert_membership(conn, membership)
                answer_message.sequence = await self._repository.next_thread_sequence(conn, thread.thread_id)
                await self._repository.upsert_message(conn, answer_message)
                answer = InteractionAnswer(
                    answer_id=uuid4(),
                    request_id=request_id,
                    participant_id=payload.actor.participant_id,
                    message_id=answer_message.message_id,
                    question_ids=list(payload.question_ids),
                    created_at=now,
                    metadata=payload.metadata,
                )
                await self._repository.upsert_interaction_answer(conn, answer)
                target = next(
                    (
                        item
                        for item in detail.targets
                        if item.participant_id == payload.actor.participant_id
                    ),
                    None,
                )
                if target is not None:
                    updated_target = target.model_copy(
                        update={
                            "status": "answered",
                            "answered_message_id": answer_message.message_id,
                            "updated_at": now,
                        }
                    )
                    await self._repository.upsert_interaction_request_target(conn, updated_target)
                refreshed = await self._repository.get_interaction_request_detail(request_id)
                assert refreshed is not None
                aggregate, completed = await self._interaction_request_aggregate_state(refreshed)
                updated_request = refreshed.request.model_copy(
                    update={
                        "status": "completed" if completed else refreshed.request.status,
                        "completed_at": now if completed else refreshed.request.completed_at,
                        "updated_at": now,
                        "metadata": {**refreshed.request.metadata, "aggregate": aggregate},
                    }
                )
                await self._repository.upsert_interaction_request(conn, updated_request)
                events = [
                    EventEnvelope(
                        event_type="message.created",
                        workspace_id=answer_message.workspace_id,
                        thread_id=answer_message.thread_id,
                        actor=answer_message.actor,
                        target=TargetRef(type="message", id=answer_message.message_id),
                        visibility=answer_message.visibility,
                        correlation_id=answer_message.correlation_id,
                        causation_id=answer_message.causation_id,
                        sequence=answer_message.sequence,
                        timestamp=now,
                        payload=answer_message.model_dump(mode="json"),
                    ),
                    await self._build_thread_event(
                        conn,
                        updated_request.workspace_id,
                        updated_request.thread_id,
                        "interaction_request.answered",
                        actor=actor,
                        target=TargetRef(type="message", id=answer_message.message_id),
                        visibility="workspace",
                        payload={
                            "request_id": str(updated_request.request_id),
                            "answer_id": str(answer.answer_id),
                            "participant_id": str(answer.participant_id),
                            "completed": completed,
                        },
                        timestamp=now,
                        correlation_id=answer_message.correlation_id,
                        causation_id=updated_request.request_id,
                    ),
                ]
                resumed_task: Task | None = None
                if completed:
                    resumed_task = await self._create_interaction_request_followup_task(
                        conn,
                        request=updated_request,
                        detail=refreshed.model_copy(update={"request": updated_request}),
                        answer_message=answer_message,
                        timestamp=now,
                    )
                    if resumed_task is not None:
                        events.append(
                            EventEnvelope(
                                event_type="task.created",
                                workspace_id=resumed_task.workspace_id,
                                thread_id=resumed_task.thread_id,
                                actor=ActorRef(type=payload.actor.participant_type, id=payload.actor.participant_id),
                                target=TargetRef(type="task", id=resumed_task.task_id),
                                visibility="agents_only",
                                correlation_id=resumed_task.correlation_id,
                                causation_id=updated_request.request_id,
                                sequence=await self._repository.next_thread_sequence(conn, resumed_task.thread_id),
                                timestamp=now,
                                payload=resumed_task.model_dump(mode="json"),
                            )
                        )
                for event in events:
                    await self._repository.record_event(conn, event)
        await self._persist_workspace_communication_messages([answer_message])
        return InteractionRequestCommandResult(
            detail=await self.get_interaction_request(request_id),
            events=events,
            answer_message=answer_message,
            resumed_task=resumed_task,
        )

    async def list_memory_entries(self, workspace_id: UUID) -> list[MemoryEntry]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return await self._repository.list_memory_entries_for_scope(
            scope="workspace",
            workspace_id=workspace_id,
            state="confirmed",
        )

    async def list_thread_memory_entries(self, thread_id: UUID) -> list[MemoryEntry]:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        return await self._repository.list_memory_entries_for_scope(
            scope="thread",
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            state="confirmed",
        )

    async def create_memory_entry(
        self, workspace_id: UUID, payload: CreateMemoryEntryRequest
    ) -> MemoryCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        )
        entry = MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            thread_id=None,
            run_id=None,
            entry_type=payload.entry_type,
            content=payload.content,
            summary=payload.summary,
            source="manual",
            created_by=payload.actor.participant_id,
            updated_by=payload.actor.participant_id,
            confirmed_by=payload.actor.participant_id,
            confirmed_at=now,
            visibility=payload.visibility,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, entry)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.memory_entry_created",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=entry.memory_entry_id),
                    visibility=entry.visibility,
                    payload=entry.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._sync_memory_entry(entry)
        return MemoryCommandResult(entry=entry, events=[event])

    async def create_thread_memory_entry(
        self, thread_id: UUID, payload: CreateThreadMemoryRequest
    ) -> MemoryCommandResult:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=payload.actor,
            now=now,
        )
        entry = MemoryEntry(
            memory_entry_id=uuid4(),
            scope="thread",
            state="confirmed",
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            run_id=None,
            entry_type=payload.entry_type,
            content=payload.content,
            summary=payload.summary,
            source="manual",
            created_by=payload.actor.participant_id,
            updated_by=payload.actor.participant_id,
            confirmed_by=payload.actor.participant_id,
            confirmed_at=now,
            visibility=payload.visibility,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, entry)
                event = await self._build_thread_event(
                    conn,
                    thread.workspace_id,
                    thread_id,
                    "thread.memory_entry_created",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=entry.memory_entry_id),
                    visibility=entry.visibility,
                    payload=entry.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._sync_memory_entry(entry)
        return MemoryCommandResult(entry=entry, events=[event])

    async def confirm_workspace_memory(
        self,
        workspace_id: UUID,
        payload: ConfirmWorkspaceMemoryRequest,
    ) -> MemoryCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        source_entry = await self._repository.fetch_memory_entry(payload.source_memory_entry_id)
        if source_entry is None or source_entry.workspace_id != workspace_id:
            raise KeyError(f"Memory entry {payload.source_memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        )
        entry = MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            thread_id=None,
            run_id=None,
            entry_type=payload.entry_type or source_entry.entry_type,
            content=payload.content or source_entry.content,
            summary=payload.summary if payload.summary is not None else source_entry.summary,
            source=f"confirmed:{source_entry.scope}:{source_entry.memory_entry_id}",
            created_by=payload.actor.participant_id,
            updated_by=payload.actor.participant_id,
            confirmed_by=payload.actor.participant_id,
            confirmed_at=now,
            visibility=payload.visibility,
            metadata={
                **dict(source_entry.metadata),
                **payload.metadata,
                "source_memory_entry_id": str(source_entry.memory_entry_id),
            },
            created_at=now,
            updated_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, entry)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.memory_entry_confirmed",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=entry.memory_entry_id),
                    visibility=entry.visibility,
                    payload=entry.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._sync_memory_entry(entry)
        return MemoryCommandResult(entry=entry, events=[event])

    async def update_memory_entry(
        self, workspace_id: UUID, memory_entry_id: UUID, payload: UpdateMemoryEntryRequest
    ) -> MemoryCommandResult:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        existing = await self._repository.fetch_memory_entry(memory_entry_id)
        if (
            existing is None
            or existing.workspace_id != workspace_id
            or existing.scope != "workspace"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=workspace_id,
            actor=payload.actor,
            now=now,
        )
        updated = existing.model_copy(
            update={
                "content": payload.content if payload.content is not None else existing.content,
                "summary": payload.summary if payload.summary is not None else existing.summary,
                "visibility": payload.visibility if payload.visibility is not None else existing.visibility,
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": now,
                "version": existing.version + 1,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, updated)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.memory_entry_updated",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=updated.memory_entry_id),
                    visibility=updated.visibility,
                    payload=updated.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._sync_memory_entry(updated)
        return MemoryCommandResult(entry=updated, events=[event])

    async def update_thread_memory_entry(
        self, thread_id: UUID, memory_entry_id: UUID, payload: UpdateMemoryEntryRequest
    ) -> MemoryCommandResult:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        existing = await self._repository.fetch_memory_entry(memory_entry_id)
        if (
            existing is None
            or existing.workspace_id != thread.workspace_id
            or existing.thread_id != thread_id
            or existing.scope != "thread"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(payload.actor)
        participant = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=payload.actor,
            now=now,
        )
        updated = existing.model_copy(
            update={
                "content": payload.content if payload.content is not None else existing.content,
                "summary": payload.summary if payload.summary is not None else existing.summary,
                "visibility": payload.visibility if payload.visibility is not None else existing.visibility,
                "metadata": (
                    {**existing.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else existing.metadata
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": now,
                "version": existing.version + 1,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, updated)
                event = await self._build_thread_event(
                    conn,
                    thread.workspace_id,
                    thread_id,
                    "thread.memory_entry_updated",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=updated.memory_entry_id),
                    visibility=updated.visibility,
                    payload=updated.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._sync_memory_entry(updated)
        return MemoryCommandResult(entry=updated, events=[event])

    async def delete_memory_entry(
        self, workspace_id: UUID, memory_entry_id: UUID, actor_input: ParticipantInput
    ) -> list[EventEnvelope]:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        existing = await self._repository.fetch_memory_entry(memory_entry_id)
        if (
            existing is None
            or existing.workspace_id != workspace_id
            or existing.scope != "workspace"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(actor_input)
        participant = await self._participant_profile_for_actor(
            workspace_id=workspace_id,
            actor=actor_input,
            now=now,
        )
        archived = existing.model_copy(
            update={
                "state": "archived",
                "updated_by": actor_input.participant_id,
                "updated_at": now,
                "version": existing.version + 1,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, archived)
                event = await self._build_workspace_event(
                    conn,
                    workspace_id,
                    "workspace.memory_entry_deleted",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=memory_entry_id),
                    visibility=existing.visibility,
                    payload={"memory_entry_id": str(memory_entry_id)},
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._delete_memory_entry_from_providers(existing)
        return [event]

    async def delete_thread_memory_entry(
        self, thread_id: UUID, memory_entry_id: UUID, actor_input: ParticipantInput
    ) -> list[EventEnvelope]:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        existing = await self._repository.fetch_memory_entry(memory_entry_id)
        if (
            existing is None
            or existing.workspace_id != thread.workspace_id
            or existing.thread_id != thread_id
            or existing.scope != "thread"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        now = self._now()
        actor = self._actor_from_input(actor_input)
        participant = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=actor_input,
            now=now,
        )
        archived = existing.model_copy(
            update={
                "state": "archived",
                "updated_by": actor_input.participant_id,
                "updated_at": now,
                "version": existing.version + 1,
            }
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, archived)
                event = await self._build_thread_event(
                    conn,
                    thread.workspace_id,
                    thread_id,
                    "thread.memory_entry_deleted",
                    actor=actor,
                    target=TargetRef(type="memory_entry", id=memory_entry_id),
                    visibility=existing.visibility,
                    payload={"memory_entry_id": str(memory_entry_id)},
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        await self._delete_memory_entry_from_providers(existing)
        return [event]

    async def search_thread_memory(
        self,
        thread_id: UUID,
        payload: SearchMemoryRequest,
    ) -> MemorySearchResponse:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        workspace = await self._repository.fetch_workspace(thread.workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {thread.workspace_id} not found")
        provider_definition = await self._resolve_search_memory_provider(
            payload.use_provider,
            organization_id=workspace.organization_id,
        )
        provider = self._memory_provider_index.get(provider_definition.provider)
        if provider is None:
            raise ValueError(f"Unsupported memory provider {provider_definition.provider!r}")
        viewer = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=payload.actor,
            now=self._now(),
        )
        raw_results = await provider.search(
            provider_definition,
            scope="thread",
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            run_id=None,
            query=payload.query,
            limit=payload.limit,
            include_graph=payload.include_graph,
            metadata_filters=payload.metadata_filters,
        )
        hits: list[MemorySearchHit] = []
        for hit in raw_results.hits:
            if hit.memory_entry_id is None:
                continue
            entry = await self._repository.fetch_memory_entry(hit.memory_entry_id)
            if entry is None or entry.state == "archived":
                continue
            if not self._filter_visible_memory_entries([entry], viewer=viewer):
                continue
            hits.append(
                MemorySearchHit(
                    entry=entry,
                    score=hit.score,
                    relations=hit.relations,
                    metadata=hit.metadata,
                )
            )
        return MemorySearchResponse(
            query=payload.query,
            provider=provider_definition.provider_key,
            results=hits,
            metadata=raw_results.metadata,
        )

    async def append_run_scratch(
        self,
        *,
        run_id: UUID,
        actor_input: ParticipantInput,
        entry_type: str,
        content: str,
        summary: str | None = None,
        metadata: dict[str, object] | None = None,
        visibility: str = "agents_only",
        source: str = "agent_runtime",
    ) -> MemoryEntry:
        run = await self._repository.fetch_run(run_id)
        if run is None:
            raise KeyError(f"Run {run_id} not found")
        now = self._now()
        participant = await self._participant_profile_for_actor(
            workspace_id=run.workspace_id,
            actor=actor_input,
            now=now,
        )
        entry = MemoryEntry(
            memory_entry_id=uuid4(),
            scope="run",
            state="scratch",
            workspace_id=run.workspace_id,
            thread_id=run.thread_id,
            run_id=run_id,
            entry_type=entry_type,
            content=content,
            summary=summary,
            source=source,
            created_by=actor_input.participant_id,
            updated_by=actor_input.participant_id,
            visibility=visibility,
            metadata=dict(metadata or {}),
            created_at=now,
            updated_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                await self._repository.upsert_memory_entry(conn, entry)
        await self._sync_memory_entry(entry)
        return entry

    async def publish_presence(
        self,
        *,
        thread_id: UUID,
        actor_input: ParticipantInput,
        status: str,
        connection_id: str | None = None,
    ) -> EventEnvelope:
        logger.debug(
            "Kernel publish_presence thread_id=%s participant_id=%s status=%s connection_id=%s",
            thread_id,
            actor_input.participant_id,
            status,
            connection_id,
        )
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        now = self._now()
        actor = self._actor_from_input(actor_input)
        participant = await self._participant_profile_for_actor(
            workspace_id=thread.workspace_id,
            actor=actor_input,
            now=now,
            status=status,
        )
        presence = PresenceState(
            participant_id=actor_input.participant_id,
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            status=status,
            connection_id=connection_id,
            last_seen_at=now,
        )
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._ensure_participant_identity(conn, participant)
                await self._repository.upsert_participant(conn, participant)
                if status == "offline":
                    await self._repository.close_active_membership(
                        conn,
                        thread_id=thread_id,
                        participant_id=actor_input.participant_id,
                        left_at=now,
                    )
                else:
                    membership = await self._repository.fetch_active_membership(
                        conn,
                        thread_id=thread_id,
                        participant_id=actor_input.participant_id,
                    )
                    if membership is None:
                        logger.debug(
                            "Kernel publish_presence creating membership thread_id=%s participant_id=%s",
                            thread_id,
                            actor_input.participant_id,
                        )
                        membership = Membership(
                            membership_id=uuid4(),
                            workspace_id=thread.workspace_id,
                            thread_id=thread_id,
                            participant_id=actor_input.participant_id,
                            role="participant",
                            permissions=["post_messages"],
                            joined_at=now,
                        )
                        await self._repository.upsert_membership(conn, membership)
                    else:
                        logger.debug(
                            "Kernel publish_presence reusing membership membership_id=%s thread_id=%s participant_id=%s",
                            membership.membership_id,
                            thread_id,
                            actor_input.participant_id,
                        )
                event = await self._build_thread_event(
                    conn,
                    thread.workspace_id,
                    thread_id,
                    "presence.updated",
                    actor=actor,
                    target=TargetRef(type="participant", id=actor_input.participant_id),
                    visibility="workspace",
                    payload=presence.model_dump(mode="json"),
                    timestamp=now,
                )
                await self._repository.record_event(conn, event)
        logger.debug(
            "Kernel publish_presence complete thread_id=%s participant_id=%s sequence=%s",
            thread_id,
            actor_input.participant_id,
            event.sequence,
        )
        return event

    async def list_thread_events(
        self, thread_id: UUID, *, after_sequence: int | None = None
    ) -> list[EventEnvelope]:
        thread = await self._repository.fetch_thread(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        return await self._repository.list_thread_events(
            thread_id, after_sequence=after_sequence
        )

    async def record_audit_event(self, draft: AuditEventDraft) -> AuditEvent:
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                return await self._repository.append_audit_event(conn, draft)

    async def get_audit_event(self, audit_event_id: UUID) -> AuditEvent | None:
        return await self._repository.get_audit_event(audit_event_id)

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
        occurred_after: datetime | None = None,
        occurred_before: datetime | None = None,
        limit: int = 100,
    ) -> AuditEventPage:
        return await self._repository.list_audit_events(
            organization_id=organization_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor_user_id=actor_user_id,
            actor_system_agent_id=actor_system_agent_id,
            action_prefix=action_prefix,
            outcome=outcome,
            target_type=target_type,
            target_id=target_id,
            correlation_id=correlation_id,
            request_id=request_id,
            occurred_after=occurred_after,
            occurred_before=occurred_before,
            limit=limit,
        )

    async def verify_audit_chain(
        self,
        chain_partition: str,
    ) -> AuditChainVerificationResult:
        return await self._repository.verify_audit_chain(chain_partition)

    async def _build_message_tasks(
        self,
        *,
        thread: Thread,
        message: TimelineMessage,
        actor_input: ParticipantInput,
        visibility: str,
        timestamp: datetime,
    ) -> list[Task]:
        participants = await self._repository.list_participants(thread.workspace_id)
        active_agents = [
            participant
            for participant in participants
            if participant.participant_type == "agent"
            and participant.status in {"active", "idle"}
            and participant.system_agent_id is not None
        ]
        target_system_agent_id = self._metadata_uuid(message.metadata, "target_system_agent_id")
        target_participant_id = self._metadata_uuid(message.metadata, "target_participant_id")
        tool_generation_request_id = self._metadata_uuid(
            message.metadata,
            "tool_generation_request_id",
        )
        if target_system_agent_id is not None:
            active_agents = [
                participant
                for participant in active_agents
                if participant.system_agent_id == target_system_agent_id
            ]
        if target_participant_id is not None:
            active_agents = [
                participant
                for participant in active_agents
                if participant.participant_id == target_participant_id
            ]
        tasks: list[Task] = []
        if not active_agents:
            tasks.append(
                Task(
                    task_id=uuid4(),
                    workspace_id=thread.workspace_id,
                    thread_id=thread.thread_id,
                    title=f"Respond to message {message.message_id}",
                    description="Agent response requested for posted message.",
                    requested_by=actor_input.participant_id,
                    correlation_id=message.correlation_id,
                    causation_id=message.message_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                    metadata={
                        "trigger_message_id": str(message.message_id),
                        "sequence_ceiling": message.sequence,
                        "response_visibility": self._response_visibility(visibility),
                        "routing_reason": "no_attached_agents",
                        **(
                            {
                                "tool_generation_request_id": str(tool_generation_request_id),
                                "tool_generation_request_status": message.metadata.get(
                                    "tool_generation_request_status",
                                ),
                            }
                            if tool_generation_request_id is not None
                            else {}
                        ),
                    },
                )
            )
            return tasks

        for participant in active_agents:
            tasks.append(
                Task(
                    task_id=uuid4(),
                    workspace_id=thread.workspace_id,
                    thread_id=thread.thread_id,
                    title=f"Reply as {participant.display_name}",
                    description="Agent response requested for posted message.",
                    requested_by=actor_input.participant_id,
                    correlation_id=message.correlation_id,
                    causation_id=message.message_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                    metadata={
                        "target_system_agent_id": str(participant.system_agent_id),
                        "target_participant_id": str(participant.participant_id),
                        "trigger_message_id": str(message.message_id),
                        "sequence_ceiling": message.sequence,
                        "response_visibility": self._response_visibility(visibility),
                        "routing_reason": "workspace_attached_agent",
                        **(
                            {
                                "tool_generation_request_id": str(tool_generation_request_id),
                                "tool_generation_request_status": message.metadata.get(
                                    "tool_generation_request_status",
                                ),
                            }
                            if tool_generation_request_id is not None
                            else {}
                        ),
                    },
                )
            )
        return tasks

    async def _build_tool_generation_request_for_message(
        self,
        *,
        thread: Thread,
        actor_input: ParticipantInput,
        participant: ParticipantProfile,
        content: str,
        metadata: dict[str, object],
        timestamp: datetime,
    ) -> ToolGenerationRequest | None:
        if actor_input.participant_type != "user":
            return None
        if metadata.get("tool_generation_request_id") is not None:
            return None
        target_system_agent_id = self._metadata_uuid(metadata, "target_system_agent_id")
        if target_system_agent_id is None:
            return None
        target_agent = await self._repository.fetch_system_agent(target_system_agent_id)
        if target_agent is None or not self._is_tool_generation_agent(target_agent):
            return None
        target_participant = await self._repository.fetch_agent_participant(
            thread.workspace_id,
            target_system_agent_id,
        )
        if target_participant is None or target_participant.status not in {"active", "idle", "busy"}:
            return None
        workspace = await self._repository.fetch_workspace(thread.workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {thread.workspace_id} not found")
        summary = content.strip()[:500] or None
        return ToolGenerationRequest(
            request_id=uuid4(),
            organization_id=workspace.organization_id,
            workspace_id=thread.workspace_id,
            thread_id=thread.thread_id,
            requester_participant_id=participant.participant_id,
            requester_message_id=None,
            target_system_agent_id=target_system_agent_id,
            requested_scope=self._tool_generation_requested_scope(metadata),
            status="submitted",
            target_tool_name=self._tool_generation_target_name(metadata, content),
            summary=summary,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "source": "targeted_message",
                "target_system_agent_id": str(target_system_agent_id),
                **dict(metadata),
            },
        )

    async def _tool_generation_request_detail(
        self,
        request_id: UUID,
    ) -> ToolGenerationRequestDetail:
        request = await self._repository.fetch_tool_generation_request(request_id)
        if request is None:
            raise KeyError(f"Tool generation request {request_id} not found")
        revisions = await self._repository.list_tool_generation_revisions(request_id)
        return ToolGenerationRequestDetail(request=request, revisions=revisions)

    @staticmethod
    def _is_tool_generation_agent(agent: AgentDefinition) -> bool:
        return bool(agent.metadata.get("tool_generation_agent")) or bool(
            agent.definition.get("tool_generation_agent")
        )

    @staticmethod
    def _tool_generation_target_name(
        metadata: dict[str, object],
        content: str,
    ) -> str | None:
        explicit = metadata.get("target_tool_name")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        stripped = content.strip()
        if not stripped:
            return None
        lowered = stripped.lower()
        marker = "tool "
        if marker in lowered:
            index = lowered.find(marker) + len(marker)
            candidate = stripped[index:].strip(" :.-")
            return candidate[:200] or None
        return None

    @staticmethod
    def _tool_generation_requested_scope(
        metadata: dict[str, object],
    ) -> str:
        value = metadata.get("target_tool_scope")
        if isinstance(value, str) and value in {"global", "organization"}:
            return value
        return "global"

    def _normalize_generated_tool_manifest(
        self,
        manifest: GeneratedToolManifest,
    ) -> GeneratedToolManifest:
        execution_profile = dict(manifest.execution.execution_profile)
        execution_profile["network"] = manifest.network_access
        execution_profile["workspace_access"] = manifest.workspace_access
        execution = manifest.execution.model_copy(update={"execution_profile": execution_profile})
        self._validate_tool_execution_binding(execution)
        return manifest.model_copy(update={"execution": execution})

    async def _link_generated_tool_assets(
        self,
        conn: asyncpg.Connection,
        *,
        request: ToolGenerationRequest,
        revision: ToolGenerationRevision,
        tool: SystemToolDefinition,
        actor_id: UUID,
        timestamp: datetime,
    ) -> None:
        for purpose, asset_id, asset_version_id in (
            ("generated_source", revision.source_asset_id, revision.source_asset_version_id),
            ("generated_manifest", revision.manifest_asset_id, revision.manifest_asset_version_id),
            ("generated_report", revision.report_asset_id, revision.report_asset_version_id),
        ):
            if asset_id is None or asset_version_id is None:
                continue
            await self._repository.deactivate_asset_links(
                conn,
                target_type="system_tool",
                target_id=tool.tool_id,
                purpose=purpose,
                organization_id=None,
                workspace_id=None,
            )
            await self._repository.upsert_asset_link(
                conn,
                AssetLink(
                    link_id=uuid4(),
                    asset_id=asset_id,
                    asset_version_id=asset_version_id,
                    organization_id=None,
                    workspace_id=None,
                    target_type="system_tool",
                    target_id=tool.tool_id,
                    purpose=purpose,
                    active=True,
                    created_by=actor_id,
                    created_at=timestamp,
                    updated_at=timestamp,
                    metadata={
                        "tool_generation_request_id": str(request.request_id),
                        "tool_generation_revision_id": str(revision.revision_id),
                    },
                ),
            )

    async def _create_tool_generation_status_message(
        self,
        conn: asyncpg.Connection,
        *,
        request: ToolGenerationRequest,
        revision: ToolGenerationRevision | None,
        status: str,
        content: str,
        timestamp: datetime,
    ) -> tuple[TimelineMessage | None, EventEnvelope | None]:
        participant = await self._repository.fetch_agent_participant(
            request.workspace_id,
            request.target_system_agent_id,
        )
        if participant is None:
            return None, None
        membership = await self._repository.fetch_active_membership(
            conn,
            thread_id=request.thread_id,
            participant_id=participant.participant_id,
        )
        if membership is None:
            await self._repository.upsert_membership(
                conn,
                Membership(
                    membership_id=uuid4(),
                    workspace_id=request.workspace_id,
                    thread_id=request.thread_id,
                    participant_id=participant.participant_id,
                    role="participant",
                    permissions=["post_messages"],
                    joined_at=timestamp,
                ),
            )
        message = TimelineMessage(
            message_id=uuid4(),
            workspace_id=request.workspace_id,
            thread_id=request.thread_id,
            actor=ActorRef(type="agent", id=participant.participant_id),
            visibility="workspace",
            content=content,
            status="completed",
            correlation_id=uuid4(),
            sequence=await self._repository.next_thread_sequence(conn, request.thread_id),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "tool_generation_request_id": str(request.request_id),
                "tool_generation_status": status,
                "tool_generation_request_status": request.status,
                **(
                    {"tool_generation_revision_id": str(revision.revision_id)}
                    if revision is not None
                    else {}
                ),
            },
        )
        await self._repository.upsert_message(conn, message)
        event = await self._build_thread_event(
            conn,
            request.workspace_id,
            request.thread_id,
            "message.created",
            actor=message.actor,
            target=TargetRef(type="message", id=message.message_id),
            visibility=message.visibility,
            payload=message.model_dump(mode="json"),
            timestamp=timestamp,
        )
        return message, event

    @staticmethod
    def _tool_generation_pending_approval_message(
        request: ToolGenerationRequest,
        revision: ToolGenerationRevision,
    ) -> str:
        lines = [
            f"Tinker prepared tool revision `{revision.manifest.name}` for platform approval.",
            f"Requested catalog scope: `{request.requested_scope}`.",
            f"Status: pending approval. Trust: `{revision.manifest.execution.trust_level}`. Network: `{revision.manifest.network_access}`. Workspace access: `{revision.manifest.workspace_access}`.",
        ]
        if revision.image_ref:
            lines.append(f"Image: `{revision.image_ref}`")
        if revision.image_digest:
            lines.append(f"Digest: `{revision.image_digest}`")
        if revision.validation_report and revision.validation_report.summary:
            lines.append(f"Validation: {revision.validation_report.summary}")
        return "\n".join(lines)

    @staticmethod
    def _tool_generation_published_message(
        tool: SystemToolDefinition,
        revision: ToolGenerationRevision,
    ) -> str:
        catalog_label = (
            "the organization system tools catalog"
            if tool.scope == "organization"
            else "the global system tools catalog"
        )
        lines = [
            f"Tool `{tool.name}` was approved and added to {catalog_label}.",
            "It is not attached to any workspace automatically. Workspace admins or supervisors can attach it when needed.",
        ]
        if revision.image_digest:
            lines.append(f"Published image digest: `{revision.image_digest}`")
        return "\n".join(lines)

    @staticmethod
    def _tool_generation_rejected_message(reason: str | None) -> str:
        if reason and reason.strip():
            return f"Tool-generation revision was rejected for this request.\nReason: {reason.strip()}"
        return "Tool-generation revision was rejected for this request."

    @staticmethod
    def _metadata_uuid(metadata: dict[str, object], key: str) -> UUID | None:
        value = metadata.get(key)
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    async def _create_interaction_requests_in_transaction(
        self,
        conn: asyncpg.Connection,
        *,
        thread: Thread,
        actor_input: ParticipantInput,
        requests: list[CreateInteractionRequest],
        timestamp: datetime,
        correlation_id: UUID,
        requester_message: TimelineMessage | None,
        requester_run: Run | None = None,
        requester_task: Task | None = None,
    ) -> InteractionRequestCommandResult:
        actor = self._actor_from_input(actor_input)
        requester = await self._repository.fetch_participant(
            thread.workspace_id,
            actor_input.participant_id,
        )
        if requester is None:
            requester = self._participant_profile(
                workspace_id=thread.workspace_id,
                actor=actor_input,
                now=timestamp,
            )
        await self._ensure_participant_identity(conn, requester)
        await self._repository.upsert_participant(conn, requester)
        details: list[InteractionRequestDetail] = []
        rendered_messages: list[TimelineMessage] = []
        events: list[EventEnvelope] = []
        for request_input in requests:
            detail, rendered_message, request_events = await self._create_interaction_request_in_transaction(
                conn,
                thread=thread,
                requester=requester,
                request_input=request_input,
                timestamp=timestamp,
                correlation_id=correlation_id,
                requester_message=requester_message,
                requester_run=requester_run,
                requester_task=requester_task,
            )
            details.append(detail)
            rendered_messages.append(rendered_message)
            events.extend(request_events)
        return InteractionRequestCommandResult(
            details=details,
            messages=rendered_messages,
            events=events,
        )

    async def _create_interaction_request_in_transaction(
        self,
        conn: asyncpg.Connection,
        *,
        thread: Thread,
        requester: ParticipantProfile,
        request_input: CreateInteractionRequest,
        timestamp: datetime,
        correlation_id: UUID,
        requester_message: TimelineMessage | None,
        requester_run: Run | None,
        requester_task: Task | None,
    ) -> tuple[InteractionRequestDetail, TimelineMessage, list[EventEnvelope]]:
        if not request_input.questions:
            raise ValueError("Interaction requests must include at least one question")
        resolved_targets = await self._resolve_interaction_request_targets(
            thread=thread,
            requester=requester,
            request_input=request_input,
        )
        completion_rule = self._normalize_completion_rule(
            request_input.completion_rule,
            resolved_targets=resolved_targets,
        )
        request = InteractionRequest(
            request_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread.thread_id,
            requester_participant_id=requester.participant_id,
            requester_message_id=(
                requester_message.message_id if requester_message is not None else None
            ),
            requester_run_id=requester_run.run_id if requester_run is not None else None,
            requester_task_id=requester_task.task_id if requester_task is not None else None,
            title=request_input.title,
            summary=request_input.summary,
            completion_rule=completion_rule,
            timeout_at=request_input.timeout_at,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                **request_input.metadata,
                "selectors": [
                    selector.model_dump(mode="json") for selector in request_input.selectors
                ],
                "input_target_participant_ids": [
                    str(participant_id)
                    for participant_id in request_input.target_participant_ids
                ],
            },
        )
        await self._repository.upsert_interaction_request(conn, request)
        questions: list[InteractionQuestion] = []
        for index, question_input in enumerate(request_input.questions):
            question = InteractionQuestion(
                question_id=uuid4(),
                request_id=request.request_id,
                prompt=question_input.prompt,
                kind=question_input.kind,
                expected_format=question_input.expected_format,
                order=index,
                metadata=question_input.metadata,
            )
            questions.append(question)
            await self._repository.upsert_interaction_request_question(conn, question)
        targets: list[InteractionRequestTarget] = []
        for resolved in resolved_targets:
            target = InteractionRequestTarget(
                target_id=uuid4(),
                request_id=request.request_id,
                participant_id=resolved["participant"].participant_id,
                selector_type=resolved["selector_type"],
                selector_value=resolved["selector_value"],
                selection_source=resolved["selection_source"],
                score=resolved["score"],
                created_at=timestamp,
                updated_at=timestamp,
                metadata=resolved["metadata"],
            )
            targets.append(target)
            await self._repository.upsert_interaction_request_target(conn, target)
        detail = InteractionRequestDetail(
            request=request,
            questions=questions,
            targets=targets,
            answers=[],
        )
        aggregate, completed = await self._interaction_request_aggregate_state(detail)
        if completed:
            request = request.model_copy(
                update={
                    "status": "completed",
                    "completed_at": timestamp,
                    "metadata": {**request.metadata, "aggregate": aggregate},
                }
            )
        else:
            request = request.model_copy(
                update={"metadata": {**request.metadata, "aggregate": aggregate}}
            )
        await self._repository.upsert_interaction_request(conn, request)
        detail = detail.model_copy(update={"request": request})
        rendered_message = TimelineMessage(
            message_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread.thread_id,
            actor=ActorRef(type=requester.participant_type, id=requester.participant_id),
            visibility="workspace",
            content=self._render_interaction_request_message(detail),
            status="completed",
            correlation_id=correlation_id,
            causation_id=request.request_id,
            sequence=await self._repository.next_thread_sequence(conn, thread.thread_id),
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "interaction_request_id": str(request.request_id),
                "interaction_request_status": request.status,
                "interaction_request_title": request.title,
                "interaction_target_count": len(targets),
                "interaction_questions": [
                    question.model_dump(mode="json") for question in questions
                ],
                "interaction_aggregate": aggregate,
            },
        )
        events = [
            await self._build_thread_event(
                conn,
                request.workspace_id,
                request.thread_id,
                "interaction_request.created",
                actor=ActorRef(type=requester.participant_type, id=requester.participant_id),
                target=TargetRef(type="interaction_request", id=request.request_id),
                visibility="workspace",
                payload={
                    "request": request.model_dump(mode="json"),
                    "questions": [question.model_dump(mode="json") for question in questions],
                    "targets": [target.model_dump(mode="json") for target in targets],
                },
                timestamp=timestamp,
                correlation_id=correlation_id,
                causation_id=request.request_id,
            )
        ]
        return detail, rendered_message, events

    async def _resolve_interaction_request_targets(
        self,
        *,
        thread: Thread,
        requester: ParticipantProfile,
        request_input: CreateInteractionRequest,
    ) -> list[dict[str, object]]:
        participants = await self._repository.list_participants(thread.workspace_id)
        memberships = await self._repository.list_memberships(thread.thread_id)
        active_member_ids = {
            membership.participant_id for membership in memberships if membership.left_at is None
        }
        desired_responder_types = list(
            request_input.metadata.get("desired_responder_types", [])
        )
        if not desired_responder_types:
            desired_responder_types = ["user"] if requester.participant_type == "agent" else ["agent"]

        participant_index = {
            participant.participant_id: participant for participant in participants
        }
        explicit_targets: dict[UUID, dict[str, object]] = {}
        for participant_id in request_input.target_participant_ids:
            participant = participant_index.get(participant_id)
            if participant is None:
                raise KeyError(f"Participant {participant_id} not found in workspace {thread.workspace_id}")
            explicit_targets[participant_id] = {
                "participant": participant,
                "selector_type": "participant",
                "selector_value": str(participant_id),
                "selection_source": "explicit_participant_id",
                "score": 1000.0,
                "metadata": {"matched_selectors": [str(participant_id)]},
            }

        for selector in request_input.selectors:
            if selector.type == "participant":
                participant = self._resolve_participant_selector_match(
                    selector=selector,
                    participants=participants,
                )
                if participant is None:
                    continue
                explicit_targets[participant.participant_id] = {
                    "participant": participant,
                    "selector_type": "participant",
                    "selector_value": selector.value,
                    "selection_source": "participant_selector",
                    "score": 1000.0,
                    "metadata": {"matched_selectors": [selector.value]},
                }

        if explicit_targets:
            return list(explicit_targets.values())

        selector_targets: dict[UUID, dict[str, object]] = {}
        role_or_capability_selectors = [
            selector for selector in request_input.selectors if selector.type in {"role", "capability"}
        ]
        if role_or_capability_selectors:
            for selector in role_or_capability_selectors:
                best = self._best_participant_for_selector(
                    selector=selector,
                    participants=participants,
                    desired_responder_types=desired_responder_types,
                    requester=requester,
                    active_member_ids=active_member_ids,
                )
                if best is None:
                    continue
                existing = selector_targets.get(best.participant_id)
                if existing is None:
                    selector_targets[best.participant_id] = {
                        "participant": best,
                        "selector_type": selector.type,
                        "selector_value": selector.value,
                        "selection_source": "selector",
                        "score": self._interaction_candidate_score(
                            participant=best,
                            selector=selector,
                            requester=requester,
                            active_member_ids=active_member_ids,
                        ),
                        "metadata": {"matched_selectors": [selector.model_dump(mode="json")]},
                    }
                else:
                    existing["metadata"]["matched_selectors"].append(selector.model_dump(mode="json"))  # type: ignore[index]
            if selector_targets:
                return list(selector_targets.values())

        fallback_candidates = [
            participant
            for participant in participants
            if participant.participant_id != requester.participant_id
            and participant.participant_type in desired_responder_types
        ]
        fallback_candidates.sort(
            key=lambda participant: (
                -self._interaction_candidate_score(
                    participant=participant,
                    selector=None,
                    requester=requester,
                    active_member_ids=active_member_ids,
                ),
                participant.display_name.lower(),
            )
        )
        if fallback_candidates:
            best = fallback_candidates[0]
            return [
                {
                    "participant": best,
                    "selector_type": None,
                    "selector_value": None,
                    "selection_source": "auto_best_match",
                    "score": self._interaction_candidate_score(
                        participant=best,
                        selector=None,
                        requester=requester,
                        active_member_ids=active_member_ids,
                    ),
                    "metadata": {},
                }
            ]
        if requester.participant_type == "agent":
            fallback_managers = [
                participant
                for participant in participants
                if participant.participant_type == "user"
                and {"admin", "supervisor"}.intersection(participant.roles)
            ]
            fallback_managers.sort(key=lambda participant: participant.display_name.lower())
            if fallback_managers:
                best = fallback_managers[0]
                return [
                    {
                        "participant": best,
                        "selector_type": None,
                        "selector_value": None,
                        "selection_source": "workspace_manager_fallback",
                        "score": 50.0,
                        "metadata": {},
                    }
                ]
        return []

    @staticmethod
    def _resolve_participant_selector_match(
        *,
        selector: ParticipantSelector,
        participants: list[ParticipantProfile],
    ) -> ParticipantProfile | None:
        if selector.participant_id is not None:
            for participant in participants:
                if participant.participant_id == selector.participant_id:
                    return participant
        normalized = selector.value.strip().lower()
        for participant in participants:
            if str(participant.participant_id).lower() == normalized:
                return participant
            if participant.display_name.lower() == normalized:
                return participant
        return None

    def _best_participant_for_selector(
        self,
        *,
        selector: ParticipantSelector,
        participants: list[ParticipantProfile],
        desired_responder_types: list[str],
        requester: ParticipantProfile,
        active_member_ids: set[UUID],
    ) -> ParticipantProfile | None:
        candidates = [
            participant
            for participant in participants
            if participant.participant_id != requester.participant_id
            and participant.participant_type in desired_responder_types
            and self._participant_matches_selector(participant, selector)
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda participant: (
                -self._interaction_candidate_score(
                    participant=participant,
                    selector=selector,
                    requester=requester,
                    active_member_ids=active_member_ids,
                ),
                participant.display_name.lower(),
            )
        )
        return candidates[0]

    @staticmethod
    def _participant_matches_selector(
        participant: ParticipantProfile,
        selector: ParticipantSelector,
    ) -> bool:
        normalized = selector.value.strip().lower()
        if selector.type == "role":
            return normalized in {role.lower() for role in participant.roles}
        if selector.type == "capability":
            return normalized in {capability.lower() for capability in participant.capabilities}
        return False

    def _interaction_candidate_score(
        self,
        *,
        participant: ParticipantProfile,
        selector: ParticipantSelector | None,
        requester: ParticipantProfile,
        active_member_ids: set[UUID],
    ) -> float:
        score = 0.0
        if participant.participant_id in active_member_ids:
            score += 25.0
        score += {
            "active": 20.0,
            "idle": 15.0,
            "busy": 5.0,
            "offline": 0.0,
        }.get(participant.status, 0.0)
        if selector is not None and self._participant_matches_selector(participant, selector):
            score += 50.0
        if requester.participant_type == "agent" and {"admin", "supervisor"}.intersection(participant.roles):
            score += 5.0
        return score

    @staticmethod
    def _normalize_completion_rule(
        completion_rule: CompletionRule | None,
        *,
        resolved_targets: list[dict[str, object]],
    ) -> CompletionRule:
        if completion_rule is not None:
            return completion_rule
        return CompletionRule(
            mode="all_targets",
            target_participant_ids=[
                resolved["participant"].participant_id  # type: ignore[index]
                for resolved in resolved_targets
            ],
        )

    async def _interaction_request_aggregate_state(
        self,
        detail: InteractionRequestDetail,
    ) -> tuple[dict[str, object], bool]:
        participants = {
            participant.participant_id: participant
            for participant in await self._repository.list_participants(detail.request.workspace_id)
        }
        active_targets = [
            target for target in detail.targets if target.status != "dismissed"
        ]
        answered_target_ids = {
            target.participant_id
            for target in detail.targets
            if target.status == "answered" and target.participant_id is not None
        }
        answered_participant_ids = {
            answer.participant_id for answer in detail.answers
        } | answered_target_ids
        completion_rule = detail.request.completion_rule
        selector_buckets = [
            selector
            for selector in detail.request.metadata.get("selectors", [])
            if selector.get("type") in {"role", "capability"}
        ]
        covered_buckets: list[str] = []
        for selector in selector_buckets:
            bucket_type = str(selector["type"])
            bucket_value = str(selector["value"])
            if any(
                self._participant_matches_selector(
                    participants[participant_id],
                    ParticipantSelector(type=bucket_type, value=bucket_value),
                )
                for participant_id in answered_participant_ids
                if participant_id in participants
            ):
                covered_buckets.append(f"{bucket_type}:{bucket_value}")
        completed = False
        if completion_rule.mode == "all_targets":
            required_ids = {
                target.participant_id for target in active_targets if target.participant_id is not None
            }
            completed = required_ids.issubset(answered_participant_ids)
        elif completion_rule.mode == "minimum_answers":
            minimum_answers = completion_rule.minimum_answers or 1
            completed = len(answered_participant_ids) >= minimum_answers
        elif completion_rule.mode == "one_per_selector_bucket":
            required_buckets = {
                f"{selector['type']}:{selector['value']}" for selector in selector_buckets
            }
            completed = required_buckets.issubset(set(covered_buckets))
        elif completion_rule.mode == "custom_targets":
            required_ids = set(completion_rule.target_participant_ids)
            completed = required_ids.issubset(answered_participant_ids)
        aggregate = {
            "answered_participant_ids": [str(participant_id) for participant_id in sorted(answered_participant_ids)],
            "answered_count": len(answered_participant_ids),
            "target_count": len(active_targets),
            "covered_selector_buckets": covered_buckets,
            "completion_rule": completion_rule.model_dump(mode="json"),
            "completed": completed,
        }
        return aggregate, completed

    def _render_interaction_request_message(
        self,
        detail: InteractionRequestDetail,
    ) -> str:
        lines = [f"[Request] {detail.request.title}"]
        if detail.request.summary:
            lines.extend(["", detail.request.summary])
        if detail.questions:
            lines.append("")
            for index, question in enumerate(detail.questions, start=1):
                lines.append(f"{index}. {question.prompt}")
        if detail.targets:
            lines.append("")
            lines.append("Targets:")
            for target in detail.targets:
                label = str(target.participant_id)
                lines.append(f"- {label}")
        return "\n".join(lines)

    async def _create_interaction_request_followup_task(
        self,
        conn: asyncpg.Connection,
        *,
        request: InteractionRequest,
        detail: InteractionRequestDetail,
        answer_message: TimelineMessage | None,
        timestamp: datetime,
    ) -> Task | None:
        requester = await self._repository.fetch_participant(
            request.workspace_id,
            request.requester_participant_id,
        )
        if requester is None or requester.participant_type != "agent" or requester.system_agent_id is None:
            return None
        existing = await self._repository.list_open_interaction_requests_for_run(
            request.requester_run_id
        ) if request.requester_run_id is not None else []
        if request.status != "completed":
            return None
        task = Task(
            task_id=uuid4(),
            workspace_id=request.workspace_id,
            thread_id=request.thread_id,
            title=f"Continue request {request.request_id}",
            description="Interaction request completed and ready for aggregation.",
            requested_by=request.requester_participant_id,
            correlation_id=answer_message.correlation_id if answer_message is not None else uuid4(),
            causation_id=request.request_id,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "target_system_agent_id": str(requester.system_agent_id),
                "target_participant_id": str(requester.participant_id),
                "request_id": str(request.request_id),
                "trigger_message_id": (
                    str(answer_message.message_id) if answer_message is not None else None
                ),
                "sequence_ceiling": answer_message.sequence if answer_message is not None else 0,
                "response_visibility": "workspace",
                "routing_reason": "interaction_request_completed",
                "open_request_count_for_run": len(existing),
            },
        )
        await self._repository.upsert_task(conn, task)
        return task

    async def _resolve_run_for_context(
        self,
        task: Task,
        participant: ParticipantProfile,
        run_id: UUID | None,
    ) -> Run:
        if run_id is not None:
            run = await self._repository.fetch_run(run_id)
            if run is None:
                raise KeyError(f"Run {run_id} not found")
            return run
        raise ValueError(
            f"A run must exist before building execution context for task {task.task_id}"
        )

    async def _resolve_agent_participant(
        self,
        *,
        workspace_id: UUID,
        system_agent_id: UUID,
        routing: AgentTaskRouting,
    ) -> ParticipantProfile | None:
        if routing.target_participant_id is not None:
            participant = await self._repository.fetch_participant(
                workspace_id,
                routing.target_participant_id,
            )
            if (
                participant is not None
                and participant.participant_type == "agent"
                and participant.system_agent_id == system_agent_id
            ):
                return participant
        return await self._repository.fetch_agent_participant(
            workspace_id,
            system_agent_id,
        )

    async def _require_run_participant(
        self,
        *,
        run: Run,
        task: Task,
        system_agent_id: UUID,
    ) -> ParticipantProfile:
        participant = await self._resolve_agent_participant(
            workspace_id=task.workspace_id,
            system_agent_id=system_agent_id,
            routing=self._task_routing(task),
        )
        if participant is None:
            raise KeyError(
                f"System agent {system_agent_id} is not attached to workspace {task.workspace_id}"
            )
        if run.participant_id != participant.participant_id:
            raise ValueError(
                f"Run {run.run_id} does not belong to system agent {system_agent_id}"
            )
        return participant

    @staticmethod
    def _task_routing(task: Task) -> AgentTaskRouting:
        metadata = task.metadata
        return AgentTaskRouting(
            target_system_agent_id=(
                UUID(metadata["target_system_agent_id"])
                if metadata.get("target_system_agent_id")
                else None
            ),
            target_participant_id=(
                UUID(metadata["target_participant_id"])
                if metadata.get("target_participant_id")
                else None
            ),
            trigger_message_id=(
                UUID(metadata["trigger_message_id"])
                if metadata.get("trigger_message_id")
                else None
            ),
            response_visibility=metadata.get("response_visibility", "workspace"),
            sequence_ceiling=metadata.get("sequence_ceiling"),
            routing_reason=metadata.get("routing_reason"),
        )

    @staticmethod
    def _filter_visible_messages(
        messages: list[TimelineMessage],
        *,
        viewer: ParticipantProfile,
        sequence_ceiling: int | None,
    ) -> list[TimelineMessage]:
        visible: list[TimelineMessage] = []
        for message in messages:
            if sequence_ceiling is not None and message.sequence > sequence_ceiling:
                continue
            if message.visibility in {"public", "workspace"}:
                visible.append(message)
                continue
            if (
                message.visibility == "agents_only"
                and viewer.participant_type == "agent"
            ):
                visible.append(message)
                continue
            if message.visibility == "private" and message.actor.id == viewer.participant_id:
                visible.append(message)
        return visible

    @staticmethod
    def _filter_visible_memory_entries(
        entries: list[MemoryEntry],
        *,
        viewer: ParticipantProfile,
    ) -> list[MemoryEntry]:
        visible: list[MemoryEntry] = []
        for entry in entries:
            if entry.visibility in {"public", "workspace"}:
                visible.append(entry)
                continue
            if entry.visibility == "agents_only" and viewer.participant_type == "agent":
                visible.append(entry)
                continue
            if entry.visibility == "private" and entry.created_by == viewer.participant_id:
                visible.append(entry)
        return visible

    @staticmethod
    def _response_visibility(message_visibility: str) -> str:
        if message_visibility in {"public", "workspace"}:
            return message_visibility
        return "workspace"

    @classmethod
    def _run_output_from_result(cls, result: AgentRunResult) -> dict[str, object]:
        payload = result.model_dump(mode="json")
        usage = cls._run_usage_from_result(result)
        if usage is not None:
            payload["usage"] = usage
        return payload

    @staticmethod
    def _run_usage_from_result(result: AgentRunResult) -> dict[str, object] | None:
        raw = result.metadata.get("usage")
        if not isinstance(raw, dict):
            return None

        def _usage_int(name: str) -> int | None:
            value = raw.get(name)
            if isinstance(value, bool):
                return None
            if isinstance(value, int):
                return value
            return None

        provider = raw.get("provider")
        model = raw.get("model")
        usage = {
            "provider": provider if isinstance(provider, str) else None,
            "model": model if isinstance(model, str) else None,
            "prompt_tokens": _usage_int("prompt_tokens"),
            "completion_tokens": _usage_int("completion_tokens"),
            "total_tokens": _usage_int("total_tokens"),
        }
        if all(value is None for value in usage.values()):
            return None
        return usage

    @staticmethod
    def _stop_reason_returns_to_thread(stop_reason: StopReason) -> bool:
        return stop_reason in {
            "completed",
            "needs_user_input",
            "blocked_dependency",
            "handoff_required",
            "budget_exhausted",
            "tool_failure",
        }

    async def _finalize_tool_call(
        self,
        tool_call_id: UUID,
        worker_id: str,
        *,
        status: str,
        result: ToolCallResult,
        error: str | None,
        event_type: str,
    ) -> ToolCallCommandResult:
        tool_call = await self._repository.fetch_tool_call(tool_call_id)
        if tool_call is None:
            raise KeyError(f"Tool call {tool_call_id} not found")
        if tool_call.claimed_by_worker != worker_id:
            raise ValueError(
                f"Tool call {tool_call_id} is not claimed by worker {worker_id}"
            )
        step = await self._repository.fetch_run_step(tool_call.run_step_id)
        run = await self._repository.fetch_run(tool_call.run_id)
        task = await self._repository.fetch_task(tool_call.task_id)
        if step is None or run is None or task is None:
            raise KeyError(f"Tool call {tool_call_id} is missing execution state")
        participant = await self._require_run_participant(
            run=run,
            task=task,
            system_agent_id=tool_call.system_agent_id,
        )
        actor = ActorRef(type="agent", id=participant.participant_id)
        now = self._now()
        updated_tool_call = tool_call.model_copy(
            update={
                "status": status,
                "error": error,
                "result": result,
                "lease_expires_at": None,
                "last_heartbeat_at": None,
                "next_retry_at": None,
                "claimed_by_worker": None,
                "execution_handle": None,
                "finished_at": now,
                "updated_at": now,
            }
        )
        next_step: RunStep | None = None
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                await self._repository.upsert_tool_call(conn, updated_tool_call)
                event = await self._build_thread_event(
                    conn,
                    task.workspace_id,
                    task.thread_id,
                    event_type,
                    actor=actor,
                    target=TargetRef(type="tool_call", id=tool_call_id),
                    payload=updated_tool_call.model_dump(mode="json"),
                    visibility="agents_only",
                    timestamp=now,
                    correlation_id=run.correlation_id,
                    causation_id=task.task_id,
                )
                await self._repository.record_event(conn, event)
                remaining = await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM tool_calls
                    WHERE run_step_id = $1
                      AND status NOT IN ('completed', 'failed')
                    """,
                    step.step_id,
                )
                step_status = await conn.fetchval(
                    """
                    SELECT status
                    FROM run_steps
                    WHERE step_id = $1
                    FOR UPDATE
                    """,
                    step.step_id,
                )
                if remaining == 0 and step_status == "waiting_tools":
                    step = step.model_copy(
                        update={
                            "status": "completed",
                            "lease_expires_at": None,
                            "last_heartbeat_at": None,
                            "next_retry_at": None,
                            "claimed_by_worker": None,
                            "execution_handle": None,
                            "finished_at": now,
                            "updated_at": now,
                        }
                    )
                    await self._repository.upsert_run_step(conn, step)
                    next_step = RunStep(
                        step_id=uuid4(),
                        run_id=step.run_id,
                        task_id=step.task_id,
                        workspace_id=step.workspace_id,
                        thread_id=step.thread_id,
                        system_agent_id=step.system_agent_id,
                        step_index=step.step_index + 1,
                        status="created",
                        submitted_at=now,
                        created_at=now,
                        updated_at=now,
                        metadata=step.metadata,
                    )
                    await self._repository.upsert_run_step(conn, next_step)

        return ToolCallCommandResult(
            tool_call=updated_tool_call,
            step=next_step or step,
            run=run,
            task=task,
            events=[event],
        )

    def _build_tool_execution_spec(
        self,
        *,
        tool: WorkspaceTool | AgentInternalToolBinding,
        draft: AgentToolCallDraft,
        workspace_id: UUID,
    ) -> ExecutionSpec:
        self._validate_tool_execution_binding(tool.execution)
        profile = dict(tool.execution.execution_profile)
        return ExecutionSpec(
            invocation_id=uuid4(),
            handler_ref=tool.execution.handler_ref or tool.name,
            inline_payload=draft.arguments,
            artifact_refs=draft.artifact_refs,
            execution_workspace=(
                draft.execution_workspace
                if draft.execution_workspace is not None
                else self._execution_workspace_for_workspace(workspace_id)
            ),
            limits=ExecutionLimits(
                timeout_seconds=int(profile.get("timeout_seconds", 60)),
                cpu_millis=profile.get("cpu_millis"),
                memory_mb=profile.get("memory_mb"),
                pids_limit=profile.get("pids_limit"),
                network=profile.get("network", "none"),
                workspace_access=profile.get("workspace_access", "read_only"),
            ),
            env_refs=draft.env_refs,
            result_sink=draft.result_sink,
            profile=profile,
            metadata={
                "tool_id": str(tool.tool_id),
                "tool_name": tool.name,
                "backend_kind": tool.execution.backend_kind,
            },
        )

    @staticmethod
    def _execution_workspace_for_workspace(workspace_id: UUID) -> ExecutionWorkspaceRef:
        return ExecutionWorkspaceRef(
            mode="local_path",
            workspace_id=workspace_id,
        )

    @staticmethod
    def _artifact_from_draft(
        draft: AgentArtifactDraft,
        *,
        task: Task,
        run: Run,
        timestamp: datetime,
    ) -> Artifact:
        return Artifact(
            artifact_id=uuid4(),
            workspace_id=task.workspace_id,
            thread_id=task.thread_id,
            task_id=task.task_id,
            run_id=run.run_id,
            kind=draft.kind,
            title=draft.title,
            content=draft.content,
            visibility=draft.visibility,
            correlation_id=task.correlation_id,
            created_at=timestamp,
            updated_at=timestamp,
            metadata=draft.metadata,
        )

    @staticmethod
    def _agent_message_from_result(
        result: AgentRunResult,
        *,
        task: Task,
        participant: ParticipantProfile,
        timestamp: datetime,
    ) -> TimelineMessage:
        routing = CollaborationKernel._task_routing(task)
        return TimelineMessage(
            message_id=uuid4(),
            workspace_id=task.workspace_id,
            thread_id=task.thread_id,
            actor=ActorRef(type="agent", id=participant.participant_id),
            visibility=routing.response_visibility,
            content=result.message or "",
            status="completed",
            correlation_id=task.correlation_id,
            causation_id=task.task_id,
            sequence=0,
            created_at=timestamp,
            updated_at=timestamp,
            metadata={
                "system_agent_id": str(participant.system_agent_id)
                if participant.system_agent_id is not None
                else None,
                "stop_reason": result.stop_reason,
                "summary": result.summary,
                **result.metadata,
            },
        )

    async def _build_workspace_event(
        self,
        conn: asyncpg.Connection,
        workspace_id: UUID,
        event_type: str,
        *,
        actor: ActorRef,
        target: TargetRef,
        payload: dict,
        visibility: str = "workspace",
        timestamp: datetime,
    ) -> EventEnvelope:
        sequence = await self._repository.next_workspace_sequence(conn, workspace_id)
        return EventEnvelope(
            event_type=event_type,
            workspace_id=workspace_id,
            actor=actor,
            target=target,
            visibility=visibility,
            sequence=sequence,
            timestamp=timestamp,
            payload=payload,
        )

    async def _build_thread_event(
        self,
        conn: asyncpg.Connection,
        workspace_id: UUID,
        thread_id: UUID,
        event_type: str,
        *,
        actor: ActorRef,
        target: TargetRef,
        payload: dict,
        visibility: str = "public",
        timestamp: datetime,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
    ) -> EventEnvelope:
        sequence = await self._repository.next_thread_sequence(conn, thread_id)
        return EventEnvelope(
            event_type=event_type,
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=actor,
            target=target,
            visibility=visibility,
            correlation_id=correlation_id or uuid4(),
            causation_id=causation_id,
            sequence=sequence,
            timestamp=timestamp,
            payload=payload,
        )

    @staticmethod
    def _actor_from_input(actor: ParticipantInput) -> ActorRef:
        return ActorRef(type=actor.participant_type, id=actor.participant_id)

    @staticmethod
    def _participant_profile(
        *,
        workspace_id: UUID,
        actor: ParticipantInput,
        now: datetime,
        status: str = "active",
        existing: ParticipantProfile | None = None,
    ) -> ParticipantProfile:
        roles = list(actor.roles) if actor.roles else list(existing.roles if existing is not None else [])
        capabilities = (
            list(actor.capabilities)
            if actor.capabilities
            else list(existing.capabilities if existing is not None else [])
        )
        description = actor.description if actor.description is not None else (
            existing.description if existing is not None else None
        )
        if actor.participant_type == "user":
            user_id = actor.user_id if actor.user_id is not None else (
                existing.user_id if existing is not None else None
            )
        else:
            user_id = None
        visibility_scope = actor.visibility_scope
        if (
            existing is not None
            and actor.visibility_scope == "workspace"
            and existing.visibility_scope != "workspace"
        ):
            visibility_scope = existing.visibility_scope
        return ParticipantProfile(
            participant_id=actor.participant_id,
            workspace_id=workspace_id,
            participant_type=actor.participant_type,
            user_id=user_id,
            system_agent_id=existing.system_agent_id if existing is not None else None,
            display_name=actor.display_name,
            description=description,
            roles=roles,
            capabilities=capabilities,
            status=status,
            visibility_scope=visibility_scope,
            agent_config=existing.agent_config if existing is not None else None,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            metadata=dict(existing.metadata) if existing is not None else {},
        )

    async def _participant_profile_for_actor(
        self,
        *,
        workspace_id: UUID,
        actor: ParticipantInput,
        now: datetime,
        status: str = "active",
    ) -> ParticipantProfile:
        if actor.participant_type == "user":
            await self._require_workspace_user_membership(workspace_id, actor)
        existing = await self._repository.fetch_participant(workspace_id, actor.participant_id)
        return self._participant_profile(
            workspace_id=workspace_id,
            actor=actor,
            now=now,
            status=status,
            existing=existing,
        )

    @staticmethod
    def _with_agent_metadata(participant: ParticipantProfile) -> ParticipantProfile:
        return participant

    async def _ensure_participant_identity(
        self,
        conn: asyncpg.Connection,
        participant: ParticipantProfile,
    ) -> None:
        if participant.participant_type != "user" or participant.user_id is None:
            return
        await self._repository.upsert_user(
            conn,
            UserRecord(
                user_id=participant.user_id,
                display_name=participant.display_name,
                created_at=participant.created_at,
                updated_at=participant.updated_at,
                metadata={},
            ),
        )

    async def resolve_authenticated_user_actor(
        self,
        workspace_id: UUID,
        *,
        user_id: UUID,
        display_name: str,
        auto_create: bool = True,
    ) -> ParticipantInput:
        workspace = await self._repository.fetch_workspace(workspace_id)
        if (
            workspace is not None
            and workspace.organization_id is not None
            and hasattr(self._repository, "fetch_organization_membership")
        ):
            membership = await self._repository.fetch_organization_membership(
                workspace.organization_id,
                user_id,
            )
            if membership is None:
                raise KeyError(
                    f"Authenticated user {user_id} is not a member of organization {workspace.organization_id}"
                )
        participant = await self._repository.fetch_user_participant(workspace_id, user_id)
        if participant is None and not auto_create:
            raise KeyError(
                f"Authenticated user {user_id} is not attached to workspace {workspace_id}"
            )
        participant_id = participant.participant_id if participant is not None else uuid4()
        return ParticipantInput(
            participant_id=participant_id,
            participant_type="user",
            user_id=user_id,
            display_name=display_name,
        )

    @staticmethod
    def _actor_user_id(actor: ParticipantInput) -> UUID | None:
        if actor.user_id is not None:
            return actor.user_id
        if actor.participant_type == "user":
            return actor.participant_id
        return None

    async def _require_workspace_user_membership(
        self,
        workspace_id: UUID,
        actor: ParticipantInput,
    ) -> None:
        user_id = self._actor_user_id(actor)
        if user_id is None:
            return
        workspace = await self._repository.fetch_workspace(workspace_id)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        if workspace.organization_id is None or not hasattr(
            self._repository,
            "fetch_organization_membership",
        ):
            return
        membership = await self._repository.fetch_organization_membership(
            workspace.organization_id,
            user_id,
        )
        if membership is None:
            raise PermissionError(
                f"User {user_id} is not a member of organization {workspace.organization_id}"
            )

    async def _require_organization_membership(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> OrganizationMembership:
        if not hasattr(self._repository, "fetch_organization_membership"):
            now = self._now()
            return OrganizationMembership(
                organization_id=organization_id,
                user_id=user_id,
                role="owner",
                joined_at=now,
                updated_at=now,
                metadata={},
            )
        membership = await self._repository.fetch_organization_membership(
            organization_id,
            user_id,
        )
        if membership is None:
            raise KeyError(
                f"User {user_id} is not a member of organization {organization_id}"
            )
        return membership

    async def _require_organization_admin(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> OrganizationMembership:
        membership = await self._require_organization_membership(organization_id, user_id)
        if membership.role not in _ORGANIZATION_ADMIN_ROLES:
            raise PermissionError("Organization admin role required")
        return membership

    async def _resolve_workspace_organization(
        self,
        *,
        requested_organization_id: UUID | None,
        actor: ParticipantInput,
    ) -> Organization:
        if requested_organization_id is not None:
            organization = await self._repository.fetch_organization(requested_organization_id)
            if organization is None:
                raise KeyError(f"Organization {requested_organization_id} not found")
            return organization
        if not hasattr(self._repository, "list_organizations_for_user"):
            return Organization(
                organization_id=UUID("11111111-1111-1111-1111-111111111111"),
                slug="default",
                name="Default Organization",
                description="Implicit test organization",
                created_by=self._actor_user_id(actor) or actor.participant_id,
                created_at=self._now(),
                updated_at=self._now(),
                metadata={},
            )
        user_id = self._actor_user_id(actor)
        organizations = (
            await self._repository.list_organizations_for_user(user_id)
            if user_id is not None
            else await self._repository.list_organizations()
        )
        if len(organizations) == 1:
            return organizations[0]
        raise ValueError("organization_id is required when multiple organizations are available")

    async def _require_workspace_management_role(
        self,
        workspace_id: UUID,
        actor: ParticipantInput,
    ) -> ParticipantProfile:
        participant = await self._repository.fetch_participant(
            workspace_id,
            actor.participant_id,
        )
        if participant is None:
            raise PermissionError(
                f"Workspace {workspace_id} requires an attached participant for this action"
            )
        if _WORKSPACE_MANAGER_ROLES.intersection(participant.roles):
            return participant
        raise PermissionError(
            "Workspace admin or supervisor role required"
        )

    @staticmethod
    def _workspace_metadata_for_create(
        *,
        metadata: dict[str, object],
        updated_by: UUID,
        updated_at: datetime,
    ) -> dict[str, object]:
        return {
            **metadata,
            "role_definitions": CollaborationKernel._merge_workspace_role_definitions(
                metadata.get("role_definitions"),
                updated_by=updated_by,
                updated_at=updated_at,
            ),
        }

    @staticmethod
    def _merge_workspace_role_definitions(
        raw: object,
        *,
        updated_by: UUID,
        updated_at: datetime,
    ) -> dict[str, dict[str, object]]:
        role_map: dict[str, dict[str, object]] = {}
        for name, definition in _DEFAULT_WORKSPACE_ROLE_DEFINITIONS.items():
            role_map[name] = RoleDefinition(
                name=name,
                definition=definition,
                updated_by=updated_by,
                updated_at=updated_at,
            ).model_dump(mode="json")
        if isinstance(raw, dict):
            for key, value in raw.items():
                role_definition = RoleDefinition.model_validate(value)
                role_map[key] = role_definition.model_dump(mode="json")
        elif isinstance(raw, list):
            for value in raw:
                role_definition = RoleDefinition.model_validate(value)
                role_map[role_definition.name] = role_definition.model_dump(mode="json")
        return role_map

    @staticmethod
    def _workspace_owner_roles(roles: list[str]) -> list[str]:
        return list(dict.fromkeys([*roles, "admin"]))

    @staticmethod
    def _utc_day_window(timestamp: datetime) -> tuple[datetime, datetime]:
        current = timestamp.astimezone(timezone.utc)
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start, day_start + timedelta(days=1)

    @staticmethod
    def _workspace_daily_token_cap(
        workspace: Workspace,
        default_cap: int,
    ) -> int:
        limits = workspace.metadata.get("limits", {})
        if isinstance(limits, dict):
            override = CollaborationKernel._metadata_int_value(
                limits.get("daily_token_cap")
            )
            if override is not None:
                return override
        override = CollaborationKernel._metadata_int_value(
            workspace.metadata.get("daily_token_cap")
        )
        if override is not None:
            return override
        return default_cap

    @staticmethod
    def _metadata_int_value(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
        return None

    @staticmethod
    def _role_definitions_from_workspace(workspace: Workspace) -> list[RoleDefinition]:
        raw = workspace.metadata.get("role_definitions", {})
        if isinstance(raw, dict):
            return [RoleDefinition.model_validate(item) for item in raw.values()]
        if isinstance(raw, list):
            return [RoleDefinition.model_validate(item) for item in raw]
        return []

    @staticmethod
    def _validate_registry_scope(*, scope: str, organization_id: UUID | None) -> None:
        if scope not in {"global", "organization"}:
            raise ValueError(f"Unsupported registry scope {scope!r}")
        if scope == "global" and organization_id is not None:
            raise ValueError("Global registry resources cannot include an organization_id")
        if scope == "organization" and organization_id is None:
            raise ValueError("Organization-scoped resources require an organization_id")

    @staticmethod
    def _validate_asset_scope(
        *,
        scope: str,
        organization_id: UUID | None,
        workspace_id: UUID | None,
    ) -> None:
        if scope not in {"global", "organization", "workspace"}:
            raise ValueError(f"Unsupported asset scope {scope!r}")
        if scope == "global" and (organization_id is not None or workspace_id is not None):
            raise ValueError("Global scope resources cannot include organization_id or workspace_id")
        if scope == "organization" and (organization_id is None or workspace_id is not None):
            raise ValueError("Organization scope resources require organization_id and forbid workspace_id")
        if scope == "workspace" and workspace_id is None:
            raise ValueError("Workspace scope resources require a workspace_id")

    @staticmethod
    def _validate_tool_execution_binding(execution) -> None:
        workspace_access = execution.execution_profile.get("workspace_access", "read_only")
        network = execution.execution_profile.get("network", "none")
        if workspace_access == "read_write" and execution.trust_level != "trusted":
            raise ValueError("read_write workspace access requires trust_level='trusted'")
        if network == "full" and execution.trust_level != "trusted":
            raise ValueError("network=full requires trust_level='trusted'")
        if execution.backend_kind == "local_process" and execution.trust_level != "trusted":
            raise ValueError("local_process execution requires trust_level='trusted'")

    async def _validate_asset_link_target(
        self,
        *,
        target_type: str,
        target_id: UUID,
        organization_id: UUID | None,
        workspace_id: UUID | None,
    ) -> None:
        if target_type == "system_agent":
            agent = await self._repository.fetch_system_agent(target_id)
            if agent is None:
                raise KeyError(f"System agent {target_id} not found")
            if (
                organization_id is not None
                and agent.scope == "organization"
                and agent.organization_id != organization_id
            ):
                raise ValueError("Organization asset links must target resources in the same organization")
            return
        if target_type == "system_tool":
            tool = await self._repository.fetch_system_tool(target_id)
            if tool is None:
                raise KeyError(f"System tool {target_id} not found")
            if (
                organization_id is not None
                and tool.scope == "organization"
                and tool.organization_id != organization_id
            ):
                raise ValueError("Organization asset links must target resources in the same organization")
            return
        if target_type == "workspace":
            workspace = await self._repository.fetch_workspace(target_id)
            if workspace is None:
                raise KeyError(f"Workspace {target_id} not found")
            if organization_id is not None and workspace.organization_id != organization_id:
                raise ValueError("Organization asset links must target workspaces in the same organization")
            return
        if target_type == "workspace_tool":
            if workspace_id is None:
                raise ValueError("workspace_tool asset links require a workspace_id override scope")
            if await self._repository.fetch_workspace_tool(workspace_id, target_id) is None:
                raise KeyError(f"Workspace tool {target_id} not found in workspace {workspace_id}")
            return
        raise ValueError(f"Unsupported asset link target type {target_type!r}")

    async def _resolve_scope_organization(
        self,
        *,
        scope: str,
        organization_id: UUID | None,
        workspace_id: UUID | None,
    ) -> Organization | None:
        self._validate_asset_scope(
            scope=scope,
            organization_id=organization_id,
            workspace_id=workspace_id,
        )
        if scope == "global":
            return None
        if workspace_id is not None:
            workspace = await self._repository.fetch_workspace(workspace_id)
            if workspace is None:
                raise KeyError(f"Workspace {workspace_id} not found")
            if organization_id is not None and workspace.organization_id != organization_id:
                raise ValueError(
                    f"Workspace {workspace_id} does not belong to organization {organization_id}"
                )
            if not hasattr(self._repository, "fetch_organization"):
                return Organization(
                    organization_id=workspace.organization_id
                    or UUID("11111111-1111-1111-1111-111111111111"),
                    slug="default",
                    name="Default Organization",
                    description="Implicit test organization",
                    created_by=workspace.owner_user_id or workspace.workspace_id,
                    created_at=workspace.created_at,
                    updated_at=workspace.updated_at,
                    metadata={},
                )
            organization = await self._repository.fetch_organization(workspace.organization_id)
            if organization is None:
                raise KeyError(f"Organization {workspace.organization_id} not found")
            return organization
        assert organization_id is not None
        if not hasattr(self._repository, "fetch_organization"):
            return Organization(
                organization_id=organization_id,
                slug="default",
                name="Default Organization",
                description="Implicit test organization",
                created_by=organization_id,
                created_at=self._now(),
                updated_at=self._now(),
                metadata={},
            )
        organization = await self._repository.fetch_organization(organization_id)
        if organization is None:
            raise KeyError(f"Organization {organization_id} not found")
        return organization

    @staticmethod
    def _resource_visible_to_workspace(
        scope: str,
        organization_id: UUID | None,
        workspace: Workspace,
    ) -> bool:
        if scope == "global":
            return True
        if scope == "organization":
            return organization_id == workspace.organization_id
        return False

    async def _visible_enabled_memory_providers(
        self,
        organization_id: UUID | None,
    ) -> list[MemoryProviderDefinition]:
        try:
            providers = await self._repository.list_enabled_memory_providers(scope="global")
        except TypeError:
            providers = await self._repository.list_enabled_memory_providers()
        if organization_id is None:
            return providers
        try:
            overrides = await self._repository.list_enabled_memory_providers(
                scope="organization",
                organization_id=organization_id,
            )
        except TypeError:
            overrides = []
        by_key = {provider.provider_key: provider for provider in providers}
        for provider in overrides:
            by_key[provider.provider_key] = provider
        return list(by_key.values())

    @staticmethod
    def _advertised_agent_capabilities(
        base_capabilities: list[str],
        workspace_tools: list[WorkspaceTool],
    ) -> list[str]:
        combined = list(base_capabilities)
        for tool in workspace_tools:
            if tool.enabled:
                combined.append(f"tool:{tool.name}")
        return list(dict.fromkeys(combined))

    @classmethod
    def _advertise_workspace_tools(
        cls,
        participant: ParticipantProfile,
        workspace_tools: list[WorkspaceTool],
    ) -> ParticipantProfile:
        if participant.participant_type != "agent":
            return participant
        return participant.model_copy(
            update={
                "capabilities": cls._advertised_agent_capabilities(
                    participant.capabilities,
                    workspace_tools,
                )
            }
        )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)
