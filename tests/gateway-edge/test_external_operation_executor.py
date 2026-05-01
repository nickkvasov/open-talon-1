from __future__ import annotations

import os
import sys
from uuid import uuid4

import httpx
import pytest

_GW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/gateway-edge")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
for path in (_GW_DIR, _CONTRACTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from gateway_edge.services.external_operations import DirectExternalOperationExecutor
from open_talon_contracts.models import (
    ExternalAccount,
    ExternalIdentityGrant,
    ExternalIdentityResolution,
    ExternalSystemDefinition,
)


@pytest.mark.asyncio
async def test_direct_external_operation_executor_calls_configured_http_operation():
    seen = {}

    async def _handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("Authorization")
        seen["subject"] = request.headers.get("X-External-Subject")
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={"ok": True, "record_id": "cust-123"},
            headers={"content-type": "application/json"},
        )

    def _client_factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(_handler))

    system = ExternalSystemDefinition(
        system_id=uuid4(),
        scope="organization",
        organization_id=uuid4(),
        system_key="crm",
        display_name="CRM",
        auth_kind="bearer_token",
        config={"base_url": "https://crm.example.test/api"},
        operation_catalog={
            "crm.read": {
                "transport": "http",
                "method": "POST",
                "path": "/customers/{customer_id}",
                "headers": {"X-Operation": "read"},
                "json": {"id": "{customer_id}", "mode": "full"},
            }
        },
        created_by=uuid4(),
        updated_by=uuid4(),
    )
    account = ExternalAccount(
        account_id=uuid4(),
        system_id=system.system_id,
        owner_kind="agent",
        system_agent_id=uuid4(),
        credential_ref={
            "bearer_token": {"value": "account-token"},
            "headers": {"X-External-Subject": {"value": "acct-123"}},
        },
        created_by=uuid4(),
        updated_by=uuid4(),
    )
    grant = ExternalIdentityGrant(
        grant_id=uuid4(),
        workspace_id=uuid4(),
        participant_id=uuid4(),
        system_id=system.system_id,
        account_id=account.account_id,
        system_agent_id=account.system_agent_id,
        created_by=uuid4(),
        updated_by=uuid4(),
    )
    executor = DirectExternalOperationExecutor(client_factory=_client_factory)

    result = await executor.execute(
        resolution=ExternalIdentityResolution(
            system=system,
            grant=grant,
            account=account,
            approved=True,
        ),
        operation_key="crm.read",
        arguments={"customer_id": "cust-123"},
    )

    assert result == {
        "executed": True,
        "transport": "http",
        "operation_key": "crm.read",
        "method": "POST",
        "status_code": 200,
        "ok": True,
        "content_type": "application/json",
        "body": {"ok": True, "record_id": "cust-123"},
    }
    assert seen == {
        "method": "POST",
        "url": "https://crm.example.test/api/customers/cust-123",
        "authorization": "Bearer account-token",
        "subject": "acct-123",
        "body": '{"id":"cust-123","mode":"full"}',
    }
