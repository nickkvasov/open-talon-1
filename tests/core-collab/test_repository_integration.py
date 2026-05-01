from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
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
    CreateMethodologyBlueprintRequest,
    CreateResearchDossierSourceRequest,
    GitRepository,
    Library,
    LlmProviderDefinition,
    McpPromptDefinition,
    McpResourceDefinition,
    McpServerDefinition,
    McpToolDefinition,
    NavigateResearchDossierRequest,
    Organization,
    OrganizationMembership,
    ParticipantInput,
    Project,
    ProjectAccessBinding,
    RequestMcpServerSyncRequest,
    ResolvedAssetBinding,
    SubmitResearchDossierHealthCheckRequest,
    SyncResearchDossierNotebookRequest,
    UpsertResearchDossierClaimRequest,
    UpsertResearchDossierConceptRequest,
    UpsertResearchDossierLinkRequest,
    UpsertResearchDossierNoteRequest,
    Workspace,
    WorkspaceHarness,
    WorkspaceMethodology,
    WorkspaceAsset,
    WorkspaceAssetVersion,
    WorkspaceMcpServer,
)
from support.model_constants import TEST_EXPLICIT_OLLAMA_MODEL
from core_collab.kernel import CollaborationKernel
from core_collab.migrations import apply_pending_migrations
from core_collab.repository import CollaborationRepository, UserRecord
from core_collab.system_defaults import (
    DEFAULT_ORGANIZATION_ID,
    ManagedSystemDefaultsRepairer,
)


pytestmark = pytest.mark.integration


def _postgres_dsn() -> str:
    return (
        os.getenv("OPEN_TALON_TEST_POSTGRES_DSN")
        or "postgresql://"
        f"{os.getenv('POSTGRES_USER', 'admin')}:{os.getenv('POSTGRES_PASSWORD', 'password')}"
        f"@{os.getenv('POSTGRES_HOST', '127.0.0.1')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB', 'app_db')}"
    )


def _dsn_with_database(dsn: str, database: str) -> str:
    parsed = urlsplit(dsn)
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"/{database}",
            parsed.query,
            parsed.fragment,
        )
    )


