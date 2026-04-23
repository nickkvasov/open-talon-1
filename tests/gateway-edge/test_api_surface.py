from __future__ import annotations


DEFAULT_ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


def _agent_payload(actor_payload: dict[str, str], *, display_name: str) -> dict[str, object]:
    return {
        "actor": actor_payload,
        "display_name": display_name,
        "description": f"{display_name} description",
        "role": "operator",
        "capabilities": ["ops"],
        "endpoint": {"kind": "remote", "model": "gpt-5.4"},
        "system_prompt": f"{display_name} system prompt.",
    }


def _tool_payload(actor_payload: dict[str, str], *, name: str) -> dict[str, object]:
    return {
        "actor": actor_payload,
        "name": name,
        "description": f"{name} description",
        "parameter_contract": {"strategy": "strict"},
        "input_schema": {"type": "object"},
        "execution": {"strategy": "local"},
    }


def _llm_provider_payload(
    actor_payload: dict[str, str],
    *,
    engine_id: str,
) -> dict[str, object]:
    return {
        "actor": actor_payload,
        "engine_id": engine_id,
        "display_name": f"{engine_id} display",
        "description": f"{engine_id} description",
        "provider": "openai",
        "endpoint_kind": "remote",
        "url": "https://api.openai.example/v1/responses",
        "default_model": "gpt-5.4",
        "capabilities": ["chat", "reasoning"],
        "locality": "cloud",
        "priority": 100,
        "enabled": True,
        "secret_config": {"env": {"name": "OPENAI_API_KEY"}},
        "metadata": {"surface": "test"},
    }


def _memory_provider_payload(
    actor_payload: dict[str, str],
    *,
    provider_key: str,
) -> dict[str, object]:
    return {
        "actor": actor_payload,
        "provider_key": provider_key,
        "display_name": f"{provider_key} display",
        "description": f"{provider_key} description",
        "provider": "mem0",
        "enabled": True,
        "config": {
            "enable_graph": False,
            "vector_store": {
                "provider": "pgvector",
                "config": {"collection_name": f"{provider_key}_collection"},
            },
        },
        "secret_config": {"env": {"name": "OPENAI_API_KEY"}},
        "metadata": {"surface": "test"},
    }


