from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
_WORKSPACE_MEMORY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/workspace-memory")
)
_AGENT_RUNTIME_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/agent-runtime")
)
for path in (_CONTRACTS_DIR, _CORE_COLLAB_DIR, _WORKSPACE_MEMORY_DIR, _AGENT_RUNTIME_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_contracts.agent_contracts import (  # noqa: E402
    build_default_interaction_contract,
    interaction_contract_is_empty,
)
from support.model_constants import TEST_EXPLICIT_OLLAMA_MODEL  # noqa: E402
from open_talon_contracts.iam import WORKSPACE_PERMISSION_NAMES  # noqa: E402
from open_talon_contracts.log_management import (  # noqa: E402
    RotationPolicy,
    append_jsonl_with_rotation,
)
from open_talon_contracts.models import (  # noqa: E402
    ActorRef,
    AgentCompactionPolicy,
    AgentDefinition,
    AgentDefinitionVersion,
    AgentEndpoint,
    AgentHarness,
    AgentInternalMcpServer,
    AgentInternalToolBinding,
    AgentMemoryPolicy,
    AgentRunResult,
    AgentToolCallDraft,
    AgentToolUsePolicy,
    ApplyMethodologyBlueprintRequest,
    AssumeParticipantRoleRequest,
    ArtifactRef,
    AttachResearchDossierContextPackRequest,
    CreateAgentParticipantRequest,
    CreateGitRepositoryRequest,
    CreateThreadRequest,
    CreateLlmProviderRequest,
    CreateMethodologyBlueprintRequest,
    CreateOrganizationRequest,
    CreateProjectRequest,
    CreateResearchDossierSourceRequest,
    CreateWorkspaceRequest,
    CreateSystemToolRequest,
    EventEnvelope,
    ExecutionSpec,
    CompletionRule,
    CancelMethodicExecutionRequest,
    CreateInteractionAnswerRequest,
    CreateInteractionQuestionRequest,
    CreateInteractionRequest,
    CreateInteractionRequestsRequest,
    CreateMethodicAssignmentRequest,
    CreateMethodicExecutionRequest,
    CreateMethodicResourceRequestRequest,
    CreateMessageRequest,
    CreateToolGenerationRevisionRequest,
    DeleteLlmProviderRequest,
    GeneratedToolManifest,
    GeneratedToolValidationReport,
    InteractionAnswer,
    InteractionQuestion,
    InteractionQuestionDraft,
    InteractionRequest,
    InteractionRequestDetail,
    InteractionRequestDraft,
    InteractionRequestTarget,
    Library,
    LibraryItem,
    LlmProviderDefinition,
    MarkResearchDossierReadyRequest,
    MemoryEntry,
    MemoryProviderDefinition,
    MemoryProviderRecord,
    NavigateResearchDossierRequest,
    MethodicExecution,
    MethodicExecutionAssignment,
    MethodicExecutionCheck,
    MethodicExecutionDetail,
    MethodicExecutionStep,
    MethodicResourceRequest,
    MethodologyBlueprint,
    MethodologyBlueprintDetail,
    MethodologyBlueprintVersion,
    McpServerDefinition,
    McpToolDefinition,
    Organization,
    ParticipantProfile,
    PublicationReview,
    Project,
    ProjectAccessBinding,
    ProjectSubjectRef,
    ResearchDossier,
    ResearchDossierClaim,
    ResearchDossierConcept,
    ResearchDossierEvent,
    ResearchDossierHealthCheck,
    ResearchDossierLink,
    ResearchDossierNote,
    ResearchDossierNotebook,
    ResearchDossierNotebookDetail,
    ResearchDossierProviderBinding,
    ResearchDossierProviderExternalRef,
    ResearchDossierSource,
    ResearchDossierSyncRun,
    RetrievalContextPack,
    Run,
    RunStep,
    SearchMemoryRequest,
    SeededAgentProfile,
    SubmitMethodologyBlueprintDraftRequest,
    SubmitResearchDossierHealthCheckRequest,
    SyncResearchDossierNotebookRequest,
    TargetRef,
    ToolCall,
    ToolCallResult,
    SystemToolDefinition,
    ToolExecutionBinding,
    ToolGenerationRequest,
    ToolGenerationRevision,
    CreateSystemAgentRequest,
    HarnessExecutionRule,
    ParticipantInput,
    Task,
    Thread,
    TimelineMessage,
    UpdateSystemAgentRequest,
    UpdateInteractionRequestRequest,
    UpdateLlmProviderRequest,
    UpdateProjectRequest,
    UpdateResearchDossierSourceRequest,
    UpsertProjectAccessRequest,
    UpsertResearchDossierClaimRequest,
    UpsertResearchDossierConceptRequest,
    UpsertResearchDossierLinkRequest,
    UpsertResearchDossierNoteRequest,
    EvaluateMethodicStepRequest,
    ReviewToolGenerationRevisionRequest,
    RemoveProjectAccessRequest,
    UpdateWorkspaceRequest,
    ReviewMethodologyBlueprintVersionRequest,
    UpsertRoleDefinitionRequest,
    Workspace,
    WorkspaceAsset,
    WorkspaceAssetVersion,
    WorkspaceCommunicationLogEntry,
    WorkspaceCommunicationLogPage,
    WorkspaceHarness,
    WorkspaceMethodic,
    WorkspaceMethodicStep,
    WorkspaceMethodology,
    WorkspaceModerationPolicy,
    WorkspaceMcpTool,
    WorkspaceTool,
)
from core_collab.kernel import ANCHOR_AGENT_ID, CollaborationKernel  # noqa: E402
from core_collab.repository import CollaborationRepository  # noqa: E402
from core_collab.runtime_execution import RuntimeExecutionService  # noqa: E402
from core_collab.system_defaults import (  # noqa: E402
    CONDUCTOR_AGENT_ID,
    ManagedSystemDefaultsRepairer,
    curator_iam_role_for_organization,
    curator_agent_for_organization,
)

ROOT_DIR = Path(__file__).resolve().parents[2]

SEEDED_AGENT_PROFILE_DOCS = {
    "reasoning-planner.md": (
        "display_name",
        "Reasoning Planner",
        "Reasoning Planner",
        "example_planning_participant",
    ),
    "tinker.md": (
        "agent_key",
        "tinker",
        "Tinker",
        "workspace_tool_generation_specialist",
    ),
    "steward.md": (
        "agent_key",
        "steward",
        "Steward",
        "platform_operations_specialist",
    ),
    "curator.md": (
        "agent_key",
        "curator",
        "Curator",
        "organization_operations_specialist",
    ),
    "anchor.md": (
        "agent_key",
        "anchor",
        "Anchor",
        "workspace_topic_governance_reviewer",
    ),
    "researcher.md": (
        "agent_key",
        "researcher",
        "Researcher",
        "methodology_research_dossier_specialist",
    ),
    "methodologist.md": (
        "agent_key",
        "methodologist",
        "Methodologist",
        "methodology_blueprint_synthesis_specialist",
    ),
    "conductor.md": (
        "agent_key",
        "conductor",
        "Conductor",
        "workspace_methodics_execution_specialist",
    ),
}


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, repository):
        self._repository = repository

    def transaction(self):
        return _FakeTransaction()

    async def fetchval(self, query, *args):
        normalized = " ".join(query.split())
        if "FROM tool_calls" in normalized and "COUNT(*)" in normalized:
            run_step_id = args[0]
            return sum(
                1
                for tool_calls in self._repository._tool_calls.values()
                for tool_call in tool_calls
                if tool_call.run_step_id == run_step_id
                and tool_call.status not in {"completed", "failed"}
            )
        if "FROM run_steps" in normalized and "SELECT status" in normalized:
            step_id = args[0]
            step = self._repository._run_steps.get(step_id)
            return step.status if step is not None else None
        raise NotImplementedError(f"Unsupported fake fetchval query: {normalized}")


class _FakeAcquire:
    def __init__(self, repository):
        self._repository = repository

    async def __aenter__(self):
        return _FakeConnection(self._repository)

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, repository):
        self._repository = repository

    def acquire(self):
        return _FakeAcquire(self._repository)


class FakeRepository:
    def __init__(
        self,
        agents: list[AgentDefinition] | None = None,
        *,
        communication_log_dir: str | Path | None = None,
    ) -> None:
        self._agents = {agent.agent_id: agent for agent in agents or []}
        self._agent_versions = {}
        self._pool = _FakePool(self)
        self._communication_log_dir = (
            Path(communication_log_dir) if communication_log_dir is not None else None
        )
        self._communication_log_policy = RotationPolicy.from_env(
            max_bytes_var="OPEN_TALON_COMMUNICATION_LOG_MAX_BYTES",
            backup_count_var="OPEN_TALON_COMMUNICATION_LOG_BACKUP_COUNT",
            default_max_bytes=20 * 1024 * 1024,
            default_backup_count=10,
        )
        self.setup_schema_calls = 0
        self.upserted_agents: list[AgentDefinition] = []
        self.recorded_events: list[EventEnvelope] = []
        self._tasks = {}
        self._runs = {}
        self._run_steps = {}
        self._organizations = {}
        self._projects = {}
        self._project_access_bindings = {}
        self._iam_roles = {}
        self._agent_internal_mcp_servers = {}
        self._workspaces = {}
        self._threads = {}
        self._participants = {}
        self._memory_entries = {}
        self._messages = {}
        self._publication_reviews = {}
        self._system_tools = {}
        self._llm_providers = {}
        self._mcp_servers = {}
        self._mcp_server_tools = {}
        self._git_repositories = {}
        self._workspace_sequences = {}
        self._thread_sequences = {}
        self._runtime_queue_stats = {}
        self._global_token_total = 0
        self._workspace_token_totals = {}
        self._memberships = {}
        now = datetime.now(timezone.utc)
        postgres_provider = MemoryProviderDefinition(
            provider_id=uuid4(),
            provider_key="postgres",
            display_name="Postgres",
            description="Canonical memory provider",
            provider="postgres",
            enabled=True,
            config={},
            secret_config={},
            created_by=uuid4(),
            created_at=now,
            updated_by=uuid4(),
            updated_at=now,
            metadata={},
        )
        self._memory_providers = {postgres_provider.provider_id: postgres_provider}
        self._memory_provider_records = {}
        self._workspace_tools = {}
        self._workspace_mcp_tools = {}
        self._agent_internal_tools = {}
        self._tool_calls = {}
        self._tool_generation_requests = {}
        self._tool_generation_revisions = {}
        self._interaction_requests = {}
        self._interaction_questions = {}
        self._interaction_targets = {}
        self._interaction_answers = {}
        self._methodic_executions = {}
        self._methodic_steps = {}
        self._methodic_assignments = {}
        self._methodic_checks = {}
        self._methodic_resource_requests = {}
        self._libraries = {}
        self._library_items = {}
        self._workspace_assets = {}
        self._workspace_asset_versions = {}
        self._retrieval_context_packs = {}
        self._methodology_blueprints = {}
        self._methodology_blueprint_versions = {}
        self._research_dossiers = {}
        self._research_dossier_sources = {}
        self._research_dossier_events = {}
        self._research_dossier_notebooks = {}
        self._research_dossier_notes = {}
        self._research_dossier_concepts = {}
        self._research_dossier_claims = {}
        self._research_dossier_links = {}
        self._research_dossier_provider_bindings = {}
        self._research_dossier_provider_external_refs = {}
        self._research_dossier_sync_runs = {}
        self._research_dossier_health_checks = {}
        default_organization = Organization(
            organization_id=UUID("11111111-1111-1111-1111-111111111111"),
            slug="default",
            name="Default Organization",
            created_by=uuid4(),
            created_at=now,
            updated_at=now,
            metadata={},
        )
        self._organizations[default_organization.organization_id] = default_organization

    async def setup_schema(self) -> None:
        self.setup_schema_calls += 1

    async def list_system_agents(self) -> list[AgentDefinition]:
        return list(self._agents.values())

    async def list_system_agents_referencing_llm_engine(self, engine_id: str) -> list[AgentDefinition]:
        referenced: list[AgentDefinition] = []
        for agent in self._agents.values():
            if agent.endpoint.engine_id == engine_id:
                referenced.append(agent)
                continue
            runtime = agent.definition.get("runtime")
            if not isinstance(runtime, dict):
                continue
            if runtime.get("engine_id") == engine_id:
                referenced.append(agent)
                continue
            preferred_engine_ids = runtime.get("preferred_engine_ids")
            if isinstance(preferred_engine_ids, list) and engine_id in preferred_engine_ids:
                referenced.append(agent)
        return referenced

    async def upsert_system_agent(self, conn, agent: AgentDefinition) -> None:
        self._agents[agent.agent_id] = agent
        self.upserted_agents.append(agent)

    async def fetch_system_agent(self, agent_id):
        return self._agents.get(agent_id)

    async def fetch_system_agent_by_key(self, *, scope: str, organization_id, agent_key: str):
        for agent in self._agents.values():
            if (
                agent.scope == scope
                and agent.organization_id == organization_id
                and agent.agent_key == agent_key
            ):
                return agent
        return None

    async def next_agent_definition_version(self, conn, agent_id):
        versions = [
            version.version
            for version in self._agent_versions.values()
            if version.agent_id == agent_id
        ]
        return max(versions, default=0) + 1

    async def upsert_agent_definition_version(self, conn, version: AgentDefinitionVersion):
        self._agent_versions[version.agent_version_id] = version

    async def fetch_agent_definition_version_by_source(
        self,
        *,
        agent_id,
        git_repository_id,
        git_commit_sha,
        bundle_path,
    ):
        for version in self._agent_versions.values():
            if (
                version.agent_id == agent_id
                and version.git_repository_id == git_repository_id
                and version.git_commit_sha == git_commit_sha
                and version.bundle_path == bundle_path
            ):
                return version
        return None

    async def fetch_agent_definition_version(self, agent_version_id):
        return self._agent_versions.get(agent_version_id)

    async def list_agent_definition_versions(self, agent_id):
        versions = [
            version
            for version in self._agent_versions.values()
            if version.agent_id == agent_id
        ]
        return sorted(versions, key=lambda item: item.version, reverse=True)

    async def fetch_task(self, task_id):
        return self._tasks.get(task_id)

    async def upsert_task(self, conn, task):
        self._tasks[task.task_id] = task

    async def list_pending_tasks_for_system_agent(self, system_agent_id, *, limit=10):
        tasks = [
            task
            for task in self._tasks.values()
            if task.status in {"created", "released"}
            and task.metadata.get("target_system_agent_id") == str(system_agent_id)
        ]
        tasks.sort(key=lambda item: item.created_at)
        return tasks[:limit]

    async def claim_task(self, conn, *, task_id, participant_id, updated_at):
        task = self._tasks.get(task_id)
        if task is None or task.status not in {"created", "released"}:
            return None
        claimed = task.model_copy(
            update={
                "status": "claimed",
                "claimed_by": participant_id,
                "updated_at": updated_at,
            }
        )
        self._tasks[task_id] = claimed
        return claimed

    async def fetch_run(self, run_id):
        return self._runs.get(run_id)

    async def fetch_run_step(self, step_id):
        return self._run_steps.get(step_id)

    async def claim_next_run_step(self, *, worker_id, lease_expires_at, now):
        candidates = [
            step
            for step in self._run_steps.values()
            if step.status == "created"
            and (step.next_retry_at is None or step.next_retry_at <= now)
        ]
        candidates.sort(
            key=lambda item: (
                item.submitted_at or item.created_at,
                item.step_index,
                item.step_id,
            )
        )
        if not candidates:
            return None
        step = candidates[0]
        claimed = step.model_copy(
            update={
                "status": "claimed",
                "claimed_by_worker": worker_id,
                "attempt_count": step.attempt_count + 1,
                "lease_expires_at": lease_expires_at,
                "last_heartbeat_at": now,
                "updated_at": now,
            }
        )
        self._run_steps[step.step_id] = claimed
        return claimed

    async def upsert_organization(self, conn, organization: Organization) -> None:
        self._organizations[organization.organization_id] = organization

    async def list_organizations(self):
        return list(self._organizations.values())

    async def fetch_organization(self, organization_id):
        return self._organizations.get(organization_id)

    async def fetch_organization_by_slug(self, slug):
        for organization in self._organizations.values():
            if organization.slug == slug:
                return organization
        return None

    async def upsert_organization_membership(self, conn, membership) -> None:
        self._memberships[(membership.organization_id, membership.user_id)] = membership

    async def upsert_project(self, conn, project: Project) -> None:
        self._projects[project.project_id] = project

    async def fetch_project(self, project_id):
        return self._projects.get(project_id)

    async def fetch_project_by_slug(self, *, organization_id, slug):
        for project in self._projects.values():
            if project.organization_id == organization_id and project.slug == slug:
                return project
        return None

    async def fetch_default_project(self, organization_id):
        return await self.fetch_project_by_slug(
            organization_id=organization_id,
            slug="default",
        )

    async def list_projects(self, organization_id):
        return [
            project
            for project in self._projects.values()
            if project.organization_id == organization_id
        ]

    async def list_projects_for_user(self, *, organization_id, user_id):
        return [
            project
            for project in self._projects.values()
            if project.organization_id == organization_id
            and (project.project_id, "user", user_id) in self._project_access_bindings
        ]

    async def list_projects_for_agent(self, *, organization_id, system_agent_id):
        return [
            project
            for project in self._projects.values()
            if project.organization_id == organization_id
            and (project.project_id, "agent", system_agent_id) in self._project_access_bindings
        ]

    async def upsert_project_access_binding(self, conn, binding: ProjectAccessBinding):
        subject_id = binding.user_id or binding.system_agent_id
        self._project_access_bindings[
            (binding.project_id, binding.subject_type, subject_id)
        ] = binding

    async def upsert_iam_role_definition(self, conn, role):
        self._iam_roles[role.role_id] = role

    async def list_iam_role_definitions(
        self,
        *,
        subject_kind: str,
        scope: str | None = None,
        organization_id=None,
    ):
        return [
            role
            for role in self._iam_roles.values()
            if role.subject_kind == subject_kind
            and (scope is None or role.scope == scope)
            and (
                scope is None
                or (scope == "global" and role.organization_id is None)
                or (scope == "organization" and role.organization_id == organization_id)
            )
        ]

    async def upsert_agent_internal_mcp_server(self, conn, *, binding: AgentInternalMcpServer):
        self._agent_internal_mcp_servers[(binding.system_agent_id, binding.server_id)] = binding

    async def list_agent_internal_mcp_servers(self, system_agent_id):
        return [
            binding
            for (agent_id, _), binding in self._agent_internal_mcp_servers.items()
            if agent_id == system_agent_id
        ]

    async def list_claimable_system_agents(self):
        return list(self._agents.values())

    async def list_project_access_bindings(self, project_id):
        return [
            binding
            for (binding_project_id, _, _), binding in self._project_access_bindings.items()
            if binding_project_id == project_id
        ]

    async def fetch_project_access_for_user(self, *, project_id, user_id):
        return self._project_access_bindings.get((project_id, "user", user_id))

    async def fetch_project_access_for_agent(self, *, project_id, system_agent_id):
        return self._project_access_bindings.get((project_id, "agent", system_agent_id))

    async def delete_project_access_binding(
        self,
        conn,
        *,
        project_id,
        user_id=None,
        system_agent_id=None,
    ):
        if user_id is not None:
            key = (project_id, "user", user_id)
        else:
            key = (project_id, "agent", system_agent_id)
        return self._project_access_bindings.pop(key, None) is not None

    async def fetch_workspace(self, workspace_id):
        return self._workspaces.get(workspace_id)

    async def list_workspaces(self, *, organization_id=None, project_id=None):
        return [
            workspace
            for workspace in self._workspaces.values()
            if (organization_id is None or workspace.organization_id == organization_id)
            and (project_id is None or workspace.project_id == project_id)
        ]

    async def list_workspaces_for_user(self, user_id, *, organization_id=None, project_id=None):
        visible = []
        for workspace in self._workspaces.values():
            if organization_id is not None and workspace.organization_id != organization_id:
                continue
            if project_id is not None and workspace.project_id != project_id:
                continue
            if (workspace.project_id, "user", user_id) in self._project_access_bindings:
                visible.append(workspace)
        return visible

    async def list_workspaces_for_agent(
        self,
        system_agent_id,
        *,
        organization_id=None,
        project_id=None,
    ):
        visible = []
        for workspace in self._workspaces.values():
            if organization_id is not None and workspace.organization_id != organization_id:
                continue
            if project_id is not None and workspace.project_id != project_id:
                continue
            attached = any(
                participant.workspace_id == workspace.workspace_id
                and getattr(participant, "system_agent_id", None) == system_agent_id
                for participant in self._participants.values()
            )
            if (
                (workspace.project_id, "agent", system_agent_id) in self._project_access_bindings
                or attached
            ):
                visible.append(workspace)
        return visible

    async def fetch_library(self, library_id):
        return self._libraries.get(library_id)

    async def upsert_library(self, conn, library: Library) -> None:
        self._libraries[library.library_id] = library

    async def fetch_library_item(self, item_id):
        return self._library_items.get(item_id)

    async def fetch_workspace_asset(self, asset_id):
        return self._workspace_assets.get(asset_id)

    async def fetch_workspace_asset_version(self, asset_version_id):
        return self._workspace_asset_versions.get(asset_version_id)

    async def list_workspace_asset_versions(self, asset_id):
        return [
            version
            for version in self._workspace_asset_versions.values()
            if version.asset_id == asset_id
        ]

    async def fetch_retrieval_context_pack(self, context_pack_id):
        return self._retrieval_context_packs.get(context_pack_id)

    async def upsert_retrieval_context_pack(self, conn, context_pack):
        self._retrieval_context_packs[context_pack.context_pack_id] = context_pack

    async def next_methodology_blueprint_version_number(self, conn, blueprint_id):
        versions = [
            version.version_number
            for version in self._methodology_blueprint_versions.values()
            if version.blueprint_id == blueprint_id
        ]
        return max(versions, default=0) + 1

    async def upsert_methodology_blueprint(
        self,
        conn,
        blueprint: MethodologyBlueprint,
    ) -> None:
        self._methodology_blueprints[blueprint.blueprint_id] = blueprint

    async def upsert_methodology_blueprint_version(
        self,
        conn,
        version: MethodologyBlueprintVersion,
    ) -> None:
        self._methodology_blueprint_versions[version.version_id] = version

    async def upsert_research_dossier(self, conn, dossier: ResearchDossier) -> None:
        self._research_dossiers[dossier.dossier_id] = dossier

    async def upsert_research_dossier_notebook(
        self,
        conn,
        notebook: ResearchDossierNotebook,
    ) -> None:
        self._research_dossier_notebooks[notebook.notebook_id] = notebook

    async def upsert_research_dossier_note(
        self,
        conn,
        note: ResearchDossierNote,
    ) -> None:
        self._research_dossier_notes[note.note_id] = note

    async def upsert_research_dossier_concept(
        self,
        conn,
        concept: ResearchDossierConcept,
    ) -> None:
        self._research_dossier_concepts[concept.concept_id] = concept

    async def upsert_research_dossier_claim(
        self,
        conn,
        claim: ResearchDossierClaim,
    ) -> None:
        self._research_dossier_claims[claim.claim_id] = claim

    async def upsert_research_dossier_link(
        self,
        conn,
        link: ResearchDossierLink,
    ) -> None:
        self._research_dossier_links[link.link_id] = link

    async def upsert_research_dossier_provider_binding(
        self,
        conn,
        binding: ResearchDossierProviderBinding,
    ) -> None:
        self._research_dossier_provider_bindings[binding.binding_id] = binding

    async def upsert_research_dossier_provider_external_ref(
        self,
        conn,
        external_ref: ResearchDossierProviderExternalRef,
    ) -> None:
        self._research_dossier_provider_external_refs[external_ref.ref_id] = external_ref

    async def upsert_research_dossier_sync_run(
        self,
        conn,
        sync_run: ResearchDossierSyncRun,
    ) -> None:
        self._research_dossier_sync_runs[sync_run.sync_run_id] = sync_run

    async def append_research_dossier_health_check(
        self,
        conn,
        check: ResearchDossierHealthCheck,
    ) -> None:
        self._research_dossier_health_checks[check.check_id] = check

    async def upsert_research_dossier_source(
        self,
        conn,
        source: ResearchDossierSource,
    ) -> None:
        self._research_dossier_sources[source.source_id] = source

    async def append_research_dossier_event(
        self,
        conn,
        event: ResearchDossierEvent,
    ) -> None:
        self._research_dossier_events.setdefault(event.dossier_id, []).append(event)

    async def fetch_methodology_blueprint(self, blueprint_id):
        return self._methodology_blueprints.get(blueprint_id)

    async def list_methodology_blueprints(self, organization_id, *, status=None):
        blueprints = [
            blueprint
            for blueprint in self._methodology_blueprints.values()
            if blueprint.organization_id == organization_id
            and (status is None or blueprint.status == status)
        ]
        return sorted(blueprints, key=lambda item: item.created_at, reverse=True)

    async def fetch_methodology_blueprint_version(self, version_id):
        return self._methodology_blueprint_versions.get(version_id)

    async def list_methodology_blueprint_versions(self, blueprint_id):
        versions = [
            version
            for version in self._methodology_blueprint_versions.values()
            if version.blueprint_id == blueprint_id
        ]
        return sorted(
            versions,
            key=lambda item: (item.version_number, item.created_at),
            reverse=True,
        )

    async def fetch_research_dossier(self, dossier_id):
        return self._research_dossiers.get(dossier_id)

    async def fetch_research_dossier_for_version(self, version_id):
        for dossier in self._research_dossiers.values():
            if dossier.version_id == version_id:
                return dossier
        return None

    async def fetch_research_dossier_source(self, source_id):
        return self._research_dossier_sources.get(source_id)

    async def list_research_dossier_sources(self, dossier_id, *, status=None):
        sources = [
            source
            for source in self._research_dossier_sources.values()
            if source.dossier_id == dossier_id
            and (status is None or source.status == status)
        ]
        return sorted(sources, key=lambda item: item.created_at)

    async def list_research_dossier_events(self, dossier_id):
        return list(self._research_dossier_events.get(dossier_id, []))

    async def fetch_research_dossier_notebook(self, notebook_id):
        return self._research_dossier_notebooks.get(notebook_id)

    async def fetch_research_dossier_notebook_for_dossier(self, dossier_id):
        for notebook in self._research_dossier_notebooks.values():
            if notebook.dossier_id == dossier_id:
                return notebook
        return None

    async def fetch_research_dossier_note(self, note_id):
        return self._research_dossier_notes.get(note_id)

    async def fetch_research_dossier_note_by_slug(self, notebook_id, slug):
        for note in self._research_dossier_notes.values():
            if note.notebook_id == notebook_id and note.slug == slug:
                return note
        return None

    async def list_research_dossier_notes(self, notebook_id, *, note_kind=None, status=None):
        notes = [
            note
            for note in self._research_dossier_notes.values()
            if note.notebook_id == notebook_id
            and (note_kind is None or note.note_kind == note_kind)
            and (status is None or note.status == status)
        ]
        return sorted(notes, key=lambda item: (item.note_kind, item.slug))

    async def fetch_research_dossier_concept(self, concept_id):
        return self._research_dossier_concepts.get(concept_id)

    async def fetch_research_dossier_concept_by_slug(self, notebook_id, slug):
        for concept in self._research_dossier_concepts.values():
            if concept.notebook_id == notebook_id and concept.slug == slug:
                return concept
        return None

    async def list_research_dossier_concepts(self, notebook_id, *, status=None):
        concepts = [
            concept
            for concept in self._research_dossier_concepts.values()
            if concept.notebook_id == notebook_id
            and (status is None or concept.status == status)
        ]
        return sorted(concepts, key=lambda item: item.slug)

    async def fetch_research_dossier_claim(self, claim_id):
        return self._research_dossier_claims.get(claim_id)

    async def fetch_research_dossier_claim_by_key(self, notebook_id, claim_key):
        for claim in self._research_dossier_claims.values():
            if claim.notebook_id == notebook_id and claim.claim_key == claim_key:
                return claim
        return None

    async def list_research_dossier_claims(self, notebook_id, *, status=None):
        claims = [
            claim
            for claim in self._research_dossier_claims.values()
            if claim.notebook_id == notebook_id
            and (status is None or claim.status == status)
        ]
        return sorted(claims, key=lambda item: item.created_at)

    async def fetch_research_dossier_link(self, link_id):
        return self._research_dossier_links.get(link_id)

    async def fetch_research_dossier_link_by_tuple(
        self,
        notebook_id,
        *,
        source_type,
        source_ref_id,
        target_type,
        target_ref_id,
        link_kind,
    ):
        for link in self._research_dossier_links.values():
            if (
                link.notebook_id == notebook_id
                and link.source_type == source_type
                and link.source_ref_id == source_ref_id
                and link.target_type == target_type
                and link.target_ref_id == target_ref_id
                and link.link_kind == link_kind
            ):
                return link
        return None

    async def list_research_dossier_links(self, notebook_id, *, link_kind=None):
        links = [
            link
            for link in self._research_dossier_links.values()
            if link.notebook_id == notebook_id
            and (link_kind is None or link.link_kind == link_kind)
        ]
        return sorted(links, key=lambda item: item.created_at)

    async def list_research_dossier_provider_bindings(
        self,
        notebook_id,
        *,
        provider_key=None,
    ):
        bindings = [
            binding
            for binding in self._research_dossier_provider_bindings.values()
            if binding.notebook_id == notebook_id
            and (provider_key is None or binding.provider_key == provider_key)
        ]
        return sorted(bindings, key=lambda item: item.created_at)

    async def list_research_dossier_provider_external_refs(
        self,
        notebook_id,
        *,
        binding_id=None,
    ):
        refs = [
            ref
            for ref in self._research_dossier_provider_external_refs.values()
            if ref.notebook_id == notebook_id
            and (binding_id is None or ref.binding_id == binding_id)
        ]
        return sorted(refs, key=lambda item: item.created_at)

    async def fetch_latest_research_dossier_health_check(self, notebook_id):
        checks = [
            check
            for check in self._research_dossier_health_checks.values()
            if check.notebook_id == notebook_id
        ]
        return max(checks, key=lambda item: item.created_at) if checks else None

    async def fetch_research_dossier_notebook_detail(self, dossier_id):
        notebook = await self.fetch_research_dossier_notebook_for_dossier(dossier_id)
        if notebook is None:
            return None
        return ResearchDossierNotebookDetail(
            notebook=notebook,
            provider_bindings=await self.list_research_dossier_provider_bindings(
                notebook.notebook_id
            ),
            notes=await self.list_research_dossier_notes(notebook.notebook_id),
            concepts=await self.list_research_dossier_concepts(notebook.notebook_id),
            claims=await self.list_research_dossier_claims(notebook.notebook_id),
            links=await self.list_research_dossier_links(notebook.notebook_id),
            external_refs=await self.list_research_dossier_provider_external_refs(
                notebook.notebook_id
            ),
            latest_health_check=await self.fetch_latest_research_dossier_health_check(
                notebook.notebook_id
            ),
        )

    async def fetch_thread(self, thread_id):
        return self._threads.get(thread_id)

    async def list_memberships(self, thread_id):
        return list(self._memberships.get(thread_id, []))

    async def fetch_active_membership(self, conn, *, thread_id, participant_id):
        for membership in self._memberships.get(thread_id, []):
            if membership.participant_id == participant_id and membership.left_at is None:
                return membership
        return None

    async def upsert_membership(self, conn, membership):
        memberships = [
            existing
            for existing in self._memberships.get(membership.thread_id, [])
            if existing.membership_id != membership.membership_id
        ]
        memberships.append(membership)
        self._memberships[membership.thread_id] = memberships

    async def fetch_interaction_request(self, request_id):
        return self._interaction_requests.get(request_id)

    async def list_interaction_requests_for_thread(self, thread_id):
        return [
            request
            for request in self._interaction_requests.values()
            if request.thread_id == thread_id
        ]

    async def list_open_interaction_requests_for_run(self, requester_run_id):
        return [
            request
            for request in self._interaction_requests.values()
            if request.requester_run_id == requester_run_id and request.status == "open"
        ]

    async def list_interaction_request_questions(self, request_id):
        return sorted(
            self._interaction_questions.get(request_id, []),
            key=lambda item: item.order,
        )

    async def list_interaction_request_targets(self, request_id):
        return list(self._interaction_targets.get(request_id, []))

    async def fetch_interaction_request_target(self, target_id):
        for targets in self._interaction_targets.values():
            for target in targets:
                if target.target_id == target_id:
                    return target
        return None

    async def list_interaction_answers(self, request_id):
        return list(self._interaction_answers.get(request_id, []))

    async def get_interaction_request_detail(self, request_id):
        request = self._interaction_requests.get(request_id)
        if request is None:
            return None
        return InteractionRequestDetail(
            request=request,
            questions=await self.list_interaction_request_questions(request_id),
            targets=await self.list_interaction_request_targets(request_id),
            answers=await self.list_interaction_answers(request_id),
        )

    async def list_interaction_request_details_for_thread(self, thread_id):
        requests = await self.list_interaction_requests_for_thread(thread_id)
        return [
            InteractionRequestDetail(
                request=request,
                questions=await self.list_interaction_request_questions(request.request_id),
                targets=await self.list_interaction_request_targets(request.request_id),
                answers=await self.list_interaction_answers(request.request_id),
            )
            for request in requests
        ]

    async def fetch_participant(self, workspace_id, participant_id):
        return self._participants.get((workspace_id, participant_id))

    async def fetch_agent_participant(self, workspace_id, system_agent_id):
        for participant in self._participants.values():
            if (
                participant.workspace_id == workspace_id
                and participant.participant_type == "agent"
                and participant.system_agent_id == system_agent_id
            ):
                return participant
        return None

    async def fetch_user_participant(self, workspace_id, user_id):
        for participant in self._participants.values():
            if (
                participant.workspace_id == workspace_id
                and participant.participant_type == "user"
                and participant.user_id == user_id
            ):
                return participant
        return None

    async def list_participants(self, workspace_id):
        return [
            participant
            for participant in self._participants.values()
            if participant.workspace_id == workspace_id
        ]

    async def list_memory_entries(self, workspace_id):
        return await self.list_memory_entries_for_scope(
            scope="workspace",
            workspace_id=workspace_id,
            state="confirmed",
        )

    async def list_memory_entries_for_scope(
        self,
        *,
        scope,
        workspace_id=None,
        thread_id=None,
        run_id=None,
        state=None,
    ):
        entries = [
            entry
            for workspace_entries in self._memory_entries.values()
            for entry in workspace_entries
            if entry.scope == scope
            and (workspace_id is None or entry.workspace_id == workspace_id)
            and (thread_id is None or entry.thread_id == thread_id)
            and (run_id is None or entry.run_id == run_id)
            and (state is None or entry.state == state)
        ]
        return sorted(entries, key=lambda item: item.updated_at, reverse=True)

    async def search_memory_entries(
        self,
        *,
        scope,
        workspace_id=None,
        thread_id=None,
        run_id=None,
        query,
        limit,
        state=None,
    ):
        lowered = query.lower()
        entries = await self.list_memory_entries_for_scope(
            scope=scope,
            workspace_id=workspace_id,
            thread_id=thread_id,
            run_id=run_id,
            state=state,
        )
        return [
            entry
            for entry in entries
            if lowered in entry.content.lower()
            or lowered in (entry.summary or "").lower()
            or lowered in entry.entry_type.lower()
        ][:limit]

    async def fetch_memory_entry(self, memory_entry_id):
        for workspace_entries in self._memory_entries.values():
            for entry in workspace_entries:
                if entry.memory_entry_id == memory_entry_id:
                    return entry
        return None

    async def upsert_memory_entry(self, conn, entry: MemoryEntry) -> None:
        workspace_entries = self._memory_entries.setdefault(entry.workspace_id, [])
        for index, existing in enumerate(workspace_entries):
            if existing.memory_entry_id == entry.memory_entry_id:
                workspace_entries[index] = entry
                break
        else:
            workspace_entries.append(entry)

    async def list_system_tools(self, *, scope="global", organization_id=None):
        return [
            tool
            for tool in self._system_tools.values()
            if tool.scope == scope and tool.organization_id == organization_id
        ]

    async def fetch_system_tool(self, tool_id):
        return self._system_tools.get(tool_id)

    async def upsert_system_tool(self, conn, tool: SystemToolDefinition) -> None:
        self._system_tools[tool.tool_id] = tool

    async def list_llm_providers(self, *, scope="global", organization_id=None):
        return [
            provider
            for provider in self._llm_providers.values()
            if provider.scope == scope and provider.organization_id == organization_id
        ]

    async def fetch_llm_provider(self, provider_id):
        return self._llm_providers.get(provider_id)

    async def list_memory_providers(self, *, scope="global", organization_id=None):
        return [
            provider
            for provider in self._memory_providers.values()
            if provider.scope == scope and provider.organization_id == organization_id
        ]

    async def list_enabled_memory_providers(self):
        return [provider for provider in self._memory_providers.values() if provider.enabled]

    async def fetch_memory_provider(self, provider_id):
        return self._memory_providers.get(provider_id)

    async def fetch_memory_provider_by_key(
        self,
        provider_key,
        *,
        scope="global",
        organization_id=None,
    ):
        for provider in self._memory_providers.values():
            if (
                provider.provider_key == provider_key
                and provider.scope == scope
                and provider.organization_id == organization_id
            ):
                return provider
        return None

    async def upsert_memory_provider(self, conn, provider: MemoryProviderDefinition) -> None:
        self._memory_providers[provider.provider_id] = provider

    async def list_mcp_servers(self, *, scope="global", organization_id=None):
        return [
            server
            for server in self._mcp_servers.values()
            if server.scope == scope and server.organization_id == organization_id
        ]

    async def upsert_mcp_server(self, conn, server: McpServerDefinition) -> None:
        self._mcp_servers[server.server_id] = server

    async def replace_mcp_server_capabilities(
        self,
        conn,
        *,
        server_id,
        tools: list[McpToolDefinition],
        resources,
        prompts,
    ):
        self._mcp_server_tools[server_id] = list(tools)

    async def delete_memory_provider(self, conn, *, provider_id):
        return self._memory_providers.pop(provider_id, None) is not None

    async def list_memory_provider_records(self, memory_entry_id):
        return [
            record
            for (entry_id, _provider_id), record in self._memory_provider_records.items()
            if entry_id == memory_entry_id
        ]

    async def fetch_memory_provider_record(self, *, memory_entry_id, provider_id):
        return self._memory_provider_records.get((memory_entry_id, provider_id))

    async def upsert_memory_provider_record(self, conn, record: MemoryProviderRecord) -> None:
        self._memory_provider_records[(record.memory_entry_id, record.provider_id)] = record

    async def list_workspace_tools(self, workspace_id):
        return list(self._workspace_tools.get(workspace_id, []))

    async def list_agent_internal_tools(self, system_agent_id):
        return list(self._agent_internal_tools.get(system_agent_id, []))

    async def fetch_agent_internal_tool_by_name(self, system_agent_id, tool_name):
        for tool in self._agent_internal_tools.get(system_agent_id, []):
            if tool.name == tool_name:
                return tool
        return None

    async def fetch_workspace_tool(self, workspace_id, tool_id):
        for tool in self._workspace_tools.get(workspace_id, []):
            if tool.tool_id == tool_id:
                return tool
        return None

    async def fetch_workspace_tool_by_name(self, workspace_id, tool_name):
        for tool in self._workspace_tools.get(workspace_id, []):
            if tool.name == tool_name:
                return tool
        return None

    async def fetch_workspace_mcp_tool_by_name(self, workspace_id, tool_name):
        for tool in self._workspace_mcp_tools.get(workspace_id, []):
            if tool.exposed_name == tool_name:
                return tool
        return None

    async def fetch_agent_internal_mcp_tool_by_name(self, system_agent_id, tool_name):
        for binding in self._agent_internal_mcp_servers.values():
            if binding.system_agent_id != system_agent_id:
                continue
            for tool in self._mcp_server_tools.get(binding.server_id, []):
                exposed_name = f"{binding.name_prefix}{tool.tool_name}"
                if exposed_name == tool_name:
                    return WorkspaceMcpTool(
                        server_id=binding.server_id,
                        server_key=binding.server_key,
                        server_display_name=binding.display_name,
                        exposed_name=exposed_name,
                        remote_name=tool.tool_name,
                        description=tool.description,
                        input_schema=tool.input_schema,
                        output_schema=tool.output_schema,
                        metadata={
                            **tool.metadata,
                            "workspace_attachment": binding.metadata,
                        },
                    )
        return None

    async def upsert_workspace_tool(self, conn, *, workspace_id, tool):
        tools = [
            existing
            for existing in self._workspace_tools.get(workspace_id, [])
            if existing.tool_id != tool.tool_id
        ]
        tools.append(tool)
        self._workspace_tools[workspace_id] = tools

    async def upsert_agent_internal_tool_binding(self, conn, binding):
        tools = [
            existing
            for existing in self._agent_internal_tools.get(binding.system_agent_id, [])
            if existing.tool_id != binding.tool_id
        ]
        tools.append(binding)
        self._agent_internal_tools[binding.system_agent_id] = tools

    async def fetch_tool_generation_request(self, request_id):
        return self._tool_generation_requests.get(request_id)

    async def list_tool_generation_requests(
        self,
        *,
        organization_id=None,
        workspace_id=None,
        thread_id=None,
        status=None,
    ):
        return [
            request
            for request in self._tool_generation_requests.values()
            if (organization_id is None or request.organization_id == organization_id)
            and (workspace_id is None or request.workspace_id == workspace_id)
            and (thread_id is None or request.thread_id == thread_id)
            and (status is None or request.status == status)
        ]

    async def upsert_tool_generation_request(self, conn, request):
        self._tool_generation_requests[request.request_id] = request

    async def fetch_tool_generation_revision(self, revision_id):
        return self._tool_generation_revisions.get(revision_id)

    async def list_tool_generation_revisions(self, request_id):
        revisions = [
            revision
            for revision in self._tool_generation_revisions.values()
            if revision.request_id == request_id
        ]
        return sorted(revisions, key=lambda item: item.revision_number, reverse=True)

    async def upsert_tool_generation_revision(self, conn, revision):
        self._tool_generation_revisions[revision.revision_id] = revision

    async def next_tool_generation_revision_number(self, conn, request_id):
        revisions = await self.list_tool_generation_revisions(request_id)
        return (revisions[0].revision_number if revisions else 0) + 1

    async def upsert_git_repository(self, conn, repository) -> None:
        self._git_repositories[repository.repo_id] = repository

    async def list_timeline_messages(self, thread_id):
        return [
            message
            for message in self._messages.get(thread_id, [])
            if message.status not in {"pending_moderation", "rejected"}
        ]

    async def fetch_message(self, message_id):
        for messages in self._messages.values():
            for message in messages:
                if message.message_id == message_id:
                    return message
        return None

    async def list_workspace_communication_log(
        self,
        workspace_id,
        *,
        thread_id=None,
        limit=200,
        offset=0,
    ):
        entries: list[WorkspaceCommunicationLogEntry] = []
        for candidate_thread_id, messages in self._messages.items():
            thread = self._threads.get(candidate_thread_id)
            if thread is None or thread.workspace_id != workspace_id:
                continue
            if thread_id is not None and candidate_thread_id != thread_id:
                continue
            for message in messages:
                if message.status in {"pending_moderation", "rejected"}:
                    continue
                actor_display_name = str(message.actor.id)
                participant = self._participants.get((workspace_id, message.actor.id))
                if participant is not None:
                    actor_display_name = participant.display_name
                metadata = dict(message.metadata)
                if metadata.get("interaction_request_id") and "interaction_question_ids" in metadata:
                    kind = "interaction_answer"
                elif metadata.get("interaction_request_id"):
                    kind = "interaction_request"
                else:
                    kind = "message"
                entries.append(
                    WorkspaceCommunicationLogEntry(
                        message_id=message.message_id,
                        workspace_id=message.workspace_id,
                        thread_id=message.thread_id,
                        thread_title=thread.title,
                        actor=message.actor,
                        actor_display_name=actor_display_name,
                        visibility=message.visibility,
                        kind=kind,
                        content=message.content,
                        status=message.status,
                        correlation_id=message.correlation_id,
                        causation_id=message.causation_id,
                        sequence=message.sequence,
                        interaction_request_id=metadata.get("interaction_request_id"),
                        interaction_request_status=metadata.get("interaction_request_status"),
                        interaction_question_ids=metadata.get("interaction_question_ids", []),
                        metadata=metadata,
                        created_at=message.created_at,
                        updated_at=message.updated_at,
                    )
                )
        entries.sort(key=lambda item: (item.created_at, item.sequence, item.message_id), reverse=True)
        return WorkspaceCommunicationLogPage(
            workspace_id=workspace_id,
            entries=entries[offset : offset + limit],
            total_count=len(entries),
        )

    async def upsert_message(self, conn, message):
        messages = [
            existing
            for existing in self._messages.get(message.thread_id, [])
            if existing.message_id != message.message_id
        ]
        messages.append(message)
        self._messages[message.thread_id] = messages

    async def upsert_publication_review(self, conn, review: PublicationReview):
        self._publication_reviews[review.review_id] = review

    async def fetch_publication_review(self, review_id):
        return self._publication_reviews.get(review_id)

    async def fetch_latest_publication_review_for_message(self, message_id):
        reviews = [
            review
            for review in self._publication_reviews.values()
            if review.message_id == message_id
        ]
        reviews.sort(key=lambda item: item.created_at, reverse=True)
        return reviews[0] if reviews else None

    async def persist_workspace_communication_messages(self, messages):
        if self._communication_log_dir is None:
            return
        grouped_lines: dict[Path, list[str]] = {}
        for message in messages:
            if message.status in {"draft", "streaming", "pending_moderation", "rejected"}:
                continue
            thread = self._threads.get(message.thread_id)
            if thread is None:
                continue
            participant = self._participants.get((message.workspace_id, message.actor.id))
            actor_display_name = (
                participant.display_name if participant is not None else str(message.actor.id)
            )
            metadata = dict(message.metadata)
            if metadata.get("interaction_request_id") and "interaction_question_ids" in metadata:
                kind = "interaction_answer"
            elif metadata.get("interaction_request_id"):
                kind = "interaction_request"
            else:
                kind = "message"
            entry = WorkspaceCommunicationLogEntry(
                message_id=message.message_id,
                workspace_id=message.workspace_id,
                thread_id=message.thread_id,
                thread_title=thread.title,
                actor=message.actor,
                actor_display_name=actor_display_name,
                visibility=message.visibility,
                kind=kind,
                content=message.content,
                status=message.status,
                correlation_id=message.correlation_id,
                causation_id=message.causation_id,
                sequence=message.sequence,
                interaction_request_id=metadata.get("interaction_request_id"),
                interaction_request_status=metadata.get("interaction_request_status"),
                interaction_question_ids=metadata.get("interaction_question_ids", []),
                metadata=metadata,
                created_at=message.created_at,
                updated_at=message.updated_at,
            )
            file_path = self._communication_log_dir / f"{message.workspace_id}.jsonl"
            grouped_lines.setdefault(file_path, []).append(
                json.dumps(entry.model_dump(mode="json"), sort_keys=True)
            )
        for file_path, lines in grouped_lines.items():
            append_jsonl_with_rotation(
                file_path,
                lines,
                policy=self._communication_log_policy,
            )

    async def upsert_interaction_request(self, conn, request):
        self._interaction_requests[request.request_id] = request

    async def upsert_interaction_request_question(self, conn, question):
        questions = [
            existing
            for existing in self._interaction_questions.get(question.request_id, [])
            if existing.question_id != question.question_id
        ]
        questions.append(question)
        self._interaction_questions[question.request_id] = questions

    async def upsert_interaction_request_target(self, conn, target):
        targets = [
            existing
            for existing in self._interaction_targets.get(target.request_id, [])
            if existing.target_id != target.target_id
        ]
        targets.append(target)
        self._interaction_targets[target.request_id] = targets

    async def upsert_interaction_answer(self, conn, answer):
        answers = [
            existing
            for existing in self._interaction_answers.get(answer.request_id, [])
            if existing.answer_id != answer.answer_id
        ]
        answers.append(answer)
        self._interaction_answers[answer.request_id] = answers

    async def fetch_tool_call(self, tool_call_id):
        for tool_calls in self._tool_calls.values():
            for tool_call in tool_calls:
                if tool_call.tool_call_id == tool_call_id:
                    return tool_call
        return None

    async def claim_next_tool_call(
        self,
        *,
        worker_id,
        lease_expires_at,
        now,
        max_parallel_calls_per_run,
        max_concurrent_calls_per_tool,
    ):
        claimed_per_run: dict[object, int] = {}
        claimed_per_tool: dict[str, int] = {}
        for tool_calls in self._tool_calls.values():
            for tool_call in tool_calls:
                if tool_call.status != "claimed":
                    continue
                claimed_per_run[tool_call.run_id] = claimed_per_run.get(tool_call.run_id, 0) + 1
                claimed_per_tool[tool_call.tool_name] = (
                    claimed_per_tool.get(tool_call.tool_name, 0) + 1
                )

        candidates = [
            tool_call
            for tool_calls in self._tool_calls.values()
            for tool_call in tool_calls
            if tool_call.status == "created"
            and (tool_call.next_retry_at is None or tool_call.next_retry_at <= now)
        ]
        candidates.sort(
            key=lambda item: (
                item.submitted_at or item.created_at,
                item.tool_call_id,
            )
        )
        for tool_call in candidates:
            if claimed_per_run.get(tool_call.run_id, 0) >= max_parallel_calls_per_run:
                continue
            if claimed_per_tool.get(tool_call.tool_name, 0) >= max_concurrent_calls_per_tool:
                continue
            claimed = tool_call.model_copy(
                update={
                    "status": "claimed",
                    "claimed_by_worker": worker_id,
                    "attempt_count": tool_call.attempt_count + 1,
                    "lease_expires_at": lease_expires_at,
                    "last_heartbeat_at": now,
                    "updated_at": now,
                }
            )
            await self.upsert_tool_call(None, claimed)
            return claimed
        return None

    async def list_completed_tool_calls_for_run(self, run_id):
        return [
            tool_call
            for tool_call in self._tool_calls.get(run_id, [])
            if tool_call.status in {"completed", "failed"}
        ]

    async def list_expired_run_steps(self, *, now):
        return [
            step
            for step in self._run_steps.values()
            if step.status == "claimed"
            and step.lease_expires_at is not None
            and step.lease_expires_at <= now
            and (step.next_retry_at is None or step.next_retry_at <= now)
        ]

    async def list_expired_tool_calls(self, *, now):
        expired = []
        for tool_calls in self._tool_calls.values():
            for tool_call in tool_calls:
                if (
                    tool_call.status == "claimed"
                    and tool_call.lease_expires_at is not None
                    and tool_call.lease_expires_at <= now
                    and (
                        tool_call.next_retry_at is None
                        or tool_call.next_retry_at <= now
                    )
                ):
                    expired.append(tool_call)
        return expired

    async def upsert_workspace(self, conn, workspace: Workspace) -> None:
        self._workspaces[workspace.workspace_id] = workspace

    async def upsert_thread(self, conn, thread: Thread) -> None:
        self._threads[thread.thread_id] = thread

    async def upsert_user(self, conn, user) -> None:
        return None

    async def upsert_participant(self, conn, participant: ParticipantProfile) -> None:
        self._participants[(participant.workspace_id, participant.participant_id)] = participant

    async def upsert_run(self, conn, run: Run) -> None:
        self._runs[run.run_id] = run

    async def upsert_run_step(self, conn, step: RunStep) -> None:
        self._run_steps[step.step_id] = step

    async def upsert_tool_call(self, conn, tool_call: ToolCall) -> None:
        tool_calls = [
            existing
            for existing in self._tool_calls.get(tool_call.run_id, [])
            if existing.tool_call_id != tool_call.tool_call_id
        ]
        tool_calls.append(tool_call)
        self._tool_calls[tool_call.run_id] = tool_calls

    async def next_workspace_sequence(self, conn, workspace_id):
        next_value = self._workspace_sequences.get(workspace_id, 0) + 1
        self._workspace_sequences[workspace_id] = next_value
        return next_value

    async def next_thread_sequence(self, conn, thread_id):
        next_value = self._thread_sequences.get(thread_id, 0) + 1
        self._thread_sequences[thread_id] = next_value
        return next_value

    async def record_event(self, conn, event: EventEnvelope) -> None:
        self.recorded_events.append(event)

    async def upsert_methodic_execution(self, conn, execution: MethodicExecution) -> None:
        self._methodic_executions[execution.execution_id] = execution

    async def fetch_methodic_execution(self, execution_id):
        return self._methodic_executions.get(execution_id)

    async def list_methodic_executions(self, *, workspace_id=None, status=None):
        executions = list(self._methodic_executions.values())
        if workspace_id is not None:
            executions = [
                execution
                for execution in executions
                if execution.workspace_id == workspace_id
            ]
        if status is not None:
            executions = [
                execution
                for execution in executions
                if execution.status == status
            ]
        return sorted(executions, key=lambda item: item.created_at, reverse=True)

    async def upsert_methodic_execution_step(
        self,
        conn,
        step: MethodicExecutionStep,
    ) -> None:
        self._methodic_steps[step.step_execution_id] = step

    async def list_methodic_execution_steps(self, execution_id):
        return sorted(
            [
                step
                for step in self._methodic_steps.values()
                if step.execution_id == execution_id
            ],
            key=lambda item: (item.methodic_index, item.step_index),
        )

    async def upsert_methodic_execution_assignment(
        self,
        conn,
        assignment: MethodicExecutionAssignment,
    ) -> None:
        self._methodic_assignments[assignment.assignment_id] = assignment

    async def list_methodic_execution_assignments(self, execution_id):
        return sorted(
            [
                assignment
                for assignment in self._methodic_assignments.values()
                if assignment.execution_id == execution_id
            ],
            key=lambda item: item.created_at,
        )

    async def upsert_methodic_execution_check(
        self,
        conn,
        check: MethodicExecutionCheck,
    ) -> None:
        self._methodic_checks[check.check_id] = check

    async def list_methodic_execution_checks(self, execution_id):
        return sorted(
            [
                check
                for check in self._methodic_checks.values()
                if check.execution_id == execution_id
            ],
            key=lambda item: item.created_at,
        )

    async def upsert_methodic_resource_request(
        self,
        conn,
        request: MethodicResourceRequest,
    ) -> None:
        self._methodic_resource_requests[request.resource_request_id] = request

    async def fetch_methodic_resource_request(self, resource_request_id):
        return self._methodic_resource_requests.get(resource_request_id)

    async def list_methodic_resource_requests(self, execution_id=None, **kwargs):
        requests = list(self._methodic_resource_requests.values())
        workspace_id = kwargs.get("workspace_id")
        status = kwargs.get("status")
        if execution_id is not None:
            requests = [
                request for request in requests if request.execution_id == execution_id
            ]
        if workspace_id is not None:
            requests = [
                request for request in requests if request.workspace_id == workspace_id
            ]
        if status is not None:
            requests = [request for request in requests if request.status == status]
        return sorted(requests, key=lambda item: item.created_at, reverse=True)

    async def get_methodic_execution_detail(self, execution_id):
        execution = self._methodic_executions.get(execution_id)
        if execution is None:
            return None
        return MethodicExecutionDetail(
            execution=execution,
            steps=await self.list_methodic_execution_steps(execution_id),
            assignments=await self.list_methodic_execution_assignments(execution_id),
            checks=await self.list_methodic_execution_checks(execution_id),
            resource_requests=await self.list_methodic_resource_requests(execution_id),
        )

    async def upsert_llm_provider(self, conn, provider: LlmProviderDefinition) -> None:
        self._llm_providers[provider.provider_id] = provider

    async def delete_llm_provider(self, conn, *, provider_id):
        return self._llm_providers.pop(provider_id, None) is not None

    async def get_runtime_queue_stats(self, *, now, since):
        return self._runtime_queue_stats

    async def get_global_token_total(self, *, day_start, day_end):
        return self._global_token_total

    async def get_workspace_token_total(self, *, workspace_id, day_start, day_end):
        return self._workspace_token_totals.get(workspace_id, 0)

    async def list_workspace_token_totals(self, *, day_start, day_end):
        return [
            {"workspace_id": workspace_id, "total_tokens": total_tokens}
            for workspace_id, total_tokens in self._workspace_token_totals.items()
        ]


