from __future__ import annotations

import os
import sys
from typing import Any
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
    form_request,
    gateway_url,
    human_client_id,
    initialize_mcp_session,
    json_request,
    live_actor,
    mcp_call,
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


def _xwiki_page_rest_url_from_ref(*, base_url: str, wiki_name: str, page_ref: str) -> str:
    ref_parts = [part for part in page_ref.split(".") if part]
    page = ref_parts[-1]
    spaces = ref_parts[:-1]
    path = f"{base_url}/rest/wikis/{wiki_name}"
    for space in spaces:
        path += f"/spaces/{space}"
    return f"{path}/pages/{page}"


def _cleanup_xwiki_page_refs(
    *,
    base_url: str,
    wiki_name: str,
    username: str,
    password: str,
    page_refs: list[str],
) -> None:
    for page_ref in reversed(list(dict.fromkeys(page_refs))):
        try:
            page_url = _xwiki_page_rest_url_from_ref(
                base_url=base_url,
                wiki_name=wiki_name,
                page_ref=page_ref,
            )
            response = httpx.delete(
                page_url,
                auth=(username, password),
                timeout=20.0,
            )
            if response.status_code in {200, 202, 204, 404}:
                continue
            httpx.put(
                page_url,
                auth=(username, password),
                headers={"Accept": "application/xml", "Content-Type": "application/xml"},
                content=(
                    '<page xmlns="http://www.xwiki.org">\n'
                    "  <title>Open Talon Live Test Cleanup</title>\n"
                    "  <syntax>xwiki/2.1</syntax>\n"
                    "  <content>Open Talon live-test cleanup marker. "
                    "Temporary content was removed after verification.</content>\n"
                    "</page>\n"
                ),
                timeout=20.0,
            ).raise_for_status()
        except Exception:
            # Cleanup must not hide the live workflow assertion that produced the page.
            pass


def _mcp_tool(
    gateway: str,
    token: str,
    session_id: str,
    *,
    name: str,
    arguments: dict[str, Any] | None = None,
    request_id: str,
) -> dict[str, Any]:
    payload, _ = mcp_call(
        gateway,
        token,
        method="tools/call",
        params={"name": name, "arguments": arguments or {}},
        session_id=session_id,
        request_id=request_id,
    )
    result = payload["result"]
    assert result["isError"] is False, result
    return result.get("structuredContent") or {}