async def test_organization_slug_routes_normalize_and_validate(client, actor_payload):
    create_resp = await client.post(
        "/v1/organizations",
        json={
            "actor": actor_payload,
            "slug": "Acme Ops!!!",
            "name": "Acme Operations",
            "description": "First organization",
        },
    )

    assert create_resp.status_code == 200
    organization_id = create_resp.json()["organization_id"]
    assert create_resp.json()["slug"] == "acme-ops"

    by_slug_resp = await client.get("/v1/organizations/by-slug/ACME-OPS")
    assert by_slug_resp.status_code == 200
    assert by_slug_resp.json()["organization_id"] == organization_id

    update_resp = await client.patch(
        f"/v1/organizations/{organization_id}",
        json={
            "actor": actor_payload,
            "slug": " Ops Team 2026 ",
            "metadata": {"region": "emea"},
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["slug"] == "ops-team-2026"
    assert update_resp.json()["metadata"]["region"] == "emea"

    duplicate_resp = await client.post(
        "/v1/organizations",
        json={
            "actor": actor_payload,
            "slug": "OPS TEAM 2026",
            "name": "Duplicate Organization",
        },
    )
    assert duplicate_resp.status_code == 400
    assert "already exists" in duplicate_resp.json()["detail"]

    invalid_resp = await client.post(
        "/v1/organizations",
        json={
            "actor": actor_payload,
            "slug": "!!!",
            "name": "Invalid Organization",
        },
    )
    assert invalid_resp.status_code == 422


async def test_global_definition_detail_routes_return_created_resources(client, actor_payload):
    agent_resp = await client.post(
        "/v1/agents",
        json=_agent_payload(actor_payload, display_name="Global Operator"),
    )
    tool_resp = await client.post(
        "/v1/tools",
        json=_tool_payload(actor_payload, name="global_tool"),
    )
    llm_resp = await client.post(
        "/v1/llm-providers",
        json=_llm_provider_payload(actor_payload, engine_id="global-openai"),
    )
    memory_resp = await client.post(
        "/v1/memory-providers",
        json=_memory_provider_payload(actor_payload, provider_key="global-mem0"),
    )

    assert agent_resp.status_code == 200
    assert tool_resp.status_code == 200
    assert llm_resp.status_code == 200
    assert memory_resp.status_code == 200

    agent_id = agent_resp.json()["agent_id"]
    tool_id = tool_resp.json()["tool_id"]
    llm_provider_id = llm_resp.json()["provider_id"]
    memory_provider_id = memory_resp.json()["provider_id"]

    assert (await client.get(f"/v1/agents/{agent_id}")).json()["display_name"] == "Global Operator"
    assert (await client.get(f"/v1/tools/{tool_id}")).json()["name"] == "global_tool"
    assert (await client.get(f"/v1/llm-providers/{llm_provider_id}")).json()["engine_id"] == "global-openai"
    assert (
        await client.get(f"/v1/memory-providers/{memory_provider_id}")
    ).json()["provider_key"] == "global-mem0"


async def test_organization_scoped_agent_and_tool_alias_routes(client, actor_payload):
    agent_resp = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/agents",
        json=_agent_payload(actor_payload, display_name="Org Operator"),
    )
    tool_resp = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/tools",
        json=_tool_payload(actor_payload, name="org_tool"),
    )

    assert agent_resp.status_code == 200
    assert tool_resp.status_code == 200

    agent_id = agent_resp.json()["agent_id"]
    tool_id = tool_resp.json()["tool_id"]

    assert (
        await client.get(f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/agents/{agent_id}")
    ).json()["agent_id"] == agent_id
    assert (
        await client.get(f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/tools/{tool_id}")
    ).json()["tool_id"] == tool_id

    agent_update = await client.patch(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/agents/{agent_id}",
        json={"actor": actor_payload, "display_name": "Org Operator Updated"},
    )
    tool_update = await client.patch(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/tools/{tool_id}",
        json={"actor": actor_payload, "description": "Updated tool description"},
    )

    assert agent_update.status_code == 200
    assert agent_update.json()["display_name"] == "Org Operator Updated"
    assert tool_update.status_code == 200
    assert tool_update.json()["description"] == "Updated tool description"

    agent_delete = await client.request(
        "DELETE",
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/agents/{agent_id}",
        json={"actor": actor_payload},
    )
    tool_delete = await client.request(
        "DELETE",
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/tools/{tool_id}",
        json={"actor": actor_payload},
    )

    assert agent_delete.status_code == 200
    assert agent_delete.json()["deleted"] is True
    assert tool_delete.status_code == 200
    assert tool_delete.json()["deleted"] is True


async def test_organization_scoped_provider_alias_routes(client, actor_payload):
    llm_resp = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/llm-providers",
        json=_llm_provider_payload(actor_payload, engine_id="org-openai"),
    )
    memory_resp = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/memory-providers",
        json=_memory_provider_payload(actor_payload, provider_key="org-mem0"),
    )

    assert llm_resp.status_code == 200
    assert memory_resp.status_code == 200

    llm_provider_id = llm_resp.json()["provider_id"]
    memory_provider_id = memory_resp.json()["provider_id"]

    assert (
        await client.get(
            f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/llm-providers/{llm_provider_id}"
        )
    ).json()["provider_id"] == llm_provider_id
    assert (
        await client.get(
            f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/memory-providers/{memory_provider_id}"
        )
    ).json()["provider_id"] == memory_provider_id

    llm_update = await client.patch(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/llm-providers/{llm_provider_id}",
        json={"actor": actor_payload, "display_name": "Org OpenAI Updated"},
    )
    memory_update = await client.patch(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/memory-providers/{memory_provider_id}",
        json={"actor": actor_payload, "display_name": "Org Mem0 Updated"},
    )

    assert llm_update.status_code == 200
    assert llm_update.json()["display_name"] == "Org OpenAI Updated"
    assert memory_update.status_code == 200
    assert memory_update.json()["display_name"] == "Org Mem0 Updated"

    llm_health = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/llm-providers/{llm_provider_id}/health-check"
    )
    memory_health = await client.post(
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/memory-providers/{memory_provider_id}/health-check"
    )

    assert llm_health.status_code == 200
    assert memory_health.status_code == 200

    llm_delete = await client.request(
        "DELETE",
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/llm-providers/{llm_provider_id}",
        json={"actor": actor_payload},
    )
    memory_delete = await client.request(
        "DELETE",
        f"/v1/organizations/{DEFAULT_ORGANIZATION_ID}/memory-providers/{memory_provider_id}",
        json={"actor": actor_payload},
    )

    assert llm_delete.status_code == 200
    assert llm_delete.json()["deleted"] is True
    assert memory_delete.status_code == 200
    assert memory_delete.json()["deleted"] is True