def _actor() -> ParticipantInput:
    return ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        display_name="Nikolay",
    )


def _workspace_manager_actor(actor: ParticipantInput) -> ParticipantInput:
    return actor.model_copy(update={"iam_permissions": list(WORKSPACE_PERMISSION_NAMES)})


@pytest.mark.asyncio
async def test_kernel_participant_profile_preserves_distinct_user_id():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    workspace_id = uuid4()
    user_id = uuid4()
    participant_id = uuid4()

    participant = kernel._participant_profile(  # noqa: SLF001
        workspace_id=workspace_id,
        actor=ParticipantInput(
            participant_id=participant_id,
            participant_type="user",
            user_id=user_id,
            display_name="Nikolay",
        ),
        now=datetime.now(timezone.utc),
    )

    assert participant.participant_id == participant_id
    assert participant.user_id == user_id


@pytest.mark.asyncio
async def test_kernel_create_organization_seeds_administration_context_and_curator():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    user_id = uuid4()

    result = await kernel.create_organization(
        CreateOrganizationRequest(
            actor=ParticipantInput(
                participant_id=uuid4(),
                participant_type="user",
                user_id=user_id,
                display_name="Nikolay",
            ),
            slug="acme",
            name="Acme",
        )
    )

    organization = result.organization
    assert organization is not None
    projects = await repository.list_projects(organization.organization_id)
    assert {project.slug for project in projects} == {"default", "administration"}
    administration = next(project for project in projects if project.slug == "administration")
    operations = [
        workspace
        for workspace in repository._workspaces.values()
        if workspace.organization_id == organization.organization_id
        and workspace.project_id == administration.project_id
    ]
    assert len(operations) == 1
    assert operations[0].name == "Organization Operations"
    curator = next(agent for agent in repository._agents.values() if agent.agent_key == "curator")
    assert curator.scope == "organization"
    assert curator.organization_id == organization.organization_id
    assert curator.role == "organization operations curator"
    assert (
        administration.project_id,
        "agent",
        curator.agent_id,
    ) in repository._project_access_bindings
    assert any(role.name == "organization_curator" for role in repository._iam_roles.values())
    assert (
        curator.agent_id,
        UUID("66666666-6666-6666-6666-666666666666"),
    ) in repository._agent_internal_mcp_servers


@pytest.mark.asyncio
async def test_kernel_create_workspace_sets_owner_admin_role_and_default_role_catalog():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    user_id = uuid4()
    participant_id = uuid4()

    result = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Ownership",
            description="Workspace ownership coverage",
            actor=ParticipantInput(
                participant_id=participant_id,
                participant_type="user",
                user_id=user_id,
                display_name="Nikolay",
            ),
        )
    )

    assert result.workspace is not None
    assert result.workspace.owner_user_id == user_id
    assert result.detail is not None
    assert result.detail.participants[0].roles == ["admin"]
    role_names = [role.name for role in result.detail.role_definitions]
    assert role_names == ["admin", "supervisor", "user"]
    assert repository.recorded_events[0].payload["owner_user_id"] == str(user_id)


@pytest.mark.asyncio
async def test_kernel_create_workspace_attaches_anchor_with_descriptive_advertisement():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    result = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Topic Workspace",
            actor=ParticipantInput(
                participant_id=uuid4(),
                participant_type="user",
                user_id=uuid4(),
                display_name="Nikolay",
            ),
        )
    )

    anchor = next(
        participant
        for participant in result.detail.participants
        if participant.system_agent_id == ANCHOR_AGENT_ID
    )
    assert anchor.display_name == "Anchor"
    assert anchor.roles == ["workspace topic alignment reviewer"]
    assert "reviews messages for alignment with the workspace topic" in anchor.capabilities
    assert anchor.metadata["task_routing"]["normal_message_fanout"] is False
    anchor_definition = repository._agents[ANCHOR_AGENT_ID]
    assert anchor_definition.endpoint.engine_id == "local-ollama"
    assert anchor_definition.endpoint.provider == "ollama"
    assert anchor_definition.definition["runtime"]["engine_id"] == "local-ollama"
    assert anchor_definition.interaction_contract.response_contract.format == "json"


