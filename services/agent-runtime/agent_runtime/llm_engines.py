from __future__ import annotations

from dataclasses import dataclass

from open_talon_contracts.llm_engines import (
    LlmEngineDescriptor,
    LlmEngineRegistry,
    LlmEngineSelectionPreferences,
    runtime_preferences_from_definition,
)
from open_talon_contracts.models import AgentEndpoint, AgentExecutionContext


@dataclass(frozen=True)
class ResolvedLlmEngine:
    endpoint: AgentEndpoint
    descriptor: LlmEngineDescriptor | None = None


def build_default_llm_engine_registry() -> LlmEngineRegistry:
    return LlmEngineRegistry.from_env()


def resolve_llm_engine_for_context(
    context: AgentExecutionContext,
    registry: LlmEngineRegistry,
) -> ResolvedLlmEngine:
    endpoint = context.system_agent.endpoint
    preferences = _selection_preferences(context)
    if endpoint.url and endpoint.engine_id is None:
        return ResolvedLlmEngine(endpoint=_apply_preference_defaults(endpoint, preferences))
    if not _should_use_registry(endpoint, preferences):
        return ResolvedLlmEngine(endpoint=_apply_preference_defaults(endpoint, preferences))

    selection = registry.resolve(preferences)
    engine = selection.engine
    model = endpoint.model
    if model is None:
        model = engine.default_model if endpoint.engine_id else (preferences.model or engine.default_model)
    resolved_endpoint = endpoint.model_copy(
        update={
            "kind": engine.endpoint_kind,
            "url": endpoint.url or engine.url,
            "model": model,
            "engine_id": endpoint.engine_id or engine.engine_id,
            "provider": endpoint.provider or preferences.provider or engine.provider,
        }
    )
    return ResolvedLlmEngine(endpoint=resolved_endpoint, descriptor=engine)


def _selection_preferences(
    context: AgentExecutionContext,
) -> LlmEngineSelectionPreferences:
    endpoint = context.system_agent.endpoint
    definition_preferences = runtime_preferences_from_definition(context.system_agent.definition)
    update = {
        "engine_id": endpoint.engine_id or definition_preferences.engine_id,
        "model": endpoint.model or definition_preferences.model,
        "provider": endpoint.provider or definition_preferences.provider,
        "endpoint_kind": endpoint.kind or definition_preferences.endpoint_kind,
        "preferred_engine_ids": definition_preferences.preferred_engine_ids,
        "required_capabilities": definition_preferences.required_capabilities,
        "preferred_capabilities": definition_preferences.preferred_capabilities,
        "preferred_locality": definition_preferences.preferred_locality,
    }
    return definition_preferences.model_copy(update=update)


def _should_use_registry(
    endpoint: AgentEndpoint,
    preferences: LlmEngineSelectionPreferences,
) -> bool:
    if endpoint.engine_id:
        return True
    if preferences.preferred_engine_ids:
        return True
    if preferences.required_capabilities or preferences.preferred_capabilities:
        return True
    if preferences.preferred_locality or preferences.provider:
        return True
    return endpoint.url is None


def _apply_preference_defaults(
    endpoint: AgentEndpoint,
    preferences: LlmEngineSelectionPreferences,
) -> AgentEndpoint:
    return endpoint.model_copy(
        update={
            "model": endpoint.model or preferences.model,
            "provider": endpoint.provider or preferences.provider,
        }
    )
