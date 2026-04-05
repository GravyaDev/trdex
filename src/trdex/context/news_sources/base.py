"""Abstract base class for news/information sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NewsArticle:
    """A single news item fetched from an external source."""

    title: str
    body: str
    url: str
    source: str          # e.g. "cryptocompare", "stockdata"
    published_at: datetime
    symbol: str | None = None   # e.g. "BTC/USDT" — None = global market news
    sentiment: float | None = None  # -1.0 … +1.0 if provided by the source

    @property
    def full_text(self) -> str:
        """Title + body combined for embedding."""
        return f"{self.title}\n\n{self.body}".strip()


class NewsSource(ABC):
    """Interface for all external news/information sources."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Source identifier used as payload field in Qdrant."""
        ...

    @abstractmethod
    async def fetch(
        self,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[NewsArticle]:
        """Fetch recent articles, optionally filtered by symbol/asset.

        Args:
            symbol: Asset symbol like 'BTC/USDT'. None = general market news.
            limit: Maximum number of articles to return.

        Returns:
            List of NewsArticle objects sorted by published_at descending.
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release HTTP client resources."""
        ...
