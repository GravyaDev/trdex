"""Alpha Vantage REST feed — stocks, FX, crypto, and technical indicators."""

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

_BASE_URL = "https://www.alphavantage.co"

# Map trdex timeframe strings to Alpha Vantage interval/function names
_CRYPTO_TIMEFRAME: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "60min",
    "1d": "DIGITAL_CURRENCY_DAILY",
    "1w": "DIGITAL_CURRENCY_WEEKLY",
}

_EQUITY_TIMEFRAME: dict[str, str] = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "60min",
    "1d": "daily",
    "1w": "weekly",
}

# Symbols we treat as crypto (base/quote pairs)
_CRYPTO_BASES = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX",
    "DOT", "MATIC", "LINK", "UNI", "LTC", "BCH", "ATOM",
}

# Symbols we treat as FX (e.g. EUR/USD)
_FX_CURRENCIES = {
    "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
    "SEK", "NOK", "DKK", "HKD", "SGD", "MXN", "BRL",
}


def _is_crypto(symbol: str) -> bool:
    base = symbol.split("/")[0].upper()
    return base in _CRYPTO_BASES


def _is_fx(symbol: str) -> bool:
    parts = symbol.upper().split("/")
    return len(parts) == 2 and parts[0] in _FX_CURRENCIES and parts[1] in _FX_CURRENCIES


