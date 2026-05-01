from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4

_TESTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from gateway_edge.config import settings
from gateway_edge.models import AuthContext, IamRoleDefinition, ParticipantProfile


def _oidc_context(*, user_id: UUID, display_name: str) -> AuthContext:
    return AuthContext(
        kind="oidc",
        user_id=user_id,
        issuer="http://issuer.test/realms/open-talon",
        subject=f"subject-{user_id}",
        email=f"{user_id}@example.test",
        display_name=display_name,
        roles=["workspace-user"],
        claims={"sub": f"subject-{user_id}"},
    )


def _patch_oidc_tokens(monkeypatch, token_map: dict[str, AuthContext]) -> None:
    monkeypatch.setattr(settings, "auth_mode", "oidc")

    async def _validate(token: str):
        return token_map.get(token)

    async def _sync(context):
        return context

    monkeypatch.setattr("gateway_edge.auth.middleware.validate_oidc_token", _validate)
    monkeypatch.setattr("gateway_edge.auth.middleware.sync_oidc_auth_context", _sync)


def _actor_payload(user_id: UUID, display_name: str) -> dict[str, str]:
    return {
        "participant_id": str(user_id),
        "participant_type": "user",
        "user_id": str(user_id),
        "display_name": display_name,
    }


def _add_org_member(mock_collaboration_service, organization_id: UUID, user_id: UUID, role: str) -> None:
    now = datetime.now(timezone.utc)
    mock_collaboration_service.organization_memberships.setdefault(str(organization_id), {})[
        str(user_id)
    ] = {
        "organization_id": organization_id,
        "user_id": user_id,
        "role": role,
        "joined_at": now,
        "updated_at": now,
        "metadata": {},
    }


def _attach_human_participant(
    mock_collaboration_service,
    *,
    workspace_id: UUID,
    user_id: UUID,
    display_name: str,
) -> UUID:
    now = datetime.now(timezone.utc)
    participant_id = uuid4()
    mock_collaboration_service.participants.setdefault(str(workspace_id), {})[
        str(participant_id)
    ] = ParticipantProfile(
        participant_id=participant_id,
        workspace_id=workspace_id,
        participant_type="user",
        user_id=user_id,
        display_name=display_name,
        created_at=now,
        updated_at=now,
    )
    return participant_id


def _grant_permissions(
    mock_collaboration_service,
    *,
    user_id: UUID,
    organization_id: UUID,
    permissions: list[str],
    name: str,
) -> None:
    now = datetime.now(timezone.utc)
    role = IamRoleDefinition(
        role_id=uuid4(),
        scope="organization",
        subject_kind="human",
        organization_id=organization_id,
        name=name,
        description="Test-only IAM role.",
        permissions=permissions,
        created_at=now,
        updated_at=now,
        metadata={},
    )
    mock_collaboration_service.iam_roles[str(role.role_id)] = role
    mock_collaboration_service.human_role_bindings.setdefault(str(user_id), set()).add(
        str(role.role_id)
    )


async def _create_workspace(client, *, owner_user_id: UUID) -> tuple[UUID, UUID]:
    response = await client.post(
        "/v1/workspaces",
        json={
            "name": f"External access {uuid4().hex[:8]}",
            "actor": _actor_payload(owner_user_id, "Workspace Owner"),
        },
    )
    assert response.status_code == 200
    workspace = response.json()["workspace"]
    return UUID(workspace["workspace_id"]), UUID(workspace["organization_id"])


async def _create_external_system(
    client,
    *,
    token: str,
    organization_id: UUID,
    actor: dict[str, str],
    operation_catalog: dict[str, object] | None = None,
):
    response = await client.post(
        f"/v1/organizations/{organization_id}/external-systems",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "actor": actor,
            "system_key": f"crm-{uuid4().hex[:8]}",
            "display_name": "CRM",
            "description": "Customer records",
            "auth_kind": "bearer_token",
            "secret_config": {"bearer_token": {"value": "do-not-return"}},
            "operation_catalog": operation_catalog or {},
        },
    )
    assert response.status_code == 200
    return response.json()


