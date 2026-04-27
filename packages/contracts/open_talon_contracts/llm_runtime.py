from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse, urlunparse

from .secrets import SecretReference, secret_references_from_config

LITELLM_PREFIXED_PROVIDERS = {
    "anthropic",
    "cohere",
    "deepseek",
    "gemini",
    "groq",
    "mistral",
    "ollama",
    "openai",
    "xai",
}


def litellm_model_name(*, provider: str, model: str) -> str:
    if "/" in model:
        return model
    if provider in LITELLM_PREFIXED_PROVIDERS:
        return f"{provider}/{model}"
    return model


def provider_base_url(
    *,
    provider: str,
    endpoint_url: str | None,
) -> str | None:
    if not endpoint_url:
        return None
    parsed = urlparse(endpoint_url)
    if not parsed.scheme or not parsed.netloc:
        return endpoint_url.rstrip("/")
    path = parsed.path.rstrip("/")
    suffixes_by_provider = {
        "anthropic": ("/v1/messages", "/messages"),
        "openai": ("/responses", "/chat/completions", "/completions"),
        "ollama": ("/api/generate", "/api/chat"),
    }
    for suffix in suffixes_by_provider.get(provider, ()):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    normalized = urlunparse(
        parsed._replace(path=path, params="", query="", fragment="")
    )
    return normalized.rstrip("/")


def api_key_references_from_engine_metadata(
    *,
    provider: str,
    metadata: dict[str, Any] | None,
) -> list[SecretReference]:
    metadata = metadata or {}
    references: list[SecretReference] = []
    references.extend(secret_references_from_config(metadata.get("api_key_secret")))
    references.extend(secret_references_from_config(metadata.get("secret_config")))
    env_name = metadata.get("auth_env_var")
    if isinstance(env_name, str) and env_name:
        references.append(SecretReference(provider="env", name=env_name))
    if not references:
        normalized_provider = provider.upper().replace("-", "_")
        references.append(
            SecretReference(provider="env", name=f"{normalized_provider}_API_KEY")
        )
        references.append(
            SecretReference(
                provider="openbao",
                mount=os.getenv("OPEN_TALON_OPENBAO_KV_MOUNT", "secret"),
                path=os.getenv(
                    f"OPEN_TALON_{normalized_provider}_OPENBAO_PATH",
                    f"open-talon/llm/{provider}",
                ),
                field_name=os.getenv(
                    f"OPEN_TALON_{normalized_provider}_OPENBAO_FIELD",
                    "api_key",
                ),
            )
        )
    return dedupe_secret_references(references)


def dedupe_secret_references(
    references: list[SecretReference],
) -> list[SecretReference]:
    seen: set[tuple[str, str | None, str | None, str | None, str | None]] = set()
    unique: list[SecretReference] = []
    for reference in references:
        key = (
            reference.provider,
            reference.name,
            reference.mount,
            reference.path,
            reference.field_name,
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(reference)
    return unique


def litellm_payload(response: Any) -> Any:
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if hasattr(response, "dict"):
        return response.dict()
    return response


def extract_text_response(payload: Any) -> str:
    if isinstance(payload, dict):
        if isinstance(payload.get("response"), str):
            return payload["response"]
        if isinstance(payload.get("message"), str):
            return payload["message"]
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        if isinstance(payload.get("text"), str):
            return payload["text"]
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                if isinstance(message, dict):
                    content = text_from_message_content(message.get("content"))
                    if content:
                        return content
    if isinstance(payload, str):
        return payload
    return ""


def text_from_message_content(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
                elif item.get("type") == "text" and isinstance(item.get("content"), str):
                    parts.append(item["content"])
        if parts:
            return "\n".join(parts)
    return None
