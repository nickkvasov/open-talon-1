from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from open_talon_contracts.iam import PROJECT_ROLE_BASE_PERMISSIONS
from pydantic import BaseModel, Field, TypeAdapter

from gateway_edge.config import settings
from gateway_edge.iam.authorization import PermissionResolution, authorization_engine
from gateway_edge.models import (
    AuthContext,
    AgentBundlePublishResult,
    AgentBundleValidationResult,
    AgentDefinition,
    AgentGitCommitRequest,
    AgentGitCommitResult,
    AgentGitDiffResult,
    AgentGitFileContent,
    AgentGitFileMutationRequest,
    AgentGitWorktreeSession,
    AuditChainVerificationResult,
    AuditEventPage,
    AuditExportRequest,
    CreateAgentGitWorktreeSessionRequest,
    CreateGitRepositoryRequest,
    CreateInteractionRequest,
    CreateMemoryEntryRequest,
    CreateMessageRequest,
    CreateProjectRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    GitRepository,
    MemoryEntry,
    LlmProviderDefinition,
    MemoryProviderDefinition,
    MemorySearchResponse,
    McpServerDefinition,
    Organization,
    OrganizationMembership,
    ParticipantInput,
    Project,
    ProjectAccessBinding,
    ProjectAccessRole,
    ProjectSubjectRef,
    PublishAgentBundleFromGitRequest,
    RemoveProjectAccessRequest,
    SystemToolDefinition,
    Thread,
    ThreadDetail,
    TimelineMessage,
    TimelinePage,
    UpdateProjectRequest,
    UpsertProjectAccessRequest,
    Workspace,
    WorkspaceDetail,
    ValidateAgentBundleFromGitRequest,
)
from gateway_edge.services import collaboration as collab_svc
from gateway_edge.services.audit import audit_service
from gateway_edge.services.iam import iam_service
from gateway_edge.services.session import get_redis

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SERVER_INFO = {
    "name": "open-talon-mcp-api",
    "title": "Open Talon MCP API",
    "version": "0.1.0",
}
_MCP_SESSION_PREFIX = "mcp:sessions:"
McpScopeKind = Literal["global", "organization", "project", "workspace"]


class EmptyArgs(BaseModel):
    model_config = {"extra": "forbid"}


class SessionSetScopeArgs(BaseModel):
    scope: McpScopeKind
    organization_id: UUID | None = None
    project_id: UUID | None = None
    workspace_id: UUID | None = None


class ProjectRefArgs(BaseModel):
    project_id: UUID | None = None


