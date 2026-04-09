"""Market specifications cache — lot size, precision, min notional.

Loads market specs from CCXT once at app startup (lifespan) and
caches them for the duration of the process. Used by the Simulator
and LiveExecutor to truncate order quantities to valid step sizes
before placing orders.

Without this, the Simulator produces fractional quantities like
6407.7529 ENJ when ENJ's lot size is 1 whole token — fine in
simulation but would be rejected by Binance in live mode.
"""

from __future__ import annotations

import logging
from decimal import ROUND_DOWN, Decimal
from typing import Any

logger = logging.getLogger(__name__)

# Module-level cache — populated once by load() at app startup.
_markets: dict[str, dict[str, Any]] = {}
_loaded = False


async def load(exchange) -> int:
    """Load market specs from a CCXT exchange instance.

    Call once at lifespan startup. Returns the number of markets loaded.
    The exchange must support ``load_markets()`` (all CCXT exchanges do).
    """
    global _markets, _loaded
    try:
        raw = await exchange.load_markets()
        _markets = raw
        _loaded = True
        logger.info("[MarketSpecs] loaded %d markets from %s", len(_markets), exchange.id)
        return len(_markets)
    except Exception:
        logger.exception("[MarketSpecs] failed to load markets — lot size truncation disabled")
        return 0


def is_loaded() -> bool:
    return _loaded


def get_amount_precision(symbol: str) -> int | None:
    """Number of decimal places for the amount (quantity) field.

    Returns None if the symbol is not in the cache.
    """
    m = _markets.get(symbol)
    if not m:
        return None
    prec = m.get("precision", {}).get("amount")
    if prec is None:
        return None
    return int(prec)


def get_step_size(symbol: str) -> Decimal | None:
    """Minimum quantity increment (lot size step) for a symbol.

    Returns None if not available. Example: ENJ/USDT → Decimal("1"),
    BTC/USDT → Decimal("0.00001").
    """
    m = _markets.get(symbol)
    if not m:
        return None
    limits = m.get("limits", {}).get("amount", {})
    step = limits.get("min")
    if step is not None:
        return Decimal(str(step))
    # Fallback: derive from precision
    prec = get_amount_precision(symbol)
    if prec is not None:
        return Decimal(10) ** -prec
    return None


def get_min_notional(symbol: str) -> Decimal | None:
    """Minimum order value in quote currency (e.g. USDT).

    Returns None if not available. Binance typically requires $5-10
    minimum per order depending on the pair.
    """
    m = _markets.get(symbol)
    if not m:
        return None
    cost_min = m.get("limits", {}).get("cost", {}).get("min")
    if cost_min is not None:
        return Decimal(str(cost_min))
    return None


def truncate_qty(symbol: str, qty: Decimal) -> Decimal:
    """Truncate a quantity to the nearest valid step size (round down).

    If the symbol is not in the cache, returns qty unchanged (graceful
    degradation — the caller should log a warning).

    Examples:
        truncate_qty("ENJ/USDT", Decimal("6407.7529"))  → Decimal("6407")
        truncate_qty("BTC/USDT", Decimal("0.002804"))   → Decimal("0.00280")
    """
    step = get_step_size(symbol)
    if step is None or step <= 0:
        return qty
    # Truncate: floor(qty / step) * step
    return (qty / step).to_integral_value(rounding=ROUND_DOWN) * step


def get_specs_summary(symbol: str) -> dict[str, Any] | None:
    """Return a human-readable summary of market specs for a symbol."""
    m = _markets.get(symbol)
    if not m:
        return None
    return {
        "symbol": symbol,
        "step_size": str(get_step_size(symbol)),
        "min_notional": str(get_min_notional(symbol)),
        "amount_precision": get_amount_precision(symbol),
        "price_precision": m.get("precision", {}).get("price"),
    }
