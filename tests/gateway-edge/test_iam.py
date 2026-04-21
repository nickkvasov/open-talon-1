from __future__ import annotations

from uuid import uuid4

from gateway_edge.config import settings
from gateway_edge.models import AuthContext


def _oidc_context(*, roles: list[str], user_id=None) -> AuthContext:
    return AuthContext(
        kind="oidc",
        user_id=user_id or uuid4(),
        issuer="http://issuer.test/realms/open-talon",
        subject="subject-123",
        email="nikolay@example.com",
        display_name="Nikolay",
        roles=roles,
        claims={"sub": "subject-123"},
    )


def _agent_context(*, agent_identity_id, system_agent_id, client_id: str) -> AuthContext:
    return AuthContext(
        kind="oidc",
        principal_type="agent",
        agent_identity_id=agent_identity_id,
        system_agent_id=system_agent_id,
        issuer="http://issuer.test/realms/open-talon",
        subject=f"service-account-{client_id}",
        client_id=client_id,
        provider_key="keycloak",
        display_name="Provisioned Agent",
        claims={"azp": client_id, "sub": f"service-account-{client_id}"},
    )


def _patch_oidc_tokens(monkeypatch, token_map: dict[str, AuthContext]) -> None:
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        return token_map.get(token)

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)


async def test_iam_permissions_route_lists_identity_and_workspace_permissions(client):
    response = await client.get("/v1/iam/permissions")

    assert response.status_code == 200
    permissions = {item["name"]: item["scope_type"] for item in response.json()}
    assert permissions["organization.members.write"] == "identity"
    assert permissions["tool_generation.review"] == "identity"
    assert permissions["workspace.tools.write"] == "workspace"
    assert permissions["workspace.audit.verify"] == "workspace"


