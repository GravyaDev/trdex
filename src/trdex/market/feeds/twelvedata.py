"""Twelve Data REST feed — FX, commodities, stocks, indices, crypto.

Primary feed for Forex and commodity OHLCV in trdex, registered before
yfinance (fallback) in the PriceFeedManager. Twelve Data supports the
trdex-native symbol format (XAU/USD, EUR/USD, GBP/JPY, AAPL, BTC/USD)
without any mapping layer.

API reference (verified against official docs on 2026-04-17):
  Base URL: https://api.twelvedata.com
  OHLCV:    /time_series?symbol=...&interval=...&outputsize=...
  Price:    /price?symbol=...
  Auth:     apikey query parameter

Response shape (time_series):
  {
    "meta":   {"symbol", "interval", "currency", "exchange", "type"},
    "values": [{"datetime", "open", "high", "low", "close", "volume"}, ...],
    "status": "ok"
  }
  Errors: {"code": 4xx, "message": "...", "status": "error"} at HTTP 4xx.

Free tier: 800 req/day, 8 req/min.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

from trdex.market.feeds.base import PriceFeed
from trdex.market.models import OHLCV, Ticker

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.twelvedata.com"

# Map trdex timeframe → Twelve Data interval
_TIMEFRAME_MAP: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1day",
    "1w": "1week",
}


class TwelveDataFeed(PriceFeed):
    """Twelve Data feed for FX, commodities, stocks, indices, crypto.

    Native symbol format (XAU/USD, EUR/USD, AAPL). No mapping layer.
    Free tier: 800 req/day, 8 req/min.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("TwelveDataFeed requires an API key.")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=httpx.Timeout(15.0),
        )

    @property
    def name(self) -> str:
        return "twelvedata"

    async def _get(self, path: str, params: dict[str, str]) -> dict:
        params["apikey"] = self._api_key
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("status") == "error":
            raise RuntimeError(
                f"TwelveData API error ({data.get('code')}): {data.get('message')}"
            )
        return data

    async def get_ticker(self, symbol: str) -> Ticker:
        data = await self._get("/price", {"symbol": symbol})
        price_str = data.get("price")
        if not price_str:
            raise ValueError(f"TwelveData: no price for {symbol!r} — resp={data!r}")
        return Ticker(
            symbol=symbol,
            price=Decimal(str(price_str)),
            timestamp=datetime.now(tz=timezone.utc),
            source=self.name,
        )

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
        since: int | None = None,  # noqa: ARG002 - applied client-side
    ) -> list[OHLCV]:
        interval = _TIMEFRAME_MAP.get(timeframe, "1day")
        outputsize = max(1, min(5000, limit))
        logger.info(
            "[twelvedata] fetching OHLCV %s interval=%s outputsize=%d",
            symbol, interval, outputsize,
        )
        data = await self._get(
            "/time_series",
            {"symbol": symbol, "interval": interval, "outputsize": str(outputsize)},
        )
        values = data.get("values", [])
        if not values:
            raise ValueError(
                f"TwelveData: no candles for {symbol!r} tf={timeframe!r} — resp={data!r}"
            )

        # API returns newest-first — reverse to oldest-first for our model.
        candles: list[OHLCV] = []
        for row in reversed(values):
            dt_str = row["datetime"]
            fmt = "%Y-%m-%d %H:%M:%S" if " " in dt_str else "%Y-%m-%d"
            ts = datetime.strptime(dt_str, fmt).replace(tzinfo=timezone.utc)
            candles.append(OHLCV(
                timestamp=ts,
                open=Decimal(row["open"]),
                high=Decimal(row["high"]),
                low=Decimal(row["low"]),
                close=Decimal(row["close"]),
                volume=Decimal(row.get("volume", "0")),
            ))

        if since is not None:
            since_dt = datetime.fromtimestamp(since / 1000, tz=timezone.utc)
            candles = [c for c in candles if c.timestamp >= since_dt]

        candles = candles[-limit:]
        logger.debug(
            "[twelvedata] %s interval=%s → %d candles",
            symbol, interval, len(candles),
        )
        return candles

    async def subscribe_ticker(
        self, symbol: str, callback: Callable[[Ticker], Any],
    ) -> None:
        raise NotImplementedError("TwelveDataFeed has no WebSocket in this adapter.")

    async def close(self) -> None:
        await self._client.aclose()
