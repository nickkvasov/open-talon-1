from __future__ import annotations

import base64

import httpx


class OllamaEmbeddingProvider:
    provider_key = "ollama"

    def __init__(self, *, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def embed_texts(self, texts: list[str], *, model: str) -> list[list[float]]:
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
            response = await client.post(
                f"{self._base_url}/api/embed",
                json={"model": model, "input": texts},
            )
            response.raise_for_status()
        payload = response.json()
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list):
            return embeddings
        single = payload.get("embedding")
        if isinstance(single, list) and len(texts) == 1:
            return [single]
        raise RuntimeError("Ollama embedding response did not include embeddings")


class OllamaVisionProvider:
    provider_key = "ollama"

    def __init__(self, *, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    async def describe_image(
        self,
        image_bytes: bytes,
        *,
        model: str,
        prompt: str,
    ) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        async with httpx.AsyncClient(timeout=180.0, trust_env=False) as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                            "images": [encoded],
                        }
                    ],
                },
            )
            response.raise_for_status()
        payload = response.json()
        message = payload.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        raise RuntimeError("Ollama vision response did not include message content")