def _client_credentials_token(*, client_id: str, client_secret: str) -> str:
    issuer = os.getenv(
        "OPEN_TALON_OIDC_ISSUER_URL",
        "http://127.0.0.1:8081/realms/open-talon",
    ).rstrip("/")
    payload = form_request(
        f"{issuer}/protocol/openid-connect/token",
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    return str(payload["access_token"])


def _provision_methodology_agent_token(
    *,
    gateway: str,
    admin_access_token: str,
    organization_id: str,
    actor: dict[str, Any],
    agent_key: str,
    suffix: str,
) -> str:
    role = (
        "evidence discovery and research dossier agent"
        if agent_key == "researcher"
        else "methodology extraction and workspace design agent"
    )
    agent = json_request(
        "POST",
        f"{gateway}/v1/organizations/{organization_id}/agents",
        token=admin_access_token,
        payload={
            "actor": actor,
            "display_name": f"Live {agent_key.title()} {suffix}",
            "description": f"Live XWiki MCP {agent_key} identity.",
            "role": role,
            "capabilities": ["methodology", "dossiers", "mcp"],
            "endpoint": {"kind": "remote", "model": "gpt-5.4"},
            "system_prompt": "Use Open Talon methodology MCP operations deterministically.",
            "metadata": {"system_test": True, "agent_key": agent_key},
        },
    )
    role = json_request(
        "POST",
        f"{gateway}/v1/organizations/{organization_id}/iam/agent-roles",
        token=admin_access_token,
        payload={
            "actor": actor,
            "name": f"xwiki-live-{agent_key}-{suffix}",
            "description": f"Live XWiki methodology workflow role for {agent_key}.",
            "permissions": [
                "organization.read",
                "methodology.read",
                "methodology.write",
            ],
        },
    )
    provisioned = json_request(
        "POST",
        f"{gateway}/v1/organizations/{organization_id}/iam/agent-identities",
        token=admin_access_token,
        payload={
            "actor": actor,
            "system_agent_id": agent["agent_id"],
            "client_id": f"xwiki-live-{agent_key}-{suffix}",
        },
    )
    identity = provisioned["identity"]
    json_request(
        "POST",
        f"{gateway}/v1/iam/agent-identities/{identity['agent_identity_id']}/roles/{role['role_id']}",
        token=admin_access_token,
        payload={"actor": actor},
    )
    return _client_credentials_token(
        client_id=str(identity["client_id"]),
        client_secret=str(provisioned["client_secret"]),
    )


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

    page_refs: list[str] = []
    try:
        result = await XWikiDossierNotebookProvider(
            timeout_seconds=30.0,
            secret_resolver=SecretResolver([EnvironmentSecretProvider()]),
        ).sync(detail=detail, binding=binding)
        page_refs = result.page_refs

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
    finally:
        _cleanup_xwiki_page_refs(
            base_url=base_url,
            wiki_name=wiki_name,
            username=username,
            password=password,
            page_refs=page_refs
            or [
                f"Dossiers.{slug}.WebHome",
                f"Dossiers.{slug}.Concepts.concept-graph.WebHome",
            ],
        )


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
    page_refs: list[str] = []
    try:
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
            page_refs = list(sync_run["stats"].get("page_refs") or [])
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
    finally:
        _cleanup_xwiki_page_refs(
            base_url=xwiki_base_url,
            wiki_name=wiki_name,
            username=username,
            password=password,
            page_refs=page_refs,
        )


def test_xwiki_live_agent_mcp_workflow_builds_updates_and_consumes_dossier() -> None:
    _require_xwiki_live()
    username, password = _require_xwiki_credentials()
    xwiki_base_url = _xwiki_base_url()
    wiki_name = _xwiki_wiki_name()
    gateway = gateway_url()
    _assert_xwiki_ready(xwiki_base_url)
    _assert_gateway_ready(gateway)

    client_id = human_client_id()
    suffix = uuid4().hex[:10]
    page_refs: list[str] = []
    try:
        with direct_access_grants_enabled(client_id=client_id):
            token = admin_token(client_id=client_id)
            actor = live_actor(display_name="XWiki live agent workflow admin")
            organization = json_request(
                "POST",
                f"{gateway}/v1/organizations",
                token=token,
                payload={
                    "actor": actor,
                    "slug": f"xwiki-agent-workflow-{suffix}",
                    "name": f"XWiki Agent Workflow {suffix}",
                    "description": "Temporary organization for the real XWiki MCP workflow.",
                    "metadata": {"system_test": True},
                },
            )
            organization_id = str(organization["organization_id"])
            detail = json_request(
                "POST",
                f"{gateway}/v1/organizations/{organization_id}/methodology/blueprints",
                token=token,
                payload={
                    "actor": actor,
                    "title": f"Live MCP dossier workflow {suffix}",
                    "topic": "Real agent MCP dossier workflow",
                    "target_goal": "Verify Researcher and Methodologist MCP dossier operations.",
                    "tasks": [
                        "Researcher records source, concept, claim, links, health, and XWiki sync.",
                        "Methodologist navigates the dossier and submits a cited blueprint draft.",
                    ],
                    "library_ids": [],
                    "metadata": {"system_test": True},
                },
            )
            dossier_id = str(detail["dossier"]["dossier_id"])
            version_id = str(detail["versions"][0]["version_id"])
            notebook = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/methodology/dossiers/{dossier_id}/notebook",
                token=token,
            )
            dossier_slug = notebook["notebook"]["metadata"]["dossier_slug"]

            researcher_token = _provision_methodology_agent_token(
                gateway=gateway,
                admin_access_token=token,
                organization_id=organization_id,
                actor=actor,
                agent_key="researcher",
                suffix=f"{suffix}-researcher",
            )
            methodologist_token = _provision_methodology_agent_token(
                gateway=gateway,
                admin_access_token=token,
                organization_id=organization_id,
                actor=actor,
                agent_key="methodologist",
                suffix=f"{suffix}-methodologist",
            )

            researcher_session_id, _ = initialize_mcp_session(gateway, researcher_token)
            _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="session.set_scope",
                arguments={"scope": "organization", "organization_id": organization_id},
                request_id="researcher-scope",
            )
            source = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="methodology.dossiers.sources.create",
                arguments={
                    "dossier_id": dossier_id,
                    "source_kind": "webpage",
                    "status": "included",
                    "title": "Live MCP evidence source",
                    "source_uri": "https://example.test/live-mcp-evidence",
                    "citation_id": "S1",
                    "quality_notes": "Deterministic live source record for XWiki workflow testing.",
                },
                request_id="researcher-source",
            )
            source_id = source["source_id"]
            first_concept = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="methodology.dossiers.concepts.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "slug": "agent-loop-evidence",
                    "name": "Agent Loop Evidence",
                    "definition": "Initial definition from the Researcher workflow.",
                    "status": "candidate",
                    "source_ids": [source_id],
                },
                request_id="researcher-concept-1",
            )
            updated_concept = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="methodology.dossiers.concepts.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "slug": "agent-loop-evidence",
                    "name": "Agent Loop Evidence",
                    "definition": "Updated definition from an idempotent Researcher retry.",
                    "status": "active",
                    "confidence": 0.93,
                    "source_ids": [source_id],
                },
                request_id="researcher-concept-2",
            )
            assert updated_concept["concept_id"] == first_concept["concept_id"]
            first_note = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="methodology.dossiers.notes.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "note_kind": "concept",
                    "status": "draft",
                    "slug": "agent-loop-evidence-note",
                    "title": "Agent Loop Evidence",
                    "body": "Initial note body.",
                    "concept_id": updated_concept["concept_id"],
                    "citation_ids": ["S1"],
                },
                request_id="researcher-note-1",
            )
            updated_note = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="methodology.dossiers.notes.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "note_kind": "concept",
                    "status": "active",
                    "slug": "agent-loop-evidence-note",
                    "title": "Agent Loop Evidence",
                    "body": "Updated note body after idempotent Researcher retry.",
                    "concept_id": updated_concept["concept_id"],
                    "citation_ids": ["S1"],
                },
                request_id="researcher-note-2",
            )
            assert updated_note["note_id"] == first_note["note_id"]
            claim = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="methodology.dossiers.claims.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "claim_key": "claim:agent-loop-evidence",
                    "statement": "Dossier workflows remain retry-safe through natural-key upserts.",
                    "status": "supported",
                    "confidence": 0.87,
                    "source_ids": [source_id],
                    "citation_ids": ["S1"],
                },
                request_id="researcher-claim",
            )
            link = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="methodology.dossiers.links.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "source_type": "concept",
                    "source_ref_id": updated_concept["concept_id"],
                    "target_type": "claim",
                    "target_ref_id": claim["claim_id"],
                    "link_kind": "supports",
                    "rationale": "Concept page grounds the supported claim.",
                },
                request_id="researcher-link",
            )
            navigation = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="methodology.dossiers.navigate",
                arguments={"dossier_id": dossier_id, "query": "agent loop evidence"},
                request_id="researcher-navigate",
            )
            assert navigation["concepts"][0]["concept_id"] == updated_concept["concept_id"]
            assert navigation["links"][0]["link_id"] == link["link_id"]
            _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="methodology.dossiers.health.submit",
                arguments={
                    "dossier_id": dossier_id,
                    "status": "passed",
                    "summary": "Live MCP workflow dossier is navigable.",
                    "unresolved_count": 0,
                    "broken_link_count": 0,
                },
                request_id="researcher-health",
            )
            sync_run = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="methodology.dossiers.sync",
                arguments={
                    "dossier_id": dossier_id,
                    "provider_key": "xwiki",
                    "force": True,
                    "metadata": {"test": "live_agent_mcp_workflow"},
                },
                request_id="researcher-sync",
            )
            page_refs = list(sync_run["stats"].get("page_refs") or [])
            assert sync_run["status"] == "completed"
            assert sync_run["stats"]["pages_failed"] == 0
            ready = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="methodology.dossiers.mark_ready",
                arguments={
                    "dossier_id": dossier_id,
                    "summary": "Researcher finished the live MCP concept dossier.",
                    "contradictions": [
                        {
                            "claim": "Retry-safe upserts can hide duplicate submissions.",
                            "resolution": "Natural keys preserve one updated record while events retain audit history.",
                        }
                    ],
                    "gaps": ["The test uses deterministic evidence instead of internet discovery."],
                    "metadata": {"test": "live_agent_mcp_workflow"},
                },
                request_id="researcher-ready",
            )
            assert ready["status"] == "ready_for_methodologist"

            concept_page = httpx.get(
                _xwiki_page_rest_url_from_ref(
                    base_url=xwiki_base_url,
                    wiki_name=wiki_name,
                    page_ref=f"Dossiers.{dossier_slug}.Concepts.agent-loop-evidence.WebHome",
                ),
                auth=(username, password),
                headers={"Accept": "application/xml"},
                timeout=20.0,
            )
            concept_page.raise_for_status()
            assert "Updated definition from an idempotent Researcher retry." in concept_page.text
            note_page = httpx.get(
                _xwiki_page_rest_url_from_ref(
                    base_url=xwiki_base_url,
                    wiki_name=wiki_name,
                    page_ref=f"Dossiers.{dossier_slug}.agent-loop-evidence-note.WebHome",
                ),
                auth=(username, password),
                headers={"Accept": "application/xml"},
                timeout=20.0,
            )
            note_page.raise_for_status()
            assert "Updated note body after idempotent Researcher retry." in note_page.text

            methodologist_session_id, _ = initialize_mcp_session(
                gateway,
                methodologist_token,
            )
            _mcp_tool(
                gateway,
                methodologist_token,
                methodologist_session_id,
                name="session.set_scope",
                arguments={"scope": "organization", "organization_id": organization_id},
                request_id="methodologist-scope",
            )
            methodologist_navigation = _mcp_tool(
                gateway,
                methodologist_token,
                methodologist_session_id,
                name="methodology.dossiers.navigate",
                arguments={"dossier_id": dossier_id, "query": "retry-safe"},
                request_id="methodologist-navigate",
            )
            assert methodologist_navigation["claims"][0]["claim_id"] == claim["claim_id"]
            submitted = _mcp_tool(
                gateway,
                methodologist_token,
                methodologist_session_id,
                name="methodology.blueprints.submit_draft",
                arguments={
                    "version_id": version_id,
                    "cited_output": (
                        "# Live MCP methodology draft\n\n"
                        "Use Researcher dossier claim S1 to preserve retry-safe "
                        "concept collection and synthesis."
                    ),
                    "harness_draft": {
                        "summary": "Live MCP methodology draft from a concept dossier.",
                        "methodology": {
                            "ontology": "Evidence sources, concepts, claims, and methodics.",
                            "principles": ["Use cited dossier claims before synthesis."],
                        },
                        "methodics": [
                            {
                                "name": "Maintain a concept dossier",
                                "goal": "Keep source-backed concepts navigable for execution.",
                                "steps": [
                                    {
                                        "instruction": "Collect source-backed claims.",
                                        "expected_artifacts": ["dossier claim map"],
                                        "verification": ["claim map cites S1"],
                                    }
                                ],
                                "success_criteria": ["Dossier is ready for Methodologist."],
                            }
                        ],
                        "execution_rules": [
                            {
                                "name": "Human start required",
                                "instruction": "Do not start Conductor execution from blueprint synthesis.",
                            }
                        ],
                        "moderation_policy": {"enabled": False, "level": "open"},
                        "metadata": {"research_dossier_id": dossier_id},
                    },
                    "metadata": {"test": "live_agent_mcp_workflow"},
                },
                request_id="methodologist-submit",
            )
            submitted_version = submitted["versions"][0]
            assert submitted_version["status"] == "pending_review"
            assert submitted["dossier"]["status"] == "completed"
            assert submitted_version["metadata"]["test"] == "live_agent_mcp_workflow"
    finally:
        _cleanup_xwiki_page_refs(
            base_url=xwiki_base_url,
            wiki_name=wiki_name,
            username=username,
            password=password,
            page_refs=page_refs,
        )