async def _create_external_account(
    client,
    *,
    token: str,
    workspace_id: UUID,
    system_id: str,
    actor: dict[str, str],
    user_id: UUID,
):
    response = await client.post(
        f"/v1/workspaces/{workspace_id}/external-accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "actor": actor,
            "system_id": system_id,
            "owner_kind": "user",
            "user_id": str(user_id),
            "display_name": "Member CRM",
            "credential_ref": {"bearer_token": {"value": "member-token"}},
        },
    )
    assert response.status_code == 200
    return response.json()


async def _create_external_grant(
    client,
    *,
    token: str,
    workspace_id: UUID,
    actor: dict[str, str],
    participant_id: UUID,
    system_id: str,
    account_id: str | None = None,
    allowed_operations: list[str] | None = None,
    risk_policy: dict[str, object] | None = None,
):
    response = await client.post(
        f"/v1/workspaces/{workspace_id}/external-identity-grants",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "actor": actor,
            "participant_id": str(participant_id),
            "system_id": system_id,
            "account_id": account_id,
            "allowed_operations": allowed_operations or [],
            "risk_policy": risk_policy or {},
        },
    )
    assert response.status_code == 200
    return response.json()


async def test_ordinary_participant_cannot_manage_grants_or_approve_operations(
    client,
    mock_collaboration_service,
    monkeypatch,
):
    admin_user_id = uuid4()
    member_user_id = uuid4()
    workspace_id, organization_id = await _create_workspace(client, owner_user_id=admin_user_id)
    member_participant_id = _attach_human_participant(
        mock_collaboration_service,
        workspace_id=workspace_id,
        user_id=member_user_id,
        display_name="Ordinary Member",
    )
    _add_org_member(mock_collaboration_service, organization_id, member_user_id, "member")
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": _oidc_context(user_id=admin_user_id, display_name="Org Admin"),
            "member-token": _oidc_context(user_id=member_user_id, display_name="Ordinary Member"),
        },
    )
    admin_actor = _actor_payload(admin_user_id, "Org Admin")
    member_actor = _actor_payload(member_user_id, "Ordinary Member")

    denied_system = await client.post(
        f"/v1/organizations/{organization_id}/external-systems",
        headers={"Authorization": "Bearer member-token"},
        json={
            "actor": member_actor,
            "system_key": "member-crm",
            "display_name": "Member CRM",
            "auth_kind": "bearer_token",
        },
    )
    system = await _create_external_system(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor=admin_actor,
    )
    denied_account = await client.post(
        f"/v1/workspaces/{workspace_id}/external-accounts",
        headers={"Authorization": "Bearer member-token"},
        json={
            "actor": member_actor,
            "system_id": system["system_id"],
            "owner_kind": "user",
            "user_id": str(member_user_id),
        },
    )
    account = await _create_external_account(
        client,
        token="admin-token",
        workspace_id=workspace_id,
        system_id=system["system_id"],
        actor=admin_actor,
        user_id=member_user_id,
    )
    denied_grant = await client.post(
        f"/v1/workspaces/{workspace_id}/external-identity-grants",
        headers={"Authorization": "Bearer member-token"},
        json={
            "actor": member_actor,
            "participant_id": str(member_participant_id),
            "system_id": system["system_id"],
            "account_id": account["account_id"],
            "allowed_operations": ["crm.delete"],
        },
    )
    await _create_external_grant(
        client,
        token="admin-token",
        workspace_id=workspace_id,
        actor=admin_actor,
        participant_id=member_participant_id,
        system_id=system["system_id"],
        account_id=account["account_id"],
        allowed_operations=["crm.delete"],
    )

    operation = await client.post(
        f"/v1/workspaces/{workspace_id}/external-systems/{system['system_id']}/operations/crm.delete",
        headers={"Authorization": "Bearer member-token"},
        json={
            "actor": member_actor,
            "arguments": {"record_id": "customer-123", "secret": "not-audited"},
            "risk_level": "high",
        },
    )
    approve = await client.post(
        f"/v1/workspaces/{workspace_id}/external-operation-requests/"
        f"{operation.json()['operation_request']['operation_request_id']}/approve",
        headers={"Authorization": "Bearer member-token"},
        json={"actor": member_actor},
    )

    assert denied_system.status_code == 403
    assert denied_account.status_code == 403
    assert denied_grant.status_code == 403
    assert operation.status_code == 200
    assert operation.json()["approved"] is False
    assert operation.json()["operation_request"]["status"] == "pending_approval"
    assert approve.status_code == 403


