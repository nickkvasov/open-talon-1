from __future__ import annotations

import httpx

from open_talon_contracts.observability import (
    LangfuseRuntimeObserver,
    NoopObservabilityProvider,
    ObservabilityProvider,
    OtlpHttpObservabilityProvider,
    RuntimeObservation,
    RuntimeObservability,
    build_observability_provider_from_env as _build_observability_provider_from_env,
)


def build_observability_provider_from_env() -> ObservabilityProvider:
    return _build_observability_provider_from_env(
        service_name="agent-runtime",
        legacy_env_prefix="AGENT_RUNTIME",
    )


__all__ = [
    "LangfuseRuntimeObserver",
    "NoopObservabilityProvider",
    "ObservabilityProvider",
    "OtlpHttpObservabilityProvider",
    "RuntimeObservation",
    "RuntimeObservability",
    "build_observability_provider_from_env",
    "httpx",
]
