from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from uuid import NAMESPACE_URL, UUID, uuid5

import asyncpg

from .contracts import (
    AgentDefinition,
    AgentEndpoint,
    AgentHarness,
    AgentInternalMcpServer,
    AgentInternalToolBinding,
    AgentInteractionContract,
    AgentMemoryPolicy,
    AgentPlanningPolicy,
    AgentResponseContract,
    AgentStopPolicy,
    AgentToolUsePolicy,
    AgentValidationPolicy,
    IamRoleDefinition,
    LlmProviderDefinition,
    McpServerDefinition,
    McpToolDefinition,
    MemoryProviderDefinition,
    Organization,
    ParticipantProfile,
    Project,
    ProjectAccessBinding,
    SystemToolDefinition,
    ToolExecutionBinding,
    ToolParameterContract,
    Workspace,
)
from .repository import CollaborationRepository

DEFAULT_ORGANIZATION_ID = UUID("11111111-1111-1111-1111-111111111111")
SYSTEM_BASE_ORGANIZATION_ID = UUID("22222222-2222-2222-2222-222222222222")
REASONING_PLANNER_AGENT_ID = UUID("33333333-3333-3333-3333-333333333333")
TINKER_AGENT_ID = UUID("44444444-4444-4444-4444-444444444444")
STEWARD_AGENT_ID = UUID("44444444-4444-4444-4444-444444444445")
ANCHOR_AGENT_ID = UUID("44444444-4444-4444-4444-444444444446")
METHODOLOGIST_AGENT_ID = UUID("44444444-4444-4444-4444-444444444447")
CONDUCTOR_AGENT_ID = UUID("44444444-4444-4444-4444-444444444448")
RESEARCHER_AGENT_ID = UUID("44444444-4444-4444-4444-444444444449")
CONTROL_PLANE_MCP_SERVER_ID = UUID("66666666-6666-6666-6666-666666666666")
WEB_SEARCH_PLUGIN_MCP_SERVER_ID = UUID("66666666-6666-6666-6666-666666666667")
LIBRARY_PLUGIN_MCP_SERVER_ID = UUID("66666666-6666-6666-6666-666666666668")
RETRIEVER_PLUGIN_MCP_SERVER_ID = UUID("66666666-6666-6666-6666-666666666669")
PLATFORM_STEWARD_ROLE_ID = UUID("77777777-7777-7777-7777-777777777771")
GLOBAL_CONDUCTOR_ROLE_ID = UUID("77777777-7777-7777-7777-777777777772")
GLOBAL_RESEARCHER_ROLE_ID = UUID("77777777-7777-7777-7777-777777777773")
GLOBAL_METHODOLOGIST_ROLE_ID = UUID("77777777-7777-7777-7777-777777777774")
SYSTEM_ACTOR_ID = UUID("00000000-0000-0000-0000-000000000000")
ANCHOR_TASK_KIND = "workspace_topic_moderation"
METHODOLOGY_RESEARCH_DOSSIER_BUILD_TASK_KIND = "methodology_research_dossier_build"
METHODOLOGY_RESEARCH_DOSSIER_REFINE_TASK_KIND = "methodology_research_dossier_refine"
METHODOLOGY_BLUEPRINT_DRAFT_TASK_KIND = "methodology_blueprint_draft"
METHODICS_EXECUTION_START_TASK_KIND = "methodics_execution_start"
METHODICS_STEP_COORDINATE_TASK_KIND = "methodics_step_coordinate"
METHODICS_STEP_VERIFY_TASK_KIND = "methodics_step_verify"
METHODICS_RESOURCE_REVIEW_TASK_KIND = "methodics_resource_review"
SEEDED_AGENT_PROFILE_VERSION = 1
ANCHOR_ROLE = "workspace topic alignment reviewer"
ANCHOR_CAPABILITIES = [
    "reviews messages for alignment with the workspace topic",
    "applies strict balanced or open topic-freedom policy",
    "blocks off-topic messages before publication in strict workspaces",
    "flags conversation drift after publication in balanced and open workspaces",
    "privately explains blocked messages to the issuer when enabled",
]


def _seeded_agent_profile(
    *,
    kind: str,
    mandate: str,
    activation: str,
    authority: list[str],
    boundaries: list[str],
    primary_inputs: list[str] | None = None,
    primary_outputs: list[str] | None = None,
    handoffs: list[str] | None = None,
    knowledge_layer: str | None = None,
) -> dict[str, object]:
    profile: dict[str, object] = {
        "profile_version": SEEDED_AGENT_PROFILE_VERSION,
        "kind": kind,
        "mandate": mandate,
        "activation": activation,
        "authority": authority,
        "boundaries": boundaries,
    }
    if primary_inputs:
        profile["primary_inputs"] = primary_inputs
    if primary_outputs:
        profile["primary_outputs"] = primary_outputs
    if handoffs:
        profile["handoffs"] = handoffs
    if knowledge_layer:
        profile["knowledge_layer"] = knowledge_layer
    return profile


def _default_reasoning_model() -> str:
    return os.getenv("OPEN_TALON_DEFAULT_REASONING_MODEL", "gemma4:31b")

_OPERATIONAL_AGENT_PERMISSIONS = [
    "organization.read",
    "organization.members.read",
    "project.read",
    "project.write",
    "workspace.list",
    "workspace.read",
    "organization.runtime.read",
    "agent_catalog.read",
    "agent_catalog.write",
    "tool_catalog.read",
    "tool_catalog.write",
    "provider.llm.read",
    "provider.llm.write",
    "provider.llm.validate",
    "provider.memory.read",
    "provider.memory.write",
    "provider.memory.validate",
    "provider.mcp.read",
    "provider.mcp.write",
    "provider.mcp.validate",
    "git_registry.read",
    "git_registry.write",
    "asset_catalog.read",
    "asset_catalog.publish",
    "asset_catalog.link",
    "asset_catalog.activate",
    "library.read",
    "library.write",
    "library.attach",
    "library.index",
    "retrieval.read",
    "retrieval.write",
    "retrieval.search",
    "retrieval.admin",
    "methodology.read",
    "methodology.write",
    "methodics.read",
    "methodics.execute",
    "methodics.admin",
    "tool_generation.read",
    "tool_generation.review",
    "audit.read",
    "audit.verify",
]
_STEWARD_AGENT_PERMISSIONS = list(
    dict.fromkeys([*_OPERATIONAL_AGENT_PERMISSIONS, "organization.write"])
)
_CURATOR_AGENT_PERMISSIONS = list(_OPERATIONAL_AGENT_PERMISSIONS)
_CONDUCTOR_AGENT_PERMISSIONS = [
    "workspace.read",
    "retrieval.read",
    "retrieval.search",
    "methodics.read",
    "methodics.execute",
]
_RESEARCHER_AGENT_PERMISSIONS = [
    "organization.read",
    "project.read",
    "workspace.list",
    "workspace.read",
    "library.read",
    "library.write",
    "library.index",
    "retrieval.read",
    "retrieval.search",
    "methodology.read",
    "methodology.write",
]
_METHODOLOGIST_AGENT_PERMISSIONS = [
    "organization.read",
    "workspace.read",
    "library.read",
    "retrieval.read",
    "retrieval.search",
    "methodology.read",
    "methodology.write",
]

_CURATOR_CONTROL_PLANE_ALLOWLIST = [
    "session.get_identity",
    "session.get_permissions",
    "session.list_scopes",
    "session.set_scope",
    "organizations.get",
    "organizations.members.list",
    "projects.list",
    "projects.create",
    "projects.get",
    "projects.update",
    "projects.access.list",
    "projects.access.upsert",
    "workspaces.list",
    "workspaces.create",
    "workspaces.get",
    "threads.create",
    "threads.list",
    "threads.get",
    "threads.timeline.get",
    "threads.messages.create",
    "memory.workspace.list",
    "memory.workspace.create",
    "memory.thread.search",
    "methodics.executions.list",
    "methodics.executions.get",
    "agent_catalog.list",
    "agent_catalog.bundle.validate",
    "agent_catalog.bundle.publish",
    "tool_catalog.list",
    "llm_providers.list",
    "memory_providers.list",
    "mcp_servers.list",
    "runtime.overview.get",
    "audit.events.list",
    "audit.chains.verify",
    "agent_git.repo.ensure",
    "agent_git.worktree.create",
    "agent_git.file.read",
    "agent_git.file.write",
    "agent_git.diff.preview",
    "agent_git.commit.push",
    "iam.agent_identities.list",
]
_CONDUCTOR_CONTROL_PLANE_ALLOWLIST = [
    "session.get_identity",
    "session.get_permissions",
    "session.list_scopes",
    "session.set_scope",
    "workspaces.get",
    "threads.create",
    "threads.list",
    "threads.get",
    "threads.timeline.get",
    "threads.messages.create",
    "memory.workspace.list",
    "memory.workspace.create",
    "memory.thread.search",
    "retrieval.corpora.list",
    "retrieval.sources.list",
    "retrieval.search",
    "retrieval.context_pack.create",
    "retrieval.context_pack.get",
    "methodics.executions.list",
    "methodics.executions.get",
    "methodics.resource_requests.create",
    "methodics.assignments.create",
    "methodics.steps.evaluate",
]
_RESEARCHER_CONTROL_PLANE_ALLOWLIST = [
    "session.get_identity",
    "session.get_permissions",
    "session.list_scopes",
    "session.set_scope",
    "organizations.get",
    "workspaces.list",
    "workspaces.get",
    "threads.get",
    "threads.timeline.get",
    "threads.messages.create",
    "methodology.dossiers.get",
    "methodology.dossiers.sources.create",
    "methodology.dossiers.sources.update",
    "methodology.dossiers.context_pack.attach",
    "methodology.dossiers.mark_ready",
    "methodology.dossiers.notebook.get",
    "methodology.dossiers.notes.upsert",
    "methodology.dossiers.concepts.upsert",
    "methodology.dossiers.claims.upsert",
    "methodology.dossiers.links.upsert",
    "methodology.dossiers.navigate",
    "methodology.dossiers.sync",
    "methodology.dossiers.health.submit",
]
_METHODOLOGIST_CONTROL_PLANE_ALLOWLIST = [
    "session.get_identity",
    "session.get_permissions",
    "session.list_scopes",
    "session.set_scope",
    "organizations.get",
    "workspaces.get",
    "threads.get",
    "threads.timeline.get",
    "retrieval.context_pack.get",
    "methodology.dossiers.get",
    "methodology.dossiers.notebook.get",
    "methodology.dossiers.navigate",
    "methodology.blueprints.submit_draft",
]
_METHODICS_HUMAN_CONTROL_PLANE_TOOLS = [
    "methodics.executions.create",
    "methodics.executions.cancel",
    "methodics.resource_requests.approve",
    "methodics.resource_requests.reject",
]
_STEWARD_CONTROL_PLANE_ALLOWLIST = [
    "organizations.list",
    "organizations.create",
    *_CURATOR_CONTROL_PLANE_ALLOWLIST,
]
_CONTROL_PLANE_TOOL_NAMES = list(
    dict.fromkeys(
        [
            *_STEWARD_CONTROL_PLANE_ALLOWLIST,
            *_CONDUCTOR_CONTROL_PLANE_ALLOWLIST,
            *_RESEARCHER_CONTROL_PLANE_ALLOWLIST,
            *_METHODOLOGIST_CONTROL_PLANE_ALLOWLIST,
            *_METHODICS_HUMAN_CONTROL_PLANE_TOOLS,
        ]
    )
)
_CONTROL_PLANE_TOOL_DENYLIST = [
    "agent_git.file.delete",
    "agent_git.worktree.discard",
    "projects.access.remove",
]

_LIBRARY_PLUGIN_TOOL_NAMES = [
    "library.libraries.list",
    "library.libraries.create",
    "library.libraries.get",
    "library.libraries.update",
    "library.libraries.archive",
    "library.items.list",
    "library.items.create",
    "library.items.create_text",
    "library.items.download_url",
    "library.workspace_attachments.attach",
    "library.workspace_attachments.detach",
]

_RETRIEVER_PLUGIN_TOOL_NAMES = [
    "retriever.library.index",
    "retriever.ingestion_jobs.list",
    "retriever.search",
    "retriever.context_pack.create",
    "retriever.context_pack.get",
]

