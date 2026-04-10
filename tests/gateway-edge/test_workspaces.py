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


async def test_delete_participant_removes_them_from_workspace_listing(client, actor_payload):
    second_actor = {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Marta",
    }
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Participant Removal", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]
    await client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        json={"title": "General", "actor": second_actor},
    )

    delete_resp = await client.request(
        "DELETE",
        f"/v1/workspaces/{workspace_id}/participants/{second_actor['participant_id']}",
        json={"actor": actor_payload},
    )

    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    participants_resp = await client.get(f"/v1/workspaces/{workspace_id}/participants")
    assert participants_resp.status_code == 200
    participant_ids = {
        participant["participant_id"] for participant in participants_resp.json()
    }
    assert second_actor["participant_id"] not in participant_ids


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


async def test_create_agent_participant_advertises_capabilities_and_llm_config(client, actor_payload):
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Agent Directory", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    create_resp = await client.post(
        "/v1/agents",
        json={
            "actor": actor_payload,
            "display_name": "Research Analyst",
            "description": "Investigates product questions and synthesizes findings.",
            "role": "research analyst",
            "capabilities": ["research", "synthesis", "briefs"],
            "endpoint": {
                "kind": "remote",
                "url": "https://api.example.com/v1/responses",
                "model": "gpt-5.4",
            },
            "system_prompt": "You are a research-focused agent who produces concise evidence-backed summaries.",
            "definition": {
                "instructions": "Produce concise evidence-backed summaries.",
                "specialty": "research",
            },
        },
    )
    agent_id = create_resp.json()["agent_id"]

    attach_resp = await client.post(
        f"/v1/workspaces/{workspace_id}/agents",
        json={"actor": actor_payload, "agent_id": agent_id},
    )

    assert create_resp.status_code == 200
    assert attach_resp.status_code == 200
    create_body = create_resp.json()
    assert create_body["interaction_contract"]["response_contract"]["required_sections"]
    body = attach_resp.json()
    assert body["participant_type"] == "agent"
    assert body["system_agent_id"] == agent_id
    assert body["roles"] == ["research analyst"]
    assert body["capabilities"] == ["research", "synthesis", "briefs"]
    assert body["agent_config"]["endpoint"]["kind"] == "remote"
    assert body["agent_config"]["endpoint"]["url"] == "https://api.example.com/v1/responses"
    assert body["agent_config"]["endpoint"]["model"] == "gpt-5.4"
    assert body["agent_config"]["system_prompt"].startswith("You are a research-focused agent")
    assert body["agent_config"]["definition"]["specialty"] == "research"

    workspace_detail = await client.get(f"/v1/workspaces/{workspace_id}")
    assert workspace_detail.status_code == 200
    agents = [
        participant
        for participant in workspace_detail.json()["participants"]
        if participant["participant_type"] == "agent"
    ]
    assert len(agents) == 1
    assert agents[0]["display_name"] == "Research Analyst"
    assert agents[0]["agent_config"]["endpoint"]["kind"] == "remote"


async def test_update_agent_participant_changes_endpoint_prompt_and_role(client, actor_payload):
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Agent Updates", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    create_resp = await client.post(
        "/v1/agents",
        json={
            "actor": actor_payload,
            "display_name": "Local Builder",
            "description": "Builds patches against the local codebase.",
            "role": "implementation agent",
            "capabilities": ["coding", "debugging"],
            "endpoint": {
                "kind": "local",
                "url": "http://127.0.0.1:11434/api/generate",
                "model": "qwen-coder",
            },
            "system_prompt": "You write careful, testable code changes.",
            "definition": {
                "runtime": "ollama",
                "temperature": 0.1,
            },
        },
    )
    agent_id = create_resp.json()["agent_id"]

    attach_resp = await client.post(
        f"/v1/workspaces/{workspace_id}/agents",
        json={"actor": actor_payload, "agent_id": agent_id},
    )
    participant_id = attach_resp.json()["participant_id"]

    update_resp = await client.patch(
        f"/v1/agents/{agent_id}",
        json={
            "actor": actor_payload,
            "description": "Builds patches and verifies them with focused tests.",
            "role": "senior implementation agent",
            "capabilities": ["coding", "debugging", "testing"],
            "endpoint": {
                "kind": "remote",
                "url": "https://api.example.com/v1/responses",
                "model": "gpt-5.4-mini",
            },
            "system_prompt": "You implement changes, run targeted validation, and report residual risk.",
            "definition": {
                "runtime": "responses-api",
                "max_output_tokens": 4000,
            },
        },
    )

    attach_update_resp = await client.patch(
        f"/v1/workspaces/{workspace_id}/agents/{participant_id}",
        json={"actor": actor_payload, "status": "busy"},
    )

    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["role"] == "senior implementation agent"
    assert body["capabilities"] == ["coding", "debugging", "testing"]
    assert body["endpoint"]["kind"] == "remote"
    assert body["endpoint"]["model"] == "gpt-5.4-mini"
    assert body["system_prompt"].startswith("You implement changes")
    assert body["interaction_contract"]["response_contract"]["required_sections"]
    assert body["definition"]["runtime"] == "responses-api"
    assert attach_update_resp.status_code == 200
    assert attach_update_resp.json()["status"] == "busy"