@pytest.mark.asyncio
async def test_kernel_creates_project_scoped_workspace_and_filters_by_project():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    actor = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        user_id=uuid4(),
        display_name="Nikolay",
    )
    organization = Organization(
        organization_id=uuid4(),
        slug="platform",
        name="Platform",
        created_by=actor.user_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    repository._organizations[organization.organization_id] = organization

    project_result = await kernel.create_project(
        organization.organization_id,
        CreateProjectRequest(
            actor=actor,
            slug="Gateway Edge",
            name="Gateway Edge",
        ),
        allow_platform_admin=True,
    )
    assert project_result.project is not None

    workspace_result = await kernel.create_workspace(
        CreateWorkspaceRequest(
            organization_id=organization.organization_id,
            project_id=project_result.project.project_id,
            name="Gateway Runtime",
            actor=actor,
        ),
        allow_platform_admin=True,
    )

    assert workspace_result.workspace is not None
    assert workspace_result.workspace.project_id == project_result.project.project_id
    workspace_created = next(
        event
        for event in reversed(repository.recorded_events)
        if event.event_type == "workspace.created"
    )
    assert workspace_created.payload["project_id"] == str(
        project_result.project.project_id
    )

    listed = await kernel.list_workspaces(
        organization_id=organization.organization_id,
        project_id=project_result.project.project_id,
    )
    assert [workspace.workspace_id for workspace in listed] == [
        workspace_result.workspace.workspace_id
    ]


@pytest.mark.asyncio
async def test_kernel_project_access_filters_projects_and_project_workspaces():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    owner = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        user_id=uuid4(),
        display_name="Owner",
    )
    viewer_user_id = uuid4()
    outsider_user_id = uuid4()
    organization = Organization(
        organization_id=uuid4(),
        slug="secure-platform",
        name="Secure Platform",
        created_by=owner.user_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    repository._organizations[organization.organization_id] = organization

    project_result = await kernel.create_project(
        organization.organization_id,
        CreateProjectRequest(
            actor=owner,
            slug="Control Plane",
            name="Control Plane",
        ),
    )
    project = project_result.project
    assert project is not None
    assert project.creator_user_id == owner.user_id
    assert project.owner_user_id == owner.user_id

    workspace_result = await kernel.create_workspace(
        CreateWorkspaceRequest(
            organization_id=organization.organization_id,
            project_id=project.project_id,
            name="Gateway",
            actor=owner,
        ),
    )
    assert workspace_result.workspace is not None

    assert [
        item.project_id
        for item in await kernel.list_projects(
            organization.organization_id,
            user_id=outsider_user_id,
        )
    ] == [project.project_id]
    assert await kernel.list_workspaces(
        user_id=outsider_user_id,
        organization_id=organization.organization_id,
        project_id=project.project_id,
    ) == []

    visible_projects = await kernel.list_projects(
        organization.organization_id,
        user_id=owner.user_id,
    )
    assert [item.project_id for item in visible_projects] == [project.project_id]
    visible_workspaces = await kernel.list_workspaces(
        user_id=owner.user_id,
        organization_id=organization.organization_id,
        project_id=project.project_id,
    )
    assert [item.workspace_id for item in visible_workspaces] == [
        workspace_result.workspace.workspace_id
    ]

    viewer_binding = await kernel.upsert_project_access(
        organization.organization_id,
        project.project_id,
        UpsertProjectAccessRequest(
            actor=owner,
            subject=ProjectSubjectRef(user_id=viewer_user_id),
            role="viewer",
        ),
    )
    assert viewer_binding.role == "viewer"
    assert [
        item.project_id
        for item in await kernel.list_projects(
            organization.organization_id,
            user_id=viewer_user_id,
        )
    ] == [project.project_id]
    assert [
        item.workspace_id
        for item in await kernel.list_workspaces(
            user_id=viewer_user_id,
            organization_id=organization.organization_id,
            project_id=project.project_id,
        )
    ] == [workspace_result.workspace.workspace_id]

    viewer = ParticipantInput(
        participant_id=viewer_user_id,
        participant_type="user",
        user_id=viewer_user_id,
        display_name="Viewer",
    )
    with pytest.raises(PermissionError):
        await kernel.create_workspace(
            CreateWorkspaceRequest(
                organization_id=organization.organization_id,
                project_id=project.project_id,
                name="Viewer Cannot Create",
                actor=viewer,
            ),
        )

    transferred_owner = await kernel.upsert_project_access(
        organization.organization_id,
        project.project_id,
        UpsertProjectAccessRequest(
            actor=owner,
            subject=ProjectSubjectRef(user_id=viewer_user_id),
            role="owner",
        ),
    )
    assert transferred_owner.role == "owner"
    bindings = await kernel.list_project_access(
        organization.organization_id,
        project.project_id,
        actor=viewer,
    )
    roles_by_user = {binding.user_id: binding.role for binding in bindings}
    assert roles_by_user[viewer_user_id] == "owner"
    assert roles_by_user[owner.user_id] == "creator"
    extra_viewer_id = uuid4()
    extra_viewer = await kernel.upsert_project_access(
        organization.organization_id,
        project.project_id,
        UpsertProjectAccessRequest(
            actor=owner,
            subject=ProjectSubjectRef(user_id=extra_viewer_id),
            role="viewer",
        ),
    )
    assert extra_viewer.role == "viewer"
    with pytest.raises(ValueError):
        await kernel.remove_project_access(
            organization.organization_id,
            project.project_id,
            RemoveProjectAccessRequest(
                actor=owner,
                subject=ProjectSubjectRef(user_id=viewer_user_id),
            ),
        )


@pytest.mark.asyncio
async def test_kernel_project_creator_owner_editor_viewer_permissions_compose():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    creator = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        user_id=uuid4(),
        display_name="Creator",
    )
    owner_user_id = uuid4()
    second_owner_user_id = uuid4()
    editor_user_id = uuid4()
    viewer_user_id = uuid4()
    owner = ParticipantInput(
        participant_id=owner_user_id,
        participant_type="user",
        user_id=owner_user_id,
        display_name="Owner",
    )
    viewer = ParticipantInput(
        participant_id=viewer_user_id,
        participant_type="user",
        user_id=viewer_user_id,
        display_name="Viewer",
    )
    second_owner = ParticipantInput(
        participant_id=second_owner_user_id,
        participant_type="user",
        user_id=second_owner_user_id,
        display_name="Second Owner",
    )
    editor = ParticipantInput(
        participant_id=editor_user_id,
        participant_type="user",
        user_id=editor_user_id,
        display_name="Editor",
    )
    organization = Organization(
        organization_id=uuid4(),
        slug="role-permissions",
        name="Role Permissions",
        created_by=creator.user_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    repository._organizations[organization.organization_id] = organization

    project_result = await kernel.create_project(
        organization.organization_id,
        CreateProjectRequest(
            actor=creator,
            slug="Role Project",
            name="Role Project",
            owner=ProjectSubjectRef(user_id=owner_user_id),
            owners=[ProjectSubjectRef(user_id=second_owner_user_id)],
            editors=[ProjectSubjectRef(user_id=editor_user_id)],
            viewers=[ProjectSubjectRef(user_id=viewer_user_id)],
        ),
    )
    project = project_result.project
    assert project is not None
    bindings = await kernel.list_project_access(
        organization.organization_id,
        project.project_id,
        actor=viewer,
    )
    roles_by_user = {binding.user_id: binding.role for binding in bindings}
    assert roles_by_user[creator.user_id] == "creator"
    assert roles_by_user[owner_user_id] == "owner"
    assert roles_by_user[second_owner_user_id] == "owner"
    assert roles_by_user[editor_user_id] == "editor"
    assert roles_by_user[viewer_user_id] == "viewer"

    updated = await kernel.update_project(
        organization.organization_id,
        project.project_id,
        UpdateProjectRequest(actor=creator, name="Creator Can Edit"),
    )
    assert updated.project is not None
    assert updated.project.name == "Creator Can Edit"

    with pytest.raises(PermissionError):
        await kernel.update_project(
            organization.organization_id,
            project.project_id,
            UpdateProjectRequest(actor=viewer, name="Viewer Cannot Edit"),
        )

    await kernel.upsert_project_access(
        organization.organization_id,
        project.project_id,
        UpsertProjectAccessRequest(
            actor=owner,
            subject=ProjectSubjectRef(user_id=uuid4()),
            role="viewer",
        ),
    )
    creator_binding = await kernel.upsert_project_access(
        organization.organization_id,
        project.project_id,
        UpsertProjectAccessRequest(
            actor=creator,
            subject=ProjectSubjectRef(user_id=uuid4()),
            role="viewer",
        ),
    )
    assert creator_binding.role == "viewer"
    with pytest.raises(ValueError):
        await kernel.upsert_project_access(
            organization.organization_id,
            project.project_id,
            UpsertProjectAccessRequest(
                actor=creator,
                subject=ProjectSubjectRef(user_id=uuid4()),
                role="creator",
            ),
        )
    second_owner_binding = await kernel.upsert_project_access(
        organization.organization_id,
        project.project_id,
        UpsertProjectAccessRequest(
            actor=second_owner,
            subject=ProjectSubjectRef(user_id=uuid4()),
            role="viewer",
        ),
    )
    assert second_owner_binding.role == "viewer"
    editor_workspace = await kernel.create_workspace(
        CreateWorkspaceRequest(
            organization_id=organization.organization_id,
            project_id=project.project_id,
            name="Editor Workspace",
            actor=editor,
        ),
    )
    assert editor_workspace.workspace is not None
    with pytest.raises(PermissionError):
        await kernel.upsert_project_access(
            organization.organization_id,
            project.project_id,
            UpsertProjectAccessRequest(
                actor=editor,
                subject=ProjectSubjectRef(user_id=uuid4()),
                role="viewer",
            ),
        )


@pytest.mark.asyncio
async def test_kernel_project_creator_and_owner_can_be_agent_subjects():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    agent_actor = ParticipantInput(
        participant_id=uuid4(),
        participant_type="agent",
        display_name="Planner Agent",
    )
    organization = Organization(
        organization_id=uuid4(),
        slug="agent-projects",
        name="Agent Projects",
        created_by=agent_actor.participant_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    repository._organizations[organization.organization_id] = organization

    project_result = await kernel.create_project(
        organization.organization_id,
        CreateProjectRequest(
            actor=agent_actor,
            slug="Agent Owned",
            name="Agent Owned",
        ),
    )
    project = project_result.project
    assert project is not None
    assert project.creator_system_agent_id == agent_actor.participant_id
    assert project.owner_system_agent_id == agent_actor.participant_id
    assert [
        item.project_id
        for item in await kernel.list_projects(
            organization.organization_id,
            system_agent_id=agent_actor.participant_id,
        )
    ] == [project.project_id]


@pytest.mark.asyncio
async def test_kernel_resolve_authenticated_user_actor_reuses_workspace_participant():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    workspace_id = uuid4()
    user_id = uuid4()
    participant_id = uuid4()
    repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=user_id,
        display_name="Nikolay",
    )

    actor = await kernel.resolve_authenticated_user_actor(
        workspace_id,
        user_id=user_id,
        display_name="Nikolay",
    )

    assert actor.user_id == user_id
    assert actor.participant_id == participant_id


@pytest.mark.asyncio
async def test_kernel_list_workspaces_filters_by_project_access():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    first_user_id = uuid4()
    second_user_id = uuid4()
    organization_id = UUID("11111111-1111-1111-1111-111111111111")
    first_actor = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        user_id=first_user_id,
        display_name="First",
    )
    second_actor = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        user_id=second_user_id,
        display_name="Second",
    )
    first_project = await kernel.create_project(
        organization_id,
        CreateProjectRequest(actor=first_actor, slug="First", name="First"),
    )
    second_project = await kernel.create_project(
        organization_id,
        CreateProjectRequest(actor=second_actor, slug="Second", name="Second"),
    )
    assert first_project.project is not None
    assert second_project.project is not None

    first = await kernel.create_workspace(
        CreateWorkspaceRequest(
            organization_id=organization_id,
            project_id=first_project.project.project_id,
            name="Visible",
            actor=first_actor,
        )
    )
    second = await kernel.create_workspace(
        CreateWorkspaceRequest(
            organization_id=organization_id,
            project_id=second_project.project.project_id,
            name="Hidden",
            actor=second_actor,
        )
    )

    visible = await kernel.list_workspaces(user_id=first_user_id)

    assert [workspace.workspace_id for workspace in visible] == [first.workspace.workspace_id]
    assert second.workspace is not None
    assert second.workspace.workspace_id not in {workspace.workspace_id for workspace in visible}


@pytest.mark.asyncio
async def test_kernel_can_create_list_update_and_delete_llm_provider():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    actor = _actor()

    created = await kernel.create_llm_provider(
        CreateLlmProviderRequest(
            actor=actor,
            engine_id="anthropic-sonnet",
            display_name="Anthropic Sonnet",
            description="Reasoning-focused cloud provider.",
            provider="anthropic",
            endpoint_kind="remote",
            url="https://api.anthropic.example/v1/messages",
            default_model="claude-sonnet-4-5",
            capabilities=["chat", "reasoning"],
            locality="cloud",
            priority=180,
            enabled=True,
            secret_config={"env": {"name": "ANTHROPIC_API_KEY"}},
            metadata={"protocol": "anthropic-messages"},
        )
    )

    assert created.provider is not None
    provider_id = created.provider.provider_id

    listed = await kernel.list_llm_providers()
    assert [item.engine_id for item in listed] == ["anthropic-sonnet"]

    updated = await kernel.update_llm_provider(
        provider_id,
        UpdateLlmProviderRequest(
            actor=actor,
            display_name="Anthropic Sonnet Updated",
            priority=240,
            enabled=False,
            capabilities=[],
            metadata={"owner": "platform"},
        ),
    )

    assert updated.provider is not None
    assert updated.provider.display_name == "Anthropic Sonnet Updated"
    assert updated.provider.priority == 240
    assert updated.provider.enabled is False
    assert updated.provider.capabilities == []
    assert updated.provider.metadata == {
        "protocol": "anthropic-messages",
        "owner": "platform",
    }

    deleted = await kernel.delete_llm_provider(
        provider_id,
        DeleteLlmProviderRequest(actor=actor),
    )

    assert deleted == {"deleted": True, "provider_id": str(provider_id)}
    assert await kernel.list_llm_providers() == []


@pytest.mark.asyncio
async def test_kernel_rejects_embedding_capability_on_llm_provider():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    with pytest.raises(ValueError, match="embedding capabilities"):
        await kernel.create_llm_provider(
            CreateLlmProviderRequest(
                actor=_actor(),
                engine_id="mixed-provider",
                display_name="Mixed Provider",
                description="Invalid mixed generation and embedding provider.",
                provider="ollama",
                endpoint_kind="local",
                url="http://127.0.0.1:11434/api/generate",
                default_model=TEST_EXPLICIT_OLLAMA_MODEL,
                capabilities=["chat", "embedding"],
                locality="host",
                priority=100,
                enabled=True,
            )
        )


@pytest.mark.asyncio
async def test_kernel_prevents_disabling_or_deleting_referenced_llm_provider():
    now = datetime.now(timezone.utc)
    repository = FakeRepository(
        agents=[
            AgentDefinition(
                agent_id=uuid4(),
                display_name="Planner Agent",
                description="Plans work using a managed engine.",
                role="planner",
                capabilities=["planning"],
                endpoint=AgentEndpoint(kind="remote", engine_id="openai-responses"),
                system_prompt="Plan carefully.",
                created_by=uuid4(),
                created_at=now,
                updated_at=now,
            )
        ]
    )
    kernel = CollaborationKernel(repository)
    actor = _actor()
    created = await kernel.create_llm_provider(
        CreateLlmProviderRequest(
            actor=actor,
            engine_id="openai-responses",
            display_name="OpenAI Responses",
            description="Cloud responses endpoint.",
            provider="openai",
            endpoint_kind="remote",
            url="https://api.openai.com/v1/responses",
            default_model="gpt-5.4-mini",
        )
    )
    provider_id = created.provider.provider_id

    with pytest.raises(ValueError, match="Cannot disable LLM provider"):
        await kernel.update_llm_provider(
            provider_id,
            UpdateLlmProviderRequest(
                actor=actor,
                enabled=False,
            ),
        )

    with pytest.raises(ValueError, match="Cannot rename LLM provider engine_id"):
        await kernel.update_llm_provider(
            provider_id,
            UpdateLlmProviderRequest(
                actor=actor,
                engine_id="openai-responses-v2",
            ),
        )

    with pytest.raises(ValueError, match="Cannot delete LLM provider"):
        await kernel.delete_llm_provider(
            provider_id,
            DeleteLlmProviderRequest(actor=actor),
        )


@pytest.mark.asyncio
async def test_kernel_detects_runtime_preferred_engine_id_references_for_llm_provider():
    now = datetime.now(timezone.utc)
    repository = FakeRepository(
        agents=[
            AgentDefinition(
                agent_id=uuid4(),
                display_name="Research Agent",
                description="Uses preferred engine ids for selection.",
                role="researcher",
                capabilities=["research"],
                endpoint=AgentEndpoint(kind="remote"),
                system_prompt="Research carefully.",
                definition={"runtime": {"preferred_engine_ids": ["anthropic-sonnet"]}},
                created_by=uuid4(),
                created_at=now,
                updated_at=now,
            )
        ]
    )
    kernel = CollaborationKernel(repository)
    actor = _actor()
    created = await kernel.create_llm_provider(
        CreateLlmProviderRequest(
            actor=actor,
            engine_id="anthropic-sonnet",
            display_name="Anthropic Sonnet",
            description="Reasoning cloud provider.",
            provider="anthropic",
            endpoint_kind="remote",
            url="https://api.anthropic.example/v1/messages",
            default_model="claude-sonnet-4-5",
        )
    )

    with pytest.raises(ValueError, match="Research Agent"):
        await kernel.delete_llm_provider(
            created.provider.provider_id,
            DeleteLlmProviderRequest(actor=actor),
        )


def test_participant_from_row_falls_back_when_user_display_name_is_missing():
    participant_id = uuid4()
    workspace_id = uuid4()
    row = {
        "participant_id": participant_id,
        "workspace_id": workspace_id,
        "participant_type": "user",
        "user_id": uuid4(),
        "system_agent_id": None,
        "description": None,
        "roles": [],
        "capabilities": [],
        "status": "active",
        "visibility_scope": "workspace",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "metadata": {},
        "user_display_name": None,
        "agent_display_name": None,
        "agent_description": None,
        "agent_role": None,
        "agent_capabilities": [],
        "agent_endpoint": None,
        "agent_system_prompt": None,
        "agent_definition": None,
    }

    participant = CollaborationRepository._participant_from_row(row)  # noqa: SLF001

    assert participant.display_name == str(participant_id)


def test_workspace_communication_log_entry_from_row_classifies_interaction_answer():
    request_id = uuid4()
    question_id = uuid4()
    row = {
        "message_id": uuid4(),
        "workspace_id": uuid4(),
        "thread_id": uuid4(),
        "thread_title": "Coordination",
        "actor_type": "user",
        "actor_id": uuid4(),
        "actor_display_name": "Alice",
        "visibility": "workspace",
        "content": "Backend is blocked on API review.",
        "status": "completed",
        "correlation_id": uuid4(),
        "causation_id": request_id,
        "sequence": 7,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "metadata": {
            "interaction_request_id": str(request_id),
            "interaction_question_ids": [str(question_id)],
        },
    }

    entry = CollaborationRepository._workspace_communication_log_entry_from_row(row)  # noqa: SLF001

    assert entry.kind == "interaction_answer"
    assert entry.actor_display_name == "Alice"
    assert entry.interaction_request_id == request_id
    assert entry.interaction_question_ids == [question_id]


def test_build_default_interaction_contract_reflects_testing_role():
    contract = build_default_interaction_contract(
        display_name="Testing Agent",
        role="testing agent",
        description="Validates changes and reports regressions.",
        capabilities=["tests", "validation"],
    )

    assert contract.response_contract.title == "Testing Agent Response"
    assert contract.response_contract.required_sections == [
        "Summary",
        "Checks performed",
        "Findings",
        "Residual risk",
        "Next action",
    ]
    assert contract.instructions
    assert not interaction_contract_is_empty(contract)


def test_build_default_interaction_contract_reflects_implementation_role():
    contract = build_default_interaction_contract(
        display_name="Builder Agent",
        role="implementation agent",
        description="Implements collaboration kernel changes safely.",
        capabilities=["coding", "backend", "validation"],
    )

    assert contract.response_contract.title == "Implementation Agent Response"
    assert contract.response_contract.required_sections == [
        "Summary",
        "Proposed change",
        "Validation",
        "Residual risk",
        "Next action",
    ]
    assert "Call out residual implementation risk honestly." in contract.response_contract.guidance


@pytest.mark.asyncio
async def test_kernel_create_system_agent_fills_missing_interaction_contract():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    result = await kernel.create_system_agent(
        CreateSystemAgentRequest(
            actor=_actor(),
            display_name="Testing Agent",
            description="Validates changes and reports regressions.",
            role="testing agent",
            capabilities=["tests", "validation"],
            endpoint=AgentEndpoint(kind="local", model=TEST_EXPLICIT_OLLAMA_MODEL),
            system_prompt="You are a careful testing agent.",
        )
    )

    assert result.agent is not None
    assert not interaction_contract_is_empty(result.agent.interaction_contract)
    assert result.agent.interaction_contract.response_contract.required_sections


@pytest.mark.asyncio
async def test_kernel_create_and_update_system_agent_round_trips_harness():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    initial_harness = AgentHarness(
        summary="Plan carefully and choose tools dynamically.",
        operating_principles=["Stay incremental."],
        tool_use_policy=AgentToolUsePolicy(
            selection_principles=["Prefer the narrowest tool that provides ground truth."],
            fallback_when_no_tool_fits="Explain the gap and ask for help.",
        ),
        compaction_policy=AgentCompactionPolicy(
            strategy="rolling_summary",
            max_estimated_input_tokens=8_000,
            recent_message_count=10,
        ),
    )

    created = await kernel.create_system_agent(
        CreateSystemAgentRequest(
            actor=_actor(),
            display_name="Harnessed Agent",
            description="Agent with explicit harness state.",
            role="research agent",
            capabilities=["research"],
            endpoint=AgentEndpoint(kind="local", model=TEST_EXPLICIT_OLLAMA_MODEL),
            system_prompt="Research carefully.",
            harness=initial_harness,
        )
    )

    updated_harness = AgentHarness(
        summary="Validate before declaring completion.",
        operating_principles=["Show evidence for claims."],
        tool_use_policy=AgentToolUsePolicy(
            selection_principles=["Use workspace tools opportunistically."],
            read_before_write=False,
        ),
        compaction_policy=AgentCompactionPolicy(
            strategy="summary_plus_retrieval",
            retrieval_provider_key="semantic-thread",
            retrieval_limit=3,
        ),
    )
    updated = await kernel.update_system_agent(
        created.agent.agent_id,
        UpdateSystemAgentRequest(
            actor=_actor(),
            description="Updated agent harness.",
            harness=updated_harness,
        ),
    )
    assert created.agent.harness == initial_harness
    assert updated.agent.harness == updated_harness
    assert repository.upserted_agents[-1].harness == updated_harness


@pytest.mark.asyncio
async def test_kernel_update_system_agent_preserves_existing_harness_when_omitted():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    initial_harness = AgentHarness(
        summary="Preserve harness when not explicitly changed.",
        tool_use_policy=AgentToolUsePolicy(
            selection_principles=["Prefer direct evidence from workspace tools."],
        ),
    )

    created = await kernel.create_system_agent(
        CreateSystemAgentRequest(
            actor=_actor(),
            display_name="Stable Harness Agent",
            description="Agent with stable harness state.",
            role="research agent",
            capabilities=["research"],
            endpoint=AgentEndpoint(kind="local", model=TEST_EXPLICIT_OLLAMA_MODEL),
            system_prompt="Research carefully.",
            harness=initial_harness,
        )
    )

    updated = await kernel.update_system_agent(
        created.agent.agent_id,
        UpdateSystemAgentRequest(
            actor=_actor(),
            description="Updated description only.",
        ),
    )

    assert updated.agent.description == "Updated description only."
    assert updated.agent.harness == initial_harness
    assert repository.upserted_agents[-1].harness == initial_harness


@pytest.mark.asyncio
async def test_kernel_update_system_agent_clears_harness_when_explicit_null():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    created = await kernel.create_system_agent(
        CreateSystemAgentRequest(
            actor=_actor(),
            display_name="Clearable Harness Agent",
            description="Agent with removable harness state.",
            role="research agent",
            capabilities=["research"],
            endpoint=AgentEndpoint(kind="local", model=TEST_EXPLICIT_OLLAMA_MODEL),
            system_prompt="Research carefully.",
            harness=AgentHarness(
                summary="This harness should be removed.",
                tool_use_policy=AgentToolUsePolicy(
                    selection_principles=["Start from visible workspace tools."],
                ),
            ),
        )
    )

    updated = await kernel.update_system_agent(
        created.agent.agent_id,
        UpdateSystemAgentRequest(
            actor=_actor(),
            harness=None,
        ),
    )

    assert updated.agent.harness is None
    assert repository.upserted_agents[-1].harness is None


def _compiled_git_agent(
    *,
    agent_key: str = "admin",
    display_name: str = "Admin Agent",
    scope: str = "global",
    organization_id=None,
    prompt: str = "Manage agent definitions safely.",
) -> AgentDefinition:
    return AgentDefinition(
        agent_id=uuid4(),
        agent_key=agent_key,
        scope=scope,
        organization_id=organization_id,
        display_name=display_name,
        description="Git-managed agent definition.",
        role="agent_admin",
        capabilities=["agent_catalog", "git_catalog"],
        endpoint=AgentEndpoint(kind="remote", model="gpt-5.4"),
        system_prompt=prompt,
        harness=AgentHarness(summary=f"{display_name} harness."),
        interaction_contract=build_default_interaction_contract(
            display_name=display_name,
            role="agent_admin",
            description="Git-managed agent definition.",
            capabilities=["agent_catalog", "git_catalog"],
        ),
        definition={"source": "git", "agent_key": agent_key},
        created_by=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        metadata={"source": "git"},
    )


@pytest.mark.asyncio
async def test_kernel_publish_git_managed_agent_creates_versions_and_is_idempotent():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    publisher_id = uuid4()
    repo_id = uuid4()

    first_agent, first_version = await kernel.publish_git_managed_agent_definition(
        compiled_agent=_compiled_git_agent(prompt="Version one."),
        git_repository_id=repo_id,
        git_commit_sha="commit-one",
        bundle_path="agents/admin",
        manifest_sha256="manifest-one",
        published_by=publisher_id,
        metadata={"channel": "test"},
    )
    repeated_agent, repeated_version = await kernel.publish_git_managed_agent_definition(
        compiled_agent=_compiled_git_agent(prompt="Version one."),
        git_repository_id=repo_id,
        git_commit_sha="commit-one",
        bundle_path="agents/admin",
        manifest_sha256="manifest-one",
        published_by=publisher_id,
        metadata={"channel": "test"},
    )
    second_agent, second_version = await kernel.publish_git_managed_agent_definition(
        compiled_agent=_compiled_git_agent(prompt="Version two."),
        git_repository_id=repo_id,
        git_commit_sha="commit-two",
        bundle_path="agents/admin",
        manifest_sha256="manifest-two",
        published_by=publisher_id,
        metadata={"channel": "test"},
    )

    assert first_agent.agent_id == repeated_agent.agent_id == second_agent.agent_id
    assert first_version.agent_version_id == repeated_version.agent_version_id
    assert first_version.version == 1
    assert second_version.version == 2
    assert second_agent.active_agent_version_id == second_version.agent_version_id
    assert len(repository._agent_versions) == 2
    assert repository._agents[first_agent.agent_id].system_prompt == "Version two."


@pytest.mark.asyncio
async def test_kernel_activate_agent_definition_version_rolls_back_projection():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    publisher_id = uuid4()
    repo_id = uuid4()

    first_agent, first_version = await kernel.publish_git_managed_agent_definition(
        compiled_agent=_compiled_git_agent(prompt="Stable prompt."),
        git_repository_id=repo_id,
        git_commit_sha="commit-stable",
        bundle_path="agents/admin",
        manifest_sha256="manifest-stable",
        published_by=publisher_id,
    )
    await kernel.publish_git_managed_agent_definition(
        compiled_agent=_compiled_git_agent(prompt="Broken prompt."),
        git_repository_id=repo_id,
        git_commit_sha="commit-broken",
        bundle_path="agents/admin",
        manifest_sha256="manifest-broken",
        published_by=publisher_id,
    )

    activated_agent, activated_version = await kernel.activate_agent_definition_version(
        agent_id=first_agent.agent_id,
        agent_version_id=first_version.agent_version_id,
        actor_id=publisher_id,
        metadata={"reason": "rollback"},
    )

    assert activated_version.agent_version_id == first_version.agent_version_id
    assert activated_agent.system_prompt == "Stable prompt."
    assert activated_agent.active_agent_version_id == first_version.agent_version_id
    assert activated_agent.metadata["activated_from_version"] == 1
    assert repository._agents[first_agent.agent_id].system_prompt == "Stable prompt."


@pytest.mark.asyncio
async def test_kernel_git_agent_keys_are_isolated_by_scope_and_manual_agents_still_work():
    manual_agent = AgentDefinition(
        agent_id=uuid4(),
        display_name="Manual Agent",
        description="Manual database-backed agent.",
        role="assistant",
        capabilities=["chat"],
        endpoint=AgentEndpoint(kind="local", model=TEST_EXPLICIT_OLLAMA_MODEL),
        system_prompt="Manual prompt.",
        created_by=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repository = FakeRepository([manual_agent])
    kernel = CollaborationKernel(repository)
    organization_id = uuid4()
    repo_id = uuid4()
    publisher_id = uuid4()

    global_agent, _ = await kernel.publish_git_managed_agent_definition(
        compiled_agent=_compiled_git_agent(agent_key="admin", scope="global", organization_id=None),
        git_repository_id=repo_id,
        git_commit_sha="global-commit",
        bundle_path="agents/admin",
        manifest_sha256="global-manifest",
        published_by=publisher_id,
    )
    org_agent, _ = await kernel.publish_git_managed_agent_definition(
        compiled_agent=_compiled_git_agent(
            agent_key="admin",
            display_name="Org Admin Agent",
            scope="organization",
            organization_id=organization_id,
        ),
        git_repository_id=repo_id,
        git_commit_sha="org-commit",
        bundle_path="agents/admin",
        manifest_sha256="org-manifest",
        published_by=publisher_id,
    )

    assert manual_agent.agent_key is None
    assert repository._agents[manual_agent.agent_id].metadata == {}
    assert global_agent.agent_id != org_agent.agent_id
    assert global_agent.scope == "global"
    assert org_agent.scope == "organization"
    assert org_agent.organization_id == organization_id


@pytest.mark.asyncio
async def test_kernel_search_thread_memory_filters_agents_only_hits_for_user_viewer():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    actor = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        user_id=uuid4(),
        display_name="Nikolay",
    )
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Engineering",
        description="Shared workspace",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Release prep",
        created_at=now,
        updated_at=now,
    )
    repository._memory_entries[workspace_id] = [
        MemoryEntry(
            memory_entry_id=uuid4(),
            scope="thread",
            state="confirmed",
            workspace_id=workspace_id,
            thread_id=thread_id,
            entry_type="decision",
            summary="Workspace-visible decision",
            content="Migration plan is tracked in staging.",
            created_by=actor.participant_id,
            updated_by=actor.participant_id,
            visibility="workspace",
            created_at=now,
            updated_at=now,
        ),
        MemoryEntry(
            memory_entry_id=uuid4(),
            scope="thread",
            state="confirmed",
            workspace_id=workspace_id,
            thread_id=thread_id,
            entry_type="decision",
            summary="Agents-only note",
            content="Migration rollback command lives in a private scratchpad.",
            created_by=actor.participant_id,
            updated_by=actor.participant_id,
            visibility="agents_only",
            created_at=now,
            updated_at=now + timedelta(seconds=1),
        ),
    ]

    response = await kernel.search_thread_memory(
        thread_id,
        SearchMemoryRequest(
            actor=actor,
            query="migration",
            limit=10,
            include_graph=False,
        ),
    )

    assert response.provider == "postgres"
    assert len(response.results) == 1
    assert response.results[0].entry.summary == "Workspace-visible decision"


@pytest.mark.asyncio
async def test_kernel_upsert_run_scratch_reuses_existing_compaction_entry():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    run_id = uuid4()
    actor = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        user_id=uuid4(),
        display_name="Nikolay",
    )
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Engineering",
        description="Shared workspace",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Release prep",
        created_at=now,
        updated_at=now,
    )
    repository._runs[run_id] = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        task_id=uuid4(),
        participant_id=actor.participant_id,
        status="started",
        created_at=now,
        updated_at=now,
    )

    first = await kernel.upsert_run_scratch(
        run_id=run_id,
        actor_input=actor,
        entry_type="context_compaction_summary",
        content="First compacted summary",
        summary="Compacted context",
        metadata={"covered_sequence_end": 3},
        visibility="agents_only",
        source="agent_runtime_compaction",
    )
    second = await kernel.upsert_run_scratch(
        run_id=run_id,
        actor_input=actor,
        entry_type="context_compaction_summary",
        content="Updated compacted summary",
        summary="Compacted context",
        metadata={"covered_sequence_end": 4},
        visibility="agents_only",
        source="agent_runtime_compaction",
        memory_entry_id=first.memory_entry_id,
    )

    stored = await repository.fetch_memory_entry(first.memory_entry_id)
    run_entries = await repository.list_memory_entries_for_scope(
        scope="run",
        workspace_id=workspace_id,
        thread_id=thread_id,
        run_id=run_id,
        state="scratch",
    )

    assert second.memory_entry_id == first.memory_entry_id
    assert second.version == 2
    assert stored is not None
    assert stored.content == "Updated compacted summary"
    assert len(
        [entry for entry in run_entries if entry.entry_type == "context_compaction_summary"]
    ) == 1


@pytest.mark.asyncio
async def test_kernel_update_workspace_preserves_existing_harness_when_omitted():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    actor = _actor()
    manager_actor = _workspace_manager_actor(actor)
    initial_harness = WorkspaceHarness(
        summary="Preserve workspace harness unless explicitly replaced.",
        methodology=WorkspaceMethodology(
            ontology="Artifacts are first-class evidence.",
        ),
    )

    created = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Stable Harness Workspace",
            description="Workspace with stable harness state.",
            actor=actor,
            harness=initial_harness,
        )
    )

    updated = await kernel.update_workspace(
        created.workspace.workspace_id,
        UpdateWorkspaceRequest(
            actor=manager_actor,
            description="Updated description only.",
        ),
    )

    assert updated.workspace.description == "Updated description only."
    assert updated.workspace.harness == initial_harness
    assert repository._workspaces[created.workspace.workspace_id].harness == initial_harness


@pytest.mark.asyncio
async def test_kernel_update_workspace_clears_harness_when_explicit_null():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    actor = _actor()
    manager_actor = _workspace_manager_actor(actor)

    created = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Clearable Harness Workspace",
            description="Workspace with removable harness state.",
            actor=actor,
            harness=WorkspaceHarness(
                summary="This harness should be removed.",
                methodology=WorkspaceMethodology(
                    ontology="Evidence begins with visible artifacts.",
                ),
            ),
        )
    )

    updated = await kernel.update_workspace(
        created.workspace.workspace_id,
        UpdateWorkspaceRequest(
            actor=manager_actor,
            harness=None,
        ),
    )

    assert updated.workspace.harness is None
    assert repository._workspaces[created.workspace.workspace_id].harness is None


@pytest.mark.asyncio
async def test_kernel_create_system_tool_rejects_read_write_workspace_access_for_untrusted_tool():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    with pytest.raises(ValueError, match="read_write workspace access requires trust_level='trusted'"):
        await kernel.create_system_tool(
            CreateSystemToolRequest(
                actor=_actor(),
                name="repo_write",
                description="Writes into a mounted workspace.",
                execution=ToolExecutionBinding(
                    backend_kind="docker",
                    handler_ref="repo_write",
                    execution_profile={"workspace_access": "read_write"},
                    trust_level="sandboxed",
                ),
            )
        )


@pytest.mark.asyncio
async def test_kernel_create_system_tool_rejects_full_network_for_untrusted_tool():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    with pytest.raises(ValueError, match="network=full requires trust_level='trusted'"):
        await kernel.create_system_tool(
            CreateSystemToolRequest(
                actor=_actor(),
                name="repo_sync",
                description="Downloads remote content.",
                execution=ToolExecutionBinding(
                    backend_kind="docker",
                    handler_ref="repo_sync",
                    execution_profile={"network": "full"},
                    trust_level="sandboxed",
                ),
            )
        )


