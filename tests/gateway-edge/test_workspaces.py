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


async def test_assume_role_updates_workspace_participant_profile(client, actor_payload):
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Role Directory", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    role_resp = await client.patch(
        f"/v1/workspaces/{workspace_id}/participants/{actor_payload['participant_id']}/role",
        json={
            "actor": actor_payload,
            "role": "backend architect",
            "description": "Designs collaboration kernels and event-driven service boundaries.",
            "capabilities": ["system design", "postgres", "kafka"],
        },
    )

    assert role_resp.status_code == 200
    body = role_resp.json()
    assert body["roles"] == ["backend architect"]
    assert body["capabilities"] == ["system design", "postgres", "kafka"]
    assert body["description"] == "Designs collaboration kernels and event-driven service boundaries."

    workspace_detail = await client.get(f"/v1/workspaces/{workspace_id}")
    assert workspace_detail.status_code == 200
    participant = workspace_detail.json()["participants"][0]
    assert participant["roles"] == ["backend architect"]
    assert participant["capabilities"] == ["system design", "postgres", "kafka"]


async def test_workspace_participants_can_see_each_others_roles(client, actor_payload):
    second_actor = {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Marta",
    }
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Shared Roles", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]
    await client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        json={"title": "General", "actor": second_actor},
    )

    await client.patch(
        f"/v1/workspaces/{workspace_id}/participants/{actor_payload['participant_id']}/role",
        json={
            "actor": actor_payload,
            "role": "product strategist",
            "description": "Translates product questions into execution plans.",
            "capabilities": ["roadmapping", "prioritization"],
        },
    )
    await client.patch(
        f"/v1/workspaces/{workspace_id}/participants/{second_actor['participant_id']}/role",
        json={
            "actor": second_actor,
            "role": "ml engineer",
            "description": "Builds and evaluates agent behavior.",
            "capabilities": ["evaluation", "prompting"],
        },
    )

    workspace_detail = await client.get(f"/v1/workspaces/{workspace_id}")
    assert workspace_detail.status_code == 200
    participants = {
        participant["participant_id"]: participant
        for participant in workspace_detail.json()["participants"]
    }
    assert participants[actor_payload["participant_id"]]["roles"] == ["product strategist"]
    assert participants[second_actor["participant_id"]]["roles"] == ["ml engineer"]


async def test_create_or_update_named_role_definition_in_workspace(client, actor_payload):
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Role Catalog", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    create_resp = await client.put(
        f"/v1/workspaces/{workspace_id}/roles/reviewer",
        json={
            "actor": actor_payload,
            "name": "ignored-by-path",
            "definition": "Reviews design docs, code changes, and test coverage.",
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["name"] == "reviewer"
    assert create_resp.json()["definition"] == "Reviews design docs, code changes, and test coverage."

    update_resp = await client.put(
        f"/v1/workspaces/{workspace_id}/roles/reviewer",
        json={
            "actor": actor_payload,
            "name": "still-ignored",
            "definition": "Reviews code, architecture, and rollout risk with a QA mindset.",
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "reviewer"
    assert update_resp.json()["definition"] == "Reviews code, architecture, and rollout risk with a QA mindset."

    workspace_detail = await client.get(f"/v1/workspaces/{workspace_id}")
    assert workspace_detail.status_code == 200
    roles = {
        role["name"]: role
        for role in workspace_detail.json()["role_definitions"]
    }
    assert roles["reviewer"]["definition"] == "Reviews code, architecture, and rollout risk with a QA mindset."


async def test_assume_precreated_role_uses_workspace_role_definition(client, actor_payload):
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Role Reuse", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    await client.put(
        f"/v1/workspaces/{workspace_id}/roles/reviewer",
        json={
            "actor": actor_payload,
            "name": "ignored",
            "definition": "Reviews code and risk before changes go live.",
        },
    )

    assume_resp = await client.patch(
        f"/v1/workspaces/{workspace_id}/participants/{actor_payload['participant_id']}/role",
        json={
            "actor": actor_payload,
            "role": "reviewer",
            "capabilities": ["regressions", "qa"],
        },
    )

    assert assume_resp.status_code == 200
    body = assume_resp.json()
    assert body["roles"] == ["reviewer"]
    assert body["description"] == "Reviews code and risk before changes go live."
    assert body["capabilities"] == ["regressions", "qa"]
