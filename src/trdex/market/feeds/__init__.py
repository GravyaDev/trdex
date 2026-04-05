"""Market data feed implementations."""

from trdex.market.feeds.alphavantage import AlphaVantageFeed
from trdex.market.feeds.binance import BinanceFeed
from trdex.market.feeds.binance_ws import BinanceWSFeed
from trdex.market.feeds.coingecko import CoinGeckoFeed
from trdex.market.feeds.cryptocompare import CryptoCompareFeed
from trdex.market.feeds.forex import ForexFeed
from trdex.market.feeds.freecryptoapi import FreeCryptoAPIFeed

__all__ = [
    "AlphaVantageFeed",
    "BinanceFeed",
    "BinanceWSFeed",
    "CoinGeckoFeed",
    "CryptoCompareFeed",
    "ForexFeed",
    "FreeCryptoAPIFeed",
]
