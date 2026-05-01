from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4
from unittest.mock import AsyncMock

import pytest

from gateway_edge.models import (
    MethodologyBlueprint,
    MethodologyBlueprintDetail,
    MethodologyBlueprintVersion,
    ResearchDossierGraph,
    ResearchDossierNavigationResult,
    ResearchDossierNote,
    ResearchDossierNotebook,
    ResearchDossierNotebookDetail,
    ResearchDossierProviderBinding,
    ResearchDossier,
    ResearchDossierSyncRun,
)


pytestmark = pytest.mark.asyncio


DEFAULT_ORGANIZATION_ID = UUID("11111111-1111-1111-1111-111111111111")


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
                research_dossier_id=dossier_id,
                created_by=actor_id,
                created_at=now,
                updated_at=now,
                metadata={},
            )
        ],
        dossier=ResearchDossier(
            dossier_id=dossier_id,
            blueprint_id=blueprint_id,
            version_id=version_id,
            organization_id=organization_id,
            retained_library_id=uuid4(),
            status="researching",
            topic="Onboarding methodology",
            tasks=["Discover", "Synthesize"],
            created_by=actor_id,
            created_at=now,
            updated_at=now,
            metadata={},
        ),
        sources=[],
    )


def _notebook_detail(dossier: ResearchDossier) -> ResearchDossierNotebookDetail:
    now = datetime.now(timezone.utc)
    notebook_id = uuid4()
    note = ResearchDossierNote(
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
    notebook = ResearchDossierNotebook(
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
    binding = ResearchDossierProviderBinding(
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
    return ResearchDossierNotebookDetail(
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


async def test_dossier_source_route_rejects_cross_org_dossier(
    client,
    mock_collaboration_service,
    actor_payload,
):
    wrong_org_detail = _blueprint_detail(organization_id=uuid4())
    dossier = wrong_org_detail.dossier
    mock_collaboration_service.get_research_dossier = AsyncMock(return_value=dossier)
    mock_collaboration_service.create_research_dossier_source = AsyncMock()

    response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/dossiers/{dossier.dossier_id}/sources",
        json={
            "actor": actor_payload,
            "source_kind": "webpage",
            "status": "included",
            "title": "External source",
        },
    )

    assert response.status_code == 404
    mock_collaboration_service.create_research_dossier_source.assert_not_awaited()


async def test_dossier_notebook_routes_call_scoped_services(
    client,
    mock_collaboration_service,
    actor_payload,
):
    detail = _blueprint_detail()
    dossier = detail.dossier
    notebook_detail = _notebook_detail(dossier)
    graph = ResearchDossierGraph(
        dossier_id=dossier.dossier_id,
        notebook_id=notebook_detail.notebook.notebook_id,
        nodes=[{"type": "note", "id": str(notebook_detail.notes[0].note_id)}],
        links=[],
    )
    navigation = ResearchDossierNavigationResult(
        dossier_id=dossier.dossier_id,
        notebook_id=notebook_detail.notebook.notebook_id,
        query="home",
        entry_notes=notebook_detail.notes,
    )
    sync_run = ResearchDossierSyncRun(
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
    mock_collaboration_service.get_research_dossier = AsyncMock(return_value=dossier)
    mock_collaboration_service.get_research_dossier_notebook_detail = AsyncMock(
        return_value=notebook_detail
    )
    mock_collaboration_service.get_research_dossier_graph = AsyncMock(
        return_value=graph
    )
    mock_collaboration_service.navigate_research_dossier = AsyncMock(
        return_value=navigation
    )
    mock_collaboration_service.sync_research_dossier_notebook = AsyncMock(
        return_value=sync_run
    )

    notebook_response = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/dossiers/{dossier.dossier_id}/notebook"
    )
    graph_response = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/dossiers/{dossier.dossier_id}/graph"
    )
    navigate_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/dossiers/{dossier.dossier_id}/navigate",
        json={"actor": actor_payload, "query": "home"},
    )
    sync_response = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/dossiers/{dossier.dossier_id}/sync",
        json={"actor": actor_payload, "provider_key": "xwiki", "force": True},
    )

    assert notebook_response.status_code == 200
    assert notebook_response.json()["notebook"]["provider_key"] == "xwiki"
    assert graph_response.status_code == 200
    assert graph_response.json()["nodes"][0]["type"] == "note"
    assert navigate_response.status_code == 200
    assert navigate_response.json()["entry_notes"][0]["slug"] == "home"
    assert sync_response.status_code == 200
    assert sync_response.json()["stats"]["pages_synced"] == 1
    mock_collaboration_service.get_research_dossier_notebook_detail.assert_awaited_once()
    mock_collaboration_service.get_research_dossier_graph.assert_awaited_once()
    mock_collaboration_service.navigate_research_dossier.assert_awaited_once()
    mock_collaboration_service.sync_research_dossier_notebook.assert_awaited_once()


async def test_dossier_notebook_route_rejects_cross_org_dossier(
    client,
    mock_collaboration_service,
):
    wrong_org_detail = _blueprint_detail(organization_id=uuid4())
    dossier = wrong_org_detail.dossier
    mock_collaboration_service.get_research_dossier = AsyncMock(return_value=dossier)
    mock_collaboration_service.get_research_dossier_notebook_detail = AsyncMock()

    response = await client.get(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/methodology/dossiers/{dossier.dossier_id}/notebook"
    )

    assert response.status_code == 404
    mock_collaboration_service.get_research_dossier_notebook_detail.assert_not_awaited()


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