async def test_human_iam_role_binding_grants_provider_permissions(
    client,
    actor_payload,
    monkeypatch,
):
    admin = _oidc_context(roles=["admin"])
    human = _oidc_context(roles=["workspace-user"])
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": admin,
            "human-token": human,
        },
    )

    create_role = await client.post(
        "/v1/iam/human-roles",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "name": "llm-operator",
            "description": "May manage global LLM providers.",
            "permissions": ["provider.llm.read", "provider.llm.write", "provider.llm.validate"],
        },
    )

    assert create_role.status_code == 200
    role_id = create_role.json()["role_id"]

    bind_role = await client.post(
        f"/v1/iam/users/{human.user_id}/roles/{role_id}",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": actor_payload},
    )

    assert bind_role.status_code == 200

    create_provider = await client.post(
        "/v1/llm-providers",
        headers={"Authorization": "Bearer human-token"},
        json={
            "actor": actor_payload,
            "engine_id": "delegated-openai",
            "display_name": "Delegated OpenAI",
            "description": "Managed through IAM role binding.",
            "provider": "openai",
            "endpoint_kind": "remote",
        },
    )
    list_roles = await client.get(
        f"/v1/iam/users/{human.user_id}/roles",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert create_provider.status_code == 200
    assert create_provider.json()["engine_id"] == "delegated-openai"
    assert list_roles.status_code == 200
    assert [item["name"] for item in list_roles.json()] == ["llm-operator"]


async def test_agent_identity_lifecycle_and_agent_role_permissions(
    client,
    actor_payload,
    monkeypatch,
):
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    create_agent = await client.post(
        "/v1/agents",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "display_name": "Catalog Reader",
            "description": "Reads the global agent catalog.",
            "role": "catalog-reader",
            "capabilities": ["catalog"],
            "endpoint": {"kind": "remote", "model": "gpt-5.4"},
            "system_prompt": "Read catalogs only.",
        },
    )

    assert create_agent.status_code == 200
    system_agent_id = create_agent.json()["agent_id"]

    create_role = await client.post(
        "/v1/iam/agent-roles",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "name": "agent-catalog-reader",
            "description": "May read the global agent catalog.",
            "permissions": ["agent_catalog.read"],
        },
    )

    assert create_role.status_code == 200
    role_id = create_role.json()["role_id"]

    provision = await client.post(
        "/v1/iam/agent-identities",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "system_agent_id": system_agent_id,
            "client_id": "catalog-reader-client",
        },
    )

    assert provision.status_code == 200
    provisioned = provision.json()
    assert provisioned["client_secret"] == "secret-catalog-reader-client"
    assert provisioned["identity"]["client_id"] == "catalog-reader-client"
    assert provisioned["identity"]["secret_ref"]["openbao"]["field"] == "client_secret"
    agent_identity_id = provisioned["identity"]["agent_identity_id"]

    bind_role = await client.post(
        f"/v1/iam/agent-identities/{agent_identity_id}/roles/{role_id}",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": actor_payload},
    )
    rotate = await client.post(
        f"/v1/iam/agent-identities/{agent_identity_id}/rotate-secret",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": actor_payload},
    )
    disable = await client.post(
        f"/v1/iam/agent-identities/{agent_identity_id}/disable",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": actor_payload},
    )
    enable = await client.post(
        f"/v1/iam/agent-identities/{agent_identity_id}/enable",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": actor_payload},
    )
    list_roles = await client.get(
        f"/v1/iam/agent-identities/{agent_identity_id}/roles",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert bind_role.status_code == 200
    assert rotate.status_code == 200
    assert rotate.json()["client_secret"] == "rotated-catalog-reader-client"
    assert disable.status_code == 200
    assert disable.json()["status"] == "disabled"
    assert enable.status_code == 200
    assert enable.json()["status"] == "active"
    assert list_roles.status_code == 200
    assert [item["name"] for item in list_roles.json()] == ["agent-catalog-reader"]

    agent_context = _agent_context(
        agent_identity_id=provisioned["identity"]["agent_identity_id"],
        system_agent_id=provisioned["identity"]["system_agent_id"],
        client_id=provisioned["identity"]["client_id"],
    )
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": admin,
            "agent-token": agent_context,
        },
    )

    denied = await client.get(
        "/v1/tools",
        headers={"Authorization": "Bearer agent-token"},
    )
    allowed = await client.get(
        "/v1/agents",
        headers={"Authorization": "Bearer agent-token"},
    )

    assert denied.status_code == 403
    assert denied.json()["detail"] == "Permission 'tool_catalog.read' required"
    assert allowed.status_code == 200
    assert allowed.json()[0]["display_name"] == "Catalog Reader"


async def test_organization_human_role_binding_extends_member_permissions(
    client,
    actor_payload,
    monkeypatch,
):
    organization_id = "11111111-1111-1111-1111-111111111111"
    admin = _oidc_context(roles=["admin"])
    member = _oidc_context(roles=["workspace-user"])
    target_user_id = uuid4()
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": admin,
            "member-token": member,
        },
    )

    add_member = await client.post(
        f"/v1/organizations/{organization_id}/members",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "user_id": str(member.user_id),
            "role": "member",
        },
    )
    create_role = await client.post(
        f"/v1/organizations/{organization_id}/iam/human-roles",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "name": "membership-manager",
            "description": "May manage organization members.",
            "permissions": ["organization.members.write", "organization.members.read"],
        },
    )

    assert add_member.status_code == 200
    assert create_role.status_code == 200
    role_id = create_role.json()["role_id"]

    bind_role = await client.post(
        f"/v1/organizations/{organization_id}/iam/users/{member.user_id}/roles/{role_id}",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": actor_payload},
    )
    delegated_add = await client.post(
        f"/v1/organizations/{organization_id}/members",
        headers={"Authorization": "Bearer member-token"},
        json={
            "actor": actor_payload,
            "user_id": str(target_user_id),
            "role": "member",
        },
    )

    assert bind_role.status_code == 200
    assert delegated_add.status_code == 200
    assert delegated_add.json()["user_id"] == str(target_user_id)


