from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4
from unittest.mock import AsyncMock

import pytest

from gateway_edge.config import settings
from gateway_edge.models import (
    AuthContext,
    MethodologyBlueprint,
    MethodologyBlueprintDetail,
    MethodologyBlueprintVersion,
    MethodologyResearchKnowledgeComponent,
    MethodologyResearchState,
    OrganizationMembership,
    DossierClaim,
    DossierConcept,
    DossierEvent,
    DossierGraph,
    DossierLink,
    DossierNavigationResult,
    DossierNote,
    DossierNotebook,
    DossierNotebookDetail,
    DossierProviderBinding,
    Dossier,
    DossierSource,
    DossierSyncRun,
)


pytestmark = pytest.mark.asyncio


DEFAULT_ORGANIZATION_ID = UUID("11111111-1111-1111-1111-111111111111")


def _oidc_context(*, roles: list[str], user_id: UUID | None = None) -> AuthContext:
    return AuthContext(
        kind="oidc",
        user_id=user_id or uuid4(),
        issuer="http://issuer.test/realms/open-talon",
        subject="subject-123",
        email="nikolay@example.com",
        display_name="Nikolay",
        roles=roles,
        claims={"sub": "subject-123"},
    )


def _patch_oidc_tokens(monkeypatch, token_map: dict[str, AuthContext]) -> None:
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        return token_map.get(token)

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)


def _grant_organization_membership(
    mock_collaboration_service,
    *,
    organization_id: UUID,
    user_id: UUID,
    role: str,
) -> None:
    now = datetime.now(timezone.utc)
    membership = OrganizationMembership(
        organization_id=organization_id,
        user_id=user_id,
        role=role,
        joined_at=now,
        updated_at=now,
        metadata={},
    )
    mock_collaboration_service.organization_memberships.setdefault(
        str(organization_id),
        {},
    )[str(user_id)] = membership.model_dump(mode="json")


def _blueprint_detail(
    *,
    organization_id: UUID = DEFAULT_ORGANIZATION_ID,
    blueprint_id: UUID | None = None,
    version_id: UUID | None = None,
    dossier_id: UUID | None = None,
) -> MethodologyBlueprintDetail:
    now = datetime.now(timezone.utc)
    actor_id = uuid4()
    blueprint_id = blueprint_id or uuid4()
    version_id = version_id or uuid4()
    dossier_id = dossier_id or uuid4()
    return MethodologyBlueprintDetail(
        blueprint=MethodologyBlueprint(
            blueprint_id=blueprint_id,
            organization_id=organization_id,
            title="Evidence-backed onboarding",
            topic="Onboarding methodology",
            target_goal="Create a reusable onboarding workflow",
            tasks=["Discover", "Synthesize"],
            status="draft",
            created_by=actor_id,
            created_at=now,
            updated_at=now,
            metadata={},
        ),
        versions=[
            MethodologyBlueprintVersion(
                version_id=version_id,
                blueprint_id=blueprint_id,
                organization_id=organization_id,
                version_number=1,
                status="researching",
                dossier_id=dossier_id,
                created_by=actor_id,
                created_at=now,
                updated_at=now,
                metadata={},
            )
        ],
        dossier=Dossier(
            dossier_id=dossier_id,
            blueprint_id=blueprint_id,
            version_id=version_id,
            organization_id=organization_id,
            retained_library_id=uuid4(),
            status="scoping",
            topic="Onboarding methodology",
            tasks=["Discover", "Synthesize"],
            created_by=actor_id,
            created_at=now,
            updated_at=now,
            metadata={},
        ),
        sources=[],
    )


