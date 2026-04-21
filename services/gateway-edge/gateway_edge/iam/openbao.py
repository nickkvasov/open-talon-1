from __future__ import annotations

from typing import Any

import httpx

from gateway_edge.config import settings
from gateway_edge.iam.provider_interfaces import SecretStore


class OpenBaoSecretStore(SecretStore):
    def __init__(
        self,
        *,
        address: str,
        token: str,
        mount: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._address = address.rstrip("/")
        self._token = token
        self._mount = mount.strip("/")
        self._timeout_seconds = timeout_seconds

    async def store_secret(
        self,
        *,
        path: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_path = path.strip().strip("/")
        async with httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False) as client:
            response = await client.post(
                f"{self._address}/v1/{self._mount}/data/{normalized_path}",
                headers={"X-Vault-Token": self._token},
                json={"data": values},
            )
            response.raise_for_status()
        return {
            "openbao": {
                "mount": self._mount,
                "path": normalized_path,
            }
        }


def build_secret_store() -> SecretStore:
    return OpenBaoSecretStore(
        address=settings.openbao_address,
        token=settings.openbao_admin_token,
        mount=settings.openbao_kv_mount,
    )
