from __future__ import annotations

import asyncio

from open_talon_contracts.oci_registry import OciRegistryConfig
from open_talon_contracts.secrets import SecretResolver, secret_references_from_config

from .config import RuntimeWorkerSettings


def config_from_settings(settings: RuntimeWorkerSettings) -> OciRegistryConfig:
    return OciRegistryConfig(
        base_url=settings.forgejo_registry_url,
        username=settings.forgejo_registry_username,
        password_secret_config=settings.forgejo_registry_password_secret_config,
        repository_prefix=settings.oci_registry_repository_prefix,
        validate_on_startup=settings.forgejo_registry_validate_on_startup,
    )


async def resolve_registry_password(
    config: OciRegistryConfig,
    *,
    secret_resolver: SecretResolver,
) -> str | None:
    if not config.password_secret_config:
        return None
    return await secret_resolver.resolve(
        secret_references_from_config(config.password_secret_config),
        label="OCI registry password",
        required=False,
    )


async def docker_login(
    config: OciRegistryConfig,
    *,
    password: str,
) -> None:
    if not config.base_url or not config.username:
        return
    process = await asyncio.create_subprocess_exec(
        "docker",
        "login",
        config.base_url,
        "--username",
        config.username,
        "--password-stdin",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(password.encode())
    if process.returncode != 0:
        detail = (stderr or stdout).decode().strip()
        raise RuntimeError(f"OCI registry login failed: {detail}")


__all__ = [
    "config_from_settings",
    "docker_login",
    "resolve_registry_password",
]