def _notebook_detail(dossier: Dossier) -> DossierNotebookDetail:
    now = datetime.now(timezone.utc)
    notebook_id = uuid4()
    note = DossierNote(
        note_id=uuid4(),
        notebook_id=notebook_id,
        dossier_id=dossier.dossier_id,
        organization_id=dossier.organization_id,
        note_kind="home",
        status="active",
        slug="home",
        title="Home",
        body="Dossier home.",
        created_by=dossier.created_by,
        updated_by=dossier.created_by,
        created_at=now,
        updated_at=now,
    )
    notebook = DossierNotebook(
        notebook_id=notebook_id,
        dossier_id=dossier.dossier_id,
        organization_id=dossier.organization_id,
        provider_kind="xwiki",
        provider_key="xwiki",
        status="created",
        home_note_id=note.note_id,
        external_space_ref="Dossiers.gateway-test",
        external_url="http://xwiki.test/bin/view/Dossiers/gateway-test/",
        created_by=dossier.created_by,
        updated_by=dossier.created_by,
        created_at=now,
        updated_at=now,
    )
    binding = DossierProviderBinding(
        binding_id=uuid4(),
        notebook_id=notebook_id,
        dossier_id=dossier.dossier_id,
        organization_id=dossier.organization_id,
        provider_kind="xwiki",
        provider_key="xwiki",
        external_space_ref="Dossiers.gateway-test",
        external_base_url="http://xwiki.test",
        created_by=dossier.created_by,
        updated_by=dossier.created_by,
        created_at=now,
        updated_at=now,
    )
    return DossierNotebookDetail(
        notebook=notebook,
        provider_bindings=[binding],
        notes=[note],
    )


async def test_create_methodology_blueprint_route_starts_dossier(
    client,
    mock_collaboration_service,
    actor_payload,
):
    detail = _blueprint_detail()
    mock_collaboration_service.create_methodology_blueprint = AsyncMock(
        return_value=detail
    )

    response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/blueprints",
        json={
            "actor": actor_payload,
            "title": "Evidence-backed onboarding",
            "topic": "Onboarding methodology",
            "target_goal": "Create a reusable onboarding workflow",
            "tasks": ["Discover", "Synthesize"],
            "library_ids": [],
        },
    )

    assert response.status_code == 200
    assert response.json()["dossier"]["dossier_id"] == str(
        detail.dossier.dossier_id
    )
    called_organization_id, called_payload = (
        mock_collaboration_service.create_methodology_blueprint.await_args.args
    )
    assert called_organization_id == DEFAULT_ORGANIZATION_ID
    assert called_payload.topic == "Onboarding methodology"
    assert called_payload.tasks == ["Discover", "Synthesize"]


async def test_methodology_research_state_and_request_routes_are_org_scoped(
    client,
    mock_collaboration_service,
    actor_payload,
):
    detail = _blueprint_detail()
    state = MethodologyResearchState(
        blueprint=detail.blueprint,
        active_or_latest_version=detail.versions[0],
        dossier=detail.dossier,
        sources=[],
        events=[],
        notebook=None,
        interaction_requests=[],
        knowledge_components=[
            MethodologyResearchKnowledgeComponent(
                component="research_plan",
                present=False,
            )
        ],
        search_turns=[],
        metadata={"can_request_research": True},
    )
    mock_collaboration_service.get_methodology_research_state = AsyncMock(
        return_value=state
    )
    mock_collaboration_service.get_methodology_blueprint_detail = AsyncMock(
        return_value=detail
    )
    mock_collaboration_service.create_methodology_research_request = AsyncMock(
        return_value=state
    )

    state_response = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/blueprints/{detail.blueprint.blueprint_id}/research-state"
    )
    request_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/blueprints/{detail.blueprint.blueprint_id}/research-requests",
        json={
            "actor": actor_payload,
            "instructions": "Run B2C market research web search and fill coverage.",
            "max_search_turns": 4,
            "required_components": ["research_plan", "synthesis"],
            "require_admin_ready_approval": True,
            "metadata": {"scenario": "b2c"},
        },
    )

    assert state_response.status_code == 200
    assert state_response.json()["metadata"]["can_request_research"] is True
    assert request_response.status_code == 200
    called_blueprint_id, called_payload = (
        mock_collaboration_service.create_methodology_research_request.await_args.args
    )
    assert called_blueprint_id == detail.blueprint.blueprint_id
    assert called_payload.instructions.startswith("Run B2C market research")
    assert called_payload.max_search_turns == 4
    assert called_payload.required_components == ["research_plan", "synthesis"]


async def test_dossier_source_route_rejects_cross_org_dossier(
    client,
    mock_collaboration_service,
    actor_payload,
):
    wrong_org_detail = _blueprint_detail(organization_id=uuid4())
    dossier = wrong_org_detail.dossier
    mock_collaboration_service.get_dossier = AsyncMock(return_value=dossier)
    mock_collaboration_service.create_dossier_source = AsyncMock()

    response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/sources",
        json={
            "actor": actor_payload,
            "source_kind": "webpage",
            "status": "included",
            "title": "External source",
        },
    )

    assert response.status_code == 404
    mock_collaboration_service.create_dossier_source.assert_not_awaited()


