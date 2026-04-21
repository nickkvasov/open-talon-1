from __future__ import annotations

from typing import Any
import httpx

from gateway_edge.config import settings
from gateway_edge.iam.provider_interfaces import (
    MachineIdentityProvisioner,
    ProvisionedMachineIdentity,
)


def _realm_admin_base() -> str:
    return (
        f"{settings.keycloak_base_url.rstrip('/')}"
        f"/admin/realms/{settings.keycloak_realm}"
    )


def _token_url() -> str:
    issuer = settings.oidc_issuer_url.rstrip("/")
    return f"{issuer}/protocol/openid-connect/token"


class KeycloakMachineIdentityProvisioner(MachineIdentityProvisioner):
    def __init__(
        self,
        *,
        base_url: str,
        realm: str,
        admin_client_id: str,
        admin_username: str,
        admin_password: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._realm = realm
        self._admin_client_id = admin_client_id
        self._admin_username = admin_username
        self._admin_password = admin_password
        self._timeout_seconds = timeout_seconds

    async def create_machine_identity(
        self,
        *,
        client_id: str,
        display_name: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProvisionedMachineIdentity:
        token = await self._admin_token()
        payload = {
            "clientId": client_id,
            "name": display_name,
            "description": description or display_name,
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "bearerOnly": False,
            "serviceAccountsEnabled": True,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "attributes": {
                "open_talon_metadata": (metadata or {}),
            },
        }
        async with httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False) as client:
            response = await client.post(
                f"{_realm_admin_base()}/clients",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            if response.status_code not in {201, 204, 409}:
                response.raise_for_status()
            internal_id = await self._client_internal_id(client, token=token, client_id=client_id)
            secret_response = await client.get(
                f"{_realm_admin_base()}/clients/{internal_id}/client-secret",
                headers={"Authorization": f"Bearer {token}"},
            )
            secret_response.raise_for_status()
            secret_value = secret_response.json().get("value")
        if not isinstance(secret_value, str) or not secret_value:
            raise ValueError(f"Keycloak did not return a client secret for {client_id}")
        return ProvisionedMachineIdentity(
            client_id=client_id,
            client_secret=secret_value,
            issuer=settings.oidc_issuer_url.rstrip("/"),
            token_endpoint=_token_url(),
        )

    async def rotate_machine_secret(self, *, client_id: str) -> ProvisionedMachineIdentity:
        token = await self._admin_token()
        async with httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False) as client:
            internal_id = await self._client_internal_id(client, token=token, client_id=client_id)
            response = await client.post(
                f"{_realm_admin_base()}/clients/{internal_id}/client-secret",
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            secret_value = response.json().get("value")
        if not isinstance(secret_value, str) or not secret_value:
            raise ValueError(f"Keycloak did not rotate a client secret for {client_id}")
        return ProvisionedMachineIdentity(
            client_id=client_id,
            client_secret=secret_value,
            issuer=settings.oidc_issuer_url.rstrip("/"),
            token_endpoint=_token_url(),
        )

    async def disable_machine_identity(self, *, client_id: str) -> None:
        await self._set_client_enabled(client_id=client_id, enabled=False)

    async def enable_machine_identity(self, *, client_id: str) -> None:
        await self._set_client_enabled(client_id=client_id, enabled=True)

    async def _set_client_enabled(self, *, client_id: str, enabled: bool) -> None:
        token = await self._admin_token()
        async with httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False) as client:
            internal_id = await self._client_internal_id(client, token=token, client_id=client_id)
            existing_response = await client.get(
                f"{_realm_admin_base()}/clients/{internal_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            existing_response.raise_for_status()
            existing = existing_response.json()
            existing["enabled"] = enabled
            response = await client.put(
                f"{_realm_admin_base()}/clients/{internal_id}",
                headers={"Authorization": f"Bearer {token}"},
                json=existing,
            )
            response.raise_for_status()

    async def token_endpoint(self) -> str:
        return _token_url()

    async def _admin_token(self) -> str:
        token_url = (
            f"{self._base_url}/realms/master/protocol/openid-connect/token"
        )
        async with httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False) as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "password",
                    "client_id": self._admin_client_id,
                    "username": self._admin_username,
                    "password": self._admin_password,
                },
            )
            response.raise_for_status()
            payload = response.json()
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("Keycloak admin token response did not include access_token")
        return access_token

    async def _client_internal_id(
        self,
        client: httpx.AsyncClient,
        *,
        token: str,
        client_id: str,
    ) -> str:
        response = await client.get(
            f"{_realm_admin_base()}/clients",
            headers={"Authorization": f"Bearer {token}"},
            params={"clientId": client_id},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            raise KeyError(f"Keycloak client {client_id!r} not found")
        internal_id = payload[0].get("id")
        if not isinstance(internal_id, str) or not internal_id:
            raise ValueError(f"Keycloak client {client_id!r} is missing an internal id")
        return internal_id


def build_machine_identity_provisioner() -> MachineIdentityProvisioner:
    return KeycloakMachineIdentityProvisioner(
        base_url=settings.keycloak_base_url,
        realm=settings.keycloak_realm,
        admin_client_id=settings.keycloak_admin_client_id,
        admin_username=settings.keycloak_admin_username,
        admin_password=settings.keycloak_admin_password,
    )
