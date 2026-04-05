"""ExchangeRate-API REST feed for FX pairs."""

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


class ForexFeed(PriceFeed):
    """FX price feed via ExchangeRate-API (https://www.exchangerate-api.com).

    Supports ticker only — no OHLCV on the free tier.
    Only registered when TRDEX_FOREX_API_KEY is set.
    """

    _BASE_URL = "https://v6.exchangerate-api.com/v6"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))

    @property
    def name(self) -> str:
        return "forex"

    async def get_ticker(self, symbol: str) -> Ticker:
        """Get FX rate for a pair like 'EUR/USD'."""
        parts = symbol.upper().split("/")
        if len(parts) != 2:
            raise ValueError(f"ForexFeed: expected 'BASE/QUOTE' symbol, got {symbol!r}")
        base, quote = parts
        url = f"{self._BASE_URL}/{self._api_key}/latest/{base}"
        resp = await self._client.get(url)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") != "success":
            raise RuntimeError(f"ForexFeed error: {data.get('error-type', 'unknown')}")
        rate = data["conversion_rates"].get(quote)
        if rate is None:
            raise ValueError(f"ForexFeed: no rate for {quote} in response")
        price = Decimal(str(rate))
        logger.debug("[Forex] %s = %s", symbol, price)
        return Ticker(
            symbol=symbol,
            price=price,
            timestamp=datetime.now(tz=timezone.utc),
            source=self.name,
        )

    async def get_ohlcv(self, symbol: str, timeframe: str = "1d", limit: int = 100) -> list[OHLCV]:
        raise NotImplementedError("ForexFeed does not support OHLCV (free tier only).")

    async def subscribe_ticker(self, symbol: str, callback: Callable[[Ticker], Any]) -> None:
        raise NotImplementedError("ForexFeed has no WebSocket feed.")

    async def close(self) -> None:
        await self._client.aclose()
