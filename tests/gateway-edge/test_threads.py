from __future__ import annotations


async def _create_workspace(client, actor_payload) -> str:
    resp = await client.post(
        "/v1/workspaces",
        json={"name": "Agents", "actor": actor_payload},
    )
    return resp.json()["workspace"]["workspace_id"]


async def _create_thread(client, workspace_id: str, actor_payload) -> str:
    resp = await client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        json={"title": "Execution", "actor": actor_payload},
    )
    return resp.json()["thread"]["thread_id"]


async def test_create_thread_returns_membership_detail(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)

    resp = await client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        json={"title": "Planning", "actor": actor_payload},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["thread"]["title"] == "Planning"
    assert body["memberships"][0]["participant_id"] == actor_payload["participant_id"]


async def test_list_threads_returns_created_thread(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)
    await _create_thread(client, workspace_id, actor_payload)

    resp = await client.get(f"/v1/workspaces/{workspace_id}/threads")
    assert resp.status_code == 200
    assert resp.json()[0]["title"] == "Execution"


async def test_post_message_appends_timeline_entry(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)
    thread_id = await _create_thread(client, workspace_id, actor_payload)

    post_resp = await client.post(
        f"/v1/threads/{thread_id}/messages",
        json={
            "actor": actor_payload,
            "content": "Ship the collaboration kernel",
            "visibility": "public",
        },
    )
    assert post_resp.status_code == 200
    assert post_resp.json()["content"] == "Ship the collaboration kernel"

    timeline_resp = await client.get(f"/v1/threads/{thread_id}/timeline")
    assert timeline_resp.status_code == 200
    timeline = timeline_resp.json()["messages"]
    assert len(timeline) == 1
    assert timeline[0]["content"] == "Ship the collaboration kernel"


async def test_get_thread_returns_404_for_unknown_thread(client):
    resp = await client.get("/v1/threads/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 404


async def test_create_list_and_answer_interaction_request(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)
    thread_id = await _create_thread(client, workspace_id, actor_payload)

    create_resp = await client.post(
        f"/v1/threads/{thread_id}/requests",
        json={
            "actor": actor_payload,
            "requests": [
                {
                    "title": "Need feedback",
                    "questions": [{"prompt": "What is blocking delivery?"}],
                    "selectors": [{"type": "participant", "value": actor_payload["display_name"]}],
                }
            ],
        },
    )
    assert create_resp.status_code == 200
    body = create_resp.json()
    assert body[0]["request"]["title"] == "Need feedback"
    request_id = body[0]["request"]["request_id"]

    list_resp = await client.get(f"/v1/threads/{thread_id}/requests")
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["request"]["request_id"] == request_id

    answer_resp = await client.post(
        f"/v1/requests/{request_id}/answers",
        json={
            "actor": actor_payload,
            "content": "Waiting on API review.",
            "question_ids": [],
        },
    )
    assert answer_resp.status_code == 200
    assert answer_resp.json()["answers"][0]["participant_id"] == actor_payload["participant_id"]


async def test_get_and_cancel_interaction_request(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)
    thread_id = await _create_thread(client, workspace_id, actor_payload)

    create_resp = await client.post(
        f"/v1/threads/{thread_id}/requests",
        json={
            "actor": actor_payload,
            "requests": [
                {
                    "title": "Need a decision",
                    "questions": [{"prompt": "Should we ship?"}],
                    "selectors": [{"type": "participant", "value": actor_payload["display_name"]}],
                }
            ],
        },
    )
    request_id = create_resp.json()[0]["request"]["request_id"]

    get_resp = await client.get(f"/v1/requests/{request_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["request"]["title"] == "Need a decision"

    cancel_resp = await client.patch(
        f"/v1/requests/{request_id}",
        json={
            "actor": actor_payload,
            "action": "cancel",
        },
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["request"]["status"] == "cancelled"


async def test_update_interaction_request_target_status(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)
    thread_id = await _create_thread(client, workspace_id, actor_payload)

    create_resp = await client.post(
        f"/v1/threads/{thread_id}/requests",
        json={
            "actor": actor_payload,
            "requests": [
                {
                    "title": "Need acknowledgement",
                    "questions": [{"prompt": "Can you confirm receipt?"}],
                    "selectors": [{"type": "participant", "value": actor_payload["display_name"]}],
                }
            ],
        },
    )
    created = create_resp.json()[0]
    request_id = created["request"]["request_id"]
    target_id = created["targets"][0]["target_id"]

    update_resp = await client.patch(
        f"/v1/requests/{request_id}",
        json={
            "actor": actor_payload,
            "action": "dismiss_target",
            "target_id": target_id,
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["targets"][0]["status"] == "dismissed"


async def test_post_message_with_requests_creates_atomic_request(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)
    thread_id = await _create_thread(client, workspace_id, actor_payload)

    post_resp = await client.post(
        f"/v1/threads/{thread_id}/messages",
        json={
            "actor": actor_payload,
            "content": "Please gather delivery blockers.",
            "visibility": "workspace",
            "create_task": False,
            "requests": [
                {
                    "title": "Need release feedback",
                    "questions": [{"prompt": "What blocks delivery?"}],
                    "selectors": [{"type": "participant", "value": actor_payload["display_name"]}],
                }
            ],
        },
    )
    assert post_resp.status_code == 200

    timeline_resp = await client.get(f"/v1/threads/{thread_id}/timeline")
    assert timeline_resp.status_code == 200
    timeline = timeline_resp.json()["messages"]
    assert len(timeline) == 2
    assert timeline[0]["content"] == "Please gather delivery blockers."
    assert timeline[1]["metadata"]["interaction_request_status"] == "open"

    requests_resp = await client.get(f"/v1/threads/{thread_id}/requests")
    assert requests_resp.status_code == 200
    assert requests_resp.json()[0]["questions"][0]["prompt"] == "What blocks delivery?"


async def test_workspace_communication_log_lists_messages_requests_and_answers(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)
    thread_id = await _create_thread(client, workspace_id, actor_payload)

    message_resp = await client.post(
        f"/v1/threads/{thread_id}/messages",
        json={
            "actor": actor_payload,
            "content": "Please gather delivery blockers.",
            "visibility": "workspace",
            "create_task": False,
        },
    )
    assert message_resp.status_code == 200

    create_resp = await client.post(
        f"/v1/threads/{thread_id}/requests",
        json={
            "actor": actor_payload,
            "requests": [
                {
                    "title": "Need backend feedback",
                    "questions": [{"prompt": "What blocks delivery?"}],
                    "selectors": [{"type": "participant", "value": actor_payload["display_name"]}],
                }
            ],
        },
    )
    assert create_resp.status_code == 200
    request_id = create_resp.json()[0]["request"]["request_id"]

    answer_resp = await client.post(
        f"/v1/requests/{request_id}/answers",
        json={
            "actor": actor_payload,
            "content": "API review is the blocker.",
            "question_ids": [],
        },
    )
    assert answer_resp.status_code == 200

    log_resp = await client.get(
        f"/v1/workspaces/{workspace_id}/communication-log",
        params={"thread_id": thread_id, "limit": 10, "offset": 0},
    )
    assert log_resp.status_code == 200
    body = log_resp.json()
    assert body["workspace_id"] == workspace_id
    assert body["total_count"] == 3
    assert {entry["kind"] for entry in body["entries"]} == {
        "message",
        "interaction_request",
        "interaction_answer",
    }
