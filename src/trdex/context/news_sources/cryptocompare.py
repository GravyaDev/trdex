"""CryptoCompare news source — crypto news with sentiment scores."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from trdex.context.news_sources.base import NewsArticle, NewsSource

logger = logging.getLogger(__name__)

_BASE_URL = "https://min-api.cryptocompare.com"


class CryptoCompareNewsSource(NewsSource):
    """Fetches crypto news from CryptoCompare /data/v2/news/ endpoint.

    Provides sentiment scores (-1.0 to +1.0) when available.
    Free tier requires API key. Rate limit: ~100 calls/sec.

    Supports coin-specific filtering: pass symbol='BTC/USDT' to get
    news tagged with BTC.
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
        return "cryptocompare_news"

    def _sentiment(self, article: dict) -> float | None:
        """Map CryptoCompare sentiment labels to float score."""
        raw = article.get("sentiment", "")
        mapping = {"Positive": 0.6, "Negative": -0.6, "Neutral": 0.0}
        return mapping.get(raw)

    async def fetch(self, symbol: str | None = None, limit: int = 50) -> list[NewsArticle]:
        params: dict[str, str | int] = {"sortOrder": "latest", "limit": min(limit, 100)}

        if symbol:
            base = symbol.split("/")[0].upper()
            params["categories"] = base

        resp = await self._client.get("/data/v2/news/", params=params)
        resp.raise_for_status()
        data = resp.json()

        if data.get("Response") == "Error":
            raise ValueError(f"CryptoCompareNews error: {data.get('Message')}")

        articles = []
        for item in data.get("Data", [])[:limit]:
            published_at = datetime.fromtimestamp(item["published_on"], tz=timezone.utc)
            articles.append(NewsArticle(
                title=item.get("title", ""),
                body=item.get("body", ""),
                url=item.get("url", ""),
                source=self.name,
                published_at=published_at,
                symbol=symbol,
                sentiment=self._sentiment(item),
            ))

        logger.info("[CryptoCompareNews] fetched %d articles (symbol=%s)", len(articles), symbol)
        return articles

    async def close(self) -> None:
        await self._client.aclose()