@pytest.mark.asyncio
async def test_fresh_database_migration_chain_builds_xwiki_dossier_schema():
    source_dsn = _postgres_dsn()
    admin_dsn = _dsn_with_database(
        source_dsn,
        os.getenv("OPEN_TALON_TEST_POSTGRES_MAINTENANCE_DB", "postgres"),
    )
    database_name = f"open_talon_migration_xwiki_{uuid4().hex[:12]}"
    admin_conn: asyncpg.Connection | None = None
    pool: asyncpg.Pool | None = None
    try:
        admin_conn = await asyncpg.connect(dsn=admin_dsn)
        await admin_conn.execute(f'CREATE DATABASE "{database_name}" TEMPLATE template0')
        await admin_conn.close()
        admin_conn = None
        pool = await asyncpg.create_pool(
            dsn=_dsn_with_database(source_dsn, database_name),
            min_size=1,
            max_size=2,
        )
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Fresh Postgres migration-chain test unavailable: {exc}")
    try:
        await apply_pending_migrations(pool)
        async with pool.acquire() as conn:
            tables = {
                row["table_name"]
                for row in await conn.fetch(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name LIKE 'research_dossier%'
                    """
                )
            }
            expected_tables = {
                "research_dossiers",
                "research_dossier_sources",
                "research_dossier_events",
                "research_dossier_notebooks",
                "research_dossier_notes",
                "research_dossier_concepts",
                "research_dossier_claims",
                "research_dossier_links",
                "research_dossier_provider_bindings",
                "research_dossier_provider_external_refs",
                "research_dossier_sync_runs",
                "research_dossier_health_checks",
            }
            assert expected_tables.issubset(tables)
            seeded_agents = {
                row["agent_key"]
                for row in await conn.fetch(
                    """
                    SELECT agent_key
                    FROM system_agents
                    WHERE agent_key IN ('researcher', 'methodologist')
                    """
                )
            }
            assert seeded_agents == {"researcher", "methodologist"}
            private_tools = {
                row["tool_name"]
                for row in await conn.fetch(
                    """
                    SELECT DISTINCT tool_name
                    FROM (
                        SELECT jsonb_array_elements_text(tool_allowlist) AS tool_name
                        FROM agent_internal_mcp_servers
                    ) AS allowed_tools
                    WHERE tool_name IN (
                        'methodology.dossiers.notes.upsert',
                        'methodology.dossiers.concepts.upsert',
                        'methodology.dossiers.navigate',
                        'methodology.dossiers.sync',
                        'methodology.blueprints.submit_draft'
                    )
                    """
                )
            }
            assert {
                "methodology.dossiers.notes.upsert",
                "methodology.dossiers.concepts.upsert",
                "methodology.dossiers.navigate",
                "methodology.dossiers.sync",
                "methodology.blueprints.submit_draft",
            }.issubset(private_tools)
    finally:
        if pool is not None:
            await pool.close()
        try:
            admin_conn = admin_conn or await asyncpg.connect(dsn=admin_dsn)
            await admin_conn.execute(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        except Exception:
            pass
        finally:
            if admin_conn is not None and not admin_conn.is_closed():
                await admin_conn.close()


@pytest.mark.asyncio
async def test_repository_methodology_dossier_notebook_round_trips():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    try:
        await apply_pending_migrations(pool)
        await ManagedSystemDefaultsRepairer(repository).repair()
        kernel = CollaborationKernel(repository)
        organization = await repository.fetch_organization(DEFAULT_ORGANIZATION_ID)
        assert organization is not None
        actor = ParticipantInput(
            participant_id=organization.created_by,
            participant_type="user",
            user_id=organization.created_by,
            display_name="Repository Methodology Owner",
        )
        blueprint_result = await kernel.create_methodology_blueprint(
            organization.organization_id,
            CreateMethodologyBlueprintRequest(
                actor=actor,
                title=f"Repository dossier {uuid4().hex[:8]}",
                topic="Evidence-backed repository integration dossier",
                target_goal="Exercise canonical dossier notebook persistence",
                tasks=["collect", "organize", "sync"],
            ),
        )
        assert blueprint_result.detail is not None
        dossier = blueprint_result.detail.dossier
        notebook_detail = await kernel.get_research_dossier_notebook_detail(
            dossier.dossier_id,
            actor=actor,
        )
        assert notebook_detail.notebook.provider_kind == "xwiki"
        assert notebook_detail.provider_bindings[0].provider_key == "xwiki"
        assert {note.slug for note in notebook_detail.notes}.issuperset(
            {"home", "sources", "concepts", "synthesis"}
        )

        researcher = await repository.fetch_system_agent_by_key(
            scope="global",
            organization_id=None,
            agent_key="researcher",
        )
        assert researcher is not None
        assert dossier.operations_workspace_id is not None
        researcher_participant = await repository.fetch_agent_participant(
            dossier.operations_workspace_id,
            researcher.agent_id,
        )
        assert researcher_participant is not None
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
                title="Repository integration evidence",
                source_uri="https://example.test/repository-dossier-evidence",
                citation_id="S1",
                quality_notes="Stable fixture source for integration coverage.",
            ),
        )
        source = source_result.source
        assert source is not None
        assert source.discovered_by_system_agent_id == researcher.agent_id

        concept_result = await kernel.upsert_research_dossier_concept(
            dossier.dossier_id,
            UpsertResearchDossierConceptRequest(
                actor=agent_actor,
                slug="repository-evidence-loop",
                name="Repository Evidence Loop",
                definition="A concept persisted through the dossier notebook tables.",
                status="active",
                source_ids=[source.source_id],
            ),
        )
        concept = concept_result.concept
        assert concept is not None
        note_result = await kernel.upsert_research_dossier_note(
            dossier.dossier_id,
            UpsertResearchDossierNoteRequest(
                actor=agent_actor,
                note_kind="concept",
                status="active",
                slug="repository-evidence-loop-note",
                title="Repository Evidence Loop",
                body="Concept note tied to source S1.",
                concept_id=concept.concept_id,
                citation_ids=["S1"],
            ),
        )
        note = note_result.note
        assert note is not None
        claim_result = await kernel.upsert_research_dossier_claim(
            dossier.dossier_id,
            UpsertResearchDossierClaimRequest(
                actor=agent_actor,
                claim_key=f"claim:{uuid4().hex[:8]}",
                statement="Dossier notebooks preserve conceptual research structure.",
                status="supported",
                source_ids=[source.source_id],
                citation_ids=["S1"],
            ),
        )
        claim = claim_result.claim
        assert claim is not None
        link_result = await kernel.upsert_research_dossier_link(
            dossier.dossier_id,
            UpsertResearchDossierLinkRequest(
                actor=agent_actor,
                source_type="concept",
                source_ref_id=concept.concept_id,
                target_type="claim",
                target_ref_id=claim.claim_id,
                link_kind="supports",
                rationale="The concept supports the persisted claim.",
            ),
        )
        assert link_result.link is not None
        navigation = await kernel.navigate_research_dossier(
            dossier.dossier_id,
            NavigateResearchDossierRequest(
                actor=agent_actor,
                query="repository evidence",
            ),
        )
        assert [item.concept_id for item in navigation.concepts] == [concept.concept_id]
        health = await kernel.submit_research_dossier_health_check(
            dossier.dossier_id,
            SubmitResearchDossierHealthCheckRequest(
                actor=agent_actor,
                status="passed",
                summary="Repository notebook round-trip passed.",
            ),
        )
        sync = await kernel.sync_research_dossier_notebook(
            dossier.dossier_id,
            SyncResearchDossierNotebookRequest(
                actor=agent_actor,
                provider_key="xwiki",
            ),
            stats={"pages_synced": len(notebook_detail.notes) + 2},
        )
        fetched = await repository.fetch_research_dossier_notebook_detail(
            dossier.dossier_id
        )
        assert fetched is not None
        assert fetched.latest_health_check is not None
        assert fetched.latest_health_check.check_id == health.check_id
        assert fetched.notebook.status == "ready"
        assert fetched.provider_bindings[0].last_sync_at == sync.completed_at
        assert any(item.note_id == note.note_id for item in fetched.notes)
        assert any(item.concept_id == concept.concept_id for item in fetched.concepts)
        assert any(item.claim_id == claim.claim_id for item in fetched.claims)
        assert any(item.link_id == link_result.link.link_id for item in fetched.links)
    finally:
        await pool.close()


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
async def test_repository_mcp_sync_replaces_capabilities_and_workspace_plugin_metadata():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)
    kernel = CollaborationKernel(repository)

    now = datetime.now(timezone.utc)
    owner_id = uuid4()
    organization_id = uuid4()
    project_id = uuid4()
    workspace_id = uuid4()
    server_id = uuid4()
    organization = Organization(
        organization_id=organization_id,
        slug=f"system-plugin-repo-{organization_id.hex[:8]}",
        name="System Plugin Repository Integration",
        created_by=owner_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    project = Project(
        project_id=project_id,
        organization_id=organization_id,
        slug="system-plugin-project",
        name="System Plugin Project",
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
        name="System Plugin Workspace",
        description="Workspace for repository-backed plugin integration.",
        owner_user_id=owner_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    server = McpServerDefinition(
        server_id=server_id,
        scope="organization",
        organization_id=organization_id,
        server_key="repo_web_search",
        display_name="Repository Web Search",
        description="Repository integration System Plugin backing server.",
        transport_kind="streamable_http",
        config={"url": "http://127.0.0.1:8181/mcp"},
        trust_level="sandboxed",
        enabled=True,
        created_by=owner_id,
        created_at=now,
        updated_by=owner_id,
        updated_at=now,
        metadata={"system_plugin": {"backing_protocol": "mcp"}},
    )

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.upsert_user(
                    conn,
                    UserRecord(
                        user_id=owner_id,
                        display_name="Plugin Owner",
                        created_at=now,
                        updated_at=now,
                        metadata={},
                    ),
                )
                await repository.upsert_organization(conn, organization)
                await repository.upsert_organization_membership(
                    conn,
                    OrganizationMembership(
                        organization_id=organization_id,
                        user_id=owner_id,
                        role="owner",
                        joined_at=now,
                        updated_at=now,
                        metadata={},
                    ),
                )
                await repository.upsert_project(conn, project)
                await repository.upsert_workspace(conn, workspace)
                await repository.upsert_mcp_server(conn, server)

        requested = await kernel.request_mcp_server_sync(
            server_id,
            RequestMcpServerSyncRequest(
                actor=ParticipantInput(
                    participant_id=owner_id,
                    participant_type="user",
                    user_id=owner_id,
                    display_name="Plugin Owner",
                ),
                metadata={"source": "repository-integration"},
            ),
        )
        assert requested.server.last_sync_status == "queued"
        assert requested.job.metadata == {"source": "repository-integration"}

        claimed = await kernel.claim_next_mcp_server_sync_job(worker_id="repo-test-worker")
        assert claimed is not None
        assert claimed.server_id == server_id
        assert claimed.status == "claimed"
        running_server = await repository.fetch_mcp_server(server_id)
        assert running_server is not None
        assert running_server.last_sync_status == "running"

        completed = await kernel.complete_mcp_server_sync_job(
            claimed.job_id,
            worker_id="repo-test-worker",
            tools=[
                McpToolDefinition(
                    server_id=uuid4(),
                    tool_name="search",
                    display_name="Search",
                    description="Search the web.",
                    input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
                    output_schema={"type": "object"},
                    capability_hash="search-v1",
                    discovered_at=now,
                    metadata={"kind": "search"},
                ),
                McpToolDefinition(
                    server_id=uuid4(),
                    tool_name="fetch",
                    display_name="Fetch",
                    description="Fetch a URL.",
                    input_schema={"type": "object", "properties": {"url": {"type": "string"}}},
                    output_schema={"type": "object"},
                    capability_hash="fetch-v1",
                    discovered_at=now,
                    metadata={"kind": "fetch"},
                ),
            ],
            resources=[
                McpResourceDefinition(
                    server_id=uuid4(),
                    uri="ot://web-search/recent",
                    name="recent",
                    description="Recent web-search state.",
                    mime_type="application/json",
                    capability_hash="recent-v1",
                    discovered_at=now,
                    metadata={"kind": "resource"},
                )
            ],
            prompts=[
                McpPromptDefinition(
                    server_id=uuid4(),
                    prompt_name="summarize_search",
                    description="Summarize web-search results.",
                    arguments_schema={"type": "object"},
                    capability_hash="prompt-v1",
                    discovered_at=now,
                    metadata={"kind": "prompt"},
                )
            ],
            metadata={"validated": True},
        )
        assert completed.server.last_sync_status == "completed"
        assert completed.server.last_synced_at is not None
        assert completed.job.result == {
            "tool_count": 2,
            "resource_count": 1,
            "prompt_count": 1,
            "validated": True,
        }
        assert {tool.tool_name for tool in await repository.list_mcp_server_tools(server_id)} == {
            "fetch",
            "search",
        }

        replacement = await kernel.request_mcp_server_sync(
            server_id,
            RequestMcpServerSyncRequest(
                actor=ParticipantInput(
                    participant_id=owner_id,
                    participant_type="user",
                    user_id=owner_id,
                    display_name="Plugin Owner",
                ),
                metadata={"source": "replacement"},
            ),
        )
        replacement_claim = await kernel.claim_next_mcp_server_sync_job(
            worker_id="repo-test-worker"
        )
        assert replacement_claim is not None
        assert replacement_claim.job_id == replacement.job.job_id
        await kernel.complete_mcp_server_sync_job(
            replacement_claim.job_id,
            worker_id="repo-test-worker",
            tools=[
                McpToolDefinition(
                    server_id=uuid4(),
                    tool_name="search_and_fetch",
                    display_name="Search and Fetch",
                    description="Search then fetch top results.",
                    input_schema={"type": "object"},
                    output_schema={"type": "object"},
                    capability_hash="search-and-fetch-v1",
                    discovered_at=now,
                    metadata={"kind": "combined"},
                )
            ],
            resources=[],
            prompts=[],
        )
        assert [
            tool.tool_name for tool in await repository.list_mcp_server_tools(server_id)
        ] == ["search_and_fetch"]
        assert await repository.list_mcp_server_resources(server_id) == []
        assert await repository.list_mcp_server_prompts(server_id) == []

        failed_request = await kernel.request_mcp_server_sync(
            server_id,
            RequestMcpServerSyncRequest(
                actor=ParticipantInput(
                    participant_id=owner_id,
                    participant_type="user",
                    user_id=owner_id,
                    display_name="Plugin Owner",
                ),
                metadata={"source": "failure"},
            ),
        )
        failed_claim = await kernel.claim_next_mcp_server_sync_job(
            worker_id="repo-test-worker"
        )
        assert failed_claim is not None
        assert failed_claim.job_id == failed_request.job.job_id
        failed = await kernel.fail_mcp_server_sync_job(
            failed_claim.job_id,
            worker_id="repo-test-worker",
            error="MCP initialize failed",
        )
        assert failed.server.last_sync_status == "failed"
        assert failed.server.last_sync_error == "MCP initialize failed"
        assert failed.job.status == "failed"
        assert failed.job.error == "MCP initialize failed"
        assert [
            tool.tool_name for tool in await repository.list_mcp_server_tools(server_id)
        ] == ["search_and_fetch"]

        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.upsert_workspace_mcp_server(
                    conn,
                    workspace_id=workspace_id,
                    binding=WorkspaceMcpServer(
                        server_id=server_id,
                        server_key=server.server_key,
                        display_name=server.display_name,
                        description=server.description,
                        transport_kind=server.transport_kind,
                        trust_level=server.trust_level,
                        server_enabled=True,
                        enabled=True,
                        tools_enabled=True,
                        resources_enabled=False,
                        prompts_enabled=False,
                        sampling_enabled=False,
                        name_prefix="web_",
                        tool_allowlist=["search_and_fetch"],
                        tool_denylist=[],
                        resource_allowlist=[],
                        prompt_allowlist=[],
                        attached_by=owner_id,
                        attached_at=now,
                        updated_at=now,
                        metadata={
                            "persist_assets": False,
                            "asset_candidate_output": "disabled",
                        },
                    ),
                )

        attachments = await repository.list_workspace_mcp_servers(workspace_id)
        workspace_tools = await repository.list_workspace_mcp_tools(workspace_id)
        assert len(attachments) == 1
        assert attachments[0].server_id == server_id
        assert attachments[0].server_key == "repo_web_search"
        assert len(workspace_tools) == 1
        assert workspace_tools[0].exposed_name == "web_search_and_fetch"
        assert workspace_tools[0].remote_name == "search_and_fetch"
        assert workspace_tools[0].metadata["kind"] == "combined"
        assert workspace_tools[0].metadata["workspace_attachment"] == {
            "persist_assets": False,
            "asset_candidate_output": "disabled",
        }
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM workspace_mcp_servers WHERE workspace_id = $1", workspace_id)
            await conn.execute("DELETE FROM mcp_server_sync_jobs WHERE server_id = $1", server_id)
            await conn.execute("DELETE FROM mcp_server_tools WHERE server_id = $1", server_id)
            await conn.execute("DELETE FROM mcp_server_resources WHERE server_id = $1", server_id)
            await conn.execute("DELETE FROM mcp_server_prompts WHERE server_id = $1", server_id)
            await conn.execute("DELETE FROM mcp_servers WHERE server_id = $1", server_id)
            await conn.execute("DELETE FROM workspaces WHERE workspace_id = $1", workspace_id)
            await conn.execute("DELETE FROM projects WHERE project_id = $1", project_id)
            await conn.execute(
                "DELETE FROM organization_memberships WHERE organization_id = $1",
                organization_id,
            )
            await conn.execute("DELETE FROM organizations WHERE organization_id = $1", organization_id)
            await conn.execute("DELETE FROM users WHERE user_id = $1", owner_id)
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

        methodologist = await repository.fetch_system_agent(
            UUID("44444444-4444-4444-4444-444444444447")
        )
        assert methodologist is not None
        assert methodologist.agent_key == "methodologist"
        assert methodologist.display_name == "Methodologist"
        assert methodologist.role == "methodology extraction and workspace design agent"
        assert methodologist.endpoint.engine_id == "local-ollama"
        assert methodologist.endpoint.provider == "ollama"
        assert "extracts methodology basis" in " ".join(methodologist.capabilities)
        assert "Methodology Basis" in (
            methodologist.interaction_contract.response_contract.required_sections
        )
        assert "Workspace Template" in (
            methodologist.interaction_contract.response_contract.required_sections
        )
        assert methodologist.definition["runtime"]["engine_id"] == "local-ollama"
        assert methodologist.definition["output_targets"]["workspace_harness_fields"] == [
            "methodology",
            "methodics",
            "execution_rules",
            "metadata",
        ]
        conductor = await repository.fetch_system_agent(
            UUID("44444444-4444-4444-4444-444444444448")
        )
        assert conductor is not None
        assert conductor.agent_key == "conductor"
        assert conductor.display_name == "Conductor"
        assert conductor.role == "workspace methodics execution conductor"
        assert conductor.definition["task_routing"]["normal_message_fanout"] is False
        assert conductor.definition["task_routing"]["accepted_task_kinds"] == [
            "methodics_execution_start",
            "methodics_step_coordinate",
            "methodics_step_verify",
            "methodics_resource_review",
        ]
        conductor_tools = await repository.list_agent_internal_mcp_tools(
            conductor.agent_id
        )
        conductor_exposed = {tool.exposed_name for tool in conductor_tools}
        assert "control_plane__methodics.executions.get" in conductor_exposed
        assert "control_plane__methodics.resource_requests.create" in conductor_exposed
        assert "control_plane__methodics.assignments.create" in conductor_exposed
        assert "control_plane__methodics.steps.evaluate" in conductor_exposed
        assert "control_plane__methodics.executions.create" not in conductor_exposed
        conductor_roles = await repository.list_iam_role_definitions(
            subject_kind="agent",
            scope="global",
            organization_id=None,
        )
        conductor_role = next(
            role for role in conductor_roles if role.name == "workspace_conductor"
        )
        assert "methodics.execute" in conductor_role.permissions
        assert "methodics.admin" not in conductor_role.permissions
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
async def test_repository_libraries_allow_reused_slugs_across_owner_scopes():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    now = datetime.now(timezone.utc)
    organization_id = uuid4()
    owner_id = uuid4()
    project_a_id = uuid4()
    project_b_id = uuid4()
    workspace_a_id = uuid4()
    workspace_b_id = uuid4()

    organization = Organization(
        organization_id=organization_id,
        slug=f"library-it-{organization_id.hex[:8]}",
        name="Library Integration",
        created_by=owner_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    project_a = Project(
        project_id=project_a_id,
        organization_id=organization_id,
        slug="project-a",
        name="Project A",
        created_by=owner_id,
        creator_user_id=owner_id,
        owner_user_id=owner_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    project_b = Project(
        project_id=project_b_id,
        organization_id=organization_id,
        slug="project-b",
        name="Project B",
        created_by=owner_id,
        creator_user_id=owner_id,
        owner_user_id=owner_id,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    workspace_a = Workspace(
        workspace_id=workspace_a_id,
        organization_id=organization_id,
        project_id=project_a_id,
        name="Workspace A",
        created_at=now,
        updated_at=now,
    )
    workspace_b = Workspace(
        workspace_id=workspace_b_id,
        organization_id=organization_id,
        project_id=project_b_id,
        name="Workspace B",
        created_at=now,
        updated_at=now,
    )

    def _library(
        *,
        scope: str,
        project_id: UUID | None = None,
        workspace_id: UUID | None = None,
    ) -> Library:
        return Library(
            library_id=uuid4(),
            scope=scope,
            organization_id=organization_id,
            project_id=project_id,
            workspace_id=workspace_id,
            slug="references",
            name="References",
            created_by=owner_id,
            created_at=now,
            updated_by=owner_id,
            updated_at=now,
            metadata={},
        )

    libraries = [
        _library(scope="organization"),
        _library(scope="project", project_id=project_a_id),
        _library(scope="project", project_id=project_b_id),
        _library(scope="workspace", project_id=project_a_id, workspace_id=workspace_a_id),
        _library(scope="workspace", project_id=project_b_id, workspace_id=workspace_b_id),
    ]

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.upsert_organization(conn, organization)
                await repository.upsert_project(conn, project_a)
                await repository.upsert_project(conn, project_b)
                await repository.upsert_workspace(conn, workspace_a)
                await repository.upsert_workspace(conn, workspace_b)
                for library in libraries:
                    await repository.upsert_library(conn, library)

        assert len(
            await repository.list_libraries(
                scope="project",
                organization_id=organization_id,
                project_id=project_a_id,
            )
        ) == 1
        assert len(
            await repository.list_libraries(
                scope="workspace",
                organization_id=organization_id,
                project_id=project_a_id,
                workspace_id=workspace_a_id,
            )
        ) == 1

        with pytest.raises(asyncpg.UniqueViolationError):
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await repository.upsert_library(
                        conn,
                        _library(scope="project", project_id=project_a_id),
                    )
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM organizations WHERE organization_id = $1", organization_id)
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
