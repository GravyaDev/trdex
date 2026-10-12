"""Research helpers: sealed holdout, seasonality tests, volatility-regime range.

Rules these helpers enforce, because a research loop that ignores them
finds "edges" by chance:

- Only the development period is ever analysed: the most recent
  ``holdout`` fraction of the sample is cut off before any statistic is
  computed (``dev_period``). It stays sealed for one final test.
- Returns are net of fees with the backtest engine's cost model (taker
  fee on entry and exit), so a window must beat ~20 bps round trip.
- Symbols are combined into one equal-weight basket per timestamp, so
  ten highly correlated coins do not count as ten independent samples.
- Every bucket tested is a hypothesis: p-values are corrected for the
  number of tests (Holm and Benjamini-Hochberg), including windows
  already tried before (``prior_tests``), and an "edge" must also hold in
  every sub-period of the development sample.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

import numpy as np

from trdex.risk.sizing import VOL_WINDOW

Bucket = Literal["hour", "weekday", "hour_of_week"]

# Windows already evaluated on this data before this tool existed. Count
# them in the multiple-testing correction:
# - 13-22 UTC, used by TimeFilterLive and ZanniLikeScalp (run_suite).
# If agent_scheduler_active_hours is ever set from a seasonality result,
# that choice is one more tested window.
PRIOR_TIME_WINDOW_TESTS = 1


# ── sealed holdout ────────────────────────────────────────────────────────


def dev_period(
    ohlcv_by_symbol: dict[str, list[list]], holdout: float
) -> tuple[dict[str, list[list]], int]:
    """Drop the most recent ``holdout`` fraction of the sample (by time).

    The cutoff is one timestamp for all symbols, so the sealed period is
    the same calendar window everywhere. Returns (dev bars, cutoff_ts_ms):
    every returned bar has ``ts < cutoff``.
    """
    if not 0.0 < holdout < 1.0:
        raise ValueError(f"holdout must be in (0, 1), got {holdout}")
    stamps = [bars[i][0] for bars in ohlcv_by_symbol.values() for i in (0, -1) if bars]
    if not stamps:
        raise ValueError("no bars")
    start, end = min(stamps), max(stamps)
    cutoff = start + int((end - start) * (1.0 - holdout))
    dev = {sym: [b for b in bars if b[0] < cutoff] for sym, bars in ohlcv_by_symbol.items()}
    return dev, cutoff


def data_end(ohlcv_by_symbol: dict[str, list[list]]) -> int:
    """Timestamp (ms) of the most recent bar across all symbols.

    This is what ``regime_data_end`` records: the readiness gate rejects
    regime bounds whose data set ends more than regime_max_age_days ago.
    """
    stamps = [bars[-1][0] for bars in ohlcv_by_symbol.values() if bars]
    if not stamps:
        raise ValueError("no bars")
    return max(stamps)


# ── seasonality ───────────────────────────────────────────────────────────


def bucket_of(ts_ms: int, by: Bucket) -> int:
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=UTC)
    if by == "hour":
        return dt.hour
    if by == "weekday":
        return dt.weekday()
    if by == "hour_of_week":
        return dt.weekday() * 24 + dt.hour
    raise ValueError(f"unknown bucket {by!r}")


def basket_returns(
    ohlcv_by_symbol: dict[str, list[list]],
    *,
    horizon: int = 1,
    fee_pct: float = 0.001,
) -> list[tuple[int, float]]:
    """Net return of a long entered at the open of each bar, exited at the
    close ``horizon`` bars later, averaged across symbols per timestamp.

    Cost model as the backtest engine: fee on entry and on exit, so the
    net return is ``close / open * (1 - fee)**2 - 1``.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")
    per_ts: dict[int, list[float]] = defaultdict(list)
    keep = (1.0 - fee_pct) ** 2
    for bars in ohlcv_by_symbol.values():
        for i in range(len(bars) - horizon + 1):
            o = bars[i][1]
            c = bars[i + horizon - 1][4]
            if o > 0:
                per_ts[bars[i][0]].append(c / o * keep - 1.0)
    return sorted((ts, sum(v) / len(v)) for ts, v in per_ts.items())


def _one_sided_p(mean: float, sd: float, n: int) -> float:
    """P(mean > 0) test, normal approximation (n per bucket is large)."""
    if n < 2 or sd == 0:
        return 1.0 if mean <= 0 else 0.0
    z = mean / (sd / math.sqrt(n))
    return 0.5 * math.erfc(z / math.sqrt(2))


def holm(pvalues: list[float], m: int | None = None) -> list[float]:
    """Holm step-down adjusted p-values. ``m`` >= len(pvalues) counts extra
    hypotheses tested elsewhere (assumed to rank after these: conservative)."""
    n = len(pvalues)
    m = n if m is None else m
    if m < n:
        raise ValueError("m must be >= number of p-values")
    order = sorted(range(n), key=lambda i: pvalues[i])
    adj = [0.0] * n
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adj[i] = running
    return adj


