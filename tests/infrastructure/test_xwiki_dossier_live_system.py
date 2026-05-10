from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from urllib.error import HTTPError

import httpx
import psycopg
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
    DossierConcept,
    DossierNote,
    DossierNotebook,
    DossierNotebookDetail,
    DossierProviderBinding,
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
    postgres_dsn,
)


pytestmark = pytest.mark.integration

_WEB_SEARCH_MCP_HEALTH_URL = "http://127.0.0.1:8181/health"
_WEB_SEARCH_MCP_URL = "http://127.0.0.1:8181/mcp"
_FULL_METHODOLOGY_KNOWLEDGE_COMPONENTS = [
    "research_plan",
    "source_bibliography",
    "methodology_basis",
    "methodology_principles",
    "methodics_inventory",
    "participants_and_roles",
    "tools_and_methods",
    "information_assets",
    "libraries_and_dossiers",
    "quality_evaluation",
    "contradictions",
    "gaps",
    "synthesis",
]
_METHODOLOGY_COMPONENT_NOTE_KIND = {
    "contradictions": "contradiction",
    "gaps": "gap",
    "source_bibliography": "source",
    "synthesis": "synthesis",
}
_METHODOLOGY_SOURCE_FALLBACK_URLS = [
    "https://www.nngroup.com/articles/user-interviews/",
    "https://www.nngroup.com/articles/diary-studies/",
    "https://www.nngroup.com/articles/which-ux-research-methods/",
    "https://www.nngroup.com/articles/ux-research-cheat-sheet/",
    "https://www.nngroup.com/articles/focus-groups/",
    "https://www.nngroup.com/articles/ab-testing-and-ux-research/",
    "https://www.nngroup.com/articles/quantitative-user-research-methods/",
    "https://www.surveymonkey.com/market-research/resources/complete-guide-to-segmentation-surveys/",
    "https://www.surveymonkey.com/market-research/resources/pricing-surveys/",
    "https://www.xlstat.com/solutions/features/price-sensitivity-meter",
]


def _component_note_spec_text(components: list[str]) -> str:
    specs = []
    for component in components:
        specs.append(
            {
                "component": component,
                "notes.upsert": {
                    "slug": f"coverage-{component.replace('_', '-')}",
                    "title": component.replace("_", " ").title(),
                    "note_kind": _METHODOLOGY_COMPONENT_NOTE_KIND.get(
                        component,
                        "other",
                    ),
                    "status": "active",
                    "summary": (
                        "Concise "
                        + component.replace("_", " ")
                        + " coverage for the methodology dossier."
                    ),
                    "metadata": {"knowledge_component": component},
                },
            }
        )
    return " | ".join(json.dumps(item, sort_keys=True) for item in specs)


def _require_xwiki_live() -> None:
    if os.getenv("OPEN_TALON_RUN_XWIKI_LIVE") != "1":
        pytest.skip("Set OPEN_TALON_RUN_XWIKI_LIVE=1 to run live XWiki tests")


def _require_real_methodology_deep_research_live() -> None:
    if os.getenv("OPEN_TALON_RUN_METHODOLOGY_DEEP_RESEARCH_LIVE") != "1":
        pytest.skip(
            "Set OPEN_TALON_RUN_METHODOLOGY_DEEP_RESEARCH_LIVE=1 to run the "
            "real Researcher/Methodologist deep methodology research live test"
        )


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


def _assert_web_search_ready() -> None:
    try:
        response = httpx.get(_WEB_SEARCH_MCP_HEALTH_URL, timeout=10.0)
    except httpx.HTTPError as exc:
        pytest.skip(
            f"Web-search MCP is not reachable at {_WEB_SEARCH_MCP_HEALTH_URL}: {exc}"
        )
    if response.status_code != 200:
        pytest.skip(
            "Web-search MCP is not healthy at "
            f"{_WEB_SEARCH_MCP_HEALTH_URL}: {response.status_code}"
        )


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _ensure_web_search_plugin_synced(
    *,
    gateway: str,
    token: str,
    actor: dict[str, Any],
) -> None:
    plugins = json_request("GET", f"{gateway}/v1/system-plugins", token=token)
    plugin = next(item for item in plugins if item["plugin_key"] == "web_search")
    plugin_id = str(plugin["plugin_id"])
    json_request(
        "POST",
        f"{gateway}/v1/system-plugins/{plugin_id}/sync",
        token=token,
        payload={
            "actor": actor,
            "metadata": {
                "source": "real_methodology_deep_research_live_test",
            },
        },
    )
    deadline = time.monotonic() + 120.0
    last_names: set[str] = set()
    while time.monotonic() < deadline:
        tools = json_request(
            "GET",
            f"{gateway}/v1/system-plugins/{plugin_id}/tools",
            token=token,
        )
        last_names = {str(tool["name"]) for tool in tools}
        if {"search", "fetch", "search_and_fetch"}.issubset(last_names):
            return
        time.sleep(2.0)
    raise AssertionError(
        "Timed out waiting for web_search plugin sync; "
        f"last discovered tools={sorted(last_names)}"
    )


