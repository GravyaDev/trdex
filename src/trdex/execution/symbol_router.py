"""Symbol router — maps a symbol to its (PriceFeed, ExecutionGateway) pair.

Today crypto-only. Non-crypto symbols raise SymbolNotRoutable; the
Telegram executor treats that as a skip-with-reason and moves on.
When the Multi-asset Forex epic (OandaFeed + OandaExecutor) lands,
this router gains a forex branch.

The router does not own feed/gateway instances — callers inject them.
Keeps symbol_router.py pure and testable without infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trdex.execution.gateway import ExecutionGateway
    from trdex.market.feeds.base import PriceFeed


class SymbolNotRoutable(ValueError):
    """Raised when no (feed, gateway) pair is available for this symbol.

    The Telegram executor catches this exception and skips the signal
    with a logged reason. Non-fatal.
    """


# Quote currencies recognized as crypto. If the symbol is "BASE/QUOTE"
# with QUOTE in this set, treat as crypto. Otherwise non-crypto.
_CRYPTO_QUOTES: frozenset[str] = frozenset({
    "USDT", "USDC", "BUSD", "DAI", "BTC", "ETH", "BNB", "FDUSD", "TUSD",
})


def is_crypto(symbol: str) -> bool:
    """True if `symbol` looks like a crypto pair (BASE/CRYPTO_QUOTE)."""
    if not symbol or "/" not in symbol:
        return False
    _, _, quote = symbol.partition("/")
    return quote.upper() in _CRYPTO_QUOTES


def route(
    symbol: str,
    *,
    feed: PriceFeed,
    gateway: ExecutionGateway,
) -> tuple[PriceFeed, ExecutionGateway]:
    """Return the (feed, gateway) pair that should handle `symbol`.

    Raises SymbolNotRoutable for any non-crypto symbol.
    """
    if is_crypto(symbol):
        return feed, gateway
    raise SymbolNotRoutable(
        f"No executor available for symbol {symbol!r} "
        f"(crypto-only today; forex/commodity deferred to Multi-asset epic)"
    )