class ProjectCreateArgs(BaseModel):
    slug: str
    name: str
    description: str | None = None
    owner: ProjectSubjectRef | None = None
    owners: list[ProjectSubjectRef] = Field(default_factory=list)
    editors: list[ProjectSubjectRef] = Field(default_factory=list)
    viewers: list[ProjectSubjectRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdateArgs(BaseModel):
    project_id: UUID | None = None
    slug: str | None = None
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class ProjectAccessListArgs(BaseModel):
    project_id: UUID | None = None


class ProjectAccessUpsertArgs(BaseModel):
    subject: ProjectSubjectRef
    role: ProjectAccessRole
    project_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectAccessRemoveArgs(BaseModel):
    subject: ProjectSubjectRef
    project_id: UUID | None = None


class WorkspaceListArgs(BaseModel):
    project_id: UUID | None = None


class WorkspaceCreateArgs(BaseModel):
    name: str
    description: str | None = None
    project_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadRefArgs(BaseModel):
    thread_id: UUID


class ThreadMessageCreateArgs(BaseModel):
    thread_id: UUID
    content: str
    visibility: str = "public"
    target_system_agent_id: UUID | None = None
    target_tool_scope: str | None = None
    create_task: bool = True
    task_instructions: list[str] = Field(default_factory=list)
    requests: list[CreateInteractionRequest] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadCreateArgs(BaseModel):
    title: str
    parent_thread_id: UUID | None = None
    previous_thread_id: UUID | None = None
    related_thread_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceMemoryCreateArgs(BaseModel):
    entry_type: str
    content: str
    summary: str | None = None
    visibility: str = "workspace"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThreadMemorySearchArgs(BaseModel):
    thread_id: UUID
    query: str
    limit: int = 10
    use_provider: str | None = None
    include_graph: bool = True
    metadata_filters: dict[str, Any] = Field(default_factory=dict)


class AuditEventsListArgs(BaseModel):
    organization_id: UUID | None = None
    workspace_id: UUID | None = None
    thread_id: UUID | None = None
    actor_user_id: UUID | None = None
    actor_system_agent_id: UUID | None = None
    action_prefix: str | None = None
    outcome: str | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    correlation_id: UUID | None = None
    request_id: UUID | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class AuditChainVerifyArgs(BaseModel):
    chain_partition: str | None = None


class AgentBundleGitArgs(BaseModel):
    repository_id: UUID
    bundle_path: str
    revision: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentGitRepoEnsureArgs(BaseModel):
    name: str
    local_path: str
    forgejo_url: str | None = None
    clone_url: str | None = None
    default_branch: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentGitWorktreeCreateArgs(BaseModel):
    repository_id: UUID
    branch: str
    bundle_path: str
    base_revision: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentGitWorktreeFileArgs(BaseModel):
    session_id: UUID
    path: str
    content: str | None = None
    content_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentGitWorktreeRefArgs(BaseModel):
    session_id: UUID


class AgentGitWorktreeCommitArgs(BaseModel):
    session_id: UUID
    message: str
    push: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class McpScopeCandidate(BaseModel):
    kind: McpScopeKind
    id: UUID | None = None
    label: str
    organization_id: UUID | None = None
    project_id: UUID | None = None


class McpSessionState(BaseModel):
    session_id: UUID
    principal_fingerprint: str
    principal_type: Literal["human", "agent"]
    active_scope_kind: McpScopeKind = "global"
    active_scope_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OperationDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    output_schema: dict[str, Any]
    allowed_scopes: frozenset[McpScopeKind]
    required_permission_type: Literal["identity", "workspace"] | None
    required_permission: str | None
    required_project_permission: str | None = None
    requires_workspace_actor: bool = False
    handler_name: str = ""

    @property
    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()


class McpNotificationHub:
    def __init__(self) -> None:
        self._subscribers: dict[UUID, set[asyncio.Queue[dict[str, Any]]]] = {}

    async def subscribe(self, session_id: UUID) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.setdefault(session_id, set()).add(queue)
        return queue

    def unsubscribe(self, session_id: UUID, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subscribers = self._subscribers.get(session_id)
        if subscribers is None:
            return
        subscribers.discard(queue)
        if not subscribers:
            self._subscribers.pop(session_id, None)

    async def publish(self, session_id: UUID, payload: dict[str, Any]) -> None:
        for queue in self._subscribers.get(session_id, set()):
            await queue.put(payload)


notification_hub = McpNotificationHub()


def _scope_payload(session: McpSessionState) -> dict[str, Any]:
    if session.active_scope_kind == "global":
        return {"scope": "global"}
    field = f"{session.active_scope_kind}_id"
    return {"scope": session.active_scope_kind, field: str(session.active_scope_id)}


def _principal_fingerprint(auth_context: AuthContext) -> str:
    payload = {
        "principal_type": auth_context.principal_type,
        "user_id": str(auth_context.user_id) if auth_context.user_id is not None else None,
        "agent_identity_id": (
            str(auth_context.agent_identity_id) if auth_context.agent_identity_id is not None else None
        ),
        "system_agent_id": (
            str(auth_context.system_agent_id) if auth_context.system_agent_id is not None else None
        ),
        "issuer": auth_context.issuer,
        "subject": auth_context.subject,
        "client_id": auth_context.client_id,
        "provider_key": auth_context.provider_key,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


async def create_mcp_session(auth_context: AuthContext) -> McpSessionState:
    now = datetime.now(UTC)
    session = McpSessionState(
        session_id=uuid4(),
        principal_fingerprint=_principal_fingerprint(auth_context),
        principal_type=auth_context.principal_type,
        created_at=now,
        updated_at=now,
    )
    await save_mcp_session(session)
    return session


async def save_mcp_session(session: McpSessionState) -> None:
    redis = await get_redis()
    await redis.set(
        f"{_MCP_SESSION_PREFIX}{session.session_id}",
        session.model_dump_json(),
        ex=settings.mcp_session_ttl_seconds,
    )


async def load_mcp_session(session_id: UUID, auth_context: AuthContext) -> McpSessionState:
    redis = await get_redis()
    raw = await redis.get(f"{_MCP_SESSION_PREFIX}{session_id}")
    if raw is None:
        raise HTTPException(status_code=400, detail="Unknown or expired MCP session")
    session = McpSessionState.model_validate_json(raw)
    if session.principal_fingerprint != _principal_fingerprint(auth_context):
        raise HTTPException(status_code=401, detail="MCP session principal mismatch")
    refreshed = session.model_copy(update={"updated_at": datetime.now(UTC)})
    await save_mcp_session(refreshed)
    return refreshed


class McpApiContext:
    def __init__(
        self,
        *,
        request: Request,
        auth_context: AuthContext,
        session: McpSessionState,
    ) -> None:
        self.request = request
        self.auth_context = auth_context
        self.session = session
        self.scope_changed = False
        self._scope_candidates: list[McpScopeCandidate] | None = None
        self._resolution: PermissionResolution | None = None

    @property
    def active_scope_kind(self) -> McpScopeKind:
        return self.session.active_scope_kind

    @property
    def active_scope_id(self) -> UUID | None:
        return self.session.active_scope_id

    async def current_resolution(self) -> PermissionResolution:
        if self._resolution is not None:
            return self._resolution
        if self.active_scope_kind == "organization" and self.active_scope_id is not None:
            self._resolution = await authorization_engine.compute_effective_permissions(
                self.auth_context,
                organization_id=self.active_scope_id,
            )
            return self._resolution
        if self.active_scope_kind == "project" and self.active_scope_id is not None:
            project = await collab_svc.collaboration_service.get_project(self.active_scope_id)
            self._resolution = await authorization_engine.compute_effective_permissions(
                self.auth_context,
                organization_id=project.organization_id,
            )
            return self._resolution
        if self.active_scope_kind == "workspace" and self.active_scope_id is not None:
            self._resolution = await authorization_engine.compute_effective_permissions(
                self.auth_context,
                workspace_id=self.active_scope_id,
            )
            return self._resolution
        self._resolution = await authorization_engine.compute_effective_permissions(self.auth_context)
        return self._resolution

    async def active_organization_id(self) -> UUID | None:
        if self.active_scope_kind == "organization":
            return self.active_scope_id
        if self.active_scope_kind == "project" and self.active_scope_id is not None:
            project = await collab_svc.collaboration_service.get_project(self.active_scope_id)
            return project.organization_id
        if self.active_scope_kind == "workspace" and self.active_scope_id is not None:
            detail = await collab_svc.collaboration_service.get_workspace(self.active_scope_id)
            return detail.workspace.organization_id
        return None

    async def active_project_id(self) -> UUID | None:
        if self.active_scope_kind == "project":
            return self.active_scope_id
        if self.active_scope_kind == "workspace" and self.active_scope_id is not None:
            detail = await collab_svc.collaboration_service.get_workspace(self.active_scope_id)
            return detail.workspace.project_id
        return None

    def identity_actor(self) -> ParticipantInput:
        participant_id = (
            self.auth_context.user_id
            or self.auth_context.system_agent_id
            or self.auth_context.agent_identity_id
            or uuid4()
        )
        return ParticipantInput(
            participant_id=participant_id,
            participant_type=(
                "agent" if self.auth_context.principal_type == "agent" else "user"
            ),
            user_id=(
                self.auth_context.user_id
                if self.auth_context.principal_type == "human"
                else None
            ),
            display_name=(
                self.auth_context.display_name
                or self.auth_context.client_id
                or self.auth_context.subject
                or self.auth_context.principal_type
            ),
            iam_permissions=[],
        )

    async def require_visible(self, operation: OperationDefinition) -> None:
        if not await self.operation_visible(operation):
            raise PermissionError(
                f"Operation {operation.name!r} is not available in the current scope or with current permissions"
            )

    async def operation_visible(self, operation: OperationDefinition) -> bool:
        if self.active_scope_kind not in operation.allowed_scopes:
            return False
        try:
            await self._authorize_operation(operation)
            if (
                operation.required_project_permission is not None
                and self.active_scope_kind == "project"
                and self.active_scope_id is not None
            ):
                project = await collab_svc.collaboration_service.get_project(self.active_scope_id)
                await self.require_project_permission(
                    project,
                    permission=operation.required_project_permission,
                )
            if operation.requires_workspace_actor and self.active_scope_kind == "workspace":
                await self.resolve_workspace_actor(auto_create=False)
            return True
        except Exception:
            return False

    async def _authorize_operation(self, operation: OperationDefinition) -> PermissionResolution | None:
        if operation.required_permission is None or operation.required_permission_type is None:
            return None
        organization_id = await self.active_organization_id()
        workspace_id = self.active_scope_id if self.active_scope_kind == "workspace" else None
        return await authorization_engine.authorize(
            f"mcp.{operation.name}",
            {
                "auth_context": self.auth_context,
                "permission_type": operation.required_permission_type,
                "permission": operation.required_permission,
                "organization_id": organization_id,
                "workspace_id": workspace_id,
            },
        )

    async def resolve_workspace_actor(self, *, auto_create: bool) -> ParticipantInput:
        if self.active_scope_kind != "workspace" or self.active_scope_id is None:
            raise ValueError("Workspace actor resolution requires an active workspace scope")
        workspace = await collab_svc.collaboration_service.get_workspace(self.active_scope_id)
        await authorization_engine.authorize(
            "mcp.workspace.read",
            {
                "auth_context": self.auth_context,
                "permission_type": "identity",
                "permission": "workspace.read",
                "organization_id": workspace.workspace.organization_id,
            },
        )
        if self.auth_context.principal_type == "agent":
            return await collab_svc.collaboration_service.resolve_authenticated_agent_actor(
                workspace_id=self.active_scope_id,
                auth_context=self.auth_context,
            )
        return await collab_svc.collaboration_service.resolve_authenticated_user_actor(
            workspace_id=self.active_scope_id,
            auth_context=self.auth_context,
            auto_create=auto_create,
        )

    async def resolve_thread_actor(self, thread_id: UUID, *, auto_create: bool) -> ParticipantInput:
        thread = await collab_svc.collaboration_service.get_thread(thread_id)
        if self.active_scope_kind != "workspace" or thread.thread.workspace_id != self.active_scope_id:
            raise PermissionError(f"Thread {thread_id} is outside the active workspace scope")
        return await self.resolve_workspace_actor(auto_create=auto_create)

    async def ensure_thread_in_scope(self, thread_id: UUID) -> ThreadDetail:
        thread = await collab_svc.collaboration_service.get_thread(thread_id)
        if self.active_scope_kind != "workspace" or thread.thread.workspace_id != self.active_scope_id:
            raise PermissionError(f"Thread {thread_id} is outside the active workspace scope")
        return thread

    def project_subject(self) -> ProjectSubjectRef | None:
        if self.auth_context.principal_type == "human" and self.auth_context.user_id is not None:
            return ProjectSubjectRef(user_id=self.auth_context.user_id)
        if self.auth_context.principal_type == "agent" and self.auth_context.system_agent_id is not None:
            return ProjectSubjectRef(system_agent_id=self.auth_context.system_agent_id)
        return None

    async def project_access_binding(self, project: Project) -> ProjectAccessBinding | None:
        subject = self.project_subject()
        if subject is None:
            return None
        bindings = await collab_svc.collaboration_service.list_project_access(
            project.organization_id,
            project.project_id,
            actor=None,
            allow_platform_admin=True,
        )
        for binding in bindings:
            if subject.user_id is not None and binding.user_id == subject.user_id:
                return binding
            if subject.system_agent_id is not None and binding.system_agent_id == subject.system_agent_id:
                return binding
        return None

    async def require_project_permission(
        self,
        project: Project,
        *,
        permission: str,
    ) -> ProjectAccessBinding | None:
        if self.auth_context.platform_admin:
            return None
        binding = await self.project_access_binding(project)
        if binding is None:
            raise KeyError(f"Project {project.project_id} not found")
        effective_permissions = PROJECT_ROLE_BASE_PERMISSIONS.get(binding.role, ())
        if permission not in effective_permissions:
            raise PermissionError(f"Project permission {permission!r} required")
        return binding

    async def identity_payload(self) -> dict[str, Any]:
        return {
            "principal_type": self.auth_context.principal_type,
            "user_id": str(self.auth_context.user_id) if self.auth_context.user_id else None,
            "agent_identity_id": (
                str(self.auth_context.agent_identity_id) if self.auth_context.agent_identity_id else None
            ),
            "system_agent_id": (
                str(self.auth_context.system_agent_id) if self.auth_context.system_agent_id else None
            ),
            "issuer": self.auth_context.issuer,
            "subject": self.auth_context.subject,
            "client_id": self.auth_context.client_id,
            "display_name": self.auth_context.display_name,
            "platform_admin": self.auth_context.platform_admin,
            "active_scope": _scope_payload(self.session),
        }

    async def permissions_payload(self) -> dict[str, Any]:
        resolution = await self.current_resolution()
        return {
            "active_scope": _scope_payload(self.session),
            "identity_permissions": sorted(resolution.identity_permissions),
            "workspace_permissions": sorted(resolution.workspace_permissions),
            "organization_member": resolution.organization_member,
            "workspace_participant_id": (
                str(resolution.workspace_participant.participant_id)
                if resolution.workspace_participant is not None
                else None
            ),
        }

    async def list_scope_candidates(self) -> list[McpScopeCandidate]:
        if self._scope_candidates is not None:
            return self._scope_candidates

        candidates: list[McpScopeCandidate] = []
        global_resolution = await authorization_engine.compute_effective_permissions(self.auth_context)
        if self.auth_context.platform_admin or global_resolution.identity_permissions:
            candidates.append(McpScopeCandidate(kind="global", label="Global"))

        organizations: list[Organization] = []
        if self.auth_context.principal_type == "human":
            user_id = None if self.auth_context.platform_admin else self.auth_context.user_id
            organizations = await collab_svc.collaboration_service.list_organizations(user_id=user_id)
        else:
            organization_ids: set[UUID] = set()
            if self.auth_context.agent_identity_id is not None:
                identity = await collab_svc.collaboration_service.get_agent_identity(
                    self.auth_context.agent_identity_id
                )
                if identity is not None and identity.organization_id is not None:
                    organization_ids.add(identity.organization_id)
                roles = await collab_svc.collaboration_service.list_agent_roles_for_identity(
                    agent_identity_id=self.auth_context.agent_identity_id
                )
                organization_ids.update(
                    role.organization_id
                    for role in roles
                    if role.scope == "organization" and role.organization_id is not None
                )
            if (
                self.auth_context.platform_admin
                or "organization.read" in global_resolution.identity_permissions
            ):
                organizations = await collab_svc.collaboration_service.list_organizations()
            else:
                organizations = [
                    await collab_svc.collaboration_service.get_organization(organization_id)
                    for organization_id in sorted(organization_ids, key=str)
                ]

        seen_orgs: set[UUID] = set()
        visible_organizations: list[Organization] = []
        for organization in organizations:
            if organization.organization_id in seen_orgs:
                continue
            seen_orgs.add(organization.organization_id)
            visible_organizations.append(organization)
            candidates.append(
                McpScopeCandidate(
                    kind="organization",
                    id=organization.organization_id,
                    label=organization.name,
                )
            )

        projects = await self._list_project_scope_candidates(visible_organizations)
        seen_projects: set[UUID] = set()
        for project in projects:
            if project.project_id in seen_projects:
                continue
            seen_projects.add(project.project_id)
            candidates.append(
                McpScopeCandidate(
                    kind="project",
                    id=project.project_id,
                    label=project.name,
                    organization_id=project.organization_id,
                )
            )

        workspaces = await self._list_workspace_scope_candidates(organizations)
        seen_workspaces: set[UUID] = set()
        for workspace in workspaces:
            if workspace.workspace_id in seen_workspaces:
                continue
            seen_workspaces.add(workspace.workspace_id)
            candidates.append(
                McpScopeCandidate(
                    kind="workspace",
                    id=workspace.workspace_id,
                    label=workspace.name,
                    organization_id=workspace.organization_id,
                    project_id=workspace.project_id,
                )
            )

        self._scope_candidates = sorted(
            candidates,
            key=lambda item: (item.kind, item.label.lower(), str(item.id) if item.id else ""),
        )
        return self._scope_candidates

    async def _list_project_scope_candidates(
        self,
        organizations: list[Organization],
    ) -> list[Project]:
        projects: list[Project] = []
        for organization in organizations:
            try:
                await authorization_engine.authorize(
                    "mcp.projects.list",
                    {
                        "auth_context": self.auth_context,
                        "permission_type": "identity",
                        "permission": "project.read",
                        "organization_id": organization.organization_id,
                        "workspace_id": None,
                    },
                )
            except Exception:
                continue
            projects.extend(
                await collab_svc.collaboration_service.list_projects(
                    organization.organization_id
                )
            )
        return projects

    async def _list_workspace_scope_candidates(
        self,
        organizations: list[Organization],
    ) -> list[Workspace]:
        if self.auth_context.principal_type == "human":
            user_id = None if self.auth_context.platform_admin else self.auth_context.user_id
            return await collab_svc.collaboration_service.list_workspaces(user_id=user_id)

        if self.auth_context.system_agent_id is None:
            return []

        if not organizations:
            workspaces = await collab_svc.collaboration_service.list_workspaces(
                system_agent_id=self.auth_context.system_agent_id,
                organization_id=None,
            )
        else:
            workspaces = []
            for organization in organizations:
                workspaces.extend(
                    await collab_svc.collaboration_service.list_workspaces(
                        system_agent_id=self.auth_context.system_agent_id,
                        organization_id=organization.organization_id,
                    )
                )

        attached: list[Workspace] = []
        for workspace in workspaces:
            try:
                await collab_svc.collaboration_service.resolve_authenticated_agent_actor(
                    workspace_id=workspace.workspace_id,
                    auth_context=self.auth_context,
                )
            except Exception:
                continue
            attached.append(workspace)
        return attached

    async def set_scope(self, args: SessionSetScopeArgs) -> dict[str, Any]:
        candidates = await self.list_scope_candidates()
        if args.scope == "global":
            target_id = None
        elif args.scope == "organization":
            if args.organization_id is None or args.project_id is not None or args.workspace_id is not None:
                raise ValueError("organization scope requires organization_id and forbids project_id/workspace_id")
            target_id = args.organization_id
        elif args.scope == "project":
            if args.project_id is None or args.organization_id is not None or args.workspace_id is not None:
                raise ValueError("project scope requires project_id and forbids organization_id/workspace_id")
            target_id = args.project_id
        else:
            if args.workspace_id is None or args.organization_id is not None or args.project_id is not None:
                raise ValueError("workspace scope requires workspace_id and forbids organization_id/project_id")
            target_id = args.workspace_id

        if args.scope != "global":
            if not any(item.kind == args.scope and item.id == target_id for item in candidates):
                raise PermissionError(f"Scope {args.scope}:{target_id} is not available to this principal")

        if self.session.active_scope_kind != args.scope or self.session.active_scope_id != target_id:
            self.scope_changed = True
        self.session = self.session.model_copy(
            update={
                "active_scope_kind": args.scope,
                "active_scope_id": target_id,
                "updated_at": datetime.now(UTC),
            }
        )
        self._resolution = None
        await save_mcp_session(self.session)
        return _scope_payload(self.session)


def _type_schema(tp: Any) -> dict[str, Any]:
    return TypeAdapter(tp).json_schema()


def _operation_registry() -> dict[str, OperationDefinition]:
    return {
        "session.get_identity": OperationDefinition(
            name="session.get_identity",
            description="Return the authenticated Open Talon principal bound to the MCP session.",
            input_model=EmptyArgs,
            output_schema=_type_schema(dict[str, Any]),
            allowed_scopes=frozenset({"global", "organization", "project", "workspace"}),
            required_permission_type=None,
            required_permission=None,
            handler_name="handle_session_get_identity",
        ),
        "session.get_permissions": OperationDefinition(
            name="session.get_permissions",
            description="Return effective Open Talon permissions in the current MCP scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(dict[str, Any]),
            allowed_scopes=frozenset({"global", "organization", "project", "workspace"}),
            required_permission_type=None,
            required_permission=None,
            handler_name="handle_session_get_permissions",
        ),
        "session.list_scopes": OperationDefinition(
            name="session.list_scopes",
            description="List global, organization, project, and workspace scopes available to this principal.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[McpScopeCandidate]),
            allowed_scopes=frozenset({"global", "organization", "project", "workspace"}),
            required_permission_type=None,
            required_permission=None,
            handler_name="handle_session_list_scopes",
        ),
        "session.set_scope": OperationDefinition(
            name="session.set_scope",
            description="Set the active Open Talon scope for subsequent MCP API operations.",
            input_model=SessionSetScopeArgs,
            output_schema=_type_schema(dict[str, Any]),
            allowed_scopes=frozenset({"global", "organization", "project", "workspace"}),
            required_permission_type=None,
            required_permission=None,
            handler_name="handle_session_set_scope",
        ),
        "organizations.list": OperationDefinition(
            name="organizations.list",
            description="List organizations visible in the current scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[Organization]),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="organization.read",
            handler_name="handle_organizations_list",
        ),
        "organizations.get": OperationDefinition(
            name="organizations.get",
            description="Return the active organization in organization scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(Organization),
            allowed_scopes=frozenset({"organization"}),
            required_permission_type="identity",
            required_permission="organization.read",
            handler_name="handle_organizations_get",
        ),
        "organizations.members.list": OperationDefinition(
            name="organizations.members.list",
            description="List organization memberships for the active organization.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[OrganizationMembership]),
            allowed_scopes=frozenset({"organization"}),
            required_permission_type="identity",
            required_permission="organization.members.read",
            handler_name="handle_organizations_members_list",
        ),
        "projects.list": OperationDefinition(
            name="projects.list",
            description="List projects inside the active organization scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[Project]),
            allowed_scopes=frozenset({"organization", "project"}),
            required_permission_type="identity",
            required_permission="project.read",
            required_project_permission="project.read",
            handler_name="handle_projects_list",
        ),
        "projects.create": OperationDefinition(
            name="projects.create",
            description="Create a project inside the active organization scope.",
            input_model=ProjectCreateArgs,
            output_schema=_type_schema(Project),
            allowed_scopes=frozenset({"organization"}),
            required_permission_type="identity",
            required_permission="project.write",
            handler_name="handle_projects_create",
        ),
        "projects.get": OperationDefinition(
            name="projects.get",
            description="Return project detail for a project in the active organization or project scope.",
            input_model=ProjectRefArgs,
            output_schema=_type_schema(Project),
            allowed_scopes=frozenset({"organization", "project"}),
            required_permission_type="identity",
            required_permission="project.read",
            required_project_permission="project.read",
            handler_name="handle_projects_get",
        ),
        "projects.update": OperationDefinition(
            name="projects.update",
            description="Update project metadata for a project in the active organization or project scope.",
            input_model=ProjectUpdateArgs,
            output_schema=_type_schema(Project),
            allowed_scopes=frozenset({"organization", "project"}),
            required_permission_type="identity",
            required_permission="project.read",
            required_project_permission="project.write",
            handler_name="handle_projects_update",
        ),
        "projects.access.list": OperationDefinition(
            name="projects.access.list",
            description="List project access bindings for a project in the active organization or project scope.",
            input_model=ProjectAccessListArgs,
            output_schema=_type_schema(list[ProjectAccessBinding]),
            allowed_scopes=frozenset({"organization", "project"}),
            required_permission_type="identity",
            required_permission="project.read",
            required_project_permission="project.read",
            handler_name="handle_projects_access_list",
        ),
        "projects.access.upsert": OperationDefinition(
            name="projects.access.upsert",
            description="Create or update a project access binding.",
            input_model=ProjectAccessUpsertArgs,
            output_schema=_type_schema(ProjectAccessBinding),
            allowed_scopes=frozenset({"organization", "project"}),
            required_permission_type="identity",
            required_permission="project.read",
            required_project_permission="project.access.write",
            handler_name="handle_projects_access_upsert",
        ),
        "projects.access.remove": OperationDefinition(
            name="projects.access.remove",
            description="Remove a project access binding.",
            input_model=ProjectAccessRemoveArgs,
            output_schema=_type_schema(dict[str, Any]),
            allowed_scopes=frozenset({"organization", "project"}),
            required_permission_type="identity",
            required_permission="project.read",
            required_project_permission="project.access.write",
            handler_name="handle_projects_access_remove",
        ),
        "workspaces.list": OperationDefinition(
            name="workspaces.list",
            description="List workspaces accessible in the current global, organization, project, or workspace scope.",
            input_model=WorkspaceListArgs,
            output_schema=_type_schema(list[Workspace]),
            allowed_scopes=frozenset({"global", "organization", "project", "workspace"}),
            required_permission_type="identity",
            required_permission="workspace.list",
            required_project_permission="workspace.list",
            handler_name="handle_workspaces_list",
        ),
        "workspaces.create": OperationDefinition(
            name="workspaces.create",
            description="Create a workspace in the active organization or project scope.",
            input_model=WorkspaceCreateArgs,
            output_schema=_type_schema(WorkspaceDetail),
            allowed_scopes=frozenset({"organization", "project"}),
            required_permission_type="identity",
            required_permission="workspace.list",
            required_project_permission="workspace.create",
            handler_name="handle_workspaces_create",
        ),
        "workspaces.get": OperationDefinition(
            name="workspaces.get",
            description="Return the active workspace detail in workspace scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(WorkspaceDetail),
            allowed_scopes=frozenset({"workspace"}),
            required_permission_type="identity",
            required_permission="workspace.read",
            requires_workspace_actor=True,
            handler_name="handle_workspaces_get",
        ),
        "threads.create": OperationDefinition(
            name="threads.create",
            description="Create a thread in the active workspace.",
            input_model=ThreadCreateArgs,
            output_schema=_type_schema(ThreadDetail),
            allowed_scopes=frozenset({"workspace"}),
            required_permission_type="identity",
            required_permission="workspace.read",
            requires_workspace_actor=True,
            handler_name="handle_threads_create",
        ),
        "threads.list": OperationDefinition(
            name="threads.list",
            description="List threads in the active workspace.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[Thread]),
            allowed_scopes=frozenset({"workspace"}),
            required_permission_type="identity",
            required_permission="workspace.read",
            requires_workspace_actor=True,
            handler_name="handle_threads_list",
        ),
        "threads.get": OperationDefinition(
            name="threads.get",
            description="Return thread detail for a thread inside the active workspace.",
            input_model=ThreadRefArgs,
            output_schema=_type_schema(ThreadDetail),
            allowed_scopes=frozenset({"workspace"}),
            required_permission_type="identity",
            required_permission="workspace.read",
            requires_workspace_actor=True,
            handler_name="handle_threads_get",
        ),
        "threads.timeline.get": OperationDefinition(
            name="threads.timeline.get",
            description="Return the timeline for a thread inside the active workspace.",
            input_model=ThreadRefArgs,
            output_schema=_type_schema(TimelinePage),
            allowed_scopes=frozenset({"workspace"}),
            required_permission_type="identity",
            required_permission="workspace.read",
            requires_workspace_actor=True,
            handler_name="handle_threads_timeline_get",
        ),
        "threads.messages.create": OperationDefinition(
            name="threads.messages.create",
            description="Post a message to a thread inside the active workspace.",
            input_model=ThreadMessageCreateArgs,
            output_schema=_type_schema(TimelineMessage),
            allowed_scopes=frozenset({"workspace"}),
            required_permission_type="identity",
            required_permission="workspace.read",
            requires_workspace_actor=True,
            handler_name="handle_threads_messages_create",
        ),
        "memory.workspace.list": OperationDefinition(
            name="memory.workspace.list",
            description="List workspace memory entries for the active workspace.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[MemoryEntry]),
            allowed_scopes=frozenset({"workspace"}),
            required_permission_type="identity",
            required_permission="workspace.read",
            requires_workspace_actor=True,
            handler_name="handle_memory_workspace_list",
        ),
        "memory.workspace.create": OperationDefinition(
            name="memory.workspace.create",
            description="Create a workspace memory entry in the active workspace.",
            input_model=WorkspaceMemoryCreateArgs,
            output_schema=_type_schema(MemoryEntry),
            allowed_scopes=frozenset({"workspace"}),
            required_permission_type="identity",
            required_permission="workspace.read",
            requires_workspace_actor=True,
            handler_name="handle_memory_workspace_create",
        ),
        "memory.thread.search": OperationDefinition(
            name="memory.thread.search",
            description="Search confirmed thread memory for a thread inside the active workspace.",
            input_model=ThreadMemorySearchArgs,
            output_schema=_type_schema(MemorySearchResponse),
            allowed_scopes=frozenset({"workspace"}),
            required_permission_type="identity",
            required_permission="workspace.read",
            requires_workspace_actor=True,
            handler_name="handle_memory_thread_search",
        ),
        "agent_catalog.list": OperationDefinition(
            name="agent_catalog.list",
            description="List system agents in the current global or organization scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[AgentDefinition]),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="agent_catalog.read",
            handler_name="handle_agent_catalog_list",
        ),
        "agent_catalog.bundle.validate": OperationDefinition(
            name="agent_catalog.bundle.validate",
            description="Validate a Git-managed agent bundle in the current global or organization scope.",
            input_model=AgentBundleGitArgs,
            output_schema=_type_schema(AgentBundleValidationResult),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="agent_catalog.write",
            handler_name="handle_agent_catalog_bundle_validate",
        ),
        "agent_catalog.bundle.publish": OperationDefinition(
            name="agent_catalog.bundle.publish",
            description="Publish a Git-managed agent bundle in the current global or organization scope.",
            input_model=AgentBundleGitArgs,
            output_schema=_type_schema(AgentBundlePublishResult),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="agent_catalog.write",
            handler_name="handle_agent_catalog_bundle_publish",
        ),
        "tool_catalog.list": OperationDefinition(
            name="tool_catalog.list",
            description="List system tools in the current global or organization scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[SystemToolDefinition]),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="tool_catalog.read",
            handler_name="handle_tool_catalog_list",
        ),
        "llm_providers.list": OperationDefinition(
            name="llm_providers.list",
            description="List LLM provider records in the current global or organization scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[LlmProviderDefinition]),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="provider.llm.read",
            handler_name="handle_llm_providers_list",
        ),
        "memory_providers.list": OperationDefinition(
            name="memory_providers.list",
            description="List memory provider records in the current global or organization scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[MemoryProviderDefinition]),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="provider.memory.read",
            handler_name="handle_memory_providers_list",
        ),
        "mcp_servers.list": OperationDefinition(
            name="mcp_servers.list",
            description="List MCP server records in the current global or organization scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[McpServerDefinition]),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="provider.mcp.read",
            handler_name="handle_mcp_servers_list",
        ),
        "runtime.overview.get": OperationDefinition(
            name="runtime.overview.get",
            description="Return runtime queue, failure, and token overview for the current scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(dict[str, Any]),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="organization.runtime.read",
            handler_name="handle_runtime_overview_get",
        ),
        "audit.events.list": OperationDefinition(
            name="audit.events.list",
            description="List audit events for the current or provided authorized scope.",
            input_model=AuditEventsListArgs,
            output_schema=_type_schema(AuditEventPage),
            allowed_scopes=frozenset({"global", "organization", "workspace"}),
            required_permission_type="identity",
            required_permission="audit.read",
            handler_name="handle_audit_events_list",
        ),
        "audit.chains.verify": OperationDefinition(
            name="audit.chains.verify",
            description="Verify audit chain integrity for the current or provided authorized chain partition.",
            input_model=AuditChainVerifyArgs,
            output_schema=_type_schema(AuditChainVerificationResult),
            allowed_scopes=frozenset({"global", "organization", "workspace"}),
            required_permission_type="identity",
            required_permission="audit.verify",
            handler_name="handle_audit_chains_verify",
        ),
        "agent_git.repo.ensure": OperationDefinition(
            name="agent_git.repo.ensure",
            description="Register or update a Git repository for agent definition authoring.",
            input_model=AgentGitRepoEnsureArgs,
            output_schema=_type_schema(GitRepository),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="git_registry.write",
            handler_name="handle_agent_git_repo_ensure",
        ),
        "agent_git.worktree.create": OperationDefinition(
            name="agent_git.worktree.create",
            description="Create a managed Git worktree session for agent definition authoring.",
            input_model=AgentGitWorktreeCreateArgs,
            output_schema=_type_schema(AgentGitWorktreeSession),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="agent_catalog.write",
            handler_name="handle_agent_git_worktree_create",
        ),
        "agent_git.file.read": OperationDefinition(
            name="agent_git.file.read",
            description="Read a file from a managed agent-authoring Git worktree.",
            input_model=AgentGitWorktreeFileArgs,
            output_schema=_type_schema(AgentGitFileContent),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="agent_catalog.write",
            handler_name="handle_agent_git_file_read",
        ),
        "agent_git.file.write": OperationDefinition(
            name="agent_git.file.write",
            description="Write a file in a managed agent-authoring Git worktree.",
            input_model=AgentGitWorktreeFileArgs,
            output_schema=_type_schema(AgentGitFileContent),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="agent_catalog.write",
            handler_name="handle_agent_git_file_write",
        ),
        "agent_git.file.delete": OperationDefinition(
            name="agent_git.file.delete",
            description="Delete a file from a managed agent-authoring Git worktree.",
            input_model=AgentGitWorktreeFileArgs,
            output_schema=_type_schema(dict[str, Any]),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="agent_catalog.write",
            handler_name="handle_agent_git_file_delete",
        ),
        "agent_git.diff.preview": OperationDefinition(
            name="agent_git.diff.preview",
            description="Preview a managed agent-authoring Git worktree diff.",
            input_model=AgentGitWorktreeRefArgs,
            output_schema=_type_schema(AgentGitDiffResult),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="agent_catalog.write",
            handler_name="handle_agent_git_diff_preview",
        ),
        "agent_git.commit.push": OperationDefinition(
            name="agent_git.commit.push",
            description="Commit and optionally push a managed agent-authoring Git worktree.",
            input_model=AgentGitWorktreeCommitArgs,
            output_schema=_type_schema(AgentGitCommitResult),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="agent_catalog.write",
            handler_name="handle_agent_git_commit_push",
        ),
        "agent_git.worktree.discard": OperationDefinition(
            name="agent_git.worktree.discard",
            description="Discard a managed agent-authoring Git worktree session.",
            input_model=AgentGitWorktreeRefArgs,
            output_schema=_type_schema(dict[str, Any]),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="agent_catalog.write",
            handler_name="handle_agent_git_worktree_discard",
        ),
        "iam.agent_identities.list": OperationDefinition(
            name="iam.agent_identities.list",
            description="List agent identities in the current global or organization scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[dict[str, Any]]),
            allowed_scopes=frozenset({"global", "organization"}),
            required_permission_type="identity",
            required_permission="organization.members.read",
            handler_name="handle_iam_agent_identities_list",
        ),
    }


OPERATION_REGISTRY = _operation_registry()


def list_resource_definitions() -> list[dict[str, Any]]:
    return [
        {
            "uri": "ot://session/identity",
            "name": "Session Identity",
            "description": "Authenticated Open Talon principal for this MCP session.",
            "mimeType": "application/json",
        },
        {
            "uri": "ot://session/permissions",
            "name": "Session Permissions",
            "description": "Effective Open Talon permissions for the current MCP scope.",
            "mimeType": "application/json",
        },
        {
            "uri": "ot://session/scope",
            "name": "Session Scope",
            "description": "Current active MCP scope.",
            "mimeType": "application/json",
        },
    ]


async def read_resource(ctx: McpApiContext, uri: str) -> dict[str, Any]:
    if uri == "ot://session/identity":
        payload = await ctx.identity_payload()
    elif uri == "ot://session/permissions":
        payload = await ctx.permissions_payload()
    elif uri == "ot://session/scope":
        payload = _scope_payload(ctx.session)
    else:
        raise KeyError(f"Unknown resource {uri!r}")
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(jsonable_encoder(payload), sort_keys=True),
            }
        ]
    }