def test_xwiki_live_cleanup_archives_temporary_page_content() -> None:
    _require_xwiki_live()
    username, password = _require_xwiki_credentials()
    base_url = _xwiki_base_url()
    wiki_name = _xwiki_wiki_name()
    _assert_xwiki_ready(base_url)

    page_ref = f"Dossiers.cleanup-{uuid4().hex[:10]}.WebHome"
    page_url = _xwiki_page_rest_url_from_ref(
        base_url=base_url,
        wiki_name=wiki_name,
        page_ref=page_ref,
    )
    create_response = httpx.put(
        page_url,
        auth=(username, password),
        headers={"Accept": "application/xml", "Content-Type": "application/xml"},
        content=(
            '<page xmlns="http://www.xwiki.org">\n'
            "  <title>Cleanup Live Test</title>\n"
            "  <syntax>xwiki/2.1</syntax>\n"
            "  <content>Temporary page for live cleanup verification.</content>\n"
            "</page>\n"
        ),
        timeout=20.0,
    )
    create_response.raise_for_status()
    assert httpx.get(
        page_url,
        auth=(username, password),
        headers={"Accept": "application/xml"},
        timeout=20.0,
    ).status_code == 200

    _cleanup_xwiki_page_refs(
        base_url=base_url,
        wiki_name=wiki_name,
        username=username,
        password=password,
        page_refs=[page_ref],
    )
    read_after_delete = httpx.get(
        page_url,
        auth=(username, password),
        headers={"Accept": "application/xml"},
        timeout=20.0,
    )
    read_after_delete.raise_for_status()
    assert "Open Talon live-test cleanup marker" in read_after_delete.text
    assert "Temporary page for live cleanup verification." not in read_after_delete.text