@pytest.mark.asyncio
async def test_kernel_create_system_tool_rejects_local_process_for_untrusted_tool():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    with pytest.raises(ValueError, match="local_process execution requires trust_level='trusted'"):
        await kernel.create_system_tool(
            CreateSystemToolRequest(
                actor=_actor(),
                name="repo_scan",
                description="Scans the local process workspace.",
                execution=ToolExecutionBinding(
                    backend_kind="local_process",
                    handler_ref="repo_scan",
                    trust_level="sandboxed",
                ),
            )
        )


@pytest.mark.asyncio
async def test_queue_tool_call_for_system_plugin_uses_mcp_backend_without_system_tool_id():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    step_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    user_id = uuid4()
    mcp_server_id = uuid4()

    repository._agents[system_agent_id] = AgentDefinition(
        agent_id=system_agent_id,
        display_name="Plugin Agent",
        description="Uses external System Plugins.",
        role="assistant",
        endpoint=AgentEndpoint(kind="local"),
        system_prompt="Use attached capabilities only.",
        created_by=user_id,
        created_at=now,
        updated_by=user_id,
        updated_at=now,
    )
    repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Plugin Agent",
        roles=["assistant"],
        status="active",
        visibility_scope="workspace",
        created_at=now,
        updated_at=now,
    )
    repository._tasks[task_id] = Task(
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Search the web",
        requested_by=user_id,
        status="claimed",
        claimed_by=participant_id,
        metadata={
            "target_system_agent_id": str(system_agent_id),
            "target_participant_id": str(participant_id),
            "response_visibility": "workspace",
        },
        created_at=now,
        updated_at=now,
    )
    repository._runs[run_id] = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        task_id=task_id,
        participant_id=participant_id,
        status="started",
        created_at=now,
        updated_at=now,
    )
    repository._run_steps[step_id] = RunStep(
        step_id=step_id,
        run_id=run_id,
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        system_agent_id=system_agent_id,
        status="claimed",
        claimed_by_worker="agent-worker",
        created_at=now,
        updated_at=now,
    )
    repository._workspace_mcp_tools[workspace_id] = [
        WorkspaceMcpTool(
            server_id=mcp_server_id,
            server_key="web_search",
            server_display_name="Web Search",
            exposed_name="web_search",
            remote_name="search",
            description="Search the web through SearXNG.",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            output_schema={"type": "object"},
            metadata={
                "workspace_attachment": {
                    "persist_assets": False,
                    "asset_candidate_output": "disabled",
                }
            },
        )
    ]

    result = await kernel.queue_tool_calls_for_run_step(
        step_id,
        "agent-worker",
        [
            AgentToolCallDraft(
                tool_name="web_search",
                arguments={"query": "open talon system plugins"},
                metadata={"source": "model"},
            )
        ],
    )

    queued_calls = repository._tool_calls[run_id]
    assert result.step.status == "waiting_tools"
    assert len(queued_calls) == 1
    tool_call = queued_calls[0]
    assert tool_call.tool_id is None
    assert tool_call.tool_name == "web_search"
    assert tool_call.metadata["tool_source"] == "mcp_server"
    assert tool_call.metadata["mcp_server_key"] == "web_search"
    assert tool_call.metadata["mcp_tool_name"] == "search"

    execution_spec = ExecutionSpec.model_validate(tool_call.execution_spec)
    assert execution_spec.handler_ref == "search"
    assert execution_spec.inline_payload == {"query": "open talon system plugins"}
    assert execution_spec.limits.network == "full"
    assert execution_spec.limits.workspace_access == "none"
    assert execution_spec.metadata["backend_kind"] == "mcp"
    assert execution_spec.metadata["tool_source"] == "mcp_server"
    assert execution_spec.metadata["mcp_server_id"] == str(mcp_server_id)
    assert execution_spec.metadata["mcp_tool_name"] == "search"
    assert execution_spec.metadata["mcp_workspace_attachment_metadata"] == {
        "persist_assets": False,
        "asset_candidate_output": "disabled",
    }
    assert "tool_id" not in execution_spec.metadata


