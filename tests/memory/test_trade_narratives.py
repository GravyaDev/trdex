"""Unit tests for Tier 4 trade narratives (store + service + text builder)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from trdex.memory.trade_narratives import (
    COLLECTION_NAME,
    TradeNarrative,
    TradeNarrativeHit,
    TradeNarrativeService,
    TradeNarrativeStore,
    build_narrative_text,
)


# ---------- helpers ---------------------------------------------------------


def _make_narrative(**overrides) -> TradeNarrative:
    base = dict(
        symbol="BTC/USDT",
        text="",
        signal="BUY",
        confidence=0.62,
        outcome="WIN",
        pnl_pct=2.4,
        duration_minutes=360,
        volatility_regime="high",
        run_id="run-1",
        closed_at=datetime(2026, 4, 7, 9, 0, 0),
        indicators={"rsi": 28.4, "sma_5": 90100.0},
    )
    base.update(overrides)
    return TradeNarrative(**base)


class _FakeEmbedder:
    """Stand-in for JinaEmbedder. Records calls and returns canned vectors."""

    def __init__(self, vector_dim: int = 8) -> None:
        self.dim = vector_dim
        self.embed_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    async def __aenter__(self) -> "_FakeEmbedder":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def embed(self, texts: list[str], task: str = "retrieval.passage") -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [[float(i)] * self.dim for i, _ in enumerate(texts)]

    async def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return [0.5] * self.dim


def _scored_point(
    *,
    doc_id: str = "abc",
    score: float = 0.9,
    payload: dict | None = None,
) -> MagicMock:
    p = MagicMock()
    p.id = doc_id
    p.score = score
    p.payload = payload or {
        "text": "BTC/USDT BUY WIN +2.4%",
        "symbol": "BTC/USDT",
        "signal": "BUY",
        "outcome": "WIN",
        "pnl_pct": 2.4,
    }
    return p


# ---------- build_narrative_text -------------------------------------------


def test_build_narrative_text_full() -> None:
    n = _make_narrative()
    text = build_narrative_text(n)
    assert "BTC/USDT" in text
    assert "BUY" in text
    assert "conf=0.62" in text
    assert "rsi=28.40" in text
    assert "regime=high" in text
    assert "outcome=WIN" in text
    assert "pnl=+2.40%" in text
    assert "duration=360m" in text


def test_build_narrative_text_negative_pnl() -> None:
    n = _make_narrative(outcome="LOSS", pnl_pct=-1.5)
    text = build_narrative_text(n)
    assert "pnl=-1.50%" in text


def test_build_narrative_text_minimal() -> None:
    n = TradeNarrative(
        symbol="ETH/USDT",
        text="",
        signal="SELL",
        confidence=0.5,
        outcome="UNKNOWN",
    )
    text = build_narrative_text(n)
    assert "ETH/USDT" in text
    assert "SELL" in text
    assert "outcome=UNKNOWN" in text
    assert "regime" not in text
    assert "pnl" not in text
    assert "duration" not in text


# ---------- TradeNarrativeStore --------------------------------------------


async def test_ensure_collection_creates_when_missing() -> None:
    client = AsyncMock()
    client.get_collections.return_value = MagicMock(collections=[])
    store = TradeNarrativeStore(client=client)
    await store.ensure_collection()
    client.create_collection.assert_called_once()
    args, kwargs = client.create_collection.call_args
    assert kwargs["collection_name"] == COLLECTION_NAME


async def test_ensure_collection_skips_when_present() -> None:
    client = AsyncMock()
    existing = MagicMock()
    existing.name = COLLECTION_NAME
    client.get_collections.return_value = MagicMock(collections=[existing])
    store = TradeNarrativeStore(client=client)
    await store.ensure_collection()
    client.create_collection.assert_not_called()


async def test_upsert_passes_points_with_payload() -> None:
    client = AsyncMock()
    store = TradeNarrativeStore(client=client)
    n = _make_narrative()
    n.text = build_narrative_text(n)
    await store.upsert([n], [[1.0] * 4])
    client.upsert.assert_called_once()
    kwargs = client.upsert.call_args.kwargs
    assert kwargs["collection_name"] == COLLECTION_NAME
    points = kwargs["points"]
    assert len(points) == 1
    assert points[0].payload["symbol"] == "BTC/USDT"
    assert points[0].payload["outcome"] == "WIN"
    assert points[0].payload["pnl_pct"] == 2.4
    assert points[0].payload["volatility_regime"] == "high"


async def test_upsert_validates_length_mismatch() -> None:
    client = AsyncMock()
    store = TradeNarrativeStore(client=client)
    with pytest.raises(ValueError):
        await store.upsert([_make_narrative(), _make_narrative()], [[1.0]])


async def test_upsert_skips_empty_batch() -> None:
    client = AsyncMock()
    store = TradeNarrativeStore(client=client)
    await store.upsert([], [])
    client.upsert.assert_not_called()


def _query_response(points: list) -> MagicMock:
    """Mimic ``QueryResponse`` returned by ``AsyncQdrantClient.query_points``."""
    response = MagicMock()
    response.points = points
    return response


async def test_search_with_filters_builds_qdrant_filter() -> None:
    client = AsyncMock()
    client.query_points.return_value = _query_response([_scored_point()])
    store = TradeNarrativeStore(client=client)
    out = await store.search([0.1] * 4, symbol="BTC/USDT", outcome="WIN", limit=3)
    assert len(out) == 1
    kwargs = client.query_points.call_args.kwargs
    assert kwargs["collection_name"] == COLLECTION_NAME
    assert kwargs["limit"] == 3
    assert kwargs["query_filter"] is not None  # filter present
    # The new API uses ``query=`` instead of ``query_vector=``.
    assert kwargs["query"] == [0.1] * 4


async def test_search_without_filters_passes_none_filter() -> None:
    client = AsyncMock()
    client.query_points.return_value = _query_response([])
    store = TradeNarrativeStore(client=client)
    await store.search([0.1] * 4)
    kwargs = client.query_points.call_args.kwargs
    assert kwargs["query_filter"] is None


# ---------- TradeNarrativeService ------------------------------------------


async def test_record_embeds_text_and_upserts() -> None:
    embedder = _FakeEmbedder()
    store = AsyncMock(spec=TradeNarrativeStore)
    service = TradeNarrativeService(embedder=embedder, store=store)

    n = _make_narrative()
    await service.record(n)

    # Service auto-builds the canonical text when missing.
    assert n.text != ""
    assert "BTC/USDT" in n.text
    assert embedder.embed_calls == [[n.text]]
    store.upsert.assert_awaited_once()


async def test_record_batch_handles_empty() -> None:
    embedder = _FakeEmbedder()
    store = AsyncMock(spec=TradeNarrativeStore)
    service = TradeNarrativeService(embedder=embedder, store=store)
    await service.record_batch([])
    store.upsert.assert_not_called()
    assert embedder.embed_calls == []


async def test_search_returns_hits() -> None:
    embedder = _FakeEmbedder()
    store = AsyncMock(spec=TradeNarrativeStore)
    store.search.return_value = [
        _scored_point(doc_id="a", score=0.95),
        _scored_point(doc_id="b", score=0.80),
    ]
    service = TradeNarrativeService(embedder=embedder, store=store)

    hits = await service.search("BTC oversold high vol", symbol="BTC/USDT", limit=2)

    assert embedder.query_calls == ["BTC oversold high vol"]
    assert len(hits) == 2
    assert isinstance(hits[0], TradeNarrativeHit)
    assert hits[0].doc_id == "a"
    assert hits[0].score == pytest.approx(0.95)
    assert hits[0].symbol == "BTC/USDT"
    store.search.assert_awaited_once()


async def test_similar_to_uses_narrative_text() -> None:
    embedder = _FakeEmbedder()
    store = AsyncMock(spec=TradeNarrativeStore)
    store.search.return_value = []
    service = TradeNarrativeService(embedder=embedder, store=store)

    n = _make_narrative()
    await service.similar_to(n, same_symbol_only=True, limit=3)

    assert len(embedder.query_calls) == 1
    assert "BTC/USDT" in embedder.query_calls[0]
    kwargs = store.search.call_args.kwargs
    assert kwargs["symbol"] == "BTC/USDT"
    assert kwargs["limit"] == 3


async def test_setup_calls_store() -> None:
    embedder = _FakeEmbedder()
    store = AsyncMock(spec=TradeNarrativeStore)
    service = TradeNarrativeService(embedder=embedder, store=store)
    await service.setup()
    store.ensure_collection.assert_awaited_once()
