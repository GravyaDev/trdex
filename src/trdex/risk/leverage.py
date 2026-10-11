"""Derivatives venue, leverage and liquidation (shared by live, Telegram, backtest).

Sizing is risk-based (notional = risk / stop), so leverage never changes
what a stop-out loses: it only reduces the margin locked for that
notional. What leverage adds is the chance of being liquidated before
the stop. Each leveraged entry therefore gets the largest leverage, up
to ``max_leverage``, whose liquidation distance keeps the stop inside
``buffer`` of it, and is rejected if not even 1x does.

Isolated margin, one maintenance-margin rate (tiers approximated), fees
ignored in the liquidation distance: ``liq(L) = 1/L - mmr``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

VENUES = ("usdm", "spot")
DEFAULT_VENUE = "usdm"
DEFAULT_MAX_LEVERAGE = 3.0
MAX_LEVERAGE_LIMIT = 20.0  # sanity bound on the setting
DEFAULT_MMR = 0.005
DEFAULT_BUFFER = 0.5
DEFAULT_FUNDING_8H = 0.0001  # Binance's baseline (interest component) per 8h
FUNDING_HOURS = (0, 8, 16)


@dataclass(frozen=True)
class DerivativesConfig:
    venue: str = DEFAULT_VENUE
    max_leverage: float = DEFAULT_MAX_LEVERAGE
    mmr: float = DEFAULT_MMR
    buffer: float = DEFAULT_BUFFER
    funding_rate_8h: float = DEFAULT_FUNDING_8H

    @property
    def perps(self) -> bool:
        """Positions are perpetuals: shorts, leverage, funding, liquidation."""
        return self.venue == "usdm"


SPOT = DerivativesConfig(venue="spot")


def derivatives_config(cfg: Any) -> DerivativesConfig:
    """From Runtime Config ``thresholds``; blank -> default, nonsense raises."""
    if cfg is None:
        return DerivativesConfig()

    def raw(key: str) -> str:
        return str(cfg.get("thresholds", key, "") or "").strip()

    def num(key: str, default: float, lo: float, hi: float) -> float:
        text = raw(key)
        if not text:
            return default
        value = float(text)
        if not lo <= value <= hi:  # also rejects nan
            raise ValueError(f"{key} must be between {lo} and {hi}, got {text}")
        return value

    venue = raw("execution_venue").lower() or DEFAULT_VENUE
    if venue not in VENUES:
        raise ValueError(f"execution_venue must be one of {VENUES}, got {venue!r}")
    return DerivativesConfig(
        venue=venue,
        max_leverage=num("max_leverage", DEFAULT_MAX_LEVERAGE, 1.0, MAX_LEVERAGE_LIMIT),
        mmr=num("maintenance_margin_rate", DEFAULT_MMR, 0.0, 0.1),
        buffer=num("liquidation_buffer", DEFAULT_BUFFER, 0.05, 1.0),
        funding_rate_8h=num("funding_rate_8h", DEFAULT_FUNDING_8H, -0.01, 0.01),
    )


def liquidation_distance(leverage: float, mmr: float) -> float:
    """Adverse move (fraction of entry) that liquidates an isolated position."""
    return 1.0 / leverage - mmr


def choose_leverage(stop_pct: float, dc: DerivativesConfig) -> tuple[int | None, str]:
    """(leverage, note) for an entry with this stop; (None, reason) to reject.

    Spot: always 1x, nothing to liquidate.
    """
    if not dc.perps:
        return 1, ""
    if stop_pct <= 0:
        return None, f"stop {stop_pct:.2%} is not a loss distance"
    limit = 1.0 / (stop_pct / dc.buffer + dc.mmr)
    lev = math.floor(min(dc.max_leverage, limit) + 1e-9)
    if lev < 1:
        return None, (
            f"stop {stop_pct:.2%} too wide for any leverage: liquidation at 1x is "
            f"{liquidation_distance(1, dc.mmr):.2%} away and the stop must stay within "
            f"{dc.buffer:.0%} of it"
        )
    note = (
        f" Leverage {lev}x (liquidation {liquidation_distance(lev, dc.mmr):.2%} away, "
        f"stop {stop_pct:.2%})."
    )
    return lev, note


def liquidation_price(entry: float, side: str, leverage: float, mmr: float) -> float:
    """Price at which an isolated position is liquidated (side BUY/SELL)."""
    d = liquidation_distance(leverage, mmr)
    return entry * (1 - d) if side == "BUY" else entry * (1 + d)


def funding_times(start: datetime, end: datetime) -> list[datetime]:
    """Funding timestamps (00, 08, 16 UTC) in (start, end]."""
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    t = start.replace(minute=0, second=0, microsecond=0)
    t = t.replace(hour=(t.hour // 8) * 8)
    out = []
    while t <= end:
        if t > start:
            out.append(t)
        t += timedelta(hours=8)
    return out


def funding_cash(side: str, qty: float, price: float, rate: float) -> float:
    """Cash change at one funding time: longs pay a positive rate, shorts receive."""
    paid = qty * price * rate
    return -paid if side == "BUY" else paid
