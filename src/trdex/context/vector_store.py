"""Qdrant vector store wrapper for news/sentiment context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    HnswConfigDiff,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from trdex.config import get_settings
from trdex.context.embeddings import EMBEDDING_DIM

COLLECTION_NAME = "trdex_context"


@dataclass
class ContextDocument:
    """A news/sentiment document stored in the vector DB."""

    text: str
    source: str                     # e.g. "binance_news", "cryptopanic"
    symbol: str | None = None       # e.g. "BTC/USDT" — None = global
    sentiment: float | None = None  # -1.0 … +1.0
    published_at: datetime = field(default_factory=datetime.utcnow)
    doc_id: str = field(default_factory=lambda: str(uuid4()))


class QdrantStore:
    """Async wrapper around Qdrant for context document storage and retrieval.

    Usage:
        store = QdrantStore()
        await store.ensure_collection()
        await store.upsert(docs, vectors)
        hits = await store.search(query_vector, symbol="BTC/USDT", limit=5)
    """

    def __init__(self, client: AsyncQdrantClient | None = None) -> None:
        self._client = client

    async def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            settings = get_settings()
            # check_compatibility=False suppresses the noisy "minor version
            # difference > 1" warning. We only use stable API surface
            # (ensure_collection / upsert / query_points) that has been
            # consistent across v1.9 → v1.17, so the strict-version sanity
            # check the client enforces by default is overconservative.
            self._client = AsyncQdrantClient(
                url=settings.qdrant_url, check_compatibility=False
            )
        return self._client

    async def ensure_collection(self) -> None:
        """Create the collection if it doesn't exist."""
        client = await self._get_client()
        existing = [c.name for c in (await client.get_collections()).collections]
        if COLLECTION_NAME not in existing:
            await client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,
                    hnsw_config=HnswConfigDiff(m=16, ef_construct=100),
                ),
            )

    async def upsert(
        self,
        docs: list[ContextDocument],
        vectors: list[list[float]],
    ) -> None:
        """Store documents with their embedding vectors."""
        if not docs:
            return
        client = await self._get_client()
        points = [
            PointStruct(
                id=doc.doc_id,
                vector=vector,
                payload={
                    "text": doc.text,
                    "source": doc.source,
                    "symbol": doc.symbol,
                    "sentiment": doc.sentiment,
                    "published_at": doc.published_at.isoformat(),
                },
            )
            for doc, vector in zip(docs, vectors, strict=True)
        ]
        await client.upsert(collection_name=COLLECTION_NAME, points=points)

    async def search(
        self,
        query_vector: list[float],
        symbol: str | None = None,
        limit: int = 5,
    ) -> list[ScoredPoint]:
        """Semantic search. Optionally filter by symbol.

        Uses ``query_points`` (the API since qdrant-client 1.10) which replaced
        the removed ``search`` method. The response object exposes ``.points``
        as the ``list[ScoredPoint]`` we return to keep the upstream contract.
        """
        client = await self._get_client()
        query_filter = None
        if symbol:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            query_filter = Filter(
                must=[FieldCondition(key="symbol", match=MatchValue(value=symbol))]
            )
        response = await client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return response.points

    async def close(self) -> None:
        if self._client:
            await self._client.close()
