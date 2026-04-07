"""FreeCryptoAPI feed — real-time prices + pre-computed technical indicators."""

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

_BASE_URL = "https://api.freecryptoapi.com/v1"


class FreeCryptoAPIFeed(PriceFeed):
    """FreeCryptoAPI feed for crypto prices and pre-computed technical indicators.

    Free tier: up to 10,000,000 requests/month.
    Provides RSI, MACD, Bollinger Bands, support/resistance, breakout signals.

    Extra method: get_indicators(symbol) returns a dict of pre-computed values
    that can be fed directly into the agent context without re-computing locally.
    """

    def __init__(self, api_key: str = "") -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers=headers,
            timeout=httpx.Timeout(15.0),
        )

    @property
    def name(self) -> str:
        return "freecryptoapi"

    def _normalize_symbol(self, symbol: str) -> str:
        """Convert 'BTC/USDT' → 'BTCUSDT'."""
        return symbol.replace("/", "").upper()

    async def get_ticker(self, symbol: str) -> Ticker:
        sym = self._normalize_symbol(symbol)
        resp = await self._client.get("/getData", params={"symbol": sym})
        resp.raise_for_status()
        data = resp.json()
        if not data or "price" not in data:
            raise ValueError(f"FreeCryptoAPI: no price for {symbol!r}")
        price = Decimal(str(data["price"]))
        logger.debug("[FreeCryptoAPI] %s = %s", symbol, price)
        return Ticker(
            symbol=symbol,
            price=price,
            timestamp=datetime.now(tz=timezone.utc),
            source=self.name,
        )

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        since: int | None = None,  # noqa: ARG002 - aggregator API does not honour since
    ) -> list[OHLCV]:
        """FreeCryptoAPI provides OHLCV via historical endpoint."""
        sym = self._normalize_symbol(symbol)
        interval_map = {
            "1m": "1", "5m": "5", "15m": "15", "30m": "30",
            "1h": "60", "4h": "240", "1d": "1440", "1w": "10080",
        }
        interval = interval_map.get(timeframe, "60")
        resp = await self._client.get(
            "/getHistoricalData",
            params={"symbol": sym, "interval": interval, "limit": str(limit)},
        )
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list):
            return []
        candles = [
            OHLCV(
                timestamp=datetime.fromtimestamp(row["time"] / 1000, tz=timezone.utc)
                if row.get("time", 0) > 1e10
                else datetime.fromtimestamp(row["time"], tz=timezone.utc),
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=Decimal(str(row.get("volume", 0))),
            )
            for row in rows
            if row.get("open", 0) > 0
        ]
        logger.debug("[FreeCryptoAPI] ohlcv %s tf=%s candles=%d", symbol, timeframe, len(candles))
        return candles

    async def get_indicators(self, symbol: str) -> dict[str, Any]:
        """Fetch pre-computed technical indicators for a symbol.

        Returns a dict with keys like: rsi, macd, macd_signal, macd_hist,
        bb_upper, bb_middle, bb_lower, support, resistance, breakout, etc.

        This is a FreeCryptoAPI-specific method — not part of PriceFeed interface.
        """
        sym = self._normalize_symbol(symbol)
        resp = await self._client.get("/getIndicators", params={"symbol": sym})
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            raise ValueError(f"FreeCryptoAPI: unexpected indicators response for {symbol!r}")
        logger.debug("[FreeCryptoAPI] indicators for %s: %s", symbol, list(data.keys()))
        return data

    async def subscribe_ticker(self, symbol: str, callback: Callable[[Ticker], Any]) -> None:
        raise NotImplementedError("FreeCryptoAPI has no WebSocket feed.")

    async def close(self) -> None:
        await self._client.aclose()
