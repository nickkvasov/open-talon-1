from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "gateway-edge",
    ROOT / "packages" / "contracts",
    ROOT / "tests" / "infrastructure",
):
    path_string = str(path)
    if path_string not in sys.path:
        sys.path.insert(0, path_string)

from open_talon_contracts.secrets import EnvironmentSecretProvider, SecretResolver  # noqa: E402
from gateway_edge.models import (  # noqa: E402
    ResearchDossierConcept,
    ResearchDossierNote,
    ResearchDossierNotebook,
    ResearchDossierNotebookDetail,
    ResearchDossierProviderBinding,
)
from gateway_edge.services.dossier_notebook_provider import (  # noqa: E402
    XWikiDossierNotebookProvider,
)
from operational_agents_live.helpers import (  # noqa: E402
    admin_token,
    direct_access_grants_enabled,
    gateway_url,
    human_client_id,
    json_request,
    live_actor,
)


pytestmark = pytest.mark.integration


def _require_xwiki_live() -> None:
    if os.getenv("OPEN_TALON_RUN_XWIKI_LIVE") != "1":
        pytest.skip("Set OPEN_TALON_RUN_XWIKI_LIVE=1 to run live XWiki tests")


def _require_xwiki_credentials() -> tuple[str, str]:
    username = os.getenv("OPEN_TALON_XWIKI_USERNAME")
    password = os.getenv("OPEN_TALON_XWIKI_PASSWORD")
    if not username or not password:
        pytest.skip(
            "Set OPEN_TALON_XWIKI_USERNAME and OPEN_TALON_XWIKI_PASSWORD to run "
            "mutating live XWiki tests"
        )
    return username, password


def _xwiki_base_url() -> str:
    return os.getenv("OPEN_TALON_XWIKI_BASE_URL", "http://127.0.0.1:8083").rstrip("/")


def _xwiki_wiki_name() -> str:
    return os.getenv("OPEN_TALON_XWIKI_WIKI_NAME", "xwiki").strip("/") or "xwiki"


def _assert_xwiki_ready(base_url: str) -> None:
    last_error = "not attempted"
    for path in ("/", "/bin/view/Main/"):
        try:
            response = httpx.get(f"{base_url}{path}", timeout=10.0, follow_redirects=False)
            if response.status_code in {200, 302, 401}:
                return
            last_error = f"{response.status_code} {response.text[:200]}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
    pytest.skip(f"XWiki is not reachable at {base_url}: {last_error}")


def _assert_gateway_ready(base_url: str) -> None:
    try:
        response = httpx.get(f"{base_url}/health", timeout=10.0)
    except httpx.HTTPError as exc:
        pytest.skip(f"Gateway is not reachable at {base_url}: {exc}")
    if response.status_code != 200:
        pytest.skip(f"Gateway is not healthy at {base_url}: {response.status_code}")


def _xwiki_page_rest_url(
    *,
    base_url: str,
    wiki_name: str,
    dossier_slug: str,
    page_ref_suffix: str,
) -> str:
    ref_parts = [part for part in page_ref_suffix.split(".") if part]
    page = ref_parts[-1]
    nested_spaces = ref_parts[:-1]
    path = f"{base_url}/rest/wikis/{wiki_name}/spaces/Dossiers/spaces/{dossier_slug}"
    for space in nested_spaces:
        path += f"/spaces/{space}"
    return f"{path}/pages/{page}"


@pytest.mark.asyncio
async def test_xwiki_dossier_provider_live_syncs_concept_notebook_pages() -> None:
    _require_xwiki_live()
    username, password = _require_xwiki_credentials()
    base_url = _xwiki_base_url()
    wiki_name = _xwiki_wiki_name()
    _assert_xwiki_ready(base_url)

    now = datetime.now(timezone.utc)
    owner_id = uuid4()
    organization_id = uuid4()
    dossier_id = uuid4()
    notebook_id = uuid4()
    slug = f"live-{uuid4().hex[:10]}"
    binding = ResearchDossierProviderBinding(
        binding_id=uuid4(),
        notebook_id=notebook_id,
        dossier_id=dossier_id,
        organization_id=organization_id,
        provider_kind="xwiki",
        provider_key="xwiki",
        external_space_ref=f"Dossiers.{slug}",
        external_base_url=base_url,
        config={"wiki_name": wiki_name},
        secret_config={
            "username": {"env": {"name": "OPEN_TALON_XWIKI_USERNAME"}},
            "password": {"env": {"name": "OPEN_TALON_XWIKI_PASSWORD"}},
        },
        created_by=owner_id,
        updated_by=owner_id,
        created_at=now,
        updated_at=now,
    )
    note = ResearchDossierNote(
        note_id=uuid4(),
        notebook_id=notebook_id,
        dossier_id=dossier_id,
        organization_id=organization_id,
        note_kind="home",
        status="active",
        slug="home",
        title="Live XWiki Dossier",
        summary="Live sync smoke test for an Open Talon concept dossier.",
        body="This page was written through the DossierNotebookProvider abstraction.",
        citation_ids=["S1"],
        external_page_ref=f"Dossiers.{slug}.WebHome",
        created_by=owner_id,
        updated_by=owner_id,
        created_at=now,
        updated_at=now,
    )
    concept = ResearchDossierConcept(
        concept_id=uuid4(),
        notebook_id=notebook_id,
        dossier_id=dossier_id,
        organization_id=organization_id,
        slug="concept-graph",
        name="Concept Graph",
        definition="A navigable knowledge structure persisted into XWiki.",
        status="active",
        confidence=0.9,
        created_by=owner_id,
        updated_by=owner_id,
        created_at=now,
        updated_at=now,
    )
    detail = ResearchDossierNotebookDetail(
        notebook=ResearchDossierNotebook(
            notebook_id=notebook_id,
            dossier_id=dossier_id,
            organization_id=organization_id,
            provider_kind="xwiki",
            provider_key="xwiki",
            status="created",
            home_note_id=note.note_id,
            external_space_ref=binding.external_space_ref,
            created_by=owner_id,
            updated_by=owner_id,
            created_at=now,
            updated_at=now,
        ),
        provider_bindings=[binding],
        notes=[note],
        concepts=[concept],
    )

    result = await XWikiDossierNotebookProvider(
        timeout_seconds=30.0,
        secret_resolver=SecretResolver([EnvironmentSecretProvider()]),
    ).sync(detail=detail, binding=binding)

    assert result.status == "completed"
    assert result.pages_synced == 2
    assert result.pages_failed == 0
    assert f"Dossiers.{slug}.WebHome" in result.page_refs
    page_response = httpx.get(
        f"{base_url}/rest/wikis/{wiki_name}/spaces/Dossiers/spaces/{slug}/pages/WebHome",
        auth=(username, password),
        headers={"Accept": "application/xml"},
        timeout=20.0,
    )
    page_response.raise_for_status()
    assert "Live XWiki Dossier" in page_response.text