async def handle_session_get_identity(ctx: McpApiContext, _: EmptyArgs) -> dict[str, Any]:
    return await ctx.identity_payload()


async def handle_session_get_permissions(ctx: McpApiContext, _: EmptyArgs) -> dict[str, Any]:
    return await ctx.permissions_payload()


async def handle_session_list_scopes(ctx: McpApiContext, _: EmptyArgs) -> list[dict[str, Any]]:
    scopes = await ctx.list_scope_candidates()
    return [scope.model_dump(mode="json") for scope in scopes]


async def handle_session_set_scope(ctx: McpApiContext, args: SessionSetScopeArgs) -> dict[str, Any]:
    return await ctx.set_scope(args)


async def handle_organizations_list(ctx: McpApiContext, _: EmptyArgs) -> list[Organization]:
    if ctx.active_scope_kind == "organization" and ctx.active_scope_id is not None:
        return [await collab_svc.collaboration_service.get_organization(ctx.active_scope_id)]
    if ctx.auth_context.principal_type == "human":
        user_id = None if ctx.auth_context.platform_admin else ctx.auth_context.user_id
        return await collab_svc.collaboration_service.list_organizations(user_id=user_id)
    resolution = await authorization_engine.compute_effective_permissions(ctx.auth_context)
    if ctx.auth_context.platform_admin or "organization.read" in resolution.identity_permissions:
        return await collab_svc.collaboration_service.list_organizations()
    scopes = await ctx.list_scope_candidates()
    organizations: list[Organization] = []
    for scope in scopes:
        if scope.kind == "organization" and scope.id is not None:
            organizations.append(await collab_svc.collaboration_service.get_organization(scope.id))
    return organizations


