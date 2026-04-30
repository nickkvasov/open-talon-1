from __future__ import annotations

import json
import threading
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from .harnesses import (
    MethodologistTaskHarnessHandler,
    MethodologistTaskHarnessServer,
    MethodologistTaskHarnessState,
)
from .helpers import (
    admin_token,
    direct_access_grants_enabled,
    gateway_url,
    human_client_id,
    json_request,
    live_actor,
    postgres_dsn,
    require_live_operational_agents,
    wait_for,
)


pytestmark = pytest.mark.integration


def _actor_from_participant(participant: dict[str, Any]) -> dict[str, Any]:
    actor = {
        "participant_id": participant["participant_id"],
        "participant_type": participant["participant_type"],
        "display_name": participant["display_name"],
    }
    for key in ("user_id", "description", "roles", "capabilities", "visibility_scope"):
        if participant.get(key) is not None:
            actor[key] = participant[key]
    return actor


def _insert_retriever_context_pack(
    *,
    organization_id: str,
    workspace_id: str,
    created_by: str,
) -> tuple[str, str, str]:
    context_pack_id = str(uuid4())
    source_id = str(uuid4())
    content = (
        f"[1] source={source_id}; chunk=0; page=12; section=Methodology Basis\n"
        "The methodology begins with evidence-first diagnosis, shared interpretation, "
        "and explicit verification criteria before implementation begins.\n\n"
        f"[2] source={source_id}; chunk=1; page=13; section=Methodics\n"
        "The operating methodics are to collect evidence, record decision context, "
        "assign artifact work, review artifacts against criteria, and log gaps."
    )
    with psycopg.connect(postgres_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT project_id FROM workspaces WHERE workspace_id = %s::uuid",
                (workspace_id,),
            )
            project_row = cur.fetchone()
            if project_row is None:
                raise AssertionError(f"Workspace {workspace_id} not found")
            project_id = str(project_row[0])
            cur.execute(
                """
                INSERT INTO retrieval_context_packs (
                    context_pack_id, run_id, scope, organization_id, project_id, workspace_id,
                    profile_id, query, content, token_count, hits, created_by, created_at,
                    metadata
                )
                VALUES (
                    %s::uuid, NULL, 'workspace', %s::uuid, %s::uuid, %s::uuid,
                    NULL, %s, %s, %s, %s::jsonb, %s::uuid, NOW(), %s::jsonb
                )
                """,
                (
                    context_pack_id,
                    organization_id,
                    project_id,
                    workspace_id,
                    "evidence-backed incident learning methodology",
                    content,
                    len(content.split()),
                    json.dumps([]),
                    created_by,
                    json.dumps(
                        {
                            "system_test": True,
                            "source": "operational_methodologist_live_test",
                            "fixture_kind": "bounded_retriever_context_pack",
                        }
                    ),
                ),
            )
        conn.commit()
    return context_pack_id, source_id, content