async def test_create_system_agent_participant_uses_system_scope(client, actor_payload):
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "System Agents", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    create_resp = await client.post(
        "/v1/agents",
        json={
            "actor": actor_payload,
            "display_name": "Ops Agent",
            "description": "Handles system-wide operational tasks.",
            "role": "operations agent",
            "capabilities": ["deployments", "observability"],
            "endpoint": {
                "kind": "system",
                "model": "ops-router",
            },
            "system_prompt": "You coordinate system-wide operational workflows safely.",
            "definition": {
                "routing_group": "ops",
                "approval_policy": "manual",
            },
        },
    )

    assert create_resp.status_code == 200
    body = create_resp.json()
    assert body["endpoint"]["kind"] == "system"
    assert body["endpoint"]["url"] is None
    assert body["interaction_contract"]["response_contract"]["required_sections"]
    assert body["definition"]["routing_group"] == "ops"


async def test_agents_can_access_workspace_participant_advertisements(client, actor_payload):
    second_actor = {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Marta",
    }
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Shared Directory", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    await client.patch(
        f"/v1/workspaces/{workspace_id}/participants/{actor_payload['participant_id']}/role",
        json={
            "actor": actor_payload,
            "role": "product strategist",
            "description": "Turns product goals into execution plans.",
            "capabilities": ["planning", "prioritization"],
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
    create_agent_resp = await client.post(
        "/v1/agents",
        json={
            "actor": actor_payload,
            "display_name": "Planner Agent",
            "description": "Helps route work to the right people.",
            "role": "coordination agent",
            "capabilities": ["routing", "triage"],
            "endpoint": {
                "kind": "remote",
                "url": "https://api.example.com/v1/responses",
                "model": "gpt-5.4-mini",
            },
            "system_prompt": "You analyze workspace participants and route requests to the best fit.",
            "definition": {
                "routing_strategy": "best-fit",
            },
        },
    )
    assert create_agent_resp.status_code == 200
    agent_id = create_agent_resp.json()["agent_id"]
    agent_resp = await client.post(
        f"/v1/workspaces/{workspace_id}/agents",
        json={"actor": actor_payload, "agent_id": agent_id},
    )
    assert agent_resp.status_code == 200

    directory_resp = await client.get(f"/v1/workspaces/{workspace_id}/participants")
    assert directory_resp.status_code == 200
    participants = {
        participant["display_name"]: participant
        for participant in directory_resp.json()
    }
    assert participants["Nikolay"]["roles"] == ["product strategist"]
    assert participants["Nikolay"]["capabilities"] == ["planning", "prioritization"]
    assert participants["Marta"]["roles"] == ["ml engineer"]
    assert participants["Marta"]["description"] == "Builds and evaluates agent behavior."
    assert participants["Planner Agent"]["participant_type"] == "agent"
    assert participants["Planner Agent"]["agent_config"]["system_prompt"].startswith(
        "You analyze workspace participants"
    )


async def test_all_workspace_participants_can_access_participant_advertisements(client, actor_payload):
    second_actor = {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Marta",
    }
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Open Directory", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    await client.patch(
        f"/v1/workspaces/{workspace_id}/participants/{actor_payload['participant_id']}/role",
        json={
            "actor": actor_payload,
            "role": "product strategist",
            "description": "Turns product goals into execution plans.",
            "capabilities": ["planning", "prioritization"],
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

    directory_resp = await client.get(f"/v1/workspaces/{workspace_id}/participants")
    assert directory_resp.status_code == 200
    participants = {
        participant["display_name"]: participant
        for participant in directory_resp.json()
    }
    assert participants["Nikolay"]["roles"] == ["product strategist"]
    assert participants["Marta"]["roles"] == ["ml engineer"]
    assert participants["Marta"]["capabilities"] == ["evaluation", "prompting"]
