"""CoinGecko REST price feed (crypto only)."""

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

# CoinGecko coin ID by base currency symbol
_SYMBOL_MAP: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "ATOM": "cosmos",
}

_TIMEFRAME_DAYS: dict[str, int] = {
    "1h": 1,
    "4h": 7,
    "1d": 30,
    "1w": 90,
}

_BASE_URL = "https://api.coingecko.com/api/v3"
_PRO_BASE_URL = "https://pro-api.coingecko.com/api/v3"


class CoinGeckoFeed(PriceFeed):
    """CoinGecko REST price feed.

    Uses the free public API when no api_key is provided, or the Pro API otherwise.
    Rate limit: ~30 calls/min (free), 500 calls/min (Pro).
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        base_url = _PRO_BASE_URL if api_key else _BASE_URL
        headers = {"x-cg-pro-api-key": api_key} if api_key else {}
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(15.0),
        )

    @property
    def name(self) -> str:
        return "coingecko"

    def _cg_id(self, symbol: str) -> str:
        """Extract base currency from 'BTC/USDT' and map to CoinGecko ID."""
        base = symbol.split("/")[0].upper()
        cg_id = _SYMBOL_MAP.get(base)
        if not cg_id:
            raise ValueError(f"CoinGeckoFeed: no mapping for symbol {symbol!r}")
        return cg_id

    async def get_ticker(self, symbol: str) -> Ticker:
        cg_id = self._cg_id(symbol)
        resp = await self._client.get(
            "/simple/price",
            params={"ids": cg_id, "vs_currencies": "usd", "include_last_updated_at": "true"},
        )
        resp.raise_for_status()
        data = resp.json()[cg_id]
        price = Decimal(str(data["usd"]))
        ts = data.get("last_updated_at")
        timestamp = (
            datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(tz=timezone.utc)
        )
        logger.debug("[CoinGecko] %s = %s", symbol, price)
        return Ticker(symbol=symbol, price=price, timestamp=timestamp, source=self.name)

    async def get_ohlcv(self, symbol: str, timeframe: str = "1d", limit: int = 100) -> list[OHLCV]:
        cg_id = self._cg_id(symbol)
        days = _TIMEFRAME_DAYS.get(timeframe, 30)
        resp = await self._client.get(
            f"/coins/{cg_id}/ohlc",
            params={"vs_currency": "usd", "days": str(days)},
        )
        resp.raise_for_status()
        rows: list[list[float]] = resp.json()
        candles = [
            OHLCV(
                timestamp=datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc),
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal("0"),  # CoinGecko OHLC endpoint has no volume
            )
            for row in rows[-limit:]
        ]
        logger.debug("[CoinGecko] ohlcv %s days=%d candles=%d", symbol, days, len(candles))
        return candles

    async def subscribe_ticker(self, symbol: str, callback: Callable[[Ticker], Any]) -> None:
        raise NotImplementedError("CoinGecko has no WebSocket feed.")

    async def close(self) -> None:
        await self._client.aclose()