async def handle_organizations_get(ctx: McpApiContext, _: EmptyArgs) -> Organization:
    if ctx.active_scope_kind != "organization" or ctx.active_scope_id is None:
        raise ValueError("organizations.get requires an active organization scope")
    return await collab_svc.collaboration_service.get_organization(ctx.active_scope_id)


async def handle_organizations_members_list(
    ctx: McpApiContext,
    _: EmptyArgs,
) -> list[OrganizationMembership]:
    if ctx.active_scope_kind != "organization" or ctx.active_scope_id is None:
        raise ValueError("organizations.members.list requires an active organization scope")
    return await collab_svc.collaboration_service.list_organization_memberships(ctx.active_scope_id)


async def _resolve_project_arg(ctx: McpApiContext, project_id: UUID | None) -> Project:
    effective_project_id = project_id or (
        ctx.active_scope_id if ctx.active_scope_kind == "project" else None
    )
    if effective_project_id is None:
        raise ValueError("A project_id argument or active project scope is required")
    project = await collab_svc.collaboration_service.get_project(effective_project_id)
    active_org_id = await ctx.active_organization_id()
    if active_org_id is not None and project.organization_id != active_org_id:
        raise PermissionError(f"Project {project.project_id} is outside the active organization scope")
    return project


async def handle_projects_list(ctx: McpApiContext, _: EmptyArgs) -> list[Project]:
    if ctx.active_scope_kind == "project" and ctx.active_scope_id is not None:
        project = await collab_svc.collaboration_service.get_project(ctx.active_scope_id)
        return [project]
    if ctx.active_scope_kind != "organization" or ctx.active_scope_id is None:
        raise ValueError("projects.list requires an active organization or project scope")
    return await collab_svc.collaboration_service.list_projects(ctx.active_scope_id)