@pytest.mark.asyncio
async def test_kernel_workspace_management_requires_admin_or_supervisor_role():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    owner_user_id = uuid4()
    member_user_id = uuid4()
    created = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Guarded",
            actor=ParticipantInput(
                participant_id=uuid4(),
                participant_type="user",
                user_id=owner_user_id,
                display_name="Owner",
            ),
        )
    )
    assert created.workspace is not None
    workspace_id = created.workspace.workspace_id
    member_participant_id = uuid4()
    repository._participants[(workspace_id, member_participant_id)] = ParticipantProfile(
        participant_id=member_participant_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=member_user_id,
        display_name="Member",
        roles=["user"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    with pytest.raises(PermissionError, match="Workspace permission 'workspace.roles.write' required"):
        await kernel.upsert_role_definition(
            workspace_id,
            UpsertRoleDefinitionRequest(
                actor=ParticipantInput(
                    participant_id=member_participant_id,
                    participant_type="user",
                    user_id=member_user_id,
                    display_name="Member",
                ),
                name="qa",
                definition="Reviews release candidates.",
            ),
        )

    with pytest.raises(PermissionError, match="Workspace permission 'workspace.repositories.write' required"):
        await kernel.create_git_repository(
            scope="workspace",
            workspace_id=workspace_id,
            payload=CreateGitRepositoryRequest(
                actor=ParticipantInput(
                    participant_id=member_participant_id,
                    participant_type="user",
                    user_id=member_user_id,
                    display_name="Member",
                ),
                name="workspace-defs",
                local_path="/tmp/workspace-defs",
            ),
        )


@pytest.mark.asyncio
async def test_kernel_setup_schema_backfills_existing_agents_without_contracts():
    stale_agent = AgentDefinition(
        agent_id=uuid4(),
        display_name="Legacy Agent",
        description="Older agent definition without explicit contract.",
        role="research agent",
        capabilities=["analysis"],
        endpoint=AgentEndpoint(kind="remote", url="https://example.invalid", model="gpt-5.4"),
        system_prompt="You are a research agent.",
        created_by=uuid4(),
    )
    repository = FakeRepository([stale_agent])
    kernel = CollaborationKernel(repository)

    await kernel.setup_schema()

    assert repository.setup_schema_calls == 1
    assert len(repository.upserted_agents) == 1
    backfilled = repository.upserted_agents[0]
    assert backfilled.agent_id == stale_agent.agent_id
    assert not interaction_contract_is_empty(backfilled.interaction_contract)
    assert backfilled.interaction_contract.response_contract.required_sections == [
        "Summary",
        "Evidence",
        "Open questions",
        "Next action",
    ]


@pytest.mark.asyncio
async def test_managed_system_defaults_repairer_recreates_managed_records():
    repository = FakeRepository()
    repository._agents.clear()
    repository._llm_providers.clear()
    repository._memory_providers.clear()

    summary = await ManagedSystemDefaultsRepairer(repository).repair()

    assert summary["organizations"] >= 2
    assert await repository.fetch_organization_by_slug("default") is not None
    assert await repository.fetch_organization_by_slug("system-base") is not None

    default_organization = await repository.fetch_organization_by_slug("default")
    system_base = await repository.fetch_organization_by_slug("system-base")
    default_project = await repository.fetch_project_by_slug(
        organization_id=default_organization.organization_id,
        slug="default",
    )
    default_administration = await repository.fetch_project_by_slug(
        organization_id=default_organization.organization_id,
        slug="administration",
    )
    system_administration = await repository.fetch_project_by_slug(
        organization_id=system_base.organization_id,
        slug="administration",
    )
    assert default_project is not None
    assert default_administration is not None
    assert system_administration is not None
    assert (
        default_project.project_id,
        "user",
        default_project.creator_user_id,
    ) in repository._project_access_bindings
    assert (
        default_administration.project_id,
        "user",
        default_administration.creator_user_id,
    ) in repository._project_access_bindings

    agent_keys = {agent.agent_key for agent in repository._agents.values()}
    assert {
        "tinker",
        "steward",
        "curator",
        "anchor",
        "researcher",
        "methodologist",
        "conductor",
    }.issubset(agent_keys)
    assert any(agent.display_name == "Reasoning Planner" for agent in repository._agents.values())
    tinker = next(agent for agent in repository._agents.values() if agent.agent_key == "tinker")
    assert tinker.role == "generated tool authoring and validation agent"
    assert "validates generated tools before approval" in tinker.capabilities
    assert tinker.definition["profile"]["kind"] == "workspace_tool_generation_specialist"
    assert "human approval for publication" in tinker.definition["profile"]["authority"]
    steward = next(agent for agent in repository._agents.values() if agent.agent_key == "steward")
    assert steward.role == "platform operations steward"
    assert "reviews platform runtime and audit health" in steward.capabilities
    assert steward.definition["profile"]["kind"] == "platform_operations_specialist"
    assert "platform_steward IAM role" in steward.definition["profile"]["authority"]
    curator = next(agent for agent in repository._agents.values() if agent.agent_key == "curator")
    assert curator.definition["profile"]["kind"] == "organization_operations_specialist"
    assert "stay inside the owning organization" in curator.definition["profile"]["boundaries"]
    researcher = next(
        agent for agent in repository._agents.values() if agent.agent_key == "researcher"
    )
    assert researcher.display_name == "Researcher"
    assert researcher.role == "evidence discovery and research dossier agent"
    assert researcher.definition["profile"]["kind"] == "methodology_research_dossier_specialist"
    assert (
        researcher.definition["profile"]["knowledge_layer"]
        == "dossier knowledge storage over retained data and indexed information"
    )
    assert researcher.definition["task_routing"]["normal_message_fanout"] is False
    assert researcher.definition["task_routing"]["accepted_task_kinds"] == [
        "methodology_research_dossier_build",
        "methodology_research_dossier_refine",
    ]
    assert "Research Scope" in researcher.interaction_contract.response_contract.required_sections
    assert "Contradictions" in researcher.interaction_contract.response_contract.required_sections
    methodologist = next(
        agent for agent in repository._agents.values() if agent.agent_key == "methodologist"
    )
    assert methodologist.display_name == "Methodologist"
    assert methodologist.role == "methodology extraction and workspace design agent"
    assert methodologist.endpoint.engine_id == "local-ollama"
    assert methodologist.endpoint.provider == "ollama"
    assert (
        methodologist.definition["profile"]["kind"]
        == "methodology_blueprint_synthesis_specialist"
    )
    assert (
        "do not perform open-ended research triage"
        in methodologist.definition["profile"]["boundaries"]
    )
    assert (
        "Workspace Template"
        in methodologist.interaction_contract.response_contract.required_sections
    )
    assert methodologist.definition["output_targets"]["workspace_harness_fields"] == [
        "methodology",
        "methodics",
        "execution_rules",
        "metadata",
    ]
    conductor = next(
        agent for agent in repository._agents.values() if agent.agent_key == "conductor"
    )
    assert conductor.display_name == "Conductor"
    assert conductor.role == "workspace methodics execution conductor"
    assert conductor.endpoint.engine_id == "local-ollama"
    assert conductor.endpoint.provider == "ollama"
    assert (
        conductor.definition["profile"]["kind"]
        == "workspace_methodics_execution_specialist"
    )
    assert (
        "no active loop without explicit execution start"
        in conductor.definition["profile"]["boundaries"]
    )
    assert conductor.definition["task_routing"]["normal_message_fanout"] is False
    assert conductor.definition["task_routing"]["accepted_task_kinds"] == [
        "methodics_execution_start",
        "methodics_step_coordinate",
        "methodics_step_verify",
        "methodics_resource_review",
    ]

    provider_keys = {provider.engine_id for provider in repository._llm_providers.values()}
    assert {"local-ollama", "openai-responses"}.issubset(provider_keys)
    memory_keys = {provider.provider_key for provider in repository._memory_providers.values()}
    assert {"postgres", "mem0"}.issubset(memory_keys)

    tool_names = {tool.name for tool in repository._system_tools.values()}
    assert "generated_tool_repo_bootstrap" in tool_names
    assert "generated_tool_registry_pull_verify" in tool_names
    tinker = next(agent for agent in repository._agents.values() if agent.agent_key == "tinker")
    tinker_internal_tools = {
        tool.name for tool in repository._agent_internal_tools[tinker.agent_id]
    }
    assert "generated_tool_repo_bootstrap" in tinker_internal_tools
    assert "generated_tool_registry_pull_verify" in tinker_internal_tools

    control_plane = next(iter(repository._mcp_servers.values()))
    assert control_plane.server_key == "open_talon_control_plane"
    assert {
        "organizations.list",
        "organizations.create",
        "workspaces.create",
        "iam.agent_identities.list",
        "methodology.dossiers.sources.create",
        "methodology.dossiers.notebook.get",
        "methodology.dossiers.notes.upsert",
        "methodology.dossiers.navigate",
        "methodology.blueprints.submit_draft",
        "methodics.resource_requests.approve",
    }.issubset({tool.tool_name for tool in repository._mcp_server_tools[control_plane.server_id]})
    web_search = next(
        server for server in repository._mcp_servers.values() if server.server_key == "web_search"
    )
    assert web_search.display_name == "Web Search"
    assert web_search.transport_kind == "streamable_http"
    assert web_search.config["url"] == "http://127.0.0.1:8181/mcp"
    assert web_search.config["capabilities"] == ["search", "fetch", "search_and_fetch"]
    assert web_search.last_sync_status == "not_synced"
    assert web_search.metadata["system_plugin"] is True
    assert web_search.metadata["backing_protocol"] == "mcp"
    library_plugin = next(
        server for server in repository._mcp_servers.values() if server.server_key == "library"
    )
    retriever_plugin = next(
        server for server in repository._mcp_servers.values() if server.server_key == "retriever"
    )
    assert library_plugin.display_name == "Library"
    assert retriever_plugin.display_name == "Retriever"
    assert library_plugin.config["url"] == "http://127.0.0.1:8000/v1/mcp"
    assert retriever_plugin.config["docling_serve_url"] is None
    assert {"library.libraries.create", "library.items.create_text"}.issubset(
        {tool.tool_name for tool in repository._mcp_server_tools[library_plugin.server_id]}
    )
    assert {"retriever.library.index", "retriever.search"}.issubset(
        {tool.tool_name for tool in repository._mcp_server_tools[retriever_plugin.server_id]}
    )

    steward_binding = repository._agent_internal_mcp_servers[
        (steward.agent_id, control_plane.server_id)
    ]
    assert "organizations.create" in steward_binding.tool_allowlist
    steward_role = next(role for role in repository._iam_roles.values() if role.name == "platform_steward")
    assert "organization.write" in steward_role.permissions
    researcher_binding = repository._agent_internal_mcp_servers[
        (researcher.agent_id, control_plane.server_id)
    ]
    assert "methodology.dossiers.mark_ready" in researcher_binding.tool_allowlist
    assert "methodology.dossiers.notes.upsert" in researcher_binding.tool_allowlist
    assert "methodology.dossiers.health.submit" in researcher_binding.tool_allowlist
    assert "methodology.blueprints.submit_draft" not in researcher_binding.tool_allowlist
    researcher_library_binding = repository._agent_internal_mcp_servers[
        (researcher.agent_id, library_plugin.server_id)
    ]
    researcher_retriever_binding = repository._agent_internal_mcp_servers[
        (researcher.agent_id, retriever_plugin.server_id)
    ]
    researcher_web_binding = repository._agent_internal_mcp_servers[
        (researcher.agent_id, web_search.server_id)
    ]
    assert "library.items.create_text" in researcher_library_binding.tool_allowlist
    assert "retriever.context_pack.create" in researcher_retriever_binding.tool_allowlist
    assert researcher_web_binding.server_key == "web_search"
    researcher_role = next(role for role in repository._iam_roles.values() if role.name == "methodology_researcher")
    assert "library.write" in researcher_role.permissions
    assert "methodology.write" in researcher_role.permissions
    methodologist_binding = repository._agent_internal_mcp_servers[
        (methodologist.agent_id, control_plane.server_id)
    ]
    assert "methodology.dossiers.get" in methodologist_binding.tool_allowlist
    assert "methodology.dossiers.navigate" in methodologist_binding.tool_allowlist
    assert "methodology.blueprints.submit_draft" in methodologist_binding.tool_allowlist
    methodologist_role = next(role for role in repository._iam_roles.values() if role.name == "methodology_methodologist")
    assert "methodology.write" in methodologist_role.permissions
    system_operations = next(
        workspace
        for workspace in repository._workspaces.values()
        if workspace.organization_id == system_base.organization_id
        and workspace.metadata.get("operations_level") == "system"
    )
    assert any(
        participant.workspace_id == system_operations.workspace_id
        and participant.system_agent_id == steward.agent_id
        for participant in repository._participants.values()
    )
    assert (
        system_administration.project_id,
        "agent",
        steward.agent_id,
    ) in repository._project_access_bindings

    curator = next(agent for agent in repository._agents.values() if agent.agent_key == "curator")
    curator_binding = repository._agent_internal_mcp_servers[
        (curator.agent_id, control_plane.server_id)
    ]
    assert "organizations.list" in curator_binding.tool_denylist
    assert "methodics.resource_requests.approve" not in curator_binding.tool_allowlist
    curator_role = next(role for role in repository._iam_roles.values() if role.name == "organization_curator")
    assert "organization.write" not in curator_role.permissions
    assert (
        default_administration.project_id,
        "agent",
        curator.agent_id,
    ) in repository._project_access_bindings

    conductor_binding = repository._agent_internal_mcp_servers[
        (conductor.agent_id, control_plane.server_id)
    ]
    assert "methodics.executions.get" in conductor_binding.tool_allowlist
    assert "methodics.resource_requests.create" in conductor_binding.tool_allowlist
    assert "methodics.assignments.create" in conductor_binding.tool_allowlist
    assert "methodics.steps.evaluate" in conductor_binding.tool_allowlist
    assert "methodics.executions.create" not in conductor_binding.tool_allowlist
    assert "methodics.resource_requests.approve" in conductor_binding.tool_denylist
    conductor_role = next(role for role in repository._iam_roles.values() if role.name == "workspace_conductor")
    assert conductor_role.permissions == [
        "workspace.read",
        "retrieval.read",
        "retrieval.search",
        "methodics.read",
        "methodics.execute",
    ]


def test_agent_definition_rejects_unknown_seeded_profile_kind():
    with pytest.raises(ValueError):
        AgentDefinition(
            agent_id=uuid4(),
            agent_key="custom",
            display_name="Custom",
            description="Invalid profile contract coverage.",
            role="test agent",
            capabilities=[],
            endpoint=AgentEndpoint(kind="system"),
            system_prompt="Test.",
            definition={
                "profile": {
                    "profile_version": 1,
                    "kind": "unknown_specialist",
                    "mandate": "Test.",
                    "activation": "Test.",
                    "authority": ["test authority"],
                    "boundaries": ["test boundary"],
                }
            },
            created_by=uuid4(),
        )


@pytest.mark.asyncio
async def test_seeded_agent_profiles_are_typed_and_match_docs_cards():
    repository = FakeRepository()

    await ManagedSystemDefaultsRepairer(repository).repair()

    concept_doc = (
        ROOT_DIR / "docs" / "seeded-agents" / "system-and-roles-concept.md"
    ).read_text(encoding="utf-8")
    profiles_by_kind = set()
    for doc_name, (lookup_field, lookup_value, display_name, expected_kind) in (
        SEEDED_AGENT_PROFILE_DOCS.items()
    ):
        agent = next(
            agent
            for agent in repository._agents.values()
            if getattr(agent, lookup_field) == lookup_value
        )
        profile = SeededAgentProfile.model_validate(agent.definition["profile"])

        assert profile == agent.seeded_profile
        assert profile.profile_version == 1
        assert profile.kind == expected_kind
        assert profile.authority
        assert profile.boundaries
        profiles_by_kind.add(profile.kind)

        card = (ROOT_DIR / "docs" / "seeded-agents" / doc_name).read_text(
            encoding="utf-8"
        )
        assert f"| Profile kind | `{profile.kind}` |" in card
        assert f"| {display_name} | `{profile.kind}` |" in concept_doc

    seeded_profile_kinds = {
        SeededAgentProfile.model_validate(agent.definition["profile"]).kind
        for agent in repository._agents.values()
        if agent.definition.get("profile") is not None
    }
    assert seeded_profile_kinds == profiles_by_kind


def test_seeded_agent_profile_is_descriptive_not_runtime_task_authority():
    profile = SeededAgentProfile(
        kind="workspace_methodics_execution_specialist",
        mandate="Describe a specialist boundary without granting runtime authority.",
        activation="Only explicit task routing should decide accepted task kinds.",
        authority=["profile authority text is not executable authorization"],
        boundaries=["must not claim blocked_task from the profile alone"],
    ).model_dump(mode="json")
    agent_definition = {
        "profile": profile,
        "task_routing": {"accepted_task_kinds": ["allowed_task"]},
    }
    now = datetime.now(timezone.utc)
    allowed_task = Task(
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        title="Allowed",
        requested_by=uuid4(),
        created_at=now,
        updated_at=now,
        metadata={"task_kind": "allowed_task"},
    )
    blocked_task = allowed_task.model_copy(
        update={
            "task_id": uuid4(),
            "title": "Blocked",
            "metadata": {"task_kind": "blocked_task"},
        }
    )

    assert RuntimeExecutionService._agent_accepts_task_kind(
        agent_definition,
        allowed_task,
    )
    assert not RuntimeExecutionService._agent_accepts_task_kind(
        agent_definition,
        blocked_task,
    )
    assert RuntimeExecutionService._agent_accepts_task_kind(
        {"profile": profile},
        blocked_task,
    )


@pytest.mark.asyncio
async def test_runtime_claimability_uses_task_routing_not_definition_profile():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    user_participant_id = uuid4()
    profile = SeededAgentProfile(
        kind="workspace_methodics_execution_specialist",
        mandate="Describe a runtime profile without granting authorization.",
        activation="Profile activation text is descriptive only.",
        authority=["profile text claims blocked_task authority"],
        boundaries=["profile text says allowed_task should not be claimed"],
    ).model_dump(mode="json")

    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Runtime Profile Boundary",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Runtime",
        created_at=now,
        updated_at=now,
    )
    repository._agents[system_agent_id] = AgentDefinition(
        agent_id=system_agent_id,
        agent_key="profile-runtime-boundary",
        display_name="Profile Runtime Boundary",
        description="Verifies profile text is not runtime authorization.",
        role="runtime test agent",
        capabilities=["tests runtime routing"],
        endpoint=AgentEndpoint(kind="system"),
        system_prompt="Follow runtime task routing.",
        definition={
            "profile": profile,
            "task_routing": {"accepted_task_kinds": ["allowed_task"]},
        },
        created_by=user_participant_id,
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, user_participant_id)] = ParticipantProfile(
        participant_id=user_participant_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=uuid4(),
        display_name="Nikolay",
        status="active",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Profile Runtime Boundary",
        roles=["runtime test agent"],
        capabilities=["tests runtime routing"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    allowed_task = Task(
        task_id=uuid4(),
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Allowed by task routing",
        requested_by=user_participant_id,
        created_at=now,
        updated_at=now,
        metadata={
            "target_system_agent_id": str(system_agent_id),
            "target_participant_id": str(participant_id),
            "task_kind": "allowed_task",
        },
    )
    blocked_task = allowed_task.model_copy(
        update={
            "task_id": uuid4(),
            "title": "Only profile text says this is authorized",
            "metadata": {
                "target_system_agent_id": str(system_agent_id),
                "target_participant_id": str(participant_id),
                "task_kind": "blocked_task",
            },
        }
    )
    repository._tasks[allowed_task.task_id] = allowed_task
    repository._tasks[blocked_task.task_id] = blocked_task

    pending = await kernel.list_pending_tasks_for_system_agent(system_agent_id)

    assert [task.task_id for task in pending] == [allowed_task.task_id]
    claim = await kernel.claim_task_for_system_agent(
        allowed_task.task_id,
        system_agent_id,
    )
    assert claim.task is not None
    assert claim.task.task_id == allowed_task.task_id
    assert claim.task.status == "claimed"
    with pytest.raises(ValueError, match="task kind not accepted"):
        await kernel.claim_task_for_system_agent(blocked_task.task_id, system_agent_id)


@pytest.mark.asyncio
async def test_managed_system_defaults_repairer_reuses_existing_org_curator_by_key():
    repository = FakeRepository()
    default_organization = next(
        organization
        for organization in repository._organizations.values()
        if organization.slug == "default"
    )
    legacy_created_at = datetime.now(timezone.utc) - timedelta(days=1)
    legacy_curator = curator_agent_for_organization(
        default_organization,
        now=legacy_created_at,
    ).model_copy(
        update={
            "agent_id": uuid4(),
            "metadata": {"legacy": True},
        }
    )
    legacy_curator_role = curator_iam_role_for_organization(
        default_organization.organization_id,
        now=legacy_created_at,
    ).model_copy(
        update={
            "role_id": uuid4(),
            "metadata": {"legacy": True},
        }
    )
    repository._agents[legacy_curator.agent_id] = legacy_curator
    repository._iam_roles[legacy_curator_role.role_id] = legacy_curator_role

    await ManagedSystemDefaultsRepairer(repository).repair()

    curator_agents = [
        agent
        for agent in repository._agents.values()
        if agent.scope == "organization"
        and agent.organization_id == default_organization.organization_id
        and agent.agent_key == "curator"
    ]
    assert len(curator_agents) == 1
    assert curator_agents[0].agent_id == legacy_curator.agent_id
    assert curator_agents[0].created_at == legacy_created_at
    assert curator_agents[0].metadata["legacy"] is True
    assert curator_agents[0].metadata["managed"] is True
    curator_roles = [
        role
        for role in repository._iam_roles.values()
        if role.scope == "organization"
        and role.organization_id == default_organization.organization_id
        and role.name == "organization_curator"
    ]
    assert len(curator_roles) == 1
    assert curator_roles[0].role_id == legacy_curator_role.role_id
    assert curator_roles[0].created_at == legacy_created_at
    assert curator_roles[0].metadata["legacy"] is True
    assert curator_roles[0].metadata["managed"] is True


def _methodology_actor() -> ParticipantInput:
    actor_id = uuid4()
    return ParticipantInput(
        participant_id=actor_id,
        participant_type="user",
        user_id=actor_id,
        display_name="Methodology Owner",
        iam_permissions=sorted(WORKSPACE_PERMISSION_NAMES),
    )


async def _seed_methodology_world() -> tuple[
    FakeRepository,
    CollaborationKernel,
    Organization,
    Workspace,
    ParticipantInput,
]:
    repository = FakeRepository()
    await ManagedSystemDefaultsRepairer(repository).repair()
    organization = next(
        organization
        for organization in repository._organizations.values()
        if organization.slug == "default"
    )
    operations_workspace = next(
        workspace
        for workspace in repository._workspaces.values()
        if workspace.organization_id == organization.organization_id
        and workspace.metadata.get("managed") is True
        and workspace.metadata.get("operations_workspace") is True
        and workspace.metadata.get("operations_level") == "organization"
    )
    return (
        repository,
        CollaborationKernel(repository),
        organization,
        operations_workspace,
        _methodology_actor(),
    )


def _methodology_library(
    repository: FakeRepository,
    *,
    organization_id: UUID,
    actor: ParticipantInput,
    scope: str = "organization",
) -> Library:
    now = datetime.now(timezone.utc)
    library = Library(
        library_id=uuid4(),
        scope=scope,
        organization_id=organization_id,
        project_id=uuid4() if scope == "project" else None,
        slug=f"methodology-{uuid4().hex[:8]}",
        name="Methodology Sources",
        created_by=actor.participant_id,
        updated_by=actor.participant_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    repository._libraries[library.library_id] = library
    return library


def _methodology_library_item(
    repository: FakeRepository,
    *,
    library: Library,
    actor: ParticipantInput,
    title: str = "Evidence Note",
) -> LibraryItem:
    now = datetime.now(timezone.utc)
    asset_id = uuid4()
    version_id = uuid4()
    repository._workspace_assets[asset_id] = WorkspaceAsset(
        asset_id=asset_id,
        scope=library.scope,
        organization_id=library.organization_id,
        project_id=library.project_id,
        workspace_id=library.workspace_id,
        asset_type="text",
        logical_name=title.lower().replace(" ", "-"),
        title=title,
        created_by=actor.participant_id,
        created_at=now,
        updated_at=now,
    )
    repository._workspace_asset_versions[version_id] = WorkspaceAssetVersion(
        asset_version_id=version_id,
        asset_id=asset_id,
        version=1,
        source_kind="library_text",
        bucket="open-talon-assets",
        object_key=f"methodology/{asset_id}.md",
        content_type="text/markdown",
        size_bytes=128,
        sha256="b" * 64,
        created_by=actor.participant_id,
        created_at=now,
    )
    item = LibraryItem(
        item_id=uuid4(),
        library_id=library.library_id,
        asset_id=asset_id,
        active_asset_version_id=version_id,
        item_kind="text",
        title=title,
        content_type="text/markdown",
        created_by=actor.participant_id,
        updated_by=actor.participant_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    repository._library_items[item.item_id] = item
    return item


def _methodology_context_pack(
    repository: FakeRepository,
    *,
    organization_id: UUID,
    actor: ParticipantInput,
    content: str = "Source [1] supports the methodology basis.",
) -> RetrievalContextPack:
    now = datetime.now(timezone.utc)
    context_pack = RetrievalContextPack(
        context_pack_id=uuid4(),
        scope="organization",
        organization_id=organization_id,
        query="methodology source evidence",
        content=content,
        token_count=12,
        created_by=actor.participant_id,
        created_at=now,
        metadata={"citation_ids": ["S1"]},
    )
    repository._retrieval_context_packs[context_pack.context_pack_id] = context_pack
    return context_pack


async def _create_methodology_blueprint_fixture(
    repository: FakeRepository,
    kernel: CollaborationKernel,
    organization: Organization,
    actor: ParticipantInput,
) -> MethodologyBlueprintDetail:
    selected_library = _methodology_library(
        repository,
        organization_id=organization.organization_id,
        actor=actor,
    )
    result = await kernel.create_methodology_blueprint(
        organization.organization_id,
        CreateMethodologyBlueprintRequest(
            actor=actor,
            title="Evidence-backed onboarding",
            topic="Use evidence to onboard organization teams",
            target_goal="Create a reusable onboarding methodology",
            tasks=["Discover sources", "Map contradictions", "Draft workspace harness"],
            library_ids=[selected_library.library_id],
        ),
    )
    assert result.detail is not None
    return result.detail


@pytest.mark.asyncio
async def test_methodology_blueprint_creation_creates_dossier_library_and_researcher_task():
    repository, kernel, organization, operations_workspace, actor = (
        await _seed_methodology_world()
    )

    detail = await _create_methodology_blueprint_fixture(
        repository,
        kernel,
        organization,
        actor,
    )

    assert detail.blueprint.status == "draft"
    assert len(detail.versions) == 1
    version = detail.versions[0]
    assert version.status == "researching"
    assert version.research_dossier_id == detail.dossier.dossier_id
    dossier = detail.dossier
    assert dossier is not None
    assert dossier.status == "researching"
    assert dossier.operations_workspace_id == operations_workspace.workspace_id
    assert dossier.retained_library_id in repository._libraries
    retained_library = repository._libraries[dossier.retained_library_id]
    assert retained_library.scope == "organization"
    assert retained_library.organization_id == organization.organization_id
    assert retained_library.metadata["research_dossier"] is True
    notebook_detail = await kernel.get_research_dossier_notebook_detail(
        dossier.dossier_id,
        actor=actor,
    )
    assert notebook_detail.notebook.provider_kind == "xwiki"
    assert notebook_detail.notebook.external_space_ref.startswith("Dossiers.dossier-")
    assert notebook_detail.provider_bindings[0].provider_key == "xwiki"
    assert notebook_detail.provider_bindings[0].external_space_ref == (
        notebook_detail.notebook.external_space_ref
    )
    assert {note.slug for note in notebook_detail.notes} == {
        "home",
        "sources",
        "concepts",
        "entities",
        "methods",
        "questions",
        "contradictions",
        "gaps",
        "synthesis",
    }
    assert len(notebook_detail.external_refs) == 10
    assert repository._threads[dossier.thread_id].metadata["research_dossier_id"] == str(
        dossier.dossier_id
    )

    researcher = await repository.fetch_system_agent_by_key(
        scope="global",
        organization_id=None,
        agent_key="researcher",
    )
    methodologist = await repository.fetch_system_agent_by_key(
        scope="global",
        organization_id=None,
        agent_key="methodologist",
    )
    assert await repository.fetch_agent_participant(
        operations_workspace.workspace_id,
        researcher.agent_id,
    )
    assert await repository.fetch_agent_participant(
        operations_workspace.workspace_id,
        methodologist.agent_id,
    )
    researcher_tasks = await kernel.list_pending_tasks_for_system_agent(
        researcher.agent_id
    )
    assert len(researcher_tasks) == 1
    task = researcher_tasks[0]
    assert task.correlation_id == dossier.dossier_id
    assert task.metadata["task_kind"] == "methodology_research_dossier_build"
    assert task.metadata["retained_library_id"] == str(dossier.retained_library_id)
    assert "Use web follow-up for gaps, recency, and contradiction checks." in task.metadata[
        "task_instructions"
    ]
    assert repository._methodic_executions == {}


@pytest.mark.asyncio
async def test_research_dossier_notebook_concepts_claims_links_health_and_sync():
    repository, kernel, organization, _operations_workspace, actor = (
        await _seed_methodology_world()
    )
    detail = await _create_methodology_blueprint_fixture(
        repository,
        kernel,
        organization,
        actor,
    )
    dossier = detail.dossier
    source_result = await kernel.create_research_dossier_source(
        dossier.dossier_id,
        CreateResearchDossierSourceRequest(
            actor=actor,
            source_kind="webpage",
            status="included",
            title="Evidence onboarding source",
            source_uri="https://example.test/onboarding",
            citation_id="S1",
            quality_notes="Primary source for test evidence.",
        ),
    )
    source = source_result.source
    assert source is not None

    concept_result = await kernel.upsert_research_dossier_concept(
        dossier.dossier_id,
        UpsertResearchDossierConceptRequest(
            actor=actor,
            slug="evidence-backed-onboarding",
            name="Evidence-backed onboarding",
            definition="Onboarding decisions grounded in retained source evidence.",
            status="active",
            confidence=0.9,
            source_ids=[source.source_id],
        ),
    )
    concept = concept_result.concept
    assert concept is not None

    note_result = await kernel.upsert_research_dossier_note(
        dossier.dossier_id,
        UpsertResearchDossierNoteRequest(
            actor=actor,
            note_kind="concept",
            status="active",
            slug="evidence-backed-onboarding-note",
            title="Evidence-backed onboarding",
            body="Concept note with [[S1]] citation.",
            concept_id=concept.concept_id,
            citation_ids=["S1"],
        ),
    )
    note = note_result.note
    assert note is not None

    claim_result = await kernel.upsert_research_dossier_claim(
        dossier.dossier_id,
        UpsertResearchDossierClaimRequest(
            actor=actor,
            claim_key="claim:evidence-onboarding",
            statement="Reusable onboarding should be grounded in retained evidence.",
            status="supported",
            confidence=0.8,
            source_ids=[source.source_id],
            citation_ids=["S1"],
        ),
    )
    claim = claim_result.claim
    assert claim is not None

    link_result = await kernel.upsert_research_dossier_link(
        dossier.dossier_id,
        UpsertResearchDossierLinkRequest(
            actor=actor,
            source_type="concept",
            source_ref_id=concept.concept_id,
            target_type="claim",
            target_ref_id=claim.claim_id,
            link_kind="supports",
            rationale="The concept contains the supported claim.",
            confidence=0.7,
        ),
    )
    link = link_result.link
    assert link is not None

    navigation = await kernel.navigate_research_dossier(
        dossier.dossier_id,
        NavigateResearchDossierRequest(
            actor=actor,
            query="onboarding",
            max_results=5,
        ),
    )
    assert [item.concept_id for item in navigation.concepts] == [concept.concept_id]
    assert any(item.note_id == note.note_id for item in navigation.entry_notes)
    assert navigation.links[0].link_id == link.link_id

    health = await kernel.submit_research_dossier_health_check(
        dossier.dossier_id,
        SubmitResearchDossierHealthCheckRequest(
            actor=actor,
            status="passed",
            summary="Concept notebook is navigable.",
        ),
    )
    assert health.status == "passed"
    sync = await kernel.sync_research_dossier_notebook(
        dossier.dossier_id,
        SyncResearchDossierNotebookRequest(
            actor=actor,
            provider_key="xwiki",
            metadata={"test": True},
        ),
        stats={"pages_synced": 11},
    )
    assert sync.status == "completed"
    refreshed = await kernel.get_research_dossier_notebook_detail(
        dossier.dossier_id,
        actor=actor,
    )
    assert refreshed.latest_health_check is not None
    assert refreshed.latest_health_check.check_id == health.check_id
    assert refreshed.notebook.status == "ready"
    assert refreshed.provider_bindings[0].last_sync_at == sync.completed_at
    assert {
        event.event_type for event in await repository.list_research_dossier_events(
            dossier.dossier_id
        )
    }.issuperset(
        {
            "research_dossier_notebook.concept_upserted",
            "research_dossier_notebook.claim_upserted",
            "research_dossier_notebook.link_upserted",
            "research_dossier_notebook.health_checked",
            "research_dossier_notebook.synced",
        }
    )


@pytest.mark.asyncio
async def test_research_dossier_notebook_upserts_are_idempotent_by_natural_keys():
    repository, kernel, organization, _operations_workspace, actor = (
        await _seed_methodology_world()
    )
    detail = await _create_methodology_blueprint_fixture(
        repository,
        kernel,
        organization,
        actor,
    )
    dossier = detail.dossier
    source_result = await kernel.create_research_dossier_source(
        dossier.dossier_id,
        CreateResearchDossierSourceRequest(
            actor=actor,
            source_kind="webpage",
            status="included",
            title="Retry-safe evidence",
            source_uri="https://example.test/retry-safe",
            citation_id="S1",
        ),
    )
    source = source_result.source
    assert source is not None

    first_concept = (
        await kernel.upsert_research_dossier_concept(
            dossier.dossier_id,
            UpsertResearchDossierConceptRequest(
                actor=actor,
                slug="retry-safe-concept",
                name="Retry-safe concept",
                definition="Initial definition.",
                status="candidate",
                source_ids=[source.source_id],
                metadata={"attempt": 1},
            ),
        )
    ).concept
    second_concept = (
        await kernel.upsert_research_dossier_concept(
            dossier.dossier_id,
            UpsertResearchDossierConceptRequest(
                actor=actor,
                slug="retry-safe-concept",
                name="Retry-safe concept updated",
                definition="Updated definition.",
                status="active",
                confidence=0.91,
                source_ids=[source.source_id],
                metadata={"attempt": 2},
            ),
        )
    ).concept
    assert first_concept is not None
    assert second_concept is not None
    assert second_concept.concept_id == first_concept.concept_id
    assert second_concept.created_at == first_concept.created_at
    assert second_concept.definition == "Updated definition."
    assert second_concept.metadata == {"attempt": 2}

    first_note = (
        await kernel.upsert_research_dossier_note(
            dossier.dossier_id,
            UpsertResearchDossierNoteRequest(
                actor=actor,
                note_kind="concept",
                status="draft",
                slug="retry-safe-note",
                title="Retry-safe note",
                body="Initial body.",
                concept_id=second_concept.concept_id,
                citation_ids=["S1"],
            ),
        )
    ).note
    second_note = (
        await kernel.upsert_research_dossier_note(
            dossier.dossier_id,
            UpsertResearchDossierNoteRequest(
                actor=actor,
                note_kind="concept",
                status="active",
                slug="retry-safe-note",
                title="Retry-safe note updated",
                body="Updated body.",
                concept_id=second_concept.concept_id,
                citation_ids=["S1", "S2"],
            ),
        )
    ).note
    assert first_note is not None
    assert second_note is not None
    assert second_note.note_id == first_note.note_id
    assert second_note.status == "active"
    assert second_note.citation_ids == ["S1", "S2"]

    first_claim = (
        await kernel.upsert_research_dossier_claim(
            dossier.dossier_id,
            UpsertResearchDossierClaimRequest(
                actor=actor,
                claim_key="claim:retry-safe",
                statement="Initial claim.",
                status="draft",
                source_ids=[source.source_id],
                citation_ids=["S1"],
            ),
        )
    ).claim
    second_claim = (
        await kernel.upsert_research_dossier_claim(
            dossier.dossier_id,
            UpsertResearchDossierClaimRequest(
                actor=actor,
                claim_key="claim:retry-safe",
                statement="Updated claim.",
                status="supported",
                confidence=0.82,
                source_ids=[source.source_id],
                citation_ids=["S1"],
            ),
        )
    ).claim
    assert first_claim is not None
    assert second_claim is not None
    assert second_claim.claim_id == first_claim.claim_id
    assert second_claim.statement == "Updated claim."

    first_link = (
        await kernel.upsert_research_dossier_link(
            dossier.dossier_id,
            UpsertResearchDossierLinkRequest(
                actor=actor,
                source_type="concept",
                source_ref_id=second_concept.concept_id,
                target_type="claim",
                target_ref_id=second_claim.claim_id,
                link_kind="supports",
                rationale="Initial rationale.",
            ),
        )
    ).link
    second_link = (
        await kernel.upsert_research_dossier_link(
            dossier.dossier_id,
            UpsertResearchDossierLinkRequest(
                actor=actor,
                source_type="concept",
                source_ref_id=second_concept.concept_id,
                target_type="claim",
                target_ref_id=second_claim.claim_id,
                link_kind="supports",
                rationale="Updated rationale.",
                confidence=0.75,
            ),
        )
    ).link
    assert first_link is not None
    assert second_link is not None
    assert second_link.link_id == first_link.link_id
    assert second_link.rationale == "Updated rationale."

    notebook = await kernel.get_research_dossier_notebook_detail(
        dossier.dossier_id,
        actor=actor,
    )
    assert [item.slug for item in notebook.concepts].count("retry-safe-concept") == 1
    assert [item.slug for item in notebook.notes].count("retry-safe-note") == 1
    assert [item.claim_key for item in notebook.claims].count("claim:retry-safe") == 1
    assert len(
        [
            item
            for item in notebook.links
            if item.source_ref_id == second_concept.concept_id
            and item.target_ref_id == second_claim.claim_id
            and item.link_kind == "supports"
        ]
    ) == 1


@pytest.mark.asyncio
async def test_research_dossier_agent_events_record_system_agent_id_not_participant_id():
    repository, kernel, organization, operations_workspace, actor = (
        await _seed_methodology_world()
    )
    detail = await _create_methodology_blueprint_fixture(
        repository,
        kernel,
        organization,
        actor,
    )
    dossier = detail.dossier
    researcher = await repository.fetch_system_agent_by_key(
        scope="global",
        organization_id=None,
        agent_key="researcher",
    )
    researcher_participant = await repository.fetch_agent_participant(
        operations_workspace.workspace_id,
        researcher.agent_id,
    )
    agent_actor = ParticipantInput(
        participant_id=researcher_participant.participant_id,
        participant_type="agent",
        display_name=researcher.display_name,
    )

    source_result = await kernel.create_research_dossier_source(
        dossier.dossier_id,
        CreateResearchDossierSourceRequest(
            actor=agent_actor,
            source_kind="webpage",
            status="included",
            title="Researcher source",
            source_uri="https://example.test/researcher-source",
        ),
    )
    source = source_result.source
    assert source is not None
    assert source.discovered_by_system_agent_id == researcher.agent_id
    assert source.discovered_by_system_agent_id != researcher_participant.participant_id
    source_events = [
        event
        for event in await repository.list_research_dossier_events(dossier.dossier_id)
        if event.event_type == "research_dossier_source.created"
    ]
    assert source_events[0].system_agent_id == researcher.agent_id


@pytest.mark.asyncio
async def test_research_dossier_sources_reject_cross_org_refs_and_ready_handoff():
    repository, kernel, organization, _operations_workspace, actor = (
        await _seed_methodology_world()
    )
    detail = await _create_methodology_blueprint_fixture(
        repository,
        kernel,
        organization,
        actor,
    )
    dossier = detail.dossier
    same_org_library = _methodology_library(
        repository,
        organization_id=organization.organization_id,
        actor=actor,
    )
    same_org_item = _methodology_library_item(
        repository,
        library=same_org_library,
        actor=actor,
    )
    context_pack = _methodology_context_pack(
        repository,
        organization_id=organization.organization_id,
        actor=actor,
    )

    source_result = await kernel.create_research_dossier_source(
        dossier.dossier_id,
        CreateResearchDossierSourceRequest(
            actor=actor,
            source_kind="library_item",
            status="included",
            title="Evidence Note",
            library_id=same_org_library.library_id,
            library_item_id=same_org_item.item_id,
            asset_id=same_org_item.asset_id,
            asset_version_id=same_org_item.active_asset_version_id,
            context_pack_ids=[context_pack.context_pack_id],
            citation_id="S1",
            quality_notes="Directly relevant retained source.",
            rationale="Primary source for onboarding constraints.",
        ),
    )

    source = source_result.source
    assert source is not None
    assert source.status == "included"
    assert source.library_item_id == same_org_item.item_id
    assert source.context_pack_ids == [context_pack.context_pack_id]
    assert {
        event.event_type
        for event in await repository.list_research_dossier_events(dossier.dossier_id)
    } == {"research_dossier.created", "research_dossier_source.created"}

    cross_org_library = _methodology_library(
        repository,
        organization_id=uuid4(),
        actor=actor,
    )
    with pytest.raises(KeyError, match="not found in organization"):
        await kernel.create_research_dossier_source(
            dossier.dossier_id,
            CreateResearchDossierSourceRequest(
                actor=actor,
                source_kind="library_item",
                status="included",
                title="Wrong Org Source",
                library_id=cross_org_library.library_id,
            ),
        )

    cross_org_pack = _methodology_context_pack(
        repository,
        organization_id=uuid4(),
        actor=actor,
    )
    with pytest.raises(ValueError, match="context pack belongs to a different organization"):
        await kernel.create_research_dossier_source(
            dossier.dossier_id,
            CreateResearchDossierSourceRequest(
                actor=actor,
                source_kind="other",
                status="included",
                title="Wrong Org Context",
                context_pack_ids=[cross_org_pack.context_pack_id],
            ),
        )

    updated_dossier = await kernel.attach_research_dossier_context_pack(
        dossier.dossier_id,
        AttachResearchDossierContextPackRequest(
            actor=actor,
            context_pack_id=context_pack.context_pack_id,
            source_id=source.source_id,
        ),
    )
    assert updated_dossier.context_pack_ids == [context_pack.context_pack_id]
    assert repository._research_dossier_sources[source.source_id].context_pack_ids == [
        context_pack.context_pack_id
    ]

    ready = await kernel.mark_research_dossier_ready(
        dossier.dossier_id,
        MarkResearchDossierReadyRequest(
            actor=actor,
            summary="Evidence is sufficient for Methodologist.",
            contradictions=[
                {
                    "claim": "Team autonomy",
                    "sources": ["S1"],
                    "note": "Source disagrees on approval depth.",
                }
            ],
            gaps=["No recent compliance source found."],
        ),
    )

    assert ready.status == "ready_for_methodologist"
    assert ready.summary == "Evidence is sufficient for Methodologist."
    assert repository._methodology_blueprint_versions[detail.versions[0].version_id].status == (
        "ready_for_methodologist"
    )
    methodologist = await repository.fetch_system_agent_by_key(
        scope="global",
        organization_id=None,
        agent_key="methodologist",
    )
    methodologist_tasks = await kernel.list_pending_tasks_for_system_agent(
        methodologist.agent_id
    )
    assert len(methodologist_tasks) == 1
    assert methodologist_tasks[0].metadata["task_kind"] == "methodology_blueprint_draft"
    assert methodologist_tasks[0].metadata["dossier_summary"] == ready.summary
    assert methodologist_tasks[0].metadata["context_pack_ids"] == [
        str(context_pack.context_pack_id)
    ]
    assert methodologist_tasks[0].metadata["dossier_sources"][0]["source_id"] == str(
        source.source_id
    )
    assert methodologist_tasks[0].metadata["dossier_sources"][0]["status"] == "included"
    assert repository._methodic_executions == {}


@pytest.mark.asyncio
async def test_compound_research_dossier_workflow_preserves_knowledge_layers():
    repository, kernel, organization, operations_workspace, actor = (
        await _seed_methodology_world()
    )
    detail = await _create_methodology_blueprint_fixture(
        repository,
        kernel,
        organization,
        actor,
    )
    dossier = detail.dossier
    researcher = await repository.fetch_system_agent_by_key(
        scope="global",
        organization_id=None,
        agent_key="researcher",
    )
    methodologist = await repository.fetch_system_agent_by_key(
        scope="global",
        organization_id=None,
        agent_key="methodologist",
    )
    assert researcher is not None
    assert methodologist is not None
    researcher_participant = await repository.fetch_agent_participant(
        operations_workspace.workspace_id,
        researcher.agent_id,
    )
    methodologist_participant = await repository.fetch_agent_participant(
        operations_workspace.workspace_id,
        methodologist.agent_id,
    )
    assert researcher_participant is not None
    assert methodologist_participant is not None
    researcher_actor = ParticipantInput(
        participant_id=researcher_participant.participant_id,
        participant_type="agent",
        display_name=researcher.display_name,
    )
    methodologist_actor = ParticipantInput(
        participant_id=methodologist_participant.participant_id,
        participant_type="agent",
        display_name=methodologist.display_name,
    )
    retained_library = repository._libraries[dossier.retained_library_id]
    retained_item = _methodology_library_item(
        repository,
        library=retained_library,
        actor=actor,
        title="Retained onboarding field guide",
    )
    context_pack = _methodology_context_pack(
        repository,
        organization_id=organization.organization_id,
        actor=actor,
        content=(
            "S1 supports evidence-backed onboarding. S2 warns that approval-heavy "
            "onboarding reduces team autonomy."
        ),
    )

    local_source = (
        await kernel.create_research_dossier_source(
            dossier.dossier_id,
            CreateResearchDossierSourceRequest(
                actor=researcher_actor,
                source_kind="library_item",
                status="included",
                title="Retained onboarding field guide",
                library_id=retained_library.library_id,
                library_item_id=retained_item.item_id,
                asset_id=retained_item.asset_id,
                asset_version_id=retained_item.active_asset_version_id,
                context_pack_ids=[context_pack.context_pack_id],
                citation_id="S1",
                quality_notes="Retained internal field guide with direct task evidence.",
                rationale="Primary local evidence for onboarding methodics.",
                fetch_metadata={"storage_layer": "library", "raw_asset_preserved": True},
            ),
        )
    ).source
    unresolved_web_source = (
        await kernel.create_research_dossier_source(
            dossier.dossier_id,
            CreateResearchDossierSourceRequest(
                actor=researcher_actor,
                source_kind="webpage",
                status="unresolved",
                title="Recent onboarding benchmark",
                source_uri="https://example.test/recent-onboarding-benchmark",
                citation_id="S2",
                quality_notes="Recent web source found during follow-up discovery.",
                contradictions=[
                    {
                        "claim": "Approval depth",
                        "note": "Benchmarks recommend lighter approval gates.",
                    }
                ],
                rationale="Used to map disagreement around approval-heavy workflows.",
                fetch_metadata={"storage_layer": "web_snapshot", "fetched": True},
            ),
        )
    ).source
    included_web_source = (
        await kernel.update_research_dossier_source(
            dossier.dossier_id,
            unresolved_web_source.source_id,
            UpdateResearchDossierSourceRequest(
                actor=researcher_actor,
                status="included",
                quality_notes="Triaged as relevant and recent enough for synthesis.",
                metadata={"triage": "resolved_after_followup"},
            ),
        )
    ).source
    duplicate_source = (
        await kernel.create_research_dossier_source(
            dossier.dossier_id,
            CreateResearchDossierSourceRequest(
                actor=researcher_actor,
                source_kind="webpage",
                status="duplicate",
                title="Mirror of onboarding field guide",
                source_uri="https://example.test/field-guide-mirror",
                rationale="Duplicate of S1, retained as metadata only.",
            ),
        )
    ).source
    excluded_source = (
        await kernel.create_research_dossier_source(
            dossier.dossier_id,
            CreateResearchDossierSourceRequest(
                actor=researcher_actor,
                source_kind="paper",
                status="excluded",
                title="Consumer onboarding paper",
                source_uri="https://example.test/consumer-onboarding",
                rationale="Different domain from organization team onboarding.",
            ),
        )
    ).source
    failed_source = (
        await kernel.create_research_dossier_source(
            dossier.dossier_id,
            CreateResearchDossierSourceRequest(
                actor=researcher_actor,
                source_kind="webpage",
                status="failed",
                title="Removed onboarding memo",
                source_uri="https://example.test/removed-onboarding-memo",
                error="404 during fetch",
                rationale="Search result retained as failed evidence trail.",
            ),
        )
    ).source
    unresolved_source = (
        await kernel.create_research_dossier_source(
            dossier.dossier_id,
            CreateResearchDossierSourceRequest(
                actor=researcher_actor,
                source_kind="dataset",
                status="unresolved",
                title="Regional onboarding dataset",
                rationale="Promising but unavailable before Methodologist handoff.",
            ),
        )
    ).source
    assert local_source is not None
    assert included_web_source is not None
    assert duplicate_source is not None
    assert excluded_source is not None
    assert failed_source is not None
    assert unresolved_source is not None
    await kernel.attach_research_dossier_context_pack(
        dossier.dossier_id,
        AttachResearchDossierContextPackRequest(
            actor=researcher_actor,
            context_pack_id=context_pack.context_pack_id,
            source_id=local_source.source_id,
        ),
    )

    supported_claim = (
        await kernel.upsert_research_dossier_claim(
            dossier.dossier_id,
            UpsertResearchDossierClaimRequest(
                actor=researcher_actor,
                claim_key="claim:onboarding-evidence-gates",
                statement="Team onboarding needs explicit evidence gates before execution.",
                status="supported",
                confidence=0.86,
                source_ids=[local_source.source_id],
                citation_ids=["S1"],
                context_pack_ids=[context_pack.context_pack_id],
            ),
        )
    ).claim
    autonomy_claim = (
        await kernel.upsert_research_dossier_claim(
            dossier.dossier_id,
            UpsertResearchDossierClaimRequest(
                actor=researcher_actor,
                claim_key="claim:approval-depth",
                statement="Approval-heavy onboarding can reduce team autonomy.",
                status="ambiguous",
                confidence=0.62,
                source_ids=[included_web_source.source_id],
                citation_ids=["S2"],
                contradicted_by_claim_ids=[supported_claim.claim_id],
            ),
        )
    ).claim
    concept = (
        await kernel.upsert_research_dossier_concept(
            dossier.dossier_id,
            UpsertResearchDossierConceptRequest(
                actor=researcher_actor,
                slug="evidence-gated-onboarding",
                name="Evidence-gated onboarding",
                aliases=["Karpathy-style onboarding dossier", "concept graph onboarding"],
                definition=(
                    "A navigable concept graph that connects onboarding methods, "
                    "source citations, approval gaps, and contradictions."
                ),
                status="active",
                confidence=0.88,
                source_ids=[local_source.source_id, included_web_source.source_id],
                claim_ids=[supported_claim.claim_id, autonomy_claim.claim_id],
            ),
        )
    ).concept
    concept_note = (
        await kernel.upsert_research_dossier_note(
            dossier.dossier_id,
            UpsertResearchDossierNoteRequest(
                actor=researcher_actor,
                note_kind="concept",
                status="active",
                slug="evidence-gated-onboarding",
                title="Evidence-gated onboarding",
                summary="Central concept connecting retained sources and synthesis claims.",
                body="Use S1 for source-grounded gates and S2 for approval-depth caveats.",
                concept_id=concept.concept_id,
                citation_ids=["S1", "S2"],
            ),
        )
    ).note
    contradiction_note = (
        await kernel.upsert_research_dossier_note(
            dossier.dossier_id,
            UpsertResearchDossierNoteRequest(
                actor=researcher_actor,
                note_kind="contradiction",
                status="active",
                slug="approval-depth-contradiction",
                title="Approval depth contradiction",
                summary="S1 favors explicit gates; S2 warns against heavy approvals.",
                body="Methodologist must preserve the distinction between gates and approvals.",
                related_note_ids=[concept_note.note_id],
                citation_ids=["S1", "S2"],
            ),
        )
    ).note
    gap_note = (
        await kernel.upsert_research_dossier_note(
            dossier.dossier_id,
            UpsertResearchDossierNoteRequest(
                actor=researcher_actor,
                note_kind="gap",
                status="active",
                slug="regional-dataset-gap",
                title="Regional dataset gap",
                summary="Dataset remains unresolved and must be called out before synthesis.",
                body="Synthesis can proceed only if the regional dataset gap is explicit.",
                source_id=unresolved_source.source_id,
            ),
        )
    ).note
    source_note = (
        await kernel.upsert_research_dossier_note(
            dossier.dossier_id,
            UpsertResearchDossierNoteRequest(
                actor=researcher_actor,
                note_kind="source",
                status="active",
                slug="retained-field-guide-source",
                title="Retained field guide source summary",
                summary="S1 source summary.",
                body="Raw evidence is preserved in the retained dossier library.",
                source_id=local_source.source_id,
                citation_ids=["S1"],
            ),
        )
    ).note
    assert contradiction_note is not None
    assert gap_note is not None
    assert source_note is not None
    await kernel.upsert_research_dossier_link(
        dossier.dossier_id,
        UpsertResearchDossierLinkRequest(
            actor=researcher_actor,
            source_type="concept",
            source_ref_id=concept.concept_id,
            target_type="claim",
            target_ref_id=supported_claim.claim_id,
            link_kind="supports",
            rationale="The concept operationalizes the supported claim.",
        ),
    )
    await kernel.upsert_research_dossier_link(
        dossier.dossier_id,
        UpsertResearchDossierLinkRequest(
            actor=researcher_actor,
            source_type="claim",
            source_ref_id=autonomy_claim.claim_id,
            target_type="claim",
            target_ref_id=supported_claim.claim_id,
            link_kind="contradicts",
            rationale="S2 complicates the approval-gate interpretation in S1.",
        ),
    )
    await kernel.upsert_research_dossier_link(
        dossier.dossier_id,
        UpsertResearchDossierLinkRequest(
            actor=researcher_actor,
            source_type="source",
            source_ref_id=local_source.source_id,
            target_type="note",
            target_ref_id=source_note.note_id,
            link_kind="derived_from",
            rationale="The source summary is derived from the retained library item.",
        ),
    )
    warning = await kernel.submit_research_dossier_health_check(
        dossier.dossier_id,
        SubmitResearchDossierHealthCheckRequest(
            actor=researcher_actor,
            status="warning",
            summary="Notebook is useful but still has one explicit unresolved dataset.",
            unresolved_count=1,
            findings=[{"kind": "gap", "note_id": str(gap_note.note_id)}],
        ),
    )
    assert warning.checked_by_system_agent_id == researcher.agent_id
    passed = await kernel.submit_research_dossier_health_check(
        dossier.dossier_id,
        SubmitResearchDossierHealthCheckRequest(
            actor=researcher_actor,
            status="passed",
            summary="Notebook is navigable and unresolved items are explicit.",
            unresolved_count=1,
            findings=[{"kind": "accepted_gap", "note_id": str(gap_note.note_id)}],
        ),
    )
    sync = await kernel.sync_research_dossier_notebook(
        dossier.dossier_id,
        SyncResearchDossierNotebookRequest(
            actor=researcher_actor,
            provider_key="xwiki",
            metadata={"provider": "xwiki", "mode": "compound-test"},
        ),
        stats={"pages_synced": 13, "provider_projection": "mocked"},
    )
    assert sync.system_agent_id == researcher.agent_id

    graph = await kernel.get_research_dossier_graph(
        dossier.dossier_id,
        actor=researcher_actor,
    )
    node_statuses = {
        node["label"]: node["status"]
        for node in graph.nodes
        if node["type"] == "source"
    }
    assert node_statuses == {
        "Retained onboarding field guide": "included",
        "Recent onboarding benchmark": "included",
        "Mirror of onboarding field guide": "duplicate",
        "Consumer onboarding paper": "excluded",
        "Removed onboarding memo": "failed",
        "Regional onboarding dataset": "unresolved",
    }
    assert graph.metadata["knowledge_storage"] is True
    assert graph.metadata["node_count"] >= 16
    assert graph.metadata["link_count"] == 3
    navigation = await kernel.navigate_research_dossier(
        dossier.dossier_id,
        NavigateResearchDossierRequest(
            actor=methodologist_actor,
            query="approval",
            max_results=10,
        ),
    )
    assert any(item.concept_id == concept.concept_id for item in navigation.concepts)
    assert any(item.claim_id == autonomy_claim.claim_id for item in navigation.claims)
    assert any(item.note_id == contradiction_note.note_id for item in navigation.contradictions)
    assert any(item.note_id == gap_note.note_id for item in navigation.gaps)
    focused = await kernel.navigate_research_dossier(
        dossier.dossier_id,
        NavigateResearchDossierRequest(
            actor=methodologist_actor,
            focus_concept_id=concept.concept_id,
        ),
    )
    assert focused.concepts == [concept]
    refreshed_notebook = await kernel.get_research_dossier_notebook_detail(
        dossier.dossier_id,
        actor=methodologist_actor,
    )
    assert refreshed_notebook.latest_health_check is not None
    assert refreshed_notebook.latest_health_check.check_id == passed.check_id
    assert refreshed_notebook.notebook.status == "ready"

    ready = await kernel.mark_research_dossier_ready(
        dossier.dossier_id,
        MarkResearchDossierReadyRequest(
            actor=researcher_actor,
            summary="Research dossier is ready with explicit evidence, contradictions, and gaps.",
            contradictions=[
                {
                    "claims": [
                        "claim:onboarding-evidence-gates",
                        "claim:approval-depth",
                    ],
                    "notes": [str(contradiction_note.note_id)],
                    "source_refs": ["S1", "S2"],
                }
            ],
            gaps=[
                "Regional onboarding dataset remains unresolved; do not overgeneralize."
            ],
            metadata={"latest_health_check_id": str(passed.check_id)},
        ),
    )
    assert ready.status == "ready_for_methodologist"
    methodologist_tasks = await kernel.list_pending_tasks_for_system_agent(
        methodologist.agent_id
    )
    draft_task = next(
        task
        for task in methodologist_tasks
        if task.metadata["task_kind"] == "methodology_blueprint_draft"
        and task.correlation_id == dossier.dossier_id
    )
    assert draft_task.metadata["dossier_summary"] == ready.summary
    assert draft_task.metadata["dossier_gaps"] == ready.gaps
    assert draft_task.metadata["dossier_sources"][0]["citation_id"] == "S1"
    assert {
        item["status"] for item in draft_task.metadata["dossier_sources"]
    } == {"included", "duplicate", "excluded", "failed", "unresolved"}

    harness_draft = WorkspaceHarness(
        summary="Evidence-gated onboarding workspace harness.",
        methodology=WorkspaceMethodology(
            ontology="Concepts, claims, source summaries, contradictions, and gaps.",
            principles=[
                "Treat MinIO/library evidence as source material.",
                "Treat the dossier concept graph as knowledge storage.",
            ],
        ),
        methodics=[
            WorkspaceMethodic(
                name="Evidence-gated onboarding",
                goal="Move a team into execution with cited evidence gates.",
                steps=[
                    WorkspaceMethodicStep(
                        instruction="Read the dossier synthesis, contradictions, and gaps.",
                        expected_artifacts=["cited onboarding brief"],
                        verification=["brief cites S1 and explains the S2 approval caveat"],
                    )
                ],
                success_criteria=["Human reviewer accepts the cited onboarding brief."],
            )
        ],
        execution_rules=[
            HarnessExecutionRule(
                name="No hidden execution",
                instruction="Do not start Conductor execution without explicit human start.",
            )
        ],
        metadata={
            "research_dossier_id": str(dossier.dossier_id),
            "notebook_id": str(refreshed_notebook.notebook.notebook_id),
        },
    )
    submitted = await kernel.submit_methodology_blueprint_draft(
        detail.versions[0].version_id,
        SubmitMethodologyBlueprintDraftRequest(
            actor=methodologist_actor,
            cited_output=(
                "# Evidence-gated onboarding\n\n"
                "Use explicit gates from S1 while preserving the approval-depth caveat from S2."
            ),
            harness_draft=harness_draft,
            metadata={"consumed_via": "navigate+graph"},
        ),
    )
    submitted_version = submitted.versions[0]
    assert submitted_version.status == "pending_review"
    assert submitted_version.submitted_by_system_agent_id == methodologist.agent_id
    assert submitted_version.metadata["consumed_via"] == "navigate+graph"
    assert submitted.dossier.status == "completed"
    with pytest.raises(ValueError, match="Only approved"):
        target_workspace = Workspace(
            workspace_id=uuid4(),
            organization_id=organization.organization_id,
            project_id=uuid4(),
            name="Compound target workspace",
            created_by=actor.participant_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        repository._workspaces[target_workspace.workspace_id] = target_workspace
        repository._participants[(target_workspace.workspace_id, actor.participant_id)] = (
            ParticipantProfile(
                participant_id=actor.participant_id,
                workspace_id=target_workspace.workspace_id,
                participant_type="user",
                user_id=actor.user_id,
                display_name=actor.display_name,
                roles=["admin"],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await kernel.apply_methodology_blueprint(
            detail.blueprint.blueprint_id,
            ApplyMethodologyBlueprintRequest(
                actor=actor,
                workspace_id=target_workspace.workspace_id,
                version_id=submitted_version.version_id,
            ),
        )
    assert repository._methodic_executions == {}


@pytest.mark.asyncio
async def test_methodology_blueprint_draft_review_and_apply_are_human_gated():
    repository, kernel, organization, _operations_workspace, actor = (
        await _seed_methodology_world()
    )
    detail = await _create_methodology_blueprint_fixture(
        repository,
        kernel,
        organization,
        actor,
    )
    dossier = await kernel.mark_research_dossier_ready(
        detail.dossier.dossier_id,
        MarkResearchDossierReadyRequest(
            actor=actor,
            summary="Ready for synthesis.",
        ),
    )
    version = repository._methodology_blueprint_versions[dossier.version_id]

    with pytest.raises(ValueError, match="without a harness draft"):
        await kernel.review_methodology_blueprint_version(
            detail.blueprint.blueprint_id,
            version.version_id,
            ReviewMethodologyBlueprintVersionRequest(actor=actor),
            approved=True,
        )

    methodologist = await repository.fetch_system_agent_by_key(
        scope="global",
        organization_id=None,
        agent_key="methodologist",
    )
    harness_draft = WorkspaceHarness(
        summary="Reusable onboarding methodology.",
        methodology=WorkspaceMethodology(
            ontology="People, work artifacts, and evidence gates.",
            principles=["Cite every source-backed methodic."],
        ),
        methodics=[
            WorkspaceMethodic(
                name="Onboard team",
                goal="Move a team into evidence-backed execution.",
                steps=[
                    WorkspaceMethodicStep(
                        instruction="Collect current operating constraints.",
                        expected_artifacts=["constraint brief"],
                        verification=["brief cites dossier source"],
                    )
                ],
                success_criteria=["Team has an accepted execution brief."],
            )
        ],
        execution_rules=[
            HarnessExecutionRule(
                name="Citation discipline",
                instruction="Cite dossier sources for source-backed claims.",
            )
        ],
        moderation_policy=WorkspaceModerationPolicy(enabled=False, level="open"),
        metadata={"draft": True},
    )
    submitted = await kernel.submit_methodology_blueprint_draft(
        version.version_id,
        SubmitMethodologyBlueprintDraftRequest(
            actor=ParticipantInput(
                participant_id=methodologist.agent_id,
                participant_type="agent",
                display_name="Methodologist",
            ),
            cited_output="# Blueprint\n\nClaim [S1]",
            harness_draft=harness_draft,
        ),
    )
    assert submitted.versions[0].status == "pending_review"
    assert submitted.dossier.status == "completed"

    target_workspace = Workspace(
        workspace_id=uuid4(),
        organization_id=organization.organization_id,
        project_id=uuid4(),
        name="Execution Workspace",
        harness=WorkspaceHarness(
            moderation_policy=WorkspaceModerationPolicy(
                enabled=True,
                level="strict",
                topic="Existing workspace topic",
            )
        ),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repository._workspaces[target_workspace.workspace_id] = target_workspace
    repository._participants[(target_workspace.workspace_id, actor.participant_id)] = (
        ParticipantProfile(
            participant_id=actor.participant_id,
            workspace_id=target_workspace.workspace_id,
            participant_type="user",
            user_id=actor.user_id,
            display_name=actor.display_name,
            roles=["admin"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    with pytest.raises(ValueError, match="Only approved"):
        await kernel.apply_methodology_blueprint(
            detail.blueprint.blueprint_id,
            ApplyMethodologyBlueprintRequest(
                actor=actor,
                workspace_id=target_workspace.workspace_id,
                version_id=version.version_id,
            ),
        )

    approved = await kernel.review_methodology_blueprint_version(
        detail.blueprint.blueprint_id,
        version.version_id,
        ReviewMethodologyBlueprintVersionRequest(
            actor=actor,
            reason="Evidence and draft accepted.",
        ),
        approved=True,
    )
    assert approved.blueprint.status == "active"
    assert approved.blueprint.active_version_id == version.version_id

    applied = await kernel.apply_methodology_blueprint(
        detail.blueprint.blueprint_id,
        ApplyMethodologyBlueprintRequest(
            actor=actor,
            workspace_id=target_workspace.workspace_id,
            version_id=version.version_id,
            metadata={"applied_by_test": True},
        ),
    )
    assert applied.workspace is not None
    assert applied.workspace.harness.summary == "Reusable onboarding methodology."
    assert applied.workspace.harness.moderation_policy.level == "strict"
    assert applied.workspace.harness.moderation_policy.topic == "Existing workspace topic"
    assert applied.workspace.harness.metadata["methodology_blueprint_id"] == str(
        detail.blueprint.blueprint_id
    )
    assert applied.workspace.harness.metadata["applied_by_test"] is True
    assert repository._methodic_executions == {}


def _workspace_actor_with_methodics_permissions() -> ParticipantInput:
    actor_id = uuid4()
    return ParticipantInput(
        participant_id=actor_id,
        participant_type="user",
        user_id=actor_id,
        display_name="Workspace Admin",
        iam_permissions=sorted(WORKSPACE_PERMISSION_NAMES),
    )


def _seed_methodics_workspace(
    repository: FakeRepository,
    actor: ParticipantInput,
) -> Workspace:
    now = datetime.now(timezone.utc)
    workspace = Workspace(
        workspace_id=uuid4(),
        organization_id=UUID("11111111-1111-1111-1111-111111111111"),
        project_id=uuid4(),
        name="Launch Methodics Workspace",
        harness=WorkspaceHarness(
            methodology=WorkspaceMethodology(
                ontology="Delivery artifacts and verification evidence.",
                principles=["Keep each step evidence-backed."],
            ),
            methodics=[
                WorkspaceMethodic(
                    name="Evidence-backed launch",
                    goal="Launch a small workspace workflow",
                    steps=[
                        WorkspaceMethodicStep(
                            instruction="Collect launch requirements.",
                            expected_artifacts=["requirements note"],
                            verification=["requirements are visible in the workspace"],
                        ),
                        WorkspaceMethodicStep(
                            instruction="Verify launch readiness.",
                            expected_artifacts=["readiness report"],
                            verification=["definition of done is satisfied"],
                        ),
                    ],
                    success_criteria=["workflow outcome is explicitly accepted"],
                )
            ],
        ),
        created_by=actor.participant_id,
        created_at=now,
        updated_at=now,
    )
    repository._workspaces[workspace.workspace_id] = workspace
    repository._participants[(workspace.workspace_id, actor.participant_id)] = ParticipantProfile(
        participant_id=actor.participant_id,
        workspace_id=workspace.workspace_id,
        participant_type="user",
        user_id=actor.user_id,
        display_name=actor.display_name,
        roles=["admin"],
        capabilities=[],
        status="active",
        created_at=now,
        updated_at=now,
    )
    return workspace


def _attach_conductor_participant(
    repository: FakeRepository,
    workspace: Workspace,
    *,
    system_agent_id: UUID = CONDUCTOR_AGENT_ID,
) -> ParticipantProfile:
    now = datetime.now(timezone.utc)
    participant = ParticipantProfile(
        participant_id=uuid4(),
        workspace_id=workspace.workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Conductor",
        roles=["workspace methodics execution conductor"],
        capabilities=["coordinates active WorkspaceHarness methodics"],
        status="active",
        metadata={
            "task_routing": {
                "normal_message_fanout": False,
                "accepted_task_kinds": [
                    "methodics_execution_start",
                    "methodics_step_coordinate",
                    "methodics_step_verify",
                    "methodics_resource_review",
                ],
            }
        },
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace.workspace_id, participant.participant_id)] = participant
    return participant


def _conductor_methodics_actor(participant: ParticipantProfile) -> ParticipantInput:
    return ParticipantInput(
        participant_id=participant.participant_id,
        participant_type="agent",
        display_name=participant.display_name,
        iam_permissions=["methodics.execute"],
    )


@pytest.mark.asyncio
async def test_conductor_manual_attachment_preserves_no_normal_fanout_routing():
    repository = FakeRepository()
    await ManagedSystemDefaultsRepairer(repository).repair()
    conductor = next(
        agent for agent in repository._agents.values() if agent.agent_key == "conductor"
    )
    actor = _workspace_actor_with_methodics_permissions()
    workspace = _seed_methodics_workspace(repository, actor)
    kernel = CollaborationKernel(repository)

    result = await kernel.create_agent_participant(
        workspace.workspace_id,
        CreateAgentParticipantRequest(actor=actor, agent_id=conductor.agent_id),
    )

    assert result.participant is not None
    assert result.participant.system_agent_id == CONDUCTOR_AGENT_ID
    assert result.participant.metadata["task_routing"]["normal_message_fanout"] is False
    assert result.participant.metadata["task_routing"]["accepted_task_kinds"] == [
        "methodics_execution_start",
        "methodics_step_coordinate",
        "methodics_step_verify",
        "methodics_resource_review",
    ]
    now = datetime.now(timezone.utc)
    thread_id = uuid4()
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace.workspace_id,
        title="Methodics",
        created_at=now,
        updated_at=now,
    )
    accepted_task = Task(
        task_id=uuid4(),
        workspace_id=workspace.workspace_id,
        thread_id=thread_id,
        title="Coordinate methodics",
        requested_by=actor.participant_id,
        created_at=now,
        updated_at=now,
        metadata={
            "target_system_agent_id": str(conductor.agent_id),
            "target_participant_id": str(result.participant.participant_id),
            "task_kind": "methodics_execution_start",
        },
    )
    rejected_task = accepted_task.model_copy(
        update={
            "task_id": uuid4(),
            "title": "Ordinary targeted work",
            "metadata": {
                "target_system_agent_id": str(conductor.agent_id),
                "target_participant_id": str(result.participant.participant_id),
                "task_kind": "general_reply",
            },
        }
    )
    repository._tasks[accepted_task.task_id] = accepted_task
    repository._tasks[rejected_task.task_id] = rejected_task

    pending = await kernel.list_pending_tasks_for_system_agent(conductor.agent_id)

    assert [task.task_id for task in pending] == [accepted_task.task_id]


@pytest.mark.asyncio
async def test_methodics_execution_start_requires_attached_conductor():
    repository = FakeRepository()
    actor = _workspace_actor_with_methodics_permissions()
    workspace = _seed_methodics_workspace(repository, actor)
    now = datetime.now(timezone.utc)
    ordinary_agent_id = uuid4()
    ordinary_participant = ParticipantProfile(
        participant_id=uuid4(),
        workspace_id=workspace.workspace_id,
        participant_type="agent",
        system_agent_id=ordinary_agent_id,
        display_name="Ordinary Agent",
        roles=["collaborator"],
        capabilities=[],
        status="active",
        metadata={
            "task_routing": {
                "normal_message_fanout": True,
                "accepted_task_kinds": ["general_reply"],
            }
        },
        created_at=now,
        updated_at=now,
    )
    repository._participants[
        (workspace.workspace_id, ordinary_participant.participant_id)
    ] = ordinary_participant
    kernel = CollaborationKernel(repository)

    with pytest.raises(ValueError, match="Conductor must be attached"):
        await kernel.create_methodic_execution(
            workspace.workspace_id,
            CreateMethodicExecutionRequest(actor=actor, target_goal="Launch the workflow"),
        )

    assert repository._methodic_executions == {}
    assert repository._tasks == {}


@pytest.mark.asyncio
async def test_methodics_execution_start_snapshots_methodics_and_targets_execution_agent_by_contract():
    repository = FakeRepository()
    actor = _workspace_actor_with_methodics_permissions()
    workspace = _seed_methodics_workspace(repository, actor)
    now = datetime.now(timezone.utc)
    methodics_agent_id = uuid4()
    conductor_participant = ParticipantProfile(
        participant_id=uuid4(),
        workspace_id=workspace.workspace_id,
        participant_type="agent",
        system_agent_id=methodics_agent_id,
        display_name="Workspace Methodics Agent",
        roles=["methodics coordinator"],
        capabilities=["coordinates active WorkspaceHarness methodics"],
        status="active",
        metadata={
            "task_routing": {
                "normal_message_fanout": False,
                "accepted_task_kinds": ["methodics_execution_start"],
            }
        },
        created_at=now,
        updated_at=now,
    )
    repository._participants[
        (workspace.workspace_id, conductor_participant.participant_id)
    ] = conductor_participant
    kernel = CollaborationKernel(repository)

    result = await kernel.create_methodic_execution(
        workspace.workspace_id,
        CreateMethodicExecutionRequest(actor=actor, target_goal="Launch the workflow"),
    )

    assert result.detail is not None
    detail = result.detail
    assert detail.execution.status == "running"
    assert detail.execution.conductor_system_agent_id == methodics_agent_id
    assert detail.execution.conductor_participant_id == conductor_participant.participant_id
    assert detail.execution.methodics_snapshot[0]["name"] == "Evidence-backed launch"
    assert len(detail.steps) == 2
    assert detail.steps[0].status == "active"
    assert detail.steps[0].definition_of_done == [
        "requirements are visible in the workspace",
        "workflow outcome is explicitly accepted",
    ]
    assert len(detail.assignments) == 1
    assignment = detail.assignments[0]
    assert assignment.assignment_kind == "agent_task"
    assert assignment.assignee_system_agent_id == methodics_agent_id
    task = repository._tasks[assignment.task_id]
    assert task.metadata["target_system_agent_id"] == str(methodics_agent_id)
    assert task.metadata["target_participant_id"] == str(conductor_participant.participant_id)
    assert task.metadata["task_kind"] == "methodics_execution_start"
    assert "methodic_execution.started" in {event.event_type for event in result.events}
    assert "task.created" in {event.event_type for event in result.events}


@pytest.mark.asyncio
async def test_methodics_resource_request_create_is_pending_and_agent_requested():
    repository = FakeRepository()
    actor = _workspace_actor_with_methodics_permissions()
    workspace = _seed_methodics_workspace(repository, actor)
    now = datetime.now(timezone.utc)
    conductor_participant = ParticipantProfile(
        participant_id=uuid4(),
        workspace_id=workspace.workspace_id,
        participant_type="agent",
        system_agent_id=CONDUCTOR_AGENT_ID,
        display_name="Conductor",
        roles=["workspace methodics execution conductor"],
        capabilities=["coordinates active WorkspaceHarness methodics"],
        status="active",
        metadata={
            "task_routing": {
                "normal_message_fanout": False,
                "accepted_task_kinds": ["methodics_execution_start"],
            }
        },
        created_at=now,
        updated_at=now,
    )
    repository._participants[
        (workspace.workspace_id, conductor_participant.participant_id)
    ] = conductor_participant
    kernel = CollaborationKernel(repository)

    start = await kernel.create_methodic_execution(
        workspace.workspace_id,
        CreateMethodicExecutionRequest(actor=actor, target_goal="Launch the workflow"),
    )
    assert start.detail is not None
    resource = await kernel.create_methodic_resource_request(
        workspace.workspace_id,
        start.detail.execution.execution_id,
        CreateMethodicResourceRequestRequest(
            actor=ParticipantInput(
                participant_id=conductor_participant.participant_id,
                participant_type="agent",
                display_name="Conductor",
                iam_permissions=["methodics.execute"],
            ),
            resource_kind="tool",
            action="attach",
            title="Attach evidence checklist tool",
            description="Needed to collect step evidence.",
            required_permission="workspace.tools.write",
            payload={"tool_name": "evidence-checklist"},
        ),
    )

    assert resource.resource_request is not None
    assert resource.resource_request.status == "pending"
    assert resource.resource_request.requested_by_system_agent_id == CONDUCTOR_AGENT_ID
    assert resource.resource_request.step_execution_id == (
        start.detail.execution.current_step_execution_id
    )
    assert "methodic_resource_request.created" in {
        event.event_type for event in resource.events
    }


@pytest.mark.asyncio
async def test_methodics_assignment_dod_rework_progression_and_final_report():
    repository = FakeRepository()
    actor = _workspace_actor_with_methodics_permissions()
    workspace = _seed_methodics_workspace(repository, actor)
    conductor_participant = _attach_conductor_participant(repository, workspace)
    conductor_actor = _conductor_methodics_actor(conductor_participant)
    kernel = CollaborationKernel(repository)

    start = await kernel.create_methodic_execution(
        workspace.workspace_id,
        CreateMethodicExecutionRequest(actor=actor, target_goal="Launch the workflow"),
    )
    assert start.detail is not None
    first_step = start.detail.steps[0]

    assigned = await kernel.create_methodic_assignment(
        workspace.workspace_id,
        start.detail.execution.execution_id,
        CreateMethodicAssignmentRequest(
            actor=conductor_actor,
            step_execution_id=first_step.step_execution_id,
            title="Collect launch requirements",
            instructions="Create a requirements note and attach evidence.",
            assignee_participant_id=actor.participant_id,
            metadata={"source": "unit-test"},
        ),
    )

    assert assigned.detail is not None
    manual_assignment = next(
        assignment
        for assignment in assigned.detail.assignments
        if assignment.assignment_kind == "manual"
    )
    assert manual_assignment.status == "waiting"
    assert manual_assignment.assignee_participant_id == actor.participant_id
    assert assigned.detail.steps[0].assigned_participant_id == actor.participant_id

    rework = await kernel.evaluate_methodic_step(
        workspace.workspace_id,
        start.detail.execution.execution_id,
        EvaluateMethodicStepRequest(
            actor=conductor_actor,
            step_execution_id=first_step.step_execution_id,
            outcome="rework",
            reason="Requirements note is missing acceptance criteria.",
            confidence=0.4,
            evidence_refs=[{"kind": "message", "id": "requirements-draft"}],
            rework_instructions="Add measurable acceptance criteria.",
        ),
    )

    assert rework.detail is not None
    assert rework.detail.execution.status == "running"
    assert rework.detail.execution.current_step_execution_id == first_step.step_execution_id
    assert rework.detail.steps[0].status == "rework"
    assert rework.detail.checks[-1].status == "failed"
    assert rework.detail.checks[-1].metadata["outcome"] == "rework"
    rework_assignment = next(
        assignment
        for assignment in rework.detail.assignments
        if assignment.metadata.get("task_kind") == "methodics_step_coordinate"
        and assignment.step_execution_id == first_step.step_execution_id
    )
    assert repository._tasks[rework_assignment.task_id].metadata["task_kind"] == (
        "methodics_step_coordinate"
    )

    progressed = await kernel.evaluate_methodic_step(
        workspace.workspace_id,
        start.detail.execution.execution_id,
        EvaluateMethodicStepRequest(
            actor=conductor_actor,
            step_execution_id=first_step.step_execution_id,
            outcome="passed",
            reason="Acceptance criteria are now present.",
            confidence=0.92,
            evidence_refs=[{"kind": "artifact", "id": "requirements-note-v2"}],
        ),
    )

    assert progressed.detail is not None
    second_step = progressed.detail.steps[1]
    assert progressed.detail.steps[0].status == "passed"
    assert second_step.status == "active"
    assert progressed.detail.execution.current_step_execution_id == second_step.step_execution_id
    assert any(
        assignment.status == "completed"
        for assignment in progressed.detail.assignments
        if assignment.step_execution_id == first_step.step_execution_id
    )

    second_assigned = await kernel.create_methodic_assignment(
        workspace.workspace_id,
        start.detail.execution.execution_id,
        CreateMethodicAssignmentRequest(
            actor=conductor_actor,
            step_execution_id=second_step.step_execution_id,
            title="Verify launch readiness",
            instructions="Produce readiness evidence for the final DoD check.",
            assignee_participant_id=actor.participant_id,
        ),
    )
    assert second_assigned.detail is not None
    assert second_assigned.detail.steps[1].assigned_participant_id == actor.participant_id

    final = await kernel.evaluate_methodic_step(
        workspace.workspace_id,
        start.detail.execution.execution_id,
        EvaluateMethodicStepRequest(
            actor=conductor_actor,
            step_execution_id=second_step.step_execution_id,
            outcome="passed",
            reason="Readiness evidence satisfies the definition of done.",
            confidence=0.95,
            evidence_refs=[{"kind": "artifact", "id": "readiness-report"}],
            final_report="Final execution report: launch workflow completed with cited evidence.",
        ),
    )

    assert final.detail is not None
    assert final.detail.execution.status == "completed"
    assert final.detail.execution.current_step_execution_id is None
    assert final.detail.execution.metadata["final_report"].startswith("Final execution report")
    assert [step.status for step in final.detail.steps] == ["passed", "passed"]
    assert [check.metadata["outcome"] for check in final.detail.checks] == [
        "rework",
        "passed",
        "passed",
    ]
    final_messages = [
        message
        for messages in repository._messages.values()
        for message in messages
        if message.metadata.get("methodics_final_report")
    ]
    assert len(final_messages) == 1
    assert "launch workflow completed" in final_messages[0].content


@pytest.mark.asyncio
async def test_methodics_dod_failure_and_active_step_cancellation_are_terminal():
    repository = FakeRepository()
    actor = _workspace_actor_with_methodics_permissions()
    workspace = _seed_methodics_workspace(repository, actor)
    conductor_participant = _attach_conductor_participant(repository, workspace)
    conductor_actor = _conductor_methodics_actor(conductor_participant)
    kernel = CollaborationKernel(repository)

    failing_start = await kernel.create_methodic_execution(
        workspace.workspace_id,
        CreateMethodicExecutionRequest(actor=actor, target_goal="Fail the workflow"),
    )
    assert failing_start.detail is not None
    failing_step = failing_start.detail.steps[0]

    failed = await kernel.evaluate_methodic_step(
        workspace.workspace_id,
        failing_start.detail.execution.execution_id,
        EvaluateMethodicStepRequest(
            actor=conductor_actor,
            step_execution_id=failing_step.step_execution_id,
            outcome="failed",
            reason="Definition of done cannot be satisfied.",
            evidence_refs=[{"kind": "artifact", "id": "failed-evidence"}],
        ),
    )

    assert failed.detail is not None
    assert failed.detail.execution.status == "failed"
    assert failed.detail.execution.current_step_execution_id is None
    assert failed.detail.steps[0].status == "failed"
    assert failed.detail.checks[-1].metadata["outcome"] == "failed"
    assert all(
        assignment.status == "failed"
        for assignment in failed.detail.assignments
        if assignment.step_execution_id == failing_step.step_execution_id
    )

    cancellable_start = await kernel.create_methodic_execution(
        workspace.workspace_id,
        CreateMethodicExecutionRequest(actor=actor, target_goal="Cancel active workflow"),
    )
    assert cancellable_start.detail is not None
    assert cancellable_start.detail.execution.status == "running"
    assert cancellable_start.detail.steps[0].status == "active"

    cancelled = await kernel.cancel_methodic_execution(
        workspace.workspace_id,
        cancellable_start.detail.execution.execution_id,
        CancelMethodicExecutionRequest(
            actor=actor,
            reason="Human owner stopped the workflow during the active step.",
        ),
    )

    assert cancelled.detail is not None
    assert cancelled.detail.execution.status == "cancelled"
    assert cancelled.detail.execution.cancelled_at is not None
    assert cancelled.detail.execution.current_step_execution_id is None
    assert cancelled.detail.execution.error.startswith("Human owner")


def test_kernel_run_output_includes_standardized_usage_payload():
    payload = CollaborationKernel._run_output_from_result(  # noqa: SLF001
        AgentRunResult(
            stop_reason="completed",
            message="Done",
            metadata={
                "usage": {
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "prompt_tokens": 21,
                    "completion_tokens": 9,
                    "total_tokens": 30,
                }
            },
        )
    )

    assert payload["usage"] == {
        "provider": "openai",
        "model": "gpt-5.4-mini",
        "prompt_tokens": 21,
        "completion_tokens": 9,
        "total_tokens": 30,
    }


@pytest.mark.asyncio
async def test_kernel_enforce_run_step_token_budget_uses_workspace_metadata_override():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    workspace_id = uuid4()
    step = RunStep(
        step_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        workspace_id=workspace_id,
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        status="claimed",
        claimed_by_worker="agent-loop-worker",
    )
    repository._run_steps[step.step_id] = step
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Budgeted",
        metadata={"limits": {"daily_token_cap": 10}},
    )
    repository._global_token_total = 5
    repository._workspace_token_totals[workspace_id] = 10
    budget_failure = object()
    kernel.fail_run_step = AsyncMock(return_value=budget_failure)  # type: ignore[method-assign]

    result = await kernel.enforce_run_step_token_budget(
        step_id=step.step_id,
        worker_id="agent-loop-worker",
        global_daily_token_cap=100,
        default_workspace_daily_token_cap=50,
    )

    assert result is budget_failure
    kernel.fail_run_step.assert_awaited_once()  # type: ignore[attr-defined]
    args = kernel.fail_run_step.await_args.args  # type: ignore[attr-defined]
    kwargs = kernel.fail_run_step.await_args.kwargs  # type: ignore[attr-defined]
    assert args[:2] == (step.step_id, "agent-loop-worker")
    assert "Workspace daily token cap exceeded (10/10)" in args[2]
    assert kwargs == {"stop_reason": "budget_exhausted"}


@pytest.mark.asyncio
async def test_kernel_requeue_expired_run_step_applies_retry_backoff():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    step = RunStep(
        step_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        status="claimed",
        claimed_by_worker="agent-loop-worker",
        lease_expires_at=now,
        last_heartbeat_at=now,
        attempt_count=2,
    )

    requeued = await kernel._requeue_expired_run_step(step, now=now)  # noqa: SLF001

    assert requeued.status == "created"
    assert requeued.claimed_by_worker is None
    assert requeued.lease_expires_at is None
    assert requeued.last_heartbeat_at is None
    assert requeued.next_retry_at == now + timedelta(seconds=120)
    assert requeued.error == "Run step lease expired; retry 3 scheduled"
    assert await repository.fetch_run_step(step.step_id) == requeued


@pytest.mark.asyncio
async def test_kernel_fail_expired_tool_call_fails_waiting_step_and_run():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    step_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    tool_call_id = uuid4()
    correlation_id = uuid4()
    error = "Tool call lease expired after 3 attempts"

    task = Task(
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Reconcile execution",
        description="Validate expired tool-call handling.",
        requested_by=uuid4(),
        status="claimed",
        claimed_by=participant_id,
        correlation_id=correlation_id,
        metadata={
            "target_system_agent_id": str(system_agent_id),
            "target_participant_id": str(participant_id),
            "response_visibility": "workspace",
        },
        created_at=now,
        updated_at=now,
    )
    run = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        task_id=task_id,
        participant_id=participant_id,
        status="started",
        correlation_id=correlation_id,
        causation_id=task_id,
        created_at=now,
        updated_at=now,
    )
    step = RunStep(
        step_id=step_id,
        run_id=run_id,
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        system_agent_id=system_agent_id,
        status="waiting_tools",
        created_at=now,
        updated_at=now,
    )
    tool_call = ToolCall(
        tool_call_id=tool_call_id,
        run_id=run_id,
        run_step_id=step_id,
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        system_agent_id=system_agent_id,
        tool_id=uuid4(),
        tool_name="repo_search",
        status="claimed",
        execution_spec=ExecutionSpec(
            invocation_id=uuid4(),
            handler_ref="repo_search",
        ).model_dump(mode="json"),
        claimed_by_worker="tool-worker",
        attempt_count=3,
        lease_expires_at=now,
        last_heartbeat_at=now,
        created_at=now,
        updated_at=now,
    )
    repository._tasks[task_id] = task
    repository._runs[run_id] = run
    repository._run_steps[step_id] = step
    repository._tool_calls[run_id] = [tool_call]

    participant = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Testing Agent",
        roles=["testing agent"],
        created_at=now,
        updated_at=now,
    )
    failure_event = EventEnvelope(
        event_type="run.failed",
        workspace_id=workspace_id,
        thread_id=thread_id,
        actor=ActorRef(type="agent", id=participant_id),
        target=TargetRef(type="run", id=run_id),
        visibility="agents_only",
    )
    tool_event = EventEnvelope(
        event_type="tool_call.failed",
        workspace_id=workspace_id,
        thread_id=thread_id,
        actor=ActorRef(type="agent", id=participant_id),
        target=TargetRef(type="tool_call", id=tool_call_id),
        visibility="agents_only",
    )
    kernel._require_run_participant = AsyncMock(return_value=participant)  # type: ignore[method-assign]
    kernel._build_thread_event = AsyncMock(return_value=tool_event)  # type: ignore[method-assign]
    kernel.fail_run = AsyncMock(return_value=type("Failure", (), {"events": [failure_event]})())  # type: ignore[method-assign]

    result = await kernel._fail_expired_tool_call(tool_call, error=error)  # noqa: SLF001

    updated_step = await repository.fetch_run_step(step_id)
    updated_tool_call = await repository.fetch_tool_call(tool_call_id)
    assert updated_step is not None
    assert updated_step.status == "failed"
    assert updated_step.error == error
    assert updated_tool_call is not None
    assert updated_tool_call.status == "failed"
    assert updated_tool_call.error == error
    assert updated_tool_call.result is not None
    assert updated_tool_call.result.error == error
    assert updated_tool_call.next_retry_at is None
    kernel.fail_run.assert_awaited_once_with(  # type: ignore[attr-defined]
        run_id,
        system_agent_id,
        error,
        stop_reason="tool_failure",
    )
    assert result.events == [tool_event, failure_event]


@pytest.mark.asyncio
async def test_kernel_reconcile_expired_execution_leases_routes_requeues_and_terminal_failures():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    kernel._now = lambda: now  # type: ignore[method-assign]
    requeue_step = RunStep(
        step_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        status="claimed",
        attempt_count=1,
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    fail_step = RunStep(
        step_id=uuid4(),
        run_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        status="claimed",
        attempt_count=3,
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    requeue_tool = ToolCall(
        tool_call_id=uuid4(),
        run_id=uuid4(),
        run_step_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        tool_id=uuid4(),
        tool_name="repo_search",
        status="claimed",
        execution_spec=ExecutionSpec(invocation_id=uuid4(), handler_ref="repo_search").model_dump(mode="json"),
        attempt_count=1,
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    fail_tool = ToolCall(
        tool_call_id=uuid4(),
        run_id=uuid4(),
        run_step_id=uuid4(),
        task_id=uuid4(),
        workspace_id=uuid4(),
        thread_id=uuid4(),
        system_agent_id=uuid4(),
        tool_id=uuid4(),
        tool_name="repo_search",
        status="claimed",
        execution_spec=ExecutionSpec(invocation_id=uuid4(), handler_ref="repo_search").model_dump(mode="json"),
        attempt_count=3,
        lease_expires_at=now,
        created_at=now,
        updated_at=now,
    )
    repository._run_steps[requeue_step.step_id] = requeue_step
    repository._run_steps[fail_step.step_id] = fail_step
    repository._tool_calls[requeue_tool.run_id] = [requeue_tool]
    repository._tool_calls[fail_tool.run_id] = [fail_tool]

    expected_step = requeue_step.model_copy(update={"status": "created"})
    expected_tool = requeue_tool.model_copy(update={"status": "created"})
    step_failure_event = EventEnvelope(
        event_type="run.failed",
        workspace_id=fail_step.workspace_id,
        thread_id=fail_step.thread_id,
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="run", id=fail_step.run_id),
        visibility="agents_only",
    )
    tool_failure_event = EventEnvelope(
        event_type="tool_call.failed",
        workspace_id=fail_tool.workspace_id,
        thread_id=fail_tool.thread_id,
        actor=ActorRef(type="agent", id=uuid4()),
        target=TargetRef(type="tool_call", id=fail_tool.tool_call_id),
        visibility="agents_only",
    )
    kernel._requeue_expired_run_step = AsyncMock(return_value=expected_step)  # type: ignore[method-assign]
    kernel._fail_expired_run_step = AsyncMock(  # type: ignore[method-assign]
        return_value=type("Failure", (), {"events": [step_failure_event]})()
    )
    kernel._requeue_expired_tool_call = AsyncMock(return_value=expected_tool)  # type: ignore[method-assign]
    kernel._fail_expired_tool_call = AsyncMock(  # type: ignore[method-assign]
        return_value=type("Failure", (), {"events": [tool_failure_event]})()
    )

    result = await kernel.reconcile_expired_execution_leases()

    assert result.run_steps == [expected_step]
    assert result.tool_calls == [expected_tool]
    assert result.events == [step_failure_event, tool_failure_event]
    kernel._requeue_expired_run_step.assert_awaited_once_with(requeue_step, now=now)  # type: ignore[attr-defined]
    kernel._fail_expired_run_step.assert_awaited_once()  # type: ignore[attr-defined]
    kernel._requeue_expired_tool_call.assert_awaited_once_with(requeue_tool, now=now)  # type: ignore[attr-defined]
    kernel._fail_expired_tool_call.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_build_agent_execution_context_filters_messages_and_memory_by_viewer_and_sequence():
    actor_id = uuid4()
    workspace_id = uuid4()
    thread_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    trigger_message_id = uuid4()
    now = datetime.now(timezone.utc)

    agent = AgentDefinition(
        agent_id=system_agent_id,
        display_name="Testing Agent",
        description="Validates changes with only the allowed workspace context.",
        role="testing agent",
        capabilities=["tests", "validation"],
        endpoint=AgentEndpoint(kind="local", model=TEST_EXPLICIT_OLLAMA_MODEL),
        system_prompt="You are a careful testing agent.",
        interaction_contract=build_default_interaction_contract(
            display_name="Testing Agent",
            role="testing agent",
            description="Validates changes with only the allowed workspace context.",
            capabilities=["tests", "validation"],
        ),
        created_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    repository = FakeRepository([agent])
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Kernel",
        description="Collaboration kernel",
        created_at=now,
        updated_at=now,
        metadata={
            "role_definitions": [
                {
                    "name": "testing agent",
                    "definition": "Validates changes and reports regressions.",
                    "updated_by": str(actor_id),
                    "updated_at": now.isoformat(),
                }
            ],
        },
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Visibility",
        created_at=now,
        updated_at=now,
    )
    agent_participant = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Testing Agent",
        description="Validates changes with only the allowed workspace context.",
        roles=["testing agent"],
        capabilities=["tests", "validation"],
        status="active",
        visibility_scope="workspace",
        created_at=now,
        updated_at=now,
    )
    user_participant = ParticipantProfile(
        participant_id=actor_id,
        workspace_id=workspace_id,
        participant_type="user",
        display_name="Nikolay",
        description="Coordinates the rollout.",
        roles=["release lead"],
        capabilities=["planning"],
        status="active",
        visibility_scope="workspace",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, participant_id)] = agent_participant
    repository._participants[(workspace_id, actor_id)] = user_participant
    tool_id = uuid4()
    repository._system_tools[tool_id] = SystemToolDefinition(
        tool_id=tool_id,
        name="repo_search",
        description="Search the current workspace source tree.",
        parameter_contract={
            "parameters": [
                {
                    "name": "query",
                    "type": "string",
                    "description": "Search text to look up in the repository.",
                    "required": True,
                }
            ],
            "additional_properties": False,
        },
        input_schema={"type": "object"},
        created_by=actor_id,
        created_at=now,
        updated_by=actor_id,
        updated_at=now,
    )
    repository._workspace_tools[workspace_id] = [
        WorkspaceTool(
            tool_id=tool_id,
            name="repo_search",
            description="Search the current workspace source tree.",
            parameter_contract={
                "parameters": [
                    {
                        "name": "query",
                        "type": "string",
                        "description": "Search text to look up in the repository.",
                        "required": True,
                    }
                ],
                "additional_properties": False,
            },
            input_schema={"type": "object"},
            enabled=True,
            attached_by=actor_id,
            attached_at=now,
            updated_at=now,
        )
    ]
    repository._tasks[task_id] = Task(
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Validate rollout",
        description="Review the visible rollout context.",
        requested_by=actor_id,
        correlation_id=uuid4(),
        causation_id=trigger_message_id,
        created_at=now,
        updated_at=now,
        metadata={
            "target_system_agent_id": str(system_agent_id),
            "target_participant_id": str(participant_id),
            "trigger_message_id": str(trigger_message_id),
            "sequence_ceiling": 3,
            "response_visibility": "workspace",
            "routing_reason": "workspace_attached_agent",
        },
    )
    repository._runs[run_id] = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        task_id=task_id,
        participant_id=participant_id,
        status="started",
        correlation_id=repository._tasks[task_id].correlation_id,
        causation_id=task_id,
        created_at=now,
        updated_at=now,
    )
    repository._tool_calls[run_id] = [
        ToolCall(
            tool_call_id=uuid4(),
            run_id=run_id,
            run_step_id=uuid4(),
            task_id=task_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            system_agent_id=system_agent_id,
            tool_id=tool_id,
            tool_name="repo_search",
            status="completed",
            arguments={"query": "migrations"},
            execution_spec=ExecutionSpec(
                invocation_id=uuid4(),
                handler_ref="repo_search",
                inline_payload={"query": "migrations"},
            ).model_dump(mode="json"),
            result=ToolCallResult(
                output_payload={"matches": ["db/migrations/20260411000100_initial_schema.sql"]},
                stdout_ref=ArtifactRef(
                    name="stdout",
                    uri="/tmp/stdout.txt",
                    content_type="text/plain",
                ),
            ),
            created_at=now,
            updated_at=now,
        )
    ]
    repository._memory_entries[workspace_id] = [
        MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            entry_type="note",
            content="Visible to the whole workspace.",
            summary="Workspace note",
            created_by=actor_id,
            updated_by=actor_id,
            visibility="workspace",
            created_at=now,
            updated_at=now,
        ),
        MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            entry_type="note",
            content="Visible to agents.",
            summary="Agents note",
            created_by=actor_id,
            updated_by=actor_id,
            visibility="agents_only",
            created_at=now,
            updated_at=now,
        ),
        MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            entry_type="note",
            content="Should not leak to the agent.",
            summary="User private note",
            created_by=actor_id,
            updated_by=actor_id,
            visibility="private",
            created_at=now,
            updated_at=now,
        ),
    ]
    repository._messages[thread_id] = [
        TimelineMessage(
            message_id=uuid4(),
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=actor_id),
            visibility="workspace",
            content="Visible workspace request",
            sequence=1,
            correlation_id=uuid4(),
            created_at=now,
            updated_at=now,
        ),
        TimelineMessage(
            message_id=uuid4(),
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=actor_id),
            visibility="agents_only",
            content="Visible agent coordination note",
            sequence=2,
            correlation_id=uuid4(),
            created_at=now,
            updated_at=now,
        ),
        TimelineMessage(
            message_id=trigger_message_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=actor_id),
            visibility="workspace",
            content="Validate the rollout carefully",
            sequence=3,
            correlation_id=repository._tasks[task_id].correlation_id,
            created_at=now,
            updated_at=now,
        ),
        TimelineMessage(
            message_id=uuid4(),
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=actor_id),
            visibility="workspace",
            content="Too late for this run",
            sequence=4,
            correlation_id=uuid4(),
            created_at=now,
            updated_at=now,
        ),
        TimelineMessage(
            message_id=uuid4(),
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=actor_id),
            visibility="private",
            content="Private user note",
            sequence=2,
            correlation_id=uuid4(),
            created_at=now,
            updated_at=now,
        ),
    ]

    kernel = CollaborationKernel(repository)
    context = await kernel.build_agent_execution_context(task_id, system_agent_id, run_id)

    assert context.sequence_ceiling == 3
    assert [message.content for message in context.messages] == [
        "Visible workspace request",
        "Visible agent coordination note",
        "Validate the rollout carefully",
    ]
    assert [entry.summary for entry in context.workspace_memory] == [
        "Workspace note",
        "Agents note",
    ]
    assert context.run_memory == []
    assert context.thread_memory == []
    assert context.trigger_message is not None
    assert context.trigger_message.content == "Validate the rollout carefully"
    assert context.thread_reply_contract == agent.interaction_contract
    assert context.role_definitions[0].name == "testing agent"
    assert context.workspace_tools[0].name == "repo_search"
    assert context.workspace_tools[0].parameter_contract.parameters[0].name == "query"
    assert "tool:repo_search" in context.participant.capabilities
    assert "tool:repo_search" in context.participants[0].capabilities
    assert context.tool_results[0].result is not None
    assert context.tool_results[0].result.output_payload["matches"][0].endswith("initial_schema.sql")