async def test_dossier_events_and_notebook_curation_routes_call_scoped_services(
    client,
    mock_collaboration_service,
    actor_payload,
):
    detail = _blueprint_detail()
    dossier = detail.dossier
    notebook_detail = _notebook_detail(dossier)
    now = datetime.now(timezone.utc)
    source = DossierSource(
        source_id=uuid4(),
        dossier_id=dossier.dossier_id,
        organization_id=dossier.organization_id,
        source_kind="webpage",
        status="included",
        title="B2C market research source",
        source_uri="https://example.test/b2c",
        created_at=now,
        updated_at=now,
    )
    event = DossierEvent(
        event_id=uuid4(),
        dossier_id=dossier.dossier_id,
        organization_id=dossier.organization_id,
        event_type="dossier.research_requested",
        created_at=now,
    )
    concept = DossierConcept(
        concept_id=uuid4(),
        notebook_id=notebook_detail.notebook.notebook_id,
        dossier_id=dossier.dossier_id,
        organization_id=dossier.organization_id,
        slug="b2c-demand",
        name="B2C demand",
        created_by=dossier.created_by,
        updated_by=dossier.created_by,
        created_at=now,
        updated_at=now,
    )
    claim = DossierClaim(
        claim_id=uuid4(),
        notebook_id=notebook_detail.notebook.notebook_id,
        dossier_id=dossier.dossier_id,
        organization_id=dossier.organization_id,
        statement="B2C demand should be triangulated.",
        created_by=dossier.created_by,
        updated_by=dossier.created_by,
        created_at=now,
        updated_at=now,
    )
    link = DossierLink(
        link_id=uuid4(),
        notebook_id=notebook_detail.notebook.notebook_id,
        dossier_id=dossier.dossier_id,
        organization_id=dossier.organization_id,
        source_type="concept",
        source_ref_id=concept.concept_id,
        target_type="claim",
        target_ref_id=claim.claim_id,
        created_by=dossier.created_by,
        updated_by=dossier.created_by,
        created_at=now,
        updated_at=now,
    )
    mock_collaboration_service.get_dossier = AsyncMock(return_value=dossier)
    mock_collaboration_service.list_dossier_events = AsyncMock(return_value=[event])
    mock_collaboration_service.update_dossier_source = AsyncMock(return_value=source)
    mock_collaboration_service.upsert_dossier_note = AsyncMock(
        return_value=notebook_detail.notes[0]
    )
    mock_collaboration_service.upsert_dossier_concept = AsyncMock(return_value=concept)
    mock_collaboration_service.upsert_dossier_claim = AsyncMock(return_value=claim)
    mock_collaboration_service.upsert_dossier_link = AsyncMock(return_value=link)

    events_response = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/events"
    )
    source_response = await client.patch(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/sources/{source.source_id}",
        json={"actor": actor_payload, "status": "included"},
    )
    note_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/notes",
        json={
            "actor": actor_payload,
            "note_kind": "synthesis",
            "status": "active",
            "slug": "b2c-synthesis",
            "title": "B2C synthesis",
            "metadata": {"knowledge_component": "synthesis"},
        },
    )
    concept_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/concepts",
        json={
            "actor": actor_payload,
            "slug": "b2c-demand",
            "name": "B2C demand",
        },
    )
    claim_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/claims",
        json={
            "actor": actor_payload,
            "statement": "B2C demand should be triangulated.",
        },
    )
    link_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/links",
        json={
            "actor": actor_payload,
            "source_type": "concept",
            "source_ref_id": str(concept.concept_id),
            "target_type": "claim",
            "target_ref_id": str(claim.claim_id),
            "link_kind": "supports",
        },
    )

    assert events_response.status_code == 200
    assert events_response.json()[0]["event_type"] == "dossier.research_requested"
    assert source_response.status_code == 200
    assert note_response.status_code == 200
    assert concept_response.status_code == 200
    assert claim_response.status_code == 200
    assert link_response.status_code == 200
    mock_collaboration_service.list_dossier_events.assert_awaited_once()
    mock_collaboration_service.update_dossier_source.assert_awaited_once()
    mock_collaboration_service.upsert_dossier_note.assert_awaited_once()
    mock_collaboration_service.upsert_dossier_concept.assert_awaited_once()
    mock_collaboration_service.upsert_dossier_claim.assert_awaited_once()
    mock_collaboration_service.upsert_dossier_link.assert_awaited_once()