async def handle_projects_create(ctx: McpApiContext, args: ProjectCreateArgs) -> Project:
    if ctx.active_scope_kind != "organization" or ctx.active_scope_id is None:
        raise ValueError("projects.create requires an active organization scope")
    payload = CreateProjectRequest(actor=ctx.identity_actor(), **args.model_dump())
    return await collab_svc.collaboration_service.create_project(
        ctx.active_scope_id,
        payload,
        allow_platform_admin=ctx.auth_context.platform_admin,
    )


async def handle_projects_get(ctx: McpApiContext, args: ProjectRefArgs) -> Project:
    project = await _resolve_project_arg(ctx, args.project_id)
    await ctx.require_project_permission(project, permission="project.read")
    return project


async def handle_projects_update(ctx: McpApiContext, args: ProjectUpdateArgs) -> Project:
    project = await _resolve_project_arg(ctx, args.project_id)
    await ctx.require_project_permission(project, permission="project.write")
    payload = UpdateProjectRequest(
        actor=ctx.identity_actor(),
        **args.model_dump(exclude={"project_id"}),
    )
    return await collab_svc.collaboration_service.update_project(
        project.organization_id,
        project.project_id,
        payload,
        allow_platform_admin=ctx.auth_context.platform_admin,
    )


async def handle_projects_access_list(
    ctx: McpApiContext,
    args: ProjectAccessListArgs,
) -> list[ProjectAccessBinding]:
    project = await _resolve_project_arg(ctx, args.project_id)
    await ctx.require_project_permission(project, permission="project.read")
    return await collab_svc.collaboration_service.list_project_access(
        project.organization_id,
        project.project_id,
        actor=None,
        allow_platform_admin=True,
    )


