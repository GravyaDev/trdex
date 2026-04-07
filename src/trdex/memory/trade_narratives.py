"""Tier 4 — Semantic memory of completed trades (Qdrant).

A *trade narrative* is a short natural-language recap of one completed agent
cycle whose position has been closed:

    "BTC/USDT 2026-04-07 09:00 — BUY conf=0.62 (RSI=28 oversold; SMA bullish);
     regime=high. Risk approved. Filled @ 90123. Outcome: WIN +2.4% in 6h."

These narratives are embedded with Jina and stored in a dedicated Qdrant
collection (``trdex_trade_narratives``) so future agent cycles can ask:
"have we seen something semantically similar before, and how did it end?".

Design notes:
- We **only** write a narrative when the outcome is known (position closed).
  This avoids the need for Qdrant updates; an entry is immutable once written.
- The collection is separate from ``trdex_context`` (news/sentiment) so the
  payload schemas don't bleed into each other.
- Both the embedder and the store are injectable to keep the service unit
  testable without hitting Jina or Qdrant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from trdex.config import get_settings
from trdex.context.embeddings import EMBEDDING_DIM, JinaEmbedder

logger = logging.getLogger(__name__)

COLLECTION_NAME = "trdex_trade_narratives"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TradeNarrative:
    """One completed-trade recap, ready for embedding + storage."""

    symbol: str
    text: str
    signal: str  # BUY | SELL
    confidence: float
    outcome: str  # WIN | LOSS | BREAKEVEN | UNKNOWN
    pnl_pct: float | None = None
    duration_minutes: int | None = None
    volatility_regime: str | None = None
    run_id: str | None = None
    closed_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc).replace(tzinfo=None)
    )
    doc_id: str = field(default_factory=lambda: str(uuid4()))
    indicators: dict | None = None  # snapshot at entry, e.g. {"rsi": 28.4, ...}


@dataclass
class TradeNarrativeHit:
    """A semantic search result."""

    doc_id: str
    score: float
    text: str
    symbol: str
    signal: str
    outcome: str
    pnl_pct: float | None
    payload: dict


# ---------------------------------------------------------------------------
# Qdrant store
# ---------------------------------------------------------------------------


class TradeNarrativeStore:
    """Async Qdrant wrapper for the ``trdex_trade_narratives`` collection."""

    def __init__(self, client: AsyncQdrantClient | None = None) -> None:
        self._client = client

    async def _get_client(self) -> AsyncQdrantClient:
        if self._client is None:
            settings = get_settings()
            # check_compatibility=False — see vector_store.QdrantStore for the
            # rationale. We only use stable API surface (ensure_collection /
            # upsert / query_points) consistent across v1.9 → v1.17.
            self._client = AsyncQdrantClient(
                url=settings.qdrant_url, check_compatibility=False
            )
        return self._client

    async def ensure_collection(self) -> None:
        """Create the collection on first use."""
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
            logger.info("[trade_narratives] created collection %s", COLLECTION_NAME)

    async def upsert(
        self,
        narratives: list[TradeNarrative],
        vectors: list[list[float]],
    ) -> None:
        """Insert a batch of narratives with their precomputed vectors."""
        if not narratives:
            return
        if len(narratives) != len(vectors):
            raise ValueError("narratives and vectors must have the same length")

        client = await self._get_client()
        points = [
            PointStruct(
                id=n.doc_id,
                vector=v,
                payload={
                    "text": n.text,
                    "symbol": n.symbol,
                    "signal": n.signal,
                    "confidence": n.confidence,
                    "outcome": n.outcome,
                    "pnl_pct": n.pnl_pct,
                    "duration_minutes": n.duration_minutes,
                    "volatility_regime": n.volatility_regime,
                    "run_id": n.run_id,
                    "closed_at": n.closed_at.isoformat(),
                    "indicators": n.indicators,
                },
            )
            for n, v in zip(narratives, vectors, strict=True)
        ]
        await client.upsert(collection_name=COLLECTION_NAME, points=points)

    async def search(
        self,
        query_vector: list[float],
        *,
        symbol: str | None = None,
        outcome: str | None = None,
        limit: int = 5,
    ) -> list[ScoredPoint]:
        """Top-k semantic search with optional symbol/outcome filters.

        Uses ``query_points`` (the API since qdrant-client 1.10) which replaced
        the removed ``search`` method. ``response.points`` is the same
        ``list[ScoredPoint]`` callers used to receive directly.
        """
        client = await self._get_client()
        must: list[FieldCondition] = []
        if symbol:
            must.append(FieldCondition(key="symbol", match=MatchValue(value=symbol)))
        if outcome:
            must.append(FieldCondition(key="outcome", match=MatchValue(value=outcome)))
        query_filter = Filter(must=must) if must else None
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
            self._client = None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def build_narrative_text(narrative: TradeNarrative) -> str:
    """Render a deterministic, embedding-friendly text from a TradeNarrative.

    This is the canonical text format used for ingestion. Keeping it stable
    over time means embeddings remain comparable across versions.
    """
    parts: list[str] = []
    closed_at = narrative.closed_at.strftime("%Y-%m-%d %H:%M")
    parts.append(
        f"{narrative.symbol} {closed_at} — {narrative.signal} "
        f"conf={narrative.confidence:.2f}"
    )
    if narrative.indicators:
        ind_bits = ", ".join(
            f"{k}={v:.2f}" if isinstance(v, (int, float)) else f"{k}={v}"
            for k, v in narrative.indicators.items()
        )
        parts.append(f"({ind_bits})")
    if narrative.volatility_regime:
        parts.append(f"regime={narrative.volatility_regime}")
    parts.append(f"outcome={narrative.outcome}")
    if narrative.pnl_pct is not None:
        sign = "+" if narrative.pnl_pct >= 0 else ""
        parts.append(f"pnl={sign}{narrative.pnl_pct:.2f}%")
    if narrative.duration_minutes is not None:
        parts.append(f"duration={narrative.duration_minutes}m")
    return " ".join(parts)


class TradeNarrativeService:
    """High-level API for writing and querying trade narratives.

    Handles the embedding + storage roundtrip so callers don't need to know
    about vectors or Qdrant directly.

    Usage::

        service = TradeNarrativeService()
        await service.setup()
        await service.record(narrative)        # writes one
        hits = await service.search("BTC oversold bounce on high vol", limit=5)
    """

    def __init__(
        self,
        embedder: JinaEmbedder | None = None,
        store: TradeNarrativeStore | None = None,
    ) -> None:
        self._embedder = embedder or JinaEmbedder()
        self._store = store or TradeNarrativeStore()

    async def setup(self) -> None:
        await self._store.ensure_collection()

    async def record(self, narrative: TradeNarrative) -> None:
        """Embed and store a single narrative."""
        await self.record_batch([narrative])

    async def record_batch(self, narratives: list[TradeNarrative]) -> None:
        """Embed and store a batch of narratives."""
        if not narratives:
            return
        # Ensure each narrative has its canonical text populated.
        for n in narratives:
            if not n.text:
                n.text = build_narrative_text(n)
        async with self._embedder as embedder:
            vectors = await embedder.embed([n.text for n in narratives])
        await self._store.upsert(narratives, vectors)
        logger.info("[trade_narratives] recorded %d narratives", len(narratives))

    async def search(
        self,
        query: str,
        *,
        symbol: str | None = None,
        outcome: str | None = None,
        limit: int = 5,
    ) -> list[TradeNarrativeHit]:
        """Find narratives semantically similar to ``query``."""
        async with self._embedder as embedder:
            qvec = await embedder.embed_query(query)
        hits = await self._store.search(
            qvec, symbol=symbol, outcome=outcome, limit=limit
        )
        return [self._hit_from_point(h) for h in hits]

    async def similar_to(
        self,
        narrative: TradeNarrative,
        *,
        limit: int = 5,
        same_symbol_only: bool = False,
    ) -> list[TradeNarrativeHit]:
        """Find narratives similar to a given narrative (e.g. live cycle preview)."""
        text = narrative.text or build_narrative_text(narrative)
        return await self.search(
            text,
            symbol=narrative.symbol if same_symbol_only else None,
            limit=limit,
        )

    @staticmethod
    def _hit_from_point(point: ScoredPoint) -> TradeNarrativeHit:
        payload = point.payload or {}
        return TradeNarrativeHit(
            doc_id=str(point.id),
            score=float(point.score),
            text=payload.get("text", ""),
            symbol=payload.get("symbol", ""),
            signal=payload.get("signal", ""),
            outcome=payload.get("outcome", "UNKNOWN"),
            pnl_pct=payload.get("pnl_pct"),
            payload=payload,
        )