async def test_dossier_notebook_routes_call_scoped_services(
    client,
    mock_collaboration_service,
    actor_payload,
):
    detail = _blueprint_detail()
    dossier = detail.dossier
    notebook_detail = _notebook_detail(dossier)
    graph = DossierGraph(
        dossier_id=dossier.dossier_id,
        notebook_id=notebook_detail.notebook.notebook_id,
        nodes=[{"type": "note", "id": str(notebook_detail.notes[0].note_id)}],
        links=[],
    )
    navigation = DossierNavigationResult(
        dossier_id=dossier.dossier_id,
        notebook_id=notebook_detail.notebook.notebook_id,
        query="home",
        entry_notes=notebook_detail.notes,
    )
    sync_run = DossierSyncRun(
        sync_run_id=uuid4(),
        binding_id=notebook_detail.provider_bindings[0].binding_id,
        notebook_id=notebook_detail.notebook.notebook_id,
        dossier_id=dossier.dossier_id,
        organization_id=dossier.organization_id,
        status="completed",
        stats={"pages_synced": 1},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_collaboration_service.get_dossier = AsyncMock(return_value=dossier)
    mock_collaboration_service.get_dossier_notebook_detail = AsyncMock(
        return_value=notebook_detail
    )
    mock_collaboration_service.get_dossier_graph = AsyncMock(
        return_value=graph
    )
    mock_collaboration_service.navigate_dossier = AsyncMock(
        return_value=navigation
    )
    mock_collaboration_service.sync_dossier_notebook = AsyncMock(
        return_value=sync_run
    )
    mock_collaboration_service.transition_dossier_lifecycle = AsyncMock(
        return_value=dossier.model_copy(update={"status": "ready"})
    )

    notebook_response = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/notebook"
    )
    graph_response = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/graph"
    )
    navigate_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/navigate",
        json={"actor": actor_payload, "query": "home"},
    )
    sync_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/sync",
        json={"actor": actor_payload, "provider_key": "xwiki", "force": True},
    )
    lifecycle_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/lifecycle",
        json={
            "actor": actor_payload,
            "target_status": "ready",
            "summary": "Ready for synthesis.",
            "reason": "test",
        },
    )

    assert notebook_response.status_code == 200
    assert notebook_response.json()["notebook"]["provider_key"] == "xwiki"
    assert graph_response.status_code == 200
    assert graph_response.json()["nodes"][0]["type"] == "note"
    assert navigate_response.status_code == 200
    assert navigate_response.json()["entry_notes"][0]["slug"] == "home"
    assert sync_response.status_code == 200
    assert sync_response.json()["stats"]["pages_synced"] == 1
    assert lifecycle_response.status_code == 200
    assert lifecycle_response.json()["status"] == "ready"
    mock_collaboration_service.get_dossier_notebook_detail.assert_awaited_once()
    mock_collaboration_service.get_dossier_graph.assert_awaited_once()
    mock_collaboration_service.navigate_dossier.assert_awaited_once()
    mock_collaboration_service.sync_dossier_notebook.assert_awaited_once()
    mock_collaboration_service.transition_dossier_lifecycle.assert_awaited_once()


async def test_dossier_notebook_route_rejects_cross_org_dossier(
    client,
    mock_collaboration_service,
):
    wrong_org_detail = _blueprint_detail(organization_id=uuid4())
    dossier = wrong_org_detail.dossier
    mock_collaboration_service.get_dossier = AsyncMock(return_value=dossier)
    mock_collaboration_service.get_dossier_notebook_detail = AsyncMock()

    response = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/notebook"
    )

    assert response.status_code == 404
    mock_collaboration_service.get_dossier_notebook_detail.assert_not_awaited()


