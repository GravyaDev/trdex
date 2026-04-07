"""CryptoCompare REST price feed (crypto only)."""

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

_BASE_URL = "https://min-api.cryptocompare.com"

_TIMEFRAME_ENDPOINT: dict[str, str] = {
    "1m": "/data/histominute",
    "5m": "/data/histominute",
    "15m": "/data/histominute",
    "1h": "/data/histohour",
    "4h": "/data/histohour",
    "1d": "/data/histoday",
    "1w": "/data/histoday",
}

_TIMEFRAME_AGGREGATE: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "1h": 1,
    "4h": 4,
    "1d": 1,
    "1w": 7,
}


class CryptoCompareFeed(PriceFeed):
    """CryptoCompare REST price feed.

    Provides ticker prices and OHLCV historical data for crypto assets.
    Free tier requires API key (register at cryptocompare.com).
    Rate limit: ~100 calls/sec on free tier.
    """

    def __init__(self, api_key: str = "") -> None:
        headers: dict[str, str] = {}
        if api_key:
            headers["authorization"] = f"Apikey {api_key}"
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers=headers,
            timeout=httpx.Timeout(15.0),
        )

    @property
    def name(self) -> str:
        return "cryptocompare"

    def _base_quote(self, symbol: str) -> tuple[str, str]:
        """Parse 'BTC/USDT' → ('BTC', 'USDT')."""
        parts = symbol.upper().split("/")
        if len(parts) != 2:
            raise ValueError(f"CryptoCompareFeed: invalid symbol {symbol!r}")
        return parts[0], parts[1]

    async def get_ticker(self, symbol: str) -> Ticker:
        base, quote = self._base_quote(symbol)
        resp = await self._client.get(
            "/data/price",
            params={"fsym": base, "tsyms": quote},
        )
        resp.raise_for_status()
        data = resp.json()
        if "Response" in data and data["Response"] == "Error":
            raise ValueError(f"CryptoCompareFeed error: {data.get('Message')}")
        price = Decimal(str(data[quote]))
        logger.debug("[CryptoCompare] %s = %s", symbol, price)
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
        since: int | None = None,  # noqa: ARG002 - not yet wired through CryptoCompare API
    ) -> list[OHLCV]:
        base, quote = self._base_quote(symbol)
        endpoint = _TIMEFRAME_ENDPOINT.get(timeframe, "/data/histohour")
        aggregate = _TIMEFRAME_AGGREGATE.get(timeframe, 1)
        resp = await self._client.get(
            endpoint,
            params={
                "fsym": base,
                "tsym": quote,
                "limit": limit,
                "aggregate": aggregate,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("Response") == "Error":
            raise ValueError(f"CryptoCompareFeed OHLCV error: {data.get('Message')}")
        candles = [
            OHLCV(
                timestamp=datetime.fromtimestamp(row["time"], tz=timezone.utc),
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=Decimal(str(row.get("volumefrom", 0))),
            )
            for row in data.get("Data", {}).get("Data", [])
            if row.get("open", 0) > 0
        ]
        logger.debug("[CryptoCompare] ohlcv %s tf=%s candles=%d", symbol, timeframe, len(candles))
        return candles[-limit:]

    async def subscribe_ticker(self, symbol: str, callback: Callable[[Ticker], Any]) -> None:
        raise NotImplementedError("CryptoCompare has no WebSocket feed in this implementation.")

    async def close(self) -> None:
        await self._client.aclose()
