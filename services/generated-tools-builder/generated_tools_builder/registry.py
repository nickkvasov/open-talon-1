from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from open_talon_contracts.oci_registry import OciRegistryConfig
from open_talon_contracts.secrets import SecretResolver, secret_references_from_config


def registry_secret_config_from_env() -> dict[str, Any]:
    raw = os.getenv("OPEN_TALON_OCI_REGISTRY_PASSWORD_SECRET_CONFIG")
    if raw and raw.strip():
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    raw = os.getenv("OPEN_TALON_FORGEJO_REGISTRY_PASSWORD_SECRET_CONFIG")
    if raw and raw.strip():
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    env_name = str(os.getenv("OPEN_TALON_OCI_REGISTRY_PASSWORD_ENV") or "").strip()
    if env_name:
        return {"env": env_name}
    env_name = str(os.getenv("OPEN_TALON_FORGEJO_REGISTRY_PASSWORD_ENV") or "").strip()
    return {"env": env_name or "OPEN_TALON_OCI_REGISTRY_PASSWORD"}


def registry_config_from_env() -> OciRegistryConfig:
    return OciRegistryConfig(
        base_url=str(
            os.getenv("OPEN_TALON_OCI_REGISTRY_URL")
            or os.getenv("OPEN_TALON_FORGEJO_REGISTRY_URL")
            or "localhost:3001"
        ).strip()
        or None,
        username=str(
            os.getenv("OPEN_TALON_OCI_REGISTRY_USERNAME")
            or os.getenv("OPEN_TALON_FORGEJO_REGISTRY_USERNAME")
            or "forgejo"
        ).strip()
        or None,
        password_secret_config=registry_secret_config_from_env(),
        repository_prefix=str(
            os.getenv("OPEN_TALON_OCI_REGISTRY_REPOSITORY_PREFIX") or "forgejo/generated-tools"
        ).strip("/")
        or None,
        validate_on_startup=True,
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
    "docker_login",
    "registry_config_from_env",
    "registry_secret_config_from_env",
    "resolve_registry_password",
]
