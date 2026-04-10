from __future__ import annotations

from uuid import uuid4


async def test_create_workspace_returns_workspace_and_participants(client, actor_payload):
    resp = await client.post(
        "/v1/workspaces",
        json={
            "name": "Core Platform",
            "description": "Shared engineering workspace",
            "actor": actor_payload,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace"]["name"] == "Core Platform"
    assert body["participants"][0]["participant_id"] == actor_payload["participant_id"]


async def test_list_workspaces_returns_created_workspace(client, actor_payload):
    await client.post(
        "/v1/workspaces",
        json={"name": "Observability", "actor": actor_payload},
    )

    resp = await client.get("/v1/workspaces")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "Observability"


async def test_get_workspace_returns_404_for_unknown_workspace(client):
    resp = await client.get(f"/v1/workspaces/{uuid4()}")
    assert resp.status_code == 404


async def test_delete_workspace_removes_workspace_and_threads(client, actor_payload):
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Disposable", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]
    await client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        json={"title": "Temporary", "actor": actor_payload},
    )

    delete_resp = await client.request(
        "DELETE",
        f"/v1/workspaces/{workspace_id}",
        json={"actor": actor_payload},
    )

    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    get_resp = await client.get(f"/v1/workspaces/{workspace_id}")
    assert get_resp.status_code == 404