async def test_participant_grant_listing_is_limited_to_own_active_grants(
    client,
    mock_collaboration_service,
    monkeypatch,
):
    admin_user_id = uuid4()
    member_user_id = uuid4()
    other_user_id = uuid4()
    workspace_id, organization_id = await _create_workspace(client, owner_user_id=admin_user_id)
    member_participant_id = _attach_human_participant(
        mock_collaboration_service,
        workspace_id=workspace_id,
        user_id=member_user_id,
        display_name="Ordinary Member",
    )
    other_participant_id = _attach_human_participant(
        mock_collaboration_service,
        workspace_id=workspace_id,
        user_id=other_user_id,
        display_name="Other Member",
    )
    _add_org_member(mock_collaboration_service, organization_id, member_user_id, "member")
    _add_org_member(mock_collaboration_service, organization_id, other_user_id, "member")
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": _oidc_context(user_id=admin_user_id, display_name="Org Admin"),
            "member-token": _oidc_context(user_id=member_user_id, display_name="Ordinary Member"),
        },
    )
    admin_actor = _actor_payload(admin_user_id, "Org Admin")
    member_actor = _actor_payload(member_user_id, "Ordinary Member")
    system = await _create_external_system(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor=admin_actor,
    )
    revoked = await _create_external_grant(
        client,
        token="admin-token",
        workspace_id=workspace_id,
        actor=admin_actor,
        participant_id=member_participant_id,
        system_id=system["system_id"],
        allowed_operations=["crm.read"],
    )
    revoke_response = await client.request(
        "DELETE",
        f"/v1/workspaces/{workspace_id}/external-identity-grants/{revoked['grant_id']}",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": admin_actor},
    )
    active = await _create_external_grant(
        client,
        token="admin-token",
        workspace_id=workspace_id,
        actor=admin_actor,
        participant_id=member_participant_id,
        system_id=system["system_id"],
        allowed_operations=["crm.update"],
    )
    other = await _create_external_grant(
        client,
        token="admin-token",
        workspace_id=workspace_id,
        actor=admin_actor,
        participant_id=other_participant_id,
        system_id=system["system_id"],
        allowed_operations=["crm.export"],
    )

    member_list = await client.get(
        f"/v1/workspaces/{workspace_id}/external-identity-grants",
        params={
            "participant_id": str(other_participant_id),
            "include_inactive": "true",
        },
        headers={"Authorization": "Bearer member-token"},
    )
    admin_list = await client.get(
        f"/v1/workspaces/{workspace_id}/external-identity-grants",
        params={"include_inactive": "true"},
        headers={"Authorization": "Bearer admin-token"},
    )

    assert revoke_response.status_code == 200
    assert member_list.status_code == 200
    assert [grant["grant_id"] for grant in member_list.json()] == [active["grant_id"]]
    assert {grant["grant_id"] for grant in admin_list.json()} == {
        revoked["grant_id"],
        active["grant_id"],
        other["grant_id"],
    }


