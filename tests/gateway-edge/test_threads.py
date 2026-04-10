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
