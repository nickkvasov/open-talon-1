from __future__ import annotations

import logging

from open_talon_contracts.secrets import SecretResolver

from .config import RuntimeWorkerSettings
from .oci_registry import config_from_settings, docker_login, resolve_registry_password

logger = logging.getLogger(__name__)


async def ensure_oci_registry_login(
    settings: RuntimeWorkerSettings,
    *,
    secret_resolver: SecretResolver,
) -> None:
    config = config_from_settings(settings)
    if not config.validate_on_startup:
        return
    if not config.base_url or not config.username:
        logger.info("Skipping OCI registry login because registry configuration is incomplete")
        return
    password = await resolve_registry_password(config, secret_resolver=secret_resolver)
    if not password:
        logger.warning("Skipping OCI registry login because no registry password could be resolved")
        return
    await docker_login(config, password=password)
    logger.info("Validated OCI registry login for %s", config.base_url)


__all__ = ["ensure_oci_registry_login"]
