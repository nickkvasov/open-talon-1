from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from open_talon_contracts.secrets import EnvironmentSecretProvider, SecretResolver

from gateway_edge.models import (
    ResearchDossierConcept,
    ResearchDossierNote,
    ResearchDossierNotebook,
    ResearchDossierNotebookDetail,
    ResearchDossierProviderBinding,
)
from gateway_edge.services import dossier_notebook_provider as provider_module
from gateway_edge.services.dossier_notebook_provider import XWikiDossierNotebookProvider


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None


class _FailingResponse:
    def raise_for_status(self) -> None:
        raise provider_module.httpx.HTTPStatusError(
            "server error",
            request=provider_module.httpx.Request("PUT", "http://xwiki.test"),
            response=provider_module.httpx.Response(500),
        )


class _FakeAsyncClient:
    calls: list[dict[str, object]] = []
    init_kwargs: dict[str, object] = {}

    def __init__(self, **kwargs) -> None:
        type(self).init_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def put(self, path, *, content, headers):
        type(self).calls.append(
            {"path": path, "content": content, "headers": headers}
        )
        return _FakeResponse()


class _FailingAsyncClient(_FakeAsyncClient):
    async def put(self, path, *, content, headers):
        type(self).calls.append(
            {"path": path, "content": content, "headers": headers}
        )
        return _FailingResponse()


def _notebook_detail(
    *,
    binding: ResearchDossierProviderBinding,
    note: ResearchDossierNote | None = None,
    concept: ResearchDossierConcept | None = None,
) -> ResearchDossierNotebookDetail:
    now = datetime.now(timezone.utc)
    note = note or ResearchDossierNote(
        note_id=uuid4(),
        notebook_id=binding.notebook_id,
        dossier_id=binding.dossier_id,
        organization_id=binding.organization_id,
        note_kind="home",
        status="active",
        slug="home",
        title="Home",
        body="A <concept> note with citation S1.",
        summary="Summary",
        citation_ids=["S1"],
        external_page_ref="Dossiers.test-dossier.WebHome",
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=now,
        updated_at=now,
    )
    return ResearchDossierNotebookDetail(
        notebook=ResearchDossierNotebook(
            notebook_id=binding.notebook_id,
            dossier_id=binding.dossier_id,
            organization_id=binding.organization_id,
            provider_kind="xwiki",
            provider_key="xwiki",
            status="created",
            home_note_id=note.note_id,
            external_space_ref=binding.external_space_ref,
            created_by=uuid4(),
            updated_by=uuid4(),
            created_at=now,
            updated_at=now,
        ),
        provider_bindings=[binding],
        notes=[note],
        concepts=[concept] if concept is not None else [],
    )


def _provider_binding(*, with_secret_refs: bool = True) -> ResearchDossierProviderBinding:
    now = datetime.now(timezone.utc)
    secret_config = (
        {
            "username": {"env": {"name": "OPEN_TALON_XWIKI_USERNAME"}},
            "password": {"env": {"name": "OPEN_TALON_XWIKI_PASSWORD"}},
        }
        if with_secret_refs
        else {}
    )
    return ResearchDossierProviderBinding(
        binding_id=uuid4(),
        notebook_id=uuid4(),
        dossier_id=uuid4(),
        organization_id=uuid4(),
        provider_kind="xwiki",
        provider_key="xwiki",
        external_space_ref="Dossiers.test-dossier",
        external_base_url="http://xwiki.test",
        config={"wiki_name": "xwiki"},
        secret_config=secret_config,
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_xwiki_dossier_provider_syncs_notebook_pages_with_basic_auth(
    monkeypatch,
) -> None:
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setenv("OPEN_TALON_XWIKI_USERNAME", "Admin")
    monkeypatch.setenv("OPEN_TALON_XWIKI_PASSWORD", "secret")
    _FakeAsyncClient.calls = []
    binding = _provider_binding()
    detail = _notebook_detail(binding=binding)

    result = await XWikiDossierNotebookProvider(
        secret_resolver=SecretResolver([EnvironmentSecretProvider()])
    ).sync(detail=detail, binding=binding)

    assert result.status == "completed"
    assert result.pages_synced == 1
    assert _FakeAsyncClient.init_kwargs["base_url"] == "http://xwiki.test"
    assert _FakeAsyncClient.init_kwargs["auth"] == ("Admin", "secret")
    assert _FakeAsyncClient.calls[0]["path"] == (
        "/rest/wikis/xwiki/spaces/Dossiers/spaces/test-dossier/pages/WebHome"
    )
    assert b"A &lt;concept&gt; note" in _FakeAsyncClient.calls[0]["content"].encode()


@pytest.mark.asyncio
async def test_xwiki_dossier_provider_syncs_without_auth_and_renders_concepts(
    monkeypatch,
) -> None:
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.calls = []
    binding = _provider_binding(with_secret_refs=False)
    now = datetime.now(timezone.utc)
    concept = ResearchDossierConcept(
        concept_id=uuid4(),
        notebook_id=binding.notebook_id,
        dossier_id=binding.dossier_id,
        organization_id=binding.organization_id,
        slug="feedback-loop",
        name="Feedback Loop",
        aliases=["learning cycle"],
        definition="A structured review cycle.",
        status="active",
        confidence=0.75,
        source_ids=[uuid4()],
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=now,
        updated_at=now,
    )
    detail = _notebook_detail(binding=binding, concept=concept)

    result = await XWikiDossierNotebookProvider().sync(
        detail=detail,
        binding=binding,
    )

    assert result.status == "completed"
    assert result.pages_synced == 2
    assert _FakeAsyncClient.init_kwargs["auth"] is None
    assert _FakeAsyncClient.calls[1]["path"] == (
        "/rest/wikis/xwiki/spaces/Dossiers/spaces/test-dossier/spaces/Concepts/"
        "spaces/feedback-loop/pages/WebHome"
    )
    content = _FakeAsyncClient.calls[1]["content"]
    assert "Feedback Loop" in content
    assert "learning cycle" in content


@pytest.mark.asyncio
async def test_xwiki_dossier_provider_reports_page_failures(monkeypatch) -> None:
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", _FailingAsyncClient)
    _FailingAsyncClient.calls = []
    binding = _provider_binding(with_secret_refs=False)
    note = ResearchDossierNote(
        note_id=uuid4(),
        notebook_id=binding.notebook_id,
        dossier_id=binding.dossier_id,
        organization_id=binding.organization_id,
        note_kind="home",
        status="active",
        slug="home",
        title="Home",
        external_page_ref="Dossiers.test-dossier.BadPage",
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    detail = _notebook_detail(binding=binding, note=note)

    result = await XWikiDossierNotebookProvider().sync(
        detail=detail,
        binding=binding,
    )

    assert result.status == "failed"
    assert result.pages_synced == 0
    assert result.pages_failed == 1
    assert "Dossiers.test-dossier.BadPage" in result.error
