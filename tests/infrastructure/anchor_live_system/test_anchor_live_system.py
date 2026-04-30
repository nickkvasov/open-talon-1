from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

_HELPERS_DIR = Path(__file__).resolve().parents[1] / "operational_agents_live"
if str(_HELPERS_DIR) not in sys.path:
    sys.path.insert(0, str(_HELPERS_DIR))

from helpers import (  # type: ignore  # noqa: E402
    admin_token,
    direct_access_grants_enabled,
    gateway_url,
    human_client_id,
    json_request,
    live_actor,
)


pytestmark = pytest.mark.integration


def _require_live_anchor() -> None:
    if os.getenv("OPEN_TALON_RUN_ANCHOR_LIVE") != "1":
        pytest.skip("Set OPEN_TALON_RUN_ANCHOR_LIVE=1 to run Anchor live tests")


def _wait_for_timeline(
    gateway: str,
    token: str,
    thread_id: str,
    predicate,
    *,
    timeout: float = 120.0,
):
    deadline = time.time() + timeout
    last_page = None
    while time.time() < deadline:
        last_page = json_request(
            "GET",
            f"{gateway}/v1/threads/{thread_id}/timeline",
            token=token,
        )
        if predicate(last_page):
            return last_page
        time.sleep(3)
    pytest.fail(f"timeline condition was not met before timeout: {last_page}")


def _create_anchor_workspace(gateway: str, token: str, *, level: str, topic: str) -> tuple[dict, dict]:
    suffix = uuid4().hex[:10]
    actor = live_actor()
    organization = json_request(
        "POST",
        f"{gateway}/v1/organizations",
        token=token,
        payload={
            "actor": actor,
            "slug": f"anchor-live-{suffix}",
            "name": f"Anchor Live {suffix}",
            "metadata": {"system_test": True},
        },
    )
    workspace_detail = json_request(
        "POST",
        f"{gateway}/v1/workspaces",
        token=token,
        payload={
            "actor": actor,
            "organization_id": organization["organization_id"],
            "name": f"Anchor Live {suffix}",
            "description": topic,
            "harness": {
                "version": 1,
                "summary": topic,
                "moderation_policy": {
                    "enabled": True,
                    "level": level,
                    "topic": topic,
                    "allowed_adjacent_topics": ["implementation tests"],
                    "blocked_topics": ["vacation planning", "restaurant recommendations"],
                    "explain_blocked_messages": True,
                },
            },
        },
    )
    workspace = workspace_detail["workspace"]
    participants = workspace_detail["participants"]
    anchor = next(item for item in participants if item.get("system_agent_id"))
    assert anchor["roles"] == ["workspace topic alignment reviewer"]
    assert anchor["metadata"]["task_routing"]["normal_message_fanout"] is False
    agents = json_request("GET", f"{gateway}/v1/agents", token=token)
    anchor_definition = next(item for item in agents if item.get("agent_key") == "anchor")
    assert anchor_definition["endpoint"]["engine_id"] == "local-ollama"
    assert anchor_definition["endpoint"]["provider"] == "ollama"
    thread_detail = json_request(
        "POST",
        f"{gateway}/v1/workspaces/{workspace['workspace_id']}/threads",
        token=token,
        payload={"actor": actor, "title": "Anchor Live Review"},
    )
    return workspace, thread_detail["thread"]


def test_anchor_live_strict_approval_and_block_paths():
    _require_live_anchor()
    gateway = gateway_url()
    client_id = human_client_id()

    with direct_access_grants_enabled(client_id=client_id):
        token = admin_token(client_id=client_id)
        actor = live_actor()
        workspace, thread = _create_anchor_workspace(
            gateway,
            token,
            level="strict",
            topic="Gateway runtime worker leases and publication review tests",
        )

        approved = json_request(
            "POST",
            f"{gateway}/v1/threads/{thread['thread_id']}/messages",
            token=token,
            payload={
                "actor": actor,
                "content": "Please review gateway runtime worker lease retry behavior.",
                "visibility": "workspace",
                "create_task": True,
            },
        )
        assert approved["status"] == "pending_moderation"
        _wait_for_timeline(
            gateway,
            token,
            thread["thread_id"],
            lambda page: any(
                message["content"] == "Please review gateway runtime worker lease retry behavior."
                for message in page["messages"]
            ),
        )

        blocked = json_request(
            "POST",
            f"{gateway}/v1/threads/{thread['thread_id']}/messages",
            token=token,
            payload={
                "actor": actor,
                "content": "Plan a beach vacation and restaurant itinerary.",
                "visibility": "workspace",
                "create_task": True,
            },
        )
        assert blocked["status"] == "pending_moderation"
        timeline = _wait_for_timeline(
            gateway,
            token,
            thread["thread_id"],
            lambda page: len(page["messages"]) >= 2,
        )
        assert all(
            message["content"] != "Plan a beach vacation and restaurant itinerary."
            for message in timeline["messages"]
        )
        log_page = json_request(
            "GET",
            f"{gateway}/v1/workspaces/{workspace['workspace_id']}/communication-log?thread_id={thread['thread_id']}",
            token=token,
        )
        assert all(
            entry["content"] != "Plan a beach vacation and restaurant itinerary."
            for entry in log_page["entries"]
        )


def test_anchor_live_balanced_flagging_path():
    _require_live_anchor()
    gateway = gateway_url()
    client_id = human_client_id()

    with direct_access_grants_enabled(client_id=client_id):
        token = admin_token(client_id=client_id)
        actor = live_actor()
        _workspace, thread = _create_anchor_workspace(
            gateway,
            token,
            level="balanced",
            topic="Gateway runtime worker leases and publication review tests",
        )

        message = json_request(
            "POST",
            f"{gateway}/v1/threads/{thread['thread_id']}/messages",
            token=token,
            payload={
                "actor": actor,
                "content": "Plan a beach vacation itinerary with hotel pools and restaurant reservations.",
                "visibility": "workspace",
                "create_task": False,
            },
        )
        assert message["status"] == "completed"
        page = _wait_for_timeline(
            gateway,
            token,
            thread["thread_id"],
            lambda timeline: any(
                item["message_id"] == message["message_id"]
                and item.get("metadata", {}).get("publication_review_status") == "flagged"
                for item in timeline["messages"]
            ),
            timeout=240.0,
        )
        flagged = next(item for item in page["messages"] if item["message_id"] == message["message_id"])
        assert flagged["metadata"]["publication_review_kind"] == "workspace_topic_alignment"