@pytest.mark.asyncio
async def test_build_agent_execution_context_applies_harness_memory_policy():
    actor_id = uuid4()
    workspace_id = uuid4()
    thread_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    trigger_message_id = uuid4()
    now = datetime.now(timezone.utc)

    agent = AgentDefinition(
        agent_id=system_agent_id,
        display_name="Harnessed Agent",
        description="Uses harness state during execution.",
        role="testing agent",
        capabilities=["tests", "validation"],
        endpoint=AgentEndpoint(kind="local", model=TEST_EXPLICIT_OLLAMA_MODEL),
        system_prompt="Validate carefully.",
        harness=AgentHarness(
            summary="Ground work in evidence.",
            memory_policy=AgentMemoryPolicy(
                use_run_memory=False,
                use_thread_memory=False,
                use_workspace_memory=True,
            ),
        ),
        interaction_contract=build_default_interaction_contract(
            display_name="Harnessed Agent",
            role="testing agent",
            description="Uses harness state during execution.",
            capabilities=["tests", "validation"],
        ),
        created_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    repository = FakeRepository([agent])
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Kernel",
        description="Harnessed workspace",
        harness=WorkspaceHarness(
            summary="Prefer explicit validation artifacts.",
            methodology=WorkspaceMethodology(
                ontology="Artifacts and tests are primary evidence.",
            ),
            methodics=[
                WorkspaceMethodic(
                    name="Validate changes",
                    goal="Check behavior incrementally.",
                    steps=[
                        WorkspaceMethodicStep(
                            instruction="Read visible context before changing anything.",
                            recommended_tool_patterns=["repo_search"],
                            verification=["Confirm current state first."],
                        )
                    ],
                )
            ],
            execution_rules=[
                HarnessExecutionRule(
                    name="evidence-first",
                    instruction="Prefer direct verification over assumption.",
                    priority="critical",
                    scope="validation",
                )
            ],
        ),
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Visibility",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Harnessed Agent",
        description="Uses harness state during execution.",
        roles=["testing agent"],
        capabilities=["tests", "validation"],
        status="active",
        visibility_scope="workspace",
        created_at=now,
        updated_at=now,
    )
    repository._tasks[task_id] = Task(
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Run harnessed validation",
        requested_by=actor_id,
        correlation_id=uuid4(),
        created_at=now,
        updated_at=now,
        metadata={
            "target_system_agent_id": str(system_agent_id),
            "target_participant_id": str(participant_id),
            "trigger_message_id": str(trigger_message_id),
            "sequence_ceiling": 1,
            "response_visibility": "workspace",
        },
    )
    repository._runs[run_id] = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        task_id=task_id,
        participant_id=participant_id,
        status="started",
        correlation_id=repository._tasks[task_id].correlation_id,
        causation_id=task_id,
        created_at=now,
        updated_at=now,
    )
    repository._messages[thread_id] = [
        TimelineMessage(
            message_id=trigger_message_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type="user", id=actor_id),
            visibility="workspace",
            content="Validate the rollout carefully",
            sequence=1,
            correlation_id=repository._tasks[task_id].correlation_id,
            created_at=now,
            updated_at=now,
        )
    ]
    repository._memory_entries[run_id] = [
        MemoryEntry(
            memory_entry_id=uuid4(),
            scope="run",
            state="scratch",
            workspace_id=workspace_id,
            thread_id=thread_id,
            run_id=run_id,
            entry_type="note",
            content="Ephemeral scratchpad",
            summary="Run scratch",
            created_by=actor_id,
            updated_by=actor_id,
            visibility="workspace",
            created_at=now,
            updated_at=now,
        )
    ]
    repository._memory_entries[thread_id] = [
        MemoryEntry(
            memory_entry_id=uuid4(),
            scope="thread",
            state="confirmed",
            workspace_id=workspace_id,
            thread_id=thread_id,
            entry_type="note",
            content="Thread note",
            summary="Thread memory",
            created_by=actor_id,
            updated_by=actor_id,
            visibility="workspace",
            created_at=now,
            updated_at=now,
        )
    ]
    repository._memory_entries[workspace_id] = [
        MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            entry_type="note",
            content="Workspace note",
            summary="Workspace memory",
            created_by=actor_id,
            updated_by=actor_id,
            visibility="workspace",
            created_at=now,
            updated_at=now,
        )
    ]

    kernel = CollaborationKernel(repository)
    context = await kernel.build_agent_execution_context(task_id, system_agent_id, run_id)

    assert context.workspace_harness == repository._workspaces[workspace_id].harness
    assert context.agent_harness == agent.harness
    assert context.run_memory == []
    assert context.thread_memory == []
    assert [entry.summary for entry in context.workspace_memory] == ["Workspace memory"]


