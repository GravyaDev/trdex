"""Unit tests for Tier 4b market episodes (detection + store + service)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from trdex.memory.market_episodes import (
    COLLECTION_NAME,
    MarketEpisode,
    MarketEpisodeHit,
    MarketEpisodeService,
    MarketEpisodeStore,
    build_episode_text,
    detect_episodes,
)


# ---------- helpers ---------------------------------------------------------


def _timestamps(n: int, start: datetime | None = None) -> list[datetime]:
    """Generate N hourly timestamps."""
    start = start or datetime(2025, 6, 1, tzinfo=timezone.utc)
    return [start + timedelta(hours=i) for i in range(n)]


def _make_episode(**overrides) -> MarketEpisode:
    base = dict(
        symbol="BTC/USDT",
        timeframe="1h",
        episode_type="trend_reversal",
        start_time=datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2025, 6, 3, 0, 0, tzinfo=timezone.utc),
        price_change_pct=8.5,
        volatility_regime="high",
        volatility_cv=0.042,
        rsi_start=45.0,
        rsi_end=75.0,
        volume_ratio_peak=1.8,
        sma_short=91000.0,
        sma_long=89500.0,
        candle_count=50,
    )
    base.update(overrides)
    return MarketEpisode(**base)


class _FakeEmbedder:
    """Stand-in for JinaEmbedder."""

    def __init__(self, dim: int = 8) -> None:
        self.dim = dim
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


def _scored_point(*, doc_id: str = "abc", score: float = 0.9, payload: dict | None = None) -> MagicMock:
    p = MagicMock()
    p.id = doc_id
    p.score = score
    p.payload = payload or {
        "text": "BTC/USDT trend reversal",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "episode_type": "trend_reversal",
        "price_change_pct": 8.5,
        "volatility_regime": "high",
    }
    return p


# ---------- MarketEpisode dataclass -----------------------------------------


def test_episode_doc_id_is_deterministic() -> None:
    """Same symbol+timeframe+end_time → same doc_id (idempotent upsert)."""
    ep1 = _make_episode()
    ep2 = _make_episode()
    assert ep1.doc_id == ep2.doc_id
    assert len(ep1.doc_id) == 32  # truncated sha256


def test_episode_doc_id_differs_by_end_time() -> None:
    ep1 = _make_episode()
    ep2 = _make_episode(end_time=datetime(2025, 6, 4, 0, 0, tzinfo=timezone.utc))
    assert ep1.doc_id != ep2.doc_id


def test_episode_doc_id_differs_by_symbol() -> None:
    ep1 = _make_episode(symbol="BTC/USDT")
    ep2 = _make_episode(symbol="ETH/USDT")
    assert ep1.doc_id != ep2.doc_id


# ---------- build_episode_text ----------------------------------------------


def test_build_episode_text_full() -> None:
    ep = _make_episode()
    text = build_episode_text(ep)
    assert "BTC/USDT" in text
    assert "Trend Reversal" in text
    assert "High volatility" in text
    assert "4.2%" in text  # CV formatted
    assert "+8.5%" in text
    assert "RSI at end: 75" in text
    assert "Volume 1.8x" in text


def test_build_episode_text_bearish_sma() -> None:
    ep = _make_episode(sma_short=90000.0, sma_long=91000.0)
    text = build_episode_text(ep)
    assert "bearish" in text


def test_build_episode_text_oversold_rsi() -> None:
    ep = _make_episode(rsi_end=25.0, price_change_pct=-7.0)
    text = build_episode_text(ep)
    assert "oversold" in text
    assert "downtrend" in text


# ---------- detect_episodes --------------------------------------------------


def test_detect_episodes_insufficient_data() -> None:
    """Fewer candles than window → no episodes."""
    ts = _timestamps(20)
    closes = [100.0] * 20
    volumes = [1000.0] * 20
    episodes = detect_episodes("BTC/USDT", "1h", ts, closes, volumes, window=50)
    assert episodes == []


def test_detect_episodes_flat_market_no_signal() -> None:
    """Flat price, constant volume → no significant episodes."""
    ts = _timestamps(100)
    closes = [100.0] * 100
    volumes = [1000.0] * 100
    episodes = detect_episodes("BTC/USDT", "1h", ts, closes, volumes, window=50, stride=25)
    assert episodes == []


def test_detect_episodes_volume_surge() -> None:
    """Window whose last candle has vol_ratio > 2.0 → volume_surge.

    volume_ratio compares the last candle's volume to the trailing 20-candle
    baseline (inside the window). So the surge must be on the LAST candle of
    the window, not across many candles.
    """
    ts = _timestamps(100)
    closes = [100.0 + i * 0.01 for i in range(100)]  # tiny move
    # Baseline 1000 everywhere, spike only on the last candle of each window.
    # Window [0:50] → last candle = index 49; window [25:75] → index 74 etc.
    volumes = [1000.0] * 100
    volumes[49] = 5000.0  # spike in first window
    volumes[99] = 5000.0  # spike in last window
    episodes = detect_episodes("BTC/USDT", "1h", ts, closes, volumes, window=50, stride=25)
    assert len(episodes) >= 1
    assert any(e.episode_type == "volume_surge" for e in episodes)


def test_detect_episodes_trend_reversal_with_rsi_extreme() -> None:
    """Strong uptrend (>5%) + RSI overbought → trend_reversal."""
    ts = _timestamps(100)
    # Strong uptrend in last 50 candles
    closes = [100.0] * 50 + [100.0 + i * 0.5 for i in range(50)]  # last goes to 124.5
    volumes = [1000.0] * 100
    episodes = detect_episodes("BTC/USDT", "1h", ts, closes, volumes, window=50, stride=10)
    # At least one window should detect trend_reversal
    reversal_episodes = [e for e in episodes if e.episode_type == "trend_reversal"]
    assert len(reversal_episodes) >= 1
    assert all(abs(e.price_change_pct) > 5.0 for e in reversal_episodes)


def test_detect_episodes_metadata_populated() -> None:
    """Detected episodes carry correct metadata."""
    ts = _timestamps(60)
    closes = [100.0 + i * 0.3 for i in range(60)]  # +18% move
    volumes = [1000.0] * 60
    episodes = detect_episodes("BTC/USDT", "1h", ts, closes, volumes, window=50, stride=50)
    assert len(episodes) >= 1
    ep = episodes[0]
    assert ep.symbol == "BTC/USDT"
    assert ep.timeframe == "1h"
    assert ep.candle_count == 50
    assert ep.start_time == ts[0]
    assert ep.end_time == ts[49]
    assert ep.text != ""  # auto-populated


# ---------- MarketEpisodeStore ----------------------------------------------


async def test_ensure_collection_creates_when_missing() -> None:
    client = AsyncMock()
    client.get_collections.return_value = MagicMock(collections=[])
    store = MarketEpisodeStore(client=client)
    await store.ensure_collection()
    client.create_collection.assert_called_once()
    kwargs = client.create_collection.call_args.kwargs
    assert kwargs["collection_name"] == COLLECTION_NAME


async def test_ensure_collection_skips_when_present() -> None:
    client = AsyncMock()
    existing = MagicMock()
    existing.name = COLLECTION_NAME
    client.get_collections.return_value = MagicMock(collections=[existing])
    store = MarketEpisodeStore(client=client)
    await store.ensure_collection()
    client.create_collection.assert_not_called()


async def test_upsert_passes_points_with_payload() -> None:
    client = AsyncMock()
    store = MarketEpisodeStore(client=client)
    ep = _make_episode()
    await store.upsert([ep], [[1.0] * 4])
    client.upsert.assert_called_once()
    kwargs = client.upsert.call_args.kwargs
    assert kwargs["collection_name"] == COLLECTION_NAME
    points = kwargs["points"]
    assert len(points) == 1
    assert points[0].payload["symbol"] == "BTC/USDT"
    assert points[0].payload["episode_type"] == "trend_reversal"
    assert points[0].payload["volatility_regime"] == "high"
    assert points[0].payload["price_change_pct"] == 8.5


async def test_upsert_validates_length_mismatch() -> None:
    client = AsyncMock()
    store = MarketEpisodeStore(client=client)
    with pytest.raises(ValueError):
        await store.upsert([_make_episode(), _make_episode(end_time=datetime(2025, 6, 5, tzinfo=timezone.utc))], [[1.0]])


async def test_upsert_skips_empty_batch() -> None:
    client = AsyncMock()
    store = MarketEpisodeStore(client=client)
    await store.upsert([], [])
    client.upsert.assert_not_called()


def _query_response(points: list) -> MagicMock:
    response = MagicMock()
    response.points = points
    return response


async def test_search_with_filters() -> None:
    client = AsyncMock()
    client.query_points.return_value = _query_response([_scored_point()])
    store = MarketEpisodeStore(client=client)
    out = await store.search([0.1] * 4, symbol="BTC/USDT", episode_type="trend_reversal", limit=3)
    assert len(out) == 1
    kwargs = client.query_points.call_args.kwargs
    assert kwargs["collection_name"] == COLLECTION_NAME
    assert kwargs["limit"] == 3
    assert kwargs["query_filter"] is not None


async def test_search_without_filters() -> None:
    client = AsyncMock()
    client.query_points.return_value = _query_response([])
    store = MarketEpisodeStore(client=client)
    await store.search([0.1] * 4)
    kwargs = client.query_points.call_args.kwargs
    assert kwargs["query_filter"] is None


# ---------- MarketEpisodeService --------------------------------------------


async def test_record_batch_embeds_and_upserts() -> None:
    embedder = _FakeEmbedder()
    store = AsyncMock(spec=MarketEpisodeStore)
    service = MarketEpisodeService(embedder=embedder, store=store)

    ep = _make_episode()
    count = await service.record_batch([ep])

    assert count == 1
    assert ep.text != ""  # auto-populated
    assert len(embedder.embed_calls) == 1
    assert embedder.embed_calls[0] == [ep.text]
    store.upsert.assert_awaited_once()


async def test_record_batch_empty() -> None:
    embedder = _FakeEmbedder()
    store = AsyncMock(spec=MarketEpisodeStore)
    service = MarketEpisodeService(embedder=embedder, store=store)
    count = await service.record_batch([])
    assert count == 0
    store.upsert.assert_not_called()


async def test_search_returns_hits() -> None:
    embedder = _FakeEmbedder()
    store = AsyncMock(spec=MarketEpisodeStore)
    store.search.return_value = [
        _scored_point(doc_id="a", score=0.95),
        _scored_point(doc_id="b", score=0.80),
    ]
    service = MarketEpisodeService(embedder=embedder, store=store)

    hits = await service.search("BTC high vol breakout", symbol="BTC/USDT", limit=2)

    assert embedder.query_calls == ["BTC high vol breakout"]
    assert len(hits) == 2
    assert isinstance(hits[0], MarketEpisodeHit)
    assert hits[0].doc_id == "a"
    assert hits[0].score == pytest.approx(0.95)


async def test_search_similar_context_builds_query_from_indicators() -> None:
    embedder = _FakeEmbedder()
    store = AsyncMock(spec=MarketEpisodeStore)
    store.search.return_value = []
    service = MarketEpisodeService(embedder=embedder, store=store)

    # 30 closes with uptrend, high volume on last
    closes = [100.0 + i * 0.5 for i in range(30)]
    volumes = [1000.0] * 29 + [3000.0]

    await service.search_similar_context("BTC/USDT", closes, volumes, limit=3)

    assert len(embedder.query_calls) == 1
    query = embedder.query_calls[0]
    assert "BTC/USDT" in query
    assert "volatility" in query
    kwargs = store.search.call_args.kwargs
    assert kwargs["symbol"] == "BTC/USDT"
    assert kwargs["limit"] == 3


async def test_setup_calls_store() -> None:
    embedder = _FakeEmbedder()
    store = AsyncMock(spec=MarketEpisodeStore)
    service = MarketEpisodeService(embedder=embedder, store=store)
    await service.setup()
    store.ensure_collection.assert_awaited_once()