class AlphaVantageFeed(PriceFeed):
    """Alpha Vantage feed supporting stocks, FX pairs, and crypto.

    Detects asset type from symbol format:
    - 'BTC/USDT' or 'ETH/USD' → crypto
    - 'EUR/USD', 'GBP/JPY' → forex
    - 'AAPL', 'MSFT', '^DJI' → equity/index

    Free tier: 25 requests/day (standard) or 500/day with free API key.
    Premium tiers available for higher limits.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("AlphaVantageFeed requires an API key.")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=httpx.Timeout(20.0),
        )

    @property
    def name(self) -> str:
        return "alphavantage"

    async def _query(self, params: dict[str, str]) -> dict:
        params["apikey"] = self._api_key
        resp = await self._client.get("/query", params=params)
        resp.raise_for_status()
        data = resp.json()
        if "Error Message" in data:
            raise ValueError(f"AlphaVantage error: {data['Error Message']}")
        if "Note" in data:
            raise RuntimeError(f"AlphaVantage rate limit: {data['Note']}")
        if "Information" in data:
            raise RuntimeError(f"AlphaVantage limit: {data['Information']}")
        return data

    # ------------------------------------------------------------------ #
    #  Ticker                                                              #
    # ------------------------------------------------------------------ #

    async def get_ticker(self, symbol: str) -> Ticker:
        if _is_crypto(symbol):
            return await self._ticker_crypto(symbol)
        if _is_fx(symbol):
            return await self._ticker_fx(symbol)
        return await self._ticker_equity(symbol)

    async def _ticker_crypto(self, symbol: str) -> Ticker:
        base, quote = symbol.upper().split("/")
        market = quote if quote in ("USD", "EUR", "GBP") else "USD"
        data = await self._query({"function": "CURRENCY_EXCHANGE_RATE", "from_currency": base, "to_currency": market})
        rate = data["Realtime Currency Exchange Rate"]
        price = Decimal(rate["5. Exchange Rate"])
        ts = datetime.strptime(rate["6. Last Refreshed"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        logger.debug("[AlphaVantage] crypto %s = %s", symbol, price)
        return Ticker(symbol=symbol, price=price, timestamp=ts, source=self.name)

    async def _ticker_fx(self, symbol: str) -> Ticker:
        from_cur, to_cur = symbol.upper().split("/")
        data = await self._query({"function": "CURRENCY_EXCHANGE_RATE", "from_currency": from_cur, "to_currency": to_cur})
        rate = data["Realtime Currency Exchange Rate"]
        price = Decimal(rate["5. Exchange Rate"])
        ts = datetime.strptime(rate["6. Last Refreshed"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        logger.debug("[AlphaVantage] fx %s = %s", symbol, price)
        return Ticker(symbol=symbol, price=price, timestamp=ts, source=self.name)

    async def _ticker_equity(self, symbol: str) -> Ticker:
        data = await self._query({"function": "GLOBAL_QUOTE", "symbol": symbol})
        quote = data.get("Global Quote", {})
        if not quote:
            raise ValueError(f"AlphaVantage: no quote for {symbol!r}")
        price = Decimal(quote["05. price"])
        ts_str = quote.get("07. latest trading day", "")
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            ts = datetime.now(tz=timezone.utc)
        logger.debug("[AlphaVantage] equity %s = %s", symbol, price)
        return Ticker(symbol=symbol, price=price, timestamp=ts, source=self.name)

    # ------------------------------------------------------------------ #
    #  OHLCV                                                               #
    # ------------------------------------------------------------------ #

    async def get_ohlcv(self, symbol: str, timeframe: str = "1d", limit: int = 100) -> list[OHLCV]:
        if _is_crypto(symbol):
            return await self._ohlcv_crypto(symbol, timeframe, limit)
        if _is_fx(symbol):
            return await self._ohlcv_fx(symbol, timeframe, limit)
        return await self._ohlcv_equity(symbol, timeframe, limit)

    async def _ohlcv_crypto(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        base, quote = symbol.upper().split("/")
        market = quote if quote in ("USD", "EUR", "GBP") else "USD"
        tf = _CRYPTO_TIMEFRAME.get(timeframe, "DIGITAL_CURRENCY_DAILY")

        if tf in ("DIGITAL_CURRENCY_DAILY", "DIGITAL_CURRENCY_WEEKLY"):
            fn = tf
            data = await self._query({"function": fn, "symbol": base, "market": market})
            key = next((k for k in data if "Time Series" in k), None)
            if not key:
                return []
            series = data[key]
            candles = []
            for ts_str, row in sorted(series.items())[-limit:]:
                ts = datetime.strptime(ts_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                candles.append(OHLCV(
                    timestamp=ts,
                    open=Decimal(row.get(f"1a. open ({market})", row.get("1. open", "0"))),
                    high=Decimal(row.get(f"2a. high ({market})", row.get("2. high", "0"))),
                    low=Decimal(row.get(f"3a. low ({market})", row.get("3. low", "0"))),
                    close=Decimal(row.get(f"4a. close ({market})", row.get("4. close", "0"))),
                    volume=Decimal(row.get("5. volume", "0")),
                ))
        else:
            data = await self._query({"function": "CRYPTO_INTRADAY", "symbol": base, "market": market, "interval": tf, "outputsize": "compact"})
            key = next((k for k in data if "Time Series Crypto" in k), None)
            if not key:
                return []
            series = data[key]
            candles = []
            for ts_str, row in sorted(series.items())[-limit:]:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                candles.append(OHLCV(
                    timestamp=ts,
                    open=Decimal(row["1. open"]),
                    high=Decimal(row["2. high"]),
                    low=Decimal(row["3. low"]),
                    close=Decimal(row["4. close"]),
                    volume=Decimal(row.get("5. volume", "0")),
                ))
        logger.debug("[AlphaVantage] crypto ohlcv %s tf=%s count=%d", symbol, timeframe, len(candles))
        return candles

    async def _ohlcv_fx(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        from_cur, to_cur = symbol.upper().split("/")
        tf = _EQUITY_TIMEFRAME.get(timeframe, "daily")

        if tf in ("daily", "weekly"):
            fn = "FX_DAILY" if tf == "daily" else "FX_WEEKLY"
            data = await self._query({"function": fn, "from_symbol": from_cur, "to_symbol": to_cur, "outputsize": "compact"})
        else:
            data = await self._query({"function": "FX_INTRADAY", "from_symbol": from_cur, "to_symbol": to_cur, "interval": tf, "outputsize": "compact"})

        key = next((k for k in data if "Time Series FX" in k), None)
        if not key:
            return []
        series = data[key]
        candles = []
        for ts_str, row in sorted(series.items())[-limit:]:
            fmt = "%Y-%m-%d %H:%M:%S" if " " in ts_str else "%Y-%m-%d"
            ts = datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
            candles.append(OHLCV(
                timestamp=ts,
                open=Decimal(row["1. open"]),
                high=Decimal(row["2. high"]),
                low=Decimal(row["3. low"]),
                close=Decimal(row["4. close"]),
                volume=Decimal("0"),
            ))
        logger.debug("[AlphaVantage] fx ohlcv %s tf=%s count=%d", symbol, timeframe, len(candles))
        return candles

    async def _ohlcv_equity(self, symbol: str, timeframe: str, limit: int) -> list[OHLCV]:
        tf = _EQUITY_TIMEFRAME.get(timeframe, "daily")

        if tf in ("daily", "weekly", "monthly"):
            fn_map = {"daily": "TIME_SERIES_DAILY", "weekly": "TIME_SERIES_WEEKLY", "monthly": "TIME_SERIES_MONTHLY"}
            data = await self._query({"function": fn_map[tf], "symbol": symbol, "outputsize": "compact"})
        else:
            data = await self._query({"function": "TIME_SERIES_INTRADAY", "symbol": symbol, "interval": tf, "outputsize": "compact"})

        key = next((k for k in data if "Time Series" in k), None)
        if not key:
            return []
        series = data[key]
        candles = []
        for ts_str, row in sorted(series.items())[-limit:]:
            fmt = "%Y-%m-%d %H:%M:%S" if " " in ts_str else "%Y-%m-%d"
            ts = datetime.strptime(ts_str, fmt).replace(tzinfo=timezone.utc)
            candles.append(OHLCV(
                timestamp=ts,
                open=Decimal(row["1. open"]),
                high=Decimal(row["2. high"]),
                low=Decimal(row["3. low"]),
                close=Decimal(row["4. close"]),
                volume=Decimal(row.get("5. volume", "0")),
            ))
        logger.debug("[AlphaVantage] equity ohlcv %s tf=%s count=%d", symbol, timeframe, len(candles))
        return candles

    async def subscribe_ticker(self, symbol: str, callback: Callable[[Ticker], Any]) -> None:
        raise NotImplementedError("AlphaVantage has no WebSocket feed.")

    async def close(self) -> None:
        await self._client.aclose()
