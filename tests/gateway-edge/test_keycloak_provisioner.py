from __future__ import annotations

import json

import httpx
import pytest

from gateway_edge.iam.keycloak import KeycloakMachineIdentityProvisioner


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload=None, url: str = "http://test") -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.request = httpx.Request("POST", url)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code} error",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, recorder: dict[str, object]) -> None:
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = exc_type
        _ = exc
        _ = tb

    async def post(self, url: str, *, headers=None, json=None, data=None):
        _ = headers
        if url.endswith("/realms/master/protocol/openid-connect/token"):
            return _FakeResponse(payload={"access_token": "admin-token"}, url=url)
        if url.endswith("/admin/realms/open-talon/clients"):
            self._recorder["client_payload"] = json
            return _FakeResponse(status_code=201, payload={}, url=url)
        if url.endswith("/client-secret"):
            return _FakeResponse(payload={"value": "secret-value"}, url=url)
        raise AssertionError(f"Unexpected POST {url}")

    async def get(self, url: str, *, headers=None, params=None):
        _ = headers
        if url.endswith("/admin/realms/open-talon/clients"):
            self._recorder["client_lookup_params"] = params
            return _FakeResponse(payload=[{"id": "internal-id"}], url=url)
        if url.endswith("/admin/realms/open-talon/clients/internal-id/client-secret"):
            return _FakeResponse(payload={"value": "secret-value"}, url=url)
        raise AssertionError(f"Unexpected GET {url}")


@pytest.mark.asyncio
async def test_keycloak_machine_identity_serializes_open_talon_metadata(monkeypatch):
    recorder: dict[str, object] = {}

    def _client_factory(*, timeout: float, trust_env: bool):
        assert timeout == 10.0
        assert trust_env is False
        return _FakeAsyncClient(recorder)

    monkeypatch.setattr("gateway_edge.iam.keycloak.httpx.AsyncClient", _client_factory)

    provisioner = KeycloakMachineIdentityProvisioner(
        base_url="http://127.0.0.1:8081",
        realm="open-talon",
        admin_client_id="admin-cli",
        admin_username="admin",
        admin_password="admin",
    )

    result = await provisioner.create_machine_identity(
        client_id="mcp-live-client",
        display_name="MCP Live Client",
        metadata={"organization_id": "org-123", "system_test": True},
    )

    assert result.client_id == "mcp-live-client"
    assert result.client_secret == "secret-value"
    assert recorder["client_lookup_params"] == {"clientId": "mcp-live-client"}
    assert recorder["client_payload"] == {
        "clientId": "mcp-live-client",
        "name": "MCP Live Client",
        "description": "MCP Live Client",
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": False,
        "bearerOnly": False,
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "attributes": {
            "open_talon_metadata": json.dumps(
                {"organization_id": "org-123", "system_test": True},
                sort_keys=True,
            )
        },
    }