async def handle_projects_access_upsert(
    ctx: McpApiContext,
    args: ProjectAccessUpsertArgs,
) -> ProjectAccessBinding:
    project = await _resolve_project_arg(ctx, args.project_id)
    await ctx.require_project_permission(project, permission="project.access.write")
    payload = UpsertProjectAccessRequest(
        actor=ctx.identity_actor(),
        **args.model_dump(exclude={"project_id"}),
    )
    return await collab_svc.collaboration_service.upsert_project_access(
        project.organization_id,
        project.project_id,
        payload,
        allow_platform_admin=ctx.auth_context.platform_admin,
    )


async def handle_projects_access_remove(
    ctx: McpApiContext,
    args: ProjectAccessRemoveArgs,
) -> dict[str, Any]:
    project = await _resolve_project_arg(ctx, args.project_id)
    await ctx.require_project_permission(project, permission="project.access.write")
    payload = RemoveProjectAccessRequest(
        actor=ctx.identity_actor(),
        **args.model_dump(exclude={"project_id"}),
    )
    return await collab_svc.collaboration_service.remove_project_access(
        project.organization_id,
        project.project_id,
        payload,
        allow_platform_admin=ctx.auth_context.platform_admin,
    )


async def handle_workspaces_list(ctx: McpApiContext, args: WorkspaceListArgs) -> list[Workspace]:
    if ctx.active_scope_kind == "workspace" and ctx.active_scope_id is not None:
        detail = await collab_svc.collaboration_service.get_workspace(ctx.active_scope_id)
        return [detail.workspace]
    organization_id = await ctx.active_organization_id()
    project_id = args.project_id or (
        ctx.active_scope_id if ctx.active_scope_kind == "project" else None
    )
    if project_id is not None:
        project = await _resolve_project_arg(ctx, project_id)
        await ctx.require_project_permission(project, permission="workspace.list")
        organization_id = project.organization_id
    if ctx.auth_context.principal_type == "human":
        user_id = None if ctx.auth_context.platform_admin else ctx.auth_context.user_id
        return await collab_svc.collaboration_service.list_workspaces(
            user_id=user_id,
            organization_id=organization_id,
            project_id=project_id,
        )
    if ctx.auth_context.system_agent_id is None and not ctx.auth_context.platform_admin:
        return []
    return await collab_svc.collaboration_service.list_workspaces(
        system_agent_id=None
        if ctx.auth_context.platform_admin
        else ctx.auth_context.system_agent_id,
        organization_id=organization_id,
        project_id=project_id,
    )


async def handle_workspaces_create(ctx: McpApiContext, args: WorkspaceCreateArgs) -> WorkspaceDetail:
    organization_id = await ctx.active_organization_id()
    if organization_id is None:
        raise ValueError("workspaces.create requires an active organization or project scope")
    project_id = args.project_id or (
        ctx.active_scope_id if ctx.active_scope_kind == "project" else None
    )
    if project_id is not None:
        project = await _resolve_project_arg(ctx, project_id)
        await ctx.require_project_permission(project, permission="workspace.create")
        organization_id = project.organization_id
    payload = CreateWorkspaceRequest(
        actor=ctx.identity_actor(),
        organization_id=organization_id,
        project_id=project_id,
        **args.model_dump(exclude={"project_id"}),
    )
    return await collab_svc.collaboration_service.create_workspace(
        payload,
        allow_platform_admin=ctx.auth_context.platform_admin,
    )


async def handle_workspaces_get(ctx: McpApiContext, _: EmptyArgs) -> WorkspaceDetail:
    if ctx.active_scope_kind != "workspace" or ctx.active_scope_id is None:
        raise ValueError("workspaces.get requires an active workspace scope")
    await ctx.resolve_workspace_actor(auto_create=False)
    return await collab_svc.collaboration_service.get_workspace(ctx.active_scope_id)


