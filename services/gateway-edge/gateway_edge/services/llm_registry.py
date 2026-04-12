from __future__ import annotations

from open_talon_contracts.llm_engines import (
    LlmEngineDescriptor,
    LlmEngineRegistry,
    llm_engine_descriptor_from_provider_definition,
)

from gateway_edge.services import collaboration as collab_svc


async def list_registered_llm_engines() -> list[LlmEngineDescriptor]:
    managed = [
        llm_engine_descriptor_from_provider_definition(item)
        for item in await collab_svc.collaboration_service.list_llm_providers()
    ]
    return LlmEngineRegistry.merged(LlmEngineRegistry.from_env().list(), managed).list()
