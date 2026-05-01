from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import urljoin

import httpx
from open_talon_contracts.models import ExternalIdentityResolution
from open_talon_contracts.secrets import (
    SecretResolver,
    build_default_secret_resolver,
    secret_references_from_config,
)


_TEMPLATE_VAR = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class DirectExternalOperationExecutor:
    def __init__(
        self,
        *,
        secret_resolver: SecretResolver | None = None,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._secret_resolver = secret_resolver or build_default_secret_resolver()
        self._client_factory = client_factory

    async def execute(
        self,
        *,
        resolution: ExternalIdentityResolution,
        operation_key: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        operation = self._operation_definition(
            resolution.system.operation_catalog,
            operation_key,
        )
        if operation is None:
            return None
        transport = str(operation.get("transport") or operation.get("kind") or "http")
        if transport != "http":
            raise ValueError(
                f"Unsupported direct external operation transport {transport!r}"
            )
        method = str(operation.get("method") or "POST").upper()
        url = self._operation_url(resolution, operation, arguments)
        headers = await self._operation_headers(resolution, operation)
        params = self._render_value(operation.get("params") or {}, arguments)
        json_body = self._operation_json_body(operation, arguments, method=method)
        timeout_seconds = float(operation.get("timeout_seconds") or 30.0)
        client = (
            self._client_factory()
            if self._client_factory is not None
            else httpx.AsyncClient(timeout=timeout_seconds, trust_env=False)
        )
        try:
            async with client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params if isinstance(params, dict) else None,
                    json=json_body,
                )
        except httpx.RequestError as exc:
            return {
                "executed": True,
                "transport": "http",
                "operation_key": operation_key,
                "method": method,
                "status_code": None,
                "ok": False,
                "error": str(exc),
            }
        return {
            "executed": True,
            "transport": "http",
            "operation_key": operation_key,
            "method": method,
            "status_code": response.status_code,
            "ok": response.is_success,
            "content_type": response.headers.get("content-type"),
            "body": self._response_body(response),
        }

    @staticmethod
    def _operation_definition(
        operation_catalog: dict[str, Any],
        operation_key: str,
    ) -> dict[str, Any] | None:
        operation = operation_catalog.get(operation_key)
        if isinstance(operation, dict):
            return operation
        operations = operation_catalog.get("operations")
        if isinstance(operations, dict):
            operation = operations.get(operation_key)
            if isinstance(operation, dict):
                return operation
        return None

    def _operation_url(
        self,
        resolution: ExternalIdentityResolution,
        operation: dict[str, Any],
        arguments: dict[str, Any],
    ) -> str:
        raw_url = operation.get("url")
        if isinstance(raw_url, str) and raw_url:
            return self._render_template(raw_url, arguments)
        base_url = resolution.system.config.get("base_url") or operation.get("base_url")
        path = operation.get("path")
        if not isinstance(base_url, str) or not base_url:
            raise ValueError("HTTP external operation requires url or system.config.base_url")
        if not isinstance(path, str):
            path = ""
        return urljoin(
            base_url.rstrip("/") + "/",
            self._render_template(path.lstrip("/"), arguments),
        )

    async def _operation_headers(
        self,
        resolution: ExternalIdentityResolution,
        operation: dict[str, Any],
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        configured_headers = operation.get("headers")
        if isinstance(configured_headers, dict):
            for key, value in configured_headers.items():
                if isinstance(key, str) and isinstance(value, str):
                    headers[key] = value
        credential_config = (
            resolution.account.credential_ref
            if resolution.account is not None
            else resolution.system.secret_config
        )
        auth_config = operation.get("auth") if isinstance(operation.get("auth"), dict) else {}
        credential_headers = credential_config.get("headers")
        if isinstance(credential_headers, dict):
            for key, value in credential_headers.items():
                if isinstance(key, str):
                    resolved = await self._resolve_secret_value(
                        value,
                        label=f"external operation header {key}",
                        required=False,
                    )
                    if resolved:
                        headers[key] = resolved
        token = await self._resolve_secret_value(
            credential_config.get("bearer_token") or credential_config.get("token"),
            label="external operation bearer token",
            required=False,
        )
        if token:
            header_name = str(auth_config.get("header_name") or "Authorization")
            scheme = str(auth_config.get("scheme") or "Bearer")
            headers[header_name] = token if not scheme else f"{scheme} {token}"
        api_key = await self._resolve_secret_value(
            credential_config.get("api_key"),
            label="external operation API key",
            required=False,
        )
        if api_key:
            header_name = str(auth_config.get("header_name") or "X-API-Key")
            headers[header_name] = api_key
        return headers

    def _operation_json_body(
        self,
        operation: dict[str, Any],
        arguments: dict[str, Any],
        *,
        method: str,
    ) -> Any:
        if "json" in operation:
            return self._render_value(operation["json"], arguments)
        if "body" in operation:
            return self._render_value(operation["body"], arguments)
        if method in {"POST", "PUT", "PATCH"}:
            return arguments
        return None

    async def _resolve_secret_value(
        self,
        value: Any,
        *,
        label: str,
        required: bool = True,
    ) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            raw = value.get("value")
            if isinstance(raw, str):
                return raw
            references = secret_references_from_config(value)
            if references:
                return await self._secret_resolver.resolve(
                    references,
                    label=label,
                    required=required,
                )
        if required:
            raise ValueError(f"Unable to resolve {label}")
        return None

    def _render_value(self, value: Any, arguments: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self._render_template(value, arguments)
        if isinstance(value, dict):
            return {
                key: self._render_value(item, arguments)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._render_value(item, arguments) for item in value]
        return value

    @staticmethod
    def _render_template(template: str, arguments: dict[str, Any]) -> str:
        def _replace(match: re.Match[str]) -> str:
            key = match.group(1)
            return str(arguments.get(key, match.group(0)))

        return _TEMPLATE_VAR.sub(_replace, template)

    @staticmethod
    def _response_body(response: httpx.Response) -> Any:
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                return response.json()
            except ValueError:
                return None
        return response.text


direct_external_operation_executor = DirectExternalOperationExecutor()
