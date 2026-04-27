from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4

import asyncpg
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
for path in (_CONTRACTS_DIR, _CORE_COLLAB_DIR, _WORKSPACE_MEMORY_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_contracts.agent_contracts import build_default_interaction_contract
from open_talon_contracts.models import (
    AgentCompactionPolicy,
    AgentDefinition,
    AgentDefinitionVersion,
    AgentEndpoint,
    AgentHarness,
    AgentToolUsePolicy,
    AssetLink,
    AuditEventDraft,
    GitRepository,
    LlmProviderDefinition,
    Organization,
    OrganizationMembership,
    Project,
    ProjectAccessBinding,
    ResolvedAssetBinding,
    Workspace,
    WorkspaceHarness,
    WorkspaceMethodology,
    WorkspaceAsset,
    WorkspaceAssetVersion,
)
from support.model_constants import TEST_EXPLICIT_OLLAMA_MODEL
from core_collab.migrations import apply_pending_migrations
from core_collab.repository import CollaborationRepository, UserRecord


pytestmark = pytest.mark.integration


def _postgres_dsn() -> str:
    return (
        os.getenv("OPEN_TALON_TEST_POSTGRES_DSN")
        or "postgresql://"
        f"{os.getenv('POSTGRES_USER', 'admin')}:{os.getenv('POSTGRES_PASSWORD', 'password')}"
        f"@{os.getenv('POSTGRES_HOST', '127.0.0.1')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB', 'app_db')}"
    )


@pytest.mark.asyncio
async def test_repository_llm_provider_round_trips_and_finds_referencing_agents():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    now = datetime.now(timezone.utc)
    provider_id = uuid4()
    agent_id = uuid4()
    owner_id = uuid4()
    engine_id = f"it-openai-{uuid4().hex[:8]}"
    provider = LlmProviderDefinition(
        provider_id=provider_id,
        engine_id=engine_id,
        display_name="Integration OpenAI",
        description="Repository integration provider.",
        provider="openai",
        endpoint_kind="remote",
        url="https://api.openai.com/v1/responses",
        default_model="gpt-5.4-mini",
        capabilities=["chat", "reasoning"],
        locality="cloud",
        priority=250,
        enabled=True,
        secret_config={
            "openbao": {
                "mount": "secret",
                "path": f"open-talon/test/{engine_id}",
                "field": "api_key",
            }
        },
        created_by=owner_id,
        created_at=now,
        updated_by=owner_id,
        updated_at=now,
        metadata={"source": "integration-test"},
    )
    agent = AgentDefinition(
        agent_id=agent_id,
        display_name="Integration Planner",
        description="Agent referencing a managed engine.",
        role="planner",
        capabilities=["planning", "reasoning"],
        endpoint=AgentEndpoint(
            kind="remote",
            engine_id=engine_id,
            provider="openai",
        ),
        system_prompt="Plan carefully.",
        interaction_contract=build_default_interaction_contract(
            display_name="Integration Planner",
            role="planner",
            description="Agent referencing a managed engine.",
            capabilities=["planning", "reasoning"],
        ),
        definition={"runtime": {"preferred_engine_ids": [engine_id]}},
        created_by=owner_id,
        created_at=now,
        updated_at=now,
        metadata={"source": "integration-test"},
    )

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.upsert_llm_provider(conn, provider)
                await repository.upsert_system_agent(conn, agent)

        fetched = await repository.fetch_llm_provider(provider_id)
        assert fetched is not None
        assert fetched.engine_id == engine_id
        assert fetched.secret_config["openbao"]["path"] == f"open-talon/test/{engine_id}"

        listed = await repository.list_llm_providers()
        assert any(item.provider_id == provider_id for item in listed)

        references = await repository.list_system_agents_referencing_llm_engine(engine_id)
        assert [item.agent_id for item in references] == [agent_id]
        assert references[0].definition["runtime"]["preferred_engine_ids"] == [engine_id]

        async with pool.acquire() as conn:
            async with conn.transaction():
                deleted = await repository.delete_llm_provider(conn, provider_id=provider_id)
                await conn.execute("DELETE FROM system_agents WHERE agent_id = $1", agent_id)
        assert deleted is True
        assert await repository.fetch_llm_provider(provider_id) is None
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM system_agents WHERE agent_id = $1", agent_id)
            await conn.execute("DELETE FROM llm_providers WHERE provider_id = $1", provider_id)
        await pool.close()


@pytest.mark.asyncio
async def test_repository_migrations_seed_default_reasoning_planner_agent():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    try:
        agents = await repository.list_system_agents()
        seeded = next(
            agent for agent in agents if str(agent.agent_id) == "33333333-3333-3333-3333-333333333333"
        )
        assert seeded.display_name == "Reasoning Planner"
        assert seeded.endpoint.engine_id == "openai-responses"
        assert seeded.endpoint.provider == "openai"
        assert seeded.definition["runtime"]["engine_id"] == "openai-responses"
        assert seeded.definition["runtime"]["preferred_locality"] == "cloud"
        assert seeded.interaction_contract.response_contract.required_sections == [
            "Summary",
            "Findings",
            "Next action",
        ]
        assert seeded.metadata["seeded"] is True
        assert seeded.metadata["example"] is True
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_repository_migrations_seed_tinker_agent_with_internal_tools():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    try:
        tinker_agent_id = UUID("44444444-4444-4444-4444-444444444444")
        tinker = await repository.fetch_system_agent(tinker_agent_id)

        assert tinker is not None
        assert tinker.display_name == "Tinker"
        assert tinker.role == "generated tool authoring and validation agent"
        assert set(tinker.capabilities) == {
            "generates new agent-usable tools from workspace requests",
            "checks whether existing tools already satisfy a request",
            "validates generated tools before approval",
            "submits generated tool revisions for catalog review",
            "reports trust network and workspace-access rationale for generated tools",
        }
        assert tinker.metadata["tool_generation_agent"] is True

        internal_tools = await repository.list_agent_internal_tools(tinker_agent_id)
        assert {tool.name for tool in internal_tools} == {
            "generated_tool_repo_bootstrap",
            "generated_tool_repo_write",
            "generated_tool_build",
            "generated_tool_registry_push",
            "generated_tool_registry_pull_verify",
            "generated_tool_smoke_test",
            "generated_tool_asset_publish",
            "generated_tool_request_status_update",
        }
        assert all(tool.execution.trust_level == "trusted" for tool in internal_tools)
        assert all(tool.metadata["managed"] is True for tool in internal_tools)
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_repository_migrations_seed_operational_agents_and_contexts_idempotently():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)
    await apply_pending_migrations(pool)

    try:
        system_base = await repository.fetch_organization_by_slug("system-base")
        assert system_base is not None
        admin_project = await repository.fetch_project_by_slug(
            organization_id=system_base.organization_id,
            slug="administration",
        )
        assert admin_project is not None
        operations = await repository.list_workspaces(
            organization_id=system_base.organization_id,
            project_id=admin_project.project_id,
        )
        assert any(workspace.name == "System Operations" for workspace in operations)

        steward = await repository.fetch_system_agent(
            UUID("44444444-4444-4444-4444-444444444445")
        )
        assert steward is not None
        assert steward.agent_key == "steward"
        assert steward.role == "platform operations steward"
        steward_mcp_tools = await repository.list_agent_internal_mcp_tools(steward.agent_id)
        assert "control_plane__runtime.overview.get" in {
            tool.exposed_name for tool in steward_mcp_tools
        }

        default_org = await repository.fetch_organization_by_slug("default")
        assert default_org is not None
        default_admin = await repository.fetch_project_by_slug(
            organization_id=default_org.organization_id,
            slug="administration",
        )
        assert default_admin is not None
        curators = await repository.list_system_agents(
            scope="organization",
            organization_id=default_org.organization_id,
        )
        curator = next(agent for agent in curators if agent.agent_key == "curator")
        assert curator.role == "organization operations curator"
        curator_tools = await repository.list_agent_internal_mcp_tools(curator.agent_id)
        exposed = {tool.exposed_name for tool in curator_tools}
        assert "control_plane__organizations.get" in exposed
        assert "control_plane__organizations.list" not in exposed

        anchor = await repository.fetch_system_agent(
            UUID("44444444-4444-4444-4444-444444444446")
        )
        assert anchor is not None
        assert anchor.agent_key == "anchor"
        assert anchor.role == "workspace topic alignment reviewer"
        assert "reviews messages for alignment with the workspace topic" in anchor.capabilities
        assert anchor.endpoint.engine_id == "local-ollama"
        assert anchor.endpoint.provider == "ollama"
        assert anchor.definition["runtime"]["engine_id"] == "local-ollama"
        assert anchor.definition["runtime"]["provider"] == "ollama"
        assert anchor.interaction_contract.response_contract.format == "json"
        for workspace in await repository.list_workspaces():
            participant = await repository.fetch_agent_participant(
                workspace.workspace_id,
                anchor.agent_id,
            )
            assert participant is not None
            assert participant.metadata["task_routing"]["normal_message_fanout"] is False
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_repository_runtime_queue_stats_query_executes_with_org_filter():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    try:
        now = datetime.now(timezone.utc)
        stats = await repository.get_runtime_queue_stats(
            now=now,
            since=now,
            organization_id=uuid4(),
        )
        global_tokens = await repository.get_global_token_total(
            day_start=now,
            day_end=now,
            organization_id=uuid4(),
        )
        workspace_totals = await repository.list_workspace_token_totals(
            day_start=now,
            day_end=now,
            organization_id=uuid4(),
        )

        assert stats["tasks_pending"] == 0
        assert stats["tasks_claimed"] == 0
        assert stats["run_steps_pending"] == 0
        assert stats["tool_calls_pending"] == 0
        assert global_tokens == 0
        assert workspace_totals == []
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_repository_workspace_and_agent_harness_round_trip():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    agent_id = uuid4()
    owner_id = uuid4()

    workspace = Workspace(
        workspace_id=workspace_id,
        name="Harness Workspace",
        description="Workspace harness integration test.",
        harness=WorkspaceHarness(
            summary="Prefer explicit validation artifacts.",
            methodology=WorkspaceMethodology(
                ontology="Artifacts and tests are first-class evidence.",
            ),
        ),
        created_at=now,
        updated_at=now,
    )
    agent = AgentDefinition(
        agent_id=agent_id,
        display_name="Harness Agent",
        description="Agent harness integration test.",
        role="research agent",
        capabilities=["research"],
        endpoint=AgentEndpoint(kind="local", model=TEST_EXPLICIT_OLLAMA_MODEL),
        system_prompt="Research carefully.",
        harness=AgentHarness(
            summary="Choose tools dynamically from the workspace catalog.",
            tool_use_policy=AgentToolUsePolicy(
                selection_principles=["Prefer the narrowest tool that provides evidence."],
            ),
            compaction_policy=AgentCompactionPolicy(
                strategy="rolling_summary",
                max_estimated_input_tokens=8_500,
                recent_message_count=10,
                max_run_memory_entries=4,
            ),
        ),
        interaction_contract=build_default_interaction_contract(
            display_name="Harness Agent",
            role="research agent",
            description="Agent harness integration test.",
            capabilities=["research"],
        ),
        created_by=owner_id,
        created_at=now,
        updated_at=now,
    )

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.upsert_workspace(conn, workspace)
                await repository.upsert_system_agent(conn, agent)

        fetched_workspace = await repository.fetch_workspace(workspace_id)
        fetched_agent = await repository.fetch_system_agent(agent_id)
        listed_workspaces = await repository.list_workspaces()
        listed_agents = await repository.list_system_agents()

        assert fetched_workspace is not None
        assert fetched_workspace.harness is not None
        assert fetched_workspace.harness.summary == "Prefer explicit validation artifacts."
        assert fetched_workspace.harness.methodology.ontology.startswith("Artifacts and tests")
        listed_workspace = next(item for item in listed_workspaces if item.workspace_id == workspace_id)
        assert listed_workspace.harness is not None
        assert listed_workspace.harness.summary == "Prefer explicit validation artifacts."
        assert fetched_agent is not None
        assert fetched_agent.harness is not None
        assert fetched_agent.harness.summary.startswith("Choose tools dynamically")
        assert fetched_agent.harness.tool_use_policy.selection_principles == [
            "Prefer the narrowest tool that provides evidence."
        ]
        assert fetched_agent.harness.compaction_policy.strategy == "rolling_summary"
        listed_agent = next(item for item in listed_agents if item.agent_id == agent_id)
        assert listed_agent.harness is not None
        assert listed_agent.harness.summary.startswith("Choose tools dynamically")
        assert listed_agent.harness.compaction_policy.max_run_memory_entries == 4
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM system_agents WHERE agent_id = $1", agent_id)
            await conn.execute("DELETE FROM workspaces WHERE workspace_id = $1", workspace_id)
        await pool.close()