async def handle_threads_create(ctx: McpApiContext, args: ThreadCreateArgs) -> ThreadDetail:
    if ctx.active_scope_kind != "workspace" or ctx.active_scope_id is None:
        raise ValueError("threads.create requires an active workspace scope")
    actor = await ctx.resolve_workspace_actor(auto_create=True)
    payload = CreateThreadRequest(actor=actor, **args.model_dump())
    return await collab_svc.collaboration_service.create_thread(ctx.active_scope_id, payload)


async def handle_threads_list(ctx: McpApiContext, _: EmptyArgs) -> list[Thread]:
    if ctx.active_scope_kind != "workspace" or ctx.active_scope_id is None:
        raise ValueError("threads.list requires an active workspace scope")
    await ctx.resolve_workspace_actor(auto_create=False)
    return await collab_svc.collaboration_service.list_threads(ctx.active_scope_id)


async def handle_threads_get(ctx: McpApiContext, args: ThreadRefArgs) -> ThreadDetail:
    await ctx.resolve_workspace_actor(auto_create=False)
    return await ctx.ensure_thread_in_scope(args.thread_id)


async def handle_threads_timeline_get(ctx: McpApiContext, args: ThreadRefArgs) -> TimelinePage:
    await ctx.resolve_workspace_actor(auto_create=False)
    await ctx.ensure_thread_in_scope(args.thread_id)
    return await collab_svc.collaboration_service.get_timeline(args.thread_id)


async def handle_threads_messages_create(
    ctx: McpApiContext,
    args: ThreadMessageCreateArgs,
) -> TimelineMessage:
    actor = await ctx.resolve_thread_actor(args.thread_id, auto_create=True)
    payload = CreateMessageRequest(
        actor=actor,
        **args.model_dump(exclude={"thread_id"}),
    )
    return await collab_svc.collaboration_service.post_message(args.thread_id, payload)


async def handle_memory_workspace_list(ctx: McpApiContext, _: EmptyArgs) -> list[MemoryEntry]:
    if ctx.active_scope_kind != "workspace" or ctx.active_scope_id is None:
        raise ValueError("memory.workspace.list requires an active workspace scope")
    await ctx.resolve_workspace_actor(auto_create=False)
    return await collab_svc.collaboration_service.list_memory_entries(ctx.active_scope_id)


async def handle_memory_workspace_create(
    ctx: McpApiContext,
    args: WorkspaceMemoryCreateArgs,
) -> MemoryEntry:
    if ctx.active_scope_kind != "workspace" or ctx.active_scope_id is None:
        raise ValueError("memory.workspace.create requires an active workspace scope")
    actor = await ctx.resolve_workspace_actor(auto_create=True)
    payload = CreateMemoryEntryRequest(actor=actor, **args.model_dump())
    return await collab_svc.collaboration_service.create_memory_entry(ctx.active_scope_id, payload)


async def handle_memory_thread_search(
    ctx: McpApiContext,
    args: ThreadMemorySearchArgs,
) -> MemorySearchResponse:
    actor = await ctx.resolve_thread_actor(args.thread_id, auto_create=False)
    await ctx.ensure_thread_in_scope(args.thread_id)
    return await collab_svc.collaboration_service.search_thread_memory(
        args.thread_id,
        CreateThreadMemorySearchRequest.from_args(actor, args),
    )


async def handle_agent_catalog_list(ctx: McpApiContext, _: EmptyArgs) -> list[AgentDefinition]:
    organization_id = ctx.active_scope_id if ctx.active_scope_kind == "organization" else None
    return await collab_svc.collaboration_service.list_system_agents(
        scope="organization" if organization_id is not None else "global",
        organization_id=organization_id,
    )


async def handle_tool_catalog_list(ctx: McpApiContext, _: EmptyArgs) -> list[SystemToolDefinition]:
    organization_id = ctx.active_scope_id if ctx.active_scope_kind == "organization" else None
    return await collab_svc.collaboration_service.list_system_tools(
        scope="organization" if organization_id is not None else "global",
        organization_id=organization_id,
    )


async def handle_llm_providers_list(
    ctx: McpApiContext,
    _: EmptyArgs,
) -> list[LlmProviderDefinition]:
    organization_id = ctx.active_scope_id if ctx.active_scope_kind == "organization" else None
    return await collab_svc.collaboration_service.list_llm_providers(
        scope="organization" if organization_id is not None else "global",
        organization_id=organization_id,
    )


async def handle_memory_providers_list(
    ctx: McpApiContext,
    _: EmptyArgs,
) -> list[MemoryProviderDefinition]:
    organization_id = ctx.active_scope_id if ctx.active_scope_kind == "organization" else None
    return await collab_svc.collaboration_service.list_memory_providers(
        scope="organization" if organization_id is not None else "global",
        organization_id=organization_id,
    )


async def handle_mcp_servers_list(ctx: McpApiContext, _: EmptyArgs) -> list[McpServerDefinition]:
    organization_id = ctx.active_scope_id if ctx.active_scope_kind == "organization" else None
    return await collab_svc.collaboration_service.list_mcp_servers(
        scope="organization" if organization_id is not None else "global",
        organization_id=organization_id,
    )


async def handle_runtime_overview_get(ctx: McpApiContext, _: EmptyArgs) -> dict[str, Any]:
    organization_id = ctx.active_scope_id if ctx.active_scope_kind == "organization" else None
    return await collab_svc.collaboration_service.get_runtime_overview(
        organization_id=organization_id,
    )


async def handle_audit_events_list(
    ctx: McpApiContext,
    args: AuditEventsListArgs,
) -> AuditEventPage:
    organization_id = args.organization_id
    workspace_id = args.workspace_id
    if ctx.active_scope_kind == "organization":
        active_org_id = ctx.active_scope_id
        if organization_id is None:
            organization_id = active_org_id
        elif organization_id != active_org_id:
            raise PermissionError("Requested audit organization is outside the active MCP scope")
    if ctx.active_scope_kind == "workspace":
        active_workspace_id = ctx.active_scope_id
        if workspace_id is None:
            workspace_id = active_workspace_id
        elif workspace_id != active_workspace_id:
            raise PermissionError("Requested audit workspace is outside the active MCP scope")
    return await audit_service.list_audit_events(
        AuditExportRequest(
            organization_id=organization_id,
            workspace_id=workspace_id,
            thread_id=args.thread_id,
            actor_user_id=args.actor_user_id,
            actor_system_agent_id=args.actor_system_agent_id,
            action_prefix=args.action_prefix,
            outcome=args.outcome,
            target_type=args.target_type,
            target_id=args.target_id,
            correlation_id=args.correlation_id,
            request_id=args.request_id,
            limit=args.limit,
        )
    )


async def handle_audit_chains_verify(
    ctx: McpApiContext,
    args: AuditChainVerifyArgs,
) -> AuditChainVerificationResult:
    chain_partition = args.chain_partition
    if chain_partition is None:
        if ctx.active_scope_kind == "workspace" and ctx.active_scope_id is not None:
            chain_partition = f"workspace:{ctx.active_scope_id}"
        elif ctx.active_scope_kind == "organization" and ctx.active_scope_id is not None:
            chain_partition = f"organization:{ctx.active_scope_id}"
        else:
            chain_partition = "global"
    if ctx.active_scope_kind == "organization" and ctx.active_scope_id is not None:
        expected = f"organization:{ctx.active_scope_id}"
        if chain_partition != expected:
            raise PermissionError("Requested audit chain is outside the active organization scope")
    if ctx.active_scope_kind == "workspace" and ctx.active_scope_id is not None:
        expected = f"workspace:{ctx.active_scope_id}"
        if chain_partition != expected:
            raise PermissionError("Requested audit chain is outside the active workspace scope")
    return await audit_service.verify_audit_chain(chain_partition)


async def handle_agent_catalog_bundle_validate(
    ctx: McpApiContext,
    args: AgentBundleGitArgs,
) -> AgentBundleValidationResult:
    actor = ctx.identity_actor()
    organization_id = ctx.active_scope_id if ctx.active_scope_kind == "organization" else None
    return await collab_svc.collaboration_service.validate_agent_bundle_from_git(
        scope="organization" if organization_id is not None else "global",
        organization_id=organization_id,
        payload=ValidateAgentBundleFromGitRequest(actor=actor, **args.model_dump()),
    )


