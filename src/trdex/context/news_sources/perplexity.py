"""Perplexity Sonar news source — LLM-native search for market-moving news.

Unlike CryptoCompare/StockData which return raw article lists, Perplexity
returns synthesised narratives with citations. This produces denser,
higher-signal context documents for the Qdrant vector store, improving
Scout/Analyst retrieval quality.

Uses the Perplexity Sonar API (chat completions endpoint with
search_recency_filter for freshness). Each fetch() call makes one API
request per symbol with a market-focused prompt.

Cost: ~$0.005/call (sonar model). With 5 symbols × 12 cycles/hour ×
14 active hours = ~840 calls/day ≈ $4.20/day ≈ $126/month.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from trdex.context.news_sources.base import NewsArticle, NewsSource

logger = logging.getLogger(__name__)

_API_URL = "https://api.perplexity.ai/chat/completions"
_DEFAULT_MODEL = "sonar"

_PROMPT_TEMPLATE = """\
What are the most significant news and events for {symbol} in the last \
{minutes} minutes? Focus on:
- Price-impacting events (large trades, liquidations, exchange listings/delistings)
- Regulatory actions or government statements affecting crypto
- Macro economic events that could impact {base_asset} specifically
- Social media sentiment shifts or influential commentary
- Technical milestones (network upgrades, protocol changes, partnerships)

Be concise and factual. Cite sources. If there is no significant news, \
say "No significant news for {symbol} in this period." and nothing else.\
"""


class PerplexityNewsSource(NewsSource):
    """Fetches market-moving news via Perplexity Sonar search API.

    Each call to fetch() makes one Sonar API request that searches the
    web for recent news about the given symbol, synthesises the results
    into a narrative paragraph with citations, and returns it as a
    single NewsArticle (the synthesis) plus one article per citation
    (for granular vector store retrieval).
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        recency_minutes: int = 30,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._recency_minutes = recency_minutes
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    @property
    def name(self) -> str:
        return "perplexity_sonar"

    async def fetch(self, symbol: str | None = None, limit: int = 50) -> list[NewsArticle]:
        if not symbol:
            symbol = "crypto market"

        base_asset = symbol.split("/")[0] if "/" in symbol else symbol
        prompt = _PROMPT_TEMPLATE.format(
            symbol=symbol,
            base_asset=base_asset,
            minutes=self._recency_minutes,
        )

        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a financial news analyst. Report only verified, "
                        "factual information with source citations. Be concise."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "search_recency_filter": "day",
            "return_citations": True,
        }

        try:
            resp = await self._client.post(_API_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "[Perplexity] API error %s for %s: %s",
                exc.response.status_code, symbol, exc.response.text[:200],
            )
            return []
        except Exception as exc:
            logger.warning("[Perplexity] request failed for %s: %s", symbol, exc)
            return []

        # Extract the synthesis text
        choices = data.get("choices", [])
        if not choices:
            logger.warning("[Perplexity] empty response for %s", symbol)
            return []

        synthesis = choices[0].get("message", {}).get("content", "")
        if not synthesis or "no significant news" in synthesis.lower():
            logger.debug("[Perplexity] no significant news for %s", symbol)
            return []

        now = datetime.now(tz=timezone.utc)
        articles: list[NewsArticle] = []

        # Main synthesis as one dense document
        articles.append(NewsArticle(
            title=f"Perplexity market brief: {symbol}",
            body=synthesis,
            url="",
            source=self.name,
            published_at=now,
            symbol=symbol,
            sentiment=None,  # LLM synthesis, no numeric sentiment
        ))

        # Individual citations as separate documents (for granular retrieval)
        citations = data.get("citations", [])
        for i, url in enumerate(citations[:limit - 1]):
            if isinstance(url, str) and url.startswith("http"):
                articles.append(NewsArticle(
                    title=f"[{i + 1}] Source for {symbol}",
                    body=f"Citation from Perplexity search: {url}",
                    url=url,
                    source=self.name,
                    published_at=now,
                    symbol=symbol,
                    sentiment=None,
                ))

        logger.info(
            "[Perplexity] fetched %d articles for %s (%d citations)",
            len(articles), symbol, len(citations),
        )
        return articles

    async def close(self) -> None:
        await self._client.aclose()
