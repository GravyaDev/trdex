"""Context ingestion pipeline: raw text → embeddings → Qdrant."""

from __future__ import annotations

from trdex.context.embeddings import JinaEmbedder
from trdex.context.vector_store import ContextDocument, QdrantStore


class ContextIngestionPipeline:
    """Orchestrates the news/sentiment ingestion flow.

    Usage:
        pipeline = ContextIngestionPipeline()
        await pipeline.ingest(docs)
    """

    def __init__(
        self,
        embedder: JinaEmbedder | None = None,
        store: QdrantStore | None = None,
    ) -> None:
        self._embedder = embedder or JinaEmbedder()
        self._store = store or QdrantStore()

    async def setup(self) -> None:
        """Ensure the vector collection exists."""
        await self._store.ensure_collection()

    async def ingest(self, docs: list[ContextDocument]) -> None:
        """Embed and store a batch of context documents."""
        if not docs:
            return
        async with JinaEmbedder() as embedder:
            vectors = await embedder.embed([doc.text for doc in docs])
        await self._store.upsert(docs, vectors)

    async def query(
        self,
        text: str,
        symbol: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Retrieve the top-k most relevant context documents for a query."""
        async with JinaEmbedder() as embedder:
            query_vector = await embedder.embed_query(text)
        hits = await self._store.search(query_vector, symbol=symbol, limit=limit)
        return [
            {
                "score": hit.score,
                "text": hit.payload.get("text", "") if hit.payload else "",
                "source": hit.payload.get("source", "") if hit.payload else "",
                "sentiment": hit.payload.get("sentiment") if hit.payload else None,
                "published_at": hit.payload.get("published_at") if hit.payload else None,
            }
            for hit in hits
        ]
