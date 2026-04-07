"""Abstract base classes for price feeds."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from trdex.market.models import OHLCV, Ticker


class PriceFeed(ABC):
    """Interface for all market data price feeds.

    Implementations: BinanceFeed (REST via CCXT), CoinGeckoFeed, ForexFeed.
    """

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """Get current price for a symbol."""
        ...

    @abstractmethod
    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 100,
        since: int | None = None,
    ) -> list[OHLCV]:
        """Get historical candlestick data.

        Args:
            symbol: trading pair, e.g. "BTC/USDT".
            timeframe: feed-native timeframe string ("1m", "1h", "1d", ...).
            limit: max candles to return.
            since: optional millisecond UTC epoch lower bound. Feeds that
                support paginated history (Binance, CryptoCompare) will
                return candles with ``open_time >= since``. Feeds that
                cannot honour the parameter MUST accept and ignore it.
        """
        ...

    @abstractmethod
    async def subscribe_ticker(self, symbol: str, callback: Callable[[Ticker], Any]) -> None:
        """Subscribe to real-time price updates (where supported)."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close all connections and release resources."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Feed source identifier."""
        ...
