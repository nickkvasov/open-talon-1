from __future__ import annotations

import asyncio
import logging

from open_talon_contracts.secrets import SecretResolver, secret_references_from_config

from .config import RuntimeWorkerSettings

logger = logging.getLogger(__name__)


async def ensure_forgejo_registry_login(
    settings: RuntimeWorkerSettings,
    *,
    secret_resolver: SecretResolver,
) -> None:
    if not settings.forgejo_registry_validate_on_startup:
        return
    if not settings.forgejo_registry_url or not settings.forgejo_registry_username:
        logger.info("Skipping Forgejo registry login because registry configuration is incomplete")
        return
    password = await secret_resolver.resolve(
        secret_references_from_config(settings.forgejo_registry_password_secret_config),
        label="Forgejo registry password",
        required=False,
    )
    if not password:
        logger.warning("Skipping Forgejo registry login because no registry password could be resolved")
        return
    process = await asyncio.create_subprocess_exec(
        "docker",
        "login",
        settings.forgejo_registry_url,
        "--username",
        settings.forgejo_registry_username,
        "--password-stdin",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(password.encode())
    if process.returncode != 0:
        detail = (stderr or stdout).decode().strip()
        raise RuntimeError(f"Forgejo registry login failed: {detail}")
    logger.info("Validated Forgejo registry login for %s", settings.forgejo_registry_url)


__all__ = ["ensure_forgejo_registry_login"]
