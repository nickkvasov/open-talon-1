from __future__ import annotations

import httpx
from uuid import uuid4

from gateway_edge.config import settings
from gateway_edge.models import AuthContext


def _oidc_context(*, roles: list[str]) -> AuthContext:
    return AuthContext(
        kind="oidc",
        user_id=uuid4(),
        issuer="http://issuer.test/realms/open-talon",
        subject="subject-123",
        email="nikolay@example.com",
        display_name="Nikolay",
        roles=roles,
        claims={"sub": "subject-123"},
    )


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


async def test_list_llm_engines_returns_registered_engines(client, actor_payload):
    await client.post(
        "/v1/llm-providers",
        json={
            "actor": actor_payload,
            "engine_id": "local-ollama",
            "display_name": "Local Ollama",
            "description": "Host-local Ollama generation endpoint.",
            "provider": "ollama",
            "endpoint_kind": "local",
            "url": "http://127.0.0.1:11434/api/generate",
            "default_model": "qwen3:latest",
            "capabilities": ["chat", "completion", "local", "host", "ollama"],
            "locality": "host",
            "priority": 100,
        },
    )
    await client.post(
        "/v1/llm-providers",
        json={
            "actor": actor_payload,
            "engine_id": "openai-responses",
            "display_name": "OpenAI Responses",
            "description": "Primary cloud engine for reasoning-heavy work.",
            "provider": "openai",
            "endpoint_kind": "remote",
            "url": "https://api.example.com/v1/responses",
            "default_model": "gpt-5.4",
            "capabilities": ["chat", "tool_calling", "reasoning"],
            "locality": "cloud",
            "priority": 250,
            "secret_config": {
                "openbao": {
                    "mount": "secret",
                    "path": "open-talon/llm/openai",
                    "field": "api_key",
                }
            },
        },
    )

    resp = await client.get("/v1/llm-engines")

    assert resp.status_code == 200
    engines = {engine["engine_id"]: engine for engine in resp.json()}
    assert engines["openai-responses"]["description"] == "Primary cloud engine for reasoning-heavy work."
    assert engines["openai-responses"]["capabilities"] == ["chat", "tool_calling", "reasoning"]
    assert engines["openai-responses"]["provider"] == "openai"
    assert engines["local-ollama"]["default_model"] == "qwen3:latest"
    assert "ollama" in engines["local-ollama"]["capabilities"]
    assert engines["openai-responses"]["metadata"]["secret_config"]["openbao"]["path"] == "open-talon/llm/openai"


async def test_git_repositories_and_asset_publish_flow_support_global_agent_bindings(client, actor_payload):
    create_agent = await client.post(
        "/v1/agents",
        json={
            "actor": actor_payload,
            "display_name": "Admin Agent",
            "description": "Coordinates subsidiary agents.",
            "role": "system admin",
            "capabilities": ["coding", "orchestration"],
            "endpoint": {"kind": "remote", "model": "gpt-5.4"},
            "system_prompt": "Manage agents and their published definitions safely.",
        },
    )
    assert create_agent.status_code == 200
    agent_id = create_agent.json()["agent_id"]

    create_repo = await client.post(
        "/v1/git-repositories",
        json={
            "actor": actor_payload,
            "name": "agent-definitions",
            "local_path": "/tmp/agent-definitions",
            "forgejo_url": "http://localhost:3001/open-talon/agent-definitions",
            "clone_url": "ssh://git@localhost:2222/open-talon/agent-definitions.git",
        },
    )
    assert create_repo.status_code == 200
    repository_id = create_repo.json()["repo_id"]

    publish = await client.post(
        "/v1/assets/publish-from-git",
        json={
            "actor": actor_payload,
            "repository_id": repository_id,
            "asset_type": "agent_instruction",
            "logical_name": "admin-agent-md",
            "title": "Admin Agent Instructions",
            "git_path": "agents/admin/AGENT.md",
            "revision": "HEAD",
            "content_type": "text/markdown",
        },
    )
    assert publish.status_code == 200
    version = publish.json()

    assets = await client.get("/v1/assets")
    assert assets.status_code == 200
    asset = next(item for item in assets.json() if item["logical_name"] == "admin-agent-md")

    activate = await client.post(
        f"/v1/assets/{asset['asset_id']}/activate",
        json={
            "actor": actor_payload,
            "asset_version_id": version["asset_version_id"],
            "target_type": "system_agent",
            "target_id": agent_id,
            "purpose": "agent_md",
        },
    )
    assert activate.status_code == 200

    resolved = await client.get(f"/v1/agents/{agent_id}/assets")
    assert resolved.status_code == 200
    assert resolved.json()[0]["purpose"] == "agent_md"
    assert resolved.json()[0]["version"]["asset_version_id"] == version["asset_version_id"]