async def test_dossier_notebook_routes_enforce_permission_matrix_and_org_scope(
    client,
    mock_collaboration_service,
    actor_payload,
    monkeypatch,
):
    owner = _oidc_context(roles=[])
    member = _oidc_context(roles=[])
    outsider = _oidc_context(roles=[])
    _patch_oidc_tokens(
        monkeypatch,
        {
            "owner-token": owner,
            "member-token": member,
            "outsider-token": outsider,
        },
    )
    _grant_organization_membership(
        mock_collaboration_service,
        organization_id=DEFAULT_ORGANIZATION_ID,
        user_id=owner.user_id,
        role="owner",
    )
    _grant_organization_membership(
        mock_collaboration_service,
        organization_id=DEFAULT_ORGANIZATION_ID,
        user_id=member.user_id,
        role="member",
    )

    detail = _blueprint_detail()
    dossier = detail.dossier
    notebook_detail = _notebook_detail(dossier)
    graph = DossierGraph(
        dossier_id=dossier.dossier_id,
        notebook_id=notebook_detail.notebook.notebook_id,
        nodes=[{"type": "note", "id": str(notebook_detail.notes[0].note_id)}],
        links=[],
    )
    navigation = DossierNavigationResult(
        dossier_id=dossier.dossier_id,
        notebook_id=notebook_detail.notebook.notebook_id,
        query="home",
        entry_notes=notebook_detail.notes,
    )
    sync_run = DossierSyncRun(
        sync_run_id=uuid4(),
        binding_id=notebook_detail.provider_bindings[0].binding_id,
        notebook_id=notebook_detail.notebook.notebook_id,
        dossier_id=dossier.dossier_id,
        organization_id=dossier.organization_id,
        status="completed",
        stats={"pages_synced": 1},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    mock_collaboration_service.get_dossier = AsyncMock(return_value=dossier)
    mock_collaboration_service.get_dossier_notebook_detail = AsyncMock(
        return_value=notebook_detail
    )
    mock_collaboration_service.get_dossier_graph = AsyncMock(
        return_value=graph
    )
    mock_collaboration_service.navigate_dossier = AsyncMock(
        return_value=navigation
    )
    mock_collaboration_service.sync_dossier_notebook = AsyncMock(
        return_value=sync_run
    )

    owner_notebook = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/notebook",
        headers={"Authorization": "Bearer owner-token"},
    )
    member_graph = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/graph",
        headers={"Authorization": "Bearer member-token"},
    )
    member_navigate = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/navigate",
        headers={"Authorization": "Bearer member-token"},
        json={"actor": actor_payload, "query": "home"},
    )
    member_sync = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/sync",
        headers={"Authorization": "Bearer member-token"},
        json={"actor": actor_payload, "provider_key": "xwiki", "force": True},
    )
    owner_sync = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/sync",
        headers={"Authorization": "Bearer owner-token"},
        json={"actor": actor_payload, "provider_key": "xwiki", "force": True},
    )
    outsider_notebook = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{dossier.dossier_id}/notebook",
        headers={"Authorization": "Bearer outsider-token"},
    )

    assert owner_notebook.status_code == 200
    assert member_graph.status_code == 200
    assert member_navigate.status_code == 200
    assert member_sync.status_code == 403
    assert owner_sync.status_code == 200
    assert outsider_notebook.status_code == 404
    assert mock_collaboration_service.sync_dossier_notebook.await_count == 1

    wrong_org_dossier = _blueprint_detail(organization_id=uuid4()).dossier
    mock_collaboration_service.get_dossier = AsyncMock(
        return_value=wrong_org_dossier
    )
    mock_collaboration_service.get_dossier_graph = AsyncMock()
    cross_org_graph = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/dossiers/{wrong_org_dossier.dossier_id}/graph",
        headers={"Authorization": "Bearer owner-token"},
    )
    assert cross_org_graph.status_code == 404
    mock_collaboration_service.get_dossier_graph.assert_not_awaited()


async def test_methodology_read_routes_do_not_fabricate_actor_without_oidc(
    client,
    mock_collaboration_service,
):
    detail = _blueprint_detail()
    mock_collaboration_service.list_methodology_blueprints = AsyncMock(
        return_value=[detail.blueprint]
    )
    mock_collaboration_service.get_methodology_blueprint_detail = AsyncMock(
        return_value=detail
    )

    list_response = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/blueprints"
    )
    get_response = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/blueprints/{detail.blueprint.blueprint_id}"
    )

    assert list_response.status_code == 200
    assert get_response.status_code == 200
    assert mock_collaboration_service.list_methodology_blueprints.await_args.kwargs[
        "actor"
    ] is None
    assert mock_collaboration_service.get_methodology_blueprint_detail.await_args.kwargs[
        "actor"
    ] is None


