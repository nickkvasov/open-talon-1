from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import quote
from xml.sax.saxutils import escape

import httpx
from open_talon_contracts.secrets import (
    SecretResolver,
    build_default_secret_resolver,
    secret_references_from_config,
)

from gateway_edge.models import (
    DossierConcept,
    DossierNote,
    DossierNotebookDetail,
    DossierProviderBinding,
)


@dataclass(frozen=True)
class DossierNotebookSyncResult:
    status: str
    pages_synced: int = 0
    pages_failed: int = 0
    page_refs: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def stats(self) -> dict[str, object]:
        return {
            "pages_synced": self.pages_synced,
            "pages_failed": self.pages_failed,
            "page_refs": self.page_refs,
            **self.metadata,
        }

    @property
    def error(self) -> str | None:
        return "; ".join(self.errors) if self.errors else None


class DossierNotebookProvider(Protocol):
    async def sync(
        self,
        *,
        detail: DossierNotebookDetail,
        binding: DossierProviderBinding,
    ) -> DossierNotebookSyncResult: ...


class XWikiDossierNotebookProvider:
    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        secret_resolver: SecretResolver | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._secret_resolver = secret_resolver or build_default_secret_resolver()

    async def sync(
        self,
        *,
        detail: DossierNotebookDetail,
        binding: DossierProviderBinding,
    ) -> DossierNotebookSyncResult:
        base_url = self._base_url(binding)
        wiki_name = self._wiki_name(binding)
        auth = await self._auth(binding)
        pages = self._pages(detail, binding)
        synced: list[str] = []
        errors: list[str] = []
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=self._timeout_seconds,
            auth=auth,
            trust_env=False,
        ) as client:
            for page_ref, title, content in pages:
                try:
                    await self._put_page(
                        client=client,
                        wiki_name=wiki_name,
                        page_ref=page_ref,
                        title=title,
                        content=content,
                    )
                    synced.append(page_ref)
                except Exception as exc:
                    errors.append(f"{page_ref}: {exc}")
        return DossierNotebookSyncResult(
            status="failed" if errors else "completed",
            pages_synced=len(synced),
            pages_failed=len(errors),
            page_refs=synced,
            errors=errors,
            metadata={
                "provider_kind": "xwiki",
                "provider_key": binding.provider_key,
                "external_space_ref": binding.external_space_ref,
                "wiki_name": wiki_name,
            },
        )

    @staticmethod
    def _base_url(binding: DossierProviderBinding) -> str:
        configured = (
            binding.external_base_url
            or binding.config.get("base_url")
            or "http://127.0.0.1:8083"
        )
        return str(configured).rstrip("/")

    @staticmethod
    def _wiki_name(binding: DossierProviderBinding) -> str:
        configured = binding.config.get("wiki_name") or "xwiki"
        return str(configured).strip("/") or "xwiki"

    async def _auth(
        self,
        binding: DossierProviderBinding,
    ) -> tuple[str, str] | None:
        username_refs = secret_references_from_config(binding.secret_config.get("username"))
        password_refs = secret_references_from_config(binding.secret_config.get("password"))
        username = await self._secret_resolver.resolve(
            username_refs,
            label=f"XWiki username for {binding.binding_id}",
            required=False,
        )
        password = await self._secret_resolver.resolve(
            password_refs,
            label=f"XWiki password for {binding.binding_id}",
            required=False,
        )
        if username and password:
            return username, password
        return None

    def _pages(
        self,
        detail: DossierNotebookDetail,
        binding: DossierProviderBinding,
    ) -> list[tuple[str, str, str]]:
        note_pages = [
            (
                self._note_page_ref(note, binding),
                note.title,
                self._render_note(detail, note, binding),
            )
            for note in detail.notes
        ]
        concept_pages = [
            (
                self._concept_page_ref(concept, binding),
                concept.name,
                self._render_concept(detail, concept, binding),
            )
            for concept in detail.concepts
        ]
        return [*note_pages, *concept_pages]

    @staticmethod
    def _note_page_ref(
        note: DossierNote,
        binding: DossierProviderBinding,
    ) -> str:
        if note.external_page_ref:
            return note.external_page_ref
        space = binding.external_space_ref or "Dossiers.Unknown"
        return f"{space}.{note.slug}.WebHome"

    @staticmethod
    def _concept_page_ref(
        concept: DossierConcept,
        binding: DossierProviderBinding,
    ) -> str:
        space = binding.external_space_ref or "Dossiers.Unknown"
        return f"{space}.Concepts.{concept.slug}.WebHome"

    @staticmethod
    def _render_note(
        detail: DossierNotebookDetail,
        note: DossierNote,
        binding: DossierProviderBinding,
    ) -> str:
        lines = [
            f"= {note.title} =",
            "",
            "{{info}}",
            f"Open Talon dossier: {note.dossier_id}",
            f"Notebook: {note.notebook_id}",
            f"Note: {note.note_id}",
            f"Provider binding: {binding.binding_id}",
            "{{/info}}",
            "",
            f"* Kind: {note.note_kind}",
            f"* Status: {note.status}",
            f"* Slug: {note.slug}",
        ]
        if note.source_id:
            lines.append(f"* Source: {note.source_id}")
        if note.concept_id:
            lines.append(f"* Concept: {note.concept_id}")
        if note.citation_ids:
            lines.append(f"* Citations: {', '.join(note.citation_ids)}")
        if note.related_note_ids:
            related = ", ".join(str(note_id) for note_id in note.related_note_ids)
            lines.append(f"* Related notes: {related}")
        if note.summary:
            lines.extend(["", "== Summary ==", "", note.summary])
        if note.body:
            lines.extend(["", "== Body ==", "", note.body])
        links = [
            link
            for link in detail.links
            if link.source_ref_id == note.note_id or link.target_ref_id == note.note_id
        ]
        if links:
            lines.extend(["", "== Links =="])
            for link in links:
                lines.append(
                    f"* {link.source_type}:{link.source_ref_id} "
                    f"{link.link_kind} {link.target_type}:{link.target_ref_id}"
                )
        lines.extend(
            [
                "",
                "== Sync ==",
                "",
                f"* Last Open Talon update: {note.updated_at.isoformat()}",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _render_concept(
        detail: DossierNotebookDetail,
        concept: DossierConcept,
        binding: DossierProviderBinding,
    ) -> str:
        lines = [
            f"= {concept.name} =",
            "",
            "{{info}}",
            f"Open Talon dossier: {concept.dossier_id}",
            f"Notebook: {concept.notebook_id}",
            f"Concept: {concept.concept_id}",
            f"Provider binding: {binding.binding_id}",
            "{{/info}}",
            "",
            f"* Status: {concept.status}",
            f"* Slug: {concept.slug}",
        ]
        if concept.aliases:
            lines.append(f"* Aliases: {', '.join(concept.aliases)}")
        if concept.confidence is not None:
            lines.append(f"* Confidence: {concept.confidence}")
        if concept.source_ids:
            lines.append("* Sources: " + ", ".join(str(item) for item in concept.source_ids))
        if concept.definition:
            lines.extend(["", "== Definition ==", "", concept.definition])
        claims = [
            claim
            for claim in detail.claims
            if claim.claim_id in concept.claim_ids
            or any(source_id in concept.source_ids for source_id in claim.source_ids)
        ]
        if claims:
            lines.extend(["", "== Claims =="])
            for claim in claims:
                lines.append(f"* ({claim.status}) {claim.statement}")
        links = [
            link
            for link in detail.links
            if link.source_ref_id == concept.concept_id
            or link.target_ref_id == concept.concept_id
        ]
        if links:
            lines.extend(["", "== Links =="])
            for link in links:
                lines.append(
                    f"* {link.source_type}:{link.source_ref_id} "
                    f"{link.link_kind} {link.target_type}:{link.target_ref_id}"
                )
        lines.extend(
            [
                "",
                "== Sync ==",
                "",
                f"* Last Open Talon update: {concept.updated_at.isoformat()}",
            ]
        )
        return "\n".join(lines)

    async def _put_page(
        self,
        *,
        client: httpx.AsyncClient,
        wiki_name: str,
        page_ref: str,
        title: str,
        content: str,
    ) -> None:
        response = await client.put(
            self._page_path(wiki_name, page_ref),
            content=self._page_xml(title=title, content=content),
            headers={
                "Accept": "application/xml",
                "Content-Type": "application/xml",
            },
        )
        response.raise_for_status()

    @staticmethod
    def _page_path(wiki_name: str, page_ref: str) -> str:
        parts = [part for part in page_ref.split(".") if part]
        if len(parts) < 2:
            raise ValueError(f"Invalid XWiki page ref {page_ref!r}")
        page = parts[-1]
        spaces = parts[:-1]
        path = f"/rest/wikis/{quote(wiki_name, safe='')}"
        for space in spaces:
            path += f"/spaces/{quote(space, safe='')}"
        path += f"/pages/{quote(page, safe='')}"
        return path

    @staticmethod
    def _page_xml(*, title: str, content: str) -> str:
        return (
            '<page xmlns="http://www.xwiki.org">\n'
            f"  <title>{escape(title)}</title>\n"
            "  <syntax>xwiki/2.1</syntax>\n"
            f"  <content>{escape(content)}</content>\n"
            "</page>\n"
        )
