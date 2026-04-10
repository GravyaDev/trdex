"""Market hours utilities — determines if a market is open for trading."""

from __future__ import annotations

from datetime import datetime, timezone

# Forex market: Sunday 22:00 UTC → Friday 22:00 UTC
# Crypto: 24/7/365
# Stocks: not yet supported

_FOREX_QUOTES = {"USD", "EUR", "GBP", "JPY", "CAD", "CHF", "AUD", "NZD"}
_METAL_BASES = {"XAU", "XAG", "XPT", "XPD"}


def is_forex(symbol: str) -> bool:
    """True if the symbol is a Forex or metals pair (not crypto)."""
    parts = symbol.upper().replace("-", "/").replace("_", "/").split("/")
    if len(parts) != 2:
        return False
    base, quote = parts
    if base in _METAL_BASES:
        return True
    if quote in _FOREX_QUOTES and base in _FOREX_QUOTES:
        return True
    return False


def is_market_open(symbol: str, now: datetime | None = None) -> bool:
    """Check if the market for the given symbol is currently open.

    Crypto: always open.
    Forex/metals: open Sunday 22:00 UTC to Friday 22:00 UTC.
    """
    if not is_forex(symbol):
        return True  # crypto is 24/7

    now = now or datetime.now(tz=timezone.utc)
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    hour = now.hour

    # Closed: Friday 22:00+ through Sunday 21:59
    if weekday == 4 and hour >= 22:  # Friday after 22:00
        return False
    if weekday == 5:  # Saturday — all day closed
        return False
    if weekday == 6 and hour < 22:  # Sunday before 22:00
        return False
    return True