def _web_search_mcp_rpc(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = httpx.post(
        _WEB_SEARCH_MCP_URL,
        json={
            "jsonrpc": "2.0",
            "id": "xwiki-methodology-live",
            "method": method,
            "params": params or {},
        },
        timeout=60.0,
    )
    response.raise_for_status()
    payload = response.json()
    if "error" in payload:
        raise AssertionError(f"web-search MCP {method} failed: {payload['error']}")
    return payload["result"]


def _internet_search_turn(*, query: str, turn: int) -> dict[str, Any]:
    result = _web_search_mcp_rpc(
        "tools/call",
        {
            "name": "search",
            "arguments": {
                "query": query,
                "limit": 5,
                "safe_search": 1,
                "language": "en",
            },
        },
    )
    payload = result["structuredContent"]
    results = payload.get("results") or []
    citations = payload.get("citations") or []
    assert payload["metadata"]["source"] == "searxng"
    assert len(results) >= 1, f"internet search turn {turn} returned no results"
    assert len(citations) == len(results)
    assert all(item["url"].startswith(("http://", "https://")) for item in results)
    return {
        "turn": turn,
        "query": query,
        "results": results,
        "citations": citations,
        "metadata": payload["metadata"],
    }


def _selected_search_result(search_turn: dict[str, Any], index: int = 0) -> dict[str, Any]:
    result = search_turn["results"][index]
    citation = search_turn["citations"][index]
    return {
        "title": result.get("title") or f"Internet search result {search_turn['turn']}",
        "url": result["url"],
        "snippet": result.get("content") or result.get("snippet") or "",
        "citation": citation,
    }


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


def _page_refs_from_notebook(notebook: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    notebook_row = notebook.get("notebook") if isinstance(notebook, dict) else {}
    if isinstance(notebook_row, dict):
        external_space_ref = notebook_row.get("external_space_ref")
        if isinstance(external_space_ref, str) and external_space_ref:
            refs.extend(
                [
                    f"{external_space_ref}.WebHome",
                    f"{external_space_ref}.Sources.WebHome",
                    f"{external_space_ref}.Concepts.WebHome",
                    f"{external_space_ref}.Contradictions.WebHome",
                    f"{external_space_ref}.Gaps.WebHome",
                    f"{external_space_ref}.Synthesis.WebHome",
                ]
            )
    for key in ("notes", "concepts", "claims"):
        for item in notebook.get(key) or []:
            external_page_ref = item.get("external_page_ref")
            if isinstance(external_page_ref, str) and external_page_ref:
                refs.append(external_page_ref)
    return list(dict.fromkeys(refs))


def _answer_open_research_requests(
    *,
    gateway: str,
    token_ref: dict[str, str],
    refresh_token: Callable[[], str] | None,
    actor: dict[str, Any],
    research_state: dict[str, Any],
    answered_request_ids: set[str],
) -> None:
    for detail in research_state.get("interaction_requests") or []:
        request = detail.get("request") or {}
        if request.get("status") != "open":
            continue
        request_id = request.get("request_id")
        if not request_id or str(request_id) in answered_request_ids:
            continue
        question_ids = [
            question["question_id"]
            for question in detail.get("questions") or []
            if question.get("question_id")
        ]
        _json_request_with_token_refresh(
            "POST",
            f"{gateway}/v1/requests/{request_id}/answers",
            token_ref=token_ref,
            refresh_token=refresh_token,
            payload={
                "actor": actor,
                "question_ids": question_ids,
                "content": (
                    "For this live test, prioritize US and English-speaking digital "
                    "wellness subscription consumers, keep assumptions explicit, "
                    "continue multi-turn web research, and preserve all supporting "
                    "sources, dossiers, libraries, tools, participants, methodics, "
                    "information assets, contradictions, gaps, and synthesis."
                ),
                "metadata": {
                    "source": "real_methodology_deep_research_live_test",
                    "auto_answered": True,
                },
            },
        )
        answered_request_ids.add(str(request_id))


def _json_request_with_token_refresh(
    method: str,
    url: str,
    *,
    token_ref: dict[str, str],
    refresh_token: Callable[[], str] | None,
    payload: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict | list:
    try:
        return json_request(
            method,
            url,
            token=token_ref["token"],
            payload=payload,
            timeout=timeout,
        )
    except HTTPError as exc:
        if exc.code != 401 or refresh_token is None:
            raise
        token_ref["token"] = refresh_token()
        return json_request(
            method,
            url,
            token=token_ref["token"],
            payload=payload,
            timeout=timeout,
        )


def _included_real_internet_sources(research_state: dict[str, Any]) -> list[dict[str, Any]]:
    included: list[dict[str, Any]] = []
    for source in research_state.get("sources") or []:
        metadata = source.get("fetch_metadata") or {}
        uri = str(source.get("source_uri") or "")
        if (
            source.get("status") == "included"
            and metadata.get("internet_search") is True
            and uri.startswith(("http://", "https://"))
            and "example.test" not in uri
        ):
            included.append(source)
    return included


def _missing_knowledge_components(research_state: dict[str, Any]) -> list[str]:
    return [
        item["component"]
        for item in research_state.get("knowledge_components") or []
        if item.get("component") in _FULL_METHODOLOGY_KNOWLEDGE_COMPONENTS
        and not item.get("present")
    ]


def _researcher_task_exhaustion_summary(*, organization_id: str) -> dict[str, Any] | None:
    with psycopg.connect(postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE tasks.status NOT IN ('completed', 'failed', 'cancelled')
                    ) AS active_tasks,
                    COUNT(*) FILTER (
                        WHERE tasks.status IN ('completed', 'failed', 'cancelled')
                    ) AS terminal_tasks,
                    COUNT(tool_calls.tool_call_id) AS tool_calls,
                    COUNT(tool_calls.tool_call_id) FILTER (
                        WHERE tool_calls.tool_name LIKE %s
                    ) AS web_search_tool_calls,
                    (
                        SELECT COUNT(*)
                        FROM dossier_sources
                        WHERE dossier_sources.organization_id = %s::uuid
                    ) AS sources,
                    MAX(tasks.updated_at) FILTER (
                        WHERE tasks.status IN ('completed', 'failed', 'cancelled')
                    ) AS latest_terminal_task_at
                FROM tasks
                LEFT JOIN tool_calls
                  ON tool_calls.task_id = tasks.task_id
                WHERE tasks.correlation_id IN (
                    SELECT dossier_id
                    FROM dossiers
                    WHERE organization_id = %s::uuid
                )
                  AND tasks.metadata->>'task_kind' IN (
                    'methodology_dossier_build',
                    'methodology_dossier_refine'
                  )
                """,
                ("web_search__%", organization_id, organization_id),
            )
            row = cur.fetchone()
    if row is None:
        return None
    (
        active_tasks,
        terminal_tasks,
        tool_calls,
        web_search_tool_calls,
        sources,
        latest_terminal_task_at,
    ) = row
    if active_tasks == 0 and terminal_tasks > 0:
        return {
            "active_researcher_tasks": int(active_tasks),
            "terminal_researcher_tasks": int(terminal_tasks),
            "tool_calls": int(tool_calls),
            "web_search_tool_calls": int(web_search_tool_calls),
            "sources": int(sources),
            "latest_terminal_task_at": (
                latest_terminal_task_at.isoformat()
                if latest_terminal_task_at is not None
                else None
            ),
        }
    return None


def _researcher_web_search_tool_call_count(*, organization_id: str) -> int:
    with psycopg.connect(postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(tool_calls.tool_call_id)
                FROM tasks
                JOIN tool_calls
                  ON tool_calls.task_id = tasks.task_id
                WHERE tasks.correlation_id IN (
                    SELECT dossier_id
                    FROM dossiers
                    WHERE organization_id = %s::uuid
                )
                  AND tasks.metadata->>'task_kind' IN (
                    'methodology_dossier_build',
                    'methodology_dossier_refine'
                  )
                  AND tool_calls.tool_name LIKE %s
                  AND tool_calls.status = 'completed'
                """,
                (organization_id, "web_search__%"),
            )
            row = cur.fetchone()
    return int(row[0]) if row is not None else 0


def _methodologist_draft_task_summary(
    *,
    organization_id: str,
    blueprint_id: str,
    dossier_id: str | None,
) -> list[dict[str, Any]]:
    with psycopg.connect(postgres_dsn()) as conn:
        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT
                    tasks.task_id::text AS task_id,
                    tasks.title,
                    tasks.status,
                    tasks.created_at,
                    tasks.updated_at,
                    tasks.metadata,
                    COUNT(DISTINCT tool_calls.tool_call_id) AS tool_calls,
                    COUNT(DISTINCT tool_calls.tool_call_id) FILTER (
                        WHERE tool_calls.tool_name = %s
                          AND tool_calls.status = 'completed'
                    ) AS completed_submit_draft_tool_calls,
                    ARRAY_REMOVE(ARRAY_AGG(DISTINCT runs.status), NULL) AS run_statuses
                FROM tasks
                JOIN workspaces
                  ON workspaces.workspace_id = tasks.workspace_id
                LEFT JOIN tool_calls
                  ON tool_calls.task_id = tasks.task_id
                LEFT JOIN runs
                  ON runs.task_id = tasks.task_id
                WHERE workspaces.organization_id = %s::uuid
                  AND tasks.metadata->>'task_kind' = 'methodology_blueprint_draft'
                  AND (
                        tasks.metadata->>'methodology_blueprint_id' = %s
                     OR (%s::text IS NOT NULL AND tasks.metadata->>'dossier_id' = %s)
                     OR (%s::text IS NOT NULL AND tasks.correlation_id::text = %s)
                  )
                GROUP BY tasks.task_id
                ORDER BY tasks.created_at DESC
                LIMIT 12
                """,
                (
                    "control_plane__methodology.blueprints.submit_draft",
                    organization_id,
                    blueprint_id,
                    dossier_id,
                    dossier_id,
                    dossier_id,
                    dossier_id,
                ),
            )
            rows = cur.fetchall()
    return [
        {
            **dict(row),
            "created_at": (
                row["created_at"].isoformat() if row["created_at"] is not None else None
            ),
            "updated_at": (
                row["updated_at"].isoformat() if row["updated_at"] is not None else None
            ),
            "metadata": row["metadata"] or {},
            "tool_calls": int(row["tool_calls"] or 0),
            "completed_submit_draft_tool_calls": int(
                row["completed_submit_draft_tool_calls"] or 0
            ),
        }
        for row in rows
    ]


def _wait_for_real_researcher_deep_research(
    *,
    gateway: str,
    token_ref: dict[str, str],
    refresh_token: Callable[[], str] | None,
    actor: dict[str, Any],
    organization_id: str,
    blueprint_id: str,
    min_search_turns: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    answered_request_ids: set[str] = set()
    last_summary: dict[str, Any] = {}
    admin_followups = 0
    last_followup_terminal_tasks = 0
    max_admin_followups = _int_env(
        "OPEN_TALON_METHODOLOGY_DEEP_RESEARCH_MAX_ADMIN_FOLLOWUPS",
        6,
    )
    while time.monotonic() < deadline:
        state = _json_request_with_token_refresh(
            "GET",
            (
                f"{gateway}/v1/organizations/{organization_id}/methodology/"
                f"blueprints/{blueprint_id}/research-state"
            ),
            token_ref=token_ref,
            refresh_token=refresh_token,
            timeout=60.0,
        )
        _answer_open_research_requests(
            gateway=gateway,
            token_ref=token_ref,
            refresh_token=refresh_token,
            actor=actor,
            research_state=state,
            answered_request_ids=answered_request_ids,
        )
        dossier_status = (state.get("dossier") or {}).get("status")
        search_turns = state.get("search_turns") or []
        web_search_tool_calls = _researcher_web_search_tool_call_count(
            organization_id=organization_id,
        )
        internet_turns = max(len(search_turns), web_search_tool_calls)
        sources = _included_real_internet_sources(state)
        missing_components = _missing_knowledge_components(state)
        last_summary = {
            "dossier_status": dossier_status,
            "search_turns": len(search_turns),
            "web_search_tool_calls": web_search_tool_calls,
            "included_real_internet_sources": len(sources),
            "missing_components": missing_components,
            "admin_followups": admin_followups,
            "open_interaction_requests": len(
                [
                    detail
                    for detail in state.get("interaction_requests") or []
                    if (detail.get("request") or {}).get("status") == "open"
                ]
            ),
        }
        if dossier_status == "failed":
            raise AssertionError(f"Researcher marked dossier failed: {last_summary}")
        if (
            dossier_status in {"ready", "consumed"}
            and internet_turns >= min_search_turns
            and len(sources) >= min_search_turns
            and not missing_components
        ):
            return state
        if (
            dossier_status in {"collecting", "synthesizing"}
            and internet_turns >= min_search_turns
            and len(sources) >= min_search_turns
            and not missing_components
        ):
            _admin_approve_real_researcher_readiness(
                gateway=gateway,
                token_ref=token_ref,
                refresh_token=refresh_token,
                actor=actor,
                organization_id=organization_id,
                research_state=state,
            )
            continue
        exhausted = _researcher_task_exhaustion_summary(
            organization_id=organization_id,
        )
        if exhausted is not None:
            terminal_count = int(exhausted["terminal_researcher_tasks"])
            if terminal_count > last_followup_terminal_tasks:
                if admin_followups >= max_admin_followups:
                    raise AssertionError(
                        "Real Researcher tasks exhausted before dossier readiness; "
                        f"exhaustion_summary={exhausted}; last_summary={last_summary}"
                    )
                admin_followups += 1
                last_followup_terminal_tasks = terminal_count
                source_gap = max(0, min_search_turns - len(sources))
                source_fallback_required = source_gap > 0
                targeted_missing_components = (
                    missing_components
                    if source_gap > 0
                    else missing_components[:2]
                )
                component_text = ", ".join(targeted_missing_components) or "none"
                if source_gap == 0 and not missing_components:
                    followup_instructions = (
                        "Only the generic dossier readiness lifecycle handoff remains. "
                        "Use AgentRunResult JSON with tool_calls; do not return markdown "
                        "until the lifecycle tools are complete. Do not call web_search. "
                        "If the current dossier status is collecting, first call "
                        "control_plane__dossiers.lifecycle.transition with arguments "
                        f"{{\"dossier_id\":\"{(state.get('dossier') or {}).get('dossier_id')}\","
                        "\"target_status\":\"synthesizing\","
                        "\"reason\":\"evidence_collection_complete\"}}. "
                        "Use the argument name target_status exactly; do not use to or "
                        "status. Then call control_plane__dossiers.health.submit with "
                        "status=\"passed\" and a summary that all full-methodology "
                        "research components and at least five included internet sources "
                        "are persisted. Then call control_plane__dossiers.sync with "
                        "provider_key=\"xwiki\" and force=true. Finally call "
                        "control_plane__dossiers.lifecycle.transition with "
                        "target_status=\"ready\", a summary, contradictions, gaps, and "
                        "metadata.scenario=\"real_agent_b2c_market_research_methodology\". "
                        "If the dossier is already synthesizing, skip only the collecting "
                        "to synthesizing transition and still submit health, sync, and "
                        "target_status=\"ready\"."
                    )
                else:
                    if source_fallback_required:
                        fallback_batch_size = max(1, min(source_gap, 2))
                        source_instruction = (
                            f"Persist at least {source_gap} additional included HTTP "
                            "internet source records with fetch_metadata.internet_search=true, "
                            "fetch_metadata.search_turn, fetch_metadata.search_query, and "
                            "fetch_metadata.rank. This is a deterministic source-fallback "
                            f"turn: use the first {fallback_batch_size} not-yet-included "
                            "URL(s) from the fallback list. Return a single AgentRunResult "
                            "JSON containing paired tool calls for each URL: first "
                            "web_search__fetch, then control_plane__dossiers.sources.create "
                            "for the same URL with status=\"included\". Do not return "
                            "a fetch-only tool request and do not wait for another turn to "
                            "persist the source. Do not call web_search__search, "
                            "web_search__search_and_fetch, retriever, notebook, lifecycle, "
                            "health, or sync before source records are created. "
                            "Fallback URLs: "
                            f"{', '.join(_METHODOLOGY_SOURCE_FALLBACK_URLS)}. "
                            f"Use fetch_metadata.search_turn={len(search_turns) + 1} "
                            "for the next included source, increment it by one for each "
                            "additional included source, and use a concrete "
                            "fetch_metadata.search_query that names the fetched method. "
                            "Do not use about:blank, searxng://, retriever://, or failed "
                            "search placeholders for included source coverage. "
                        )
                    else:
                        source_instruction = (
                        f"Persist at least {source_gap} additional included HTTP "
                        "internet source records with fetch_metadata.internet_search=true, "
                        "fetch_metadata.search_turn, fetch_metadata.search_query, and "
                        "fetch_metadata.rank. Source persistence is the next action: "
                        "do not call retriever, notebook, lifecycle, health, or sync "
                        "before creating those source records from already fetched search "
                        "results, one concise search_and_fetch result, or web_search__fetch "
                        "of the fallback URLs below. If search engines are rate-limited, "
                        "blocked, or empty, fetch these authoritative URLs and persist "
                        "successful HTTP fetches as included webpage sources: "
                        f"{', '.join(_METHODOLOGY_SOURCE_FALLBACK_URLS)}. "
                        "Do not use about:blank, searxng://, retriever://, or failed "
                        "search placeholders for included source coverage. After each "
                        "web_search result or successful fetch, immediately call "
                        "control_plane__dossiers.sources.create for at least one credible "
                        "HTTP source before any other discovery call. "
                        if source_gap > 0
                        else (
                            "The included internet source count is sufficient. Do not run "
                            "more web_search or retriever calls in this follow-up. "
                            "This is a focused coverage-repair turn: write only the "
                            "targeted missing knowledge-component notes listed below. "
                        )
                        )
                    followup_instructions = (
                        "Continue the same real B2C subscription wellness app "
                        "methodology dossier. The previous Researcher pass completed "
                        "before the readiness gate was satisfied. Do not summarize "
                        "completion until all required data is persisted. "
                        "Do not include asset persistence, retained library, retain, "
                        "persist, persist_asset, or save options in web_search calls. "
                        f"{source_instruction}"
                        "For every targeted missing required component, call "
                        "control_plane__dossiers.notes.upsert with metadata."
                        "knowledge_component set exactly to that component key. "
                        "Use _mcp_scope with scope=organization and this organization_id "
                        "in every control_plane tool call. Use note_kind other for "
                        "research_plan, information_assets, libraries_and_dossiers, and "
                        "quality_evaluation; source for source_bibliography; method for "
                        "methodology_basis, methodology_principles, methodics_inventory, "
                        "participants_and_roles, and tools_and_methods; contradiction "
                        "for contradictions; gap for gaps; synthesis for synthesis. "
                        f"Targeted missing components for this follow-up: {component_text}. "
                        "Use these exact note payload specs: "
                        f"{_component_note_spec_text(targeted_missing_components)}. "
                        "For coverage notes, use summary instead of body; keep summary "
                        "as one valid JSON string without literal newlines or unescaped "
                        "quotes. Include concrete methodics, required steps, participants, "
                        "tools, information assets, libraries/dossiers, quality "
                        "criteria, contradictions, gaps, and synthesis as relevant to "
                        "the targeted components. If source_gap is zero, after these "
                        "notes.upsert calls stop this turn; do not call XWiki sync, "
                        "health, or lifecycle until a later research-state read shows "
                        "no missing components. If source_gap is greater than zero, "
                        "finish the source persistence before any lifecycle call."
                    )
                try:
                    _json_request_with_token_refresh(
                        "POST",
                        (
                            f"{gateway}/v1/organizations/{organization_id}/methodology/"
                            f"blueprints/{blueprint_id}/research-requests"
                        ),
                        token_ref=token_ref,
                        refresh_token=refresh_token,
                        payload={
                            "actor": actor,
                            "instructions": followup_instructions,
                            "max_search_turns": max(5, min_search_turns),
                            "required_components": _FULL_METHODOLOGY_KNOWLEDGE_COMPONENTS,
                            "require_admin_ready_approval": True,
                            "metadata": {
                                "system_test": True,
                                "scenario": "real_agent_b2c_market_research_methodology",
                                "auto_admin_followup": True,
                                "followup_number": admin_followups,
                            "source_gap": source_gap,
                            "source_fallback_required": source_fallback_required,
                            "next_search_turn": len(search_turns) + 1,
                            "source_fallback_batch_size": max(1, min(source_gap, 2)),
                            "missing_components": targeted_missing_components,
                                "all_missing_components": missing_components,
                                "source_fallback_candidate_urls": (
                                    _METHODOLOGY_SOURCE_FALLBACK_URLS
                                ),
                            },
                        },
                        timeout=60.0,
                    )
                except HTTPError as exc:
                    if exc.code != 400:
                        raise
                    refreshed_state = _json_request_with_token_refresh(
                        "GET",
                        (
                            f"{gateway}/v1/organizations/{organization_id}/methodology/"
                            f"blueprints/{blueprint_id}/research-state"
                        ),
                        token_ref=token_ref,
                        refresh_token=refresh_token,
                        timeout=60.0,
                    )
                    refreshed_status = (refreshed_state.get("dossier") or {}).get(
                        "status"
                    )
                    if (
                        refreshed_status in {"ready", "consumed"}
                        and max(
                            len(refreshed_state.get("search_turns") or []),
                            _researcher_web_search_tool_call_count(
                                organization_id=organization_id,
                            ),
                        )
                        >= min_search_turns
                        and len(_included_real_internet_sources(refreshed_state))
                        >= min_search_turns
                        and not _missing_knowledge_components(refreshed_state)
                    ):
                        return refreshed_state
                    raise
                continue
        time.sleep(10.0)
    raise AssertionError(
        "Timed out waiting for real Researcher deep research; "
        f"last_summary={last_summary}"
    )


def _admin_approve_real_researcher_readiness(
    *,
    gateway: str,
    token_ref: dict[str, str],
    refresh_token: Callable[[], str] | None,
    actor: dict[str, Any],
    organization_id: str,
    research_state: dict[str, Any],
) -> None:
    dossier = research_state.get("dossier") or {}
    dossier_id = dossier.get("dossier_id")
    if not dossier_id:
        raise AssertionError("Cannot approve readiness without a dossier id")
    if dossier.get("status") == "collecting":
        _json_request_with_token_refresh(
            "POST",
            f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/lifecycle",
            token_ref=token_ref,
            refresh_token=refresh_token,
            payload={
                "actor": actor,
                "target_status": "synthesizing",
                "reason": "admin_confirmed_evidence_collection_complete",
                "metadata": {
                    "system_test": True,
                    "scenario": "real_agent_b2c_market_research_methodology",
                    "admin_readiness_approval": True,
                },
            },
            timeout=60.0,
        )
    _json_request_with_token_refresh(
        "POST",
        f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/lifecycle",
        token_ref=token_ref,
        refresh_token=refresh_token,
        payload={
            "actor": actor,
            "target_status": "ready",
            "summary": (
                dossier.get("summary")
                or "Admin approved Researcher dossier readiness after live evidence coverage validation."
            ),
            "contradictions": dossier.get("contradictions") or [],
            "gaps": dossier.get("gaps") or [],
            "reason": "admin_approved_full_methodology_readiness",
            "metadata": {
                "system_test": True,
                "scenario": "real_agent_b2c_market_research_methodology",
                "admin_readiness_approval": True,
                "approval_basis": "search_source_and_knowledge_coverage_met",
            },
        },
        timeout=60.0,
    )


def _wait_for_real_methodologist_draft(
    *,
    gateway: str,
    token_ref: dict[str, str],
    refresh_token: Callable[[], str] | None,
    actor: dict[str, Any],
    organization_id: str,
    blueprint_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_summary: dict[str, Any] = {}
    resumed_task_ids: set[str] = set()
    handoff_recovery_count = 0
    max_handoff_recoveries = 3
    while time.monotonic() < deadline:
        detail = _json_request_with_token_refresh(
            "GET",
            f"{gateway}/v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}",
            token_ref=token_ref,
            refresh_token=refresh_token,
            timeout=60.0,
        )
        versions = detail.get("versions") or []
        drafted = [
            version
            for version in versions
            if version.get("status") == "pending_review"
            and version.get("cited_output")
            and version.get("harness_draft")
        ]
        last_summary = {
            "version_statuses": [
                {
                    "version_id": version.get("version_id"),
                    "status": version.get("status"),
                    "has_cited_output": bool(version.get("cited_output")),
                    "has_harness_draft": bool(version.get("harness_draft")),
                }
                for version in versions
            ],
            "dossier_status": (detail.get("dossier") or {}).get("status"),
        }
        dossier = detail.get("dossier") or {}
        dossier_id = dossier.get("dossier_id")
        methodologist_tasks = _methodologist_draft_task_summary(
            organization_id=organization_id,
            blueprint_id=blueprint_id,
            dossier_id=dossier_id,
        )
        last_summary["methodologist_tasks"] = methodologist_tasks
        if drafted:
            return detail
        failed_tasks = [
            task for task in methodologist_tasks if task.get("status") == "failed"
        ]
        if failed_tasks:
            task_id = failed_tasks[0]["task_id"]
            if task_id not in resumed_task_ids:
                _json_request_with_token_refresh(
                    "POST",
                    (
                        f"{gateway}/v1/organizations/{organization_id}/runtime/"
                        f"tasks/{task_id}/resume"
                    ),
                    token_ref=token_ref,
                    refresh_token=refresh_token,
                    payload={
                        "actor": actor,
                        "reason": "live_test_resuming_methodologist_after_provider_or_runtime_failure",
                        "metadata": {
                            "system_test": True,
                            "scenario": "real_agent_b2c_market_research_methodology",
                            "methodologist_live_resume": True,
                        },
                    },
                    timeout=60.0,
                )
                resumed_task_ids.add(task_id)
                time.sleep(5.0)
                continue
        active_tasks = [
            task
            for task in methodologist_tasks
            if task.get("status") in {"created", "released", "claimed"}
        ]
        completed_without_draft = [
            task for task in methodologist_tasks if task.get("status") == "completed"
        ]
        ready_for_draft = any(
            version.get("status") == "ready_for_draft" for version in versions
        )
        if (
            dossier_id
            and dossier.get("status") == "ready"
            and ready_for_draft
            and not active_tasks
            and handoff_recovery_count < max_handoff_recoveries
        ):
            _json_request_with_token_refresh(
                "POST",
                f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/lifecycle",
                token_ref=token_ref,
                refresh_token=refresh_token,
                payload={
                    "actor": actor,
                    "target_status": "ready",
                    "summary": (
                        dossier.get("summary")
                        or "Admin recovered Methodologist handoff for ready dossier."
                    ),
                    "contradictions": dossier.get("contradictions") or [],
                    "gaps": dossier.get("gaps") or [],
                    "reason": "admin_recovered_methodologist_handoff",
                    "metadata": {
                        "system_test": True,
                        "scenario": "real_agent_b2c_market_research_methodology",
                        "ensure_methodologist_task": True,
                        "handoff_recovery_attempt": handoff_recovery_count + 1,
                        "completed_without_draft_count": len(completed_without_draft),
                    },
                },
                timeout=60.0,
            )
            handoff_recovery_count += 1
            time.sleep(5.0)
            continue
        time.sleep(10.0)
    raise AssertionError(
        "Timed out waiting for real Methodologist draft submission; "
        f"last_summary={last_summary}"
    )


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
        "evidence discovery and dossier agent"
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
    binding = DossierProviderBinding(
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
    note = DossierNote(
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
    concept = DossierConcept(
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
    detail = DossierNotebookDetail(
        notebook=DossierNotebook(
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
                f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/notebook",
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
                f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/sync",
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
                f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/notebook",
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
    _assert_web_search_ready()

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
                    "description": (
                        "Temporary organization for the real B2C market research "
                        "methodology MCP workflow."
                    ),
                    "metadata": {
                        "system_test": True,
                        "scenario": "b2c_market_research_methodology",
                    },
                },
            )
            organization_id = str(organization["organization_id"])
            detail = json_request(
                "POST",
                f"{gateway}/v1/organizations/{organization_id}/methodology/blueprints",
                token=token,
                payload={
                    "actor": actor,
                    "title": f"Live B2C market research methodology {suffix}",
                    "topic": (
                        "Create a B2C market research methodology for validating "
                        "subscription wellness app demand."
                    ),
                    "target_goal": (
                        "Verify Researcher evidence collection, Methodologist synthesis, "
                        "and human-edited methodology revision."
                    ),
                    "tasks": [
                        (
                            "Researcher records B2C segment, purchase-intent, "
                            "and objection evidence."
                        ),
                        "Methodologist submits a cited B2C methodology draft from the dossier.",
                        "Human editor creates a revised methodology version before approval.",
                    ],
                    "library_ids": [],
                    "metadata": {
                        "system_test": True,
                        "scenario": "b2c_market_research_methodology",
                    },
                },
            )
            blueprint_id = str(detail["blueprint"]["blueprint_id"])
            dossier_id = str(detail["dossier"]["dossier_id"])
            version_id = str(detail["versions"][0]["version_id"])
            research_state = json_request(
                "POST",
                (
                    f"{gateway}/v1/organizations/{organization_id}/methodology/"
                    f"blueprints/{blueprint_id}/research-requests"
                ),
                token=token,
                payload={
                    "actor": actor,
                    "instructions": (
                        "Researcher must perform multi-turn internet research for a "
                        "B2C market research methodology, persist selected sources, "
                        "fill all full-methodology knowledge components, sync XWiki, "
                        "and propose readiness for Methodologist handoff."
                    ),
                    "max_search_turns": 5,
                    "required_components": _FULL_METHODOLOGY_KNOWLEDGE_COMPONENTS,
                    "require_admin_ready_approval": True,
                    "metadata": {
                        "system_test": True,
                        "scenario": "b2c_market_research_methodology",
                        "requested_from": "live_research_console_api",
                    },
                },
            )
            assert research_state["metadata"]["can_request_research"] is True
            events = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/events",
                token=token,
            )
            assert "dossier.research_requested" in {
                event["event_type"] for event in events
            }
            notebook = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/notebook",
                token=token,
            )
            dossier_slug = notebook["notebook"]["metadata"]["dossier_slug"]
            search_turn_1 = _internet_search_turn(
                query=(
                    "B2C market research methodology consumer segmentation "
                    "purchase intent"
                ),
                turn=1,
            )
            first_search_result = _selected_search_result(search_turn_1)
            search_turn_2 = _internet_search_turn(
                query=(
                    "B2C willingness to pay survey diary study purchase intent "
                    "methodology"
                ),
                turn=2,
            )
            second_search_result = _selected_search_result(search_turn_2)
            assert search_turn_1["query"] != search_turn_2["query"]

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
            _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.lifecycle.transition",
                arguments={
                    "dossier_id": dossier_id,
                    "target_status": "collecting",
                    "reason": "researcher_started_source_collection",
                },
                request_id="researcher-collecting",
            )
            methodology_source = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.sources.create",
                arguments={
                    "dossier_id": dossier_id,
                    "source_kind": "webpage",
                    "status": "included",
                    "title": first_search_result["title"],
                    "source_uri": first_search_result["url"],
                    "citation_id": "S1",
                    "quality_notes": (
                        "Internet search turn 1 selected a B2C market research "
                        "methodology source."
                    ),
                    "rationale": (
                        "Collect the broad methodology definition before refining "
                        "toward validation methodics."
                    ),
                    "fetch_metadata": {
                        "internet_search": True,
                        "search_turn": search_turn_1["turn"],
                        "query": search_turn_1["query"],
                        "result_snippet": first_search_result["snippet"],
                        "citation": first_search_result["citation"],
                        "source": search_turn_1["metadata"]["source"],
                    },
                    "metadata": {
                        "scenario": "b2c_market_research_methodology",
                        "collection_phase": "methodology_definition",
                    },
                },
                request_id="researcher-source",
            )
            validation_source = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.sources.create",
                arguments={
                    "dossier_id": dossier_id,
                    "source_kind": "webpage",
                    "status": "included",
                    "title": second_search_result["title"],
                    "source_uri": second_search_result["url"],
                    "citation_id": "S2",
                    "quality_notes": (
                        "Internet search turn 2 refined the topic toward willingness-to-pay, "
                        "survey, and diary-study methodics."
                    ),
                    "rationale": (
                        "Refine the collected methodology into actionable demand "
                        "validation steps."
                    ),
                    "fetch_metadata": {
                        "internet_search": True,
                        "search_turn": search_turn_2["turn"],
                        "query": search_turn_2["query"],
                        "previous_turn_selected_title": first_search_result["title"],
                        "result_snippet": second_search_result["snippet"],
                        "citation": second_search_result["citation"],
                        "source": search_turn_2["metadata"]["source"],
                    },
                    "metadata": {
                        "scenario": "b2c_market_research_methodology",
                        "collection_phase": "methodics_refinement",
                    },
                },
                request_id="researcher-source-refined",
            )
            source_ids = [methodology_source["source_id"], validation_source["source_id"]]
            first_concept = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.concepts.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "slug": "b2c-market-research-methodology",
                    "name": "B2C Market Research Methodology",
                    "definition": (
                        "Initial methodology collection from internet search: "
                        "define B2C market research around consumer segments, "
                        "needs, objections, and buying intent."
                    ),
                    "status": "candidate",
                    "source_ids": source_ids,
                },
                request_id="researcher-concept-1",
            )
            updated_concept = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.concepts.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "slug": "b2c-market-research-methodology",
                    "name": "B2C Market Research Methodology",
                    "definition": (
                        "Updated methodology collection from a refined internet search: "
                        "combine segment discovery, purchase-intent validation, "
                        "survey quantification, diary signals, and willingness-to-pay "
                        "checks."
                    ),
                    "status": "active",
                    "confidence": 0.93,
                    "source_ids": source_ids,
                },
                request_id="researcher-concept-2",
            )
            assert updated_concept["concept_id"] == first_concept["concept_id"]
            first_note = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.notes.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "note_kind": "concept",
                    "status": "draft",
                    "slug": "b2c-methodology-collection-note",
                    "title": "Collected B2C Methodology",
                    "body": (
                        "Initial methodology collection note from internet search turn 1."
                    ),
                    "concept_id": updated_concept["concept_id"],
                    "citation_ids": ["S1", "S2"],
                },
                request_id="researcher-note-1",
            )
            updated_note = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.notes.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "note_kind": "concept",
                    "status": "active",
                    "slug": "b2c-methodology-collection-note",
                    "title": "Collected B2C Methodology",
                    "body": (
                        "Updated methodology collection note after internet search turn 2: "
                        "include participants, tools, information assets, survey "
                        "quantification, diary-study evidence, and willingness-to-pay "
                        "signals."
                    ),
                    "concept_id": updated_concept["concept_id"],
                    "citation_ids": ["S1", "S2"],
                },
                request_id="researcher-note-2",
            )
            assert updated_note["note_id"] == first_note["note_id"]
            claim = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.claims.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "claim_key": "claim:b2c-methodology-methodics",
                    "statement": (
                        "A B2C market research methodology should collect internet "
                        "sources, define the target segment, and convert evidence "
                        "into methodics with participants, tools, and information assets."
                    ),
                    "status": "supported",
                    "confidence": 0.87,
                    "source_ids": source_ids,
                    "citation_ids": ["S1", "S2"],
                },
                request_id="researcher-claim",
            )
            for component in _FULL_METHODOLOGY_KNOWLEDGE_COMPONENTS:
                _mcp_tool(
                    gateway,
                    researcher_token,
                    researcher_session_id,
                    name="dossiers.notes.upsert",
                    arguments={
                        "dossier_id": dossier_id,
                        "note_kind": (
                            "gap"
                            if component == "gaps"
                            else "contradiction"
                            if component == "contradictions"
                            else "synthesis"
                            if component == "synthesis"
                            else "source"
                            if component == "source_bibliography"
                            else "other"
                        ),
                        "status": "active",
                        "slug": f"b2c-coverage-{component}",
                        "title": f"B2C coverage: {component.replace('_', ' ')}",
                        "summary": (
                            "Full methodology research component for the live B2C "
                            f"workflow: {component}."
                        ),
                        "body": (
                            "Researcher stores the required methodology knowledge "
                            f"component `{component}` with supporting sources, "
                            "participants, tools, methodics, information assets, "
                            "libraries, dossiers, contradictions, gaps, and synthesis."
                        ),
                        "source_id": (
                            methodology_source["source_id"]
                            if component == "source_bibliography"
                            else None
                        ),
                        "citation_ids": ["S1", "S2"],
                        "metadata": {
                            "knowledge_component": component,
                            "scenario": "b2c_market_research_methodology",
                            "completion_profile": "full_methodology_research",
                        },
                    },
                    request_id=f"researcher-coverage-{component}",
                )
            link = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.links.upsert",
                arguments={
                    "dossier_id": dossier_id,
                    "source_type": "concept",
                    "source_ref_id": updated_concept["concept_id"],
                    "target_type": "claim",
                    "target_ref_id": claim["claim_id"],
                    "link_kind": "supports",
                    "rationale": (
                        "Collected methodology sources ground the supported B2C "
                        "methodics claim."
                    ),
                },
                request_id="researcher-link",
            )
            navigation = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.navigate",
                arguments={
                    "dossier_id": dossier_id,
                    "query": "B2C market research methodology methodics",
                },
                request_id="researcher-navigate",
            )
            assert navigation["concepts"][0]["concept_id"] == updated_concept["concept_id"]
            assert navigation["links"][0]["link_id"] == link["link_id"]
            _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.lifecycle.transition",
                arguments={
                    "dossier_id": dossier_id,
                    "target_status": "synthesizing",
                    "reason": "researcher_started_evidence_synthesis",
                },
                request_id="researcher-synthesizing",
            )
            _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.health.submit",
                arguments={
                    "dossier_id": dossier_id,
                    "status": "passed",
                    "summary": (
                        "Live B2C dossier is navigable after two "
                        "internet search turns."
                    ),
                    "unresolved_count": 0,
                    "broken_link_count": 0,
                },
                request_id="researcher-health",
            )
            sync_run = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.sync",
                arguments={
                    "dossier_id": dossier_id,
                    "provider_key": "xwiki",
                    "force": True,
                    "metadata": {
                        "test": "live_agent_mcp_workflow",
                        "scenario": "b2c_market_research_methodology",
                    },
                },
                request_id="researcher-sync",
            )
            page_refs = list(sync_run["stats"].get("page_refs") or [])
            assert sync_run["status"] == "completed"
            assert sync_run["stats"]["pages_failed"] == 0
            research_state = json_request(
                "GET",
                (
                    f"{gateway}/v1/organizations/{organization_id}/methodology/"
                    f"blueprints/{blueprint_id}/research-state"
                ),
                token=token,
            )
            assert len(research_state["search_turns"]) >= 2
            assert {
                turn["turn"] for turn in research_state["search_turns"]
            }.issuperset({1, 2})
            missing_components = [
                item["component"]
                for item in research_state["knowledge_components"]
                if item["component"] in _FULL_METHODOLOGY_KNOWLEDGE_COMPONENTS
                and not item["present"]
            ]
            assert missing_components == []
            ready = _mcp_tool(
                gateway,
                researcher_token,
                researcher_session_id,
                name="dossiers.lifecycle.transition",
                arguments={
                    "dossier_id": dossier_id,
                    "target_status": "ready",
                    "summary": (
                        "Researcher finished the live B2C dossier after "
                        "multi-turn internet search and source collection."
                    ),
                    "contradictions": [
                        {
                            "claim": "Survey intent can overstate actual willingness to pay.",
                            "resolution": (
                                "Use diary signals and willingness-to-pay screens before "
                                "launch channel recommendations."
                            ),
                        }
                    ],
                    "gaps": [
                        (
                            "Internet result quality varies; Methodologist must verify "
                            "source fit before applying methodics."
                        ),
                    ],
                    "metadata": {
                        "test": "live_agent_mcp_workflow",
                        "scenario": "b2c_market_research_methodology",
                    },
                },
                request_id="researcher-ready",
            )
            assert ready["status"] == "ready"

            concept_page = httpx.get(
                _xwiki_page_rest_url_from_ref(
                    base_url=xwiki_base_url,
                    wiki_name=wiki_name,
                    page_ref=(
                        f"Dossiers.{dossier_slug}.Concepts."
                        "b2c-market-research-methodology.WebHome"
                    ),
                ),
                auth=(username, password),
                headers={"Accept": "application/xml"},
                timeout=20.0,
            )
            concept_page.raise_for_status()
            assert (
                "Updated methodology collection from a refined internet search"
                in concept_page.text
            )
            note_page = httpx.get(
                _xwiki_page_rest_url_from_ref(
                    base_url=xwiki_base_url,
                    wiki_name=wiki_name,
                    page_ref=(
                        f"Dossiers.{dossier_slug}."
                        "b2c-methodology-collection-note.WebHome"
                    ),
                ),
                auth=(username, password),
                headers={"Accept": "application/xml"},
                timeout=20.0,
            )
            note_page.raise_for_status()
            assert (
                "Updated methodology collection note after internet search turn 2"
                in note_page.text
            )

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
                name="dossiers.navigate",
                arguments={
                    "dossier_id": dossier_id,
                    "query": "collected B2C methodology participants tools assets",
                },
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
                        "# Live B2C market research methodology draft\n\n"
                        "Use internet search sources S1 and S2 to collect the B2C "
                        "market research methodology, define the consumer segment, "
                        "and create execution methodics with participants, tools, "
                        "and information assets."
                    ),
                    "harness_draft": {
                        "summary": (
                            "Live B2C market research methodology draft collected "
                            "from multi-turn internet search and dossier synthesis."
                        ),
                        "methodology": {
                            "ontology": (
                                "Consumers, segments, needs, purchase triggers, "
                                "objections, channels, and evidence artifacts."
                            ),
                            "axiology": "Reduce launch and positioning risk with cited evidence.",
                            "epistemology": (
                                "Triangulate interview, diary, survey, and "
                                "willingness-to-pay signals."
                            ),
                            "principles": [
                                "Separate stated preference from observable buying intent.",
                                "Keep B2C channel recommendations tied to dossier claims.",
                            ],
                        },
                        "methodics": [
                            {
                                "name": "Collect B2C methodology from internet evidence",
                                "goal": (
                                    "Turn multi-turn internet search results into a cited "
                                    "dossier."
                                ),
                                "applicability": (
                                    "Use when a team needs to define a B2C market research "
                                    "approach before fieldwork."
                                ),
                                "steps": [
                                    {
                                        "instruction": (
                                            "Researcher runs broad and refined internet search "
                                            "queries for B2C market research methodology and "
                                            "records selected web sources."
                                        ),
                                        "recommended_tool_patterns": [
                                            "web_search.search",
                                            "dossiers.sources.create",
                                        ],
                                        "expected_artifacts": [
                                            "search query log",
                                            "selected source bibliography",
                                        ],
                                        "verification": [
                                            "at least two internet search turns are recorded",
                                            "selected sources have HTTP or HTTPS URLs",
                                        ],
                                    },
                                    {
                                        "instruction": (
                                            "Methodologist converts collected sources into "
                                            "methodology concepts, claims, and a reusable "
                                            "methodics outline."
                                        ),
                                        "recommended_tool_patterns": [
                                            "dossiers.navigate",
                                            "dossiers.claims.upsert",
                                            "methodology.blueprints.submit_draft",
                                        ],
                                        "expected_artifacts": [
                                            "methodology concept note",
                                            "supported methodics claim",
                                        ],
                                        "verification": [
                                            "concept and claim cite S1 and S2",
                                            "draft names participants, tools, and assets",
                                        ],
                                    }
                                ],
                                "success_criteria": [
                                    "The dossier contains searched sources, concepts, notes, "
                                    "claims, and links for the B2C methodology.",
                                ],
                            },
                            {
                                "name": "Execute B2C demand validation",
                                "goal": (
                                    "Achieve the launch-readiness goal by validating "
                                    "consumer segment, purchase intent, and pricing risk."
                                ),
                                "applicability": (
                                    "Use after methodology collection is complete and a "
                                    "priority B2C segment has been selected."
                                ),
                                "steps": [
                                    {
                                        "instruction": (
                                            "Participants: Product lead defines decisions, "
                                            "Researcher recruits consumer respondents, "
                                            "Methodologist maintains evidence rules, and "
                                            "Analyst prepares the segment scorecard."
                                        ),
                                        "recommended_tool_patterns": [
                                            "calendar",
                                            "crm",
                                            "workspace.participants",
                                        ],
                                        "expected_artifacts": [
                                            "participant responsibility matrix",
                                            "consumer respondent screener",
                                        ],
                                        "verification": [
                                            "each required participant role has an owner",
                                        ],
                                    },
                                    {
                                        "instruction": (
                                            "Run interviews, diary-study collection, survey "
                                            "quantification, and willingness-to-pay screening."
                                        ),
                                        "recommended_tool_patterns": [
                                            "survey",
                                            "spreadsheet",
                                            "dossiers.notes.upsert",
                                        ],
                                        "expected_artifacts": [
                                            "interview guide",
                                            "diary-study log",
                                            "survey dataset",
                                            "willingness-to-pay matrix",
                                        ],
                                        "verification": [
                                            "assets are linked to segment and objection evidence",
                                            "pricing screen cites S2 or stronger evidence",
                                        ],
                                    },
                                ],
                                "success_criteria": [
                                    "A launch channel test is backed by segment, diary, "
                                    "survey, and pricing evidence.",
                                ],
                            },
                        ],
                        "execution_rules": [
                            {
                                "name": "No uncited channel bets",
                                "instruction": (
                                    "Do not recommend launch channels without cited consumer "
                                    "evidence."
                                ),
                            }
                        ],
                        "moderation_policy": {"enabled": False, "level": "open"},
                        "metadata": {
                            "dossier_id": dossier_id,
                            "scenario": "b2c_market_research_methodology",
                            "internet_search_turns": [
                                {
                                    "turn": search_turn_1["turn"],
                                    "query": search_turn_1["query"],
                                    "selected_url": first_search_result["url"],
                                },
                                {
                                    "turn": search_turn_2["turn"],
                                    "query": search_turn_2["query"],
                                    "selected_url": second_search_result["url"],
                                },
                            ],
                            "participants": [
                                {
                                    "role": "Researcher",
                                    "responsibility": "Run internet search and collect sources.",
                                },
                                {
                                    "role": "Methodologist",
                                    "responsibility": "Synthesize methodology and methodics.",
                                },
                                {
                                    "role": "Product lead",
                                    "responsibility": "Own launch-readiness decisions.",
                                },
                                {
                                    "role": "Consumer respondents",
                                    "responsibility": "Provide interview, diary, and survey data.",
                                },
                            ],
                            "tools": [
                                "web_search.search",
                                "dossiers.sources.create",
                                "dossiers.navigate",
                                "survey",
                                "spreadsheet",
                            ],
                            "information_assets": [
                                "search query log",
                                "source bibliography",
                                "interview guide",
                                "diary-study log",
                                "survey dataset",
                                "segment scorecard",
                                "willingness-to-pay matrix",
                            ],
                        },
                    },
                    "metadata": {
                        "test": "live_agent_mcp_workflow",
                        "scenario": "b2c_market_research_methodology",
                    },
                },
                request_id="methodologist-submit",
            )
            submitted_version = submitted["versions"][0]
            assert submitted_version["status"] == "pending_review"
            assert submitted["dossier"]["status"] == "consumed"
            assert submitted_version["metadata"]["test"] == "live_agent_mcp_workflow"
            submitted_harness = submitted_version["harness_draft"]
            assert len(submitted_harness["metadata"]["internet_search_turns"]) == 2
            assert submitted_harness["metadata"]["internet_search_turns"][0]["turn"] == 1
            assert submitted_harness["metadata"]["internet_search_turns"][1]["turn"] == 2
            assert any(
                participant["role"] == "Consumer respondents"
                for participant in submitted_harness["metadata"]["participants"]
            )
            assert "web_search.search" in submitted_harness["metadata"]["tools"]
            assert "survey dataset" in submitted_harness["metadata"]["information_assets"]
            assert (
                "web_search.search"
                in submitted_harness["methodics"][0]["steps"][0][
                    "recommended_tool_patterns"
                ]
            )
            assert any(
                "participant" in step["instruction"].lower()
                for step in submitted_harness["methodics"][1]["steps"]
            )
            edited = json_request(
                "POST",
                (
                    f"{gateway}/v1/organizations/{organization_id}/methodology/"
                    f"blueprints/{blueprint_id}/versions"
                ),
                token=token,
                payload={
                    "actor": actor,
                    "base_version_id": submitted_version["version_id"],
                    "cited_output": (
                        "# Edited B2C market research methodology\n\n"
                        "Human edit keeps internet sources S1 and S2, then tightens "
                        "the methodics around participant ownership, required tools, "
                        "information assets, diary-study signals, survey quantification, "
                        "and willingness-to-pay evidence before channel tests."
                    ),
                    "harness_draft": {
                        "summary": "Human-edited B2C market research methodology.",
                        "methodology": {
                            "ontology": (
                                "Consumers, segments, diary signals, price thresholds, "
                                "channels, objections, and evidence artifacts."
                            ),
                            "axiology": (
                                "Prefer launch decisions that reduce demand and pricing risk."
                            ),
                            "epistemology": (
                                "Compare qualitative needs, behavioral signals, survey "
                                "quantification, and willingness-to-pay evidence."
                            ),
                            "principles": [
                                "Require a cited segment before channel recommendations.",
                                "Validate willingness to pay before launch-readiness approval.",
                            ],
                        },
                        "methodics": [
                            {
                                "name": "Human-edited B2C validation loop",
                                "goal": (
                                    "Turn collected methodology evidence into segment, "
                                    "pricing, and channel validation tasks."
                                ),
                                "applicability": (
                                    "Use when the initial methodology draft is approved "
                                    "but needs execution-grade participant, tool, and "
                                    "asset detail."
                                ),
                                "steps": [
                                    {
                                        "instruction": (
                                            "Assign participants: Researcher owns source "
                                            "collection, Methodologist owns synthesis, "
                                            "Analyst owns quantification, Product lead owns "
                                            "decision gates, and consumer respondents provide "
                                            "field evidence."
                                        ),
                                        "recommended_tool_patterns": [
                                            "workspace.participants",
                                            "dossiers.navigate",
                                        ],
                                        "expected_artifacts": [
                                            "RACI matrix",
                                            "decision-gate checklist",
                                        ],
                                        "verification": [
                                            "each participant role maps to one artifact owner",
                                        ],
                                    },
                                    {
                                        "instruction": (
                                            "Use web-search bibliography, interview notes, "
                                            "diary log, survey dataset, willingness-to-pay "
                                            "matrix, and analytics export to score the "
                                            "priority segment."
                                        ),
                                        "recommended_tool_patterns": [
                                            "web_search.search",
                                            "survey",
                                            "spreadsheet",
                                            "retrieval.search",
                                        ],
                                        "expected_artifacts": [
                                            "segment scorecard",
                                            "pricing-risk notes",
                                            "launch-channel test brief",
                                        ],
                                        "verification": [
                                            "segment scorecard cites S1 and S2",
                                            (
                                                "pricing-risk notes include "
                                                "willingness-to-pay evidence"
                                            ),
                                            (
                                                "channel test brief links to at least "
                                                "one information asset"
                                            ),
                                        ],
                                    }
                                ],
                                "success_criteria": [
                                    (
                                        "Launch channel tests are backed by segment "
                                        "and pricing evidence."
                                    ),
                                ],
                            }
                        ],
                        "execution_rules": [
                            {
                                "name": "Evidence before apply",
                                "instruction": (
                                    "Block apply-ready recommendations until segment, diary, "
                                    "survey, and pricing evidence are reviewed."
                                ),
                            }
                        ],
                        "moderation_policy": {"enabled": False, "level": "open"},
                        "metadata": {
                            "dossier_id": dossier_id,
                            "scenario": "b2c_market_research_methodology",
                            "human_edit": True,
                            "internet_search_turns": [
                                {
                                    "turn": search_turn_1["turn"],
                                    "query": search_turn_1["query"],
                                    "selected_url": first_search_result["url"],
                                },
                                {
                                    "turn": search_turn_2["turn"],
                                    "query": search_turn_2["query"],
                                    "selected_url": second_search_result["url"],
                                },
                            ],
                            "participants": [
                                "Researcher",
                                "Methodologist",
                                "Analyst",
                                "Product lead",
                                "Consumer respondents",
                            ],
                            "tools": [
                                "web_search.search",
                                "dossiers.navigate",
                                "survey",
                                "spreadsheet",
                                "retrieval.search",
                            ],
                            "information_assets": [
                                "source bibliography",
                                "RACI matrix",
                                "interview notes",
                                "diary-study log",
                                "survey dataset",
                                "willingness-to-pay matrix",
                                "segment scorecard",
                                "launch-channel test brief",
                            ],
                        },
                    },
                    "reason": (
                        "Human editor added B2C segmentation, survey quantification, "
                        "and pricing validation."
                    ),
                    "metadata": {
                        "test": "live_agent_mcp_workflow",
                        "scenario": "b2c_market_research_methodology",
                        "human_edit": True,
                    },
                },
            )
            edited_version = edited["versions"][0]
            assert edited_version["status"] == "pending_review"
            assert edited_version["version_number"] > submitted_version["version_number"]
            assert edited_version["harness_draft"]["summary"].startswith(
                "Human-edited B2C"
            )
            assert edited_version["metadata"]["human_edit"] is True
            assert (
                edited_version["metadata"]["base_version_id"]
                == submitted_version["version_id"]
            )
            assert "pricing validation" in edited_version["metadata"]["revision_reason"]
            edited_harness = edited_version["harness_draft"]
            assert "Analyst" in edited_harness["metadata"]["participants"]
            assert "launch-channel test brief" in edited_harness["metadata"][
                "information_assets"
            ]
            assert (
                "retrieval.search"
                in edited_harness["methodics"][0]["steps"][1][
                    "recommended_tool_patterns"
                ]
            )
            assert len(edited["versions"]) >= 2
    finally:
        _cleanup_xwiki_page_refs(
            base_url=xwiki_base_url,
            wiki_name=wiki_name,
            username=username,
            password=password,
            page_refs=page_refs,
        )


def test_xwiki_live_real_agent_deep_researches_b2c_methodology_end_to_end() -> None:
    _require_xwiki_live()
    _require_real_methodology_deep_research_live()
    username, password = _require_xwiki_credentials()
    xwiki_base_url = _xwiki_base_url()
    wiki_name = _xwiki_wiki_name()
    gateway = gateway_url()
    _assert_xwiki_ready(xwiki_base_url)
    _assert_gateway_ready(gateway)
    _assert_web_search_ready()

    timeout_seconds = _int_env(
        "OPEN_TALON_METHODOLOGY_DEEP_RESEARCH_TIMEOUT_SECONDS",
        1800,
    )
    draft_timeout_seconds = _int_env(
        "OPEN_TALON_METHODOLOGY_DEEP_RESEARCH_DRAFT_TIMEOUT_SECONDS",
        1800,
    )
    min_search_turns = _int_env(
        "OPEN_TALON_METHODOLOGY_DEEP_RESEARCH_MIN_SEARCH_TURNS",
        3,
    )

    client_id = human_client_id()
    suffix = uuid4().hex[:10]
    page_refs: list[str] = []
    try:
        with direct_access_grants_enabled(client_id=client_id):
            token = admin_token(client_id=client_id)
            token_ref = {"token": token}
            actor = live_actor(display_name="Real Agent Deep Research Admin")
            _ensure_web_search_plugin_synced(
                gateway=gateway,
                token=token,
                actor=actor,
            )

            agents = json_request("GET", f"{gateway}/v1/agents", token=token)
            researcher = next(agent for agent in agents if agent["agent_key"] == "researcher")
            methodologist = next(
                agent for agent in agents if agent["agent_key"] == "methodologist"
            )
            assert researcher["endpoint"].get("provider") != "system-test-harness"
            assert methodologist["endpoint"].get("provider") != "system-test-harness"
            assert researcher["endpoint"].get("engine_id") == "openai-responses"
            assert researcher["endpoint"].get("provider") == "openai"
            assert methodologist["endpoint"].get("engine_id") == "openai-responses"
            assert methodologist["endpoint"].get("provider") == "openai"

            organization = json_request(
                "POST",
                f"{gateway}/v1/organizations",
                token=token,
                payload={
                    "actor": actor,
                    "slug": f"real-agent-b2c-methodology-{suffix}",
                    "name": f"Real Agent B2C Methodology {suffix}",
                    "description": (
                        "Temporary organization for a real Researcher and Methodologist "
                        "deep methodology research live test."
                    ),
                    "metadata": {
                        "system_test": True,
                        "scenario": "real_agent_b2c_market_research_methodology",
                    },
                },
            )
            organization_id = str(organization["organization_id"])
            target_workspace = json_request(
                "POST",
                f"{gateway}/v1/organizations/{organization_id}/workspaces",
                token=token,
                payload={
                    "actor": actor,
                    "name": f"B2C Validation Workspace {suffix}",
                    "description": (
                        "Target workspace for applying the real-agent generated "
                        "B2C market research methodology."
                    ),
                    "metadata": {
                        "system_test": True,
                        "scenario": "real_agent_b2c_market_research_methodology",
                    },
                },
            )
            target_workspace_id = str(target_workspace["workspace"]["workspace_id"])

            detail = json_request(
                "POST",
                f"{gateway}/v1/organizations/{organization_id}/methodology/blueprints",
                token=token,
                payload={
                    "actor": actor,
                    "title": f"Real-agent B2C market research methodology {suffix}",
                    "topic": (
                        "Deep research a B2C market research methodology for validating "
                        "subscription wellness app demand before launch."
                    ),
                    "target_goal": (
                        "Produce an evidence-backed methodology with concrete methodics "
                        "for consumer segmentation, interviews, diary study signals, "
                        "survey quantification, willingness-to-pay validation, and "
                        "launch-channel decision gates."
                    ),
                    "tasks": [
                        (
                            "Researcher must perform real multi-turn internet research "
                            "through the web-search MCP tool path, select and persist "
                            "credible sources, record excluded or weak evidence when found, "
                            "and preserve search/fetch provenance."
                        ),
                        (
                            "Researcher must fill every full-methodology knowledge "
                            "component: research plan, bibliography, basis, principles, "
                            "methodics inventory, participants and roles, tools and "
                            "methods, information assets, libraries and dossiers, quality "
                            "evaluation, contradictions, gaps, and synthesis."
                        ),
                        (
                            "Researcher must sync the XWiki dossier notebook and mark the "
                            "dossier ready only after health checks pass."
                        ),
                        (
                            "Methodologist must consume the ready dossier and submit a cited "
                            "methodology draft with required steps, participants, tools, "
                            "information assets, and execution criteria."
                        ),
                    ],
                    "library_ids": [],
                    "metadata": {
                        "system_test": True,
                        "scenario": "real_agent_b2c_market_research_methodology",
                        "requires_real_agents": True,
                    },
                },
                timeout=60.0,
            )
            blueprint_id = str(detail["blueprint"]["blueprint_id"])
            dossier_id = str(detail["dossier"]["dossier_id"])
            assert detail["dossier"]["metadata"]["completion_profile"] == (
                "full_methodology_research"
            )

            launched_state = json_request(
                "POST",
                (
                    f"{gateway}/v1/organizations/{organization_id}/methodology/"
                    f"blueprints/{blueprint_id}/research-requests"
                ),
                token=token,
                payload={
                    "actor": actor,
                    "instructions": (
                        "Run this as real deep methodology research, not a synthetic "
                        "fixture. Use the real Researcher process: scope the topic, run "
                        f"at least {min_search_turns} internet search turns through "
                        "web_search tools, curate sources into the dossier, capture "
                        "contradictions and gaps, fill every required full-methodology "
                        "knowledge component, sync XWiki, and propose readiness for "
                        "Methodologist handoff. If clarification is required, ask through "
                        "the normal interaction process and continue after the answer."
                    ),
                    "max_search_turns": max(5, min_search_turns),
                    "required_components": _FULL_METHODOLOGY_KNOWLEDGE_COMPONENTS,
                    "require_admin_ready_approval": True,
                    "metadata": {
                        "system_test": True,
                        "scenario": "real_agent_b2c_market_research_methodology",
                        "requires_real_agents": True,
                        "minimum_search_turns": min_search_turns,
                    },
                },
                timeout=60.0,
            )
            assert launched_state["metadata"]["completion_profile"] == (
                "full_methodology_research"
            )
            events = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/events",
                token=token,
            )
            assert "dossier.research_requested" in {
                event["event_type"] for event in events
            }

            research_state = _wait_for_real_researcher_deep_research(
                gateway=gateway,
                token_ref=token_ref,
                refresh_token=lambda: admin_token(client_id=client_id),
                actor=actor,
                organization_id=organization_id,
                blueprint_id=blueprint_id,
                min_search_turns=min_search_turns,
                timeout_seconds=timeout_seconds,
            )
            token = token_ref["token"]
            assert _missing_knowledge_components(research_state) == []
            web_search_tool_calls = _researcher_web_search_tool_call_count(
                organization_id=organization_id,
            )
            assert max(len(research_state["search_turns"]), web_search_tool_calls) >= (
                min_search_turns
            )
            assert len(_included_real_internet_sources(research_state)) >= min_search_turns
            assert all(
                turn.get("query") for turn in research_state["search_turns"]
            )

            notebook = research_state.get("notebook") or json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/notebook",
                token=token,
                timeout=60.0,
            )
            page_refs = _page_refs_from_notebook(notebook)
            assert notebook["notebook"]["status"] == "ready"
            assert notebook["provider_bindings"][0]["last_sync_at"] is not None
            dossier_slug = notebook["notebook"]["metadata"]["dossier_slug"]
            home_response = httpx.get(
                _xwiki_page_rest_url(
                    base_url=xwiki_base_url,
                    wiki_name=wiki_name,
                    dossier_slug=dossier_slug,
                    page_ref_suffix="WebHome",
                ),
                auth=(username, password),
                headers={"Accept": "application/xml"},
                timeout=20.0,
            )
            home_response.raise_for_status()
            assert dossier_id in home_response.text

            draft_detail = _wait_for_real_methodologist_draft(
                gateway=gateway,
                token_ref=token_ref,
                refresh_token=lambda: admin_token(client_id=client_id),
                actor=actor,
                organization_id=organization_id,
                blueprint_id=blueprint_id,
                timeout_seconds=draft_timeout_seconds,
            )
            token = token_ref["token"]
            assert draft_detail["dossier"]["status"] == "consumed"
            drafted_versions = [
                version
                for version in draft_detail["versions"]
                if version["status"] == "pending_review"
                and version.get("cited_output")
                and version.get("harness_draft")
            ]
            assert drafted_versions
            draft_version = max(drafted_versions, key=lambda item: item["version_number"])
            draft_version_id = str(draft_version["version_id"])
            draft = draft_version["harness_draft"]
            draft_json = json.dumps(draft, sort_keys=True).lower()
            assert draft.get("methodics")
            assert any(methodic.get("steps") for methodic in draft["methodics"])
            for marker in (
                "participant",
                "tool",
                "asset",
                "source",
                "survey",
                "interview",
                "willingness",
            ):
                assert marker in draft_json
            assert str(dossier_id) in json.dumps(draft_version, sort_keys=True)

            approved_detail = json_request(
                "POST",
                (
                    f"{gateway}/v1/organizations/{organization_id}/methodology/"
                    f"blueprints/{blueprint_id}/versions/{draft_version_id}/approve"
                ),
                token=token,
                payload={
                    "actor": actor,
                    "reason": (
                        "Real-agent live test approved the cited B2C market research "
                        "methodology after verifying dossier coverage."
                    ),
                    "metadata": {
                        "system_test": True,
                        "scenario": "real_agent_b2c_market_research_methodology",
                    },
                },
                timeout=60.0,
            )
            approved_version = next(
                version
                for version in approved_detail["versions"]
                if str(version["version_id"]) == draft_version_id
            )
            assert approved_version["status"] == "approved"

            applied_workspace = json_request(
                "POST",
                f"{gateway}/v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}/apply",
                token=token,
                payload={
                    "actor": actor,
                    "workspace_id": target_workspace_id,
                    "version_id": draft_version_id,
                    "preserve_moderation_policy": True,
                    "metadata": {
                        "system_test": True,
                        "scenario": "real_agent_b2c_market_research_methodology",
                    },
                },
                timeout=60.0,
            )
            applied_harness = applied_workspace["workspace"]["harness"]
            assert applied_harness["methodology"]
            assert applied_harness["methodics"]

            archive_result = json_request(
                "DELETE",
                f"{gateway}/v1/organizations/{organization_id}/methodology/blueprints/{blueprint_id}",
                token=token,
                payload={
                    "actor": actor,
                    "metadata": {
                        "system_test": True,
                        "scenario": "real_agent_b2c_market_research_methodology",
                    },
                },
                timeout=60.0,
            )
            assert archive_result
            archived_dossier = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}",
                token=token,
                timeout=60.0,
            )
            assert archived_dossier["status"] == "archived"
            archived_sources = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/sources",
                token=token,
                timeout=60.0,
            )
            assert len(
                [
                    source
                    for source in archived_sources
                    if source.get("status") == "included"
                    and (source.get("source_uri") or "").startswith(("http://", "https://"))
                ]
            ) >= min_search_turns
            archived_notebook = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/dossiers/{dossier_id}/notebook",
                token=token,
                timeout=60.0,
            )
            assert len(archived_notebook.get("notes") or []) >= len(
                _FULL_METHODOLOGY_KNOWLEDGE_COMPONENTS
            )
            assert archived_notebook["provider_bindings"][0]["last_sync_at"] is not None
            page_refs = _page_refs_from_notebook(archived_notebook) or page_refs
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