def benjamini_hochberg(pvalues: list[float], m: int | None = None) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (FDR). ``m`` as in ``holm``."""
    n = len(pvalues)
    m = n if m is None else m
    if m < n:
        raise ValueError("m must be >= number of p-values")
    order = sorted(range(n), key=lambda i: pvalues[i])
    adj = [0.0] * n
    running = 1.0
    for rank in range(n - 1, -1, -1):
        i = order[rank]
        running = min(running, pvalues[i] * m / (rank + 1))
        adj[i] = min(1.0, running)
    return adj


@dataclass
class BucketStat:
    bucket: int
    n: int
    mean: float
    sd: float
    p: float
    p_holm: float = 1.0
    p_bh: float = 1.0
    split_means: list[float] = field(default_factory=list)

    @property
    def stable(self) -> bool:
        """Positive mean in every sub-period of the development sample."""
        return bool(self.split_means) and all(m > 0 for m in self.split_means)

    def significant(self, alpha: float = 0.05) -> bool:
        return self.mean > 0 and self.p_holm < alpha and self.stable


def seasonality(
    returns: list[tuple[int, float]],
    *,
    by: Bucket,
    horizon: int = 1,
    n_splits: int = 3,
    prior_tests: int = PRIOR_TIME_WINDOW_TESTS,
) -> tuple[list[BucketStat], int]:
    """Per-bucket mean net return, one-sided p (H1: mean > 0), Holm and BH
    adjusted over ``buckets + prior_tests`` hypotheses, and the mean in each
    of ``n_splits`` equal-time sub-periods. Returns (stats, m_total).

    With ``horizon > 1`` the observations of a weekday bucket overlap
    (24 consecutive entries per day), which overstates significance:
    that combination is refused.
    """
    if by == "weekday" and horizon > 1:
        raise ValueError("weekday buckets with horizon > 1 overlap; use hour or hour_of_week")
    if not returns:
        return [], prior_tests
    t0, t1 = returns[0][0], returns[-1][0]
    span = max(1, t1 - t0 + 1)
    groups: dict[int, list[float]] = defaultdict(list)
    split_groups: dict[int, list[list[float]]] = defaultdict(lambda: [[] for _ in range(n_splits)])
    for ts, r in returns:
        b = bucket_of(ts, by)
        groups[b].append(r)
        split_groups[b][min(n_splits - 1, (ts - t0) * n_splits // span)].append(r)

    stats: list[BucketStat] = []
    for b in sorted(groups):
        xs = np.asarray(groups[b], dtype=float)
        n = len(xs)
        mean = float(xs.mean())
        sd = float(xs.std(ddof=1)) if n > 1 else 0.0
        stats.append(
            BucketStat(
                bucket=b,
                n=n,
                mean=mean,
                sd=sd,
                p=_one_sided_p(mean, sd, n),
                split_means=[float(np.mean(s)) if s else 0.0 for s in split_groups[b]],
            )
        )
    m_total = len(stats) + prior_tests
    for s, ph, pb in zip(
        stats,
        holm([s.p for s in stats], m_total),
        benjamini_hochberg([s.p for s in stats], m_total),
        strict=True,
    ):
        s.p_holm, s.p_bh = ph, pb
    return stats, m_total


# ── volatility regime ────────────────────────────────────────────────────


def cv_series(closes: list[float], window: int = VOL_WINDOW) -> np.ndarray:
    """``recent_cv`` of every trailing ``window`` of closes (vectorised).

    Element k is the CV of ``closes[k : k + window]``; same sample-stdev
    formula as ``trdex.risk.sizing.recent_cv`` (the live Analyst / gate).
    """
    x = np.asarray(closes, dtype=float)
    if len(x) < window:
        return np.empty(0)
    w = np.lib.stride_tricks.sliding_window_view(x, window)
    mean = w.mean(axis=1)
    sd = w.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        cv = sd / mean
    return cv[np.isfinite(cv)]


def regime_range(
    ohlcv_by_symbol: dict[str, list[list]],
    *,
    lo_pct: float = 0.5,
    hi_pct: float = 99.5,
) -> dict[str, tuple[float, float, float, int]]:
    """Per symbol and pooled ("*"): (CV p_lo, median, p_hi, n) over the bars given.

    Feed it the development period only: the bounds describe the
    conditions the strategy was tested on.
    """
    out: dict[str, tuple[float, float, float, int]] = {}
    pooled: list[np.ndarray] = []
    for sym, bars in ohlcv_by_symbol.items():
        cv = cv_series([b[4] for b in bars])
        if len(cv) == 0:
            continue
        pooled.append(cv)
        lo, med, hi = np.percentile(cv, [lo_pct, 50.0, hi_pct])
        out[sym] = (float(lo), float(med), float(hi), len(cv))
    if pooled:
        allcv = np.concatenate(pooled)
        lo, med, hi = np.percentile(allcv, [lo_pct, 50.0, hi_pct])
        out["*"] = (float(lo), float(med), float(hi), len(allcv))
    return out
