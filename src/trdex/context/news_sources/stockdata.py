"""StockData.org news source — financial news for stocks, FX, and crypto."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from trdex.context.news_sources.base import NewsArticle, NewsSource

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.stockdata.org/v1"


class StockDataNewsSource(NewsSource):
    """Fetches financial news from StockData.org.

    Covers stocks, FX, and crypto across 150k+ tickers from 70 exchanges.
    Returns sentiment scores where available from the API.
    Free tier available at stockdata.org.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("StockDataNewsSource requires an API key.")
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            timeout=httpx.Timeout(15.0),
        )

    @property
    def name(self) -> str:
        return "stockdata_news"

    def _parse_sentiment(self, value: float | None) -> float | None:
        """StockData returns sentiment in [-1, 1] range already."""
        if value is None:
            return None
        return max(-1.0, min(1.0, float(value)))

    def _symbol_to_ticker(self, symbol: str) -> str:
        """Convert 'BTC/USDT' → 'BTC', 'AAPL' → 'AAPL', 'EUR/USD' → 'EUR'."""
        return symbol.split("/")[0].upper()

    async def fetch(self, symbol: str | None = None, limit: int = 50) -> list[NewsArticle]:
        params: dict[str, str | int] = {
            "api_token": self._api_key,
            "limit": min(limit, 100),
            "language": "en",
            "sort": "published_desc",
        }

        if symbol:
            params["symbols"] = self._symbol_to_ticker(symbol)

        resp = await self._client.get("/news/all", params=params)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            raise ValueError(f"StockDataNews error: {data['error'].get('message', 'unknown')}")

        articles = []
        for item in data.get("data", [])[:limit]:
            try:
                published_at = datetime.fromisoformat(
                    item["published_at"].replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except (ValueError, KeyError):
                published_at = datetime.now(tz=timezone.utc)

            # StockData provides per-entity sentiment in entities[] array
            sentiment: float | None = None
            for entity in item.get("entities", []):
                if entity.get("sentiment_score") is not None:
                    sentiment = self._parse_sentiment(entity["sentiment_score"])
                    break

            articles.append(NewsArticle(
                title=item.get("title", ""),
                body=item.get("description", ""),
                url=item.get("url", ""),
                source=self.name,
                published_at=published_at,
                symbol=symbol,
                sentiment=sentiment,
            ))

        logger.info("[StockDataNews] fetched %d articles (symbol=%s)", len(articles), symbol)
        return articles

    async def close(self) -> None:
        await self._client.aclose()
