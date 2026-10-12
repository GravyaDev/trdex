"""Risk-based position sizing and volatility-regime gate.

Pure functions shared by the live Risk node (``agents/risk.py``) and the
backtest replay (``scripts/backtest/strategies.py:LiveRuleEngine``), so
the two cannot drift apart.

Sizing
------
Before this module every agent entry committed the same notional
fraction of equity (``max_position_pct``, 5%), whatever the stop. The
StopLossMonitor's stop ranges from the configured base (2%) up to
2.5 x CV on volatile coins (~32% for a CV of 13%), so the equity lost at
the stop varied by an order of magnitude between trades. Risk-based
sizing commits ``risk_per_trade / stop`` instead, capped at the notional
maximum, so every trade risks the same fraction of equity at entry.

Regime gate
-----------
A strategy's backtest only says something about the volatility
conditions it was tested in. ``check_regime`` blocks entries whose CV is
outside the range measured on the backtest's development period
(``scripts/backtest/regime_range.py``).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass

# Window of the coefficient of variation. Must match what the Analyst
# writes to the entity graph (agents/analyst.py), because the
# StopLossMonitor reads that value back to compute the adaptive stop.
VOL_WINDOW = 20


def recent_cv(closes: Sequence[float], window: int = VOL_WINDOW) -> float | None:
    """Coefficient of variation (sample stdev / mean) of the last ``window`` closes.

    Same formula as the Analyst: ``None`` with fewer than 3 closes or a
    zero mean.
    """
    tail = list(closes[-window:])
    if len(tail) < 3:
        return None
    mean = statistics.mean(tail)
    if mean == 0:
        return None
    return statistics.stdev(tail) / mean


def risk_position_fraction(
    *,
    risk_per_trade: float,
    stop_pct: float,
    max_fraction: float,
) -> float:
    """Fraction of equity to commit so that hitting the stop loses ``risk_per_trade``.

    ``min(max_fraction, risk_per_trade / stop_pct)``. The cap keeps
    tight-stop trades from growing beyond the notional limit.

    Raises ``ValueError`` on non-positive inputs: the caller must block
    the trade rather than guess a size.
    """
    if stop_pct <= 0:
        raise ValueError(f"stop_pct must be > 0, got {stop_pct}")
    if risk_per_trade <= 0:
        raise ValueError(f"risk_per_trade must be > 0, got {risk_per_trade}")
    if max_fraction <= 0:
        raise ValueError(f"max_fraction must be > 0, got {max_fraction}")
    return min(max_fraction, risk_per_trade / stop_pct)


@dataclass(frozen=True)
class RegimeBounds:
    """CV range the strategy was tested on. ``None`` = no bound on that side."""

    cv_min: float | None = None
    cv_max: float | None = None

    @classmethod
    def from_config(cls, cv_min: float | None, cv_max: float | None) -> RegimeBounds:
        """Normalise config values: non-positive means unset.

        Runtime Config coerces an empty float to 0.0, which must not turn
        into "block everything above CV 0".
        """
        lo = cv_min if cv_min is not None and cv_min > 0 else None
        hi = cv_max if cv_max is not None and cv_max > 0 else None
        if lo is not None and hi is not None and lo > hi:
            raise ValueError(f"regime_cv_min {lo} > regime_cv_max {hi}")
        return cls(cv_min=lo, cv_max=hi)

    @property
    def configured(self) -> bool:
        return self.cv_min is not None or self.cv_max is not None


def check_regime(cv: float | None, bounds: RegimeBounds) -> str | None:
    """Return ``None`` if an entry is allowed, otherwise the reason it is not.

    Unconfigured bounds allow everything: whether that is acceptable is
    the caller's decision (the Risk node fails closed in live mode).
    """
    if not bounds.configured:
        return None
    if cv is None:
        return "volatility unknown (fewer than 3 closes)"
    if bounds.cv_min is not None and cv < bounds.cv_min:
        return f"CV {cv:.4f} below tested range (min {bounds.cv_min:.4f})"
    if bounds.cv_max is not None and cv > bounds.cv_max:
        return f"CV {cv:.4f} above tested range (max {bounds.cv_max:.4f})"
    return None
