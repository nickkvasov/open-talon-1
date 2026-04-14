from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Protocol

import httpx

from open_talon_contracts.local_env import load_repo_local_env


@dataclass(frozen=True)
class SecretReference:
    provider: str
    name: str | None = None
    mount: str | None = None
    path: str | None = None
    field_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SecretProvider(Protocol):
    kind: str

    async def get_secret(self, reference: SecretReference) -> str | None: ...


class EnvironmentSecretProvider:
    kind = "env"

    async def get_secret(self, reference: SecretReference) -> str | None:
        if reference.provider != self.kind or not reference.name:
            return None
        value = os.getenv(reference.name, "").strip()
        return value or None


class OpenBaoSecretProvider:
    kind = "openbao"

    def __init__(
        self,
        *,
        address: str,
        token: str | None,
        timeout_seconds: float = 5.0,
        default_mount: str = "secret",
    ) -> None:
        self._address = address.rstrip("/")
        self._token = token.strip() if token else None
        self._timeout_seconds = timeout_seconds
        self._default_mount = default_mount

    async def get_secret(self, reference: SecretReference) -> str | None:
        if reference.provider != self.kind or not self._token:
            return None
        mount = reference.mount or self._default_mount
        path = (reference.path or "").strip().strip("/")
        field_name = reference.field_name or "value"
        if not path:
            raise ValueError("OpenBao secret reference is missing a KV path")
        url = f"{self._address}/v1/{mount}/data/{path}"
        async with httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False) as client:
            response = await client.get(url, headers={"X-Vault-Token": self._token})
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data")
        if not isinstance(data, dict):
            return None
        versioned = data.get("data")
        if not isinstance(versioned, dict):
            return None
        value = versioned.get(field_name)
        if value is None:
            return None
        return value if isinstance(value, str) else str(value)


class SecretResolver:
    def __init__(self, providers: list[SecretProvider] | None = None) -> None:
        self._providers = {provider.kind: provider for provider in providers or []}

    async def resolve(
        self,
        references: list[SecretReference],
        *,
        label: str,
        required: bool = True,
    ) -> str | None:
        failures: list[str] = []
        for reference in references:
            provider = self._providers.get(reference.provider)
            if provider is None:
                continue
            try:
                value = await provider.get_secret(reference)
            except Exception as exc:
                failures.append(f"{reference.provider}: {exc}")
                continue
            if value:
                return value
        if required:
            detail = f" ({'; '.join(failures)})" if failures else ""
            raise ValueError(f"Unable to resolve {label}{detail}")
        return None


def build_default_secret_resolver() -> SecretResolver:
    load_repo_local_env()
    order = [
        item.strip()
        for item in os.getenv("OPEN_TALON_SECRET_PROVIDER_ORDER", "env,openbao").split(",")
        if item.strip()
    ]
    providers: list[SecretProvider] = []
    for provider_name in order:
        if provider_name == "env":
            providers.append(EnvironmentSecretProvider())
        elif provider_name == "openbao":
            providers.append(
                OpenBaoSecretProvider(
                    address=(
                        os.getenv("OPEN_TALON_OPENBAO_ADDRESS")
                        or os.getenv("OPENBAO_ADDRESS")
                        or "http://localhost:8200"
                    ),
                    token=(
                        os.getenv("OPEN_TALON_OPENBAO_TOKEN")
                        or os.getenv("BAO_ROOT_TOKEN")
                    ),
                    timeout_seconds=float(
                        os.getenv("OPEN_TALON_SECRET_REQUEST_TIMEOUT_SECONDS", "5.0")
                    ),
                    default_mount=os.getenv("OPEN_TALON_OPENBAO_KV_MOUNT", "secret"),
                )
            )
    return SecretResolver(providers)


def secret_references_from_config(config: Any) -> list[SecretReference]:
    if not isinstance(config, dict):
        return []
    references: list[SecretReference] = []
    env_config = config.get("env")
    if isinstance(env_config, str):
        references.append(SecretReference(provider="env", name=env_config))
    elif isinstance(env_config, dict):
        references.append(
            SecretReference(
                provider="env",
                name=env_config.get("name"),
                metadata=dict(env_config),
            )
        )
    openbao_config = config.get("openbao")
    if isinstance(openbao_config, dict):
        references.append(
            SecretReference(
                provider="openbao",
                mount=openbao_config.get("mount"),
                path=openbao_config.get("path"),
                field_name=openbao_config.get("field") or openbao_config.get("field_name"),
                metadata=dict(openbao_config),
            )
        )
    return references
