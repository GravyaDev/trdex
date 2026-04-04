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
    async def get_ohlcv(self, symbol: str, timeframe: str = "1m", limit: int = 100) -> list[OHLCV]:
        """Get historical candlestick data."""
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
