from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ValidatedToken:
    provider_key: str
    issuer: str
    principal_type: Literal["human", "agent"]
    subject: str
    client_id: str | None = None
    display_name: str | None = None
    email: str | None = None
    roles: list[str] = field(default_factory=list)
    platform_admin: bool = False
    claims: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProvisionedMachineIdentity:
    client_id: str
    client_secret: str
    issuer: str
    token_endpoint: str
    external_subject: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class IdentityProvider(Protocol):
    async def validate_token(self, token: str) -> ValidatedToken | None: ...

    def resolve_human_identity(self, validated: ValidatedToken): ...

    def resolve_machine_identity(self, validated: ValidatedToken): ...

    async def issuer_metadata(self) -> dict[str, Any]: ...


class MachineIdentityProvisioner(Protocol):
    async def create_machine_identity(
        self,
        *,
        client_id: str,
        display_name: str,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProvisionedMachineIdentity: ...

    async def rotate_machine_secret(self, *, client_id: str) -> ProvisionedMachineIdentity: ...

    async def enable_machine_identity(self, *, client_id: str) -> None: ...

    async def disable_machine_identity(self, *, client_id: str) -> None: ...

    async def token_endpoint(self) -> str: ...


class SecretStore(Protocol):
    async def store_secret(
        self,
        *,
        path: str,
        values: dict[str, Any],
    ) -> dict[str, Any]: ...