@pytest.mark.asyncio
async def test_build_agent_execution_context_does_not_advertise_disabled_workspace_tools():
    actor_id = uuid4()
    workspace_id = uuid4()
    thread_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    now = datetime.now(timezone.utc)

    agent = AgentDefinition(
        agent_id=system_agent_id,
        display_name="Testing Agent",
        description="Validates changes with only the allowed workspace context.",
        role="testing agent",
        capabilities=["tests", "validation"],
        endpoint=AgentEndpoint(kind="local", model=TEST_EXPLICIT_OLLAMA_MODEL),
        system_prompt="You are a careful testing agent.",
        interaction_contract=build_default_interaction_contract(
            display_name="Testing Agent",
            role="testing agent",
            description="Validates changes with only the allowed workspace context.",
            capabilities=["tests", "validation"],
        ),
        created_by=actor_id,
        created_at=now,
        updated_at=now,
    )
    repository = FakeRepository([agent])
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Kernel",
        description="Collaboration kernel",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Visibility",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Testing Agent",
        description="Validates changes with only the allowed workspace context.",
        roles=["testing agent"],
        capabilities=["tests", "validation"],
        status="active",
        visibility_scope="workspace",
        created_at=now,
        updated_at=now,
    )
    repository._tasks[task_id] = Task(
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Validate rollout",
        requested_by=actor_id,
        correlation_id=uuid4(),
        created_at=now,
        updated_at=now,
        metadata={"target_system_agent_id": str(system_agent_id)},
    )
    repository._runs[run_id] = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        task_id=task_id,
        participant_id=participant_id,
        status="started",
        correlation_id=repository._tasks[task_id].correlation_id,
        causation_id=task_id,
        created_at=now,
        updated_at=now,
    )
    repository._workspace_tools[workspace_id] = [
        WorkspaceTool(
            tool_id=uuid4(),
            name="repo_search",
            description="Search the current workspace source tree.",
            parameter_contract={
                "parameters": [
                    {
                        "name": "query",
                        "type": "string",
                        "description": "Search text to look up in the repository.",
                        "required": True,
                    }
                ],
                "additional_properties": False,
            },
            input_schema={"type": "object"},
            enabled=False,
            attached_by=actor_id,
            attached_at=now,
            updated_at=now,
        )
    ]

    kernel = CollaborationKernel(repository)
    context = await kernel.build_agent_execution_context(task_id, system_agent_id, run_id)

    assert context.workspace_tools[0].enabled is False
    assert "tool:repo_search" not in context.participant.capabilities


@pytest.mark.asyncio
async def test_build_requeued_execution_events_emits_run_step_and_tool_call_wakeups():
    actor_id = uuid4()
    workspace_id = uuid4()
    thread_id = uuid4()
    system_agent_id = uuid4()
    participant_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    now = datetime.now(timezone.utc)

    repository = FakeRepository()
    repository._tasks[task_id] = Task(
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        title="Run worker",
        requested_by=actor_id,
        correlation_id=uuid4(),
        created_at=now,
        updated_at=now,
        metadata={"target_system_agent_id": str(system_agent_id)},
    )
    repository._runs[run_id] = Run(
        run_id=run_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        task_id=task_id,
        participant_id=participant_id,
        status="started",
        correlation_id=repository._tasks[task_id].correlation_id,
        causation_id=task_id,
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Testing Agent",
        roles=["testing agent"],
        capabilities=["tests"],
        created_at=now,
        updated_at=now,
    )
    kernel = CollaborationKernel(repository)
    run_step = RunStep(
        step_id=uuid4(),
        run_id=run_id,
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        system_agent_id=system_agent_id,
        step_index=1,
        status="created",
        created_at=now,
        updated_at=now,
    )
    tool_call = ToolCall(
        tool_call_id=uuid4(),
        run_id=run_id,
        run_step_id=run_step.step_id,
        task_id=task_id,
        workspace_id=workspace_id,
        thread_id=thread_id,
        system_agent_id=system_agent_id,
        tool_id=uuid4(),
        tool_name="repo_search",
        status="created",
        created_at=now,
        updated_at=now,
    )

    events = await kernel.build_requeued_execution_events([run_step], [tool_call])

    assert [event.event_type for event in events] == [
        "run_step.requeued",
        "tool_call.requeued",
    ]
    assert all(event.visibility == "agents_only" for event in events)
    assert all(event.correlation_id == repository._runs[run_id].correlation_id for event in events)
    assert events[0].target.type == "run_step"
    assert events[1].target.type == "tool_call"


@pytest.mark.asyncio
async def test_kernel_create_interaction_request_resolves_capability_targets_and_renders_message():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    requester_id = uuid4()
    user_one_id = uuid4()
    user_two_id = uuid4()
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Questions",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Coordination",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, requester_id)] = ParticipantProfile(
        participant_id=requester_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=uuid4(),
        display_name="Research Agent",
        roles=["research"],
        capabilities=["analysis"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, user_one_id)] = ParticipantProfile(
        participant_id=user_one_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=uuid4(),
        display_name="Alice",
        roles=["reviewer"],
        capabilities=["frontend"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, user_two_id)] = ParticipantProfile(
        participant_id=user_two_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=uuid4(),
        display_name="Bob",
        roles=["reviewer"],
        capabilities=["backend"],
        status="active",
        created_at=now,
        updated_at=now,
    )

    result = await kernel.create_interaction_requests(
        thread_id,
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=requester_id,
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need implementation feedback",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="What blocks backend delivery?"),
                    ],
                    selectors=[{"type": "capability", "value": "backend"}],
                    completion_rule=CompletionRule(mode="all_targets"),
                )
            ],
        ),
    )

    assert len(result.details) == 1
    detail = result.details[0]
    assert detail.targets[0].participant_id == user_two_id
    assert result.messages[0].metadata["interaction_request_id"] == str(detail.request.request_id)
    assert "What blocks backend delivery?" in result.messages[0].content


def _seed_interaction_workspace(
    repository: FakeRepository,
    *,
    users: list[tuple[str, str]],
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    requester_id = uuid4()
    requester_system_agent_id = uuid4()
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Questions",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Coordination",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, requester_id)] = ParticipantProfile(
        participant_id=requester_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=requester_system_agent_id,
        display_name="Research Agent",
        roles=["research"],
        capabilities=["analysis"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    user_ids: dict[str, UUID] = {}
    for display_name, capability in users:
        participant_id = uuid4()
        repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
            participant_id=participant_id,
            workspace_id=workspace_id,
            participant_type="user",
            user_id=uuid4(),
            display_name=display_name,
            roles=["reviewer"],
            capabilities=[capability],
            status="active",
            created_at=now,
            updated_at=now,
        )
        user_ids[display_name] = participant_id
    return {
        "workspace_id": workspace_id,
        "thread_id": thread_id,
        "requester_id": requester_id,
        "requester_system_agent_id": requester_system_agent_id,
        "users": user_ids,
    }


def _seed_tinker_workspace(repository: FakeRepository) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    organization_id = uuid4()
    workspace_id = uuid4()
    thread_id = uuid4()
    user_id = uuid4()
    tinker_agent_id = uuid4()
    tinker_participant_id = uuid4()
    repository._agents[tinker_agent_id] = AgentDefinition(
        agent_id=tinker_agent_id,
        display_name="Tinker",
        description="Generates tools on demand.",
        role="generated tool authoring and validation agent",
        capabilities=["generates new agent-usable tools from workspace requests"],
        endpoint=AgentEndpoint(kind="local", model=TEST_EXPLICIT_OLLAMA_MODEL),
        system_prompt="Build tools carefully.",
        created_by=user_id,
        created_at=now,
        updated_at=now,
        metadata={"tool_generation_agent": True},
    )
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        organization_id=organization_id,
        name="Tooling",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Tool Request",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, user_id)] = ParticipantProfile(
        participant_id=user_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=uuid4(),
        display_name="Nikolay",
        roles=["admin"],
        capabilities=["planning"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, tinker_participant_id)] = ParticipantProfile(
        participant_id=tinker_participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=tinker_agent_id,
        display_name="Tinker",
        roles=["generated tool authoring and validation agent"],
        capabilities=["generates new agent-usable tools from workspace requests"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    return {
        "organization_id": organization_id,
        "workspace_id": workspace_id,
        "thread_id": thread_id,
        "user_id": user_id,
        "tinker_agent_id": tinker_agent_id,
        "tinker_participant_id": tinker_participant_id,
        "now": now,
    }


async def _claim_single_pending_task(
    kernel: CollaborationKernel,
    system_agent_id,
):
    tasks = await kernel.list_pending_tasks_for_system_agent(system_agent_id)
    assert len(tasks) == 1
    return await kernel.claim_task_for_system_agent(tasks[0].task_id, system_agent_id)


@pytest.mark.asyncio
async def test_answer_interaction_request_minimum_answers_waits_for_quorum():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[
            ("Alice", "frontend"),
            ("Bob", "backend"),
            ("Carol", "qa"),
        ],
    )

    create_result = await kernel.create_interaction_requests(
        seeded["thread_id"],
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need two viewpoints",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="What is your blocker?"),
                    ],
                    target_participant_ids=list(seeded["users"].values()),
                    completion_rule=CompletionRule(mode="minimum_answers", minimum_answers=2),
                )
            ],
        ),
    )
    request_id = create_result.details[0].request.request_id

    first_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Alice"],
                participant_type="user",
                display_name="Alice",
            ),
            content="Frontend is blocked on design review.",
        ),
    )
    assert first_answer.detail.request.status == "open"
    assert first_answer.resumed_task is None

    second_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Bob"],
                participant_type="user",
                display_name="Bob",
            ),
            content="Backend is blocked on API pagination.",
        ),
    )

    assert second_answer.detail.request.status == "completed"
    assert second_answer.resumed_task is not None
    assert second_answer.detail.request.metadata["aggregate"]["answered_count"] == 2
    pending_targets = [
        target
        for target in second_answer.detail.targets
        if target.status == "pending"
    ]
    assert len(pending_targets) == 1
    assert pending_targets[0].participant_id == seeded["users"]["Carol"]


@pytest.mark.asyncio
async def test_answer_interaction_request_one_per_selector_bucket_tracks_bucket_coverage():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[
            ("Alice", "frontend"),
            ("Bob", "backend"),
        ],
    )

    create_result = await kernel.create_interaction_requests(
        seeded["thread_id"],
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need frontend and backend feedback",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="What blocks your area?"),
                    ],
                    selectors=[
                        {"type": "capability", "value": "frontend"},
                        {"type": "capability", "value": "backend"},
                    ],
                    completion_rule=CompletionRule(mode="one_per_selector_bucket"),
                )
            ],
        ),
    )
    request_id = create_result.details[0].request.request_id

    first_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Alice"],
                participant_type="user",
                display_name="Alice",
            ),
            content="Frontend is blocked on responsive QA.",
        ),
    )
    assert first_answer.detail.request.status == "open"
    assert set(first_answer.detail.request.metadata["aggregate"]["covered_selector_buckets"]) == {
        "capability:frontend",
    }

    second_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Bob"],
                participant_type="user",
                display_name="Bob",
            ),
            content="Backend is blocked on API review.",
        ),
    )

    assert second_answer.detail.request.status == "completed"
    assert set(second_answer.detail.request.metadata["aggregate"]["covered_selector_buckets"]) == {
        "capability:frontend",
        "capability:backend",
    }


@pytest.mark.asyncio
async def test_dismiss_interaction_target_reduces_all_targets_quorum():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[
            ("Alice", "frontend"),
            ("Bob", "backend"),
        ],
    )

    create_result = await kernel.create_interaction_requests(
        seeded["thread_id"],
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need both viewpoints",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="What blocks delivery?"),
                    ],
                    target_participant_ids=list(seeded["users"].values()),
                    completion_rule=CompletionRule(mode="all_targets"),
                )
            ],
        ),
    )
    request_id = create_result.details[0].request.request_id

    answer_result = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Alice"],
                participant_type="user",
                display_name="Alice",
            ),
            content="Frontend is blocked on approvals.",
        ),
    )
    assert answer_result.detail.request.status == "open"

    bob_target = next(
        target
        for target in answer_result.detail.targets
        if target.participant_id == seeded["users"]["Bob"]
    )
    dismiss_result = await kernel.update_interaction_request(
        request_id,
        UpdateInteractionRequestRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            action="dismiss_target",
            target_id=bob_target.target_id,
        ),
    )

    assert dismiss_result.detail.request.status == "completed"
    assert dismiss_result.resumed_task is not None
    assert dismiss_result.detail.request.metadata["aggregate"]["target_count"] == 1
    dismissed_target = next(
        target
        for target in dismiss_result.detail.targets
        if target.target_id == bob_target.target_id
    )
    assert dismissed_target.status == "dismissed"


@pytest.mark.asyncio
async def test_answer_interaction_request_completes_and_requeues_requesting_agent():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    requester_id = uuid4()
    requester_system_agent_id = uuid4()
    user_one_id = uuid4()
    user_two_id = uuid4()
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        name="Questions",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Coordination",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, requester_id)] = ParticipantProfile(
        participant_id=requester_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=requester_system_agent_id,
        display_name="Research Agent",
        roles=["research"],
        capabilities=["analysis"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    for participant_id, display_name, capability in (
        (user_one_id, "Alice", "frontend"),
        (user_two_id, "Bob", "backend"),
    ):
        repository._participants[(workspace_id, participant_id)] = ParticipantProfile(
            participant_id=participant_id,
            workspace_id=workspace_id,
            participant_type="user",
            user_id=uuid4(),
            display_name=display_name,
            roles=["reviewer"],
            capabilities=[capability],
            status="active",
            created_at=now,
            updated_at=now,
        )

    create_result = await kernel.create_interaction_requests(
        thread_id,
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=requester_id,
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need both perspectives",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="Frontend concerns?"),
                        CreateInteractionQuestionRequest(prompt="Backend concerns?"),
                    ],
                    target_participant_ids=[user_one_id, user_two_id],
                    completion_rule=CompletionRule(mode="all_targets"),
                )
            ],
        ),
    )
    request_id = create_result.details[0].request.request_id

    first_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=user_one_id,
                participant_type="user",
                display_name="Alice",
            ),
            content="Frontend is blocked on responsive states.",
        ),
    )
    assert first_answer.detail.request.status == "open"

    second_answer = await kernel.answer_interaction_request(
        request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=user_two_id,
                participant_type="user",
                display_name="Bob",
            ),
            content="Backend needs API pagination.",
        ),
    )

    assert second_answer.detail.request.status == "completed"
    assert second_answer.resumed_task is not None
    assert second_answer.resumed_task.metadata["routing_reason"] == "interaction_request_completed"
    assert second_answer.resumed_task.metadata["target_system_agent_id"] == str(requester_system_agent_id)


@pytest.mark.asyncio
async def test_post_message_can_atomically_create_interaction_request():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[("Alice", "backend")],
    )

    result = await kernel.post_message(
        seeded["thread_id"],
        CreateMessageRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            content="Please coordinate feedback.",
            visibility="workspace",
            create_task=False,
            requests=[
                CreateInteractionRequest(
                    title="Need backend input",
                    questions=[
                        CreateInteractionQuestionRequest(prompt="What blocks backend delivery?"),
                    ],
                    target_participant_ids=[seeded["users"]["Alice"]],
                )
            ],
        ),
    )

    assert result.message.content == "Please coordinate feedback."
    assert len(repository._messages[seeded["thread_id"]]) == 2
    details = await kernel.list_interaction_requests(seeded["thread_id"])
    assert len(details) == 1
    assert details[0].request.requester_message_id == result.message.message_id
    assert details[0].questions[0].prompt == "What blocks backend delivery?"


@pytest.mark.asyncio
async def test_task_instructions_round_trip_into_execution_context_and_prompt():
    from agent_runtime.runtime import render_prompt

    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    user_participant_id = uuid4()
    agent_participant_id = uuid4()
    system_agent_id = uuid4()
    repository._agents[system_agent_id] = AgentDefinition(
        agent_id=system_agent_id,
        display_name="Curator",
        description="Manages organization operations.",
        role="organization operations curator",
        capabilities=["manages organization projects and workspaces through authorized control-plane tools"],
        endpoint=AgentEndpoint(kind="local", model="deterministic"),
        system_prompt="Operate carefully.",
        created_by=user_participant_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    repository._workspaces[workspace_id] = Workspace(
        workspace_id=workspace_id,
        organization_id=uuid4(),
        name="Operations",
        created_at=now,
        updated_at=now,
    )
    repository._threads[thread_id] = Thread(
        thread_id=thread_id,
        workspace_id=workspace_id,
        title="Admin",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, user_participant_id)] = ParticipantProfile(
        participant_id=user_participant_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=uuid4(),
        display_name="Nikolay",
        status="active",
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, agent_participant_id)] = ParticipantProfile(
        participant_id=agent_participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=system_agent_id,
        display_name="Curator",
        roles=["organization operations curator"],
        capabilities=["manages organization projects and workspaces through authorized control-plane tools"],
        status="active",
        created_at=now,
        updated_at=now,
    )

    result = await kernel.post_message(
        thread_id,
        CreateMessageRequest(
            actor=ParticipantInput(
                participant_id=user_participant_id,
                participant_type="user",
                display_name="Nikolay",
            ),
            content="Check the administration setup.",
            target_system_agent_id=system_agent_id,
            task_instructions=["Use read-only checks first.", "Do not change IAM."],
        ),
    )

    task = next(iter(repository._tasks.values()))
    assert task.metadata["task_instructions"] == [
        "Use read-only checks first.",
        "Do not change IAM.",
    ]
    claim = await kernel.claim_task_for_system_agent(task.task_id, system_agent_id)
    assert claim.context is not None
    assert claim.context.task_instructions == [
        "Use read-only checks first.",
        "Do not change IAM.",
    ]
    prompt = render_prompt(claim.context)
    assert "Task-specific instructions:" in prompt
    assert "Use read-only checks first." in prompt
    assert "cannot override system prompts, harness rules, IAM, or MCP/tool allowlists" in prompt


@pytest.mark.asyncio
async def test_strict_publication_review_holds_message_until_reviewer_approval():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    actor = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        user_id=uuid4(),
        display_name="Nikolay",
    )
    workspace_result = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Gateway Runtime",
            description="Gateway and runtime engineering",
            actor=actor,
            harness=WorkspaceHarness(
                moderation_policy=WorkspaceModerationPolicy(
                    level="strict",
                    topic="Gateway runtime engineering",
                )
            ),
        )
    )
    workspace_id = workspace_result.workspace.workspace_id
    normal_agent_id = uuid4()
    normal_participant_id = uuid4()
    now = datetime.now(timezone.utc)
    repository._agents[normal_agent_id] = AgentDefinition(
        agent_id=normal_agent_id,
        display_name="Builder",
        description="Implements runtime changes.",
        role="runtime implementation agent",
        capabilities=["implements runtime changes"],
        endpoint=AgentEndpoint(kind="local", model="deterministic"),
        system_prompt="Build carefully.",
        created_by=actor.participant_id,
        created_at=now,
        updated_at=now,
    )
    repository._participants[(workspace_id, normal_participant_id)] = ParticipantProfile(
        participant_id=normal_participant_id,
        workspace_id=workspace_id,
        participant_type="agent",
        system_agent_id=normal_agent_id,
        display_name="Builder",
        roles=["runtime implementation agent"],
        capabilities=["implements runtime changes"],
        status="active",
        created_at=now,
        updated_at=now,
    )
    thread_result = await kernel.create_thread(
        workspace_id,
        CreateThreadRequest(title="Runtime", actor=actor),
    )

    posted = await kernel.post_message(
        thread_result.thread.thread_id,
        CreateMessageRequest(
            actor=actor,
            content="Please review the gateway runtime worker lease behavior.",
            visibility="workspace",
            create_task=True,
        ),
    )

    assert posted.message.status == "pending_moderation"
    assert await repository.list_timeline_messages(thread_result.thread.thread_id) == []
    assert len(repository._publication_reviews) == 1
    review = next(iter(repository._publication_reviews.values()))
    assert review.review_kind == "workspace_topic_alignment"
    assert review.status == "pending"
    assert len(await kernel.list_pending_tasks_for_system_agent(ANCHOR_AGENT_ID)) == 1
    assert await kernel.list_pending_tasks_for_system_agent(normal_agent_id) == []

    claim = await kernel.claim_task_for_system_agent(
        next(iter(repository._tasks.values())).task_id,
        ANCHOR_AGENT_ID,
    )
    await kernel.complete_run(
        claim.run.run_id,
        ANCHOR_AGENT_ID,
        AgentRunResult(
            message=json.dumps(
                {
                    "decision": "allow",
                    "relatedness": "direct",
                    "confidence": 0.92,
                    "reason": "The message is directly about gateway runtime behavior.",
                }
            ),
            stop_reason="completed",
        ),
    )

    timeline = await repository.list_timeline_messages(thread_result.thread.thread_id)
    assert [message.content for message in timeline] == [
        "Please review the gateway runtime worker lease behavior."
    ]
    approved = await repository.fetch_latest_publication_review_for_message(
        posted.message.message_id
    )
    assert approved.status == "approved"
    assert approved.decision == "allow"
    normal_tasks = await kernel.list_pending_tasks_for_system_agent(normal_agent_id)
    assert len(normal_tasks) == 1
    assert await kernel.list_pending_tasks_for_system_agent(ANCHOR_AGENT_ID) == []


