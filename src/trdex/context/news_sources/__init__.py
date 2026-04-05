"""News/information source implementations."""

from trdex.context.news_sources.base import NewsArticle, NewsSource
from trdex.context.news_sources.cryptocompare import CryptoCompareNewsSource
from trdex.context.news_sources.stockdata import StockDataNewsSource

__all__ = [
    "NewsArticle",
    "NewsSource",
    "CryptoCompareNewsSource",
    "StockDataNewsSource",
]
