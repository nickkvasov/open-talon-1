from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

import httpx

from gateway_edge.models import (
    LlmProviderDefinition,
    LlmProviderHealthCheck,
    LlmProviderHealthReport,
)
from open_talon_contracts.local_env import load_repo_local_env

logger = logging.getLogger(__name__)


async def check_llm_provider_health(
    provider: LlmProviderDefinition,
    *,
    timeout_seconds: float = 5.0,
) -> LlmProviderHealthReport:
    load_repo_local_env()
    checks: list[LlmProviderHealthCheck] = []
    secret_value: str | None = None

    secret_check, secret_value = await _check_secret(provider)
    checks.append(secret_check)
    checks.append(await _check_url(provider))
    checks.append(
        await _check_connectivity(
            provider,
            timeout_seconds=timeout_seconds,
            secret_value=secret_value,
        )
    )

    if any(check.status == "fail" for check in checks):
        status = "unhealthy"
    elif any(check.status == "warn" for check in checks):
        status = "degraded"
    else:
        status = "healthy"

    return LlmProviderHealthReport(
        provider_id=provider.provider_id,
        engine_id=provider.engine_id,
        status=status,
        checks=checks,
        metadata={
            "provider": provider.provider,
            "endpoint_kind": provider.endpoint_kind,
        },
    )


async def _check_secret(
    provider: LlmProviderDefinition,
) -> tuple[LlmProviderHealthCheck, str | None]:
    config = provider.secret_config if isinstance(provider.secret_config, dict) else {}
    if not config:
        return (
            LlmProviderHealthCheck(
                name="secret",
                status="warn",
                detail="No secret reference configured; credential validation skipped.",
            ),
            None,
        )

    env_config = config.get("env")
    if isinstance(env_config, str):
        env_name = env_config
    elif isinstance(env_config, dict):
        env_name = env_config.get("name")
    else:
        env_name = None
    if isinstance(env_name, str) and env_name.strip():
        value = os.getenv(env_name.strip(), "").strip()
        if value:
            return (
                LlmProviderHealthCheck(
                    name="secret",
                    status="ok",
                    detail=f"Resolved API credential from env var {env_name.strip()}.",
                    metadata={"source": "env", "name": env_name.strip()},
                ),
                value,
            )

    openbao_config = config.get("openbao")
    if isinstance(openbao_config, dict):
        value = await _resolve_openbao_secret(openbao_config)
        if value:
            path = str(openbao_config.get("path") or "").strip()
            field_name = str(
                openbao_config.get("field") or openbao_config.get("field_name") or "value"
            ).strip()
            return (
                LlmProviderHealthCheck(
                    name="secret",
                    status="ok",
                    detail=f"Resolved API credential from OpenBao path {path}.",
                    metadata={"source": "openbao", "path": path, "field": field_name},
                ),
                value,
            )

    return (
        LlmProviderHealthCheck(
            name="secret",
            status="fail",
            detail="Configured secret references could not be resolved.",
        ),
        None,
    )


async def _check_url(provider: LlmProviderDefinition) -> LlmProviderHealthCheck:
    if provider.endpoint_kind == "system" and not provider.url:
        return LlmProviderHealthCheck(
            name="url",
            status="ok",
            detail="System provider does not require an external URL.",
        )
    if not provider.url:
        return LlmProviderHealthCheck(
            name="url",
            status="fail",
            detail="Provider URL is missing.",
        )
    parsed = urlparse(provider.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return LlmProviderHealthCheck(
            name="url",
            status="fail",
            detail=f"Provider URL is invalid: {provider.url}",
        )
    return LlmProviderHealthCheck(
        name="url",
        status="ok",
        detail=f"Provider URL parsed successfully: {provider.url}",
        metadata={"scheme": parsed.scheme, "host": parsed.netloc},
    )


async def _check_connectivity(
    provider: LlmProviderDefinition,
    *,
    timeout_seconds: float,
    secret_value: str | None,
) -> LlmProviderHealthCheck:
    if not provider.url:
        return LlmProviderHealthCheck(
            name="connectivity",
            status="warn",
            detail="Connectivity probe skipped because no URL is configured.",
        )

    headers = _provider_probe_headers(provider, secret_value)
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, trust_env=False) as client:
            response = await client.get(
                provider.url,
                headers=headers,
                follow_redirects=False,
            )
    except Exception as exc:
        return LlmProviderHealthCheck(
            name="connectivity",
            status="fail",
            detail=f"Connectivity probe failed: {exc}",
        )

    status_code = response.status_code
    if 200 <= status_code < 400:
        status = "ok"
        detail = f"Endpoint responded successfully with HTTP {status_code}."
    elif status_code in {404, 405}:
        status = "ok"
        detail = (
            f"Endpoint responded with HTTP {status_code}; probe reached the provider, "
            "but the URL does not support GET."
        )
    elif status_code in {401, 403}:
        status = "warn"
        detail = (
            f"Endpoint responded with HTTP {status_code}; provider is reachable, "
            "but credential validity was not confirmed."
        )
    else:
        status = "warn"
        detail = f"Endpoint responded with HTTP {status_code}."
    return LlmProviderHealthCheck(
        name="connectivity",
        status=status,
        detail=detail,
        metadata={"status_code": status_code},
    )


def _provider_probe_headers(
    provider: LlmProviderDefinition,
    secret_value: str | None,
) -> dict[str, str]:
    if not secret_value:
        return {}
    normalized_provider = provider.provider.strip().lower()
    if normalized_provider in {"openai", "groq"}:
        return {"Authorization": f"Bearer {secret_value}"}
    if normalized_provider == "anthropic":
        return {
            "x-api-key": secret_value,
            "anthropic-version": "2023-06-01",
        }
    return {"Authorization": f"Bearer {secret_value}"}


async def _resolve_openbao_secret(config: dict) -> str | None:
    token = (
        os.getenv("OPEN_TALON_OPENBAO_TOKEN")
        or os.getenv("BAO_ROOT_TOKEN")
        or ""
    ).strip()
    if not token:
        return None
    address = (
        os.getenv("OPEN_TALON_OPENBAO_ADDRESS")
        or os.getenv("OPENBAO_ADDRESS")
        or "http://localhost:8200"
    ).rstrip("/")
    mount = str(config.get("mount") or os.getenv("OPEN_TALON_OPENBAO_KV_MOUNT") or "secret").strip("/")
    path = str(config.get("path") or "").strip().strip("/")
    field_name = str(config.get("field") or config.get("field_name") or "value").strip()
    if not path:
        return None
    url = f"{address}/v1/{mount}/data/{path}"
    try:
        async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
            response = await client.get(url, headers={"X-Vault-Token": token})
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.debug("OpenBao secret resolution failed for %s: %s", path, exc)
        return None
    value = (
        payload.get("data", {})
        .get("data", {})
        .get(field_name)
    )
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)