async def handle_agent_catalog_bundle_publish(
    ctx: McpApiContext,
    args: AgentBundleGitArgs,
) -> AgentBundlePublishResult:
    actor = ctx.identity_actor()
    organization_id = ctx.active_scope_id if ctx.active_scope_kind == "organization" else None
    return await collab_svc.collaboration_service.publish_agent_bundle_from_git(
        scope="organization" if organization_id is not None else "global",
        organization_id=organization_id,
        payload=PublishAgentBundleFromGitRequest(actor=actor, **args.model_dump()),
    )


async def handle_agent_git_repo_ensure(
    ctx: McpApiContext,
    args: AgentGitRepoEnsureArgs,
) -> GitRepository:
    actor = ctx.identity_actor()
    organization_id = ctx.active_scope_id if ctx.active_scope_kind == "organization" else None
    return await collab_svc.collaboration_service.create_git_repository(
        scope="organization" if organization_id is not None else "global",
        organization_id=organization_id,
        workspace_id=None,
        payload=CreateGitRepositoryRequest(actor=actor, **args.model_dump()),
    )


async def handle_agent_git_worktree_create(
    ctx: McpApiContext,
    args: AgentGitWorktreeCreateArgs,
) -> AgentGitWorktreeSession:
    actor = ctx.identity_actor()
    organization_id = ctx.active_scope_id if ctx.active_scope_kind == "organization" else None
    return await collab_svc.collaboration_service.create_agent_git_worktree_session(
        scope="organization" if organization_id is not None else "global",
        organization_id=organization_id,
        payload=CreateAgentGitWorktreeSessionRequest(actor=actor, **args.model_dump()),
    )


async def handle_agent_git_file_read(
    ctx: McpApiContext,
    args: AgentGitWorktreeFileArgs,
) -> AgentGitFileContent:
    _ensure_mcp_worktree_scope(ctx, args.session_id)
    return await collab_svc.collaboration_service.read_agent_git_worktree_file(
        args.session_id,
        args.path,
    )


async def handle_agent_git_file_write(
    ctx: McpApiContext,
    args: AgentGitWorktreeFileArgs,
) -> AgentGitFileContent:
    _ensure_mcp_worktree_scope(ctx, args.session_id)
    actor = ctx.identity_actor()
    return await collab_svc.collaboration_service.write_agent_git_worktree_file(
        args.session_id,
        AgentGitFileMutationRequest(
            actor=actor,
            path=args.path,
            content=args.content,
            content_type=args.content_type,
            metadata=args.metadata,
        ),
    )


async def handle_agent_git_file_delete(
    ctx: McpApiContext,
    args: AgentGitWorktreeFileArgs,
) -> dict[str, bool | str]:
    _ensure_mcp_worktree_scope(ctx, args.session_id)
    actor = ctx.identity_actor()
    return await collab_svc.collaboration_service.delete_agent_git_worktree_file(
        args.session_id,
        AgentGitFileMutationRequest(
            actor=actor,
            path=args.path,
            content=args.content,
            content_type=args.content_type,
            metadata=args.metadata,
        ),
    )


async def handle_agent_git_diff_preview(
    ctx: McpApiContext,
    args: AgentGitWorktreeRefArgs,
) -> AgentGitDiffResult:
    _ensure_mcp_worktree_scope(ctx, args.session_id)
    return await collab_svc.collaboration_service.diff_agent_git_worktree(args.session_id)


async def handle_agent_git_commit_push(
    ctx: McpApiContext,
    args: AgentGitWorktreeCommitArgs,
) -> AgentGitCommitResult:
    _ensure_mcp_worktree_scope(ctx, args.session_id)
    actor = ctx.identity_actor()
    return await collab_svc.collaboration_service.commit_agent_git_worktree(
        args.session_id,
        AgentGitCommitRequest(
            actor=actor,
            message=args.message,
            push=args.push,
            metadata=args.metadata,
        ),
    )


async def handle_agent_git_worktree_discard(
    ctx: McpApiContext,
    args: AgentGitWorktreeRefArgs,
) -> dict[str, bool | str]:
    _ensure_mcp_worktree_scope(ctx, args.session_id)
    return await collab_svc.collaboration_service.discard_agent_git_worktree(args.session_id)


def _ensure_mcp_worktree_scope(ctx: McpApiContext, session_id: UUID) -> None:
    session = collab_svc.collaboration_service.get_agent_git_worktree_session(session_id)
    if session is None:
        raise KeyError(f"Git worktree session {session_id} not found")
    if session.scope == "organization":
        if ctx.active_scope_kind != "organization" or ctx.active_scope_id != session.organization_id:
            raise PermissionError("Git worktree session is outside the active organization scope")
    elif ctx.active_scope_kind != "global":
        raise PermissionError("System-wide Git worktree sessions require global MCP scope")


async def handle_iam_agent_identities_list(
    ctx: McpApiContext,
    _: EmptyArgs,
) -> list[dict[str, Any]]:
    if ctx.active_scope_kind == "organization" and ctx.active_scope_id is not None:
        items = await iam_service.list_agent_identities(
            scope="organization",
            organization_id=ctx.active_scope_id,
        )
    else:
        items = await iam_service.list_agent_identities(scope="global")
    return [jsonable_encoder(item) for item in items]


class CreateThreadMemorySearchRequest:
    @staticmethod
    def from_args(actor: ParticipantInput, args: ThreadMemorySearchArgs):
        from gateway_edge.models import SearchMemoryRequest

        return SearchMemoryRequest(
            actor=actor,
            query=args.query,
            limit=args.limit,
            use_provider=args.use_provider,
            include_graph=args.include_graph,
            metadata_filters=args.metadata_filters,
        )


async def dispatch_operation(
    ctx: McpApiContext,
    name: str,
    arguments: dict[str, Any] | None,
) -> Any:
    operation = OPERATION_REGISTRY.get(name)
    if operation is None:
        raise KeyError(f"Unknown operation {name!r}")
    await ctx.require_visible(operation)
    parsed = operation.input_model.model_validate(arguments or {})
    # Every operation is re-authorized on call to avoid trusting the cached tool list.
    await ctx._authorize_operation(operation)
    handler = globals()[operation.handler_name]
    return await handler(ctx, parsed)


async def list_visible_operations(ctx: McpApiContext) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for operation in sorted(OPERATION_REGISTRY.values(), key=lambda item: item.name):
        if not await ctx.operation_visible(operation):
            continue
        tools.append(
            {
                "name": operation.name,
                "title": operation.name.replace(".", " ").title(),
                "description": operation.description,
                "inputSchema": operation.input_schema,
                "outputSchema": operation.output_schema,
            }
        )
    return tools


def summarize_structured_result(name: str, payload: Any) -> str:
    if isinstance(payload, list):
        return f"{name}: returned {len(payload)} item(s)."
    if isinstance(payload, dict) and "scope" in payload:
        return f"{name}: active scope is {payload['scope']}."
    if isinstance(payload, dict) and "principal_type" in payload:
        return f"{name}: resolved principal {payload['principal_type']}."
    if isinstance(payload, dict) and "identity_permissions" in payload:
        return (
            f"{name}: {len(payload.get('identity_permissions', []))} identity permission(s) and "
            f"{len(payload.get('workspace_permissions', []))} workspace permission(s)."
        )
    if isinstance(payload, dict) and "workspace_id" in payload:
        return f"{name}: returned workspace-scoped payload."
    if isinstance(payload, dict) and "thread_id" in payload:
        return f"{name}: returned thread-scoped payload."
    return f"{name}: completed successfully."


def build_tool_result(name: str, payload: Any) -> dict[str, Any]:
    structured = jsonable_encoder(payload)
    return {
        "content": [{"type": "text", "text": summarize_structured_result(name, structured)}],
        "structuredContent": structured,
        "isError": False,
    }


def build_tool_error(name: str, exc: Exception) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": f"{name}: {exc}"}],
        "isError": True,
    }


async def publish_scope_change_notifications(session_id: UUID) -> None:
    await notification_hub.publish(
        session_id,
        {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"},
    )
    await notification_hub.publish(
        session_id,
        {"jsonrpc": "2.0", "method": "notifications/resources/list_changed"},
    )


def mcp_capabilities() -> dict[str, Any]:
    return {
        "tools": {"listChanged": True},
        "resources": {"listChanged": True},
    }