_TINKER_INTERNAL_TOOL_SPECS = [
    (
        UUID("55555555-5555-5555-5555-555555555551"),
        "generated_tool_repo_bootstrap",
        "Bootstrap or refresh the generated-tools worktree for a tool-generation request.",
        "bootstrap-worktree",
        120,
        "none",
    ),
    (
        UUID("55555555-5555-5555-5555-555555555552"),
        "generated_tool_repo_write",
        "Write or patch generated tool source files inside the generated-tools repository.",
        "write-files",
        120,
        "none",
    ),
    (
        UUID("55555555-5555-5555-5555-555555555553"),
        "generated_tool_build",
        "Build a generated tool image and capture the resulting image reference and digest.",
        "build-image",
        600,
        "none",
    ),
    (
        UUID("55555555-5555-5555-5555-555555555554"),
        "generated_tool_registry_push",
        "Push a generated tool image to the configured OCI registry.",
        "push-image",
        600,
        "full",
    ),
    (
        UUID("55555555-5555-5555-5555-555555555555"),
        "generated_tool_smoke_test",
        "Run generated-tool smoke tests against the built image before approval.",
        "smoke-test",
        300,
        "none",
    ),
    (
        UUID("55555555-5555-5555-5555-555555555556"),
        "generated_tool_asset_publish",
        "Publish generated-tool source, manifest, and validation report assets.",
        "publish-assets",
        300,
        "none",
    ),
    (
        UUID("55555555-5555-5555-5555-555555555557"),
        "generated_tool_request_status_update",
        "Update tool-generation request and revision status as the generated-tool agent progresses work.",
        "update-request-status",
        60,
        "none",
    ),
    (
        UUID("55555555-5555-5555-5555-555555555558"),
        "generated_tool_registry_pull_verify",
        "Verify that a generated tool image can be pulled from the configured OCI registry by a real worker.",
        "verify-registry-pull",
        300,
        "full",
    ),
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ManagedSystemDefaultsRepairer:
    """Repairs managed seed/default records outside the generic collaboration kernel."""

    def __init__(self, repository: CollaborationRepository) -> None:
        self._repository = repository

    async def repair(self) -> dict[str, int]:
        now = _utcnow()
        summary = {
            "organizations": 0,
            "projects": 0,
            "workspaces": 0,
            "system_agents": 0,
            "system_tools": 0,
            "llm_providers": 0,
            "memory_providers": 0,
            "mcp_servers": 0,
            "mcp_tools": 0,
            "participants": 0,
            "iam_roles": 0,
            "project_access_bindings": 0,
            "internal_tool_bindings": 0,
            "internal_mcp_bindings": 0,
        }
        async with self._repository._pool.acquire() as conn:  # noqa: SLF001
            async with conn.transaction():
                control_plane, global_agents_by_key = await self._repair_global_defaults(
                    conn,
                    now=now,
                    summary=summary,
                )
                default_organization = await self._ensure_seed_organization(
                    conn,
                    slug="default",
                    fallback=Organization(
                        organization_id=DEFAULT_ORGANIZATION_ID,
                        slug="default",
                        name="Default Organization",
                        description="Backfilled default organization for legacy workspaces.",
                        created_by=SYSTEM_ACTOR_ID,
                        created_at=now,
                        updated_at=now,
                        metadata={"seeded": True, "managed": True},
                    ),
                    summary=summary,
                )
                system_base = await self._ensure_seed_organization(
                    conn,
                    slug="system-base",
                    fallback=Organization(
                        organization_id=SYSTEM_BASE_ORGANIZATION_ID,
                        slug="system-base",
                        name="System Base",
                        description="Managed organization for Open Talon platform operations.",
                        created_by=SYSTEM_ACTOR_ID,
                        created_at=now,
                        updated_at=now,
                        metadata={"seeded": True, "managed": True, "system_base": True},
                    ),
                    summary=summary,
                )
                organization_by_id = {
                    organization.organization_id: organization
                    for organization in await self._repository.list_organizations()
                }
                organization_by_id[default_organization.organization_id] = default_organization
                organization_by_id[system_base.organization_id] = system_base
                for organization in organization_by_id.values():
                    await self._repair_organization_context(
                        conn,
                        organization=organization,
                        control_plane=control_plane,
                        global_agents_by_key=global_agents_by_key,
                        now=now,
                        summary=summary,
                    )
                for workspace in await self._repository.list_workspaces():
                    await self._ensure_anchor_attached_for_workspace(
                        conn,
                        workspace.workspace_id,
                        now=now,
                    )
                    summary["participants"] += 1
        return summary

    async def _ensure_seed_organization(
        self,
        conn: asyncpg.Connection,
        *,
        slug: str,
        fallback: Organization,
        summary: dict[str, int],
    ) -> Organization:
        existing = await self._repository.fetch_organization_by_slug(slug)
        organization = existing or fallback
        repaired = organization.model_copy(
            update={
                "updated_at": _utcnow(),
                "metadata": {**organization.metadata, **fallback.metadata},
            }
        )
        await self._repository.upsert_organization(conn, repaired)
        summary["organizations"] += 1
        return repaired

    async def _repair_global_defaults(
        self,
        conn: asyncpg.Connection,
        *,
        now: datetime,
        summary: dict[str, int],
    ) -> tuple[McpServerDefinition, dict[str, AgentDefinition]]:
        for provider in await self._default_llm_providers(now=now):
            await self._repository.upsert_llm_provider(conn, provider)
            summary["llm_providers"] += 1
        for provider in await self._default_memory_providers(now=now):
            await self._repository.upsert_memory_provider(conn, provider)
            summary["memory_providers"] += 1
        global_agents = await self._default_global_agents(now=now)
        for agent in global_agents:
            await self._repository.upsert_system_agent(conn, agent)
            summary["system_agents"] += 1

        tinker = next(
            agent for agent in global_agents if agent.agent_key == "tinker"
        )
        for tool in await self._tinker_internal_tools(now=now):
            await self._repository.upsert_system_tool(conn, tool)
            await self._repository.upsert_agent_internal_tool_binding(
                conn,
                AgentInternalToolBinding(
                    system_agent_id=tinker.agent_id,
                    tool_id=tool.tool_id,
                    name=tool.name,
                    description=tool.description,
                    parameter_contract=tool.parameter_contract,
                    input_schema=tool.input_schema,
                    execution=tool.execution,
                    enabled=True,
                    attached_by=SYSTEM_ACTOR_ID,
                    attached_at=now,
                    updated_at=now,
                    metadata={"seeded": True, "managed": True},
                ),
            )
            summary["system_tools"] += 1
            summary["internal_tool_bindings"] += 1

        control_plane = await self._control_plane_mcp_server(now=now)
        await self._repository.upsert_mcp_server(conn, control_plane)
        await self._repository.replace_mcp_server_capabilities(
            conn,
            server_id=control_plane.server_id,
            tools=[
                McpToolDefinition(
                    server_id=control_plane.server_id,
                    tool_name=name,
                    display_name=name,
                    description=f"Open Talon control-plane operation {name}.",
                    capability_hash="managed",
                    discovered_at=now,
                    metadata={"seeded": True, "managed": True, "control_plane": True},
                )
                for name in _CONTROL_PLANE_TOOL_NAMES
            ],
            resources=[],
            prompts=[],
        )
        summary["mcp_servers"] += 1
        summary["mcp_tools"] += len(_CONTROL_PLANE_TOOL_NAMES)

        web_search = await self._web_search_mcp_server(now=now)
        await self._repository.upsert_mcp_server(conn, web_search)
        summary["mcp_servers"] += 1

        library_plugin = await self._library_mcp_server(now=now)
        await self._repository.upsert_mcp_server(conn, library_plugin)
        await self._repository.replace_mcp_server_capabilities(
            conn,
            server_id=library_plugin.server_id,
            tools=self._managed_plugin_tool_definitions(
                server_id=library_plugin.server_id,
                tool_names=_LIBRARY_PLUGIN_TOOL_NAMES,
                description_prefix="Open Talon Library operation",
                now=now,
            ),
            resources=[],
            prompts=[],
        )
        summary["mcp_servers"] += 1
        summary["mcp_tools"] += len(_LIBRARY_PLUGIN_TOOL_NAMES)

        retriever_plugin = await self._retriever_mcp_server(now=now)
        await self._repository.upsert_mcp_server(conn, retriever_plugin)
        await self._repository.replace_mcp_server_capabilities(
            conn,
            server_id=retriever_plugin.server_id,
            tools=self._managed_plugin_tool_definitions(
                server_id=retriever_plugin.server_id,
                tool_names=_RETRIEVER_PLUGIN_TOOL_NAMES,
                description_prefix="Open Talon Retriever operation",
                now=now,
            ),
            resources=[],
            prompts=[],
        )
        summary["mcp_servers"] += 1
        summary["mcp_tools"] += len(_RETRIEVER_PLUGIN_TOOL_NAMES)

        steward = next(
            agent for agent in global_agents if agent.agent_key == "steward"
        )
        researcher = next(
            agent for agent in global_agents if agent.agent_key == "researcher"
        )
        methodologist = next(
            agent for agent in global_agents if agent.agent_key == "methodologist"
        )
        conductor = next(
            agent for agent in global_agents if agent.agent_key == "conductor"
        )
        await self._repository.upsert_iam_role_definition(
            conn,
            self._platform_steward_iam_role(now=now),
        )
        await self._repository.upsert_iam_role_definition(
            conn,
            self._global_researcher_iam_role(now=now),
        )
        await self._repository.upsert_iam_role_definition(
            conn,
            self._global_methodologist_iam_role(now=now),
        )
        await self._repository.upsert_iam_role_definition(
            conn,
            self._global_conductor_iam_role(now=now),
        )
        await self._repository.upsert_agent_internal_mcp_server(
            conn,
            binding=self._steward_internal_mcp_binding(
                agent_id=steward.agent_id,
                server_id=control_plane.server_id,
                now=now,
            ),
        )
        await self._repository.upsert_agent_internal_mcp_server(
            conn,
            binding=self._researcher_control_plane_mcp_binding(
                agent_id=researcher.agent_id,
                server_id=control_plane.server_id,
                now=now,
            ),
        )
        for binding in self._researcher_plugin_mcp_bindings(
            agent_id=researcher.agent_id,
            library_server_id=library_plugin.server_id,
            retriever_server_id=retriever_plugin.server_id,
            web_search_server_id=web_search.server_id,
            now=now,
        ):
            await self._repository.upsert_agent_internal_mcp_server(
                conn,
                binding=binding,
            )
        await self._repository.upsert_agent_internal_mcp_server(
            conn,
            binding=self._methodologist_internal_mcp_binding(
                agent_id=methodologist.agent_id,
                server_id=control_plane.server_id,
                now=now,
            ),
        )
        await self._repository.upsert_agent_internal_mcp_server(
            conn,
            binding=self._conductor_internal_mcp_binding(
                agent_id=conductor.agent_id,
                server_id=control_plane.server_id,
                now=now,
            ),
        )
        summary["iam_roles"] += 4
        summary["internal_mcp_bindings"] += 7
        return control_plane, {
            agent.agent_key: agent
            for agent in global_agents
            if agent.agent_key is not None
        }

    async def _repair_organization_context(
        self,
        conn: asyncpg.Connection,
        *,
        organization: Organization,
        control_plane: McpServerDefinition,
        global_agents_by_key: dict[str, AgentDefinition],
        now: datetime,
        summary: dict[str, int],
    ) -> None:
        default_project = await self._repair_project(
            conn,
            desired=self._default_project_for_organization(organization, now=now),
            summary=summary,
        )
        await self._repair_project_subject_access(
            conn,
            project=default_project,
            now=now,
            summary=summary,
        )
        administration_project = await self._repair_project(
            conn,
            desired=self._administration_project_for_organization(
                organization,
                now=now,
            ),
            summary=summary,
        )
        await self._repair_project_subject_access(
            conn,
            project=administration_project,
            now=now,
            summary=summary,
        )
        operations_workspace = self._operations_workspace_for_organization(
            organization,
            administration_project,
            now=now,
        )
        await self._repository.upsert_workspace(conn, operations_workspace)
        summary["workspaces"] += 1
        await self._ensure_anchor_attached_for_workspace(
            conn,
            operations_workspace.workspace_id,
            now=now,
        )
        summary["participants"] += 1
        if (
            organization.organization_id == SYSTEM_BASE_ORGANIZATION_ID
            or organization.slug == "system-base"
        ):
            steward_agent = global_agents_by_key.get("steward")
            if steward_agent is not None:
                await self._repository.upsert_participant(
                    conn,
                    self._operations_participant_for_agent(
                        workspace=operations_workspace,
                        agent=steward_agent,
                        now=now,
                    ),
                )
                summary["participants"] += 1
                await self._repair_agent_project_access(
                    conn,
                    project_id=administration_project.project_id,
                    system_agent_id=steward_agent.agent_id,
                    now=now,
                    summary=summary,
                )
            return

        curator_agent = self._curator_agent_for_organization(organization, now=now)
        existing_curator = await self._find_system_agent_by_key(
            scope="organization",
            organization_id=organization.organization_id,
            agent_key="curator",
        )
        if existing_curator is not None:
            curator_agent = curator_agent.model_copy(
                update={
                    "agent_id": existing_curator.agent_id,
                    "active_agent_version_id": existing_curator.active_agent_version_id,
                    "created_by": existing_curator.created_by,
                    "created_at": existing_curator.created_at,
                    "metadata": {**existing_curator.metadata, **curator_agent.metadata},
                }
            )
        await self._repository.upsert_system_agent(conn, curator_agent)
        curator_role = self._curator_iam_role_for_organization(
            organization.organization_id,
            now=now,
        )
        existing_curator_role = await self._find_iam_role_definition_by_name(
            subject_kind="agent",
            scope="organization",
            organization_id=organization.organization_id,
            name=curator_role.name,
        )
        if existing_curator_role is not None:
            curator_role = curator_role.model_copy(
                update={
                    "role_id": existing_curator_role.role_id,
                    "created_at": existing_curator_role.created_at,
                    "metadata": {**existing_curator_role.metadata, **curator_role.metadata},
                }
            )
        await self._repository.upsert_iam_role_definition(conn, curator_role)
        await self._repository.upsert_participant(
            conn,
            self._operations_participant_for_agent(
                workspace=operations_workspace,
                agent=curator_agent,
                now=now,
            ),
        )
        await self._repository.upsert_agent_internal_mcp_server(
            conn,
            binding=self._curator_internal_mcp_binding(
                agent_id=curator_agent.agent_id,
                server_id=control_plane.server_id,
                now=now,
            ),
        )
        summary["internal_mcp_bindings"] += 1
        await self._repair_agent_project_access(
            conn,
            project_id=administration_project.project_id,
            system_agent_id=curator_agent.agent_id,
            now=now,
            summary=summary,
        )
        summary["system_agents"] += 1
        summary["iam_roles"] += 1
        summary["participants"] += 1

    async def _repair_project(
        self,
        conn: asyncpg.Connection,
        *,
        desired: Project,
        summary: dict[str, int],
    ) -> Project:
        existing = await self._repository.fetch_project_by_slug(
            organization_id=desired.organization_id,
            slug=desired.slug,
        )
        if existing is not None:
            desired = desired.model_copy(
                update={
                    "project_id": existing.project_id,
                    "created_by": existing.created_by,
                    "creator_user_id": existing.creator_user_id,
                    "creator_system_agent_id": existing.creator_system_agent_id,
                    "created_at": existing.created_at,
                    "metadata": {**existing.metadata, **desired.metadata},
                }
            )
        await self._repository.upsert_project(conn, desired)
        summary["projects"] += 1
        return desired

    async def _repair_project_subject_access(
        self,
        conn: asyncpg.Connection,
        *,
        project: Project,
        now: datetime,
        summary: dict[str, int],
    ) -> None:
        for binding in _project_subject_access_bindings(project, now=now):
            await self._repository.upsert_project_access_binding(conn, binding)
            summary["project_access_bindings"] += 1

    async def _repair_agent_project_access(
        self,
        conn: asyncpg.Connection,
        *,
        project_id: UUID,
        system_agent_id: UUID,
        now: datetime,
        summary: dict[str, int],
    ) -> None:
        await self._repository.upsert_project_access_binding(
            conn,
            ProjectAccessBinding(
                project_id=project_id,
                subject_type="agent",
                system_agent_id=system_agent_id,
                role="creator",
                created_at=now,
                updated_at=now,
                metadata={
                    "seeded": True,
                    "managed": True,
                    "source": "operational_agent",
                },
            ),
        )
        summary["project_access_bindings"] += 1

    async def _find_system_agent_by_key(
        self,
        *,
        scope: str,
        organization_id: UUID | None,
        agent_key: str,
    ) -> AgentDefinition | None:
        if hasattr(self._repository, "fetch_system_agent_by_key"):
            return await self._repository.fetch_system_agent_by_key(
                scope=scope,
                organization_id=organization_id,
                agent_key=agent_key,
            )
        return next(
            (
                agent
                for agent in await self._repository.list_system_agents()
                if agent.scope == scope
                and agent.organization_id == organization_id
                and agent.agent_key == agent_key
            ),
            None,
        )

    async def _find_mcp_server_by_key(
        self,
        *,
        scope: str,
        organization_id: UUID | None,
        server_key: str,
    ) -> McpServerDefinition | None:
        return next(
            (
                server
                for server in await self._repository.list_mcp_servers(
                    scope=scope,
                    organization_id=organization_id,
                )
                if server.server_key == server_key
            ),
            None,
        )

    async def _find_iam_role_definition_by_name(
        self,
        *,
        subject_kind: str,
        scope: str,
        organization_id: UUID | None,
        name: str,
    ) -> IamRoleDefinition | None:
        return next(
            (
                role
                for role in await self._repository.list_iam_role_definitions(
                    subject_kind=subject_kind,
                    scope=scope,
                    organization_id=organization_id,
                )
                if role.name == name
            ),
            None,
        )

    async def _default_llm_providers(self, *, now: datetime) -> list[LlmProviderDefinition]:
        existing = {
            provider.engine_id: provider
            for provider in await self._repository.list_llm_providers(
                scope="global",
                organization_id=None,
            )
        }

        def provider_id(engine_id: str, fallback: str) -> UUID:
            provider = existing.get(engine_id)
            return provider.provider_id if provider is not None else UUID(fallback)

        return [
            LlmProviderDefinition(
                provider_id=provider_id(
                    "local-ollama",
                    "11111111-1111-1111-1111-111111111111",
                ),
                engine_id="local-ollama",
                display_name="Local Ollama",
                description="Host-local Ollama generation endpoint.",
                provider="ollama",
                endpoint_kind="local",
                url="http://127.0.0.1:11434/api/generate",
                default_model=_default_reasoning_model(),
                capabilities=[
                    "chat",
                    "completion",
                    "vision",
                    "image_input",
                    "local",
                    "host",
                    "ollama",
                ],
                locality="host",
                priority=100,
                enabled=True,
                secret_config={},
                created_by=SYSTEM_ACTOR_ID,
                created_at=now,
                updated_by=SYSTEM_ACTOR_ID,
                updated_at=now,
                metadata={"managed": True, "seeded": True},
            ),
            LlmProviderDefinition(
                provider_id=provider_id(
                    "openai-responses",
                    "22222222-2222-2222-2222-222222222222",
                ),
                engine_id="openai-responses",
                display_name="OpenAI Responses",
                description="Cloud OpenAI Responses API provider.",
                provider="openai",
                endpoint_kind="remote",
                url="https://api.openai.com/v1/responses",
                default_model="gpt-5.4-mini",
                capabilities=[
                    "chat",
                    "completion",
                    "tool_calling",
                    "reasoning",
                    "vision",
                    "image_input",
                    "responses-api",
                    "model:gpt-5.4-mini",
                ],
                locality="cloud",
                priority=220,
                enabled=True,
                secret_config={
                    "env": {"name": "OPENAI_API_KEY"},
                    "openbao": {
                        "mount": "secret",
                        "path": "open-talon/llm/openai",
                        "field": "api_key",
                    },
                },
                created_by=SYSTEM_ACTOR_ID,
                created_at=now,
                updated_by=SYSTEM_ACTOR_ID,
                updated_at=now,
                metadata={"managed": True, "seeded": True},
            ),
        ]

    async def _default_memory_providers(
        self,
        *,
        now: datetime,
    ) -> list[MemoryProviderDefinition]:
        existing_postgres = await self._repository.fetch_memory_provider_by_key(
            "postgres",
            scope="global",
            organization_id=None,
        )
        existing_mem0 = await self._repository.fetch_memory_provider_by_key(
            "mem0",
            scope="global",
            organization_id=None,
        )
        return [
            MemoryProviderDefinition(
                provider_id=(
                    existing_postgres.provider_id
                    if existing_postgres is not None
                    else UUID("44444444-4444-4444-4444-444444444441")
                ),
                provider_key="postgres",
                display_name="Canonical Postgres Memory",
                description="Canonical layered memory store backed by Open Talon Postgres.",
                provider="postgres",
                enabled=True,
                config={},
                secret_config={},
                created_by=SYSTEM_ACTOR_ID,
                created_at=now,
                updated_by=SYSTEM_ACTOR_ID,
                updated_at=now,
                metadata={"seeded": True, "managed": True},
            ),
            MemoryProviderDefinition(
                provider_id=(
                    existing_mem0.provider_id
                    if existing_mem0 is not None
                    else UUID("44444444-4444-4444-4444-444444444442")
                ),
                provider_key="mem0",
                display_name="Mem0 Layered Memory",
                description="Mem0 OSS semantic memory provider with optional graph support.",
                provider="mem0",
                enabled=True,
                config={
                    "enable_graph": False,
                    "vector_store": {
                        "provider": "pgvector",
                        "config": {
                            "host": "localhost",
                            "port": 5432,
                            "user": "admin",
                            "password": "password",
                            "dbname": "app_db",
                            "collection_name": "open_talon_memories",
                        },
                    },
                    "llm": {
                        "provider": "openai",
                        "config": {"model": "gpt-4.1-mini"},
                    },
                    "embedder": {
                        "provider": "openai",
                        "config": {"model": "text-embedding-3-small"},
                    },
                },
                secret_config={
                    "env": {"name": "OPENAI_API_KEY"},
                    "openbao": {
                        "mount": "secret",
                        "path": "open-talon/memory/mem0",
                        "field": "api_key",
                    },
                },
                created_by=SYSTEM_ACTOR_ID,
                created_at=now,
                updated_by=SYSTEM_ACTOR_ID,
                updated_at=now,
                metadata={"seeded": True, "managed": True, "graph_optional": True},
            ),
        ]

    async def _default_global_agents(self, *, now: datetime) -> list[AgentDefinition]:
        agents = [self._reasoning_planner_agent_definition(now=now)]
        for scope, organization_id, agent_key, factory in [
            ("global", None, "tinker", self._tinker_agent_definition),
            ("global", None, "steward", self._steward_agent_definition),
            ("global", None, "anchor", self._anchor_agent_definition),
            ("global", None, "researcher", self._researcher_agent_definition),
            ("global", None, "methodologist", self._methodologist_agent_definition),
            ("global", None, "conductor", self._conductor_agent_definition),
        ]:
            existing = await self._find_system_agent_by_key(
                scope=scope,
                organization_id=organization_id,
                agent_key=agent_key,
            )
            agent = factory(now=now)
            if existing is not None:
                agent = agent.model_copy(
                    update={
                        "agent_id": existing.agent_id,
                        "active_agent_version_id": existing.active_agent_version_id,
                        "created_by": existing.created_by,
                        "created_at": existing.created_at,
                        "metadata": {**existing.metadata, **agent.metadata},
                    }
                )
            agents.append(agent)
        return agents

    @staticmethod
    def _reasoning_planner_agent_definition(*, now: datetime) -> AgentDefinition:
        return AgentDefinition(
            agent_id=REASONING_PLANNER_AGENT_ID,
            display_name="Reasoning Planner",
            description="Plans multi-step work with cloud reasoning.",
            role="planning agent",
            capabilities=["planning", "triage", "reasoning"],
            endpoint=AgentEndpoint(
                kind="remote",
                engine_id="openai-responses",
                provider="openai",
            ),
            system_prompt="You plan carefully and explain tradeoffs clearly.",
            interaction_contract=AgentInteractionContract(
                instructions=[
                    "Operate as Reasoning Planner, fulfilling the role planning agent.",
                    "Use only the provided Open Talon execution context and be explicit about uncertainty.",
                    "Return a collaborator-friendly reply suitable for the shared thread.",
                ],
                response_contract=AgentResponseContract(
                    format="markdown",
                    title="Planning Agent Response",
                    required_sections=["Summary", "Findings", "Next action"],
                    guidance=[
                        "Keep the response concise and thread-ready.",
                        "Reference concrete evidence from the visible context when possible.",
                    ],
                ),
                completion_criteria=[
                    "Address the latest visible request.",
                    "Explain evidence or lack of evidence clearly.",
                    "Make the next action obvious to collaborators.",
                ],
                metadata={"contract_version": 1, "generated": True},
            ),
            definition={
                "runtime": {
                    "engine_id": "openai-responses",
                    "preferred_capabilities": ["reasoning", "tool_calling"],
                    "preferred_locality": "cloud",
                },
                "seeded": True,
                "profile": _seeded_agent_profile(
                    kind="example_planning_participant",
                    mandate=(
                        "Provide small-scope planning, triage, and reasoning examples "
                        "for installations and tests."
                    ),
                    activation=(
                        "Manual workspace attachment or explicit targeted planning tasks; "
                        "no automatic managed operations role."
                    ),
                    authority=[
                        "visible workspace/thread context",
                        "workspace tools granted through ordinary attachment",
                    ],
                    boundaries=[
                        "no private operational MCP bindings",
                        "no platform or organization administration authority",
                        "no special runtime behavior",
                    ],
                    primary_inputs=["user request", "visible workspace context"],
                    primary_outputs=["planning summary", "findings", "next action"],
                ),
            },
            created_by=SYSTEM_ACTOR_ID,
            created_at=now,
            updated_at=now,
            metadata={"managed": True, "seeded": True, "example": True},
        )

    @staticmethod
    def _tinker_agent_definition(*, now: datetime) -> AgentDefinition:
        return AgentDefinition(
            agent_id=TINKER_AGENT_ID,
            agent_key="tinker",
            scope="global",
            organization_id=None,
            display_name="Tinker",
            description=(
                "Builds new agent-usable tools from workspace requests, validates generated "
                "tools, and submits reviewable revisions for catalog approval."
            ),
            role="generated tool authoring and validation agent",
            capabilities=[
                "generates new agent-usable tools from workspace requests",
                "checks whether existing tools already satisfy a request",
                "validates generated tools before approval",
                "submits generated tool revisions for catalog review",
                "reports trust network and workspace-access rationale for generated tools",
            ],
            endpoint=AgentEndpoint(
                kind="system",
                engine_id="openai-responses",
                provider="openai",
            ),
            system_prompt=(
                "You are Tinker. Reuse existing tools when they already satisfy the need. "
                "Ask clarifying questions when requirements are incomplete. When authoring "
                "a new tool, produce reviewable revisions, capture trust/network rationale, "
                "and prepare concise status updates for the shared thread."
            ),
            harness=AgentHarness(
                version=1,
                summary="Global tool generation harness for Tinker.",
                operating_principles=[
                    "Prefer existing visible tools before creating a new one.",
                    "Ask follow-up questions when requirements are ambiguous or missing.",
                    "Use internal authoring helpers instead of assuming local side effects succeeded.",
                    "Do not claim publication until validation evidence exists.",
                ],
                tool_use_policy=AgentToolUsePolicy(
                    prefer_existing_workspace_tools=True,
                    read_before_write=True,
                    inspect_schema_before_use=True,
                    cite_tool_results_in_reasoning=True,
                    verify_side_effects_after_mutation=True,
                ),
                validation_policy=AgentValidationPolicy(
                    required_checks=[
                        "confirm whether an existing catalog tool already satisfies the request",
                        "justify requested network or read_write access",
                        "capture validation evidence before moving to pending approval",
                    ],
                    require_evidence_for_claims=True,
                    require_tool_results_for_completion=True,
                    require_tests_before_done=True,
                ),
                metadata={"seeded": True, "tool_generation_agent": True},
            ),
            interaction_contract=AgentInteractionContract(
                instructions=[
                    "Operate as Tinker, the system-wide tool generation agent.",
                    "Reuse an existing visible tool when that is sufficient.",
                    "If requirements are incomplete, create interaction requests instead of guessing.",
                    "When proposing a generated tool, summarize trust, network, workspace access, validation, and artifacts.",
                ],
                response_contract=AgentResponseContract(
                    format="markdown",
                    title="Tinker Update",
                    required_sections=["Summary", "Status"],
                    guidance=[
                        "Keep thread replies concise and operational.",
                        "Make approval state and next action obvious.",
                    ],
                ),
                completion_criteria=[
                    "Either identify an existing tool that satisfies the need or advance a generated-tool request.",
                    "Leave a clear next action for the user or platform admin.",
                ],
                metadata={"contract_version": 1, "seeded": True},
            ),
            definition={
                "runtime": {
                    "engine_id": "openai-responses",
                    "preferred_capabilities": ["reasoning", "tool_calling"],
                    "preferred_locality": "cloud",
                },
                "seeded": True,
                "managed": True,
                "tool_generation_agent": True,
                "agent_key": "tinker",
                "system_test_harness": False,
                "profile": _seeded_agent_profile(
                    kind="workspace_tool_generation_specialist",
                    mandate=(
                        "Turn workspace requests for missing capabilities into "
                        "reviewable generated-tool revisions."
                    ),
                    activation=(
                        "Manual workspace attachment followed by a targeted "
                        "tool-generation request."
                    ),
                    authority=[
                        "visible workspace context and attached tools",
                        "private generated-tool authoring helpers",
                        "human approval for publication",
                    ],
                    boundaries=[
                        "reuse existing visible tools before authoring",
                        "do not publish without validation evidence and approval",
                        "do not auto-attach approved tools to workspaces",
                    ],
                    primary_inputs=[
                        "workspace request",
                        "existing tool catalog",
                        "trust/network/workspace-access requirements",
                    ],
                    primary_outputs=[
                        "generated-tool request",
                        "revision",
                        "validation evidence",
                        "approval-ready status update",
                    ],
                    handoffs=[
                        "human reviewers approve or reject generated revisions",
                        "workspace owners attach approved tools manually",
                    ],
                ),
            },
            created_by=SYSTEM_ACTOR_ID,
            created_at=now,
            updated_at=now,
            metadata={
                "managed": True,
                "seeded": True,
                "tool_generation_agent": True,
                "agent_key": "tinker",
                "system_test_harness": False,
            },
        )

    @staticmethod
    def _steward_agent_definition(*, now: datetime) -> AgentDefinition:
        return AgentDefinition(
            agent_id=STEWARD_AGENT_ID,
            agent_key="steward",
            scope="global",
            organization_id=None,
            display_name="Steward",
            description=(
                "Manages platform-wide Open Talon operations through authorized control-plane "
                "APIs and private MCP tools."
            ),
            role="platform operations steward",
            capabilities=[
                "manages platform operations through authorized control-plane tools",
                "reviews platform runtime and audit health",
                "coordinates system-wide catalog and provider administration",
                "repairs managed administration contexts when authorized",
                "keeps tenant IAM audit and secret boundaries explicit",
            ],
            endpoint=AgentEndpoint(
                kind="system",
                engine_id="openai-responses",
                provider="openai",
            ),
            system_prompt=(
                "You are Steward, the platform operations agent. Operate only through "
                "authorized APIs and MCP tools. Prefer read, validate, repair, and review "
                "actions before mutation. Never bypass IAM, audit, or MCP/tool allowlists."
            ),
            harness=AgentHarness(
                version=1,
                summary="Global platform operations harness for Steward.",
                operating_principles=[
                    "Use Open Talon control-plane APIs for platform operations.",
                    "Keep IAM, audit, secret handling, and tenant boundaries explicit.",
                    "Treat destructive operations as unavailable unless separately granted.",
                ],
                tool_use_policy=AgentToolUsePolicy(
                    inspect_schema_before_use=True,
                    read_before_write=True,
                    verify_side_effects_after_mutation=True,
                    cite_tool_results_in_reasoning=True,
                ),
                metadata={"seeded": True, "managed": True},
            ),
            interaction_contract=AgentInteractionContract(
                instructions=[
                    "Operate as Steward, the platform steward.",
                    "Use only allowlisted control-plane APIs and visible tools.",
                    "Do not perform destructive delete, audit export, member removal, or secret rotation unless a later explicit binding grants it.",
                ],
                response_contract=AgentResponseContract(
                    format="markdown",
                    title="Steward Update",
                    required_sections=["Summary", "Status"],
                    guidance=["Keep operational replies concise and evidence-backed."],
                ),
                completion_criteria=["Report the operation outcome and any follow-up needed."],
                metadata={"contract_version": 1, "seeded": True},
            ),
            definition={
                "runtime": {
                    "engine_id": "openai-responses",
                    "preferred_capabilities": ["reasoning", "tool_calling"],
                    "preferred_locality": "cloud",
                },
                "seeded": True,
                "managed": True,
                "agent_key": "steward",
                "profile": _seeded_agent_profile(
                    kind="platform_operations_specialist",
                    mandate=(
                        "Inspect, validate, repair, and coordinate platform-wide "
                        "Open Talon operational resources."
                    ),
                    activation=(
                        "Seeded in the System Base operations workspace and targeted "
                        "through authorized platform operations tasks."
                    ),
                    authority=[
                        "platform_steward IAM role",
                        "System Operations workspace attachment",
                        "private control-plane MCP allowlist",
                    ],
                    boundaries=[
                        "role text is descriptive and not authorization",
                        "destructive or secret-rotating operations remain denied unless explicitly granted",
                        "tenant IAM and audit boundaries must stay explicit",
                    ],
                    primary_inputs=[
                        "platform runtime state",
                        "catalog/provider state",
                        "audit and health signals",
                    ],
                    primary_outputs=[
                        "platform operation status",
                        "validated or repaired managed resources",
                        "follow-up recommendations",
                    ],
                ),
            },
            created_by=SYSTEM_ACTOR_ID,
            created_at=now,
            updated_at=now,
            metadata={"managed": True, "seeded": True, "agent_key": "steward"},
        )

    @staticmethod
    def _anchor_agent_definition(*, now: datetime) -> AgentDefinition:
        return AgentDefinition(
            agent_id=ANCHOR_AGENT_ID,
            agent_key="anchor",
            scope="global",
            organization_id=None,
            display_name="Anchor",
            description=(
                "Reviews workspace communication for topic fit, applies the workspace "
                "topic-freedom policy, and explains blocked messages when configured."
            ),
            role=ANCHOR_ROLE,
            capabilities=list(ANCHOR_CAPABILITIES),
            endpoint=AgentEndpoint(
                kind="system",
                engine_id="local-ollama",
                provider="ollama",
            ),
            system_prompt=(
                "You are Anchor. Review the supplied candidate workspace communication "
                "only for fit with the workspace topic and moderation policy. Do not "
                "provide general safety review, style review, or task assistance. "
                "Return only the JSON object required by your response contract."
            ),
            harness=AgentHarness(
                summary=(
                    "Reviews candidate workspace communication for topic fit using the "
                    "workspace moderation policy."
                ),
                operating_principles=[
                    "Judge topic relevance, not general quality or style.",
                    "Use the workspace topic, description, harness, and configured policy as the authority.",
                    "Prefer allowing messages when relevance is plausible outside strict mode.",
                    "Give concise, actionable issuer guidance when a strict-mode message is blocked.",
                ],
                planning=AgentPlanningPolicy(
                    plan_before_act=False,
                    incremental_execution=False,
                    one_goal_at_a_time=True,
                    explicit_uncertainty=True,
                ),
                tool_use_policy=AgentToolUsePolicy(
                    prefer_existing_workspace_tools=False,
                    read_before_write=False,
                    inspect_schema_before_use=False,
                    cite_tool_results_in_reasoning=False,
                    verify_side_effects_after_mutation=False,
                    selection_principles=[
                        "Do not call workspace tools during ordinary topic review.",
                        "Use only the moderation context supplied with the task.",
                    ],
                    fallback_when_no_tool_fits=(
                        "Return a structured moderation decision from the supplied context."
                    ),
                ),
                memory_policy=AgentMemoryPolicy(
                    use_run_memory=False,
                    use_thread_memory=True,
                    use_workspace_memory=False,
                ),
                validation_policy=AgentValidationPolicy(
                    require_evidence_for_claims=True,
                    require_tool_results_for_completion=False,
                    require_tests_before_done=False,
                ),
                stop_policy=AgentStopPolicy(
                    completion_conditions=[
                        "Return one structured moderation decision for the candidate message."
                    ],
                    stop_conditions=[
                        "Do not continue into conversation or task assistance."
                    ],
                    max_turns=1,
                ),
                metadata={
                    "managed": True,
                    "agent_key": "anchor",
                    "moderation_agent": True,
                },
            ),
            interaction_contract=AgentInteractionContract(
                instructions=[
                    "Review only the supplied candidate message for workspace-topic fit.",
                    "Apply the workspace moderation policy supplied in task instructions.",
                    "Return only a JSON moderation decision.",
                ],
                response_contract=AgentResponseContract(
                    format="json",
                    title="Topic moderation decision",
                    guidance=[
                        "Use decision=allow when the message fits the topic policy.",
                        "Use decision=block for strict-mode messages that must not be published.",
                        "Use decision=flag for balanced or open mode messages that should remain visible but be marked as drift.",
                    ],
                    json_schema={
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["decision", "relatedness", "confidence", "reason"],
                        "properties": {
                            "decision": {
                                "type": "string",
                                "enum": ["allow", "block", "flag"],
                            },
                            "relatedness": {
                                "type": "string",
                                "enum": [
                                    "direct",
                                    "adjacent",
                                    "unrelated",
                                    "blocked_topic",
                                    "unknown",
                                ],
                            },
                            "confidence": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                            "reason": {"type": "string"},
                            "issuer_explanation": {"type": "string"},
                        },
                    },
                ),
                completion_criteria=[
                    "The decision matches the supplied workspace topic-freedom policy.",
                    "The reason cites concrete topic fit or topic drift without exposing hidden policy data.",
                ],
                metadata={"contract_version": 1, "seeded": True, "agent_key": "anchor"},
            ),
            definition={
                "runtime": {
                    "engine_id": "local-ollama",
                    "provider": "ollama",
                    "preferred_capabilities": ["local", "ollama"],
                    "preferred_locality": "host",
                },
                "seeded": True,
                "managed": True,
                "agent_key": "anchor",
                "moderation_agent": True,
                "task_routing": {
                    "normal_message_fanout": False,
                    "accepted_task_kinds": [ANCHOR_TASK_KIND],
                },
                "profile": _seeded_agent_profile(
                    kind="workspace_topic_governance_reviewer",
                    mandate=(
                        "Review candidate workspace communication for fit with the "
                        "workspace topic and topic-freedom policy."
                    ),
                    activation=(
                        "Auto-attached to workspaces and invoked only through targeted "
                        "workspace_topic_moderation tasks."
                    ),
                    authority=[
                        "workspace moderation policy",
                        "workspace topic, description, and harness context",
                        "publication-review task payload",
                    ],
                    boundaries=[
                        "no normal message fanout",
                        "no general safety, style, or task-assistance review",
                        "one-turn JSON decision only",
                    ],
                    primary_inputs=[
                        "candidate message",
                        "workspace topic policy",
                        "workspace context snapshot",
                    ],
                    primary_outputs=[
                        "allow/block/flag decision",
                        "relatedness",
                        "confidence",
                        "reason",
                    ],
                ),
            },
            created_by=SYSTEM_ACTOR_ID,
            created_at=now,
            updated_at=now,
            metadata={
                "managed": True,
                "seeded": True,
                "agent_key": "anchor",
                "moderation_agent": True,
            },
        )

    @staticmethod
    def _researcher_agent_definition(*, now: datetime) -> AgentDefinition:
        accepted_task_kinds = [
            METHODOLOGY_RESEARCH_DOSSIER_BUILD_TASK_KIND,
            METHODOLOGY_RESEARCH_DOSSIER_REFINE_TASK_KIND,
        ]
        return AgentDefinition(
            agent_id=RESEARCHER_AGENT_ID,
            agent_key="researcher",
            scope="global",
            organization_id=None,
            display_name="Researcher",
            description=(
                "Builds durable research dossiers by discovering, collecting, "
                "triaging, and organizing evidence from local libraries, indexed "
                "retrieval corpora, databases, files, media, and web follow-up."
            ),
            role="evidence discovery and research dossier agent",
            capabilities=[
                "discovers sources across selected organization libraries and retrieval corpora",
                "uses web follow-up for recency gaps contradiction checks and missing coverage",
                "triages sources by quality relevance duplication inclusion and unresolved status",
                "maps contradictions disagreements and follow-up questions before synthesis",
                "preserves fetched pages papers files and media in retained dossier libraries",
                "structures concept notes claims gaps and synthesis pages in the dossier notebook",
                "submits structured research dossier source records and readiness updates",
            ],
            endpoint=AgentEndpoint(
                kind="system",
                engine_id="local-ollama",
                provider="ollama",
            ),
            system_prompt=(
                "You are Researcher. Build durable research dossiers for specific "
                "topics and tasks. Start with selected local and organization libraries, "
                "pre-indexed Retriever corpora, files, media, and database-visible context. "
                "Use web search and fetch only for gaps, recency, contradiction checks, "
                "or missing source coverage. Preserve fetched sources in the retained "
                "dossier library when possible. Record each source with retained refs, "
                "quality notes, rationale, status, fetch metadata, contradictions, and "
                "errors. Mark a dossier ready only when the evidence boundary, gaps, and "
                "disagreements are explicit enough for downstream agents or humans."
            ),
            harness=AgentHarness(
                version=1,
                summary=(
                    "Research dossier harness for auditable multi-step discovery, "
                    "triage, contradiction mapping, and retained source organization."
                ),
                operating_principles=[
                    "Treat the dossier as knowledge storage: a reusable concept repository for agents, users, and participants.",
                    "Search local libraries and indexed corpora before broad web discovery.",
                    "Use explicit web follow-up for gaps, recency, and contradictions.",
                    "Preserve fetched source snapshots in the retained dossier library whenever possible.",
                    "Keep the concept notebook navigable with source summaries, concepts, claims, typed links, gaps, contradictions, methods, and synthesis pages.",
                    "Keep included, excluded, duplicate, failed, and unresolved records visible.",
                    "Separate evidence, quality judgment, disagreement mapping, and open gaps.",
                ],
                planning=AgentPlanningPolicy(
                    plan_before_act=True,
                    incremental_execution=True,
                    one_goal_at_a_time=True,
                    explicit_uncertainty=True,
                    guidance=[
                        "Start with a research plan covering local libraries, retrieval, web follow-up, and triage criteria.",
                        "Iterate when contradictions or gaps imply a follow-up search.",
                        "Do a final dossier readiness pass before marking ready for downstream synthesis.",
                    ],
                ),
                tool_use_policy=AgentToolUsePolicy(
                    prefer_existing_workspace_tools=True,
                    read_before_write=True,
                    inspect_schema_before_use=True,
                    cite_tool_results_in_reasoning=True,
                    verify_side_effects_after_mutation=True,
                    selection_principles=[
                        "Use Library tools to inspect selected and retained dossier libraries.",
                        "Use Retriever tools for indexed searches and context packs.",
                        "Use Web Search only for explicit follow-up discovery, gaps, or recency.",
                        "Use methodology dossier MCP tools to persist every source, notebook note, concept, claim, link, health check, sync, and readiness update.",
                    ],
                    fallback_when_no_tool_fits=(
                        "Record the limitation as an unresolved dossier gap and continue with visible evidence."
                    ),
                ),
                memory_policy=AgentMemoryPolicy(
                    use_run_memory=True,
                    use_thread_memory=True,
                    use_workspace_memory=True,
                ),
                validation_policy=AgentValidationPolicy(
                    required_checks=[
                        "Every fetched source has a retained reference or a clear fetch failure.",
                        "Every source has a terminal triage status before readiness.",
                        "Quality notes and rationale are present for included and excluded sources.",
                        "Contradictions and disagreements are mapped with affected source ids.",
                        "Open gaps and follow-up opportunities are explicit before mark_ready.",
                        "The concept notebook is navigable or unresolved notebook health issues are explicit.",
                    ],
                    require_evidence_for_claims=True,
                    require_tool_results_for_completion=True,
                    require_tests_before_done=False,
                ),
                stop_policy=AgentStopPolicy(
                    completion_conditions=[
                        "The research dossier has structured sources, summary, contradictions, gaps, context packs, and a readiness decision."
                    ],
                    stop_conditions=[
                        "Do not synthesize the methodology blueprint; hand the completed dossier to Methodologist."
                    ],
                ),
                metadata={
                    "seeded": True,
                    "managed": True,
                    "agent_key": "researcher",
                    "research_dossier_agent": True,
                    "task_routing": {
                        "normal_message_fanout": False,
                        "accepted_task_kinds": accepted_task_kinds,
                    },
                },
            ),
            interaction_contract=AgentInteractionContract(
                instructions=[
                    "Operate as Researcher, the evidence discovery and research dossier agent.",
                    "Build and refine durable dossiers through targeted dossier tasks only.",
                    "Search local libraries and Retriever context first, then use web follow-up for gaps and recency.",
                    "Persist source records, context packs, concept notes, claims, links, contradictions, gaps, health checks, sync, and readiness through dossier MCP operations.",
                    "Do not synthesize the final methodology blueprint.",
                ],
                response_contract=AgentResponseContract(
                    format="markdown",
                    title="Research Dossier Update",
                    required_sections=[
                        "Research Scope",
                        "Discovery Plan",
                        "Sources",
                        "Quality Notes",
                        "Contradictions",
                        "Gaps",
                        "Retained References",
                        "Concept Notebook",
                        "Readiness",
                    ],
                    guidance=[
                        "Group sources by status: included, excluded, duplicate, failed, and unresolved.",
                        "Cite retained library item ids, context pack ids, asset refs, or source URIs.",
                        "State why follow-up searches were or were not needed.",
                    ],
                ),
                completion_criteria=[
                    "The dossier is durable enough for Methodologist, another agent, or a human reviewer to consume.",
                    "Source statuses and retained refs are explicit.",
                    "Contradictions and remaining gaps are explicit.",
                ],
                metadata={"contract_version": 1, "seeded": True, "agent_key": "researcher"},
            ),
            definition={
                "runtime": {
                    "engine_id": "local-ollama",
                    "provider": "ollama",
                    "preferred_capabilities": ["local", "ollama", "reasoning"],
                    "preferred_locality": "host",
                },
                "seeded": True,
                "managed": True,
                "agent_key": "researcher",
                "research_dossier_agent": True,
                "task_routing": {
                    "normal_message_fanout": False,
                    "accepted_task_kinds": accepted_task_kinds,
                },
                "profile": _seeded_agent_profile(
                    kind="methodology_research_dossier_specialist",
                    mandate=(
                        "Discover, collect, triage, preserve, and organize evidence "
                        "into durable concept dossiers."
                    ),
                    activation=(
                        "Targeted organization-operations dossier build/refine tasks "
                        "created by methodology blueprint workflows."
                    ),
                    authority=[
                        "methodology_researcher IAM role",
                        "organization operations workspace attachment",
                        "Library, Retriever, Web Search, and dossier MCP allowlists",
                    ],
                    boundaries=[
                        "no normal message fanout",
                        "do not synthesize the methodology blueprint",
                        "mark unresolved evidence and notebook health gaps explicitly",
                    ],
                    primary_inputs=[
                        "topic",
                        "target tasks",
                        "selected libraries",
                        "Retriever corpora/context packs",
                        "local files/media/database context",
                        "web follow-up results",
                    ],
                    primary_outputs=[
                        "research dossier",
                        "source records",
                        "retained source refs",
                        "concept notebook",
                        "claims and typed links",
                        "contradictions",
                        "gaps",
                        "readiness decision",
                    ],
                    handoffs=[
                        "Methodologist receives ready dossiers for blueprint drafting",
                        "humans and other agents can navigate the dossier notebook",
                    ],
                    knowledge_layer="dossier knowledge storage over retained data and indexed information",
                ),
                "dossier_outputs": {
                    "source_statuses": [
                        "included",
                        "excluded",
                        "duplicate",
                        "failed",
                        "unresolved",
                    ],
                    "required_judgments": [
                        "source_quality",
                        "rationale",
                        "contradictions",
                        "gaps",
                        "retained_refs",
                    ],
                },
            },
            created_by=SYSTEM_ACTOR_ID,
            created_at=now,
            updated_at=now,
            metadata={
                "managed": True,
                "seeded": True,
                "agent_key": "researcher",
                "research_dossier_agent": True,
                "task_routing": {
                    "normal_message_fanout": False,
                    "accepted_task_kinds": accepted_task_kinds,
                },
            },
        )

    @staticmethod
    def _methodologist_agent_definition(*, now: datetime) -> AgentDefinition:
        return AgentDefinition(
            agent_id=METHODOLOGIST_AGENT_ID,
            agent_key="methodologist",
            scope="global",
            organization_id=None,
            display_name="Methodologist",
            description=(
                "Extracts methodology basis, methodics, methods, actors, tools, and "
                "workspace implementation templates from completed research dossiers "
                "or cited domain source material."
            ),
            role="methodology extraction and workspace design agent",
            capabilities=[
                "consumes completed research dossiers with source records concept notebooks contradictions gaps and context packs",
                "analyzes narrow-domain books and source corpora through cited retrieval evidence",
                "extracts methodology basis including ontology axiology epistemology and principles",
                "derives methodics as high-level repeatable steps for achieving a stated goal",
                "separates source-grounded methods from inferred implementation tools and automations",
                "proposes human and agent actor responsibilities for workspace execution",
                "drafts project and workspace template structures with harness methodology methodics and execution rules",
            ],
            endpoint=AgentEndpoint(
                kind="system",
                engine_id="local-ollama",
                provider="ollama",
            ),
            system_prompt=(
                "You are Methodologist. Analyze completed research dossiers or cited source "
                "material for a narrow domain and extract the methodology basis, methodics, "
                "concrete methods, required actors, candidate tools, and a project/workspace "
                "template for implementing the approach. Use dossier source records, "
                "concept notebook navigation, contradictions, gaps, and retrieval/context-pack evidence as the authority "
                "for source-derived claims. "
                "Clearly separate what the source states from what you infer or ideate for Open Talon "
                "implementation. Do not invent citations, and ask for more source material or a clearer "
                "target goal when evidence is insufficient."
            ),
            harness=AgentHarness(
                version=1,
                summary=(
                    "Evidence-first methodology extraction harness for turning source corpora into "
                    "workspace-ready operating templates."
                ),
                operating_principles=[
                    "Start from the user's target goal and the completed dossier or cited source corpus; do not treat general knowledge as source evidence.",
                    "Use dossier source records, concept notebook pages, contradictions, gaps, and context packs as the evidence boundary when a dossier is supplied.",
                    "Separate methodology basis, methodics, methods, tools, actors, artifacts, and workspace template decisions.",
                    "Keep source-grounded extraction distinct from implementation ideation.",
                    "Preserve citations for claims that come from the source material.",
                    "Expose uncertainty, missing coverage, and assumptions instead of overfitting a thin source set.",
                    "Design workspace templates in terms of existing Open Talon concepts: project, workspace harness, methodology, methodics, execution rules, participants, tools, retrieval corpora, and artifacts.",
                ],
                planning=AgentPlanningPolicy(
                    plan_before_act=True,
                    incremental_execution=True,
                    one_goal_at_a_time=True,
                    explicit_uncertainty=True,
                    guidance=[
                        "Identify the domain, target outcome, dossier or source boundaries, and expected template consumer before synthesizing.",
                        "Use an extraction pass before the design pass.",
                        "Do a final consistency pass that maps each recommended methodic to evidence, actors, tools, and expected artifacts.",
                    ],
                ),
                tool_use_policy=AgentToolUsePolicy(
                    prefer_existing_workspace_tools=True,
                    read_before_write=True,
                    inspect_schema_before_use=True,
                    cite_tool_results_in_reasoning=True,
                    verify_side_effects_after_mutation=True,
                    selection_principles=[
                        "Read and navigate the completed research dossier notebook before synthesizing when a dossier id is supplied.",
                        "Use retrieval search or context packs for source evidence before synthesis.",
                        "Inspect existing workspace harness, files, and retrieval corpora before proposing changes.",
                        "Use authoring or catalog tools only when the user asks to materialize the template.",
                    ],
                    fallback_when_no_tool_fits=(
                        "Return a cited analysis and explicit template draft from the visible context; "
                        "ask for ingestion or source access when evidence is missing."
                    ),
                ),
                memory_policy=AgentMemoryPolicy(
                    use_run_memory=True,
                    use_thread_memory=True,
                    use_workspace_memory=True,
                ),
                validation_policy=AgentValidationPolicy(
                    required_checks=[
                        "Every source-derived methodology or methodic claim has cited evidence or is marked as an inference.",
                        "The output distinguishes Methodology, Methodics, Methods, Tools, Actors, and Workspace Template.",
                        "Each methodic includes goal, applicability, ordered steps, expected artifacts, and verification criteria.",
                        "Tool recommendations state whether they are source-stated, derived from a method, or implementation ideation.",
                        "Workspace template recommendations map to existing Open Talon harness fields where possible.",
                    ],
                    require_evidence_for_claims=True,
                    require_tool_results_for_completion=False,
                    require_tests_before_done=False,
                ),
                stop_policy=AgentStopPolicy(
                    completion_conditions=[
                        "Return a cited methodology extraction and a workspace-ready template draft, or identify the missing source/goal needed to do so."
                    ],
                    stop_conditions=[
                        "Do not continue into implementation unless the user explicitly asks to materialize the template."
                    ],
                ),
                metadata={
                    "seeded": True,
                    "managed": True,
                    "agent_key": "methodologist",
                    "methodology_agent": True,
                },
            ),
            interaction_contract=AgentInteractionContract(
                instructions=[
                    "Operate as Methodologist, the methodology extraction and workspace design agent.",
                    "Use completed research dossiers, cited retrieval, or visible source evidence for source-derived claims.",
                    "Separate source-grounded extraction from implementation ideation.",
                    "When evidence is missing, state the gap and ask for ingestion, corpus selection, or a clearer target goal.",
                    "Return a structure that can be translated into an Open Talon workspace harness.",
                ],
                response_contract=AgentResponseContract(
                    format="markdown",
                    title="Methodology Extraction And Workspace Template",
                    required_sections=[
                        "Source Scope",
                        "Target Goal",
                        "Methodology Basis",
                        "Methodics",
                        "Methods And Tools",
                        "Actors",
                        "Workspace Template",
                        "Evidence And Gaps",
                        "Next Actions",
                    ],
                    guidance=[
                        "Cite source evidence for extracted methodology and methodics.",
                        "Mark inferred or ideated tools explicitly.",
                        "Represent methodics as ordered high-level steps with artifacts and verification criteria.",
                        "Keep workspace-template recommendations compatible with `WorkspaceHarness.methodology`, `methodics`, and `execution_rules`.",
                    ],
                ),
                completion_criteria=[
                    "The source scope, target goal, and evidence gaps are explicit.",
                    "Methodology basis and methodics are separated from methods, tools, and actors.",
                    "The workspace template can guide creating or updating a project/workspace.",
                ],
                metadata={"contract_version": 1, "seeded": True, "agent_key": "methodologist"},
            ),
            definition={
                "runtime": {
                    "engine_id": "local-ollama",
                    "provider": "ollama",
                    "preferred_capabilities": ["local", "ollama", "reasoning"],
                    "preferred_locality": "host",
                },
                "seeded": True,
                "managed": True,
                "agent_key": "methodologist",
                "methodology_agent": True,
                "profile": _seeded_agent_profile(
                    kind="methodology_blueprint_synthesis_specialist",
                    mandate=(
                        "Turn completed research dossiers or cited source corpora into "
                        "methodology, methodics, and workspace harness drafts."
                    ),
                    activation=(
                        "Targeted blueprint-draft tasks after dossier readiness, or "
                        "manual workspace attachment for explicit extraction/design work."
                    ),
                    authority=[
                        "methodology_methodologist IAM role",
                        "visible dossier notebook and source records",
                        "cited Retriever/context-pack evidence",
                        "private dossier-read and blueprint-draft MCP allowlist",
                    ],
                    boundaries=[
                        "do not perform open-ended research triage",
                        "do not execute methodics",
                        "label inferred implementation ideas separately from source-backed claims",
                    ],
                    primary_inputs=[
                        "ready research dossier",
                        "dossier notebook navigation",
                        "source records",
                        "contradictions and gaps",
                        "context packs",
                        "target goal",
                    ],
                    primary_outputs=[
                        "cited methodology basis",
                        "methodics",
                        "methods and tools",
                        "actor responsibilities",
                        "WorkspaceHarness-compatible template draft",
                    ],
                    handoffs=[
                        "humans review and approve blueprint versions",
                        "Conductor can execute approved methodics only after explicit attachment and start",
                    ],
                    knowledge_layer="methodology synthesis over dossier knowledge storage",
                ),
                "output_targets": {
                    "workspace_harness_fields": [
                        "methodology",
                        "methodics",
                        "execution_rules",
                        "metadata",
                    ],
                    "template_sections": [
                        "project",
                        "workspace",
                        "retrieval_corpora",
                        "participants",
                        "tools",
                        "artifacts",
                    ],
                },
            },
            created_by=SYSTEM_ACTOR_ID,
            created_at=now,
            updated_at=now,
            metadata={
                "managed": True,
                "seeded": True,
                "agent_key": "methodologist",
                "methodology_agent": True,
            },
        )

    @staticmethod
    def _conductor_agent_definition(*, now: datetime) -> AgentDefinition:
        accepted_task_kinds = [
            METHODICS_EXECUTION_START_TASK_KIND,
            METHODICS_STEP_COORDINATE_TASK_KIND,
            METHODICS_STEP_VERIFY_TASK_KIND,
            METHODICS_RESOURCE_REVIEW_TASK_KIND,
        ]
        return AgentDefinition(
            agent_id=CONDUCTOR_AGENT_ID,
            agent_key="conductor",
            scope="global",
            organization_id=None,
            display_name="Conductor",
            description=(
                "Coordinates active workspace methodics only when explicitly attached "
                "to the workspace and an execution is started."
            ),
            role="workspace methodics execution conductor",
            capabilities=[
                "coordinates active WorkspaceHarness methodics through explicit execution state",
                "creates targeted assignments and interaction requests for workspace participants",
                "verifies definition of done evidence before advancing methodic steps",
                "proposes human-gated resource attachment requests for users agents tools MCP servers assets and retrieval resources",
                "tracks methodics execution progress until completion cancellation failure or rework",
            ],
            endpoint=AgentEndpoint(
                kind="system",
                engine_id="local-ollama",
                provider="ollama",
            ),
            system_prompt=(
                "You are Conductor. Execute active workspace methodics only for a started "
                "methodic execution in a workspace where you are already attached. Use the "
                "execution snapshot, current step state, assignments, checks, resource requests, "
                "and visible workspace evidence as the source of truth. Coordinate participants "
                "through targeted tasks, interaction requests, messages, and artifacts. Verify "
                "definition of done evidence before advancing. Propose resource attachments for "
                "authorized human approval instead of attaching users, agents, tools, MCP servers, "
                "assets, or retrieval resources yourself."
            ),
            harness=AgentHarness(
                version=1,
                summary=(
                    "Workspace methodics execution harness for explicit, opt-in Conductor "
                    "orchestration."
                ),
                operating_principles=[
                    "Do nothing unless a targeted methodics execution task is assigned.",
                    "Treat the methodics snapshot captured at execution start as the execution contract.",
                    "Coordinate one active methodic step at a time unless the snapshot explicitly supports parallel work.",
                    "Create clear assignments with expected evidence and definition of done.",
                    "Verify evidence before marking a step passed; create rework when evidence is missing or weak.",
                    "Request resource attachments through human-gated methodic resource requests.",
                    "Keep ordinary workspace conversation unaffected when Conductor is not attached or no execution is active.",
                ],
                planning=AgentPlanningPolicy(
                    plan_before_act=True,
                    incremental_execution=True,
                    one_goal_at_a_time=True,
                    explicit_uncertainty=True,
                    guidance=[
                        "Start by reading execution state, current step, open assignments, checks, and resource requests.",
                        "Prefer targeted coordination over broad message fanout.",
                        "Record next action, blocker, or verification decision in execution state.",
                    ],
                ),
                tool_use_policy=AgentToolUsePolicy(
                    prefer_existing_workspace_tools=True,
                    read_before_write=True,
                    inspect_schema_before_use=True,
                    cite_tool_results_in_reasoning=True,
                    verify_side_effects_after_mutation=True,
                    selection_principles=[
                        "Use MCP methodics tools to read and update execution state when available.",
                        "Use collaboration tools to create assignments, messages, and interaction requests.",
                        "Use retrieval only for evidence needed by the current methodic step.",
                    ],
                    fallback_when_no_tool_fits=(
                        "Return a concise execution status with the next required human or agent action."
                    ),
                ),
                memory_policy=AgentMemoryPolicy(
                    use_run_memory=True,
                    use_thread_memory=True,
                    use_workspace_memory=True,
                ),
                validation_policy=AgentValidationPolicy(
                    required_checks=[
                        "The execution id, current step, and methodics snapshot are explicit.",
                        "Assignments identify assignee, required evidence, and definition of done.",
                        "Step verification cites concrete evidence or records why evidence is insufficient.",
                        "Resource attachments remain pending human approval until explicitly approved.",
                    ],
                    require_evidence_for_claims=True,
                    require_tool_results_for_completion=False,
                    require_tests_before_done=False,
                ),
                stop_policy=AgentStopPolicy(
                    completion_conditions=[
                        "The current methodic execution task has a recorded coordination, verification, resource request, or status update."
                    ],
                    stop_conditions=[
                        "Do not continue executing methodics outside the active execution snapshot."
                    ],
                ),
                metadata={
                    "seeded": True,
                    "managed": True,
                    "agent_key": "conductor",
                    "methodics_execution_agent": True,
                },
            ),
            interaction_contract=AgentInteractionContract(
                instructions=[
                    "Operate as Conductor, the workspace methodics execution conductor.",
                    "Respond only to targeted methodics execution tasks.",
                    "Use the active methodic execution state and snapshot as the authority.",
                    "Coordinate participants through explicit assignments and interaction requests.",
                    "Verify definition of done evidence before advancing or completing steps.",
                    "Create human-gated resource requests instead of attaching resources directly.",
                ],
                response_contract=AgentResponseContract(
                    format="markdown",
                    title="Methodics Execution Update",
                    required_sections=[
                        "Execution State",
                        "Current Step",
                        "Assignments",
                        "DoD Verification",
                        "Resource Requests",
                        "Next Action",
                    ],
                    guidance=[
                        "Keep updates operational and tied to execution ids and step ids.",
                        "State whether the current step is coordinating, verifying, blocked, rework, or passed.",
                        "List only resource requests that require human approval.",
                    ],
                ),
                completion_criteria=[
                    "The execution status and current step are clear.",
                    "Any next assignment, verification decision, rework, or resource request is explicit.",
                    "The update does not imply automatic orchestration when Conductor is not attached.",
                ],
                metadata={"contract_version": 1, "seeded": True, "agent_key": "conductor"},
            ),
            definition={
                "runtime": {
                    "engine_id": "local-ollama",
                    "provider": "ollama",
                    "preferred_capabilities": ["local", "ollama", "reasoning"],
                    "preferred_locality": "host",
                },
                "seeded": True,
                "managed": True,
                "agent_key": "conductor",
                "methodics_execution_agent": True,
                "task_routing": {
                    "normal_message_fanout": False,
                    "accepted_task_kinds": accepted_task_kinds,
                },
                "profile": _seeded_agent_profile(
                    kind="workspace_methodics_execution_specialist",
                    mandate=(
                        "Coordinate active workspace methodics from an explicit "
                        "execution snapshot."
                    ),
                    activation=(
                        "Manual workspace attachment plus explicit human start of a "
                        "methodics execution."
                    ),
                    authority=[
                        "workspace_conductor IAM role",
                        "workspace participant attachment",
                        "methodic execution state",
                        "private Conductor MCP allowlist",
                    ],
                    boundaries=[
                        "no normal message fanout",
                        "no active loop without explicit execution start",
                        "human-gated start, cancel, approve, and reject operations stay outside private allowlist",
                    ],
                    primary_inputs=[
                        "WorkspaceHarness.methodics snapshot",
                        "execution state",
                        "assignments",
                        "definition-of-done evidence",
                        "resource requests",
                    ],
                    primary_outputs=[
                        "assignments",
                        "DoD verification",
                        "step advancement or rework",
                        "pending resource requests",
                        "final execution report",
                    ],
                    handoffs=[
                        "humans approve/reject resource requests and control start/cancel",
                        "participants complete assignments and provide evidence",
                    ],
                ),
                "execution_source": "WorkspaceHarness.methodics",
                "resource_attachment_policy": "human_gated",
                "dod_verification": "agent_only",
            },
            created_by=SYSTEM_ACTOR_ID,
            created_at=now,
            updated_at=now,
            metadata={
                "managed": True,
                "seeded": True,
                "agent_key": "conductor",
                "methodics_execution_agent": True,
                "task_routing": {
                    "normal_message_fanout": False,
                    "accepted_task_kinds": accepted_task_kinds,
                },
            },
        )

    @staticmethod
    def _platform_steward_iam_role(*, now: datetime) -> IamRoleDefinition:
        return IamRoleDefinition(
            role_id=PLATFORM_STEWARD_ROLE_ID,
            scope="global",
            subject_kind="agent",
            organization_id=None,
            name="platform_steward",
            description="Least-privilege platform operations permissions for Steward.",
            permissions=list(_STEWARD_AGENT_PERMISSIONS),
            created_at=now,
            updated_at=now,
            metadata={"seeded": True, "managed": True, "agent_key": "steward"},
        )

    @staticmethod
    def _global_conductor_iam_role(*, now: datetime) -> IamRoleDefinition:
        return IamRoleDefinition(
            role_id=GLOBAL_CONDUCTOR_ROLE_ID,
            scope="global",
            subject_kind="agent",
            organization_id=None,
            name="workspace_conductor",
            description=(
                "Least-privilege workspace methodics execution permissions for "
                "Conductor after explicit workspace attachment."
            ),
            permissions=list(_CONDUCTOR_AGENT_PERMISSIONS),
            created_at=now,
            updated_at=now,
            metadata={"seeded": True, "managed": True, "agent_key": "conductor"},
        )

    @staticmethod
    def _global_researcher_iam_role(*, now: datetime) -> IamRoleDefinition:
        return IamRoleDefinition(
            role_id=GLOBAL_RESEARCHER_ROLE_ID,
            scope="global",
            subject_kind="agent",
            organization_id=None,
            name="methodology_researcher",
            description=(
                "Least-privilege research dossier permissions for the seeded "
                "Researcher specialist."
            ),
            permissions=list(_RESEARCHER_AGENT_PERMISSIONS),
            created_at=now,
            updated_at=now,
            metadata={"seeded": True, "managed": True, "agent_key": "researcher"},
        )

    @staticmethod
    def _global_methodologist_iam_role(*, now: datetime) -> IamRoleDefinition:
        return IamRoleDefinition(
            role_id=GLOBAL_METHODOLOGIST_ROLE_ID,
            scope="global",
            subject_kind="agent",
            organization_id=None,
            name="methodology_methodologist",
            description=(
                "Least-privilege methodology blueprint drafting permissions for "
                "the seeded Methodologist specialist."
            ),
            permissions=list(_METHODOLOGIST_AGENT_PERMISSIONS),
            created_at=now,
            updated_at=now,
            metadata={"seeded": True, "managed": True, "agent_key": "methodologist"},
        )

    async def _control_plane_mcp_server(self, *, now: datetime) -> McpServerDefinition:
        existing = await self._find_mcp_server_by_key(
            scope="global",
            organization_id=None,
            server_key="open_talon_control_plane",
        )
        server = McpServerDefinition(
            server_id=CONTROL_PLANE_MCP_SERVER_ID,
            scope="global",
            organization_id=None,
            server_key="open_talon_control_plane",
            display_name="Open Talon Control Plane",
            description="Managed MCP server exposing authorized Open Talon control-plane APIs.",
            transport_kind="streamable_http",
            config={
                "url": "http://127.0.0.1:8000/v1/mcp",
                "auth": {"kind": "open_talon_agent_identity"},
            },
            secret_config={},
            trust_level="trusted",
            enabled=True,
            created_by=SYSTEM_ACTOR_ID,
            created_at=now,
            updated_by=SYSTEM_ACTOR_ID,
            updated_at=now,
            metadata={"seeded": True, "managed": True, "control_plane": True},
        )
        if existing is None:
            return server
        return server.model_copy(
            update={
                "server_id": existing.server_id,
                "created_by": existing.created_by,
                "created_at": existing.created_at,
                "metadata": {**existing.metadata, **server.metadata},
            }
        )

    async def _web_search_mcp_server(self, *, now: datetime) -> McpServerDefinition:
        existing = await self._find_mcp_server_by_key(
            scope="global",
            organization_id=None,
            server_key="web_search",
        )
        server = McpServerDefinition(
            server_id=WEB_SEARCH_PLUGIN_MCP_SERVER_ID,
            scope="global",
            organization_id=None,
            server_key="web_search",
            display_name="Web Search",
            description=(
                "Managed System Plugin for web search and page extraction backed by "
                "self-hosted SearXNG and Crawl4AI."
            ),
            transport_kind="streamable_http",
            config={
                "url": os.getenv("OPEN_TALON_WEB_SEARCH_MCP_URL", "http://127.0.0.1:8181/mcp"),
                "capabilities": ["search", "fetch", "search_and_fetch"],
            },
            secret_config={},
            trust_level="sandboxed",
            enabled=True,
            last_sync_status="not_synced",
            created_by=SYSTEM_ACTOR_ID,
            created_at=now,
            updated_by=SYSTEM_ACTOR_ID,
            updated_at=now,
            metadata={
                "seeded": True,
                "managed": True,
                "system_plugin": True,
                "plugin_key": "web_search",
                "backing_protocol": "mcp",
            },
        )
        if existing is None:
            return server
        return server.model_copy(
            update={
                "server_id": existing.server_id,
                "created_by": existing.created_by,
                "created_at": existing.created_at,
                "last_sync_status": existing.last_sync_status,
                "last_sync_error": existing.last_sync_error,
                "last_synced_at": existing.last_synced_at,
                "metadata": {**existing.metadata, **server.metadata},
            }
        )

    async def _library_mcp_server(self, *, now: datetime) -> McpServerDefinition:
        existing = await self._find_mcp_server_by_key(
            scope="global",
            organization_id=None,
            server_key="library",
        )
        server = McpServerDefinition(
            server_id=LIBRARY_PLUGIN_MCP_SERVER_ID,
            scope="global",
            organization_id=None,
            server_key="library",
            display_name="Library",
            description=(
                "Managed System Plugin for durable organization, project, and workspace "
                "reference libraries."
            ),
            transport_kind="streamable_http",
            config={
                "url": os.getenv("OPEN_TALON_LIBRARY_MCP_URL", "http://127.0.0.1:8000/v1/mcp"),
                "auth": {"kind": "open_talon_agent_identity"},
                "capabilities": ["libraries", "items", "attachments"],
                "managed_static_capabilities": True,
            },
            secret_config={},
            trust_level="trusted",
            enabled=True,
            last_sync_status="completed",
            last_synced_at=now,
            created_by=SYSTEM_ACTOR_ID,
            created_at=now,
            updated_by=SYSTEM_ACTOR_ID,
            updated_at=now,
            metadata={
                "seeded": True,
                "managed": True,
                "system_plugin": True,
                "plugin_key": "library",
                "backing_protocol": "mcp",
            },
        )
        if existing is None:
            return server
        return server.model_copy(
            update={
                "server_id": existing.server_id,
                "created_by": existing.created_by,
                "created_at": existing.created_at,
                "metadata": {**existing.metadata, **server.metadata},
            }
        )

    async def _retriever_mcp_server(self, *, now: datetime) -> McpServerDefinition:
        existing = await self._find_mcp_server_by_key(
            scope="global",
            organization_id=None,
            server_key="retriever",
        )
        server = McpServerDefinition(
            server_id=RETRIEVER_PLUGIN_MCP_SERVER_ID,
            scope="global",
            organization_id=None,
            server_key="retriever",
            display_name="Retriever",
            description=(
                "Managed System Plugin for explicit library indexing, retrieval search, "
                "and cited context packs."
            ),
            transport_kind="streamable_http",
            config={
                "url": os.getenv("OPEN_TALON_RETRIEVER_MCP_URL", "http://127.0.0.1:8000/v1/mcp"),
                "auth": {"kind": "open_talon_agent_identity"},
                "capabilities": ["index", "status", "search", "context_pack"],
                "docling_serve_url": os.getenv("OPEN_TALON_DOCLING_SERVE_URL"),
                "managed_static_capabilities": True,
            },
            secret_config={},
            trust_level="trusted",
            enabled=True,
            last_sync_status="completed",
            last_synced_at=now,
            created_by=SYSTEM_ACTOR_ID,
            created_at=now,
            updated_by=SYSTEM_ACTOR_ID,
            updated_at=now,
            metadata={
                "seeded": True,
                "managed": True,
                "system_plugin": True,
                "plugin_key": "retriever",
                "backing_protocol": "mcp",
            },
        )
        if existing is None:
            return server
        return server.model_copy(
            update={
                "server_id": existing.server_id,
                "created_by": existing.created_by,
                "created_at": existing.created_at,
                "metadata": {**existing.metadata, **server.metadata},
            }
        )

    @staticmethod
    def _managed_plugin_tool_definitions(
        *,
        server_id: UUID,
        tool_names: list[str],
        description_prefix: str,
        now: datetime,
    ) -> list[McpToolDefinition]:
        return [
            McpToolDefinition(
                server_id=server_id,
                tool_name=name,
                display_name=name,
                description=f"{description_prefix} {name}.",
                capability_hash="managed",
                discovered_at=now,
                metadata={"seeded": True, "managed": True},
            )
            for name in tool_names
        ]

    @staticmethod
    def _steward_internal_mcp_binding(
        *,
        agent_id: UUID,
        server_id: UUID,
        now: datetime,
    ) -> AgentInternalMcpServer:
        return AgentInternalMcpServer(
            system_agent_id=agent_id,
            server_id=server_id,
            server_key="open_talon_control_plane",
            display_name="Open Talon Control Plane",
            description="Managed MCP server exposing authorized Open Talon control-plane APIs.",
            transport_kind="streamable_http",
            trust_level="trusted",
            name_prefix="control_plane__",
            tool_allowlist=list(_STEWARD_CONTROL_PLANE_ALLOWLIST),
            tool_denylist=list(_CONTROL_PLANE_TOOL_DENYLIST),
            attached_by=SYSTEM_ACTOR_ID,
            attached_at=now,
            updated_at=now,
            metadata={"seeded": True, "managed": True, "agent_key": "steward"},
        )

    @staticmethod
    def _conductor_internal_mcp_binding(
        *,
        agent_id: UUID,
        server_id: UUID,
        now: datetime,
    ) -> AgentInternalMcpServer:
        return AgentInternalMcpServer(
            system_agent_id=agent_id,
            server_id=server_id,
            server_key="open_talon_control_plane",
            display_name="Open Talon Control Plane",
            description=(
                "Managed MCP server exposing Conductor-safe workspace coordination APIs."
            ),
            transport_kind="streamable_http",
            trust_level="trusted",
            name_prefix="control_plane__",
            tool_allowlist=list(_CONDUCTOR_CONTROL_PLANE_ALLOWLIST),
            tool_denylist=[
                *_METHODICS_HUMAN_CONTROL_PLANE_TOOLS,
                *_CONTROL_PLANE_TOOL_DENYLIST,
            ],
            attached_by=SYSTEM_ACTOR_ID,
            attached_at=now,
            updated_at=now,
            metadata={"seeded": True, "managed": True, "agent_key": "conductor"},
        )

    @staticmethod
    def _researcher_control_plane_mcp_binding(
        *,
        agent_id: UUID,
        server_id: UUID,
        now: datetime,
    ) -> AgentInternalMcpServer:
        return AgentInternalMcpServer(
            system_agent_id=agent_id,
            server_id=server_id,
            server_key="open_talon_control_plane",
            display_name="Open Talon Control Plane",
            description=(
                "Managed MCP server exposing Researcher-safe dossier persistence APIs."
            ),
            transport_kind="streamable_http",
            trust_level="trusted",
            name_prefix="control_plane__",
            tool_allowlist=list(_RESEARCHER_CONTROL_PLANE_ALLOWLIST),
            tool_denylist=list(_CONTROL_PLANE_TOOL_DENYLIST),
            attached_by=SYSTEM_ACTOR_ID,
            attached_at=now,
            updated_at=now,
            metadata={"seeded": True, "managed": True, "agent_key": "researcher"},
        )

    @staticmethod
    def _methodologist_internal_mcp_binding(
        *,
        agent_id: UUID,
        server_id: UUID,
        now: datetime,
    ) -> AgentInternalMcpServer:
        return AgentInternalMcpServer(
            system_agent_id=agent_id,
            server_id=server_id,
            server_key="open_talon_control_plane",
            display_name="Open Talon Control Plane",
            description=(
                "Managed MCP server exposing Methodologist-safe dossier read and "
                "blueprint draft submission APIs."
            ),
            transport_kind="streamable_http",
            trust_level="trusted",
            name_prefix="control_plane__",
            tool_allowlist=list(_METHODOLOGIST_CONTROL_PLANE_ALLOWLIST),
            tool_denylist=list(_CONTROL_PLANE_TOOL_DENYLIST),
            attached_by=SYSTEM_ACTOR_ID,
            attached_at=now,
            updated_at=now,
            metadata={"seeded": True, "managed": True, "agent_key": "methodologist"},
        )

    @staticmethod
    def _researcher_plugin_mcp_bindings(
        *,
        agent_id: UUID,
        library_server_id: UUID,
        retriever_server_id: UUID,
        web_search_server_id: UUID,
        now: datetime,
    ) -> list[AgentInternalMcpServer]:
        return [
            AgentInternalMcpServer(
                system_agent_id=agent_id,
                server_id=library_server_id,
                server_key="library",
                display_name="Library",
                description="Managed Library plugin for retained dossier sources.",
                transport_kind="streamable_http",
                trust_level="trusted",
                name_prefix="library__",
                tool_allowlist=list(_LIBRARY_PLUGIN_TOOL_NAMES),
                attached_by=SYSTEM_ACTOR_ID,
                attached_at=now,
                updated_at=now,
                metadata={"seeded": True, "managed": True, "agent_key": "researcher"},
            ),
            AgentInternalMcpServer(
                system_agent_id=agent_id,
                server_id=retriever_server_id,
                server_key="retriever",
                display_name="Retriever",
                description="Managed Retriever plugin for indexed search and context packs.",
                transport_kind="streamable_http",
                trust_level="trusted",
                name_prefix="retriever__",
                tool_allowlist=list(_RETRIEVER_PLUGIN_TOOL_NAMES),
                attached_by=SYSTEM_ACTOR_ID,
                attached_at=now,
                updated_at=now,
                metadata={"seeded": True, "managed": True, "agent_key": "researcher"},
            ),
            AgentInternalMcpServer(
                system_agent_id=agent_id,
                server_id=web_search_server_id,
                server_key="web_search",
                display_name="Web Search",
                description="Managed Web Search plugin for follow-up discovery and fetches.",
                transport_kind="streamable_http",
                trust_level="sandboxed",
                name_prefix="web_search__",
                tool_allowlist=[],
                attached_by=SYSTEM_ACTOR_ID,
                attached_at=now,
                updated_at=now,
                metadata={"seeded": True, "managed": True, "agent_key": "researcher"},
            ),
        ]

    async def _tinker_internal_tools(self, *, now: datetime) -> list[SystemToolDefinition]:
        list_tools = (
            self._repository.list_system_tools_by_scope
            if hasattr(self._repository, "list_system_tools_by_scope")
            else self._repository.list_system_tools
        )
        existing = {
            tool.name: tool
            for tool in await list_tools(
                scope="global",
                organization_id=None,
            )
        }
        tools: list[SystemToolDefinition] = []
        for (
            fallback_id,
            name,
            description,
            command,
            timeout_seconds,
            network,
        ) in _TINKER_INTERNAL_TOOL_SPECS:
            existing_tool = existing.get(name)
            tools.append(
                SystemToolDefinition(
                    tool_id=existing_tool.tool_id if existing_tool is not None else fallback_id,
                    scope="global",
                    organization_id=None,
                    name=name,
                    description=description,
                    parameter_contract=ToolParameterContract(additional_properties=True),
                    input_schema={"type": "object", "additionalProperties": True},
                    execution=ToolExecutionBinding(
                        backend_kind="local_process",
                        handler_ref="python",
                        execution_profile={
                            "command": [
                                "python",
                                "-m",
                                "generated_tools_builder.cli",
                                command,
                            ],
                            "timeout_seconds": timeout_seconds,
                            "network": network,
                            "workspace_access": "none",
                        },
                        trust_level="trusted",
                    ),
                    created_by=SYSTEM_ACTOR_ID,
                    created_at=(
                        existing_tool.created_at if existing_tool is not None else now
                    ),
                    updated_by=SYSTEM_ACTOR_ID,
                    updated_at=now,
                    metadata={
                        "seeded": True,
                        "managed": True,
                        "agent_key": "tinker",
                        "internal_only": True,
                    },
                )
            )
        return tools

    @staticmethod
    def _default_project_for_organization(
        organization: Organization,
        *,
        now: datetime,
    ) -> Project:
        return default_project_for_organization(
            organization,
            created_by=organization.created_by,
            creator_user_id=organization.created_by,
            creator_system_agent_id=None,
            owner_user_id=organization.created_by,
            owner_system_agent_id=None,
            now=now,
        )

    @staticmethod
    def _administration_project_for_organization(
        organization: Organization,
        *,
        now: datetime,
    ) -> Project:
        return administration_project_for_organization(
            organization,
            created_by=organization.created_by,
            creator_user_id=organization.created_by,
            creator_system_agent_id=None,
            owner_user_id=organization.created_by,
            owner_system_agent_id=None,
            now=now,
        )

    @staticmethod
    def _operations_workspace_for_organization(
        organization: Organization,
        project: Project,
        *,
        now: datetime,
    ) -> Workspace:
        return operations_workspace_for_organization(organization, project, now=now)

    async def _ensure_anchor_attached_for_workspace(
        self,
        conn: asyncpg.Connection,
        workspace_id: UUID,
        *,
        now: datetime,
    ) -> ParticipantProfile:
        return await ensure_anchor_attached_for_workspace(
            self._repository,
            conn,
            workspace_id,
            now=now,
        )

    @staticmethod
    def _anchor_participant_for_workspace(
        workspace_id: UUID,
        *,
        agent_id: UUID = ANCHOR_AGENT_ID,
        now: datetime,
    ) -> ParticipantProfile:
        return anchor_participant_for_workspace(workspace_id, agent_id=agent_id, now=now)

    @staticmethod
    def _curator_agent_for_organization(
        organization: Organization,
        *,
        now: datetime,
    ) -> AgentDefinition:
        return curator_agent_for_organization(organization, now=now)

    @staticmethod
    def _curator_iam_role_for_organization(
        organization_id: UUID,
        *,
        now: datetime,
    ) -> IamRoleDefinition:
        return curator_iam_role_for_organization(organization_id, now=now)

    @staticmethod
    def _operations_participant_for_agent(
        *,
        workspace: Workspace,
        agent: AgentDefinition,
        now: datetime,
    ) -> ParticipantProfile:
        return operations_participant_for_agent(workspace=workspace, agent=agent, now=now)

    @staticmethod
    def _curator_internal_mcp_binding(
        *,
        agent_id: UUID,
        server_id: UUID,
        now: datetime,
    ) -> AgentInternalMcpServer:
        return curator_internal_mcp_binding(
            agent_id=agent_id,
            server_id=server_id,
            now=now,
        )


def _project_subject_access_bindings(
    project: Project,
    *,
    now: datetime,
) -> list[ProjectAccessBinding]:
    bindings: list[ProjectAccessBinding] = []
    owner_subject = (project.owner_user_id, project.owner_system_agent_id)
    creator_subject = (project.creator_user_id, project.creator_system_agent_id)

    def append_binding(
        *,
        role: str,
        user_id: UUID | None,
        system_agent_id: UUID | None,
        source: str,
    ) -> None:
        if user_id is None and system_agent_id is None:
            return
        bindings.append(
            ProjectAccessBinding(
                project_id=project.project_id,
                subject_type="agent" if system_agent_id is not None else "user",
                user_id=user_id,
                system_agent_id=system_agent_id,
                role=role,
                created_at=project.created_at,
                updated_at=now,
                metadata={"seeded": True, "managed": True, "source": source},
            )
        )

    if owner_subject != creator_subject:
        append_binding(
            role="owner",
            user_id=project.owner_user_id,
            system_agent_id=project.owner_system_agent_id,
            source="project_owner",
        )
    append_binding(
        role="creator",
        user_id=project.creator_user_id,
        system_agent_id=project.creator_system_agent_id,
        source="project_creator",
    )
    return bindings


def default_project_for_organization(
    organization: Organization,
    *,
    created_by: UUID,
    creator_user_id: UUID | None,
    creator_system_agent_id: UUID | None,
    owner_user_id: UUID | None,
    owner_system_agent_id: UUID | None,
    now: datetime,
) -> Project:
    return Project(
        project_id=uuid5(
            NAMESPACE_URL,
            f"open-talon-default-project:{organization.organization_id}",
        ),
        organization_id=organization.organization_id,
        slug="default",
        name="Default Project",
        description="Default project for workspaces that do not specify a project.",
        created_by=created_by,
        creator_user_id=creator_user_id,
        creator_system_agent_id=creator_system_agent_id,
        owner_user_id=owner_user_id,
        owner_system_agent_id=owner_system_agent_id,
        created_at=now,
        updated_at=now,
        metadata={"seeded": True, "managed": True},
    )


def administration_project_for_organization(
    organization: Organization,
    *,
    created_by: UUID,
    creator_user_id: UUID | None,
    creator_system_agent_id: UUID | None,
    owner_user_id: UUID | None,
    owner_system_agent_id: UUID | None,
    now: datetime,
) -> Project:
    return Project(
        project_id=uuid5(
            NAMESPACE_URL,
            f"open-talon-administration-project:{organization.organization_id}",
        ),
        organization_id=organization.organization_id,
        slug="administration",
        name="Administration",
        description="Managed project for operational agents and administrative workspaces.",
        created_by=created_by,
        creator_user_id=creator_user_id,
        creator_system_agent_id=creator_system_agent_id,
        owner_user_id=owner_user_id,
        owner_system_agent_id=owner_system_agent_id,
        created_at=now,
        updated_at=now,
        metadata={"seeded": True, "managed": True, "administration": True},
    )


def operations_workspace_for_organization(
    organization: Organization,
    project: Project,
    *,
    now: datetime,
) -> Workspace:
    is_system_base = organization.organization_id == SYSTEM_BASE_ORGANIZATION_ID
    creator_user_id = (
        None if project.creator_user_id == SYSTEM_ACTOR_ID else project.creator_user_id
    )
    creator_system_agent_id = (
        None
        if project.creator_system_agent_id == SYSTEM_ACTOR_ID
        else project.creator_system_agent_id
    )
    return Workspace(
        workspace_id=uuid5(
            NAMESPACE_URL,
            f"open-talon-operations-workspace:{organization.organization_id}",
        ),
        organization_id=organization.organization_id,
        project_id=project.project_id,
        name="System Operations" if is_system_base else "Organization Operations",
        description=(
            "Managed workspace for platform operations."
            if is_system_base
            else "Managed workspace for organization operations."
        ),
        owner_user_id=None,
        created_by=project.created_by,
        creator_user_id=creator_user_id,
        creator_system_agent_id=creator_system_agent_id,
        created_at=now,
        updated_at=now,
        metadata={
            "seeded": True,
            "managed": True,
            "administration": True,
            "operations_workspace": True,
            "operations_level": "system" if is_system_base else "organization",
        },
    )


def anchor_agent_definition(*, now: datetime) -> AgentDefinition:
    return ManagedSystemDefaultsRepairer._anchor_agent_definition(now=now)


def anchor_participant_for_workspace(
    workspace_id: UUID,
    *,
    agent_id: UUID = ANCHOR_AGENT_ID,
    now: datetime,
) -> ParticipantProfile:
    participant_digest = hashlib.md5(  # noqa: S324 - deterministic identifier, not security.
        f"open-talon-anchor-participant:{workspace_id}".encode("utf-8")
    ).hexdigest()
    return ParticipantProfile(
        participant_id=UUID(hex=participant_digest),
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=agent_id,
        display_name="Anchor",
        description=(
            "Reviews workspace communication for topic fit, applies the workspace "
            "topic-freedom policy, and explains blocked messages when configured."
        ),
        roles=[ANCHOR_ROLE],
        capabilities=list(ANCHOR_CAPABILITIES),
        status="active",
        visibility_scope="workspace",
        created_at=now,
        updated_at=now,
        metadata={
            "seeded": True,
            "managed": True,
            "agent_key": "anchor",
            "task_routing": {
                "normal_message_fanout": False,
                "accepted_task_kinds": [ANCHOR_TASK_KIND],
            },
        },
    )


async def ensure_anchor_attached_for_workspace(
    repository: CollaborationRepository,
    conn: asyncpg.Connection,
    workspace_id: UUID,
    *,
    now: datetime,
) -> ParticipantProfile:
    finder = ManagedSystemDefaultsRepairer(repository)._find_system_agent_by_key
    existing = await finder(scope="global", organization_id=None, agent_key="anchor")
    agent = anchor_agent_definition(now=now)
    if existing is not None:
        agent = agent.model_copy(
            update={
                "agent_id": existing.agent_id,
                "active_agent_version_id": existing.active_agent_version_id,
                "created_by": existing.created_by,
                "created_at": existing.created_at,
                "metadata": {**existing.metadata, **agent.metadata},
            }
        )
    participant = anchor_participant_for_workspace(
        workspace_id,
        agent_id=agent.agent_id,
        now=now,
    )
    await repository.upsert_system_agent(conn, agent)
    await repository.upsert_participant(conn, participant)
    return participant


def curator_agent_for_organization(
    organization: Organization,
    *,
    now: datetime,
) -> AgentDefinition:
    return AgentDefinition(
        agent_id=uuid5(
            NAMESPACE_URL,
            f"open-talon-curator-agent:{organization.organization_id}",
        ),
        agent_key="curator",
        scope="organization",
        organization_id=organization.organization_id,
        display_name="Curator",
        description=(
            "Manages organization, project, and workspace operations through "
            "authorized control-plane APIs."
        ),
        role="organization operations curator",
        capabilities=[
            "manages organization projects and workspaces through authorized control-plane tools",
            "coordinates organization-scoped workspace administration",
            "reviews organization audit and runtime health",
            "keeps organization resources inside tenant boundaries",
            "maintains managed organization operations contexts",
        ],
        endpoint=AgentEndpoint(
            kind="system",
            engine_id="openai-responses",
            provider="openai",
        ),
        system_prompt=(
            "You are Curator, the organization operations agent. Operate only "
            "inside your organization through authorized APIs and MCP tools. "
            "Respect organization boundaries and use the Administration project "
            "for operational work."
        ),
        definition={
            "runtime": {
                "engine_id": "openai-responses",
                "preferred_capabilities": ["reasoning", "tool_calling"],
                "preferred_locality": "cloud",
            },
            "seeded": True,
            "managed": True,
            "agent_key": "curator",
            "organization_id": str(organization.organization_id),
            "profile": _seeded_agent_profile(
                kind="organization_operations_specialist",
                mandate=(
                    "Manage organization-local projects, workspaces, catalog resources, "
                    "runtime health, and operational context."
                ),
                activation=(
                    "Seeded per non-system organization and targeted through that "
                    "organization's Operations workspace."
                ),
                authority=[
                    "organization_curator IAM role",
                    "Organization Operations workspace attachment",
                    "organization-scoped private control-plane MCP allowlist",
                ],
                boundaries=[
                    "stay inside the owning organization",
                    "do not perform platform-wide discovery",
                    "destructive control-plane operations remain denied",
                ],
                primary_inputs=[
                    "organization-local control-plane context",
                    "projects and workspaces",
                    "catalog/provider/runtime health",
                ],
                primary_outputs=[
                    "organization-local projects",
                    "workspaces",
                    "resource status",
                    "operational follow-up",
                ],
            ),
        },
        created_by=organization.created_by,
        created_at=now,
        updated_at=now,
        metadata={
            "managed": True,
            "seeded": True,
            "agent_key": "curator",
            "organization_id": str(organization.organization_id),
        },
    )


def curator_iam_role_for_organization(
    organization_id: UUID,
    *,
    now: datetime,
) -> IamRoleDefinition:
    return IamRoleDefinition(
        role_id=uuid5(
            NAMESPACE_URL,
            f"open-talon-curator-iam-role:{organization_id}",
        ),
        scope="organization",
        subject_kind="agent",
        organization_id=organization_id,
        name="organization_curator",
        description="Least-privilege organization operations permissions for Curator.",
        permissions=list(_CURATOR_AGENT_PERMISSIONS),
        created_at=now,
        updated_at=now,
        metadata={
            "seeded": True,
            "managed": True,
            "agent_key": "curator",
            "organization_id": str(organization_id),
        },
    )


def operations_participant_for_agent(
    *,
    workspace: Workspace,
    agent: AgentDefinition,
    now: datetime,
) -> ParticipantProfile:
    return ParticipantProfile(
        participant_id=uuid5(
            NAMESPACE_URL,
            f"open-talon-operations-participant:{workspace.workspace_id}:{agent.agent_id}",
        ),
        workspace_id=workspace.workspace_id,
        participant_type="agent",
        system_agent_id=agent.agent_id,
        display_name=agent.display_name,
        description=f"{agent.display_name} attached to the managed operations workspace.",
        roles=[agent.role],
        capabilities=list(agent.capabilities),
        status="active",
        visibility_scope="workspace",
        created_at=now,
        updated_at=now,
        metadata={"seeded": True, "managed": True, "operations_participant": True},
    )


def curator_internal_mcp_binding(
    *,
    agent_id: UUID,
    server_id: UUID,
    now: datetime,
) -> AgentInternalMcpServer:
    return AgentInternalMcpServer(
        system_agent_id=agent_id,
        server_id=server_id,
        server_key="open_talon_control_plane",
        display_name="Open Talon Control Plane",
        description="Managed MCP server exposing authorized Open Talon control-plane APIs.",
        transport_kind="streamable_http",
        trust_level="trusted",
        name_prefix="control_plane__",
        tool_allowlist=list(_CURATOR_CONTROL_PLANE_ALLOWLIST),
        tool_denylist=[
            "organizations.list",
            *_CONTROL_PLANE_TOOL_DENYLIST,
        ],
        attached_by=SYSTEM_ACTOR_ID,
        attached_at=now,
        updated_at=now,
        metadata={"seeded": True, "managed": True, "agent_key": "curator"},
    )
