from __future__ import annotations

from uuid import uuid4

import pytest

from agent_runtime.execution.mcp import McpExecutionBackend
from open_talon_contracts.models import (
    ExecutionSpec,
    ExternalAccount,
    ExternalIdentityGrant,
    ExternalIdentityResolution,
    ExternalOperationRequest,
    ExternalSystemDefinition,
    McpServerDefinition,
)


class _PendingApprovalKernel:
    def __init__(self, server: McpServerDefinition) -> None:
        self.server = server
        self.calls = []
        self.system = ExternalSystemDefinition(
            system_id=uuid4(),
            scope="organization",
            organization_id=uuid4(),
            system_key="crm",
            display_name="CRM",
            auth_kind="bearer_token",
            created_by=uuid4(),
            updated_by=uuid4(),
        )
        self.grant = ExternalIdentityGrant(
            grant_id=uuid4(),
            workspace_id=uuid4(),
            participant_id=uuid4(),
            system_id=self.system.system_id,
            system_agent_id=uuid4(),
            allowed_operations=["crm.delete"],
            created_by=uuid4(),
            updated_by=uuid4(),
        )
        self.operation_request = ExternalOperationRequest(
            operation_request_id=uuid4(),
            workspace_id=self.grant.workspace_id,
            thread_id=uuid4(),
            tool_call_id=uuid4(),
            system_id=self.system.system_id,
            grant_id=self.grant.grant_id,
            participant_id=self.grant.participant_id,
            system_agent_id=self.grant.system_agent_id,
            operation_key="crm.delete",
            source="mcp",
            risk_level="high",
            requested_by=self.grant.participant_id,
        )

    async def get_mcp_server(self, server_id):
        return self.server if server_id == self.server.server_id else None

    async def resolve_external_identity_for_operation(self, **kwargs):
        self.calls.append(kwargs)
        return ExternalIdentityResolution(
            system=self.system,
            grant=self.grant,
            operation_request=self.operation_request,
            approved=False,
        )


class _ApprovedKernel(_PendingApprovalKernel):
    def __init__(self, server: McpServerDefinition) -> None:
        super().__init__(server)
        self.account = ExternalAccount(
            account_id=uuid4(),
            system_id=self.system.system_id,
            owner_kind="agent",
            system_agent_id=self.grant.system_agent_id,
            credential_ref={
                "bearer_token": {"value": "account-token"},
                "headers": {"X-External-Subject": {"value": "acct-123"}},
            },
            created_by=uuid4(),
            updated_by=uuid4(),
        )
        self.system = self.system.model_copy(
            update={"secret_config": {"bearer_token": {"value": "system-token"}}}
        )
        self.grant = self.grant.model_copy(update={"account_id": self.account.account_id})

    async def resolve_external_identity_for_operation(self, **kwargs):
        self.calls.append(kwargs)
        return ExternalIdentityResolution(
            system=self.system,
            grant=self.grant,
            account=self.account,
            approved=True,
        )


@pytest.mark.asyncio
async def test_mcp_external_identity_returns_pending_approval_without_network_call():
    workspace_id = uuid4()
    system_agent_id = uuid4()
    tool_call_id = uuid4()
    thread_id = uuid4()
    server = McpServerDefinition(
        server_id=uuid4(),
        server_key="crm_mcp",
        display_name="CRM MCP",
        description="CRM bridge",
        config={
            "url": "http://example.invalid/mcp",
            "auth": {
                "kind": "external_identity",
                "external_system_key": "crm",
                "risk_level": "high",
            },
        },
        created_by=uuid4(),
        updated_by=uuid4(),
    )
    kernel = _PendingApprovalKernel(server)
    backend = McpExecutionBackend(kernel=kernel)
    spec = ExecutionSpec(
        invocation_id=uuid4(),
        handler_ref="crm.delete",
        inline_payload={"record_id": "123", "token": "should-not-be-recorded"},
        metadata={
            "mcp_server_id": str(server.server_id),
            "workspace_id": str(workspace_id),
            "system_agent_id": str(system_agent_id),
            "thread_id": str(thread_id),
            "tool_call_id": str(tool_call_id),
            "mcp_tool_name": "crm.delete",
        },
    )

    handle = await backend.submit(spec)
    result = await backend.collect(handle)

    assert result.status == "pending_approval"
    assert result.metadata["external_operation_pending_approval"] is True
    assert result.output_payload["operation_request_id"] == str(
        kernel.operation_request.operation_request_id
    )
    assert kernel.calls == [
        {
            "workspace_id": workspace_id,
            "system_agent_id": system_agent_id,
            "system_id": None,
            "system_key": "crm",
            "operation_key": "crm.delete",
            "risk_level": "high",
            "source": "mcp",
            "thread_id": thread_id,
            "tool_call_id": tool_call_id,
            "request_metadata": {
                "mcp_server_id": str(server.server_id),
                "mcp_server_key": "crm_mcp",
                "mcp_tool_name": "crm.delete",
                "argument_keys": ["record_id", "token"],
            },
        }
    ]


@pytest.mark.asyncio
async def test_mcp_external_identity_uses_approved_account_credentials_for_headers():
    workspace_id = uuid4()
    system_agent_id = uuid4()
    server = McpServerDefinition(
        server_id=uuid4(),
        server_key="crm_mcp",
        display_name="CRM MCP",
        description="CRM bridge",
        config={
            "url": "http://example.invalid/mcp",
            "auth": {
                "kind": "external_identity",
                "external_system_key": "crm",
            },
        },
        created_by=uuid4(),
        updated_by=uuid4(),
    )
    kernel = _ApprovedKernel(server)
    backend = McpExecutionBackend(kernel=kernel)
    spec = ExecutionSpec(
        invocation_id=uuid4(),
        handler_ref="crm.read",
        inline_payload={"record_id": "123"},
        metadata={
            "mcp_server_id": str(server.server_id),
            "workspace_id": str(workspace_id),
            "system_agent_id": str(system_agent_id),
            "mcp_tool_name": "crm.read",
        },
    )

    headers = await backend._headers_for_server(server, spec)  # noqa: SLF001

    assert headers["Authorization"] == "Bearer account-token"
    assert headers["X-External-Subject"] == "acct-123"
    assert "system-token" not in str(headers)
    assert kernel.calls[0]["workspace_id"] == workspace_id
    assert kernel.calls[0]["system_agent_id"] == system_agent_id
    assert kernel.calls[0]["request_metadata"]["argument_keys"] == ["record_id"]
