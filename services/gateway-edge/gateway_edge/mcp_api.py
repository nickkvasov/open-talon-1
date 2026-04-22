from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, TypeAdapter

from gateway_edge.config import settings
from gateway_edge.iam.authorization import PermissionResolution, authorization_engine
from gateway_edge.models import (
    AuthContext,
    CreateInteractionRequest,
    CreateMemoryEntryRequest,
    CreateMessageRequest,
    CreateThreadRequest,
    MemoryEntry,
    MemorySearchResponse,
    Organization,
    OrganizationMembership,
    ParticipantInput,
    Thread,
    ThreadDetail,
    TimelineMessage,
    TimelinePage,
    Workspace,
    WorkspaceDetail,
)
from gateway_edge.services import collaboration as collab_svc
from gateway_edge.services.iam import iam_service
from gateway_edge.services.session import get_redis

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SERVER_INFO = {
    "name": "open-talon-mcp-api",
    "title": "Open Talon MCP API",
    "version": "0.1.0",
}
_MCP_SESSION_PREFIX = "mcp:sessions:"


class EmptyArgs(BaseModel):
    model_config = {"extra": "forbid"}


class SessionSetScopeArgs(BaseModel):
    scope: Literal["global", "organization", "workspace"]
    organization_id: UUID | None = None
    workspace_id: UUID | None = None


class ThreadRefArgs(BaseModel):
    thread_id: UUID


class ThreadMessageCreateArgs(BaseModel):
    thread_id: UUID
    content: str
    visibility: str = "public"
    target_system_agent_id: UUID | None = None
    target_tool_scope: str | None = None
    create_task: bool = True
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


class McpScopeCandidate(BaseModel):
    kind: Literal["global", "organization", "workspace"]
    id: UUID | None = None
    label: str
    organization_id: UUID | None = None


class McpSessionState(BaseModel):
    session_id: UUID
    principal_fingerprint: str
    principal_type: Literal["human", "agent"]
    active_scope_kind: Literal["global", "organization", "workspace"] = "global"
    active_scope_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OperationDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    output_schema: dict[str, Any]
    allowed_scopes: frozenset[Literal["global", "organization", "workspace"]]
    required_permission_type: Literal["identity", "workspace"] | None
    required_permission: str | None
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
    field = "organization_id" if session.active_scope_kind == "organization" else "workspace_id"
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
    def active_scope_kind(self) -> Literal["global", "organization", "workspace"]:
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
        if self.active_scope_kind == "workspace" and self.active_scope_id is not None:
            detail = await collab_svc.collaboration_service.get_workspace(self.active_scope_id)
            return detail.workspace.organization_id
        return None

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
        for organization in organizations:
            if organization.organization_id in seen_orgs:
                continue
            seen_orgs.add(organization.organization_id)
            candidates.append(
                McpScopeCandidate(
                    kind="organization",
                    id=organization.organization_id,
                    label=organization.name,
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
                )
            )

        self._scope_candidates = sorted(
            candidates,
            key=lambda item: (item.kind, item.label.lower(), str(item.id) if item.id else ""),
        )
        return self._scope_candidates

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
                user_id=None,
                organization_id=None,
            )
        else:
            workspaces = []
            for organization in organizations:
                workspaces.extend(
                    await collab_svc.collaboration_service.list_workspaces(
                        user_id=None,
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
            if args.organization_id is None or args.workspace_id is not None:
                raise ValueError("organization scope requires organization_id and forbids workspace_id")
            target_id = args.organization_id
        else:
            if args.workspace_id is None or args.organization_id is not None:
                raise ValueError("workspace scope requires workspace_id and forbids organization_id")
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
            allowed_scopes=frozenset({"global", "organization", "workspace"}),
            required_permission_type=None,
            required_permission=None,
            handler_name="handle_session_get_identity",
        ),
        "session.get_permissions": OperationDefinition(
            name="session.get_permissions",
            description="Return effective Open Talon permissions in the current MCP scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(dict[str, Any]),
            allowed_scopes=frozenset({"global", "organization", "workspace"}),
            required_permission_type=None,
            required_permission=None,
            handler_name="handle_session_get_permissions",
        ),
        "session.list_scopes": OperationDefinition(
            name="session.list_scopes",
            description="List global, organization, and workspace scopes available to this principal.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[McpScopeCandidate]),
            allowed_scopes=frozenset({"global", "organization", "workspace"}),
            required_permission_type=None,
            required_permission=None,
            handler_name="handle_session_list_scopes",
        ),
        "session.set_scope": OperationDefinition(
            name="session.set_scope",
            description="Set the active Open Talon scope for subsequent MCP API operations.",
            input_model=SessionSetScopeArgs,
            output_schema=_type_schema(dict[str, Any]),
            allowed_scopes=frozenset({"global", "organization", "workspace"}),
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
        "workspaces.list": OperationDefinition(
            name="workspaces.list",
            description="List workspaces accessible in the current global, organization, or workspace scope.",
            input_model=EmptyArgs,
            output_schema=_type_schema(list[Workspace]),
            allowed_scopes=frozenset({"global", "organization", "workspace"}),
            required_permission_type="identity",
            required_permission="workspace.list",
            handler_name="handle_workspaces_list",
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


async def handle_workspaces_list(ctx: McpApiContext, _: EmptyArgs) -> list[Workspace]:
    if ctx.active_scope_kind == "workspace" and ctx.active_scope_id is not None:
        detail = await collab_svc.collaboration_service.get_workspace(ctx.active_scope_id)
        return [detail.workspace]
    organization_id = ctx.active_scope_id if ctx.active_scope_kind == "organization" else None
    if ctx.auth_context.principal_type == "human":
        user_id = None if ctx.auth_context.platform_admin else ctx.auth_context.user_id
        return await collab_svc.collaboration_service.list_workspaces(
            user_id=user_id,
            organization_id=organization_id,
        )
    scopes = await ctx.list_scope_candidates()
    visible_workspace_ids = {
        scope.id
        for scope in scopes
        if scope.kind == "workspace"
        and scope.id is not None
        and (organization_id is None or scope.organization_id == organization_id)
    }
    workspaces = await collab_svc.collaboration_service.list_workspaces(
        user_id=None,
        organization_id=organization_id,
    )
    return [workspace for workspace in workspaces if workspace.workspace_id in visible_workspace_ids]


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
