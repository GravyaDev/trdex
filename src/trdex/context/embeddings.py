"""Jina AI embeddings client (httpx-based, no extra SDK required)."""

from __future__ import annotations

import httpx

from trdex.config import get_settings

JINA_ENDPOINT = "https://api.jina.ai/v1/embeddings"
JINA_MODEL = "jina-embeddings-v3"
EMBEDDING_DIM = 1024


class JinaEmbeddingError(RuntimeError):
    """Raised when the Jina API returns an error."""


class JinaEmbedder:
    """Async client for Jina embeddings API.

    Usage:
        async with JinaEmbedder() as embedder:
            vectors = await embedder.embed(["text1", "text2"])
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owned = client is None

    async def __aenter__(self) -> JinaEmbedder:
        if self._owned:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owned and self._client:
            await self._client.aclose()
            self._client = None

    async def embed(
        self,
        texts: list[str],
        task: str = "retrieval.passage",
    ) -> list[list[float]]:
        """Embed a batch of texts. Returns list of 1024-dim float vectors."""
        if not texts:
            return []

        settings = get_settings()
        headers = {
            "Authorization": f"Bearer {settings.jina_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": JINA_MODEL,
            "input": texts,
            "task": task,
            "dimensions": EMBEDDING_DIM,
            "normalized": False,
        }

        if self._client is None:
            raise RuntimeError("Use JinaEmbedder as async context manager")
        response = await self._client.post(JINA_ENDPOINT, json=payload, headers=headers)
        if response.status_code != 200:
            raise JinaEmbeddingError(f"Jina API error {response.status_code}: {response.text}")

        data = response.json()
        # Response: {"data": [{"index": 0, "embedding": [...]}, ...]}
        items: list[dict] = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string (task=retrieval.query)."""
        results = await self.embed([text], task="retrieval.query")
        return results[0]