async def test_workspace_git_repository_publish_and_versions_are_listed(client, actor_payload):
    workspace = await client.post(
        "/v1/workspaces",
        json={"name": "Workspace Assets", "actor": actor_payload},
    )
    assert workspace.status_code == 200
    workspace_id = workspace.json()["workspace"]["workspace_id"]

    repo = await client.post(
        f"/v1/workspaces/{workspace_id}/git-repositories",
        json={
            "actor": actor_payload,
            "name": "workspace-playbooks",
            "local_path": "/tmp/workspace-playbooks",
            "forgejo_url": "http://localhost:3001/workspace/playbooks",
        },
    )
    assert repo.status_code == 200
    repository_id = repo.json()["repo_id"]

    first = await client.post(
        f"/v1/workspaces/{workspace_id}/assets/publish-from-git",
        json={
            "actor": actor_payload,
            "repository_id": repository_id,
            "asset_type": "agent_instruction",
            "logical_name": "workspace-agent-md",
            "title": "Workspace Agent Instructions",
            "git_path": "agents/research/AGENT.md",
        },
    )
    assert first.status_code == 200

    second = await client.post(
        f"/v1/workspaces/{workspace_id}/assets/publish-from-git",
        json={
            "actor": actor_payload,
            "repository_id": repository_id,
            "asset_type": "agent_instruction",
            "logical_name": "workspace-agent-md",
            "title": "Workspace Agent Instructions",
            "git_path": "agents/research/AGENT.md",
            "revision": "HEAD~1",
        },
    )
    assert second.status_code == 200

    assets = await client.get(f"/v1/assets?workspace_id={workspace_id}")
    assert assets.status_code == 200
    asset = next(item for item in assets.json() if item["logical_name"] == "workspace-agent-md")

    versions = await client.get(f"/v1/assets/{asset['asset_id']}/versions")
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()] == [1, 2]


