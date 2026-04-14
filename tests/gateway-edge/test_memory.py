from __future__ import annotations


async def _create_workspace(client, actor_payload) -> str:
    resp = await client.post(
        "/v1/workspaces",
        json={"name": "Memory", "actor": actor_payload},
    )
    return resp.json()["workspace"]["workspace_id"]


async def _create_thread(client, workspace_id: str, actor_payload) -> str:
    resp = await client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        json={"title": "Memory thread", "actor": actor_payload},
    )
    return resp.json()["thread"]["thread_id"]


async def test_workspace_memory_crud_flow(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)

    create_resp = await client.post(
        f"/v1/workspaces/{workspace_id}/memory",
        json={
            "actor": actor_payload,
            "entry_type": "decision",
            "summary": "Kernel ownership",
            "content": "core-collab owns sequencing",
            "visibility": "workspace",
            "metadata": {"kind": "architecture"},
        },
    )
    assert create_resp.status_code == 200
    entry = create_resp.json()
    assert entry["scope"] == "workspace"
    assert entry["state"] == "confirmed"

    list_resp = await client.get(f"/v1/workspaces/{workspace_id}/memory")
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["summary"] == "Kernel ownership"

    update_resp = await client.patch(
        f"/v1/workspaces/{workspace_id}/memory/{entry['memory_entry_id']}",
        json={
            "actor": actor_payload,
            "content": "core-collab owns canonical sequencing and projections",
            "summary": "Canonical kernel ownership",
            "metadata": {"confirmed": True},
        },
    )
    assert update_resp.status_code == 200
    assert "canonical sequencing" in update_resp.json()["content"]
    assert update_resp.json()["summary"] == "Canonical kernel ownership"
    assert update_resp.json()["version"] == 2

    delete_resp = await client.request(
        "DELETE",
        f"/v1/workspaces/{workspace_id}/memory/{entry['memory_entry_id']}",
        json=actor_payload,
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    final_list_resp = await client.get(f"/v1/workspaces/{workspace_id}/memory")
    assert final_list_resp.status_code == 200
    assert final_list_resp.json() == []


async def test_thread_memory_search_and_workspace_confirmation(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)
    thread_id = await _create_thread(client, workspace_id, actor_payload)

    create_resp = await client.post(
        f"/v1/threads/{thread_id}/memory",
        json={
            "actor": actor_payload,
            "entry_type": "decision",
            "summary": "Sequencing decision",
            "content": "Thread participants agreed core-collab should remain canonical.",
            "visibility": "workspace",
        },
    )
    assert create_resp.status_code == 200
    thread_entry = create_resp.json()
    assert thread_entry["scope"] == "thread"
    assert thread_entry["thread_id"] == thread_id

    list_resp = await client.get(f"/v1/threads/{thread_id}/memory")
    assert list_resp.status_code == 200
    assert [entry["summary"] for entry in list_resp.json()] == ["Sequencing decision"]

    search_resp = await client.post(
        f"/v1/threads/{thread_id}/memory/search",
        json={
            "actor": actor_payload,
            "query": "canonical",
            "limit": 5,
            "use_provider": "postgres",
            "include_graph": False,
        },
    )
    assert search_resp.status_code == 200
    search_body = search_resp.json()
    assert search_body["provider"] == "postgres"
    assert search_body["results"][0]["entry"]["memory_entry_id"] == thread_entry["memory_entry_id"]

    confirm_resp = await client.post(
        f"/v1/workspaces/{workspace_id}/memory/confirm",
        json={
            "actor": actor_payload,
            "source_memory_entry_id": thread_entry["memory_entry_id"],
            "summary": "Canonical ownership decision",
            "visibility": "workspace",
        },
    )
    assert confirm_resp.status_code == 200
    confirmed = confirm_resp.json()
    assert confirmed["scope"] == "workspace"
    assert confirmed["confirmed_by"] == actor_payload["participant_id"]
    assert confirmed["metadata"]["source_memory_entry_id"] == thread_entry["memory_entry_id"]

    workspace_memory_resp = await client.get(f"/v1/workspaces/{workspace_id}/memory")
    assert workspace_memory_resp.status_code == 200
    assert workspace_memory_resp.json()[0]["summary"] == "Canonical ownership decision"


async def test_thread_memory_update_and_delete_flow(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)
    thread_id = await _create_thread(client, workspace_id, actor_payload)

    create_resp = await client.post(
        f"/v1/threads/{thread_id}/memory",
        json={
            "actor": actor_payload,
            "entry_type": "note",
            "summary": "Draft rollout note",
            "content": "Need a final validation pass.",
            "visibility": "workspace",
        },
    )
    entry = create_resp.json()

    update_resp = await client.patch(
        f"/v1/threads/{thread_id}/memory/{entry['memory_entry_id']}",
        json={
            "actor": actor_payload,
            "content": "Need a final validation and migration pass.",
            "summary": "Validated rollout note",
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["summary"] == "Validated rollout note"
    assert update_resp.json()["version"] == 2

    delete_resp = await client.request(
        "DELETE",
        f"/v1/threads/{thread_id}/memory/{entry['memory_entry_id']}",
        json=actor_payload,
    )
    assert delete_resp.status_code == 200

    list_resp = await client.get(f"/v1/threads/{thread_id}/memory")
    assert list_resp.status_code == 200
    assert list_resp.json() == []


async def test_list_memory_returns_404_for_unknown_workspace(client):
    resp = await client.get("/v1/workspaces/00000000-0000-0000-0000-000000000001/memory")
    assert resp.status_code == 404
