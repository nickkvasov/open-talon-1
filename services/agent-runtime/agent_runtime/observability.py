from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
import os
from time import time_ns
from typing import Any, Protocol

import httpx

from open_talon_contracts.telemetry import PayloadRedactionPolicy, redact_payload

logger = logging.getLogger(__name__)


class RuntimeObservation(Protocol):
    def update(self, **kwargs: Any) -> None: ...


class RuntimeObservability(Protocol):
    def start_span(
        self,
        *,
        name: str,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any: ...

    def start_generation(
        self,
        *,
        name: str,
        model: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any: ...

    def flush(self) -> None: ...


class ObservabilityProvider(RuntimeObservability, Protocol):
    provider_name: str


class _NoopObservation:
    def __enter__(self) -> "_NoopObservation":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def update(self, **kwargs: Any) -> None:
        _ = kwargs


class NoopObservabilityProvider:
    provider_name = "none"

    def start_span(
        self,
        *,
        name: str,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        _ = name
        _ = input
        _ = metadata
        return _NoopObservation()

    def start_generation(
        self,
        *,
        name: str,
        model: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        _ = name
        _ = model
        _ = input
        _ = metadata
        return _NoopObservation()

    def flush(self) -> None:
        return None


class LangfuseRuntimeObserver:
    provider_name = "langfuse"

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @classmethod
    def from_env(cls) -> "LangfuseRuntimeObserver":
        public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        if not public_key or not secret_key:
            return cls()

        base_url = (
            os.getenv("LANGFUSE_BASE_URL")
            or os.getenv("LANGFUSE_HOST")
            or os.getenv("LANGFUSE_PUBLIC_URL")
        )
        if base_url and "LANGFUSE_BASE_URL" not in os.environ:
            os.environ["LANGFUSE_BASE_URL"] = base_url

        try:
            from langfuse import get_client
        except ImportError:
            logger.warning(
                "Langfuse credentials are configured but the Python SDK is not installed. "
                "Install the 'langfuse' package to enable runtime tracing."
            )
            return cls()

        try:
            return cls(get_client())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to initialize Langfuse client: %s", exc)
            return cls()

    def start_span(
        self,
        *,
        name: str,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        if self._client is None:
            return _NoopObservation()
        return self._client.start_as_current_observation(
            name=name,
            as_type="span",
            input=input,
            metadata=metadata,
        )

    def start_generation(
        self,
        *,
        name: str,
        model: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        if self._client is None:
            return _NoopObservation()
        return self._client.start_as_current_observation(
            name=name,
            as_type="generation",
            model=model,
            input=input,
            metadata=metadata,
        )

    def flush(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Langfuse flush failed: %s", exc)


@dataclass
class _BufferedObservation:
    provider: "OtlpHttpObservabilityProvider"
    kind: str
    name: str
    model: str | None
    input_payload: Any | None
    metadata: dict[str, Any] | None
    started_at_unix_ns: int = field(default_factory=time_ns)
    updates: list[dict[str, Any]] = field(default_factory=list)

    def __enter__(self) -> "_BufferedObservation":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        ended_at_unix_ns = time_ns()
        self.provider.record_observation(
            kind=self.kind,
            name=self.name,
            model=self.model,
            input_payload=self.input_payload,
            metadata=self.metadata,
            updates=self.updates,
            started_at_unix_ns=self.started_at_unix_ns,
            ended_at_unix_ns=ended_at_unix_ns,
            error=exc,
        )
        return False

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)


class OtlpHttpObservabilityProvider:
    provider_name = "otlp"

    def __init__(
        self,
        *,
        endpoint: str,
        service_name: str,
        environment: str | None = None,
        timeout_seconds: float = 5.0,
        redaction_policy: PayloadRedactionPolicy | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._service_name = service_name
        self._environment = environment
        self._timeout_seconds = timeout_seconds
        self._redaction_policy = redaction_policy or PayloadRedactionPolicy()
        self._pending: list[dict[str, Any]] = []

    def start_span(
        self,
        *,
        name: str,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return _BufferedObservation(
            provider=self,
            kind="span",
            name=name,
            model=None,
            input_payload=input,
            metadata=metadata,
        )

    def start_generation(
        self,
        *,
        name: str,
        model: str | None = None,
        input: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return _BufferedObservation(
            provider=self,
            kind="generation",
            name=name,
            model=model,
            input_payload=input,
            metadata=metadata,
        )

    def record_observation(
        self,
        *,
        kind: str,
        name: str,
        model: str | None,
        input_payload: Any | None,
        metadata: dict[str, Any] | None,
        updates: list[dict[str, Any]],
        started_at_unix_ns: int,
        ended_at_unix_ns: int,
        error: BaseException | None,
    ) -> None:
        sanitized_input = redact_payload(input_payload, policy=self._redaction_policy)
        sanitized_metadata = redact_payload(metadata or {}, policy=self._redaction_policy)
        sanitized_updates = [
            redact_payload(update, policy=self._redaction_policy)
            for update in updates
        ]
        attributes = {
            "open_talon.observation.kind": kind,
            "open_talon.observation.name": name,
            "open_talon.observation.model": model,
            "open_talon.observation.input": sanitized_input,
            "open_talon.observation.metadata": sanitized_metadata,
            "open_talon.observation.updates": sanitized_updates,
            "open_talon.observation.error": str(error) if error is not None else None,
            "open_talon.service.name": self._service_name,
            "deployment.environment": self._environment,
            "open_talon.exported_at": datetime.now(UTC).isoformat(),
        }
        self._pending.append(
            {
                "resourceSpans": [
                    {
                        "resource": {
                            "attributes": _otlp_attributes(
                                {
                                    "service.name": self._service_name,
                                    "deployment.environment": self._environment,
                                }
                            )
                        },
                        "scopeSpans": [
                            {
                                "scope": {"name": "open-talon-runtime"},
                                "spans": [
                                    {
                                        "name": name,
                                        "kind": 1,
                                        "startTimeUnixNano": str(started_at_unix_ns),
                                        "endTimeUnixNano": str(ended_at_unix_ns),
                                        "attributes": _otlp_attributes(attributes),
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        )

    def flush(self) -> None:
        if not self._pending:
            return
        pending = list(self._pending)
        self._pending.clear()
        try:
            with httpx.Client(timeout=self._timeout_seconds, trust_env=False) as client:
                for payload in pending:
                    response = client.post(self._endpoint, json=payload)
                    response.raise_for_status()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("OTLP observability flush failed: %s", exc)


def build_observability_provider_from_env() -> ObservabilityProvider:
    provider_name = os.getenv("AGENT_RUNTIME_OBSERVABILITY_PROVIDER")
    if provider_name == "none":
        return NoopObservabilityProvider()
    if provider_name == "langfuse":
        return LangfuseRuntimeObserver.from_env()
    if provider_name == "otlp":
        endpoint = os.getenv(
            "AGENT_RUNTIME_OTLP_HTTP_ENDPOINT",
            "http://127.0.0.1:4318/v1/traces",
        )
        return OtlpHttpObservabilityProvider(
            endpoint=endpoint,
            service_name=os.getenv("AGENT_RUNTIME_OTLP_SERVICE_NAME", "agent-runtime"),
            environment=os.getenv("AGENT_RUNTIME_OTLP_ENVIRONMENT"),
            redaction_policy=PayloadRedactionPolicy(
                rich_payloads_enabled=_get_bool(
                    "AGENT_RUNTIME_OBSERVABILITY_RICH_PAYLOADS",
                    True,
                )
            ),
        )
    if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
        return LangfuseRuntimeObserver.from_env()
    return NoopObservabilityProvider()


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _otlp_attributes(values: dict[str, Any]) -> list[dict[str, Any]]:
    attributes: list[dict[str, Any]] = []
    for key, value in values.items():
        if value is None:
            continue
        attributes.append(
            {
                "key": key,
                "value": {
                    "stringValue": json.dumps(value, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else str(value)
                },
            }
        )
    return attributes