def test_gateway_methodology_blueprint_live_syncs_real_xwiki_space() -> None:
    _require_xwiki_live()
    username, password = _require_xwiki_credentials()
    xwiki_base_url = _xwiki_base_url()
    wiki_name = _xwiki_wiki_name()
    gateway = gateway_url()
    _assert_xwiki_ready(xwiki_base_url)
    _assert_gateway_ready(gateway)

    client_id = human_client_id()
    suffix = uuid4().hex[:10]
    with direct_access_grants_enabled(client_id=client_id):
        token = admin_token(client_id=client_id)
        actor = live_actor(display_name="XWiki live dossier tester")
        organization = json_request(
            "POST",
            f"{gateway}/v1/organizations",
            token=token,
            payload={
                "actor": actor,
                "slug": f"xwiki-dossier-live-{suffix}",
                "name": f"XWiki Dossier Live {suffix}",
                "description": "Temporary organization for the real XWiki live dossier test.",
            },
        )
        organization_id = organization["organization_id"]
        detail = json_request(
            "POST",
            f"{gateway}/v1/organizations/{organization_id}/methodology/blueprints",
            token=token,
            payload={
                "actor": actor,
                "title": f"XWiki live concept dossier {suffix}",
                "topic": "Real XWiki dossier sync live test",
                "target_goal": "Create a navigable XWiki-backed concept dossier.",
                "tasks": [
                    "Create canonical dossier metadata in Open Talon.",
                    "Project managed concept pages into XWiki.",
                    "Read back the XWiki pages through the real REST API.",
                ],
                "library_ids": [],
            },
        )
        dossier_id = detail["dossier"]["dossier_id"]
        notebook = json_request(
            "GET",
            f"{gateway}/v1/organizations/{organization_id}/methodology/dossiers/{dossier_id}/notebook",
            token=token,
        )
        binding = notebook["provider_bindings"][0]
        dossier_slug = notebook["notebook"]["metadata"]["dossier_slug"]
        assert binding["provider_kind"] == "xwiki"
        assert binding["external_base_url"].rstrip("/") == xwiki_base_url
        assert binding["config"]["wiki_name"] == wiki_name
        assert notebook["notebook"]["external_space_ref"] == f"Dossiers.{dossier_slug}"

        sync_run = json_request(
            "POST",
            f"{gateway}/v1/organizations/{organization_id}/methodology/dossiers/{dossier_id}/sync",
            token=token,
            payload={
                "actor": actor,
                "provider_key": "xwiki",
                "force": True,
                "metadata": {"test": "live_real_xwiki_gateway_sync"},
            },
            timeout=60.0,
        )
        assert sync_run["status"] == "completed", sync_run
        assert sync_run["stats"]["provider_kind"] == "xwiki"
        assert sync_run["stats"]["provider_key"] == "xwiki"
        assert sync_run["stats"]["pages_synced"] >= 9
        assert sync_run["stats"]["pages_failed"] == 0

        refreshed = json_request(
            "GET",
            f"{gateway}/v1/organizations/{organization_id}/methodology/dossiers/{dossier_id}/notebook",
            token=token,
        )
        assert refreshed["notebook"]["status"] == "ready"
        assert refreshed["provider_bindings"][0]["status"] == "ready"
        assert refreshed["provider_bindings"][0]["last_sync_at"] is not None

    page_expectations = {
        "WebHome": ["Home", dossier_id],
        "Sources.WebHome": ["Sources", dossier_id],
        "Concepts.WebHome": ["Concepts", dossier_id],
        "Contradictions.WebHome": ["Contradictions", dossier_id],
        "Gaps.WebHome": ["Gaps", dossier_id],
        "Synthesis.WebHome": ["Synthesis", dossier_id],
    }
    for page_ref_suffix, expected_fragments in page_expectations.items():
        response = httpx.get(
            _xwiki_page_rest_url(
                base_url=xwiki_base_url,
                wiki_name=wiki_name,
                dossier_slug=dossier_slug,
                page_ref_suffix=page_ref_suffix,
            ),
            auth=(username, password),
            headers={"Accept": "application/xml"},
            timeout=20.0,
        )
        response.raise_for_status()
        for fragment in expected_fragments:
            assert fragment in response.text