@pytest.mark.asyncio
async def test_repository_project_access_round_trip_and_filters_workspaces():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    now = datetime.now(timezone.utc)
    owner_id = uuid4()
    viewer_id = uuid4()
    outsider_id = uuid4()
    organization_id = uuid4()
    project_id = uuid4()
    workspace_id = uuid4()
    organization = Organization(
        organization_id=organization_id,
        slug=f"project-access-{organization_id.hex[:8]}",
        name="Project Access Integration",
        created_by=owner_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    project = Project(
        project_id=project_id,
        organization_id=organization_id,
        slug="access-project",
        name="Access Project",
        created_by=owner_id,
        creator_user_id=owner_id,
        owner_user_id=owner_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    workspace = Workspace(
        workspace_id=workspace_id,
        organization_id=organization_id,
        project_id=project_id,
        name="Project Workspace",
        description="Workspace visible through project access.",
        owner_user_id=owner_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                for user_id, display_name in [
                    (owner_id, "Owner"),
                    (viewer_id, "Viewer"),
                    (outsider_id, "Outsider"),
                ]:
                    await repository.upsert_user(
                        conn,
                        UserRecord(
                            user_id=user_id,
                            display_name=display_name,
                            created_at=now,
                            updated_at=now,
                            metadata={},
                        ),
                    )
                await repository.upsert_organization(conn, organization)
                for user_id in [owner_id, viewer_id, outsider_id]:
                    await repository.upsert_organization_membership(
                        conn,
                        OrganizationMembership(
                            organization_id=organization_id,
                            user_id=user_id,
                            role="member",
                            joined_at=now,
                            updated_at=now,
                            metadata={},
                        ),
                    )
                await repository.upsert_project(conn, project)
                await repository.upsert_project_access_binding(
                    conn,
                    ProjectAccessBinding(
                        project_id=project_id,
                        subject_type="user",
                        user_id=owner_id,
                        role="owner",
                        created_at=now,
                        updated_at=now,
                        metadata={},
                    ),
                )
                await repository.upsert_project_access_binding(
                    conn,
                    ProjectAccessBinding(
                        project_id=project_id,
                        subject_type="user",
                        user_id=viewer_id,
                        role="viewer",
                        created_at=now,
                        updated_at=now,
                        metadata={},
                    ),
                )
                await repository.upsert_workspace(conn, workspace)

        owner_projects = await repository.list_projects_for_user(
            organization_id=organization_id,
            user_id=owner_id,
        )
        viewer_workspaces = await repository.list_workspaces_for_user(
            viewer_id,
            organization_id=organization_id,
            project_id=project_id,
        )
        outsider_projects = await repository.list_projects_for_user(
            organization_id=organization_id,
            user_id=outsider_id,
        )
        outsider_workspaces = await repository.list_workspaces_for_user(
            outsider_id,
            organization_id=organization_id,
            project_id=project_id,
        )

        assert [item.project_id for item in owner_projects] == [project_id]
        assert [item.workspace_id for item in viewer_workspaces] == [workspace_id]
        assert outsider_projects == []
        assert outsider_workspaces == []
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM organizations WHERE organization_id = $1", organization_id)
            await conn.execute("DELETE FROM users WHERE user_id = ANY($1::uuid[])", [owner_id, viewer_id, outsider_id])
        await pool.close()


@pytest.mark.asyncio
async def test_repository_workspace_assets_round_trip_and_resolve_workspace_override():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    owner_id = uuid4()
    target_agent_id = uuid4()
    global_repo_id = uuid4()
    workspace_repo_id = uuid4()
    global_asset_id = uuid4()
    workspace_asset_id = uuid4()
    global_version_id = uuid4()
    workspace_version_id = uuid4()

    workspace = Workspace(
        workspace_id=workspace_id,
        name="Assets",
        description="Asset resolution integration test.",
        created_at=now,
        updated_at=now,
    )
    global_repo = GitRepository(
        repo_id=global_repo_id,
        scope="global",
        workspace_id=None,
        name="global-defs",
        local_path="/tmp/global-defs",
        forgejo_url="http://localhost:3001/global-defs",
        created_by=owner_id,
        created_at=now,
        updated_at=now,
    )
    workspace_repo = GitRepository(
        repo_id=workspace_repo_id,
        scope="workspace",
        workspace_id=workspace_id,
        name="workspace-defs",
        local_path="/tmp/workspace-defs",
        forgejo_url="http://localhost:3001/workspace-defs",
        created_by=owner_id,
        created_at=now,
        updated_at=now,
    )
    global_asset = WorkspaceAsset(
        asset_id=global_asset_id,
        scope="global",
        workspace_id=None,
        asset_type="agent_instruction",
        logical_name="agent-md",
        title="Global Agent.md",
        created_by=owner_id,
        created_at=now,
        updated_at=now,
    )
    workspace_asset = WorkspaceAsset(
        asset_id=workspace_asset_id,
        scope="workspace",
        workspace_id=workspace_id,
        asset_type="agent_instruction",
        logical_name="agent-md",
        title="Workspace Agent.md",
        created_by=owner_id,
        created_at=now,
        updated_at=now,
    )
    global_version = WorkspaceAssetVersion(
        asset_version_id=global_version_id,
        asset_id=global_asset_id,
        version=1,
        source_kind="git_publish",
        git_repository_id=global_repo_id,
        git_revision="global-sha",
        git_path="agents/admin/AGENT.md",
        storage_backend="minio",
        bucket="open-talon-assets",
        object_key="global/agent-md/1/AGENT.md",
        content_type="text/markdown",
        size_bytes=42,
        sha256="1" * 64,
        created_by=owner_id,
        created_at=now,
    )
    workspace_version = WorkspaceAssetVersion(
        asset_version_id=workspace_version_id,
        asset_id=workspace_asset_id,
        version=1,
        source_kind="git_publish",
        git_repository_id=workspace_repo_id,
        git_revision="workspace-sha",
        git_path="agents/admin/AGENT.md",
        storage_backend="minio",
        bucket="open-talon-assets",
        object_key="workspaces/test/agent-md/1/AGENT.md",
        content_type="text/markdown",
        size_bytes=84,
        sha256="2" * 64,
        created_by=owner_id,
        created_at=now,
    )
    global_link = AssetLink(
        link_id=uuid4(),
        asset_id=global_asset_id,
        asset_version_id=global_version_id,
        workspace_id=None,
        target_type="system_agent",
        target_id=target_agent_id,
        purpose="agent_md",
        created_by=owner_id,
        created_at=now,
        updated_at=now,
    )
    workspace_link = AssetLink(
        link_id=uuid4(),
        asset_id=workspace_asset_id,
        asset_version_id=workspace_version_id,
        workspace_id=workspace_id,
        target_type="system_agent",
        target_id=target_agent_id,
        purpose="agent_md",
        created_by=owner_id,
        created_at=now,
        updated_at=now,
    )

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.upsert_workspace(conn, workspace)
                await repository.upsert_git_repository(conn, global_repo)
                await repository.upsert_git_repository(conn, workspace_repo)
                await repository.upsert_workspace_asset(conn, global_asset)
                await repository.upsert_workspace_asset(conn, workspace_asset)
                await repository.upsert_workspace_asset_version(conn, global_version)
                await repository.upsert_workspace_asset_version(conn, workspace_version)
                await repository.upsert_asset_link(conn, global_link)
                await repository.upsert_asset_link(conn, workspace_link)

        repos = await repository.list_git_repositories(scope="workspace", workspace_id=workspace_id)
        assert [repo.repo_id for repo in repos] == [workspace_repo_id]

        versions = await repository.list_workspace_asset_versions(workspace_asset_id)
        assert [version.asset_version_id for version in versions] == [workspace_version_id]

        bindings = await repository.list_asset_links_for_target(
            target_type="system_agent",
            target_id=target_agent_id,
            workspace_id=workspace_id,
        )
        assert len(bindings) == 1
        assert bindings[0].workspace_id == workspace_id
        assert bindings[0].version.asset_version_id == workspace_version_id
        assert bindings[0].asset.title == "Workspace Agent.md"
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM asset_links WHERE target_id = $1", target_agent_id)
            await conn.execute("DELETE FROM workspace_asset_versions WHERE asset_id IN ($1, $2)", global_asset_id, workspace_asset_id)
            await conn.execute("DELETE FROM workspace_assets WHERE asset_id IN ($1, $2)", global_asset_id, workspace_asset_id)
            await conn.execute("DELETE FROM git_repositories WHERE repo_id IN ($1, $2)", global_repo_id, workspace_repo_id)
            await conn.execute("DELETE FROM workspaces WHERE workspace_id = $1", workspace_id)
        await pool.close()


@pytest.mark.asyncio
async def test_repository_agent_definition_versions_round_trip_active_projection():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    now = datetime.now(timezone.utc)
    owner_id = uuid4()
    repo_id = uuid4()
    agent_id = uuid4()
    version_id = uuid4()
    agent_key = f"it-agent-{uuid4().hex[:8]}"
    agent = AgentDefinition(
        agent_id=agent_id,
        agent_key=agent_key,
        display_name="Integration Git Agent",
        description="Git-managed repository integration agent.",
        role="agent_admin",
        capabilities=["agent_catalog"],
        endpoint=AgentEndpoint(kind="remote", model="gpt-5.4"),
        system_prompt="Publish carefully.",
        harness=AgentHarness(summary="Integration harness."),
        interaction_contract=build_default_interaction_contract(
            display_name="Integration Git Agent",
            role="agent_admin",
            description="Git-managed repository integration agent.",
            capabilities=["agent_catalog"],
        ),
        definition={"source": "git"},
        created_by=owner_id,
        created_at=now,
        updated_at=now,
        metadata={"source": "git"},
    )
    git_repo = GitRepository(
        repo_id=repo_id,
        scope="global",
        organization_id=None,
        workspace_id=None,
        name=f"it-agent-defs-{uuid4().hex[:8]}",
        local_path="/tmp/it-agent-defs",
        default_branch="main",
        created_by=owner_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    version = AgentDefinitionVersion(
        agent_version_id=version_id,
        agent_id=agent_id,
        version=1,
        scope="global",
        organization_id=None,
        agent_key=agent_key,
        git_repository_id=repo_id,
        git_commit_sha="abc123",
        bundle_path="agents/integration",
        manifest_sha256="manifest",
        compiled_definition=agent.model_dump(mode="json"),
        published_by=owner_id,
        published_at=now,
        metadata={"source": "integration-test"},
    )

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.upsert_git_repository(conn, git_repo)
                await repository.upsert_system_agent(conn, agent)
                await repository.upsert_agent_definition_version(conn, version)
                await repository.upsert_system_agent(
                    conn,
                    agent.model_copy(
                        update={
                            "active_agent_version_id": version_id,
                            "metadata": {
                                **agent.metadata,
                                "active_agent_version_id": str(version_id),
                            },
                        }
                    ),
                )

        fetched_agent = await repository.fetch_system_agent(agent_id)
        by_key = await repository.fetch_system_agent_by_key(
            scope="global",
            organization_id=None,
            agent_key=agent_key,
        )
        versions = await repository.list_agent_definition_versions(agent_id)
        by_source = await repository.fetch_agent_definition_version_by_source(
            agent_id=agent_id,
            git_repository_id=repo_id,
            git_commit_sha="abc123",
            bundle_path="agents/integration",
        )

        assert fetched_agent is not None
        assert fetched_agent.agent_key == agent_key
        assert fetched_agent.active_agent_version_id == version_id
        assert by_key is not None
        assert by_key.agent_id == agent_id
        assert [item.agent_version_id for item in versions] == [version_id]
        assert by_source is not None
        assert by_source.manifest_sha256 == "manifest"
        assert by_source.compiled_definition["agent_key"] == agent_key
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM system_agents WHERE agent_id = $1", agent_id)
            await conn.execute("DELETE FROM git_repositories WHERE repo_id = $1", repo_id)
        await pool.close()


@pytest.mark.asyncio
async def test_repository_appends_and_verifies_audit_chain():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    first_event_id = uuid4()
    second_event_id = uuid4()
    chain_partition = f"workspace:{uuid4()}"
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                first = await repository.append_audit_event(
                    conn,
                    AuditEventDraft(
                        audit_event_id=first_event_id,
                        scope_type="workspace",
                        actor_type="system",
                        source_service="integration-test",
                        source_component="repository",
                        action_category="workspace",
                        action_name="workspace.created",
                        outcome="success",
                        metadata={"test": "first"},
                        chain_partition=chain_partition,
                    ),
                )
                second = await repository.append_audit_event(
                    conn,
                    AuditEventDraft(
                        audit_event_id=second_event_id,
                        scope_type="workspace",
                        actor_type="system",
                        source_service="integration-test",
                        source_component="repository",
                        action_category="workspace",
                        action_name="workspace.updated",
                        outcome="success",
                        metadata={"test": "second"},
                        chain_partition=chain_partition,
                    ),
                )

        assert first.chain_sequence == 1
        assert first.prev_hash == "0" * 64
        assert second.chain_sequence == 2
        assert second.prev_hash == first.event_hash

        verification = await repository.verify_audit_chain(chain_partition)
        assert verification.verified is True
        assert verification.checked_events == 2

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE audit_event_ledger
                SET event_hash = $2
                WHERE audit_event_id = $1
                """,
                second_event_id,
                "f" * 64,
            )

        tampered = await repository.verify_audit_chain(chain_partition)
        assert tampered.verified is False
        assert tampered.failing_audit_event_id == second_event_id
        assert tampered.detail == "Audit chain event hash mismatch"
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM audit_event_ledger WHERE audit_event_id IN ($1, $2)",
                first_event_id,
                second_event_id,
            )
            await conn.execute(
                "DELETE FROM audit_chain_heads WHERE chain_partition = $1",
                chain_partition,
            )
        await pool.close()


@pytest.mark.asyncio
async def test_repository_verifies_retained_audit_chain_with_snapshot():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    first_event_id = uuid4()
    second_event_id = uuid4()
    chain_partition = f"workspace:{uuid4()}"
    cutoff = datetime.now(timezone.utc)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                first = await repository.append_audit_event(
                    conn,
                    AuditEventDraft(
                        audit_event_id=first_event_id,
                        scope_type="workspace",
                        actor_type="system",
                        source_service="integration-test",
                        source_component="repository",
                        action_category="workspace",
                        action_name="workspace.created",
                        outcome="success",
                        metadata={"test": "first"},
                        chain_partition=chain_partition,
                    ),
                )
                second = await repository.append_audit_event(
                    conn,
                    AuditEventDraft(
                        audit_event_id=second_event_id,
                        scope_type="workspace",
                        actor_type="system",
                        source_service="integration-test",
                        source_component="repository",
                        action_category="workspace",
                        action_name="workspace.updated",
                        outcome="success",
                        metadata={"test": "second"},
                        chain_partition=chain_partition,
                    ),
                )
                await repository.record_audit_retention_snapshot(
                    conn,
                    chain_partition=chain_partition,
                    cutoff_recorded_at=cutoff,
                    last_pruned_sequence=first.chain_sequence,
                    last_pruned_event_hash=first.event_hash,
                    object_key="audit/retention/test.jsonl",
                    metadata={"event_count": 1},
                )
                await repository.prune_audit_events(
                    conn,
                    chain_partition=chain_partition,
                    max_ledger_offset=first.ledger_offset,
                )

        verification = await repository.verify_audit_chain(chain_partition)
        assert verification.verified is True
        assert verification.checked_events == 1
    finally:
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM audit_event_ledger WHERE audit_event_id IN ($1, $2)",
                first_event_id,
                second_event_id,
            )
            await conn.execute(
                "DELETE FROM audit_retention_snapshots WHERE chain_partition = $1",
                chain_partition,
            )
            await conn.execute(
                "DELETE FROM audit_chain_heads WHERE chain_partition = $1",
                chain_partition,
            )
        await pool.close()