async def test_llm_providers_can_be_created_listed_updated_and_deleted(client, actor_payload):
    create_resp = await client.post(
        "/v1/llm-providers",
        json={
            "actor": actor_payload,
            "engine_id": "anthropic-claude-sonnet",
            "display_name": "Anthropic Claude Sonnet",
            "description": "Cloud Claude endpoint for long-form reasoning.",
            "provider": "anthropic",
            "endpoint_kind": "remote",
            "url": "https://api.anthropic.example/v1/messages",
            "default_model": "claude-sonnet-4-5",
            "capabilities": ["chat", "reasoning"],
            "locality": "cloud",
            "priority": 180,
            "enabled": True,
            "secret_config": {
                "env": {"name": "ANTHROPIC_API_KEY"},
                "openbao": {
                    "mount": "secret",
                    "path": "open-talon/llm/anthropic",
                    "field": "api_key",
                },
            },
            "metadata": {"protocol": "anthropic-messages"},
        },
    )

    assert create_resp.status_code == 200
    provider_id = create_resp.json()["provider_id"]
    assert create_resp.json()["engine_id"] == "anthropic-claude-sonnet"

    list_resp = await client.get("/v1/llm-providers")
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["secret_config"]["openbao"]["path"] == "open-talon/llm/anthropic"

    update_resp = await client.patch(
        f"/v1/llm-providers/{provider_id}",
        json={
            "actor": actor_payload,
            "display_name": "Anthropic Claude Sonnet Updated",
            "priority": 220,
            "enabled": False,
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["display_name"] == "Anthropic Claude Sonnet Updated"
    assert update_resp.json()["priority"] == 220
    assert update_resp.json()["enabled"] is False

    delete_resp = await client.request(
        "DELETE",
        f"/v1/llm-providers/{provider_id}",
        json={"actor": actor_payload},
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True


async def test_memory_providers_can_be_created_listed_updated_and_deleted(client, actor_payload):
    create_resp = await client.post(
        "/v1/memory-providers",
        json={
            "actor": actor_payload,
            "provider_key": "mem0-primary",
            "display_name": "Mem0 Primary",
            "description": "Graph-aware semantic memory provider.",
            "provider": "mem0",
            "enabled": True,
            "config": {
                "enable_graph": True,
                "vector_store": {"provider": "pgvector", "config": {"collection_name": "workspace_memories"}},
                "graph_store": {"provider": "memgraph", "config": {"url": "bolt://memgraph:7687"}},
            },
            "secret_config": {"env": {"name": "OPENAI_API_KEY"}},
            "metadata": {"tier": "primary"},
        },
    )

    assert create_resp.status_code == 200
    provider_id = create_resp.json()["provider_id"]
    assert create_resp.json()["config"]["graph_store"]["provider"] == "memgraph"

    list_resp = await client.get("/v1/memory-providers")
    assert list_resp.status_code == 200
    assert list_resp.json()[0]["provider_key"] == "mem0-primary"

    update_resp = await client.patch(
        f"/v1/memory-providers/{provider_id}",
        json={
            "actor": actor_payload,
            "display_name": "Mem0 Primary Updated",
            "enabled": False,
            "config": {
                "enable_graph": False,
                "vector_store": {"provider": "pgvector", "config": {"collection_name": "workspace_memories_v2"}},
            },
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["display_name"] == "Mem0 Primary Updated"
    assert update_resp.json()["enabled"] is False
    assert update_resp.json()["config"]["enable_graph"] is False

    delete_resp = await client.request(
        "DELETE",
        f"/v1/memory-providers/{provider_id}",
        json={"actor": actor_payload},
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True


async def test_validate_memory_provider_graph_mode_returns_health_without_persisting(
    client,
    actor_payload,
    monkeypatch,
):
    async def fake_check(provider):
        from gateway_edge.models import MemoryProviderHealthCheck, MemoryProviderHealthReport

        assert provider.provider == "mem0"
        assert provider.config["enable_graph"] is True
        assert provider.config["graph_store"]["provider"] == "memgraph"
        return MemoryProviderHealthReport(
            provider_id=provider.provider_id,
            provider_key=provider.provider_key,
            status="healthy",
            checks=[
                MemoryProviderHealthCheck(
                    name="graph_store",
                    status="ok",
                    detail="Graph memory enabled with backend memgraph.",
                    metadata={"provider": "memgraph"},
                )
            ],
            metadata={
                "provider": provider.provider,
                "graph_enabled": True,
                "vector_store_provider": "pgvector",
                "graph_store_provider": "memgraph",
            },
        )

    monkeypatch.setattr("gateway_edge.routers.collaboration.check_memory_provider_health", fake_check)

    validate_resp = await client.post(
        "/v1/memory-providers/validate",
        json={
            "actor": actor_payload,
            "provider_key": "mem0-graph",
            "display_name": "Mem0 Graph",
            "description": "Dry-run graph provider validation.",
            "provider": "mem0",
            "enabled": True,
            "config": {
                "enable_graph": True,
                "vector_store": {"provider": "pgvector", "config": {}},
                "graph_store": {"provider": "memgraph", "config": {"url": "bolt://memgraph:7687"}},
            },
        },
    )
    list_resp = await client.get("/v1/memory-providers")

    assert validate_resp.status_code == 200
    body = validate_resp.json()
    assert body["status"] == "healthy"
    assert body["metadata"]["graph_enabled"] is True
    assert body["metadata"]["graph_store_provider"] == "memgraph"
    assert body["checks"][0]["name"] == "graph_store"
    assert list_resp.status_code == 200
    assert list_resp.json() == []


async def test_memory_provider_health_check_reports_memgraph_backend(
    client,
    actor_payload,
    monkeypatch,
):
    create_resp = await client.post(
        "/v1/memory-providers",
        json={
            "actor": actor_payload,
            "provider_key": "mem0-graph",
            "display_name": "Mem0 Graph",
            "description": "Stored graph-aware memory provider.",
            "provider": "mem0",
            "enabled": True,
            "config": {
                "enable_graph": True,
                "vector_store": {"provider": "pgvector", "config": {}},
                "graph_store": {"provider": "memgraph", "config": {"url": "bolt://memgraph:7687"}},
            },
        },
    )
    assert create_resp.status_code == 200
    provider_id = create_resp.json()["provider_id"]

    async def fake_check(provider):
        from gateway_edge.models import MemoryProviderHealthCheck, MemoryProviderHealthReport

        return MemoryProviderHealthReport(
            provider_id=provider.provider_id,
            provider_key=provider.provider_key,
            status="healthy",
            checks=[
                MemoryProviderHealthCheck(
                    name="vector_store",
                    status="ok",
                    detail="Vector store configured as pgvector.",
                    metadata={"provider": "pgvector"},
                ),
                MemoryProviderHealthCheck(
                    name="graph_store",
                    status="ok",
                    detail="Graph memory enabled with backend memgraph.",
                    metadata={"provider": "memgraph"},
                ),
            ],
            metadata={
                "provider": provider.provider,
                "graph_enabled": True,
                "vector_store_provider": "pgvector",
                "graph_store_provider": "memgraph",
            },
        )

    monkeypatch.setattr("gateway_edge.routers.collaboration.check_memory_provider_health", fake_check)

    health_resp = await client.post(f"/v1/memory-providers/{provider_id}/health-check")

    assert health_resp.status_code == 200
    body = health_resp.json()
    assert body["status"] == "healthy"
    checks = {check["name"]: check for check in body["checks"]}
    assert checks["vector_store"]["status"] == "ok"
    assert checks["graph_store"]["status"] == "ok"
    assert checks["graph_store"]["metadata"]["provider"] == "memgraph"
    assert body["metadata"]["graph_enabled"] is True
    assert body["metadata"]["graph_store_provider"] == "memgraph"


async def test_memory_provider_management_requires_admin_role_in_oidc_mode(
    client,
    actor_payload,
    monkeypatch,
):
    auth_context = _oidc_context(roles=["workspace-user"])
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    create_resp = await client.post(
        "/v1/memory-providers",
        headers={"Authorization": "Bearer good-token"},
        json={
            "actor": actor_payload,
            "provider_key": "guarded-mem0",
            "display_name": "Guarded Mem0",
            "description": "Should require admin access.",
            "provider": "mem0",
            "config": {"enable_graph": False},
        },
    )
    list_resp = await client.get(
        "/v1/memory-providers",
        headers={"Authorization": "Bearer good-token"},
    )

    assert create_resp.status_code == 403
    assert create_resp.json()["detail"] == "Admin access required"
    assert list_resp.status_code == 403
    assert list_resp.json()["detail"] == "Admin access required"


async def test_validate_memory_provider_requires_admin_role_in_oidc_mode(
    client,
    actor_payload,
    monkeypatch,
):
    auth_context = _oidc_context(roles=["workspace-user"])
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    response = await client.post(
        "/v1/memory-providers/validate",
        headers={"Authorization": "Bearer good-token"},
        json={
            "actor": actor_payload,
            "provider_key": "dry-run-mem0",
            "display_name": "Dry Run Mem0",
            "description": "Dry-run provider validation.",
            "provider": "mem0",
            "config": {"enable_graph": True},
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


async def test_memory_provider_health_check_requires_admin_role_in_oidc_mode(
    client,
    actor_payload,
    monkeypatch,
):
    create_resp = await client.post(
        "/v1/memory-providers",
        json={
            "actor": actor_payload,
            "provider_key": "stored-mem0",
            "display_name": "Stored Mem0",
            "description": "Stored provider for auth check.",
            "provider": "mem0",
            "config": {"enable_graph": False},
        },
    )
    assert create_resp.status_code == 200
    provider_id = create_resp.json()["provider_id"]

    auth_context = _oidc_context(roles=["workspace-user"])
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    response = await client.post(
        f"/v1/memory-providers/{provider_id}/health-check",
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


async def test_llm_provider_management_requires_admin_role_in_oidc_mode(client, actor_payload, monkeypatch):
    auth_context = _oidc_context(roles=["workspace-user"])
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    create_resp = await client.post(
        "/v1/llm-providers",
        headers={"Authorization": "Bearer good-token"},
        json={
            "actor": actor_payload,
            "engine_id": "guarded-openai",
            "display_name": "Guarded OpenAI",
            "description": "Should require admin access.",
            "provider": "openai",
            "endpoint_kind": "remote",
        },
    )
    list_resp = await client.get(
        "/v1/llm-providers",
        headers={"Authorization": "Bearer good-token"},
    )

    assert create_resp.status_code == 403
    assert create_resp.json()["detail"] == "Admin access required"
    assert list_resp.status_code == 403
    assert list_resp.json()["detail"] == "Admin access required"


async def test_llm_provider_management_allows_admin_role_in_oidc_mode(client, actor_payload, monkeypatch):
    auth_context = _oidc_context(roles=["open-talon-admin"])
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    create_resp = await client.post(
        "/v1/llm-providers",
        headers={"Authorization": "Bearer good-token"},
        json={
            "actor": actor_payload,
            "engine_id": "admin-openai",
            "display_name": "Admin OpenAI",
            "description": "Allowed for admins.",
            "provider": "openai",
            "endpoint_kind": "remote",
        },
    )
    list_resp = await client.get(
        "/v1/llm-providers",
        headers={"Authorization": "Bearer good-token"},
    )

    assert create_resp.status_code == 200
    assert create_resp.json()["engine_id"] == "admin-openai"
    assert list_resp.status_code == 200
    assert [item["engine_id"] for item in list_resp.json()] == ["admin-openai"]


async def test_llm_provider_update_can_clear_capabilities(client, actor_payload):
    create_resp = await client.post(
        "/v1/llm-providers",
        json={
            "actor": actor_payload,
            "engine_id": "groq-fast",
            "display_name": "Groq Fast",
            "description": "Low-latency cloud provider.",
            "provider": "groq",
            "endpoint_kind": "remote",
            "url": "https://api.groq.example/openai/v1/responses",
            "default_model": "llama-4-fast",
            "capabilities": ["chat", "fast"],
            "locality": "cloud",
            "priority": 90,
            "enabled": True,
        },
    )
    assert create_resp.status_code == 200
    provider_id = create_resp.json()["provider_id"]

    update_resp = await client.patch(
        f"/v1/llm-providers/{provider_id}",
        json={
            "actor": actor_payload,
            "capabilities": [],
        },
    )

    assert update_resp.status_code == 200
    assert update_resp.json()["capabilities"] == []

    list_resp = await client.get("/v1/llm-providers")
    assert list_resp.status_code == 200
    provider = next(item for item in list_resp.json() if item["provider_id"] == provider_id)
    assert provider["capabilities"] == []


async def test_referenced_llm_provider_cannot_be_disabled_renamed_or_deleted(client, actor_payload):
    create_provider_resp = await client.post(
        "/v1/llm-providers",
        json={
            "actor": actor_payload,
            "engine_id": "openai-responses",
            "display_name": "OpenAI Responses",
            "description": "Primary reasoning engine.",
            "provider": "openai",
            "endpoint_kind": "remote",
            "url": "https://api.openai.com/v1/responses",
            "default_model": "gpt-5.4-mini",
        },
    )
    provider_id = create_provider_resp.json()["provider_id"]

    create_agent_resp = await client.post(
        "/v1/agents",
        json={
            "actor": actor_payload,
            "display_name": "Reasoning Planner",
            "description": "Plans multi-step work with cloud reasoning.",
            "role": "planning agent",
            "capabilities": ["planning", "reasoning"],
            "endpoint": {
                "kind": "remote",
                "engine_id": "openai-responses",
                "provider": "openai",
            },
            "system_prompt": "You plan carefully and explain tradeoffs clearly.",
            "definition": {
                "runtime": {
                    "engine_id": "openai-responses",
                    "preferred_engine_ids": ["openai-responses"],
                }
            },
        },
    )

    assert create_agent_resp.status_code == 200

    disable_resp = await client.patch(
        f"/v1/llm-providers/{provider_id}",
        json={
            "actor": actor_payload,
            "enabled": False,
        },
    )
    rename_resp = await client.patch(
        f"/v1/llm-providers/{provider_id}",
        json={
            "actor": actor_payload,
            "engine_id": "openai-responses-v2",
        },
    )
    delete_resp = await client.request(
        "DELETE",
        f"/v1/llm-providers/{provider_id}",
        json={"actor": actor_payload},
    )

    assert disable_resp.status_code == 400
    assert "Cannot disable LLM provider" in disable_resp.json()["detail"]
    assert "Reasoning Planner" in disable_resp.json()["detail"]
    assert rename_resp.status_code == 400
    assert "Cannot rename LLM provider engine_id" in rename_resp.json()["detail"]
    assert delete_resp.status_code == 400
    assert "Cannot delete LLM provider" in delete_resp.json()["detail"]


async def test_llm_provider_health_check_reports_healthy_for_resolved_secret_and_reachable_endpoint(
    client,
    actor_payload,
    monkeypatch,
):
    create_resp = await client.post(
        "/v1/llm-providers",
        json={
            "actor": actor_payload,
            "engine_id": "health-openai",
            "display_name": "Health OpenAI",
            "description": "Provider used for health checks.",
            "provider": "openai",
            "endpoint_kind": "remote",
            "url": "https://api.openai.com/v1/responses",
            "secret_config": {"env": {"name": "OPENAI_API_KEY"}},
        },
    )
    provider_id = create_resp.json()["provider_id"]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, follow_redirects=False):
            assert url == "https://api.openai.com/v1/responses"
            assert headers == {"Authorization": "Bearer sk-test"}
            return httpx.Response(405, request=httpx.Request("GET", url))

    monkeypatch.setattr(
        "gateway_edge.services.llm_provider_health.httpx.AsyncClient",
        FakeAsyncClient,
    )

    health_resp = await client.post(f"/v1/llm-providers/{provider_id}/health-check")

    assert health_resp.status_code == 200
    body = health_resp.json()
    assert body["status"] == "healthy"
    checks = {check["name"]: check for check in body["checks"]}
    assert checks["secret"]["status"] == "ok"
    assert checks["url"]["status"] == "ok"
    assert checks["connectivity"]["status"] == "ok"
    assert checks["connectivity"]["metadata"]["status_code"] == 405


async def test_llm_provider_health_check_reports_unhealthy_for_missing_secret_and_invalid_url(
    client,
    actor_payload,
):
    create_resp = await client.post(
        "/v1/llm-providers",
        json={
            "actor": actor_payload,
            "engine_id": "broken-provider",
            "display_name": "Broken Provider",
            "description": "Provider with invalid config.",
            "provider": "openai",
            "endpoint_kind": "remote",
            "url": "not-a-url",
            "secret_config": {"env": {"name": "MISSING_OPENAI_API_KEY"}},
        },
    )
    provider_id = create_resp.json()["provider_id"]

    health_resp = await client.post(f"/v1/llm-providers/{provider_id}/health-check")

    assert health_resp.status_code == 200
    body = health_resp.json()
    assert body["status"] == "unhealthy"
    checks = {check["name"]: check for check in body["checks"]}
    assert checks["secret"]["status"] == "fail"
    assert checks["url"]["status"] == "fail"
    assert checks["connectivity"]["status"] in {"warn", "fail"}


async def test_validate_llm_provider_dry_run_returns_health_without_persisting(
    client,
    actor_payload,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-dry-run")

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers=None, follow_redirects=False):
            assert url == "https://api.openai.com/v1/responses"
            assert headers == {"Authorization": "Bearer sk-dry-run"}
            return httpx.Response(405, request=httpx.Request("GET", url))

    monkeypatch.setattr(
        "gateway_edge.services.llm_provider_health.httpx.AsyncClient",
        FakeAsyncClient,
    )

    validate_resp = await client.post(
        "/v1/llm-providers/validate",
        json={
            "actor": actor_payload,
            "engine_id": "dry-run-openai",
            "display_name": "Dry Run OpenAI",
            "description": "Dry-run provider validation.",
            "provider": "openai",
            "endpoint_kind": "remote",
            "url": "https://api.openai.com/v1/responses",
            "default_model": "gpt-5.4-mini",
            "secret_config": {"env": {"name": "OPENAI_API_KEY"}},
        },
    )
    list_resp = await client.get("/v1/llm-providers")

    assert validate_resp.status_code == 200
    body = validate_resp.json()
    assert body["engine_id"] == "dry-run-openai"
    assert body["status"] == "healthy"
    assert list_resp.status_code == 200
    assert list_resp.json() == []


async def test_validate_llm_provider_requires_admin_role_in_oidc_mode(client, actor_payload, monkeypatch):
    auth_context = _oidc_context(roles=["workspace-user"])
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    response = await client.post(
        "/v1/llm-providers/validate",
        headers={"Authorization": "Bearer good-token"},
        json={
            "actor": actor_payload,
            "engine_id": "dry-run-openai",
            "display_name": "Dry Run OpenAI",
            "description": "Dry-run provider validation.",
            "provider": "openai",
            "endpoint_kind": "remote",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


async def test_llm_provider_health_check_requires_admin_role_in_oidc_mode(client, actor_payload, monkeypatch):
    create_resp = await client.post(
        "/v1/llm-providers",
        json={
            "actor": actor_payload,
            "engine_id": "stored-openai",
            "display_name": "Stored OpenAI",
            "description": "Stored provider for auth check.",
            "provider": "openai",
            "endpoint_kind": "remote",
        },
    )
    assert create_resp.status_code == 200
    provider_id = create_resp.json()["provider_id"]

    auth_context = _oidc_context(roles=["workspace-user"])
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        assert token == "good-token"
        return auth_context

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)

    response = await client.post(
        f"/v1/llm-providers/{provider_id}/health-check",
        headers={"Authorization": "Bearer good-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


async def test_list_llm_engines_includes_managed_llm_providers(client, actor_payload, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    create_resp = await client.post(
        "/v1/llm-providers",
        json={
            "actor": actor_payload,
            "engine_id": "managed-anthropic",
            "display_name": "Managed Anthropic",
            "description": "Managed provider from API.",
            "provider": "anthropic",
            "endpoint_kind": "remote",
            "url": "https://api.anthropic.example/v1/messages",
            "default_model": "claude-sonnet-4-5",
            "capabilities": ["chat", "reasoning"],
            "secret_config": {
                "openbao": {
                    "mount": "secret",
                    "path": "open-talon/llm/anthropic",
                    "field": "api_key",
                }
            },
        },
    )
    assert create_resp.status_code == 200

    resp = await client.get("/v1/llm-engines")

    assert resp.status_code == 200
    engines = {engine["engine_id"]: engine for engine in resp.json()}
    assert engines["managed-anthropic"]["provider"] == "anthropic"
    assert engines["managed-anthropic"]["metadata"]["secret_config"]["openbao"]["path"] == (
        "open-talon/llm/anthropic"
    )


async def test_list_llm_engines_returns_empty_when_no_providers_exist(client):
    resp = await client.get("/v1/llm-engines")

    assert resp.status_code == 200
    assert resp.json() == []


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


async def test_create_workspace_tool_exposes_it_in_workspace_detail(client, actor_payload):
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Tool Catalog", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    system_tool_resp = await client.post(
        "/v1/tools",
        json={
            "actor": actor_payload,
            "name": "repo_search",
            "description": "Searches the current workspace source tree.",
            "parameter_contract": {
                "parameters": [
                    {
                        "name": "query",
                        "type": "string",
                        "description": "Search text to look up in the repository.",
                        "required": True,
                    }
                ],
                "additional_properties": False,
            },
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
            "metadata": {"provider": "workspace"},
        },
    )
    tool_id = system_tool_resp.json()["tool_id"]
    tool_resp = await client.put(
        f"/v1/workspaces/{workspace_id}/tools/{tool_id}",
        json={
            "actor": actor_payload,
            "tool_id": tool_id,
            "enabled": True,
            "metadata": {"provider": "workspace"},
        },
    )

    assert tool_resp.status_code == 200
    assert system_tool_resp.status_code == 200
    assert tool_resp.json()["name"] == "repo_search"
    assert tool_resp.json()["description"] == "Searches the current workspace source tree."
    assert tool_resp.json()["parameter_contract"]["parameters"][0]["name"] == "query"

    detail_resp = await client.get(f"/v1/workspaces/{workspace_id}")
    assert detail_resp.status_code == 200
    tools = {tool["name"]: tool for tool in detail_resp.json()["tools"]}
    assert tools["repo_search"]["enabled"] is True
    assert tools["repo_search"]["metadata"]["provider"] == "workspace"


async def test_system_tools_can_be_listed_and_updated(client, actor_payload):
    create_resp = await client.post(
        "/v1/tools",
        json={
            "actor": actor_payload,
            "name": "repo_search",
            "description": "Searches the current workspace source tree.",
            "parameter_contract": {
                "parameters": [
                    {
                        "name": "query",
                        "type": "string",
                        "description": "Search text to look up in the repository.",
                        "required": True,
                    }
                ],
                "additional_properties": False,
            },
            "input_schema": {"type": "object"},
        },
    )
    assert create_resp.status_code == 200
    tool_id = create_resp.json()["tool_id"]

    list_resp = await client.get("/v1/tools")
    assert list_resp.status_code == 200
    assert [tool["name"] for tool in list_resp.json()] == ["repo_search"]

    update_resp = await client.patch(
        f"/v1/tools/{tool_id}",
        json={
            "actor": actor_payload,
            "description": "Searches repository code and metadata.",
            "metadata": {"version": 2},
        },
    )
    assert update_resp.status_code == 200
    body = update_resp.json()
    assert body["tool_id"] == tool_id
    assert body["description"] == "Searches repository code and metadata."
    assert body["metadata"]["version"] == 2
    assert body["parameter_contract"]["parameters"][0]["name"] == "query"


async def test_workspace_tool_attachment_can_be_disabled_and_removed(client, actor_payload):
    workspace_resp = await client.post(
        "/v1/workspaces",
        json={"name": "Tool Lifecycle", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]

    agent_resp = await client.post(
        "/v1/agents",
        json={
            "actor": actor_payload,
            "display_name": "Research Analyst",
            "description": "Investigates product questions and synthesizes findings.",
            "role": "research analyst",
            "capabilities": ["research", "synthesis"],
            "endpoint": {
                "kind": "remote",
                "url": "https://api.example.com/v1/responses",
                "model": "gpt-5.4",
            },
            "system_prompt": "You are a research-focused agent.",
        },
    )
    agent_id = agent_resp.json()["agent_id"]

    system_tool_resp = await client.post(
        "/v1/tools",
        json={
            "actor": actor_payload,
            "name": "repo_search",
            "description": "Searches the current workspace source tree.",
            "parameter_contract": {
                "parameters": [
                    {
                        "name": "query",
                        "type": "string",
                        "description": "Search text to look up in the repository.",
                        "required": True,
                    }
                ],
                "additional_properties": False,
            },
        },
    )
    tool_id = system_tool_resp.json()["tool_id"]

    attach_resp = await client.put(
        f"/v1/workspaces/{workspace_id}/tools/{tool_id}",
        json={
            "actor": actor_payload,
            "tool_id": tool_id,
            "enabled": True,
        },
    )
    assert attach_resp.status_code == 200

    disable_resp = await client.patch(
        f"/v1/workspaces/{workspace_id}/tools/{tool_id}",
        json={
            "actor": actor_payload,
            "enabled": False,
            "metadata": {"reason": "maintenance"},
        },
    )
    assert disable_resp.status_code == 200
    assert disable_resp.json()["enabled"] is False
    assert disable_resp.json()["metadata"]["reason"] == "maintenance"

    workspace_detail = await client.get(f"/v1/workspaces/{workspace_id}")
    assert workspace_detail.status_code == 200
    tools = {tool["tool_id"]: tool for tool in workspace_detail.json()["tools"]}
    assert tools[tool_id]["enabled"] is False

    attach_agent_resp = await client.post(
        f"/v1/workspaces/{workspace_id}/agents",
        json={"actor": actor_payload, "agent_id": agent_id},
    )
    assert attach_agent_resp.status_code == 200
    assert "tool:repo_search" not in attach_agent_resp.json()["capabilities"]

    delete_resp = await client.request(
        "DELETE",
        f"/v1/workspaces/{workspace_id}/tools/{tool_id}",
        json={"actor": actor_payload},
    )
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True
    assert delete_resp.json()["tool_id"] == tool_id

    final_detail = await client.get(f"/v1/workspaces/{workspace_id}")
    assert final_detail.status_code == 200
    assert final_detail.json()["tools"] == []


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

    system_tool_resp = await client.post(
        "/v1/tools",
        json={
            "actor": actor_payload,
            "name": "repo_search",
            "description": "Searches the current workspace source tree.",
        },
    )
    tool_id = system_tool_resp.json()["tool_id"]
    tool_resp = await client.put(
        f"/v1/workspaces/{workspace_id}/tools/{tool_id}",
        json={
            "actor": actor_payload,
            "tool_id": tool_id,
            "enabled": True,
        },
    )
    assert tool_resp.status_code == 200

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
    assert body["capabilities"] == ["research", "synthesis", "briefs", "tool:repo_search"]
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
    assert "tool:repo_search" in agents[0]["capabilities"]


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


async def test_create_system_agent_preserves_engine_id_and_provider(client, actor_payload):
    create_resp = await client.post(
        "/v1/agents",
        json={
            "actor": actor_payload,
            "display_name": "Reasoning Planner",
            "description": "Plans multi-step work with cloud reasoning.",
            "role": "planning agent",
            "capabilities": ["planning", "triage", "reasoning"],
            "endpoint": {
                "kind": "remote",
                "engine_id": "openai-responses",
                "provider": "openai",
            },
            "system_prompt": "You plan carefully and explain tradeoffs clearly.",
            "definition": {
                "runtime": {
                    "engine_id": "openai-responses",
                    "preferred_capabilities": ["reasoning", "tool_calling"],
                    "preferred_locality": "cloud",
                }
            },
        },
    )

    assert create_resp.status_code == 200
    body = create_resp.json()
    assert body["endpoint"]["engine_id"] == "openai-responses"
    assert body["endpoint"]["provider"] == "openai"
    assert body["definition"]["runtime"]["engine_id"] == "openai-responses"


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