async def test_methodology_version_create_and_archive_routes_are_org_scoped(
    client,
    mock_collaboration_service,
    actor_payload,
):
    detail = _blueprint_detail()
    blueprint_id = detail.blueprint.blueprint_id
    version_id = detail.versions[0].version_id
    mock_collaboration_service.get_methodology_blueprint_detail = AsyncMock(
        return_value=detail
    )
    mock_collaboration_service.create_methodology_blueprint_version = AsyncMock(
        return_value=detail
    )
    mock_collaboration_service.archive_methodology_blueprint = AsyncMock(
        return_value={
            "deleted": True,
            "blueprint_id": str(blueprint_id),
            "status": "archived",
        }
    )

    create_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/blueprints/{blueprint_id}/versions",
        json={
            "actor": actor_payload,
            "base_version_id": str(version_id),
            "cited_output": "# Edited methodology\n\nClaim [S1]",
            "harness_draft": {
                "summary": "Edited onboarding methodology.",
                "methodics": [],
                "execution_rules": [],
                "metadata": {},
            },
            "reason": "Human review edit.",
        },
    )
    archive_response = await client.request(
        "DELETE",
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/blueprints/{blueprint_id}",
        json={"actor": actor_payload, "metadata": {"archived_by_test": True}},
    )

    assert create_response.status_code == 200
    assert archive_response.status_code == 200
    called_blueprint_id, called_payload = (
        mock_collaboration_service.create_methodology_blueprint_version.await_args.args
    )
    assert called_blueprint_id == blueprint_id
    assert called_payload.base_version_id == version_id
    assert called_payload.reason == "Human review edit."
    mock_collaboration_service.archive_methodology_blueprint.assert_awaited_once()


async def test_methodology_version_create_and_archive_reject_cross_org_blueprint(
    client,
    mock_collaboration_service,
    actor_payload,
):
    wrong_org_detail = _blueprint_detail(organization_id=uuid4())
    blueprint_id = wrong_org_detail.blueprint.blueprint_id
    version_id = wrong_org_detail.versions[0].version_id
    mock_collaboration_service.get_methodology_blueprint_detail = AsyncMock(
        return_value=wrong_org_detail
    )
    mock_collaboration_service.create_methodology_blueprint_version = AsyncMock()
    mock_collaboration_service.archive_methodology_blueprint = AsyncMock()

    create_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/blueprints/{blueprint_id}/versions",
        json={
            "actor": actor_payload,
            "base_version_id": str(version_id),
            "cited_output": "# Edited methodology",
            "harness_draft": {"summary": "Edited methodology."},
        },
    )
    archive_response = await client.request(
        "DELETE",
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/blueprints/{blueprint_id}",
        json={"actor": actor_payload},
    )

    assert create_response.status_code == 404
    assert archive_response.status_code == 404
    mock_collaboration_service.create_methodology_blueprint_version.assert_not_awaited()
    mock_collaboration_service.archive_methodology_blueprint.assert_not_awaited()


async def test_methodology_review_and_apply_routes_preserve_human_gates(
    client,
    mock_collaboration_service,
    actor_payload,
):
    detail = _blueprint_detail()
    blueprint_id = detail.blueprint.blueprint_id
    version_id = detail.versions[0].version_id
    workspace_id = uuid4()
    mock_collaboration_service.review_methodology_blueprint_version = AsyncMock(
        side_effect=ValueError(
            "Cannot approve a methodology blueprint version without a harness draft"
        )
    )

    approve_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/blueprints/{blueprint_id}/versions/{version_id}/approve",
        json={"actor": actor_payload},
    )

    assert approve_response.status_code == 400

    mock_collaboration_service.get_methodology_blueprint_detail = AsyncMock(
        return_value=detail
    )
    mock_collaboration_service.apply_methodology_blueprint = AsyncMock(
        side_effect=PermissionError(
            "Workspace permission 'workspace.roles.write' required"
        )
    )

    apply_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/blueprints/{blueprint_id}/apply",
        json={
            "actor": actor_payload,
            "workspace_id": str(workspace_id),
            "version_id": str(version_id),
        },
    )

    assert apply_response.status_code == 403
