"""Portfolio-level risk: total risk at stop, correlated clusters, reward/risk.

Per-trade sizing already makes each entry lose ``risk_per_trade_pct`` at
its stop. These rules bound what per-trade sizing cannot see:

- **Risk budget**: the equity lost if *every* open position and the new
  one hit their stops stays under ``portfolio_risk_max_pct``. A new entry
  that does not fit is first **reduced** to the room left, and rejected
  only if less than ``MIN_KEEP`` of its planned size would remain.
- **Correlated clusters**: crypto majors move together, so five longs on
  alts are one bet. Clusters (symbols whose daily returns correlate above
  a threshold) are computed weekly by the regime refresher; at most
  ``max_positions_per_cluster`` open positions per cluster.
- **Reward/risk**: the take-profit the monitor will apply must be at
  least ``min_reward_risk`` times the stop it will apply.

All pure functions; the Risk node, the Telegram gates and the backtest
replay share them.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

MIN_KEEP = 0.25  # reject rather than open a crumb of the planned position
DEFAULT_PORTFOLIO_RISK = 0.005  # 0.5% of equity at stop, all positions together
DEFAULT_MAX_PER_CLUSTER = 3
DEFAULT_MIN_REWARD_RISK = 1.5
DEFAULT_CORRELATION = 0.8
_MIN_DAYS = 31  # daily closes -> 30 returns, the least a correlation is computed on


# ── risk budget ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BudgetFit:
    size: float  # equity fraction to commit (0 when rejected)
    reduced: bool
    rejected: str | None  # reason, None if the entry goes ahead
    note: str


def fit_to_budget(
    *, planned_size: float, stop_pct: float, open_risk: float, cap: float | None
) -> BudgetFit:
    """Fit a planned entry into the portfolio risk budget.

    ``open_risk`` and ``cap`` are equity fractions lost at stop; ``cap``
    None or <= 0 disables the budget.
    """
    if cap is None or cap <= 0:
        return BudgetFit(planned_size, False, None, "")
    if stop_pct <= 0 or planned_size <= 0:
        raise ValueError(f"planned_size and stop_pct must be > 0 ({planned_size}, {stop_pct})")
    room = cap - open_risk
    head = f"open risk {open_risk:.3%} of {cap:.3%} budget"
    if room <= 0:
        return BudgetFit(0.0, False, f"portfolio risk budget exhausted ({head})", "")
    planned_risk = planned_size * stop_pct
    if planned_risk <= room:
        return BudgetFit(planned_size, False, None, f" Portfolio: {head}.")
    size = room / stop_pct
    if size < planned_size * MIN_KEEP:
        return BudgetFit(
            0.0,
            False,
            f"portfolio risk budget: only {size / planned_size:.0%} of the planned size "
            f"fits ({head})",
            "",
        )
    return BudgetFit(
        size,
        True,
        None,
        f" REDUCED to {size:.2%} of equity ({size / planned_size:.0%} of planned) to fit "
        f"the portfolio risk budget ({head}).",
    )


# ── correlated clusters ───────────────────────────────────────────────────


def parse_clusters(raw: Any) -> list[frozenset[str]]:
    """Clusters stored as JSON ``[["BTC/USDT", "ETH/USDT"], ...]``; blank -> [].

    Raises ValueError on anything else: the value is written by the
    refresher, so garbage means corruption and callers fail closed.
    """
    if raw is None or not str(raw).strip():
        return []
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, list) or not all(
        isinstance(c, list) and all(isinstance(x, str) for x in c) for c in data
    ):
        raise ValueError(f"correlation_clusters is not a list of symbol lists: {str(raw)[:80]}")
    return [frozenset(c) for c in data if len(c) > 1]


def cluster_block(
    symbol: str,
    open_symbols: Iterable[str],
    clusters: Sequence[frozenset[str]],
    max_per_cluster: int,
) -> str | None:
    """Why ``symbol`` may not be opened because of its cluster, or None."""
    if max_per_cluster <= 0:
        return None
    for cluster in clusters:
        if symbol in cluster:
            peers = sorted({s for s in open_symbols if s in cluster})
            if len(peers) >= max_per_cluster:
                return (
                    f"correlation limit: {len(peers)} positions already open in "
                    f"{symbol}'s cluster ({', '.join(peers)}), max {max_per_cluster}"
                )
    return None


def daily_closes(bars: Sequence[Sequence[float]]) -> dict[int, float]:
    """Last close of each UTC day from [ts_ms, o, h, l, c, v] bars."""
    out: dict[int, float] = {}
    for b in bars:
        out[int(b[0]) // 86_400_000] = float(b[4])
    return out


def correlation_clusters(
    bars_by_symbol: Mapping[str, Sequence[Sequence[float]]],
    *,
    threshold: float = DEFAULT_CORRELATION,
    days: int = 90,
) -> list[list[str]] | None:
    """Single-linkage clusters of symbols whose daily returns correlate >= threshold.

    Only the last ``days`` days before the newest bar of any symbol count;
    a pair is compared on the days both have there and needs at least 30
    returns, so a newly listed or stale symbol is simply left out instead
    of shrinking everyone's window. Singletons are omitted. None when
    fewer than two symbols have enough data: unknown, not "uncorrelated".
    """
    closes = {s: daily_closes(b) for s, b in bars_by_symbol.items() if b}
    if not closes:
        return None
    last_day = max(max(c) for c in closes.values())
    first_day = last_day - days
    recent = {s: {d: v for d, v in c.items() if d >= first_day} for s, c in closes.items()}
    symbols = sorted(s for s, c in recent.items() if len(c) >= _MIN_DAYS)
    if len(symbols) < 2:
        return None
    parent = {s: s for s in symbols}

    def find(s: str) -> str:
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    for i, a in enumerate(symbols):
        for b in symbols[i + 1 :]:
            common = sorted(recent[a].keys() & recent[b].keys())
            if len(common) < _MIN_DAYS:
                continue
            ra = [recent[a][d] / recent[a][p] - 1.0 for p, d in pairwise(common)]
            rb = [recent[b][d] / recent[b][p] - 1.0 for p, d in pairwise(common)]
            if _pearson(ra, rb) >= threshold:
                parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for s in symbols:
        groups.setdefault(find(s), []).append(s)
    return sorted((sorted(g) for g in groups.values() if len(g) > 1), key=lambda g: g[0])


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


# ── reward / risk ─────────────────────────────────────────────────────────


def reward_risk_block(stop_pct: float, take_profit_pct: float, min_rr: float) -> str | None:
    """Why the exits are not worth the risk, or None. ``min_rr`` <= 0 disables."""
    if min_rr <= 0:
        return None
    if stop_pct <= 0:
        return f"stop {stop_pct:.2%} is not a loss distance"
    rr = take_profit_pct / stop_pct
    if rr < min_rr:
        return (
            f"reward/risk {rr:.2f} < {min_rr:.2f} "
            f"(take-profit {take_profit_pct:.2%} vs stop {stop_pct:.2%})"
        )
    return None


# ── config ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PortfolioRules:
    risk_cap: float | None = DEFAULT_PORTFOLIO_RISK
    clusters: tuple[frozenset[str], ...] = ()
    max_per_cluster: int = DEFAULT_MAX_PER_CLUSTER
    min_reward_risk: float = DEFAULT_MIN_REWARD_RISK


def portfolio_rules(cfg: Any) -> PortfolioRules:
    """Rules from Runtime Config ``thresholds``; blank -> default, 0 -> off.

    Raises ValueError on invalid values (callers fail closed).
    """
    if cfg is None:
        return PortfolioRules()

    def num(key: str, default: float) -> float:
        raw = str(cfg.get("thresholds", key, "") or "").strip()
        if not raw:
            return default
        value = float(raw)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{key} must be a number >= 0, got {raw!r}")
        return value

    cap = num("portfolio_risk_max_pct", DEFAULT_PORTFOLIO_RISK)
    per_cluster = num("max_positions_per_cluster", DEFAULT_MAX_PER_CLUSTER)
    if not per_cluster.is_integer():
        raise ValueError(f"max_positions_per_cluster must be a whole number, got {per_cluster}")
    return PortfolioRules(
        risk_cap=cap if cap > 0 else None,
        clusters=tuple(parse_clusters(cfg.get("thresholds", "correlation_clusters", ""))),
        max_per_cluster=int(per_cluster),
        min_reward_risk=num("min_reward_risk", DEFAULT_MIN_REWARD_RISK),
    )