@pytest.mark.asyncio
async def test_strict_publication_review_suppresses_message_and_private_explanation():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    actor = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        user_id=uuid4(),
        display_name="Nikolay",
    )
    workspace_result = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Database Work",
            actor=actor,
            harness=WorkspaceHarness(
                moderation_policy=WorkspaceModerationPolicy(
                    level="strict",
                    topic="Database migrations",
                    explain_blocked_messages=True,
                )
            ),
        )
    )
    thread_result = await kernel.create_thread(
        workspace_result.workspace.workspace_id,
        CreateThreadRequest(title="Migrations", actor=actor),
    )
    posted = await kernel.post_message(
        thread_result.thread.thread_id,
        CreateMessageRequest(
            actor=actor,
            content="Let's plan a ski trip instead.",
            visibility="workspace",
            create_task=True,
        ),
    )
    claim = await kernel.claim_task_for_system_agent(
        next(iter(repository._tasks.values())).task_id,
        ANCHOR_AGENT_ID,
    )

    await kernel.complete_run(
        claim.run.run_id,
        ANCHOR_AGENT_ID,
        AgentRunResult(
            message=json.dumps(
                {
                    "decision": "block",
                    "relatedness": "unrelated",
                    "confidence": 0.95,
                    "reason": "The message is unrelated to database migrations.",
                    "issuer_explanation": "Keep this thread focused on database migrations.",
                }
            ),
            stop_reason="completed",
        ),
    )

    assert await repository.list_timeline_messages(thread_result.thread.thread_id) == [
        message
        for message in repository._messages[thread_result.thread.thread_id]
        if message.visibility == "private"
    ]
    rejected = await repository.fetch_message(posted.message.message_id)
    assert rejected.status == "rejected"
    review = await repository.fetch_latest_publication_review_for_message(
        posted.message.message_id
    )
    assert review.status == "suppressed"
    assert review.decision == "suppress"
    private_messages = [
        message
        for message in repository._messages[thread_result.thread.thread_id]
        if message.visibility == "private"
    ]
    assert private_messages[0].metadata["recipient_participant_id"] == str(actor.participant_id)
    assert "database migrations" in private_messages[0].content.lower()


@pytest.mark.asyncio
async def test_balanced_publication_review_flags_after_publication():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    actor = ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        user_id=uuid4(),
        display_name="Nikolay",
    )
    workspace_result = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Runtime",
            actor=actor,
            harness=WorkspaceHarness(
                moderation_policy=WorkspaceModerationPolicy(
                    level="balanced",
                    topic="Runtime operations",
                )
            ),
        )
    )
    thread_result = await kernel.create_thread(
        workspace_result.workspace.workspace_id,
        CreateThreadRequest(title="Ops", actor=actor),
    )

    posted = await kernel.post_message(
        thread_result.thread.thread_id,
        CreateMessageRequest(
            actor=actor,
            content="This is probably a tangent about office snacks.",
            visibility="workspace",
            create_task=False,
        ),
    )

    assert posted.message.status == "completed"
    assert len(await repository.list_timeline_messages(thread_result.thread.thread_id)) == 1
    claim = await kernel.claim_task_for_system_agent(
        next(iter(repository._tasks.values())).task_id,
        ANCHOR_AGENT_ID,
    )
    await kernel.complete_run(
        claim.run.run_id,
        ANCHOR_AGENT_ID,
        AgentRunResult(
            message=json.dumps(
                {
                    "decision": "flag",
                    "relatedness": "unrelated",
                    "confidence": 0.8,
                    "reason": "This appears to drift from runtime operations.",
                }
            ),
            stop_reason="completed",
        ),
    )

    updated = await repository.fetch_message(posted.message.message_id)
    assert updated.status == "completed"
    assert updated.metadata["publication_review_status"] == "flagged"
    assert any(
        event.event_type == "message.publication_flagged"
        for event in repository.recorded_events
    )


@pytest.mark.asyncio
async def test_kernel_lists_workspace_communication_log_entries():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[("Alice", "backend")],
    )

    await kernel.post_message(
        seeded["thread_id"],
        CreateMessageRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            content="Please gather blockers.",
            visibility="workspace",
            create_task=False,
        ),
    )
    create_result = await kernel.create_interaction_requests(
        seeded["thread_id"],
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need backend input",
                    questions=[CreateInteractionQuestionRequest(prompt="What blocks backend delivery?")],
                    target_participant_ids=[seeded["users"]["Alice"]],
                )
            ],
        ),
    )
    await kernel.answer_interaction_request(
        create_result.details[0].request.request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Alice"],
                participant_type="user",
                display_name="Alice",
            ),
            content="API review is blocking backend delivery.",
        ),
    )

    page = await kernel.list_workspace_communication_log(
        seeded["workspace_id"],
        thread_id=seeded["thread_id"],
        limit=10,
        offset=0,
    )

    assert page.total_count == 3
    assert {entry.kind for entry in page.entries} == {
        "message",
        "interaction_request",
        "interaction_answer",
    }


@pytest.mark.asyncio
async def test_kernel_persists_workspace_communication_log_to_jsonl(tmp_path):
    repository = FakeRepository(communication_log_dir=tmp_path)
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[("Alice", "backend")],
    )

    await kernel.post_message(
        seeded["thread_id"],
        CreateMessageRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            content="Please gather blockers.",
            visibility="workspace",
            create_task=False,
        ),
    )
    create_result = await kernel.create_interaction_requests(
        seeded["thread_id"],
        CreateInteractionRequestsRequest(
            actor=ParticipantInput(
                participant_id=seeded["requester_id"],
                participant_type="agent",
                display_name="Research Agent",
            ),
            requests=[
                CreateInteractionRequest(
                    title="Need backend input",
                    questions=[CreateInteractionQuestionRequest(prompt="What blocks backend delivery?")],
                    target_participant_ids=[seeded["users"]["Alice"]],
                )
            ],
        ),
    )
    await kernel.answer_interaction_request(
        create_result.details[0].request.request_id,
        CreateInteractionAnswerRequest(
            actor=ParticipantInput(
                participant_id=seeded["users"]["Alice"],
                participant_type="user",
                display_name="Alice",
            ),
            content="API review is blocking backend delivery.",
        ),
    )

    log_file = tmp_path / f"{seeded['workspace_id']}.jsonl"
    assert log_file.exists()
    entries = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert [entry["kind"] for entry in entries] == [
        "message",
        "interaction_request",
        "interaction_answer",
    ]
    assert entries[0]["thread_title"] == "Coordination"
    assert entries[0]["actor_display_name"] == "Research Agent"
    assert entries[2]["actor_display_name"] == "Alice"
    assert entries[2]["content"] == "API review is blocking backend delivery."


@pytest.mark.asyncio
async def test_kernel_rotates_workspace_communication_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_TALON_COMMUNICATION_LOG_MAX_BYTES", "450")
    monkeypatch.setenv("OPEN_TALON_COMMUNICATION_LOG_BACKUP_COUNT", "2")
    repository = FakeRepository(communication_log_dir=tmp_path)
    kernel = CollaborationKernel(repository)
    seeded = _seed_interaction_workspace(
        repository,
        users=[("Alice", "backend")],
    )

    for index in range(6):
        await kernel.post_message(
            seeded["thread_id"],
            CreateMessageRequest(
                actor=ParticipantInput(
                    participant_id=seeded["requester_id"],
                    participant_type="agent",
                    display_name="Research Agent",
                ),
                content=f"rotation-test-{index}-" + ("x" * 120),
                visibility="workspace",
                create_task=False,
            ),
        )

    log_file = tmp_path / f"{seeded['workspace_id']}.jsonl"
    rotated_file = tmp_path / f"{seeded['workspace_id']}.jsonl.1"

    assert log_file.exists()
    assert rotated_file.exists()

    latest_entries = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rotated_entries = [
        json.loads(line)
        for line in rotated_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert latest_entries[-1]["content"].startswith("rotation-test-5-")
    assert rotated_entries[0]["content"].startswith("rotation-test-")


@pytest.mark.asyncio
async def test_post_message_creates_tool_generation_request_for_targeted_tinker():
    repository = FakeRepository()
    seeded = _seed_tinker_workspace(repository)
    kernel = CollaborationKernel(repository)

    result = await kernel.post_message(
        seeded["thread_id"],
        CreateMessageRequest(
            actor=ParticipantInput(
                participant_id=seeded["user_id"],
                participant_type="user",
                display_name="Nikolay",
            ),
            content="Please build a tool repo_stats for repository summaries.",
            visibility="workspace",
            target_system_agent_id=seeded["tinker_agent_id"],
            create_task=True,
        ),
    )

    assert len(repository._tool_generation_requests) == 1
    request = next(iter(repository._tool_generation_requests.values()))
    assert request.status == "submitted"
    assert request.requester_message_id == result.message.message_id
    assert request.target_system_agent_id == seeded["tinker_agent_id"]
    assert request.requested_scope == "global"
    assert result.message.metadata["tool_generation_request_id"] == str(request.request_id)

    tasks = await kernel.list_pending_tasks_for_system_agent(seeded["tinker_agent_id"])
    assert len(tasks) == 1
    assert tasks[0].metadata["tool_generation_request_id"] == str(request.request_id)


@pytest.mark.asyncio
async def test_post_message_can_request_organization_scoped_tool_generation():
    repository = FakeRepository()
    seeded = _seed_tinker_workspace(repository)
    kernel = CollaborationKernel(repository)

    result = await kernel.post_message(
        seeded["thread_id"],
        CreateMessageRequest(
            actor=ParticipantInput(
                participant_id=seeded["user_id"],
                participant_type="user",
                display_name="Nikolay",
            ),
            content="Please build a tool repo_stats for repository summaries.",
            visibility="workspace",
            target_system_agent_id=seeded["tinker_agent_id"],
            target_tool_scope="organization",
            create_task=True,
        ),
    )

    request = next(iter(repository._tool_generation_requests.values()))
    assert request.requested_scope == "organization"
    assert result.message.metadata["tool_generation_request_id"] == str(request.request_id)
    assert result.message.metadata["target_tool_scope"] == "organization"


@pytest.mark.asyncio
async def test_build_agent_execution_context_includes_internal_tools_and_tool_generation_request():
    repository = FakeRepository()
    seeded = _seed_tinker_workspace(repository)
    kernel = CollaborationKernel(repository)
    now = seeded["now"]
    request_id = uuid4()
    revision_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    internal_tool_id = uuid4()

    repository._tool_generation_requests[request_id] = ToolGenerationRequest(
        request_id=request_id,
        organization_id=seeded["organization_id"],
        workspace_id=seeded["workspace_id"],
        thread_id=seeded["thread_id"],
        requester_participant_id=seeded["user_id"],
        target_system_agent_id=seeded["tinker_agent_id"],
        status="pending_approval",
        target_tool_name="repo_stats",
        summary="Build a repository statistics tool.",
        latest_revision_id=revision_id,
        created_at=now,
        updated_at=now,
    )
    repository._tool_generation_revisions[revision_id] = ToolGenerationRevision(
        revision_id=revision_id,
        request_id=request_id,
        revision_number=1,
        status="pending_approval",
        manifest=GeneratedToolManifest(
            name="repo_stats",
            description="Builds repository summaries.",
            build_context_path="/tmp/generated-tools/repo_stats",
            execution=ToolExecutionBinding(
                backend_kind="docker",
                handler_ref="registry.example/repo_stats:latest",
                execution_profile={"network": "none", "workspace_access": "none"},
            ),
            network_access="none",
            workspace_access="none",
        ),
        validation_report=GeneratedToolValidationReport(summary="Smoke tests passed."),
        image_ref="registry.example/repo_stats:latest",
        image_digest="sha256:abcd",
        created_by=seeded["tinker_participant_id"],
        created_at=now,
        updated_at=now,
    )
    repository._agent_internal_tools[seeded["tinker_agent_id"]] = [
        AgentInternalToolBinding(
            system_agent_id=seeded["tinker_agent_id"],
            tool_id=internal_tool_id,
            name="generated_tool_build",
            description="Builds generated tool images.",
            execution=ToolExecutionBinding(
                backend_kind="local_process",
                handler_ref="python",
                execution_profile={"network": "none", "workspace_access": "none"},
                trust_level="trusted",
            ),
            attached_by=seeded["user_id"],
            attached_at=now,
            updated_at=now,
        )
    ]
    repository._tasks[task_id] = Task(
        task_id=task_id,
        workspace_id=seeded["workspace_id"],
        thread_id=seeded["thread_id"],
        title="Reply as Tinker",
        requested_by=seeded["user_id"],
        created_at=now,
        updated_at=now,
        metadata={
            "target_system_agent_id": str(seeded["tinker_agent_id"]),
            "target_participant_id": str(seeded["tinker_participant_id"]),
            "tool_generation_request_id": str(request_id),
        },
    )
    repository._runs[run_id] = Run(
        run_id=run_id,
        workspace_id=seeded["workspace_id"],
        thread_id=seeded["thread_id"],
        task_id=task_id,
        participant_id=seeded["tinker_participant_id"],
        created_at=now,
        updated_at=now,
    )

    context = await kernel.build_agent_execution_context(
        task_id,
        seeded["tinker_agent_id"],
        run_id,
    )

    assert [tool.name for tool in context.internal_tools] == ["generated_tool_build"]
    assert context.tool_generation_request is not None
    assert context.tool_generation_request.request.request_id == request_id
    assert context.tool_generation_request.revisions[0].revision_id == revision_id


@pytest.mark.asyncio
async def test_create_tool_generation_revision_rejects_pending_approval_without_digest():
    repository = FakeRepository()
    seeded = _seed_tinker_workspace(repository)
    kernel = CollaborationKernel(repository)
    now = seeded["now"]
    request_id = uuid4()

    repository._tool_generation_requests[request_id] = ToolGenerationRequest(
        request_id=request_id,
        organization_id=seeded["organization_id"],
        workspace_id=seeded["workspace_id"],
        thread_id=seeded["thread_id"],
        requester_participant_id=seeded["user_id"],
        target_system_agent_id=seeded["tinker_agent_id"],
        status="drafting",
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(ValueError, match="image_ref and image_digest"):
        await kernel.create_tool_generation_revision(
            request_id,
            CreateToolGenerationRevisionRequest(
                actor=ParticipantInput(
                    participant_id=seeded["tinker_participant_id"],
                    participant_type="agent",
                    display_name="Tinker",
                ),
                manifest=GeneratedToolManifest(
                    name="repo_stats",
                    description="Builds repository summaries.",
                    build_context_path="/tmp/generated-tools/repo_stats",
                    execution=ToolExecutionBinding(
                        backend_kind="docker",
                        handler_ref="repo_stats:latest",
                    ),
                    network_access="none",
                    workspace_access="none",
                ),
                image_ref="registry.example/repo_stats:latest",
                image_digest=None,
            ),
        )


@pytest.mark.asyncio
async def test_create_and_reject_tool_generation_revision_records_audit_events():
    repository = FakeRepository()
    seeded = _seed_tinker_workspace(repository)
    kernel = CollaborationKernel(repository)
    now = seeded["now"]
    request_id = uuid4()

    repository._tool_generation_requests[request_id] = ToolGenerationRequest(
        request_id=request_id,
        organization_id=seeded["organization_id"],
        workspace_id=seeded["workspace_id"],
        thread_id=seeded["thread_id"],
        requester_participant_id=seeded["user_id"],
        target_system_agent_id=seeded["tinker_agent_id"],
        status="submitted",
        target_tool_name="repo_stats",
        summary="Build a repository statistics tool.",
        created_at=now,
        updated_at=now,
    )

    create_result = await kernel.create_tool_generation_revision(
        request_id,
        CreateToolGenerationRevisionRequest(
            actor=ParticipantInput(
                participant_id=seeded["tinker_participant_id"],
                participant_type="agent",
                display_name="Tinker",
            ),
            status="pending_approval",
            manifest=GeneratedToolManifest(
                name="repo_stats",
                description="Builds repository summaries.",
                build_context_path="/tmp/generated-tools/repo_stats",
                execution=ToolExecutionBinding(
                    backend_kind="docker",
                    handler_ref="registry.example/repo_stats:latest",
                    execution_profile={"network": "none", "workspace_access": "none"},
                ),
                network_access="none",
                workspace_access="none",
            ),
            validation_report=GeneratedToolValidationReport(summary="Smoke tests passed."),
            image_ref="registry.example/repo_stats:latest",
            image_digest="sha256:abcd",
        ),
    )

    assert create_result.revision is not None
    assert {
        event.event_type for event in repository.recorded_events
    } >= {
        "tool_generation_revision.created",
        "tool_generation_request.pending_approval",
        "message.created",
    }

    reject_result = await kernel.reject_tool_generation_revision(
        create_result.revision.revision_id,
        ReviewToolGenerationRevisionRequest(
            actor=ParticipantInput(
                participant_id=seeded["user_id"],
                participant_type="user",
                display_name="Admin",
            ),
            reason="Needs a narrower scope.",
        ),
    )

    assert reject_result.detail is not None
    assert reject_result.detail.request.status == "rejected"
    assert {
        event.event_type for event in repository.recorded_events
    } >= {
        "tool_generation_revision.rejected",
        "message.created",
    }


@pytest.mark.asyncio
async def test_approve_tool_generation_revision_rejects_local_image_refs():
    repository = FakeRepository()
    seeded = _seed_tinker_workspace(repository)
    kernel = CollaborationKernel(repository)
    now = seeded["now"]
    request_id = uuid4()
    revision_id = uuid4()
    verification_tool_id = uuid4()

    repository._tool_generation_requests[request_id] = ToolGenerationRequest(
        request_id=request_id,
        organization_id=seeded["organization_id"],
        workspace_id=seeded["workspace_id"],
        thread_id=seeded["thread_id"],
        requester_participant_id=seeded["user_id"],
        target_system_agent_id=seeded["tinker_agent_id"],
        status="pending_approval",
        target_tool_name="repo_stats",
        latest_revision_id=revision_id,
        created_at=now,
        updated_at=now,
    )
    repository._tool_generation_revisions[revision_id] = ToolGenerationRevision(
        revision_id=revision_id,
        request_id=request_id,
        revision_number=1,
        status="pending_approval",
        manifest=GeneratedToolManifest(
            name="repo_stats",
            description="Builds repository summaries.",
            build_context_path="/tmp/generated-tools/repo_stats",
            execution=ToolExecutionBinding(
                backend_kind="docker",
                handler_ref="repo_stats:latest",
            ),
            network_access="none",
            workspace_access="none",
        ),
        image_ref="open-talon-test/repo_stats:latest",
        image_digest="sha256:abcd",
        created_by=seeded["tinker_participant_id"],
        created_at=now,
        updated_at=now,
    )
    repository._agent_internal_tools[seeded["tinker_agent_id"]] = [
        AgentInternalToolBinding(
            system_agent_id=seeded["tinker_agent_id"],
            tool_id=verification_tool_id,
            name="generated_tool_registry_pull_verify",
            description="Verifies worker-side OCI pulls.",
            execution=ToolExecutionBinding(
                backend_kind="local_process",
                handler_ref="python",
                execution_profile={"network": "full", "workspace_access": "none"},
                trust_level="trusted",
            ),
            attached_by=seeded["user_id"],
            attached_at=now,
            updated_at=now,
        )
    ]

    with pytest.raises(ValueError, match="OCI registry images"):
        await kernel.approve_tool_generation_revision(
            revision_id,
            ReviewToolGenerationRevisionRequest(
                actor=ParticipantInput(
                    participant_id=uuid4(),
                    participant_type="user",
                    display_name="Admin",
                )
            ),
        )


@pytest.mark.asyncio
async def test_approve_tool_generation_revision_starts_registry_pull_verification():
    repository = FakeRepository()
    seeded = _seed_tinker_workspace(repository)
    kernel = CollaborationKernel(repository)
    now = seeded["now"]
    request_id = uuid4()
    revision_id = uuid4()
    verification_tool_id = uuid4()

    repository._tool_generation_requests[request_id] = ToolGenerationRequest(
        request_id=request_id,
        organization_id=seeded["organization_id"],
        workspace_id=seeded["workspace_id"],
        thread_id=seeded["thread_id"],
        requester_participant_id=seeded["user_id"],
        target_system_agent_id=seeded["tinker_agent_id"],
        status="pending_approval",
        target_tool_name="repo_stats",
        summary="Build a repository statistics tool.",
        latest_revision_id=revision_id,
        created_at=now,
        updated_at=now,
    )
    repository._tool_generation_revisions[revision_id] = ToolGenerationRevision(
        revision_id=revision_id,
        request_id=request_id,
        revision_number=1,
        status="pending_approval",
        manifest=GeneratedToolManifest(
            name="repo_stats",
            description="Builds repository summaries.",
            build_context_path="/tmp/generated-tools/repo_stats",
            execution=ToolExecutionBinding(
                backend_kind="docker",
                handler_ref="registry.example/repo_stats:latest",
                execution_profile={"network": "none", "workspace_access": "none"},
            ),
            network_access="none",
            workspace_access="none",
        ),
        validation_report=GeneratedToolValidationReport(summary="Smoke tests passed."),
        image_ref="registry.example/repo_stats:latest",
        image_digest="sha256:abcd",
        created_by=seeded["tinker_participant_id"],
        created_at=now,
        updated_at=now,
    )
    repository._agent_internal_tools[seeded["tinker_agent_id"]] = [
        AgentInternalToolBinding(
            system_agent_id=seeded["tinker_agent_id"],
            tool_id=verification_tool_id,
            name="generated_tool_registry_pull_verify",
            description="Verifies worker-side OCI pulls.",
            execution=ToolExecutionBinding(
                backend_kind="local_process",
                handler_ref="python",
                execution_profile={"network": "full", "workspace_access": "none"},
                trust_level="trusted",
            ),
            attached_by=seeded["user_id"],
            attached_at=now,
            updated_at=now,
            metadata={"internal_only": True},
        )
    ]

    result = await kernel.approve_tool_generation_revision(
        revision_id,
        ReviewToolGenerationRevisionRequest(
            actor=ParticipantInput(
                participant_id=uuid4(),
                participant_type="user",
                display_name="Admin",
            )
        ),
    )

    assert result.detail is not None
    assert result.detail.request.status == "verifying_registry_pull"
    assert result.detail.request.final_tool_id is None
    assert repository._workspace_tools.get(seeded["workspace_id"]) in (None, [])
    pending_tool_calls = [
        tool_call
        for tool_calls in repository._tool_calls.values()
        for tool_call in tool_calls
        if tool_call.tool_name == "generated_tool_registry_pull_verify"
    ]
    assert len(pending_tool_calls) == 1
    assert pending_tool_calls[0].arguments["immutable_ref"] == "registry.example/repo_stats@sha256:abcd"
    assert any(
        message.metadata.get("tool_generation_status") == "verifying_registry_pull"
        for message in repository._messages[seeded["thread_id"]]
    )
    assert {
        event.event_type for event in repository.recorded_events
    } >= {
        "task.claimed",
        "run.started",
        "tool_call.created",
        "tool_generation_revision.approval_started",
        "message.created",
    }


@pytest.mark.asyncio
async def test_tool_generation_registry_pull_verification_completion_publishes_organization_scoped_tool():
    repository = FakeRepository()
    seeded = _seed_tinker_workspace(repository)
    kernel = CollaborationKernel(repository)
    now = seeded["now"]
    request_id = uuid4()
    revision_id = uuid4()
    verification_tool_id = uuid4()

    repository._tool_generation_requests[request_id] = ToolGenerationRequest(
        request_id=request_id,
        organization_id=seeded["organization_id"],
        workspace_id=seeded["workspace_id"],
        thread_id=seeded["thread_id"],
        requester_participant_id=seeded["user_id"],
        target_system_agent_id=seeded["tinker_agent_id"],
        requested_scope="organization",
        status="pending_approval",
        target_tool_name="repo_stats",
        summary="Build an organization repository statistics tool.",
        latest_revision_id=revision_id,
        created_at=now,
        updated_at=now,
    )
    repository._tool_generation_revisions[revision_id] = ToolGenerationRevision(
        revision_id=revision_id,
        request_id=request_id,
        revision_number=1,
        status="pending_approval",
        manifest=GeneratedToolManifest(
            name="repo_stats",
            description="Builds repository summaries.",
            build_context_path="/tmp/generated-tools/repo_stats",
            execution=ToolExecutionBinding(
                backend_kind="docker",
                handler_ref="registry.example/repo_stats:latest",
                execution_profile={"network": "none", "workspace_access": "none"},
            ),
            network_access="none",
            workspace_access="none",
        ),
        validation_report=GeneratedToolValidationReport(summary="Smoke tests passed."),
        image_ref="registry.example/repo_stats:latest",
        image_digest="sha256:abcd",
        created_by=seeded["tinker_participant_id"],
        created_at=now,
        updated_at=now,
    )
    repository._agent_internal_tools[seeded["tinker_agent_id"]] = [
        AgentInternalToolBinding(
            system_agent_id=seeded["tinker_agent_id"],
            tool_id=verification_tool_id,
            name="generated_tool_registry_pull_verify",
            description="Verifies worker-side OCI pulls.",
            execution=ToolExecutionBinding(
                backend_kind="local_process",
                handler_ref="python",
                execution_profile={"network": "full", "workspace_access": "none"},
                trust_level="trusted",
            ),
            attached_by=seeded["user_id"],
            attached_at=now,
            updated_at=now,
            metadata={"internal_only": True},
        )
    ]

    approval = await kernel.approve_tool_generation_revision(
        revision_id,
        ReviewToolGenerationRevisionRequest(
            actor=ParticipantInput(
                participant_id=uuid4(),
                participant_type="user",
                display_name="Admin",
            )
        ),
    )
    assert approval.detail is not None
    verification_tool_call = next(
        tool_call
        for tool_calls in repository._tool_calls.values()
        for tool_call in tool_calls
        if tool_call.tool_name == "generated_tool_registry_pull_verify"
    )
    claimed = await kernel.claim_next_tool_call(
        worker_id="tool-worker",
        lease_ttl_seconds=30,
        max_parallel_calls_per_run=1,
        max_concurrent_calls_per_tool=1,
    )
    assert claimed.tool_call is not None
    assert claimed.tool_call.tool_call_id == verification_tool_call.tool_call_id
    await kernel.update_tool_call_execution_handle(
        verification_tool_call.tool_call_id,
        "tool-worker",
        "verification-handle",
    )
    await kernel.complete_tool_call(
        verification_tool_call.tool_call_id,
        "tool-worker",
        result=ToolCallResult(
            output_payload={"immutable_ref": "registry.example/repo_stats@sha256:abcd"},
        ),
    )
    result = await kernel.get_tool_generation_request(request_id)

    published_tool = repository._system_tools[result.request.final_tool_id]
    assert published_tool.scope == "organization"
    assert published_tool.organization_id == seeded["organization_id"]
    assert published_tool.execution.handler_ref == "registry.example/repo_stats@sha256:abcd"
    assert repository._workspace_tools.get(seeded["workspace_id"]) in (None, [])
    assert any(
        message.content.startswith(
            "Tool `repo_stats` was approved and added to the organization system tools catalog."
        )
        for message in repository._messages[seeded["thread_id"]]
    )
    assert {
        event.event_type for event in repository.recorded_events
    } >= {
        "tool_generation_revision.approval_started",
        "tool_generation_revision.published",
        "message.created",
    }


@pytest.mark.asyncio
async def test_tool_generation_registry_pull_verification_failure_returns_request_to_pending_approval():
    repository = FakeRepository()
    seeded = _seed_tinker_workspace(repository)
    kernel = CollaborationKernel(repository)
    now = seeded["now"]
    request_id = uuid4()
    revision_id = uuid4()
    verification_tool_id = uuid4()

    repository._tool_generation_requests[request_id] = ToolGenerationRequest(
        request_id=request_id,
        organization_id=seeded["organization_id"],
        workspace_id=seeded["workspace_id"],
        thread_id=seeded["thread_id"],
        requester_participant_id=seeded["user_id"],
        target_system_agent_id=seeded["tinker_agent_id"],
        status="pending_approval",
        target_tool_name="repo_stats",
        summary="Build a repository statistics tool.",
        latest_revision_id=revision_id,
        created_at=now,
        updated_at=now,
    )
    repository._tool_generation_revisions[revision_id] = ToolGenerationRevision(
        revision_id=revision_id,
        request_id=request_id,
        revision_number=1,
        status="pending_approval",
        manifest=GeneratedToolManifest(
            name="repo_stats",
            description="Builds repository summaries.",
            build_context_path="/tmp/generated-tools/repo_stats",
            execution=ToolExecutionBinding(
                backend_kind="docker",
                handler_ref="registry.example/repo_stats:latest",
                execution_profile={"network": "none", "workspace_access": "none"},
            ),
            network_access="none",
            workspace_access="none",
        ),
        validation_report=GeneratedToolValidationReport(summary="Smoke tests passed."),
        image_ref="registry.example/repo_stats:latest",
        image_digest="sha256:abcd",
        created_by=seeded["tinker_participant_id"],
        created_at=now,
        updated_at=now,
    )
    repository._agent_internal_tools[seeded["tinker_agent_id"]] = [
        AgentInternalToolBinding(
            system_agent_id=seeded["tinker_agent_id"],
            tool_id=verification_tool_id,
            name="generated_tool_registry_pull_verify",
            description="Verifies worker-side OCI pulls.",
            execution=ToolExecutionBinding(
                backend_kind="local_process",
                handler_ref="python",
                execution_profile={"network": "full", "workspace_access": "none"},
                trust_level="trusted",
            ),
            attached_by=seeded["user_id"],
            attached_at=now,
            updated_at=now,
            metadata={"internal_only": True},
        )
    ]

    await kernel.approve_tool_generation_revision(
        revision_id,
        ReviewToolGenerationRevisionRequest(
            actor=ParticipantInput(
                participant_id=uuid4(),
                participant_type="user",
                display_name="Admin",
            )
        ),
    )
    claimed = await kernel.claim_next_tool_call(
        worker_id="tool-worker",
        lease_ttl_seconds=30,
        max_parallel_calls_per_run=1,
        max_concurrent_calls_per_tool=1,
    )
    assert claimed.tool_call is not None
    await kernel.update_tool_call_execution_handle(
        claimed.tool_call.tool_call_id,
        "tool-worker",
        "verification-handle",
    )
    await kernel.fail_tool_call(
        claimed.tool_call.tool_call_id,
        "tool-worker",
        "docker pull failed: unauthorized",
    )

    detail = await kernel.get_tool_generation_request(request_id)
    assert detail.request.status == "pending_approval"
    assert detail.revisions[0].status == "pending_approval"
    assert (
        detail.request.metadata["approval_verification_error"]
        == "docker pull failed: unauthorized"
    )
    assert any(
        "registry pull verification failed" in message.content.lower()
        for message in repository._messages[seeded["thread_id"]]
    )
    assert {
        event.event_type for event in repository.recorded_events
    } >= {
        "tool_generation_revision.approval_started",
        "tool_generation_revision.verification_failed",
        "message.created",
    }
