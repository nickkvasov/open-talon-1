from __future__ import annotations


async def _create_workspace(client, actor_payload) -> str:
    resp = await client.post(
        "/v1/workspaces",
        json={"name": "Memory", "actor": actor_payload},
    )
    return resp.json()["workspace"]["workspace_id"]


async def test_memory_crud_flow(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)

    create_resp = await client.post(
        f"/v1/workspaces/{workspace_id}/memory",
        json={
            "actor": actor_payload,
            "entry_type": "decision",
            "title": "Kernel ownership",
            "content": "core-collab owns sequencing",
            "tags": ["architecture"],
            "visibility": "workspace",
        },
    )
    assert create_resp.status_code == 200
    entry = create_resp.json()

    list_resp = await client.get(f"/v1/workspaces/{workspace_id}/memory")
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["title"] == "Kernel ownership"

    update_resp = await client.patch(
        f"/v1/workspaces/{workspace_id}/memory/{entry['memory_entry_id']}",
        json={
            "actor": actor_payload,
            "content": "core-collab owns canonical sequencing and projections",
            "tags": ["architecture", "kernel"],
        },
    )
    assert update_resp.status_code == 200
    assert "canonical sequencing" in update_resp.json()["content"]
    assert update_resp.json()["version"] == 2

    delete_resp = await client.request(
        "DELETE",
        f"/v1/workspaces/{workspace_id}/memory/{entry['memory_entry_id']}",
        json=actor_payload,
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True


async def test_list_memory_returns_404_for_unknown_workspace(client):
    resp = await client.get("/v1/workspaces/00000000-0000-0000-0000-000000000001/memory")
    assert resp.status_code == 404