def test_methodologist_live_extracts_template_from_cited_retriever_evidence():
    require_live_operational_agents()
    gateway = gateway_url()
    client_id = human_client_id()
    actor = live_actor(display_name="Methodologist Live Admin")
    server: MethodologistTaskHarnessServer | None = None
    server_thread: threading.Thread | None = None
    original_methodologist_endpoint: dict[str, Any] | None = None
    methodologist_id: str | None = None
    token: str | None = None

    with direct_access_grants_enabled(client_id=client_id):
        try:
            token = admin_token(client_id=client_id)
            suffix = uuid4().hex[:10]
            organization = json_request(
                "POST",
                f"{gateway}/v1/organizations",
                token=token,
                payload={
                    "actor": actor,
                    "slug": f"methodologist-live-{suffix}",
                    "name": f"Methodologist Live {suffix}",
                    "metadata": {"system_test": True},
                },
            )
            organization_id = str(organization["organization_id"])
            me = json_request("GET", f"{gateway}/v1/me", token=token)
            organization_members = json_request(
                "GET",
                f"{gateway}/v1/organizations/{organization_id}/members",
                token=token,
            )
            if not any(member["user_id"] == me["user_id"] for member in organization_members):
                json_request(
                    "POST",
                    f"{gateway}/v1/organizations/{organization_id}/members",
                    token=token,
                    payload={
                        "actor": actor,
                        "user_id": me["user_id"],
                        "role": "owner",
                        "metadata": {"system_test": True},
                    },
                )
            workspace_detail = json_request(
                "POST",
                f"{gateway}/v1/organizations/{organization_id}/workspaces",
                token=token,
                payload={
                    "name": f"Methodologist Evidence {suffix}",
                    "description": "Live Methodologist evidence extraction workspace.",
                    "actor": actor,
                    "metadata": {"system_test": True},
                },
            )
            workspace_id = str(workspace_detail["workspace"]["workspace_id"])
            workspace_actor = _actor_from_participant(
                next(
                    participant
                    for participant in workspace_detail["participants"]
                    if participant["participant_type"] == "user"
                )
            )

            agents = json_request("GET", f"{gateway}/v1/agents", token=token)
            methodologist = next(agent for agent in agents if agent["agent_key"] == "methodologist")
            methodologist_id = str(methodologist["agent_id"])
            original_methodologist_endpoint = methodologist["endpoint"]

            context_pack_id, source_id, context_pack_content = _insert_retriever_context_pack(
                organization_id=organization_id,
                workspace_id=workspace_id,
                created_by=workspace_actor["participant_id"],
            )
            context_pack = json_request(
                "GET",
                (
                    f"{gateway}/v1/workspaces/{workspace_id}/retrieval/context-packs/"
                    f"{context_pack_id}"
                ),
                token=token,
            )
            assert context_pack["context_pack_id"] == context_pack_id
            assert f"source={source_id}" in context_pack["content"]

            harness_state = MethodologistTaskHarnessState(
                context_pack_id=context_pack_id,
                source_id=source_id,
            )
            server = MethodologistTaskHarnessServer(
                ("127.0.0.1", 0),
                MethodologistTaskHarnessHandler,
                state=harness_state,
            )
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            harness_url = f"http://127.0.0.1:{server.server_address[1]}/methodologist"

            json_request(
                "PATCH",
                f"{gateway}/v1/agents/{methodologist_id}",
                token=token,
                payload={
                    "actor": actor,
                    "endpoint": {
                        "kind": "remote",
                        "url": harness_url,
                        "model": methodologist["endpoint"].get("model"),
                        "provider": "system-test-harness",
                    },
                    "metadata": {"system_test_harness": True},
                },
            )

            methodologist_participant = json_request(
                "POST",
                f"{gateway}/v1/workspaces/{workspace_id}/agents",
                token=token,
                payload={"actor": workspace_actor, "agent_id": methodologist_id},
            )
            assert methodologist_participant["system_agent_id"] == methodologist_id

            thread_detail = json_request(
                "POST",
                f"{gateway}/v1/workspaces/{workspace_id}/threads",
                token=token,
                payload={
                    "title": "Methodologist Retriever Evidence Extraction",
                    "actor": workspace_actor,
                },
            )
            thread_id = str(thread_detail["thread"]["thread_id"])
            json_request(
                "POST",
                f"{gateway}/v1/threads/{thread_id}/messages",
                token=token,
                payload={
                    "actor": workspace_actor,
                    "content": (
                        "Methodologist, use the cited Retriever context pack below to extract "
                        "methodology basis, methodics, methods/tools/actors, and a workspace "
                        "template draft. Clearly separate source-backed claims from inferred "
                        "or ideated Open Talon implementation items.\n\n"
                        f"retrieval_context_pack_id: {context_pack_id}\n"
                        "query: evidence-backed incident learning methodology\n\n"
                        f"{context_pack_content}"
                    ),
                    "visibility": "workspace",
                    "target_system_agent_id": methodologist_id,
                    "task_instructions": [
                        "Use only the cited Retriever context pack as source evidence.",
                        "Cite source-derived claims with [1] or [2].",
                        "Label inferred or ideated tools and Open Talon implementation items.",
                        "Return the Methodologist response-contract sections.",
                    ],
                    "metadata": {
                        "system_test": True,
                        "retrieval_context_pack_id": context_pack_id,
                        "retrieval_source_id": source_id,
                    },
                },
            )

            assert wait_for(
                "Methodologist harness request with Retriever evidence",
                harness_state.saw_retriever_evidence,
                timeout_seconds=120.0,
                interval_seconds=1.0,
            )

            def final_methodologist_message() -> dict[str, Any] | None:
                timeline = json_request(
                    "GET",
                    f"{gateway}/v1/threads/{thread_id}/timeline",
                    token=token,
                )
                for message in reversed(timeline["messages"]):
                    actor_ref = message.get("actor") or {}
                    content = str(message.get("content") or "")
                    required_markers = [
                        "Methodology Basis",
                        "Methodics",
                        "Methods And Tools",
                        "Actors",
                        "Workspace Template",
                        "Source-backed",
                        "Inferred/ideated",
                        "WorkspaceHarness.methodology",
                        "WorkspaceHarness.methodics",
                        context_pack_id,
                        "[1]",
                        "[2]",
                    ]
                    if actor_ref.get("type") == "agent" and all(
                        marker in content for marker in required_markers
                    ):
                        return message
                return None

            final_message = wait_for(
                "Methodologist final methodology/template message",
                final_methodologist_message,
                timeout_seconds=180.0,
                interval_seconds=2.0,
            )
            content = str(final_message["content"])
            assert "evidence-first diagnosis" in content
            assert "Conductor can coordinate methodics execution only when attached" in content
            assert "Gap: the context pack is intentionally small" in content
        finally:
            if (
                original_methodologist_endpoint is not None
                and methodologist_id is not None
                and token is not None
            ):
                try:
                    json_request(
                        "PATCH",
                        f"{gateway}/v1/agents/{methodologist_id}",
                        token=token,
                        payload={
                            "actor": actor,
                            "endpoint": original_methodologist_endpoint,
                            "metadata": {"system_test_harness": False},
                        },
                    )
                except Exception:
                    pass
            if server is not None:
                server.shutdown()
                server.server_close()
            if server_thread is not None:
                server_thread.join(timeout=5.0)