async def test_direct_operation_executes_configured_http_operation_and_sanitizes_resolution(
    client,
    mock_collaboration_service,
    monkeypatch,
):
    admin_user_id = uuid4()
    member_user_id = uuid4()
    workspace_id, organization_id = await _create_workspace(client, owner_user_id=admin_user_id)
    member_participant_id = _attach_human_participant(
        mock_collaboration_service,
        workspace_id=workspace_id,
        user_id=member_user_id,
        display_name="Ordinary Member",
    )
    _add_org_member(mock_collaboration_service, organization_id, member_user_id, "member")
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": _oidc_context(user_id=admin_user_id, display_name="Org Admin"),
            "member-token": _oidc_context(user_id=member_user_id, display_name="Ordinary Member"),
        },
    )
    captured = {}

    class _Executor:
        async def execute(self, *, resolution, operation_key, arguments):
            captured["system_secret_config"] = resolution.system.secret_config
            captured["account_credential_ref"] = resolution.account.credential_ref
            captured["operation_key"] = operation_key
            captured["arguments"] = arguments
            return {"executed": True, "status_code": 200, "body": {"ok": True}}

    monkeypatch.setattr(
        "gateway_edge.routers.external_access.direct_external_operation_executor",
        _Executor(),
    )
    admin_actor = _actor_payload(admin_user_id, "Org Admin")
    member_actor = _actor_payload(member_user_id, "Ordinary Member")
    system = await _create_external_system(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor=admin_actor,
        operation_catalog={"crm.read": {"transport": "http", "path": "/records/{record_id}"}},
    )
    account = await _create_external_account(
        client,
        token="admin-token",
        workspace_id=workspace_id,
        system_id=system["system_id"],
        actor=admin_actor,
        user_id=member_user_id,
    )
    await _create_external_grant(
        client,
        token="admin-token",
        workspace_id=workspace_id,
        actor=admin_actor,
        participant_id=member_participant_id,
        system_id=system["system_id"],
        account_id=account["account_id"],
        allowed_operations=["crm.read"],
        risk_policy={"preapproved_operations": ["crm.read"]},
    )

    response = await client.post(
        f"/v1/workspaces/{workspace_id}/external-systems/{system['system_id']}/operations/crm.read",
        headers={"Authorization": "Bearer member-token"},
        json={"actor": member_actor, "arguments": {"record_id": "cust-123"}},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["approved"] is True
    assert body["operation_result"] == {
        "executed": True,
        "status_code": 200,
        "body": {"ok": True},
    }
    assert body["system"]["secret_config"] == {}
    assert body["account"]["credential_ref"] == {}
    assert captured["system_secret_config"] == {"bearer_token": {"value": "do-not-return"}}
    assert captured["account_credential_ref"] == {"bearer_token": {"value": "member-token"}}
    assert captured["operation_key"] == "crm.read"
    assert captured["arguments"] == {"record_id": "cust-123"}


async def test_external_access_update_revoke_and_review_reject_wrong_workspace_scope(
    client,
    mock_collaboration_service,
    monkeypatch,
):
    admin_user_id = uuid4()
    member_user_id = uuid4()
    workspace_id, organization_id = await _create_workspace(client, owner_user_id=admin_user_id)
    wrong_workspace_id, _ = await _create_workspace(client, owner_user_id=admin_user_id)
    member_participant_id = _attach_human_participant(
        mock_collaboration_service,
        workspace_id=workspace_id,
        user_id=member_user_id,
        display_name="Ordinary Member",
    )
    _add_org_member(mock_collaboration_service, organization_id, member_user_id, "member")
    _patch_oidc_tokens(
        monkeypatch,
        {
            "admin-token": _oidc_context(user_id=admin_user_id, display_name="Org Admin"),
            "member-token": _oidc_context(user_id=member_user_id, display_name="Ordinary Member"),
        },
    )
    admin_actor = _actor_payload(admin_user_id, "Org Admin")
    member_actor = _actor_payload(member_user_id, "Ordinary Member")
    system = await _create_external_system(
        client,
        token="admin-token",
        organization_id=organization_id,
        actor=admin_actor,
    )
    grant = await _create_external_grant(
        client,
        token="admin-token",
        workspace_id=workspace_id,
        actor=admin_actor,
        participant_id=member_participant_id,
        system_id=system["system_id"],
        allowed_operations=["crm.delete"],
    )
    operation = await client.post(
        f"/v1/workspaces/{workspace_id}/external-systems/{system['system_id']}/operations/crm.delete",
        headers={"Authorization": "Bearer member-token"},
        json={"actor": member_actor, "risk_level": "high"},
    )
    operation_request_id = operation.json()["operation_request"]["operation_request_id"]

    wrong_patch = await client.patch(
        f"/v1/workspaces/{wrong_workspace_id}/external-identity-grants/{grant['grant_id']}",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": admin_actor, "allowed_operations": ["crm.read"]},
    )
    wrong_delete = await client.request(
        "DELETE",
        f"/v1/workspaces/{wrong_workspace_id}/external-identity-grants/{grant['grant_id']}",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": admin_actor},
    )
    wrong_approve = await client.post(
        f"/v1/workspaces/{wrong_workspace_id}/external-operation-requests/"
        f"{operation_request_id}/approve",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": admin_actor},
    )
    wrong_reject = await client.post(
        f"/v1/workspaces/{wrong_workspace_id}/external-operation-requests/"
        f"{operation_request_id}/reject",
        headers={"Authorization": "Bearer admin-token"},
        json={"actor": admin_actor},
    )

    assert wrong_patch.status_code == 404
    assert wrong_delete.status_code == 404
    assert wrong_approve.status_code == 404
    assert wrong_reject.status_code == 404


async def test_agent_attach_external_grant_preassignment_requires_external_grant_permission(
    client,
    mock_collaboration_service,
    monkeypatch,
):
    owner_user_id = uuid4()
    manager_user_id = uuid4()
    workspace_id, organization_id = await _create_workspace(client, owner_user_id=owner_user_id)
    _attach_human_participant(
        mock_collaboration_service,
        workspace_id=workspace_id,
        user_id=manager_user_id,
        display_name="Agent Manager",
    )
    _add_org_member(mock_collaboration_service, organization_id, manager_user_id, "member")
    _grant_permissions(
        mock_collaboration_service,
        user_id=manager_user_id,
        organization_id=organization_id,
        permissions=["workspace.agents.write"],
        name="workspace-agent-manager",
    )
    owner_actor = _actor_payload(owner_user_id, "Owner")
    manager_actor = _actor_payload(manager_user_id, "Agent Manager")
    create_agent = await client.post(
        "/v1/agents",
        json={
            "actor": owner_actor,
            "display_name": "CRM Agent",
            "description": "Uses CRM when explicitly granted.",
            "role": "crm-specialist",
            "capabilities": ["crm"],
            "endpoint": {"kind": "remote", "model": "gpt-5.4"},
            "system_prompt": "Use external access only when granted.",
        },
    )
    assert create_agent.status_code == 200
    agent_id = create_agent.json()["agent_id"]
    _patch_oidc_tokens(
        monkeypatch,
        {
            "owner-token": _oidc_context(user_id=owner_user_id, display_name="Owner"),
            "manager-token": _oidc_context(user_id=manager_user_id, display_name="Agent Manager"),
        },
    )
    system = await _create_external_system(
        client,
        token="owner-token",
        organization_id=organization_id,
        actor=owner_actor,
    )
    payload = {
        "actor": manager_actor,
        "agent_id": agent_id,
        "external_access_grants": [
            {
                "system_id": system["system_id"],
                "allowed_operations": ["crm.read"],
                "risk_policy": {"preapproved_operations": ["crm.read"]},
            }
        ],
    }

    denied = await client.post(
        f"/v1/workspaces/{workspace_id}/agents",
        headers={"Authorization": "Bearer manager-token"},
        json=payload,
    )
    _grant_permissions(
        mock_collaboration_service,
        user_id=manager_user_id,
        organization_id=organization_id,
        permissions=["external.grants.write"],
        name="external-grant-manager",
    )
    allowed = await client.post(
        f"/v1/workspaces/{workspace_id}/agents",
        headers={"Authorization": "Bearer manager-token"},
        json=payload,
    )

    assert denied.status_code == 403
    assert allowed.status_code == 200
    created_grants = [
        grant
        for grant in mock_collaboration_service.external_identity_grants.values()
        if str(grant.participant_id) == allowed.json()["participant_id"]
    ]
    assert len(created_grants) == 1
    assert str(created_grants[0].system_agent_id) == agent_id
    assert created_grants[0].allowed_operations == ["crm.read"]
