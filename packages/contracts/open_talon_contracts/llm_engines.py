from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

LlmEngineLocality = Literal["host", "lan", "cloud", "system"]
LlmEngineEndpointKind = Literal["local", "system", "remote"]

DEFAULT_LOCAL_OLLAMA_ENGINE_ID = "local-ollama"
DEFAULT_LOCAL_OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_OPENAI_ENGINE_ID = "openai-responses"
DEFAULT_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"


class LlmEngineDescriptor(BaseModel):
    engine_id: str
    display_name: str
    description: str
    endpoint_kind: LlmEngineEndpointKind = "remote"
    provider: str | None = None
    url: str | None = None
    default_model: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    locality: LlmEngineLocality = "cloud"
    priority: int = 100
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class LlmEngineSelectionPreferences(BaseModel):
    engine_id: str | None = None
    preferred_engine_ids: list[str] = Field(default_factory=list)
    model: str | None = None
    provider: str | None = None
    endpoint_kind: LlmEngineEndpointKind | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    preferred_capabilities: list[str] = Field(default_factory=list)
    preferred_locality: LlmEngineLocality | None = None


class LlmEngineSelection(BaseModel):
    engine: LlmEngineDescriptor
    score: int = 0
    reasons: list[str] = Field(default_factory=list)


class LlmEngineRegistry:
    def __init__(self, engines: list[LlmEngineDescriptor] | None = None) -> None:
        self._engines: dict[str, LlmEngineDescriptor] = {}
        for engine in engines or []:
            self.register(engine)

    def register(self, engine: LlmEngineDescriptor) -> None:
        self._engines[engine.engine_id] = engine

    def list(self) -> list[LlmEngineDescriptor]:
        return sorted(
            (engine for engine in self._engines.values() if engine.enabled),
            key=lambda engine: (-engine.priority, engine.display_name.lower(), engine.engine_id),
        )

    def resolve(
        self,
        preferences: LlmEngineSelectionPreferences,
    ) -> LlmEngineSelection:
        engines = self.list()
        if preferences.engine_id:
            try:
                engine = self._engines[preferences.engine_id]
            except KeyError as exc:
                raise ValueError(
                    f"No LLM engine registered for {preferences.engine_id!r}"
                ) from exc
            if not engine.enabled:
                raise ValueError(f"LLM engine {preferences.engine_id!r} is disabled")
            return LlmEngineSelection(
                engine=engine,
                score=10_000,
                reasons=[f"engine_id={preferences.engine_id}"],
            )

        ranked: list[LlmEngineSelection] = []
        required_capabilities = set(preferences.required_capabilities)
        preferred_capabilities = set(preferences.preferred_capabilities)
        preferred_engine_ids = set(preferences.preferred_engine_ids)

        for engine in engines:
            engine_capabilities = set(engine.capabilities)
            if required_capabilities and not required_capabilities.issubset(engine_capabilities):
                continue
            if preferences.endpoint_kind and engine.endpoint_kind != preferences.endpoint_kind:
                continue
            if preferences.provider and engine.provider and engine.provider != preferences.provider:
                continue

            score = engine.priority
            reasons: list[str] = []
            if engine.engine_id in preferred_engine_ids:
                score += 500
                reasons.append(f"preferred_engine_id={engine.engine_id}")
            if preferences.provider and engine.provider == preferences.provider:
                score += 200
                reasons.append(f"provider={preferences.provider}")
            if preferences.preferred_locality and engine.locality == preferences.preferred_locality:
                score += 100
                reasons.append(f"preferred_locality={preferences.preferred_locality}")
            if preferences.model and engine.default_model == preferences.model:
                score += 75
                reasons.append(f"model={preferences.model}")
            matched_capabilities = sorted(preferred_capabilities.intersection(engine_capabilities))
            if matched_capabilities:
                score += 25 * len(matched_capabilities)
                reasons.append(
                    "preferred_capabilities=" + ",".join(matched_capabilities)
                )
            ranked.append(LlmEngineSelection(engine=engine, score=score, reasons=reasons))

        if not ranked:
            raise ValueError("No registered LLM engine satisfies the requested preferences")

        ranked.sort(
            key=lambda item: (
                -item.score,
                item.engine.display_name.lower(),
                item.engine.engine_id,
            )
        )
        return ranked[0]

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> "LlmEngineRegistry":
        _ = environ
        return cls([])

    @classmethod
    def merged(
        cls,
        *engine_lists: list[LlmEngineDescriptor],
    ) -> "LlmEngineRegistry":
        merged: list[LlmEngineDescriptor] = []
        for engine_list in engine_lists:
            merged.extend(engine_list)
        return cls(merged)


def runtime_preferences_from_definition(
    definition: dict[str, Any] | None,
) -> LlmEngineSelectionPreferences:
    runtime = (definition or {}).get("runtime")
    if runtime is None:
        return LlmEngineSelectionPreferences()
    if isinstance(runtime, str):
        return LlmEngineSelectionPreferences(provider=runtime)
    if not isinstance(runtime, dict):
        return LlmEngineSelectionPreferences()

    payload = dict(runtime)
    provider = payload.get("provider")
    preferred_engine_ids = list(payload.get("preferred_engine_ids") or [])
    preferred_capabilities = list(payload.get("preferred_capabilities") or [])
    if provider == "ollama" and "engine_id" not in payload:
        preferred_engine_ids.append(DEFAULT_LOCAL_OLLAMA_ENGINE_ID)
    elif provider and provider not in preferred_capabilities:
        preferred_capabilities.append(provider)
    payload["preferred_engine_ids"] = preferred_engine_ids
    payload["preferred_capabilities"] = preferred_capabilities
    return LlmEngineSelectionPreferences.model_validate(payload)


def llm_engine_descriptor_from_provider_definition(
    provider_definition: Any,
) -> LlmEngineDescriptor:
    secret_config = dict(provider_definition.secret_config)
    return LlmEngineDescriptor(
        engine_id=provider_definition.engine_id,
        display_name=provider_definition.display_name,
        description=provider_definition.description,
        endpoint_kind=provider_definition.endpoint_kind,
        provider=provider_definition.provider,
        url=provider_definition.url,
        default_model=provider_definition.default_model,
        capabilities=list(provider_definition.capabilities),
        locality=provider_definition.locality,
        priority=provider_definition.priority,
        enabled=provider_definition.enabled,
        metadata={
            **dict(provider_definition.metadata),
            "secret_config": secret_config,
            "api_key_secret": secret_config,
            "managed_provider_id": str(provider_definition.provider_id),
            "managed": True,
        },
    )