async def test_organization_agent_role_binding_allows_org_tool_management(
    client,
    actor_payload,
    monkeypatch,
):
    organization_id = "11111111-1111-1111-1111-111111111111"
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    create_agent = await client.post(
        f"/v1/organizations/{organization_id}/agents",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "display_name": "Org Tool Operator",
            "description": "Manages org tool definitions.",
            "role": "tool-operator",
            "capabilities": ["tools"],
            "endpoint": {"kind": "remote", "model": "gpt-5.4"},
            "system_prompt": "Manage organization tools.",
        },
    )
    assert create_agent.status_code == 200
    system_agent_id = create_agent.json()["agent_id"]

    create_role = await client.post(
        f"/v1/organizations/{organization_id}/iam/agent-roles",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "name": "org-tool-operator",
            "description": "May manage organization tool definitions.",
            "permissions": ["tool_catalog.read", "tool_catalog.write"],
        },
    )
    assert create_role.status_code == 200
    role_id = create_role.json()["role_id"]

    provision = await client.post(
        f"/v1/organizations/{organization_id}/iam/agent-identities",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "system_agent_id": system_agent_id,
            "client_id": "org-tool-operator-client",
        },
    )
    assert provision.status_code == 200
    identity = provision.json()["identity"]
    agent_identity_id = identity["agent_identity_id"]

    bind_role = await client.post(
        f"/v1/iam/agent-identities/{agent_identity_id}/roles/{role_id}",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": actor_payload},
    )
    assert bind_role.status_code == 200

    agent_context = _agent_context(
        agent_identity_id=identity["agent_identity_id"],
        system_agent_id=identity["system_agent_id"],
        client_id=identity["client_id"],
    )
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": admin,
            "agent-token": agent_context,
        },
    )

    create_tool = await client.post(
        f"/v1/organizations/{organization_id}/tools",
        headers={"Authorization": "Bearer agent-token"},
        json={
            "actor": actor_payload,
            "name": "org_repo_search",
            "description": "Managed by an org-scoped agent identity.",
        },
    )
    list_tools = await client.get(
        f"/v1/organizations/{organization_id}/tools",
        headers={"Authorization": "Bearer agent-token"},
    )

    assert create_tool.status_code == 200
    assert create_tool.json()["name"] == "org_repo_search"
    assert list_tools.status_code == 200
    assert [item["name"] for item in list_tools.json()] == ["org_repo_search"]


async def test_duplicate_agent_identity_client_id_is_rejected(
    client,
    actor_payload,
    monkeypatch,
):
    admin = _oidc_context(roles=["admin"])
    _patch_oidc_tokens(monkeypatch, {"admin-token": admin})

    first_agent = await client.post(
        "/v1/agents",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "display_name": "First Machine",
            "description": "First machine identity target.",
            "role": "machine",
            "capabilities": [],
            "endpoint": {"kind": "remote", "model": "gpt-5.4"},
            "system_prompt": "First machine identity.",
        },
    )
    second_agent = await client.post(
        "/v1/agents",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "display_name": "Second Machine",
            "description": "Second machine identity target.",
            "role": "machine",
            "capabilities": [],
            "endpoint": {"kind": "remote", "model": "gpt-5.4"},
            "system_prompt": "Second machine identity.",
        },
    )

    assert first_agent.status_code == 200
    assert second_agent.status_code == 200

    first_provision = await client.post(
        "/v1/iam/agent-identities",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "system_agent_id": first_agent.json()["agent_id"],
            "client_id": "shared-client-id",
        },
    )
    duplicate = await client.post(
        "/v1/iam/agent-identities",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "actor": actor_payload,
            "system_agent_id": second_agent.json()["agent_id"],
            "client_id": "shared-client-id",
        },
    )

    assert first_provision.status_code == 200
    assert duplicate.status_code == 400
    assert "already exists" in duplicate.json()["detail"]
