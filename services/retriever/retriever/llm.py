from __future__ import annotations

from dataclasses import dataclass
import base64
import importlib
from typing import Any

from open_talon_contracts.llm_engines import (
    DEFAULT_LOCAL_OLLAMA_ENGINE_ID,
    LlmEngineDescriptor,
    LlmEngineRegistry,
    LlmEngineSelectionPreferences,
)
from open_talon_contracts.llm_runtime import (
    api_key_references_from_engine_metadata,
    extract_text_response,
    litellm_model_name,
    litellm_payload,
    provider_base_url,
)
from open_talon_contracts.secrets import (
    SecretResolver,
    build_default_secret_resolver,
)

from .config import RetrieverSettings
from .ollama import OllamaVisionProvider


_LITELLM_MODULE: Any | None = None


@dataclass(frozen=True)
class ResolvedVisionEngine:
    descriptor: LlmEngineDescriptor
    model: str


def default_vision_engine_descriptor(settings: RetrieverSettings) -> LlmEngineDescriptor:
    provider = settings.default_vision_provider or "ollama"
    engine_id = settings.default_vision_engine_id or (
        DEFAULT_LOCAL_OLLAMA_ENGINE_ID if provider == "ollama" else provider
    )
    return LlmEngineDescriptor(
        engine_id=engine_id,
        display_name="Retriever Default Vision Engine",
        description="Fallback Retriever visual extraction engine from service config.",
        endpoint_kind="local" if provider == "ollama" else "remote",
        provider=provider,
        url=f"{settings.ollama_base_url.rstrip('/')}/api/generate"
        if provider == "ollama"
        else None,
        default_model=settings.default_vision_model,
        capabilities=["chat", "completion", "vision", "image_input", provider],
        locality="host" if provider == "ollama" else "cloud",
        priority=10,
        enabled=True,
        metadata={"source": "retriever_config"},
    )


def resolve_vision_engine(
    *,
    registry: LlmEngineRegistry,
    settings: RetrieverSettings,
    profile: Any | None,
) -> ResolvedVisionEngine:
    provider_key = profile.vision_provider_key if profile is not None else None
    requested_model = (
        profile.vision_model if profile is not None and profile.vision_model else None
    )
    fallback_model = settings.default_vision_model if not provider_key else None
    preference_model = requested_model or fallback_model
    engine_ids = {engine.engine_id for engine in registry.list()}
    if provider_key:
        preferences = (
            LlmEngineSelectionPreferences(engine_id=provider_key, model=preference_model)
            if provider_key in engine_ids
            else LlmEngineSelectionPreferences(
                provider=provider_key,
                model=preference_model,
                preferred_capabilities=["vision", "image_input"],
            )
        )
    elif settings.default_vision_engine_id:
        preferences = LlmEngineSelectionPreferences(
            engine_id=settings.default_vision_engine_id,
            model=preference_model,
        )
    else:
        preferences = LlmEngineSelectionPreferences(
            provider=settings.default_vision_provider,
            model=preference_model,
            preferred_capabilities=["vision", "image_input"],
        )
    selection = registry.resolve(preferences)
    selected_model = (
        requested_model
        or fallback_model
        or selection.engine.default_model
        or settings.default_vision_model
    )
    if not selected_model:
        raise ValueError(
            f"Vision LLM engine {selection.engine.engine_id!r} does not define a model"
        )
    return ResolvedVisionEngine(descriptor=selection.engine, model=selected_model)


class LlmVisionProvider:
    provider_key = "llm-engine"

    def __init__(
        self,
        *,
        settings: RetrieverSettings,
        secret_resolver: SecretResolver | None = None,
        timeout_seconds: float = 180.0,
    ) -> None:
        self._settings = settings
        self._secret_resolver = secret_resolver or build_default_secret_resolver()
        self._timeout_seconds = timeout_seconds

    async def describe_image(
        self,
        image_bytes: bytes,
        *,
        engine: ResolvedVisionEngine,
        prompt: str,
    ) -> str:
        provider = engine.descriptor.provider or ""
        if provider == "ollama":
            base_url = provider_base_url(
                provider=provider,
                endpoint_url=engine.descriptor.url,
            )
            return await OllamaVisionProvider(
                base_url=base_url or self._settings.ollama_base_url,
            ).describe_image(
                image_bytes,
                model=engine.model,
                prompt=prompt,
            )
        return await self._describe_image_with_litellm(
            image_bytes,
            provider=provider,
            endpoint_url=engine.descriptor.url,
            model=engine.model,
            engine_metadata=engine.descriptor.metadata,
            prompt=prompt,
        )

    async def _describe_image_with_litellm(
        self,
        image_bytes: bytes,
        *,
        provider: str,
        endpoint_url: str | None,
        model: str,
        engine_metadata: dict[str, Any],
        prompt: str,
    ) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        call_kwargs: dict[str, Any] = {
            "model": litellm_model_name(provider=provider, model=model),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{encoded}",
                            },
                        },
                    ],
                }
            ],
            "timeout": self._timeout_seconds,
        }
        api_base = provider_base_url(provider=provider, endpoint_url=endpoint_url)
        if api_base:
            call_kwargs["api_base"] = api_base
        if provider != "ollama":
            call_kwargs["api_key"] = await self._secret_resolver.resolve(
                api_key_references_from_engine_metadata(
                    provider=provider,
                    metadata=engine_metadata,
                ),
                label=f"{provider} API key",
            )
        payload = litellm_payload(await _load_litellm().acompletion(**call_kwargs))
        text = extract_text_response(payload).strip()
        if not text:
            raise RuntimeError(f"{provider} vision response did not include text content")
        return text


def _load_litellm() -> Any:
    global _LITELLM_MODULE
    if _LITELLM_MODULE is None:
        try:
            _LITELLM_MODULE = importlib.import_module("litellm")
        except ImportError as exc:  # pragma: no cover - defensive
            raise RuntimeError(
                "litellm is required for non-Ollama Retriever vision providers. "
                "Reinstall the repo Python environment to pick up the dependency."
            ) from exc
    return _LITELLM_MODULE
